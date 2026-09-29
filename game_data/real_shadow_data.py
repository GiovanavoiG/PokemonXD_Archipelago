"""Real, ISO-extracted Shadow Pokemon roster.

A Shadow's species is not on its DDPK record: it resolves through that record's `story_deck_index`, a pointer
into the same DPKM pool the ordinary teams use, which is why `real_trainer_data.py` leaves DDPK slots out of
its census. Those entries are disjoint from ordinary teams -- of the 823 real DPKM entries in
`DeckData_Story.bin`, 726 belong to the 232 ordinary trainers and the other 97 are referenced by no DTNR
trainer, zero overlap measured -- so patching a Shadow's DPKM entry cannot alter an unrelated team.

`data/deckdata_dark_pokemon.json` is a one-time extraction: decode `DeckData_DarkPokemon.bin`, keep the 83 of
127 non-empty DDPK entries whose `story_deck_index` is nonzero (the other 44 carry the in-use flag but point
at nothing), resolve each through `DeckFile.dpkm_full`, record
`{ddpk_index, dpkm_index, species, shadow_level}`. It joins to `shadow_pokemon_list.json` by species, not
position: position-for-position gives 82 mismatches out of 83.
"""

from __future__ import annotations

from . import load_json_data_file
from ..randomizer.team_shuffle import PokemonInstance, Trainer, TrainerPool
from ..shadow_species import shadow_capture_location_for_dex
from ..tools.xd_species_index import INTERNAL_INDEX_TO_NATIONAL_DEX


def load_real_shadow_pool() -> TrainerPool | None:
    """A `TrainerPool` of 83 single-Pokemon "trainers", one per Shadow encounter, or None when
    `data/deckdata_dark_pokemon.json` is not in this build.

    `Trainer.name` is the encounter's fixed AP location name, resolved from the entry's VANILLA species --
    randomization changes which species is found there, never the location name. `is_shadow=True` so the
    shuffler applies its species dedup guard: `shadow_species.py`'s detection needs species -> location to
    stay one-to-one."""
    raw = load_json_data_file("deckdata_dark_pokemon.json")
    if raw is None:
        return None

    trainers: list[Trainer] = []
    for entry in raw:
        national_dex, _name = INTERNAL_INDEX_TO_NATIONAL_DEX.get(entry["species"], (None, None))
        location_name = shadow_capture_location_for_dex(national_dex) if national_dex is not None else None
        trainers.append(Trainer(
            name=location_name or f"Shadow DDPK #{entry['ddpk_index']} (unmatched)",
            team=[PokemonInstance(
                index=entry["dpkm_index"],
                species_id=entry["species"],
                level=entry["shadow_level"],
                item_id=None,
                is_shadow=True,
            )],
        ))
    return TrainerPool(name="DeckData_DarkPokemon.bin (real, ISO-extracted)", trainers=trainers)


def vanilla_shadow_species() -> set[int] | None:
    """Internal species indices of the 83 vanilla Shadows, or None when the data file is absent.
    `shadow_expansion` excludes them from the new-Shadow pool: a species already tracked at a fixed location
    turning up as a new Shadow would make that location's detection ambiguous."""
    raw = load_json_data_file("deckdata_dark_pokemon.json")
    if raw is None:
        return None
    return {entry["species"] for entry in raw}
