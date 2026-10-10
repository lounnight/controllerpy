from __future__ import annotations

import os
import select
import shutil
import sys
import time
from typing import List, Optional, TextIO, Tuple

from .keys import parse_key
from .render import Frame
from .syntax import Span

__all__ = ["EditorError", "Terminal", "apply_styles"]

_ENTER_ALT = "\x1b[?1049h"
_LEAVE_ALT = "\x1b[?1049l"
_SHOW_CURSOR = "\x1b[?25h"
_RESET = "\x1b[0m"
_CLEAR = "\x1b[2J\x1b[H"
_CURRENT_LINE = "\x1b[48;5;236m"
_STYLE_OFF = "\x1b[22;39m"

_SEQUENCE_WAIT = 0.1

_STYLE_CODES = {
    "keyword": "\x1b[1;34m",
    "builtin": "\x1b[36m",
    "constant": "\x1b[35m",
    "type": "\x1b[33m",
    "string": "\x1b[32m",
    "number": "\x1b[36m",
    "comment": "\x1b[90m",
}


def apply_styles(line: str, spans: List[Span]) -> str:
    if not spans:
        return line

    pieces: List[str] = []
    cursor = 0
    for start, end, kind in spans:
        if start > cursor:
            pieces.append(line[cursor:start])
        pieces.append(_STYLE_CODES.get(kind, ""))
        pieces.append(line[start:end])
        pieces.append(_STYLE_OFF)
        cursor = end
    pieces.append(line[cursor:])

    return "".join(pieces)


class EditorError(Exception):
    pass


class Terminal:
    def __init__(self, stdin: Optional[TextIO] = None, stdout: Optional[TextIO] = None) -> None:
        self._stdin = sys.stdin if stdin is None else stdin
        self._stdout = sys.stdout if stdout is None else stdout
        self._fd = -1
        self._saved: Optional[list] = None
        self._pending = b""

    def __enter__(self) -> "Terminal":
        try:
            import termios
            import tty
        except ImportError as exc:
            raise EditorError("The editor needs a POSIX terminal (Linux or macOS).") from exc

        if not _isatty(self._stdin) or not _isatty(self._stdout):
            raise EditorError("The editor needs an interactive terminal, not a pipe or a file.")

        self._fd = self._stdin.fileno()
        self._saved = termios.tcgetattr(self._fd)
        try:
            tty.setraw(self._fd)
            self._write(_ENTER_ALT + _SHOW_CURSOR + _CLEAR)
        except BaseException:
            self._restore()

            raise

        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self._write(_RESET + _SHOW_CURSOR + _LEAVE_ALT)
        finally:
            self._restore()

    def size(self) -> Tuple[int, int]:
        cols, rows = shutil.get_terminal_size(fallback=(80, 24))

        return max(rows, 1), max(cols, 1)

    def draw(self, frame: Frame) -> None:
        parts = []
        for index, line in enumerate(frame.lines):
            spans = frame.styles[index] if index < len(frame.styles) else []
            background = _CURRENT_LINE if index == frame.highlight_row else ""
            parts.append(f"\x1b[{index + 1};1H{background}{apply_styles(line, spans)}\x1b[K{_RESET}")
        parts.append(f"\x1b[{len(frame.lines) + 1};1H\x1b[J")
        parts.append(f"\x1b[{frame.cursor_row + 1};{frame.cursor_col + 1}H")
        self._write("".join(parts))

    def read_key(self, timeout: float = 0.5) -> Optional[str]:
        deadline = time.monotonic() + timeout
        while True:
            if self._pending:
                key, consumed = parse_key(self._pending)
                if key is not None:
                    self._pending = self._pending[consumed:]
                    if key:
                        return key

                    continue
                wait = _SEQUENCE_WAIT
            else:
                wait = timeout

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self._flush()

            ready = select.select([self._fd], [], [], min(wait, remaining))[0]
            if not ready:
                return self._flush()

            chunk = os.read(self._fd, 1024)
            if not chunk:
                raise EditorError("Terminal input closed.")
            self._pending += chunk

    def _flush(self) -> Optional[str]:
        pending = self._pending
        self._pending = b""
        if pending == b"\x1b":
            return "escape"

        return None

    def _restore(self) -> None:
        saved = self._saved
        self._saved = None
        if saved is None:
            return

        try:
            import termios
        except ImportError:
            return

        try:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, saved)
        except (OSError, termios.error):
            pass

    def _write(self, text: str) -> None:
        self._stdout.write(text)
        self._stdout.flush()


def _isatty(stream: TextIO) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False
