"""
Enhanced Difficulty: which real trainers get their ordinary (non-Shadow) team padded out, and a level boost
for every existing member, decided per seed with the world's own seeded RNG.

Ordinary DPKM entries only, never Shadow Pokemon: this option touches the DPKM section and Shadow Pokemon
Expansion touches DDPK capacity, so either works with the other off. The ramp is in `_tier_add_count`, keyed
off the DTNR `trainer_index` because no confirmed story order exists for the 232-trainer roster.
`build_enhanced_difficulty_plan` is generic over the table it gets and `generate_output` calls it again for
Mt. Battle's `DeckData_Hundred.bin`; the two tables' trainer_index values are unrelated namespaces, so each
call site passes its own `permanently_excluded_trainer_indices`.
"""

from __future__ import annotations

import math
import random

from ..game_data.real_trainer_data import PERMANENTLY_EXCLUDED_TRAINER_INDICES
from .team_shuffle import Species, choose_moveset, resolve_natural_evolution

# Multiplied into each Pokemon's own level and floored, through `_scaled_level()` -- the one place both
# existing-member boosting and new-member padding go, so the two cannot drift apart.
ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER = 1.33
ENHANCED_DIFFICULTY_MOVE_COUNT = 4  # grown entries, not the in-place shuffle budget ADDENDUM 35 capped at 3

# Ramp boundaries -- see `_tier_add_count`.
_TIER_EXCLUDED_MAX_INDEX = 5
_TIER_PLUS_ONE_MAX_INDEX = 10
_TIER_PLUS_TWO_MAX_INDEX = 15


def adjust_team_census_for_reserved_slots(team_census: list[dict], reserved_by_trainer: dict[int, int]) -> list[dict]:
    """Returns a copy of `team_census` with each trainer's `free_slots` reduced by
    `reserved_by_trainer.get(trainer_index, 0)`, floored at 0. Shadow Expansion and Enhanced Difficulty both
    draw new members from the same pre-patch free-slot count and Shadow Expansion's ISO write lands first, so
    with both on dozens of real trainers ended up with an ED plan asking for more members than they had slots
    left. An empty mapping is a safe no-op."""
    return [
        {**t, "free_slots": max(0, t["free_slots"] - reserved_by_trainer.get(t["trainer_index"], 0))}
        for t in team_census
    ]


# How many members a setting will ever add to one trainer. `None` is "fill", the ramp's own top tier.
FILL_THE_TEAM: "int | None" = None


def ordinary_level_assignment(
    team_census: "list[dict]",
    level_multiplier: float = ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER,
    scale_levels: bool = True,
    permanently_excluded_trainer_indices: "frozenset[int]" = PERMANENTLY_EXCLUDED_TRAINER_INDICES,
) -> "dict[int, int]":
    """Every existing ordinary team member's final level this seed, `{dpkm_index: level}`. Shared with
    `__init__.generate_early`, which evolves each shuffled species against the level it will be fought at --
    that level is this output, not the vanilla one in the census, and the two used to disagree. Chobin gets no
    entry, matching the plan builder; with `scale_levels` False the result is empty."""
    levels: "dict[int, int]" = {}
    if not scale_levels:
        return levels
    for t in team_census:
        if t["trainer_index"] in permanently_excluded_trainer_indices:
            continue
        for dpkm_index, level in t["member_levels"].items():
            levels[dpkm_index] = _scaled_level(level, level_multiplier)
    return levels


def shadow_level_assignment(
    shadow_census: "list[dict]",
    level_multiplier: float = ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER,
    scale_levels: bool = True,
) -> "tuple[dict[int, int], dict[int, int]]":
    """Vanilla Shadow Pokemon, matched to their trainer's team average and then scaled.

    Two maps, because a Shadow's level is stored twice and they have to agree: {dpkm_index: level} for the DPKM
    record the DDPK points at, where species and level really live, and {ddpk_index: level} for the DDPK
    record's own `shadow_level` byte (+0x02). Matching comes first, then scaling, which is not the same as
    scaling what is there: a level-17 Shadow on a team averaging 50 becomes 50, then 66, not 22. The nine
    Shadows on teamless trainers keep their own level, scaled, and `scale_levels` False still returns matched
    levels. A record carrying `"level_source": "path"` is already on the level ramp and skips the floor below."""
    dpkm_levels: "dict[int, int]" = {}
    ddpk_levels: "dict[int, int]" = {}
    multiplier = level_multiplier if scale_levels else 1.0
    for record in shadow_census:
        base = record.get("team_avg_level")
        if base is None:
            base = record.get("shadow_level")
        if base is None:
            continue
        # Floor the base at the vanilla level BEFORE scaling, so it composes with the multiplier the way a
        # matched level does: 17 on a team averaging 8.8 stays 17, then 22 (ADDENDUM 317). Matching runs both
        # ways, and the downward half was producing Shadows weaker than the unmodified game's.
        #
        # Path-scaled records are exempt, per record, since both populations share one census: their base is the
        # region's tier level, which ADDENDUM 296 lets sit far below vanilla (capped 50, floored 8) so a late
        # area handed out early stays survivable -- flooring it leaves a level-28 Shadow on a level-12 team.
        # Measured on AP_84192203482497242093 (path scaling on, ED off): `max(tier_level, vanilla)` predicted 76
        # of the 76 checkable shipped Shadow levels and beat the ramp on 57 of 83.
        vanilla = record.get("shadow_level")
        if vanilla is not None and record.get("level_source") != "path":
            base = max(base, vanilla)
        level = _scaled_level(base, multiplier)
        if record.get("dpkm_index") is not None:
            dpkm_levels[record["dpkm_index"]] = level
        if record.get("ddpk_index") is not None:
            ddpk_levels[record["ddpk_index"]] = level
    return dpkm_levels, ddpk_levels


def cap_for_option(value: int) -> "int | None":
    """The `max_added_members` a given EnhancedDifficulty choice means, kept beside the ramp it caps. `0` (off)
    never reaches the plan builder, but is mapped anyway so an off setting cannot yield a silent "fill"."""
    if value <= 0:
        return 0
    if value == 1:
        return 1
    if value == 2:
        return 2
    return FILL_THE_TEAM


def _tier_add_count(trainer_index: int, free_slots: int, cap: "int | None" = FILL_THE_TEAM) -> int:
    """The ramp, then the player's chosen setting as a second ceiling, then the trainer's own free slots.

    The bands are themselves caps: trainer 1-5 may receive nothing, 6-10 at most one, 11-15 at most two, 16+
    every remaining slot. The setting can only lower what a band receives, never raise it, and "up to" is
    literal -- nobody ever loses an existing member or exceeds six."""
    if trainer_index <= _TIER_EXCLUDED_MAX_INDEX:
        wanted = 0
    elif trainer_index <= _TIER_PLUS_ONE_MAX_INDEX:
        wanted = 1
    elif trainer_index <= _TIER_PLUS_TWO_MAX_INDEX:
        wanted = 2
    else:
        wanted = free_slots  # every remaining slot, for every later trainer
    if cap is not None:
        wanted = min(wanted, cap)
    return min(wanted, free_slots)


def _scaled_level(level: float, multiplier: float) -> int:
    """`floor(level * multiplier)`, clamped to the real 1-100 range. Floor, not round: the rule is "1.33x
    their level... round down if it's not a whole number"."""
    return max(1, min(100, math.floor(level * multiplier)))


def _moveset_for(species_id: int, level: int, level_up_moves: dict[int, list[tuple[int, int]]],
                  rng: random.Random, move_count: int = ENHANCED_DIFFICULTY_MOVE_COUNT) -> list[int]:
    """Thin wrapper over `team_shuffle.choose_moveset` for a brand-new ordinary DPKM entry; see that function
    for the move exclusions."""
    learnset = level_up_moves.get(species_id, [])
    return choose_moveset(species_id, level, learnset, rng, move_count)


def build_enhanced_difficulty_plan(
    team_census: list[dict],
    species_pool: dict[int, Species],
    level_up_moves: dict[int, list[tuple[int, int]]],
    rng: random.Random,
    level_multiplier: float = ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER,
    excluded_trainer_indices: frozenset[int] = frozenset(),
    permanently_excluded_trainer_indices: frozenset[int] = PERMANENTLY_EXCLUDED_TRAINER_INDICES,
    max_added_members: "int | None" = FILL_THE_TEAM,
    scale_levels: bool = True,
) -> dict:
    """The full per-seed plan: every existing ordinary member's level scaled to `floor(level *
    level_multiplier)`, and every eligible trainer's team padded per the ramp with real, level-appropriate,
    non-legendary species and movesets drawn from `rng` (the world's own seeded RNG). Legendaries are excluded
    from new members, but species may repeat across trainers, unlike Shadow Pokemon.

    `permanently_excluded_trainer_indices` applies unconditionally and skips BOTH padding and level scaling,
    unlike `excluded_trainer_indices`, which gates only the padding. Its Chobin default is Story-scoped and
    wrong for any other table -- Story trainer_index 15 and Mt. Battle trainer_index 15 are unrelated trainers
    -- so a Mt. Battle caller must pass its own value, usually `frozenset()`.

    Returns `{"level_assignment", "new_dpkm_entries", "team_slot_plan"}` as
    `iso_patcher.write_enhanced_difficulty_patch` consumes it."""
    candidate_species = [sid for sid, sp in species_pool.items() if not sp.is_legendary]

    level_assignment: dict[int, int] = {}
    new_dpkm_entries: list[dict] = []
    team_slot_plan: list[dict] = []

    for t in sorted(team_census, key=lambda t: t["trainer_index"]):
        trainer_index = t["trainer_index"]
        if trainer_index in permanently_excluded_trainer_indices:
            # Unconditional, and the only thing here that skips the level scaling too.
            continue
        if scale_levels:
            # One implementation, shared with generate_early -- see ordinary_level_assignment.
            level_assignment.update(ordinary_level_assignment(
                [t], level_multiplier, True, permanently_excluded_trainer_indices,
            ))

        if trainer_index in excluded_trainer_indices:
            continue
        add_count = _tier_add_count(trainer_index, t["free_slots"], max_added_members)
        if add_count == 0 or not candidate_species:
            continue

        # A padding member has no level of its own, so it joins at the team average, through the same
        # `_scaled_level` every existing member uses -- and at the plain average with scaling off, or the
        # switch would still hand padded trainers members 33% above the team they joined.
        new_member_level = (_scaled_level(t["avg_level"], level_multiplier) if scale_levels
                            else _scaled_level(t["avg_level"], 1.0))
        for _ in range(add_count):
            species_id = rng.choice(candidate_species)
            # An ordinary slot has no cross-slot uniqueness invariant (unlike the shadow dedup) to protect.
            species_id = resolve_natural_evolution(species_id, new_member_level, species_pool)
            entry_pos = len(new_dpkm_entries)
            new_dpkm_entries.append({
                "species": species_id,
                "level": new_member_level,
                "moves": _moveset_for(species_id, new_member_level, level_up_moves, rng),
            })
            team_slot_plan.append({"trainer_index": trainer_index, "new_entry_pos": entry_pos})

    return {
        "level_assignment": level_assignment,
        "new_dpkm_entries": new_dpkm_entries,
        "team_slot_plan": team_slot_plan,
    }
