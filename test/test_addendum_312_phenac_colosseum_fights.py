"""ADDENDUM 312 -- Snattle and Smarton behind the Music Disc and the Mayor's Note, in every mode.

Player: "Entering the colosseum should also be gated behind disc and note - snattle and the smarton fight there
should both be behind those two key items." The gap was travel randomization: SS Libra is flown to directly, and
Smarton's fight (row 128 / the named cumulative location) carried no item requirement of its own."""
from BaseClasses import CollectionState

from . import PokemonXDTestBase
from .. import items

_BASE = ["Machine Part", "Data ROM & ID Card", "System Lever", "Scooter Upgrade"]
_FIGHTS = ("Snattle", "Smarton")


class _Probe:
    def _state(self, extra):
        world = self.multiworld.worlds[self.player]
        names = _BASE + list(extra)
        if self.options.get("randomize_travel_locations"):
            names += list(items.TRAVEL_UNLOCK_ITEMS)
        state = CollectionState(self.multiworld)
        for name in names:
            if name in items.ITEM_TABLE:
                state.collect(world.create_item(name), prevent_sweep=True)
        state.sweep_for_advancements()
        return state

    def _fights(self):
        out = [l for l in self.multiworld.get_locations(self.player)
               if any(k in l.name for k in _FIGHTS) and "#2" not in l.name
               and "Citadark" not in l.name and "Factory" not in l.name]
        self.assertTrue(out)
        return out

    def test_none_open_without_both(self) -> None:
        for held in ([], ["Music Disc"], ["Mayor's Note"]):
            state = self._state(held)
            for location in self._fights():
                self.assertFalse(location.can_reach(state), (held, location.name))

    def test_all_open_with_both(self) -> None:
        state = self._state(["Music Disc", "Mayor's Note"])
        for location in self._fights():
            self.assertTrue(location.can_reach(state), location.name)


class TestUnique(_Probe, PokemonXDTestBase):
    options = {"key_item_shuffle": True}


class TestCumulative(_Probe, PokemonXDTestBase):
    options = {"key_item_shuffle": True, "trainer_defeat_mode": 0}


class TestUniqueTravel(_Probe, PokemonXDTestBase):
    options = {"key_item_shuffle": True, "randomize_travel_locations": True}


class TestCumulativeTravel(_Probe, PokemonXDTestBase):
    options = {"key_item_shuffle": True, "randomize_travel_locations": True, "trainer_defeat_mode": 0}
