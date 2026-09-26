"""Printing expressions.

An expression is rendered to C++ text, parenthesised only where C++ would
otherwise parse it differently from the Python it came from.  That needs the
binding power of every sub-expression, so each handler returns both the text
and its precedence (:mod:`.operators`); ``expr`` is the plain-text entry point
and ``_expr`` is the precedence-aware one.

Nothing here writes a line or looks at a statement: expressions form a closed
group, which is why this module has no dependency on :mod:`.statements`.
"""

from __future__ import annotations

import ast
from typing import List, Tuple

from ..validator import ARDUINO_OBJECTS, API_FUNCTIONS, BUILTIN_FUNCTIONS, UNKNOWN_TYPE, CompileContext
from .formatting import cpp_string_literal
from .operators import (
    BINOP_TOKENS,
    COMPARE_TOKENS,
    PRE_AND,
    PRE_ATOM,
    PRE_EQ,
    PRE_NONE,
    PRE_OR,
    PRE_REL,
    PRE_TERNARY,
    PRE_UNARY,
)

__all__ = ["ExpressionEmitter"]


class ExpressionEmitter:
    """Renders a validated expression as C++."""

    def __init__(self, context: CompileContext) -> None:
        self.ctx = context

    def name(self, identifier: str) -> str:
        """C++ safe identifier for a Python name."""

        return self.ctx.cpp_name(identifier)

    def type_of(self, node: ast.AST) -> str:
        """The C++ type stage 2 inferred for *node*."""

        return self.ctx.expression_types.get(id(node), UNKNOWN_TYPE)

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
        base_type = self.type_of(base)
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
        token, precedence = BINOP_TOKENS[type(op)]
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
            token = COMPARE_TOKENS[type(op)]
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

    def _is_float(self, node: ast.AST) -> bool:
        if isinstance(node, ast.BinOp):
            return "float" in (
                self.type_of(node.left),
                self.type_of(node.right),
            )

        return False
