"""ADDENDUM 459 (2026-10-10) -- no generated or relocated Shadow on a trainer the game re-fights with the same team.

Player report: "one of the trainers in Agate having a shadow Snubbul that respawned upon being caught. Those trainers
let you rematch them but they have the exact same team - perhaps we can't give them shadows? It was trainers 24-27".
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

    def test_excluded_from_every_shadow_host(self) -> None:
        self.assertTrue(mt.SAME_TEAM_REMATCH_TRAINER_INDICES <= mt.shadow_expansion_excluded_trainer_indices())


class TestTheExpansionNeverPicksThem(PokemonXDTestBase):
    options = {"shadow_pokemon_expansion": 44}

    def test_no_plan_targets_them(self) -> None:
        world = self.multiworld.worlds[self.player]
        hosts = {int(plan["trainer_index"]) for plan in (world._shadow_expansion_plans or [])}
        self.assertTrue(hosts)
        self.assertFalse(hosts & mt.SAME_TEAM_REMATCH_TRAINER_INDICES)
        for dex_hosts in (world._shadow_catch_expansion_hosts or {}).values():
            self.assertFalse(set(dex_hosts) & mt.SAME_TEAM_REMATCH_TRAINER_INDICES)


class TestRelocationsNeverPickThem(PokemonXDTestBase):
    options = {"remove_citadark_shadows": True}

    def test_no_relocation_targets_them(self) -> None:
        world = self.multiworld.worlds[self.player]
        hosts = {int(plan["trainer_index"]) for plan in (getattr(world, "_nightmare_relocations", None) or [])}
        self.assertTrue(hosts)
        self.assertFalse(hosts & mt.SAME_TEAM_REMATCH_TRAINER_INDICES)


if __name__ == "__main__":
    unittest.main()
