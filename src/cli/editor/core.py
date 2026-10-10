from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol, Tuple

from .buffer import TAB_WIDTH, TextBuffer
from .render import Frame, render

__all__ = ["Editor", "Screen", "run_editor"]

Snapshot = Tuple[Tuple[str, ...], bool, str]
DiskVersion = Optional[Tuple[int, int]]


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
        self.message = ""
        self.running = True
        self.discarded = False
        self.pending: Optional[str] = None
        self._saved: Snapshot = buffer.snapshot()

    @property
    def dirty(self) -> bool:
        return self.buffer.snapshot() != self._saved

    def handle_key(self, key: str) -> None:
        self.message = ""
        if key == "ctrl+q":
            if self.dirty and self.pending != "quit":
                self.pending = "quit"
                self.message = "Unsaved changes: press ctrl+q again to discard them"

                return

            self.running = False
            self.discarded = self.dirty

            return

        if key == "ctrl+s":
            self.save(force=self.pending == "save")

            return

        if self.pending:
            self.pending = None

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
            self.row, self.col = self.buffer.insert(self.row, self.col, "\n")
        elif key == "tab":
            self.row, self.col = self.buffer.insert(self.row, self.col, " " * TAB_WIDTH)
        elif key == "backspace":
            self._backspace()
        elif key == "delete":
            self._delete_forward()
        elif len(key) == 1 and key.isprintable():
            self.row, self.col = self.buffer.insert(self.row, self.col, key)

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

    def _changed_on_disk(self) -> bool:
        return self.disk_version != _disk_version(self.path)

    def _vertical(self, delta: int) -> None:
        target = max(0, min(self.row + delta, self.buffer.line_count - 1))
        self.row = target
        self.col = min(self.col, len(self.buffer.line(self.row)))

    def _backspace(self) -> None:
        if self.col > 0:
            self.buffer.delete((self.row, self.col - 1), (self.row, self.col))
            self.col -= 1

            return

        if self.row > 0:
            previous = self.row - 1
            join_col = len(self.buffer.line(previous))
            self.buffer.delete((previous, join_col), (self.row, 0))
            self.row, self.col = previous, join_col

    def _delete_forward(self) -> None:
        line = self.buffer.line(self.row)
        if self.col < len(line):
            self.buffer.delete((self.row, self.col), (self.row, self.col + 1))

            return

        if self.row < self.buffer.line_count - 1:
            self.buffer.delete((self.row, len(line)), (self.row + 1, 0))


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
