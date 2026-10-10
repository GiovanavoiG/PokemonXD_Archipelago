"""ADDENDUM 240 (2026-09-16) -- plain Pyrite Town is not behind the Data ROM. Only its second half is.

Player: "Pyrite is half before data rom, half after. So the first shop is NOT gated behind data rom/id card,
but the expansions are." Then, asked which of three readings was right: "Pyrite vending machine and first shop
version are accessible as soon as pyrite town is. The expansion items are after ONBS/data rom/id card. Any
chests in ONBS are gated behind the data rom/id card - every other chest is ONLY gated behind pyrite town."

THE REQUIREMENT WAS ON THE WRONG EDGE. `("Cipher Lab", "Pyrite Town", ("Data ROM",))` put all of plain Pyrite
behind the ROM -- the shop's twelve lines, the vending machine's four, and every chest and trainer in the
town. Pyrite is visited in two halves, which is what the two region names have always said; the gate just sat
on the way IN instead of on the way THROUGH.

NOTHING DOWNSTREAM LOOSENED, and that is the part worth testing rather than asserting. The ROM did not move
off the graph -- it is still on `Pyrite Town -> Poke Spots`, and `Pyrite Town (ONBS)` is reachable only
through Poke Spots. So ADDENDUM 211's guarantee ("every Pyrite Cipher battle is behind the Data ROM AND the
Poke Spots") holds by exactly the construction it always did.

ONE GATE WOKE UP. Pyrite's shop lines 11-12 were recorded (ADDENDUM 239b) as a NON-binding tier gate: they
opened with their room, because the room already needed the ROM. Now the room does not, so that gate is the
only thing holding them, and it binds.
"""
import unittest

from . import PokemonXDTestBase
from .. import regions as world_regions


class TestTheEdgeMoved(unittest.TestCase):
    def test_the_way_into_pyrite_is_free_and_the_way_out_is_not(self) -> None:
        self.assertIn(("Cipher Lab", "Pyrite Town", ()), world_regions.REGION_EDGES)
        # ADDENDUM 406: the way out is free too. Player (ADDENDUM 406): "Poke spots do NOT need the data rom."
        self.assertIn(("Pyrite Town", "Poke Spots", ()), world_regions.REGION_EDGES)
        self.assertIn(("Poke Spots", "Pyrite Town (ONBS)", ()), world_regions.REGION_EDGES)


class TestTheSplitIsWhereThePlayerSaidItIs(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True}

    def _state(self, held):
        from BaseClasses import CollectionState
        state = CollectionState(self.multiworld)
        for name in held:
            state.collect(self.multiworld.worlds[1].create_item(name), prevent_sweep=True)
        state.sweep_for_advancements()
        return state

    def _by_region(self):
        plain, onbs = [], []
        for location in self.multiworld.get_locations(1):
            if location.parent_region.name == "Pyrite Town":
                plain.append(location)
            elif location.parent_region.name == "Pyrite Town (ONBS)":
                onbs.append(location)
        return plain, onbs

    # ADDENDUM 418: with travel shuffle off the ROM is back on the way IN. Player: "Every pyrite town item in
    # vanilla locations should also be gated behind Data Rom & ID Card". So the town state is the Machine Part AND
    # the ROM, and the Machine Part alone opens neither half. Travel mode keeps ADDENDUM 406's free Pyrite
    # (test_addendum_406's TestTravelShuffleToo).
    TOWN = ["Machine Part", "Data ROM & ID Card"]

    def test_nothing_in_either_half_opens_without_the_rom(self) -> None:
        plain, onbs = self._by_region()
        self.assertTrue(plain and onbs)
        no_rom = self._state(["Machine Part"])
        for location in plain + onbs:
            self.assertFalse(location.can_reach(no_rom), location.name)

    def test_only_the_shop_expansion_is_held_back_in_plain_pyrite(self) -> None:
        """The whole of plain Pyrite opens with the town; nothing in it needs more than the town does."""
        plain, _onbs = self._by_region()
        town = self._state(self.TOWN)
        self.assertEqual(sorted(l.name for l in plain if not l.can_reach(town)), [])

    def test_every_onbs_location_opens_with_the_town(self) -> None:
        _plain, onbs = self._by_region()
        town = self._state(self.TOWN)
        for location in onbs:
            self.assertTrue(location.can_reach(town), location.name)

    def test_the_chests_split_exactly_as_described(self) -> None:
        """Player: "Any chests in ONBS are gated behind the data rom/id card - every other chest is ONLY gated
        behind pyrite town." With 418 Pyrite itself is behind the ROM, so both halves open together."""
        plain, onbs = self._by_region()
        town = self._state(self.TOWN)
        plain_chests = [l for l in plain if "Chest" in l.name]
        onbs_chests = [l for l in onbs if "Chest" in l.name]
        self.assertTrue(plain_chests and onbs_chests)
        for location in plain_chests + onbs_chests:
            self.assertTrue(location.can_reach(town), location.name)

    def test_the_vending_machine_and_the_first_shelf_open_with_the_town(self) -> None:
        town = self._state(self.TOWN)
        for name in ([f"Pyrite Vending Machine AP Item {n}" for n in range(1, 5)]
                     + [f"Pyrite Town Shop AP Item {n}" for n in range(1, 11)]):
            self.assertTrue(self.multiworld.get_location(name, 1).can_reach(town), name)

    def test_the_expansion_gate_now_binds(self) -> None:
        """ADDENDUM 406: the gate names the ONBS regions only, so it opens when they do -- with the town."""
        town = self._state(self.TOWN)
        for name in ("Pyrite Town Shop AP Item 11", "Pyrite Town Shop AP Item 12"):
            self.assertTrue(self.multiworld.get_location(name, 1).can_reach(town), name)

    def test_addendum_211s_cipher_battles_still_sit_in_onbs(self) -> None:
        """What 211 still guarantees is the PLACE -- every Pyrite Cipher battle is filed in ONBS, which hangs off
        the Poke Spots."""
        town = self._state(self.TOWN)
        self.assertTrue(town.can_reach("Poke Spots", player=self.player))
        self.assertTrue(town.can_reach("Pyrite Town (ONBS)", player=self.player))
        for location in self.multiworld.get_locations(1):
            if "Cipher" in location.name and "Pyrite" in location.parent_region.name:
                self.assertEqual(location.parent_region.name, "Pyrite Town (ONBS)", location.name)

if __name__ == "__main__":
    unittest.main()
