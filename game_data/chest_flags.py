"""Per-chest "already opened" flag: where it lives in the player-state block and how to read it.

Every XDTreasureBoxData entry carries a u16BE flag id at entry offset +0x06. The id indexes a global bitfield
of u32BE words in the player-state block:

    i    = flag_id - FLAG_ANCHOR_ID
    word = BLOCK_BASE + FLAG_WORD_BASE_OFFSET + 4 * (i // 32)      # floor division, i may be negative
    open = u32BE(word) & (1 << (i % 32))

Measured live 2026-09-13 on the player's save: chest 3 (room 138) flipped BLOCK_BASE+0x107AC 0x00 -> 0x08 and
chest 40 (room 49) flipped BLOCK_BASE+0x107B2 0x00 -> 0x40, the only changes outside the Bag in a 0x30000-byte
span. BLOCK_BASE was 0x80479504 in all four dumps. A search over bits-per-flag x bit order x word swap x every
offset in +/-8192 left one family: 1 bit per flag, LSB-first, 4-byte swap. Two alignments fit and answer
identically for all 115 chests; this file uses the 4-byte-aligned one, the other being anchor 1867 with base
0x107AB. Do not read it as "bit index = chest id": that fits the first sample by luck and breaks on the second.

The four dumps decode monotonically -- 95/96/97, then +3, then +40 -- and 95, 96, 97 are consecutive ids all in
room 117, i.e. one room cleared, which is what a real save leaves behind rather than an arbitrary bit pattern.

This is the GLOBAL flag array, not a chest-only one: set bits at BLOCK_BASE+0x10791, +0x1079C and +0x107E1 in
the same dumps decode to no chest. Nothing may be written into it on a guess.

Chests 108 and 113 share flag id 1149, so opening either sets the same bit. AMBIGUOUS_CHEST_IDS names them;
anything needing per-chest identity must treat the pair as one.
"""
from __future__ import annotations

# The flag id whose bit sits at bit 0 of the word at FLAG_WORD_BASE_OFFSET.
FLAG_ANCHOR_ID = 1859
FLAG_WORD_BASE_OFFSET = 0x107AC

# Chests whose flag id is 0 -- the game records nothing for them. Both are in room 175, the debug room
# chest_regions.EXCLUDED_ROOMS already drops on independent grounds.
UNFLAGGED_CHEST_IDS: "frozenset[int]" = frozenset({114, 115})


# Flag ids fall in six clusters, not one contiguous run, and ADDENDUM 173's model was fitted entirely inside
# 1862..1944; it reaches the others by arithmetic alone:
#
#     1130..1149   i -729..-710   20 chests   <- the HQ Lab, Gateon, Agate, Phenac, Cipher Lab...
#     1192..1198   i -667..-661    7 chests
#     1440..1455   i -419..-404    4 chests
#     1712..1727   i -147..-132    8 chests
#     1862..1944   i   +3..  +85   72 chests   <- the only cluster any measurement touched
#     2276..2277   i +417.. +418    2 chests
#
# The four original dumps contradict the extrapolation: every byte the single-line model assigns to the four
# below-anchor clusters (0x10750-0x10753, 0x1075A-0x1075B, 0x10774, 0x1077A-0x1077B, 0x10798-0x1079A) and to
# 0x107E3 above it is ZERO in all four, on a save that had already cleared room 117 -- while a dense band of set
# bits at 0x1071C..0x10730 maps to no chest at all. So an unmeasured cluster gets no answer rather than a wrong
# one: `chest_flag_is_validated` is False there and `ram_client.chest_is_open_in_block` returns None.
DIRECTLY_EVIDENCED_FLAG_IDS: "frozenset[int]" = frozenset({1872, 1873, 1874, 1886, 1905})

# Kept for callers; superseded by CLUSTER_POSITION_OFFSETS, which now covers more than one cluster.
VALIDATED_FLAG_ID_RANGE: "tuple[int, int]" = (1862, 1944)


def flag_is_validated(flag_id: int) -> bool:
    """True when the flag's whole CLUSTER has been measured. Derived from CLUSTER_POSITION_OFFSETS rather than
    a hard-coded range, so measuring another cluster does not mean editing this fence."""
    return flag_bit_position(flag_id) is not None


def chest_flag_is_validated(chest_id: int) -> bool:
    """False for a chest this module can only locate arithmetically, and for a chest with no flag at all."""
    flag_id = CHEST_FLAG_IDS.get(chest_id)
    return bool(flag_id) and flag_is_validated(flag_id)


def unvalidated_chest_ids() -> "tuple[int, ...]":
    return tuple(sorted(
        chest_id for chest_id, flag_id in CHEST_FLAG_IDS.items()
        if flag_id and not flag_is_validated(flag_id)
    ))

# GENERATED from the player's own ISO (common_rel, XDTreasureBoxData entry offset +0x06). Do not hand-edit.
CHEST_FLAG_IDS: "dict[int, int]" = {
    1: 1136,  # room 143
    2: 1137,  # room 142
    3: 1886,  # room 138
    4: 1140,  # room 153
    5: 1141,  # room 146
    6: 1142,  # room 158
    7: 1143,  # room 158
    8: 1138,  # room 160
    9: 1888,  # room 145
    10: 1132,  # room 132
    11: 1133,  # room 132
    12: 1134,  # room 126
    13: 1135,  # room 126
    14: 1884,  # room 132
    15: 1885,  # room 125
    16: 1144,  # room 1
    17: 1145,  # room 8
    18: 1139,  # room 8
    19: 1440,  # room 8
    20: 1889,  # room 1
    21: 1890,  # room 8
    22: 1891,  # room 8
    23: 1892,  # room 9
    24: 1893,  # room 10
    25: 1894,  # room 10
    26: 1895,  # room 10
    27: 1896,  # room 10
    28: 1897,  # room 9
    29: 1444,  # room 20
    30: 1146,  # room 38
    31: 1727,  # room 41
    32: 1898,  # room 37
    33: 1899,  # room 37
    34: 1900,  # room 39
    35: 1901,  # room 40
    36: 1902,  # room 41
    37: 1903,  # room 43
    38: 2276,  # room 38
    39: 1904,  # room 58
    40: 1905,  # room 49
    41: 1906,  # room 59
    42: 1147,  # room 67
    43: 1192,  # room 64
    44: 1193,  # room 64
    45: 1194,  # room 65
    46: 1195,  # room 65
    47: 1196,  # room 66
    48: 1197,  # room 70
    49: 1907,  # room 64
    50: 1908,  # room 65
    51: 1909,  # room 66
    52: 1910,  # room 67
    53: 1911,  # room 67
    54: 1912,  # room 68
    55: 1913,  # room 68
    56: 2277,  # room 64
    57: 1198,  # room 82
    58: 1914,  # room 88
    59: 1915,  # room 76
    60: 1916,  # room 77
    61: 1917,  # room 77
    62: 1918,  # room 80
    63: 1919,  # room 80
    64: 1920,  # room 80
    65: 1921,  # room 81
    66: 1922,  # room 81
    67: 1923,  # room 83
    68: 1924,  # room 83
    69: 1925,  # room 83
    70: 1926,  # room 84
    71: 1927,  # room 84
    72: 1928,  # room 85
    73: 1929,  # room 85
    74: 1930,  # room 85
    75: 1931,  # room 73
    76: 1933,  # room 73
    77: 1712,  # room 92
    78: 1130,  # room 97
    79: 1131,  # room 107
    80: 1454,  # room 98
    81: 1713,  # room 100
    82: 1714,  # room 100
    83: 1715,  # room 100
    84: 1716,  # room 100
    85: 1717,  # room 96
    86: 1718,  # room 96
    87: 1862,  # room 100
    88: 1863,  # room 100
    89: 1864,  # room 107
    90: 1865,  # room 107
    91: 1866,  # room 107
    92: 1868,  # room 107
    93: 1455,  # room 119
    94: 1871,  # room 120
    95: 1872,  # room 117
    96: 1873,  # room 117
    97: 1874,  # room 117
    98: 1875,  # room 110
    99: 1876,  # room 110
    100: 1877,  # room 109
    101: 1934,  # room 165
    102: 1935,  # room 165
    103: 1936,  # room 166
    104: 1937,  # room 166
    105: 1938,  # room 166
    106: 1939,  # room 167
    107: 1940,  # room 167
    108: 1149,  # room 171
    109: 1941,  # room 171
    110: 1942,  # room 172
    111: 1943,  # room 172
    112: 1944,  # room 172
    113: 1149,  # room 172
    114: 0,  # room 175
    115: 0,  # room 175
}


def _ambiguous() -> "frozenset[int]":
    seen: "dict[int, list[int]]" = {}
    for chest_id, flag_id in CHEST_FLAG_IDS.items():
        if flag_id:
            seen.setdefault(flag_id, []).append(chest_id)
    out: "set[int]" = set()
    for chest_ids in seen.values():
        if len(chest_ids) > 1:
            out.update(chest_ids)
    return frozenset(out)


# Chests sharing a flag id, so indistinguishable. Derived, not hand-listed, so it survives a regeneration.
AMBIGUOUS_CHEST_IDS: "frozenset[int]" = _ambiguous()


# The array is one contiguous bitfield, but flag ids do not map onto it as a straight line: the offset is a
# property of the CLUSTER. Expressing each measurement as an absolute bit position from BLOCK_BASE+0x10700:
#
#     chest 98  flag 1875  ->  position 1392     flag_id - position = 483     (the ADDENDUM 173 cluster)
#     chest  1  flag 1136  ->  position  440     flag_id - position = 696
#     chest  4  flag 1140  ->  position  444     flag_id - position = 696     (PREDICTED first, then measured)
#
# 213 array slots sit between the two clusters with nothing known in them; other game flags share this array
# and some of them may be wider than one bit, so nothing here guesses at them.
#
# Within a cluster it is one bit per flag id. That was tested, not assumed: chest 1 (flag 1136) measured at bit
# 0 of BLOCK_BASE+0x10734 predicts chest 4 (flag 1140) at bit 4 of the same byte, stated in advance and hit.
#
# How to measure one: stand still, read a 1 KB window, open exactly one chest, read again. A clean sample
# changes ONE byte. Walking between rooms first changes about twelve -- story flags share this array and fire
# constantly -- so such a run is contaminated, not interpretable.
#
# Still unmeasured: clusters 1192-1198, 1712-1727 and 2276-2277 -- 17 of the 115 chests (96 have a measured
# flag; 114 and 115 have none at all). Fixing one takes two dumps around opening a single chest in it, then the
# same search anchored in that band. One sample can never tell a real mapping from a coincidence.
CLUSTER_POSITION_OFFSETS: "tuple[tuple[int, int, int], ...]" = (
    # (first flag id, last flag id, offset)  -- position = flag_id - offset
    (1130, 1149, 696),   # measured: chest 1, then chest 4 predicted from it and confirmed
    (1440, 1455, 464),   # measured: chest 80 only; spacing assumed -- see below
    (1862, 1944, 483),   # measured: chests 3, 40, 95, 96, 97
)

# Positions stay in flag-id order but the offsets go 696, 464, 483 -- not even monotone -- so no formula fitted
# to two clusters predicts a third. Never interpolate an offset for an unmeasured cluster; measure it.
#
# 1440-1455 has one measurement (chest 80), which fixes its offset but not its spacing; the one-bit-per-id rule
# is carried over from the other two clusters there. Opening chest 93 (Pyrite room 119, predicted
# BLOCK_BASE+0x10778 mask 0x80) or chest 29 (Mt. Battle exterior, predicted +0x10779 mask 0x10) would settle it.

# The origin the offsets above are measured from. Word-aligned, and deliberately not FLAG_WORD_BASE_OFFSET,
# which is one cluster's own base -- mistaking it for the array origin is what produced the single-line model.
FLAG_ARRAY_ORIGIN_OFFSET = 0x10700


def flag_bit_position(flag_id: int) -> "int | None":
    """Absolute bit position in the flag array, or None for a flag in a cluster nobody has measured."""
    for lo, hi, offset in CLUSTER_POSITION_OFFSETS:
        if lo <= flag_id <= hi:
            return flag_id - offset
    return None


def flag_word_offset(flag_id: int) -> int:
    """Offset from BLOCK_BASE of the u32BE word holding `flag_id`'s bit.

    Resolved per cluster. An unmeasured cluster still gets the old single-line answer so callers keep a shape to
    work with, but `chest_flag_is_validated` is False there and the client refuses to act on it."""
    position = flag_bit_position(flag_id)
    if position is not None:
        return FLAG_ARRAY_ORIGIN_OFFSET + 4 * (position // 32)
    i = flag_id - FLAG_ANCHOR_ID
    return FLAG_WORD_BASE_OFFSET + 4 * (i // 32)   # floor division on purpose: i is negative for low ids


def flag_word_bit(flag_id: int) -> int:
    """Which bit of that word, counted from the word's LSB (0..31)."""
    position = flag_bit_position(flag_id)
    if position is not None:
        return position % 32
    return (flag_id - FLAG_ANCHOR_ID) % 32


def flag_byte_offset_and_mask(flag_id: int) -> "tuple[int, int]":
    """The same bit as a byte offset from BLOCK_BASE plus an 8-bit mask, for callers reading one byte. The
    `3 -` is the big-endian byte order inside the word -- what made the raw measurements look scrambled."""
    bit = flag_word_bit(flag_id)
    return flag_word_offset(flag_id) + (3 - bit // 8), 1 << (bit % 8)


def chest_flag_id(chest_id: int) -> "int | None":
    """The flag id for a chest, or None when the chest has no flag (the room-175 debug pair)."""
    flag_id = CHEST_FLAG_IDS.get(chest_id)
    return None if not flag_id else flag_id


def chest_byte_offset_and_mask(chest_id: int) -> "tuple[int, int] | None":
    flag_id = chest_flag_id(chest_id)
    return None if flag_id is None else flag_byte_offset_and_mask(flag_id)


def flag_at_byte_bit(byte_offset: int, bit_in_byte: int) -> int:
    """Inverse of `flag_byte_offset_and_mask`: which flag id a set bit at this byte/bit means. Used by the
    `!chestflags` diagnostic, where naming the set bits is how a disagreement with the model shows up."""
    word = byte_offset & ~0x3
    bit = (3 - (byte_offset - word)) * 8 + bit_in_byte
    # Measured clusters first, so the diagnostic names a bit the way the forward mapping placed it. Their
    # position ranges are disjoint, so a position can match at most one.
    position = ((word - FLAG_ARRAY_ORIGIN_OFFSET) // 4) * 32 + bit
    for lo, hi, offset in CLUSTER_POSITION_OFFSETS:
        if lo - offset <= position <= hi - offset:
            return position + offset
    # Outside every measured cluster: the old single-line reading, known wrong there. Treat it as "what the old
    # model would have called this bit", never as a fact.
    return FLAG_ANCHOR_ID + ((word - FLAG_WORD_BASE_OFFSET) // 4) * 32 + bit


def flagged_chest_ids() -> "tuple[int, ...]":
    return tuple(sorted(c for c in CHEST_FLAG_IDS if CHEST_FLAG_IDS[c]))


assert UNFLAGGED_CHEST_IDS == frozenset(c for c in CHEST_FLAG_IDS if not CHEST_FLAG_IDS[c]), (
    "UNFLAGGED_CHEST_IDS disagrees with the generated table"
)
