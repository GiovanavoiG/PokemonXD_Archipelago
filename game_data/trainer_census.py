"""Trainer/species census loader.

`load_trainer_census()` looks for `pokemon_xd/data/trainer_census.json` and parses it into
`team_shuffle.Species` / `TrainerPool`. Absent, it returns None and `generate_output` skips trainer-team
randomization for that seed, leaving item placement alone. The file is not shipped: a hand-transcribed roster
would bake wrong species/level data into a patch the player trusts.

Expected shape:
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

from . import load_json_data_file
from ..randomizer.team_shuffle import PokemonInstance, Species, Trainer, TrainerPool


def load_trainer_census() -> tuple[dict[int, Species], list[TrainerPool]] | None:
    """(species_pool, trainer_pools) when a census file is present, else None -- a missing file is the
    expected state, not an error. Goes through `load_json_data_file` so it works the same from a loose
    checkout or a zipped .apworld."""
    raw = load_json_data_file("trainer_census.json")
    if raw is None:
        return None

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
