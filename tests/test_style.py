"""Colour: when it is allowed, and what the escapes look like.

The rule these tests protect is the one that keeps the CLI usable everywhere: a
line means the same thing whether or not it is painted, so colour is only ever
switched off - never required, never assumed.
"""

from __future__ import annotations

import io
import sys

import pytest

from micropy.cli import style


class Terminal(io.StringIO):
    """A stream that claims to be a terminal, for the tests that need one."""

    def isatty(self) -> bool:
        return True


class Pipe(io.StringIO):
    """A stream that is not a terminal, and says so."""

    def isatty(self) -> bool:
        return False


def test_a_redirected_stream_is_never_painted():
    """The common case: output into a file or a pipe has to stay readable."""

    assert style.supports_colour(Pipe()) is False
    assert style.paint("hello", "red", stream=Pipe()) == "hello"


def test_a_terminal_is_painted_with_the_code_and_a_reset():
    assert style.supports_colour(Terminal()) is True
    painted = style.paint("hello", "red", stream=Terminal())
    assert painted == "\033[31mhello\033[0m"
    # The reset is part of the contract: a line must not bleed into the next.
    assert painted.endswith("\033[0m")


@pytest.mark.parametrize(
    ("style_name", "code"),
    [
        ("bold", "1"),
        ("dim", "2"),
        ("red", "31"),
        ("green", "32"),
        ("yellow", "33"),
        ("blue", "34"),
        ("cyan", "36"),
    ],
)
def test_every_style_has_its_own_code(style_name, code):
    """No two styles share a code, and each is the one a terminal expects."""

    assert style_name in style.COLOURS
    assert style.paint("x", style_name, stream=Terminal()) == f"\033[{code}mx\033[0m"


def test_several_styles_combine_into_one_sequence():
    assert style.paint("x", "red", "bold", stream=Terminal()) == "\033[31;1mx\033[0m"


def test_an_unknown_style_is_ignored_rather_than_raising():
    """A typo in a status line should cost a colour, not the whole command."""

    assert style.paint("x", "chartreuse", stream=Terminal()) == "x"
    assert style.paint("x", "chartreuse", "red", stream=Terminal()) == "\033[31mx\033[0m"


def test_no_colour_asks_for_plain_text(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert style.supports_colour(Terminal()) is False
    assert style.paint("x", "green", stream=Terminal()) == "x"


def test_no_color_is_honoured_whatever_its_value(monkeypatch):
    """https://no-color.org: any non-empty value means "no colour"."""

    monkeypatch.setenv("NO_COLOR", "0")
    assert style.supports_colour(Terminal()) is False


def test_force_color_asks_for_colour_on_a_pipe(monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert style.supports_colour(Pipe()) is True


def test_no_color_outranks_force_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert style.supports_colour(Terminal()) is False


def test_a_dumb_terminal_is_treated_as_no_terminal(monkeypatch):
    monkeypatch.setenv("TERM", "dumb")
    assert style.supports_colour(Terminal()) is False


def test_the_stream_asked_about_is_the_one_that_decides(monkeypatch):
    """stdout and stderr are redirected independently, so they decide alone."""

    monkeypatch.setattr(sys, "stdout", Terminal())
    monkeypatch.setattr(sys, "stderr", Pipe())

    assert style.supports_colour() is True
    assert style.supports_colour(sys.stderr) is False


def test_a_stream_that_cannot_answer_counts_as_a_file():
    class NoIsatty:
        pass

    class Closed:
        def isatty(self) -> bool:
            raise ValueError("I/O operation on closed file")

    assert style.supports_colour(NoIsatty()) is False
    assert style.supports_colour(Closed()) is False


def test_painting_is_a_no_op_without_a_style():
    assert style.paint("hello", stream=Terminal()) == "hello"
