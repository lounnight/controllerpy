"""Registry that maps micropy imports to Arduino C++ libraries.

``from micropy import Servo`` emits ``#include <Servo.h>`` and makes ``Servo``
a known C++ type, e.g. ``servo = Servo()`` becomes ``Servo servo;``.  Only
libraries that ship with the Arduino AVR core are listed; an API that is not
described here is passed through unchanged (``servo.attach(9)``).

This is the extension point for future Arduino library support: add an entry
here instead of teaching the compiler about individual libraries.  A library
describes everything it contributes to the generated C++ - the header to
include, the classes it provides and, per class, the constructor and the
methods with the C++ call each one maps to - so the whole description of a
library is one entry.

This module is a leaf of the package: it holds data, looks names up, and
imports nothing from the rest of the compiler.  The types stored on
:class:`ApiMethod` and :class:`ApiClass` are the C++ type strings the type
system works with (``int``, ``float``, ``bool``, ``String``, ``void``).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

__all__ = ["ApiClass", "ApiMethod", "Library", "LIBRARIES", "API_IMPORT_MODULES", "library_for", "supported_libraries"]

@dataclass(frozen=True)
class ApiMethod:
    py_name: str
    min_args: int
    max_args: int
    returns: str = "void"
    cpp_name: Optional[str] = None

    @property
    def cpp_method(self) -> str:
        return self.cpp_name or self.py_name

@dataclass(frozen=True)
class ApiClass:
    name: str
    cpp_type: str
    methods: Tuple[ApiMethod, ...] = ()
    ctor_min_args: int = 0
    ctor_max_args: int = 0

    def method(self, py_name: str) -> Optional[ApiMethod]:
        for candidate in self.methods:
            if candidate.py_name == py_name:
                return candidate

        return None

@dataclass(frozen=True)
class Library:
    name: str
    header: str
    cpp_type: Optional[str] = None
    
    module: Optional[str] = None
    classes: Tuple[ApiClass, ...] = ()

    def class_named(self, name: str) -> Optional[ApiClass]:
        for candidate in self.classes:
            if candidate.name == name:
                return candidate

        return None

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