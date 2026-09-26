"""The command line interface: build, check, clean, compile, upload, ..."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from micropy import __version__
from micropy.arduino import ENV_VAR, INSTALL_URL
from micropy.cli import (
    EXIT_COMPILE_ERROR,
    EXIT_INTERNAL,
    EXIT_OK,
    EXIT_TOOLCHAIN,
    EXIT_USAGE,
    build_parser,
    main,
    output,
)
from micropy.cli.commands import toolchain
from micropy.compiler.validator import API_FUNCTIONS
from micropy.errors import MicropyError
from micropy.runtime import API_STUB

PROGRAM = 'LED = 13\n\ndef main():\n    pin_mode(LED, OUTPUT)\n\ndef loop():\n    digital_write(LED, HIGH)\n    delay(1000)\n'


@pytest.fixture
def source(tmp_path) -> Path:
    path = tmp_path / "main.py"
    path.write_text(PROGRAM, encoding="utf-8")
    return path


@pytest.fixture
def cli_help(capsys):
    """The --help text of one command."""

    def show(command: str) -> str:
        with pytest.raises(SystemExit):
            main([command, "--help"])
        return capsys.readouterr().out

    return show


@pytest.fixture
def no_arduino_cli(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setenv("PATH", "")


@pytest.fixture
def reported_tool_commands(monkeypatch):
    """Every ``(command, verbose)`` pair the CLI handed cli/output.py to print.

    The recorder replaces ``cli.output.report_tool_command`` and still prints
    through it, so the captured stdout stays exactly what a user would see and
    the "printed once" assertions keep their meaning.
    """

    seen = []
    render = output.report_tool_command

    def record(args, verbose):
        seen.append((list(args), verbose))
        render(args, verbose)

    monkeypatch.setattr(toolchain, "report_tool_command", record)
    return seen


# ------------------------------------------------------------------ the stub
def _annotation(node: ast.expr) -> str:
    return ast.unparse(node)


def _signature(node: ast.FunctionDef) -> str:
    """``(pin: int, mode: int) -> None`` - the parameters and return type only.

    The body is left out on purpose: a docstring is documentation, not part of
    the signature the type-checker sees.
    """

    args = list(node.args.args)
    defaults = list(node.args.defaults)
    undecided = len(args) - len(defaults)
    parts = []
    for index, arg in enumerate(args):
        text = arg.arg
        if arg.annotation is not None:
            text += f": {_annotation(arg.annotation)}"
        if index >= undecided:
            default = ast.unparse(defaults[index - undecided])
            text += f" = {default}" if arg.annotation is not None else f"={default}"
        parts.append(text)
    returns = f" -> {_annotation(node.returns)}" if node.returns is not None else ""

    return f"({', '.join(parts)}){returns}"


class StubAPI:
    """The API a ``.pyi`` publishes, read by parsing it rather than by matching.

    ``micropy init`` and ``micropy stubs`` copy the bundled stub verbatim, so
    the contract these tests care about is the one that file *declares* - which
    names exist, what they take, what they return.  Parsing states that
    directly and leaves the layout free: adding a docstring to a function, or
    reflowing the file, does not invalidate any assertion, and a name that only
    appears in a comment no longer counts as present.
    """

    def __init__(self, source: str) -> None:
        tree = ast.parse(source)
        self.functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
        self.constants = {
            node.target.id: _annotation(node.annotation)
            for node in tree.body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }

    def signature(self, name: str) -> str:
        """The signature of a module-level function."""
        return _signature(self.functions[name])

    def methods(self, class_name: str) -> dict[str, str]:
        """``{name: signature}`` for the methods of one declared class."""
        return {
            node.name: _signature(node)
            for node in self.classes[class_name].body
            if isinstance(node, ast.FunctionDef)
        }


# --------------------------------------------------------------------- build
def test_build_writes_build_main_ino(source, tmp_path, capsys):
    assert main(["build", str(source), "-o", str(tmp_path / "build")]) == EXIT_OK
    generated = tmp_path / "build" / "main.ino"
    assert generated.exists()
    assert "#include <Arduino.h>" not in generated.read_text(encoding="utf-8")
    assert generated.read_text(encoding="utf-8").startswith("const int LED = 13;\n")
    assert "const int LED = 13;" in generated.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert output.STEP in out and "Compiling" in out
    assert output.SUCCESS in out and "Build complete" in out
    # The file that was written is named, with its size.
    assert str(generated) in out
    assert "lines" in out


def test_build_uses_the_default_output_directory(source, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["build", str(source)]) == EXIT_OK
    assert (tmp_path / "build" / "main.ino").exists()


def test_build_verbose_adds_a_summary(tmp_path, capsys):
    helper = tmp_path / "prog.py"
    helper.write_text(
        "LED = 13\n\ndef toggle(pin):\n    digital_write(pin, HIGH)\n\ndef main():\n    toggle(LED)\n\ndef loop():\n    pass\n",
        encoding="utf-8",
    )
    main(["build", str(helper), "-o", str(tmp_path / "build"), "-v"])
    out = capsys.readouterr().out
    assert "1 global" in out
    assert "1 function" in out


def test_build_reports_source_errors_without_a_traceback(tmp_path, capsys):
    broken = tmp_path / "broken.py"
    broken.write_text("def main():\n    pass\n", encoding="utf-8")
    assert main(["build", str(broken), "-o", str(tmp_path / "build")]) == EXIT_COMPILE_ERROR
    captured = capsys.readouterr()
    err = captured.err
    assert err.startswith(f"  {output.FAILURE} MicropyError")
    assert "Missing required function: loop()" in err
    assert "Traceback" not in err
    assert not (tmp_path / "build").exists()


def test_build_reports_syntax_errors_with_a_location(tmp_path, capsys):
    broken = tmp_path / "broken.py"
    broken.write_text("def main(:\n", encoding="utf-8")
    assert main(["build", str(broken), "-o", str(tmp_path / "build")]) == EXIT_COMPILE_ERROR
    err = capsys.readouterr().err
    assert "broken.py:1" in err
    # The location gets a line of its own, so it can be spotted without
    # reading the rest of the block.
    location = next(line for line in err.splitlines() if "broken.py:1" in line)
    assert location.strip() == f"{broken}:1:10"


def test_build_missing_file(tmp_path, capsys):
    assert main(["build", str(tmp_path / "nope.py")]) == EXIT_COMPILE_ERROR
    assert "Source file not found" in capsys.readouterr().err


# --------------------------------------------------------------------- check
def test_check_succeeds_and_writes_nothing(source, tmp_path, capsys):
    assert main(["check", str(source), "-o", str(tmp_path / "build")]) == EXIT_OK
    assert "OK" in capsys.readouterr().out
    assert not (tmp_path / "build").exists()


def test_check_verbose_reports_a_summary(source, capsys):
    main(["check", str(source), "-v"])
    assert "1 global" in capsys.readouterr().out


def test_check_never_needs_arduino_cli(source, no_arduino_cli, capsys):
    assert main(["check", str(source)]) == EXIT_OK


# --------------------------------------------------------------------- clean
def test_clean_removes_the_output_directory(source, tmp_path, capsys):
    build = tmp_path / "build"
    main(["build", str(source), "-o", str(build)])
    assert main(["clean", "-o", str(build)]) == EXIT_OK
    assert not build.exists()
    assert "Removed" in capsys.readouterr().out


def test_clean_without_output_is_friendly(tmp_path, capsys):
    assert main(["clean", "-o", str(tmp_path / "nothing")]) == EXIT_OK
    assert "Nothing to clean" in capsys.readouterr().out


# ------------------------------------------------------------------- compile
def test_compile_without_arduino_cli_explains_the_install(source, no_arduino_cli, capsys):
    assert main(["compile", str(source), "--board", "uno"]) == EXIT_TOOLCHAIN
    err = capsys.readouterr().err
    assert err.startswith(f"  {output.FAILURE} ArduinoCliError")
    assert INSTALL_URL in err


def test_compile_invokes_arduino_cli(source, tmp_path, fake_arduino_cli, recorded_calls, capsys):
    script = fake_arduino_cli()
    build = tmp_path / "build"
    code = main(["compile", str(source), "--board", "uno", "-o", str(build), "--arduino-cli", str(script)])
    assert code == EXIT_OK
    assert (build / "main.ino").exists()
    assert (build / "main" / "main.ino").read_text(encoding="utf-8") == (build / "main.ino").read_text(encoding="utf-8")
    calls = recorded_calls()
    assert len(calls) == 1
    assert calls[0].startswith("compile --fqbn arduino:avr:uno")
    assert str(build / "main") in calls[0]
    out = capsys.readouterr().out
    assert f"  {output.SUCCESS} Compile complete" in out
    assert "Arduino Uno" in _fact_row(out, output.BOARD)


def test_compile_reports_a_failing_toolchain(source, tmp_path, fake_arduino_cli, capsys):
    script = fake_arduino_cli(exit_code=1, stdout="error: no such core")
    code = main(["compile", str(source), "--arduino-cli", str(script)])
    assert code == EXIT_TOOLCHAIN
    assert "no such core" in capsys.readouterr().err


def test_compile_verbose_echoes_the_command_through_output(
    source, tmp_path, fake_arduino_cli, recorded_calls, reported_tool_commands, capsys
):
    script = fake_arduino_cli()
    build = tmp_path / "build"

    code = main(["compile", str(source), "-o", str(build), "-v", "--arduino-cli", str(script)])

    assert code == EXIT_OK
    # cli/output.py rendered it, once, for the one toolchain call that ran.
    assert len(reported_tool_commands) == 1
    ((command, verbose),) = reported_tool_commands
    assert verbose is True
    # It is the command arduino-cli actually received, not a second rendering.
    assert command[0] == str(script)
    assert command[1] == "compile"
    assert recorded_calls() == [" ".join(command[1:])]
    # And it reached stdout exactly once, in the left margin, after the step
    # that announced the work and before the result.
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert out.count("$ ") == 1
    assert lines[0] == f"  {output.STEP} Compiling {source} for Arduino Uno"
    assert lines[1] == "$ " + " ".join(command)
    assert f"  {output.SUCCESS} Compile complete" in out


def test_compile_verbose_echo_does_not_come_from_the_toolchain(
    source, tmp_path, fake_arduino_cli, monkeypatch, capsys
):
    """Silence the formatter: a surviving ``$`` would mean a handler printed it.

    This is the other half of the test above - the echo is routed through
    cli/output.py, not printed by micropy.arduino or the handler.
    """

    script = fake_arduino_cli()
    monkeypatch.setattr(toolchain, "report_tool_command", lambda args, verbose: None)

    assert main(["compile", str(source), "-o", str(tmp_path / "build"), "-v", "--arduino-cli", str(script)]) == EXIT_OK

    captured = capsys.readouterr()
    assert "$ " not in captured.out
    assert "$ " not in captured.err


def test_compile_without_verbose_prints_no_command(
    source, tmp_path, fake_arduino_cli, reported_tool_commands, capsys
):
    """Without ``-v`` the handler still routes, and output.py stays quiet."""

    script = fake_arduino_cli()

    assert main(["compile", str(source), "-o", str(tmp_path / "build"), "--arduino-cli", str(script)]) == EXIT_OK

    assert [verbose for _, verbose in reported_tool_commands] == [False]
    assert "$ " not in capsys.readouterr().out


def test_unknown_board_is_reported(source, capsys):
    assert main(["compile", str(source), "--board", "teensy"]) == EXIT_COMPILE_ERROR
    err = capsys.readouterr().err
    assert "Unknown board: 'teensy'." in err
    assert "arduino:avr:uno" in err


def test_planned_board_is_reported(source, capsys):
    assert main(["compile", str(source), "--board", "esp32"]) == EXIT_COMPILE_ERROR
    assert "not supported yet" in capsys.readouterr().err


# -------------------------------------------------------------------- upload
def test_upload_needs_a_port(source, capsys):
    assert main(["upload", str(source)]) == EXIT_USAGE
    err = capsys.readouterr().err
    assert "serial port" in err
    assert "micropy ports" in err


def test_upload_rejects_a_missing_port_path(source, tmp_path, fake_arduino_cli, capsys):
    script = fake_arduino_cli()
    code = main(["upload", str(source), "--port", str(tmp_path / "missing"), "--arduino-cli", str(script)])
    assert code == EXIT_USAGE
    assert "does not exist" in capsys.readouterr().err


def test_upload_compiles_and_then_uploads(source, tmp_path, fake_arduino_cli, recorded_calls, capsys):
    script = fake_arduino_cli()
    port = tmp_path / "ttyUSB0"
    port.write_text("", encoding="utf-8")
    code = main(
        [
            "upload",
            str(source),
            "--board",
            "arduino:avr:uno",
            "--port",
            str(port),
            "-o",
            str(tmp_path / "build"),
            "--arduino-cli",
            str(script),
        ]
    )
    assert code == EXIT_OK
    calls = recorded_calls()
    assert len(calls) == 2
    assert calls[0].startswith("compile --fqbn arduino:avr:uno")
    assert calls[1].startswith(f"upload --fqbn arduino:avr:uno --port {port}")
    out = capsys.readouterr().out
    assert f"  {output.SUCCESS} Upload complete" in out
    assert str(port) in _fact_row(out, output.PORT)


def test_upload_verbose_echoes_both_commands_once_each(
    source, tmp_path, fake_arduino_cli, recorded_calls, reported_tool_commands, capsys
):
    script = fake_arduino_cli()
    port = tmp_path / "ttyUSB0"
    port.write_text("", encoding="utf-8")

    code = main(
        [
            "upload",
            str(source),
            "-o",
            str(tmp_path / "build"),
            "-v",
            "--port",
            str(port),
            "--arduino-cli",
            str(script),
        ]
    )

    assert code == EXIT_OK
    # compile, then upload: one echo each, in the order they ran.
    assert [command[1] for command, _ in reported_tool_commands] == ["compile", "upload"]
    assert recorded_calls() == [" ".join(command[1:]) for command, _ in reported_tool_commands]
    out = capsys.readouterr().out
    assert out.count("$ ") == 2
    assert [line for line in out.splitlines() if line.startswith("$ ")] == [
        "$ " + " ".join(command) for command, _ in reported_tool_commands
    ]


# ---------------------------------------------------------------- other cmds
def test_boards_lists_supported_and_planned(capsys):
    assert main(["boards"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "arduino:avr:uno" in out
    assert "(default)" in out
    assert "esp32" in out


def test_ports_uses_arduino_cli(fake_arduino_cli, recorded_calls, capsys):
    script = fake_arduino_cli(stdout="Port Protocol Type")
    assert main(["ports", "--arduino-cli", str(script)]) == EXIT_OK
    assert recorded_calls() == ["board list"]
    assert "Port Protocol Type" in capsys.readouterr().out


def test_ports_verbose_echoes_the_command_once(fake_arduino_cli, recorded_calls, reported_tool_commands, capsys):
    script = fake_arduino_cli(stdout="Port Protocol Type")

    assert main(["ports", "-v", "--arduino-cli", str(script)]) == EXIT_OK

    ((command, verbose),) = reported_tool_commands
    assert verbose is True
    assert command == [str(script), "board", "list"]
    assert recorded_calls() == [" ".join(command[1:])]
    out = capsys.readouterr().out
    assert out.count("$ ") == 1
    assert out.splitlines()[:2] == ["$ " + " ".join(command), "Port Protocol Type"]


def test_stubs_writes_the_ide_stub(tmp_path, capsys):
    target = tmp_path / "micropy_api.pyi"
    assert main(["stubs", "-o", str(target)]) == EXIT_OK

    api = StubAPI(target.read_text(encoding="utf-8"))
    # What the copied file declares, not how the declarations are laid out.
    assert api.signature("pin_mode") == "(pin: int, mode: int) -> None"
    assert api.signature("digital_read") == "(pin: int) -> int"
    assert api.constants["OUTPUT"] == "int"
    assert api.constants["A0"] == "int"
    # Arduino's own classes come across with their methods intact.
    assert api.methods("String")["__init__"] == "(self, value: Any = ...) -> None"
    assert api.methods("String")["length"] == "(self) -> int"
    assert api.methods("String")["charAt"] == "(self, index: int) -> str"
    assert api.methods("Servo")["attach"] == "(self, pin: int) -> None"
    assert api.methods("Servo")["detach"] == "(self) -> None"
    assert api.methods("Servo")["write"] == "(self, angle: int) -> None"
    assert api.methods("Servo")["read"] == "(self) -> int"
    assert "micropy_api import" in capsys.readouterr().out


# `stubs` writes one file; every other -o takes a directory.  All three
# spellings mean the same file path, and none of them reinterprets it.
STUB_OUTPUT_FORMS = ["-o", "--output", "--output-file"]


@pytest.mark.parametrize("option", STUB_OUTPUT_FORMS)
def test_stubs_output_forms_all_write_that_exact_file(option, tmp_path):
    target = tmp_path / "api.pyi"
    assert main(["stubs", option, str(target)]) == EXIT_OK

    assert target.is_file()
    assert not (tmp_path / "micropy_api.pyi").exists()
    assert "def pin_mode" in target.read_text(encoding="utf-8")


@pytest.mark.parametrize("option", STUB_OUTPUT_FORMS)
def test_stubs_output_creates_missing_parent_directories(option, tmp_path):
    target = tmp_path / "deep" / "nested" / "api.pyi"
    assert main(["stubs", option, str(target)]) == EXIT_OK

    assert target.is_file()


def test_stubs_output_defaults_to_the_api_stub_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert main(["stubs"]) == EXIT_OK

    assert (tmp_path / "micropy_api.pyi").is_file()


def test_stubs_overwrites_an_existing_file(tmp_path):
    """An existing *file* is a valid target and is replaced, not refused."""

    target = tmp_path / "api.pyi"
    target.write_text("# stale\n", encoding="utf-8")

    assert main(["stubs", "-o", str(target)]) == EXIT_OK

    assert "def pin_mode" in target.read_text(encoding="utf-8")


# ``-o`` names a file.  A directory is a usage error the CLI reports, not an
# IsADirectoryError that escapes as an internal error.
@pytest.mark.parametrize("option", STUB_OUTPUT_FORMS)
def test_stubs_rejects_an_existing_directory(option, tmp_path, capsys):
    target = tmp_path / "out"
    target.mkdir()
    keep = target / "keep.txt"
    keep.write_text("mine\n", encoding="utf-8")

    code = main(["stubs", option, str(target)])

    assert code == EXIT_USAGE == 2
    assert code != EXIT_INTERNAL
    captured = capsys.readouterr()
    assert f"{target} is a directory, not a stub file." in captured.err
    assert "micropy stubs -o micropy_api.pyi" in captured.err
    assert "internal error" not in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""
    assert keep.read_text(encoding="utf-8") == "mine\n"


def test_stubs_rejects_a_directory_at_the_default_path(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    Path("micropy_api.pyi").mkdir()

    assert main(["stubs"]) == EXIT_USAGE

    assert "is a directory, not a stub file." in capsys.readouterr().err


def test_stubs_directory_error_stays_a_usage_error_with_debug(tmp_path, capsys):
    """--debug re-raises bugs; a usage error is not a bug, so it still returns 2."""

    target = tmp_path / "out"
    target.mkdir()

    assert main(["stubs", "--debug", "-o", str(target)]) == EXIT_USAGE

    captured = capsys.readouterr()
    assert "is a directory, not a stub file." in captured.err
    assert "internal error" not in captured.err
    assert "Traceback" not in captured.err


def test_stubs_output_is_a_file_not_a_directory(cli_help):
    """The option is documented as a file, and the help says so explicitly."""

    help_text = cli_help("stubs")
    assert "--output-file" in help_text
    assert "stub file to write" in help_text
    assert "--output-dir" not in help_text


def test_every_other_command_keeps_output_dir(tmp_path, source, cli_help):
    """-o stays an output directory everywhere else: the paths are unchanged."""

    build = tmp_path / "out"
    assert main(["build", str(source), "-o", str(build)]) == EXIT_OK
    assert (build / "main.ino").is_file()
    assert (build / "main.ino").read_text(encoding="utf-8").startswith("const int LED = 13;\n")

    assert main(["clean", "-o", str(build)]) == EXIT_OK
    assert not build.exists()

    for command in ("build", "check", "compile", "upload", "clean"):
        help_text = cli_help(command)
        assert "--output-dir" in help_text
        assert "--output-file" not in help_text


# --------------------------------------------------------------------- init
def test_init_creates_the_ide_files(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == EXIT_OK
    assert (tmp_path / "micropy_api.pyi").exists()
    assert (tmp_path / "pyrightconfig.json").exists()
    assert (tmp_path / "main.py").exists()
    out = capsys.readouterr().out
    assert f"  {output.SUCCESS} Initialized Micropy project" in out
    created = out.split("Created:", 1)[1]
    for name in ("micropy_api.pyi", "pyrightconfig.json", "main.py"):
        assert f"    {name}" in created
    assert "Your IDE is now configured for Micropy." in out
    assert "micropy check main.py" in out


def test_init_writes_a_pyright_config_that_discovers_the_stub(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == EXIT_OK
    config = json.loads((tmp_path / "pyrightconfig.json").read_text(encoding="utf-8"))
    assert "*.py" in config["include"]
    assert "." in config["extraPaths"]
    shim = (tmp_path / "main.py").read_text(encoding="utf-8")
    assert "from micropy_api import *" in shim


def test_init_does_not_overwrite_without_force(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    mine = tmp_path / "micropy_api.pyi"
    mine.write_text("# my own stub\n", encoding="utf-8")
    assert main(["init"]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert "micropy_api.pyi already exists." in captured.err
    assert "Use --force to overwrite it." in captured.err
    assert mine.read_text(encoding="utf-8") == "# my own stub\n"
    assert not (tmp_path / "pyrightconfig.json").exists()


def test_init_force_regenerates_the_ide_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == EXIT_OK
    for name in ("micropy_api.pyi", "pyrightconfig.json", "main.py"):
        (tmp_path / name).write_text("stale", encoding="utf-8")
    assert main(["init", "--force"]) == EXIT_OK
    stub = (tmp_path / "micropy_api.pyi").read_text(encoding="utf-8")
    assert "stale" not in stub
    # The whole file was replaced by the real API, so it parses and declares it.
    api = StubAPI(stub)
    assert api.signature("pin_mode") == "(pin: int, mode: int) -> None"
    assert api.constants["OUTPUT"] == "int"
    assert {"String", "Servo"} <= set(api.classes)
    assert "extraPaths" in (tmp_path / "pyrightconfig.json").read_text(encoding="utf-8")
    assert "from micropy_api import *" in (tmp_path / "main.py").read_text(encoding="utf-8")


def test_init_stub_lists_every_supported_api_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == EXIT_OK
    api = StubAPI((tmp_path / "micropy_api.pyi").read_text(encoding="utf-8"))
    functions = [
        "pin_mode",
        "digital_write",
        "digital_read",
        "analog_read",
        "analog_write",
        "delay",
        "delay_microseconds",
        "millis",
        "micros",
        "pulseIn",
        "tone",
        "noTone",
        "serial_begin",
        "serial_print",
        "serial_println",
        "serial_available",
        "serial_read",
    ]
    constants = [
        "HIGH",
        "LOW",
        "INPUT",
        "OUTPUT",
        "INPUT_PULLUP",
        "INPUT_PULLDOWN",
        "CHANGE",
        "RISING",
        "FALLING",
        "A0",
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "LED_BUILTIN",
    ]
    for name in functions:
        assert name in api.functions, f"{name}() missing from the stub"
    for name in constants:
        assert api.constants.get(name) == "int", f"{name} missing from the stub"
    assert api.signature("pulseIn") == "(pin: int, state: int, timeout: int = 1000000) -> int"
    assert api.signature("tone") == "(pin: int, frequency: int, duration: int = ...) -> None"
    assert api.signature("noTone") == "(pin: int) -> None"


def test_stub_return_annotations_match_the_api_table():
    """The IDE stub and the compiler table must agree on every return type."""
    api = StubAPI(API_STUB.read_text(encoding="utf-8"))
    expected = {"None": "void", "int": "int", "float": "float"}
    for name, function in API_FUNCTIONS.items():
        assert name in api.functions, f"{name}() missing from the stub"
        annotated = ast.unparse(api.functions[name].returns)
        assert expected[annotated] == function.returns, (
            f"{name}() -> {annotated} in the stub, {function.returns} in api.py"
        )


def test_init_and_stubs_copy_the_same_source_stub(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == EXIT_OK
    assert main(["stubs", "-o", "copy.pyi"]) == EXIT_OK
    from_init = (tmp_path / "micropy_api.pyi").read_text(encoding="utf-8")
    from_stubs = (tmp_path / "copy.pyi").read_text(encoding="utf-8")
    assert from_init == from_stubs


def test_init_does_not_overwrite_an_existing_main_py(source, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    original = source.read_text(encoding="utf-8")
    assert main(["init"]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert "main.py already exists." in captured.err
    assert "Use --force to overwrite it." in captured.err
    assert source.read_text(encoding="utf-8") == original


def test_build_is_unaffected_by_the_ide_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == EXIT_OK
    (tmp_path / "main.py").write_text(PROGRAM, encoding="utf-8")
    assert main(["build", "main.py"]) == EXIT_OK
    ino = (tmp_path / "build" / "main.ino").read_text(encoding="utf-8")
    assert ino.startswith("const int LED = 13;\n")
    assert "micropy_api" not in ino


def test_check_does_not_require_the_api_import(source, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert "micropy_api" not in source.read_text(encoding="utf-8")
    assert main(["check", "main.py"]) == EXIT_OK
    assert "main.py: OK" in capsys.readouterr().out


def test_check_and_build_accept_the_init_generated_header(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == EXIT_OK
    header = (tmp_path / "main.py").read_text(encoding="utf-8")
    assert "from builtins import *" in header
    assert "from micropy_api import *" in header
    (tmp_path / "main.py").write_text(header + "\n" + PROGRAM, encoding="utf-8")
    assert main(["check", "main.py"]) == EXIT_OK
    assert main(["build", "main.py"]) == EXIT_OK
    ino = (tmp_path / "build" / "main.ino").read_text(encoding="utf-8")
    assert "const int LED = 13;" in ino
    assert "micropy_api" not in ino


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["--version"])
    assert caught.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_a_command_is_required(capsys):
    with pytest.raises(SystemExit) as caught:
        main([])
    assert caught.value.code == EXIT_USAGE


# ------------------------------------------------------------------ warnings
def test_init_force_says_what_it_replaced(tmp_path, monkeypatch, capsys):
    """--force is consent to overwrite, but not a reason to do it silently."""

    monkeypatch.chdir(tmp_path)
    (tmp_path / "micropy_api.pyi").write_text("# mine\n", encoding="utf-8")

    assert main(["init", "--force"]) == EXIT_OK

    captured = capsys.readouterr()
    assert captured.err.startswith(f"  {output.WARNING} ")
    assert "Overwriting" in captured.err
    assert "micropy_api.pyi" in captured.err
    assert "Initialized Micropy project" in captured.out


def test_init_without_force_has_nothing_to_warn_about(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == EXIT_OK
    assert capsys.readouterr().err == ""


def test_stubs_says_when_it_replaces_a_file(tmp_path, capsys):
    target = tmp_path / "api.pyi"
    target.write_text("# stale\n", encoding="utf-8")

    assert main(["stubs", "-o", str(target)]) == EXIT_OK

    captured = capsys.readouterr()
    assert "Overwriting" in captured.err
    assert "api.pyi" in captured.err
    assert f"Wrote {target}" in captured.out


def test_stubs_is_quiet_when_there_is_nothing_to_replace(tmp_path, capsys):
    assert main(["stubs", "-o", str(tmp_path / "api.pyi")]) == EXIT_OK
    assert capsys.readouterr().err == ""


# ---------------------------------------------------------------------- help
COMMANDS = ["init", "build", "check", "clean", "compile", "upload", "ports", "boards", "stubs"]


def _fact_row(out: str, label: str) -> str:
    """The value on a facts row, found by its label rather than its padding."""

    for line in out.splitlines():
        if line.strip().startswith(label):
            return line.strip()

    raise AssertionError(f"no {label!r} row in:\n{out}")


def test_the_top_level_help_leads_with_the_wordmark_and_the_tagline(capsys):
    """The one screen that introduces micropy is also the one that is branded."""

    with pytest.raises(SystemExit):
        main(["--help"])

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("  MicroPy ")
    assert __version__ in lines[0]
    assert lines[1].startswith("  Write Arduino programs")
    assert lines[3].startswith("usage: micropy ")


@pytest.mark.parametrize("command", COMMANDS)
def test_no_subcommand_repeats_the_wordmark(command, cli_help):
    """A mark on the root screen is an introduction; on every command it is wallpaper."""

    assert "MicroPy" not in cli_help(command)


def test_the_wordmark_is_painted_on_a_terminal_but_not_in_a_pipe(terminal, monkeypatch):
    out, _ = terminal()
    with pytest.raises(SystemExit):
        main(["--help"])
    painted = out.getvalue()

    assert re.search(r"\033\[36;1mMicroPy\033\[0m", painted)

    plain, _ = terminal()
    monkeypatch.setenv("NO_COLOR", "1")
    with pytest.raises(SystemExit):
        main(["--help"])
    assert plain.getvalue().splitlines()[0].startswith("  MicroPy ")


@pytest.mark.parametrize("command", COMMANDS)
def test_every_command_has_help_that_exits_cleanly(command, capsys):
    """--help is documentation, not a failure: exit code 0, and it opens with usage."""

    with pytest.raises(SystemExit) as caught:
        main([command, "--help"])

    assert caught.value.code == 0
    assert capsys.readouterr().out.startswith(f"usage: micropy {command} ")


def test_the_top_level_help_lists_every_command_and_says_how_to_learn_more(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["--help"])

    out = capsys.readouterr().out
    assert caught.value.code == 0
    for command in COMMANDS:
        assert re.search(rf"^\s+{command}\s+\S", out, re.MULTILINE), command
    assert "--debug" in out
    assert "examples:" in out
    assert "micropy COMMAND --help" in out


@pytest.mark.parametrize("command", ["build", "check", "compile", "upload"])
def test_a_command_that_takes_a_program_shows_a_way_to_run_it(command, cli_help):
    help_text = cli_help(command)
    assert "examples:" in help_text
    assert f"micropy {command} main.py" in help_text


@pytest.mark.parametrize("command", COMMANDS)
def test_help_carries_no_escapes_when_the_output_is_not_a_terminal(command, cli_help):
    """A pipe, a file and CI get plain help, argparse's own colouring included."""

    assert "\033[" not in cli_help(command)


@pytest.mark.parametrize("command", [None, "build", "ports"])
def test_no_color_silences_the_help_screen_itself(command, terminal, monkeypatch):
    """Python 3.14's argparse paints help; micropy decides whether it may.

    Without this the help screen would be the one output ``NO_COLOR`` did not
    reach, because argparse applies its own rules rather than ours.
    """

    monkeypatch.setenv("NO_COLOR", "1")
    painted, _ = terminal()
    argv = ["--help"] if command is None else [command, "--help"]

    with pytest.raises(SystemExit):
        main(argv)

    assert "\033[" not in painted.getvalue()


def test_the_source_commands_document_their_common_options(cli_help):
    for command in ("build", "check", "compile", "upload"):
        help_text = cli_help(command)
        assert "--output-dir OUTPUT_DIR" in help_text
        assert "-v, --verbose" in help_text


def test_the_toolchain_commands_document_the_toolchain_options(cli_help):
    for command in ("compile", "upload", "ports"):
        assert "--arduino-cli PATH" in cli_help(command)
    assert "-b, --board" in cli_help("compile")
    assert "-p, --port" in cli_help("upload")


# --------------------------------------------------------------------- --debug
#: ``--debug`` is a global flag, so it has to work before the command, right
#: after it, and after the command's own arguments - for every command.
DEBUG_POSITIONS = [
    ["--debug", "build", "main.py"],
    ["build", "--debug", "main.py"],
    ["build", "main.py", "--debug"],
    ["--debug", "check", "main.py"],
    ["check", "main.py", "--debug"],
    ["clean", "--debug"],
    ["--debug", "init"],
    ["init", "--debug", "--force"],
    ["boards", "--debug"],
    ["--debug", "ports"],
    ["stubs", "--debug", "-o", "api.pyi"],
    ["compile", "main.py", "--debug"],
    ["upload", "main.py", "--debug", "-p", "/dev/ttyACM0"],
]

DEBUG_POSITIONS_IN_BUILD = DEBUG_POSITIONS[:3]


@pytest.mark.parametrize("argv", DEBUG_POSITIONS)
def test_debug_is_recognized_in_any_position(argv):
    """Before the command, after it, or after the arguments - all accepted."""

    assert build_parser().parse_args(argv).debug is True


@pytest.mark.parametrize("argv", DEBUG_POSITIONS)
def test_debug_stays_off_when_it_is_not_given(argv):
    """Every command still defaults to no debugging."""

    without = [item for item in argv if item != "--debug"]
    assert build_parser().parse_args(without).debug is False


@pytest.mark.parametrize("command", ["init", "build", "check", "clean", "compile", "upload", "ports", "boards", "stubs"])
def test_every_command_documents_debug(command, capsys):
    """A flag the user may write after the command has to be discoverable."""

    with pytest.raises(SystemExit):
        main([command, "--help"])
    assert "--debug" in capsys.readouterr().out


@pytest.fixture
def broken_compile(monkeypatch):
    """Make the compiler fail with something that is not a MicropyError."""

    def explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("micropy.cli.commands.sketch.compile_file", explode)


@pytest.mark.parametrize("argv", DEBUG_POSITIONS_IN_BUILD)
def test_debug_re_raises_the_traceback_in_any_position(argv, source, tmp_path, broken_compile):
    """--debug is not merely accepted: the real exception reaches the user."""

    resolved = [str(source) if item == "main.py" else item for item in argv]
    resolved += ["-o", str(tmp_path / "build")]

    with pytest.raises(RuntimeError, match="boom"):
        main(resolved)


@pytest.mark.parametrize("argv", DEBUG_POSITIONS_IN_BUILD)
def test_without_debug_the_same_failure_stays_quiet(argv, source, tmp_path, monkeypatch, broken_compile, capsys):
    resolved = [str(source) if item == "main.py" else item for item in argv]
    resolved = [item for item in resolved if item != "--debug"]
    resolved += ["-o", str(tmp_path / "build")]

    assert main(resolved) == EXIT_INTERNAL
    err = capsys.readouterr().err
    assert err.startswith(f"  {output.FAILURE} Internal error: RuntimeError: boom")
    assert "Please re-run with --debug and report this." in err
    assert "Traceback" not in err


def test_debug_re_raises_a_source_error_too(tmp_path, capsys):
    """The MicropyError branch honours --debug as well."""

    broken = tmp_path / "broken.py"
    broken.write_text("def main():\n    pass\n", encoding="utf-8")

    for argv in (
        ["--debug", "build", str(broken)],
        ["build", "--debug", str(broken)],
        ["build", str(broken), "--debug"],
    ):
        with pytest.raises(MicropyError, match="Missing required function"):
            main(argv + ["-o", str(tmp_path / "build")])

    assert main(["build", str(broken), "-o", str(tmp_path / "build")]) == EXIT_COMPILE_ERROR
    err = capsys.readouterr().err
    assert "Missing required function: loop()" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("argv", DEBUG_POSITIONS_IN_BUILD)
def test_debug_does_not_change_a_successful_run(argv, source, tmp_path, capsys):
    """A successful build prints exactly the same with the flag on or off."""

    resolved = [str(source) if item == "main.py" else item for item in argv]
    if "--debug" not in resolved:
        resolved += ["--debug"]
    resolved += ["-o", str(tmp_path / "build")]

    assert main(resolved) == EXIT_OK
    assert (tmp_path / "build" / "main.ino").read_text(encoding="utf-8").startswith("const int LED = 13;\n")
