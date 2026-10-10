"""ADDENDUM 418 (2026-10-05) -- with travel shuffle off, Pyrite Town and everything past it need the Data ROM.

Player: "Every pyrite town item in vanilla locations should also be gated behind Data Rom & ID Card" ... "As should
everything after pyrite town, which is EVERYTHING EXCEPT agate, gateon, mt battle, and cipher lab"
"""
from __future__ import annotations

import unittest

from BaseClasses import CollectionState

from . import PokemonXDTestBase
from .. import items, regions

ROM = items.COMBINED_KEY_ITEM_NAME
OPEN = frozenset({"Pokemon HQ Lab", "Kaminko's House", "Gateon Port", "Agate Village", "Relic Forest",
                  "Mt. Battle", "Cipher Lab"})
PAST_PYRITE = frozenset(regions.REGION_NAMES) - OPEN - {"Pokemon HQ Lab"}


class TestTheTable(unittest.TestCase):
    def test_one_vanilla_only_edge(self) -> None:
        self.assertEqual({("Cipher Lab", "Pyrite Town"): ("Data ROM",)}, regions.VANILLA_TRAVEL_EDGE_ITEMS)

    def test_region_edges_still_describe_the_game_for_both_modes(self) -> None:
        self.assertIn(("Cipher Lab", "Pyrite Town", ()), regions.REGION_EDGES)


class _Measured(PokemonXDTestBase):
    def _state(self, skip=None):
        state = CollectionState(self.multiworld)
        for item in self.multiworld.itempool:
            if item.player == self.player and item.name != skip:
                state.collect(item, prevent_sweep=True)
        state.sweep_for_advancements()
        return state


class TestVanillaTravel(_Measured):
    options = {"key_item_shuffle": True, "randomize_travel_locations": False, "shuffle_trainer_defeats": True,
               "trainer_defeat_mode": 1, "randomize_shops": True}

    def test_every_region_past_the_lab_needs_the_rom(self) -> None:
        state = self._state(skip=ROM)
        # ADDENDUM 435: Citadark Isle is the Parts-only ride from Gateon now, ROM or no ROM.
        for region in PAST_PYRITE - {"Citadark Isle"}:
            self.assertFalse(state.can_reach(region, "Region", self.player), region)
        for region in OPEN:
            self.assertTrue(state.can_reach(region, "Region", self.player), region)

    def test_every_location_in_them_does_too(self) -> None:
        state = self._state(skip=ROM)
        everything = self._state()
        checked = 0
        for location in self.multiworld.get_locations(self.player):
            if location.address is None or location.parent_region.name not in PAST_PYRITE:
                continue
            if location.parent_region.name == "Citadark Isle":
                continue          # ADDENDUM 435: the Parts-only ride from Gateon, ROM or no ROM
            checked += 1
            self.assertFalse(location.can_reach(state), location.name)
            self.assertTrue(location.can_reach(everything), location.name)
        self.assertGreater(checked, 180)    # ADDENDUM 435: Citadark's locations no longer counted

    def test_the_machine_part_and_the_rom_open_the_town(self) -> None:
        state = CollectionState(self.multiworld)
        for name in ("Machine Part", ROM):
            state.collect(self.multiworld.worlds[self.player].create_item(name), prevent_sweep=True)
        state.sweep_for_advancements()
        for region in ("Pyrite Town", "Poke Spots", "Pyrite Town (ONBS)"):
            self.assertTrue(state.can_reach(region, "Region", self.player), region)


class TestLocationShuffleUnchanged(_Measured):
    """Travel mode keeps ADDENDUM 406: the ROM gates only the lab's own set (and the species found there)."""
    options = {"key_item_shuffle": True, "randomize_travel_locations": True, "shuffle_trainer_defeats": True,
               "trainer_defeat_mode": 1, "randomize_shops": True}

    def test_pyrite_and_past_it_open_without_the_rom(self) -> None:
        state = self._state(skip=ROM)
        for region in ("Pyrite Town", "Poke Spots", "Pyrite Town (ONBS)", "Realgam Tower", "Citadark Isle"):
            self.assertTrue(state.can_reach(region, "Region", self.player), region)
        self.assertTrue(state.can_reach("Citadark Isle - Defeat Cipher Boss", "Location", self.player))


class TestKeyItemsOffIgnoresIt(_Measured):
    """No ROM in the pool, no gate: an edge may only name an item that enters the pool."""
    options = {"key_item_shuffle": False, "randomize_travel_locations": False}

    def test_pyrite_opens_on_the_chain(self) -> None:
        self.assertTrue(self._state().can_reach("Pyrite Town", "Region", self.player))


if __name__ == "__main__":
    unittest.main()
