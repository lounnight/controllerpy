from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import pytest

from controllerpy.cli import EXIT_OK, EXIT_USAGE, main
from controllerpy.cli.commands import edit as edit_module
from controllerpy.cli.editor import Editor, Frame, TextBuffer, render, run_editor
from controllerpy.cli.editor.keys import parse_key, parse_keys
from controllerpy.cli.editor.syntax import highlight_line
from controllerpy.cli.editor.terminal import Terminal, apply_styles

PROGRAM = (
    "from builtins import *\n"
    "from controllerpy_api import *\n"
    "\n"
    "def main():\n"
    "    pin_mode(13, OUTPUT)\n"
    "\n"
    "def loop():\n"
    "    delay(50)\n"
)


class FakeScreen:
    def __init__(self, keys: List[str], size: Tuple[int, int] = (12, 40)) -> None:
        self.keys = list(keys)
        self.size_value = size
        self.frames = []

    def size(self) -> Tuple[int, int]:
        return self.size_value

    def draw(self, frame) -> None:
        self.frames.append(frame)

    def read_key(self, timeout: float) -> Optional[str]:
        if not self.keys:
            raise AssertionError("screen ran out of keys")

        return self.keys.pop(0)

    def __enter__(self) -> "FakeScreen":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def load_editor(path: Path) -> Editor:
    text = path.read_text(encoding="utf-8")
    stat = path.stat()
    buffer = TextBuffer.from_text(text)

    return Editor(path, buffer, disk_version=(stat.st_mtime_ns, stat.st_size))


def new_editor(path: Path) -> Editor:
    return Editor(path, TextBuffer.empty(), disk_version=None)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "\n",
        "a",
        "a\n",
        "a\n\n",
        "line1\nline2\n",
        "  indented\n    deeper\n",
        "a\r\nb\r\n",
        "a\r\n",
        "a\r",
        PROGRAM,
    ],
)
def test_buffer_round_trips_text(text: str):
    assert TextBuffer.from_text(text).text() == text


def test_new_buffer_saves_with_trailing_newline():
    buffer = TextBuffer.empty()
    buffer.insert(0, 0, "x")

    assert buffer.text() == "x\n"


def test_insert_splits_and_joins_lines():
    buffer = TextBuffer.from_text("abcd\n")

    row, col = buffer.insert(0, 2, "\n")
    assert (row, col) == (1, 0)
    assert buffer.text() == "ab\ncd\n"

    buffer.delete((0, 2), (1, 0))
    assert buffer.text() == "abcd\n"


def test_editor_tracks_dirty_state(tmp_path):
    path = tmp_path / "main.py"
    path.write_text("a\n", encoding="utf-8")
    editor = load_editor(path)
    assert not editor.dirty

    editor.handle_key("i")
    editor.handle_key("x")
    assert editor.dirty

    editor.handle_key("ctrl+s")
    assert not editor.dirty
    assert path.read_text(encoding="utf-8") == "xa\n"


def test_editor_inserts_printable_keys_and_enter(tmp_path):
    path = tmp_path / "main.py"
    editor = new_editor(path)

    editor.handle_key("i")
    for key in "ab":
        editor.handle_key(key)
    editor.handle_key("enter")
    for key in "cd":
        editor.handle_key(key)
    editor.handle_key("tab")

    assert editor.buffer.text() == "ab\ncd    \n"
    assert (editor.row, editor.col) == (1, 6)


def test_editor_arrow_navigation_stays_inside_the_text(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abc\nde\n"), disk_version=None)

    editor.handle_key("right")
    editor.handle_key("right")
    editor.handle_key("right")
    editor.handle_key("right")
    assert (editor.row, editor.col) == (0, 2)

    editor.handle_key("down")
    assert (editor.row, editor.col) == (1, 1)

    editor.handle_key("down")
    assert (editor.row, editor.col) == (1, 1)

    editor.handle_key("up")
    editor.handle_key("up")
    assert (editor.row, editor.col) == (0, 1)

    editor.handle_key("left")
    editor.handle_key("left")
    editor.handle_key("left")
    editor.handle_key("left")
    assert (editor.row, editor.col) == (0, 0)

    editor.handle_key("end")
    assert editor.col == 2
    editor.handle_key("home")
    assert editor.col == 0


def test_editor_backspace_and_delete_join_lines(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("ab\ncd\n"), disk_version=None)

    editor.handle_key("i")
    editor.handle_key("down")
    editor.handle_key("backspace")
    assert editor.buffer.text() == "abcd\n"
    assert (editor.row, editor.col) == (0, 2)

    editor.handle_key("end")
    editor.handle_key("delete")
    assert editor.buffer.text() == "abcd\n"

    editor.handle_key("home")
    editor.handle_key("delete")
    assert editor.buffer.text() == "bcd\n"


def test_editor_ctrl_q_requires_confirmation_when_dirty(tmp_path):
    path = tmp_path / "main.py"
    editor = new_editor(path)
    editor.handle_key("i")
    editor.handle_key("z")

    editor.handle_key("ctrl+q")
    assert editor.running
    assert "Unsaved changes" in editor.message
    assert path.exists() is False

    editor.handle_key("ctrl+q")
    assert not editor.running
    assert editor.discarded


def test_editor_ctrl_q_cancels_confirmation_on_other_key(tmp_path):
    path = tmp_path / "main.py"
    editor = new_editor(path)
    editor.handle_key("i")
    editor.handle_key("z")
    editor.handle_key("ctrl+q")
    editor.handle_key("left")

    assert editor.pending is None
    editor.handle_key("ctrl+q")
    assert editor.running
    assert not editor.discarded


def test_editor_quits_cleanly_without_changes(tmp_path):
    path = tmp_path / "main.py"
    editor = new_editor(path)

    editor.handle_key("ctrl+q")
    assert not editor.running
    assert not editor.discarded
    assert path.exists() is False


def test_editor_save_refuses_until_confirmed_after_external_change(tmp_path):
    path = tmp_path / "main.py"
    path.write_text("one\n", encoding="utf-8")
    editor = load_editor(path)
    path.write_text("changed externally\n", encoding="utf-8")

    editor.handle_key("ctrl+s")
    assert "changed on disk" in editor.message
    assert path.read_text(encoding="utf-8") == "changed externally\n"

    editor.handle_key("ctrl+s")
    assert path.read_text(encoding="utf-8") == "one\n"
    assert not editor.dirty


def test_editor_reports_write_failure(tmp_path):
    path = tmp_path / "missing" / "main.py"
    editor = Editor(path, TextBuffer.empty(), disk_version=None)
    editor.handle_key("q")

    assert editor.save() is False
    assert "Cannot write" in editor.message


def test_run_editor_renders_and_handles_a_session(tmp_path):
    path = tmp_path / "main.py"
    editor = new_editor(path)
    screen = FakeScreen(["i", "a", "enter", "b", "ctrl+s", "ctrl+q"])

    run_editor(editor, screen)

    assert not editor.running
    assert path.read_text(encoding="utf-8") == "a\nb\n"
    assert screen.frames
    assert "written" in screen.frames[-1].lines[-1]
    assert any("main.py" in frame.lines[frame.status_row] for frame in screen.frames)


def test_render_layout_and_status(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abc\n"), disk_version=None)

    frame = render(editor, 4, 40)
    assert frame.lines[0] == "  1 | abc"
    assert frame.lines[1] == ""
    assert frame.status_row == 2
    assert frame.command_row == 3
    assert "main.py" in frame.lines[frame.status_row]
    assert "Line 1, Col 1" in frame.lines[frame.status_row]
    assert "NORMAL" in frame.lines[frame.status_row]
    assert frame.lines[frame.command_row] == ""
    assert frame.command_kind == "idle"
    assert frame.cursor_row == 0
    assert frame.cursor_col == 6

    editor.message = "hello"
    frame = render(editor, 4, 40)
    assert frame.lines[-1] == " hello"
    assert frame.command_kind == "message"


def test_render_expands_tabs_for_display(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("\tx\n"), disk_version=None)

    frame = render(editor, 3, 20)
    assert frame.lines[0] == "  1 |     x"

    editor.col = 1
    frame = render(editor, 3, 20)
    assert frame.cursor_col == 10


def test_render_keeps_cursor_visible_while_scrolling(tmp_path):
    path = tmp_path / "main.py"
    lines = "".join(f"line{i}\n" for i in range(50))
    editor = Editor(path, TextBuffer.from_text(lines), disk_version=None)
    editor.row = 40

    frame = render(editor, 10, 30)
    assert editor.top_row == 33
    assert frame.cursor_row == 7
    assert "line40" in frame.lines[7]

    editor.row = 0
    frame = render(editor, 10, 30)
    assert editor.top_row == 0
    assert frame.cursor_row == 0


def test_render_clips_to_small_terminals(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abcdef\n"), disk_version=None)
    editor.col = 6

    frame = render(editor, 3, 4)
    assert frame.lines[0] == "def"
    assert len(frame.lines) == 3

    frame = render(editor, 1, 4)
    assert len(frame.lines) == 1
    assert frame.cursor_col <= 3

    frame = render(editor, 0, 0)
    assert len(frame.lines) == 1
    assert frame.cursor_col == 0


def test_editor_starts_normal_and_insert_mode_round_trips(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abc\n"), disk_version=None)

    assert editor.mode == "normal"

    editor.handle_key("l")
    editor.handle_key("l")
    assert (editor.row, editor.col) == (0, 2)

    editor.handle_key("i")
    assert editor.mode == "insert"
    editor.handle_key("X")

    editor.handle_key("escape")
    assert editor.mode == "normal"
    assert editor.buffer.text() == "abXc\n"
    assert (editor.row, editor.col) == (0, 2)


def test_editor_escape_at_line_start_keeps_column(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abc\n"), disk_version=None)

    editor.handle_key("i")
    editor.handle_key("escape")

    assert editor.mode == "normal"
    assert editor.col == 0


def test_editor_normal_hjkl_and_arrows_move_the_cursor(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abc\ndef\n"), disk_version=None)

    editor.handle_key("l")
    editor.handle_key("l")
    assert (editor.row, editor.col) == (0, 2)

    editor.handle_key("j")
    assert (editor.row, editor.col) == (1, 2)

    editor.handle_key("k")
    assert (editor.row, editor.col) == (0, 2)

    editor.handle_key("h")
    assert editor.col == 1

    editor.handle_key("right")
    assert editor.col == 2

    editor.handle_key("down")
    editor.handle_key("up")
    assert (editor.row, editor.col) == (0, 2)


def test_editor_normal_column_motions(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abc\n"), disk_version=None)

    editor.handle_key("$")
    assert editor.col == 2

    editor.handle_key("0")
    assert editor.col == 0

    editor.handle_key("end")
    assert editor.col == 2

    editor.handle_key("home")
    assert editor.col == 0


def test_editor_normal_word_motions(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("foo bar baz\n"), disk_version=None)

    editor.handle_key("w")
    assert editor.col == 4

    editor.handle_key("w")
    assert editor.col == 8

    editor.handle_key("b")
    assert editor.col == 4

    editor.handle_key("b")
    assert editor.col == 0


def test_editor_normal_gg_moves_to_first_non_blank(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("  aaa\nbbb\nccc\n"), disk_version=None)
    editor.row = 2
    editor.col = 2

    editor.handle_key("g")
    editor.handle_key("g")

    assert (editor.row, editor.col) == (0, 2)


def test_editor_normal_x_deletes_the_character_under_the_cursor(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abc\n"), disk_version=None)

    editor.handle_key("l")
    editor.handle_key("x")
    assert editor.buffer.text() == "ac\n"
    assert editor.col == 1

    editor.handle_key("x")
    assert editor.buffer.text() == "a\n"
    assert editor.col == 0


def test_editor_normal_dd_deletes_lines(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("one\ntwo\nthree\n"), disk_version=None)

    editor.handle_key("d")
    editor.handle_key("d")
    assert editor.buffer.text() == "two\nthree\n"
    assert editor.row == 0

    editor.handle_key("j")
    editor.handle_key("d")
    editor.handle_key("d")
    assert editor.buffer.text() == "two\n"

    editor.handle_key("d")
    editor.handle_key("d")
    assert editor.buffer.text() == "\n"


def test_editor_normal_undo_restores_previous_state(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abc\n"), disk_version=None)

    editor.handle_key("x")
    assert editor.buffer.text() == "bc\n"

    editor.handle_key("u")
    assert editor.buffer.text() == "abc\n"

    editor.handle_key("u")
    assert "Already at oldest change" in editor.message


def test_editor_normal_reports_invalid_sequences(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abc\n"), disk_version=None)

    editor.handle_key("g")
    editor.handle_key("x")

    assert "Invalid key sequence" in editor.message
    assert editor.buffer.text() == "abc\n"


def test_editor_normal_discards_stale_sequences_after_timeout(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("aaa\nbbb\nccc\n"), disk_version=None)
    editor.sequence_timeout = -1

    editor.handle_key("g")
    editor.handle_key("j")

    assert editor.row == 1
    assert editor.message == ""


def test_render_status_shows_mode(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abc\n"), disk_version=None)

    frame = render(editor, 4, 60)
    assert "NORMAL" in frame.lines[frame.status_row]

    editor.handle_key("i")
    frame = render(editor, 4, 60)
    assert "INSERT" in frame.lines[frame.status_row]


def run_prompt(editor: Editor, prompt: str, text: str) -> None:
    editor.handle_key(prompt)
    for char in text:
        editor.handle_key(char)
    editor.handle_key("enter")


def run_command(editor: Editor, text: str) -> None:
    run_prompt(editor, ":", text)


def test_editor_command_save_writes_the_file(tmp_path):
    path = tmp_path / "main.py"
    editor = new_editor(path)
    editor.handle_key("i")
    editor.handle_key("x")
    editor.handle_key("escape")

    run_command(editor, "w")

    assert editor.mode == "normal"
    assert not editor.dirty
    assert path.read_text(encoding="utf-8") == "x\n"


def test_editor_command_quit_refuses_when_dirty(tmp_path):
    path = tmp_path / "main.py"
    editor = new_editor(path)
    editor.handle_key("i")
    editor.handle_key("x")
    editor.handle_key("escape")

    run_command(editor, "q")

    assert editor.running
    assert "No write since last change" in editor.message


def test_editor_command_force_quit_discards_changes(tmp_path):
    path = tmp_path / "main.py"
    editor = new_editor(path)
    editor.handle_key("i")
    editor.handle_key("x")
    editor.handle_key("escape")

    run_command(editor, "q!")

    assert not editor.running
    assert editor.discarded
    assert not path.exists()


def test_editor_command_write_quit_saves_and_exits(tmp_path):
    path = tmp_path / "main.py"
    editor = new_editor(path)
    editor.handle_key("i")
    editor.handle_key("x")
    editor.handle_key("escape")

    run_command(editor, "wq")

    assert not editor.running
    assert not editor.discarded
    assert path.read_text(encoding="utf-8") == "x\n"


def test_editor_command_goto_line_and_last_line(tmp_path):
    path = tmp_path / "main.py"
    text = "".join(f"line{i}\n" for i in range(1, 6))
    editor = Editor(path, TextBuffer.from_text(text), disk_version=None)

    run_command(editor, "4")
    assert editor.row == 3
    assert editor.col == 0

    run_command(editor, "$")
    assert editor.row == 4


def test_editor_command_unknown_reports_message(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abc\n"), disk_version=None)

    run_command(editor, "frobnicate")

    assert "Unknown command" in editor.message


def test_editor_command_escape_cancels(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abc\n"), disk_version=None)

    editor.handle_key(":")
    editor.handle_key("w")
    assert editor.mode == "command"

    editor.handle_key("escape")

    assert editor.mode == "normal"
    assert editor.command == ""


def test_editor_command_backspace_edits_and_exits_when_empty(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abc\n"), disk_version=None)

    editor.handle_key(":")
    editor.handle_key("w")
    editor.handle_key("x")
    editor.handle_key("backspace")
    assert editor.command == "w"

    editor.handle_key("backspace")
    assert editor.command == ""

    editor.handle_key("backspace")
    assert editor.command == ""
    assert editor.mode == "normal"


def test_render_command_line_positions_cursor(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abc\n"), disk_version=None)

    editor.handle_key(":")
    editor.handle_key("w")

    frame = render(editor, 4, 40)
    assert frame.lines[-1] == ":w"
    assert frame.cursor_row == 3
    assert frame.cursor_col == 2


def test_editor_search_moves_to_matching_line(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("alpha\nbeta\ngamma\nbeta again\n"), disk_version=None)

    run_prompt(editor, "/", "beta")

    assert (editor.row, editor.col) == (1, 0)


def test_editor_search_sets_column_to_match(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("xxxxmatch\n"), disk_version=None)

    run_prompt(editor, "/", "match")

    assert (editor.row, editor.col) == (0, 4)


def test_editor_search_repeat_and_reverse(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("x\nmatch\ny\nmatch\n"), disk_version=None)

    run_prompt(editor, "/", "match")
    assert editor.row == 1

    editor.handle_key("n")
    assert editor.row == 3

    editor.handle_key("n")
    assert editor.row == 1

    editor.handle_key("N")
    assert editor.row == 3


def test_editor_empty_search_repeats_last(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("match\nx\nmatch\n"), disk_version=None)

    run_prompt(editor, "/", "match")
    assert editor.row == 2

    run_prompt(editor, "/", "")
    assert editor.row == 0


def test_editor_search_reports_when_not_found(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("alpha\n"), disk_version=None)

    run_prompt(editor, "/", "nope")

    assert "Pattern not found" in editor.message


def test_editor_repeat_search_without_history(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("alpha\n"), disk_version=None)

    editor.handle_key("n")

    assert "No previous search" in editor.message


def test_editor_search_escape_cancels(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("alpha\n"), disk_version=None)

    editor.handle_key("/")
    editor.handle_key("m")
    assert editor.mode == "command"

    editor.handle_key("escape")

    assert editor.mode == "normal"
    assert editor.command == ""
    assert editor.prompt == ""


def test_render_search_line_positions_cursor(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("alpha\n"), disk_version=None)

    editor.handle_key("/")
    editor.handle_key("m")

    frame = render(editor, 4, 40)
    assert frame.lines[-1] == "/m"
    assert frame.cursor_col == 2


def test_editor_yank_line_and_put_below(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("one\ntwo\n"), disk_version=None)

    editor.handle_key("y")
    editor.handle_key("y")
    assert editor.register == ["one"]
    assert editor.register_linewise

    editor.handle_key("p")
    assert editor.buffer.text() == "one\none\ntwo\n"


def test_editor_delete_line_then_put_restores_it(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("one\ntwo\nthree\n"), disk_version=None)

    editor.handle_key("d")
    editor.handle_key("d")
    assert editor.buffer.text() == "two\nthree\n"

    editor.handle_key("p")
    assert editor.buffer.text() == "two\none\nthree\n"


def test_editor_put_above_inserts_before_current_line(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("one\ntwo\n"), disk_version=None)

    editor.handle_key("j")
    editor.handle_key("y")
    editor.handle_key("y")
    editor.handle_key("P")

    assert editor.buffer.text() == "one\ntwo\ntwo\n"


def test_editor_put_with_empty_register_is_noop(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abc\n"), disk_version=None)

    editor.handle_key("p")
    editor.handle_key("P")

    assert editor.buffer.text() == "abc\n"


def test_editor_visual_yank_and_put(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abcdef\n"), disk_version=None)

    editor.handle_key("v")
    assert editor.mode == "visual"
    editor.handle_key("l")
    editor.handle_key("l")
    editor.handle_key("y")

    assert editor.mode == "normal"
    assert editor.register == ["abc"]
    assert not editor.register_linewise

    editor.handle_key("$")
    editor.handle_key("p")
    assert editor.buffer.text() == "abcdefabc\n"


def test_editor_visual_delete_range(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abcdef\n"), disk_version=None)

    editor.handle_key("v")
    editor.handle_key("l")
    editor.handle_key("l")
    editor.handle_key("d")

    assert editor.mode == "normal"
    assert editor.buffer.text() == "def\n"
    assert (editor.row, editor.col) == (0, 0)
    assert editor.register == ["abc"]


def test_editor_visual_multiline_yank(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abc\ndef\nghi\n"), disk_version=None)
    editor.handle_key("l")

    editor.handle_key("v")
    editor.handle_key("j")
    editor.handle_key("y")

    assert editor.register == ["bc", "de"]
    assert not editor.register_linewise


def test_editor_visual_escape_cancels(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abcdef\n"), disk_version=None)

    editor.handle_key("v")
    editor.handle_key("l")
    editor.handle_key("escape")

    assert editor.mode == "normal"
    assert editor.buffer.text() == "abcdef\n"


def test_render_status_shows_visual_mode(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abc\n"), disk_version=None)

    editor.handle_key("v")

    frame = render(editor, 4, 60)
    assert "VISUAL" in frame.lines[frame.status_row]


def test_highlight_keywords_and_comments():
    spans = highlight_line("def main():  # start")

    assert (0, 3, "keyword") in spans
    assert (13, 20, "comment") in spans
    assert spans[-1][2] == "comment"


def test_highlight_builtins_numbers_and_constants():
    spans = highlight_line("pin_mode(13, OUTPUT)")

    assert (0, 8, "builtin") in spans
    assert (9, 11, "number") in spans
    assert (13, 19, "constant") in spans


def test_highlight_strings_and_types():
    spans = highlight_line('x = String("hi")')

    assert (4, 10, "type") in spans
    assert (11, 15, "string") in spans


def test_highlight_numeric_literals():
    spans = highlight_line("x = 0x1F + 3.5")

    assert (4, 8, "number") in spans
    assert (11, 14, "number") in spans


def test_highlight_comment_consumes_rest_of_line():
    line = 'x = 1  # def "str"'
    spans = highlight_line(line)

    assert spans[-1] == (7, len(line), "comment")
    assert not any(kind in ("keyword", "string") for _, _, kind in spans)


def test_render_produces_styles_for_source_lines(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("def main():  # hi\n"), disk_version=None)

    frame = render(editor, 4, 40)

    assert (6, 9, "keyword") in frame.styles[0]
    assert any(kind == "comment" for _, _, kind in frame.styles[0])
    assert frame.styles[-1] == []
    assert len(frame.styles) == len(frame.lines)


def test_render_clips_styles_when_scrolled(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("def main(): 0123456789\n"), disk_version=None)
    editor.col = 15

    frame = render(editor, 3, 20)

    assert editor.left_col == 2
    assert frame.lines[0] == "  1 | f main(): 0123"
    assert (6, 7, "keyword") in frame.styles[0]


def test_render_number_width_grows_with_line_count(tmp_path):
    path = tmp_path / "main.py"
    small = Editor(path, TextBuffer.from_text("alpha\nbeta\n"), disk_version=None)
    large = Editor(path, TextBuffer.from_text("".join(f"l{i}\n" for i in range(1234))), disk_version=None)

    frame = render(small, 4, 40)
    assert frame.lines[0] == "  1 | alpha"

    frame = render(large, 4, 40)
    assert frame.lines[0] == "   1 | l0"


def test_render_numbering_tracks_line_deletion(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("alpha\nbeta\ngamma\n"), disk_version=None)

    frame = render(editor, 5, 30)
    assert frame.lines[0] == "  1 | alpha"
    assert frame.lines[2] == "  3 | gamma"

    editor.handle_key("d")
    editor.handle_key("d")

    frame = render(editor, 5, 30)
    assert frame.lines[0] == "  1 | beta"
    assert frame.lines[1] == "  2 | gamma"
    assert frame.lines[2] == ""


def test_render_hides_gutter_when_columns_are_too_narrow(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abc\n"), disk_version=None)

    frame = render(editor, 3, 5)
    assert frame.lines[0] == "abc"
    assert frame.cursor_col == 0


def test_render_highlight_row_tracks_the_cursor(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("alpha\nbeta\ngamma\n"), disk_version=None)
    editor.row = 1

    frame = render(editor, 5, 30)
    assert frame.highlight_row == 1
    assert frame.cursor_row == 1

    editor.mode = "command"
    frame = render(editor, 5, 30)
    assert frame.highlight_row == -1


def test_render_cursor_column_accounts_for_gutter_and_tabs(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("\tab\n"), disk_version=None)
    editor.col = 1

    frame = render(editor, 3, 30)
    assert frame.lines[0] == "  1 |     ab"
    assert frame.cursor_col == 10


def test_render_status_reports_line_and_column(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("alpha\nbeta\ngamma\n"), disk_version=None)
    editor.row = 2
    editor.col = 3

    frame = render(editor, 5, 60)
    assert "Line 3, Col 4" in frame.lines[frame.status_row]


def test_render_scrolls_horizontally_to_keep_cursor_visible(tmp_path):
    path = tmp_path / "main.py"
    long_line = "".join(str(i % 10) for i in range(60))
    editor = Editor(path, TextBuffer.from_text(long_line + "\n"), disk_version=None)
    editor.col = 55

    frame = render(editor, 3, 20)
    assert editor.left_col > 0
    assert frame.cursor_col <= 19
    assert frame.lines[0].startswith("  1 | ")
    assert len(frame.lines[0]) <= 20

    editor.col = 0
    frame = render(editor, 3, 20)
    assert editor.left_col == 0
    assert frame.cursor_col == 6


def test_render_keeps_gutter_while_in_command_mode(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("alpha\n"), disk_version=None)
    editor.mode = "command"

    frame = render(editor, 3, 30)
    assert frame.lines[0] == "  1 | alpha"
    assert frame.highlight_row == -1


def test_gutter_and_cursor_are_not_written_to_disk(tmp_path, monkeypatch):
    path = tmp_path / "main.py"
    path.write_text("alpha\n", encoding="utf-8")
    monkeypatch.setattr(edit_module, "Terminal", lambda: FakeScreen(["l", "i", "z", "ctrl+s", "ctrl+q"]))

    code = main(["edit", str(path)])

    assert code == EXIT_OK
    assert path.read_text(encoding="utf-8") == "azlpha\n"


def test_apply_styles_wraps_spans_with_colour_codes():
    styled = apply_styles("def x", [(0, 3, "keyword")])

    assert styled == "\x1b[1;34mdef\x1b[22;39m x"
    assert apply_styles("plain", []) == "plain"


def test_terminal_draw_emits_style_codes():
    out = io.StringIO()
    terminal = Terminal(stdin=sys.stdin, stdout=out)
    frame = Frame(["def x"], 0, 0, [[(0, 3, "keyword")]], -1, -1, -1, "idle")

    terminal.draw(frame)

    rendered = out.getvalue()
    assert "\x1b[1;34m" in rendered
    assert "def" in rendered
    assert "\x1b[0m" in rendered


def test_render_command_area_is_its_own_bottom_row(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("alpha\n"), disk_version=None)

    frame = render(editor, 6, 40)
    assert frame.command_row == len(frame.lines) - 1
    assert frame.status_row == frame.command_row - 1
    assert frame.lines[frame.command_row] == ""
    assert frame.lines[frame.status_row] != ""
    assert frame.command_kind == "idle"

    editor.handle_key(":")
    editor.handle_key("w")
    frame = render(editor, 6, 40)
    assert frame.lines[frame.command_row] == ":w"
    assert frame.command_kind == "prompt"
    assert frame.cursor_row == frame.command_row
    assert frame.cursor_col == 2


def test_render_error_message_uses_error_kind(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("alpha\n"), disk_version=None)

    run_command(editor, "bogus")
    frame = render(editor, 4, 60)
    assert frame.command_kind == "error"
    assert "Unknown command" in frame.lines[frame.command_row]

    editor.message = "ok"
    editor.error = False
    frame = render(editor, 4, 60)
    assert frame.command_kind == "message"


def test_render_command_area_stays_at_the_bottom_on_resize(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("alpha\nbeta\n"), disk_version=None)
    editor.handle_key(":")
    editor.handle_key("w")

    for rows, cols in ((4, 20), (8, 60), (3, 10), (2, 12), (1, 8)):
        frame = render(editor, rows, cols)
        assert frame.command_row == len(frame.lines) - 1
        assert frame.cursor_row == frame.command_row
        assert frame.cursor_col <= cols - 1

    editor.handle_key("escape")


def test_render_command_area_does_not_overlap_source(tmp_path):
    path = tmp_path / "main.py"
    text = "".join(f"line{i}\n" for i in range(20))
    editor = Editor(path, TextBuffer.from_text(text), disk_version=None)
    editor.handle_key(":")
    editor.handle_key("w")

    frame = render(editor, 6, 40)
    assert frame.highlight_row == -1
    assert frame.lines[frame.command_row].startswith(":")
    for row in range(frame.status_row):
        assert not frame.lines[row].startswith(":")


def test_terminal_draw_styles_the_command_bar():
    out = io.StringIO()
    terminal = Terminal(stdin=sys.stdin, stdout=out)
    frame = Frame(["alpha", "status", ":w"], 2, 2, [[], [], []], -1, 1, 2, "prompt")

    terminal.draw(frame)

    rendered = out.getvalue()
    assert "\x1b[48;5;24m" in rendered
    assert "\x1b[1;97m:" in rendered
    assert "w" in rendered


def test_terminal_draw_styles_error_and_message_bars():
    out = io.StringIO()
    terminal = Terminal(stdin=sys.stdin, stdout=out)
    terminal.draw(Frame(["alpha", "status", " bad"], 0, 0, [[], [], []], -1, 1, 2, "error"))
    assert "\x1b[48;5;124m" in out.getvalue()

    out = io.StringIO()
    terminal = Terminal(stdin=sys.stdin, stdout=out)
    terminal.draw(Frame(["alpha", "status", " ok"], 0, 0, [[], [], []], -1, 1, 2, "message"))
    assert "\x1b[48;5;136m" in out.getvalue()


def test_terminal_draw_styles_the_status_bar():
    out = io.StringIO()
    terminal = Terminal(stdin=sys.stdin, stdout=out)
    frame = Frame(["alpha", " main.py", ""], 0, 0, [[], [], []], -1, 1, 2, "idle")

    terminal.draw(frame)

    assert "\x1b[48;5;238m" in out.getvalue()


def test_parse_key_reads_named_keys():
    assert parse_key(b"a") == ("a", 1)
    assert parse_key(b"\x13") == ("ctrl+s", 1)
    assert parse_key(b"\r") == ("enter", 1)
    assert parse_key(b"\x7f") == ("backspace", 1)
    assert parse_key(b"\x1b[A") == ("up", 3)
    assert parse_key(b"\x1b[3~") == ("delete", 4)
    assert parse_key(b"\xc3\xa9") == ("é", 2)
    assert parse_key(b"") == (None, 0)
    assert parse_key(b"\x1b") == (None, 0)


def test_parse_key_ignores_unknown_sequences():
    assert parse_key(b"\x1b[99~") == ("", 5)
    assert parse_key(b"\x1bzx") == ("", 2)


def test_parse_keys_returns_complete_keys_and_leftovers():
    keys, rest = parse_keys(b"\x1b[Ax\x1b")
    assert keys == ["up", "x"]
    assert rest == b"\x1b"

    keys, rest = parse_keys(b"\xc3")
    assert keys == []
    assert rest == b"\xc3"


def test_cmd_edit_rejects_a_directory(tmp_path, capsys):
    code = main(["edit", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == EXIT_USAGE
    assert "is a directory" in captured.err


def test_cmd_edit_rejects_a_missing_parent_directory(tmp_path, capsys):
    code = main(["edit", str(tmp_path / "missing" / "main.py")])
    captured = capsys.readouterr()
    assert code == EXIT_USAGE
    assert "does not exist" in captured.err


def test_cmd_edit_rejects_invalid_utf8(tmp_path, capsys):
    path = tmp_path / "main.py"
    path.write_bytes(b"\xff\xfe\x00")
    code = main(["edit", str(path)])
    captured = capsys.readouterr()
    assert code == EXIT_USAGE
    assert "UTF-8" in captured.err


def test_cmd_edit_requires_an_interactive_terminal(tmp_path, capsys):
    path = tmp_path / "main.py"
    path.write_text("a\n", encoding="utf-8")
    code = main(["edit", str(path)])
    captured = capsys.readouterr()
    assert code == EXIT_USAGE
    assert "interactive terminal" in captured.err


def test_cmd_edit_creates_and_saves_a_new_file(tmp_path, monkeypatch):
    path = tmp_path / "new.py"
    monkeypatch.setattr(edit_module, "Terminal", lambda: FakeScreen(["i", "h", "i", "ctrl+s", "ctrl+q"]))

    code = main(["edit", str(path)])

    assert code == EXIT_OK
    assert path.read_text(encoding="utf-8") == "hi\n"


def test_cmd_edit_round_trips_a_program_without_changes(tmp_path, monkeypatch):
    path = tmp_path / "main.py"
    path.write_text(PROGRAM, encoding="utf-8")
    monkeypatch.setattr(edit_module, "Terminal", lambda: FakeScreen(["ctrl+q"]))

    code = main(["edit", str(path)])

    assert code == EXIT_OK
    assert path.read_text(encoding="utf-8") == PROGRAM


def test_cmd_edit_reports_discarded_changes(tmp_path, monkeypatch, capsys):
    path = tmp_path / "main.py"
    path.write_text("a\n", encoding="utf-8")
    monkeypatch.setattr(edit_module, "Terminal", lambda: FakeScreen(["i", "z", "ctrl+q", "ctrl+q"]))

    code = main(["edit", str(path)])

    captured = capsys.readouterr()
    assert code == EXIT_OK
    assert "Discarded unsaved changes" in captured.err
    assert path.read_text(encoding="utf-8") == "a\n"
