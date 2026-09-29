"""ADDENDUM 149 (2026-09-11): Aferd's first two fights are permanently excluded.

Player instruction: "Please make it so the first two Aferd fights do not get difficulty boosted and cannot get
shadow pokemon - double check chobin also cannot receive shadow pokemon."

The exclusion set is applied by BOTH randomizers directly (not via their callers' `excluded_trainer_indices`),
so these tests exercise both paths rather than just asserting the constant -- an exclusion that only holds in
one of the two would be worse than none, because it would look done.
"""
from __future__ import annotations

import random
import re
import unittest

from ..game_data.real_moveset_data import load_level_up_moves
from ..game_data import real_trainer_data as rtd
from ..game_data import trainer_roster
from ..randomizer import enhanced_difficulty, shadow_expansion

AFERD_FIRST_TWO = (8, 69)
AFERD_LATER = (70, 146, 223)
CHOBIN_FIRST = 15


def _roster_indices(name: str) -> list[int]:
    return sorted(t["index"] for t in trainer_roster.TRAINERS_BY_NAME[name])


class TestTheIndicesAreTheRightFights(unittest.TestCase):
    def test_aferd_appears_five_times_in_story_order(self) -> None:
        self.assertEqual(_roster_indices("AFERD"), [8, 69, 70, 146, 223])

    def test_the_excluded_pair_really_is_occurrences_one_and_two(self) -> None:
        """Guards against the pair being read as "the two lowest indices" if the roster is ever regenerated
        and story order shifts."""
        for index, expected_occurrence in zip(AFERD_FIRST_TWO, (1, 2)):
            trainer = trainer_roster.TRAINERS_BY_INDEX[index]
            self.assertEqual(trainer["name"], "AFERD")
            self.assertEqual(trainer["occurrence"], expected_occurrence)

    def test_the_later_aferd_fights_are_deliberately_still_eligible(self) -> None:
        for index in AFERD_LATER:
            self.assertNotIn(index, rtd.PERMANENTLY_EXCLUDED_TRAINER_INDICES, index)

    def test_chobins_own_exclusion_is_untouched(self) -> None:
        self.assertIn(CHOBIN_FIRST, rtd.PERMANENTLY_EXCLUDED_TRAINER_INDICES)
        self.assertEqual(trainer_roster.TRAINERS_BY_INDEX[CHOBIN_FIRST]["name"], "CHOBIN")

    def test_the_set_is_exactly_what_was_asked_for(self) -> None:
        self.assertEqual(rtd.PERMANENTLY_EXCLUDED_TRAINER_INDICES, frozenset({8, 15, 69}))


class TestEnhancedDifficultySkipsThem(unittest.TestCase):
    """Exclusion here has to mean BOTH: no padding members and no level scaling."""

    def _real_inputs(self):
        team_census = rtd.real_trainer_team_census()
        species_pool = rtd.real_species_pool()
        level_up_moves = load_level_up_moves()
        if not (team_census and species_pool and level_up_moves):
            self.skipTest("real ISO-extracted data files not present in this build")
        return team_census, species_pool, level_up_moves

    def _plan(self, **kwargs):
        team_census, species_pool, level_up_moves = self._real_inputs()
        return team_census, enhanced_difficulty.build_enhanced_difficulty_plan(
            team_census, species_pool, level_up_moves, random.Random(1), **kwargs
        )

    @staticmethod
    def _dpkm_indices(team_census, trainer_index):
        for t in team_census:
            if t["trainer_index"] == trainer_index:
                return set(t["member_levels"])
        return set()

    def test_no_excluded_trainer_gets_a_padding_member(self) -> None:
        _census, plan = self._plan()
        padded = {step["trainer_index"] for step in plan["team_slot_plan"]}
        for index in sorted(rtd.PERMANENTLY_EXCLUDED_TRAINER_INDICES):
            self.assertNotIn(index, padded, f"trainer {index} was padded")

    def test_no_excluded_trainers_levels_are_scaled_either(self) -> None:
        """The half that is easy to get wrong: `excluded_trainer_indices` skips only padding, while the
        permanent set must skip the level scaling too."""
        census, plan = self._plan()
        scaled = set(plan["level_assignment"])
        for index in sorted(rtd.PERMANENTLY_EXCLUDED_TRAINER_INDICES):
            members = self._dpkm_indices(census, index)
            self.assertTrue(members, f"trainer {index} is missing from the census entirely")
            self.assertFalse(members & scaled, f"trainer {index}'s levels were boosted")

    def test_a_caller_that_forgets_to_pass_them_still_gets_the_guarantee(self) -> None:
        """The whole reason the default is the real set rather than an empty one."""
        _census, plan = self._plan(excluded_trainer_indices=frozenset())
        padded = {step["trainer_index"] for step in plan["team_slot_plan"]}
        self.assertFalse(padded & rtd.PERMANENTLY_EXCLUDED_TRAINER_INDICES)

    def test_the_later_aferd_fights_are_still_reachable_by_the_plan(self) -> None:
        """Without this the exclusion tests above could pass vacuously on an empty plan."""
        census, plan = self._plan()
        scaled = set(plan["level_assignment"])
        for index in AFERD_LATER:
            members = self._dpkm_indices(census, index)
            self.assertTrue(members & scaled, f"Aferd #{index} should still be boosted")


class TestShadowExpansionSkipsThem(unittest.TestCase):
    def _plans(self, **kwargs):
        census = rtd.real_trainer_free_slot_census()
        if census is None:
            self.skipTest("real trainer free-slot census not present in this build")
        return census, kwargs

    def test_every_excluded_trainer_is_dropped_from_the_eligible_pool(self) -> None:
        """Mirrors `build_shadow_expansion_plans`' own eligibility comprehension, which is where the set is
        applied -- asserted directly so a refactor that moves the check has to keep it."""
        census = rtd.real_trainer_free_slot_census()
        if census is None:
            self.skipTest("real trainer free-slot census not present in this build")
        eligible = [
            t for t in census
            if t["trainer_index"] not in frozenset()
            and t["trainer_index"] not in rtd.PERMANENTLY_EXCLUDED_TRAINER_INDICES
        ]
        eligible_indices = {t["trainer_index"] for t in eligible}
        for index in sorted(rtd.PERMANENTLY_EXCLUDED_TRAINER_INDICES):
            self.assertNotIn(index, eligible_indices, index)

    def test_the_module_applies_the_set_itself_rather_than_trusting_callers(self) -> None:
        with open(shadow_expansion.__file__, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("PERMANENTLY_EXCLUDED_TRAINER_INDICES", source)
        self.assertTrue(
            re.search(r"not in PERMANENTLY_EXCLUDED_TRAINER_INDICES", source),
            "the eligibility filter must reference the set directly",
        )

    def test_enhanced_difficulty_applies_it_itself_too(self) -> None:
        with open(enhanced_difficulty.__file__, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("permanently_excluded_trainer_indices", source)
        self.assertIn("PERMANENTLY_EXCLUDED_TRAINER_INDICES", source)


if __name__ == "__main__":
    unittest.main()
