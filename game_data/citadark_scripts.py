"""Lovrina #2, Grason and Litnar on Citadark Isle fight at any story point past the island's arrival.

Their triggers (and Lovrina's placement in `preprocess`) only run while the story value is 890-900. The island is
entered at 910 when the client takes you there, so they never appeared. Each window's `<= 900` becomes `<= 16777600`;
the `>= 890` half stays. Nothing writes the story value: each trigger also tests the trainer's own beaten marker
(1358 Lovrina, 1360 Grason, 1376 Litnar), which the game sets after the win.

Each edit is (word index, stock word, patched word); instruction w sits at the CODE section + 0x20 + 4w.
"""
from __future__ import annotations

import struct

# ------------------------------------------------------------ D6_fort_1F
CITADARK_1F_SIZE = 0x2340
_1F_CODE0 = 0x260
CITADARK_1F_WORD_EDITS = (
    (16, 0x00000384, 0x01000384),
    (398, 0x00000384, 0x01000384),
)
CITADARK_1F_ANCHORS = (
    (0x0000, b"TCOD"), (0x0004, struct.pack(">I", CITADARK_1F_SIZE)),
    (0x0010, b"FTBL"), (0x01D0, b"HEAD"), (0x0240, b"CODE"), (0x2170, b"GVAR"), (0x2190, b"STRG"),
    (0x21B0, b"VECT"), (0x2220, b"GIRI"), (0x2290, b"ARRY"),
    # the battle-id load, never patched: it pins the script to this floor
    (_1F_CODE0 + 4 * 1371, bytes.fromhex("0201000000000177")),   # ldimm 375
)


# ------------------------------------------------------------ D6_fort_B1
CITADARK_B1_SIZE = 0xCD0
_B1_CODE0 = 0x220
CITADARK_B1_WORD_EDITS = (
    (193, 0x00000384, 0x01000384),
    (240, 0x00000384, 0x01000384),
)
CITADARK_B1_ANCHORS = (
    (0x0000, b"TCOD"), (0x0004, struct.pack(">I", CITADARK_B1_SIZE)),
    (0x0010, b"FTBL"), (0x01A0, b"HEAD"), (0x0200, b"CODE"), (0x0B90, b"GVAR"), (0x0BC0, b"STRG"),
    (0x0BE0, b"VECT"), (0x0C10, b"GIRI"), (0x0CA0, b"ARRY"),
    # the battle-id load, never patched: it pins the script to this floor
    (_B1_CODE0 + 4 * 569, bytes.fromhex("020100000000017a")),   # ldimm 378
)


CITADARK_FLOORS = (
    ("Citadark Isle 1F", CITADARK_1F_SIZE, _1F_CODE0, CITADARK_1F_WORD_EDITS, CITADARK_1F_ANCHORS, None),
    ("Citadark Isle B1", CITADARK_B1_SIZE, _B1_CODE0, CITADARK_B1_WORD_EDITS, CITADARK_B1_ANCHORS, None),
)
