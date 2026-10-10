from __future__ import annotations

from typing import List, Optional, Tuple

__all__ = ["Span", "highlight_line"]

Span = Tuple[int, int, str]

KEYWORDS = frozenset(
    {
        "and",
        "as",
        "assert",
        "async",
        "await",
        "break",
        "class",
        "continue",
        "def",
        "del",
        "elif",
        "else",
        "except",
        "finally",
        "for",
        "from",
        "global",
        "if",
        "import",
        "in",
        "is",
        "lambda",
        "nonlocal",
        "not",
        "or",
        "pass",
        "raise",
        "return",
        "try",
        "while",
        "with",
        "yield",
        "True",
        "False",
        "None",
    }
)

BUILTINS = frozenset(
    {
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
        "serial_end",
        "serial_flush",
        "serial_available",
        "serial_read",
        "serial_print",
        "serial_println",
        "abs",
        "min",
        "max",
        "constrain",
        "pow",
        "sqrt",
        "floor",
        "ceil",
        "round",
        "print",
        "len",
        "range",
        "int",
        "float",
        "str",
        "bool",
        "list",
        "dict",
        "tuple",
        "enumerate",
        "zip",
        "input",
        "map",
        "filter",
        "sum",
        "sorted",
        "reversed",
        "any",
        "all",
        "isinstance",
        "repr",
        "format",
    }
)

CONSTANTS = frozenset(
    {
        "OUTPUT",
        "INPUT",
        "INPUT_PULLUP",
        "INPUT_PULLDOWN",
        "HIGH",
        "LOW",
        "CHANGE",
        "RISING",
        "FALLING",
        "LED_BUILTIN",
        "A0",
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
    }
)

TYPES = frozenset(
    {
        "String",
        "Servo",
        "SoftwareSerial",
        "LiquidCrystal",
        "Wire",
        "SPI",
        "EEPROM",
    }
)

_TRIPLE_QUOTES = ('"""', "'''")


def highlight_line(line: str) -> List[Span]:
    spans: List[Span] = []
    index = 0
    length = len(line)
    while index < length:
        char = line[index]
        if char == "#":
            spans.append((index, length, "comment"))

            break

        if char in ('"', "'"):
            index = _scan_string(line, index, spans)

            continue

        if char.isdigit():
            start = index
            index = _scan_number(line, index)
            spans.append((start, index, "number"))

            continue

        if char.isalpha() or char == "_":
            start = index
            while index < length and (line[index].isalnum() or line[index] == "_"):
                index += 1
            kind = _classify(line[start:index])
            if kind is not None:
                spans.append((start, index, kind))

            continue

        index += 1

    return spans


def _scan_string(line: str, index: int, spans: List[Span]) -> int:
    length = len(line)
    delimiter = line[index : index + 3]
    if delimiter in _TRIPLE_QUOTES:
        end = line.find(delimiter, index + 3)
        if end == -1:
            spans.append((index, length, "string"))

            return length

        spans.append((index, end + 3, "string"))

        return end + 3

    quote = line[index]
    cursor = index + 1
    while cursor < length:
        if line[cursor] == "\\":
            cursor += 2

            continue

        if line[cursor] == quote:
            cursor += 1

            break

        cursor += 1

    cursor = min(cursor, length)
    spans.append((index, cursor, "string"))

    return cursor


def _scan_number(line: str, index: int) -> int:
    length = len(line)
    if line[index : index + 2].lower() in ("0x", "0b", "0o"):
        index += 2
    while index < length and (line[index].isalnum() or line[index] in "._"):
        index += 1

    return index


def _classify(word: str) -> Optional[str]:
    if word in KEYWORDS:
        return "keyword"

    if word in CONSTANTS:
        return "constant"

    if word in TYPES:
        return "type"

    if word in BUILTINS:
        return "builtin"

    return None
