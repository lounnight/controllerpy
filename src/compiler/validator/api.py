"""The Arduino API micropy exposes to programs.

These tables are the single description of the *Arduino* side of the language:
which Python helper functions exist, what they map to in C++, which constants
the core defines and which of them are just passed through.  Validation,
code generation and error hints all read them, so the supported surface is
described in exactly one place.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

__all__ = [
    "ApiFunction",
    "API_FUNCTIONS",
    "ARDUINO_CONSTANTS",
    "ARDUINO_OBJECTS",
    "BUILTIN_FUNCTIONS",
    "PYTHON_BUILTIN_HINTS",
]


#: Arduino constants are passed through unchanged - never folded into numbers -
#: so the generated code stays readable.
ARDUINO_CONSTANTS = frozenset(
    {
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
        "LSBFIRST",
        "MSBFIRST",
        "DEC",
        "HEX",
        "OCT",
        "BIN",
        "PI",
    }
)

#: Objects declared by the Arduino core itself (methods are passed through).
ARDUINO_OBJECTS = frozenset({"Serial", "Wire", "SPI", "EEPROM"})


@dataclass(frozen=True)
class ApiFunction:
    """A micropy helper function and the C++ call it maps to."""

    py_name: str
    cpp_name: str
    min_args: int
    max_args: int
    returns: str = "void"
    receiver: Optional[str] = None

    @property
    def cpp_member(self) -> str:
        """The C++ function name (``Serial.begin`` -> ``begin``)."""

        return self.cpp_name.split(".")[-1]

    def doc(self) -> str:
        return f"{self.py_name}() -> {self.cpp_name}()"


def _api(
    py_name: str,
    cpp_name: str,
    min_args: int,
    max_args: int,
    returns: str = "void",
    receiver: Optional[str] = None,
) -> ApiFunction:
    return ApiFunction(py_name, cpp_name, min_args, max_args, returns, receiver)


API_FUNCTIONS: Dict[str, ApiFunction] = {
    fn.py_name: fn
    for fn in (
        _api("pin_mode", "pinMode", 2, 2),
        _api("digital_write", "digitalWrite", 2, 2),
        _api("digital_read", "digitalRead", 1, 1, "int"),
        _api("analog_read", "analogRead", 1, 1, "int"),
        _api("analog_write", "analogWrite", 2, 2),
        _api("delay", "delay", 1, 1),
        _api("delay_microseconds", "delayMicroseconds", 1, 1),
        _api("millis", "millis", 0, 0, "int"),
        _api("micros", "micros", 0, 0, "int"),
        _api("pulseIn", "pulseIn", 2, 3, "long"),
        _api("serial_begin", "begin", 1, 1, receiver="Serial"),
        _api("serial_end", "end", 0, 0, receiver="Serial"),
        _api("serial_flush", "flush", 0, 0, receiver="Serial"),
        _api("serial_print", "print", 1, 2, receiver="Serial"),
        _api("serial_println", "println", 0, 2, receiver="Serial"),
        _api("serial_available", "available", 0, 0, "int", receiver="Serial"),
        _api("serial_read", "read", 0, 0, "int", receiver="Serial"),
    )
}

BUILTIN_FUNCTIONS: Dict[str, str] = {
    "abs": "abs",
    "min": "min",
    "max": "max",
    "constrain": "constrain",
    "pow": "pow",
    "sqrt": "sqrt",
    "floor": "floor",
    "ceil": "ceil",
    "round": "round",
}

PYTHON_BUILTIN_HINTS: Dict[str, str] = {
    "print": "use serial_println() to print over the serial port",
    "input": "read user input with serial_read() / serial_available()",
    "open": "files are not available on Arduino",
    "sleep": "use delay(milliseconds)",
    "type": "types are not available at runtime on Arduino",
    "isinstance": "types are not available at runtime on Arduino",
    "enumerate": "use for i in range(...)",
    "zip": "not available on Arduino",
    "map": "not available on Arduino",
    "filter": "not available on Arduino",
    "sum": "accumulate a variable in a loop instead",
    "sorted": "not available on Arduino",
    "format": "use serial_print() with separate values",
    "super": "class inheritance is not supported",
}
