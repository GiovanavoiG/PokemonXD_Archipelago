"""Skip Opening Movie: a new game goes straight to the first map, past the opening cutscene.

After the name screen, the title menu's New Game path (`zz_8002f718_`) calls `floorLink(182)`: room 182 is
`opening_event.fsys`, the in-engine cutscene of Shadow Lugia lifting the S.S. Libra. Its script plays seventeen
scenes and then links to floor 141, the HQ Lab room a new game starts in. It sets no story value and no flag on
the way, so linking to 141 directly instead changes nothing but the cutscene.
"""
from __future__ import annotations

NEW_GAME_FLOOR_LINK = 0x8002FA6C        # li r3, 182 -- the argument to floorLink, two words before the call
NEW_GAME_FLOOR_VANILLA = 0x386000B6     # li r3, 182 (opening_event)
NEW_GAME_FLOOR_SKIP = 0x3860008D        # li r3, 141 (the HQ Lab, where the cutscene ends)


def dol_patch_words() -> "tuple[tuple[int, int, int], ...]":
    """(address, vanilla word, new word) for `iso_patcher.write_dol_words_patch`."""
    return ((NEW_GAME_FLOOR_LINK, NEW_GAME_FLOOR_VANILLA, NEW_GAME_FLOOR_SKIP),)
