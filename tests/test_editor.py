from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

import pytest

from controllerpy.cli import EXIT_OK, EXIT_USAGE, main
from controllerpy.cli.commands import edit as edit_module
from controllerpy.cli.editor import Editor, TextBuffer, render, run_editor
from controllerpy.cli.editor.keys import parse_key, parse_keys

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

    editor.handle_key("x")
    assert editor.dirty

    editor.handle_key("ctrl+s")
    assert not editor.dirty
    assert path.read_text(encoding="utf-8") == "xa\n"


def test_editor_inserts_printable_keys_and_enter(tmp_path):
    path = tmp_path / "main.py"
    editor = new_editor(path)

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
    assert (editor.row, editor.col) == (0, 3)

    editor.handle_key("down")
    assert (editor.row, editor.col) == (1, 2)

    editor.handle_key("down")
    assert (editor.row, editor.col) == (1, 2)

    editor.handle_key("up")
    editor.handle_key("up")
    assert (editor.row, editor.col) == (0, 2)

    editor.handle_key("left")
    editor.handle_key("left")
    editor.handle_key("left")
    editor.handle_key("left")
    assert (editor.row, editor.col) == (0, 0)

    editor.handle_key("end")
    assert editor.col == 3
    editor.handle_key("home")
    assert editor.col == 0


def test_editor_backspace_and_delete_join_lines(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("ab\ncd\n"), disk_version=None)

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
    screen = FakeScreen(["a", "enter", "b", "ctrl+s", "ctrl+q"])

    run_editor(editor, screen)

    assert not editor.running
    assert path.read_text(encoding="utf-8") == "a\nb\n"
    assert screen.frames
    assert "written" in screen.frames[-1].lines[-1]
    assert any("main.py" in frame.lines[-1] for frame in screen.frames)


def test_render_layout_and_status(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abc\n"), disk_version=None)

    frame = render(editor, 4, 30)
    assert frame.lines[0] == "abc"
    assert frame.lines[1] == ""
    assert "main.py" in frame.lines[-1]
    assert "1:1" in frame.lines[-1]
    assert frame.cursor_row == 0
    assert frame.cursor_col == 0

    editor.message = "hello"
    frame = render(editor, 4, 30)
    assert frame.lines[-1] == " hello"


def test_render_expands_tabs_for_display(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("\tx\n"), disk_version=None)

    frame = render(editor, 3, 20)
    assert frame.lines[0] == "    x"

    editor.col = 1
    frame = render(editor, 3, 20)
    assert frame.cursor_col == 4


def test_render_keeps_cursor_visible_while_scrolling(tmp_path):
    path = tmp_path / "main.py"
    lines = "".join(f"line{i}\n" for i in range(50))
    editor = Editor(path, TextBuffer.from_text(lines), disk_version=None)
    editor.row = 40

    frame = render(editor, 10, 30)
    assert editor.top_row == 32
    assert frame.cursor_row == 8
    assert "line40" in frame.lines[8]

    editor.row = 0
    frame = render(editor, 10, 30)
    assert editor.top_row == 0
    assert frame.cursor_row == 0


def test_render_clips_to_small_terminals(tmp_path):
    path = tmp_path / "main.py"
    editor = Editor(path, TextBuffer.from_text("abcdef\n"), disk_version=None)
    editor.col = 6

    frame = render(editor, 3, 4)
    assert frame.lines[0] == "abcd"
    assert len(frame.lines) == 3

    frame = render(editor, 1, 4)
    assert len(frame.lines) == 1
    assert frame.cursor_col <= 3

    frame = render(editor, 0, 0)
    assert len(frame.lines) == 1
    assert frame.cursor_col == 0


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
    monkeypatch.setattr(edit_module, "Terminal", lambda: FakeScreen(["h", "i", "ctrl+s", "ctrl+q"]))

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
    monkeypatch.setattr(edit_module, "Terminal", lambda: FakeScreen(["z", "ctrl+q", "ctrl+q"]))

    code = main(["edit", str(path)])

    captured = capsys.readouterr()
    assert code == EXIT_OK
    assert "Discarded unsaved changes" in captured.err
    assert path.read_text(encoding="utf-8") == "a\n"
