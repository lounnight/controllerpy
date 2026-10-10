from __future__ import annotations

import time
from pathlib import Path
from typing import List, Optional, Protocol, Tuple

from .buffer import TAB_WIDTH, TextBuffer
from .render import Frame, render

__all__ = ["Editor", "Screen", "run_editor"]

Snapshot = Tuple[Tuple[str, ...], bool, str]
DiskVersion = Optional[Tuple[int, int]]

UNDO_LIMIT = 500
SEQUENCE_TIMEOUT = 1.0

MODE_INSERT = "insert"
MODE_NORMAL = "normal"


class Screen(Protocol):
    def size(self) -> Tuple[int, int]:
        ...

    def draw(self, frame: Frame) -> None:
        ...

    def read_key(self, timeout: float) -> Optional[str]:
        ...


class Editor:
    def __init__(self, path: Path, buffer: TextBuffer, *, disk_version: DiskVersion = None) -> None:
        self.path = path
        self.buffer = buffer
        self.disk_version = disk_version
        self.row = 0
        self.col = 0
        self.top_row = 0
        self.left_col = 0
        self.mode = MODE_NORMAL
        self.message = ""
        self.running = True
        self.discarded = False
        self.pending: Optional[str] = None
        self.sequence: Optional[str] = None
        self.sequence_at = 0.0
        self.sequence_timeout = SEQUENCE_TIMEOUT
        self._undo_stack: List[Tuple[Snapshot, int, int]] = []
        self._saved: Snapshot = buffer.snapshot()

    @property
    def dirty(self) -> bool:
        return self.buffer.snapshot() != self._saved

    def handle_key(self, key: str) -> None:
        self.message = ""
        if key == "ctrl+q":
            self.sequence = None
            if self.dirty and self.pending != "quit":
                self.pending = "quit"
                self.message = "Unsaved changes: press ctrl+q again to discard them"

                return

            self.running = False
            self.discarded = self.dirty

            return

        if key == "ctrl+s":
            self.sequence = None
            self.save(force=self.pending == "save")

            return

        if self.pending:
            self.pending = None

        if self.mode == MODE_INSERT:
            self._handle_insert(key)

            return

        self._handle_normal(key)

    def save(self, *, force: bool = False) -> bool:
        if not force and self._changed_on_disk():
            self.pending = "save"
            self.message = "File changed on disk: press ctrl+s again to overwrite"

            return False

        try:
            with open(self.path, "w", encoding="utf-8", newline="") as handle:
                handle.write(self.buffer.text())
        except OSError as exc:
            self.message = f"Cannot write {self.path}: {exc.strerror or exc}"

            return False

        self._saved = self.buffer.snapshot()
        self.disk_version = _disk_version(self.path)
        self.pending = None
        self.message = f'"{self.path.name}" written'

        return True

    def _handle_insert(self, key: str) -> None:
        if key == "escape":
            self.mode = MODE_NORMAL
            if self.col > 0:
                self.col -= 1

            return

        if key == "left":
            self.col = max(0, self.col - 1)
        elif key == "right":
            self.col = min(len(self.buffer.line(self.row)), self.col + 1)
        elif key == "up":
            self._vertical(-1)
        elif key == "down":
            self._vertical(1)
        elif key == "home":
            self.col = 0
        elif key == "end":
            self.col = len(self.buffer.line(self.row))
        elif key == "enter":
            self._push_undo()
            self.row, self.col = self.buffer.insert(self.row, self.col, "\n")
        elif key == "tab":
            self._push_undo()
            self.row, self.col = self.buffer.insert(self.row, self.col, " " * TAB_WIDTH)
        elif key == "backspace":
            self._backspace()
        elif key == "delete":
            self._delete_forward()
        elif len(key) == 1 and key.isprintable():
            self._push_undo()
            self.row, self.col = self.buffer.insert(self.row, self.col, key)

    def _handle_normal(self, key: str) -> None:
        if self.sequence:
            if time.monotonic() - self.sequence_at > self.sequence_timeout:
                self.sequence = None
            else:
                self._finish_sequence(key)

                return

        if key in ("g", "d"):
            self.sequence = key
            self.sequence_at = time.monotonic()
        elif key == "i":
            self.mode = MODE_INSERT
        elif key in ("h", "left"):
            self.col = max(0, self.col - 1)
        elif key in ("l", "right"):
            self.col = min(len(self.buffer.line(self.row)), self.col + 1)
        elif key in ("k", "up"):
            self._vertical(-1)
        elif key in ("j", "down"):
            self._vertical(1)
        elif key in ("0", "home"):
            self.col = 0
        elif key in ("$", "end"):
            self.col = len(self.buffer.line(self.row))
        elif key == "w":
            self._word_forward()
        elif key == "b":
            self._word_backward()
        elif key == "x":
            self._delete_char_under_cursor()
        elif key == "u":
            self._undo()

        line = self.buffer.line(self.row)
        self.col = min(self.col, max(0, len(line) - 1))

    def _finish_sequence(self, key: str) -> None:
        sequence = self.sequence
        self.sequence = None
        if sequence == key == "g":
            self._go_first_line()

            return

        if sequence == key == "d":
            self._delete_line()

            return

        self.message = "Invalid key sequence"

    def _changed_on_disk(self) -> bool:
        return self.disk_version != _disk_version(self.path)

    def _vertical(self, delta: int) -> None:
        target = max(0, min(self.row + delta, self.buffer.line_count - 1))
        self.row = target
        self.col = min(self.col, len(self.buffer.line(self.row)))

    def _word_forward(self) -> None:
        row, col = self.row, self.col
        line = self.buffer.line(row)
        if col < len(line) and not line[col].isspace():
            word = _is_word_char(line[col])
            while col < len(line) and not line[col].isspace() and _is_word_char(line[col]) == word:
                col += 1
            if col < len(line) and not line[col].isspace():
                self.row, self.col = row, col

                return

        line = self.buffer.line(row)
        while col < len(line) and line[col].isspace():
            col += 1
        if col < len(line):
            self.row, self.col = row, col

            return

        if row + 1 < self.buffer.line_count:
            self.row, self.col = row + 1, 0
        else:
            self.row, self.col = row, len(line)

    def _word_backward(self) -> None:
        row, col = self.row, self.col
        if col > 0:
            col -= 1
        elif row > 0:
            row -= 1
            col = len(self.buffer.line(row))
        else:
            return

        line = self.buffer.line(row)
        while col > 0 and (col >= len(line) or line[col].isspace()):
            col -= 1
        if col < len(line) and not line[col].isspace():
            word = _is_word_char(line[col])
            while col > 0 and not line[col - 1].isspace() and _is_word_char(line[col - 1]) == word:
                col -= 1

        self.row, self.col = row, col

    def _go_first_line(self) -> None:
        line = self.buffer.line(0)
        self.row = 0
        self.col = len(line) - len(line.lstrip())

    def _delete_char_under_cursor(self) -> None:
        line = self.buffer.line(self.row)
        if self.col >= len(line):
            return

        self._push_undo()
        self.buffer.delete((self.row, self.col), (self.row, self.col + 1))

    def _delete_line(self) -> None:
        if self.buffer.line_count == 1:
            if not self.buffer.lines[0]:
                return

            self._push_undo()
            self.buffer.delete((0, 0), (0, len(self.buffer.lines[0])))
            self.row, self.col = 0, 0

            return

        self._push_undo()
        if self.row == self.buffer.line_count - 1:
            previous = self.row - 1
            join_col = len(self.buffer.line(previous))
            self.buffer.delete((previous, join_col), (self.row, len(self.buffer.line(self.row))))
            self.row = previous
        else:
            self.buffer.delete((self.row, 0), (self.row + 1, 0))

        self.col = min(self.col, len(self.buffer.line(self.row)))

    def _backspace(self) -> None:
        if self.col > 0:
            self._push_undo()
            self.buffer.delete((self.row, self.col - 1), (self.row, self.col))
            self.col -= 1

            return

        if self.row > 0:
            self._push_undo()
            previous = self.row - 1
            join_col = len(self.buffer.line(previous))
            self.buffer.delete((previous, join_col), (self.row, 0))
            self.row, self.col = previous, join_col

    def _delete_forward(self) -> None:
        line = self.buffer.line(self.row)
        if self.col < len(line):
            self._push_undo()
            self.buffer.delete((self.row, self.col), (self.row, self.col + 1))

            return

        if self.row < self.buffer.line_count - 1:
            self._push_undo()
            self.buffer.delete((self.row, len(line)), (self.row + 1, 0))

    def _push_undo(self) -> None:
        self._undo_stack.append((self.buffer.snapshot(), self.row, self.col))
        if len(self._undo_stack) > UNDO_LIMIT:
            del self._undo_stack[0]

    def _undo(self) -> None:
        if not self._undo_stack:
            self.message = "Already at oldest change"

            return

        snapshot, row, col = self._undo_stack.pop()
        self.buffer.restore(snapshot)
        self.row = min(row, self.buffer.line_count - 1)
        self.col = min(col, len(self.buffer.line(self.row)))


def _is_word_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _disk_version(path: Path) -> DiskVersion:
    try:
        stat = path.stat()
    except OSError:
        return None

    return stat.st_mtime_ns, stat.st_size


def run_editor(editor: Editor, screen: Screen) -> None:
    while editor.running:
        frame = render(editor, *screen.size())
        screen.draw(frame)
        key = screen.read_key(timeout=0.5)
        if key is not None:
            editor.handle_key(key)
