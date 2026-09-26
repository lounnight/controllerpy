"""Printing declarations.

Everything that turns a symbol from stage 2 into a C++ *declaration*: the
identifier spelling, ``const int x``, ``int values[3]``, a parameter list, and
the two ways a global or local object is introduced.  Both the program layout
(:mod:`.generator`, for globals and prototypes) and statement emission
(:mod:`.statements`, for locals and class members) need these, so they live
here rather than being written twice.
"""

from __future__ import annotations

import ast
from typing import Optional, Sequence, Union

from ..validator import UNKNOWN_TYPE, CompileContext, FunctionInfo, MethodInfo, VarInfo
from .expressions import ExpressionEmitter

__all__ = ["DeclarationEmitter", "OwnerInfo"]

OwnerInfo = Union[FunctionInfo, MethodInfo]


class DeclarationEmitter:
    def __init__(self, context: CompileContext, expressions: ExpressionEmitter) -> None:
        self.ctx = context
        self.exprs = expressions

    def name(self, identifier: str) -> str:
        return self.ctx.cpp_name(identifier)

    def is_object(self, var: VarInfo) -> bool:
        return bool(var.is_object or self.ctx.is_object_type(var.cpp_type))

    def declaration(self, var: VarInfo, *, const: Optional[bool] = None) -> str:
        cpp_type = var.cpp_type if var.cpp_type != UNKNOWN_TYPE else "int"
        declarator = self.name(var.name)
        if var.is_array:
            size = "" if var.array_len is None else str(var.array_len)
            declarator = f"{declarator}[{size}]"
        use_const = var.is_const if const is None else const
        if use_const and cpp_type != "const char*":
            return f"const {cpp_type} {declarator}"
        return f"{cpp_type} {declarator}"

    def parameters(self, params: Sequence[VarInfo]) -> str:
        parts = []
        for param in params:
            cpp_type = param.cpp_type if param.cpp_type != UNKNOWN_TYPE else "int"
            parts.append(f"{cpp_type} {self.name(param.name)}")

        return ", ".join(parts)

    def global_declaration(self, var: VarInfo) -> str:
        if self.is_object(var):
            if isinstance(var.value, ast.Call):
                return f"{self.object_declaration(var, var.value)};"
            type_name = var.cpp_type if var.cpp_type != UNKNOWN_TYPE else "int"
            return f"{self.name(type_name)} {self.name(var.name)};"
        declaration = self.declaration(var, const=var.is_const)
        if var.value is None:
            return f"{declaration};"

        return f"{declaration} = {self.exprs.value(var.value)};"

    def object_declaration(self, var: VarInfo, call: ast.Call) -> str:
        type_name = var.cpp_type if var.cpp_type != UNKNOWN_TYPE else "int"
        args = ", ".join(self.exprs.value(arg) for arg in call.args)
        suffix = f"({args})" if args else ""

        return f"{self.name(type_name)} {self.name(var.name)}{suffix}"

    def uses_class_type(self, info: OwnerInfo) -> bool:
        if info.return_type in self.ctx.classes:
            return True

        return any(param.cpp_type in self.ctx.classes for param in info.params)
