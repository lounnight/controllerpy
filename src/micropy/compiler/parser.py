"""Stage 1 of the compiler: Python source -> AST.

Uses Python's own :mod:`ast` module - never regular expressions - so that
micropy accepts exactly the Python grammar.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Union

from ..errors import MicropyError
__all__ = ["SourceFile", "parse_source", "parse_file"]

@dataclass(frozen=True)
class SourceFile:
    filename: str
    text: str

    @property
    def lines(self) -> List[str]:
        return self.text.splitlines()

    def line(self, lineno: int) -> str:
        lines = self.lines
        if 1 <= lineno <= len(lines):
            return lines[lineno - 1]
        return ""


def parse_source(text: str, filename: str = "<string>") -> ast.Module:
    try:
        return ast.parse(text, filename=filename, mode="exec", type_comments=False)
    except SyntaxError as exc:  # also covers IndentationError/TabError
        raise MicropyError(
            f"Invalid Python syntax: {exc.msg}",
            filename=exc.filename or filename,
            line=exc.lineno,
            col=exc.offset,
            hint="micropy compiles Python 3 source code.",
        ) from None
    except ValueError as exc:
        raise MicropyError(f"Could not parse {filename}: {exc}", filename=filename) from None
    except RecursionError:
        raise MicropyError(
            f"Could not parse {filename}: the file is nested too deeply", filename=filename
        ) from None


def parse_file(path: Union[str, Path]) -> Tuple[SourceFile, ast.Module]:
    source_path = Path(path)
    if not source_path.exists():
        raise MicropyError(f"Source file not found: {source_path}")
    if source_path.is_dir():
        raise MicropyError(f"{source_path} is a directory, not a Python file")
    try:
        text = source_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise MicropyError(
            f"{source_path} is not valid UTF-8 text: {exc}", filename=str(source_path)
        ) from None
    except OSError as exc:
        raise MicropyError(f"Could not read {source_path}: {exc}", filename=str(source_path)) from None

    source = SourceFile(str(source_path), text)
    
    return source, parse_source(text, str(source_path))
