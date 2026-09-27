"""The ``controllerpy`` entry point.

    controllerpy init [--force]                    write the IDE configuration files
    controllerpy build main.py                     generate build/main.ino
    controllerpy check main.py                     parse and validate only
    controllerpy clean                             remove generated files
    controllerpy compile main.py --board uno       compile with arduino-cli
    controllerpy upload main.py --board uno --port /dev/ttyACM0
    controllerpy ports | boards | stubs

:func:`main` does three things and nothing else: parse the arguments, run the
command the parser selected, and turn whatever comes back into an exit code.  It
is the single place that decides which failure is the user's fault and which is
ours, so those rules can only ever change here.
"""

from __future__ import annotations

import argparse
from typing import Callable, Optional, Sequence

from ..errors import ArduinoCliError, ControllerPyError
from .exit_codes import EXIT_COMPILE_ERROR, EXIT_INTERRUPTED, EXIT_INTERNAL, EXIT_TOOLCHAIN
from .output import report_exception, report_internal_error, report_interrupted
from .parser import build_parser

__all__ = ["main"]

Handler = Callable[[argparse.Namespace], int]


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    handler: Handler = args.handler
    try:
        return handler(args)
    except ControllerPyError as exc:
        if args.debug:
            raise
        report_exception(exc)
        return EXIT_TOOLCHAIN if isinstance(exc, ArduinoCliError) else EXIT_COMPILE_ERROR
    except KeyboardInterrupt:
        report_interrupted()
        return EXIT_INTERRUPTED
    except Exception as exc:
        if args.debug:
            raise
        report_internal_error(exc)
        return EXIT_INTERNAL
