"""Which key-item chests become AP checks when KeyItemShuffle is on.

Chest randomization skips every chest whose vanilla item is at or above `xd_rel_format.KEY_ITEM_ID_FLOOR`, so
with the option on a key item sat in the AP pool AND still in its chest, leaving every gate satisfiable by
the vanilla copy. The floor catches 24 chests; only five hold an item that enters the pool:

    chest 17  room   8  Data ROM       chest 78  room  97  Mayor's Note
    chest 18  room   8  ID Card        chest 80  room  98  Music Disc
    chest 42  room  67  System Lever

The other nineteen stay vanilla: chest 79 (Elevator Key) and chest 77 (Miror Radar) are not pool items, so
dummying them would delete the only copy, and the Radar gates the Oasis and Cave Poke Spots; chests 9 and 114
are in excluded rooms; the remaining sixteen are Battle CDs (534-592).

`xd_rel_format.apply_chest_dummy_item` takes this set as an argument so the ISO patch and the location table
read one list -- otherwise a chest becomes a check without being dummied, or is dummied without becoming one
and its key item vanishes from the seed.
"""
from __future__ import annotations

# chest id -> the vanilla item name it holds, for the five that become checks under KeyItemShuffle.
SHUFFLED_KEY_ITEM_CHESTS: "dict[int, str]" = {
    17: "Data ROM",
    18: "ID Card",
    42: "System Lever",
    78: "Mayor's Note",
    80: "Music Disc",
}

# Key-item chests deliberately left vanilla, with the reason, so none of them is ever silently reconsidered.
KEPT_VANILLA: "dict[int, str]" = {
    77: "Miror Radar -- not in the pool, and the in-game gate for the Oasis/Cave Poke Spots",
    79: "Elevator Key -- the player's explicit exception, and never in the pool",
}


def chest_ids_to_convert(shuffle_key_items: bool) -> "frozenset[int]":
    """The chests chest randomization dummies out and that become AP locations. Empty when the option is off,
    which is what keeps the option's two halves in step."""
    return frozenset(SHUFFLED_KEY_ITEM_CHESTS) if shuffle_key_items else frozenset()
