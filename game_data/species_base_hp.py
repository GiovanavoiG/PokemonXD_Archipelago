"""Base HP per species, and the max-HP band that implies.

Max HP identifies an encounter and costs nothing to read: a stale battle-roster copy stays pinned at the
Pokemon's MaxHP for the whole battle and every Pokemon starts a fight at full HP, so the maximum current-HP
seen across copies of a slot IS its MaxHP. Base HP is only the input -- it is a species constant (Magmar and
Electabuzz both have 65) -- and max HP comes from it and level through the Gen III formula, so it moves with
level: Magmar reads 56-74 at level 20, 69-94 at 26, 125-172 at 50.

IVs and EVs are unknown, so this gives a band from IV 0 / EV 0 to IV 31 / EV 255: wide, but encounters differ
by level far more than that. Keyed by National Dex across all 386 species through `national_dex_for()`, the
master index the deck and the stats table share -- Shedinja 1, Wailord 170, Rayquaza 105, Deoxys 50, Treecko
40. A species with no base HP contributes no band, like a Shadow slot.
"""
from __future__ import annotations

from . import load_json_data_file

_BASE_HP: "dict[int, int] | None" = None

# Kept as a named constant because tests and comments refer to the boundary, but it no longer fences the
# table: 1-251 is simply the range where the master internal index and the National Dex number coincide.
UNAMBIGUOUS_DEX_MAX = 251

# Gen III stat extremes. A trainer's Pokemon has fixed IVs/EVs in the deck data, but this project has never
# extracted them, so both ends are carried.
MIN_IV, MAX_IV = 0, 31
MIN_EV, MAX_EV = 0, 255


def base_hp(dex_number: int) -> "int | None":
    """Base HP for a National Dex number (all 386), or None when the species is unknown or the data file is
    not present in this build -- the same 'not yet extracted' convention every other loader here follows."""
    global _BASE_HP
    if _BASE_HP is None:
        raw = load_json_data_file("species_base_hp.json")
        table = (raw or {}).get("base_hp") or {}
        _BASE_HP = {int(k): int(v) for k, v in table.items()}
    return _BASE_HP.get(dex_number)


def all_base_hp() -> "dict[int, int]":
    """{National Dex number: base HP}, the whole census. `xd_rel_format.verify_species_stats_table` uses it
    to prove an ISO's stats table is where the REL's pointer says before the experience-rate pass writes a
    byte into it -- many species agreeing at once is how that offset was located in the first place."""
    base_hp(1)                     # force the lazy load
    return dict(_BASE_HP or {})


def max_hp(base: int, level: int, iv: int, ev: int) -> int:
    """The Gen III HP formula: floor((2*base + IV + floor(EV/4)) * level / 100) + level + 10."""
    return ((2 * base + iv + ev // 4) * level) // 100 + level + 10


def max_hp_band(dex_number: int, level: int) -> "tuple[int, int] | None":
    """(lowest possible MaxHP, highest possible MaxHP) for this species at this level, or None when base HP
    is unknown. Inclusive at both ends."""
    base = base_hp(dex_number)
    if base is None or not 1 <= level <= 100:
        return None
    return (max_hp(base, level, MIN_IV, MIN_EV), max_hp(base, level, MAX_IV, MAX_EV))
