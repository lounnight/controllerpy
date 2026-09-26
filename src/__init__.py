"""micropy - write Arduino programs in a Python-like subset.

Example::

    from micropy import compile_source

    result = compile_source("def main():\n    pin_mode(13, OUTPUT)\n\ndef loop():\n    pass\n")
    print(result.cpp)
"""

from .boards import DEFAULT_BOARD, Board, resolve_board, supported_boards
from .compiler import CompileResult, Compiler, compile_file, compile_source
from .errors import ArduinoCliError, ArduinoPyError, MicropyError

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_BOARD",
    "ArduinoCliError",
    "ArduinoPyError",
    "Board",
    "CompileResult",
    "Compiler",
    "MicropyError",
    "compile_file",
    "compile_source",
    "resolve_board",
    "supported_boards",
    "__version__",
]
