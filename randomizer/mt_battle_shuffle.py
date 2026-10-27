"""Mt. Battle's teams, randomized like the story's.

Mt. Battle's 100 trainers live in `DeckData_Hundred.bin`, their own table with their own DPKM numbering, so the
story shuffle never reaches them. With Exclude Mt. Battle Trainers off they are fought for checks, and every
member is re-rolled here by the story's rules: each slot its own draw, evolved for the level it is fought at, no
species twice on one team, legendaries only for legendaries unless Legendary Trainer Pokemon is on. Each member then
gets a moveset for its new species and level from the same chooser every other trainer Pokemon uses.

Levels are not decided here; the caller passes each member's final level (Enhanced Difficulty and path scaling
have already run). Trainer and DPKM indices are Mt. Battle's own, never the story table's.
"""
from __future__ import annotations

import random
from typing import Iterable

from .team_shuffle import MOVESET_SHUFFLE_DEFAULT_MOVE_COUNT, Species, choose_moveset, pick_distinct_species


def _members(trainers: Iterable[dict]):
    for trainer in trainers:
        for slot in trainer.get("team", ()):
            if slot.get("kind") == "DPKM" and slot.get("dpkm_index") is not None:
                yield trainer, slot


def shuffle_species(trainers: "list[dict]", final_levels: "dict[int, int]", species_pool: "dict[int, Species]",
                    rng: random.Random, legendary_safe: bool = True) -> "dict[int, int]":
    """{dpkm_index: new species} for every Mt. Battle member. `trainers` is `data/mtbattle_trainer_census.json`;
    `final_levels` overrides a member's census level."""
    candidates = {
        legendary: [sid for sid, sp in species_pool.items() if sp.is_legendary == legendary or not legendary_safe]
        for legendary in (False, True)
    }
    out: "dict[int, int]" = {}
    for trainer in trainers:
        team: "set[int]" = set()
        for slot in trainer.get("team", ()):
            if slot.get("kind") != "DPKM" or slot.get("dpkm_index") is None:
                continue
            dpkm = int(slot["dpkm_index"])
            original = species_pool.get(int(slot["species"]))
            if original is None:
                continue        # an unknown species is left as the game has it
            level = int(final_levels.get(dpkm, slot["level"]))
            pool = candidates[original.is_legendary] or list(species_pool)
            species = pick_distinct_species(rng, pool, level, species_pool, team)
            team.add(species)
            out[dpkm] = species
    return out


def movesets(species_by_dpkm: "dict[int, int]", final_levels: "dict[int, int]", trainers: "list[dict]",
             level_up_moves: "dict[int, list[tuple[int, int]]]", rng: random.Random,
             move_count: int = MOVESET_SHUFFLE_DEFAULT_MOVE_COUNT) -> "dict[int, list[int]]":
    """{dpkm_index: [move_count ids, 0-padded]} for each re-rolled member. A species with no level-up data keeps
    the record's moves."""
    out: "dict[int, list[int]]" = {}
    for _trainer, slot in _members(trainers):
        dpkm = int(slot["dpkm_index"])
        species = species_by_dpkm.get(dpkm)
        if species is None:
            continue
        level = int(final_levels.get(dpkm, slot["level"]))
        chosen = choose_moveset(species, level, level_up_moves.get(species, []), rng, move_count)
        if chosen:
            out[dpkm] = list(chosen) + [0] * (move_count - len(chosen))
    return out


def team_species(trainers: "list[dict]", species_by_dpkm: "dict[int, int]") -> "dict[int, set[int]]":
    """{trainer index: the species its team fields}, for keeping Enhanced Difficulty's padding off them."""
    return {
        int(trainer["index"]): {species_by_dpkm.get(int(slot["dpkm_index"]), int(slot["species"]))
                                for slot in trainer.get("team", ())
                                if slot.get("kind") == "DPKM" and slot.get("dpkm_index") is not None}
        for trainer in trainers
    }
