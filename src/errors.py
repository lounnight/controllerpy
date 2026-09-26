from __future__ import annotations
from typing import Iterable, Optional

__all__ = ["MicropyError", "ArduinoCliError", "ArduinoPyError"]

class MicropyError(Exception):
    title = "MicropyError"

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


#: Legacy name of :class:`MicropyError`, kept for the first prototype's API.
ArduinoPyError = MicropyError


class ArduinoCliError(MicropyError):
    """Raised when arduino-cli is missing or the toolchain call failed."""

    title = "ArduinoCliError"
