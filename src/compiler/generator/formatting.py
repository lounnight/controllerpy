"""How generated C++ text is shaped.

Two primitives that know nothing about Python, the AST or the symbol tables:
:class:`CodeWriter` collects indented lines and hands back the finished source,
and :func:`cpp_string_literal` renders a Python string as a C++ string literal.
Changing indentation, blank-line handling or escaping happens here and nowhere
else.
"""

from __future__ import annotations

from typing import Dict, List

__all__ = ["CodeWriter", "cpp_string_literal"]

_ESCAPES: Dict[str, str] = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def cpp_string_literal(value: str) -> str:
    out = ['"']
    for char in value:
        if char in _ESCAPES:
            out.append(_ESCAPES[char])
        elif ord(char) < 32 or ord(char) == 127:
            out.append(f"\\{ord(char):03o}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


class CodeWriter:
    def __init__(self, indent_unit: str = "    ") -> None:
        self._lines: List[str] = []
        self._indent_unit = indent_unit
        self._level = 0

    def line(self, text: str = "") -> None:
        if text:
            self._lines.append(f"{self._indent_unit * self._level}{text}")
        else:
            self._lines.append("")

    def blank(self) -> None:
        if self._lines and self._lines[-1] != "":
            self._lines.append("")

    def indent(self) -> None:
        self._level += 1

    def dedent(self) -> None:
        self._level = max(0, self._level - 1)

    def text(self) -> str:
        while self._lines and self._lines[-1] == "":
            self._lines.pop()
        return "\n".join(self._lines) + "\n"
