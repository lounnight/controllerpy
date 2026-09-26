"""The C++ type system: how a Python type maps onto a C++ type.

The tables and helpers here describe types only.  They know nothing about the
symbol tables, which is what keeps them free of cycles: :mod:`.symbols` builds
on this module and :mod:`.context` stores the result.
"""
from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Dict, Optional

from .libraries import LIBRARIES

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .context import CompileContext

__all__ = [
    "ANNOTATION_TYPES",
    "CONFLICT_TYPE",
    "DEFAULT_TYPE",
    "SCALAR_TYPES",
    "UNKNOWN_TYPE",
    "VOID_TYPE",
    "merge_types",
    "resolve_annotation",
    "types_compatible",
]

UNKNOWN_TYPE = "unknown"
CONFLICT_TYPE = "<conflict>"
VOID_TYPE = "void"
DEFAULT_TYPE = "int"

#: Python annotation -> C++ type.
ANNOTATION_TYPES: Dict[str, str] = {
    "int": "int",
    "float": "float",
    "double": "float",
    "bool": "bool",
    "str": "String",
    "String": "String",
    "None": "void",
    "void": "void",
}

SCALAR_TYPES = frozenset({"int", "float", "bool", "String", "const char*", "char"})


def merge_types(first: Optional[str], second: Optional[str]) -> Optional[str]:
    if first is None:
        return second
    
    if second is None:
        return first
    
    if first == second:
        return first
    pair = {first, second}


    if pair <= {"int", "float", "char"}:
        return "float" if "float" in pair else "int"
    
    if pair <= {"int", "bool", "char"}:
        return "int"
    
    if pair <= {"String", "const char*"}:
        return "String"
    
    return CONFLICT_TYPE


def types_compatible(declared: str, inferred: str) -> bool:
    """Can *inferred* be stored in something declared as *declared*?"""

    if inferred in (UNKNOWN_TYPE, CONFLICT_TYPE):
        return True
    if declared == inferred:
        return True
    if declared == "float" and inferred in ("int", "bool", "char"):
        return True
    if declared == "int" and inferred in ("bool", "char"):
        return True
    if declared == "String" and inferred == "const char*":
        return True
    return False


def resolve_annotation(context: "CompileContext", node: ast.AST) -> str:
    """Map a Python type annotation onto a C++ type."""

    if isinstance(node, ast.Constant) and node.value is None:
        return VOID_TYPE
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        mapped = ANNOTATION_TYPES.get(node.value)
        if mapped:
            return mapped
    if isinstance(node, ast.Name):
        mapped = ANNOTATION_TYPES.get(node.id)
        if mapped:
            return mapped
        if node.id in context.classes:
            return node.id
        if node.id in context.external_types:
            return context.external_types[node.id]
        context.error(
            node,
            f"Unsupported type annotation: '{node.id}'",
            hint="Supported annotations:",
            hint_lines=["int", "float", "bool", "str"] + sorted(context.classes),
        )
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        if node.value.id in LIBRARIES:
            return node.attr
    context.error(node, "Unsupported type annotation.")
    
    return UNKNOWN_TYPE  # pragma: no cover - error() always raises
