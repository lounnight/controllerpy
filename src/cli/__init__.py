"""The ``micropy`` command line interface.

An ``argparse`` front end that turns one of the commands below into a pipeline
run and its result into text on stdout, an exit code, or a clean error message.
It only ever calls the public facades - :func:`micropy.compile_file` for stage 1
to stage 3, :mod:`micropy.boards` for the target, :mod:`micropy.arduino` for the
toolchain - and never inspects a stage's internals.

    micropy init [--force]                    write the IDE configuration files
    micropy build main.py                     generate build/main.ino
    micropy check main.py                     parse and validate only
    micropy clean                             remove generated files
    micropy compile main.py --board uno       compile with arduino-cli
    micropy upload main.py --board uno --port /dev/ttyACM0
    micropy ports | boards | stubs

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
#: documented exit-code contract (``micropy`` itself only uses ``EXIT_CODES``).
__all__ = ["EXIT_CODES", "build_parser", "main", "sketch_name"]
