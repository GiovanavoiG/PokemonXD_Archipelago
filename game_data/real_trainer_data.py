"""
Real, ISO-extracted trainer census for Pokemon XD: Gale of Darkness (2026-09-06).

Not `trainer_census.py`, which loads a hand-transcribed census (68 of the game's 232 trainers, from wiki/FAQ
text -- `data/trainer_pools_SOURCES.md`) keyed by display name, with no join key back to the ISO's own DPKM
records, so a shuffle over it can never become a patch.

This loads `data/deckdata_story_trainers.json`, decoded from a real ISO by `tools/xd_deck_format.py`'s
`DeckFile`: all 232 non-empty trainers, each DPKM slot's own `dpkm_index` kept as `PokemonInstance.index`,
which is the byte position `tools/iso_patcher.py` overwrites. Species are the game's INTERNAL indices
(`tools/xd_species_index.py`), not National Dex; convert for display via `national_dex_for()`. Shadow (DDPK)
slots are excluded: their species resolves indirectly through a `story_deck_index` pointer into this same
pool, not extracted here, and randomizing it would desync `shadow_species.py`'s "Shadow Defeat - {trainer}
({species})" locations from what the game produces.

Shape of that file (from `tools/xd_deck_format.py`'s `__main__`):
[{"index": int, "trainer_class": int, "name_id": int, "party_size": int,
  "team": [{"slot": int, "kind": "DPKM", "dpkm_index": int, "species": int, "level": int} |
           {"slot": int, "kind": "DDPK", "ddpk_index": int}, ...]}, ...]
"""

from __future__ import annotations

from . import load_json_data_file
from ..randomizer.team_shuffle import PokemonInstance, Species, Trainer, TrainerPool
from ..tools.xd_species_index import INTERNAL_INDEX_TO_NATIONAL_DEX

# Legendary/mythical National Dex numbers in Gen I-III (this game's whole species range) -- drives the
# pool's `is_legendary` flag, so `legendary_safe=True` never randomizes an ordinary trainer into one.
LEGENDARY_NATIONAL_DEX: set[int] = {
    144, 145, 146, 150, 151,  # Articuno, Zapdos, Moltres, Mewtwo, Mew
    243, 244, 245, 249, 250, 251,  # Raikou, Entei, Suicune, Lugia, Ho-Oh, Celebi
    377, 378, 379, 380, 381, 382, 383, 384, 385, 386,  # Regirock/Regice/Registeel/Latias/Latios/Kyogre/
                                                        # Groudon/Rayquaza/Jirachi/Deoxys
}

# ADDENDUM 101: Lugia, Bonsly and Munchlax are permanently off the randomizable pool by player request.
# Internal species indices (National Dex 249, 387, 388), filtered in `real_species_pool()` -- the one shared
# source every candidate list draws from. Vanilla slots holding them are still reassigned like any other;
# what changes is that nothing can be randomized INTO them.
PERMANENTLY_EXCLUDED_SPECIES_INDICES: frozenset[int] = frozenset({249, 413, 414})  # Lugia, Bonsly, Munchlax


def real_species_pool() -> dict[int, Species]:
    """Every valid internal species index as a `Species`, keyed by that internal index (not National Dex).
    Excludes the 25 reserved/unused 252-276 slots and `PERMANENTLY_EXCLUDED_SPECIES_INDICES`.

    `evolves_into`/`evolves_at_level` come from `evolution_data`; before ADDENDUM 100 this never set them,
    which made `_apply_forced_evolution` a silent no-op. Level-up, single-target evolutions only."""
    from .evolution_data import national_dex_to_internal_level_evolutions

    level_evolutions = national_dex_to_internal_level_evolutions()
    pool: dict[int, Species] = {}
    for internal_index, (national_dex, name) in INTERNAL_INDEX_TO_NATIONAL_DEX.items():
        if name is None:
            continue  # reserved/unused slot -- not a real species, never a valid replacement
        if internal_index in PERMANENTLY_EXCLUDED_SPECIES_INDICES:
            continue  # ADDENDUM 101 -- player-requested permanent exclusion, see that set's own comment
        evolves_into, evolves_at_level = level_evolutions.get(internal_index, (None, None))
        pool[internal_index] = Species(
            species_id=internal_index,
            is_legendary=national_dex in LEGENDARY_NATIONAL_DEX,
            evolves_into=evolves_into,
            evolves_at_level=evolves_at_level,
        )
    return pool


def load_real_trainer_pools() -> tuple[dict[int, Species], list[TrainerPool]] | None:
    """(species_pool, trainer_pools) from the real ISO-extracted data, or None if that file is not in this
    build. Every `PokemonInstance.index` is the slot's real `dpkm_index`; preserve it end to end
    (`shuffle_teams` reassigns only `.species_id`/`.level`/`.item_id`) so `iso_patcher` can apply it."""
    raw_trainers = load_json_data_file("deckdata_story_trainers.json")
    if raw_trainers is None:
        return None

    trainers: list[Trainer] = []
    for t in raw_trainers:
        team = [
            PokemonInstance(
                index=slot["dpkm_index"],
                species_id=slot["species"],
                level=slot["level"],
                item_id=None,
                is_shadow=False,
            )
            for slot in t.get("team", [])
            if slot.get("kind") == "DPKM"  # shadow (DDPK) slots excluded -- see module docstring
        ]
        if not team:
            continue  # an all-shadow trainer (or, defensively, an empty one) -- nothing for us to randomize
        trainers.append(Trainer(name=f"Trainer #{t['index']} (class {t['trainer_class']})", team=team))

    pool = TrainerPool(name="DeckData_Story.bin (real, ISO-extracted)", trainers=trainers)
    return real_species_pool(), [pool]


def real_trainer_free_slot_census() -> list[dict] | None:
    """What `randomizer.shadow_expansion` needs to place a new Shadow: each trainer's DTNR `trainer_index`
    (which `load_real_trainer_pools` drops), free slot count (`6 - party_size`), and average team level.
    `[{"trainer_index": int, "free_slots": int, "avg_level": float}]`, for trainers with at least one free
    slot AND one member carrying a real level -- an all-Shadow trainer is skipped, not guessed at."""
    raw_trainers = load_json_data_file("deckdata_story_trainers.json")
    if raw_trainers is None:
        return None

    census: list[dict] = []
    for t in raw_trainers:
        free_slots = 6 - t["party_size"]
        if free_slots < 1:
            continue
        levels = [slot["level"] for slot in t.get("team", []) if slot.get("level") is not None]
        if not levels:
            continue
        census.append({
            "trainer_index": t["index"],
            "free_slots": free_slots,
            "avg_level": sum(levels) / len(levels),
        })
    return census


def real_trainer_team_census() -> list[dict] | None:
    """Per-member levels for Enhanced Difficulty: `iso_patcher.apply_level_boost()` takes
    `{dpkm_index: new_level}`, so each DPKM member needs its own index and level, not a team average.
    `[{"trainer_index", "free_slots", "avg_level", "member_levels": {dpkm_index: level}}]`. Includes every
    trainer with a DPKM member regardless of `free_slots` -- a full trainer still needs boosting."""
    raw_trainers = load_json_data_file("deckdata_story_trainers.json")
    if raw_trainers is None:
        return None

    census: list[dict] = []
    for t in raw_trainers:
        member_levels = {
            slot["dpkm_index"]: slot["level"]
            for slot in t.get("team", [])
            if slot.get("kind") == "DPKM" and slot.get("level") is not None
        }
        if not member_levels:
            continue
        census.append({
            "trainer_index": t["index"],
            "free_slots": 6 - t["party_size"],
            "avg_level": sum(member_levels.values()) / len(member_levels),
            "member_levels": member_levels,
        })
    return census


def real_shadow_census() -> "list[dict] | None":
    """Every vanilla Shadow Pokemon, with the DPKM record its level actually lives in and the average level
    of the ordinary team it belongs to.

    A trainer's Shadow slot carries only a `ddpk_index`, no level and no dpkm_index, so
    `real_trainer_team_census` cannot see it. `DeckData_DarkPokemon.bin` is the join: each DDPK record holds
    a `story_deck_index` (called `dpkm_index` here) pointing at the DPKM record where that Shadow's species
    and level really are. Those records are disjoint from every team slot -- zero overlap of 726 team slots
    against 83 Shadow records -- so their levels go through the same `{dpkm_index: level}` channel Enhanced
    Difficulty uses, with no risk of two plans fighting over one record.

    `[{"ddpk_index", "dpkm_index", "trainer_index", "shadow_level", "team_avg_level"}]`, or None if either
    data file is missing. `team_avg_level` is None for the nine Shadows whose trainer has no ordinary member
    (Hordel's Teddiursa, Greevil's six); with no team to average, the caller keeps the Shadow's own level."""
    ddpk = load_json_data_file("deckdata_dark_pokemon.json")
    if ddpk is None or load_json_data_file("deckdata_story_trainers.json") is None:
        return None

    # ADDENDUM 316: the holder is resolved once in `game_data/shadow_holders.py` and read here rather than
    # re-derived -- re-deriving it is how this disagreed with the logic side (ADDENDUM 315). `occurrence`
    # and `region` come across too, so a caller asking "which fight?" need not join back to the roster.
    from . import shadow_holders

    holders = shadow_holders.vanilla_shadow_holders()

    out: "list[dict]" = []
    for record in ddpk:
        ddpk_index = record.get("ddpk_index")
        dpkm_index = record.get("dpkm_index")
        if ddpk_index is None or dpkm_index is None:
            continue
        holder = holders.get(ddpk_index)
        out.append({
            "ddpk_index": ddpk_index,
            "dpkm_index": dpkm_index,
            "trainer_index": holder.trainer_index if holder else None,
            "shadow_level": record.get("shadow_level"),
            "team_avg_level": holder.team_avg_level if holder else None,
            "occurrence": holder.occurrence if holder else None,
            "region": holder.region if holder else None,
        })
    return out


# Permanently empty by design, not an unfinished placeholder: Mt. Battle's trainers are not in
# `DeckData_Story.bin` at all. ADDENDUM 92/93 decoded them from `DeckData_Hundred.bin`, which has its own
# trainer_index namespace (1-100, unrelated to any story index of the same number), and this constant gates
# story-scoped exclusion. `ExcludeMtBattleTrainers` gates `game_data/mtbattle_trainer_data.py` instead.
MT_BATTLE_TRAINER_INDICES: frozenset[int] = frozenset()


# Excluded UNCONDITIONALLY, whatever the YAML says: no new team members and no level boost.
# `enhanced_difficulty.build_enhanced_difficulty_plan` and `shadow_expansion.build_shadow_expansion_plans`
# apply this set themselves rather than trusting every caller to merge it into `excluded_trainer_indices`.
# 15 is the early Chobin fight (solo level-5 Sunkern, party_size 1 per `data/deckdata_story_trainers.json`);
# 8 and 69 are Aferd's first two encounters (ADDENDUM 149) -- AFERD is story indices 8, 69, 70, 146, 223,
# occurrences 1-5, and 70/146/223 stay eligible on purpose.
PERMANENTLY_EXCLUDED_TRAINER_INDICES: frozenset[int] = frozenset({15, 8, 69})


def dpkm_species_assignment(trainer_pools: list[TrainerPool]) -> dict[int, int]:
    """Flattens shuffled `TrainerPool`s into {dpkm_index: new_internal_species_index}, the shape
    `tools/iso_patcher.py` consumes to patch `DeckData_Story.bin` in place. Safe as a 1:1 flatten: 726 DPKM
    team slots, 726 distinct dpkm_index values, verified 2026-09-06 against the real data."""
    assignment: dict[int, int] = {}
    for pool in trainer_pools:
        for trainer in pool.trainers:
            for mon in trainer.team:
                assignment[mon.index] = mon.species_id
    return assignment
