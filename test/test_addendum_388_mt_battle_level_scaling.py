"""ADDENDUM 388 (2026-09-28) -- Mt. Battle's own ceiling, its padded members, and what "exclude" means.

Player: "Can we examine how our multiple level scaling options affect mt battle? Their team levels are very
inconsistent and all over the place right now"

Measured across the option matrix on real generated seeds, all 100 trainers, before any change:

    vanilla                        9..70   mean 48.5   padded   0   worst team spread  5
    ED scale only                 11..93   mean 64.0   padded   0   worst team spread  6
    path only                     12..50   mean 34.8   padded   0   worst team spread  5
    ED fill + path (Mt. in)       11..69   mean 36.6   padded 235   worst team spread 24
    ED fill + ED scale + path     14..91   mean 48.2   padded 235   worst team spread 33

Three separate faults, all visible in that table.

ONE -- ADDENDUM 383 NEVER REACHED MT. BATTLE. That addendum made Enhanced Difficulty's padded members follow
the ramp instead of their trainer's vanilla average; it was applied to the story roster only. So trainer 75
fielded five level-40 Pokemon and one at 64, and 33 apart once the multiplier was on top. 235 members.

TWO -- THE RAMP ENDED AT 50 WHILE THE MOUNTAIN ENDS AT 70. `LAST_TIER_LEVEL` is 50 because Citadark Isle is
where the STORY ends. Mt. Battle's hundredth trainer is a level-70 fight, so sharing that ceiling made path
scaling hand back a mountain whose top fifth is easier than the unmodified game -- the mean fell 14 levels.
It is also what made fault one so violent: a padded member levelled from a vanilla 64 sat above the whole
ramp. The ceiling is now DERIVED from Mt. Battle's own census, and is never allowed below the story's.

THREE -- "EXCLUDE MT BATTLE FROM ENHANCED DIFFICULTY" ONLY EXCLUDED HALF OF IT. The toggle is on by default
and gated the padding alone, so the default configuration still multiplied every Mt. Battle level by 1.33
while the option read as though it had not. It now gates both. Path scaling is a DIFFERENT option and is
deliberately still allowed to re-level Mt. Battle when the toggle is on.

AFTER: the worst team spread is 5 with the multiplier off and 7 with it on -- the same as vanilla's own 5 --
and the default configuration leaves the mountain at its vanilla levels unless path scaling is asked for.
"""
from __future__ import annotations

import pathlib
import statistics
import unittest

from ..game_data.mtbattle_trainer_data import mtbattle_team_census
from ..randomizer import path_level_scaling as pls


def _census():
    census = mtbattle_team_census()
    if not census:
        raise unittest.SkipTest("data/mtbattle_trainer_census.json not available")
    return census


class TestTheMountainHasItsOwnCeiling(unittest.TestCase):
    def setUp(self) -> None:
        self.census = _census()

    def test_it_is_the_highest_level_the_mountain_fields(self) -> None:
        highest = max(level for row in self.census for level in row["member_levels"].values())
        self.assertEqual(highest, pls.mt_battle_ramp_top(self.census))
        self.assertEqual(70, pls.mt_battle_ramp_top(self.census), "the real census's top, recorded")

    def test_it_is_above_the_story_ramp_s_ceiling(self) -> None:
        """The whole point. If these were equal the option would still be flattening the mountain."""
        self.assertGreater(pls.mt_battle_ramp_top(self.census), pls.LAST_TIER_LEVEL)

    def test_it_never_falls_below_the_story_ramp(self) -> None:
        """Mt. Battle is later content than Citadark, so a census that somehow topped out lower must not
        drag the mountain under the story's ending level."""
        gentle = [{"trainer_index": 1, "member_levels": {0: 5}}]
        self.assertEqual(pls.LAST_TIER_LEVEL, pls.mt_battle_ramp_top(gentle))

    def test_an_empty_census_falls_back_rather_than_raising(self) -> None:
        self.assertEqual(pls.LAST_TIER_LEVEL, pls.mt_battle_ramp_top([]))

    def test_it_is_clamped_to_the_level_cap(self) -> None:
        absurd = [{"trainer_index": 1, "member_levels": {0: 500}}]
        self.assertEqual(pls.MAX_LEVEL, pls.mt_battle_ramp_top(absurd))


class TestTheRampReachesIt(unittest.TestCase):
    def setUp(self) -> None:
        self.census = _census()
        self.levels, self.averages = pls.build_mt_battle_path_level_plan(self.census)

    def test_the_hundredth_trainer_is_at_the_mountain_s_top(self) -> None:
        top = pls.mt_battle_ramp_top(self.census)
        self.assertEqual(top, max(self.levels.values()))
        last = max(self.averages)
        self.assertAlmostEqual(top, self.averages[last], delta=1.5)

    def test_it_no_longer_stops_at_the_story_s_fifty(self) -> None:
        """The regression this addendum exists to prevent, asserted as a number someone would have to undo."""
        self.assertGreater(max(self.levels.values()), pls.LAST_TIER_LEVEL)

    def test_it_still_starts_at_the_mountain_s_place_on_the_path(self) -> None:
        """Raising the ceiling must not move the floor -- the anchor is the whole reason this ramp exists."""
        first = min(self.averages)
        self.assertLess(self.averages[first], 20, "the opening trainers stay low-level")

    def test_the_mean_is_back_near_vanilla(self) -> None:
        """It measured 34.8 against vanilla's 48.5. Re-levelling is allowed to move it; halving the
        mountain's difficulty is not."""
        vanilla = statistics.mean(level for row in self.census
                                  for level in row["member_levels"].values())
        scaled = statistics.mean(self.levels.values())
        self.assertGreater(scaled, vanilla - 6, f"vanilla {vanilla:.1f}, scaled {scaled:.1f}")

    def test_an_explicit_ceiling_still_wins(self) -> None:
        """Tests and deliberate callers keep their say; only the DEFAULT changed."""
        levels, _averages = pls.build_mt_battle_path_level_plan(self.census, last=40)
        self.assertLessEqual(max(levels.values()), 41)

    def test_every_level_is_inside_the_cap(self) -> None:
        for level in self.levels.values():
            self.assertTrue(pls.MIN_LEVEL <= level <= pls.MAX_LEVEL, level)


class TestThePaddedMembersFollowTheMountainsRamp(unittest.TestCase):
    """Structural, for the reason ADDENDUM 383's own tests give: the fix lives inside `generate_output`."""

    def setUp(self) -> None:
        self.source = (pathlib.Path(__file__).resolve().parent.parent / "__init__.py").read_text(
            encoding="utf-8")
        self.start = self.source.index("_mt_relevelled_additions = 0")

    def _body(self) -> str:
        return self.source[self.start:self.start + 1200]

    def test_it_relevels_mt_battle_s_own_entries(self) -> None:
        body = self._body()
        self.assertIn('mt_battle_enhanced_difficulty_plan["new_dpkm_entries"]', body)
        self.assertIn('mt_battle_enhanced_difficulty_plan["team_slot_plan"]', body,
                      "an entry does not carry its trainer index -- the slot plan is the only way across")

    def test_it_takes_mt_battle_s_averages_not_the_story_s(self) -> None:
        """Two namespaces. `path_averages` is the story roster's and its trainer indices mean something
        else entirely here, so using it would re-level against the wrong trainers."""
        body = self._body()
        self.assertIn("mt_averages.get", body)
        self.assertNotIn("path_averages", body)

    def test_the_averages_are_no_longer_thrown_away(self) -> None:
        """They were bound to `_mt_averages` and discarded, which is what made the bug invisible."""
        self.assertIn("mt_levels, mt_averages = build_mt_battle_path_level_plan", self.source)

    def test_a_trainer_off_the_ramp_keeps_its_vanilla_level(self) -> None:
        body = self._body()
        self.assertIn("if _average is None:", body)
        self.assertIn("continue", body)

    def test_the_multiplier_is_applied_to_the_addition_too(self) -> None:
        """The originals get it, so an addition that did not would be the same bug at a smaller scale."""
        body = self._body()
        self.assertIn("if mt_ed_scale_levels:", body)
        self.assertIn("_path_scaled(_level)", body)

    def test_the_level_is_clamped(self) -> None:
        body = self._body()
        self.assertIn("PATH_MIN_LEVEL", body)
        self.assertIn("PATH_MAX_LEVEL", body)

    def test_it_reports_what_it_moved(self) -> None:
        body = self._body()
        self.assertIn('seed_data["notes"].append', body)

    def test_it_is_inside_the_path_scaling_branch(self) -> None:
        branch = self.source.index("mt_levels, mt_averages = build_mt_battle_path_level_plan")
        self.assertLess(branch, self.start)


class TestExcludeMeansFullyExcluded(unittest.TestCase):
    def setUp(self) -> None:
        self.source = (pathlib.Path(__file__).resolve().parent.parent / "__init__.py").read_text(
            encoding="utf-8")

    def test_the_toggle_is_read_once_into_a_name(self) -> None:
        self.assertIn("mt_excluded_from_ed = bool(self.options.exclude_mt_battle_trainers)", self.source)

    def test_it_gates_the_level_multiplier_as_well_as_the_padding(self) -> None:
        self.assertIn("mt_ed_scale_levels = ed_scale_levels and not mt_excluded_from_ed", self.source)
        self.assertIn("scale_levels=mt_ed_scale_levels", self.source)

    def test_the_story_roster_is_untouched_by_this(self) -> None:
        """A Mt. Battle toggle must not reach the main roster's plan."""
        self.assertIn("scale_levels=ed_scale_levels", self.source,
                      "the story roster still takes the option itself")

    def test_path_scaling_is_deliberately_not_gated_by_it(self) -> None:
        """They are different options. Excluding Mt. Battle from Enhanced Difficulty must not silently
        switch off a scaling option the player asked for separately."""
        branch = self.source.index("mt_levels, mt_averages = build_mt_battle_path_level_plan")
        preceding = self.source.rindex("if path_scale_levels:", 0, branch)
        window = self.source[preceding:branch]
        self.assertNotIn("mt_excluded_from_ed", window)

    def test_the_option_docstring_promises_what_it_now_does(self) -> None:
        from ..options import ExcludeMtBattleTrainers
        text = " ".join((ExcludeMtBattleTrainers.__doc__ or "").split())
        self.assertIn("enhanced difficulty", text.lower())


if __name__ == "__main__":
    unittest.main()
