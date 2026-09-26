"""How the CLI looks: everything ``micropy`` prints, in one vocabulary.

Handlers decide *what* happened; the ``report_*`` functions here decide how it
is rendered.  Messages that more than one command needs, or that need real
formatting (the board table, the "created files" list), live here; a one-off
message stays in its own handler.

All error output goes through :func:`report_error` as well, so a message can
never accidentally be written to stdout where a script would try to parse it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence, Union

from ..boards import Board

__all__ = [
    "report_board_table",
    "report_compiled",
    "report_conflicts",
    "report_error",
    "report_generated",
    "report_internal_error",
    "report_interrupted",
    "report_tool_output",
    "report_uploaded",
    "report_written_files",
]


# stdout
def report_generated(
    path: Union[str, Path],
    *,
    line_count: Optional[int] = None,
    summary: Optional[str] = None,
) -> None:
    """``build`` adds the size of the file, the toolchain commands do not."""

    if line_count is None:
        print(f"Generated {path}")
        return
    details = f", {summary}" if summary else ""
    print(f"Generated {path} ({line_count} lines{details})")


def report_compiled(sketch_dir: Path, board: Board) -> None:
    print(f"Compiled {sketch_dir} for {board.name} ({board.fqbn})")


def report_uploaded(sketch_dir: Path, port: str, board: Board) -> None:
    print(f"Uploaded {sketch_dir} to {port} ({board.name})")


def report_tool_output(text: str, verbose: bool) -> None:
    """Show what arduino-cli printed, but only when asked to."""

    if verbose and text.strip():
        print(text.strip())


def report_written_files(paths: Iterable[Path]) -> None:
    """The ``Created:`` block of ``micropy init``."""

    print()
    print("Created:")
    for path in paths:
        print(f"  ✓ {Path(path).name}")
    print()


def report_board_table(boards: Sequence[Board], planned: Dict[str, str], default_fqbn: str) -> None:
    """Two aligned columns: the boards that work, and the ones that do not."""

    print("Supported boards:")
    for board in boards:
        marker = " (default)" if board.fqbn == default_fqbn else ""
        print(f"  {board.alias:<6} {board.fqbn:<18} {board.name}{marker}")
    print("")
    print("Planned boards (not implemented yet):")
    for alias, fqbn in sorted(planned.items()):
        print(f"  {alias:<6} {fqbn}")


# stderr
def report_error(message: str) -> None:
    print(message, file=sys.stderr)


def report_conflicts(paths: Iterable[Path]) -> None:
    """Files ``micropy init`` refuses to overwrite without ``--force``."""

    for path in paths:
        report_error(f"{Path(path).name} already exists.")
        report_error("Use --force to overwrite it.")


def report_interrupted() -> None:
    report_error("micropy: interrupted")


def report_internal_error(exc: Exception) -> None:
    report_error(f"micropy: internal error: {type(exc).__name__}: {exc}")
    report_error("Please re-run with --debug and report this.")
