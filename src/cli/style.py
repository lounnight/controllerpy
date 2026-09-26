from __future__ import annotations

import os
import sys
from typing import Dict, Optional, TextIO

__all__ = ["COLOURS", "paint", "supports_colour"]

_CODES: Dict[str, str] = {
    "bold": "1",
    "dim": "2",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "cyan": "36",
}

COLOURS = frozenset(_CODES)

_RESET = "\033[0m"
_DUMB_TERM = "dumb"


def supports_colour(stream: Optional[TextIO] = None) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True

    target = sys.stdout if stream is None else stream

    return _is_a_terminal(target) and os.environ.get("TERM", "") != _DUMB_TERM


def paint(text: str, *styles: str, stream: Optional[TextIO] = None) -> str:
    codes = [_CODES[name] for name in styles if name in _CODES]
    if not codes or not supports_colour(stream):
        return text

    return f"\033[{';'.join(codes)}m{text}{_RESET}"


def _is_a_terminal(stream: object) -> bool:
    try:
        return bool(stream.isatty())  
    except (AttributeError, ValueError):
        return False
