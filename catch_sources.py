"""
Where each "Catch - {species}" check can actually be caught THIS seed.

This cannot go in the location name: names are part of the datapackage and must be identical for every seed,
while which trainer holds Luvdisc changes per seed. So it goes in AP's two per-seed channels instead --
`World.extend_hint_information` (shown in brackets after the location in hints and the spoiler) and slot_data
`catch_sources` (what the client's `/catches` command prints, so the player need not spend hints).

Built from the same per-seed caches `rules._catch_gates_for_species` reads. The shadow pool is shuffled in
place, so re-deriving any of this later would describe the vanilla game and the text would disagree with the
logic.
"""
from __future__ import annotations

from typing import Any

_POKESPOT_LABEL = {"rock": "Rock Poke Spot", "oasis": "Oasis Poke Spot", "cave": "Cave Poke Spot",
                   "all": "any Poke Spot"}


def _host_label(index: int) -> "str | None":
    from .game_data import trainer_roster

    trainer = trainer_roster.TRAINERS_BY_INDEX.get(index)
    if trainer is None:
        return None
    label = trainer_roster.trainer_label(trainer)
    return label[len("Defeat - "):] if label.startswith("Defeat - ") else label


def sources_by_dex(world: Any) -> "dict[int, list[str]]":
    """dex -> human-readable sources, earliest-recorded first, duplicates dropped."""
    from .game_data import shadow_regions, trainer_placements

    out: "dict[int, list[str]]" = {}

    def add(dex: int, text: str) -> None:
        bucket = out.setdefault(dex, [])
        if text not in bucket:
            bucket.append(text)

    for dex, labels in (getattr(world, "_shadow_catch_labels", None) or {}).items():
        for location_name in labels:
            label = shadow_regions.trainer_label_from_location(location_name)
            gate = shadow_regions.gate_for_label(label)
            add(dex, f"Shadow: {label}, {gate.region}" if gate else f"Shadow: {label}")

    for dex, hosts in (getattr(world, "_shadow_catch_expansion_hosts", None) or {}).items():
        for index in hosts:
            label = _host_label(index) or f"trainer #{index}"
            region = trainer_placements.region_for(index)
            add(dex, f"Shadow: {label}, {region}" if region else f"Shadow: {label}")

    for entry in (getattr(world, "_pokespot_species_assignment", None) or []):
        dex = entry.get("new_dex")
        if isinstance(dex, int):
            add(dex, f"Wild: {_POKESPOT_LABEL.get(entry.get('pool'), 'Poke Spot')}")
    return out


def sources_by_location(world: Any) -> "dict[str, str]":
    """"Catch - {species}" -> "source; source", only for catch locations this seed actually created."""
    from .species import location_name_for_species

    created = {location.name for location in world.multiworld.get_locations(world.player)}
    out: "dict[str, str]" = {}
    for dex, texts in sources_by_dex(world).items():
        try:
            name = location_name_for_species(dex)
        except KeyError:
            continue
        if name in created and texts:
            out[name] = "; ".join(texts)
    return out
