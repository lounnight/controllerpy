"""Helpers shared by more than one command.

Two things live here: the rule that turns a file name into a legal sketch name,
and the on-disk layout the CLI promises (``build/<name>.ino``, the sketch folder
for arduino-cli, the copied IDE stub).  Commands that need one of these call it
rather than rebuilding the path themselves.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Union

from ..compiler import CompileResult
from ..runtime import API_STUB

__all__ = [
    "arduino_build_path",
    "ino_path",
    "sketch_name",
    "write_api_stub",
    "write_ino",
]

_INVALID_SKETCH_CHARS = re.compile(r"[^A-Za-z0-9_]")


def sketch_name(source: str) -> str:
    """The Arduino sketch name for *source*: letters, digits and underscores only."""

    stem = Path(source).stem or "sketch"
    name = _INVALID_SKETCH_CHARS.sub("_", stem)

    if not name:
        return "sketch"
    if name[0].isdigit():
        return f"sketch_{name}"

    return name


def ino_path(output_dir: Union[str, Path], source: str) -> Path:
    """``build/main.ino`` - exactly the generated C++."""

    return Path(output_dir) / f"{sketch_name(source)}.ino"


def arduino_build_path(output_dir: Union[str, Path], source: str) -> Path:
    """``build/arduino/main/`` - where arduino-cli keeps its artifacts."""

    return Path(output_dir) / "arduino" / sketch_name(source)


def write_ino(output_dir: Union[str, Path], source: str, result: CompileResult) -> Path:
    path = ino_path(output_dir, source)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.cpp, encoding="utf-8")

    return path


def write_api_stub(target: Path) -> None:
    """Copy the bundled IDE stub to *target* (``init`` and ``stubs``)."""

    if target.parent != Path(""):
        target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(API_STUB, target)
