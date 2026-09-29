"""GENERATED -- do not hand-edit the table; edit `DESCRIPTORS` only.

Every real chest in `common_rel`'s treasure table (`XDTreasureBoxData`), keyed by room id in the same
numbering the live `!room` readout reports, so "which chests are in the room I am standing in" is a direct
lookup.

Extracted from the real ISO via `xd_rel_format.read_chest_entry`. Fields per chest:
    chest  -- the treasure-table index. This is the stable identity; use it as the key for anything durable.
    room   -- room id (see ram_client.KNOWN_ROOM_IDS for the names learned so far).
    item   -- the VANILLA item id this chest holds. Chest randomization overwrites this with a dummy berry
              for chests below KEY_ITEM_ID_FLOOR, so it describes the unpatched game, not the seed.
    qty    -- vanilla quantity (forced to 1 by the randomizer -- see apply_chest_dummy_item).
    model  -- 68 and 36 are the two values that occur; believed to be the large chest vs the small item ball,
              NOT yet confirmed in game. Useful as a descriptor either way.
    x/y/z  -- world coordinates, which is what actually separates two chests in the same room.

`DESCRIPTORS` is the hand-written half: a short human label per chest index, filled in by playing with
`!chests` open. Nothing depends on it being complete."""
from __future__ import annotations

CHESTS: list[dict] = [
    {"chest": 16, "room": 1, "item": 22, "qty": 1, "model": 36, "x": 56.0, "y": 0.0, "z": -54.0},
    {"chest": 20, "room": 1, "item": 4, "qty": 3, "model": 36, "x": -95.0, "y": 0.0, "z": -48.0},
    {"chest": 17, "room": 8, "item": 505, "qty": 1, "model": 68, "x": 28.0, "y": 0.0, "z": -204.0},
    {"chest": 18, "room": 8, "item": 506, "qty": 1, "model": 68, "x": 38.0, "y": 8.0, "z": -45.0},
    {"chest": 19, "room": 8, "item": 34, "qty": 1, "model": 36, "x": 104.0, "y": 0.0, "z": 105.0},
    {"chest": 21, "room": 8, "item": 23, "qty": 1, "model": 36, "x": -76.0, "y": 0.0, "z": 42.0},
    {"chest": 22, "room": 8, "item": 3, "qty": 1, "model": 36, "x": 95.0, "y": 0.0, "z": -43.0},
    {"chest": 23, "room": 9, "item": 98, "qty": 1, "model": 36, "x": -45.0, "y": 0.0, "z": -40.0},
    {"chest": 28, "room": 9, "item": 575, "qty": 1, "model": 68, "x": -74.0, "y": 7.0, "z": -39.0},
    {"chest": 24, "room": 10, "item": 22, "qty": 3, "model": 36, "x": 134.0, "y": 0.0, "z": -20.0},
    {"chest": 25, "room": 10, "item": 3, "qty": 1, "model": 36, "x": -94.0, "y": 0.0, "z": 158.0},
    {"chest": 26, "room": 10, "item": 24, "qty": 1, "model": 36, "x": 32.0, "y": 0.0, "z": -150.0},
    {"chest": 27, "room": 10, "item": 34, "qty": 1, "model": 36, "x": 130.0, "y": 0.0, "z": 115.0},
    {"chest": 29, "room": 20, "item": 23, "qty": 1, "model": 36, "x": 17.0, "y": 0.0, "z": -143.0},
    {"chest": 32, "room": 37, "item": 95, "qty": 1, "model": 36, "x": 45.0, "y": 10.0, "z": -32.0},
    {"chest": 33, "room": 37, "item": 69, "qty": 2, "model": 36, "x": 45.0, "y": 10.0, "z": 32.0},
    {"chest": 30, "room": 38, "item": 200, "qty": 1, "model": 68, "x": 0.0, "y": 0.0, "z": 5.0},
    {"chest": 38, "room": 38, "item": 11, "qty": 1, "model": 36, "x": 48.0, "y": 0.0, "z": 67.0},
    {"chest": 34, "room": 39, "item": 65, "qty": 1, "model": 36, "x": -50.0, "y": 10.0, "z": -32.0},
    {"chest": 35, "room": 40, "item": 35, "qty": 1, "model": 36, "x": 45.0, "y": 10.0, "z": 10.0},
    {"chest": 31, "room": 41, "item": 40, "qty": 1, "model": 36, "x": 32.0, "y": 10.0, "z": -45.0},
    {"chest": 36, "room": 41, "item": 323, "qty": 1, "model": 36, "x": -30.0, "y": 10.0, "z": -16.0},
    {"chest": 37, "room": 43, "item": 551, "qty": 1, "model": 68, "x": 35.0, "y": 0.0, "z": 8.0},
    {"chest": 40, "room": 49, "item": 66, "qty": 1, "model": 36, "x": 20.0, "y": 0.0, "z": 20.0},
    {"chest": 39, "room": 58, "item": 64, "qty": 1, "model": 36, "x": 84.0, "y": -15.0, "z": 126.0},
    {"chest": 41, "room": 59, "item": 2, "qty": 1, "model": 36, "x": -64.0, "y": 0.0, "z": 93.0},
    {"chest": 43, "room": 64, "item": 68, "qty": 1, "model": 36, "x": 96.0, "y": 0.0, "z": 48.0},
    {"chest": 44, "room": 64, "item": 2, "qty": 3, "model": 36, "x": 68.0, "y": 0.0, "z": 68.0},
    {"chest": 49, "room": 64, "item": 21, "qty": 3, "model": 36, "x": -50.0, "y": 0.0, "z": -105.0},
    {"chest": 56, "room": 64, "item": 24, "qty": 2, "model": 36, "x": -134.0, "y": 0.0, "z": -175.0},
    {"chest": 45, "room": 65, "item": 36, "qty": 1, "model": 36, "x": -11.0, "y": 0.0, "z": -169.0},
    {"chest": 46, "room": 65, "item": 19, "qty": 1, "model": 36, "x": 63.0, "y": 0.0, "z": -26.0},
    {"chest": 50, "room": 65, "item": 69, "qty": 1, "model": 36, "x": 101.0, "y": 0.0, "z": -75.0},
    {"chest": 47, "room": 66, "item": 23, "qty": 3, "model": 36, "x": 73.0, "y": 0.0, "z": -36.0},
    {"chest": 51, "room": 66, "item": 25, "qty": 1, "model": 36, "x": -76.0, "y": 0.0, "z": -51.0},
    {"chest": 42, "room": 67, "item": 508, "qty": 1, "model": 68, "x": 32.0, "y": 9.0, "z": -50.0},
    {"chest": 52, "room": 67, "item": 63, "qty": 1, "model": 36, "x": -90.0, "y": 0.0, "z": -88.0},
    {"chest": 53, "room": 67, "item": 21, "qty": 2, "model": 36, "x": 60.0, "y": 0.0, "z": -68.0},
    {"chest": 54, "room": 68, "item": 312, "qty": 1, "model": 36, "x": 69.0, "y": 0.0, "z": 108.0},
    {"chest": 55, "room": 68, "item": 580, "qty": 1, "model": 68, "x": 148.0, "y": 6.0, "z": 44.0},
    {"chest": 48, "room": 70, "item": 314, "qty": 1, "model": 36, "x": -55.0, "y": 30.0, "z": 39.0},
    {"chest": 75, "room": 73, "item": 25, "qty": 1, "model": 36, "x": 154.0, "y": 0.0, "z": -114.0},
    {"chest": 76, "room": 73, "item": 579, "qty": 1, "model": 68, "x": 0.0, "y": 3.0, "z": 0.0},
    {"chest": 59, "room": 76, "item": 37, "qty": 1, "model": 36, "x": 48.0, "y": 0.0, "z": -184.0},
    {"chest": 60, "room": 77, "item": 24, "qty": 2, "model": 36, "x": -15.0, "y": 0.0, "z": -110.0},
    {"chest": 61, "room": 77, "item": 180, "qty": 2, "model": 36, "x": 115.0, "y": 0.0, "z": -143.0},
    {"chest": 62, "room": 80, "item": 36, "qty": 1, "model": 36, "x": 64.0, "y": 0.0, "z": 72.0},
    {"chest": 63, "room": 80, "item": 19, "qty": 2, "model": 36, "x": -10.0, "y": 0.0, "z": -75.0},
    {"chest": 64, "room": 80, "item": 21, "qty": 2, "model": 36, "x": -17.0, "y": 0.0, "z": -21.0},
    {"chest": 65, "room": 81, "item": 20, "qty": 2, "model": 36, "x": 38.0, "y": 0.0, "z": -56.0},
    {"chest": 66, "room": 81, "item": 69, "qty": 1, "model": 36, "x": 72.0, "y": 0.0, "z": 16.0},
    {"chest": 57, "room": 82, "item": 68, "qty": 3, "model": 36, "x": -42.0, "y": 0.0, "z": 25.0},
    {"chest": 67, "room": 83, "item": 25, "qty": 1, "model": 36, "x": 26.0, "y": 0.0, "z": -82.0},
    {"chest": 68, "room": 83, "item": 10, "qty": 3, "model": 36, "x": -86.0, "y": 0.0, "z": -64.0},
    {"chest": 69, "room": 83, "item": 24, "qty": 2, "model": 36, "x": 86.0, "y": 0.0, "z": 86.0},
    {"chest": 70, "room": 84, "item": 35, "qty": 3, "model": 36, "x": -76.0, "y": 0.0, "z": -6.0},
    {"chest": 71, "room": 84, "item": 23, "qty": 4, "model": 36, "x": 32.0, "y": 0.0, "z": 86.0},
    {"chest": 72, "room": 85, "item": 21, "qty": 3, "model": 36, "x": -124.0, "y": 0.0, "z": -145.0},
    {"chest": 73, "room": 85, "item": 19, "qty": 2, "model": 36, "x": 106.0, "y": 0.0, "z": -146.0},
    {"chest": 74, "room": 85, "item": 2, "qty": 5, "model": 36, "x": -100.0, "y": 0.0, "z": 19.0},
    {"chest": 58, "room": 88, "item": 71, "qty": 1, "model": 36, "x": -96.0, "y": 140.0, "z": -40.0},
    {"chest": 77, "room": 92, "item": 510, "qty": 1, "model": 68, "x": -3.0, "y": 0.0, "z": 57.0},
    {"chest": 85, "room": 96, "item": 560, "qty": 1, "model": 68, "x": -5.0, "y": 0.0, "z": 8.0},
    {"chest": 86, "room": 96, "item": 565, "qty": 1, "model": 68, "x": 0.0, "y": 0.0, "z": 0.0},
    {"chest": 78, "room": 97, "item": 509, "qty": 1, "model": 68, "x": -17.5, "y": 0.0, "z": 10.0},
    {"chest": 80, "room": 98, "item": 507, "qty": 1, "model": 68, "x": -2.0, "y": 8.0, "z": 12.0},
    {"chest": 81, "room": 100, "item": 552, "qty": 1, "model": 68, "x": 135.0, "y": 33.0, "z": -48.0},
    {"chest": 82, "room": 100, "item": 549, "qty": 1, "model": 68, "x": -51.0, "y": 0.0, "z": 295.0},
    {"chest": 83, "room": 100, "item": 561, "qty": 1, "model": 68, "x": -120.0, "y": 33.0, "z": -41.0},
    {"chest": 84, "room": 100, "item": 541, "qty": 1, "model": 68, "x": 9.0, "y": 33.0, "z": 26.0},
    {"chest": 87, "room": 100, "item": 21, "qty": 2, "model": 36, "x": -142.0, "y": 33.0, "z": 78.0},
    {"chest": 88, "room": 100, "item": 2, "qty": 3, "model": 36, "x": 142.0, "y": 0.0, "z": 100.0},
    {"chest": 79, "room": 107, "item": 501, "qty": 1, "model": 68, "x": 10.0, "y": 0.0, "z": 10.0},
    {"chest": 89, "room": 107, "item": 301, "qty": 1, "model": 36, "x": 137.0, "y": 0.0, "z": 175.0},
    {"chest": 90, "room": 107, "item": 97, "qty": 1, "model": 36, "x": -119.0, "y": 0.0, "z": 196.0},
    {"chest": 91, "room": 107, "item": 69, "qty": 1, "model": 36, "x": 196.0, "y": 0.0, "z": -92.0},
    {"chest": 92, "room": 107, "item": 577, "qty": 1, "model": 68, "x": 0.0, "y": 0.0, "z": -196.0},
    {"chest": 100, "room": 109, "item": 34, "qty": 1, "model": 36, "x": 120.0, "y": 0.0, "z": 76.0},
    {"chest": 98, "room": 110, "item": 24, "qty": 1, "model": 36, "x": -70.0, "y": 0.0, "z": 30.0},
    {"chest": 99, "room": 110, "item": 63, "qty": 1, "model": 36, "x": 72.0, "y": 0.0, "z": 32.0},
    {"chest": 95, "room": 117, "item": 3, "qty": 3, "model": 36, "x": 62.0, "y": 0.0, "z": -37.0},
    {"chest": 96, "room": 117, "item": 18, "qty": 1, "model": 36, "x": -45.0, "y": 0.0, "z": -60.0},
    {"chest": 97, "room": 117, "item": 196, "qty": 1, "model": 36, "x": 52.0, "y": 0.0, "z": -91.0},
    {"chest": 93, "room": 119, "item": 3, "qty": 1, "model": 36, "x": 190.0, "y": 0.0, "z": -588.0},
    {"chest": 94, "room": 120, "item": 21, "qty": 1, "model": 36, "x": 100.0, "y": 0.0, "z": 55.0},
    {"chest": 15, "room": 125, "item": 15, "qty": 2, "model": 36, "x": -5.0, "y": 0.0, "z": -27.0},
    {"chest": 12, "room": 126, "item": 4, "qty": 1, "model": 36, "x": 58.0, "y": 0.0, "z": -12.0},
    {"chest": 13, "room": 126, "item": 22, "qty": 1, "model": 36, "x": 24.0, "y": 0.0, "z": 40.0},
    {"chest": 10, "room": 132, "item": 4, "qty": 1, "model": 36, "x": -146.0, "y": 0.0, "z": 126.0},
    {"chest": 11, "room": 132, "item": 34, "qty": 1, "model": 36, "x": 260.0, "y": 120.0, "z": -6.0},
    {"chest": 14, "room": 132, "item": 13, "qty": 3, "model": 36, "x": 108.0, "y": 80.0, "z": -102.0},
    {"chest": 3, "room": 138, "item": 13, "qty": 3, "model": 36, "x": -80.0, "y": 0.0, "z": -75.0},
    {"chest": 2, "room": 142, "item": 1, "qty": 1, "model": 36, "x": -55.0, "y": 0.0, "z": -38.0},
    {"chest": 1, "room": 143, "item": 14, "qty": 2, "model": 36, "x": 57.0, "y": 10.0, "z": -342.0},
    {"chest": 9, "room": 145, "item": 539, "qty": 1, "model": 68, "x": -58.0, "y": 7.0, "z": 20.0},
    {"chest": 5, "room": 146, "item": 22, "qty": 1, "model": 36, "x": 6.0, "y": 0.0, "z": 20.0},
    {"chest": 4, "room": 153, "item": 4, "qty": 3, "model": 36, "x": -427.0, "y": 0.0, "z": -190.0},
    {"chest": 6, "room": 158, "item": 13, "qty": 1, "model": 36, "x": -8.0, "y": 0.0, "z": -31.0},
    {"chest": 7, "room": 158, "item": 18, "qty": 1, "model": 36, "x": 9.0, "y": 0.0, "z": -31.0},
    {"chest": 8, "room": 160, "item": 17, "qty": 1, "model": 36, "x": -50.0, "y": 0.0, "z": 11.0},
    {"chest": 101, "room": 165, "item": 2, "qty": 3, "model": 36, "x": 44.900001525878906, "y": 0.0, "z": -134.0},
    {"chest": 102, "room": 165, "item": 317, "qty": 1, "model": 36, "x": 98.0, "y": 0.0, "z": 36.0},
    {"chest": 103, "room": 166, "item": 23, "qty": 2, "model": 36, "x": 116.0, "y": 0.0, "z": 78.0},
    {"chest": 104, "room": 166, "item": 21, "qty": 2, "model": 36, "x": -5.0, "y": 0.0, "z": -97.0},
    {"chest": 105, "room": 166, "item": 69, "qty": 1, "model": 36, "x": -88.0, "y": 0.0, "z": 31.0},
    {"chest": 106, "room": 167, "item": 24, "qty": 2, "model": 36, "x": 0.0, "y": 0.0, "z": 31.0},
    {"chest": 107, "room": 167, "item": 68, "qty": 1, "model": 36, "x": 24.0, "y": 0.0, "z": -104.0},
    {"chest": 108, "room": 171, "item": 68, "qty": 1, "model": 36, "x": -64.0, "y": 0.0, "z": -24.0},
    {"chest": 109, "room": 171, "item": 556, "qty": 1, "model": 68, "x": 0.0, "y": 0.0, "z": 96.0},
    {"chest": 110, "room": 172, "item": 538, "qty": 1, "model": 68, "x": -134.0, "y": 60.0, "z": 95.0},
    {"chest": 111, "room": 172, "item": 544, "qty": 1, "model": 68, "x": -155.0, "y": 60.0, "z": -52.0},
    {"chest": 112, "room": 172, "item": 562, "qty": 1, "model": 68, "x": -35.0, "y": 60.0, "z": -50.0},
    {"chest": 113, "room": 172, "item": 68, "qty": 1, "model": 36, "x": -174.0, "y": 0.0, "z": -46.0},
    {"chest": 114, "room": 175, "item": 508, "qty": 10, "model": 36, "x": -45.0, "y": 0.0, "z": -45.0},
    {"chest": 115, "room": 175, "item": 0, "qty": 10, "model": 68, "x": 45.0, "y": 10.0, "z": 30.0},
]

CHESTS_BY_ROOM: "dict[int, list[dict]]" = {}
for _c in CHESTS:
    CHESTS_BY_ROOM.setdefault(_c["room"], []).append(_c)

# Hand-written labels, chest index -> description. Add entries as rooms get explored with `!chests`.
DESCRIPTORS: "dict[int, str]" = {
    18: "Cipher Lab -- holds the ID Card (item 506) in the unpatched game",
}


def chests_in_room(room_id: "int | None") -> list[dict]:
    """Every real chest in `room_id`, ordered by chest index. Empty for an unknown or chest-less room."""
    if room_id is None:
        return []
    return list(CHESTS_BY_ROOM.get(room_id, ()))


def describe_chest(chest: dict) -> str:
    label = DESCRIPTORS.get(chest["chest"])
    shape = "chest" if chest["model"] == 68 else ("ball" if chest["model"] == 36 else f"model {chest['model']}")
    line = (f"#{chest['chest']:<4} {shape:<5} at x={chest['x']:g} y={chest['y']:g} z={chest['z']:g}"
            f"  vanilla item {chest['item']}" + (f" x{chest['qty']}" if chest["qty"] != 1 else ""))
    return line + (f"  -- {label}" if label else "")
