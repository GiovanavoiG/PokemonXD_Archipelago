"""
Shadow Pokemon capture-location roster: 83 encounters (species, owning trainer, area) from
data/shadow_pokemon_list.json, gathered from Bulbapedia's List of Shadow Pokemon and cross-checked against
Serebii's XD Pokemon table. locations.py's "Shadow Defeat - {trainer} ({species})" names come from the same
data; SHADOW_CAPTURE_LOCATION_TO_DEX is the reverse mapping the client needs.

Stdlib-only, like species.py, because the client (ram_client.py / Client.py) must load this table without
pulling in the Archipelago-dependent world package (locations.py imports BaseClasses/Region).

All 83 shadow species are numerically distinct, and most of XD's 386-species Dex is not obtainable from
ordinary wild encounters at all, so "a species new to the party/PC" -- the signal SpeciesTracker already uses
for "Catch - {species}" -- works as a proxy for snagging that Shadow Pokemon, since snagging puts it in the
party like any other catch. Best-effort, not airtight: a species could in principle arrive by some other
route, but this needs no new RAM research.
"""

from .game_data import load_json_data_file


def _load_shadow_capture_location_to_dex() -> dict[str, int]:
    """Rebuild location-name -> National Dex # from data/shadow_pokemon_list.json at import time, using the
    same "Shadow Defeat - {trainer} ({species_name})" convention locations.py generated the names with, so the
    two cannot drift apart.

    Goes through load_json_data_file rather than open() relative to __file__: in an installed .apworld the
    module's __file__ points inside the zip, so the plain lookup silently returned {} and every "Shadow
    Defeat" detection quietly stopped working. load_json_data_file is stdlib-only, keeping this module free of
    Archipelago-core dependencies.
    """
    raw = load_json_data_file("shadow_pokemon_list.json")
    if raw is None:
        return {}
    mapping: dict[str, int] = {}
    for entry in raw:
        name = f"Shadow Defeat - {entry['trainer']} ({entry['species_name']})"
        mapping[name] = entry["species_id"]
    return mapping


SHADOW_CAPTURE_LOCATION_TO_DEX: dict[str, int] = _load_shadow_capture_location_to_dex()

# Reverse direction: National Dex # -> the one Shadow Defeat location name for it, if any (see module
# docstring -- every dex # maps to at most one shadow-capture location, by construction).
DEX_TO_SHADOW_CAPTURE_LOCATION: dict[int, str] = {
    dex: name for name, dex in SHADOW_CAPTURE_LOCATION_TO_DEX.items()
}


def shadow_capture_location_for_dex(dex_number: int) -> str | None:
    return DEX_TO_SHADOW_CAPTURE_LOCATION.get(dex_number)
