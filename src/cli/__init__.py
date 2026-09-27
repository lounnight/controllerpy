"""The ``controllerpy`` command line interface.

An ``argparse`` front end that turns one of the commands below into a pipeline
run and its result into text on stdout, an exit code, or a clean error message.
It only ever calls the public facades - :func:`controllerpy.compile_file` for stage 1
to stage 3, :mod:`controllerpy.boards` for the target, :mod:`controllerpy.arduino` for the
toolchain - and never inspects a stage's internals.

    controllerpy init [--force]                    write the IDE configuration files
    controllerpy build main.py                     generate build/main.ino
    controllerpy check main.py                     parse and validate only
    controllerpy clean                             remove generated files
    controllerpy compile main.py --board uno       compile with arduino-cli
    controllerpy upload main.py --board uno --port /dev/ttyACM0
    controllerpy ports | boards | stubs

Where to change what:

* a new command, or a new flag on one -> :mod:`.parser`
* what a command does -> :mod:`.commands`
* what the CLI prints -> :mod:`.output`
* whether colour is allowed at all -> :mod:`.style`
* which failure is which exit code -> :mod:`.main`
* the numbers behind those exit codes -> :mod:`.exit_codes`
* the sketch naming and ``build/`` layout -> :mod:`.utils`
"""

from .exit_codes import (
    EXIT_CODES,
    EXIT_COMPILE_ERROR,
    EXIT_INTERRUPTED,
    EXIT_INTERNAL,
    EXIT_OK,
    EXIT_TOOLCHAIN,
    EXIT_USAGE,
)
from .main import main
from .parser import build_parser
from .utils import sketch_name

#: ``EXIT_OK`` & friends stay importable from here: they are part of the
#: documented exit-code contract (``controllerpy`` itself only uses ``EXIT_CODES``).
__all__ = ["EXIT_CODES", "build_parser", "main", "sketch_name"]
