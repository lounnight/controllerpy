"""Commands that set a project up, or describe what it can target.

``init`` and ``stubs`` write the IDE/type-checker files, and they own the
templates they write so a new API name only has to be added to
``micropy.runtime.api``.  ``boards`` reports the board registry and needs no
compiler and no toolchain.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ...boards import DEFAULT_BOARD, PLANNED_BOARDS, supported_boards
from ..exit_codes import EXIT_OK, EXIT_USAGE
from ..output import report_board_table, report_conflicts, report_written_files
from ..utils import write_api_stub

__all__ = ["cmd_boards", "cmd_init", "cmd_stubs"]

STUB_NAME = "micropy_api.pyi"
PYRIGHT_CONFIG_NAME = "pyrightconfig.json"
BUILTINS_STUB_NAME = "main.py"

PYRIGHT_CONFIG_JSON = '{\n  "include": ["*.py"],\n  "extraPaths": ["."]\n}'

BUILTINS_STUB = (
    "# Write your arduino code here\n"
    "# Please don't clear the imports, for ide config\n"
    "from builtins import *\n"
    "from micropy_api import *\n"
)


def cmd_init(args: argparse.Namespace) -> int:
    """Write the IDE files, refusing to clobber a project that already has them."""

    stub = Path(STUB_NAME)
    config = Path(PYRIGHT_CONFIG_NAME)
    builtins_stub = Path(BUILTINS_STUB_NAME)
    conflicts = [path for path in (stub, config, builtins_stub) if path.exists()]
    if conflicts and not args.force:
        report_conflicts(conflicts)
        return EXIT_USAGE

    write_api_stub(stub)
    config.write_text(PYRIGHT_CONFIG_JSON, encoding="utf-8")
    builtins_stub.write_text(BUILTINS_STUB, encoding="utf-8")

    print("Initialized Micropy project.")
    report_written_files((stub, config))
    print("Your IDE is now configured for Micropy.")

    return EXIT_OK


def cmd_stubs(args: argparse.Namespace) -> int:
    target = Path(args.output)
    write_api_stub(target)
    print(f"Wrote {target}")
    print("Add 'from micropy_api import *' to your program for IDE autocompletion.")

    return EXIT_OK


def cmd_boards(args: argparse.Namespace) -> int:
    report_board_table(supported_boards(), PLANNED_BOARDS, DEFAULT_BOARD)

    return EXIT_OK
