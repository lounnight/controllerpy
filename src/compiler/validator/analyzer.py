"""Stage 2, phase 2: analyse function bodies and infer expression types.

:class:`BodyAnalyzer` is the type inference engine.  It visits every statement
inside a function, binds names to the scope, and infers the C++ type of every
expression, recording the result for the generator.  Expressions are analysed
by :meth:`BodyAnalyzer._type`, which both checks the construct and returns its
type; statement handlers are plain ``visit_*`` methods, and anything not handled
falls through to :meth:`BodyAnalyzer.generic_visit` and is reported as
unsupported instead of being silently ignored.

Types are not always known after a single pass - ``def add(a, b): return a + b``
can only be typed once the call sites told us what ``a`` and ``b`` are - so
:meth:`BodyAnalyzer.retype_returns` and
:meth:`BodyAnalyzer.refine_local_types` run as a small fixpoint on top.
"""

from __future__ import annotations

import ast
from typing import Dict, List, Optional, Sequence, Tuple

from ...errors import ControllerPyError
from .api import API_FUNCTIONS, ARDUINO_CONSTANTS, ARDUINO_OBJECTS, BUILTIN_FUNCTIONS, PYTHON_BUILTIN_HINTS
from .ast_utils import augassign_label, constant_int, is_docstring, iter_statements, target_names, unsupported_label
from .context import CompileContext
from .naming import check_reserved_variable
from .symbols import ClassInfo, FunctionInfo, MethodInfo, Scope, VarInfo
from .types import (
    CONFLICT_TYPE,
    DEFAULT_TYPE,
    UNKNOWN_TYPE,
    VOID_TYPE,
    merge_types,
    resolve_annotation,
    types_compatible,
)

__all__ = ["BodyAnalyzer", "RETYPE_PASSES"]

#: How often return types and locals are re-inferred before giving up.
RETYPE_PASSES = 4

_INT_MIN = -2147483648
_INT_MAX = 2147483647


def _merge_observed(observed: Sequence[Optional[str]]) -> str:
    """Combine the observed return types of one function into a C++ type."""

    merged: Optional[str] = None
    for observed_type in observed:
        if observed_type is None:
            continue
        merged = merge_types(merged, observed_type)
        if merged == CONFLICT_TYPE:
            return UNKNOWN_TYPE  # _resolve_return_type() reports the conflict
    if merged is None:
        return VOID_TYPE
    return merged


class BodyAnalyzer(ast.NodeVisitor):
    """Validates every statement/expression and infers variable types."""

    def __init__(self, context: CompileContext) -> None:
        self.ctx = context
        self.scope = context.scope
        self.owner: Optional[object] = None
        self.class_info: Optional[ClassInfo] = None
        self.entry_name: Optional[str] = None
        self.in_runtime_flow = False

    # ---------------------------------------------------------------- guards
    def generic_visit(self, node: ast.AST) -> None:  # pragma: no cover - safety net
        self.ctx.error(node, f"Unsupported Python feature: {unsupported_label(node)}")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.ctx.error(
            node,
            "Unsupported Python feature: nested function",
            hint="Define every function at the top level of the file.",
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.ctx.error(node, "Unsupported Python feature: nested class")

    def visit_Import(self, node: ast.Import) -> None:
        self.ctx.error(node, "Unsupported Python feature: import inside a function", hint="Put all imports at the top of the file.")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.ctx.error(node, "Unsupported Python feature: import inside a function", hint="Put all imports at the top of the file.")

    # ---------------------------------------------------------------- module
    def visit_Module(self, node: ast.Module) -> None:
        # Globals first so that functions can be analysed with known types.
        for stmt in node.body:
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                self._analyze_global(stmt)
        for stmt in node.body:
            self._analyze_top_level(stmt)

    def _analyze_top_level(self, stmt: ast.stmt) -> None:
        if isinstance(stmt, (ast.Import, ast.ImportFrom, ast.Pass, ast.Assign, ast.AnnAssign)) or is_docstring(stmt):
            return
        if isinstance(stmt, ast.FunctionDef):
            if stmt is self.ctx.setup_node or stmt is self.ctx.loop_node:
                self._analyze_entry_point(stmt)
            else:
                self._analyze_function(stmt)
            return
        if isinstance(stmt, ast.ClassDef):
            self._analyze_class(stmt)

    def _analyze_global(self, stmt: ast.stmt) -> None:
        value = getattr(stmt, "value", None)
        if isinstance(stmt, ast.AnnAssign):
            variable = self.ctx.globals.get(stmt.target.id)
            if variable is not None:
                variable.record_type(variable.cpp_type)
        if value is None:
            return
        targets = getattr(stmt, "targets", None)
        if targets is None:
            targets = [stmt.target]
        for target in targets:
            for name, _ in target_names(target):
                variable = self.ctx.globals.get(name)
                if variable is not None:
                    self._bind_value(variable, value)

    def _bind_value(self, var: VarInfo, value: ast.AST) -> None:
        """Record the type of *value* on *var* (module level binding)."""

        if isinstance(value, (ast.List, ast.Tuple)):
            element_type, length = self._literal_elements(value)
            var.is_array = True
            var.array_len = length
            var.record_type(element_type)
            return
        inferred = self._type(value)
        var.record_type(inferred)
        if self.ctx.is_object_type(inferred):
            var.is_object = True

    # ------------------------------------------------------------- functions
    def _analyze_entry_point(self, node: ast.FunctionDef) -> None:
        info = FunctionInfo(
            name=node.name,
            return_type=VOID_TYPE,
            annotated_return=VOID_TYPE,
            node=node,
            lineno=node.lineno,
            col_offset=node.col_offset,
        )
        if node.name == "main":
            self.ctx.setup_info = info
        else:
            self.ctx.loop_info = info
        scope = Scope("function", owner=node.name, parent=self.ctx.scope)
        self._prepare_locals(node, scope, [], info)
        self._run_body(scope, info, None, node.name, node.body)

    def _analyze_function(self, node: ast.FunctionDef) -> None:
        info = self.ctx.functions[node.name]
        scope = Scope("function", owner=info.name, parent=self.ctx.scope)
        for param in info.params:
            scope.declare(
                VarInfo(
                    name=param.name,
                    is_param=True,
                    cpp_type=param.cpp_type,
                    lineno=param.lineno,
                    col_offset=param.col_offset,
                )
            )
        self._prepare_locals(node, scope, info.params, info)
        self._run_body(scope, info, None, None, node.body)

    def _run_body(
        self,
        scope: Scope,
        owner: object,
        class_info: Optional[ClassInfo],
        entry_name: Optional[str],
        body: Sequence[ast.stmt],
    ) -> None:
        previous = (self.scope, self.owner, self.class_info, self.entry_name, self.in_runtime_flow)
        self.scope, self.owner, self.class_info, self.entry_name = scope, owner, class_info, entry_name
        try:
            self._analyze_body(body)
        finally:
            (self.scope, self.owner, self.class_info, self.entry_name, self.in_runtime_flow) = previous

    def _analyze_body(self, body: Sequence[ast.stmt]) -> None:
        for stmt in body:
            self.visit(stmt)

    def _analyze_runtime_body(self, body: Sequence[ast.stmt]) -> None:
        previous = self.in_runtime_flow
        self.in_runtime_flow = True
        try:
            self._analyze_body(body)
        finally:
            self.in_runtime_flow = previous

    def _prepare_locals(
        self,
        node: ast.FunctionDef,
        scope: Scope,
        params: Sequence[VarInfo],
        info: object,
    ) -> None:
        """Hoist local variables, following Python's function-wide scoping."""

        param_names = {param.name for param in params}
        first_assignment: Dict[str, ast.stmt] = {}
        assigned_at: Dict[str, ast.AST] = {}
        loop_vars: Dict[str, ast.stmt] = {}

        for stmt in iter_statements(node.body):
            if isinstance(stmt, ast.For):
                for name, target in target_names(stmt.target):
                    loop_vars.setdefault(name, stmt)
                    assigned_at.setdefault(name, target)
            else:
                targets = list(getattr(stmt, "targets", [])) or (
                    [stmt.target] if isinstance(stmt, (ast.AnnAssign, ast.AugAssign)) else []
                )
                for target in targets:
                    for name, target_node in target_names(target):
                        first_assignment.setdefault(name, stmt)
                        assigned_at.setdefault(name, target_node)

        for name, stmt in loop_vars.items():
            self._check_reserved_variable(loop_vars[name], name)
            if name in scope.variables:
                self.ctx.error(
                    loop_vars[name],
                    f"Loop variable '{name}' hides the parameter '{name}'.",
                    hint="Rename the loop variable.",
                )
            if name in self.ctx.globals:
                self.ctx.error(
                    loop_vars[name],
                    f"Loop variable '{name}' hides the global variable '{name}'.",
                    hint="Rename the loop variable.",
                )
            # The C++ for-loop declares the variable itself; make it visible for
            # the rest of the function body so reads/writes can be type-checked.
            if not scope.has_local(name):
                scope.declare(
                    VarInfo(
                        name=name,
                        cpp_type="int",
                        lineno=getattr(assigned_at.get(name), "lineno", None),
                        col_offset=getattr(assigned_at.get(name), "col_offset", None),
                    )
                )

        direct_statements = {id(stmt) for stmt in node.body}
        for name, stmt in first_assignment.items():
            if name in param_names or name in self.ctx.globals:
                continue  # parameters and module level names are not locals
            if name in loop_vars:
                self.ctx.error(
                    stmt,
                    f"Loop variable '{name}' is also used outside the loop.",
                    hint="Rename the loop variable.",
                )
            self._check_reserved_variable(assigned_at.get(name, node), name)
            var = VarInfo(
                name=name,
                value=getattr(stmt, "value", None),
                lineno=getattr(assigned_at.get(name), "lineno", None),
                col_offset=getattr(assigned_at.get(name), "col_offset", None),
            )
            scope.declare(var)
            getattr(info, "locals")[name] = var
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)) and id(stmt) in direct_statements:
                var.declare_node = stmt
            else:
                getattr(info, "hoisted").append(name)

    # --------------------------------------------------------------- classes
    def _analyze_class(self, node: ast.ClassDef) -> None:
        info = self.ctx.classes[node.name]
        methods = info.all_methods()
        self._prepare_fields(info, methods)
        for method in methods:
            self._analyze_method(info, method)

    def _prepare_fields(self, info: ClassInfo, methods: Sequence[MethodInfo]) -> None:
        """Collect ``self.x = ...`` targets so fields exist before analysis."""

        for method in methods:
            if method.node is None:
                continue
            for stmt in iter_statements(method.node.body):
                targets = getattr(stmt, "targets", None)
                if targets is None:
                    targets = [stmt.target] if isinstance(stmt, (ast.AnnAssign, ast.AugAssign)) else []
                for target in targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                    ):
                        info.fields.setdefault(
                            target.attr,
                            VarInfo(name=target.attr, lineno=target.lineno, col_offset=target.col_offset),
                        )

    def _analyze_method(self, info: ClassInfo, method: MethodInfo) -> None:
        if method.node is None:  # pragma: no cover - defensive
            return
        scope = Scope("method", owner=f"{info.name}.{method.name}", parent=self.ctx.scope)
        scope.declare(VarInfo(name="self", is_param=True, is_object=True, cpp_type=info.name))
        for param in method.params:
            scope.declare(
                VarInfo(
                    name=param.name,
                    is_param=True,
                    cpp_type=param.cpp_type,
                    lineno=param.lineno,
                    col_offset=param.col_offset,
                )
            )
        self._prepare_locals(method.node, scope, method.params, method)
        self._run_body(scope, method, info, None, method.node.body)

    # annotations
    def _check_reserved_variable(self, node: ast.AST, name: str) -> None:
        check_reserved_variable(self.ctx.error, node, name)

    def _annotation(self, node: ast.AST) -> str:
        return resolve_annotation(node, self.ctx.classes, self.ctx.external_types, self.ctx.error)

    # statements
    def visit_Assign(self, node: ast.Assign) -> None:
        targets = list(node.targets)
        if len(targets) == 1 and isinstance(targets[0], (ast.Tuple, ast.List)) and isinstance(
            node.value, (ast.Tuple, ast.List)
        ):
            target_elements = targets[0].elts
            value_elements = node.value.elts
            if len(target_elements) != len(value_elements):
                self.ctx.error(
                    node,
                    "Cannot unpack: the number of names and values does not match.",
                    hint="Use the same number of names and values.",
                )
            for target, value in zip(target_elements, value_elements):
                self._bind_target(target, node, types=(self._type(value),))
            return
        if isinstance(node.value, (ast.List, ast.Tuple)):
            element_type, length = self._literal_elements(node.value)
            for target in targets:
                self._bind_target(target, node, types=(element_type,), is_array=True, array_len=length)
            return
        inferred = self._type(node.value)
        for target in targets:
            self._bind_target(target, node, types=(inferred,))

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        declared = self._annotation(node.annotation)
        if declared == VOID_TYPE:
            self.ctx.error(node.annotation, "'None' is not a valid variable type.")
        if isinstance(node.value, (ast.List, ast.Tuple)):
            element_type, length = self._literal_elements(node.value)
            self._bind_target(
                node.target, node, types=(declared, element_type), is_array=True, array_len=length
            )
            return
        inferred = self._type(node.value) if node.value is not None else None
        types = (declared,) if inferred is None else (declared, inferred)
        self._bind_target(node.target, node, types=types)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        label = augassign_label(node.op)
        if label is None:
            self.ctx.error(node, f"Unsupported augmented assignment: {type(node.op).__name__}")
        target_type = self._type(node.target)
        if target_type in ("const char*", "String"):
            self.ctx.error(node, f"Cannot use {label} on a string.")
            return
        self._type(node.value)
        self._bind_target(node.target, node, types=())

    def visit_Expr(self, node: ast.Expr) -> None:
        if is_docstring(node):
            return
        call = node.value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "append":
            self._append_call_type(call, call.func.value, [self._type(arg) for arg in call.args])
            return
        self._type(node.value)

    def visit_If(self, node: ast.If) -> None:
        self._type(node.test)
        self._analyze_runtime_body(node.body)
        self._analyze_runtime_body(node.orelse)

    def visit_While(self, node: ast.While) -> None:
        if node.orelse:
            self.ctx.error(node, "Unsupported Python feature: while/else")
        self._type(node.test)
        self._analyze_runtime_body(node.body)

    def visit_For(self, node: ast.For) -> None:
        if node.orelse:
            self.ctx.error(node, "Unsupported Python feature: for/else")
        if not isinstance(node.target, ast.Name):
            self.ctx.error(node, "For loops must use a single variable: for i in range(...)")
        iterator = node.iter
        if not (
            isinstance(iterator, ast.Call)
            and isinstance(iterator.func, ast.Name)
            and iterator.func.id == "range"
        ):
            self.ctx.error(
                iterator,
                "Only 'for <name> in range(...)' loops are supported.",
                hint="Use a while loop for anything else.",
            )
        self._check_range(iterator)
        self._analyze_runtime_body(node.body)

    def _check_range(self, call: ast.Call) -> None:
        if call.keywords:
            self.ctx.error(call, "range() does not accept keyword arguments.")
        args = list(call.args)
        if not 1 <= len(args) <= 3:
            self.ctx.error(call, f"range() takes 1 to 3 arguments but got {len(args)}.")
        for arg in args:
            if self._type(arg) not in ("int", "bool", UNKNOWN_TYPE):
                self.ctx.error(arg, "range() arguments must be integers.")
        if len(args) == 3:
            step = constant_int(args[2])
            if step is None:
                self.ctx.error(
                    args[2],
                    "The step argument of range() must be a constant integer.",
                    hint="C++ for loops cannot change the step at runtime; use a while loop instead.",
                )
            elif step == 0:
                self.ctx.error(args[2], "range() step cannot be zero.")

    def visit_Return(self, node: ast.Return) -> None:
        if self.entry_name:
            if node.value is not None:
                self.ctx.error(node, f"{self.entry_name}() must not return a value.")
            return
        if self.owner is None:
            self.ctx.error(node, "Unsupported Python feature: 'return' outside of a function")
            return
        value_type = self._type(node.value) if node.value is not None else None
        self.owner.observed_returns.append(value_type)  # type: ignore[attr-defined]

    def visit_Break(self, node: ast.Break) -> None:
        return

    def visit_Continue(self, node: ast.Continue) -> None:
        return

    def visit_Pass(self, node: ast.Pass) -> None:
        return

    # ---------------------------------------------------------- assign targets
    def _bind_target(
        self,
        target: ast.AST,
        stmt: ast.stmt,
        *,
        types: Sequence[Optional[str]] = (),
        is_array: bool = False,
        array_len: Optional[int] = None,
    ) -> None:
        if isinstance(target, ast.Name):
            name = target.id
            global_var = self.ctx.globals.get(name)
            if global_var is not None:
                # Top-level names behave like C++ globals: functions assign them.
                global_var.write_count += 1
                for observed in types:
                    global_var.record_type(observed)
                return
            var = self.scope.lookup(name)
            if var is None:
                self.ctx.error(target, f"'{name}' is not defined.")
                return
            if var.is_param:
                return
            if is_array:
                if var.declare_node is not stmt:
                    self.ctx.error(
                        target,
                        f"Array '{name}' must get its values where it is declared.",
                        hint="Move the list literal to the top of the function.",
                    )
                    return
                var.is_array = True
                var.array_len = array_len
            elif var.is_array:
                self.ctx.error(
                    target,
                    f"Array '{name}' cannot be reassigned.",
                    hint="C++ arrays cannot be assigned; write to the elements instead.",
                )
                return
            var.write_count += 1
            for observed in types:
                var.record_type(observed)
            return

        if isinstance(target, ast.Attribute):
            if is_array:
                self.ctx.error(target, "Object attributes cannot hold array values.")
            if isinstance(target.value, ast.Name) and target.value.id == "self":
                if self.class_info is None:
                    self.ctx.error(target, "'self' can only be used inside a class method.")
                    return
                field = self.class_info.fields.get(target.attr)
                if field is None:
                    field = VarInfo(name=target.attr, lineno=target.lineno, col_offset=target.col_offset)
                    self.class_info.fields[target.attr] = field
                field.write_count += 1
                for observed in types:
                    field.record_type(observed)
                return
            base_type = self._type(target.value)
            class_info = self.ctx.class_of(base_type)
            if class_info is None:
                self.ctx.error(target, f"Cannot assign to attribute '{target.attr}' of this value.")
                return
            field = class_info.fields.get(target.attr)
            if field is None:
                self.ctx.error(target, f"Class '{class_info.name}' has no attribute '{target.attr}'.")
                return
            field.write_count += 1
            for observed in types:
                field.record_type(observed)
            return

        if isinstance(target, ast.Subscript):
            base = target.value
            if not isinstance(base, ast.Name):
                self.ctx.error(target, "Unsupported assignment target.")
                return
            var = self.scope.lookup(base.id)
            if var is None:
                self.ctx.error(base, f"'{base.id}' is not defined.")
                return
            if not var.is_array:
                self.ctx.error(target, f"'{base.id}' is not an array, so it cannot be indexed.")
                return
            index_type = self._type(target.slice)
            if index_type not in ("int", "bool", "char", UNKNOWN_TYPE):
                self.ctx.error(target.slice, "Array indices must be integers.")
            var.write_count += 1
            element_type = self._variable_type(var)
            for observed in types:
                if observed in (None, UNKNOWN_TYPE):
                    continue
                if merge_types(element_type, observed) == CONFLICT_TYPE:
                    self.ctx.error(target, f"Array '{base.id}' holds {element_type} values, not {observed}.")
            return

        self.ctx.error(target, "Unsupported assignment target.")

    # ------------------------------------------------------------ expressions
    def _type(self, node: ast.AST) -> str:
        """Infer (and validate) the C++ type of an expression."""

        inferred = self._infer(node)
        self.ctx.expression_types[id(node)] = inferred
        return inferred

    def _infer(self, node: ast.AST) -> str:
        if isinstance(node, ast.Constant):
            return self._constant_type(node)
        if isinstance(node, ast.Name):
            return self._name_type(node)
        if isinstance(node, ast.Attribute):
            return self._attribute_type(node)
        if isinstance(node, ast.Call):
            return self._call_type(node)
        if isinstance(node, ast.Subscript):
            return self._subscript_type(node)
        if isinstance(node, ast.BinOp):
            return self._binop_type(node)
        if isinstance(node, ast.UnaryOp):
            return self._unary_type(node)
        if isinstance(node, ast.BoolOp):
            return self._boolop_type(node)
        if isinstance(node, ast.Compare):
            return self._compare_type(node)
        if isinstance(node, ast.IfExp):
            return self._ifexp_type(node)
        if isinstance(node, (ast.List, ast.Tuple)):
            self.ctx.error(
                node,
                "List literals can only be assigned to a variable.",
                hint="values = [1, 2, 3]",
            )
        self.ctx.error(node, f"Unsupported Python feature: {unsupported_label(node)}")
        return UNKNOWN_TYPE  # pragma: no cover - error() always raises

    def _constant_type(self, node: ast.Constant) -> str:
        value = node.value
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            if value < _INT_MIN or value > _INT_MAX:
                self.ctx.error(node, f"Integer literal {value} does not fit into an Arduino int (32 bit).")
            return "int"
        if isinstance(value, float):
            return "float"
        if isinstance(value, str):
            return "const char*"
        if value is None:
            self.ctx.error(
                node, "Unsupported Python feature: None", hint="Use a real value, or a bool flag instead."
            )
        if isinstance(value, bytes):
            self.ctx.error(node, "Unsupported Python feature: bytes literal")
        self.ctx.error(node, f"Unsupported literal: {value!r}")
        return UNKNOWN_TYPE  # pragma: no cover

    def _name_type(self, node: ast.Name) -> str:
        name = node.id
        if name in ARDUINO_CONSTANTS:
            return "int"
        if name in ARDUINO_OBJECTS:
            return name
        if name in self.ctx.external_types:
            return self.ctx.external_types[name]
        if name in self.ctx.functions:
            self.ctx.error(node, f"'{name}' is a function; call it like {name}(...)")
        if name == "String":
            self.ctx.error(node, "'String' must be called: String(value)")
        if name in self.ctx.classes:
            self.ctx.error(node, f"'{name}' is a class; create an object with {name}(...)")
        var = self.scope.lookup(name)
        if var is None:
            hint = PYTHON_BUILTIN_HINTS.get(name)
            if hint:
                self.ctx.error(node, f"Python builtin '{name}' is not available on Arduino.", hint=hint)
            self.ctx.error(node, f"Unknown name: '{name}'", hint="Declare it first, or check the spelling.")
        if var.is_array:
            self.ctx.error(
                node,
                f"Array '{name}' cannot be used as a value.",
                hint=f"Index it ({name}[0]) or use len({name}).",
            )
        return self._variable_type(var)

    @staticmethod
    def _variable_type(var: VarInfo) -> str:
        merged = var.final_type()
        if merged and merged != CONFLICT_TYPE:
            return merged
        if var.cpp_type != UNKNOWN_TYPE:
            return var.cpp_type
        return UNKNOWN_TYPE

    def _attribute_type(self, node: ast.Attribute) -> str:
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            if self.class_info is None:
                self.ctx.error(node, "'self' can only be used inside a class method.")
                return UNKNOWN_TYPE
            field = self.class_info.fields.get(node.attr)
            if field is None:
                self.ctx.error(node, f"Class '{self.class_info.name}' has no attribute '{node.attr}'.")
                return UNKNOWN_TYPE
            return self._variable_type(field)
        base_type = self._type(node.value)
        if base_type in ARDUINO_OBJECTS:
            self.ctx.error(node, f"{base_type}.{node.attr} must be called as a method.")
            return UNKNOWN_TYPE
        class_info = self.ctx.class_of(base_type)
        if class_info is None:
            if self.ctx.is_object_type(base_type):
                return UNKNOWN_TYPE  # library object: pass through
            self.ctx.error(node, f"Cannot read attribute '{node.attr}' of this value.")
            return UNKNOWN_TYPE
        field = class_info.fields.get(node.attr)
        if field is None:
            self.ctx.error(node, f"Class '{class_info.name}' has no attribute '{node.attr}'.")
            return UNKNOWN_TYPE
        return self._variable_type(field)

    def _call_type(self, node: ast.Call) -> str:
        if node.keywords:
            self.ctx.error(node, "Unsupported Python feature: keyword arguments")
        if any(isinstance(arg, ast.Starred) for arg in node.args):
            self.ctx.error(node, "Unsupported Python feature: starred arguments")
        func = node.func
        if isinstance(func, ast.Name) and func.id == "len":
            return self._len_type(node)
        arg_types = [self._type(arg) for arg in node.args]
        if isinstance(func, ast.Name):
            return self._name_call_type(node, func.id, arg_types)
        if isinstance(func, ast.Attribute):
            return self._method_call_type(node, func, arg_types)
        self.ctx.error(node.func, "Unsupported call expression.")
        return UNKNOWN_TYPE  # pragma: no cover

    def _name_call_type(self, node: ast.Call, name: str, arg_types: Sequence[str]) -> str:
        api = API_FUNCTIONS.get(name)
        if api is not None:
            self._check_arity(node, name, len(node.args), api.min_args, api.max_args)
            return api.returns
        if name in BUILTIN_FUNCTIONS:
            self._check_arity(node, name, len(node.args), 1, 5)
            if name in ("pow", "sqrt", "floor", "ceil", "round"):
                return "float"
            merged: Optional[str] = None
            for arg_type in arg_types:
                merged = merge_types(merged, arg_type)
                if merged == CONFLICT_TYPE:
                    merged = UNKNOWN_TYPE
                    break
            return merged or UNKNOWN_TYPE
        if name == "len":
            return self._len_type(node)
        if name == "String":
            return "String"
        if name == "range":
            self.ctx.error(node, "range() can only be used in a for loop.")
        cls = self.ctx.classes.get(name)
        if cls is not None:
            if cls.is_struct and node.args:
                self.ctx.error(
                    node,
                    f"Struct '{name}' cannot be created with arguments.",
                    hint="Create the struct and assign its fields:",
                    hint_lines=[f"point = {name}()", "point.x = 1"],
                )
            params = cls.constructor.params if cls.constructor is not None else []
            self._check_arity(node, name, len(node.args), len(params), len(params))
            for param, arg_type in zip(params, arg_types):
                if param.cpp_type == UNKNOWN_TYPE:
                    param.record_type(arg_type)
            return cls.name
        if name in self.ctx.external_types:
            library_class = self.ctx.library_class(name)
            if library_class is None:
                return self.ctx.external_types[name]
            self._check_arity(
                node,
                name,
                len(node.args),
                library_class.ctor_min_args,
                library_class.ctor_max_args,
            )
            self._check_argument_types(node, name, library_class.ctor_params, arg_types)
            return library_class.cpp_type
        info = self.ctx.functions.get(name)
        if info is None:
            hint = PYTHON_BUILTIN_HINTS.get(name)
            if hint:
                self.ctx.error(node, f"Python builtin '{name}' is not available on Arduino.", hint=hint)
            known = sorted(list(API_FUNCTIONS) + list(self.ctx.functions))
            self.ctx.error(
                node,
                f"Unknown ArduinoPy function: {name}()",
                hint="Supported Arduino functions include:",
                hint_lines=[f"{item}()" for item in known],
            )
        self._check_arity(node, name, len(node.args), len(info.params), len(info.params))
        for param, arg_type in zip(info.params, arg_types):
            if param.cpp_type == UNKNOWN_TYPE:
                param.record_type(arg_type)
        return info.return_type or UNKNOWN_TYPE

    def _method_call_type(self, node: ast.Call, func: ast.Attribute, arg_types: Sequence[str]) -> str:
        attr = func.attr
        base = func.value
        if isinstance(base, ast.Name) and base.id == "self":
            if self.class_info is None:
                self.ctx.error(node, "'self' can only be used inside a class method.")
                return UNKNOWN_TYPE
            method = self.class_info.methods.get(attr)
            if method is None:
                if attr in self.class_info.fields:
                    self.ctx.error(node, f"'{attr}' is an attribute of {self.class_info.name}, not a method.")
                    return UNKNOWN_TYPE
                self.ctx.error(node, f"Class '{self.class_info.name}' has no method '{attr}'.")
                return UNKNOWN_TYPE
            self._check_arity(node, f"{self.class_info.name}.{attr}", len(node.args), len(method.params), len(method.params))
            for param, arg_type in zip(method.params, arg_types):
                if param.cpp_type == UNKNOWN_TYPE:
                    param.record_type(arg_type)
            return method.return_type or UNKNOWN_TYPE
        if isinstance(base, ast.Name) and base.id in ARDUINO_OBJECTS:
            return UNKNOWN_TYPE  # Serial.begin(...) / Wire.begin() pass through
        if attr == "append":
            self.ctx.error(
                node,
                "append() has to be used as a statement.",
                hint="readings.append(Reading())",
            )
            return UNKNOWN_TYPE
        base_type = self._type(base)
        if base_type in ARDUINO_OBJECTS:
            return UNKNOWN_TYPE
        class_info = self.ctx.class_of(base_type)
        if class_info is None:
            if self.ctx.is_object_type(base_type):
                return self._library_method_type(node, base_type, attr, arg_types)
            self.ctx.error(node, f"Cannot call method '{attr}' on this value.")
            return UNKNOWN_TYPE
        method = class_info.methods.get(attr)
        if method is None:
            self.ctx.error(node, f"Class '{class_info.name}' has no method '{attr}'.")
            return UNKNOWN_TYPE
        self._check_arity(node, f"{class_info.name}.{attr}", len(node.args), len(method.params), len(method.params))
        for param, arg_type in zip(method.params, arg_types):
            if param.cpp_type == UNKNOWN_TYPE:
                param.record_type(arg_type)
        return method.return_type or UNKNOWN_TYPE

    def _library_method_type(self, node: ast.Call, base_type: str, attr: str, arg_types: Sequence[str]) -> str:
        api_class = self.ctx.api_class_of(base_type)
        if api_class is None:
            return UNKNOWN_TYPE
        method = api_class.method(attr)
        if method is None:
            self.ctx.error(node, f"Class '{api_class.name}' has no method '{attr}'.")
            return UNKNOWN_TYPE
        label = f"{api_class.name}.{attr}"
        self._check_arity(node, label, len(node.args), method.min_args, method.max_args)
        self._check_argument_types(node, label, method.params, arg_types)
        return method.returns

    def _check_argument_types(self, node: ast.Call, label: str, params: Sequence[str], arg_types: Sequence[str]) -> None:
        for index, (declared, inferred) in enumerate(zip(params, arg_types), start=1):
            if not types_compatible(declared, inferred):
                self.ctx.error(node.args[index - 1], f"Argument {index} of {label}() must be {declared}, not {inferred}.")

    def _append_call_type(self, node: ast.Call, base: ast.AST, arg_types: Sequence[str]) -> str:
        if self.in_runtime_flow:
            self.ctx.error(
                node,
                "append() cannot be used in runtime control flow because the list capacity is set at compile time.",
                hint="Call append() once for every value in main().",
            )
            return UNKNOWN_TYPE
        if self.entry_name != "main":
            self.ctx.error(
                node,
                "append() can only be used in main() because the list capacity is set at compile time.",
                hint="Move the append() calls into main().",
            )
            return UNKNOWN_TYPE
        if not isinstance(base, ast.Name):
            self.ctx.error(node, "append() needs a list variable.", hint="values = [1, 2]  then  values.append(3)")
            return UNKNOWN_TYPE
        var = self.scope.lookup(base.id)
        if var is None:
            self.ctx.error(base, f"'{base.id}' is not defined.")
            return UNKNOWN_TYPE
        if not var.is_array:
            self.ctx.error(node, f"'{base.id}' is not a list, so it cannot be appended to.")
            return UNKNOWN_TYPE
        self._check_arity(node, "append", len(node.args), 1, 1)
        arg_type = arg_types[0]
        element_type = self._variable_type(var)
        if element_type not in (UNKNOWN_TYPE, CONFLICT_TYPE) and arg_type not in (UNKNOWN_TYPE, CONFLICT_TYPE):
            if merge_types(element_type, arg_type) == CONFLICT_TYPE:
                self.ctx.error(node.args[0], f"List '{base.id}' holds {element_type} values, not {arg_type}.")
        var.record_type(arg_type)
        var.append_count += 1
        var.write_count += 1
        return VOID_TYPE

    def _len_type(self, node: ast.Call) -> str:
        self._check_arity(node, "len", len(node.args), 1, 1)
        base = node.args[0]
        if isinstance(base, ast.Name):
            var = self.scope.lookup(base.id)
            if var is not None and var.is_array:
                self.ctx.tracked_arrays[id(base)] = var
                return "int"
        self.ctx.error(
            node,
            "len() is only supported for arrays created from a list literal.",
            hint="values = [1, 2, 3]  then  len(values)",
        )
        return "int"  # pragma: no cover

    def _subscript_type(self, node: ast.Subscript) -> str:
        base = node.value
        if not isinstance(base, ast.Name):
            self.ctx.error(node, "Only arrays can be indexed.")
            return UNKNOWN_TYPE
        var = self.scope.lookup(base.id)
        if var is None:
            self.ctx.error(base, f"'{base.id}' is not defined.")
            return UNKNOWN_TYPE
        if not var.is_array:
            self.ctx.error(
                node,
                f"'{base.id}' is not an array, so it cannot be indexed.",
                hint="Only list literals become arrays in controllerpy.",
            )
            return UNKNOWN_TYPE
        index_type = self._type(node.slice)
        if index_type not in ("int", "bool", "char", UNKNOWN_TYPE):
            self.ctx.error(node.slice, "Array indices must be integers.")
        return self._variable_type(var)

    def _binop_type(self, node: ast.BinOp) -> str:
        left = self._type(node.left)
        right = self._type(node.right)
        op = node.op
        if isinstance(op, (ast.BitAnd, ast.BitOr, ast.BitXor, ast.LShift, ast.RShift)):
            for operand in (left, right):
                if operand not in ("int", "bool", "char", UNKNOWN_TYPE):
                    self.ctx.error(node, f"Bitwise and shift operators need integer values, not {operand}.")
            return "int"
        if isinstance(op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)):
            for operand in (left, right):
                if operand in ("const char*", "String"):
                    self.ctx.error(
                        node,
                        "String arithmetic is not supported.",
                        hint="Print values separately with serial_print()/serial_println().",
                    )
                if self.ctx.is_object_type(operand):
                    self.ctx.error(node, f"Operators cannot be used with objects of type '{operand}'.")
            if "float" in (left, right):
                return "float"
            if UNKNOWN_TYPE in (left, right):
                return UNKNOWN_TYPE
            return "int"
        if isinstance(op, ast.Pow):
            for operand in (left, right):
                if operand not in ("int", "float", "bool", "char", UNKNOWN_TYPE):
                    self.ctx.error(node, "The '**' operator needs numeric values.")
            return "float" if "float" in (left, right) else "int"
        self.ctx.error(node, f"Unsupported Python feature: operator {type(op).__name__}")
        return UNKNOWN_TYPE  # pragma: no cover

    def _unary_type(self, node: ast.UnaryOp) -> str:
        operand = self._type(node.operand)
        if isinstance(node.op, ast.Not):
            return "bool"
        if isinstance(node.op, ast.Invert):
            if operand not in ("int", "bool", "char", UNKNOWN_TYPE):
                self.ctx.error(node, "'~' needs an integer value.")
            return "int"
        if isinstance(node.op, (ast.USub, ast.UAdd)):
            if operand in ("const char*", "String") or self.ctx.is_object_type(operand):
                self.ctx.error(node, "Unary +/- is not supported for this value.")
            return operand
        self.ctx.error(node, f"Unsupported Python feature: unary {type(node.op).__name__}")
        return UNKNOWN_TYPE  # pragma: no cover

    def _boolop_type(self, node: ast.BoolOp) -> str:
        for value in node.values:
            self._type(value)
        return "bool"

    def _compare_type(self, node: ast.Compare) -> str:
        left_type = self._type(node.left)
        if len(node.ops) > 1:
            for comparator in node.comparators:
                if any(isinstance(child, ast.Call) for child in ast.walk(comparator)):
                    self.ctx.error(
                        node,
                        "Chained comparisons cannot contain function calls.",
                        hint="Split them into two separate conditions.",
                    )
        for op, comparator in zip(node.ops, node.comparators):
            if isinstance(op, (ast.In, ast.NotIn)):
                self.ctx.error(node, "Unsupported Python feature: the 'in' operator")
            if isinstance(op, (ast.Is, ast.IsNot)):
                self.ctx.error(node, "Unsupported Python feature: 'is' comparison", hint="Compare values with == instead.")
            right_type = self._type(comparator)
            if isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
                for operand in (left_type, right_type):
                    if operand in ("const char*", "String"):
                        self.ctx.error(
                            node,
                            "Ordered comparison of strings is not supported.",
                            hint="Use == or != for strings.",
                        )
            left_type = right_type
        return "bool"

    def _ifexp_type(self, node: ast.IfExp) -> str:
        self._type(node.test)
        merged = merge_types(self._type(node.body), self._type(node.orelse))
        if merged == CONFLICT_TYPE:
            self.ctx.error(node, "Both branches of a conditional expression must have the same type.")
        return merged or UNKNOWN_TYPE

    def _literal_elements(self, node: ast.AST) -> Tuple[Optional[str], int]:
        elements = list(getattr(node, "elts"))
        if not elements:
            return None, 0
        element_type: Optional[str] = None
        for element in elements:
            if isinstance(element, (ast.List, ast.Tuple, ast.Dict, ast.Set)):
                self.ctx.error(element, "Nested lists are not supported on Arduino.", hint="Use separate arrays.")
            observed = self._type(element)
            if self.ctx.is_object_type(observed) and not self.ctx.is_struct_type(observed):
                self.ctx.error(
                    element,
                    "Lists of class objects are not supported on Arduino.",
                    hint="Use a struct: a class with fields and no methods.",
                )
            element_type = merge_types(element_type, observed)
            if element_type == CONFLICT_TYPE:
                self.ctx.error(node, "All elements of a list must have the same type.")
        return (element_type or DEFAULT_TYPE), len(elements)

    def _check_arity(self, node: ast.AST, name: str, given: int, low: int, high: int) -> None:
        if low <= given <= high:
            return
        if low == high:
            expected = f"exactly {low} argument{'s' if low != 1 else ''}"
        else:
            expected = f"{low} to {high} arguments"
        verb = "was" if given == 1 else "were"
        self.ctx.error(node, f"{name}() takes {expected} but {given} {verb} given.")

    # ------------------------------------------------------------ return types
    def retype_returns(self) -> bool:
        """Re-infer return types now that parameters and locals have types.

        A function such as ``def add(a, b): return a + b`` can only be typed
        after the call sites told us that ``a`` and ``b`` are integers, so this
        runs as a small fixpoint loop after the first analysis pass.
        """

        targets = self._return_targets()
        for _ in range(RETYPE_PASSES):
            changed = False
            for owner, node, class_info in targets:
                if owner.annotated_return is not None or owner in (self.ctx.setup_info, self.ctx.loop_info):
                    continue
                observed = self._collect_return_types(owner, node, class_info)
                if observed != list(owner.observed_returns):
                    owner.observed_returns = observed
                    changed = True
                resolved = _merge_observed(observed)
                if resolved != owner.return_type:
                    owner.return_type = resolved
                    changed = True
            if not changed:
                return False
        return True

    def _return_targets(self) -> List[Tuple[object, ast.FunctionDef, Optional[ClassInfo]]]:
        targets: List[Tuple[object, ast.FunctionDef, Optional[ClassInfo]]] = []
        for info in self.ctx.functions.values():
            if info.node is not None:
                targets.append((info, info.node, None))
        for cls in self.ctx.classes.values():
            for method in cls.all_methods():
                if method.node is not None:
                    targets.append((method, method.node, cls))
        for info in (self.ctx.setup_info, self.ctx.loop_info):
            if info is not None and info.node is not None:
                targets.append((info, info.node, None))
        return targets

    def refine_local_types(self) -> bool:
        """Type locals that were inferred from a forward referenced function."""

        changed = False
        for owner, _, class_info in self._return_targets():
            scope: Optional[Scope] = None
            for var in getattr(owner, "locals").values():
                if var.value is None or var.final_type() not in (None, UNKNOWN_TYPE, CONFLICT_TYPE):
                    continue
                if scope is None:
                    scope = self._rebuild_scope(owner, class_info)
                inferred = self._safe_type_in(var.value, scope, owner, class_info)
                if inferred in (None, UNKNOWN_TYPE, CONFLICT_TYPE):
                    continue
                var.record_type(inferred)
                changed = True
        return changed

    def _safe_type_in(
        self,
        node: ast.AST,
        scope: Scope,
        owner: object,
        class_info: Optional[ClassInfo],
    ) -> str:
        previous = (self.scope, self.owner, self.class_info, self.entry_name)
        self.scope, self.owner, self.class_info, self.entry_name = scope, owner, class_info, None
        try:
            return self._type(node)
        except ControllerPyError:
            return UNKNOWN_TYPE
        finally:
            self.scope, self.owner, self.class_info, self.entry_name = previous

    def _collect_return_types(
        self, owner: object, node: ast.FunctionDef, class_info: Optional[ClassInfo]
    ) -> List[Optional[str]]:
        scope = self._rebuild_scope(owner, class_info)
        previous = (self.scope, self.owner, self.class_info, self.entry_name)
        self.scope, self.owner, self.class_info, self.entry_name = scope, owner, class_info, None
        observed: List[Optional[str]] = []
        try:
            for stmt in iter_statements(node.body):
                if isinstance(stmt, ast.Return):
                    observed.append(None if stmt.value is None else self._safe_type(stmt.value))
        finally:
            self.scope, self.owner, self.class_info, self.entry_name = previous
        return observed

    def _safe_type(self, node: ast.AST) -> str:
        """Best effort type for an already validated expression."""

        try:
            return self._type(node)
        except ControllerPyError:
            return UNKNOWN_TYPE

    def _rebuild_scope(self, owner: object, class_info: Optional[ClassInfo]) -> Scope:
        scope = Scope("function", owner=getattr(owner, "name", None), parent=self.ctx.scope)
        if class_info is not None:
            scope.declare(VarInfo(name="self", is_param=True, is_object=True, cpp_type=class_info.name))
        for param in getattr(owner, "params"):
            scope.declare(
                VarInfo(
                    name=param.name,
                    is_param=True,
                    cpp_type=param.resolved_type(),
                )
            )
        for name, var in getattr(owner, "locals").items():
            scope.declare(
                VarInfo(
                    name=name,
                    cpp_type=var.resolved_type(),
                    is_array=var.is_array,
                    array_len=var.array_len,
                )
            )
        return scope
