"""ADDENDA 192-194. The workbook's `Repeat?` column, the goal fight, and what sphere zero contains.

Three requests in one message, after the player had asked about the missable fence five times:

  1. "Chobin 3 is marked missable, but has a key item. PLEASE. CHECK. THE. EXCEL. SHEET."
  2. "a key item is locked behind Greevil 3. That's Citadark, and also beyond the final boss."
  3. "If travel shuffle is on, Ensure that ZERO locations outside of Agate, Gateon, Kaminko and HQ are
     reachable UNLESS we've received them in archipelago."
"""
from __future__ import annotations

import unittest

from BaseClasses import CollectionState

from . import PokemonXDTestBase
from .. import locations, travel_locations
from ..game_data import census_repeat_column, missable_trainers, trainer_roster

ALWAYS_OPEN_AREAS = {"Pokemon HQ Lab", "Kaminko's House", "Gateon Port", "Agate Village", "Relic Forest"}


class TestTheWorkbookFence(unittest.TestCase):
    """The fence is derived from the workbook, so these assert against the workbook's own numbers."""

    def test_the_transcription_matches_the_sheet(self) -> None:
        c = census_repeat_column
        self.assertEqual(232, len(c.CENSUS_REPEAT_AND_MISSABLE))
        self.assertEqual(47, c.WORKBOOK_MISSABLE_COUNT)
        self.assertEqual(88, c.WORKBOOK_EARLIER_COUNT)
        self.assertEqual(35, c.WORKBOOK_FINAL_COUNT)

    def test_chobin_three_is_a_one_shot_fight(self) -> None:
        """The row the player named. It is blank in `Missable?` and "earlier (3 of 7)" in `Repeat?`."""
        repeat, missable = census_repeat_column.CENSUS_REPEAT_AND_MISSABLE[124]
        self.assertFalse(missable, "Chobin #3 is NOT marked in the Missable? column -- that was the trap")
        self.assertEqual("earlier (3 of 7)", repeat)
        self.assertIn(124, missable_trainers.FILLER_ONLY_TRAINER_INDICES)

    def test_every_earlier_occurrence_is_fenced(self) -> None:
        """All 88 of them, not the 20 that happen to also be marked missable."""
        unfenced = sorted(
            index for index, (repeat, _m) in census_repeat_column.CENSUS_REPEAT_AND_MISSABLE.items()
            if repeat is not None and repeat.startswith("earlier")
            and index not in missable_trainers.FILLER_ONLY_TRAINER_INDICES
        )
        self.assertEqual([], unfenced)

    def test_every_marked_missable_row_is_fenced(self) -> None:
        unfenced = sorted(
            index for index, (_r, missable) in census_repeat_column.CENSUS_REPEAT_AND_MISSABLE.items()
            if missable and index not in missable_trainers.FILLER_ONLY_TRAINER_INDICES
        )
        self.assertEqual([], unfenced)

    def test_every_occurrence_of_a_fenced_name_is_fenced(self) -> None:
        """ADDENDUM 188's rule, kept. The workbook marks OCCURRENCES; fencing "Aferd 1" and leaving Aferd 2-5
        open is what let the Machine Part sit on Aferd #2 for four rounds."""
        fenced_names = {
            trainer_roster.TRAINERS_BY_INDEX[i]["name"].upper()
            for i in missable_trainers.FILLER_ONLY_TRAINER_INDICES
            if i in trainer_roster.TRAINERS_BY_INDEX
        }
        stragglers = sorted(
            index for index, trainer in trainer_roster.TRAINERS_BY_INDEX.items()
            if trainer["name"].upper() in fenced_names
            and index not in missable_trainers.FILLER_ONLY_TRAINER_INDICES
        )
        self.assertEqual([], stragglers)

    def test_rows_with_no_region_are_fenced(self) -> None:
        """"EVERY SINGLE MISSING ENTRY SHOULD BE EXCLUDED", read the other way: no region data, no progression."""
        from ..game_data import trainer_placements

        unfenced = sorted(
            index for index, placement in trainer_placements.PLACEMENTS.items()
            if placement.region is None and index not in missable_trainers.FILLER_ONLY_TRAINER_INDICES
        )
        self.assertEqual([], unfenced)


class TestTheGoalFight(unittest.TestCase):
    def test_the_final_greevil_fight_is_fenced_on_its_own_terms(self) -> None:
        """Not because the name expansion happens to catch it.

        ADDENDUM 192's fence does cover all three Greevil rows, because #1 and #2 are "earlier" and the name
        expansion pulls #3 along. That is an accident of the data. The rule has to stand without it.
        """
        self.assertTrue(missable_trainers.POST_GOAL_TRAINER_INDICES)
        for index in missable_trainers.POST_GOAL_TRAINER_INDICES:
            trainer = trainer_roster.TRAINERS_BY_INDEX[index]
            self.assertEqual("GREEVIL", trainer["name"].upper())
            self.assertEqual(trainer["occurrence"], trainer["total_with_name"],
                             "only the LAST Greevil fight is the goal")
            self.assertIn(index, missable_trainers.FILLER_ONLY_TRAINER_INDICES)


class TestSphereZeroTravelOn(PokemonXDTestBase):
    """"ZERO locations outside of Agate, Gateon, Kaminko and HQ are reachable UNLESS we've received them.\""""

    options = {"randomize_travel_locations": True, "key_item_shuffle": True,
               "randomize_chests": True, "randomize_shops": True, "shuffle_trainer_defeats": True,
               "trainer_defeat_mode": "unique"}

    def test_nothing_of_consequence_outside_the_four_areas_is_reachable_with_nothing(self) -> None:
        """Filler-only locations are exempt and have to be: AP requires every location to be reachable so it
        has somewhere to put filler. What must not be reachable is anything the seed can DEPEND on."""
        empty = CollectionState(self.multiworld)
        offenders = sorted(
            f"{location.name} ({location.parent_region.name})"
            for location in self.multiworld.get_locations(self.player)
            if location.parent_region.name not in ALWAYS_OPEN_AREAS
            and location.progress_type.name != "EXCLUDED"
            and location.can_reach(empty)
        )
        self.assertEqual([], offenders)

    def test_the_two_eevee_checks_are_filed_where_they_are_obtained(self) -> None:
        """Both are legitimately sphere zero -- the player's own ruling -- and both used to sit in the
        synthetic `Pokemon Storage` bucket, which made the assertion above need an exception list."""
        self.assertEqual("Pokemon HQ Lab", locations.LOCATION_TABLE["Catch - Eevee"].region)
        self.assertEqual("Gateon Port", locations.LOCATION_TABLE[locations.EEVEELUTION_LOCATION_NAME].region)
        self.assertTrue(self.can_reach_location("Catch - Eevee"))

    def test_no_travel_destination_leaks_into_sphere_zero(self) -> None:
        empty = CollectionState(self.multiworld)
        for region in sorted(travel_locations.gateway_only_regions()):
            self.assertFalse(empty.can_reach(region, player=self.player), region)
