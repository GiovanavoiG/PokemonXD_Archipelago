"""Nightmare Citadark and Nightmare Greevil turn Reduce Citadark Grind on when it is off."""
from __future__ import annotations

from . import PokemonXDTestBase


class TestNightmareCitadark(PokemonXDTestBase):
    options = {"nightmare_citadark": True, "reduce_citadark_grind": 0}

    def test_it_is_turned_on(self) -> None:
        self.assertEqual(1, int(self.multiworld.worlds[self.player].options.reduce_citadark_grind))


class TestNightmareGreevil(PokemonXDTestBase):
    options = {"nightmare_greevil": True, "reduce_citadark_grind": 0}

    def test_it_is_turned_on(self) -> None:
        self.assertEqual(1, int(self.multiworld.worlds[self.player].options.reduce_citadark_grind))


class TestAChoiceIsKept(PokemonXDTestBase):
    options = {"nightmare_greevil": True, "reduce_citadark_grind": 2}

    def test_equal_to_citadark_entry_stays(self) -> None:
        self.assertEqual(2, int(self.multiworld.worlds[self.player].options.reduce_citadark_grind))


class TestWithoutNightmare(PokemonXDTestBase):
    options = {"reduce_citadark_grind": 0}

    def test_it_stays_off(self) -> None:
        self.assertEqual(0, int(self.multiworld.worlds[self.player].options.reduce_citadark_grind))
