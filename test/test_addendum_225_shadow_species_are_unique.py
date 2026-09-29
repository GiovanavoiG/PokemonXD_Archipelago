"""ADDENDUM 225 (2026-09-15) -- every Shadow Pokemon is a distinct species, and that is now load-bearing.

Player: "For purifications, ensure that every shadow pokemon is unique so there's still enough checks."

WHY THIS MATTERS NOW. ADDENDUM 220 made `PurificationCountTracker` key on SPECIES, because that is the only
thing that makes a save-menu re-observation distinguishable from a real purification. The cost of that key is
that two Shadow Pokemon sharing a species would be counted once, and the purification ladder would run short.

THE ANSWER IS THAT IT ALREADY HOLDS, BY CONSTRUCTION -- measured, not assumed:

  * the 83 vanilla Shadow slots are 83 distinct species in the unmodified game;
  * `TeamShuffler._picked_shadow_species` keeps the reassignment one-to-one, so shuffling preserves it;
  * `build_shadow_expansion_plans` receives the union of the vanilla and post-shuffle species sets
    (ADDENDUM 199) and draws its 44 from what is left.

So no change was needed. What WAS needed is this file: an invariant that used to be incidental is now
depended on, and an incidental invariant with no test is one refactor away from quietly disappearing.
"""
import collections
import random
import unittest

from .. import ram_client as rc
from ..game_data import real_shadow_data as rsd, real_trainer_data as rtd
from ..game_data.real_moveset_data import load_level_up_moves
from ..randomizer import shadow_expansion
from ..randomizer.team_shuffle import TeamShuffleOptions, shuffle_teams

SEEDS = (1, 2, 3, 17, 99)


def _shadow_pool():
    pool = rsd.load_real_shadow_pool()
    if pool is None:
        raise unittest.SkipTest("no real ISO-extracted Shadow data in this build")
    return pool


class TestVanillaShadowsAreAlreadyDistinct(unittest.TestCase):
    def test_the_unmodified_game_has_no_duplicate_shadow_species(self):
        species = [mon.species_id for trainer in _shadow_pool().trainers for mon in trainer.team]
        duplicates = {s: n for s, n in collections.Counter(species).items() if n > 1}
        self.assertEqual(duplicates, {})
        self.assertEqual(len(species), 83)


class TestTheShuffleKeepsThemDistinct(unittest.TestCase):
    def test_reassignment_stays_one_to_one(self):
        for seed in SEEDS:
            pool = _shadow_pool()
            mons = [m for t in pool.trainers for m in t.team]
            shuffle_teams([pool], rtd.real_species_pool(),
                          TeamShuffleOptions(legendary_safe=False), random.Random(seed))
            species = [m.species_id for m in mons]
            self.assertEqual(len(set(species)), len(species), f"seed {seed}")


class TestGeneratedShadowsCollideWithNothing(unittest.TestCase):
    """Both option paths, because they pass DIFFERENT exclusion sets and only one of them was ever the bug
    (ADDENDUM 199's stale set)."""

    def setUp(self):
        self.learnsets = load_level_up_moves()
        if not self.learnsets:
            self.skipTest("no real ISO-extracted learnset data in this build")

    def _generate(self, excluded, seed):
        plans = shadow_expansion.build_shadow_expansion_plans(
            rtd.real_trainer_free_slot_census(), rtd.real_species_pool(),
            self.learnsets, excluded, 44, random.Random(seed),
        )
        return [mon["species"] for plan in plans for mon in plan["new_pokemon"]]

    def test_with_species_randomization_on(self):
        for seed in SEEDS:
            rng = random.Random(seed)
            pool = _shadow_pool()
            mons = [m for t in pool.trainers for m in t.team]
            shuffle_teams([pool], rtd.real_species_pool(),
                          TeamShuffleOptions(legendary_safe=False), rng)
            after = {m.species_id for m in mons}
            excluded = set(rsd.vanilla_shadow_species()) | after
            generated = self._generate(excluded, seed)
            self.assertEqual(len(set(generated)), len(generated), f"seed {seed}: generated duplicates")
            self.assertFalse(set(generated) & after, f"seed {seed}: generated collides with a vanilla slot")

    def test_with_species_randomization_off(self):
        for seed in SEEDS:
            vanilla = set(rsd.vanilla_shadow_species())
            generated = self._generate(vanilla, seed)
            self.assertEqual(len(set(generated)), len(generated), f"seed {seed}")
            self.assertFalse(set(generated) & vanilla, f"seed {seed}")


class TestThereAreEnoughDistinctSpeciesForTheLadder(unittest.TestCase):
    """The player's actual question: "so there's still enough checks"."""

    def setUp(self):
        self.learnsets = load_level_up_moves()
        if not self.learnsets:
            self.skipTest("no real ISO-extracted learnset data in this build")

    def test_a_maximal_seed_has_one_species_per_shadow_pokemon(self):
        for seed in SEEDS:
            rng = random.Random(seed)
            pool = _shadow_pool()
            mons = [m for t in pool.trainers for m in t.team]
            shuffle_teams([pool], rtd.real_species_pool(),
                          TeamShuffleOptions(legendary_safe=False), rng)
            after = {m.species_id for m in mons}
            plans = shadow_expansion.build_shadow_expansion_plans(
                rtd.real_trainer_free_slot_census(), rtd.real_species_pool(),
                self.learnsets, set(rsd.vanilla_shadow_species()) | after, 44, rng,
            )
            generated = [m["species"] for p in plans for m in p["new_pokemon"]]
            total = len(mons) + len(generated)
            distinct = len(after | set(generated))
            self.assertEqual(distinct, total,
                             f"seed {seed}: {total} Shadow Pokemon but only {distinct} distinct species -- "
                             f"the purification ledger would under-count by {total - distinct}")

    def test_even_the_vanilla_slots_alone_clear_the_ladder(self):
        """The floor, not the ceiling: a seed with no expansion at all still has far more distinct Shadow
        species than the ladder has rungs, so this cannot be the thing that runs short."""
        self.assertGreater(len(set(rsd.vanilla_shadow_species())), rc.PURIFICATION_LOCATION_COUNT)


class TestTheTrackerRecordsWhyItCanKeyOnSpecies(unittest.TestCase):
    def test_the_reasoning_is_written_down_next_to_the_code_that_depends_on_it(self):
        import inspect

        source = inspect.getsource(rc.PurificationCountTracker)
        self.assertIn("ADDENDUM 225", source)
        self.assertIn("distinct species", source)


if __name__ == "__main__":
    unittest.main()
