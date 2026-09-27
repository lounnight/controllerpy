"""Every command, argument and option ``controllerpy`` accepts.

This is the only module that talks to :mod:`argparse`, so changing what a
command takes - a new flag, a different default, better help text - is always a
one-file edit.  The handlers come from :mod:`.commands` and are attached with
``set_defaults(handler=...)``; :mod:`.main` looks for that attribute.

The help text is written for someone who has never run the command: every
subcommand says what it does in one line, and the ones that take a program end
with a runnable example.  ``RawDescriptionHelpFormatter`` is what lets those
examples keep their own line breaks - the default formatter would reflow them
into a paragraph and the commands would stop being copy-pasteable.
"""

from __future__ import annotations

import argparse
import inspect
from typing import Any, Callable, Dict, TypeAlias

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
from .commands.project import STUB_NAME
from .style import paint, supports_colour

__all__ = ["DEFAULT_OUTPUT_DIR", "DEBUG_HELP", "PROG", "build_parser"]

PROG = "controllerpy"
DEFAULT_OUTPUT_DIR = "build"

DEBUG_HELP = "show internal tracebacks (for bug reports)"
VERBOSE_HELP = "show details and the arduino-cli commands"

DESCRIPTION = "Write Arduino programs in a Python-like subset, and turn them into C++."

_EPILOG = """\
examples:
  controllerpy init                     set up IDE support here
  controllerpy check main.py            parse and validate, write nothing
  controllerpy build main.py            generate build/main.ino
  controllerpy compile main.py -b uno   generate the sketch and compile it
  controllerpy upload main.py -p PORT   compile it and flash it to a board
  controllerpy boards                   list the boards that can be targeted
  controllerpy ports                    list the boards connected to this computer

'build' and 'check' work without arduino-cli.  Run 'controllerpy COMMAND --help'
for one command's own options.
"""

Handler = Callable[[argparse.Namespace], int]
SubParsers: TypeAlias = "argparse._SubParsersAction[argparse.ArgumentParser]"

_HAS_COLOUR_KEYWORD = "color" in inspect.signature(argparse.ArgumentParser).parameters


def _colour_kwargs() -> Any:
    if not _HAS_COLOUR_KEYWORD:
        return {}

    return {"color": supports_colour()}


class _RootParser(argparse.ArgumentParser):
    banner = ""

    def format_help(self) -> str:
        return self.banner + super().format_help()


def _brand() -> str:
    return f"  {paint('ControllerPy', 'cyan', 'bold')} {paint(__version__, 'dim')}\n  {DESCRIPTION}\n\n"

_EPILOGS: Dict[str, str] = {
    "init": "examples:\n"
    "  controllerpy init              write controllerpy_api.pyi and pyrightconfig.json\n"
    "  controllerpy init --force      rewrite them, overwriting what is already there",
    "build": "examples:\n"
    "  controllerpy build main.py\n"
    "  controllerpy build main.py -o out -v  write to out/, and say what it contains",
    "check": "examples:\n"
    "  controllerpy check main.py\n"
    "  controllerpy check main.py -v  also say what the program contains",
    "clean": "examples:\n  controllerpy clean\n  controllerpy clean -o out",
    "compile": "examples:\n"
    "  controllerpy compile main.py\n"
    "  controllerpy compile main.py -b uno -v",
    "upload": "examples:\n"
    "  controllerpy upload main.py -p /dev/ttyACM0\n"
    "  controllerpy upload main.py -b uno -p COM3",
    "ports": "examples:\n  controllerpy ports\n  controllerpy ports -v",
    "stubs": "examples:\n" f"  controllerpy stubs\n  controllerpy stubs -o {STUB_NAME}",
}

def _shared_options() -> argparse.ArgumentParser:
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--debug", action="store_true", default=argparse.SUPPRESS, help=DEBUG_HELP)

    return shared


def _add_command(subparsers: SubParsers, name: str, **kwargs) -> argparse.ArgumentParser:
    kwargs.setdefault("formatter_class", argparse.RawDescriptionHelpFormatter)
    kwargs.setdefault("epilog", _EPILOGS.get(name))
    kwargs.update(_colour_kwargs())

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
    parser = _add_command(subparsers, name, help=help_text)
    parser.add_argument("source", help="controllerpy program, e.g. main.py")
    parser.add_argument(
        "-o", "--output-dir", default=DEFAULT_OUTPUT_DIR, help=f"output directory (default: {DEFAULT_OUTPUT_DIR})"
    )
    if board:
        parser.add_argument(
            "-b", "--board", default=DEFAULT_BOARD, help=f"board FQBN or alias, e.g. uno (default: {DEFAULT_BOARD})"
        )
    if arduino_cli:
        parser.add_argument("--arduino-cli", metavar="PATH", default=None, help="path to the arduino-cli executable")
    parser.add_argument("-v", "--verbose", action="store_true", help=VERBOSE_HELP)
    parser.set_defaults(handler=handler)

    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = _RootParser(
        prog=PROG,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        **_colour_kwargs(),
    )
    parser.banner = _brand()
    parser.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    parser.add_argument("--debug", action="store_true", help=DEBUG_HELP)
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        title="Commands",
        parser_class=argparse.ArgumentParser,
    )

    init = _add_command(
        subparsers,
        "init",
        help="set up IDE support for this project",
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
    ports.add_argument("-v", "--verbose", action="store_true", help=VERBOSE_HELP)
    ports.set_defaults(handler=cmd_ports)

    boards = _add_command(subparsers, "boards", help="list supported boards")
    boards.set_defaults(handler=cmd_boards)

    stubs = _add_command(
        subparsers,
        "stubs",
        help=f"write the IDE stub ({STUB_NAME}) into your project (legacy; prefer 'init')",
    )

    stubs.add_argument(
        "-o",
        "--output-file",
        "--output",
        dest="output",
        default=STUB_NAME,
        help=f"stub file to write (default: {STUB_NAME})",
    )
    stubs.set_defaults(handler=cmd_stubs)

    return parser
