"""ADDENDUM 415 (2026-10-04) -- a Purify check per Shadow, a toggle for all of them, and the Greevil goal.

Defeat Greevil 2 is the goal, and having ever defeated Greevil twice also sends the victory. The purification
check count is raised, and an option (above the purification count) turns purifications as a whole on or off as
checks.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from BaseClasses import CollectionState

from . import PokemonXDTestBase
from .. import locations as L, options as O, ram_client as rc
from ..game_data import trainer_roster as tr

CLIENT = (Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")


def _purifies(test) -> "list[int]":
    return sorted(L.PURIFICATION_LOCATION_TO_COUNT[l.name] for l in test.multiworld.get_locations(test.player)
                  if l.name in L.PURIFICATION_LOCATION_TO_COUNT)


class TestTheTable(unittest.TestCase):
    def test_one_name_per_shadow_a_seed_can_hold(self) -> None:
        self.assertEqual(83 + O.ShadowPokemonExpansion.range_end, L.PURIFICATION_LOCATION_COUNT)
        self.assertEqual(127, L.PURIFICATION_LOCATION_COUNT)
        self.assertEqual(O.PurificationProgressionCap.range_end, L.PURIFICATION_LOCATION_COUNT)
        for n in range(1, 128):
            self.assertIn(L.purification_location_name(n), L.LOCATION_TABLE)

    def test_the_old_32_kept_their_ids_and_the_new_ones_are_frozen(self) -> None:
        self.assertEqual(635, L._FROZEN_LOCATION_OFFSETS["Purify 32 Shadow Pokemon"])
        self.assertEqual(1692, L.LOCATION_TABLE["Purify 33 Shadow Pokemon"].id_offset)
        self.assertEqual(1786, L.LOCATION_TABLE["Purify 127 Shadow Pokemon"].id_offset)

    def test_the_client_agrees(self) -> None:
        self.assertEqual(L.PURIFICATION_LOCATION_COUNT, rc.PURIFICATION_LOCATION_COUNT)

    def test_the_option_sits_above_the_cap(self) -> None:
        names = list(O.PokemonXDOptions.type_hints)
        self.assertEqual(names.index("purification_checks") + 1, names.index("purification_progression_cap"))
        self.assertTrue(O.PurificationChecks.default)


class TestVanilla(PokemonXDTestBase):
    options = {"shadow_pokemon_expansion": 0}

    def test_eighty_three(self) -> None:
        # RETARGETED BY ADDENDUM 479: 75 -- Greevil's seven and Miror B.'s post-game Dragonite have no rungs.
        self.assertEqual(list(range(1, 76)), _purifies(self))


class TestFullExpansion(PokemonXDTestBase):
    options = {"shadow_pokemon_expansion": 44, "purification_progression_cap": 127}

    def test_one_per_shadow_the_seed_really_holds(self) -> None:
        world = self.multiworld.worlds[self.player]
        self.assertGreater(world._purification_location_count, 83)
        self.assertEqual(list(range(1, world._purification_location_count + 1)), _purifies(self))

    def test_every_one_is_reachable_with_everything(self) -> None:
        state = CollectionState(self.multiworld)
        for item in self.multiworld.itempool:
            if item.player == self.player:
                state.collect(item, prevent_sweep=True)
        state.sweep_for_advancements()
        for n in _purifies(self):
            self.assertTrue(self.multiworld.get_location(L.purification_location_name(n), self.player)
                            .can_reach(state), n)

    def test_past_the_vanilla_83_needs_every_shadow_region(self) -> None:
        location = self.multiworld.get_location(L.purification_location_name(84), self.player)
        self.assertFalse(location.can_reach(CollectionState(self.multiworld)))


class TestTheToggleOff(PokemonXDTestBase):
    options = {"purification_checks": False, "shadow_pokemon_expansion": 20}

    def test_no_purification_checks_at_all(self) -> None:
        self.assertEqual([], _purifies(self))


class TestTheClientHonoursTheToggle(unittest.TestCase):
    def test_it_sends_nothing_with_the_toggle_off(self) -> None:
        self.assertIn("if newly_crossed and ctx.purification_checks:", CLIENT)
        self.assertIn('slot_data.get("purification_checks", True)', CLIENT)


class TestTheGreevilGoal(unittest.TestCase):
    def setUp(self) -> None:
        body = CLIENT.split("_GREEVIL_REMATCH_LOCATION_NAMES", 1)[1].split("\nasync def ", 1)[0]
        self.names = {n for n in tr.UNIQUE_SURNAME_TO_LOCATION_QUEUE["GREEVIL"] if not n.endswith("#1")}
        self.body = body

    def test_unique_mode_relies_on_the_win_count_not_a_greevil_two_label(self) -> None:
        # "Defeat - Greevil #2" is a numbered rematch check and no longer exists, so the unique queue contributes
        # no label; the goal rests on the win count by surname (and the story-byte backup).
        self.assertNotIn("Defeat - Greevil #2", self.names)
        self.assertIn("Defeat - Greevil #2", tr.REMOVED_DEFEAT_LOCATIONS)
        self.assertIn('UNIQUE_SURNAME_TO_LOCATION_QUEUE.get("GREEVIL"', self.body)
        self.assertIn('wins_by_surname or {}).get("GREEVIL", 0) >= GREEVIL_WINS_FOR_GOAL', CLIENT)

    def test_two_wins_is_enough(self) -> None:
        self.assertIn("GREEVIL_WINS_FOR_GOAL = 2", CLIENT)
        self.assertIn('wins_by_surname or {}).get("GREEVIL", 0) >= GREEVIL_WINS_FOR_GOAL', CLIENT)
        self.assertIn("ctx.trainer_defeat_tracker.wins_by_surname", CLIENT)


class TestTheWinCount(unittest.TestCase):
    def _win(self, tracker, species):
        rec = lambda hp: rc.BattleRosterRecord(address=0, trainer_name="GREEVIL",  # noqa: E731
                                              species_name=species, current_hp=hp)
        for records in ([], [rec(30)], [rec(0)], [rec(0)]):
            tracker.poll({}, lambda n: "", records=records, count_location_max=0)

    def test_every_win_counts_rematches_included(self) -> None:
        tracker = rc.TrainerBattleDefeatTracker()
        self._win(tracker, "Hitmontop")
        self.assertEqual(1, tracker.wins_by_surname["GREEVIL"])
        self._win(tracker, "Hitmontop")                   # the same team again still counts as a win
        self.assertEqual(2, tracker.wins_by_surname["GREEVIL"])

    def test_it_survives_a_reconnect(self) -> None:
        tracker = rc.TrainerBattleDefeatTracker()
        self._win(tracker, "Hitmontop")
        restored = rc.TrainerBattleDefeatTracker()
        restored.load_json(tracker.to_json())
        self.assertEqual(1, restored.wins_by_surname["GREEVIL"])
        restored.load_json({"wins": {"GREEVIL": "x"}, "beaten_teams": {}})   # junk degrades, never raises
        self.assertEqual(1, restored.wins_by_surname["GREEVIL"])


if __name__ == "__main__":
    unittest.main()
