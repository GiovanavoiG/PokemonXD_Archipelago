"""ADDENDUM 198 (second half) and ADDENDUM 199. Two ordering bugs, both found by asking the finished seed
the inverse-shaped question rather than asking the code.

ADDENDUM 198's two requirements only agree if they run in the right order:

  1. "with level scaling on, both vanilla and generated shadow pokemon get matched to the trainer team's
     average level and then scaled, as well as normal pokemon."
  2. "every randomized/padded/shadow pokemon will be evolved if it's at a level it could evolve at."

The species is chosen by the shuffle in `generate_early`; the level is chosen by Enhanced Difficulty. The
shuffle evolves each pick against `PokemonInstance.level`, and that field still held the VANILLA level -- so
requirement 1 raised the level AFTER requirement 2 had already used the old one. A Shadow fielded at 66 was
evolved as though it were still 17. Same thing one layer over for ordinary trainers, where the boost is
floor(level * 1.33): a Charmander shuffled in at 15 is fought at 19 and should be a Charmeleon.

ADDENDUM 199 came out of verifying the above. `build_shadow_expansion_plans` is handed the species it must
not reuse, so that no generated Shadow duplicates one sitting at a fixed, `shadow_species.py`-tracked Shadow
location. The call site passed `vanilla_shadow_species()` -- the 83 species the GAME ships -- which is the
wrong set the moment `randomize_shadow_species` is on, because those 83 slots now hold different species.
Measured on seed 4242: 16 of the 44 generated Shadows shared a species with a vanilla Shadow slot.

These tests pin the CONTRACT (ordinary_level_assignment agreeing with the plan builder; the exclusion set
being the post-shuffle one) rather than re-running generation, and a companion end-to-end check lives in the
project doc."""
from __future__ import annotations

import random
import unittest

from ..game_data.real_shadow_data import load_real_shadow_pool, vanilla_shadow_species
from ..game_data.real_trainer_data import (
    PERMANENTLY_EXCLUDED_TRAINER_INDICES,
    load_real_trainer_pools,
    real_shadow_census,
    real_species_pool,
    real_trainer_team_census,
)
from ..game_data.real_moveset_data import load_level_up_moves
from ..randomizer.enhanced_difficulty import (
    ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER,
    FILL_THE_TEAM,
    build_enhanced_difficulty_plan,
    ordinary_level_assignment,
    shadow_level_assignment,
)
from ..randomizer.shadow_expansion import build_shadow_expansion_plans
from ..randomizer.team_shuffle import (
    TeamShuffleOptions,
    resolve_natural_evolution,
    shuffle_teams,
)


class TestOrdinaryLevelAssignmentIsTheOneImplementation(unittest.TestCase):
    """The helper generate_early reads and the plan builder writes must be the same numbers."""

    def setUp(self) -> None:
        self.census = real_trainer_team_census()
        self.assertTrue(self.census, "real trainer census is required for this test")

    def _plan_levels(self, scale: bool) -> dict:
        plan = build_enhanced_difficulty_plan(
            self.census,
            real_species_pool(),
            load_level_up_moves() or {},
            random.Random(11),
            max_added_members=FILL_THE_TEAM,
            scale_levels=scale,
        )
        return plan["level_assignment"]

    def test_it_matches_the_plan_builder_exactly(self) -> None:
        self.assertEqual(self._plan_levels(True), ordinary_level_assignment(self.census, scale_levels=True))

    def test_scaling_off_relevels_nothing(self) -> None:
        self.assertEqual({}, ordinary_level_assignment(self.census, scale_levels=False))
        self.assertEqual({}, self._plan_levels(False))

    def test_permanently_excluded_trainers_get_no_entry(self) -> None:
        levels = ordinary_level_assignment(self.census, scale_levels=True)
        for trainer in self.census:
            if trainer["trainer_index"] in PERMANENTLY_EXCLUDED_TRAINER_INDICES:
                for dpkm_index in trainer["member_levels"]:
                    self.assertNotIn(dpkm_index, levels)

    def test_it_is_the_scaled_level_not_the_vanilla_one(self) -> None:
        levels = ordinary_level_assignment(self.census, scale_levels=True)
        import math
        for trainer in self.census:
            if trainer["trainer_index"] in PERMANENTLY_EXCLUDED_TRAINER_INDICES:
                continue
            for dpkm_index, level in trainer["member_levels"].items():
                self.assertEqual(
                    max(1, min(100, math.floor(level * ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER))),
                    levels[dpkm_index],
                )


class TestEverySlotIsEvolvedForTheLevelItIsFoughtAt(unittest.TestCase):
    """Replays what generate_early now does, then asks the inverse question of the result."""

    def setUp(self) -> None:
        self.pool = real_species_pool()

    def test_ordinary_slots_after_the_second_pass(self) -> None:
        census = load_real_trainer_pools()
        self.assertIsNotNone(census)
        species_pool, trainer_pools = census
        shuffle_teams(trainer_pools, species_pool, TeamShuffleOptions(legendary_safe=True), random.Random(3))
        levels = ordinary_level_assignment(real_trainer_team_census(), scale_levels=True)

        # Without the second pass this assertion fails -- measured on this exact shuffle, dozens of slots are
        # one stage short. Kept as a live measurement rather than a hardcoded count so the test says what it
        # means even if the species pool or the RNG stream changes.
        before = sum(
            1
            for pool in trainer_pools
            for trainer in pool.trainers
            for mon in trainer.team
            if mon.index in levels
            and resolve_natural_evolution(mon.species_id, levels[mon.index], species_pool) != mon.species_id
        )
        self.assertGreater(before, 0, "the shuffle should leave work for the second pass to find")

        for pool in trainer_pools:
            for trainer in pool.trainers:
                for mon in trainer.team:
                    level = levels.get(mon.index)
                    if level is None:
                        continue
                    mon.level = level
                    mon.species_id = resolve_natural_evolution(mon.species_id, level, species_pool)

        for pool in trainer_pools:
            for trainer in pool.trainers:
                for mon in trainer.team:
                    level = levels.get(mon.index)
                    if level is None:
                        continue
                    self.assertEqual(
                        mon.species_id, resolve_natural_evolution(mon.species_id, level, species_pool)
                    )

    def test_shadows_are_relevelled_before_the_shuffle_not_after(self) -> None:
        shadow_pool = load_real_shadow_pool()
        self.assertIsNotNone(shadow_pool)
        final_levels, _ = shadow_level_assignment(real_shadow_census(), scale_levels=True)

        raised = 0
        for trainer in shadow_pool.trainers:
            for mon in trainer.team:
                level = final_levels.get(mon.index)
                if level is None:
                    continue
                if level > mon.level:
                    raised += 1
                mon.level = level
        self.assertGreater(raised, 0, "matching to the team average should raise some Shadows")

        shuffle_teams([shadow_pool], real_species_pool(), TeamShuffleOptions(legendary_safe=False),
                      random.Random(5))

        for trainer in shadow_pool.trainers:
            for mon in trainer.team:
                self.assertEqual(
                    mon.species_id,
                    resolve_natural_evolution(mon.species_id, mon.level, self.pool),
                    f"{trainer.name} is not fully evolved for level {mon.level}",
                )

    def test_the_shadow_dedup_still_holds_after_relevelling(self) -> None:
        """Raising every level pushes many picks onto the same evolved forms -- the dedup has to survive it."""
        shadow_pool = load_real_shadow_pool()
        final_levels, _ = shadow_level_assignment(real_shadow_census(), scale_levels=True)
        for trainer in shadow_pool.trainers:
            for mon in trainer.team:
                mon.level = final_levels.get(mon.index, mon.level)
        shuffle_teams([shadow_pool], real_species_pool(), TeamShuffleOptions(legendary_safe=False),
                      random.Random(7))
        picked = [mon.species_id for trainer in shadow_pool.trainers for mon in trainer.team]
        self.assertEqual(len(picked), len(set(picked)))


class TestGeneratedShadowsAvoidThePostShuffleSpecies(unittest.TestCase):
    """ADDENDUM 199."""

    def setUp(self) -> None:
        from ..game_data.real_trainer_data import real_trainer_free_slot_census

        self.free_slots = real_trainer_free_slot_census()
        self.species_pool = real_species_pool()
        self.moves = load_level_up_moves()
        self.assertTrue(self.free_slots and self.species_pool and self.moves)

    def _post_shuffle_shadow_species(self, seed: int) -> set[int]:
        shadow_pool = load_real_shadow_pool()
        shuffle_teams([shadow_pool], real_species_pool(), TeamShuffleOptions(legendary_safe=False),
                      random.Random(seed))
        return {mon.species_id for trainer in shadow_pool.trainers for mon in trainer.team}

    def test_the_vanilla_set_is_not_the_set_in_play_once_shuffled(self) -> None:
        """The premise of the bug: the two sets genuinely disagree, so the choice of set matters."""
        self.assertNotEqual(vanilla_shadow_species(), self._post_shuffle_shadow_species(13))

    def test_excluding_the_union_leaves_no_duplicate_shadow_species(self) -> None:
        in_play = self._post_shuffle_shadow_species(13)
        plans = build_shadow_expansion_plans(
            self.free_slots,
            self.species_pool,
            self.moves,
            vanilla_shadow_species() | in_play,   # what the call site now passes
            44,
            random.Random(21),
        )
        generated = [mon["species"] for plan in plans for mon in plan["new_pokemon"]]
        self.assertEqual(44, len(generated))
        self.assertEqual(len(generated), len(set(generated)), "generated Shadows duplicate each other")
        self.assertEqual(set(), set(generated) & in_play, "a generated Shadow duplicates a vanilla one")
        self.assertEqual(set(), set(generated) & (vanilla_shadow_species() or set()))

    def test_excluding_only_the_vanilla_set_is_what_collided(self) -> None:
        """The bug itself, pinned: the old argument lets generated Shadows land on in-play species."""
        in_play = self._post_shuffle_shadow_species(13)
        plans = build_shadow_expansion_plans(
            self.free_slots,
            self.species_pool,
            self.moves,
            vanilla_shadow_species(),             # what the call site used to pass
            44,
            random.Random(21),
        )
        generated = {mon["species"] for plan in plans for mon in plan["new_pokemon"]}
        self.assertGreater(
            len(generated & in_play), 0,
            "if this stops colliding the regression this test guards has moved, not gone",
        )


if __name__ == "__main__":
    unittest.main()
