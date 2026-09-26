"""The C++ operator vocabulary stage 3 prints.

Operator precedence and the token each Python operator maps to are facts about
C++ itself, not about any particular expression, so they live in one table
instead of being spread through the printer.  A new operator is added here;
nothing in :mod:`.expressions` or :mod:`.statements` needs to change.
"""

from __future__ import annotations

import ast
from typing import Dict, Tuple

__all__ = [
    "AUGASSIGN_TOKENS",
    "BINOP_TOKENS",
    "COMPARE_TOKENS",
    "PRE_ADD",
    "PRE_AND",
    "PRE_ATOM",
    "PRE_BITAND",
    "PRE_BITOR",
    "PRE_BITXOR",
    "PRE_EQ",
    "PRE_MUL",
    "PRE_NONE",
    "PRE_OR",
    "PRE_REL",
    "PRE_SHIFT",
    "PRE_TERNARY",
    "PRE_UNARY",
]

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

BINOP_TOKENS: Dict[type, Tuple[str, int]] = {
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

COMPARE_TOKENS: Dict[type, str] = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
}

AUGASSIGN_TOKENS: Dict[type, str] = {
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
