"""Per-chest "already opened" flag: where it lives in the player-state block and how to read it.

Every XDTreasureBoxData entry carries a u16BE flag id at entry offset +0x06. It is an ordinary game flag -- the same
id space the map scripts' getFlag/setFlag use -- so where its bit lives is not measured but READ, from the game's own
flag descriptor table (6 bytes per flag id, in common.rel; `ram_client._gs_descriptor` reads the same table live for
the trainer beaten flags):

    byte 0 & 0x3F   width in bits (1 for every chest)
    byte 0 >> 3 & 0x18   which storage group (0x18 for every chest: the save block's flag words)
    bytes 2-3       bit position inside that group's storage

That group's storage sits at BLOCK_BASE + FLAG_STORAGE_OFFSET in every save and every boot looked at, and bit p is
bit p % 32 of the u32BE word at storage + 4 * (p // 32):

    open = u32BE(BLOCK_BASE + 0x106B0 + 4 * (p // 32)) >> (p % 32) & 1

The earlier cluster model (offsets 696/464/483 per cluster) was fitted to bytes measured with the block base taken
four bytes high, so its 1862-1944 cluster sat one word low and its 1440-1455 spacing was a guess; read against the
descriptor table it agrees with every live sample in absolute terms, and saves read this way open their chests in
story order (HQ Lab, then Gateon, Agate and Mt. Battle, then the Cave spot and Pyrite).

Chests 108 and 113 share flag id 1149, so opening either sets the same bit. AMBIGUOUS_CHEST_IDS names them;
anything needing per-chest identity must treat the pair as one.
"""
from __future__ import annotations

# Chests whose flag id is 0 -- the game records nothing for them. Both are in room 175, the debug room
# chest_regions.EXCLUDED_ROOMS already drops on independent grounds.
UNFLAGGED_CHEST_IDS: "frozenset[int]" = frozenset({114, 115})

#: Where the chests' flag group keeps its words, from BLOCK_BASE.
FLAG_STORAGE_OFFSET = 0x106B0

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

#: {flag id: bit position in the flag storage}, from the game's flag descriptor table (common.rel). Every chest flag
#: is one bit wide and in the save block's flag group. Do not hand-edit.
CHEST_FLAG_BITS: "dict[int, int]" = {
    1130: 1074, 1131: 1075, 1132: 1076, 1133: 1077, 1134: 1078, 1135: 1079, 1136: 1080, 1137: 1081, 1138: 1082,
    1139: 1083, 1140: 1084, 1141: 1085, 1142: 1086, 1143: 1087, 1144: 1088, 1145: 1089, 1146: 1090, 1147: 1091,
    1149: 1093, 1192: 1145, 1193: 1146, 1194: 1147, 1195: 1148, 1196: 1149, 1197: 1150, 1198: 1151, 1440: 1567,
    1444: 1572, 1454: 1630, 1455: 1631, 1712: 1897, 1713: 1898, 1714: 1899, 1715: 1900, 1716: 1901, 1717: 1902,
    1718: 1903, 1727: 1912, 1862: 2051, 1863: 2052, 1864: 2053, 1865: 2054, 1866: 2055, 1868: 2057, 1871: 2060,
    1872: 2061, 1873: 2062, 1874: 2063, 1875: 2064, 1876: 2065, 1877: 2066, 1884: 2073, 1885: 2074, 1886: 2075,
    1888: 2077, 1889: 2078, 1890: 2079, 1891: 2080, 1892: 2081, 1893: 2082, 1894: 2083, 1895: 2084, 1896: 2085,
    1897: 2086, 1898: 2087, 1899: 2088, 1900: 2089, 1901: 2090, 1902: 2091, 1903: 2092, 1904: 2093, 1905: 2094,
    1906: 2095, 1907: 2096, 1908: 2097, 1909: 2098, 1910: 2099, 1911: 2100, 1912: 2101, 1913: 2102, 1914: 2103,
    1915: 2104, 1916: 2105, 1917: 2106, 1918: 2107, 1919: 2108, 1920: 2109, 1921: 2110, 1922: 2111, 1923: 2112,
    1924: 2113, 1925: 2114, 1926: 2115, 1927: 2116, 1928: 2117, 1929: 2118, 1930: 2119, 1931: 2120, 1933: 2122,
    1934: 2123, 1935: 2124, 1936: 2125, 1937: 2126, 1938: 2127, 1939: 2128, 1940: 2129, 1941: 2130, 1942: 2131,
    1943: 2132, 1944: 2133, 2276: 2470, 2277: 2471,
}


def flag_is_validated(flag_id: int) -> bool:
    """True when the game's descriptor table places this flag (every chest flag does)."""
    return flag_id in CHEST_FLAG_BITS


def chest_flag_is_validated(chest_id: int) -> bool:
    """False only for a chest with no flag at all."""
    flag_id = CHEST_FLAG_IDS.get(chest_id)
    return bool(flag_id) and flag_is_validated(flag_id)


def unvalidated_chest_ids() -> "tuple[int, ...]":
    return tuple(sorted(
        chest_id for chest_id, flag_id in CHEST_FLAG_IDS.items()
        if flag_id and not flag_is_validated(flag_id)
    ))


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


def flag_bit_position(flag_id: int) -> "int | None":
    """The flag's bit position in its storage, or None for a flag this table does not hold."""
    return CHEST_FLAG_BITS.get(flag_id)


def flag_word_offset(flag_id: int) -> int:
    """Offset from BLOCK_BASE of the u32BE word holding `flag_id`'s bit."""
    return FLAG_STORAGE_OFFSET + 4 * (CHEST_FLAG_BITS[flag_id] // 32)


def flag_word_bit(flag_id: int) -> int:
    """Which bit of that word, counted from the word's LSB (0..31)."""
    return CHEST_FLAG_BITS[flag_id] % 32


def flag_byte_offset_and_mask(flag_id: int) -> "tuple[int, int]":
    """The same bit as a byte offset from BLOCK_BASE plus an 8-bit mask, for callers reading one byte. The
    `3 -` is the big-endian byte order inside the word."""
    bit = flag_word_bit(flag_id)
    return flag_word_offset(flag_id) + (3 - bit // 8), 1 << (bit % 8)


_FLAG_BY_POSITION: "dict[int, int]" = {position: flag_id for flag_id, position in CHEST_FLAG_BITS.items()}


def flag_at_byte_bit(byte_offset: int, bit_in_byte: int) -> "int | None":
    """Inverse of `flag_byte_offset_and_mask`: the chest flag a set bit at this byte/bit is, or None when that bit
    belongs to some other game flag. Used by the `/chestflags` diagnostic."""
    word = byte_offset & ~0x3
    position = ((word - FLAG_STORAGE_OFFSET) // 4) * 32 + (3 - (byte_offset - word)) * 8 + bit_in_byte
    return _FLAG_BY_POSITION.get(position)


def chest_flag_id(chest_id: int) -> "int | None":
    """The flag id for a chest, or None when the chest has no flag (the room-175 debug pair)."""
    flag_id = CHEST_FLAG_IDS.get(chest_id)
    return None if not flag_id else flag_id


def chest_byte_offset_and_mask(chest_id: int) -> "tuple[int, int] | None":
    flag_id = chest_flag_id(chest_id)
    return None if flag_id is None else flag_byte_offset_and_mask(flag_id)


def flagged_chest_ids() -> "tuple[int, ...]":
    return tuple(sorted(c for c in CHEST_FLAG_IDS if CHEST_FLAG_IDS[c]))


assert UNFLAGGED_CHEST_IDS == frozenset(c for c in CHEST_FLAG_IDS if not CHEST_FLAG_IDS[c]), (
    "UNFLAGGED_CHEST_IDS disagrees with the generated table"
)
assert set(CHEST_FLAG_BITS) == {f for f in CHEST_FLAG_IDS.values() if f}, "a chest flag has no descriptor"
assert len(_FLAG_BY_POSITION) == len(CHEST_FLAG_BITS), "two chest flags share a bit"
