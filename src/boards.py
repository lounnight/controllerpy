from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional
from .errors import MicropyError


__all__ = [
    "Board",
    "BOARDS",
    "PLANNED_BOARDS",
    "DEFAULT_BOARD",
    "board_aliases",
    "default_board",
    "resolve_board",
    "supported_boards",
]

@dataclass(frozen=True)
class Board:
    fqbn: str
    name: str
    alias: str
    supported: bool = True

BOARDS: Dict[str, Board] = {
    "arduino:avr:uno": Board(fqbn="arduino:avr:uno", name="Arduino Uno", alias="uno"),
}

PLANNED_BOARDS: Dict[str, str] = {
    "nano": "arduino:avr:nano",
    "mega": "arduino:avr:mega",
    "esp32": "esp32:esp32:esp32",
}

DEFAULT_BOARD = "arduino:avr:uno"

def supported_boards() -> List[Board]:
    return list(BOARDS.values())

def board_aliases() -> Dict[str, str]:
    return {board.alias: board.fqbn for board in BOARDS.values()}

def default_board() -> Board:
    return BOARDS[DEFAULT_BOARD]

def resolve_board(spec: Optional[str] = None) -> Board:
    if not spec:
        return default_board()
    
    key = spec.strip()

    if key in BOARDS:
        return BOARDS[key]
    
    fqbn = board_aliases().get(key.lower())
    if fqbn:
        return BOARDS[fqbn]
    
    planned = PLANNED_BOARDS.get(key.lower())
    if planned:
        raise MicropyError(
            f"Board '{key}' is not supported yet.",
            hint="micropy currently generates code for the Arduino Uno.",
            hint_lines=[f"planned target: {planned}"],
        )
    raise MicropyError(
        f"Unknown board: '{key}'.",
        hint="Supported boards:",
        hint_lines=[f"{b.alias} ({b.fqbn}) - {b.name}" for b in supported_boards()],
    )
