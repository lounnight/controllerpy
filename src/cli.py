"""
    Command line interface. hahahaha

    micropy init [--force]                    write the IDE configuration files ( احلف )
    micropy build main.py                     generate build/main.ino
    micropy check main.py                     parse and validate only
    micropy clean                             remove generated files
    micropy compile main.py --board uno       compile with arduino-cli
    micropy upload main.py --board uno --port /dev/ttyACM0
    micropy ports | boards | stubs
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
from typing import Callable, Optional, Sequence

from . import __version__
from .arduino import compile_sketch, find_arduino_cli, list_ports, upload_sketch, write_sketch
from .boards import DEFAULT_BOARD, PLANNED_BOARDS, resolve_board, supported_boards
from .compiler import CompileResult, compile_file
from .errors import ArduinoCliError, MicropyError
from .runtime import API_STUB

__all__ = ["main", "sketch_name", "EXIT_CODES"]

PROG = "micropy"
DEFAULT_OUTPUT_DIR = "build"

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

# Exit codes:) 
EXIT_OK = 0
EXIT_COMPILE_ERROR = 1
EXIT_USAGE = 2
EXIT_TOOLCHAIN = 3
EXIT_INTERNAL = 70

EXIT_CODES = {
    "ok": EXIT_OK,
    "source-error": EXIT_COMPILE_ERROR,
    "usage": EXIT_USAGE,
    "toolchain": EXIT_TOOLCHAIN,
    "internal": EXIT_INTERNAL,
}

_INVALID_SKETCH_CHARS = re.compile(r"[^A-Za-z0-9_]")

def sketch_name(source: str) -> str:
    stem = Path(source).stem or "sketch"
    name = _INVALID_SKETCH_CHARS.sub("_", stem)

    if not name:
        return "sketch"
    if name[0].isdigit():
        return f"sketch_{name}"
    
    return name


# commands
def _cmd_build(args: argparse.Namespace) -> int:
    result = compile_file(args.source, board=args.board)
    ino_path = _write_ino(args, result)
    details = f", {result.summary()}" if args.verbose else ""

    print(f"Generated {ino_path} ({result.line_count} lines{details})")

    return EXIT_OK


def _cmd_check(args: argparse.Namespace) -> int:
    result = compile_file(args.source)
    details = f" ({result.summary()})" if args.verbose else ""
    print(f"{args.source}: OK{details}")

    return EXIT_OK


def _cmd_clean(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)

    if not output_dir.exists():
        print(f"Nothing to clean ({output_dir} does not exist)")
        return EXIT_OK
    shutil.rmtree(output_dir)
    print(f"Removed {output_dir}")

    return EXIT_OK


def _cmd_compile(args: argparse.Namespace) -> int:
    board = resolve_board(args.board)
    executable = find_arduino_cli(args.arduino_cli)
    result = compile_file(args.source, board=board)
    ino_path = _write_ino(args, result)
    sketch_dir = write_sketch(args.output_dir, sketch_name(args.source), result.cpp)

    command = compile_sketch(
        sketch_dir,
        board.fqbn,
        arduino_cli=executable,
        verbose=args.verbose,
        build_path=_build_path(args),
    )
    _print_tool_output(command.stdout, args.verbose)
    print(f"Generated {ino_path}")
    print(f"Compiled {sketch_dir} for {board.name} ({board.fqbn})")

    return EXIT_OK


def _cmd_upload(args: argparse.Namespace) -> int:
    if not args.port:
        print("upload needs a serial port: micropy upload main.py --board uno -p /dev/ttyACM0", file=sys.stderr)
        print("Run 'micropy ports' to list the boards connected to this computer.", file=sys.stderr)
        return EXIT_USAGE
    if args.port.startswith("/") and not Path(args.port).exists():
        print(f"Serial port {args.port} does not exist.", file=sys.stderr)
        print("Run 'micropy ports' to list the boards connected to this computer.", file=sys.stderr)
        return EXIT_USAGE

    board = resolve_board(args.board)
    executable = find_arduino_cli(args.arduino_cli)
    result = compile_file(args.source, board=board)
    ino_path = _write_ino(args, result)
    sketch_dir = write_sketch(args.output_dir, sketch_name(args.source), result.cpp)
    build_path = _build_path(args)

    compiled = compile_sketch(
        sketch_dir, board.fqbn, arduino_cli=executable, verbose=args.verbose, build_path=build_path
    )
    _print_tool_output(compiled.stdout, args.verbose)
    uploaded = upload_sketch(
        sketch_dir,
        board.fqbn,
        args.port,
        arduino_cli=executable,
        verbose=args.verbose,
        build_path=build_path,
    )
    _print_tool_output(uploaded.stdout, args.verbose)

    print(f"Generated {ino_path}")
    print(f"Uploaded {sketch_dir} to {args.port} ({board.name})")

    return EXIT_OK


def _cmd_ports(args: argparse.Namespace) -> int:
    executable = find_arduino_cli(args.arduino_cli)
    result = list_ports(arduino_cli=executable, verbose=args.verbose)
    output = result.stdout.strip()

    print(output if output else "No boards found.")
    return EXIT_OK


def _cmd_boards(args: argparse.Namespace) -> int:
    print("Supported boards:")
    for board in supported_boards():
        marker = " (default)" if board.fqbn == DEFAULT_BOARD else ""
        print(f"  {board.alias:<6} {board.fqbn:<18} {board.name}{marker}")
    print("")
    print("Planned boards (not implemented yet):")
    for alias, fqbn in sorted(PLANNED_BOARDS.items()):
        print(f"  {alias:<6} {fqbn}")
    
    return EXIT_OK


def _cmd_init(args: argparse.Namespace) -> int:
    stub = Path(STUB_NAME)
    config = Path(PYRIGHT_CONFIG_NAME)
    builtins_stub = Path(BUILTINS_STUB_NAME)

    conflicts = [path for path in (stub, config, builtins_stub) if path.exists()]
    if conflicts and not args.force:
        for path in conflicts:
            print(f"{path.name} already exists.", file=sys.stderr)
            print("Use --force to overwrite it.", file=sys.stderr)
        return EXIT_USAGE

    _write_api_stub(stub)
    config.write_text(PYRIGHT_CONFIG_JSON, encoding="utf-8")
    builtins_stub.write_text(BUILTINS_STUB, encoding="utf-8")

    print("Initialized Micropy project.")
    print()
    print("Created:")
    print(f"  ✓ {stub.name}")
    print(f"  ✓ {config.name}")
    print()
    print("Your IDE is now configured for Micropy.")

    return EXIT_OK


def _cmd_stubs(args: argparse.Namespace) -> int:
    target = Path(args.output)
    _write_api_stub(target)
    print(f"Wrote {target}")
    print("Add 'from micropy_api import *' to your program for IDE autocompletion.")

    return EXIT_OK


# helpers
def _write_api_stub(target: Path) -> None:

    if target.parent != Path(""):
        target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(API_STUB, target)


def _write_ino(args: argparse.Namespace, result: CompileResult) -> Path:
    path = Path(args.output_dir) / f"{sketch_name(args.source)}.ino"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.cpp, encoding="utf-8")

    return path


def _build_path(args: argparse.Namespace) -> Path:
    return Path(args.output_dir) / "arduino" / sketch_name(args.source)


def _print_tool_output(text: str, verbose: bool) -> None:
    if verbose and text.strip():
        print(text.strip())


# parser
def _add_source_command(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
    name: str,
    *,
    help_text: str,
    handler: Callable[[argparse.Namespace], int],
    board: bool = True,
    arduino_cli: bool = False,
    ) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(name, help=help_text)
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
    parser.add_argument("--debug", action="store_true", help="show internal tracebacks (for bug reports)")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    init = subparsers.add_parser(
        "init",
        help="set up IDE support for this project (micropy_api.pyi + pyrightconfig.json)",
    )
    init.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="overwrite the generated IDE files if they already exist",
    )
    init.set_defaults(handler=_cmd_init)

    _add_source_command(
        subparsers, "build", help_text="generate the Arduino sketch (no toolchain needed)", handler=_cmd_build
    )
    _add_source_command(
        subparsers, "check", help_text="parse and validate without generating files", handler=_cmd_check, board=False
    )
    clean = subparsers.add_parser("clean", help="remove generated files")
    clean.add_argument(
        "-o", "--output-dir", default=DEFAULT_OUTPUT_DIR, help=f"output directory (default: {DEFAULT_OUTPUT_DIR})"
    )
    clean.set_defaults(handler=_cmd_clean)
    _add_source_command(
        subparsers,
        "compile",
        help_text="generate and compile with arduino-cli",
        handler=_cmd_compile,
        arduino_cli=True,
    )
    upload = _add_source_command(
        subparsers,
        "upload",
        help_text="generate, compile and upload with arduino-cli",
        handler=_cmd_upload,
        arduino_cli=True,
    )
    upload.add_argument("-p", "--port", default=None, help="serial port, e.g. /dev/ttyACM0 or COM3")

    ports = subparsers.add_parser("ports", help="list boards connected to this computer")
    ports.add_argument("--arduino-cli", metavar="PATH", default=None, help="path to the arduino-cli executable")
    ports.add_argument("-v", "--verbose", action="store_true")
    ports.set_defaults(handler=_cmd_ports)

    boards = subparsers.add_parser("boards", help="list supported boards")
    boards.set_defaults(handler=_cmd_boards)

    stubs = subparsers.add_parser(
        "stubs",
        help="write the IDE stub (api.pyi) into your project (legacy; prefer 'init')",
    )

    stubs.add_argument("-o", "--output", default="micropy_api.pyi", help="where to write the stub")
    stubs.set_defaults(handler=_cmd_stubs)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler: Callable[[argparse.Namespace], int] = args.handler
    try:
        return handler(args)
    except MicropyError as exc:
        if args.debug:
            raise
        print(exc.format(), file=sys.stderr)
        return EXIT_TOOLCHAIN if isinstance(exc, ArduinoCliError) else EXIT_COMPILE_ERROR
    except KeyboardInterrupt:  
        print("micropy: interrupted", file=sys.stderr)
        return 130
    except Exception as exc: 
        if args.debug:
            raise
        print(f"micropy: internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("Please re-run with --debug and report this.", file=sys.stderr)
        return EXIT_INTERNAL
