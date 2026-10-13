"""Player, 2026-10-13: "In vanilla locations, are wild catches gated behind Machine Part and Data Rom & ID Card? If not,
they should be" ... "Also, ensure that in vanilla locations, purifications are locked behind the machine part."

Both already held when asked; this pins them. Vanilla travel:
  * wild (Poke Spot) catches need the Poke Spots, which sit behind Pyrite Town (Data ROM & ID Card, ADDENDUM 418), which
    sits behind Agate Village (Machine Part, Gateon -> Agate);
  * every `Purify N` needs Agate Village (the Purify Chamber), which is behind the Machine Part (Gateon -> Agate).
    (ADDENDUM 483: not through the Snag Machine -- the HQ Lab hands that over before the Machine Part.)
"""
from BaseClasses import CollectionState

from . import PokemonXDTestBase
from .. import items, rules, species


class TestVanillaGates(PokemonXDTestBase):
    options = {"randomize_travel_locations": False, "key_item_shuffle": True}

    def _state_without(self, drop):
        state = CollectionState(self.multiworld)
        for item in self.multiworld.itempool:
            if item.player == self.player and item.name not in drop and item.advancement:
                state.collect(item, True)
        return state

    def _wild_catch_locations(self):
        world = self.multiworld.worlds[self.player]
        gates, _ = rules._catch_gates_for_species(world)
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        out = [species.location_name_for_species(dex) for dex, ways in gates.items()
               if ways and all(way == "pokespot" for way in ways)]
        return [name for name in out if name in names]

    def _purify_locations(self):
        return [loc.name for loc in self.multiworld.get_locations(self.player) if loc.name.startswith("Purify ")]

    def test_wild_catches_need_the_machine_part_and_the_data_rom(self) -> None:
        wild = self._wild_catch_locations()
        self.assertTrue(wild)
        for drop in ({"Machine Part"}, {items.COMBINED_KEY_ITEM_NAME}):
            state = self._state_without(drop)
            self.assertFalse(state.can_reach("Poke Spots", player=self.player), drop)
            for name in wild:
                self.assertFalse(self.multiworld.get_location(name, self.player).can_reach(state), (drop, name))

    def test_purifications_need_the_machine_part(self) -> None:
        purify = self._purify_locations()
        self.assertTrue(purify)
        state = self._state_without({"Machine Part"})
        for name in purify:
            self.assertFalse(self.multiworld.get_location(name, self.player).can_reach(state), name)
