"""ADDENDUM 407 (2026-10-03) -- mandatory rematches can hold items, Pyrite is one level tier, the Unown PID watch.

Player: "Make the mandatory rematches able to hold progressive/useful. ... please make sure that pyrite visit 1 and
2 are the same level scaling, rather than separated. Also, a user reported an Unown L turning into an Unown D upon
purification. Check the code/fields and see if you can figure out how this happened."
"""
from __future__ import annotations

import unittest

from BaseClasses import LocationProgressType

from . import PokemonXDTestBase
from .. import ram_client as rc
from ..game_data import missable_trainers as mt, trainer_roster as tr
from ..randomizer import path_level_scaling as pls

ON = ["Defeat - Naps #2"]
# Player: "Cids 2 and Sixes 2 should be filler only. Naps is the only one I guess that needed changed."
# ADDENDUM 409: six of the original ten are no longer locations at all -- "Remove all of cida,clerr,belish,dosk, and
# hebon's rematches. Remove Aferd's rematches. ... Remove Finol, Dert, Raling, Labet and Doby's rematches." and,
# for the Sixes, "Remove all their other fights" (Browsix #4). The Sixes' #2 stays ("make their #2 at Phenac
# (missable, behind disc and note)") and is still filler-only; Laken and Zook were not in the ruling.
HELD = ["Defeat - Resix #2", "Defeat - Greesix #2", "Defeat - Laken #3"]   # ADDENDUM 436: Zook #2 is not a check
RULED_OUT = ["Defeat - Cida #2", "Defeat - Aferd #2", "Defeat - Hebon #2", "Defeat - Browsix #4",
             "Defeat - Dosk #2", "Defeat - Finol #2"]


class TestTheAllowlist(unittest.TestCase):
    def test_only_naps_two(self) -> None:
        names = {tr.trainer_label(tr.TRAINERS_BY_INDEX[i]) for i in mt.MANDATORY_REMATCH_INDICES}
        self.assertEqual(set(ON), names)

    def test_the_progression_fence_is_the_old_one_minus_them(self) -> None:
        self.assertEqual(mt.FILLER_ONLY_TRAINER_INDICES, mt.UNREDOABLE_TRAINER_INDICES - mt.MANDATORY_REMATCH_INDICES)

    def test_shadow_expansion_still_avoids_them(self) -> None:
        """A Shadow on a re-fightable fight is the infinite catch (ADDENDUM 236) -- unchanged by this."""
        self.assertTrue(mt.MANDATORY_REMATCH_INDICES <= mt.shadow_expansion_excluded_trainer_indices())


class TestInAGeneratedWorld(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "key_item_shuffle": True}

    def test_the_eight_can_hold_progression(self) -> None:
        for name in ON:
            self.assertEqual(LocationProgressType.DEFAULT,
                             self.multiworld.get_location(name, self.player).progress_type, name)

    def test_the_held_back_ones_cannot(self) -> None:
        for name in HELD:
            self.assertEqual(LocationProgressType.EXCLUDED,
                             self.multiworld.get_location(name, self.player).progress_type, name)

    def test_the_ruled_out_ones_are_not_locations(self) -> None:
        # ADDENDUM 409: the player removed these checks by name; they cannot hold anything because they do not exist.
        created = {location.name for location in self.multiworld.get_locations(self.player)}
        for name in RULED_OUT:
            self.assertIn(name, tr.RULED_OUT_DEFEAT_LOCATIONS, name)
            self.assertNotIn(name, created, name)

    def test_naps_two_still_needs_the_id_card(self) -> None:
        from BaseClasses import CollectionState

        state = CollectionState(self.multiworld)
        for item in self.multiworld.itempool:
            if item.player == self.player and item.name != "Data ROM & ID Card":
                state.collect(item, True)
        state.sweep_for_advancements()
        self.assertFalse(self.multiworld.get_location("Defeat - Naps #2", self.player).can_reach(state))


class TestPyriteIsOneTier(unittest.TestCase):
    def test_both_visits_share_a_rung(self) -> None:
        known = set(pls.region_by_trainer_index().values())
        tiers = pls.path_tiers(known)
        self.assertEqual(pls.tier_index("Pyrite Town", tiers, known),
                         pls.tier_index("Pyrite Town (ONBS)", tiers, known))
        self.assertEqual(12, len(tiers))

    def test_every_pyrite_fight_gets_one_level(self) -> None:
        levels = pls.level_by_trainer_index()
        regions = pls.region_by_trainer_index()
        pyrite = {levels[i] for i, region in regions.items()
                  if region in ("Pyrite Town", "Pyrite Town (ONBS)") and i in levels}
        self.assertEqual(1, len(pyrite), pyrite)


def _record(shadow_id: int, pid: int, purified: bool, dex: int = rc.UNOWN_DEX) -> "rc.ShadowRecord":
    return rc.ShadowRecord(source="party", slot=0, dex=dex, shadow_id=shadow_id,
                           purified_flag=rc.PURIFIED_FLAG_VALUE if purified else 0, level=30,
                           trainer_id=0x12345678, pid=pid, cur_hp=50, max_hp=60)


class TestUnownLetters(unittest.TestCase):
    def test_the_generation_three_formula(self) -> None:
        self.assertEqual("A", rc.unown_letter(0x00000000))
        self.assertEqual("B", rc.unown_letter(0x00000001))
        self.assertEqual("E", rc.unown_letter(0x00000100))
        self.assertEqual("L", rc.unown_letter(0x00000203))      # 2<<2 | 3 = 11
        self.assertEqual("D", rc.unown_letter(0x00000003))
        self.assertEqual("N", rc.unown_letter(0x01000101))      # 64+4+1 = 69, % 28 = 13
        self.assertEqual("?", rc.unown_letter(0x00010203))      # 16+8+3 = 27

    def test_every_value_maps_into_the_28_forms(self) -> None:
        letters = {rc.unown_letter(p) for p in range(0, 1 << 16, 7)} | {rc.unown_letter(p << 16) for p in range(256)}
        self.assertTrue(letters <= set(rc.UNOWN_LETTERS))


class TestThePidWatch(unittest.TestCase):
    def setUp(self) -> None:
        self.tracker = rc.PurificationCountTracker()

    def _scan(self, *records):
        self.tracker.observe_records(list(records))
        return list(self.tracker.new_pid_changes)

    def test_a_pid_kept_through_purification_says_nothing(self) -> None:
        self._scan(_record(7, 0x00000203, purified=False))
        self.assertEqual([], self._scan(_record(7, 0x00000203, purified=True)))

    def test_a_changed_pid_is_reported_once_with_the_letters(self) -> None:
        self._scan(_record(7, 0x00000203, purified=False))
        lines = self._scan(_record(7, 0x00000003, purified=True))
        self.assertEqual(1, len(lines))
        self.assertIn("Unown L -> D", lines[0])
        self.assertEqual([], self._scan(_record(7, 0x00000003, purified=True)), "reported once")
        self.assertTrue(any("CHANGED at purification" in line for line in self.tracker.describe()))

    def test_it_never_changes_the_count(self) -> None:
        self._scan(_record(7, 0x00000203, purified=False))
        before = self.tracker.total_purified
        self._scan(_record(7, 0x00000003, purified=True))
        self._scan(_record(7, 0x00000003, purified=True))
        self.assertEqual(before + 1, self.tracker.total_purified, "the purification still counts, exactly once")

    def test_it_survives_a_reconnect(self) -> None:
        self._scan(_record(7, 0x00000203, purified=False))
        restored = rc.PurificationCountTracker()
        restored.load_json(self.tracker.to_json())
        self.assertEqual({7: 0x00000203}, restored.snag_pids)
        restored.observe_records([_record(7, 0x00000003, purified=True)])
        self.assertTrue(restored.new_pid_changes)


if __name__ == "__main__":
    unittest.main()


class TestMisfiledItems(unittest.TestCase):
    """ADDENDUM 408: the "No256 in the TMs tab" report. Detection only -- it names what is where."""

    def _bag(self, shared: "dict[int, tuple[int, int]]", items: "dict[int, tuple[int, int]]"):
        def fake_read(base, count):
            table = shared if base == 0x1000 + rc.POKEBALL_POCKET_OFFSET else items
            return [rc.BagSlot(i, base + i * 4, *table.get(i, (0, 0))) for i in range(count)]
        return fake_read

    def test_a_healing_item_in_the_tm_tab_is_named(self) -> None:
        from unittest import mock

        shared = {16: (289, 1), 23: (19, 1), 85: (150, 2)}      # TM01, Full Restore in the TM tab, a berry
        with mock.patch.object(rc, "read_pocket", self._bag(shared, {0: (13, 5)})):
            found = rc.find_misfiled_items(0x1000)
        self.assertEqual([("TMs", 7, 19, 1)], found)

    def test_a_tm_in_the_items_pocket_is_named(self) -> None:
        from unittest import mock

        with mock.patch.object(rc, "read_pocket", self._bag({}, {3: (300, 1)})):
            self.assertEqual([("Items", 3, 300, 1)], rc.find_misfiled_items(0x1000))

    def test_a_clean_bag_says_nothing(self) -> None:
        from unittest import mock

        with mock.patch.object(rc, "read_pocket", self._bag({0: (4, 10), 20: (300, 1), 90: (160, 1)},
                                                            {0: (19, 2)})):
            self.assertEqual([], rc.find_misfiled_items(0x1000))
