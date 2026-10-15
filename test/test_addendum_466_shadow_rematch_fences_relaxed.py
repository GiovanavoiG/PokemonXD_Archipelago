"""ADDENDUM 466 (2026-10-11) -- rematches may host Shadow Pokemon again.

The Shadow rematch constraints are relaxed, with a list of every edit this makes so it can be reverted if
needed. ADDENDUM 461's six refusals reopen too.
"""
from __future__ import annotations

import unittest
from unittest import mock

from . import PokemonXDTestBase
from ..game_data import missable_trainers as mt
from ..game_data import trainer_roster as tr

NEWLY_OPEN = {24, 25, 26, 27, 13, 21, 22, 66, 67, 68, 60, 147, 164, 167}


class TestTheFence(unittest.TestCase):
    def test_exactly_these_fourteen_came_off(self):
        now = mt.shadow_expansion_excluded_trainer_indices()
        with mock.patch.object(mt, "SHADOW_REMATCH_FENCES_RELAXED", False):
            before = mt.shadow_expansion_excluded_trainer_indices()
        self.assertEqual(152, len(before), "the revert switch must give back ADDENDUM 461's fence exactly")
        # + ADDENDUM 487: the mirrored first fights (Clerr, Belish, Dert #1 -- the other four were already open).
        from ..game_data.shadow_mirrors import MIRRORED_SHADOW_HOSTS
        self.assertEqual(NEWLY_OPEN | (set(MIRRORED_SHADOW_HOSTS) & before), set(before - now))
        self.assertEqual(set(), set(now - before), "relaxing must never exclude anything new")

    def test_the_final_rows(self):
        self.assertEqual(["NAPS", "ZOOK", "SMARTON", "CHOBIN"],
                         [tr.TRAINERS_BY_INDEX[i]["name"] for i in (60, 147, 164, 167)])
        self.assertIn(202, mt.shadow_expansion_excluded_trainer_indices(), "Laken #3 stays out")

    def test_still_fenced(self):
        """Missable, unplaced, post-goal and no-snag fights are about losing the catch, not rematches."""
        excluded = mt.shadow_expansion_excluded_trainer_indices()
        self.assertLessEqual(mt.POST_GOAL_TRAINER_INDICES, excluded)
        from ..game_data.missable_indices import MISSABLE_TRAINER_INDICES
        from ..game_data.shadow_regions import NO_SNAG_TRAINER_INDICES
        self.assertLessEqual(set(MISSABLE_TRAINER_INDICES), excluded)
        self.assertLessEqual(set(NO_SNAG_TRAINER_INDICES), excluded)
        for index in (209, 221, 226, 232):   # post-game rows with no region
            self.assertIn(index, excluded)


class TestTheNewHostsGetUsed(PokemonXDTestBase):
    """Across a few seeds the expansion does pick from the reopened rows -- the fence change is live."""
    options = {"shadow_pokemon_expansion": 44, "remove_citadark_shadows": True, "shadow_catch_progression": True}

    def test_hosts(self):
        world = self.multiworld.worlds[self.player]
        hosts = {int(p["trainer_index"]) for p in (world._shadow_expansion_plans or [])}
        hosts |= {int(p["trainer_index"]) for p in (getattr(world, "_nightmare_relocations", None) or [])}
        self.assertTrue(hosts)
        self.assertFalse(hosts & mt.shadow_expansion_excluded_trainer_indices())
        self.assertTrue(hosts & NEWLY_OPEN, "with 44 Shadows and the Citadark relocations, none landed on a reopened row")


if __name__ == "__main__":
    unittest.main()
