"""Registry that maps micropy imports to Arduino C++ libraries.

``from micropy import Servo`` emits ``#include <Servo.h>`` and makes ``Servo``
a known C++ type, e.g. ``servo = Servo()`` becomes ``Servo servo;``.  Only
libraries that ship with the Arduino AVR core are listed; their APIs are not
translated, calls are passed through unchanged (``servo.attach(9)``).

This is the extension point for future Arduino library support: add an entry
here instead of teaching the compiler about individual libraries.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional

__all__ = ["Library", "LIBRARIES", "API_IMPORT_MODULES", "library_for", "supported_libraries"]

@dataclass(frozen=True)
class Library:
    name: str
    header: str
    cpp_type: Optional[str] = None

LIBRARIES: Dict[str, Library] = {
    "Servo": Library("Servo", "Servo.h", "Servo"),
    "SoftwareSerial": Library("SoftwareSerial", "SoftwareSerial.h", "SoftwareSerial"),
    "LiquidCrystal": Library("LiquidCrystal", "LiquidCrystal.h", "LiquidCrystal"),
    "Wire": Library("Wire", "Wire.h"),
    "SPI": Library("SPI", "SPI.h"),
    "EEPROM": Library("EEPROM", "EEPROM.h"),
}

API_IMPORT_MODULES = frozenset(
    {
        "builtins",
        "micropy",
        "micropy.runtime",
        "micropy_api",
        "arduinopy",
        "arduinopy.runtime",
        "arduino_py",
    }
)

def library_for(name: str) -> Optional[Library]:
    return LIBRARIES.get(name)

def supported_libraries() -> Dict[str, Library]:
    return dict(LIBRARIES)