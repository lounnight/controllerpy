from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Tuple

from ..editor import Editor, EditorError, Terminal, TextBuffer, run_editor
from ..exit_codes import EXIT_OK, EXIT_USAGE
from ..output import report_error, report_success, report_warning

__all__ = ["cmd_edit"]

DiskVersion = Optional[Tuple[int, int]]


def cmd_edit(args: argparse.Namespace) -> int:
    path = Path(args.source)
    problem = _check_target(path)
    if problem is not None:
        report_error(problem)

        return EXIT_USAGE

    try:
        buffer, version = _load(path)
    except OSError as exc:
        report_error(f"Cannot read {path}: {exc.strerror or exc}")

        return EXIT_USAGE
    except UnicodeDecodeError:
        report_error(f"{path} is not valid UTF-8 text.", hint="The editor only opens UTF-8 files.")

        return EXIT_USAGE

    editor = Editor(path, buffer, disk_version=version)
    if version is None:
        editor.message = "[New File]"

    try:
        with Terminal() as terminal:
            run_editor(editor, terminal)
    except EditorError as exc:
        report_error(str(exc))

        return EXIT_USAGE

    report_success(f"Closed {path} ({editor.buffer.line_count} lines)")
    if editor.discarded:
        report_warning("Discarded unsaved changes")

    return EXIT_OK


def _check_target(path: Path) -> Optional[str]:
    if path.exists() and path.is_dir():
        return f"{path} is a directory, not a file."
    if not path.exists() and not path.parent.exists():
        return f"The directory {path.parent} does not exist."

    return None


def _load(path: Path) -> Tuple[TextBuffer, DiskVersion]:
    if not path.exists():
        return TextBuffer.empty(), None

    with open(path, "r", encoding="utf-8", newline="") as handle:
        text = handle.read()
    stat = path.stat()

    return TextBuffer.from_text(text), (stat.st_mtime_ns, stat.st_size)
