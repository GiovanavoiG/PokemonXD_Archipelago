"""The Overworld Items census, and what it retired.

The "Overworld Items" group was 81 locations hand-compiled from a walkthrough -- a name and nothing else, no
room id, item id or chest index. Sixteen are real and detected (11 `Unlock - X`, 5 Krane Memos); the other 65
had no client detector at all and were still progression-eligible.

The arithmetic settles it. The ISO's treasure-box table holds 115 entries, 95 of them AP chest locations; 160
would be needed if the 65 were distinct pickups too, and 19 of the 20 non-AP entries are model 68 (large
chests). They describe the same objects: model 36 is a small item ball and 89 of the 95 chest locations are
model 36, region counts line up (S.S. Libra 8 vs 8, Citadark Isle 20 vs 19, Cipher Key Lair 13 vs 14,
Kaminko's Robo Groudon 2 vs 2), and fourteen match down to the item. Retirement follows the frozen-id rule:
the name leaves the current table, its id is never reassigned, and the `_FROZEN_LOCATION_OFFSETS` entry stays
behind inert.
"""
from __future__ import annotations

# Container-shaped names, or names matching a real chest's contents by item: duplicates of locations the
# per-chest system already detects. Removed from the current location table; ids never reassigned.
RETIRED_DUPLICATE_LOCATIONS: "frozenset[str]" = frozenset({
    "Agate Village - Eagun's Cave Potion",
    "Agate Village - Entry Chest",
    "Cipher Key Lair - 1F Center Room",
    "Cipher Key Lair - 1F Upper Left",
    "Cipher Key Lair - 2F Bottom Left",
    "Cipher Key Lair - 2F Center Room",
    "Cipher Key Lair - 2F Upper Left",
    "Cipher Key Lair - 3F Hallway",
    "Cipher Key Lair - 3F Moon Door",
    "Cipher Key Lair - 4F Hallway",
    "Cipher Key Lair - 4F Kleto's Room",
    "Cipher Key Lair - 5F Roof",
    "Cipher Key Lair - B1F South Room",
    "Cipher Key Lair - Jelstin's Chamber",
    "Cipher Lab - Meda's Ether",
    "Cipher Lab - Nexir Battle Revive",
    "Citadark Isle - 1F Right Door Room",
    "Citadark Isle - 2F Far Right Block",
    "Citadark Isle - 2F First Block",
    "Citadark Isle - 3F After Hunter",
    "Citadark Isle - 3F Near Nalix",
    "Citadark Isle - 3F Past Kulig and Jargo",
    "Citadark Isle - 3F-2 Entrance",
    "Citadark Isle - 4F Below Spiral Path",
    "Citadark Isle - 4F Hidden Room",
    "Citadark Isle - 4F Spiral Path",
    "Citadark Isle - 5F Timer Balls",
    "Citadark Isle - 6F Full Heals",
    "Citadark Isle - 6F Max Ethers",
    "Citadark Isle - 6F Max Revive",
    "Citadark Isle - 6F Revives",
    "Citadark Isle - Bridge Ultra Balls",
    "Citadark Isle - Dome 1F Corner",
    "Gateon Port - Krabby Club Basement Item",
    "Kaminko's House - R&D Lab Basement",
    "Outskirt Stand - HQ Lab Potions",
    "Phenac City - Behind the House",
    "Phenac City - Pre-Gym Building (Music Disc)",
    "Phenac City - Shop Ledge",
    "Pyrite Town - Colosseum Bridge Box",
    "Pyrite Town - Grand Hotel Center Room",
    "Pyrite Town - Grand Hotel Leftmost Room",
    "Pyrite Town - Grand Hotel Rightmost Room",
    "Pyrite Town - ONBS Third Floor Box",
    "S.S. Libra - Bottom Right Box",
    "S.S. Libra - Box Puzzle Bottom",
    "S.S. Libra - Box Puzzle Top",
    "S.S. Libra - Entry Box (Iron)",
    "S.S. Libra - Final Puzzle Box (TM Flamethrower)",
    "S.S. Libra - Final Puzzle Box (Yellow Flute)",
    "S.S. Libra - Third Puzzle Box (Max Ether)",
})

# The fourteen names the census could not vouch for. They were kept as merely excluded while unknown, because
# retiring a real location only loses a check while keeping a phantom lets Fill place progression somewhere
# unreachable. A playthrough then found none of them, so they are retired -- under their own name rather than
# merged into the duplicates above, because "does not exist" is a different finding from "already a chest".
RETIRED_UNREAL_LOCATIONS: "frozenset[str]" = frozenset({
    # Nearly retired as a duplicate on the word "Catwalk", then held back because it is a gift (Jovi's diary
    # pages) rather than a box; the playthrough settled it the other way.
    "Kaminko's House - Catwalk Diary Pages",
    "Agate Village - Eagun's Cave Ball",
    "Agate Village - Eagun's Item",
    "Cipher Key Lair - Admin Item",
    "Citadark Isle - After Furgy",
    "Citadark Isle - B1F After Grason",
    "Citadark Isle - Pre-Boss Item",
    "Phenac City - Cologne's Item",
    "Phenac City - Stadium Item",
    "Pyrite Town - Duel Square Item",
    "Pyrite Town - Jailhouse Item",
    "Realgam Tower - Colosseum Clear Reward",
    "Relic Forest - Hidden Item",
    "S.S. Libra - Bonsly's Item",
})

# Every Overworld Item name this census removes from the current table, whatever the reason. One set for the
# filter in locations.py, so a third finding is one entry here rather than a second call site.
RETIRED_LOCATIONS: "frozenset[str]" = RETIRED_DUPLICATE_LOCATIONS | RETIRED_UNREAL_LOCATIONS

# `UNCERTAIN_EXCLUDED_LOCATIONS` is gone rather than left empty: an empty set still wired into `locations.py`'s
# excluded pass would read as a guarantee that something is protected when nothing is. If a future census
# cannot vouch for a name, the set comes back with that name in it.

assert not (RETIRED_DUPLICATE_LOCATIONS & RETIRED_UNREAL_LOCATIONS), (
    "a location is retired twice, for two different reasons -- it must be one or the other"
)
assert len(RETIRED_LOCATIONS) == len(RETIRED_DUPLICATE_LOCATIONS) + len(RETIRED_UNREAL_LOCATIONS), (
    "the combined retirement set lost or gained a name"
)
