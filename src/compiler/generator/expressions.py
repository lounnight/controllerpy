"""Printing expressions.

An expression is rendered to C++ text, parenthesised where C++ would otherwise
parse it differently from the Python it came from - and wherever the source
already grouped a sub-expression in parentheses, so the author's structure
survives the translation.  That needs the binding power of every sub-expression,
so each handler returns both the text and its precedence (:mod:`.operators`);
``expr`` is the plain-text entry point and ``_expr`` is the precedence-aware one.

Nothing here writes a line or looks at a statement: expressions form a closed
group, which is why this module has no dependency on :mod:`.statements`.
"""

from __future__ import annotations

import ast
from typing import List, Optional, Tuple

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
    def __init__(self, context: CompileContext) -> None:
        self.ctx = context

    def name(self, identifier: str) -> str:
        return self.ctx.cpp_name(identifier)

    def type_of(self, node: ast.AST) -> str:
        return self.ctx.expression_types.get(id(node), UNKNOWN_TYPE)

    # parentheses
    def _source_line(self, lineno: Optional[int]) -> str:
        source = self.ctx.source
        if source is None or lineno is None:
            return ""
        get_line = getattr(source, "line", None)
        line = get_line(lineno) if callable(get_line) else ""
        if isinstance(line, str):
            return line

        return ""

    def _parenthesized(self, node: ast.AST) -> bool:
        lineno = getattr(node, "lineno", None)
        start = getattr(node, "col_offset", None)
        end = getattr(node, "end_col_offset", None)
        if start is None or end is None or start < 1:
            return False
        if getattr(node, "end_lineno", lineno) != lineno:
            return False
        line = self._source_line(lineno)
        if len(line) <= end:
            return False
        if line[start - 1] != "(" or line[end] != ")":
            return False
        
        previous = line[start - 2] if start >= 2 else ""
        if previous.isalnum() or previous == "_":
            return False

        return True

    def _needs_parentheses(
        self, node: ast.AST, child_precedence: int, precedence: int, *, allow_equal: bool
    ) -> bool:
        if self._parenthesized(node):
            return True
        if allow_equal:
            return child_precedence < precedence

        return child_precedence <= precedence

    # expressions
    def expr(self, node: ast.AST) -> str:
        return self._expr(node)[0]

    def value(self, node: ast.AST) -> str:
        text = self.expr(node)
        if self._parenthesized(node):
            return f"({text})"

        return text

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
        if base_type in ARDUINO_OBJECTS:
            return attribute
        if self.ctx.is_library_type(base_type):
            return self._library_member_name(base_type, attribute)

        return self.name(attribute)

    def _library_member_name(self, base_type: str, attribute: str) -> str:
        api_class = self.ctx.api_class_of(base_type)
        if api_class is None:
            return attribute
        method = api_class.method(attribute)
        if method is None:
            return attribute

        return method.cpp_method

    def _subscript(self, node: ast.Subscript) -> str:
        return f"{self.expr(node.value)}[{self.value(node.slice)}]"

    def _call(self, node: ast.Call) -> str:
        func = node.func
        args = ", ".join(self.value(arg) for arg in node.args)
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
                    tracked = self.ctx.tracked_arrays.get(id(base))
                    if tracked is not None and tracked.has_count:
                        return self.ctx.count_name(base.id)
                    return f"(sizeof({array}) / sizeof({array}[0]))"
                self.ctx.error(node, "Internal error: len() on an unsupported expression")
            if name == "String":
                return f"String({args})"
            if name in self.ctx.classes or name in self.ctx.functions or name in self.ctx.external_types:
                return f"{self.name(name)}({args})"
            self.ctx.error(node, f"Internal error: unknown function {name}()")
        if isinstance(func, ast.Attribute):
            if func.attr == "append" and isinstance(func.value, ast.Name):
                return f"{self.expr(func.value)}[{self.ctx.count_name(func.value.id)}++] = {args}"
            if func.attr == "pop" and isinstance(func.value, ast.Name):
                return f"{self.expr(func.value)}[--{self.ctx.count_name(func.value.id)}]"
            if isinstance(func.value, ast.Name) and func.value.id == "self":
                return f"this->{self.name(func.attr)}({args})"
            return f"{self.expr(func.value)}.{self._member_name(func.value, func.attr)}({args})"
        self.ctx.error(node, "Internal error: unsupported call expression")

        return ""

    def _binop(self, node: ast.BinOp) -> Tuple[str, int]:
        op = node.op
        if isinstance(op, ast.Pow):
            left = self.value(node.left)
            right = self.value(node.right)
            return (f"pow({left}, {right})", PRE_ATOM)
        if isinstance(op, (ast.FloorDiv, ast.Mod)) and self._is_float(node):
            left = self.value(node.left)
            right = self.value(node.right)
            if isinstance(op, ast.FloorDiv):
                return (f"floor({left} / {right})", PRE_ATOM)
            return (f"fmod({left}, {right})", PRE_ATOM)
        token, precedence = BINOP_TOKENS[type(op)]
        left_text, left_precedence = self._expr(node.left)
        right_text, right_precedence = self._expr(node.right)
        if self._needs_parentheses(node.left, left_precedence, precedence, allow_equal=True):
            left_text = f"({left_text})"
        if self._needs_parentheses(node.right, right_precedence, precedence, allow_equal=False):
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
            if self._needs_parentheses(value, value_precedence, precedence, allow_equal=True):
                text = f"({text})"
            parts.append(text)

        return (f" {token} ".join(parts), precedence)

    def _unary(self, node: ast.UnaryOp) -> Tuple[str, int]:
        text, precedence = self._expr(node.operand)
        if self._needs_parentheses(node.operand, precedence, PRE_UNARY, allow_equal=False):
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
        left_node = node.left
        left_text, left_precedence = self._expr(left_node)
        lowest = PRE_REL
        for op, comparator in zip(node.ops, node.comparators):
            token = COMPARE_TOKENS[type(op)]
            precedence = PRE_REL if isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)) else PRE_EQ
            lowest = min(lowest, precedence)
            right_text, right_precedence = self._expr(comparator)
            left_side = left_text
            if self._needs_parentheses(left_node, left_precedence, precedence, allow_equal=True):
                left_side = f"({left_text})"
            right_side = right_text
            if self._needs_parentheses(comparator, right_precedence, precedence, allow_equal=False):
                right_side = f"({right_text})"
            parts.append(f"{left_side} {token} {right_side}")
            left_node, left_text, left_precedence = comparator, right_text, right_precedence
        if len(parts) == 1:
            return (parts[0], lowest)

        return (" && ".join(parts), PRE_AND)

    def _ifexp(self, node: ast.IfExp) -> Tuple[str, int]:
        parts: List[str] = []
        for child, allow_equal in ((node.test, False), (node.body, True), (node.orelse, True)):
            text, child_precedence = self._expr(child)
            if self._needs_parentheses(child, child_precedence, PRE_TERNARY, allow_equal=allow_equal):
                text = f"({text})"
            parts.append(text)

        return (f"{parts[0]} ? {parts[1]} : {parts[2]}", PRE_TERNARY)

    def _array_initializer(self, node: ast.AST) -> str:
        return "{" + ", ".join(self.value(element) for element in getattr(node, "elts")) + "}"

    def _is_float(self, node: ast.AST) -> bool:
        if isinstance(node, ast.BinOp):
            return "float" in (
                self.type_of(node.left),
                self.type_of(node.right),
            )

        return False
