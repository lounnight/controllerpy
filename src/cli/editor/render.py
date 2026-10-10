from __future__ import annotations

from typing import TYPE_CHECKING, List, NamedTuple

from .buffer import TAB_WIDTH

if TYPE_CHECKING:
    from .core import Editor

__all__ = ["Frame", "render"]


class Frame(NamedTuple):
    lines: List[str]
    cursor_row: int
    cursor_col: int


def render(editor: "Editor", rows: int, cols: int) -> Frame:
    rows = max(rows, 1)
    cols = max(cols, 1)
    text_rows = max(rows - 1, 0)
    _follow(editor, text_rows)

    lines: List[str] = []
    for index in range(text_rows):
        source_row = editor.top_row + index
        if source_row >= editor.buffer.line_count:
            lines.append("")
        else:
            lines.append(_visible(editor.buffer.line(source_row), editor.left_col, cols))
    lines.append(_last_line(editor, cols))

    screen_row = max(0, min(editor.row - editor.top_row, len(lines) - 1))
    screen_col = _screen_column(editor.buffer.line(editor.row), editor.col) - editor.left_col
    screen_col = max(0, min(screen_col, cols - 1))

    return Frame(lines, screen_row, screen_col)


def _follow(editor: "Editor", text_rows: int) -> None:
    if editor.row < editor.top_row:
        editor.top_row = editor.row
    if text_rows > 0 and editor.row >= editor.top_row + text_rows:
        editor.top_row = editor.row - text_rows + 1
    editor.top_row = max(0, editor.top_row)


def _expand_tabs(line: str) -> str:
    pieces: List[str] = []
    column = 0
    for char in line:
        if char == "\t":
            width = TAB_WIDTH - column % TAB_WIDTH
            pieces.append(" " * width)
            column += width
        else:
            pieces.append(char)
            column += 1

    return "".join(pieces)


def _screen_column(line: str, col: int) -> int:
    return len(_expand_tabs(line[:col]))


def _visible(line: str, left_col: int, cols: int) -> str:
    return _expand_tabs(line)[left_col : left_col + cols]


def _last_line(editor: "Editor", cols: int) -> str:
    if editor.message:
        return " " + editor.message[: cols - 1]

    dirty = " [+]" if editor.dirty else ""
    position = f"  {editor.row + 1}:{editor.col + 1}"
    hint = "  ctrl+s save  ctrl+q quit"
    for target in (str(editor.path), editor.path.name):
        line = f" {target}{dirty}{position}{hint}"
        if len(line) <= cols:
            return line

    return f" {editor.path.name}{dirty}{position}{hint}"[:cols]
