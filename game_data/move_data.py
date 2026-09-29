"""Move type, plus a curated table of strong TM attacks, for the moveset chooser.

Standard Gen I-III move data reconstructed from general game knowledge, not extracted from the ISO -- no
move-data extraction exists in this codebase -- and not verified line by line. Move ids are this game's own,
the numbering `species_level_up_moves.json` and `STATUS_MOVE_IDS` use (Gen III National ordering, 1-354);
Shadow moves are a disjoint 356-373 and are not here, since Shadow slots never reach the TM step.

TM_ATTACKING_MOVES is the fixed Gen III TM set filtered to damaging attacks of 80+ base power, offered to
every species uniformly -- real per-species TM compatibility would need the ISO's TM bitmask, which nothing
here extracts. Excludes Hidden Power (no fixed type), Facade and Giga Drain (under 80 BP in Gen III) and
every HM.
"""

from __future__ import annotations

# {move_id: type_name} -- standard Gen I-III move types, National move dex id order (1-354).
MOVE_TYPES: dict[int, str] = {
    1: "Normal", 2: "Fighting", 3: "Normal", 4: "Normal", 5: "Normal", 6: "Normal", 7: "Fire",
    8: "Ice", 9: "Electric", 10: "Normal", 11: "Normal", 12: "Normal", 13: "Normal", 14: "Normal",
    15: "Normal", 16: "Flying", 17: "Flying", 18: "Normal", 19: "Flying", 20: "Normal",
    21: "Normal", 22: "Grass", 23: "Normal", 24: "Fighting", 25: "Normal", 26: "Fighting",
    27: "Fighting", 28: "Ground", 29: "Normal", 30: "Normal", 31: "Normal", 32: "Normal",
    33: "Normal", 34: "Normal", 35: "Normal", 36: "Normal", 37: "Normal", 38: "Normal",
    39: "Normal", 40: "Poison", 41: "Bug", 42: "Bug", 43: "Normal", 44: "Dark", 45: "Normal",
    46: "Normal", 47: "Normal", 48: "Normal", 49: "Normal", 50: "Normal", 51: "Poison", 52: "Fire",
    53: "Fire", 54: "Ice", 55: "Water", 56: "Water", 57: "Water", 58: "Ice", 59: "Ice",
    60: "Psychic", 61: "Water", 62: "Ice", 63: "Normal", 64: "Flying", 65: "Flying",
    66: "Fighting", 67: "Fighting", 68: "Fighting", 69: "Fighting", 70: "Normal", 71: "Grass",
    72: "Grass", 73: "Grass", 74: "Normal", 75: "Grass", 76: "Grass", 77: "Poison", 78: "Grass",
    79: "Grass", 80: "Grass", 81: "Bug", 82: "Dragon", 83: "Fire", 84: "Electric",
    85: "Electric", 86: "Electric", 87: "Electric", 88: "Rock", 89: "Ground", 90: "Ground",
    91: "Ground", 92: "Poison", 93: "Psychic", 94: "Psychic", 95: "Psychic", 96: "Psychic",
    97: "Psychic", 98: "Normal", 99: "Normal", 100: "Psychic", 101: "Ghost", 102: "Normal",
    103: "Normal", 104: "Normal", 105: "Normal", 106: "Normal", 107: "Normal", 108: "Normal",
    109: "Ghost", 110: "Water", 111: "Normal", 112: "Psychic", 113: "Psychic", 114: "Ice",
    115: "Psychic", 116: "Normal", 117: "Normal", 118: "Normal", 119: "Flying", 120: "Normal",
    121: "Normal", 122: "Ghost", 123: "Poison", 124: "Poison", 125: "Ground", 126: "Fire",
    127: "Water", 128: "Water", 129: "Normal", 130: "Normal", 131: "Normal", 132: "Normal",
    133: "Psychic", 134: "Psychic", 135: "Normal", 136: "Fighting", 137: "Normal",
    138: "Psychic", 139: "Poison", 140: "Normal", 141: "Bug", 142: "Normal", 143: "Flying",
    144: "Normal", 145: "Water", 146: "Normal", 147: "Grass", 148: "Normal", 149: "Psychic",
    150: "Normal", 151: "Poison", 152: "Water", 153: "Normal", 154: "Normal", 155: "Ground",
    156: "Psychic", 157: "Rock", 158: "Normal", 159: "Normal", 160: "Normal", 161: "Normal",
    162: "Normal", 163: "Normal", 164: "Normal", 165: "Normal", 166: "Normal", 167: "Fighting",
    168: "Dark", 169: "Bug", 170: "Normal", 171: "Ghost", 172: "Fire", 173: "Normal",
    174: "Ghost", 175: "Normal", 176: "Normal", 177: "Flying", 178: "Grass", 179: "Fighting",
    180: "Ghost", 181: "Ice", 182: "Normal", 183: "Fighting", 184: "Normal", 185: "Dark",
    186: "Normal", 187: "Normal", 188: "Poison", 189: "Ground", 190: "Water", 191: "Ground",
    192: "Electric", 193: "Normal", 194: "Ghost", 195: "Normal", 196: "Ice", 197: "Fighting",
    198: "Ground", 199: "Normal", 200: "Dragon", 201: "Rock", 202: "Grass", 203: "Normal",
    204: "Normal", 205: "Rock", 206: "Normal", 207: "Normal", 208: "Normal", 209: "Electric",
    210: "Bug", 211: "Steel", 212: "Normal", 213: "Normal", 214: "Normal", 215: "Normal",
    216: "Normal", 217: "Normal", 218: "Normal", 219: "Normal", 220: "Normal", 221: "Fire",
    222: "Ground", 223: "Fighting", 224: "Bug", 225: "Dragon", 226: "Normal", 227: "Normal",
    228: "Dark", 229: "Normal", 230: "Normal", 231: "Steel", 232: "Steel", 233: "Fighting",
    234: "Normal", 235: "Grass", 236: "Dark", 237: "Normal", 238: "Fighting", 239: "Dragon",
    240: "Water", 241: "Fire", 242: "Dark", 243: "Psychic", 244: "Normal", 245: "Normal",
    246: "Rock", 247: "Ghost", 248: "Psychic", 249: "Fighting", 250: "Water", 251: "Dark",
    252: "Normal", 253: "Normal", 254: "Normal", 255: "Normal", 256: "Normal", 257: "Fire",
    258: "Ice", 259: "Dark", 260: "Dark", 261: "Fire", 262: "Dark", 263: "Normal",
    264: "Fighting", 265: "Normal", 266: "Normal", 267: "Normal", 268: "Electric", 269: "Dark",
    270: "Normal", 271: "Psychic", 272: "Psychic", 273: "Normal", 274: "Normal", 275: "Grass",
    276: "Fighting", 277: "Psychic", 278: "Normal", 279: "Fighting", 280: "Fighting",
    281: "Normal", 282: "Dark", 283: "Normal", 284: "Fire", 285: "Psychic", 286: "Psychic",
    287: "Normal", 288: "Ghost", 289: "Dark", 290: "Normal", 291: "Water", 292: "Fighting",
    293: "Normal", 294: "Bug", 295: "Psychic", 296: "Psychic", 297: "Flying", 298: "Normal",
    299: "Fire", 300: "Ground", 301: "Ice", 302: "Grass", 303: "Normal", 304: "Normal",
    305: "Poison", 306: "Normal", 307: "Fire", 308: "Water", 309: "Steel", 310: "Ghost",
    311: "Normal", 312: "Grass", 313: "Dark", 314: "Flying", 315: "Fire", 316: "Normal",
    317: "Rock", 318: "Bug", 319: "Steel", 320: "Grass", 321: "Normal", 322: "Psychic",
    323: "Water", 324: "Bug", 325: "Ghost", 326: "Psychic", 327: "Fighting", 328: "Ground",
    329: "Ice", 330: "Water", 331: "Grass", 332: "Flying", 333: "Ice", 334: "Steel",
    335: "Normal", 336: "Normal", 337: "Dragon", 338: "Grass", 339: "Fighting", 340: "Flying",
    341: "Ground", 342: "Poison", 343: "Normal", 344: "Electric", 345: "Grass", 346: "Water",
    347: "Psychic", 348: "Grass", 349: "Dragon", 350: "Rock", 351: "Electric", 352: "Water",
    353: "Steel", 354: "Psychic",
}

# {move_id: base_power} -- Gen III TM moves that are damaging attacks of 80+ base power.
TM_ATTACKING_MOVES: dict[int, int] = {
    264: 150,  # TM01 Focus Punch (Fighting)
    337: 80,   # TM02 Dragon Claw (Dragon)
    58: 95,    # TM13 Ice Beam (Ice)
    59: 120,   # TM14 Blizzard (Ice)
    63: 150,   # TM15 Hyper Beam (Normal)
    76: 120,   # TM22 Solarbeam (Grass)
    231: 100,  # TM23 Iron Tail (Steel)
    85: 95,    # TM24 Thunderbolt (Electric)
    87: 120,   # TM25 Thunder (Electric)
    89: 100,   # TM26 Earthquake (Ground)
    94: 90,    # TM29 Psychic (Psychic)
    247: 80,   # TM30 Shadow Ball (Ghost)
    53: 95,    # TM35 Flamethrower (Fire)
    188: 90,   # TM36 Sludge Bomb (Poison)
    126: 120,  # TM38 Fire Blast (Fire)
    315: 140,  # TM50 Overheat (Fire)
}


def move_type(move_id: int) -> str | None:
    """The move's elemental type, or None for an unmapped id (a Shadow move, or move 0). Callers treat
    unknown as "not a duplicate type" rather than raising."""
    return MOVE_TYPES.get(move_id)
