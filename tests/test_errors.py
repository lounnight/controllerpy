"""The error type and the exact layout the CLI prints."""

from __future__ import annotations

from controllerpy.errors import ArduinoCliError, ArduinoPyError, ControllerPyError


def test_error_layout_matches_the_documented_format():
    error = ControllerPyError(
        "Unknown ArduinoPy function: foo()",
        filename="main.py",
        line=8,
        col=5,
        hint="Supported Arduino functions include:",
        hint_lines=["digital_write()", "digital_read()", "pin_mode()"],
    )
    assert error.format() == (
        "ControllerPyError:\n"
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
    error = ControllerPyError("Missing required function: loop()")
    assert error.format() == "ControllerPyError:\n\n  Missing required function: loop()"


def test_location_falls_back_to_the_file_name():
    assert ControllerPyError("x", filename="main.py").location == "main.py"
    assert ControllerPyError("x", filename="main.py", line=3).location == "main.py:3"
    assert ControllerPyError("x").location is None


def test_str_uses_the_formatted_output():
    error = ControllerPyError("boom", filename="main.py", line=2, col=1)
    assert str(error) == error.format()
    assert "main.py:2:1" in str(error)


def test_arduino_cli_error_title_and_alias():
    assert ArduinoCliError("nope").title == "ArduinoCliError"
    assert "ArduinoCliError:" in ArduinoCliError("nope").format()
    assert ArduinoPyError is ControllerPyError


def test_controllerpy_error_is_an_exception_with_the_message():
    error = ControllerPyError("boom")
    assert isinstance(error, Exception)
    assert error.args == ("boom",)
