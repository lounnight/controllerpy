"""Every command, argument and option ``micropy`` accepts.

This is the only module that talks to :mod:`argparse`, so changing what a
command takes - a new flag, a different default, better help text - is always a
one-file edit.  The handlers come from :mod:`.commands` and are attached with
``set_defaults(handler=...)``; :mod:`.main` looks for that attribute.
"""

from __future__ import annotations

import argparse
from typing import Callable

from .. import __version__
from ..boards import DEFAULT_BOARD
from .commands import (
    cmd_boards,
    cmd_build,
    cmd_check,
    cmd_clean,
    cmd_compile,
    cmd_init,
    cmd_ports,
    cmd_stubs,
    cmd_upload,
)

__all__ = ["DEFAULT_OUTPUT_DIR", "DEBUG_HELP", "PROG", "build_parser"]

PROG = "micropy"
DEFAULT_OUTPUT_DIR = "build"

DEBUG_HELP = "show internal tracebacks (for bug reports)"

Handler = Callable[[argparse.Namespace], int]
SubParsers = "argparse._SubParsersAction[argparse.ArgumentParser]"


def _shared_options() -> argparse.ArgumentParser:
    """The options every command accepts, wherever they are written.

    ``--debug`` is a global flag, so it has to work after the command name as
    well as before it (``micropy --debug build x.py`` *and* ``micropy build x.py
    --debug``).  argparse's answer to that is a parent parser: the option is
    defined once here and inherited by every subcommand, so it cannot drift
    between them.

    ``default=SUPPRESS`` is what makes inheriting it safe.  Since Python 3.13 a
    subcommand's defaults are copied onto the parent's namespace, so an ordinary
    ``store_true`` default here would write ``False`` over a ``--debug`` the
    user already passed to ``micropy``.  Suppressing the default means this
    parser only ever writes the flag when it is really there.
    """

    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--debug", action="store_true", default=argparse.SUPPRESS, help=DEBUG_HELP)

    return shared


def _add_command(subparsers: SubParsers, name: str, **kwargs) -> argparse.ArgumentParser:
    """Register a subcommand.  Every command goes through here, so every
    command accepts the shared options."""

    return subparsers.add_parser(name, parents=[_shared_options()], **kwargs)


def _add_source_command(
    subparsers: SubParsers,
    name: str,
    *,
    help_text: str,
    handler: Handler,
    board: bool = True,
    arduino_cli: bool = False,
    ) -> argparse.ArgumentParser:
    """Register a command that compiles ``source``: the common options, once."""

    parser = _add_command(subparsers, name, help=help_text)
    parser.add_argument("source", help="micropy program, e.g. main.py")
    parser.add_argument(
        "-o", "--output-dir", default=DEFAULT_OUTPUT_DIR, help=f"output directory (default: {DEFAULT_OUTPUT_DIR})"
    )
    if board:
        parser.add_argument(
            "-b", "--board", default=DEFAULT_BOARD, help=f"board FQBN or alias, e.g. uno (default: {DEFAULT_BOARD})"
        )
    if arduino_cli:
        parser.add_argument("--arduino-cli", metavar="PATH", default=None, help="path to the arduino-cli executable")
    parser.add_argument("-v", "--verbose", action="store_true", help="show details and arduino-cli commands")
    parser.set_defaults(handler=handler)

    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Compile Python-like programs for Arduino boards.",
        epilog="'build' and 'check' work without arduino-cli.",
    )
    parser.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    parser.add_argument("--debug", action="store_true", help=DEBUG_HELP)
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    init = _add_command(
        subparsers,
        "init",
        help="set up IDE support for this project (micropy_api.pyi + pyrightconfig.json)",
    )
    init.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="overwrite the generated IDE files if they already exist",
    )
    init.set_defaults(handler=cmd_init)

    _add_source_command(
        subparsers, "build", help_text="generate the Arduino sketch (no toolchain needed)", handler=cmd_build
    )
    _add_source_command(
        subparsers, "check", help_text="parse and validate without generating files", handler=cmd_check, board=False
    )
    clean = _add_command(subparsers, "clean", help="remove generated files")
    clean.add_argument(
        "-o", "--output-dir", default=DEFAULT_OUTPUT_DIR, help=f"output directory (default: {DEFAULT_OUTPUT_DIR})"
    )
    clean.set_defaults(handler=cmd_clean)
    _add_source_command(
        subparsers,
        "compile",
        help_text="generate and compile with arduino-cli",
        handler=cmd_compile,
        arduino_cli=True,
    )
    upload = _add_source_command(
        subparsers,
        "upload",
        help_text="generate, compile and upload with arduino-cli",
        handler=cmd_upload,
        arduino_cli=True,
    )
    upload.add_argument("-p", "--port", default=None, help="serial port, e.g. /dev/ttyACM0 or COM3")

    ports = _add_command(subparsers, "ports", help="list boards connected to this computer")
    ports.add_argument("--arduino-cli", metavar="PATH", default=None, help="path to the arduino-cli executable")
    ports.add_argument("-v", "--verbose", action="store_true")
    ports.set_defaults(handler=cmd_ports)

    boards = _add_command(subparsers, "boards", help="list supported boards")
    boards.set_defaults(handler=cmd_boards)

    stubs = _add_command(
        subparsers,
        "stubs",
        help="write the IDE stub (api.pyi) into your project (legacy; prefer 'init')",
    )

    stubs.add_argument("-o", "--output", default="micropy_api.pyi", help="where to write the stub")
    stubs.set_defaults(handler=cmd_stubs)

    return parser
