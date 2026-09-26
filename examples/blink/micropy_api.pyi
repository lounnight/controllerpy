"""Type stubs for the micropy API - IDE/type-checker support only.

This file is never uploaded to the Arduino and is never imported while
compiling.  Run ``micropy init`` to copy it into a project next to
``pyrightconfig.json`` and ``main.py``; VS Code / Pylance then
complete the constants and functions below without any import.

``micropy stubs`` copies the very same file for older projects, which
can still add::

    from micropy_api import *
"""

from typing import Any

# digital and analog constants
OUTPUT: int
INPUT: int
INPUT_PULLUP: int
INPUT_PULLDOWN: int
HIGH: int
LOW: int
CHANGE: int
RISING: int
FALLING: int
LED_BUILTIN: int
A0: int
A1: int
A2: int
A3: int
A4: int
A5: int

# digital and analog I/O
def pin_mode(pin: int, mode: int) -> None:
    """Configure an Arduino pin as an input or output."""
    ...
def digital_write(pin: int, value: int) -> None:
    """Write a HIGH or LOW value to a digital Arduino pin."""
    ...
def digital_read(pin: int) -> int:
    """Read the digital state of an Arduino pin."""
    ...
def analog_read(pin: int) -> int:
    """Read an analog value from an Arduino pin."""
    ...
def analog_write(pin: int, value: int) -> None:
    """Write an analog/PWM value to an Arduino pin."""
    ...

# timing
def delay(milliseconds: int) -> None:
    """Pause the program for the specified number of milliseconds."""
    ...
def delay_microseconds(microseconds: int) -> None:
    """Pause the program for the specified number of microseconds."""
    ...
def millis() -> int:
    """Return the number of milliseconds since the Arduino started."""
    ...
def micros() -> int:
    """Return the number of microseconds since the Arduino started."""
    ...

# serial
def serial_begin(baud: int) -> None:
    """Start serial communication at the specified baud rate."""
    ...
def serial_end() -> None:
    """Stop serial communication."""
    ...
def serial_flush() -> None:
    """Wait for outgoing serial data to finish transmitting."""
    ...
def serial_available() -> int:
    """Return the number of bytes available to read from the serial port."""
    ...
def serial_read() -> int:
    """Read the next byte from the serial input."""
    ...
def serial_print(value: Any, format: int = ...) -> None:
    """Print a value to the serial port without adding a newline."""
    ...
def serial_println(value: Any = ..., format: int = ...) -> None:
    """Print a value to the serial port followed by a newline."""
    ...

# Arduino's String class
class String:
    """Arduino-compatible string class."""
    def __init__(self, value: Any = ...) -> None:
        """Create a String from the given value."""
        ...
    def length(self) -> int:
        """Return the number of characters in the string."""
        ...
    def charAt(self, index: int) -> str:
        """Return the character at the specified index."""
        ...

# math helpers
# Arduino maps these onto the C++ standard library
def abs(value: int) -> int:
    """Return the absolute value of a number."""
    ...
def min(a: int, b: int) -> int:
    """Return the smaller of two values."""
    ...
def max(a: int, b: int) -> int:
    """Return the larger of two values."""
    ...
def constrain(value: int, low: int, high: int) -> int:
    """Constrain a value to a specified minimum and maximum range."""
    ...
def pow(base: float, exponent: float) -> float:
    """Return the base raised to the specified exponent."""
    ...
def sqrt(value: float) -> float:
    """Return the square root of a value."""
    ...
def floor(value: float) -> float:
    """Round a value down to the nearest integer."""
    ...
def ceil(value: float) -> float:
    """Round a value up to the nearest integer."""
    ...
def round(value: float) -> float:
    """Round a value to the nearest integer."""
    ...

# Arduino libraries

# from micropy import Servo
class Servo:
    """Control a standard Arduino servo motor."""
    def attach(self, pin: int) -> None:
        """Attach the servo to the specified Arduino pin."""
        ...
    def detach(self) -> None:
        """Detach the servo from its Arduino pin."""
        ...
    def write(self, angle: int) -> None:
        """Set the servo position to the specified angle."""
        ...
    def read(self) -> int:
        """Return the servo's current position in degrees."""
        ...