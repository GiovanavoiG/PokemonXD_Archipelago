"""ADDENDUM 266 (2026-09-17): trainer levels that follow the INTENDED path.

Player: "please investigate scaling level for location shuffle - first area unlocked has level 10s, second has
20s, etc - it's fine to scale them by INTENDED path rather than when they're actually received."

That concession is what makes the feature buildable. With travel randomization on, the order a player ACTUALLY
reaches areas in is decided by the multiworld and is not knowable at patch time -- the ISO is patched before
anyone plays -- so scaling by it would mean rewriting levels live from the client. The intended path is a
property of the GAME, fixed for every seed, and bakes straight into the ISO.

## The path is derived, not written down

`story_bytes.area_entry_floor(region)` is the byte at which the unmodified game first lets you into a region.
Sorting the regions trainers live in by that value IS the intended path, in the game's own terms. Twelve
distinct tiers fall out:

    always-open -> 0x19 -> 0x24 -> 0x26 -> 0x30 -> 0x35 -> 0x3E -> 0x4E -> 0x5D -> 0x5F -> 0x62 -> 0x6E

Writing that ordering by hand would have been a thirteenth table describing something three existing tables
already know -- the exact failure this project keeps finding (ADDENDA 185/211/241/242/254 and the standing
"what else is described in two places" sweep).

## The curve

The player chose the vanilla range: 10 at the first tier, 65 at the last, spread evenly. It lands on clean
fives (10, 15, 20 ... 65) by arithmetic rather than by being typed that way, which is worth a test of its own.

The literal "+10 per tier" reading overshoots -- twelve tiers reaches 120 and the last three areas flatten
against the cap, taking the differentiation out of exactly the stretch where it matters most.

## Mt. Battle is one region and a hundred trainers

Included at the player's request, and it cannot take a single band without erasing the 1-to-100 gauntlet that
is the whole point of the place. It keeps its own ramp and takes the path only as a STARTING POINT.
"""
from __future__ import annotations

import unittest

from ..game_data import story_bytes, trainer_placements
from ..randomizer import path_level_scaling as path


class TestThePathIsDerivedFromTheStoryFloors(unittest.TestCase):

    def test_the_tiers_are_the_distinct_entry_floors_in_order(self) -> None:
        regions = {p.region for p in trainer_placements.PLACEMENTS.values() if p.region}
        tiers = path.path_tiers(regions)
        real = [t for t in tiers if t is not None]
        self.assertEqual(sorted(real), real, "the path must be in ascending story order")
        self.assertEqual(len(set(tiers)), len(tiers), "a floor may appear once")
        # ADDENDUM 279: compared against this module's OWN notion of a floor, not `area_entry_floor`. The
        # three always-open regions gained first-visit bytes (0x01/0x03/0x0F) for the story-byte subsystem,
        # and `path_tiers` deliberately collapses them back to one opening tier -- see its docstring for why
        # letting that leak here would have re-levelled every trainer in a path-scaled seed.
        # ADDENDUM 367: compared over the regions the ramp actually PLACES. All three always-open regions
        # are excluded now, so their None floor is no longer among the tiers -- which is the change, not a
        # drift between the two notions of a floor that this line exists to catch.
        placed = {r for r in regions if r not in path.PATH_EXCLUDED_REGIONS}
        self.assertEqual({path._path_floor(r) for r in placed}, set(tiers))

    def test_the_always_open_regions_sort_first(self) -> None:
        """"The game lets you in immediately" is a position on the path, not missing data -- dropping it would
        leave the opening areas with no tier at all.

        RETARGETED 2026-09-26 (ADDENDUM 367). All three always-open regions are off the ramp, so the real
        placement data no longer produces this tier at all. The COLLAPSE is still the module's rule and
        `path_tiers` is a total function over any region set, so it is exercised on an explicit set -- which
        is what this test was always about -- and the live absence is asserted separately."""
        explicit = {"Pokemon HQ Lab", "Gateon Port", "Agate Village"}
        tiers = path.path_tiers(explicit | path.PATH_EXCLUDED_REGIONS)
        self.assertEqual(tiers, path.path_tiers({"Agate Village"}),
                         "every always-open region is excluded, so none of them contributes a tier")

        # The collapse itself, on a set the exclusion does not touch: three regions, one leading tier.
        from unittest import mock
        with mock.patch.object(path, "PATH_EXCLUDED_REGIONS", frozenset()):
            collapsed = path.path_tiers({"Pokemon HQ Lab", "Gateon Port", "Kaminko's House", "Agate Village"})
            self.assertIsNone(collapsed[0])
            self.assertEqual(len(collapsed), 2, "three always-open regions are ONE opening tier")
            for region in ("Pokemon HQ Lab", "Gateon Port", "Kaminko's House"):
                self.assertEqual(0, path.tier_index(region, collapsed), region)

        # And each is still always-open -- excluded from the ramp, not re-floored.
        for region in path.PATH_EXCLUDED_REGIONS:
            self.assertIsNone(path._path_floor(region), region)

    def test_regions_that_share_a_floor_share_a_tier(self) -> None:
        """RETARGETED BY ADDENDUM 329 (2026-09-23), and the retarget is the point of that addendum.

        This test used to name three PAIRS -- Pyrite Town and its ONBS wing, Phenac and Post-Sixes, the Key
        Lair and its exterior -- and assert each pair shared a tier, on the reasoning that they are "the same
        moment in the story". They are not. Their story floors differ (0x30/0x3C, 0x3E/0x46, 0x5D/0x64), and
        the only reason they came out equal was that `_path_floor` asked `area_entry_floor`, which hands every
        region of an `AREA_GROUPS` place its place's first number. So the test was asserting the collapse that
        put a level-40 Biden in a level-15 Snagem Hideout rather than the rule it was named after.

        The rule itself survives untouched, and is now asserted as a rule: regions that share a floor share a
        tier, and regions that do not, do not. Written over every trainer region rather than three hand-picked
        pairs, so it keeps holding when a floor moves.

        RE-EXPRESSED BY ADDENDUM 368 (2026-09-26), and deliberately not weakened. The floor the ramp reads is
        `_path_floor`, which is `region_floor` for every region except the ones ADDENDUM 368 merges onto
        another region's floor on the player's ruling ("Key lair interior and exterior should be the same
        place"). Asking `_path_floor` keeps this an iff over the whole region set rather than an iff with a
        hand-waved exception, and `test_the_merge_is_the_only_gap_between_the_two_floors` below pins that the
        two functions differ nowhere else -- so a future merge cannot quietly widen the gap this test allows."""
        regions = {p.region for p in trainer_placements.PLACEMENTS.values() if p.region}
        tiers = path.path_tiers(regions)
        for a in sorted(regions):
            for b in sorted(regions):
                same_floor = path._path_floor(a) == path._path_floor(b)
                same_tier = path.tier_index(a, tiers, regions) == path.tier_index(b, tiers, regions)
                self.assertEqual(same_floor, same_tier, f"{a} vs {b}")

    def test_the_merge_is_the_only_gap_between_the_two_floors(self) -> None:
        """ADDENDUM 368. `_path_floor` answers "where does the ramp put this region" and `story_bytes
        .region_floor` answers "where does the story put it". They agreed exactly until the Key Lair merge, and
        this pins that the merge table is the ONLY place they still disagree -- which is what makes the test
        above safe to write against `_path_floor`."""
        from ..game_data import story_bytes

        regions = {p.region for p in trainer_placements.PLACEMENTS.values() if p.region}
        differ = {name for name in regions
                  if name not in story_bytes.ALWAYS_OPEN_REGIONS
                  and path._path_floor(name) != story_bytes.region_floor(name)}
        self.assertEqual(differ, set(path.PATH_FLOOR_MERGES) & regions)
        self.assertTrue(differ, "the merge table no longer moves any placed region")

    def test_citadark_is_last_and_agate_is_early(self) -> None:
        regions = {p.region for p in trainer_placements.PLACEMENTS.values() if p.region}
        tiers = path.path_tiers(regions)
        self.assertEqual(len(tiers) - 1, path.tier_index("Citadark Isle", tiers))
        # ADDENDUM 367: Agate is tier 0 now -- the opening tier it used to sit behind is gone.
        self.assertEqual(0, path.tier_index("Agate Village", tiers))

    def test_an_unknown_region_has_no_position(self) -> None:
        """The 37 region-less rows keep their vanilla levels. Forcing them to an end would be guessing where
        they sit on the path -- the same guess `trainer_placements` refuses to make for logic."""
        regions = {p.region for p in trainer_placements.PLACEMENTS.values() if p.region}
        tiers = path.path_tiers(regions)
        self.assertIsNone(path.tier_index(None, tiers))
        # CAUGHT BY THIS TEST BEFORE IT SHIPPED: without the known-region set, an unrecognised name's None
        # floor found the ALWAYS-OPEN tier via `list.index(None)` and came back as tier 0 -- so a typo'd or
        # newly-added region would have silently fielded level-10 teams as though it were the HQ Lab. It
        # cannot bite through the module's own callers, which is exactly why it would have gone unnoticed.
        self.assertIsNone(path.tier_index("Somewhere That Does Not Exist", tiers, regions))
        # ADDENDUM 367: the always-open regions are all excluded, so the guard is demonstrated on the real
        # first tier instead. The point is unchanged -- a KNOWN region answers, an unknown one does not.
        self.assertEqual(0, path.tier_index("Agate Village", tiers, regions),
                         "a genuinely known region must still answer its tier")


class TestTheCurve(unittest.TestCase):

    def test_it_runs_from_the_first_endpoint_to_the_last(self) -> None:
        n = 12
        self.assertEqual(path.FIRST_TIER_LEVEL, path.level_for_tier(0, n))
        self.assertEqual(path.LAST_TIER_LEVEL, path.level_for_tier(n - 1, n))

    def test_it_rises_monotonically(self) -> None:
        n = 12
        levels = [path.level_for_tier(i, n) for i in range(n)]
        self.assertEqual(sorted(levels), levels)
        self.assertEqual(len(set(levels)), n, "every tier must be distinguishable from its neighbours")

    def test_the_real_ramp_is_even_between_its_endpoints(self) -> None:
        """REWRITTEN by ADDENDUM 296, and the rewrite is the lesson.

        This used to assert the literal list `[10, 15, 20, ..., 65]` -- the clean fives that fell out of
        10..65 over twelve tiers. That was pinned on the reasoning that a reader seeing those numbers would
        assume they were hand-written, so a future endpoint change should be a visible decision rather than a
        surprise. It was visible, and it was a decision (8..50), and the test then had to be edited to say a
        second set of numbers that are just as much a coincidence of the endpoints.

        So it asserts the PROPERTY instead: the ramp starts at the first endpoint, ends at the last, climbs
        strictly, and its steps differ by at most one level. That is everything "an even ramp" means, it
        survives any endpoint change, and it still fails loudly if the spacing ever stops being even."""
        regions = {p.region for p in trainer_placements.PLACEMENTS.values() if p.region}
        n = len(path.path_tiers(regions))
        levels = [path.level_for_tier(i, n) for i in range(n)]
        self.assertEqual(path.FIRST_TIER_LEVEL, levels[0])
        self.assertEqual(path.LAST_TIER_LEVEL, levels[-1])
        self.assertEqual(sorted(levels), levels)
        steps = [b - a for a, b in zip(levels, levels[1:])]
        self.assertLessEqual(max(steps) - min(steps), 1,
                             f"the ramp is not evenly spaced: {levels}")

    def test_a_single_tier_does_not_divide_by_zero(self) -> None:
        self.assertEqual(path.FIRST_TIER_LEVEL, path.level_for_tier(0, 1))

    def test_every_level_is_inside_the_games_own_range(self) -> None:
        for n in (2, 5, 12, 40):
            for i in range(n):
                level = path.level_for_tier(i, n)
                self.assertGreaterEqual(level, path.MIN_LEVEL)
                self.assertLessEqual(level, path.MAX_LEVEL)


class TestThePlan(unittest.TestCase):

    # RETARGETED 2026-09-26 (ADDENDUM 367). Trainers 8 and 9 were chosen as "always-open, therefore the
    # first tier"; all three always-open regions are off the ramp now, so they would be absent from the plan
    # and every assertion below would pass vacuously. Replaced with trainers in the region that IS the first
    # tier now, Agate Village -- 20 is Eagun, 19 and 23 its neighbours -- so "first tier" still means what
    # these tests say it means.
    CENSUS = [
        {"trainer_index": 20, "member_levels": {100: 5, 101: 6}},       # Agate Village -- the first tier
        {"trainer_index": 19, "member_levels": {102: 7}},               # Agate Village
        {"trainer_index": 2, "member_levels": {103: 30}},               # Poke Spots
        {"trainer_index": 1, "member_levels": {104: 42}},               # Hordel -- region None
    ]

    def test_a_trainer_in_a_known_region_takes_its_tier_s_level(self) -> None:
        """REVISED by ADDENDUM 295, and the revision is the whole of that addendum.

        This used to assert that every member of the first tier's team was exactly `FIRST_TIER_LEVEL` -- true,
        because the tier's level was written to every member. A tier is now where the team's AVERAGE lands,
        with each member keeping its distance from its own vanilla average, so 5/6 arrives as 10/11 rather
        than 10/10. What the tier means for a team is unchanged; what it means for one Pokemon is not.

        A one-member team is still exactly the tier by construction (dpkm 102), which is what keeps the
        single-member half of this assertion meaningful rather than merely loosened."""
        levels, averages = path.build_path_level_plan(self.CENSUS)
        self.assertEqual(path.FIRST_TIER_LEVEL, levels[102], "a lone member has no offset to keep")
        self.assertEqual(levels[101] - levels[100], 1, "vanilla 5/6 keeps its one-level gap")
        # ADDENDUM 367: trainer 20, not 8 -- the census moved to Agate Village when the always-open regions
        # came off the ramp. See the CENSUS comment.
        self.assertAlmostEqual(averages[20], sum((levels[100], levels[101])) / 2)
        self.assertLessEqual(abs(averages[20] - path.FIRST_TIER_LEVEL), 1.0,
                             "the team's average must still sit on its tier")
        self.assertGreater(levels[103], levels[100], "Poke Spots comes well after Agate Village")
        self.assertEqual(float(levels[103]), averages[2], "a one-member team's average IS its level")

    def test_a_trainer_with_no_known_region_is_absent_entirely(self) -> None:
        """Absent, not zeroed. The patcher only writes the dpkm indices it is handed, so absence IS the
        "keep vanilla levels" instruction -- there is no separate mechanism to get wrong."""
        levels, averages = path.build_path_level_plan(self.CENSUS)
        self.assertNotIn(104, levels)
        self.assertNotIn(1, averages)

    def test_the_new_team_averages_come_back_for_the_shadows(self) -> None:
        """Not a diagnostic. `shadow_level_assignment` matches a Shadow to its trainer's TEAM AVERAGE, so
        re-levelling the ordinary members without handing back the new average leaves a Shadow sitting at the
        old team's level on a team that has moved."""
        _levels, averages = path.build_path_level_plan(self.CENSUS)
        self.assertEqual({20, 19, 2}, set(averages))   # ADDENDUM 367: Agate, not the always-open pair

    def test_every_trainer_with_a_region_gets_a_level_even_with_no_team(self) -> None:
        """Nine trainers carry a Shadow and no ordinary member at all, so they never appear in the team
        census. Found by reading a generated seed and spotting 11, 17, 46 and 57 among the ramp's clean
        fives."""
        by_trainer = path.level_by_trainer_index()
        census_indices = {row["trainer_index"] for row in self.CENSUS}
        self.assertTrue(set(by_trainer) - census_indices)
        # ADDENDUM 298: back to every placed trainer, ADDENDUM 297's exclusion having been reversed.
        # ADDENDUM 366: minus the trainers in a region the ramp has no opinion about.
        placed = {i for i, p in trainer_placements.PLACEMENTS.items()
                  if p.region is not None and p.region not in path.PATH_EXCLUDED_REGIONS}
        self.assertEqual(placed, set(by_trainer))
        excluded = {i for i, p in trainer_placements.PLACEMENTS.items()
                    if p.region in path.PATH_EXCLUDED_REGIONS}
        self.assertTrue(excluded, "the exclusion must actually remove trainers or it says nothing")
        self.assertFalse(excluded & set(by_trainer))


class TestMtBattleKeepsItsGauntlet(unittest.TestCase):

    CENSUS = [{"trainer_index": i, "member_levels": {1000 + i: 20}} for i in range(1, 101)]

    def test_it_starts_at_its_place_on_the_path_and_climbs_to_the_top(self) -> None:
        levels, averages = path.build_mt_battle_path_level_plan(self.CENSUS)
        regions = {p.region for p in trainer_placements.PLACEMENTS.values() if p.region}
        tiers = path.path_tiers(regions)
        anchor = path.level_for_tier(path.tier_index("Mt. Battle", tiers), len(tiers))
        self.assertEqual(anchor, averages[1])
        self.assertEqual(path.LAST_TIER_LEVEL, averages[100])

    def test_it_is_not_flattened_into_one_band(self) -> None:
        """The whole reason Mt. Battle needed its own path. One region at one tier would put all 100 trainers
        at the same level and erase the gauntlet."""
        levels, _ = path.build_mt_battle_path_level_plan(self.CENSUS)
        self.assertGreater(len(set(levels.values())), 10)

    def test_it_rises_with_the_trainer_index(self) -> None:
        _levels, averages = path.build_mt_battle_path_level_plan(self.CENSUS)
        ordered = [averages[i] for i in range(1, 101)]
        self.assertEqual(sorted(ordered), ordered)

    def test_an_empty_census_is_not_a_crash(self) -> None:
        self.assertEqual(({}, {}), path.build_mt_battle_path_level_plan([]))


class TestTheSeedWiring(unittest.TestCase):
    """Structural. The composition order is the part worth pinning: the option text promises path scaling sets
    the base level and Enhanced Difficulty's multiplier scales it, and two writers of one dict is how that
    promise gets broken quietly."""

    @classmethod
    def setUpClass(cls) -> None:
        import pathlib
        cls.source = (pathlib.Path(__file__).resolve().parent.parent / "__init__.py").read_text(encoding="utf-8")

    def test_path_levels_override_rather_than_merge_under(self) -> None:
        self.assertIn('enhanced_difficulty_plan["level_assignment"].update(path_levels)', self.source)
        override = self.source.index('enhanced_difficulty_plan["level_assignment"].update(path_levels)')
        built = self.source.index("enhanced_difficulty_plan = build_enhanced_difficulty_plan(")
        self.assertLess(built, override, "path scaling must be applied over ED's plan, not before it")

    def test_the_multiplier_is_applied_once(self) -> None:
        """Both options on must not scale twice. The shadow pass explicitly stands down when path scaling has
        already done it."""
        self.assertIn("scale_levels=ed_scale_levels and not path_scale_levels", self.source)

    def test_the_block_runs_when_only_path_scaling_is_on(self) -> None:
        self.assertIn("if ed_added_members != 0 or ed_scale_levels or path_scale_levels:", self.source)

    def test_the_ramp_is_recorded_in_the_seed_notes(self) -> None:
        """ADDENDUM 299: the note now describes THIS SEED's ordering, so the call carries it. A note built
        from the intended path beside an ISO built from a different order would be worse than no note."""
        self.assertIn("describe_path_ramp(tier_by_region=", self.source)


if __name__ == "__main__":
    unittest.main()


class TestAddendum281ThePinnedTutorialFight(unittest.TestCase):
    """Player: *"Make sure chobin 1's pokemon is always level 5 - level path scaling is making him level 10."*

    Chobin #1 is `trainer_index` 15, one Sunkern, level 5 in the real deck data. He lives in Kaminko's House,
    an always-open region and therefore tier 0 -- and tier 0 is `FIRST_TIER_LEVEL`, 10. So the ramp doubled
    the first fight in the game.

    A pin rather than a tier change, because the ramp is not wrong: the opening tier covers the lab, Kaminko's
    and Gateon, and 10 is right for those areas in a shuffled seed. Chobin #1 is the exception because he is
    the tutorial, fought before the player has anything."""

    CENSUS = [
        {"trainer_index": 15, "member_levels": {25: 5}},     # Chobin #1 -- pinned
        {"trainer_index": 18, "member_levels": {29: 6, 30: 6}},  # Chobin #2 -- same region, NOT pinned
    ]

    def test_chobin_one_is_pinned_to_five(self) -> None:
        levels, _averages = path.build_path_level_plan(self.CENSUS)
        self.assertEqual(5, levels[25])

    def test_the_pin_is_the_level_the_real_deck_data_holds(self) -> None:
        """Asserted against the shipped census rather than against the literal, so the pin and the game agree
        today -- and a future re-dump that moves him shows up here as a decision to make."""
        import json
        import pathlib

        census = json.loads((pathlib.Path(__file__).resolve().parent.parent
                             / "data" / "deckdata_story_trainers.json").read_text(encoding="utf-8"))
        row = next(r for r in census if r["index"] == 15)
        vanilla = [m["level"] for m in row["team"] if "dpkm_index" in m]
        self.assertEqual([5], vanilla)
        self.assertEqual(5, path.PINNED_TRAINER_LEVELS[15])

    def test_his_neighbour_in_the_same_region_keeps_its_deck_levels(self) -> None:
        """RETARGETED 2026-09-26 (ADDENDUM 366). This used to assert that Chobin #2 was scaled to the opening
        tier while #1 was pinned -- "the pin must be one trainer, not the whole opening tier". Kaminko's House
        is off the ramp now, so the neighbour is not scaled to anything: it keeps what the deck says.

        The original claim survives in a stronger form. The pin is still ONE trainer -- #1 is in the plan at 5
        and #2 is absent from it entirely, which is what "the ramp has no opinion" looks like downstream."""
        levels, averages = path.build_path_level_plan(self.CENSUS)
        self.assertEqual(5, levels[25])
        self.assertNotIn(29, levels)
        self.assertNotIn(30, levels)
        self.assertNotIn(18, averages)

    def test_the_team_average_follows_the_pin(self) -> None:
        """Not cosmetic. `enhanced_difficulty.shadow_level_assignment` matches Shadows to this average, so a
        tier-level average on a pinned team is the two disagreeing -- the failure `build_path_level_plan`'s
        own docstring exists to prevent. Chobin #1 has no Shadow; a future pin might."""
        _levels, averages = path.build_path_level_plan(self.CENSUS)
        self.assertEqual(5.0, averages[15])

    def test_a_pin_survives_a_change_to_the_endpoints(self) -> None:
        """A pin is a literal and owes nothing to the ramp's endpoints -- which is the whole reason ADDENDUM
        281 chose a pin over an exemption. Demonstrated on a trainer the ramp still places, since ADDENDUM 366
        took Chobin's neighbour off it."""
        levels, _averages = path.build_path_level_plan(self.CENSUS, first=30, last=90)
        self.assertEqual(5, levels[25])
        moved, _ = path.build_path_level_plan(
            [{"trainer_index": 1, "member_levels": {900: 20}}],
            regions_by_trainer={1: "Agate Village"}, first=30, last=90,   # ADDENDUM 367: on the ramp
        )
        self.assertEqual(30, moved[900], "an unpinned trainer still moves with the ramp")
