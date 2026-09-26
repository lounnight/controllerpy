"""The error type and the exact layout the CLI prints."""

from __future__ import annotations

from micropy.errors import ArduinoCliError, ArduinoPyError, MicropyError


def test_error_layout_matches_the_documented_format():
    error = MicropyError(
        "Unknown ArduinoPy function: foo()",
        filename="main.py",
        line=8,
        col=5,
        hint="Supported Arduino functions include:",
        hint_lines=["digital_write()", "digital_read()", "pin_mode()"],
    )
    assert error.format() == (
        "MicropyError:\n"
        "\n"
        "  main.py:8:5\n"
        "\n"
        "  Unknown ArduinoPy function: foo()\n"
        "\n"
        "  Supported Arduino functions include:\n"
        "    digital_write()\n"
        "    digital_read()\n"
        "    pin_mode()"
    )


def test_error_without_location_still_prints_a_message():
    error = MicropyError("Missing required function: loop()")
    assert error.format() == "MicropyError:\n\n  Missing required function: loop()"


def test_location_falls_back_to_the_file_name():
    assert MicropyError("x", filename="main.py").location == "main.py"
    assert MicropyError("x", filename="main.py", line=3).location == "main.py:3"
    assert MicropyError("x").location is None


def test_str_uses_the_formatted_output():
    error = MicropyError("boom", filename="main.py", line=2, col=1)
    assert str(error) == error.format()
    assert "main.py:2:1" in str(error)


def test_arduino_cli_error_title_and_alias():
    assert ArduinoCliError("nope").title == "ArduinoCliError"
    assert "ArduinoCliError:" in ArduinoCliError("nope").format()
    assert ArduinoPyError is MicropyError


def test_micropy_error_is_an_exception_with_the_message():
    error = MicropyError("boom")
    assert isinstance(error, Exception)
    assert error.args == ("boom",)
