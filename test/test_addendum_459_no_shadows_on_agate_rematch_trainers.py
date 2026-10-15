"""ADDENDUM 459 (2026-10-10) -- no generated or relocated Shadow on a trainer the game re-fights with the same team.

One of the trainers in Agate had a Shadow Snubbul that respawned upon being caught. Those trainers (24-27) can be
rematched, and they have the exact same team every time, so they get no Shadows.
"""
from __future__ import annotations

import unittest

from . import PokemonXDTestBase
from ..game_data import missable_trainers as mt
from ..game_data import trainer_placements as tp
from ..game_data import trainer_roster as tr


class TestTheFence(unittest.TestCase):
    def test_the_four_agate_trainers(self) -> None:
        self.assertEqual(frozenset({24, 25, 26, 27}), mt.SAME_TEAM_REMATCH_TRAINER_INDICES)
        self.assertEqual(["GORPS", "JOLS", "LADI", "CRON"],
                         [tr.TRAINERS_BY_INDEX[i]["name"] for i in (24, 25, 26, 27)])
        self.assertTrue(all(tp.PLACEMENTS[i].region == "Agate Village" for i in (24, 25, 26, 27)))

    def test_reopened_by_addendum_466(self) -> None:
        """ADDENDUM 466: the fence is lifted -- a snagged Shadow is no longer rebuilt on a rematch (465). The set
        stays defined, and `SHADOW_REMATCH_FENCES_RELAXED = False` puts it back."""
        self.assertFalse(mt.SAME_TEAM_REMATCH_TRAINER_INDICES & mt.shadow_expansion_excluded_trainer_indices())
        with __import__("unittest").mock.patch.object(mt, "SHADOW_REMATCH_FENCES_RELAXED", False):
            self.assertTrue(mt.SAME_TEAM_REMATCH_TRAINER_INDICES <= mt.shadow_expansion_excluded_trainer_indices())


class TestTheExpansionMayPickThem(PokemonXDTestBase):
    """ADDENDUM 466: hosts are drawn from the ordinary pool again; nothing forbids or forces these four."""
    options = {"shadow_pokemon_expansion": 44}

    def test_hosts_are_inside_the_new_fence(self) -> None:
        world = self.multiworld.worlds[self.player]
        hosts = {int(plan["trainer_index"]) for plan in (world._shadow_expansion_plans or [])}
        self.assertTrue(hosts)
        self.assertFalse(hosts & mt.shadow_expansion_excluded_trainer_indices())


if __name__ == "__main__":
    unittest.main()
