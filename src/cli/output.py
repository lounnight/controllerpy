"""How the CLI looks: every symbol, colour and line ``micropy`` prints.

Handlers decide *what* happened; the ``report_*`` functions here decide how it is
rendered.  The whole vocabulary rests on four ideas, so that a transcript reads
the same whichever command produced it:

* **A line starts with a status symbol.**  ``→`` is work in progress, ``✓`` is
  finished, ``!`` is suspicious, ``✗`` failed.  A reader can scan a long run and
  see what happened without reading a word of it, which is why the symbols stay
  sparse: one per line, and only where they say something.
* **The symbol carries the colour, the sentence stays readable without it.**
  Green for success, cyan for work in progress, yellow for a warning, red for a
  failure - see :mod:`.style` for when colour is allowed at all.  Because colour
  is only ever decoration, every line means the same thing in a pipe, in CI and
  on a terminal that understands nothing but ASCII.
* **Context sits under the line it belongs to.**  A path, a line count, a hint
  or a transcript is indented further and dimmed, which keeps the symbols in one
  column and makes the shape of a run visible at a glance.
* **A result with parts is a block, not a sentence.**  ``✓ Compile complete``
  says the job is done; the aligned ``Sketch``/``Board``/``Output`` rows under it
  say what it was done to, with the labels dimmed so the values are what the eye
  lands on.  A command with one fact to report does not get a block.

Advice is the one thing that gets a word rather than only a position: a line
under a failure is a hint far more often than it is a second message, so it says
``hint:`` and lets the reader decide whether to keep reading.

The first few ``report_*`` functions are the primitives every message is built
from; the ones after them are the vocabulary the commands speak, so a new command
composes existing pieces instead of inventing a look of its own.

Everything that goes to stderr goes through :func:`report_error` or one of its
neighbours, so a message can never accidentally be written to stdout where a
script would try to parse it.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence, Tuple, Union

from ..boards import Board
from ..errors import MicropyError
from .style import paint

__all__ = [
    "BOARD",
    "FAILURE",
    "OUTPUT",
    "PORT",
    "SKETCH",
    "STEP",
    "SUCCESS",
    "WARNING",
    "report_board_table",
    "report_built",
    "report_checked",
    "report_compiled",
    "report_conflicts",
    "report_detail",
    "report_error",
    "report_exception",
    "report_facts",
    "report_internal_error",
    "report_interrupted",
    "report_nothing_to_clean",
    "report_overwritten",
    "report_port_listing",
    "report_removed",
    "report_step",
    "report_success",
    "report_tool_command",
    "report_tool_output",
    "report_uploaded",
    "report_warning",
    "report_written_files",
]

STEP = "→"
SUCCESS = "✓"
WARNING = "!"
FAILURE = "✗"

SKETCH = "Sketch"
BOARD = "Board"
PORT = "Port"
OUTPUT = "Output"

_DEFINES = "Defines"

_STATUS = "  "
_DETAIL = "    "
_NESTED = "      "

_FACT_GAP = 2
_HINT_LABEL = "hint:"
_CREATED = "Created:"

_BOARD_HEADER = f"{'ALIAS':<6} {'FQBN':<18} NAME"
_PLANNED_HEADER = f"{'ALIAS':<6} FQBN"


# plumbing
def _out(text: str, *styles: str) -> str:
    return paint(text, *styles)


def _err(text: str, *styles: str) -> str:
    return paint(text, *styles, stream=sys.stderr)


def _stdout(line: str = "") -> None:
    print(line, flush=True)


def _failure(message: str) -> None:
    print(f"{_STATUS}{_err(FAILURE, 'red', 'bold')} {message}", file=sys.stderr, flush=True)


def _warn(message: str) -> None:
    print(f"{_STATUS}{_err(WARNING, 'yellow')} {message}", file=sys.stderr, flush=True)


def _hint(message: str) -> None:
    print(f"{_DETAIL}{_err(_HINT_LABEL, 'dim')} {_err(message, 'dim')}", file=sys.stderr, flush=True)


# primitives
def report_step(message: str) -> None:
    _stdout(f"{_STATUS}{_out(STEP, 'cyan')} {message}")


def report_success(message: str) -> None:
    _stdout(f"{_STATUS}{_out(SUCCESS, 'green')} {message}")


def report_detail(message: str) -> None:
    for line in message.splitlines() or [""]:
        _stdout(f"{_DETAIL}{_out(line, 'dim')}")


def report_facts(facts: Iterable[Tuple[str, str]]) -> None:
    rows = list(facts)
    if not rows:
        return

    width = max(len(label) for label, _ in rows) + _FACT_GAP
    _stdout()
    for label, value in rows:
        _stdout(f"{_DETAIL}{_out(label.ljust(width), 'dim')}{value}")


def report_warning(message: str, *, hint: Optional[str] = None) -> None:
    _warn(message)
    if hint:
        _hint(hint)


def report_error(message: str, *, hint: Optional[str] = None) -> None:
    _failure(message)
    if hint:
        _hint(hint)


# errors
def report_exception(exc: MicropyError) -> None:
    _failure(exc.title)
    print(file=sys.stderr)

    location = exc.location
    if location:
        print(f"{_STATUS}{_err(location, 'red', 'bold')}", file=sys.stderr)
    print(f"{_STATUS}{exc.message}", file=sys.stderr)

    if exc.hint:
        print(file=sys.stderr)
        _hint(exc.hint)
    for line in exc.hint_lines:
        print(f"{_NESTED}{line}".rstrip(), file=sys.stderr)


def report_conflicts(paths: Iterable[Path]) -> None:
    names = [Path(path).name for path in paths]
    for name in names:
        _failure(f"{name} already exists.")
    if names:
        _hint(f"Use --force to overwrite {_pronoun(len(names))}.")

def report_interrupted() -> None:
    report_error("Interrupted.")

def report_internal_error(exc: Exception) -> None:
    report_error(f"Internal error: {type(exc).__name__}: {exc}", hint="Please re-run with --debug and report this.")

# the sketch
def report_checked(source: str, summary: Optional[str] = None) -> None:
    details = f" ({_out(summary, 'dim')})" if summary else ""
    report_success(f"{source}: OK{details}")

def report_built(path: Union[str, Path], *, line_count: Optional[int] = None, summary: Optional[str] = None) -> None:
    facts = [(OUTPUT, f"{path}" + (f" ({line_count} lines)" if line_count is not None else ""))]
    if summary:
        facts.append((_DEFINES, summary))

    report_success("Build complete")
    report_facts(facts)

def report_compiled(sketch: Path, output: Union[str, Path], board: Board) -> None:
    report_success("Compile complete")
    report_facts(
        [
            (SKETCH, str(sketch)),
            (BOARD, f"{board.name} {_out(f'({board.fqbn})', 'dim')}"),
            (OUTPUT, str(output)),
        ]
    )

def report_uploaded(sketch: Path, output: Union[str, Path], port: str, board: Board) -> None:
    report_success("Upload complete")
    report_facts(
        [
            (SKETCH, str(sketch)),
            (BOARD, board.name),
            (PORT, _out(port, "bold")),
            (OUTPUT, str(output)),
        ]
    )

def report_removed(path: Path) -> None:
    report_success(f"Removed {path}")

def report_nothing_to_clean(path: Path) -> None:
    report_detail(f"Nothing to clean ({path} does not exist)")

# the project
def report_written_files(paths: Iterable[Path]) -> None:
    _stdout()
    _stdout(f"{_STATUS}{_out(_CREATED, 'bold')}")
    for path in paths:
        _stdout(f"{_DETAIL}{_out(Path(path).name)}")
    _stdout()


def report_overwritten(paths: Iterable[Path]) -> None:
    names = [Path(path).name for path in paths]
    if names:
        report_warning(f"Overwriting {_pronoun(len(names), 'existing file', 'existing files')}: {_list(names)}")


def report_board_table(boards: Sequence[Board], planned: Dict[str, str], default_fqbn: str) -> None:
    _stdout(f"{_STATUS}{_out('Supported boards', 'bold')}")
    _stdout(f"{_DETAIL}{_out(_BOARD_HEADER, 'dim')}")
    for board in boards:
        marker = f" {_out('(default)', 'dim')}" if board.fqbn == default_fqbn else ""
        _stdout(f"{_DETAIL}{board.alias:<6} {board.fqbn:<18} {board.name}{marker}")

    _stdout()
    _stdout(f"{_STATUS}{_out('Planned boards (not implemented yet)', 'bold')}")
    _stdout(f"{_DETAIL}{_out(_PLANNED_HEADER, 'dim')}")
    for alias, fqbn in sorted(planned.items()):
        _stdout(f"{_DETAIL}{alias:<6} {fqbn}")


# toolchain
def report_tool_command(args: Sequence[str], verbose: bool) -> None:
    if verbose:
        _stdout(_out("$ " + " ".join(args), "dim"))


def report_tool_output(text: str, verbose: bool) -> None:
    if not verbose:
        return
    for line in text.strip().splitlines():
        _stdout(f"{_DETAIL}{_out(line.rstrip(), 'dim')}")


def report_port_listing(text: str) -> None:
    listing = text.strip()
    if listing:
        _stdout(listing)
    else:
        report_detail("No boards found.")


# words
def _pronoun(count: int, singular: str = "it", plural: str = "them") -> str:
    return singular if count == 1 else plural


def _list(names: Sequence[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    
    return f"{', '.join(names[:-1])} and {names[-1]}"
