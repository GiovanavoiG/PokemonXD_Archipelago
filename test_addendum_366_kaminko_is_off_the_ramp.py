"""ADDENDUM 366 (2026-09-26): Kaminko's House is off the path-scaling ramp.

Player: *"Since we do not scale the first chobin fight, don't include kaminko in the path scaling design."*

WHAT THE RAMP WAS ACTUALLY DOING, measured before anything changed. All SEVEN Chobin fights are placed in
`Kaminko's House`, which is always-open and therefore tier 0, so every one of them was levelled to
`FIRST_TIER_LEVEL`. Their vanilla levels are 5, 6, 26, 26, 26, 37, 38 -- so path scaling was quietly dropping
the last five to 8, and ADDENDUM 281's pin only ever covered the first.

THE REGION IS THE PROBLEM, NOT THE NUMBERS. A tier is a claim about WHEN a fight happens, derived from where
it is. That derivation holds everywhere else in this game and cannot hold in Kaminko's House: the manor is
open from the first hour and Chobin is fought in it across the whole story. Tier 0 was not mis-ordered; it was
answering a question the region cannot answer.

TWO THINGS THIS HAD TO NOT BREAK, and both are pinned below:

  * THE TIER COUNT. `Pokemon HQ Lab` and `Gateon Port` are also always-open, so tier 0 survives without
    Kaminko's and the ramp stays fifteen tiers. If it had shrunk, every other trainer in the game would have
    moved a level or two as a side effect of a change about Chobin.

  * ADDENDUM 281'S PIN. `build_path_level_plan` read the pin AFTER its no-tier skip, so the exclusion would
    have made "always level 5" unreachable the moment it landed -- the dead-rule shape this project refuses.
    The lookup moved above the skip. An exclusion says the RAMP has no opinion about this region; a pin says
    this fight is exactly this level. They are only in tension if the skip is read before the pin.
"""
from __future__ import annotations

import unittest

from ..game_data import real_trainer_data, story_bytes, trainer_placements, trainer_roster
from ..randomizer import path_level_scaling as pls

KAMINKO = "Kaminko's House"


def _regions() -> "dict[int, str]":
    return {index: trainer_placements.region_for(index) for index in trainer_roster.TRAINERS_BY_INDEX}


def _chobin_indices() -> "list[int]":
    return sorted(i for i, row in trainer_roster.TRAINERS_BY_INDEX.items() if row["name"] == "CHOBIN")


class TestTheMeasurementThisRestsOn(unittest.TestCase):
    def test_every_chobin_fight_is_in_kaminkos_house(self) -> None:
        """If one ever moves, this exclusion stops covering it and the reasoning above has to be re-read."""
        regions = _regions()
        indices = _chobin_indices()
        self.assertEqual(len(indices), 7)
        for index in indices:
            self.assertEqual(regions[index], KAMINKO, index)

    def test_the_manor_is_always_open_which_is_why_it_could_not_be_tiered(self) -> None:
        self.assertIn(KAMINKO, story_bytes.ALWAYS_OPEN_REGIONS)

    def test_their_vanilla_levels_span_most_of_the_game(self) -> None:
        """The whole point. A single tier cannot describe 5 through 38."""
        levels = [sorted(m["level"] for m in trainer_roster.TRAINERS_BY_INDEX[i]["team"] if "level" in m)[0]
                  for i in _chobin_indices()]
        self.assertEqual(levels, [5, 6, 26, 26, 26, 37, 38])


class TestTheExclusion(unittest.TestCase):
    def test_kaminkos_house_is_excluded(self) -> None:
        self.assertIn(KAMINKO, pls.PATH_EXCLUDED_REGIONS)

    def test_the_set_is_not_empty(self) -> None:
        """ADDENDUM 298 deleted this mechanism when it was empty, on the grounds that a condition nobody can
        trigger reads as a guarantee. The import-time fence refuses an empty set; this says so out loud."""
        self.assertTrue(pls.PATH_EXCLUDED_REGIONS)

    def test_an_excluded_region_has_no_tier(self) -> None:
        regions = _regions()
        known = {r for r in regions.values() if r}
        tiers = pls.path_tiers(known)
        self.assertIsNone(pls.tier_index(KAMINKO, tiers, known))

    def test_it_contributes_no_tier_of_its_own(self) -> None:
        self.assertEqual(pls.path_tiers({KAMINKO}), [])

    def test_the_opening_tier_is_gone_entirely(self) -> None:
        """SUPERSEDED 2026-09-26 (ADDENDUM 367). This asserted that tier 0 survived on `Pokemon HQ Lab` and
        `Gateon Port` -- true at the time, and the reason this change looked like it re-spaced nothing.

        Measuring what was IN that tier is what moved it: twelve levelled trainers with vanilla levels of 5
        through 50 (Laken #3 at fifty, Ardos #1 at 44), every one flattened to 8. The same defect as Chobin's,
        for the same reason, so all three always-open regions came off and the opening tier went with them."""
        regions = _regions()
        known = {r for r in regions.values() if r}
        tiers = pls.path_tiers(known)
        self.assertNotIn(None, tiers, "no always-open region is left on the ramp")
        self.assertEqual(sorted(r for r in known if pls.tier_index(r, tiers, known) == 0),
                         ["Agate Village"])

    def test_the_ramp_is_thirteen_tiers(self) -> None:
        """Fifteen while the opening tier existed (ADDENDUM 366); fourteen once it did not (ADDENDUM 367);
        thirteen once the Key Lair's doorway stopped being its own rung (ADDENDUM 368). The count is asserted
        rather than the spacing because the curve is stored as endpoints -- see `THE CURVE` in the module."""
        regions = _regions()
        known = {r for r in regions.values() if r}
        self.assertEqual(len(pls.path_tiers(known)), 13)

    def test_the_seeds_own_sphere_ordering_excludes_it_too(self) -> None:
        """`sphere_tier_order` feeds `tier_by_region`, which the builders read instead of `tier_index`. If the
        exclusion did not reach it, a sphere-ordered seed would still scale Chobin."""
        order = pls.sphere_tier_order({r: 1 for r in _regions().values() if r})
        self.assertNotIn(KAMINKO, order)


class TestWhatTheTrainersGetNow(unittest.TestCase):
    def setUp(self) -> None:
        self.census = real_trainer_data.real_trainer_team_census()
        self.levels, self.averages = pls.build_path_level_plan(self.census)
        self.rows = {row["trainer_index"]: row for row in self.census}

    def test_chobin_two_through_seven_keep_their_deck_levels(self) -> None:
        """The patcher only writes the dpkm indices it is given, so absence from the plan IS "keep vanilla"."""
        for index in _chobin_indices()[1:]:
            row = self.rows.get(index)
            self.assertIsNotNone(row, index)
            for dpkm_index in row["member_levels"]:
                self.assertNotIn(dpkm_index, self.levels, f"Chobin {index} slot {dpkm_index}")
            self.assertNotIn(index, self.averages, index)

    def test_chobin_one_is_still_pinned_to_five(self) -> None:
        """ADDENDUM 281's instruction, which the exclusion must not have swallowed."""
        row = self.rows[15]
        for dpkm_index in row["member_levels"]:
            self.assertEqual(self.levels[dpkm_index], 5, dpkm_index)
        self.assertEqual(self.averages[15], 5.0)

    def test_the_last_chobin_would_have_been_flattened_to_eight_before_this(self) -> None:
        """The regression, stated as a number. Without the exclusion he is tier 0 and tier 0 is FIRST_TIER
        _LEVEL; his deck says 38."""
        self.assertEqual(pls.FIRST_TIER_LEVEL, 8)
        vanilla = {m["level"] for m in trainer_roster.TRAINERS_BY_INDEX[167]["team"] if "level" in m}
        self.assertEqual(vanilla, {38})

    def test_no_other_trainer_moved(self) -> None:
        """SUPERSEDED 2026-09-26 (ADDENDUM 367) and kept as a record of what ADDENDUM 366 alone did.

        366 really did move nothing outside Kaminko's -- the diff below is empty when only that region is
        excluded, which is the finding that sent the next addendum looking at what the opening tier actually
        contained. 367 then took the other two always-open regions off as well, which DOES re-space the ramp;
        that is asserted in `TestAddendum367`, not here. So this pins 366's own claim by excluding only the
        one region, rather than being deleted for having been overtaken."""
        from unittest import mock

        # BOTH sides are computed under a patched exclusion set. `self.levels` comes from setUp and reflects
        # the LIVE set, which ADDENDUM 367 widened to all three always-open regions -- comparing against that
        # would be measuring 367, not 366.
        with mock.patch.object(pls, "PATH_EXCLUDED_REGIONS", frozenset()):
            before, before_avg = pls.build_path_level_plan(self.census)
        with mock.patch.object(pls, "PATH_EXCLUDED_REGIONS", frozenset({KAMINKO})):
            after, after_avg = pls.build_path_level_plan(self.census)

        regions = _regions()
        kaminko_slots = {
            dpkm_index
            for row in self.census if regions.get(row["trainer_index"]) == KAMINKO
            for dpkm_index in row["member_levels"]
        }
        kaminko_trainers = {row["trainer_index"] for row in self.census
                            if regions.get(row["trainer_index"]) == KAMINKO}

        self.assertEqual({k: v for k, v in before.items() if k not in kaminko_slots},
                         {k: v for k, v in after.items() if k not in kaminko_slots})
        self.assertEqual({k: v for k, v in before_avg.items() if k not in kaminko_trainers},
                         {k: v for k, v in after_avg.items() if k not in kaminko_trainers})

    def test_and_every_kaminko_trainer_except_the_pinned_one_did(self) -> None:
        """The other half: the diff above is only meaningful if the exclusion actually removed something."""
        from unittest import mock

        with mock.patch.object(pls, "PATH_EXCLUDED_REGIONS", frozenset()):
            before, _ = pls.build_path_level_plan(self.census)

        for index in _chobin_indices()[1:]:
            row = self.rows[index]
            for dpkm_index in row["member_levels"]:
                self.assertIn(dpkm_index, before, "the old ramp really did level this slot")
                self.assertEqual(before[dpkm_index], pls.FIRST_TIER_LEVEL)
                self.assertNotIn(dpkm_index, self.levels)


class TestThePinnedPastTheSkipBranch(unittest.TestCase):
    def test_a_pinned_trainer_in_an_excluded_region_still_gets_its_pin(self) -> None:
        """The reorder itself, exercised directly rather than only through Chobin -- so the branch is pinned
        even if the census changes under it."""
        census = [{"trainer_index": 15, "member_levels": {900: 40, 901: 41}}]
        levels, averages = pls.build_path_level_plan(census, regions_by_trainer={15: KAMINKO})
        self.assertEqual(levels, {900: 5, 901: 5})
        self.assertEqual(averages, {15: 5.0})

    def test_an_unpinned_trainer_in_an_excluded_region_gets_nothing(self) -> None:
        census = [{"trainer_index": 167, "member_levels": {910: 38}}]
        levels, averages = pls.build_path_level_plan(census, regions_by_trainer={167: KAMINKO})
        self.assertEqual(levels, {})
        self.assertEqual(averages, {})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
