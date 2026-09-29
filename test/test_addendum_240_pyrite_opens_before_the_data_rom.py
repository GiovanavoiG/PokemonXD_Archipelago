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
        self.assertIn(("Pyrite Town", "Poke Spots", ("Data ROM",)), world_regions.REGION_EDGES)
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

    def test_only_the_shop_expansion_is_held_back_in_plain_pyrite(self) -> None:
        """The whole of plain Pyrite opens with the town, EXCEPT the two shop lines the ONBS crisis adds --
        which are held by their own tier rule, not by the room."""
        plain, _onbs = self._by_region()
        no_rom = self._state(["Machine Part"])
        blocked = sorted(l.name for l in plain if not l.can_reach(no_rom))
        self.assertEqual(blocked, ["Pyrite Town Shop AP Item 11", "Pyrite Town Shop AP Item 12"])

    def test_every_onbs_location_still_needs_the_rom(self) -> None:
        _plain, onbs = self._by_region()
        self.assertTrue(onbs)
        no_rom = self._state(["Machine Part"])
        with_rom = self._state(["Machine Part", "Data ROM & ID Card"])
        for location in onbs:
            self.assertFalse(location.can_reach(no_rom), location.name)
            self.assertTrue(location.can_reach(with_rom), location.name)

    def test_the_chests_split_exactly_as_described(self) -> None:
        """Player: "Any chests in ONBS are gated behind the data rom/id card - every other chest is ONLY gated
        behind pyrite town." """
        plain, onbs = self._by_region()
        no_rom = self._state(["Machine Part"])
        plain_chests = [l for l in plain if "Chest" in l.name]
        onbs_chests = [l for l in onbs if "Chest" in l.name]
        self.assertTrue(plain_chests and onbs_chests)
        for location in plain_chests:
            self.assertTrue(location.can_reach(no_rom), location.name)
        for location in onbs_chests:
            self.assertFalse(location.can_reach(no_rom), location.name)

    def test_the_vending_machine_and_the_first_shelf_open_with_the_town(self) -> None:
        no_rom = self._state(["Machine Part"])
        for name in ([f"Pyrite Vending Machine AP Item {n}" for n in range(1, 5)]
                     + [f"Pyrite Town Shop AP Item {n}" for n in range(1, 11)]):
            self.assertTrue(self.multiworld.get_location(name, 1).can_reach(no_rom), name)

    def test_the_expansion_gate_now_binds(self) -> None:
        """ADDENDUM 239b recorded this gate as non-binding -- it opened with its room, because the room needed
        the ROM too. That is no longer true, so the tier rule is now the only thing holding these two."""
        no_rom = self._state(["Machine Part"])
        with_rom = self._state(["Machine Part", "Data ROM & ID Card"])
        for name in ("Pyrite Town Shop AP Item 11", "Pyrite Town Shop AP Item 12"):
            location = self.multiworld.get_location(name, 1)
            self.assertFalse(location.can_reach(no_rom), name)
            self.assertTrue(location.can_reach(with_rom), name)

    def test_addendum_211s_cipher_gate_is_untouched(self) -> None:
        """The regression that would matter most if this change were wrong."""
        no_rom = self._state(["Machine Part"])
        self.assertFalse(self.multiworld.state.__class__(self.multiworld) and
                         no_rom.can_reach("Poke Spots", player=self.player))
        self.assertFalse(no_rom.can_reach("Pyrite Town (ONBS)", player=self.player))
        for location in self.multiworld.get_locations(1):
            if "Cipher" in location.name and "Pyrite" in location.parent_region.name:
                self.assertEqual(location.parent_region.name, "Pyrite Town (ONBS)", location.name)
                self.assertFalse(location.can_reach(no_rom), location.name)


if __name__ == "__main__":
    unittest.main()
