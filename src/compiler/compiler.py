"""The compiler facade: parse -> validate -> generate."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union

from ..boards import Board, resolve_board
from .generator import CppGenerator
from .parser import SourceFile, parse_file, parse_source
from .validator import CompileContext, Validator
__all__ = ["CompileResult", "Compiler", "compile_file", "compile_source"]

@dataclass
class CompileResult:
    cpp: str
    context: CompileContext
    source: Optional[SourceFile] = None

    @property
    def line_count(self) -> int:
        return len(self.cpp.rstrip("\n").split("\n"))

    def summary(self) -> str:
        context = self.context
        globals_count = len(context.globals)
        functions_count = len(context.functions)

        parts = [
            f"{globals_count} global" + ("" if globals_count == 1 else "s"),
            f"{functions_count} function" + ("" if functions_count == 1 else "s"),
        ]

        if context.classes:
            count = len(context.classes)
            parts.append(f"{count} class" + ("" if count == 1 else "es"))
        
        return ", ".join(parts)


class Compiler:
    def __init__(self, *, filename: str = "<string>", board: Union[str, Board, None] = None) -> None:
        self.filename = filename
        self.board = board if isinstance(board, Board) else resolve_board(board)
        self.source: Optional[SourceFile] = None
        self.tree: Optional[ast.Module] = None
        self.context: Optional[CompileContext] = None

    # stages
    def parse(self, text: str) -> ast.Module:
        if self.source is None:
            self.source = SourceFile(self.filename, text)
        self.tree = parse_source(text, self.filename)

        return self.tree

    def validate(self, tree: Optional[ast.Module] = None) -> CompileContext:
        module = self.tree if tree is None else tree
        if module is None:
            raise ValueError("no parsed module: call parse() first")
        context = CompileContext(filename=self.filename, board=self.board, source=self.source)
        self.context = Validator(context).validate(module)

        return self.context

    def generate(self, context: Optional[CompileContext] = None) -> str:
        validated = self.context if context is None else context
        if validated is None:
            raise ValueError("no validated context: call validate() first")
        
        return CppGenerator(validated).generate()

    # convenience
    def compile(self, text: str, source: Optional[SourceFile] = None) -> CompileResult:
        self.source = source
        tree = self.parse(text)
        context = self.validate(tree)

        return CompileResult(cpp=self.generate(context), context=context, source=self.source)

    def compile_file(self, path: Union[str, Path]) -> CompileResult:
        source, tree = parse_file(path)
        self.source = source
        self.filename = source.filename
        context = self.validate(tree)

        return CompileResult(cpp=self.generate(context), context=context, source=source)


def compile_source(text: str, *, filename: str = "<string>", board: Union[str, Board, None] = None) -> CompileResult:
    return Compiler(filename=filename, board=board).compile(text)


def compile_file(path: Union[str, Path], *, board: Union[str, Board, None] = None) -> CompileResult:
    return Compiler(board=board).compile_file(path)
