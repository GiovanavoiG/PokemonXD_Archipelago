"""Human names for chest locations that have one.

A location name is its identity to Archipelago, and `locations.py` and `ram_client.py` build it independently
-- ram_client must stay importable without the world package -- so both read this table. Keyed by the
chest-id tuple, because a merged location can carry two ids (`chest_flags.AMBIGUOUS_CHEST_IDS`); anything
unlisted keeps the generated "Chest N (Room R)" form. Renaming is safe, renumbering is not: a renamed entry
keeps its frozen id, at the cost of in-flight seeds."""
from __future__ import annotations

# Names come from the player's room-by-room list, every row checked against the ISO by the fence at the foot
# of this module. That fence settled three discrepancies, all in the ISO's favour: room 1 holds chests 16 and
# 20 (17 is room 8's), room 8 holds five (17, 18, 19, 21, 22), and of the Kaminko Crane Room's 110-113 only
# 113 is an AP location. Chest 98 was "Pickup PDA" until the ISO settled it -- room 110 (ONBS), a Revive,
# beside 99 -- so 98/99 keep ids 1510/1511 and the old labels stay in `_FROZEN_LOCATION_OFFSETS`.
CHEST_LOCATION_NAME_OVERRIDES: "dict[tuple[int, ...], str]" = {
    # HQ Lab and the port
    (1,): "Outside HQ Lab",
    (2,): "Master Ball Chest",
    (3,): "Player's Room Chest",
    (5,): "Krabby Klub Basement Chest",
    (6,): "Gateon Tower 1F Chest 1",
    (7,): "Gateon Tower 1F Chest 2",
    (8,): "Gateon Tower 3F Chest",

    # Agate Village
    (10,): "Agate Bridge Chest",
    (11,): "Agate Right Side Chest",
    (14,): "Behind Eagun's House Chest",
    (12,): "Agate Cave Chest 1",
    (13,): "Agate Cave Chest 2",
    (15,): "Agate Relic Path Chest",

    # Mt. Battle
    (29,): "Outside Mt Battle",

    # Cipher Lab
    (16,): "Cipher Lab Left Door Chest 1",
    (20,): "Cipher Lab Left Door Chest 2",
    # Was "Cipher Lab Chest 1". The rest keep their numbering, so the list reads 2-5 with no 1.
    (17,): "Lovrina Defeat Item",
    (18,): "Cipher Lab Chest 2",
    (19,): "Cipher Lab Chest 3",
    (21,): "Cipher Lab Chest 4",
    (22,): "Cipher Lab Chest 5",
    (24,): "Cipher Lab Downstairs Chest 1",
    (25,): "Cipher Lab Downstairs Chest 2",
    (26,): "Cipher Lab Downstairs Chest 3",
    (27,): "Cipher Lab Downstairs Chest 4",

    # Pyrite Town
    (93,): "Pyrite Town Chest",
    (94,): "Pyrite Town Jail Chest",
    (95,): "Pyrite Hotel Chest 1",
    (96,): "Pyrite Hotel Chest 2",
    (97,): "Pyrite Hotel Chest 3",
    (98,): "ONBS 3F Chest 1",   # room 110 -- was "Pickup PDA"
    (99,): "ONBS 3F Chest 2",   # room 110 -- was the bare "ONBS 3F Chest"
    (100,): "ONBS 2F Chest",

    # Phenac City
    (87,): "Phenac City Chest 1",
    (88,): "Phenac City Chest 2",

    # Realgam Tower
    (39,): "Realgam Tower Outside Chest",
    (40,): "Realgam Tower Crossroads Chest",
    (41,): "Realgam Tower Main Hall Chest",

    # Chests 108 and 113 set the same flag bit and were once one merged location; (room, berry) tells them
    # apart, so they are named separately further down.

    # SS Libra
    (34,): "SS Libra Push Room 1 Chest",
    (32,): "SS Libra Push Room 2 Chest 1",
    (33,): "SS Libra Push Room 2 Chest 2",
    (35,): "SS Libra Push Room 3 Chest",
    (31,): "SS Libra Push Room 4 Chest 1",
    (36,): "SS Libra Push Room 4 Chest 2",
    # Labels swapped from live play; both are room 38, so ids stay put (1502 with chest 30, 1509 with 38).
    # `model` is 68 on 30 and 36 on 38, but 36 is what both existing "Shiny Chest" rows carry, so it witnesses
    # nothing.
    (30,): "Bonsly Room Shiny Chest",
    (38,): "Bonsly Room Chest 1",

    # Snagem Hideout
    (101,): "Snagem 1F Chest 1",
    (102,): "Snagem 1F Chest 2",
    # Labels swapped; both are room 166, so no region or gate moves and the ids stay put (1515 with 103,
    # 1517 with 105).
    (103,): "Gonzap Room Chest",
    (104,): "Snagem 2F Chest 2",
    (105,): "Snagem 2F Chest 1",
    (106,): "Snagem 3F Chest 1",
    (107,): "Snagem 3F Chest 2",

    # Cipher Key Lair
    (43,): "Cipher Key Lair 1F Chest 1",
    (44,): "Cipher Key Lair 1F Chest 2",
    (49,): "Cipher Key Lair 1F Chest 3",
    (56,): "Cipher Key Lair 1F Chest 4",
    (45,): "Cipher Key Lair 2F Chest 1",
    (46,): "Cipher Key Lair 2F Chest 2",
    (50,): "Cipher Key Lair 2F Chest 3",
    (47,): "Cipher Key Lair 3F Chest 1",
    (51,): "Cipher Key Lair 3F Chest 2",
    (42,): "Cipher Key Lair 4F Chest 1",
    (52,): "Cipher Key Lair 4F Chest 2",
    (53,): "Cipher Key Lair 4F Shiny Chest",
    (48,): "Cipher Key Lair Roof Chest",

    # Generated names the player approved. Chest 23 is room 9, generated until a real name arrived later.
    (23,): 'Cipher Lab Krane Chest',
    (4,): 'Gateon Port Chest',
    (78,): "Mayor's House Upstairs Chest",   # room 97 -- the Note is picked up upstairs (ladder 0x43 -> 0x44)
    (80,): 'Music Disc Chest',   # room 98 -- this chest IS the Disc (ladder 0x41 -> 0x42)
    # Room 107 is the Phenac Colosseum: it also holds chest 79, the Elevator Key, which the ladder places there.
    (89,): 'Phenac Colosseum Chest 1',
    (90,): 'Phenac Colosseum Chest 2',
    (91,): 'Phenac Colosseum Chest 3',
    # Separate locations since ADDENDUM 224 -- 108 is room 171, 113 is room 172.
    (108,): 'Kaminko Crane Room Chest 1',
    (113,): 'Kaminko Crane Room Chest 2',
    # Room 68 sits between the Key Lair's 4F (room 67) and its roof (room 70). Called 5F once; id 1462.
    (54,): 'Cipher Key Lair Basement Chest',
    # No floor labels for Citadark in this project, so these are numbered by room order and that is all the
    # numbering claims. A test pins it -- a silent shift renames every Citadark chest at once.
    (75,): 'Citadark Isle Chest 1',   # room 73
    (59,): 'Citadark Isle Chest 2',   # room 76
    (60,): 'Citadark Isle Chest 3',   # room 77
    (61,): 'Citadark Isle Chest 4',   # room 77
    (62,): 'Citadark Isle Chest 5',   # room 80
    (63,): 'Citadark Isle Chest 6',   # room 80
    (64,): 'Citadark Isle Chest 7',   # room 80
    (65,): 'Citadark Isle Chest 8',   # room 81
    (66,): 'Citadark Isle Chest 9',   # room 81
    (57,): 'Citadark Isle Chest 10',   # room 82
    (67,): 'Citadark Isle Chest 11',   # room 83
    (68,): 'Citadark Isle Chest 12',   # room 83
    (69,): 'Citadark Isle Chest 13',   # room 83
    (70,): 'Citadark Isle Chest 14',   # room 84
    (71,): 'Citadark Isle Chest 15',   # room 84
    (72,): 'Citadark Isle Chest 16',   # room 85
    (73,): 'Citadark Isle Chest 17',   # room 85
    (74,): 'Citadark Isle Chest 18',   # room 85
    (58,): 'Citadark Isle Chest 19',   # room 88
}

# The room each named chest is claimed to be in, checked against the ISO table below so neither can drift.
CHEST_NAME_EXPECTED_ROOM: "dict[int, int]" = {
    1: 143, 2: 142, 3: 138, 5: 146, 6: 158, 7: 158, 8: 160,
    10: 132, 11: 132, 14: 132, 12: 126, 13: 126, 15: 125,
    29: 20,
    16: 1, 20: 1, 17: 8, 18: 8, 19: 8, 21: 8, 22: 8,
    24: 10, 25: 10, 26: 10, 27: 10,
    93: 119, 94: 120, 95: 117, 96: 117, 97: 117, 99: 110, 100: 109, 98: 110,
    87: 100, 88: 100,
    39: 58, 40: 49, 41: 59,
    34: 39, 32: 37, 33: 37, 35: 40, 31: 41, 36: 41, 30: 38, 38: 38,
    101: 165, 102: 165, 103: 166, 104: 166, 105: 166, 106: 167, 107: 167,
    43: 64, 44: 64, 49: 64, 56: 64, 45: 65, 46: 65, 50: 65, 47: 66, 51: 66,
    42: 67, 52: 67, 53: 67, 48: 70,
    # ADDENDUM 230
    4: 153, 54: 68, 57: 82, 58: 88, 59: 76, 60: 77, 61: 77, 62: 80,
    63: 80, 64: 80, 65: 81, 66: 81, 67: 83, 68: 83, 69: 83, 70: 84,
    71: 84, 72: 85, 73: 85, 74: 85, 75: 73, 78: 97, 80: 98, 89: 107,
    90: 107, 91: 107, 108: 171, 113: 172,
}


def chest_location_name_override(chest_ids: "tuple[int, ...]") -> "str | None":
    return CHEST_LOCATION_NAME_OVERRIDES.get(tuple(chest_ids))


# A name describing the wrong room is worse than no name, and names are frozen once a seed ships.
def _check_names_against_the_iso() -> None:
    from .chest_table import CHESTS

    real_room = {entry["chest"]: entry["room"] for entry in CHESTS}
    problems: "list[str]" = []
    for chest_ids in CHEST_LOCATION_NAME_OVERRIDES:
        for chest in chest_ids:
            if chest not in real_room:
                problems.append(f"chest {chest} is named but is not in the ISO treasure table at all")
                continue
            expected = CHEST_NAME_EXPECTED_ROOM.get(chest)
            if expected is not None and real_room[chest] != expected:
                problems.append(
                    f"chest {chest} is named for room {expected} but the ISO puts it in room "
                    f"{real_room[chest]}"
                )
    if problems:
        raise AssertionError("chest name/room mismatch:\n  " + "\n  ".join(problems))


_check_names_against_the_iso()
