"""Shared pytest fixtures for the micropy test-suite."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from typing import Callable, Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from micropy.compiler import compile_source  # noqa: E402  (after sys.path setup)
from micropy.errors import MicropyError  # noqa: E402

EXPECTED_DIR = Path(__file__).resolve().parent / "expected"


def clean(source: str) -> str:
    """Dedent a triple quoted test program."""

    return textwrap.dedent(source).lstrip("\n")


@pytest.fixture
def program() -> Callable[..., str]:
    """Compile a source string and return the generated C++."""

    def generate(source: str, **kwargs) -> str:
        filename = kwargs.pop("filename", "main.py")
        return compile_source(clean(source), filename=filename, **kwargs).cpp

    return generate


@pytest.fixture
def result() -> Callable[..., object]:
    """Compile a source string and return the whole CompileResult."""

    def compile_and_return(source: str, **kwargs):
        filename = kwargs.pop("filename", "main.py")
        return compile_source(clean(source), filename=filename, **kwargs)

    return compile_and_return


@pytest.fixture
def error() -> Callable[..., MicropyError]:
    """Assert that compiling a source string fails with a located error."""

    def expect(
        source: str,
        *,
        message: Optional[str] = None,
        hint: Optional[str] = None,
        line: Optional[int] = None,
        col: Optional[int] = None,
    ) -> MicropyError:
        try:
            compile_source(clean(source), filename="main.py")
        except MicropyError as exc:
            if message is not None:
                assert message in exc.message, exc.format()
            if hint is not None:
                assert hint in "\n".join([exc.hint or ""] + list(exc.hint_lines)), exc.format()
            if line is not None:
                assert exc.line == line, exc.format()
            if col is not None:
                assert exc.col == col, exc.format()
            return exc
        raise AssertionError(f"expected a MicropyError for:\n{clean(source)}")

    return expect


@pytest.fixture
def expected_cpp() -> Callable[[str], str]:
    """Load an expected C++ snapshot from tests/expected/."""

    def load(name: str) -> str:
        return (EXPECTED_DIR / f"{name}.cpp").read_text(encoding="utf-8")

    return load


@pytest.fixture
def fake_arduino_cli(tmp_path) -> Callable[..., Path]:
    """Create a fake arduino-cli that records its arguments."""

    def make(*, exit_code: int = 0, stdout: str = "", name: str = "arduino-cli") -> Path:
        script = tmp_path / name
        calls = tmp_path / "arduino-calls.txt"
        script.write_text(
            "#!/bin/sh\n"
            f'printf "%s\\n" "$*" >> "{calls}"\n'
            f"echo '{stdout}'\n"
            f"exit {exit_code}\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        return script

    return make


@pytest.fixture
def recorded_calls(tmp_path) -> Callable[[], list]:
    """Arguments the fake arduino-cli was called with."""

    def calls() -> list:
        path = tmp_path / "arduino-calls.txt"
        if not path.exists():
            return []
        return [line for line in path.read_text(encoding="utf-8").splitlines() if line]

    return calls
