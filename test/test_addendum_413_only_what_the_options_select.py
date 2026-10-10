"""ADDENDUM 413 (2026-10-04) -- names no seed can hold leave the table; a seed holds only what its options select.

Player: "Can we remove these from the location table? [the catalog's 'Never in a seed (119)': Defeat 115..232
Trainers and Outskirt Stand - Eevee Gift] Also, please ensure that locations are ONLY given to the actual
multiworld IF their yaml options are selected. I do not want Defeat N Trainer checks AT ALL if unique trainer
defeats are selected, etc."
"""
from __future__ import annotations

import re
import unittest

from . import PokemonXDTestBase
from .. import locations as L, options as O, travel_locations as TL
from ..game_data import repeatable_trainers as RT, shops

COUNT = re.compile(r"^Defeat (\d+) Trainers$")


def _created(test) -> "set[str]":
    return {loc.name for loc in test.multiworld.get_locations(test.player) if loc.address is not None}


def _counts(names) -> "set[str]":
    return {n for n in names if COUNT.match(n)}


def _unique(names) -> "set[str]":
    return {n for n in names if n in L._UNIQUE_TRAINER_DEFEAT_NAME_SET}


def _named(names) -> "set[str]":
    return {n for n in names if n.startswith("Defeat - ") and n not in L._UNIQUE_TRAINER_DEFEAT_NAME_SET}


def _any(names) -> "set[str]":
    return {n for n in names if n in RT.LOCATION_NAMES}


class TestTheTable(unittest.TestCase):
    def test_no_count_past_the_options_maximum(self) -> None:
        top = O.TrainerDefeatCheckCount.range_end
        counts = sorted(int(COUNT.match(n).group(1)) for n in L.LOCATION_TABLE if COUNT.match(n))
        self.assertEqual(list(range(1, top + 1)), counts)
        self.assertNotIn(f"Defeat {top + 1} Trainers", L.LOCATION_TABLE)
        self.assertNotIn("Defeat 232 Trainers", L.LOCATION_TABLE)

    def test_the_eevee_gift_is_gone(self) -> None:
        self.assertNotIn("Outskirt Stand - Eevee Gift", L.LOCATION_TABLE)

    def test_their_ids_are_left_behind_inert(self) -> None:
        live = {data.id_offset for data in L.LOCATION_TABLE.values()}
        for name in L.NEVER_CREATED_LOCATION_NAMES:
            self.assertIn(name, L._FROZEN_LOCATION_OFFSETS, name)
            self.assertNotIn(L._FROZEN_LOCATION_OFFSETS[name], live, f"{name}'s id was handed to another location")
        self.assertEqual(119, len(L.NEVER_CREATED_LOCATION_NAMES))

    def test_the_roster_count_still_drives_the_weights(self) -> None:
        self.assertEqual(232, L.TRAINER_DEFEAT_COUNT_LOCATION_COUNT)


class _Audit:
    """Every seed: nothing created that the table does not hold, and nothing the table retired."""

    def test_only_table_names(self) -> None:
        created = _created(self)
        self.assertLessEqual(created, set(L.LOCATION_TABLE))
        self.assertFalse(created & L.NEVER_CREATED_LOCATION_NAMES)


class TestUnique(_Audit, PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": 1, "trainer_defeat_check_count": 114}

    def test_no_defeat_n_trainers_at_all(self) -> None:
        created = _created(self)
        self.assertEqual(set(), _counts(created), "unique mode creates no Defeat N Trainers, whatever the count")
        self.assertEqual(set(), _named(created), "nor cumulative mode's curated named checks")
        self.assertTrue(_unique(created))
        self.assertTrue(_any(created))


class TestCumulative(_Audit, PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": 0, "trainer_defeat_check_count": 50}

    def test_exactly_the_count_asked_for_and_nothing_else(self) -> None:
        # ADDENDUM 414: "Cumulative mode should not have the 64 names and any checks - it should just be a tally."
        created = _created(self)
        self.assertEqual({f"Defeat {n} Trainers" for n in range(1, 51)}, _counts(created))
        self.assertEqual(set(), _unique(created))
        self.assertEqual(set(), _named(created))
        self.assertEqual(set(), _any(created))
        self.assertEqual(_counts(created), {n for n in created if n.startswith("Defeat")})


class TestDefeatsOff(_Audit, PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": False}

    def test_no_trainer_defeat_check_of_any_kind(self) -> None:
        created = _created(self)
        self.assertEqual(set(), _counts(created) | _unique(created) | _named(created) | _any(created))


class TestShopsOffTravelOffKeysOff(_Audit, PokemonXDTestBase):
    options = {"randomize_shops": False, "randomize_travel_locations": False, "key_item_shuffle": False}

    def test_none_of_their_checks(self) -> None:
        created = _created(self)
        self.assertEqual(set(), {n for n in created if L.is_shop_location(n)})
        self.assertEqual(set(), {n for n in created if n.startswith(TL.TRAVEL_UNLOCK_LOCATION_PREFIX)})
        self.assertEqual(set(), {n for n in created if L.is_key_item_chest_location(n)})


class TestShopsOnTravelOnKeysOn(_Audit, PokemonXDTestBase):
    options = {"randomize_shops": True, "randomize_travel_locations": True, "key_item_shuffle": True}

    def test_all_of_their_checks(self) -> None:
        created = _created(self)
        self.assertTrue({n for n in created if L.is_shop_location(n)})
        self.assertTrue({n for n in created if n.startswith(TL.TRAVEL_UNLOCK_LOCATION_PREFIX)})
        self.assertTrue({n for n in created if L.is_key_item_chest_location(n)})


class TestPitStop(_Audit, PokemonXDTestBase):
    options = {"randomize_shops": True, "agate_village_pit_stop": True}

    def test_no_agate_shop_checks(self) -> None:
        created = _created(self)
        agate = {n for n in created if L.is_shop_location(n)
                 and L.SHOP_LOCATION_TO_SHOP_AND_SLOT[n][0].name == shops.AGATE_PIT_STOP_SHOP_NAME}
        self.assertEqual(set(), agate)


if __name__ == "__main__":
    unittest.main()
