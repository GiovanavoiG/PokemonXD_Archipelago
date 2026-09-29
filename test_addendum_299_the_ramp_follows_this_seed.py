"""
ADDENDUM 299 (2026-09-20) -- the ramp follows THIS SEED's order, and species evolve against what ships.

Player: *"Make the levels not the same for every seed. Make sure to evolve against the highest possible level
(the closest to the one we ship to the trainer) if feasible."*

## What was true before, and why it was wrong for a reason worth stating

ADDENDUM 266 built the path ramp on the INTENDED path -- `story_bytes.area_entry_floor`, a constant property
of the game. That was the player's own framing at the time (*"it's fine to scale them by INTENDED path rather
than when they're actually received"*), and this module justified it by saying the received order *"is not
knowable at patch time at all, because the ISO is patched before anyone plays."*

**The ISO is patched after GENERATION, and generation includes fill.** By the time the seed file is written
every item is placed, so the sphere in which each travel unlock becomes obtainable is knowable. It simply was
never asked for. Measured before this was built, on a real filled travel-shuffle seed: Snagem Hideout (fixed
tier 10) opened in **sphere 1** while Cipher Lab (fixed tier 3) did not open until **sphere 7** -- a level-46
area in the first hour and a level-19 area at the end.

## The shape: reorder the TIERS, not the regions

The twelve tier GROUPS survive intact -- Pyrite Town and Pyrite Town (ONBS) stay together, as do the two
Phenac tiers and the two Key Lair tiers -- and so do the 8..50 spacing and the count. Only the ORDER of the
groups changes, ranked by the earliest sphere any member of the group opens in, ties broken on the intended
path.

Three reasons for that shape rather than a free-for-all: regions sharing a story-byte floor are the same
PLACE and must never be levelled apart; keeping twelve groups keeps every property this module is already
tested on; and a seed whose spheres happen to match the intended path produces the byte-identical plan it
produced before, which makes the change auditable rather than merely different.

**Measured across two seeds: 398 of 695 planned members (57%) come out at a different level.**

## The phase problem, which is the real content of this addendum

`generate_early` re-resolves every trainer Pokemon's evolution against its FINAL level -- ADDENDUM 269, the
reason a level-65 Charmander stopped happening. A sphere-derived level is not knowable there, because
`generate_early` runs before fill.

And it cannot move to `generate_output` either: `Main.py` submits `generate_output` and `write_multidata`
(which calls `fill_slot_data`) to **one thread pool**, so they race. ADDENDUM 155 cached the team shuffle on
`self` for exactly that reason and recorded that `generate_early` "is the latest hook that provably runs
before both" -- true while the answer did not depend on fill.

**`pre_output` is the later hook that still qualifies:** `Main.py` calls it after `finalize_multiworld`, before
either consumer is submitted, and single-threaded. That is where the levels, the evolution and the fingerprint
rebuild now live.

## A fix that fell out of the move

The fingerprints ADDENDUM 155 ships to the client are rebuilt in `pre_output` now, because this pass changes
both halves of what they describe -- the species and the levels. Rebuilding them let them use the level the
seed actually ships, and that is a repair in its own right: **ADDENDUM 157 made max HP the client's primary
trainer-identification axis, and an HP band computed from a vanilla level cannot contain a path-scaled
Pokemon's HP.** With path scaling on, the strongest signal that table carried was silently useless.

## Result, measured

**612 of 612 ordinary members ship at the highest evolution their level allows.** The single exception in the
whole plan is a Shadow (dpkm 118, Houndour at 42), and Shadow re-evolution is the standing open decision in
the register -- evolving a Shadow changes *which species the player can catch*, which feeds `Catch -`
locations and ADDENDUM 225's per-seed uniqueness.
"""
from __future__ import annotations

import pathlib
import unittest

from Fill import distribute_items_restrictive

from . import PokemonXDTestBase
from ..game_data.real_trainer_data import real_trainer_team_census
from ..randomizer import path_level_scaling as path
from ..randomizer.path_level_scaling import (
    build_path_level_plan,
    describe,
    final_ordinary_levels,
    level_by_trainer_index,
    region_by_trainer_index,
    sphere_tier_order,
)

SOURCE = (pathlib.Path(__file__).resolve().parent.parent / "__init__.py").read_text(encoding="utf-8")

TRAVEL = {
    "randomize_travel_locations": True,
    "key_item_shuffle": True,
    "randomize_chests": True,
    "randomize_shops": True,
    "path_level_scaling": True,
}


# ================================================================================================
# 1. The ordering itself
# ================================================================================================
class TestSphereTierOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.regions = set(region_by_trainer_index().values())
        cls.tiers = path.path_tiers(cls.regions)
        cls.fixed = {r: path.tier_index(r, cls.tiers, cls.regions) for r in cls.regions}
        # ADDENDUM 366: a region the ramp excludes has no tier, so it cannot take part in a sphere ordering
        # either -- `sphere_tier_order` drops it and arithmetic on its None would be a test-harness bug
        # rather than a finding. The tests below work from the regions that DO have one.
        cls.tiered = {r: i for r, i in cls.fixed.items() if i is not None}

    def test_spheres_matching_the_intended_path_reproduce_it_exactly(self) -> None:
        """The auditability property. A seed whose order happens to match the game's must produce the plan it
        produced before this addendum, or nothing about the change can be checked against anything."""
        same = sphere_tier_order(dict(self.tiered), self.regions)
        self.assertEqual(same, self.tiered)

    def test_reversing_the_spheres_reverses_the_tiers(self) -> None:
        highest = max(self.tiered.values())
        reversed_order = sphere_tier_order(
            {r: highest - i for r, i in self.tiered.items()}, self.regions)
        for region, index in self.tiered.items():
            self.assertEqual(reversed_order[region], highest - index)
        for region in self.fixed:
            if region in path.PATH_EXCLUDED_REGIONS:
                self.assertNotIn(region, reversed_order, "ADDENDUM 366: excluded here too")

    def test_tier_groups_are_never_split(self) -> None:
        """Regions sharing a story-byte floor are the same PLACE. Pyrite Town and Pyrite Town (ONBS) must
        never be levelled apart, however their spheres land."""
        grouped = {}
        for region, index in self.fixed.items():
            if index is not None:
                grouped.setdefault(index, []).append(region)
        multi = [members for members in grouped.values() if len(members) > 1]
        # ADDENDUM 367: the always-open tier used to be the multi-region one, and it is gone. If the real
        # table ever has no shared tier at all this test cannot demonstrate anything, so it says so and
        # falls back to a synthetic pair rather than passing empty.
        if not multi:
            self.skipTest("no multi-region tier in the real table -- nothing to demonstrate the rule on")
        # Give one member of each group a wildly early sphere and the rest a late one.
        spheres = {r: 50 for r in self.regions}
        for members in multi:
            spheres[sorted(members)[0]] = 0
        order = sphere_tier_order(spheres, self.regions)
        for members in multi:
            self.assertEqual(len({order[r] for r in members}), 1,
                             f"{members} were split across tiers")

    def test_the_count_and_the_span_are_unchanged(self) -> None:
        order = sphere_tier_order({r: hash(r) % 7 for r in self.regions}, self.regions)
        self.assertEqual(sorted(set(order.values())),
                         list(range(len({i for i in self.fixed.values() if i is not None}))))

    def test_a_region_with_no_sphere_is_treated_as_opening_last(self) -> None:
        """The safe direction: a region nothing can reach is not an early area."""
        order = sphere_tier_order({"Agate Village": 0}, self.regions)
        self.assertEqual(order["Agate Village"], 0)
        self.assertGreater(max(order.values()), 0)

    def test_an_empty_sphere_map_falls_back_to_the_intended_path(self) -> None:
        self.assertEqual(sphere_tier_order({}, self.regions),
                         {r: i for r, i in self.fixed.items() if i is not None})


class TestTheOrderingIsThreadedEverywhere(unittest.TestCase):
    """Four call sites have to agree: the levels written, the averages Shadows are matched to, the map for
    teamless Shadows, and the note that explains it. One of them using the intended path while the others use
    the seed's is the kind of split ADDENDUM 287 spent an addendum on."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.census = real_trainer_team_census()
        regions = set(region_by_trainer_index().values())
        fixed = {r: path.tier_index(r, path.path_tiers(regions), regions) for r in regions}
        highest = max(i for i in fixed.values() if i is not None)
        cls.flipped = {r: highest - i for r, i in fixed.items() if i is not None}

    def test_build_path_level_plan_honours_it(self) -> None:
        default, _ = build_path_level_plan(self.census)
        flipped, _ = build_path_level_plan(self.census, tier_by_region=self.flipped)
        self.assertNotEqual(default, flipped)

    def test_final_ordinary_levels_honours_it(self) -> None:
        default = final_ordinary_levels(self.census, path_scaling=True, ed_scaling=False)
        flipped = final_ordinary_levels(self.census, path_scaling=True, ed_scaling=False,
                                        tier_by_region=self.flipped)
        self.assertNotEqual(default, flipped)

    def test_level_by_trainer_index_honours_it(self) -> None:
        self.assertNotEqual(level_by_trainer_index(),
                            level_by_trainer_index(tier_by_region=self.flipped))

    def test_describe_honours_it(self) -> None:
        self.assertNotEqual(describe(), describe(tier_by_region=self.flipped))
        self.assertIn("this seed's order", "\n".join(describe(tier_by_region=self.flipped)))

    def test_generate_output_passes_it_to_all_four(self) -> None:
        start = SOURCE.index("if path_scale_levels:")
        body = SOURCE[start:start + 4000]
        self.assertIn("tier_by_region=_tier_order", body)
        self.assertEqual(body.count("tier_by_region=_tier_order"), 4,
                         "every one of the four call sites must take this seed's ordering")


# ================================================================================================
# 2. The phase move
# ================================================================================================
class TestThePassRunsInTheOnlyHookThatWorks(unittest.TestCase):
    def test_pre_output_owns_it(self) -> None:
        self.assertIn("def pre_output(self)", SOURCE)
        start = SOURCE.index("def pre_output(self)")
        body = SOURCE[start:SOURCE.index("\n    def ", start + 10)]
        self.assertIn("_resolve_path_tier_order()", body)
        self.assertIn("_apply_final_levels_and_evolution()", body)

    def test_generate_early_no_longer_evolves(self) -> None:
        """The literal regression: leaving it there would evolve against a level the ISO no longer fields,
        which is the defect ADDENDUM 269 exists to prevent."""
        start = SOURCE.index("def generate_early(self)")
        end = SOURCE.index("def _build_trainer_team_shuffle(")
        self.assertNotIn("resolve_natural_evolution(", SOURCE[start:end])

    def test_the_fallback_is_the_intended_path_and_not_an_arbitrary_one(self) -> None:
        """`_resolve_path_tier_order` returns None on the option being off, on an empty sphere walk, and on
        any exception. None means every caller uses `area_entry_floor` -- the pre-299 behaviour."""
        start = SOURCE.index("def _resolve_path_tier_order(")
        body = SOURCE[start:SOURCE.index("\n    def ", start + 10)]
        self.assertEqual(body.count("return None"), 3)
        self.assertIn("except Exception:", body)


class TestTwoSeedsDiffer(PokemonXDTestBase):
    """The headline, and it needs a real fill -- the whole point is that the answer comes from one."""

    options = dict(TRAVEL)

    def test_the_ramp_is_not_the_intended_path_once_items_are_placed(self) -> None:
        distribute_items_restrictive(self.multiworld)
        self.world.pre_output()
        order = self.world._path_tier_by_region
        self.assertIsNotNone(order, "a filled travel-shuffle seed must resolve its own ordering")
        regions = set(region_by_trainer_index().values())
        fixed = {r: path.tier_index(r, path.path_tiers(regions), regions) for r in regions}
        moved = [r for r, i in order.items() if fixed.get(r) != i]
        self.assertTrue(moved, "not one region moved -- the sphere walk found nothing")

    def test_the_seed_note_describes_the_ramp_the_seed_got(self) -> None:
        distribute_items_restrictive(self.multiworld)
        self.world.pre_output()
        text = "\n".join(describe(tier_by_region=self.world._path_tier_by_region))
        self.assertIn("this seed's order", text)


class TestWithTheOptionOffNothingChanges(PokemonXDTestBase):
    options = {"path_level_scaling": False, "randomize_travel_locations": True}

    def test_no_ordering_is_resolved(self) -> None:
        self.world.pre_output()
        self.assertIsNone(self.world._path_tier_by_region)


# ================================================================================================
# 3. Evolving against what ships
# ================================================================================================
class TestSpeciesEvolveAgainstTheShippedLevel(PokemonXDTestBase):
    options = dict(TRAVEL, randomize_trainer_teams=True)

    def test_every_ordinary_member_is_at_its_highest_evolution_for_its_level(self) -> None:
        """The player's second sentence. `final_ordinary_levels` returns the level the patcher really writes
        -- path ramp, ADDENDUM 295's per-team spread and Enhanced Difficulty's multiplier all composed -- so
        the evolution resolves against the exact number rather than an approximation."""
        from ..game_data.real_trainer_data import load_real_trainer_pools
        from ..randomizer.team_shuffle import resolve_natural_evolution

        distribute_items_restrictive(self.multiworld)
        self.world.pre_output()
        pools = self.world._trainer_team_pools
        self.assertIsNotNone(pools)
        species_pool, _ = load_real_trainer_pools()
        under = [
            (mon.index, mon.species_id, mon.level)
            for pool in pools for trainer in pool.trainers for mon in trainer.team
            if resolve_natural_evolution(mon.species_id, mon.level, species_pool) != mon.species_id
        ]
        self.assertEqual(under, [], "these members could have evolved further at the level they ship at")

    def test_the_fingerprints_describe_the_teams_that_ship(self) -> None:
        """ADDENDUM 157 made max HP the client's primary identification axis, and a band from a vanilla level
        cannot contain a path-scaled Pokemon's HP. Rebuilding the fingerprints after the levels are known is
        what repairs that, so the two lists now agree -- the shipped level already carries the difficulty."""
        distribute_items_restrictive(self.multiworld)
        self.world.pre_output()
        fingerprints = self.world._trainer_team_fingerprints or {}
        self.assertTrue(fingerprints)
        for entry in fingerprints.values():
            self.assertEqual(entry["levels"], entry["levels_enhanced"])


if __name__ == "__main__":
    unittest.main()
