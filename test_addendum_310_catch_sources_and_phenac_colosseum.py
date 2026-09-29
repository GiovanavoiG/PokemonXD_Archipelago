"""ADDENDUM 310 -- catch-location sources in hints and !catches; Phenac Colosseum chests 1-3 behind the Sixes.

Player: "for Catch - Luvdisc etc, can we add the trainer that received them & the location to the check name so
that the players know where it's at? Also, Phenac colosseum chest 1 2 and 3 should be locked behind music disc
and mayor's note - currently they are not"."""
import unittest

from . import PokemonXDTestBase
from .. import catch_sources, locations, species
from ..game_data import chest_regions

COLOSSEUM_CHESTS = (89, 90, 91)


class TestTheColosseumGateIsData(unittest.TestCase):
    def test_each_chest_is_region_gated_on_post_sixes(self) -> None:
        for chest in COLOSSEUM_CHESTS:
            self.assertEqual(("Phenac City (Post-Sixes)",), chest_regions.CHEST_REGION_GATES.get(chest))

    def test_not_self_gating(self) -> None:
        """The Disc (80) and Note (78) live elsewhere; the chests gated here must not be them."""
        self.assertNotIn(80, COLOSSEUM_CHESTS)
        self.assertNotIn(78, COLOSSEUM_CHESTS)


class _ColosseumInAWorld:
    def _state(self, held):
        from BaseClasses import CollectionState
        state = CollectionState(self.multiworld)
        for name in held:
            state.collect(self.multiworld.worlds[1].create_item(name), prevent_sweep=True)
        state.sweep_for_advancements()
        return state

    def _chests(self):
        names = {locations.CHEST_ID_TO_LOCATION[c] for c in COLOSSEUM_CHESTS}
        found = [l for l in self.multiworld.get_locations(1) if l.name in names]
        self.assertEqual(3, len(found))
        return found

    def test_closed_without_the_note(self) -> None:
        state = self._state(["Machine Part", "Data ROM & ID Card", "Music Disc"])
        for location in self._chests():
            self.assertFalse(location.can_reach(state), location.name)

    def test_closed_without_the_disc(self) -> None:
        state = self._state(["Machine Part", "Data ROM & ID Card", "Mayor's Note"])
        for location in self._chests():
            self.assertFalse(location.can_reach(state), location.name)

    def test_open_with_both(self) -> None:
        state = self._state(["Machine Part", "Data ROM & ID Card", "Music Disc", "Mayor's Note"])
        for location in self._chests():
            self.assertTrue(location.can_reach(state), location.name)


class TestColosseumKeyItemsShuffled(_ColosseumInAWorld, PokemonXDTestBase):
    options = {"key_item_shuffle": True}


class TestColosseumKeyItemsVanilla(PokemonXDTestBase):
    """With the Disc and Note unshuffled they are not pool items -- the region gate must still hold, which is why
    it is a region gate and not an item gate."""
    options = {"key_item_shuffle": False}

    def test_chests_are_no_earlier_than_post_sixes(self) -> None:
        from BaseClasses import CollectionState
        state = CollectionState(self.multiworld)
        post_sixes = self.multiworld.get_region("Phenac City (Post-Sixes)", 1)
        names = {locations.CHEST_ID_TO_LOCATION[c] for c in COLOSSEUM_CHESTS}
        for location in self.multiworld.get_locations(1):
            if location.name in names and not post_sixes.can_reach(state):
                self.assertFalse(location.can_reach(state), location.name)


class TestCatchSources(PokemonXDTestBase):
    options = {
        "key_item_shuffle": True,
        "shadow_pokemon_expansion": 44,
        "randomize_shadow_species": True,
    }

    def _world(self):
        return self.multiworld.worlds[self.player]

    def test_every_created_catch_location_but_eevee_has_a_source(self) -> None:
        texts = catch_sources.sources_by_location(self._world())
        created = [l.name for l in self.multiworld.get_locations(self.player)
                   if l.name.startswith("Catch - ") and l.name not in
                   ("Catch - Eevee", "Catch - Eeveelution (Any)")]
        self.assertTrue(created)
        missing = [n for n in created if n not in texts]
        self.assertEqual([], missing)

    def test_generated_shadows_name_their_host_trainer(self) -> None:
        world = self._world()
        hosts = world._shadow_catch_expansion_hosts
        self.assertTrue(hosts, "the expansion should have placed something at 44")
        dex, indices = next(iter(hosts.items()))
        text = catch_sources.sources_by_dex(world)[dex]
        label = catch_sources._host_label(indices[0])
        self.assertTrue(any(label in t for t in text), (label, text))

    def test_texts_only_describe_this_seeds_locations(self) -> None:
        names = {l.name for l in self.multiworld.get_locations(self.player)}
        for name in catch_sources.sources_by_location(self._world()):
            self.assertIn(name, names)

    def test_hint_information_is_keyed_by_location_id(self) -> None:
        hint_data = {}
        self._world().extend_hint_information(hint_data)
        by_id = hint_data[self.player]
        name = species.location_name_for_species(next(iter(self._world()._shadow_catch_expansion_hosts)))
        location = self.multiworld.get_location(name, self.player)
        self.assertIn(location.address, by_id)
        self.assertTrue(by_id[location.address].startswith("Shadow: "))

    def test_slot_data_carries_it(self) -> None:
        slot_data = self._world().fill_slot_data()
        self.assertEqual(catch_sources.sources_by_location(self._world()), slot_data["catch_sources"])


if __name__ == "__main__":
    unittest.main()
