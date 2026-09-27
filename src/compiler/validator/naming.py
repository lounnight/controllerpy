"""C++ naming rules: which names are spoken for and how the rest are mangled.

C++ keywords and the names the Arduino core provides cannot be used as
variables, and a user name that would collide with one is renamed with a
trailing underscore.  Both rules live here so the validator and the generator
agree on every name they emit.
"""
from __future__ import annotations

import ast
from typing import FrozenSet

from ...errors import ErrorReporter
from .api import API_FUNCTIONS, ARDUINO_CONSTANTS, ARDUINO_OBJECTS, BUILTIN_FUNCTIONS

__all__ = [
    "CPP_KEYWORDS",
    "RESERVED_CPP_NAMES",
    "check_reserved_variable",
    "cpp_name",
    "is_reserved",
]

CPP_KEYWORDS = frozenset(
    {
        "alignas", "alignof", "and", "and_eq", "asm", "auto", "bitand", "bitor",
        "bool", "break", "case", "catch", "char", "char16_t", "char32_t", "class",
        "compl", "const", "constexpr", "const_cast", "continue", "decltype", "default",
        "delete", "do", "double", "dynamic_cast", "else", "enum", "explicit", "export",
        "extern", "false", "far", "float", "for", "friend", "goto", "if", "inline",
        "int", "long", "mutable", "namespace", "near", "new", "noexcept", "not", "not_eq",
        "nullptr", "operator", "or", "or_eq", "private", "protected", "public", "register",
        "reinterpret_cast", "return", "short", "signed", "sizeof", "static", "static_assert",
        "static_cast", "struct", "switch", "template", "this", "thread_local", "throw",
        "true", "try", "typedef", "typeid", "typename", "union", "unsigned", "using",
        "virtual", "void", "volatile", "wchar_t", "xor", "xor_eq",
    }
)

RESERVED_CPP_NAMES: FrozenSet[str] = (
    CPP_KEYWORDS
    | frozenset(fn.cpp_member for fn in API_FUNCTIONS.values())
    | frozenset(BUILTIN_FUNCTIONS)
    | frozenset({"setup", "loop", "String", "uint8_t", "uint16_t", "uint32_t", "int8_t", "int16_t", "int32_t"})
)


def cpp_name(name: str) -> str:
    """The C++ spelling of a user name (``explicit`` -> ``explicit_``)."""

    return f"{name}_" if name in RESERVED_CPP_NAMES else name


def is_reserved(name: str) -> bool:
    return name in RESERVED_CPP_NAMES


def check_reserved_variable(report: ErrorReporter, node: ast.AST, name: str) -> None:
    """Names owned by the Arduino core cannot become variables.

    The only thing this rule needs is something that can raise against a node,
    so the caller hands in its reporter (``CompileContext.error``) instead of
    the whole context - see :class:`~controllerpy.errors.ErrorReporter`.
    """

    if name in ARDUINO_OBJECTS or name in ARDUINO_CONSTANTS:
        report(
            node,
            f"'{name}' is used by the Arduino core and cannot be a variable name.",
            hint="Please pick another name.",
        )
