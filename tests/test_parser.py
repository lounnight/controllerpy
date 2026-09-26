"""Stage 1: parsing Python source into an AST."""

from __future__ import annotations

import ast

import pytest

from micropy.compiler import parse_source
from micropy.errors import MicropyError
from micropy.compiler.parser import SourceFile, parse_file

SIMPLE = "LED = 13\n\ndef main():\n    pass\n\ndef loop():\n    pass\n"


def test_parse_source_returns_module():
    tree = parse_source(SIMPLE, "main.py")
    assert isinstance(tree, ast.Module)
    assert [type(node).__name__ for node in tree.body] == ["Assign", "FunctionDef", "FunctionDef"]


def test_parse_source_keeps_location_information():
    tree = parse_source(SIMPLE, "main.py")
    assignment = tree.body[0]
    assert assignment.lineno == 1
    assert assignment.col_offset == 0
    main_function = tree.body[1]
    assert (main_function.name, main_function.lineno) == ("main", 3)


def test_parse_source_does_not_execute_user_code():
    # `raise` at import time would blow up a naive importer; parsing is safe.
    tree = parse_source("raise RuntimeError('boom')\n", "main.py")
    assert isinstance(tree.body[0], ast.Raise)


def test_parse_source_uses_ast_constant_nodes_only():
    tree = parse_source("x = 1\ny = 2.5\nz = True\ns = 'hi'\n", "main.py")
    values = [node.value.value for node in tree.body]
    assert values == [1, 2.5, True, "hi"]
    assert all(isinstance(node.value, ast.Constant) for node in tree.body)


def test_syntax_error_is_reported_with_location():
    with pytest.raises(MicropyError) as caught:
        parse_source("def main(:\n    pass\n", "main.py")
    assert "Invalid Python syntax" in caught.value.message
    assert caught.value.filename == "main.py"
    assert caught.value.line == 1
    assert caught.value.col == 10


def test_indentation_error_is_a_micropy_error():
    with pytest.raises(MicropyError) as caught:
        parse_source("def main():\npass\n", "main.py")
    assert "Invalid Python syntax" in caught.value.message
    assert caught.value.line == 2


def test_null_bytes_are_reported_cleanly():
    with pytest.raises(MicropyError) as caught:
        parse_source("x = 1\n\x00\n", "main.py")
    assert "main.py" in caught.value.format()


def test_source_file_helpers():
    source = SourceFile("main.py", SIMPLE)
    assert source.lines[0] == "LED = 13"
    assert source.line(3) == "def main():"
    assert source.line(999) == ""


def test_parse_file_reads_from_disk(tmp_path):
    path = tmp_path / "blink.py"
    path.write_text(SIMPLE, encoding="utf-8")
    source, tree = parse_file(path)
    assert source.filename == str(path)
    assert isinstance(tree, ast.Module)


def test_parse_file_reports_missing_file():
    with pytest.raises(MicropyError) as caught:
        parse_file("does-not-exist.py")
    assert "Source file not found" in caught.value.message


def test_parse_file_rejects_directories(tmp_path):
    with pytest.raises(MicropyError) as caught:
        parse_file(tmp_path)
    assert "is a directory" in caught.value.message
