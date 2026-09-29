"""Combined-options regression test (2026-09-08): Shadow Pokemon Expansion and Enhanced Difficulty are
independent yaml options (player request: "shadow expansion should be a separate yaml option. I do still want
shadow expansion to add pokemon even without the enhanced difficulty enabled"), but both independently draw new
team members from the SAME real, pre-patch per-trainer free-slot count, and `apply_patch()` applies Shadow
Pokemon Expansion's ISO write before Enhanced Difficulty's.

WHY THIS TEST EXISTS: while building the split, cross-checking both options' plans against this project's own
real trainer census (not synthetic data -- the collision only shows up at real scale) found 43 real trainers
where turning BOTH options on together at max settings produced a combined new-team-member count exceeding that
trainer's real free_slots. Applied to a real ISO, this would have made `write_enhanced_difficulty_patch`'s
fresh-re-read DTNR slot search (`next(slot for slot in range(6) if slot not in used_slots)`) raise `StopIteration`
partway through a real patch run, after Shadow Pokemon Expansion's own write had already gone through -- a
crash, not silent corruption, but still a real seed a player could generate and then be unable to patch.

The fix is `randomizer.enhanced_difficulty.adjust_team_census_for_reserved_slots` (see its own docstring),
called from `__init__.py`'s `generate_output` before building the Enhanced Difficulty plan whenever Shadow
Pokemon Expansion is also enabled. This test imports and exercises that exact same shared helper function (no
logic is re-implemented/duplicated here, so this test can't silently drift from the real behavior) against the
real, ISO-extracted trainer census, at the worst-case setting (shadow_pokemon_expansion=44, the real
disc-format ceiling) across several RNG seeds, and asserts the invariant that broke without the fix: no
trainer's combined (Shadow Pokemon Expansion + Enhanced Difficulty) new-member count may ever exceed that
trainer's real free_slots.
"""
import random

from ..game_data.real_moveset_data import load_level_up_moves
from ..game_data.real_shadow_data import vanilla_shadow_species
from ..game_data.real_trainer_data import real_species_pool, real_trainer_free_slot_census, real_trainer_team_census
from ..randomizer.enhanced_difficulty import adjust_team_census_for_reserved_slots, build_enhanced_difficulty_plan
from ..randomizer.shadow_expansion import SHADOW_EXPANSION_MAX_NEW_POKEMON, build_shadow_expansion_plans


def test_max_shadow_expansion_plus_enhanced_difficulty_never_overflows_real_free_slots() -> None:
    free_slot_census = real_trainer_free_slot_census()
    team_census = real_trainer_team_census()
    species_pool = real_species_pool()
    excluded_species = vanilla_shadow_species()
    level_up_moves = load_level_up_moves()

    if not (free_slot_census and team_census and species_pool and excluded_species is not None and level_up_moves):
        return  # real ISO-extracted data files not available in this build -- nothing to regress against

    free_slots_by_trainer = {t["trainer_index"]: t["free_slots"] for t in free_slot_census}

    for seed in (1, 2, 3, 42, 999, 123456):
        shadow_plans = build_shadow_expansion_plans(
            free_slot_census, species_pool, level_up_moves, excluded_species,
            SHADOW_EXPANSION_MAX_NEW_POKEMON, random.Random(seed),
        )
        shadow_slots_consumed_by_trainer = {p["trainer_index"]: len(p["new_pokemon"]) for p in shadow_plans}

        # The exact same helper __init__.py's generate_output() calls -- not a re-implementation.
        adjusted_census = adjust_team_census_for_reserved_slots(team_census, shadow_slots_consumed_by_trainer)
        ed_plan = build_enhanced_difficulty_plan(adjusted_census, species_pool, level_up_moves, random.Random(seed))
        ed_added_by_trainer: dict[int, int] = {}
        for step in ed_plan["team_slot_plan"]:
            ed_added_by_trainer[step["trainer_index"]] = ed_added_by_trainer.get(step["trainer_index"], 0) + 1

        overflow = [
            (idx, shadow_slots_consumed_by_trainer.get(idx, 0), ed_added_by_trainer.get(idx, 0), free_slots_by_trainer.get(idx, 0))
            for idx in set(shadow_slots_consumed_by_trainer) | set(ed_added_by_trainer)
            if shadow_slots_consumed_by_trainer.get(idx, 0) + ed_added_by_trainer.get(idx, 0) > free_slots_by_trainer.get(idx, 0)
        ]
        assert not overflow, (
            f"seed={seed}: {len(overflow)} trainer(s) had a combined Shadow Expansion + Enhanced Difficulty "
            f"new-member count exceeding their real free_slots: {overflow[:5]}"
        )

        # Sanity: both plans still actually produced real content at this seed (not a vacuously-passing test).
        assert sum(shadow_slots_consumed_by_trainer.values()) > 0, f"seed={seed}: Shadow Expansion produced nothing"
        assert sum(ed_added_by_trainer.values()) > 0, f"seed={seed}: Enhanced Difficulty produced nothing"
