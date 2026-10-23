"""ADDENDUM 406 (2026-10-03) -- the Mt. Battle goal, the Data ROM, the mandatory rematches, and adjust-don't-refuse.

The Mt. Battle goal was sending the clear when 100 trainers were defeated, NOT when the last Mt. Battle trainer
was defeated; victory is sent when the final trainer is defeated. The Poke Spots do NOT need the Data ROM. The
Cipher Lab is not gated by the Data ROM either -- only Lovrina, her defeat item, and chest 23 are. Naps #2 is also
gated there and is a mandatory fight, so the mandatory/non-missable rematches are still counted. Invalid settings
are auto-adjusted to valid ones instead of refused.

THE GOAL. Mt. Battle's 100th and final trainer is Mt. Btlmaster Battlus (Bulbapedia, "Battlus": "the final trainer
at Mt. Battle"; index 100 decodes out of the ISO as BATTLUS). Two things made the goal fire on the 100th defeat of
anyone instead: (1) `exclude_mt_battle_trainers`, on by default, dropped BATTLUS before the tracker looked at him,
so the surname path could never fire; (2) the backstop then armed on MIRU -- who is ALSO story trainer 30 -- and
fired 99 defeats later. The backstop is gone, Battlus is watched through the exclusion (confirmed, never counted
or sent), and the story-byte win no longer completes a Mt. Battle seed.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from BaseClasses import CollectionState

from . import PokemonXDTestBase
from .. import ram_client
from ..game_data import chest_regions, trainer_placements, trainer_roster
from ..game_data.mtbattle_trainer_data import MT_BATTLE_FINAL_TRAINER_SURNAMES, MT_BATTLE_ONLY_SURNAMES

CLIENT = (Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")


def _rec(surname: str, species: str, hp: int) -> "ram_client.BattleRosterRecord":
    return ram_client.BattleRosterRecord(address=0, trainer_name=surname, species_name=species, current_hp=hp)


def _count(n: int) -> str:
    return f"Defeat {n} Trainers"


def _win(tracker, queue, surname, species, **kwargs) -> "list[str]":
    """One confirmed kill: clear, baseline, drop to 0, confirm on a second 0 -- returns the confirming poll."""
    tracker.poll(queue, _count, records=[], **kwargs)
    tracker.poll(queue, _count, records=[_rec(surname, species, 20)], **kwargs)
    tracker.poll(queue, _count, records=[_rec(surname, species, 0)], **kwargs)
    return tracker.poll(queue, _count, records=[_rec(surname, species, 0)], **kwargs)


class TestBattlusIsTheFinalTrainer(unittest.TestCase):
    def test_his_name_is_the_one_the_goal_watches(self) -> None:
        self.assertEqual("BATTLUS", MT_BATTLE_FINAL_TRAINER_SURNAMES[0])
        self.assertIn("BATTLUS", MT_BATTLE_ONLY_SURNAMES, "the exclusion really does cover him by default")


class TestConfirmOnly(unittest.TestCase):
    def test_an_excluded_final_trainer_is_still_seen(self) -> None:
        tracker = ram_client.TrainerBattleDefeatTracker()
        done = _win(tracker, {}, "BATTLUS", "Metagross",
                    exclude_surnames=MT_BATTLE_ONLY_SURNAMES, confirm_only_surnames={"BATTLUS"})
        self.assertEqual(["BATTLUS"], tracker.last_confirmed_surnames)
        self.assertEqual([], done, "seen for the goal, never a check")
        self.assertEqual(0, tracker.defeat_count, "and never a count")

    def test_without_it_he_was_invisible(self) -> None:
        """The bug, kept as a witness."""
        tracker = ram_client.TrainerBattleDefeatTracker()
        _win(tracker, {}, "BATTLUS", "Metagross", exclude_surnames=MT_BATTLE_ONLY_SURNAMES)
        self.assertEqual([], tracker.last_confirmed_surnames)


class TestTheClientGoal(unittest.TestCase):
    def setUp(self) -> None:
        self.body = CLIENT.split("async def check_trainer_defeats", 1)[1].split("\n# The roster holds THREE", 1)[0]

    def test_no_running_count_backstop(self) -> None:
        self.assertNotIn("mt_battle_target_defeat_count", self.body)
        self.assertNotIn("MT_BATTLE_FIRST_TRAINER_SURNAME in", self.body)

    def test_battlus_is_watched_through_the_exclusion(self) -> None:
        """With the Mt. Battle option on, his win is neither counted nor sent, but the goal still sees it."""
        from ..ap_patch import PatchDefeatTracker
        from ..game_data.battle_index import BATTLE_OPPONENTS, MT_BATTLE_DECK

        battlus = next(b for b, opponent in BATTLE_OPPONENTS.items() if opponent == (MT_BATTLE_DECK, 100))
        tracker = PatchDefeatTracker()
        sent = tracker.poll([battlus], {}, lambda n: f"Defeat {n} Trainers", exclude_mt_battle=True)
        self.assertEqual([], sent)
        self.assertEqual(0, tracker.defeat_count)
        self.assertIn("BATTLUS", tracker.wins_by_surname)
        self.assertIn("MT_BATTLE_FINAL_TRAINER_SURNAMES", self.body)
        self.assertIn("exclude_mt_battle=ctx.exclude_mt_battle_trainers", self.body)

    def test_a_seed_without_defeat_checks_still_watches_for_the_goal(self) -> None:
        self.assertIn("goal_watch_only = not ctx.shuffle_trainer_defeats", self.body)
        self.assertIn("if goal_watch_only and (ctx.goal != 1 or ctx.finished_game):", self.body)
        self.assertIn("newly_completed = []", self.body)

    def test_the_story_ending_is_only_the_greevil_goals_win(self) -> None:
        body = CLIENT.split("async def check_victory_story_byte", 1)[1].split("\nasync def ", 1)[0]
        self.assertIn("if ctx.goal != 0:", body)


class TestTheMandatoryRematchesCount(unittest.TestCase):
    """Labels fire on the Nth distinct team, and a missable fight's team still counts toward N.

    ADDENDUM 409: Aferd was this class's example (#1 missable, #2-#5 mandatory). Aferd's rematches
    were then removed, so his queue is empty and his wins check nothing off. Laken's #2 and #3 have since gone the
    same way (numbered rematch checks are removed outside the forced second fights), so his queue is empty too and
    his wins check off no numbered label."""

    QUEUE = {
        "AFERD": trainer_roster.UNIQUE_SURNAME_TO_LOCATION_QUEUE["AFERD"],
        "LAKEN": trainer_roster.UNIQUE_SURNAME_TO_LOCATION_QUEUE["LAKEN"],
    }

    def _fight(self, surname, teams):
        tracker = ram_client.TrainerBattleDefeatTracker()
        sent = []
        for species in teams:
            sent += [n for n in _win(tracker, self.QUEUE, surname, species) if n.startswith("Defeat - ")]
        return sent

    def test_the_queue(self) -> None:
        # ADDENDUM 409: Aferd's rematches are removed -- #2-#5 are in RULED_OUT_DEFEAT_LOCATIONS, and #1 was
        # already gone (missable).
        self.assertEqual([], self.QUEUE["AFERD"])
        for n in (2, 3, 4, 5):
            self.assertIn(f"Defeat - Aferd #{n}", trainer_roster.RULED_OUT_DEFEAT_LOCATIONS)
        # Numbered rematch checks are removed for Laken too (no forced second fight): his queue is empty and his
        # (Any) is the check.
        self.assertEqual([], self.QUEUE["LAKEN"])
        for n in (2, 3):
            self.assertIn(f"Defeat - Laken #{n}", trainer_roster.NUMBERED_REMATCH_DEFEAT_LOCATIONS)
        self.assertIn("Defeat - Laken #1", trainer_roster.REMOVED_MISSABLE_DEFEAT_LOCATIONS)

    def test_aferds_wins_check_nothing_off_now(self) -> None:
        # ADDENDUM 409: "Remove Aferd's rematches." Five distinct wins, no numbered check.
        self.assertEqual([], self._fight("AFERD", ["Pidgey", "Rattata", "Zubat", "Geodude", "Onix"]))

    def test_skipping_the_missable_fight_costs_nothing(self) -> None:
        self.assertEqual(self.QUEUE["LAKEN"], self._fight("LAKEN", ["Rattata", "Zubat"]))

    def test_fighting_it_too_only_earns_them_sooner(self) -> None:
        self.assertEqual(self.QUEUE["LAKEN"], self._fight("LAKEN", ["Pidgey", "Rattata", "Zubat"]))

    def test_naps_two_is_a_check_and_never_was_removed(self) -> None:
        self.assertIn("Defeat - Naps #2", trainer_roster.UNIQUE_SURNAME_TO_LOCATION_QUEUE["NAPS"])
        self.assertNotIn("Defeat - Naps #2", trainer_roster.REMOVED_MISSABLE_DEFEAT_LOCATIONS)


ROM_FREE_REGIONS_VANILLA = frozenset({"Pokemon HQ Lab", "Kaminko's House", "Gateon Port", "Agate Village",
                                      "Relic Forest", "Mt. Battle", "Cipher Lab"})
MENU_BUCKETS = frozenset({"Pokemon Storage", "Shadow Pokemon Purification", "Trainer Defeat Count",
                          "Unique Trainer Defeats"})


class TestWhatTheDataRomGates(PokemonXDTestBase):
    options = {"key_item_shuffle": True, "shuffle_trainer_defeats": True}

    def test_exactly_the_cipher_lab_set(self) -> None:
        state = CollectionState(self.multiworld)
        for item in self.multiworld.itempool:
            if item.player == self.player and item.name != "Data ROM & ID Card":
                state.collect(item, True)
        state.sweep_for_advancements()
        blocked = {l.name for l in self.multiworld.get_locations(self.player)
                   if l.address is not None and not l.can_reach(state)}
        # Lovrina #1 is no longer a location; her (Any) anchors on that fight and carries its gate.
        for name in ("Defeat Lovrina (Any)", "Lovrina Defeat Item", "Cipher Lab Krane Chest", "Defeat - Naps #2"):
            self.assertIn(name, blocked, name)
        self.assertTrue(state.can_reach("Cipher Lab", player=self.player))
        region_of = {l: self.multiworld.get_location(l, self.player).parent_region.name for l in blocked}
        if self.multiworld.worlds[self.player].options.randomize_travel_locations:
            self.assertFalse({l for l in blocked if region_of[l] in ("Poke Spots", "Pyrite Town", "Pyrite Town (ONBS)")})
            self.assertTrue(state.can_reach("Poke Spots", player=self.player))
            return
        # ADDENDUM 418, travel shuffle off: Pyrite and everything past it, which is EVERYTHING EXCEPT Agate,
        # Gateon, Mt. Battle and the Cipher Lab.
        self.assertFalse(state.can_reach("Pyrite Town", player=self.player))
        self.assertFalse(state.can_reach("Poke Spots", player=self.player))
        for location in self.multiworld.get_locations(self.player):
            if location.address is None or location.parent_region.name in ROM_FREE_REGIONS_VANILLA:
                continue
            if location.parent_region.name in MENU_BUCKETS:
                continue
            # ADDENDUM 435 made Citadark Parts-only off Gateon with travel shuffle off, so it is ROM-free whenever
            # the Parts are in this state -- every seed the story weight left unbound (about 15%).
            if location.parent_region.name == "Citadark Isle" and state.can_reach("Citadark Isle", player=self.player):
                continue
            self.assertIn(location.name, blocked, f"{location.name} ({location.parent_region.name})")

    def test_the_tables_say_so(self) -> None:
        self.assertEqual(("Data ROM", "ID Card"), chest_regions.CHEST_ITEM_GATES[17])
        self.assertEqual(("Data ROM", "ID Card"), chest_regions.CHEST_ITEM_GATES[23])
        self.assertEqual(("Data ROM", "ID Card"), trainer_placements.PLACEMENTS[61].required_items)  # Lovrina #1
        self.assertEqual(("ID Card",), trainer_placements.PLACEMENTS[60].required_items)             # Naps #2


class TestTravelShuffleToo(TestWhatTheDataRomGates):
    options = {"key_item_shuffle": True, "shuffle_trainer_defeats": True, "randomize_travel_locations": True}


if __name__ == "__main__":
    unittest.main()
