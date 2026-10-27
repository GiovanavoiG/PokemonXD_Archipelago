"""Increased Walk Speed -- one main.dol float, 30.0 -> 60.0.

main.dol file offset 0x421964 is `.sdata2` 0x804EF7E4, a float constant 30.0 (0x41F00000) read by the `people`
module (`peopleMoveAlongAngle`, `_peopleMoveRotate`, `_peopleSetAutoMotionFrameCount`, `peopleDaemon`, ...).
Writing 60.0 (0x42700000) there speeds up overworld walking. It is a shared constant, so the other readers --
turning, auto-motion frame counts, the gaze check, neck tracking -- see 60.0 too.

Import-free so the standalone patcher can load it by path.
"""
from __future__ import annotations

WALK_SPEED_ADDRESS = 0x804EF7E4   # main.dol file offset 0x421964
VANILLA_WORD = 0x41F00000         # 30.0f
PATCHED_WORD = 0x42700000         # 60.0f


def dol_patch_words() -> "tuple[tuple[int, int, int], ...]":
    """(address, vanilla word, new word)."""
    return ((WALK_SPEED_ADDRESS, VANILLA_WORD, PATCHED_WORD),)
