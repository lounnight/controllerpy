"""Every shipped example must compile to its reviewed C++ snapshot."""

from __future__ import annotations

from pathlib import Path

import pytest

from micropy.compiler import compile_source

ROOT = Path(__file__).resolve().parents[1]
#: Every example is an initialized project: ``examples/<name>/main.py``.
EXAMPLES = sorted((ROOT / "examples").glob("*/main.py"))
PROGRAMS = EXAMPLES + [ROOT / "main.py"]


def example_name(path: Path) -> str:
    """Snapshot/id key: ``examples/button/main.py`` -> ``button``, root ``main.py`` -> ``main``."""

    return path.parent.name if path.parent != ROOT else path.stem

ACCEPTANCE = '''LED = 13
BUTTON = 7

def setup_led():
    pin_mode(LED, OUTPUT)

def main():
    setup_led()
    pin_mode(BUTTON, INPUT_PULLUP)
    serial_begin(9600)

def loop():
    if digital_read(BUTTON) == LOW:
        digital_write(LED, HIGH)
        serial_println("ON")
    else:
        digital_write(LED, LOW)

    delay(50)
'''


def test_the_example_directory_is_not_empty():
    assert EXAMPLES, "examples/ should contain at least the blink, button and loops projects"
    names = {example_name(path) for path in EXAMPLES}
    assert {"blink", "button", "loops"} <= names


@pytest.mark.parametrize("path", PROGRAMS, ids=example_name)
def test_example_matches_its_expected_cpp(path, expected_cpp):
    source = path.read_text(encoding="utf-8")
    result = compile_source(source, filename=path.name)
    assert result.cpp == expected_cpp(example_name(path))


@pytest.mark.parametrize("path", PROGRAMS, ids=example_name)
def test_example_defines_both_entry_points(path):
    result = compile_source(path.read_text(encoding="utf-8"), filename=path.name)
    assert result.context.setup_node is not None
    assert result.context.loop_node is not None
    assert "void setup() {" in result.cpp
    assert "void loop() {" in result.cpp


@pytest.mark.parametrize("path", PROGRAMS, ids=example_name)
def test_example_output_is_readable_cpp(path):
    cpp = compile_source(path.read_text(encoding="utf-8"), filename=path.name).cpp
    assert "#include <Arduino.h>" not in cpp
    assert cpp.endswith("}\n")
    assert "\t" not in cpp
    assert "\n\n\n" not in cpp
    assert "None" not in cpp
    assert "unknown " not in cpp


@pytest.mark.parametrize("path", PROGRAMS, ids=example_name)
def test_example_compilation_is_deterministic(path):
    source = path.read_text(encoding="utf-8")
    first = compile_source(source, filename=path.name).cpp
    second = compile_source(source, filename=path.name).cpp
    assert first == second


def test_acceptance_program_from_the_spec(result):
    compiled = result(ACCEPTANCE)
    assert compiled.cpp == (
        "const int LED = 13;\n"
        "const int BUTTON = 7;\n"
        "\n"
        "void setup_led();\n"
        "\n"
        "void setup_led() {\n"
        "    pinMode(LED, OUTPUT);\n"
        "}\n"
        "\n"
        "void setup() {\n"
        "    setup_led();\n"
        "    pinMode(BUTTON, INPUT_PULLUP);\n"
        "    Serial.begin(9600);\n"
        "}\n"
        "\n"
        "void loop() {\n"
        "    if (digitalRead(BUTTON) == LOW) {\n"
        "        digitalWrite(LED, HIGH);\n"
        '        Serial.println("ON");\n'
        "    } else {\n"
        "        digitalWrite(LED, LOW);\n"
        "    }\n"
        "\n"
        "    delay(50);\n"
        "}\n"
    )


def test_core_concept_program_from_the_spec(result):
    source = '''LED = 13
BUTTON = 7

def main():
    pin_mode(LED, OUTPUT)
    pin_mode(BUTTON, INPUT_PULLUP)

def loop():
    if digital_read(BUTTON) == LOW:
        digital_write(LED, HIGH)
    else:
        digital_write(LED, LOW)

    delay(50)
'''
    assert result(source).cpp == (
        "const int LED = 13;\n"
        "const int BUTTON = 7;\n"
        "\n"
        "void setup() {\n"
        "    pinMode(LED, OUTPUT);\n"
        "    pinMode(BUTTON, INPUT_PULLUP);\n"
        "}\n"
        "\n"
        "void loop() {\n"
        "    if (digitalRead(BUTTON) == LOW) {\n"
        "        digitalWrite(LED, HIGH);\n"
        "    } else {\n"
        "        digitalWrite(LED, LOW);\n"
        "    }\n"
        "\n"
        "    delay(50);\n"
        "}\n"
    )
