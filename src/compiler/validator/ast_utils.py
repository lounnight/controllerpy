"""AST helpers shared by both phases of stage 2, plus the subset policy.

Nothing here touches the symbol tables: these are pure functions over the
parsed AST.  ``UNSUPPORTED_FEATURES`` is the policy table behind every
"Unsupported Python feature: ..." message, so the list of rejected constructs
lives next to the helpers that recognise them.
"""
from __future__ import annotations

import ast
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

__all__ = [
    "UNSUPPORTED_FEATURES",
    "augassign_label",
    "constant_int",
    "is_bool_literal",
    "is_docstring",
    "iter_statements",
    "target_names",
    "unsupported_label",
]

#: Python constructs that controllerpy knows about but deliberately does not support.
UNSUPPORTED_FEATURES: Dict[type, str] = {
    ast.AsyncFunctionDef: "async function",
    ast.Await: "await expression",
    ast.AsyncFor: "async for loop",
    ast.AsyncWith: "async with statement",
    ast.Lambda: "lambda expression",
    ast.With: "with statement",
    ast.Try: "try/except",
    ast.Raise: "raise statement",
    ast.Assert: "assert statement",
    ast.Global: "global statement",
    ast.Nonlocal: "nonlocal statement",
    ast.Delete: "del statement",
    ast.Match: "match statement",
    ast.Yield: "yield expression",
    ast.YieldFrom: "yield from expression",
    ast.ListComp: "list comprehension",
    ast.SetComp: "set comprehension",
    ast.DictComp: "dict comprehension",
    ast.GeneratorExp: "generator expression",
    ast.Dict: "dict literal",
    ast.Set: "set literal",
    ast.Starred: "starred expression",
    ast.Slice: "slice",
    ast.JoinedStr: "f-string",
    ast.FormattedValue: "f-string",
    ast.NamedExpr: "walrus operator (:=",
}

_AUGASSIGN_LABELS: Dict[type, str] = {
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
    ast.FloorDiv: "//=",
    ast.Pow: "**=",
}


def _humanize(class_name: str) -> str:
    """``AsyncFunctionDef`` -> ``async function def`` (fallback wording)."""

    out = []
    for index, char in enumerate(class_name):
        if char.isupper() and index:
            out.append(" ")
        out.append(char.lower())
    return "".join(out)


def unsupported_label(node: ast.AST) -> str:
    """Human readable name for an unsupported node."""

    for cls in type(node).__mro__:
        if cls in UNSUPPORTED_FEATURES:
            return UNSUPPORTED_FEATURES[cls]
    return _humanize(type(node).__name__)


def augassign_label(op: ast.AST) -> Optional[str]:
    return _AUGASSIGN_LABELS.get(type(op))


def is_docstring(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def iter_statements(body: Sequence[ast.stmt]) -> Iterator[ast.stmt]:
    """Yield statements of *body* in source order, without entering defs."""

    for stmt in body:
        yield stmt
        if isinstance(stmt, ast.If):
            yield from iter_statements(stmt.body)
            yield from iter_statements(stmt.orelse)
        elif isinstance(stmt, (ast.While, ast.For)):
            yield from iter_statements(stmt.body)
            yield from iter_statements(stmt.orelse)


def target_names(target: ast.AST) -> List[Tuple[str, ast.AST]]:
    """Plain ``Name`` targets (attributes/subscripts are bound separately)."""

    if isinstance(target, ast.Name):
        return [(target.id, target)]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: List[Tuple[str, ast.AST]] = []
        for element in target.elts:
            names.extend(target_names(element))
        return names
    return []


def constant_int(node: ast.AST) -> Optional[int]:
    """Value of an integer literal, including ``-1``."""

    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return int(node.value)
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, int)
        and not isinstance(node.operand.value, bool)
    ):
        return -int(node.operand.value)
    return None


def is_bool_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, bool)
