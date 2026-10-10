from __future__ import annotations

from typing import List, Tuple

__all__ = ["TAB_WIDTH", "TextBuffer"]

TAB_WIDTH = 4


class TextBuffer:
    def __init__(self, lines: List[str], trailing_newline: bool, eol: str = "\n") -> None:
        self.lines = lines
        self.trailing_newline = trailing_newline
        self.eol = eol

    @classmethod
    def from_text(cls, text: str) -> "TextBuffer":
        eol = "\r\n" if "\r\n" in text else "\n"
        body = text.replace("\r\n", "\n")
        if body.endswith("\n"):
            return cls(body.split("\n")[:-1], True, eol)

        return cls(body.split("\n"), False, eol)

    @classmethod
    def empty(cls) -> "TextBuffer":
        return cls([""], True)

    @property
    def line_count(self) -> int:
        return len(self.lines)

    def line(self, row: int) -> str:
        if 0 <= row < len(self.lines):
            return self.lines[row]

        return ""

    def text(self) -> str:
        body = self.eol.join(self.lines)
        if self.trailing_newline:
            return body + self.eol

        return body

    def insert(self, row: int, col: int, text: str) -> Tuple[int, int]:
        line = self.lines[row]
        col = max(0, min(col, len(line)))
        parts = text.split("\n")
        if len(parts) == 1:
            self.lines[row] = line[:col] + text + line[col:]

            return row, col + len(text)

        self.lines[row] = line[:col] + parts[0]
        middle = parts[1:-1]
        self.lines[row + 1 : row + 1] = middle
        self.lines.insert(row + len(middle) + 1, parts[-1] + line[col:])

        return row + len(parts) - 1, len(parts[-1])

    def delete(self, start: Tuple[int, int], end: Tuple[int, int]) -> None:
        row1, col1 = start
        row2, col2 = end
        if (row1, col1) > (row2, col2):
            row1, col1, row2, col2 = row2, col2, row1, col1

        if row1 == row2:
            line = self.lines[row1]
            self.lines[row1] = line[:col1] + line[col2:]

            return

        head = self.lines[row1][:col1]
        tail = self.lines[row2][col2:]
        self.lines[row1 : row2 + 1] = [head + tail]

    def snapshot(self) -> Tuple[Tuple[str, ...], bool, str]:
        return tuple(self.lines), self.trailing_newline, self.eol

    def restore(self, snapshot: Tuple[Tuple[str, ...], bool, str]) -> None:
        lines, trailing_newline, eol = snapshot
        self.lines = list(lines)
        self.trailing_newline = trailing_newline
        self.eol = eol
