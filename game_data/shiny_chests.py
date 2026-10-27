"""The shining key-item chests stay until they are opened, and opening one never runs its key item's scene.

CIPHER LAB B1 (`D1_labo_B1`). The floor script shows both of its shining objects itself, and hides each one while the
player holds that chest's vanilla key item:

* chest 18 (the ID Card): shown once Klots is beaten, unless the ID Card is in the Bag (`c43.0x1c(506)`) or the
  left-up elevator has taken it (flag 1488). An ID Card from the multiworld hid it for good.
* chest 17 (the Data ROM, Lovrina's drop): shown only while the story is exactly 350 (just past Lovrina), unless the
  Data ROM is in the Bag (`c43.0x1c(505)`) or the centre elevator's attendant has taken it (flag 1182).

With key items shuffled these chests hold a check, not their key item, so each test is rewritten to the chest's own
"opened" flag (its treasure-table flag: 1139 for chest 18, 1145 for chest 17), and the Data ROM chest's `== 350`
becomes `>= 350`. Each chest is then there from its vanilla moment until it is opened, whatever the Bag holds.
Three places do these tests: `preprocess` (both chests, and the ID Card chest's pick-up distance) and
`anywaysave_restart` (the Data ROM chest, on a restart from a save made there).

PHENAC'S MUSIC DISC HOUSE (`M1_houseB_1F`, room 98). Its main loop runs `ev_get_cd` every frame: once chest 80 is
open (flag 1454) and the story is 510-529, it plays "It appears to be a MUSIC DISC" and sets the story to 530, the
"Music Disc picked up" step. With key items shuffled, the client holds that room's story at 510 until the multiworld
Music Disc arrives, so the scene played again every time it was pulled back. The test becomes "the Music Disc is in the
Bag": opening the chest only sends its check, and the scene plays when the player holds the real disc there.

The has-item call takes one word more than a flag or variable read (`ldimm item; ldncvar obj43; callstd 43.0x1c;
pop 2` against `ldimm flag; callstd 0.0x84; pop 1`). In the lab the spare word becomes a `line` marker, a no-op; in
the house the `line` marker before the read gives up its word. Same length everywhere, nothing moves.

Offsets are into the script blob; instruction w sits at the CODE section + 0x20 + 4w. Each edit is
(word index, stock word, patched word).

Import-free so the standalone patcher can load it by path.
"""
from __future__ import annotations

import struct
from typing import NamedTuple

CHEST_ID_CARD, CHEST_DATA_ROM, CHEST_MUSIC_DISC = 18, 17, 80
OPENED_FLAG = {CHEST_ID_CARD: 1139, CHEST_DATA_ROM: 1145, CHEST_MUSIC_DISC: 1454}
MUSIC_DISC_ITEM = 507

_LDIMM_INT = 0x02010000
_LDNCVAR_OBJ43 = 0x1103002B
_HAS_ITEM = 0x092B001C          # callstd 43.0x1c
_GET_FLAG = 0x09000084          # callstd 0.0x84
_GET_VAR = 0x09000085           # callstd 0.0x85
_POP2, _POP1 = 0x06020000, 0x06010000
_EQ, _GE, _LE = 0x01300000, 0x01320000, 0x01340000


class RoomPatch(NamedTuple):
    room: str
    size: int
    code0: int
    edits: "tuple[tuple[int, int, int], ...]"
    anchors: "tuple[tuple[int, bytes], ...]"
    chests: "frozenset[int]"          # the shuffled chests this room's patch is for


def _has_item_to_flag(at: int, item: int, flag: int, line: int) -> "tuple[tuple[int, int, int], ...]":
    """`ldimm item` at word `at` (its value at at+1) through the `pop 2`, as a flag test."""
    return (
        (at + 1, item, flag),
        (at + 2, _LDNCVAR_OBJ43, 0x10000000 | line),
        (at + 3, _HAS_ITEM, _GET_FLAG),
        (at + 4, _POP2, _POP1),
    )


CIPHER_LAB_B1 = RoomPatch(
    "D1_labo_B1", 0x56F0, 0x450,
    (
        # preprocess, chest 17: `S == 350` -> `S >= 350`; has Data ROM -> opened; flag 1182 -> opened.
        (109, _EQ, _GE),
        *_has_item_to_flag(112, 505, 1145, 141),
        (122, 1182, 1145),
        # preprocess, chest 18: flag 1488 -> opened; has ID Card -> opened.
        (171, 1488, 1139),
        *_has_item_to_flag(178, 506, 1139, 156),
        # preprocess, chest 18's pick-up distance: the same test.
        (238, 1488, 1139),
        *_has_item_to_flag(245, 506, 1139, 175),
        # anywaysave_restart, chest 17: `350 == S` -> `350 <= S`; has Data ROM -> opened; flag 1182 -> opened.
        (694, _EQ, _LE),
        *_has_item_to_flag(697, 505, 1145, 335),
        (707, 1182, 1145),
    ),
    (
        (0x0000, b"TCOD"), (0x0004, struct.pack(">I", 0x56F0)),
        (0x0010, b"FTBL"), (0x0380, b"HEAD"), (0x0430, b"CODE"), (0x5450, b"GVAR"), (0x5490, b"STRG"),
        (0x55A0, b"VECT"), (0x55C0, b"GIRI"), (0x5640, b"ARRY"),
        (0x450 + 4 * 1737, bytes.fromhex("020100000000010c")),   # ldimm 268 (a battle id)
        (0x450 + 4 * 4214, bytes.fromhex("02010000000000fd")),   # ldimm 253
    ),
    frozenset({CHEST_ID_CARD, CHEST_DATA_ROM}),
)

MUSIC_DISC_HOUSE = RoomPatch(
    "M1_houseB_1F", 0xF20, 0x1A0,
    (
        # ev_get_cd: `line 296; ldimm 1454; callstd getVar; pop 1` -> `ldimm 507; ldncvar obj43; callstd 43.0x1c; pop 2`
        (477, 0x10000128, _LDIMM_INT),
        (478, _LDIMM_INT, MUSIC_DISC_ITEM),
        (479, 1454, _LDNCVAR_OBJ43),
        (480, _GET_VAR, _HAS_ITEM),
        (481, _POP1, _POP2),
    ),
    (
        (0x0000, b"TCOD"), (0x0004, struct.pack(">I", 0xF20)),
        (0x0010, b"FTBL"), (0x0120, b"HEAD"), (0x0180, b"CODE"), (0x0E20, b"GVAR"), (0x0E40, b"STRG"),
        (0x0E80, b"VECT"), (0x0EA0, b"GIRI"), (0x0EF0, b"ARRY"),
        (0x1A0 + 4 * 500, bytes.fromhex("0201000000000212")),    # ldimm 530 (the scene's story step)
        (0x1A0 + 4 * 506, bytes.fromhex("0201000000008cb8")),    # ldimm 36024 ("It appears to be a MUSIC DISC")
    ),
    frozenset({CHEST_MUSIC_DISC}),
)

ROOM_PATCHES: "tuple[RoomPatch, ...]" = (CIPHER_LAB_B1, MUSIC_DISC_HOUSE)

# The original single-room names, kept for readers of the Cipher Lab patch.
ROOM, SCRIPT_SIZE, CODE0, WORD_EDITS, ANCHORS = (CIPHER_LAB_B1.room, CIPHER_LAB_B1.size, CIPHER_LAB_B1.code0,
                                                 CIPHER_LAB_B1.edits, CIPHER_LAB_B1.anchors)


def patches_for(shuffled_chests) -> "tuple[RoomPatch, ...]":
    """The room patches this seed needs: one per room holding a shuffled chest it covers."""
    chosen = set(shuffled_chests or ())
    return tuple(p for p in ROOM_PATCHES if p.chests & chosen)


def _word(patch: RoomPatch, blob: bytes, w: int) -> int:
    return struct.unpack_from(">I", blob, patch.code0 + 4 * w)[0]


def is_patched(script: bytes, patch: RoomPatch = CIPHER_LAB_B1) -> bool:
    return all(_word(patch, script, w) == new for w, _old, new in patch.edits)


def patch_script(script: bytes, patch: RoomPatch = CIPHER_LAB_B1) -> bytes:
    """The floor script with every edit applied. Refuses a script that is not this floor's, or a word that holds
    neither its stock nor its patched value."""
    for offset, expected in patch.anchors:
        if script[offset:offset + len(expected)] != expected:
            raise ValueError(f"{patch.room}'s script does not match at {offset:#x}")
    out = bytearray(script)
    for w, old, new in patch.edits:
        value = _word(patch, script, w)
        if value not in (old, new):
            raise ValueError(f"{patch.room} word {w} is {value:#010x}, not {old:#010x}")
        struct.pack_into(">I", out, patch.code0 + 4 * w, new)
    return bytes(out)


for _p in ROOM_PATCHES:
    assert len({w for w, _o, _n in _p.edits}) == len(_p.edits), _p.room
