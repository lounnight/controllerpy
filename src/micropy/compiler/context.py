"""Shared compiler state: Arduino API tables, symbol tables and type helpers.

This module deliberately contains no visiting logic.  The validator fills the
symbol tables, the generator reads them; both use the tables below so that the
supported Python subset is described in exactly one place.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from ..boards import Board, default_board
from ..errors import MicropyError
from .libraries import LIBRARIES, API_IMPORT_MODULES, Library

# Arduino constants / objects
#: Arduino constants are passed through unchanged - never folded into numbers -
#: so the generated code stays readable.
ARDUINO_CONSTANTS = frozenset(
    {
        "HIGH",
        "LOW",
        "INPUT",
        "OUTPUT",
        "INPUT_PULLUP",
        "INPUT_PULLDOWN",
        "CHANGE",
        "RISING",
        "FALLING",
        "A0",
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "LED_BUILTIN",
        "LSBFIRST",
        "MSBFIRST",
        "DEC",
        "HEX",
        "OCT",
        "BIN",
        "PI",
    }
)

# Objects declared by the Arduino core itself (methods are passed through).
ARDUINO_OBJECTS = frozenset({"Serial", "Wire", "SPI", "EEPROM"})


# micropy functions

@dataclass(frozen=True)
class ApiFunction:
    """A micropy helper function and the C++ call it maps to."""

    py_name: str
    cpp_name: str
    min_args: int
    max_args: int
    returns: str = "void"
    receiver: Optional[str] = None

    @property
    def cpp_member(self) -> str:
        """The C++ function name (``Serial.begin`` -> ``begin``)."""

        return self.cpp_name.split(".")[-1]

    def doc(self) -> str:
        return f"{self.py_name}() -> {self.cpp_name}()"


def _api(
    py_name: str,
    cpp_name: str,
    min_args: int,
    max_args: int,
    returns: str = "void",
    receiver: Optional[str] = None,
) -> ApiFunction:
    return ApiFunction(py_name, cpp_name, min_args, max_args, returns, receiver)

API_FUNCTIONS: Dict[str, ApiFunction] = {
    fn.py_name: fn
    for fn in (
        _api("pin_mode", "pinMode", 2, 2),
        _api("digital_write", "digitalWrite", 2, 2),
        _api("digital_read", "digitalRead", 1, 1, "int"),
        _api("analog_read", "analogRead", 1, 1, "int"),
        _api("analog_write", "analogWrite", 2, 2),
        _api("delay", "delay", 1, 1),
        _api("delay_microseconds", "delayMicroseconds", 1, 1),
        _api("millis", "millis", 0, 0, "int"),
        _api("micros", "micros", 0, 0, "int"),
        _api("serial_begin", "begin", 1, 1, receiver="Serial"),
        _api("serial_end", "end", 0, 0, receiver="Serial"),
        _api("serial_flush", "flush", 0, 0, receiver="Serial"),
        _api("serial_print", "print", 1, 2, receiver="Serial"),
        _api("serial_println", "println", 0, 2, receiver="Serial"),
        _api("serial_available", "available", 0, 0, "int", receiver="Serial"),
        _api("serial_read", "read", 0, 0, "int", receiver="Serial"),
    )
}

BUILTIN_FUNCTIONS: Dict[str, str] = {
    "abs": "abs",
    "min": "min",
    "max": "max",
    "constrain": "constrain",
    "pow": "pow",
    "sqrt": "sqrt",
    "floor": "floor",
    "ceil": "ceil",
    "round": "round",
}

PYTHON_BUILTIN_HINTS: Dict[str, str] = {
    "print": "use serial_println() to print over the serial port",
    "input": "read user input with serial_read() / serial_available()",
    "open": "files are not available on Arduino",
    "sleep": "use delay(milliseconds)",
    "type": "types are not available at runtime on Arduino",
    "isinstance": "types are not available at runtime on Arduino",
    "enumerate": "use for i in range(...)",
    "zip": "not available on Arduino",
    "map": "not available on Arduino",
    "filter": "not available on Arduino",
    "sum": "accumulate a variable in a loop instead",
    "sorted": "not available on Arduino",
    "format": "use serial_print() with separate values",
    "super": "class inheritance is not supported",
}

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

RESERVED_CPP_NAMES = (
    CPP_KEYWORDS
    | frozenset(fn.cpp_member for fn in API_FUNCTIONS.values())
    | frozenset(BUILTIN_FUNCTIONS)
    | frozenset({"setup", "loop", "String", "uint8_t", "uint16_t", "uint32_t", "int8_t", "int16_t", "int32_t"})
)


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

@dataclass
class VarInfo:
    name: str
    cpp_type: str = UNKNOWN_TYPE
    is_const: bool = False
    is_param: bool = False
    is_global: bool = False
    is_array: bool = False
    array_len: Optional[int] = None
    is_object: bool = False
    is_external: bool = False
    declare_node: Optional[ast.AST] = None
    value: Optional[ast.AST] = None
    write_count: int = 0
    observed_types: Set[str] = field(default_factory=set)
    lineno: Optional[int] = None
    col_offset: Optional[int] = None

    def record_type(self, cpp_type: Optional[str]) -> None:
        if cpp_type and cpp_type != UNKNOWN_TYPE:
            self.observed_types.add(cpp_type)

    def final_type(self) -> Optional[str]:
        result: Optional[str] = None
        for observed in sorted(self.observed_types):
            result = merge_types(result, observed)
            if result == CONFLICT_TYPE:
                return CONFLICT_TYPE
        
        return result

    def resolved_type(self) -> str:
        final = self.final_type()
        if not final or final == CONFLICT_TYPE:
            return self.cpp_type if self.cpp_type != UNKNOWN_TYPE else DEFAULT_TYPE
        
        return final


@dataclass
class FunctionInfo:
    name: str
    params: List[VarInfo] = field(default_factory=list)
    return_type: str = UNKNOWN_TYPE
    annotated_return: Optional[str] = None
    observed_returns: List[Optional[str]] = field(default_factory=list)
    locals: Dict[str, VarInfo] = field(default_factory=dict)
    hoisted: List[str] = field(default_factory=list)
    lineno: Optional[int] = None
    col_offset: Optional[int] = None
    node: Optional[ast.FunctionDef] = None

    @property
    def arity_text(self) -> str:
        return f"{self.name}({', '.join(p.name for p in self.params)})"


@dataclass
class MethodInfo:
    name: str
    params: List[VarInfo] = field(default_factory=list)
    return_type: str = UNKNOWN_TYPE
    annotated_return: Optional[str] = None
    observed_returns: List[Optional[str]] = field(default_factory=list)
    locals: Dict[str, VarInfo] = field(default_factory=dict)
    hoisted: List[str] = field(default_factory=list)
    is_constructor: bool = False
    lineno: Optional[int] = None
    col_offset: Optional[int] = None
    node: Optional[ast.FunctionDef] = None


@dataclass
class ClassInfo:
    name: str
    fields: Dict[str, VarInfo] = field(default_factory=dict)
    methods: Dict[str, MethodInfo] = field(default_factory=dict)
    constructor: Optional[MethodInfo] = None
    depends_on: Set[str] = field(default_factory=set)
    lineno: Optional[int] = None
    col_offset: Optional[int] = None
    node: Optional[ast.ClassDef] = None

    @property
    def field_names(self) -> List[str]:
        return list(self.fields)

    @property
    def method_names(self) -> List[str]:
        return [name for name in self.methods if not self.methods[name].is_constructor]


class Scope:
    def __init__(self, kind: str, owner: Optional[str] = None, parent: Optional["Scope"] = None) -> None:
        self.kind = kind
        self.owner = owner
        self.parent = parent
        self.variables: Dict[str, VarInfo] = {}

    def declare(self, var: VarInfo) -> VarInfo:
        self.variables[var.name] = var
        return var

    def local(self, name: str) -> Optional[VarInfo]:
        return self.variables.get(name)

    def has_local(self, name: str) -> bool:
        return name in self.variables

    def lookup(self, name: str) -> Optional[VarInfo]:
        scope: Optional[Scope] = self
        while scope is not None:
            found = scope.variables.get(name)
            if found is not None:
                return found
            scope = scope.parent
        return None


class CompileContext:
    def __init__(
        self,
        filename: str = "<string>",
        board: Optional[Board] = None,
        source: Optional[object] = None,
    ) -> None:
        self.filename = filename
        self.board = board or default_board()
        self.source = source
        self.module: Optional[ast.Module] = None

        self.functions: Dict[str, FunctionInfo] = {}
        self.classes: Dict[str, ClassInfo] = {}
        self.globals: Dict[str, VarInfo] = {}
        self.external_types: Dict[str, str] = {}
        self.imported_libraries: Dict[str, Library] = {}

        self.includes: List[str] = []
        self.setup_node: Optional[ast.FunctionDef] = None
        self.loop_node: Optional[ast.FunctionDef] = None

        self.setup_info: Optional[FunctionInfo] = None
        self.loop_info: Optional[FunctionInfo] = None
        self.scope = Scope("module")
        self._renames: Dict[str, str] = {}
        self.warnings: List[str] = []

        self.expression_types: Dict[int, str] = {}

    def error(
        self,
        node: Optional[ast.AST],
        message: str,
        *,
        hint: Optional[str] = None,
        hint_lines: Optional[List[str]] = None,
    ) -> None:
        line = getattr(node, "lineno", None)
        col = getattr(node, "col_offset", None)
        raise MicropyError(
            message,
            filename=self.filename,
            line=line,
            col=None if col is None else col + 1,
            hint=hint,
            hint_lines=hint_lines,
        )

    def api_hint_lines(self) -> List[str]:
        return [f"{name}()" for name in sorted(API_FUNCTIONS)]

    def cpp_name(self, name: str) -> str:
        if name not in self._renames:
            self._renames[name] = f"{name}_" if name in RESERVED_CPP_NAMES else name
        
        return self._renames[name]

    @staticmethod
    def is_reserved(name: str) -> bool:
        return name in RESERVED_CPP_NAMES

    def is_global(self, name: str) -> bool:
        return name in self.globals

    def class_of(self, cpp_type: Optional[str]) -> Optional[ClassInfo]:
        if cpp_type and cpp_type in self.classes:
            return self.classes[cpp_type]
        
        return None

    def is_object_type(self, cpp_type: Optional[str]) -> bool:
        return bool(cpp_type) and (cpp_type in self.classes or cpp_type in self.external_types)

    def add_function(self, info: FunctionInfo) -> FunctionInfo:
        self.functions[info.name] = info
        return info

    def add_class(self, info: ClassInfo) -> ClassInfo:
        self.classes[info.name] = info
        return info

    def add_global(self, name: str, node: Optional[ast.AST] = None) -> VarInfo:
        if name in self.globals:
            return self.globals[name]
        var = VarInfo(
            name=name,
            is_global=True,
            lineno=getattr(node, "lineno", None),
            col_offset=getattr(node, "col_offset", None),
        )
        self.globals[name] = var
        self.scope.declare(var)

        return var

    def add_include(self, header: str) -> None:
        if header not in self.includes:
            self.includes.append(header)

    def register_library(self, library: Library) -> None:
        self.imported_libraries[library.name] = library
        self.add_include(library.header)
        if library.cpp_type:
            self.external_types[library.name] = library.cpp_type

    def register_api_import(self, name: str) -> bool:
        library = LIBRARIES.get(name)
        if library is not None:
            self.register_library(library)
            return True
        
        return name in API_FUNCTIONS or name in BUILTIN_FUNCTIONS or name in ARDUINO_CONSTANTS

    def user_defined_names(self) -> List[str]:
        return sorted(list(self.functions) + list(self.classes))
