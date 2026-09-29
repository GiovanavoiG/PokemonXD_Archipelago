"""ADDENDUM 386 (2026-09-28) -- every shiny chest holds filler, widening ADDENDUM 385.

Player: "For now just exclude the ID card 'chest' from progressives." Then, once the control failed:
"I did receive a report that the bonsly shiny didn't fire." -> "Filler them then investigate."

WHAT THE CHEST TABLE SAYS. Every chest carries a model id and there are exactly two of them: 36, the
ordinary box, 90 of them; and 68, the shining object, 25 of them. The player's own name for one of these
locations is `Bonsly Room Shiny Chest`, which is where the word comes from.

Only SIX model-68 objects are ever randomized -- the five key-item chests ADDENDUM 177 punched through
ADDENDUM 134's item-id floor, plus chest 30, whose vanilla contents are ordinary (Leftovers) and so never
needed punching. The other nineteen are fenced out incidentally, by the floor, and have never been
exercised at all.

TWO OF THOSE SIX HAVE INDEPENDENT FAILURE REPORTS. Chest 18 shines in the Cipher Lab and will not be
interacted with; chest 30's check never fires. None of the 89 boxes has a report against it. One theory
covers both symptoms -- the shining object does not read the ItemID this project patches, so chest 30 hands
out its Leftovers (no berry moves, so the berry trigger sees no pickup) and chest 18 hands out its ID Card,
which the player already holds from the packaged AP item, and the game will not give a key item twice.

That theory is UNPROVEN and these tests do not assert it. What they assert is the containment the player
asked for, which holds whatever the cause turns out to be: none of the six may hold anything a seed needs.

DERIVED FROM THE MODEL. ADDENDUM 385 keyed off the one chest id; this keys off `model == 68`, so a chest
that changes model, or a new shiny object that becomes a location, is covered the day the table says so. The
ID Card chest -- the one that started this -- is re-asserted through the model at import.
"""
from __future__ import annotations

import unittest

from BaseClasses import LocationProgressType

from .. import locations as L
from ..game_data import key_item_chests
from ..game_data.chest_table import CHESTS
from . import PokemonXDTestBase


class TestTheClassIsReadOffTheTable(unittest.TestCase):
    def test_there_are_exactly_two_models(self) -> None:
        """If a third ever appears, this exclusion is reasoning about a world that no longer exists."""
        self.assertEqual({36, 68}, {entry["model"] for entry in CHESTS})

    def test_the_shiny_model_is_the_smaller_class(self) -> None:
        shiny = [e for e in CHESTS if e["model"] == L.SHINY_CHEST_MODEL]
        self.assertEqual(25, len(shiny))
        self.assertEqual(90, len(CHESTS) - len(shiny))

    def test_only_six_shiny_objects_are_locations_at_all(self) -> None:
        """The blast radius, stated as a number. Nineteen are fenced out by the item-id floor and one more
        by the excluded rooms, so widening to the whole model costs five locations beyond ADDENDUM 385."""
        self.assertEqual(
            [17, 18, 30, 42, 78, 80],
            sorted(c for c in L.SHINY_CHEST_IDS if c in L.CHEST_ID_TO_LOCATION),
        )

    def test_the_names_are_derived_not_typed(self) -> None:
        self.assertEqual(
            frozenset(L.CHEST_ID_TO_LOCATION[c] for c in L.SHINY_CHEST_IDS
                      if c in L.CHEST_ID_TO_LOCATION),
            L.FILLER_ONLY_CHEST_LOCATIONS,
        )

    def test_the_id_card_chest_is_still_caught(self) -> None:
        """ADDENDUM 385's original target, reached now through the model rather than through its id."""
        id_card_chest = next(c for c, item in key_item_chests.SHUFFLED_KEY_ITEM_CHESTS.items()
                             if item == "ID Card")
        self.assertEqual(18, id_card_chest)
        self.assertIn(L.CHEST_ID_TO_LOCATION[id_card_chest], L.FILLER_ONLY_CHEST_LOCATIONS)

    def test_the_bonsly_shiny_is_caught_too(self) -> None:
        """The one that is not a key-item chest, and the report that widened this."""
        self.assertEqual("Bonsly Room Shiny Chest", L.CHEST_ID_TO_LOCATION[30])
        self.assertIn("Bonsly Room Shiny Chest", L.FILLER_ONLY_CHEST_LOCATIONS)

    def test_no_ordinary_box_is_caught(self) -> None:
        """89 boxes work and must stay progression-eligible. A model test that swept them up would quietly
        halve the progression surface of a seed."""
        boxes = {L.CHEST_ID_TO_LOCATION[e["chest"]] for e in CHESTS
                 if e["model"] == 36 and e["chest"] in L.CHEST_ID_TO_LOCATION}
        self.assertFalse(boxes & L.FILLER_ONLY_CHEST_LOCATIONS)


class TestTheExclusionLands(PokemonXDTestBase):
    """Against a real generated world, because the progress type is set during region creation."""

    options = {"randomize_chests": 1, "key_item_shuffle": 1}

    def _location(self, name: str):
        return self.multiworld.get_location(name, self.player)

    def test_every_shiny_location_exists_and_is_excluded(self) -> None:
        """Excluding is not deleting. A player whose game does open one still gets the check; fill just
        never requires it."""
        for name in L.FILLER_ONLY_CHEST_LOCATIONS:
            self.assertIs(LocationProgressType.EXCLUDED, self._location(name).progress_type, name)

    def test_a_box_in_the_same_room_is_untouched(self) -> None:
        """Room 8 holds both classes: chests 17 and 18 shine, 19/21/22 are boxes. The exclusion follows the
        object, not the room."""
        for chest in (19, 21, 22):
            name = L.CHEST_ID_TO_LOCATION[chest]
            self.assertIsNot(LocationProgressType.EXCLUDED, self._location(name).progress_type, name)

    def test_nothing_required_is_placed_on_any_of_them(self) -> None:
        """The whole point, asserted against fill rather than against the flag."""
        from Fill import distribute_items_restrictive

        distribute_items_restrictive(self.multiworld)
        for name in L.FILLER_ONLY_CHEST_LOCATIONS:
            item = self._location(name).item
            self.assertIsNotNone(item, name)
            self.assertFalse(item.advancement, f"{name} received {item.name}, which the seed may need")


class TestTheKeyItemChestsStillExistWhenShuffleIsOff(PokemonXDTestBase):
    """With key-item shuffle off the five keep their real key items and are not checks, so there is nothing
    to exclude there. Chest 30 is not a key-item chest and stays a location either way -- still excluded."""

    options = {"randomize_chests": 1, "key_item_shuffle": 0}

    def test_the_key_item_chests_are_absent_and_the_bonsly_shiny_is_not(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        for chest in (17, 18, 42, 78, 80):
            self.assertNotIn(L.CHEST_ID_TO_LOCATION[chest], names, chest)
        self.assertIn("Bonsly Room Shiny Chest", names)

    def test_the_bonsly_shiny_is_still_excluded(self) -> None:
        location = self.multiworld.get_location("Bonsly Room Shiny Chest", self.player)
        self.assertIs(LocationProgressType.EXCLUDED, location.progress_type)


if __name__ == "__main__":
    unittest.main()
