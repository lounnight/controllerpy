"""Stage 3 of the compiler: validated AST -> readable Arduino C++.

Emission order (everything that follows is deterministic):

1. library ``#include`` lines (``Arduino.h`` is implicit in a ``.ino`` sketch)
2. global scalar/array variables
3. prototypes of functions that only use built-in types (classes may call them)
4. class definitions (ordered by their dependencies)
5. global objects (constructed after their class exists)
6. prototypes of functions that use class types
7. definitions, in source order, with ``main()`` -> ``setup()`` and ``loop()``
"""

from __future__ import annotations

import ast
from typing import Dict, List, Optional, Sequence, Set, Tuple, Union

from .context import (
    API_FUNCTIONS,
    ARDUINO_CONSTANTS,
    ARDUINO_OBJECTS,
    BUILTIN_FUNCTIONS,
    ClassInfo,
    CompileContext,
    FunctionInfo,
    MethodInfo,
    UNKNOWN_TYPE,
    VarInfo,
)
from .validator import constant_int, is_docstring
__all__ = ["CppGenerator", "CodeWriter", "cpp_string_literal"]

OwnerInfo = Union[FunctionInfo, MethodInfo]

# operator precedence (higher binds tighter)
PRE_ATOM = 20
PRE_UNARY = 15
PRE_MUL = 13
PRE_ADD = 12
PRE_SHIFT = 11
PRE_REL = 10
PRE_EQ = 9
PRE_BITAND = 8
PRE_BITXOR = 7
PRE_BITOR = 6
PRE_AND = 5
PRE_OR = 4
PRE_TERNARY = 3
PRE_NONE = 0

_BINOP_TOKENS: Dict[type, Tuple[str, int]] = {
    ast.Add: ("+", PRE_ADD),
    ast.Sub: ("-", PRE_ADD),
    ast.Mult: ("*", PRE_MUL),
    ast.Div: ("/", PRE_MUL),
    ast.FloorDiv: ("/", PRE_MUL),
    ast.Mod: ("%", PRE_MUL),
    ast.LShift: ("<<", PRE_SHIFT),
    ast.RShift: (">>", PRE_SHIFT),
    ast.BitAnd: ("&", PRE_BITAND),
    ast.BitXor: ("^", PRE_BITXOR),
    ast.BitOr: ("|", PRE_BITOR),
}

_COMPARE_TOKENS: Dict[type, str] = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
}

_AUGASSIGN_TOKENS: Dict[type, str] = {
    ast.Add: "+=",
    ast.Sub: "-=",
    ast.Mult: "*=",
    ast.Div: "/=",
    ast.Mod: "%=",
    ast.BitAnd: "&=",
    ast.BitOr: "|=",
    ast.BitXor: "^=",
    ast.LShift: "<<=",
    ast.RShift: ">>=",
}

_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}

def cpp_string_literal(value: str) -> str:
    out = ['"']
    for char in value:
        if char in _ESCAPES:
            out.append(_ESCAPES[char])
        elif ord(char) < 32 or ord(char) == 127:
            out.append(f"\\{ord(char):03o}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


class CodeWriter:
    def __init__(self, indent_unit: str = "    ") -> None:
        self._lines: List[str] = []
        self._indent_unit = indent_unit
        self._level = 0

    def line(self, text: str = "") -> None:
        if text:
            self._lines.append(f"{self._indent_unit * self._level}{text}")
        else:
            self._lines.append("")

    def blank(self) -> None:
        if self._lines and self._lines[-1] != "":
            self._lines.append("")

    def indent(self) -> None:
        self._level += 1

    def dedent(self) -> None:
        self._level = max(0, self._level - 1)

    def text(self) -> str:
        while self._lines and self._lines[-1] == "":
            self._lines.pop()
        return "\n".join(self._lines) + "\n"


class CppGenerator:
    def __init__(self, context: CompileContext) -> None:
        self.ctx = context
        self.w = CodeWriter()
        self.owner: Optional[OwnerInfo] = None
    
    def generate(self) -> str:
        module = self.ctx.module
        if module is None: 
            raise ValueError("the context has no module to generate code for")

        self._emit_includes()
        self._emit_globals(objects=False)
        self._emit_prototypes(class_signatures=False)
        self._emit_classes()
        self._emit_globals(objects=True)
        self._emit_prototypes(class_signatures=True)
        self._emit_definitions(module.body)

        return self.w.text()

    def _emit_includes(self) -> None:
        for header in self.ctx.includes:
            self.w.line(f"#include <{header}>")
        self.w.blank()

    def _emit_globals(self, *, objects: bool) -> None:
        emitted = False
        for var in self.ctx.globals.values():
            if self._is_object(var) != objects:
                continue
            self.w.line(self._global_declaration(var))
            emitted = True
        if emitted:
            self.w.blank()

    def _is_object(self, var: VarInfo) -> bool:
        return bool(var.is_object or self.ctx.is_object_type(var.cpp_type))

    def _global_declaration(self, var: VarInfo) -> str:
        if self._is_object(var):
            if isinstance(var.value, ast.Call):
                return f"{self._object_declaration(var, var.value)};"
            type_name = var.cpp_type if var.cpp_type != UNKNOWN_TYPE else "int"
            return f"{self.name(type_name)} {self.name(var.name)};"
        declaration = self._decl_text(var, const=var.is_const)
        if var.value is None:
            return f"{declaration};"
        
        return f"{declaration} = {self.expr(var.value)};"

    def _object_declaration(self, var: VarInfo, call: ast.Call) -> str:
        type_name = var.cpp_type if var.cpp_type != UNKNOWN_TYPE else "int"
        args = ", ".join(self.expr(arg) for arg in call.args)
        suffix = f"({args})" if args else ""

        return f"{self.name(type_name)} {self.name(var.name)}{suffix}"

    def _emit_prototypes(self, *, class_signatures: bool) -> None:
        emitted = False
        for info in self.ctx.functions.values():
            if self._uses_class_type(info) != class_signatures:
                continue
            self.w.line(f"{info.return_type} {self.name(info.name)}({self._params_decl(info.params)});")
            emitted = True
        if emitted:
            self.w.blank()

    def _uses_class_type(self, info: OwnerInfo) -> bool:
        if info.return_type in self.ctx.classes:
            return True

        return any(param.cpp_type in self.ctx.classes for param in info.params)

    def _params_decl(self, params: Sequence[VarInfo]) -> str:
        parts = []
        for param in params:
            cpp_type = param.cpp_type if param.cpp_type != UNKNOWN_TYPE else "int"
            parts.append(f"{cpp_type} {self.name(param.name)}")
        
        return ", ".join(parts)

    def _emit_classes(self) -> None:
        for cls in self._class_order():
            self._emit_class(cls)

    def _class_order(self) -> List[ClassInfo]:
        ordered: List[ClassInfo] = []
        visiting: List[str] = []
        done: Set[str] = set()

        def visit(name: str) -> None:
            if name in done:
                return
            if name in visiting:
                chain = " -> ".join(visiting[visiting.index(name) :] + [name])
                self.ctx.error(
                    self.ctx.classes[name].node,
                    f"Circular dependency between classes: {chain}",
                    hint="C++ classes cannot contain each other by value; restructure your classes.",
                )
            visiting.append(name)
            cls = self.ctx.classes[name]
            cls.depends_on = self._class_dependencies(cls)
            for dependency in sorted(cls.depends_on):
                visit(dependency)
            visiting.pop()
            done.add(name)
            ordered.append(cls)

        for class_name in self.ctx.classes:
            visit(class_name)
        
        return ordered

    def _class_dependencies(self, cls: ClassInfo) -> Set[str]:
        dependencies: Set[str] = set()
        for method in self._class_methods(cls):
            if method.node is None:
                continue
            for node in ast.walk(method.node):
                if isinstance(node, ast.Name) and node.id in self.ctx.classes and node.id != cls.name:
                    dependencies.add(node.id)
        
        return dependencies

    @staticmethod
    def _class_methods(cls: ClassInfo) -> List[MethodInfo]:
        methods: List[MethodInfo] = []
        if cls.constructor is not None:
            methods.append(cls.constructor)
        methods.extend(cls.methods.values())

        return methods

    def _emit_class(self, cls: ClassInfo) -> None:
        self.w.line(f"class {self.name(cls.name)} {{")
        self.w.line("public:")
        self.w.indent()
        for field in cls.fields.values():
            self.w.line(f"{self._decl_text(field)};")
        methods = self._class_methods(cls)
        if cls.fields and methods:
            self.w.blank()
        for index, method in enumerate(methods):
            if method.node is None:  # pragma: no cover - defensive
                continue
            if method.is_constructor:
                self.w.line(f"{self.name(cls.name)}({self._params_decl(method.params)}) {{")
            else:
                self.w.line(
                    f"{method.return_type} {self.name(method.name)}({self._params_decl(method.params)}) {{"
                )
            self.w.indent()
            self._emit_local_declarations(method)
            self._emit_body(method.node.body, method)
            self.w.dedent()
            self.w.line("}")
            if index != len(methods) - 1:
                self.w.blank()
        self.w.dedent()
        self.w.line("};")
        self.w.blank()

    def _emit_definitions(self, body: Sequence[ast.stmt]) -> None:
        for stmt in body:
            if isinstance(stmt, ast.FunctionDef):
                if stmt is self.ctx.setup_node:
                    self._emit_entry_point("setup", self.ctx.setup_info, stmt)
                elif stmt is self.ctx.loop_node:
                    self._emit_entry_point("loop", self.ctx.loop_info, stmt)
                else:
                    info = self.ctx.functions[stmt.name]
                    self.w.line(
                        f"{info.return_type} {self.name(info.name)}({self._params_decl(info.params)}) {{"
                    )
                    self.w.indent()
                    self._emit_local_declarations(info)
                    self._emit_body(stmt.body, info)
                    self.w.dedent()
                    self.w.line("}")
                    self.w.blank()

    def _emit_entry_point(self, name: str, info: Optional[FunctionInfo], node: ast.FunctionDef) -> None:
        if info is None:  # pragma: no cover - defensive
            raise ValueError(f"missing symbol table for {name}()")
        self.w.line(f"void {name}() {{")
        self.w.indent()
        self._emit_local_declarations(info)
        self._emit_body(node.body, info)
        self.w.dedent()
        self.w.line("}")
        self.w.blank()

    def _emit_local_declarations(self, info: OwnerInfo) -> None:
        for name in info.hoisted:
            self.w.line(f"{self._decl_text(info.locals[name])};")
        if info.hoisted:
            self.w.blank()

    def _emit_body(self, body: Sequence[ast.stmt], owner: Optional[OwnerInfo]) -> None:
        previous_owner = self.owner
        if owner is not None:
            self.owner = owner
        statements = [stmt for stmt in body if not self._is_noop(stmt)]
        previous_end: Optional[int] = None
        for stmt in statements:
            if previous_end is not None and stmt.lineno - previous_end > 1:
                self.w.blank() 
            self._emit_statement(stmt)
            previous_end = getattr(stmt, "end_lineno", stmt.lineno)
        self.owner = previous_owner

    @staticmethod
    def _is_noop(stmt: ast.stmt) -> bool:
        return isinstance(stmt, ast.Pass) or is_docstring(stmt)

    def _emit_statement(self, stmt: ast.stmt) -> None:
        if isinstance(stmt, ast.Assign):
            self._emit_assign(stmt)
        elif isinstance(stmt, ast.AnnAssign):
            self._emit_annassign(stmt)
        elif isinstance(stmt, ast.AugAssign):
            self._emit_augassign(stmt)
        elif isinstance(stmt, ast.Expr):
            self.w.line(f"{self.expr(stmt.value)};")
        elif isinstance(stmt, ast.If):
            self._emit_if(stmt)
        elif isinstance(stmt, ast.While):
            self._emit_while(stmt)
        elif isinstance(stmt, ast.For):
            self._emit_for(stmt)
        elif isinstance(stmt, ast.Return):
            self.w.line("return;" if stmt.value is None else f"return {self.expr(stmt.value)};")
        elif isinstance(stmt, ast.Break):
            self.w.line("break;")
        elif isinstance(stmt, ast.Continue):
            self.w.line("continue;")
        else:  # pragma: no cover - defensive
            self.ctx.error(stmt, f"Internal error: unhandled statement {type(stmt).__name__}")

    def _emit_assign(self, node: ast.Assign) -> None:
        targets = list(node.targets)
        if (
            len(targets) == 1
            and isinstance(targets[0], (ast.Tuple, ast.List))
            and isinstance(node.value, (ast.Tuple, ast.List))
        ):
            target_elements = list(targets[0].elts)
            value_elements = list(node.value.elts)
            if self._needs_temporaries(target_elements, value_elements):
                self._emit_swap_assign(target_elements, value_elements, node)
            else:
                for target, value in zip(target_elements, value_elements):
                    self._emit_single_assign(target, value, node)
            return
        for target in targets:
            self._emit_single_assign(target, node.value, node)

    def _needs_temporaries(self, target_elements: Sequence[ast.AST], value_elements: Sequence[ast.AST]) -> bool:
        names = {element.id for element in target_elements if isinstance(element, ast.Name)}
        for value in value_elements:
            for child in ast.walk(value):
                if isinstance(child, ast.Name) and child.id in names:
                    return True
        return False

    def _emit_swap_assign(
        self,
        target_elements: Sequence[ast.AST],
        value_elements: Sequence[ast.AST],
        stmt: ast.stmt,
    ) -> None:
        temporaries: List[str] = []
        for index, value in enumerate(value_elements):
            inferred = self._type_of(value)
            cpp_type = "int" if inferred in (UNKNOWN_TYPE, "void") else inferred
            temporary = f"micropy_tmp{index}"
            self.w.line(f"{cpp_type} {temporary} = {self.expr(value)};")
            temporaries.append(temporary)
        for target, temporary in zip(target_elements, temporaries):
            self._emit_single_assign(target, ast.Name(id=temporary, ctx=ast.Load()), stmt)

    def _emit_annassign(self, node: ast.AnnAssign) -> None:
        if node.value is None:
            if isinstance(node.target, ast.Name):
                local = self._local_info(node.target.id)
                if local is not None and local.declare_node is node:
                    self.w.line(f"{self._decl_text(local)};")
                return
            self.ctx.error(node.target, "Internal error: unsupported annotated assignment target")
        self._emit_single_assign(node.target, node.value, node)

    def _emit_augassign(self, node: ast.AugAssign) -> None:
        target = self.expr(node.target)
        value = self.expr(node.value)
        if isinstance(node.op, ast.FloorDiv):
            if self._type_of(node.target) == "float":
                self.w.line(f"{target} = floor({target} / {value});")
            else:
                self.w.line(f"{target} /= {value};")
            return
        if isinstance(node.op, ast.Pow):
            self.w.line(f"{target} = pow({target}, {value});")
            return
        token = _AUGASSIGN_TOKENS.get(type(node.op))
        if token is None: 
            self.ctx.error(node, f"Internal error: unsupported augmented assignment {type(node.op).__name__}")
        self.w.line(f"{target} {token} {value};")

    def _emit_single_assign(self, target: ast.AST, value: ast.AST, stmt: ast.stmt) -> None:
        if isinstance(target, ast.Name):
            local = self._local_info(target.id)
            if local is not None and local.declare_node is stmt:
                if self.ctx.is_object_type(local.cpp_type) and isinstance(value, ast.Call):
                    self.w.line(f"{self._object_declaration(local, value)};")
                else:
                    self.w.line(f"{self._decl_text(local)} = {self.expr(value)};")
            else:
                self.w.line(f"{self.name(target.id)} = {self.expr(value)};")
            return
        if isinstance(target, ast.Attribute):
            self.w.line(f"{self._attribute(target)} = {self.expr(value)};")
            return
        if isinstance(target, ast.Subscript):
            self.w.line(f"{self._subscript(target)} = {self.expr(value)};")
            return
        self.ctx.error(target, "Internal error: unsupported assignment target")

    def _emit_if(self, node: ast.If) -> None:
        self.w.line(f"if ({self.expr(node.test)}) {{")
        self.w.indent()
        self._emit_body(node.body, None)
        self.w.dedent()
        orelse = node.orelse
        while orelse:
            if len(orelse) == 1 and isinstance(orelse[0], ast.If):
                inner = orelse[0]
                self.w.line(f"}} else if ({self.expr(inner.test)}) {{")
                self.w.indent()
                self._emit_body(inner.body, None)
                self.w.dedent()
                orelse = inner.orelse
            else:
                self.w.line("} else {")
                self.w.indent()
                self._emit_body(orelse, None)
                self.w.dedent()
                orelse = []
        self.w.line("}")

    def _emit_while(self, node: ast.While) -> None:
        self.w.line(f"while ({self.expr(node.test)}) {{")
        self.w.indent()
        self._emit_body(node.body, None)
        self.w.dedent()
        self.w.line("}")

    def _emit_for(self, node: ast.For) -> None:
        iterator = node.iter
        assert isinstance(iterator, ast.Call) 
        args = list(iterator.args)
        loop_var = self.name(node.target.id)
        if len(args) == 1:
            start_text, stop_node = "0", args[0]
            step_value = 1
        elif len(args) == 2:
            start_text, stop_node = self.expr(args[0]), args[1]
            step_value = 1
        else:
            start_text, stop_node = self.expr(args[0]), args[1]
            step_value = constant_int(args[2]) or 0
        stop_text = self.expr(stop_node)
        comparison = "<" if step_value >= 0 else ">"
        if step_value == 1:
            increment = f"{loop_var}++"
        elif step_value == -1:
            increment = f"{loop_var}--"
        elif step_value > 0:
            increment = f"{loop_var} += {step_value}"
        else:
            increment = f"{loop_var} -= {abs(step_value)}"
        self.w.line(f"for (int {loop_var} = {start_text}; {loop_var} {comparison} {stop_text}; {increment}) {{")
        self.w.indent()
        self._emit_body(node.body, None)
        self.w.dedent()
        self.w.line("}")

    # names
    def name(self, identifier: str) -> str:
        """C++ safe identifier for a Python name."""

        return self.ctx.cpp_name(identifier)

    def _local_info(self, identifier: str) -> Optional[VarInfo]:
        if self.owner is None:
            return None
        return self.owner.locals.get(identifier)

    def _decl_text(self, var: VarInfo, *, const: Optional[bool] = None) -> str:
        cpp_type = var.cpp_type if var.cpp_type != UNKNOWN_TYPE else "int"
        declarator = self.name(var.name)
        if var.is_array:
            size = "" if var.array_len is None else str(var.array_len)
            declarator = f"{declarator}[{size}]"
        use_const = var.is_const if const is None else const
        if use_const and cpp_type != "const char*":
            return f"const {cpp_type} {declarator}"
        return f"{cpp_type} {declarator}"

    # expressions
    def expr(self, node: ast.AST) -> str:
        """Emit *node* as C++, parenthesising only where necessary."""

        return self._expr(node)[0]

    def _expr(self, node: ast.AST) -> Tuple[str, int]:
        if isinstance(node, ast.Constant):
            return (self._constant(node), PRE_ATOM)
        if isinstance(node, ast.Name):
            return (self.name(node.id), PRE_ATOM)
        if isinstance(node, ast.Attribute):
            return (self._attribute(node), PRE_ATOM)
        if isinstance(node, ast.Call):
            return (self._call(node), PRE_ATOM)
        if isinstance(node, ast.Subscript):
            return (self._subscript(node), PRE_ATOM)
        if isinstance(node, ast.BinOp):
            return self._binop(node)
        if isinstance(node, ast.BoolOp):
            return self._boolop(node)
        if isinstance(node, ast.UnaryOp):
            return self._unary(node)
        if isinstance(node, ast.Compare):
            return self._compare(node)
        if isinstance(node, ast.IfExp):
            return self._ifexp(node)
        if isinstance(node, (ast.List, ast.Tuple)):
            return (self._array_initializer(node), PRE_ATOM)
        self.ctx.error(node, f"Internal error: unhandled expression {type(node).__name__}")
        return ("", PRE_NONE)  

    def _constant(self, node: ast.Constant) -> str:
        value = node.value
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            text = repr(value)
            if "." not in text and "e" not in text and "E" not in text:
                text += ".0"
            return text
        if isinstance(value, str):
            return cpp_string_literal(value)
        if value is None:  
            return "nullptr"
        self.ctx.error(node, f"Internal error: unsupported literal {value!r}")
        return "" 

    def _attribute(self, node: ast.Attribute) -> str:
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            return f"this->{self.name(node.attr)}"
        return f"{self.expr(node.value)}.{self._member_name(node.value, node.attr)}"

    def _member_name(self, base: ast.AST, attribute: str) -> str:
        if isinstance(base, ast.Name) and (base.id in ARDUINO_OBJECTS or base.id in self.ctx.external_types):
            return attribute
        base_type = self._type_of(base)
        if base_type in ARDUINO_OBJECTS or base_type in self.ctx.external_types:
            return attribute
        
        return self.name(attribute)

    def _subscript(self, node: ast.Subscript) -> str:
        return f"{self.expr(node.value)}[{self.expr(node.slice)}]"

    def _call(self, node: ast.Call) -> str:
        func = node.func
        args = ", ".join(self.expr(arg) for arg in node.args)
        if isinstance(func, ast.Name):
            name = func.id
            api = API_FUNCTIONS.get(name)
            if api is not None:
                if api.receiver:
                    return f"{api.receiver}.{api.cpp_member}({args})"
                return f"{api.cpp_name}({args})"
            if name in BUILTIN_FUNCTIONS:
                return f"{BUILTIN_FUNCTIONS[name]}({args})"
            if name == "len":
                base = node.args[0]
                if isinstance(base, ast.Name):
                    array = self.name(base.id)
                    return f"(sizeof({array}) / sizeof({array}[0]))"
                self.ctx.error(node, "Internal error: len() on an unsupported expression")
            if name == "String":
                return f"String({args})"
            if name in self.ctx.classes or name in self.ctx.functions or name in self.ctx.external_types:
                return f"{self.name(name)}({args})"
            self.ctx.error(node, f"Internal error: unknown function {name}()")
        if isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name) and func.value.id == "self":
                return f"this->{self.name(func.attr)}({args})"
            return f"{self.expr(func.value)}.{self._member_name(func.value, func.attr)}({args})"
        self.ctx.error(node, "Internal error: unsupported call expression")

        return "" 

    def _binop(self, node: ast.BinOp) -> Tuple[str, int]:
        op = node.op
        if isinstance(op, ast.Pow):
            left = self.expr(node.left)
            right = self.expr(node.right)
            return (f"pow({left}, {right})", PRE_ATOM)
        if isinstance(op, (ast.FloorDiv, ast.Mod)) and self._is_float(node):
            left = self.expr(node.left)
            right = self.expr(node.right)
            if isinstance(op, ast.FloorDiv):
                return (f"floor({left} / {right})", PRE_ATOM)
            return (f"fmod({left}, {right})", PRE_ATOM)
        token, precedence = _BINOP_TOKENS[type(op)]
        left_text, left_precedence = self._expr(node.left)
        right_text, right_precedence = self._expr(node.right)
        if left_precedence < precedence:
            left_text = f"({left_text})"
        if right_precedence <= precedence:
            right_text = f"({right_text})"
        
        return (f"{left_text} {token} {right_text}", precedence)

    def _boolop(self, node: ast.BoolOp) -> Tuple[str, int]:
        if isinstance(node.op, ast.And):
            token, precedence = "&&", PRE_AND
        else:
            token, precedence = "||", PRE_OR
        parts = []
        for value in node.values:
            text, value_precedence = self._expr(value)
            if value_precedence < precedence:
                text = f"({text})"
            parts.append(text)
        
        return (f" {token} ".join(parts), precedence)

    def _unary(self, node: ast.UnaryOp) -> Tuple[str, int]:
        text, precedence = self._expr(node.operand)
        if precedence < PRE_UNARY:
            text = f"({text})"
        if isinstance(node.op, ast.Not):
            return (f"!{text}", PRE_UNARY)
        if isinstance(node.op, ast.USub):
            return (f"-{text}", PRE_UNARY)
        if isinstance(node.op, ast.Invert):
            return (f"~{text}", PRE_UNARY)
        
        return (f"+{text}", PRE_UNARY)

    def _compare(self, node: ast.Compare) -> Tuple[str, int]:
        parts: List[str] = []
        left_text, left_precedence = self._expr(node.left)
        lowest = PRE_REL
        for op, comparator in zip(node.ops, node.comparators):
            token = _COMPARE_TOKENS[type(op)]
            precedence = PRE_REL if isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)) else PRE_EQ
            lowest = min(lowest, precedence)
            right_text, right_precedence = self._expr(comparator)
            left_side = left_text if left_precedence >= precedence else f"({left_text})"
            right_side = right_text if right_precedence >= precedence else f"({right_text})"
            parts.append(f"{left_side} {token} {right_side}")
            left_text, left_precedence = right_text, right_precedence
        if len(parts) == 1:
            return (parts[0], lowest)
        
        # Python chains comparisons: a < b < c  ->  a < b && b < c
        return (" && ".join(parts), PRE_AND)

    def _ifexp(self, node: ast.IfExp) -> Tuple[str, int]:
        return (
            f"{self.expr(node.test)} ? {self.expr(node.body)} : {self.expr(node.orelse)}",
            PRE_TERNARY,
        )

    def _array_initializer(self, node: ast.AST) -> str:
        return "{" + ", ".join(self.expr(element) for element in getattr(node, "elts")) + "}"

    def _type_of(self, node: ast.AST) -> str:
        return self.ctx.expression_types.get(id(node), UNKNOWN_TYPE)

    def _is_float(self, node: ast.AST) -> bool:
        if isinstance(node, ast.BinOp):
            return "float" in (
                self.ctx.expression_types.get(id(node.left), UNKNOWN_TYPE),
                self.ctx.expression_types.get(id(node.right), UNKNOWN_TYPE),
            )
        
        return False
