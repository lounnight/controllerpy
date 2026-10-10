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

MODE_COMMAND = "command"
MODE_INSERT = "insert"
MODE_NORMAL = "normal"
MODE_VISUAL = "visual"


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
        self.command = ""
        self.prompt = ""
        self.search = ""
        self.visual_anchor: Optional[Tuple[int, int]] = None
        self.register: List[str] = []
        self.register_linewise = False
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

        if self.mode == MODE_COMMAND:
            self._handle_command(key)

            return

        if self.mode == MODE_INSERT:
            self._handle_insert(key)

            return

        if self.mode == MODE_VISUAL:
            self._handle_visual(key)

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

        if key in ("g", "d", "y"):
            self.sequence = key
            self.sequence_at = time.monotonic()
        elif key == "i":
            self.mode = MODE_INSERT
        elif key == "v":
            self.mode = MODE_VISUAL
            self.visual_anchor = (self.row, self.col)
        elif key == ":":
            self.mode = MODE_COMMAND
            self.prompt = ":"
            self.command = ""
        elif key == "/":
            self.mode = MODE_COMMAND
            self.prompt = "/"
            self.command = ""
        elif key == "n":
            self._repeat_search(forward=True)
        elif key == "N":
            self._repeat_search(forward=False)
        elif key == "x":
            self._delete_char_under_cursor()
        elif key == "u":
            self._undo()
        elif key == "p":
            self._put_below()
        elif key == "P":
            self._put_above()
        else:
            self._move(key)

        self._clamp_cursor()

    def _move(self, key: str) -> bool:
        if key in ("h", "left"):
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
        else:
            return False

        return True

    def _clamp_cursor(self) -> None:
        line = self.buffer.line(self.row)
        self.col = min(self.col, max(0, len(line) - 1))

    def _handle_visual(self, key: str) -> None:
        if key in ("escape", "v"):
            self.mode = MODE_NORMAL
            self.visual_anchor = None

            return

        if key == "y":
            self._yank_selection()
            self.mode = MODE_NORMAL
            self.visual_anchor = None

            return

        if key in ("d", "x"):
            self._delete_selection()
            self.mode = MODE_NORMAL
            self.visual_anchor = None

            return

        if self.sequence:
            if time.monotonic() - self.sequence_at > self.sequence_timeout:
                self.sequence = None
            else:
                self._finish_sequence(key)
                self._clamp_cursor()

                return

        if key == "g":
            self.sequence = "g"
            self.sequence_at = time.monotonic()

            return

        self._move(key)
        self._clamp_cursor()

    def _selection(self) -> Tuple[int, int, int, int, List[str]]:
        anchor = self.visual_anchor or (self.row, self.col)
        if anchor <= (self.row, self.col):
            start_row, start_col = anchor
            end_row, end_col = self.row, self.col
        else:
            start_row, start_col = self.row, self.col
            end_row, end_col = anchor

        if start_row == end_row:
            chunk = [self.buffer.line(start_row)[start_col : end_col + 1]]
        else:
            chunk = [self.buffer.line(start_row)[start_col:]]
            chunk.extend(self.buffer.line(row) for row in range(start_row + 1, end_row))
            chunk.append(self.buffer.line(end_row)[: end_col + 1])

        return start_row, start_col, end_row, end_col, chunk

    def _yank_selection(self) -> None:
        _, _, _, _, chunk = self._selection()
        self.register = chunk
        self.register_linewise = False
        self.message = f"{len(chunk)} lines yanked"

    def _delete_selection(self) -> None:
        start_row, start_col, end_row, end_col, chunk = self._selection()
        self.register = chunk
        self.register_linewise = False
        self._push_undo()
        self.buffer.delete((start_row, start_col), (end_row, end_col + 1))
        self.row = start_row
        self.col = start_col
        self._clamp_cursor()

    def _yank_line(self) -> None:
        self.register = [self.buffer.line(self.row)]
        self.register_linewise = True
        self.message = "1 line yanked"

    def _put_below(self) -> None:
        if not self.register:
            return

        self._push_undo()
        if self.register_linewise:
            text = "\n" + "\n".join(self.register)
            row, _ = self.buffer.insert(self.row, len(self.buffer.line(self.row)), text)
            self.row, self.col = row, 0
        else:
            text = "\n".join(self.register)
            col = min(self.col + 1, len(self.buffer.line(self.row)))
            self.row, self.col = self.buffer.insert(self.row, col, text)

        self._clamp_cursor()

    def _put_above(self) -> None:
        if not self.register:
            return

        self._push_undo()
        if self.register_linewise:
            text = "\n".join(self.register) + "\n"
            self.buffer.insert(self.row, 0, text)
            self.col = 0
        else:
            text = "\n".join(self.register)
            self.row, self.col = self.buffer.insert(self.row, self.col, text)

        self._clamp_cursor()

    def _handle_command(self, key: str) -> None:
        if key == "escape":
            self.mode = MODE_NORMAL
            self.command = ""
            self.prompt = ""

            return

        if key == "enter":
            prompt = self.prompt
            command = self.command
            self.mode = MODE_NORMAL
            self.prompt = ""
            self.command = ""
            if prompt == ":":
                self._run_command(command)
            else:
                self._run_search(command)

            return

        if key == "backspace":
            if self.command:
                self.command = self.command[:-1]
            else:
                self.mode = MODE_NORMAL

            return

        if len(key) == 1 and key.isprintable():
            self.command += key

    def _run_command(self, command: str) -> None:
        text = command.strip()
        if not text:
            return

        if text in ("w", "w!"):
            self.save(force=text.endswith("!"))

            return

        if text in ("q", "q!"):
            if text == "q!" or not self.dirty:
                self.running = False
                self.discarded = self.dirty

                return

            self.message = "No write since last change (add ! to override)"

            return

        if text in ("wq", "wq!", "x"):
            if not self.save(force=text.endswith("!")):
                return

            self.running = False

            return

        if text in ("e", "e!"):
            self._reload()

            return

        if text == "$":
            self.row = self.buffer.line_count - 1
            self.col = min(self.col, max(0, len(self.buffer.line(self.row)) - 1))

            return

        if text.isdigit():
            self.row = max(0, min(int(text) - 1, self.buffer.line_count - 1))
            self.col = min(self.col, max(0, len(self.buffer.line(self.row)) - 1))

            return

        self.message = f"Unknown command: {text}"

    def _reload(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8", newline="") as handle:
                text = handle.read()
        except FileNotFoundError:
            self.message = f"Cannot read {self.path}: no such file"

            return
        except OSError as exc:
            self.message = f"Cannot read {self.path}: {exc.strerror or exc}"

            return

        self.buffer = TextBuffer.from_text(text)
        self._saved = self.buffer.snapshot()
        self.disk_version = _disk_version(self.path)
        self.row = 0
        self.col = 0
        self._undo_stack.clear()

    def _run_search(self, query: str) -> None:
        if query:
            self.search = query

        if not self.search:
            return

        if not self._find(self.search, forward=True):
            self.message = f"Pattern not found: {self.search}"

    def _repeat_search(self, *, forward: bool) -> None:
        if not self.search:
            self.message = "No previous search"

            return

        if not self._find(self.search, forward=forward):
            self.message = f"Pattern not found: {self.search}"

    def _find(self, query: str, *, forward: bool) -> bool:
        count = self.buffer.line_count
        for step in range(count):
            if forward:
                target = (self.row + step) % count
            else:
                target = (self.row - step) % count
            line = self.buffer.line(target)
            if forward:
                start = self.col + 1 if step == 0 else 0
                index = line.find(query, start)
            else:
                limit = self.col if step == 0 else len(line)
                index = line.rfind(query, 0, limit)
            if index != -1:
                self.row = target
                self.col = min(index, max(0, len(line) - 1))

                return True

        return False

    def _finish_sequence(self, key: str) -> None:
        sequence = self.sequence
        self.sequence = None
        if sequence == key == "g":
            self._go_first_line()

            return

        if sequence == key == "d":
            self._delete_line()

            return

        if sequence == key == "y":
            self._yank_line()

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
        if self.buffer.line_count == 1 and not self.buffer.lines[0]:
            return

        self.register = [self.buffer.line(self.row)]
        self.register_linewise = True

        if self.buffer.line_count == 1:
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
