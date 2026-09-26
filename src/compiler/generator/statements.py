"""Printing statements, and the functions and classes that contain them.

This is where a validated body becomes lines of C++: a function or class
signature, the locals that have to be hoisted, and every statement
:class:`validator` allowed through.  Blank lines between statements are decided
from the source line numbers, so the generated code keeps the shape of the
Python it came from.

The emitter remembers which function or method it is inside (:attr:`owner`),
because a name declared by the enclosing scope is declared where it is first
assigned rather than on every assignment.
"""

from __future__ import annotations

import ast
from typing import List, Optional, Sequence

from ..validator import UNKNOWN_TYPE, ClassInfo, CompileContext, FunctionInfo, VarInfo
from ..validator.ast_utils import constant_int, is_docstring
from .declarations import DeclarationEmitter, OwnerInfo
from .expressions import ExpressionEmitter
from .formatting import CodeWriter
from .operators import AUGASSIGN_TOKENS

__all__ = ["StatementEmitter"]


class StatementEmitter:
    def __init__(
        self,
        context: CompileContext,
        writer: CodeWriter,
        expressions: ExpressionEmitter,
        declarations: DeclarationEmitter,
    ) -> None:
        self.ctx = context
        self.w = writer
        self.exprs = expressions
        self.decl = declarations
        self.owner: Optional[OwnerInfo] = None

    # definitions
    def definitions(self, body: Sequence[ast.stmt]) -> None:
        for stmt in body:
            if isinstance(stmt, ast.FunctionDef):
                if stmt is self.ctx.setup_node:
                    self.entry_point("setup", self.ctx.setup_info, stmt)
                elif stmt is self.ctx.loop_node:
                    self.entry_point("loop", self.ctx.loop_info, stmt)
                else:
                    info = self.ctx.functions[stmt.name]
                    self.w.line(
                        f"{info.return_type} {self.decl.name(info.name)}({self.decl.parameters(info.params)}) {{"
                    )
                    self.w.indent()
                    self._emit_local_declarations(info)
                    self._emit_body(stmt.body, info)
                    self.w.dedent()
                    self.w.line("}")
                    self.w.blank()

    def entry_point(self, name: str, info: Optional[FunctionInfo], node: ast.FunctionDef) -> None:
        if info is None:  # pragma: no cover - defensive
            raise ValueError(f"missing symbol table for {name}()")
        self.w.line(f"void {name}() {{")
        self.w.indent()
        self._emit_local_declarations(info)
        self._emit_body(node.body, info)
        self.w.dedent()
        self.w.line("}")
        self.w.blank()

    def class_definition(self, cls: ClassInfo) -> None:
        self.w.line(f"class {self.decl.name(cls.name)} {{")
        self.w.line("public:")
        self.w.indent()
        for field in cls.fields.values():
            self.w.line(f"{self.decl.declaration(field)};")
        methods = cls.all_methods()
        if cls.fields and methods:
            self.w.blank()
        for index, method in enumerate(methods):
            if method.node is None:  # pragma: no cover - defensive
                continue
            if method.is_constructor:
                self.w.line(f"{self.decl.name(cls.name)}({self.decl.parameters(method.params)}) {{")
            else:
                self.w.line(
                    f"{method.return_type} {self.decl.name(method.name)}({self.decl.parameters(method.params)}) {{"
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

    def _emit_local_declarations(self, info: OwnerInfo) -> None:
        for name in info.hoisted:
            self.w.line(f"{self.decl.declaration(info.locals[name])};")
        if info.hoisted:
            self.w.blank()

    # bodies
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

    def _local_info(self, identifier: str) -> Optional[VarInfo]:
        if self.owner is None:
            return None
        return self.owner.locals.get(identifier)

    # statements
    def _emit_statement(self, stmt: ast.stmt) -> None:
        if isinstance(stmt, ast.Assign):
            self._emit_assign(stmt)
        elif isinstance(stmt, ast.AnnAssign):
            self._emit_annassign(stmt)
        elif isinstance(stmt, ast.AugAssign):
            self._emit_augassign(stmt)
        elif isinstance(stmt, ast.Expr):
            self.w.line(f"{self.exprs.expr(stmt.value)};")
        elif isinstance(stmt, ast.If):
            self._emit_if(stmt)
        elif isinstance(stmt, ast.While):
            self._emit_while(stmt)
        elif isinstance(stmt, ast.For):
            self._emit_for(stmt)
        elif isinstance(stmt, ast.Return):
            self.w.line(
                "return;" if stmt.value is None else f"return {self.exprs.value(stmt.value)};"
            )
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
            inferred = self.exprs.type_of(value)
            cpp_type = "int" if inferred in (UNKNOWN_TYPE, "void") else inferred
            temporary = f"micropy_tmp{index}"
            self.w.line(f"{cpp_type} {temporary} = {self.exprs.value(value)};")
            temporaries.append(temporary)
        for target, temporary in zip(target_elements, temporaries):
            self._emit_single_assign(target, ast.Name(id=temporary, ctx=ast.Load()), stmt)

    def _emit_annassign(self, node: ast.AnnAssign) -> None:
        if node.value is None:
            if isinstance(node.target, ast.Name):
                local = self._local_info(node.target.id)
                if local is not None and local.declare_node is node:
                    self.w.line(f"{self.decl.declaration(local)};")
                return
            self.ctx.error(node.target, "Internal error: unsupported annotated assignment target")
        self._emit_single_assign(node.target, node.value, node)

    def _emit_augassign(self, node: ast.AugAssign) -> None:
        target = self.exprs.expr(node.target)
        value = self.exprs.value(node.value)
        if isinstance(node.op, ast.FloorDiv):
            if self.exprs.type_of(node.target) == "float":
                self.w.line(f"{target} = floor({target} / {value});")
            else:
                self.w.line(f"{target} /= {value};")
            return
        if isinstance(node.op, ast.Pow):
            self.w.line(f"{target} = pow({target}, {value});")
            return
        token = AUGASSIGN_TOKENS.get(type(node.op))
        if token is None:
            self.ctx.error(node, f"Internal error: unsupported augmented assignment {type(node.op).__name__}")
        self.w.line(f"{target} {token} {value};")

    def _emit_single_assign(self, target: ast.AST, value: ast.AST, stmt: ast.stmt) -> None:
        if isinstance(target, ast.Name):
            local = self._local_info(target.id)
            if local is not None and local.declare_node is stmt:
                if self.ctx.is_object_type(local.cpp_type) and isinstance(value, ast.Call):
                    self.w.line(f"{self.decl.object_declaration(local, value)};")
                else:
                    self.w.line(f"{self.decl.declaration(local)} = {self.exprs.value(value)};")
            else:
                self.w.line(f"{self.decl.name(target.id)} = {self.exprs.value(value)};")
            return
        if isinstance(target, ast.Attribute):
            self.w.line(f"{self.exprs.expr(target)} = {self.exprs.value(value)};")
            return
        if isinstance(target, ast.Subscript):
            self.w.line(f"{self.exprs.expr(target)} = {self.exprs.value(value)};")
            return
        self.ctx.error(target, "Internal error: unsupported assignment target")

    def _emit_if(self, node: ast.If) -> None:
        self.w.line(f"if ({self.exprs.expr(node.test)}) {{")
        self.w.indent()
        self._emit_body(node.body, None)
        self.w.dedent()
        orelse = node.orelse
        while orelse:
            if len(orelse) == 1 and isinstance(orelse[0], ast.If):
                inner = orelse[0]
                self.w.line(f"}} else if ({self.exprs.expr(inner.test)}) {{")
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
        self.w.line(f"while ({self.exprs.expr(node.test)}) {{")
        self.w.indent()
        self._emit_body(node.body, None)
        self.w.dedent()
        self.w.line("}")

    def _emit_for(self, node: ast.For) -> None:
        iterator = node.iter
        assert isinstance(iterator, ast.Call)
        args = list(iterator.args)
        loop_var = self.decl.name(node.target.id)
        if len(args) == 1:
            start_text, stop_node = "0", args[0]
            step_value = 1
        elif len(args) == 2:
            start_text, stop_node = self.exprs.value(args[0]), args[1]
            step_value = 1
        else:
            start_text, stop_node = self.exprs.value(args[0]), args[1]
            step_value = constant_int(args[2]) or 0
        stop_text = self.exprs.value(stop_node)
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
