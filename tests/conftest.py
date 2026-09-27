"""Shared pytest fixtures for the controllerpy test-suite."""

from __future__ import annotations

import importlib.util
import io
import sys
import textwrap
from pathlib import Path
from typing import Callable, Optional, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


class _Terminal(io.StringIO):
    """A stream that claims to be a terminal, for the tests that need one."""

    def isatty(self) -> bool:
        return True


def _load_source_package() -> None:
    """Make ``src/`` importable as ``controllerpy`` so the suite runs without installing."""

    if importlib.util.find_spec("controllerpy") is not None:
        return
    spec = importlib.util.spec_from_file_location(
        "controllerpy", SRC / "__init__.py", submodule_search_locations=[str(SRC)]
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["controllerpy"] = module
    spec.loader.exec_module(module)


_load_source_package()

from controllerpy.compiler import (
    compile_source,  # noqa: E402  (after the sys.path setup)
)
from controllerpy.errors import ControllerPyError  # noqa: E402

EXPECTED_DIR = Path(__file__).resolve().parent / "expected"


@pytest.fixture(autouse=True)
def plain_colour_environment(monkeypatch) -> None:
    """Start every test from a known colour environment.

    ``NO_COLOR``, ``FORCE_COLOR`` and ``TERM`` are the user's shell, not the
    code's, and a developer who exports any of them would otherwise see a
    different suite from CI.  Tests that care about colour set them back
    themselves; this only removes what is already there.
    """

    for name in ("NO_COLOR", "FORCE_COLOR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("TERM", raising=False)


@pytest.fixture
def terminal(monkeypatch) -> Callable[[], Tuple[io.StringIO, io.StringIO]]:
    """Swap in a stdout and stderr that look like a terminal, and keep them.

    This returns a callable that has to be *called inside the test body* rather
    than doing the patching in the fixture itself: pytest restores ``sys.stdout``
    when it suspends its own capture for the call phase, which would undo a
    fixture's patch before the command under test ever ran.
    """

    def install() -> Tuple[io.StringIO, io.StringIO]:
        out, err = _Terminal(), _Terminal()
        monkeypatch.setattr(sys, "stdout", out)
        monkeypatch.setattr(sys, "stderr", err)

        return out, err

    return install


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
def error() -> Callable[..., ControllerPyError]:
    """Assert that compiling a source string fails with a located error."""

    def expect(
        source: str,
        *,
        message: Optional[str] = None,
        hint: Optional[str] = None,
        line: Optional[int] = None,
        col: Optional[int] = None,
    ) -> ControllerPyError:
        try:
            compile_source(clean(source), filename="main.py")
        except ControllerPyError as exc:
            if message is not None:
                assert message in exc.message, exc.format()
            if hint is not None:
                assert hint in "\n".join([exc.hint or ""] + list(exc.hint_lines)), exc.format()
            if line is not None:
                assert exc.line == line, exc.format()
            if col is not None:
                assert exc.col == col, exc.format()
            return exc
        raise AssertionError(f"expected a ControllerPyError for:\n{clean(source)}")

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
