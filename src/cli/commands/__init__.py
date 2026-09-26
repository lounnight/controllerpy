"""The command handlers.

Grouped by what a command needs, not one file per command:

* :mod:`.sketch` - ``build``, ``check``, ``clean``: the compiler only.
* :mod:`.toolchain` - ``compile``, ``upload``, ``ports``: arduino-cli.
* :mod:`.project` - ``init``, ``stubs``, ``boards``: IDE files and inventory.

A handler receives the parsed namespace, does one job, prints its result
through :mod:`..output` and returns an exit code from :mod:`..exit_codes`.  None
of them parses arguments or touches stage 1/2/3 internals.
"""

from .project import cmd_boards, cmd_init, cmd_stubs
from .sketch import cmd_build, cmd_check, cmd_clean
from .toolchain import cmd_compile, cmd_ports, cmd_upload

__all__ = [
    "cmd_boards",
    "cmd_build",
    "cmd_check",
    "cmd_clean",
    "cmd_compile",
    "cmd_init",
    "cmd_ports",
    "cmd_stubs",
    "cmd_upload",
]
