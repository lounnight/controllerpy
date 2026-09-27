"""Registry that maps controllerpy imports to Arduino C++ libraries.

``from controllerpy import Servo`` emits ``#include <Servo.h>`` and makes ``Servo``
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

A method or a constructor describes the types it accepts in ``params`` /
``ctor_params``, and describing them is optional: an entry that leaves them out
has its arity checked and nothing else, so a library is described as far as it
is known to be.  The types are listed one per argument, which means an
overloaded method is described by the parameters of a single one of its
signatures at most - the rest is left to C++.

A library the Arduino core happens to provide as an object that is always there
(``Wire.begin()`` needs no import) is registered like any other library and
marked ``core``; :data:`CORE_OBJECTS` is derived from the registrations, so what
the core provides is described once, here.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional, Tuple
__all__ = ["ApiClass", "ApiMethod", "Library", "LIBRARIES", "API_IMPORT_MODULES", "CORE_OBJECTS", "library_for", "supported_libraries"]

@dataclass(frozen=True)
class ApiMethod:
    py_name: str
    min_args: int
    max_args: int
    returns: str = "void"
    cpp_name: Optional[str] = None
    params: Tuple[str, ...] = ()

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
    ctor_params: Tuple[str, ...] = ()

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
    core: bool = False

    def class_named(self, name: str) -> Optional[ApiClass]:
        for candidate in self.classes:
            if candidate.name == name:
                return candidate

        return None

    def class_of_type(self, cpp_type: str) -> Optional[ApiClass]:
        for candidate in self.classes:
            if candidate.cpp_type == cpp_type:
                return candidate

        return None

LIBRARIES: Dict[str, Library] = {
    "Servo": Library(
        "Servo",
        "Servo.h",
        "Servo",
        module="servo",
        classes=(
            ApiClass(
                "Servo",
                "Servo",
                methods=(
                    ApiMethod("attach", 1, 3, "int"),
                    ApiMethod("detach", 0, 0),
                    ApiMethod("write", 1, 1),
                    ApiMethod("read", 0, 0, "int"),
                ),
            ),
        ),
    ),
    "SoftwareSerial": Library("SoftwareSerial", "SoftwareSerial.h", "SoftwareSerial"),
    "LiquidCrystal": Library("LiquidCrystal", "LiquidCrystal.h", "LiquidCrystal"),
    "Wire": Library("Wire", "Wire.h", core=True),
    "SPI": Library("SPI", "SPI.h", core=True),
    "EEPROM": Library("EEPROM", "EEPROM.h", core=True),
}

CORE_OBJECTS: FrozenSet[str] = frozenset(name for name, library in LIBRARIES.items() if library.core)

API_IMPORT_MODULES = frozenset(
    {
        "builtins",
        "controllerpy",
        "controllerpy.runtime",
        "controllerpy_api",
        "arduinopy",
        "arduinopy.runtime",
        "arduino_py",
    }
)

def library_for(name: str) -> Optional[Library]:
    library = LIBRARIES.get(name)
    if library is not None:
        return library
    for candidate in LIBRARIES.values():
        if candidate.class_named(name) is not None:
            return candidate

    return None

def supported_libraries() -> Dict[str, Library]:
    return dict(LIBRARIES)