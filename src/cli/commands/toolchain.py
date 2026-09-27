"""Commands that drive the Arduino toolchain.

These are the only commands that need ``arduino-cli`` on the PATH.  They compile
the sketch first (through the same :func:`compile_file` the other commands use),
so a program controllerpy cannot generate is reported as a source error rather than
as a toolchain failure.

The division of labour with :mod:`controllerpy.arduino` is the point of this module:
``arduino.py`` runs a command and hands back what it ran and what it said, and
never decides how that looks.  Here each operation is announced with
``report_step`` before it happens, the command and the tool's own output are
handed to :mod:`..output` to be rendered, and the run ends on one success line
naming the sketch, the port and the board.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ...arduino import compile_sketch, find_arduino_cli, list_ports, upload_sketch, write_sketch
from ...boards import resolve_board
from ...compiler import compile_file
from ..exit_codes import EXIT_OK, EXIT_USAGE
from ..output import (
    report_compiled,
    report_error,
    report_port_listing,
    report_step,
    report_tool_command,
    report_tool_output,
    report_uploaded,
)
from ..utils import arduino_build_path, sketch_name, write_ino

__all__ = ["cmd_compile", "cmd_ports", "cmd_upload"]

_PORTS_HINT = "Run 'controllerpy ports' to list the boards connected to this computer."


def cmd_compile(args: argparse.Namespace) -> int:
    board = resolve_board(args.board)
    executable = find_arduino_cli(args.arduino_cli)
    report_step(f"Compiling {args.source} for {board.name}")

    result = compile_file(args.source, board=board)
    path = write_ino(args.output_dir, args.source, result)
    build_path = arduino_build_path(args.output_dir, args.source)
    target = write_sketch(args.output_dir, sketch_name(args.source), result.cpp)

    command = compile_sketch(
        target,
        board.fqbn,
        arduino_cli=executable,
        verbose=args.verbose,
        build_path=build_path,
    )
    report_tool_command(command.args, args.verbose)
    report_tool_output(command.stdout, args.verbose)

    report_compiled(target, path, board)

    return EXIT_OK


def cmd_upload(args: argparse.Namespace) -> int:
    if not args.port:
        report_error(
            "Upload needs a serial port: controllerpy upload main.py --board uno -p /dev/ttyACM0",
            hint=_PORTS_HINT,
        )
        return EXIT_USAGE
    if args.port.startswith("/") and not Path(args.port).exists():
        report_error(f"Serial port {args.port} does not exist.", hint=_PORTS_HINT)
        return EXIT_USAGE

    board = resolve_board(args.board)
    executable = find_arduino_cli(args.arduino_cli)

    report_step(f"Compiling {args.source} for {board.name}")
    result = compile_file(args.source, board=board)
    path = write_ino(args.output_dir, args.source, result)
    build_path = arduino_build_path(args.output_dir, args.source)
    target = write_sketch(args.output_dir, sketch_name(args.source), result.cpp)

    compiled = compile_sketch(
        target,
        board.fqbn,
        arduino_cli=executable,
        verbose=args.verbose,
        build_path=build_path,
    )
    report_tool_command(compiled.args, args.verbose)
    report_tool_output(compiled.stdout, args.verbose)

    report_step(f"Uploading to {args.port}")
    uploaded = upload_sketch(
        target,
        board.fqbn,
        args.port,
        arduino_cli=executable,
        verbose=args.verbose,
        build_path=build_path,
    )
    report_tool_command(uploaded.args, args.verbose)
    report_tool_output(uploaded.stdout, args.verbose)

    report_uploaded(target, path, args.port, board)

    return EXIT_OK


def cmd_ports(args: argparse.Namespace) -> int:
    executable = find_arduino_cli(args.arduino_cli)
    result = list_ports(arduino_cli=executable, verbose=args.verbose)
    report_tool_command(result.args, args.verbose)
    report_port_listing(result.stdout)

    return EXIT_OK
