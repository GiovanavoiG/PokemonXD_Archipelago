"""
Trainer/species census loader for Pokemon XD: Gale of Darkness.

WHAT'S MISSING AND WHY: `randomizer.team_shuffle` needs a real list of "which trainers exist, which Pokemon
species/levels/items they start with, which slots are shadow encounters" to have anything meaningful to
shuffle. That census has to come from the real game -- either extracted from a real ISO (once the
FST/FSYS-extraction gap documented in `game_data.iso_format` is closed) or transcribed by hand from a
verified source (a wiki, a disassembly, the standalone randomizer's own data files). Neither exists in this
session: no ISO was available to extract from, and hand-transcribing ~50+ trainers' full rosters from memory
risks silently wrong species/level data baked into a patch file the player would trust -- worse than not
having the feature yet.

This module is the seam where that data plugs in once it exists: `load_trainer_census()` looks for
`pokemon_xd/data/trainer_census.json` (not shipped -- see below) and, if present, parses it into the
`team_shuffle.Species` / `TrainerPool` dataclasses. If absent, it returns `None` and `generate_output` skips
trainer-team randomization for this seed, leaving item placement (which IS fully real and confirmed data)
unaffected.

Expected `trainer_census.json` shape, once one exists:
{
  "species": [{"species_id": 1, "is_legendary": false, "evolves_into": 2, "evolves_at_level": 16}, ...],
  "trainer_pools": [
    {"name": "Kaminko Manor", "trainers": [
      {"name": "Chobin", "team": [
        {"index": 0, "species_id": 161, "level": 12, "item_id": null, "is_shadow": false}
      ]}
    ]}
  ]
}
"""

from __future__ import annotations

import json
import os

from ..randomizer.team_shuffle import PokemonInstance, Species, Trainer, TrainerPool

_CENSUS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "trainer_census.json")


def load_trainer_census() -> tuple[dict[int, Species], list[TrainerPool]] | None:
    """Returns (species_pool, trainer_pools) if a real census file is present, else None. Never raises on a
    missing file -- that's the expected, current state, not an error."""
    path = os.path.normpath(_CENSUS_PATH)
    if not os.path.isfile(path):
        return None

    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    species_pool = {
        s["species_id"]: Species(
            species_id=s["species_id"],
            is_legendary=s.get("is_legendary", False),
            evolves_into=s.get("evolves_into"),
            evolves_at_level=s.get("evolves_at_level"),
        )
        for s in raw.get("species", [])
    }

    trainer_pools = [
        TrainerPool(
            name=pool["name"],
            trainers=[
                Trainer(
                    name=trainer["name"],
                    team=[
                        PokemonInstance(
                            index=mon["index"],
                            species_id=mon["species_id"],
                            level=mon["level"],
                            item_id=mon.get("item_id"),
                            is_shadow=mon.get("is_shadow", False),
                        )
                        for mon in trainer.get("team", [])
                    ],
                )
                for trainer in pool.get("trainers", [])
            ],
        )
        for pool in raw.get("trainer_pools", [])
    ]

    return species_pool, trainer_pools


def serialize_trainer_pools(trainer_pools: list[TrainerPool]) -> list[dict]:
    """Turns shuffled TrainerPool objects back into plain JSON-able dicts for patch.py's seed.json."""
    return [
        {
            "name": pool.name,
            "trainers": [
                {
                    "name": trainer.name,
                    "team": [
                        {
                            "index": mon.index,
                            "species_id": mon.species_id,
                            "level": mon.level,
                            "item_id": mon.item_id,
                            "is_shadow": mon.is_shadow,
                        }
                        for mon in trainer.team
                    ],
                }
                for trainer in pool.trainers
            ],
        }
        for pool in trainer_pools
    ]
