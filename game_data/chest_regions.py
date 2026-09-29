"""Room -> region, and therefore chest -> region, which is derived from chest_table.CHESTS's `room` field
rather than typed out so a chest cannot land in a region its room does not belong to.

Room 107 is Phenac despite chest-id adjacency suggesting Pyrite: chest 79 there holds the Elevator Key. Two
rooms are excluded outright so their chests are never AP locations -- room 175 (chest 114 System Lever x10,
chest 115 item id 0 x10: a debug room) and room 145 (chest 9, Battle CD 06, location unknown).
"""
from __future__ import annotations

from . import chest_table

# Regions are spelled exactly as story_bytes.py and regions.py spell them.
ROOM_TO_REGION: "dict[int, str]" = {
    # --- always open -------------------------------------------------------------------------------------
    138: "Pokemon HQ Lab", 139: "Pokemon HQ Lab", 140: "Pokemon HQ Lab", 141: "Pokemon HQ Lab",
    142: "Pokemon HQ Lab",   # Master Ball room -- its chest 2 is gated separately, see CHEST_ITEM_GATES
    143: "Pokemon HQ Lab",
    # The manor is walkable from the start but its chests are not takeable until Verich's cutscene puts the
    # story at 0x53, which is exactly when "Kaminko's House (Robo Groudon)" opens.
    169: "Kaminko's House (Robo Groudon)", 173: "Kaminko's House (Robo Groudon)",
    171: "Kaminko's House (Robo Groudon)",  # Lower Crane Room (player, 2026-09-13) -- chests 108, 109
    146: "Gateon Port", 153: "Gateon Port", 156: "Gateon Port", 158: "Gateon Port", 160: "Gateon Port",
    # --- story ordered -----------------------------------------------------------------------------------
    125: "Agate Village", 126: "Agate Village", 132: "Agate Village",
    134: "Agate Village",    # Agate shop (player, 2026-09-13)
    20: "Mt. Battle", 21: "Mt. Battle",
    1: "Cipher Lab", 7: "Cipher Lab", 8: "Cipher Lab", 9: "Cipher Lab", 10: "Cipher Lab", 11: "Cipher Lab",
    117: "Pyrite Town", 119: "Pyrite Town", 120: "Pyrite Town", 121: "Pyrite Town",
    90: "Poke Spots", 91: "Poke Spots", 92: "Poke Spots",
    109: "Pyrite Town (ONBS)", 110: "Pyrite Town (ONBS)",
    49: "Realgam Tower", 50: "Realgam Tower", 58: "Realgam Tower", 59: "Realgam Tower",
    60: "Realgam Tower", 61: "Realgam Tower",
    94: "Phenac City", 95: "Phenac City", 100: "Phenac City",
    98: "Phenac City",       # holds chest 80, the MUSIC DISC -- must NOT sit behind the Music Disc gate
    107: "Phenac City",      # Phenac Colosseum (player correction, confirmed by the Elevator Key in chest 79)
    97: "Phenac City (Mayor's House)",   # Mayor's House upstairs -- chest 78, the MAYOR'S NOTE
    96: "Phenac City (Mayor's House)",   # Mayor's House downstairs -- where the Music Disc is USED
    103: "Phenac City (Post-Sixes)", 104: "Phenac City (Post-Sixes)",
    37: "SS Libra", 38: "SS Libra", 39: "SS Libra", 40: "SS Libra", 41: "SS Libra", 43: "SS Libra",
    172: "Kaminko's House (Robo Groudon)",   # Crane Room -- chests 110-113
    64: "Cipher Key Lair", 65: "Cipher Key Lair", 66: "Cipher Key Lair", 67: "Cipher Key Lair",
    68: "Cipher Key Lair", 70: "Cipher Key Lair",
    # ADDENDUM 394: 163 is the INSIDE of the stand (live `!room`), 164 the exterior. Both are the same place,
    # so `region_for_room` has to answer the same for either -- the story-byte guard reads this map, and a
    # player standing at the counter was resolving to no region at all.
    163: "Outskirt Stand",
    164: "Outskirt Stand",
    165: "Snagem Hideout", 166: "Snagem Hideout", 167: "Snagem Hideout",
    # Citadark Isle -- the contiguous chests 57-75 block.
    73: "Citadark Isle", 76: "Citadark Isle", 77: "Citadark Isle", 80: "Citadark Isle", 81: "Citadark Isle",
    82: "Citadark Isle", 83: "Citadark Isle", 84: "Citadark Isle", 85: "Citadark Isle", 88: "Citadark Isle",
}

EXCLUDED_ROOMS: "dict[int, str]" = {
    175: "debug room -- System Lever x10 and a chest holding item id 0 x10",
    145: "location unknown; the player's instruction was to skip it",
}

# Chests whose region is not enough on its own -- an extra item requirement on top of reaching the room.
CHEST_ITEM_GATES: "dict[int, tuple[str, ...]]" = {
    27: ("ID Card",),        # player: "27 locked behind ID card"
    # The Cipher Lab half is already the chest's region, so this adds the item half; both names resolve
    # through `items.requirement_to_pool_item` to one pool item. Not self-gating -- the ROM lives in chest 17,
    # and fill_restrictive will not place an item on a location whose own rule demands it.
    23: ("Data ROM", "ID Card"),
    # The three ONBS chests: 98 and 99 in room 110 (3F), 100 in room 109 (2F). Belt and braces -- the region
    # is reachable only through `Poke Spots`, whose edge already requires the Data ROM -- but the explicit
    # entry survives any future re-parenting of the ONBS region. Not self-gating: the ROM lives in chest 17.
    98: ("Data ROM", "ID Card"),
    99: ("Data ROM", "ID Card"),
    100: ("Data ROM", "ID Card"),
}

# Gated on a region, not an item: chest 2 opens on story transition 0x6C->0x6E, the same one that opens
# Citadark Isle, so the Robo Kyogre Part count has one home (the Citadark edge in regions.py) and
# robo_kyogre_parts_unlock_citadark being off is tracked for free.
CHEST_REGION_GATES: "dict[int, tuple[str, ...]]" = {
    2: ("Citadark Isle",),   # 0x6C->0x6E opens the Master Ball chest and Citadark Isle in the same breath
    # The Colosseum lobby is not gated but its three chests are. Named as a region, not as the Music Disc and
    # Mayor's Note: with key_item_shuffle off those are not pool items and an item gate would filter to
    # nothing. Not self-gating -- the Disc is chest 80 (room 98), the Note chest 78 (room 97).
    89: ("Phenac City (Post-Sixes)",),
    90: ("Phenac City (Post-Sixes)",),
    91: ("Phenac City (Post-Sixes)",),
}


def _build() -> "tuple[dict[int, str], list[int], list[int]]":
    by_chest: "dict[int, str]" = {}
    excluded: "list[int]" = []
    unplaced: "list[int]" = []
    for chest in chest_table.CHESTS:
        room = chest["room"]
        if room in EXCLUDED_ROOMS:
            excluded.append(chest["chest"])
            continue
        region = ROOM_TO_REGION.get(room)
        if region is None:
            unplaced.append(chest["chest"])
            continue
        by_chest[chest["chest"]] = region
    return by_chest, sorted(excluded), sorted(unplaced)


CHEST_TO_REGION, EXCLUDED_CHESTS, UNPLACED_CHESTS = _build()

ROOMS_BY_REGION: "dict[str, list[int]]" = {}
for _room, _region in sorted(ROOM_TO_REGION.items()):
    ROOMS_BY_REGION.setdefault(_region, []).append(_room)

REGIONS_WITH_CHESTS: "frozenset[str]" = frozenset(CHEST_TO_REGION.values())


def region_for_chest(chest_id: int) -> "str | None":
    return CHEST_TO_REGION.get(chest_id)


def region_for_room(room_id: "int | None") -> "str | None":
    return None if room_id is None else ROOM_TO_REGION.get(room_id)


assert not UNPLACED_CHESTS, (
    f"every chest must land in a region or an excluded room; unplaced: {UNPLACED_CHESTS}"
)
