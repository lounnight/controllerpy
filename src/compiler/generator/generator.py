"""Stage 3: validated, typed AST -> readable Arduino C++.

This module is the orchestration of the stage and nothing else.  :meth:`CppGenerator.generate`
runs the emission passes in the one order that produces valid C++, and every
pass delegates the actual printing to the emitters:

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

from ..validator import CompileContext
from .declarations import DeclarationEmitter
from .expressions import ExpressionEmitter
from .formatting import CodeWriter
from .ordering import order_classes
from .statements import StatementEmitter

__all__ = ["CppGenerator"]


class CppGenerator:
    """Turns a validated :class:`CompileContext` into the C++ of one sketch."""

    def __init__(self, context: CompileContext) -> None:
        self.ctx = context
        self.w = CodeWriter()
        self.expressions = ExpressionEmitter(context)
        self.declarations = DeclarationEmitter(context, self.expressions)
        self.statements = StatementEmitter(context, self.w, self.expressions, self.declarations)

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
        self.statements.definitions(module.body)

        return self.w.text()

    def name(self, identifier: str) -> str:
        """C++ safe identifier for a Python name."""

        return self.expressions.name(identifier)

    def expr(self, node: ast.AST) -> str:
        return self.expressions.expr(node)

    # program layout
    def _emit_includes(self) -> None:
        for header in self.ctx.includes:
            self.w.line(f"#include <{header}>")
        self.w.blank()

    def _emit_globals(self, *, objects: bool) -> None:
        emitted = False
        for var in self.ctx.globals.values():
            if self.declarations.is_object(var) != objects:
                continue
            self.w.line(self.declarations.global_declaration(var))
            if var.append_count:
                self.w.line(f"{self.declarations.counter_declaration(var)};")
            emitted = True
        if emitted:
            self.w.blank()

    def _emit_prototypes(self, *, class_signatures: bool) -> None:
        emitted = False
        for info in self.ctx.functions.values():
            if self.declarations.uses_class_type(info) != class_signatures:
                continue
            self.w.line(
                f"{info.return_type} {self.name(info.name)}({self.declarations.parameters(info.params)});"
            )
            emitted = True
        if emitted:
            self.w.blank()

    def _emit_classes(self) -> None:
        for cls in order_classes(self.ctx):
            if cls.is_struct:
                self.statements.struct_definition(cls)
            else:
                self.statements.class_definition(cls)
