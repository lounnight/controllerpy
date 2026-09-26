"""
Deprecated single-file prototype, kept for backwards compatibility.

Use the installed CLI instead:

    micropy build main.py
    python -m micropy build main.py

Running ``python compiler.py main.py`` still prints the generated C++ to
stdout, exactly like the first prototype did.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"

if importlib.util.find_spec("micropy") is None:
    # ``src/`` is the micropy package, so a checkout works without installing.
    spec = importlib.util.spec_from_file_location(
        "micropy", SRC / "__init__.py", submodule_search_locations=[str(SRC)]
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules["micropy"] = package
    spec.loader.exec_module(package)

from micropy import compile_source
from micropy.errors import MicropyError

USAGE = "usage: python compiler.py <file.py>"


def main(argv):
    if len(argv) != 2:
        print(USAGE, file=sys.stderr)
        return 2
    path = argv[1]
    print(f"compiler.py is deprecated: use 'micropy build {path}'", file=sys.stderr)
    try:
        result = compile_source(Path(path).read_text(encoding="utf-8"), filename=path)
    except MicropyError as error:
        print(error.format(), file=sys.stderr)
        return 1
    print(result.cpp, end="")
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
