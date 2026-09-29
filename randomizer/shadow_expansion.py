"""
Shadow Pokemon expansion: which real trainers get brand-new, genuinely-distinct Shadow Pokemon beyond the
game's fixed 83, and what species/level/moves each gets, drawn from the world's own seeded RNG.

Hard capacity ceiling, read before raising `SHADOW_EXPANSION_MAX_NEW_POKEMON`: a vanilla ISO has exactly 44
free DDPK indices (128 slots in `DeckData_DarkPokemon.bin`, 83 used by the vanilla roster, 1 reserved sentinel
at index 0, from scanning the real container bytes, ADDENDUM 69), so `ShadowPokemonExpansion` is a 0-44 Range
and there is nowhere for a 45th. The full ceiling booted and battled cleanly on real hardware: 22 trainers,
all 44 slots at once. Mt. Battle is out of scope permanently, and already out structurally -- do not wire an
`mtbattle_team_census()` census into the `free_slot_census` this module is handed.
"""

from __future__ import annotations

import random

from ..game_data.real_trainer_data import PERMANENTLY_EXCLUDED_TRAINER_INDICES
from ..game_data import shadow_move_slots
from .team_shuffle import Species, choose_moveset, resolve_natural_evolution

SHADOW_EXPANSION_MAX_NEW_POKEMON = 44  # the real, disc-format-level ceiling -- see module docstring
# Tracks assign_movesets' default. Generated shadows live in grown DDPK entries rather than the in-place DPKM
# budget ADDENDUM 35 measured, but keeping the two in step leaves one place to look on a budget change.
SHADOW_EXPANSION_MOVE_COUNT = 4
# The real Shadow-move id census: all 83 vanilla DDPK entries carry exactly 2 non-zero shadow_moves, 18
# distinct ids, contiguous 356-373 (ADDENDUM 61). Selection lives in game_data/shadow_move_slots.py, which
# also records which SLOT each id is legal in.
REAL_SHADOW_MOVE_IDS: list[int] = list(range(356, 374))


def _moveset_for(species_id: int, level: int, level_up_moves: dict[int, list[tuple[int, int]]],
                  rng: random.Random, move_count: int = SHADOW_EXPANSION_MOVE_COUNT) -> list[int]:
    """Move selection for a brand-new DPKM entry with no existing slot to look up; delegates to
    `team_shuffle.choose_moveset`. Returns [] rather than padding when the species has no real level-up data --
    `grow_dpkm_section` treats a short `moves` list as "leave the rest zero"."""
    learnset = level_up_moves.get(species_id, [])
    return choose_moveset(species_id, level, learnset, rng, move_count)


def build_shadow_expansion_plans(
    free_slot_census: list[dict],
    species_pool: dict[int, Species],
    level_up_moves: dict[int, list[tuple[int, int]]],
    excluded_species: set[int],
    target_count: int,
    rng: random.Random,
    max_new_pokemon: int = SHADOW_EXPANSION_MAX_NEW_POKEMON,
    excluded_trainer_indices: frozenset[int] = frozenset(),
    level_multiplier: float = 1.0,
) -> list[dict]:
    """Picks `target_count` brand-new Shadow Pokemon -- clamped to `max_new_pokemon` and to the real free-slot
    capacity in `free_slot_census` (`real_trainer_free_slot_census()`'s output) -- and returns
    `[{"trainer_index": int, "new_pokemon": [{"species", "level", "moves", "shadow_moves"}, ...]}]`, the shape
    `iso_patcher.write_shadow_multi_trainer_patch` consumes.

    Exclusions are what that census omits, `excluded_trainer_indices`, and
    `PERMANENTLY_EXCLUDED_TRAINER_INDICES`, always applied on top so callers need not merge it in; legendaries
    and `excluded_species` (the 83 vanilla Shadow species) are dropped from `species_pool`. Species are drawn
    WITHOUT REPLACEMENT, so no two new Shadows in a seed share a species, and trainers are filled ROUND-ROBIN
    rather than one at a time, spreading new content over as many trainers as the target allows -- there are no
    trainer-index bands, because this option must work without Enhanced Difficulty. Each new Pokemon's level is
    its trainer's average team level times `level_multiplier`, rounded, clamped 1-100. Deterministic given the
    same `rng` state -- pass the world's own seeded `self.random`."""
    eligible = [
        t for t in free_slot_census
        if t["trainer_index"] not in excluded_trainer_indices
        and t["trainer_index"] not in PERMANENTLY_EXCLUDED_TRAINER_INDICES
    ]
    total_capacity = sum(t["free_slots"] for t in eligible)
    target_count = max(0, min(target_count, max_new_pokemon, total_capacity))
    if target_count == 0:
        return []

    candidate_species = [
        sid for sid, sp in species_pool.items()
        if not sp.is_legendary and sid not in excluded_species
    ]
    target_count = min(target_count, len(candidate_species))
    if target_count == 0:
        return []
    chosen_species = rng.sample(candidate_species, target_count)

    trainers = list(eligible)
    rng.shuffle(trainers)
    remaining_free_slots = {t["trainer_index"]: t["free_slots"] for t in trainers}
    avg_level_by_trainer = {t["trainer_index"]: t["avg_level"] for t in trainers}
    order = [t["trainer_index"] for t in trainers]

    assigned_counts: dict[int, int] = {idx: 0 for idx in order}
    total_assigned = 0
    while total_assigned < target_count:
        progressed = False
        for idx in order:
            if total_assigned >= target_count:
                break
            if remaining_free_slots[idx] > 0:
                assigned_counts[idx] += 1
                remaining_free_slots[idx] -= 1
                total_assigned += 1
                progressed = True
        if not progressed:
            break  # every eligible trainer's free slots are exhausted -- total_capacity already bounds this
    assigned_counts = {idx: count for idx, count in assigned_counts.items() if count > 0}

    plans: list[dict] = []
    species_cursor = 0
    # The dedup set is post-evolution and starts from the vanilla Shadow species the caller reserved: without
    # that, a new Shadow could evolve into a species a vanilla Shadow already is (ADDENDUM 198).
    claimed: set[int] = set(excluded_species)

    def _claim(pick: int, at_level: int) -> int:
        """Evolve `pick` to `at_level` and reserve the result, trying other candidates on a collision."""
        evolved = resolve_natural_evolution(pick, at_level, species_pool)
        if evolved not in claimed:
            claimed.add(evolved)
            return evolved
        for alternative in chosen_species[species_cursor:] + candidate_species:
            evolved = resolve_natural_evolution(alternative, at_level, species_pool)
            if evolved not in claimed:
                claimed.add(evolved)
                return evolved
        claimed.add(pick)
        return pick  # pool exhausted -- an unevolved duplicate beats failing generation

    for idx in sorted(assigned_counts):
        # `level_multiplier` is what carries Enhanced Difficulty's scaling into the trainer average; it
        # defaults to 1.0, so Shadow Expansion on its own behaves exactly as before.
        level = max(1, min(100, round(avg_level_by_trainer[idx] * level_multiplier)))
        new_pokemon = []
        for _ in range(assigned_counts[idx]):
            species_id = chosen_species[species_cursor]
            species_cursor += 1
            # Evolve to the level this Pokemon actually joins at, like every other randomized Pokemon.
            species_id = _claim(species_id, level)
            new_pokemon.append({
                "species": species_id,
                "level": level,
                "moves": _moveset_for(species_id, level, level_up_moves, rng),
                # Shadow-move legality is POSITIONAL: ids 367-373 never appear in slot 0 in any of the 83
                # vanilla entries, and five of 356-366 appear in no slot but 0. Sampling 2 uniformly from all 18
                # put an illegal move (no PP in-game) in slot 0 for 14 of 44 Shadows in a real seed. Measured
                # table: game_data/shadow_move_slots.py.
                "shadow_moves": shadow_move_slots.choose_shadow_moves(rng, 2),
            })
        plans.append({"trainer_index": idx, "new_pokemon": new_pokemon})
    return plans
