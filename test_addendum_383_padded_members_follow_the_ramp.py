"""ADDENDUM 383 (2026-09-28) -- Enhanced Difficulty's padded members follow the ramp, like everything else.

Player: "Double check ALL levels and stats to make sure no wacky stuff is happening despite settings - make
sure trainers dont have one pokemon with crazy levels, make sure stats make sense, etc"

Found by auditing the `seed.json` of real generated seeds across the option matrix, rather than by reading
code. With path scaling AND Enhanced Difficulty on, trainer 147's vanilla team of four level-26 Pokemon was
re-levelled to 62 while the member Enhanced Difficulty added to it arrived at **34**. Seven more teams looked
the same: 141 (originals 54-63, addition 36), 138 (57-58, 33), 160 (59-66, 42), 143 (57-58, 34). On one seed
321 additions were levelled this way.

THE CAUSE. `build_enhanced_difficulty_plan` levels a new member from its trainer's census `avg_level` times
the multiplier -- the VANILLA average. That is right when nothing else moves, and wrong the moment path
scaling re-levels the originals off the ramp instead, because the two no longer share a baseline. 26 * 1.33 is
34; the ramp put that trainer's team at 62.

This is ADDENDUM 339 again, one path over. 339 found exactly this for the expansion's generated Shadows and
fixed it with `_relevel_generated_shadows`; Enhanced Difficulty's own additions never got the equivalent pass.
The fix reuses `path_averages`, which was already being computed two lines away and used only for a note's
word count, keyed through `team_slot_plan` because an entry does not carry its own trainer index.

AFTER: the worst team spread on that seed drops from 28 to 14, and the 14 is Greevil, whose vanilla team spans
10 on purpose and is simply amplified by the multiplier.
"""
from __future__ import annotations

import os
import unittest

from ..game_data.real_trainer_data import real_trainer_team_census
from ..randomizer.path_level_scaling import build_path_level_plan


class TestTheBugWasReal(unittest.TestCase):
    """ADDENDA 247/298: a fix whose condition can never bind does not belong here. Prove the two baselines
    genuinely disagree before testing that the code prefers one."""

    def test_the_ramp_and_the_vanilla_average_disagree_for_many_trainers(self) -> None:
        census = real_trainer_team_census()
        self.assertTrue(census, "no census, no test")
        _levels, path_averages = build_path_level_plan(census)
        vanilla = {entry["trainer_index"]: entry["avg_level"] for entry in census}
        disagreeing = [index for index, average in path_averages.items()
                       if index in vanilla and abs(average - vanilla[index]) >= 5]
        self.assertGreater(len(disagreeing), 50,
                           "if the ramp agreed with the vanilla average everywhere, the bug would have been "
                           "impossible and this fix would be dead weight")

    def test_the_gap_is_large_enough_to_matter(self) -> None:
        """A few levels would be cosmetic. The measured worst case was 26 -> 62 against an addition at 34."""
        census = real_trainer_team_census()
        _levels, path_averages = build_path_level_plan(census)
        vanilla = {entry["trainer_index"]: entry["avg_level"] for entry in census}
        worst = max((abs(average - vanilla[index]) for index, average in path_averages.items()
                     if index in vanilla), default=0)
        self.assertGreaterEqual(worst, 20, "the worst disagreement should be a whole team's worth of levels")


class TestTheCallSiteRelevelsThem(unittest.TestCase):
    """Structural, because the fix lives inside `generate_output`, which needs a full generation to reach."""

    def setUp(self) -> None:
        import pathlib
        self.source = (pathlib.Path(__file__).resolve().parent.parent / "__init__.py").read_text(
            encoding="utf-8")
        self.start = self.source.index("_relevelled_additions = 0")

    def test_it_relevels_the_new_dpkm_entries(self) -> None:
        body = self.source[self.start:self.start + 900]
        self.assertIn('enhanced_difficulty_plan["new_dpkm_entries"]', body)
        self.assertIn('enhanced_difficulty_plan["team_slot_plan"]', body,
                      "an entry does not carry its trainer index -- the slot plan is the only way across")
        self.assertIn("path_averages.get", body, "it must take the ramp's average, not the census's")

    def test_it_happens_after_the_ramp_is_resolved_and_scaled(self) -> None:
        scaled = self.source.index("path_averages = {index: float(_path_scaled(level))")
        self.assertLess(scaled, self.start,
                        "re-levelling before the multiplier is applied would use half-finished averages")

    def test_it_is_inside_the_path_scaling_branch(self) -> None:
        """With path scaling off the census average IS the baseline the originals use, so touching the
        additions there would be the bug in reverse."""
        branch = self.source.index("if path_scale_levels:")
        following = self.source.index("shadow_census = real_shadow_census()", branch)
        self.assertLess(branch, self.start)
        self.assertLess(self.start, following)

    def test_a_trainer_with_no_known_region_keeps_its_vanilla_level(self) -> None:
        body = self.source[self.start:self.start + 900]
        self.assertIn("if _average is None:", body)
        self.assertIn("continue", body)

    def test_the_level_is_clamped(self) -> None:
        body = self.source[self.start:self.start + 900]
        self.assertIn("PATH_MIN_LEVEL", body)
        self.assertIn("PATH_MAX_LEVEL", body)

    def test_it_reports_what_it_moved(self) -> None:
        """A silent re-level is indistinguishable from the bug it fixes."""
        body = self.source[self.start:self.start + 900]
        self.assertIn("_relevelled_additions", body)
        self.assertIn('seed_data["notes"].append', body)


if __name__ == "__main__":
    unittest.main()
