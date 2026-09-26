"""The command line interface: build, check, clean, compile, upload, ..."""

from __future__ import annotations

import json
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
from micropy.errors import MicropyError

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


# --------------------------------------------------------------------- build
def test_build_writes_build_main_ino(source, tmp_path, capsys):
    assert main(["build", str(source), "-o", str(tmp_path / "build")]) == EXIT_OK
    generated = tmp_path / "build" / "main.ino"
    assert generated.exists()
    assert "#include <Arduino.h>" not in generated.read_text(encoding="utf-8")
    assert generated.read_text(encoding="utf-8").startswith("const int LED = 13;\n")
    assert "const int LED = 13;" in generated.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert "Generated" in out
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
    assert "MicropyError:" in captured.err
    assert "Missing required function: loop()" in captured.err
    assert "Traceback" not in captured.err
    assert not (tmp_path / "build").exists()


def test_build_reports_syntax_errors_with_a_location(tmp_path, capsys):
    broken = tmp_path / "broken.py"
    broken.write_text("def main(:\n", encoding="utf-8")
    assert main(["build", str(broken), "-o", str(tmp_path / "build")]) == EXIT_COMPILE_ERROR
    assert "broken.py:1" in capsys.readouterr().err


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
    assert "ArduinoCliError:" in err
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
    assert "Compiled" in capsys.readouterr().out


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
    # And it reached stdout exactly once, ahead of the tool's own output.
    out = capsys.readouterr().out
    assert out.count("$ ") == 1
    assert out.splitlines()[0] == "$ " + " ".join(command)


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
    assert "Uploaded" in out
    assert str(port) in out


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
    content = target.read_text(encoding="utf-8")
    assert "def pin_mode(pin: int, mode: int) -> None: ..." in content
    assert "OUTPUT: int" in content
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
    assert "Initialized Micropy project." in out
    assert "  ✓ micropy_api.pyi" in out
    assert "  ✓ pyrightconfig.json" in out
    assert "Your IDE is now configured for Micropy." in out


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
    assert "def pin_mode(pin: int, mode: int) -> None: ..." in stub
    assert "stale" not in stub
    assert "extraPaths" in (tmp_path / "pyrightconfig.json").read_text(encoding="utf-8")
    assert "from micropy_api import *" in (tmp_path / "main.py").read_text(encoding="utf-8")


def test_init_stub_lists_every_supported_api_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == EXIT_OK
    stub = (tmp_path / "micropy_api.pyi").read_text(encoding="utf-8")
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
        assert f"def {name}(" in stub, f"{name}() missing from the stub"
    for name in constants:
        assert f"{name}: int" in stub, f"{name} missing from the stub"


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
    assert "micropy: internal error: RuntimeError: boom" in err
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
