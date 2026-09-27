"""The arduino-cli integration layer (no hardware required)."""

from __future__ import annotations

import pytest

from controllerpy.arduino import (
    ENV_VAR,
    INSTALL_URL,
    compile_sketch,
    find_arduino_cli,
    list_ports,
    run,
    upload_sketch,
    write_sketch,
)
from controllerpy.cli import sketch_name
from controllerpy.errors import ArduinoCliError


# ------------------------------------------------------------------ discovery
def test_missing_arduino_cli_explains_how_to_install_it(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setenv("PATH", "")
    with pytest.raises(ArduinoCliError) as caught:
        find_arduino_cli()
    text = caught.value.format()
    assert "arduino-cli was not found." in text
    assert INSTALL_URL in text
    assert "core install arduino:avr" in text
    assert "build" in text and "check" in text


def test_explicit_path_is_found(fake_arduino_cli):
    script = fake_arduino_cli()
    assert find_arduino_cli(str(script)) == str(script)


def test_missing_explicit_path_is_reported(tmp_path):
    with pytest.raises(ArduinoCliError) as caught:
        find_arduino_cli(str(tmp_path / "nope"))
    assert "was not found at" in caught.value.message


def test_environment_variable_is_used(monkeypatch, fake_arduino_cli):
    script = fake_arduino_cli()
    monkeypatch.setenv(ENV_VAR, str(script))
    monkeypatch.setenv("PATH", "")
    # shutil.which() needs an executable on the PATH, so pass it explicitly instead
    assert find_arduino_cli(str(script)) == str(script)


def test_executable_is_taken_from_the_path(monkeypatch, fake_arduino_cli, tmp_path):
    script = fake_arduino_cli()
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert find_arduino_cli() == str(script)


# ----------------------------------------------------------------- sketching
def test_write_sketch_creates_a_matching_folder_and_file(tmp_path):
    sketch = write_sketch(tmp_path / "build", "main", "// code\n")
    assert sketch == tmp_path / "build" / "main"
    assert (sketch / "main.ino").read_text(encoding="utf-8") == "// code\n"


def test_write_sketch_overwrites_previous_output(tmp_path):
    write_sketch(tmp_path, "main", "old")
    write_sketch(tmp_path, "main", "new")
    assert (tmp_path / "main" / "main.ino").read_text(encoding="utf-8") == "new"


@pytest.mark.parametrize(
    "source, expected",
    [
        ("main.py", "main"),
        ("my-project.py", "my_project"),
        ("blink.sketch.py", "blink_sketch"),
        ("2fast.py", "sketch_2fast"),
        ("weird name!.py", "weird_name_"),
    ],
)
def test_sketch_name_is_arduino_safe(source, expected):
    assert sketch_name(source) == expected


# ---------------------------------------------------------------------- run
def test_run_reports_a_failing_command(monkeypatch, tmp_path):
    script = tmp_path / "arduino-cli"
    script.write_text("#!/bin/sh\necho 'boom' >&2\nexit 3\n", encoding="utf-8")
    script.chmod(0o755)
    with pytest.raises(ArduinoCliError) as caught:
        run(["compile", "--fqbn", "arduino:avr:uno", "sketch"], executable=str(script))
    text = caught.value.format()
    assert "exit code 3" in text
    assert "boom" in text


def test_run_returns_output_on_success(tmp_path):
    script = tmp_path / "arduino-cli"
    script.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    script.chmod(0o755)
    result = run(["version"], executable=str(script))
    assert result.ok
    assert result.stdout.strip() == "hi"


# ------------------------------------------------------------- toolchain api
def test_compile_sketch_arguments(fake_arduino_cli, recorded_calls, tmp_path):
    script = fake_arduino_cli()
    sketch = write_sketch(tmp_path, "main", "void setup() {}\n")
    compile_sketch(sketch, "arduino:avr:uno", arduino_cli=str(script), build_path=tmp_path / "arduino")
    assert recorded_calls() == [
        f"compile --fqbn arduino:avr:uno --build-path {tmp_path / 'arduino'} {sketch}"
    ]


def test_upload_sketch_arguments(fake_arduino_cli, recorded_calls, tmp_path):
    script = fake_arduino_cli()
    sketch = write_sketch(tmp_path, "main", "void setup() {}\n")
    upload_sketch(sketch, "arduino:avr:uno", "/dev/ttyACM0", arduino_cli=str(script))
    assert recorded_calls() == [
        f"upload --fqbn arduino:avr:uno --port /dev/ttyACM0 {sketch}"
    ]


def test_list_ports_uses_board_list(fake_arduino_cli, recorded_calls):
    script = fake_arduino_cli(stdout="Port Protocol Type Board")
    result = list_ports(arduino_cli=str(script))
    assert recorded_calls() == ["board list"]
    assert "Port" in result.stdout


def test_run_never_prints_the_command(fake_arduino_cli, capsys):
    """The toolchain layer executes; it does not decide how the CLI looks.

    ``$ command`` is the CLI's to print (cli.output.report_tool_command), which
    is why run() stays silent even in verbose mode.
    """

    script = fake_arduino_cli()
    result = run(["version"], executable=str(script), verbose=True)

    assert capsys.readouterr().out == ""
    assert result.args == [str(script), "version"]
