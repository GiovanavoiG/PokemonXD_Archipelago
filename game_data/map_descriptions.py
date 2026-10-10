"""ADDENDUM 454 -- one description per place on the world map.

Player: "when hovering locations on the map, the location description text jumps as we write the story byte. Can we
just rewrite all the descriptions in the iso to be the same (whatever the first/earliest one is) so that when it
"rewrites" it's just the same text anyway?"

THE TABLE (measured in three MEM1 dumps -- mapsel_s1_phenac, reboot_phenac, vis_dump3_snagem -- at three different
heap addresses, with relocated code right before it storing its address, so it is a REL module's data): 22 records
of 19 u32. Word 0 is the story-progress threshold the record applies from (1, 4, 0x0D, ... 0x63); words 1-18 are the
message ids of the 18 map places' name + description, in this order:

    Outskirt Stand, Snagem Hideout, Kaminko's House, Phenac, Pyrite, Agate, HQ Lab, Gateon, Cipher Lab,
    Mt. Battle, S.S. Libra, Realgam Tower, Key Lair, Citadark Isle, Orre Colosseum, Rock / Oasis / Cave Poke Spots

The game shows the last record whose threshold the story byte has reached. Six places change text along the way
(Snagem, Phenac, Pyrite, Cipher Lab, S.S. Libra, Key Lair), so when the client moves the story byte while the map
is open, the hovered text flips between records.

THE PATCH writes one set of 18 ids (`TARGET_IDS`) into every record (thresholds untouched): same size, same file,
every record now names the same text. That set is the first record's -- the earliest wording -- except for the three
places whose first wording hides them. Player: "Switch Libra, Cipher Lab and Key Lair to their first clear one (so
make it cipher lab, and give the other two their first ones with real descriptions/name":

    Cipher Lab  d4eb "MYSTERY FACILITY"  -> d4fd "CIPHER LAB / CIPHER's old lab back in operation. ..."
    S.S. Libra  d4ed "???"               -> d4ff "S.S. LIBRA / The POKeMON cargo ship that went missing ..."
    Key Lair    d4ef "???"               -> d501 "CIPHER KEY LAIR / A factory made secretly by CIPHER. ..."

(each the first record that names the place; texts decoded from the map-selection message table in a RAM dump).

The patcher finds the table by content inside the map-selection files (`CANDIDATE_FSYS`), proves all 22 records,
and refuses otherwise.
"""
from __future__ import annotations

import struct

RECORD_WORDS = 19
RECORD_COUNT = 22
RECORD_SIZE = RECORD_WORDS * 4

#: The first record, word for word (threshold 1, then the 18 message ids).
FIRST_RECORD = (
    0x01, 0xD4F1, 0xD4F2, 0xD4F3, 0xD4E5, 0xD4E6, 0xD4E7, 0xD4E9, 0xD4EA, 0xD4EB, 0xD4EC, 0xD4ED, 0xD4EE, 0xD4EF,
    0xD4F0, 0xD4F9, 0xD4F4, 0xD4F5, 0xD4F6,
)
#: Word index (1-18) of the three places whose first wording is a placeholder, and their first named wording.
CIPHER_LAB_WORD, SS_LIBRA_WORD, KEY_LAIR_WORD = 9, 11, 13
FIRST_NAMED_IDS = {CIPHER_LAB_WORD: 0xD4FD, SS_LIBRA_WORD: 0xD4FF, KEY_LAIR_WORD: 0xD501}
#: The 18 ids every record gets.
TARGET_IDS = tuple(FIRST_NAMED_IDS.get(i, FIRST_RECORD[i]) for i in range(1, RECORD_WORDS))
#: Every record's threshold, in order (read off the dumps).
THRESHOLDS = (0x01, 0x04, 0x0D, 0x15, 0x19, 0x1B, 0x1C, 0x1F, 0x27, 0x2A, 0x2B, 0x2F, 0x30, 0x3A, 0x46, 0x49, 0x4C,
              0x50, 0x51, 0x57, 0x62, 0x63)
#: The message ids a record may hold: the 31 place texts of the map-selection message table.
MESSAGE_ID_RANGE = range(0xD4E5, 0xD504)
#: The later wordings, (word index, id): Snagem d502; Phenac d4fa; Pyrite d4fb/d4fc; Cipher Lab d4fd/d4fe;
#: S.S. Libra d4ff/d500; Key Lair d501/d503.
VARIANT_IDS = frozenset((0xD502, 0xD4FA, 0xD4FB, 0xD4FC, 0xD4FD, 0xD4FE, 0xD4FF, 0xD500, 0xD501, 0xD503))

#: Where to look, most likely first. The REL module that holds the table is part of the world-map screen.
CANDIDATE_FSYS = ("world_map.fsys", "worldmap.fsys", "worldmap_char.fsys", "worldmap_movedemo.fsys")

_SIGNATURES = (struct.pack(f">{RECORD_WORDS}I", *FIRST_RECORD),
               struct.pack(f">{RECORD_WORDS}I", FIRST_RECORD[0], *TARGET_IDS))


def find_table(data: bytes) -> "int | None":
    """Offset of the table in `data`, or None. Every record is proven: its threshold is the measured one and its 18
    ids are place texts. A table already rewritten (every record = `TARGET_IDS`) is found too."""
    for signature in _SIGNATURES:
        at = data.find(signature)
        while at >= 0:
            if _is_table(data, at):
                return at
            at = data.find(signature, at + 1)
    return None


def _is_table(data: bytes, at: int) -> bool:
    if at + RECORD_COUNT * RECORD_SIZE > len(data):
        return False
    for index in range(RECORD_COUNT):
        words = struct.unpack_from(f">{RECORD_WORDS}I", data, at + index * RECORD_SIZE)
        if words[0] != THRESHOLDS[index]:
            return False
        if any(w not in MESSAGE_ID_RANGE for w in words[1:]):
            return False
    return True


def rewrite(data: bytearray, at: int) -> int:
    """Write `TARGET_IDS` over every record's 18 ids. Returns how many records changed."""
    new = struct.pack(f">{RECORD_WORDS - 1}I", *TARGET_IDS)
    changed = 0
    for index in range(RECORD_COUNT):
        off = at + index * RECORD_SIZE + 4
        if bytes(data[off:off + len(new)]) != new:
            data[off:off + len(new)] = new
            changed += 1
    return changed


assert len(FIRST_RECORD) == RECORD_WORDS and len(THRESHOLDS) == RECORD_COUNT
assert len(TARGET_IDS) == RECORD_WORDS - 1 and all(i in MESSAGE_ID_RANGE for i in TARGET_IDS)
