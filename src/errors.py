from __future__ import annotations

import ast
from typing import Iterable, List, Optional, Protocol

__all__ = ["ControllerPyError", "ArduinoCliError", "ArduinoPyError", "ErrorReporter"]


class ErrorReporter(Protocol):
    
    def __call__(
        self,
        node: Optional[ast.AST],
        message: str,
        *,
        hint: Optional[str] = None,
        hint_lines: Optional[List[str]] = None,
    ) -> None:
        """Raise for *message*, anchored at *node*.  Never returns."""


class ControllerPyError(Exception):
    title = "ControllerPyError"

    def __init__(
        self,
        message: str,
        *,
        filename: Optional[str] = None,
        line: Optional[int] = None,
        col: Optional[int] = None,
        hint: Optional[str] = None,
        hint_lines: Optional[Iterable[str]] = None,
        ) -> None:

        super().__init__(message)
        self.message = message
        self.filename = filename
        self.line = line
        self.col = col
        self.hint = hint

        self.hint_lines = list(hint_lines) if hint_lines else []

    @property
    def location(self) -> Optional[str]:
        if not self.filename:
            return None
        if self.line is None:
            return self.filename
        if self.col is None:
            return f"{self.filename}:{self.line}"
        
        return f"{self.filename}:{self.line}:{self.col}"

    def format(self) -> str:
        lines = [f"{self.title}:", ""]
        location = self.location

        if location:
            lines.extend([f"  {location}",""])
        lines.append(f"  {self.message}")
        if self.hint:
            lines.extend(["",f"  {self.hint}"])
        if self.hint_lines:
            lines.extend(f"    {item}".rstrip() for item in self.hint_lines)
        
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.format()


#: Legacy name of :class:`ControllerPyError`, kept for the first prototype's API.
ArduinoPyError = ControllerPyError


class ArduinoCliError(ControllerPyError):
    """Raised when arduino-cli is missing or the toolchain call failed."""

    title = "ArduinoCliError"
