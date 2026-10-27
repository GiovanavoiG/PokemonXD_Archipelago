"""The Cipher Lab's trainers fight at any point in the story; each one's own "beaten" flag turns it off.

Every floor's `hero_main` runs its trainer triggers only inside a story window (vanilla: 320-349 on 1F, B1 and B3,
330-339 on B2, 320-329 and 330-349 on B3's two halves). The client patches each loaded floor script in RAM, the same
way as the always-battle NPC scripts, so the windows always pass. Nothing here writes the story value. A trainer is
fought once: its function opens by testing its own flag, which the game sets after the battle.

1F    Corla. Window 320-349 -> any value.
B1    Javion, Tekot, Cabol, Klots (and the missable Digor and Nopia). Window 320-349 -> any value. The ">= 350 hides
      everyone" block in `preprocess` is switched off, so an unbeaten trainer is still standing; beaten ones are
      already hidden by their own flags. Lovrina's own `== 340` test is untouched.
B2    Solox, from Lovrina's scene (330) onward. The block that also holds Naps #2 and Klein is rebuilt in place:
      `330 <= S` gates Solox; Naps keeps `S < 340` inside it, because his scene moves the story. The `S == 320`
      branch (Lovrina's scene) is untouched, and the Klein-only block now falls through to it instead of skipping it.
B3    Mesak, Nexir, Crink (and the missable Morbit, Meda, Elrok, Coffy). The upper half's window -> any value, and it
      falls through into the lower half's triggers; the ">= 350 hides" block in `preprocess` is switched off.

Offsets are into the script blob; instruction w sits at the CODE section + 0x20 + 4w. Each edit is
(word index, stock word, patched word).
"""
from __future__ import annotations

import struct

# ------------------------------------------------------------ D1_labo_1F
CIPHER_LAB_1F_SIZE = 0x690
_1F_CODE0 = 0x120
CIPHER_LAB_1F_WORD_EDITS = (
    (49, 0x0000015E, 0x0100015E),
    (36, 0x00000140, 0x00000000),
)
CIPHER_LAB_1F_ANCHORS = (
    (0x0000, b"TCOD"), (0x0004, struct.pack(">I", CIPHER_LAB_1F_SIZE)),
    (0x0010, b"FTBL"), (0x00C0, b"HEAD"), (0x0100, b"CODE"), (0x0530, b"GVAR"), (0x0550, b"STRG"),
    (0x0570, b"VECT"), (0x0590, b"GIRI"), (0x05E0, b"ARRY"),
    # battle-id loads, never patched: they pin the script to this floor
    (_1F_CODE0 + 4 * 137, bytes.fromhex("02010000000000fc")),   # ldimm 252
)


# ------------------------------------------------------------ D1_labo_B1
CIPHER_LAB_B1_SIZE = 0x56F0
_B1_CODE0 = 0x450
CIPHER_LAB_B1_WORD_EDITS = (
    (906, 0x0000015E, 0x0100015E),
    (893, 0x00000140, 0x00000000),
    (435, 0x0000015E, 0x0100015E),
)
CIPHER_LAB_B1_ANCHORS = (
    (0x0000, b"TCOD"), (0x0004, struct.pack(">I", CIPHER_LAB_B1_SIZE)),
    (0x0010, b"FTBL"), (0x0380, b"HEAD"), (0x0430, b"CODE"), (0x5450, b"GVAR"), (0x5490, b"STRG"),
    (0x55A0, b"VECT"), (0x55C0, b"GIRI"), (0x5640, b"ARRY"),
    # battle-id loads, never patched: they pin the script to this floor
    (_B1_CODE0 + 4 * 1737, bytes.fromhex("020100000000010c")),   # ldimm 268
    (_B1_CODE0 + 4 * 4214, bytes.fromhex("02010000000000fd")),   # ldimm 253
)


# ------------------------------------------------------------ D1_labo_B2
CIPHER_LAB_B2_SIZE = 0x2660
_B2_CODE0 = 0x260
CIPHER_LAB_B2_WORD_EDITS = (
    (566, 0x02010000, 0x00000000),
    (567, 0x0000014A, 0x00000000),
    (568, 0x02010000, 0x00000000),
    (569, 0x000003C4, 0x00000000),
    (570, 0x09000085, 0x02010000),
    (571, 0x06010000, 0x0000014A),
    (572, 0x03020000, 0x02010000),
    (573, 0x01340000, 0x000003C4),
    (574, 0x02010000, 0x09000085),
    (575, 0x000003C4, 0x06010000),
    (576, 0x09000085, 0x03020000),
    (577, 0x06010000, 0x01340000),
    (578, 0x03020000, 0x0B000271),
    (579, 0x02010000, 0x02020000),
    (580, 0x00000154, 0x41D00000),
    (581, 0x01330000, 0x02020000),
    (582, 0x01220000, 0x41900000),
    (583, 0x0B000271, 0x02020000),
    (584, 0x1000012C, 0x41800000),
    (586, 0x41D00000, 0xC1900000),
    (587, 0x02020000, 0x03030080),
    (588, 0x41900000, 0x09230019),
    (589, 0x02020000, 0x06050000),
    (590, 0x41800000, 0x03020000),
    (591, 0x02020000, 0x02010000),
    (592, 0xC1900000, 0x00000001),
    (593, 0x03030080, 0x01300000),
    (594, 0x09230019, 0x0B000256),
    (595, 0x06050000, 0x03030084),
    (596, 0x03020000, 0x07000522),
    (597, 0x02010000, 0x06010000),
    (598, 0x00000001, 0x02010000),
    (599, 0x01300000, 0x000003C4),
    (600, 0x0B00025D, 0x09000085),
    (601, 0x1000012D, 0x06010000),
    (602, 0x03030084, 0x03020000),
    (603, 0x07000522, 0x02010000),
    (604, 0x06010000, 0x00000154),
    (605, 0x10000130, 0x01330000),
    (606, 0x02020000, 0x0B000270),
    (607, 0x41700000, 0x02020000),
    (608, 0x02020000, 0x41700000),
    (609, 0xC2700000, 0x02020000),
    (610, 0x02020000, 0xC2700000),
    (611, 0xC1400000, 0x02020000),
    (612, 0x02020000, 0xC1400000),
    (613, 0xC28C0000, 0x02020000),
    (614, 0x03030080, 0xC28C0000),
    (615, 0x09230019, 0x03030080),
    (616, 0x06050000, 0x09230019),
    (617, 0x03020000, 0x06050000),
    (618, 0x02010000, 0x03020000),
    (619, 0x00000001, 0x02010000),
    (620, 0x01300000, 0x00000001),
    (621, 0x0B000270, 0x01300000),
    (622, 0x10000131, 0x0B000270),
    (564, 0x0C00028E, 0x0C000235),
)
CIPHER_LAB_B2_ANCHORS = (
    (0x0000, b"TCOD"), (0x0004, struct.pack(">I", CIPHER_LAB_B2_SIZE)),
    (0x0010, b"FTBL"), (0x01D0, b"HEAD"), (0x0240, b"CODE"), (0x2530, b"GVAR"), (0x2560, b"STRG"),
    (0x25B0, b"VECT"), (0x25D0, b"GIRI"), (0x2630, b"ARRY"),
    # battle-id loads, never patched: they pin the script to this floor
    (_B2_CODE0 + 4 * 1403, bytes.fromhex("0201000000000101")),   # ldimm 257
    (_B2_CODE0 + 4 * 1816, bytes.fromhex("020100000000010b")),   # ldimm 267
)
# While the block is rewritten, the jump into it at w542 is pointed past it, then put back.
CIPHER_LAB_B2_GUARD = (_B2_CODE0 + 4 * 542 + 3, 0x35, 0x8E)


# ------------------------------------------------------------ D1_labo_B3
CIPHER_LAB_B3_SIZE = 0x2170
_B3_CODE0 = 0x2A0
CIPHER_LAB_B3_WORD_EDITS = (
    (98, 0x0000015E, 0x0100015E),
    (85, 0x0000014A, 0x00000000),
    (184, 0x0C0000F6, 0x0C0000CC),
    (200, 0x0000014A, 0x0100014A),
    (39, 0x0000015E, 0x0100015E),
)
CIPHER_LAB_B3_ANCHORS = (
    (0x0000, b"TCOD"), (0x0004, struct.pack(">I", CIPHER_LAB_B3_SIZE)),
    (0x0010, b"FTBL"), (0x0210, b"HEAD"), (0x0280, b"CODE"), (0x2060, b"GVAR"), (0x2080, b"STRG"),
    (0x20A0, b"VECT"), (0x20C0, b"GIRI"), (0x2140, b"ARRY"),
    # battle-id loads, never patched: they pin the script to this floor
    (_B3_CODE0 + 4 * 376, bytes.fromhex("02010000000000ff")),   # ldimm 255
    (_B3_CODE0 + 4 * 908, bytes.fromhex("0201000000000100")),   # ldimm 256
    (_B3_CODE0 + 4 * 1150, bytes.fromhex("0201000000000103")),   # ldimm 259
)


def byte_patches(code0: int, edits) -> "tuple[tuple[int, int, int], ...]":
    """(offset, stock byte, patched byte) for every byte an edit changes."""
    out = []
    for word, stock, patched in edits:
        old, new = struct.pack(">I", stock), struct.pack(">I", patched)
        for k in range(4):
            if old[k] != new[k]:
                out.append((code0 + 4 * word + k, old[k], new[k]))
    return tuple(out)


def stock_anchors(code0: int, edits) -> "tuple[tuple[int, bytes], ...]":
    """Bytes next to the edits that never change: each edited word's untouched bytes, which pin the script."""
    out = []
    for word, stock, patched in edits:
        old, new = struct.pack(">I", stock), struct.pack(">I", patched)
        for k in range(4):
            if old[k] == new[k]:
                out.append((code0 + 4 * word + k, old[k:k + 1]))
    return tuple(out)


CIPHER_LAB_FLOORS = (
    ("Cipher Lab 1F", CIPHER_LAB_1F_SIZE, _1F_CODE0, CIPHER_LAB_1F_WORD_EDITS, CIPHER_LAB_1F_ANCHORS, None),
    ("Cipher Lab B1", CIPHER_LAB_B1_SIZE, _B1_CODE0, CIPHER_LAB_B1_WORD_EDITS, CIPHER_LAB_B1_ANCHORS, None),
    ("Cipher Lab B2", CIPHER_LAB_B2_SIZE, _B2_CODE0, CIPHER_LAB_B2_WORD_EDITS, CIPHER_LAB_B2_ANCHORS,
     CIPHER_LAB_B2_GUARD),
    ("Cipher Lab B3", CIPHER_LAB_B3_SIZE, _B3_CODE0, CIPHER_LAB_B3_WORD_EDITS, CIPHER_LAB_B3_ANCHORS, None),
)
