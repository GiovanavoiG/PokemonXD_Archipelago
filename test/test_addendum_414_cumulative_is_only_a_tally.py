"""ADDENDUM 414 (2026-10-04) -- cumulative mode is the Defeat N Trainers tally and nothing else.

Player: "Cumulative mode should not have the 64 names and any checks - it should just be a tally."
"""
from __future__ import annotations

import unittest
from pathlib import Path

from . import PokemonXDTestBase
from .. import locations as L, trainer_defeat as TD
from ..game_data import repeatable_trainers as RT

CLIENT = (Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")


class TestTheTable(unittest.TestCase):
    def test_the_named_checks_are_not_locations(self) -> None:
        self.assertEqual(frozenset(TD.TRAINER_DEFEAT_LOCATION_NAMES), TD.RETIRED_CUMULATIVE_NAMED_LOCATIONS)
        self.assertFalse(TD.RETIRED_CUMULATIVE_NAMED_LOCATIONS & set(L.LOCATION_TABLE))

    def test_their_ids_stay_behind_inert(self) -> None:
        live = {data.id_offset for data in L.LOCATION_TABLE.values()}
        for name in TD.RETIRED_CUMULATIVE_NAMED_LOCATIONS:
            self.assertNotIn(L._FROZEN_LOCATION_OFFSETS[name], live, name)

    def test_the_roster_is_still_data(self) -> None:
        """Catch-area gating (rules.py) and the Greevil goal still read it."""
        self.assertEqual(66, len(TD.TRAINER_DEFEAT_ROSTER))
        self.assertTrue(TD.GREEVIL_DEFEAT_LOCATION_NAME.startswith("Defeat - "))


class TestACumulativeSeed(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": 0, "trainer_defeat_check_count": 114}

    def test_only_the_tally(self) -> None:
        defeats = {l.name for l in self.multiworld.get_locations(self.player)
                   if l.address is not None and l.name.startswith("Defeat")}
        self.assertEqual({f"Defeat {n} Trainers" for n in range(1, 115)}, defeats)
        self.assertFalse(defeats & set(RT.LOCATION_NAMES))


class TestAUniqueSeedKeepsItsAny(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": 1}

    def test_the_35_any_checks(self) -> None:
        created = {l.name for l in self.multiworld.get_locations(self.player)}
        self.assertEqual(set(RT.LOCATION_NAMES), created & set(RT.LOCATION_NAMES))


class TestTheClient(unittest.TestCase):
    def setUp(self) -> None:
        self.body = CLIENT.split("async def check_trainer_defeats", 1)[1].split("\n# The roster holds THREE", 1)[0]

    def test_cumulative_sends_only_tally_names(self) -> None:
        self.assertIn("if not ctx.unique_trainer_defeats:", self.body)
        self.assertIn("name in TRAINER_DEFEAT_COUNT_LOCATION_NAME_SET", self.body)

    def test_any_checks_only_in_unique_mode(self) -> None:
        self.assertIn("if ctx.shuffle_trainer_defeats and ctx.unique_trainer_defeats:", self.body)

    def test_the_greevil_goal_still_reads_the_named_queue(self) -> None:
        self.assertIn("goal_names = list(newly_completed)", self.body)
        self.assertIn("_greevil_rematch_defeated(goal_names", self.body)
        self.assertLess(self.body.index("goal_names = list(newly_completed)"),
                        self.body.index("TRAINER_DEFEAT_COUNT_LOCATION_NAME_SET"))


if __name__ == "__main__":
    unittest.main()
