"""The state stage 2 hands to stage 3.

:class:`CompileContext` is the contract between the phases: the validator fills
the symbol tables and the type information in it, the generator reads them.  It
deliberately contains no visiting logic and no tables of its own - the Arduino
API lives in :mod:`.api`, the type system in :mod:`.types`, the naming rules in
:mod:`.naming` and the records these tables fill in live in :mod:`.symbols`.
"""

from __future__ import annotations

import ast
from typing import Dict, List, Optional

from ...boards import Board, default_board
from ...errors import MicropyError
from .api import API_FUNCTIONS, ARDUINO_CONSTANTS, BUILTIN_FUNCTIONS
from .libraries import Library, library_for
from .naming import cpp_name as _cpp_name, is_reserved
from .symbols import ClassInfo, FunctionInfo, Scope, VarInfo

__all__ = ["CompileContext"]


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
            self._renames[name] = _cpp_name(name)
        
        return self._renames[name]

    @staticmethod
    def is_reserved(name: str) -> bool:
        return is_reserved(name)

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
        library = library_for(name)
        if library is not None:
            self.register_library(library)
            return True
        
        return name in API_FUNCTIONS or name in BUILTIN_FUNCTIONS or name in ARDUINO_CONSTANTS

    def user_defined_names(self) -> List[str]:
        return sorted(list(self.functions) + list(self.classes))
