"""The map screen's destination table. On the map (room 910) the client reads the highlighted destination from
the cursor object before the player presses A -- the pre-load hook the per-area story-byte memory needs.

Two id spaces are recorded but only `location_id` is a key: it is the highlighted-destination record's `+0x00`
(duplicated at `+0x04`) and is stable across sessions, while `cursor_index` (the cursor object's `tag+0x08`)
is a position in the list of currently UNLOCKED destinations and shifts as more unlock. Cipher Lab's location
id is 8, which is also its room id. An unknown id resolves to None and the caller declines to write.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MapDestination:
    name: str
    cursor_index: int
    location_id: int
    x: float
    y: float
    region: "str | None" = None   # the regions.py region this destination lands the player in
    note: str = ""


# Measured live 2026-09-12 across two laps and re-confirmed after a reboot (the object moved 0x810ED690 ->
# 0x810EF4D0, every value bit-identical), then completed by the player's `!map` sweep. The two disagree only
# in the cursor column -- Phenac City read cursor 1 then 3, Rock Poke Spot 9 then 13, locations 3 and 15 both
# times -- and the sweep lists cursor 10 for both SS Libra and Realgam Tower. The ids run 0..17 with one gap,
# 13, genuinely unassigned; Citadark is not a missing row, it is reached by Robo Kyogre from Gateon Port.
CONFIRMED: "tuple[MapDestination, ...]" = (
    # From 2026-09-12. These cursor indices have since moved; the location ids held.
    MapDestination("Phenac City", cursor_index=3, location_id=3, x=44.0, y=16.0, region="Phenac City",
                   note="location id corroborated twice; cursor index was 1 in the 2026-09-12 session"),
    MapDestination("Rock Poke Spot", cursor_index=13, location_id=15, x=70.0, y=-9.0, region="Poke Spots",
                   note="location id corroborated twice; cursor index was 9 in the 2026-09-12 session"),
    MapDestination("Cipher Lab", cursor_index=4, location_id=8, x=21.0, y=-19.0, region="Cipher Lab",
                   note="location id 8 CONFIRMED by the player 2026-09-23 ('cursor index 4, location id 8'), "
                        "which also closes the one row that had never appeared in their sweep. The cursor index "
                        "is updated to their reading purely for the record -- it is diagnostic, never a lookup "
                        "key (ADDENDUM 172), and this row moving 6 -> 4 while the location id held is one more "
                        "measurement of exactly why"),

    # From the player's `!map` sweep, 2026-09-13. Coordinates were not captured, so they carry 0.0.
    MapDestination("Outskirt Stand", cursor_index=0, location_id=0, x=0.0, y=0.0, region="Outskirt Stand",
                   note="corrected by the player 2026-09-13: cursor 0, location 0 -- the sweep's '0 3' was a slip"),
    MapDestination("Snagem Hideout", cursor_index=1, location_id=1, x=0.0, y=0.0, region="Snagem Hideout"),
    MapDestination("Kaminko's House", cursor_index=2, location_id=2, x=0.0, y=0.0, region="Kaminko's House"),
    MapDestination("Pyrite Town", cursor_index=4, location_id=4, x=0.0, y=0.0, region="Pyrite Town"),
    MapDestination("Agate Village", cursor_index=5, location_id=5, x=0.0, y=0.0, region="Agate Village"),
    MapDestination("Pokemon HQ Lab", cursor_index=6, location_id=6, x=0.0, y=0.0, region="Pokemon HQ Lab",
                   note="shares cursor index 6 with Cipher Lab's earlier reading -- the index is not stable"),
    MapDestination("Gateon Port", cursor_index=7, location_id=7, x=0.0, y=0.0, region="Gateon Port"),
    MapDestination("Mt. Battle", cursor_index=9, location_id=9, x=0.0, y=0.0, region="Mt. Battle"),
    MapDestination("SS Libra", cursor_index=10, location_id=10, x=0.0, y=0.0, region="SS Libra"),
    MapDestination("Realgam Tower", cursor_index=10, location_id=11, x=0.0, y=0.0, region="Realgam Tower",
                   note="cursor index 10 collides with SS Libra's in the same sweep"),
    MapDestination("Cipher Key Lair", cursor_index=11, location_id=12, x=0.0, y=0.0,
                   region="Cipher Key Lair"),
    MapDestination("Orre Colosseum", cursor_index=12, location_id=14, x=0.0, y=0.0, region="Orre Colosseum",
                   note="folded into Realgam Tower on the player's instruction"),
    MapDestination("Oasis Poke Spot", cursor_index=14, location_id=16, x=0.0, y=0.0, region="Poke Spots"),
    MapDestination("Cave Poke Spot", cursor_index=15, location_id=17, x=0.0, y=0.0, region="Poke Spots"),
)

# Empty: nothing left to measure. Kept so `coverage()` and the assertion below keep working, and so a
# destination found later has somewhere obvious to be parked. Citadark Isle must not be added -- it is not a
# map destination, which is why the Robo Kyogre parts gate Citadark rather than gating victory.
AWAITING_MEASUREMENT: "tuple[str, ...]" = ()

BY_LOCATION_ID: "dict[int, MapDestination]" = {d.location_id: d for d in CONFIRMED}
# Diagnostic only. The cursor index is unstable and collides within a single sweep, so this is last-wins and
# must never be a lookup key.
BY_CURSOR_INDEX: "dict[int, MapDestination]" = {d.cursor_index: d for d in CONFIRMED}


def destination_for_location_id(location_id: "int | None") -> "MapDestination | None":
    """The destination a live `location_id` means, or None when it has not been measured. None is a real
    answer: the caller declines to write rather than guess."""
    return None if location_id is None else BY_LOCATION_ID.get(location_id)


def region_for_location_id(location_id: "int | None") -> "str | None":
    destination = destination_for_location_id(location_id)
    return None if destination is None else destination.region


def coverage() -> "tuple[int, int]":
    """(measured, total) -- what `!map` has pinned down so far."""
    return len(CONFIRMED), len(CONFIRMED) + len(AWAITING_MEASUREMENT)


assert len(BY_LOCATION_ID) == len(CONFIRMED), "two destinations share a location id"
# No assertion on cursor-index uniqueness: SS Libra and Realgam Tower are both 10 in the same sweep, which is
# the index being unstable rather than a data error.
assert not (set(AWAITING_MEASUREMENT) & {d.name for d in CONFIRMED}), (
    "a destination is listed as both measured and awaiting measurement"
)
