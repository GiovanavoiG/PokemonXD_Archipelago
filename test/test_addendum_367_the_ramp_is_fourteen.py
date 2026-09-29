"""ADDENDUM 367 (2026-09-26): all three always-open regions come off the ramp, and it is fourteen tiers.

Player: *"Make sure to adjust the rest of the areas to scale with the missing area."*

WHAT I MEASURED FIRST, because the obvious reading of that turned out to be wrong. Removing Kaminko's House
(ADDENDUM 366) re-spaced nothing: it was never its own rung -- it shared the always-open tier with Gateon Port
and the Pokemon HQ Lab, and those two still had fourteen trainers between them. The tier list came out
byte-identical at fifteen. There was no gap to close, and re-spacing "anyway" would have meant merging two
OCCUPIED rungs with no principled way to pick which.

THEN LOOKING AT WHAT WAS IN THAT TIER ANSWERED IT. The twelve levelled trainers in Gateon Port and the HQ Lab
field vanilla levels of 5, 6, 6, 6, 6, 6, 16/17, 17, 18, 28, 44 and 50 -- and every one was being flattened to
FIRST_TIER_LEVEL, 8. Laken #3, a level-50 late-game rematch, was being handed to the player at level 8.

That is the Chobin defect exactly, on twelve more fights, for the same reason: an always-open region is open
from the first hour and fought in across the whole story, so "the game lets you in immediately" says nothing
about when any particular fight in it happens.

SO ALL THREE COME OFF, AND THE ARITHMETIC FALLS OUT. With no always-open region left on the ramp,
`path_tiers` stops emitting its leading `None` tier: fourteen real tiers, re-spread across 8-50. Agate Village
11 -> 8, Citadark Isle stays at 50, everything between moves down one to three. The endpoints are preserved
and the spacing widens from 3.00 to 3.23 -- which is the "adjust the rest of the areas" the player asked for,
arrived at by the same rule rather than imposed on top of it.
"""
from __future__ import annotations

import unittest
from unittest import mock

from ..game_data import real_trainer_data, story_bytes, trainer_placements, trainer_roster
from ..randomizer import path_level_scaling as pls

OPENING = ("Pokemon HQ Lab", "Gateon Port", "Kaminko's House")


def _regions() -> "dict[int, str]":
    return {index: trainer_placements.region_for(index) for index in trainer_roster.TRAINERS_BY_INDEX}


def _known() -> "set[str]":
    return {region for region in _regions().values() if region}


class TestTheMeasurementThatMovedIt(unittest.TestCase):
    def test_excluding_kaminko_alone_really_did_re_space_nothing(self) -> None:
        """The finding that made this addendum necessary, kept as a number rather than a memory."""
        known = _known()
        with mock.patch.object(pls, "PATH_EXCLUDED_REGIONS", frozenset()):
            before = pls.path_tiers(known)
        with mock.patch.object(pls, "PATH_EXCLUDED_REGIONS", frozenset({"Kaminko's House"})):
            after = pls.path_tiers(known)
        self.assertEqual(before, after)
        # ADDENDUM 368 removed the Key Lair doorway's rung, so this measurement -- taken with the exclusions
        # lifted, hence one extra always-open tier -- is fourteen where it was fifteen. What it demonstrates is
        # unchanged: excluding Kaminko's House alone moves NOTHING, because it never had a rung of its own.
        self.assertEqual(len(before), 14)

    def test_the_opening_tier_was_full_of_late_game_fights(self) -> None:
        """Why it could not stay. These are real placements, not a fixture."""
        regions = _regions()
        opening = [i for i, r in regions.items() if r in ("Pokemon HQ Lab", "Gateon Port")]
        levels = sorted(
            level
            for i in opening
            for level in {m["level"] for m in trainer_roster.TRAINERS_BY_INDEX[i]["team"] if "level" in m}
        )
        self.assertGreaterEqual(max(levels), 50, "Laken #3 is a level-50 fight in an always-open region")
        self.assertLessEqual(min(levels), 6)
        self.assertGreater(max(levels) - min(levels), 40,
                           "one tier cannot describe a span like that -- which is the whole point")


class TestAllThreeAreOff(unittest.TestCase):
    def test_the_excluded_set_is_exactly_the_always_open_set(self) -> None:
        self.assertEqual(pls.PATH_EXCLUDED_REGIONS, story_bytes.ALWAYS_OPEN_REGIONS)
        for region in OPENING:
            self.assertIn(region, pls.PATH_EXCLUDED_REGIONS, region)

    def test_none_of_them_has_a_tier(self) -> None:
        known = _known()
        tiers = pls.path_tiers(known)
        for region in OPENING:
            self.assertIsNone(pls.tier_index(region, tiers, known), region)

    def test_the_leading_always_open_tier_is_gone(self) -> None:
        self.assertNotIn(None, pls.path_tiers(_known()))

    def test_the_ramp_starts_at_agate_and_ends_at_citadark(self) -> None:
        """ADDENDUM 368 took the count from fourteen to thirteen by merging the Key Lair's doorway onto the
        building. The ENDPOINTS are what this addendum was about and they are unchanged -- Agate first,
        Citadark last -- so they are asserted as positions and the count is asserted as whatever the table
        says it is, derived the same way the ramp derives it."""
        known = _known()
        tiers = pls.path_tiers(known)
        self.assertEqual(len(tiers), 13)
        self.assertEqual(pls.tier_index("Agate Village", tiers, known), 0)
        self.assertEqual(pls.tier_index("Citadark Isle", tiers, known), len(tiers) - 1)

    def test_the_collapse_itself_still_works_when_something_is_not_excluded(self) -> None:
        """`path_tiers` is a total function over any region set and the tests call it with always-open
        regions directly, so the collapse is kept rather than deleted -- re-admitting one of these regions
        should be a deletion from a set, not a redesign."""
        with mock.patch.object(pls, "PATH_EXCLUDED_REGIONS", frozenset()):
            tiers = pls.path_tiers(set(OPENING) | {"Agate Village"})
            self.assertIsNone(tiers[0])
            self.assertEqual(len(tiers), 2, "three always-open regions are ONE tier")


class TestTheRespacing(unittest.TestCase):
    def setUp(self) -> None:
        self.known = _known()

    def _levels(self, excluded: "frozenset[str]") -> "dict[str, int]":
        with mock.patch.object(pls, "PATH_EXCLUDED_REGIONS", excluded):
            tiers = pls.path_tiers(self.known)
            out = {}
            for region in self.known:
                index = pls.tier_index(region, tiers, self.known)
                if index is not None:
                    out[region] = pls.level_for_tier(
                        index, len(tiers), pls.FIRST_TIER_LEVEL, pls.LAST_TIER_LEVEL
                    )
            return out

    def test_the_endpoints_are_preserved(self) -> None:
        """A re-space must not quietly change how hard the game starts or ends."""
        now = self._levels(pls.PATH_EXCLUDED_REGIONS)
        self.assertEqual(min(now.values()), pls.FIRST_TIER_LEVEL)
        self.assertEqual(max(now.values()), pls.LAST_TIER_LEVEL)
        self.assertEqual(now["Agate Village"], 8)
        self.assertEqual(now["Citadark Isle"], 50)

    def test_every_area_moved_down_or_stayed_and_none_moved_up(self) -> None:
        """Dropping a rung spreads the same range over fewer positions, so an area can only sit at or below
        where it sat -- anything moving UP would mean the ordering changed, not just the spacing."""
        before = self._levels(frozenset({"Kaminko's House"}))
        after = self._levels(pls.PATH_EXCLUDED_REGIONS)
        for region, level in after.items():
            self.assertLessEqual(level, before[region], region)
        self.assertTrue(any(after[r] < before[r] for r in after), "something must actually have moved")

    def test_the_ramp_is_still_monotone(self) -> None:
        known = self.known
        tiers = pls.path_tiers(known)
        levels = [pls.level_for_tier(i, len(tiers), pls.FIRST_TIER_LEVEL, pls.LAST_TIER_LEVEL)
                  for i in range(len(tiers))]
        self.assertEqual(levels, sorted(levels))
        self.assertEqual(len(set(levels)), len(levels), "no two rungs may share a level")


class TestWhatTheTrainersGet(unittest.TestCase):
    def setUp(self) -> None:
        self.census = real_trainer_data.real_trainer_team_census()
        self.levels, self.averages = pls.build_path_level_plan(self.census)
        self.rows = {row["trainer_index"]: row for row in self.census}

    def test_chobin_one_is_still_pinned_to_five(self) -> None:
        """The player's standing instruction, restated with this change: "Ensure Chobin 1 stays at level 5.\""""
        for dpkm_index in self.rows[15]["member_levels"]:
            self.assertEqual(self.levels[dpkm_index], 5, dpkm_index)
        self.assertEqual(self.averages[15], 5.0)

    def test_the_late_always_open_fights_keep_their_deck_levels(self) -> None:
        """Laken #3 (vanilla 50) and Ardos #1 (vanilla 44) were both being handed over at 8."""
        for index in (202, 10):
            row = self.rows[index]
            for dpkm_index in row["member_levels"]:
                self.assertNotIn(dpkm_index, self.levels, (index, dpkm_index))
            self.assertNotIn(index, self.averages, index)

    def test_only_always_open_trainers_left_the_plan(self) -> None:
        regions = _regions()
        with mock.patch.object(pls, "PATH_EXCLUDED_REGIONS", frozenset()):
            before, _ = pls.build_path_level_plan(self.census)
        gone = set(before) - set(self.levels)
        owners = {row["trainer_index"] for row in self.census
                  for d in row["member_levels"] if d in gone}
        self.assertTrue(owners)
        for index in owners:
            self.assertIn(regions[index], pls.PATH_EXCLUDED_REGIONS, index)

    def test_everyone_still_on_the_ramp_got_a_level(self) -> None:
        regions = _regions()
        for row in self.census:
            region = regions.get(row["trainer_index"])
            if not region or region in pls.PATH_EXCLUDED_REGIONS:
                continue
            self.assertTrue(any(d in self.levels for d in row["member_levels"]), row["trainer_index"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
