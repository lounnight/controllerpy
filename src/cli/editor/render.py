from __future__ import annotations

from typing import TYPE_CHECKING, List, NamedTuple

from .buffer import TAB_WIDTH
from .syntax import Span, highlight_line

if TYPE_CHECKING:
    from .core import Editor

__all__ = ["Frame", "render"]

MIN_NUMBER_WIDTH = 3
GUTTER_SEPARATOR = " | "

PROMPT_KIND = "prompt"
MESSAGE_KIND = "message"
ERROR_KIND = "error"
IDLE_KIND = "idle"


class Frame(NamedTuple):
    lines: List[str]
    cursor_row: int
    cursor_col: int
    styles: List[List[Span]]
    highlight_row: int
    status_row: int
    command_row: int
    command_kind: str


def render(editor: "Editor", rows: int, cols: int) -> Frame:
    rows = max(rows, 1)
    cols = max(cols, 1)
    status_rows = 1 if rows >= 2 else 0
    text_rows = max(rows - 1 - status_rows, 0)
    _follow(editor, text_rows)

    number_width = _number_width(editor.buffer.line_count)
    gutter_width = number_width + len(GUTTER_SEPARATOR)
    if cols <= gutter_width:
        gutter_width = 0
    source_cols = max(1, cols - gutter_width)

    if editor.mode != "command":
        _follow_horizontal(editor, source_cols)

    lines: List[str] = []
    styles: List[List[Span]] = []
    for index in range(text_rows):
        source_row = editor.top_row + index
        if source_row >= editor.buffer.line_count:
            lines.append("")
            styles.append([])

            continue

        expanded = _expand_tabs(editor.buffer.line(source_row))
        prefix = "" if gutter_width == 0 else _gutter(source_row + 1, number_width)
        visible = expanded[editor.left_col : editor.left_col + source_cols]
        lines.append(prefix + visible)

        spans = _clip_spans(highlight_line(expanded), editor.left_col, source_cols)
        if gutter_width:
            spans = [(start + gutter_width, end + gutter_width, kind) for start, end, kind in spans]
        styles.append(spans)

    status_row = -1
    if status_rows:
        status_row = len(lines)
        lines.append(_status_line(editor, cols))
        styles.append([])

    command_kind = _command_kind(editor)
    command_row = len(lines)
    lines.append(_command_line(editor, cols, command_kind))
    styles.append([])

    if editor.mode == "command":
        cursor_row = command_row
        cursor_col = max(0, min(len(editor.prompt) + len(editor.command), cols - 1))
        highlight_row = -1
    elif text_rows > 0:
        cursor_row = max(0, min(editor.row - editor.top_row, text_rows - 1))
        cursor_column = _screen_column(editor.buffer.line(editor.row), editor.col)
        cursor_col = max(0, min(gutter_width + cursor_column - editor.left_col, cols - 1))
        highlight_row = cursor_row
    else:
        cursor_row = command_row
        cursor_col = 0
        highlight_row = -1

    return Frame(lines, cursor_row, cursor_col, styles, highlight_row, status_row, command_row, command_kind)


def _number_width(line_count: int) -> int:
    return max(MIN_NUMBER_WIDTH, len(str(max(1, line_count))))


def _gutter(number: int, width: int) -> str:
    return f"{number:>{width}}{GUTTER_SEPARATOR}"


def _follow(editor: "Editor", text_rows: int) -> None:
    if editor.row < editor.top_row:
        editor.top_row = editor.row
    if text_rows > 0 and editor.row >= editor.top_row + text_rows:
        editor.top_row = editor.row - text_rows + 1
    editor.top_row = max(0, editor.top_row)


def _follow_horizontal(editor: "Editor", source_cols: int) -> None:
    cursor_column = _screen_column(editor.buffer.line(editor.row), editor.col)
    if cursor_column < editor.left_col:
        editor.left_col = cursor_column
    elif cursor_column >= editor.left_col + source_cols:
        editor.left_col = cursor_column - source_cols + 1
    editor.left_col = max(0, editor.left_col)


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


def _clip_spans(spans: List[Span], left_col: int, cols: int) -> List[Span]:
    window_end = left_col + cols
    clipped: List[Span] = []
    for start, end, kind in spans:
        begin = max(start, left_col)
        finish = min(end, window_end)
        if begin < finish:
            clipped.append((begin - left_col, finish - left_col, kind))

    return clipped


def _status_line(editor: "Editor", cols: int) -> str:
    dirty = " [+]" if editor.dirty else ""
    position = f"  Line {editor.row + 1}, Col {editor.col + 1}  {editor.mode.upper()}"
    hint = "  ctrl+s save  ctrl+q quit  : command"
    for target in (str(editor.path), editor.path.name):
        line = f" {target}{dirty}{position}{hint}"
        if len(line) <= cols:
            return line

    return f" {editor.path.name}{dirty}{position}{hint}"[:cols]


def _command_kind(editor: "Editor") -> str:
    if editor.mode == "command":
        return PROMPT_KIND
    if editor.error:
        return ERROR_KIND
    if editor.message:
        return MESSAGE_KIND

    return IDLE_KIND


def _command_line(editor: "Editor", cols: int, kind: str) -> str:
    if kind == PROMPT_KIND:
        return (editor.prompt + editor.command)[:cols]

    if editor.message:
        return " " + editor.message[: cols - 1]

    return ""
