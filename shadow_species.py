"""
Shadow Pokemon capture-location roster for the Pokemon XD: Gale of Darkness apworld (2026-09-03).

Real, web-sourced list of 83 Shadow Pokemon encounters (species, owning trainer, area) -- see
data/shadow_pokemon_list.json for the raw data and data/trainer_pools_SOURCES.md-adjacent research notes for
how it was gathered (Bulbapedia's List of Shadow Pokemon page, cross-checked against Serebii's XD Pokemon
table). `locations.py`'s "Shadow Capture - {trainer} ({species})" location names were generated directly from
this same data (see the git history / build_shadow_locations.py in the project's scratchpad for the exact
script) -- SHADOW_CAPTURE_LOCATION_TO_DEX below is the reverse mapping the client needs.

WHY THIS IS A SEPARATE, DEPENDENCY-FREE MODULE (mirrors species.py's own reasoning): the client
(ram_client.py / Client.py) needs to load this table WITHOUT pulling in the full Archipelago-dependent world
package (locations.py imports BaseClasses/Region). Like species.py, this file imports nothing beyond the
standard library.

**Key design decision**: every one of these 83 shadow species is numerically distinct (no species appears as
more than one trainer's Shadow Pokemon -- verified by construction, see build_shadow_locations.py's dedup
check) and, per this project's own live RAM findings (species.py's docstring, pokemon-xd-ram-map.md), most of
XD's 386-species Dex is NOT obtainable through ordinary wild encounters at all -- trade and Shadow Pokemon
capture are the primary legitimate sources for the great majority of this specific list. That makes "a
species new to the party/PC" (the same signal already used for "Catch - {species}" locations, see
PokemonXDClient.py's SpeciesTracker) a practical, no-ISO-patch-required proxy for "the player just
snagged/defeated this specific Shadow Pokemon" too -- snagging a Shadow Pokemon puts it in the party exactly
like catching any other Pokemon does. This is NOT a logically airtight signal (a species could in principle
also reach the player's party by some other route this project hasn't ruled out for every one of the 386
entries), but it needs zero new RAM research and is honestly the same category of best-effort heuristic this
project already ships for species-catch detection -- see Client.py's module docstring for how the two
detections are combined in the actual polling loop.
"""

import json
import os

_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "shadow_pokemon_list.json")


def _load_shadow_capture_location_to_dex() -> dict[str, int]:
    """Rebuilds the location-name -> National Dex # mapping directly from data/shadow_pokemon_list.json at
    import time, using the exact same naming convention locations.py used when generating the location list
    ("Shadow Capture - {trainer} ({species_name})") -- keeps the two in sync automatically rather than risking
    a hand-copied table drifting out of step with the real location names."""
    if not os.path.isfile(_DATA_PATH):
        return {}
    with open(_DATA_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    mapping: dict[str, int] = {}
    for entry in raw:
        name = f"Shadow Capture - {entry['trainer']} ({entry['species_name']})"
        mapping[name] = entry["species_id"]
    return mapping


SHADOW_CAPTURE_LOCATION_TO_DEX: dict[str, int] = _load_shadow_capture_location_to_dex()

# Reverse direction: National Dex # -> the one Shadow Capture location name for it, if any (see module
# docstring -- every dex # maps to at most one shadow-capture location, by construction).
DEX_TO_SHADOW_CAPTURE_LOCATION: dict[int, str] = {
    dex: name for name, dex in SHADOW_CAPTURE_LOCATION_TO_DEX.items()
}


def shadow_capture_location_for_dex(dex_number: int) -> str | None:
    return DEX_TO_SHADOW_CAPTURE_LOCATION.get(dex_number)
