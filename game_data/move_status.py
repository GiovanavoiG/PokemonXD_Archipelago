"""Every move's status behaviour, as the game stores it: which effect it applies, and how often.

Measured 2026-09-28 out of a real `common_rel` (`bridge/dumps/a263_commonrel.bin`, 704,448 bytes) while
chasing two reports that a move inflicted a status it should not -- "Poison Fang" sleeping its target and
"Icy Wind" freezing both of its. Two fields decide that, and neither was known before:

  +0x05  the secondary-effect chance, as a percentage. 24 of 24 known Generation III chances matched
         exactly (Ice Beam 10, Body Slam 30, Octazooka 50, Icy Wind 100, Shadow Ball 20, ...).
  +0x1D  the effect id, in Generation III's own EFFECT_* numbering. Located by grouping moves whose effect
         CLASS is known independently and asking which byte separates the groups: twelve classes, each
         internally unanimous, all twelve distinct. Nothing else in the 0x38-byte entry does that.

The table below is every entry, read straight off that dump -- 332 of 360 moves carry an effect
id, across 198 distinct values, and the 28 with neither are pinned too so that a move
GAINING an effect is caught as readily as one losing it.

WHY IT IS HERE AND NOT IN `tools/`. Both halves of the project need it and neither may own it: the patcher
verifies it before writing anywhere near those bytes, and the client verifies it against live RAM, where a
Dolphin save state can restore a whole `common_rel` from some other build. Two copies would be two sources of
truth for the same measurement, which is the shape ADDENDA 243/257 exist to refuse.

Confirmed identical at +0x05 and +0x1D across 163 MEM1 dumps, for all 360 moves. The only bytes that ever
differ in a move entry are +0x1E/+0x1F, the animation u16 the patcher writes -- one byte past +0x1D.
"""
from __future__ import annotations

# The byte offsets these values live at are `tools.xd_rel_format.MOVE_SECONDARY_CHANCE_OFFSET` and
# `MOVE_EFFECT_OFFSET`, with the rest of the move-entry layout. This module holds the census, not the layout.

#: {move index: (secondary-effect chance percent, effect id)} -- every entry in the table.
MOVE_STATUS: "dict[int, tuple[int, int]]" = {
    0: (0, 0), 1: (0, 0), 2: (0, 43), 3: (0, 29), 4: (0, 29), 5: (0, 0),
    6: (100, 34), 7: (10, 4), 8: (10, 5), 9: (10, 6), 10: (0, 0), 11: (0, 0),
    12: (0, 38), 13: (0, 39), 14: (0, 50), 15: (0, 0), 16: (0, 149), 17: (0, 0),
    18: (0, 28), 19: (0, 155), 20: (100, 42), 21: (0, 0), 22: (0, 0), 23: (30, 150),
    24: (0, 44), 25: (0, 0), 26: (0, 45), 27: (30, 31), 28: (0, 23), 29: (30, 31),
    30: (0, 0), 31: (0, 29), 32: (0, 38), 33: (0, 0), 34: (30, 6), 35: (100, 42),
    36: (0, 48), 37: (100, 27), 38: (0, 198), 39: (0, 19), 40: (30, 2), 41: (20, 77),
    42: (0, 29), 43: (0, 19), 44: (30, 31), 45: (0, 18), 46: (0, 28), 47: (0, 1),
    48: (0, 49), 49: (0, 130), 50: (0, 86), 51: (10, 69), 52: (10, 4), 53: (10, 4),
    54: (0, 46), 55: (0, 0), 56: (0, 0), 57: (0, 0), 58: (10, 5), 59: (10, 5),
    60: (10, 76), 61: (10, 70), 62: (10, 68), 63: (0, 80), 64: (0, 0), 65: (0, 0),
    66: (0, 48), 67: (0, 196), 68: (0, 89), 69: (0, 87), 70: (0, 0), 71: (0, 3),
    72: (0, 3), 73: (0, 84), 74: (0, 13), 75: (0, 43), 76: (0, 151), 77: (0, 66),
    78: (0, 67), 79: (0, 1), 80: (100, 27), 81: (0, 20), 82: (0, 41), 83: (100, 42),
    84: (10, 6), 85: (10, 6), 86: (0, 67), 87: (30, 152), 88: (0, 0), 89: (0, 147),
    90: (0, 38), 91: (0, 155), 92: (100, 33), 93: (10, 76), 94: (10, 72), 95: (0, 1),
    96: (0, 10), 97: (0, 52), 98: (0, 103), 99: (0, 81), 100: (0, 153), 101: (0, 87),
    102: (0, 82), 103: (0, 59), 104: (0, 16), 105: (0, 32), 106: (0, 11), 107: (0, 108),
    108: (0, 23), 109: (0, 49), 110: (0, 11), 111: (0, 156), 112: (0, 51), 113: (0, 35),
    114: (0, 25), 115: (0, 65), 116: (0, 47), 117: (0, 26), 118: (0, 83), 119: (0, 9),
    120: (0, 7), 121: (0, 0), 122: (30, 6), 123: (40, 2), 124: (30, 2), 125: (10, 31),
    126: (10, 4), 127: (0, 0), 128: (100, 42), 129: (0, 17), 130: (0, 145), 131: (0, 29),
    132: (10, 70), 133: (0, 54), 134: (0, 23), 135: (0, 157), 136: (0, 45), 137: (0, 67),
    138: (0, 8), 139: (0, 66), 140: (0, 29), 141: (0, 3), 142: (0, 1), 143: (30, 75),
    144: (0, 57), 145: (10, 70), 146: (20, 76), 147: (0, 1), 148: (0, 23), 149: (0, 88),
    150: (0, 85), 151: (0, 51), 152: (0, 43), 153: (0, 7), 154: (0, 29), 155: (0, 44),
    156: (0, 37), 157: (30, 31), 158: (10, 31), 159: (0, 10), 160: (0, 30), 161: (20, 36),
    162: (0, 40), 163: (0, 43), 164: (0, 79), 165: (0, 48), 166: (0, 95), 167: (0, 104),
    168: (100, 105), 169: (0, 106), 170: (0, 94), 171: (0, 107), 172: (10, 125), 173: (30, 92),
    174: (0, 109), 175: (0, 99), 176: (0, 93), 177: (0, 43), 178: (0, 60), 179: (0, 99),
    180: (0, 100), 181: (10, 5), 182: (0, 111), 183: (0, 103), 184: (0, 60), 185: (0, 17),
    186: (0, 49), 187: (0, 142), 188: (30, 2), 189: (100, 73), 190: (50, 73), 191: (0, 112),
    192: (100, 6), 193: (0, 113), 194: (0, 98), 195: (0, 114), 196: (100, 70), 197: (0, 111),
    198: (0, 29), 199: (0, 94), 200: (100, 27), 201: (0, 115), 202: (0, 3), 203: (0, 116),
    204: (0, 58), 205: (0, 117), 206: (0, 101), 207: (100, 118), 208: (0, 157), 209: (30, 6),
    210: (0, 119), 211: (10, 138), 212: (0, 106), 213: (0, 120), 214: (0, 97), 215: (0, 102),
    216: (0, 121), 217: (0, 122), 218: (0, 123), 219: (0, 124), 220: (0, 91), 221: (50, 125),
    222: (0, 126), 223: (100, 76), 224: (0, 0), 225: (30, 6), 226: (0, 127), 227: (0, 90),
    228: (0, 128), 229: (0, 129), 230: (0, 24), 231: (30, 69), 232: (10, 139), 233: (0, 78),
    234: (0, 132), 235: (0, 133), 236: (0, 134), 237: (0, 135), 238: (0, 43), 239: (20, 146),
    240: (0, 136), 241: (0, 137), 242: (20, 72), 243: (0, 144), 244: (0, 143), 245: (0, 103),
    246: (10, 140), 247: (20, 72), 248: (0, 148), 249: (50, 69), 250: (100, 42), 251: (0, 154),
    252: (0, 158), 253: (100, 159), 254: (0, 160), 255: (0, 161), 256: (0, 162), 257: (10, 4),
    258: (0, 164), 259: (0, 165), 260: (0, 166), 261: (0, 167), 262: (0, 168), 263: (0, 169),
    264: (0, 170), 265: (0, 171), 266: (0, 172), 267: (0, 173), 268: (0, 174), 269: (0, 175),
    270: (0, 176), 271: (0, 177), 272: (0, 178), 273: (0, 179), 274: (0, 180), 275: (0, 181),
    276: (0, 182), 277: (0, 183), 278: (0, 184), 279: (0, 185), 280: (0, 186), 281: (0, 187),
    282: (100, 188), 283: (0, 189), 284: (0, 190), 285: (0, 191), 286: (0, 192), 287: (0, 193),
    288: (0, 194), 289: (0, 195), 290: (30, 197), 291: (0, 155), 292: (0, 29), 293: (0, 213),
    294: (0, 53), 295: (50, 72), 296: (50, 71), 297: (0, 58), 298: (0, 199), 299: (10, 200),
    300: (0, 201), 301: (0, 117), 302: (30, 150), 303: (0, 32), 304: (0, 0), 305: (30, 202),
    306: (50, 69), 307: (0, 80), 308: (0, 80), 309: (20, 139), 310: (30, 150), 311: (0, 203),
    312: (0, 102), 313: (0, 62), 314: (0, 43), 315: (100, 204), 316: (0, 113), 317: (100, 70),
    318: (10, 140), 319: (0, 62), 320: (0, 1), 321: (0, 205), 322: (0, 206), 323: (0, 190),
    324: (10, 76), 325: (0, 17), 326: (10, 150), 327: (0, 207), 328: (100, 42), 329: (0, 38),
    330: (30, 73), 331: (0, 29), 332: (0, 17), 333: (0, 29), 334: (0, 51), 335: (0, 106),
    336: (0, 10), 337: (0, 0), 338: (0, 80), 339: (0, 208), 340: (30, 155), 341: (100, 70),
    342: (10, 209), 343: (100, 105), 344: (0, 198), 345: (0, 17), 346: (0, 210), 347: (0, 211),
    348: (0, 43), 349: (0, 212), 350: (0, 29), 351: (0, 17), 352: (20, 76), 353: (0, 148),
    354: (100, 204), 355: (0, 0), 356: (0, 0), 357: (0, 0), 358: (0, 0), 359: (0, 48),
}

#: The twelve effect ids the measurement pinned by class, for readable warnings. Every other id is real but
#: unnamed here: a Gen III effect is a whole battle-script behaviour, not only a status.
EFFECT_NAMES: "dict[int, str]" = {
    1: "sleep", 2: "poison", 4: "burn", 5: "freeze", 6: "paralysis", 31: "flinch",
    33: "bad poison", 67: "paralysis", 70: "Speed down", 72: "Sp.Def down", 73: "accuracy down",
    76: "confusion",
}


def describe_effect(effect_id: int) -> str:
    """A name where the measurement pinned one, else the raw id -- never a guess."""
    name = EFFECT_NAMES.get(effect_id)
    return f"{name} ({effect_id})" if name else f"effect {effect_id}"


def moves_with_effects() -> "dict[int, tuple[int, int]]":
    """Only the moves that actually carry an effect id. The guards pin everything; this is for reporting."""
    return {index: pair for index, pair in MOVE_STATUS.items() if pair[1] != 0}


# Import fence: a census is worth nothing if it quietly loses rows or stops matching what it claims.
assert len(MOVE_STATUS) == 360, "the census must cover every move entry"
assert sorted(MOVE_STATUS) == list(range(360)), "move indices must be contiguous from 0"
assert all(0 <= c <= 100 and 0 <= e <= 0xFF for c, e in MOVE_STATUS.values()), \
    "a chance is a percentage and an effect id is a byte"
assert len(moves_with_effects()) == 332, "the effect-carrying count moved"
for _id in (1, 2, 4, 5, 6, 31, 33, 67, 70, 72, 73, 76):
    assert _id in {e for _c, e in MOVE_STATUS.values()}, f"effect {_id} left the census"
    assert _id in EFFECT_NAMES, f"effect {_id} lost its name"
del _id
# The two the reports named, as anchors: Icy Wind lowers Speed at 100%, Poison Fang badly poisons at 30%.
assert MOVE_STATUS[196] == (100, 70), "Icy Wind's row moved"
assert MOVE_STATUS[305] == (30, 202), "Poison Fang's row moved"
