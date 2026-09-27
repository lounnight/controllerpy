"""Runtime helpers shipped for IDE/type-checker support.

``api.pyi`` describes the controllerpy API; it is never uploaded to the Arduino and
never imported at compile time.
"""

from pathlib import Path

API_STUB = Path(__file__).with_name("api.pyi")

__all__ = ["API_STUB"]
