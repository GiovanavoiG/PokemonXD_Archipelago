"""ADDENDUM 449 (2026-10-09) -- `progression_locations` removed; Laken behind the Machine Part.

Player: "Isn't the "progression_locations" option redundant at this point? Also, make Laken gated behind the machine
part."
"""
from __future__ import annotations

import unittest

from BaseClasses import CollectionState, LocationProgressType

from . import PokemonXDTestBase
from .. import rules
from ..options import PokemonXDOptions

LAKEN = ("Defeat - Laken #2", "Defeat - Laken #3", "Defeat Laken (Any)")


class TestTheOptionIsGone(unittest.TestCase):
    def test_gone(self) -> None:
        self.assertNotIn("progression_locations", PokemonXDOptions.type_hints)

    def test_laken_is_in_the_gate_table(self) -> None:
        for name in LAKEN:
            self.assertEqual(("Machine Part",), rules.NAMED_DEFEAT_ITEM_GATES[name])


class TestWhatWorldChecksMeantIsStillExpressible(PokemonXDTestBase):
    options = {"shadow_catch_progression": False, "purification_progression_cap": 0}

    def test_catches_and_purifications_filler_only(self) -> None:
        for location in self.multiworld.get_locations(self.player):
            if location.name.startswith("Purify "):
                self.assertIs(LocationProgressType.EXCLUDED, location.progress_type, location.name)


class TestLakenNeedsTheMachinePart(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": 1, "key_item_shuffle": True}

    def test_unreachable_without_it_reachable_with_it(self) -> None:
        names = [n for n in LAKEN if n in {l.name for l in self.multiworld.get_locations(self.player)}]
        self.assertTrue(names)
        state = CollectionState(self.multiworld)
        for item in self.multiworld.itempool:
            if item.player == self.player and item.name != "Machine Part":
                state.collect(item, True)
        for name in names:
            self.assertFalse(self.multiworld.get_location(name, self.player).can_reach(state), name)
        state.collect(self.world.create_item("Machine Part"), True)
        for name in names:
            self.assertTrue(self.multiworld.get_location(name, self.player).can_reach(state), name)


class _WakinGonzap(PokemonXDTestBase):
    """Player: "Make sure Wakin and Gonzap are NOT filler." Their fights may hold progression."""

    def test_not_filler_only(self) -> None:
        for name in ("Defeat - Wakin", "Defeat - Gonzap"):
            location = self.multiworld.get_location(name, self.player)
            self.assertIsNot(LocationProgressType.EXCLUDED, location.progress_type, name)


class TestWakinGonzapDefault(_WakinGonzap):
    options = {"shuffle_trainer_defeats": True}


class TestWakinGonzapLocationShuffle(_WakinGonzap):
    options = {"shuffle_trainer_defeats": True, "randomize_travel_locations": True, "trainer_defeat_mode": 1}


class TestWakinGonzapCumulative(PokemonXDTestBase):
    """Cumulative mode has no per-trainer checks at all (ADDENDUM 414), so there is nothing to be filler."""

    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": 0}

    def test_no_named_checks(self) -> None:
        names = {l.name for l in self.multiworld.get_locations(self.player)}
        self.assertNotIn("Defeat - Wakin", names)
        self.assertNotIn("Defeat - Gonzap", names)
