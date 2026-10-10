from __future__ import annotations

from typing import Dict, List, Optional, Tuple

__all__ = ["parse_key", "parse_keys"]

_CSI_KEYS: Dict[bytes, str] = {
    b"\x1b[A": "up",
    b"\x1b[B": "down",
    b"\x1b[C": "right",
    b"\x1b[D": "left",
    b"\x1bOA": "up",
    b"\x1bOB": "down",
    b"\x1bOC": "right",
    b"\x1bOD": "left",
    b"\x1b[H": "home",
    b"\x1b[F": "end",
    b"\x1bOH": "home",
    b"\x1bOF": "end",
    b"\x1b[1~": "home",
    b"\x1b[4~": "end",
    b"\x1b[7~": "home",
    b"\x1b[8~": "end",
    b"\x1b[3~": "delete",
    b"\x1b[5~": "pageup",
    b"\x1b[6~": "pagedown",
}

_PLAIN_KEYS: Dict[int, str] = {
    13: "enter",
    10: "enter",
    9: "tab",
    8: "backspace",
    127: "backspace",
}

_CSI_FINAL = (0x40, 0x7E)
_MAX_CSI = 16


def parse_key(data: bytes) -> Tuple[Optional[str], int]:
    if not data:
        return None, 0

    first = data[0]
    if first == 0x1B:
        if len(data) == 1:
            return None, 0
        if data[1] in (ord("["), ord("O")):
            return _parse_csi(data)
        if data[1] == 0x1B:
            return "escape", 1

        return "", 2

    return _parse_plain(data)


def parse_keys(data: bytes) -> Tuple[List[str], bytes]:
    keys: List[str] = []
    rest = data
    while rest:
        key, consumed = parse_key(rest)
        if key is None:
            break
        if consumed:
            rest = rest[consumed:]
        else:
            break
        if key:
            keys.append(key)

    return keys, rest


def _parse_csi(data: bytes) -> Tuple[Optional[str], int]:
    end = None
    for index in range(2, len(data)):
        byte = data[index]
        if _CSI_FINAL[0] <= byte <= _CSI_FINAL[1]:
            end = index
            break

    if end is None:
        if len(data) > _MAX_CSI:
            return "", len(data)

        return None, 0

    sequence = data[: end + 1]

    return _CSI_KEYS.get(sequence, ""), end + 1


def _parse_plain(data: bytes) -> Tuple[Optional[str], int]:
    byte = data[0]
    if byte in _PLAIN_KEYS:
        return _PLAIN_KEYS[byte], 1
    if 1 <= byte <= 26:
        return f"ctrl+{chr(byte + 96)}", 1
    if 32 <= byte < 127:
        return chr(byte), 1
    if byte < 32:
        return "", 1

    return _parse_utf8(data)


def _parse_utf8(data: bytes) -> Tuple[Optional[str], int]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        if len(data) >= 4:
            return "", 1

        return None, 0

    if not text:
        return None, 0

    first = text[0]

    return first, len(first.encode("utf-8"))
