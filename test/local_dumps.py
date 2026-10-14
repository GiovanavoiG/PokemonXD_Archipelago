"""Fixtures read from the developer's own MEM1 dumps. Tests that need one skip when it is not on this machine."""
from __future__ import annotations

from pathlib import Path

DUMPS = Path("/mnt/user-data/uploads/PokemonXD-working/bridge/dumps")

# S2_building_2F_2's resident script, as the room-entry dump holds it: 0x2E90 bytes at MEM1 0x8099E160. The two
# state bytes are set to how the client sees the room once it has run there (story gate patched, one counter at 1).
_SNAGEM_2F_DUMP = "vmdump.bin"
_SNAGEM_2F_AT = 0x99E160
_SNAGEM_2F_SIZE = 0x2E90
_SNAGEM_2F_STATE = ((0x797, 0x42), (0x967, 0x01))


def snagem_2f_script() -> "bytes | None":
    path = DUMPS / _SNAGEM_2F_DUMP
    if not path.is_file():
        return None
    with path.open("rb") as f:
        f.seek(_SNAGEM_2F_AT)
        script = bytearray(f.read(_SNAGEM_2F_SIZE))
    if len(script) != _SNAGEM_2F_SIZE or script[:4] != b"TCOD":
        return None
    for offset, value in _SNAGEM_2F_STATE:
        script[offset] = value
    return bytes(script)
