"""Commands that need nothing but the compiler.

``build`` and ``check`` run the three stages and stop; ``clean`` only touches
the output directory.  None of them shells out to arduino-cli, which is what
makes them work on a machine that has never installed the Arduino toolchain.

Each one says what it is doing with ``report_step`` before it does it, so a slow
run explains itself, and ends on exactly one ``report_success``: a finished
command should be unmistakable in a log, however far down it appears.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from ...compiler import compile_file
from ..exit_codes import EXIT_OK
from ..output import (
    report_built,
    report_checked,
    report_nothing_to_clean,
    report_removed,
    report_step,
)
from ..utils import write_ino

__all__ = ["cmd_build", "cmd_check", "cmd_clean"]


def cmd_build(args: argparse.Namespace) -> int:
    report_step(f"Compiling {args.source}")

    result = compile_file(args.source, board=args.board)
    path = write_ino(args.output_dir, args.source, result)

    report_built(
        path,
        line_count=result.line_count,
        summary=result.summary() if args.verbose else None,
    )

    return EXIT_OK


def cmd_check(args: argparse.Namespace) -> int:
    result = compile_file(args.source)
    report_checked(args.source, result.summary() if args.verbose else None)

    return EXIT_OK


def cmd_clean(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)

    if not output_dir.exists():
        report_nothing_to_clean(output_dir)
        return EXIT_OK

    shutil.rmtree(output_dir)
    report_removed(output_dir)

    return EXIT_OK
