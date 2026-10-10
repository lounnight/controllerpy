from __future__ import annotations

import os
import select
import shutil
import sys
import time
from typing import Optional, TextIO, Tuple

from .keys import parse_key
from .render import Frame

__all__ = ["EditorError", "Terminal"]

_ENTER_ALT = "\x1b[?1049h"
_LEAVE_ALT = "\x1b[?1049l"
_HIDE_CURSOR = "\x1b[?25l"
_SHOW_CURSOR = "\x1b[?25h"
_RESET = "\x1b[0m"
_CLEAR = "\x1b[2J\x1b[H"

_SEQUENCE_WAIT = 0.1


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
            self._write(_ENTER_ALT + _HIDE_CURSOR + _CLEAR)
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
            parts.append(f"\x1b[{index + 1};1H{line}\x1b[K")
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
