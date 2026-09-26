"""Commands that set a project up, or describe what it can target.

``init`` and ``stubs`` write the IDE/type-checker files, and they own the
templates they write so a new API name only has to be added to
``micropy.runtime.api``.  ``boards`` reports the board registry and needs no
compiler and no toolchain.

Both writers share the same promise: a file is only replaced when the user asked
for it.  ``init`` asks with ``--force``; ``stubs`` has no such flag, so replacing
a file it did not create is a warning rather than a surprise.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ...boards import DEFAULT_BOARD, PLANNED_BOARDS, supported_boards
from ..exit_codes import EXIT_OK, EXIT_USAGE
from ..output import (
    report_board_table,
    report_conflicts,
    report_detail,
    report_error,
    report_overwritten,
    report_success,
    report_written_files,
)
from ..utils import write_api_stub

__all__ = ["cmd_boards", "cmd_init", "cmd_stubs"]

STUB_NAME = "micropy_api.pyi"
PYRIGHT_CONFIG_NAME = "pyrightconfig.json"
BUILTINS_STUB_NAME = "main.py"

PYRIGHT_CONFIG_JSON = '{\n  "include": ["*.py"],\n  "extraPaths": ["."]\n}'

_STUB_TARGET_HINT = f"Pass a file name, for example: micropy stubs -o {STUB_NAME}"

_NEXT_STEPS = (
    (f"micropy check {BUILTINS_STUB_NAME}", "parse and validate, write nothing"),
    (f"micropy upload {BUILTINS_STUB_NAME} -p PORT", "compile it and flash it to a board"),
)

def _next_steps() -> str:
    width = max(len(command) for command, _ in _NEXT_STEPS)

    return "Your IDE is now configured for Micropy.\n" + "\n".join(
        f"  {command.ljust(width + 2)}{description}" for command, description in _NEXT_STEPS
    )

BUILTINS_STUB = (
    "# Write your arduino code here\n"
    "# Please don't clear the imports, for ide config\n"
    "from builtins import *\n"
    "from micropy_api import *\n"
)


def cmd_init(args: argparse.Namespace) -> int:
    stub = Path(STUB_NAME)
    config = Path(PYRIGHT_CONFIG_NAME)
    builtins_stub = Path(BUILTINS_STUB_NAME)
    conflicts = [path for path in (stub, config, builtins_stub) if path.exists()]
    if conflicts and not args.force:
        report_conflicts(conflicts)
        return EXIT_USAGE
    if conflicts:
        report_overwritten(conflicts)

    write_api_stub(stub)
    config.write_text(PYRIGHT_CONFIG_JSON, encoding="utf-8")
    builtins_stub.write_text(BUILTINS_STUB, encoding="utf-8")

    report_success("Initialized Micropy project")
    report_written_files((stub, config, builtins_stub))
    report_detail(_next_steps())

    return EXIT_OK


def cmd_stubs(args: argparse.Namespace) -> int:
    target = Path(args.output)
    if target.is_dir():
        report_error(f"{target} is a directory, not a stub file.", hint=_STUB_TARGET_HINT)
        return EXIT_USAGE
    if target.exists():
        report_overwritten((target,))

    write_api_stub(target)
    report_success(f"Wrote {target}")
    report_detail("Add 'from micropy_api import *' to your program for IDE autocompletion.")

    return EXIT_OK


def cmd_boards(args: argparse.Namespace) -> int:
    report_board_table(supported_boards(), PLANNED_BOARDS, DEFAULT_BOARD)

    return EXIT_OK
