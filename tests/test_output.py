"""How the CLI looks: symbols, streams, hierarchy and colour.

These tests care about *semantics* - which stream a line went to, which symbol
introduced it, what information survived, whether colour appeared - rather than
about exact column counts, so the layout can keep moving without the suite going
red over a space.
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

from controllerpy.boards import DEFAULT_BOARD, PLANNED_BOARDS, Board, supported_boards
from controllerpy.cli import main, output
from controllerpy.errors import ArduinoCliError, ControllerPyError

ANSI = re.compile(r"\033\[[0-9;]*m")

STATUS_INDENT = "  "
DETAIL_INDENT = "    "


# ------------------------------------------------------------------ primitives
def test_a_step_is_marked_and_goes_to_stdout(capsys):
    output.report_step("Compiling main.py")
    captured = capsys.readouterr()
    assert captured.out == f"  {output.STEP} Compiling main.py\n"
    assert captured.err == ""


def test_a_success_is_marked_and_goes_to_stdout(capsys):
    output.report_success("Build complete")
    assert capsys.readouterr().out == f"  {output.SUCCESS} Build complete\n"


def test_detail_sits_under_the_status_line_it_qualifies(capsys):
    output.report_success("Build complete")
    output.report_detail("Output: build/main.ino")
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == f"  {output.SUCCESS} Build complete"
    # Deeper indent and no symbol of its own: it is context, not an event.
    assert lines[1] == f"{DETAIL_INDENT}Output: build/main.ino"


def test_a_warning_is_marked_and_goes_to_stderr(capsys):
    output.report_warning("Overwriting main.py")
    captured = capsys.readouterr()
    assert captured.err == f"  {output.WARNING} Overwriting main.py\n"
    assert captured.out == ""


def test_an_error_is_marked_and_goes_to_stderr(capsys):
    output.report_error("Serial port /dev/nope does not exist.")
    captured = capsys.readouterr()
    assert captured.err == f"  {output.FAILURE} Serial port /dev/nope does not exist.\n"
    assert captured.out == ""


def test_an_error_may_carry_the_one_thing_that_fixes_it(capsys):
    output.report_error("Upload needs a serial port.", hint="Run 'controllerpy ports'.")
    lines = capsys.readouterr().err.splitlines()
    assert lines[0] == f"  {output.FAILURE} Upload needs a serial port."
    assert lines[1] == f"{DETAIL_INDENT}hint: Run 'controllerpy ports'."


def test_each_symbol_means_one_thing():
    """Four statuses, four symbols: a reader learns them once."""

    assert output.STEP != output.SUCCESS
    assert output.SUCCESS != output.WARNING
    assert output.WARNING != output.FAILURE
    assert len({output.STEP, output.SUCCESS, output.WARNING, output.FAILURE}) == 4


# --------------------------------------------------------------------- errors
def test_an_exception_keeps_every_word_of_the_error(capsys):
    """Prettier, never shorter: nothing the error knows may be dropped."""

    exc = ControllerPyError(
        "Unknown ArduinoPy function: foo()",
        filename="main.py",
        line=8,
        col=5,
        hint="Supported Arduino functions include:",
        hint_lines=["digital_write()", "digital_read()", "pin_mode()"],
    )
    output.report_exception(exc)
    err = capsys.readouterr().err

    assert err.splitlines()[0] == f"  {output.FAILURE} ControllerPyError"
    assert "main.py:8:5" in err
    assert "Unknown ArduinoPy function: foo()" in err
    assert "Supported Arduino functions include:" in err
    for name in ("digital_write()", "digital_read()", "pin_mode()"):
        assert name in err


def test_a_hint_is_labelled_and_its_lines_sit_under_it(capsys):
    """Advice is set apart from the message by a label and a deeper indent."""

    exc = ControllerPyError(
        "arduino-cli was not found.",
        hint="Check the path, or install the Arduino CLI:",
        hint_lines=["1. Install it", "2. Point controllerpy at it"],
    )
    output.report_exception(exc)
    lines = capsys.readouterr().err.splitlines()

    hint_at = next(i for i, line in enumerate(lines) if "hint:" in line)
    assert lines[hint_at] == f"{DETAIL_INDENT}hint: Check the path, or install the Arduino CLI:"
    for line in lines[hint_at + 1 :]:
        assert line.startswith("      ")


def test_the_headline_comes_before_the_explanation(capsys):
    """The failure has to be findable without reading the rest of the block."""

    exc = ControllerPyError("Missing required function: loop()", filename="main.py", line=1)
    output.report_exception(exc)
    err = capsys.readouterr().err

    assert err.index("ControllerPyError") < err.index("Missing required function")
    assert err.index("main.py:1") < err.index("Missing required function")


def test_the_location_gets_a_line_of_its_own(capsys):
    exc = ControllerPyError("boom", filename="main.py", line=12, col=5)
    output.report_exception(exc)
    lines = capsys.readouterr().err.splitlines()
    location = next(line for line in lines if "main.py:12:5" in line)
    assert location.strip() == "main.py:12:5"
    assert location.startswith(STATUS_INDENT)


def test_an_error_without_a_location_still_explains_itself(capsys):
    output.report_exception(ArduinoCliError("arduino-cli was not found."))
    err = capsys.readouterr().err
    assert err.splitlines()[0] == f"  {output.FAILURE} ArduinoCliError"
    assert "arduino-cli was not found." in err


def test_a_toolchain_failure_keeps_the_tool_output(capsys):
    """arduino-cli's own last words are the most useful part of the report."""

    exc = ArduinoCliError(
        "arduino-cli compile failed (exit code 1).",
        hint="arduino-cli reported:",
        hint_lines=["error: no such core", "  try 'arduino-cli core install arduino:avr'"],
    )
    output.report_exception(exc)
    captured = capsys.readouterr()

    assert captured.out == ""
    assert "arduino-cli reported:" in captured.err
    assert "no such core" in captured.err
    assert "try 'arduino-cli core install arduino:avr'" in captured.err


def test_conflicts_name_each_file_and_give_advice_once(capsys):
    output.report_conflicts([Path("controllerpy_api.pyi"), Path("main.py")])
    lines = capsys.readouterr().err.splitlines()

    failures = [line for line in lines if line.startswith(STATUS_INDENT + output.FAILURE)]
    assert failures == [
        f"  {output.FAILURE} controllerpy_api.pyi already exists.",
        f"  {output.FAILURE} main.py already exists.",
    ]
    # One piece of advice, and it agrees with the number of files.
    assert [line for line in lines if "--force" in line] == [f"{DETAIL_INDENT}hint: Use --force to overwrite them."]


def test_one_conflict_is_referred_to_in_the_singular(capsys):
    output.report_conflicts([Path("controllerpy_api.pyi")])
    assert f"{DETAIL_INDENT}hint: Use --force to overwrite it." in capsys.readouterr().err


def test_an_internal_error_names_the_exception_and_the_way_out(capsys):
    output.report_internal_error(RuntimeError("boom"))
    lines = capsys.readouterr().err.splitlines()
    assert lines[0] == f"  {output.FAILURE} Internal error: RuntimeError: boom"
    assert "--debug" in lines[1]


def test_interruption_is_reported_as_a_failure(capsys):
    output.report_interrupted()
    assert capsys.readouterr().err == f"  {output.FAILURE} Interrupted.\n"


# ------------------------------------------------------------------- the sketch
def test_check_names_the_file_that_parsed(capsys):
    output.report_checked("main.py")
    assert capsys.readouterr().out == f"  {output.SUCCESS} main.py: OK\n"


def test_a_verbose_check_says_what_it_found(capsys):
    output.report_checked("main.py", "1 global, 2 functions")
    assert "1 global, 2 functions" in capsys.readouterr().out


def fact_rows(out):
    """The value of each facts row, keyed by label, padding discarded."""

    return {
        line.split()[0]: line.split(maxsplit=1)[1]
        for line in out.splitlines()
        if line.startswith(DETAIL_INDENT) and len(line.split()) > 1
    }


def test_building_names_the_file_it_wrote_with_its_size(capsys):
    output.report_built(Path("build/main.ino"), line_count=42)
    out = capsys.readouterr().out
    assert f"  {output.SUCCESS} Build complete" in out
    assert fact_rows(out)[output.OUTPUT] == "build/main.ino (42 lines)"


def test_building_verbose_says_what_the_program_defines_on_its_own_row(capsys):
    output.report_built(Path("build/main.ino"), line_count=42, summary="1 global, 2 functions")
    rows = fact_rows(capsys.readouterr().out)
    assert rows[output.OUTPUT] == "build/main.ino (42 lines)"
    assert rows["Defines"] == "1 global, 2 functions"


def test_a_facts_block_aligns_its_column_however_long_the_labels_are(capsys):
    output.report_facts([("A", "1"), ("Longer label", "2")])
    rows = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    values = [line.index("1") if "1" in line else line.index("2") for line in rows]
    assert len(set(values)) == 1


def test_an_empty_facts_block_prints_nothing(capsys):
    output.report_facts([])
    assert capsys.readouterr().out == ""


def test_compiling_names_the_sketch_the_board_and_the_fqbn(capsys):
    board = Board(fqbn="arduino:avr:uno", name="Arduino Uno", alias="uno")
    output.report_compiled(Path("build/main"), Path("build/main.ino"), board)
    out = capsys.readouterr().out
    assert f"  {output.SUCCESS} Compile complete" in out
    rows = fact_rows(out)
    assert rows[output.SKETCH] == "build/main"
    assert rows[output.BOARD] == "Arduino Uno (arduino:avr:uno)"
    assert rows[output.OUTPUT] == "build/main.ino"


def test_uploading_names_the_port_it_flashed(capsys):
    board = Board(fqbn="arduino:avr:uno", name="Arduino Uno", alias="uno")
    output.report_uploaded(Path("build/main"), Path("build/main.ino"), "/dev/ttyACM0", board)
    rows = fact_rows(capsys.readouterr().out)
    assert rows[output.PORT] == "/dev/ttyACM0"
    assert rows[output.BOARD] == "Arduino Uno"
    assert rows[output.OUTPUT] == "build/main.ino"


def test_cleaning_reports_what_it_removed(capsys):
    output.report_removed(Path("build"))
    assert capsys.readouterr().out == f"  {output.SUCCESS} Removed build\n"


def test_having_nothing_to_clean_is_quiet_but_says_why(capsys):
    output.report_nothing_to_clean(Path("build"))
    out = capsys.readouterr().out
    assert out.startswith(DETAIL_INDENT)
    assert "Nothing to clean" in out
    assert "does not exist" in out


# ----------------------------------------------------------------- the project
def test_the_created_block_lists_every_file_written(capsys):
    output.report_written_files([Path("controllerpy_api.pyi"), Path("pyrightconfig.json")])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == ""
    assert "Created:" in lines[1]
    assert f"{DETAIL_INDENT}controllerpy_api.pyi" in lines
    assert f"{DETAIL_INDENT}pyrightconfig.json" in lines
    # A list of files is not three finished operations: no ✓ per row.
    assert output.SUCCESS not in "\n".join(lines)


def test_overwriting_is_a_warning_on_stderr(capsys):
    output.report_overwritten([Path("api.pyi")])
    captured = capsys.readouterr()
    assert captured.err.startswith(f"  {output.WARNING} ")
    assert "Overwriting" in captured.err
    assert "api.pyi" in captured.err
    assert captured.out == ""


def test_overwriting_nothing_says_nothing(capsys):
    output.report_overwritten([])
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_the_board_table_has_a_header_and_marks_the_default(capsys):
    output.report_board_table(supported_boards(), PLANNED_BOARDS, DEFAULT_BOARD)
    out = capsys.readouterr().out

    assert "ALIAS" in out and "FQBN" in out and "NAME" in out
    assert "Supported boards" in out
    assert "Planned boards (not implemented yet)" in out
    assert f"{DEFAULT_BOARD}" in out
    assert "(default)" in out
    # Every row lines up under its own column.
    aliases = [line.split()[0] for line in out.splitlines() if line.startswith(DETAIL_INDENT)]
    assert set(PLANNED_BOARDS) <= set(aliases)


def test_the_board_table_sorts_the_planned_boards(capsys):
    output.report_board_table(supported_boards(), PLANNED_BOARDS, DEFAULT_BOARD)
    aliases = tuple(DETAIL_INDENT + alias for alias in PLANNED_BOARDS)
    planned = [line for line in capsys.readouterr().out.splitlines() if line.startswith(aliases)]
    assert [line.split()[0] for line in planned] == sorted(PLANNED_BOARDS)


# ------------------------------------------------------------------ toolchain
def test_the_tool_command_is_echoed_only_when_asked(capsys):
    output.report_tool_command(["arduino-cli", "compile"], False)
    assert capsys.readouterr().out == ""

    output.report_tool_command(["arduino-cli", "compile"], True)
    assert capsys.readouterr().out == "$ arduino-cli compile\n"


def test_the_tool_command_stays_in_the_left_margin(capsys):
    """A transcript, not part of the status column."""

    output.report_tool_command(["arduino-cli", "compile"], True)
    assert capsys.readouterr().out.startswith("$ ")


def test_the_tool_output_is_indented_under_the_command(capsys):
    output.report_tool_output("Sketch uses 924 bytes\nGlobal variables use 9 bytes.\n", True)
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        f"{DETAIL_INDENT}Sketch uses 924 bytes",
        f"{DETAIL_INDENT}Global variables use 9 bytes.",
    ]


def test_the_tool_output_is_withheld_unless_asked(capsys):
    output.report_tool_output("Sketch uses 924 bytes", False)
    assert capsys.readouterr().out == ""


def test_an_empty_tool_output_prints_no_blank_lines(capsys):
    output.report_tool_output("   \n\n", True)
    assert capsys.readouterr().out == ""


def test_the_port_listing_is_relayed_exactly(capsys):
    """The table *is* the answer, so the tool's columns are taken at face value."""

    listing = "Port         Type\n/dev/ttyACM0 Serial Port (USB)"
    output.report_port_listing(listing)
    assert capsys.readouterr().out == f"{listing}\n"


def test_no_connected_boards_is_a_quiet_note(capsys):
    output.report_port_listing("  \n")
    out = capsys.readouterr().out
    assert out == f"{DETAIL_INDENT}No boards found.\n"


# ---------------------------------------------------------------------- colour
BUILDABLE = "LED = 13\n\ndef main():\n    pin_mode(LED, OUTPUT)\n\ndef loop():\n    delay(10)\n"


def test_a_terminal_run_is_painted(tmp_path, terminal):
    """On a real terminal the status symbols carry their meaning in colour."""

    out, err = terminal()
    source = tmp_path / "main.py"
    source.write_text(BUILDABLE, encoding="utf-8")

    assert main(["build", str(source), "-o", str(tmp_path / "build")]) == 0

    painted = out.getvalue()
    assert "\033[" in painted
    assert ANSI.sub("", painted) == (
        f"  {output.STEP} Compiling {source}\n"
        f"  {output.SUCCESS} Build complete\n"
        f"\n"
        f"    Output  {tmp_path / 'build' / 'main.ino'} (9 lines)\n"
    )
    assert err.getvalue() == ""


def test_no_color_run_is_identical_apart_from_the_escapes(tmp_path, terminal, monkeypatch):
    """NO_COLOR must change the bytes on the wire and nothing else."""

    out, _ = terminal()
    source = tmp_path / "main.py"
    source.write_text(BUILDABLE, encoding="utf-8")

    main(["build", str(source), "-o", str(tmp_path / "build")])
    painted = out.getvalue()

    out.truncate(0)
    out.seek(0)
    monkeypatch.setenv("NO_COLOR", "1")
    main(["build", str(source), "-o", str(tmp_path / "build")])
    plain = out.getvalue()

    assert "\033[" in painted
    assert "\033[" not in plain
    assert ANSI.sub("", painted) == plain


def test_a_failure_is_painted_only_on_the_stream_that_is_a_terminal(tmp_path, terminal, monkeypatch):
    """The two streams are judged separately, so a redirected one stays plain."""

    out, _ = terminal()
    pipe = io.StringIO()
    monkeypatch.setattr(sys, "stderr", pipe)
    broken = tmp_path / "broken.py"
    broken.write_text("def main():\n    pass\n", encoding="utf-8")

    assert main(["build", str(broken)]) == 1

    err = pipe.getvalue()
    assert "\033[" in out.getvalue()
    assert "\033[" not in err
    assert err.splitlines()[0] == f"  {output.FAILURE} ControllerPyError"
    assert "Missing required function: loop()" in err


def test_a_captured_run_is_never_painted(capsys, tmp_path):
    """A pipe, a file and CI all get plain text without being asked."""

    source = tmp_path / "main.py"
    source.write_text(BUILDABLE, encoding="utf-8")

    assert main(["build", str(source), "-o", str(tmp_path / "build")]) == 0

    captured = capsys.readouterr()
    assert "\033[" not in captured.out
    assert "\033[" not in captured.err
    assert f"  {output.SUCCESS} Build complete" in captured.out


def test_a_captured_failure_is_never_painted(capsys, tmp_path):
    broken = tmp_path / "broken.py"
    broken.write_text("def main():\n    pass\n", encoding="utf-8")

    assert main(["build", str(broken)]) == 1

    captured = capsys.readouterr()
    assert "\033[" not in captured.out
    assert "\033[" not in captured.err
