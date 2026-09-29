"""ADDENDUM 335 (2026-09-24): the fourteen uncertain Overworld Items are retired.

Player, sending the tracker's own "Missing:" list back: "Delete all of these checks. None of these are real."

The list was EXACTLY the fourteen names ADDENDUM 237 could not vouch for -- all of them, and no name it
could. That census retired 51 Overworld Items on evidence and deliberately kept these, because the two
mistakes are not equally bad: retiring a real location loses a check, keeping a phantom lets Fill place
progression somewhere unreachable. With no evidence either way, EXCLUDED was the honest answer for an unknown.

A playthrough is the evidence a walkthrough page could not give. The unknown is now known.
"""
import unittest

from . import PokemonXDTestBase
from .. import locations
from ..game_data import overworld_item_census as census

THE_FOURTEEN = frozenset({
    "Phenac City - Stadium Item",
    "Phenac City - Cologne's Item",
    "Pyrite Town - Duel Square Item",
    "Pyrite Town - Jailhouse Item",
    "Realgam Tower - Colosseum Clear Reward",
    "Kaminko's House - Catwalk Diary Pages",
    "S.S. Libra - Bonsly's Item",
    "Agate Village - Eagun's Item",
    "Relic Forest - Hidden Item",
    "Agate Village - Eagun's Cave Ball",
    "Cipher Key Lair - Admin Item",
    "Citadark Isle - Pre-Boss Item",
    "Citadark Isle - After Furgy",
    "Citadark Isle - B1F After Grason",
})


class TestTheListTransferredExactly(unittest.TestCase):
    def test_the_set_is_the_players_list_and_nothing_more(self) -> None:
        """Transcribed from the screenshot, asserted against the code. A fifteenth name here would mean
        something was retired that the player did not rule on."""
        self.assertEqual(THE_FOURTEEN, census.RETIRED_UNREAL_LOCATIONS)

    def test_it_was_the_whole_uncertain_list(self) -> None:
        """What makes this a verdict rather than a sample: nothing was left behind in limbo."""
        self.assertEqual(14, len(census.RETIRED_UNREAL_LOCATIONS))
        self.assertFalse(hasattr(census, "UNCERTAIN_EXCLUDED_LOCATIONS"),
                         "the mechanism goes with its last name (ADDENDA 247/298)")

    def test_retired_for_their_own_reason(self) -> None:
        """Not merged into `RETIRED_DUPLICATE_LOCATIONS`: those were duplicates of a real chest, these are
        absent. A reader asking "why is this gone" should get the right answer."""
        self.assertEqual(frozenset(),
                         census.RETIRED_DUPLICATE_LOCATIONS & census.RETIRED_UNREAL_LOCATIONS)
        self.assertEqual(census.RETIRED_LOCATIONS,
                         census.RETIRED_DUPLICATE_LOCATIONS | census.RETIRED_UNREAL_LOCATIONS)


class TestTheyAreReallyGone(unittest.TestCase):
    def test_none_are_in_the_location_table(self) -> None:
        for name in THE_FOURTEEN:
            self.assertNotIn(name, locations.LOCATION_TABLE, name)

    def test_none_are_in_any_region_bucket(self) -> None:
        placed = {n for names in locations.LOCATIONS_BY_REGION.values() for n in names}
        self.assertEqual(frozenset(), THE_FOURTEEN & placed)

    def test_none_have_a_live_id(self) -> None:
        live = locations.get_location_name_to_id(1000)
        for name in THE_FOURTEEN:
            self.assertNotIn(name, live, name)


class TestAddendum26sRuleHeld(unittest.TestCase):
    """A retired id is recorded forever and never reassigned."""

    def test_every_retired_name_keeps_its_frozen_entry(self) -> None:
        for name in THE_FOURTEEN:
            self.assertIn(name, locations._FROZEN_LOCATION_OFFSETS, name)

    def test_no_live_location_took_one_of_their_offsets(self) -> None:
        retired_offsets = {locations._FROZEN_LOCATION_OFFSETS[n] for n in THE_FOURTEEN}
        live_offsets = {data.id_offset for data in locations.LOCATION_TABLE.values()}
        self.assertEqual(frozenset(), retired_offsets & live_offsets)


class TestTheSeedStillBuilds(PokemonXDTestBase):
    options = {"randomize_chests": True, "shuffle_trainer_defeats": True}

    def test_no_region_was_emptied_by_the_retirement(self) -> None:
        """Fourteen locations leaving must not strand the regions they came from. Asserted against THOSE
        regions rather than against every region in the graph -- synthetic buckets are empty for their own
        reasons and have nothing to do with this change."""
        bereaved = {"Phenac City", "Pyrite Town", "Realgam Tower", "Kaminko's House", "SS Libra",
                    "Agate Village", "Cipher Key Lair", "Citadark Isle"}
        for name in sorted(bereaved):
            region = self.multiworld.get_region(name, self.player)
            self.assertTrue(region.locations,
                            f"{name} lost its last location to the retirement")

    def test_relic_forest_is_now_empty_and_that_is_recorded(self) -> None:
        """THE ONE EXCEPTION, found by the test above rather than assumed. "Relic Forest - Hidden Item" was
        the ONLY location that region held, so retiring it leaves the region with nothing in it.

        That is legal -- an empty region is a graph node Fill simply never visits -- and the region still has
        a job: `story_bytes.AREA_GROUPS["Agate Village"]` names it, so a mark earned there still counts for
        the Agate destination's floor. Asserted rather than tidied away, because a region that silently held
        no checks would otherwise look like a bug to the next reader, and because a future real Relic Forest
        location should make this test fail and be re-thought."""
        region = self.multiworld.get_region("Relic Forest", self.player)
        self.assertEqual([], list(region.locations))
        from ..game_data import story_bytes

        self.assertIn("Relic Forest", story_bytes.AREA_GROUPS["Agate Village"],
                      "the region still earns marks for Agate even with no checks of its own")

    def test_the_retired_names_are_not_reachable_anywhere(self) -> None:
        live = {location.name for location in self.multiworld.get_locations(self.player)}
        self.assertEqual(frozenset(), THE_FOURTEEN & live)
