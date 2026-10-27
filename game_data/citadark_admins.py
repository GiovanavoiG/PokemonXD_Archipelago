"""Citadark Admins Only: on Citadark Isle only the admins fight -- Lovrina, Snattle, Ardos, Gorigan, Eldes and Greevil.

Every other Citadark trainer is already beaten and is gone:

* THE CLIENT marks each one beaten by setting the variable its map script tests before starting the fight
  (`BEATEN_VARIABLES`). Those same scripts hide most of them once it is set -- the ones that drop in from above never
  appear, and the floors' `preprocess` hides the rest on load.
* THE PATCH hides the six whose floors leave a beaten trainer standing (`HIDDEN_CHARACTERS`): Furgy, Golos and Jetsal
  on 1F, and Nalix, Ibran and Kulig on 3F. Their character records lose the "visible" flag and are moved under the
  floor, so nothing is left to see, bump into or talk to.
* THE WORLD has no checks for them: their defeat checks are not created, the "Defeat N Trainers" tally does not count
  them, and their Shadows are moved to trainers elsewhere, the same way Remove Citadark Shadows moves them.

None of these trainers moves the story: Citadark's story steps are Snattle (900), the glass wall and dome (910-930),
Eldes (940) and Greevil (950), all admin scenes.

Import-free so the standalone patcher can load it by path.
"""
from __future__ import annotations

import struct

#: The admins' Citadark rows: Lovrina #2, Snattle #2, Ardos #2, Gorigan #2, Eldes and Greevil's three.
ADMIN_TRAINER_INDICES: "frozenset[int]" = frozenset({173, 191, 193, 194, 196, 199, 200, 201})

#: Every other Citadark Isle row.
REMOVED_TRAINER_INDICES: "frozenset[int]" = frozenset({
    168,   # Abson (D6_out_foot)
    169,   # Haben (D6_fort_1F)
    170,   # Furgy (D6_fort_1F)
    171,   # Golos (D6_fort_1F)
    172,   # Jetsal (D6_fort_1F)
    174,   # Bastil (D6_fort_B1)
    175,   # Litnar (D6_fort_B1)
    176,   # Grason (D6_fort_B1)
    177,   # Grupel (D6_fort_2F_1)
    178,   # Kimly (D6_fort_2F_3)
    179,   # Nalix (D6_fort_3F_1)
    180,   # Ibran (D6_fort_3F_1)
    181,   # Kulig (D6_fort_3F_1)
    182,   # Jargo (D6_fort_3F_1)
    183,   # Kolest (D6_fort_3F_1)
    184,   # Kolin (D6_fort_3F_1)
    185,   # Karbon (D6_fort_3F_2)
    186,   # Petro (D6_fort_3F_2)
    187,   # Jaymi (D6_fort_4F)
    188,   # Gromlet (D6_fort_4F)
    189,   # Geftal (D6_fort_6F)
    190,   # Leden (D6_fort_6F)
    192,   # Kleef (D6_out_foot)
    195,   # Kolax (D6_dome_B1)
    197,   # Kaller (D6_dome_1F)
    198,   # Loket (D6_dome_1F)
})
assert not ADMIN_TRAINER_INDICES & REMOVED_TRAINER_INDICES

#: {trainer index: the script variables that mark it beaten}. Each is what the trainer's trigger tests (`== 0` starts
#: the fight) and what its win path sets to 1. Karbon and Petro are one encounter: 1368 is the pair's, 1300 Karbon's.
BEATEN_VARIABLES: "dict[int, tuple[int, ...]]" = {
    168: (1352,), 169: (1353,), 170: (1354,), 171: (1355,), 172: (1356,),
    174: (1359,), 175: (1376,), 176: (1360,), 177: (1361,), 178: (1377,),
    179: (1362,), 180: (1363,), 181: (1364,), 182: (1365,), 183: (1366,), 184: (1367,),
    185: (1300, 1368), 186: (1368,),
    187: (1369,), 188: (1370,), 189: (1371,), 190: (1372,),
    192: (1357,), 195: (1375,), 197: (1373,), 198: (1374,),
}
assert set(BEATEN_VARIABLES) == REMOVED_TRAINER_INDICES


def beaten_variables() -> "tuple[int, ...]":
    """Every variable to set, once each, ascending."""
    return tuple(sorted({v for vs in BEATEN_VARIABLES.values() for v in vs}))


# ---------------------------------------------------------------------------------------------------------------
# The floor modules. A room's .fsys holds its floor module (REL, file format 28); data section 3 starts with its
# character table, 0x24 bytes a record: +0x00 flags (0x80 = visible), +0x08 name id, +0x14 talk function word
# (0x01000000 + function index, 0 for none), +0x18 x, y, z (floats).
CHARACTER_RECORD_SIZE = 0x24
VISIBLE_FLAG = 0x80
HIDDEN_Y = -1000.0

#: {room: ((character index, name id, talk function word, trainer), ...)} -- the beaten trainers a floor leaves
#: standing. The name id and talk word pin each record, so a different disc is refused rather than edited.
HIDDEN_CHARACTERS: "dict[str, tuple[tuple[int, int, int, int], ...]]" = {
    "D6_fort_1F": (
        (1, 158, 0x01000007, 170),   # Furgy -- talk_103_thief_m
        (2, 159, 0x01000008, 171),   # Golos -- talk_104_sailor1
        (3, 160, 0x01000009, 172),   # Jetsal -- talk_105_hunter_f
    ),
    "D6_fort_3F_1": (
        (0, 164, 0x01000005, 179),   # Nalix -- talk_130_thief1_f
        (1, 165, 0x01000006, 180),   # Ibran -- talk_131_hunter_f
        (2, 166, 0x01000007, 181),   # Kulig -- talk_132_rider_m
    ),
}


def _be32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def character_table_offset(rel: bytes) -> int:
    """File offset of data section 3, where the character table starts."""
    count, info = _be32(rel, 0x0C), _be32(rel, 0x10)
    if count <= 3:
        raise ValueError("the floor module has no data section 3")
    offset, _size = struct.unpack_from(">II", rel, info + 8 * 3)
    return offset


def is_hidden(rel: bytes, room: str) -> bool:
    """True when every record this room lists is already hidden (an ISO this patch has been run on)."""
    base = character_table_offset(rel)
    for index, _name, _talk, _trainer in HIDDEN_CHARACTERS[room]:
        at = base + index * CHARACTER_RECORD_SIZE
        if rel[at] & VISIBLE_FLAG or struct.unpack_from(">f", rel, at + 0x1C)[0] != HIDDEN_Y:
            return False
    return True


def hide_characters(rel: bytes, room: str) -> bytes:
    """`room`'s floor module with its beaten trainers invisible and under the floor. Refuses a record that is not
    the one expected (name id and talk function), so a different disc is never edited blind."""
    out = bytearray(rel)
    base = character_table_offset(rel)
    for index, name, talk, _trainer in HIDDEN_CHARACTERS[room]:
        at = base + index * CHARACTER_RECORD_SIZE
        got_name = struct.unpack_from(">H", out, at + 0x08)[0]
        got_talk = _be32(out, at + 0x14)
        if (got_name, got_talk) != (name, talk):
            raise ValueError(f"{room} character {index} is name {got_name} / talk {got_talk:#010x}, "
                             f"not {name} / {talk:#010x}")
        out[at] &= 0xFF & ~VISIBLE_FLAG
        struct.pack_into(">f", out, at + 0x1C, HIDDEN_Y)
    return bytes(out)


#: The cumulative-mode named checks (`trainer_defeat.TRAINER_DEFEAT_ROSTER`) filed under Citadark Isle whose surname is
#: one of the removed trainers' (the roster's own spellings). The admins' and the mis-filed non-Citadark names
#: (Zook, Smarton, Eagun, Miror B.) are not here.
REMOVED_NAMED_SURNAMES: "frozenset[str]" = frozenset({
    "Abson", "Dimon", "Furgy", "Toronba", "Ransa", "Berd", "Litnar", "Grupel", "Fajo", "Ogera", "Kolest", "Uumo",
    "Carol", "Fego", "Antol", "Karbon", "Petro", "Koral", "Akante", "Gefta", "Leden", "Metring", "Stron",
})
