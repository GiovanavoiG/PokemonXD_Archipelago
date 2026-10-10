"""ADDENDUM 433 (2026-10-08) -- Biden's uncatchable row, and Citadark under Location Shuffle.

Player: "Biden's KEY LAIR fight is uncatchable. Snagem is fine. Citadark is not gated behind key lair in location
shuffle."
"""
from __future__ import annotations

import unittest

from BaseClasses import CollectionState

from . import PokemonXDTestBase
from .. import items, regions
from ..game_data import missable_trainers, shadow_regions as SR, trainer_placements

PARTS = items.MACGUFFIN_ITEM_NAME


class TestBidensRow(unittest.TestCase):
    def test_the_key_lair_row_is_fenced_and_snagem_is_not(self):
        self.assertIn(148, SR.NO_SNAG_TRAINER_INDICES)
        self.assertNotIn(143, SR.NO_SNAG_TRAINER_INDICES)
        self.assertEqual("Cipher Key Lair (exterior)", trainer_placements.region_for(148))
        self.assertIn(148, missable_trainers.shadow_expansion_excluded_trainer_indices())


class _Base(PokemonXDTestBase):
    def _state(self, drop: "set[str]" = frozenset(), only: "set[str] | None" = None) -> CollectionState:
        state = CollectionState(self.multiworld)
        for item in self.multiworld.itempool:
            if item.player != self.player or not item.advancement:
                continue
            if item.name in drop or (only is not None and item.name not in only):
                continue
            state.collect(item, True)
        state.sweep_for_advancements()
        return state

    def _entrances(self) -> "list[str]":
        return [e.name for e in self.multiworld.get_region("Citadark Isle", self.player).entrances]


class TestShuffleRidesFromGateon(_Base):
    options = {"randomize_travel_locations": True}

    def test_the_ride_is_the_only_way_in(self):
        self.assertEqual(["Gateon Port -> Citadark Isle"], self._entrances())

    def test_the_parts_alone_open_it(self):
        state = self._state(only={PARTS})
        self.assertTrue(state.can_reach_region("Citadark Isle", self.player))

    def test_no_key_lair_unlock_and_no_lever_needed(self):
        state = self._state(drop={"Travel Unlock - Cipher Key Lair", "System Lever"})
        self.assertTrue(state.can_reach_region("Citadark Isle", self.player))
        self.assertFalse(state.can_reach_region("Cipher Key Lair", self.player))

    def test_the_parts_still_gate_it(self):
        self.assertFalse(self._state(drop={PARTS}).can_reach_region("Citadark Isle", self.player))
        # ADDENDUM 430's fence follows the new entrance: no Part can sit on the island.
        world = self.multiworld.worlds[self.player]
        self.assertTrue(world._citadark_reliant_locations)
        self.assertTrue(any(name.startswith("Citadark") or "Citadark" in name
                            for name in world._citadark_reliant_locations))


class TestVanillaKeepsTheChain(_Base):
    options = {"randomize_travel_locations": False}

    def test_the_island_stays_behind_the_key_lair(self):
        """SUPERSEDED by ADDENDUM 435: vanilla travel rides from Gateon with the Parts too."""
        self.assertEqual(["Gateon Port -> Citadark Isle"], self._entrances())
        self.assertTrue(self._state(drop={"System Lever"}).can_reach_region("Citadark Isle", self.player))


class TestShuffleWithoutThePartsGate(_Base):
    options = {"randomize_travel_locations": True, "robo_kyogre_parts_unlock_citadark": False}

    def test_the_story_route_stays(self):
        # No Parts override means no ride from Gateon until the story gets there.
        self.assertEqual(["Cipher Key Lair (deep) -> Citadark Isle"], self._entrances())


class TestTheTable(unittest.TestCase):
    def test_it_names_real_regions(self):
        self.assertEqual({"Citadark Isle": "Gateon Port"}, regions.TRAVEL_SHUFFLE_PARTS_SOURCE)


if __name__ == "__main__":
    unittest.main()
