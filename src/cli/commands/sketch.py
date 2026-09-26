"""Commands that need nothing but the compiler.

``build`` and ``check`` run the three stages and stop; ``clean`` only touches
the output directory.  None of them shells out to arduino-cli, which is what
makes them work on a machine that has never installed the Arduino toolchain.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from ...compiler import compile_file
from ..exit_codes import EXIT_OK
from ..output import report_generated
from ..utils import write_ino

__all__ = ["cmd_build", "cmd_check", "cmd_clean"]


def cmd_build(args: argparse.Namespace) -> int:
    result = compile_file(args.source, board=args.board)
    path = write_ino(args.output_dir, args.source, result)
    report_generated(
        path,
        line_count=result.line_count,
        summary=result.summary() if args.verbose else None,
    )

    return EXIT_OK


def cmd_check(args: argparse.Namespace) -> int:
    result = compile_file(args.source)
    details = f" ({result.summary()})" if args.verbose else ""
    print(f"{args.source}: OK{details}")

    return EXIT_OK


def cmd_clean(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)

    if not output_dir.exists():
        print(f"Nothing to clean ({output_dir} does not exist)")
        return EXIT_OK
    shutil.rmtree(output_dir)
    print(f"Removed {output_dir}")

    return EXIT_OK
