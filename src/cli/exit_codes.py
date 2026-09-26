"""The exit codes ``micropy`` returns, in one place.

Every command returns one of these, and so does :mod:`.main` when it converts an
exception into a result.  They are defined here rather than in ``main`` so the
commands and the entry point can both use them without importing each other.
"""

from __future__ import annotations

__all__ = [
    "EXIT_CODES",
    "EXIT_COMPILE_ERROR",
    "EXIT_INTERRUPTED",
    "EXIT_INTERNAL",
    "EXIT_OK",
    "EXIT_TOOLCHAIN",
    "EXIT_USAGE",
]

EXIT_OK = 0
EXIT_COMPILE_ERROR = 1
EXIT_USAGE = 2
EXIT_TOOLCHAIN = 3
EXIT_INTERNAL = 70
EXIT_INTERRUPTED = 130

#: Documented in the README: the name -> value mapping of the public contract.
EXIT_CODES = {
    "ok": EXIT_OK,
    "source-error": EXIT_COMPILE_ERROR,
    "usage": EXIT_USAGE,
    "toolchain": EXIT_TOOLCHAIN,
    "internal": EXIT_INTERNAL,
}
