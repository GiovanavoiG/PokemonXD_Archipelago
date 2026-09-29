"""Loader for the real, ISO-extracted per-species level-up movesets.

`data/species_level_up_moves.json` is `{internal_species_index: [[level, move_id], ...]}` for all 415 real
species, extracted by `xd_rel_format.read_level_up_moves()` from `common_rel`'s XDPokemonStats table
(pointer-table index 88).

Keyed by this game's INTERNAL species index -- what DPKM/DTNR records and `PokemonInstance.species_id` use,
not National Dex, which differs from index 252 onward.
"""

from __future__ import annotations

from . import load_json_data_file


def load_level_up_moves() -> dict[int, list[tuple[int, int]]] | None:
    """{internal_species_index: [(level, move_id), ...]}, or None when the data file is not in this build --
    callers skip the feature and note it in the seed rather than guess. A species with no level-up moves at
    all (a real vanilla gap: Bonsly, Munchlax) maps to `[]`, never a missing key."""
    raw = load_json_data_file("species_level_up_moves.json")
    if raw is None:
        return None
    return {int(species_index): [(int(level), int(move)) for level, move in pairs] for species_index, pairs in raw.items()}
