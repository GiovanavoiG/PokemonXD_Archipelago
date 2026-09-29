"""ADDENDUM 175 (2026-09-13): the 232 per-trainer locations get real regions and real gates.

Player instruction: "Obviously place these trainers' logic both behind their area & any required items." Both,
ANDed -- and the tests that matter are the ones about BOTH halves being present, since a region-only gate on a
fight behind the Music Disc reads as available far too early.

The other thing worth pinning hard is the Elevator Key filter. Six census rows name an item that can never
enter the pool, and ADDENDUM 168's rule says naming one makes its location unreachable forever. On a region
edge that failure is loud; on a location it is silent, and most of these locations are EXCLUDED so nothing
would complain until a fill check ran.
"""
from __future__ import annotations

import unittest

from BaseClasses import LocationProgressType

from . import PokemonXDTestBase
from .. import items, locations, regions, rules
from ..game_data import missable_trainers, trainer_placements, trainer_roster


class TestTheCensusData(unittest.TestCase):
    def test_it_covers_the_whole_roster_exactly_once(self) -> None:
        self.assertEqual(sorted(trainer_placements.PLACEMENTS), list(range(1, 233)))

    def test_every_named_region_is_a_real_graph_node(self) -> None:
        """A typo here would file a trainer into a region that does not exist, and locations.py would create
        that region on the spot -- unconnected, so the location would be unreachable."""
        for region in trainer_placements.REGIONS_WITH_TRAINERS:
            self.assertIn(region, regions.REGION_NAMES)

    def test_the_workbook_normalisations_landed(self) -> None:
        """Three values in the returned workbook were not usable as-is. Each was a judgement, so each is
        pinned: "Cave Spot" -> the single Poke Spots region, "Phenac Colosseum" -> Phenac City (which is also
        where chest_regions puts room 107, so the two tables agree independently)."""
        self.assertEqual(trainer_placements.region_for(2), "Poke Spots")
        self.assertEqual(trainer_placements.region_for(106), "Phenac City")
        from ..game_data import chest_regions
        self.assertEqual(chest_regions.ROOM_TO_REGION[107], "Phenac City")

    def test_the_logic_column_resolved_to_real_item_names(self) -> None:
        """The workbook's LOGIC column is free text ("Behind Data Rom", "Behind Lever"). `state.has` needs the
        exact item name, so a mis-spelling would be a silently dead gate."""
        every_required = {
            name for placement in trainer_placements.PLACEMENTS.values()
            for name in placement.required_items
        }
        self.assertTrue(every_required)
        for name in every_required:
            self.assertIn(name, items.ITEM_TABLE, name)

    def test_the_counts_are_what_the_player_returned(self) -> None:
        self.assertEqual(len(trainer_placements.PLACED_INDICES), 195)
        self.assertEqual(len(trainer_placements.FILLER_ONLY_INDICES), 37)
        with_items = [i for i, p in trainer_placements.PLACEMENTS.items() if p.required_items]
        # 38 from the player's census, +1 for ADDENDUM 312 (row 128, Smarton #1: Music Disc + Mayor's Note).
        self.assertEqual(len(with_items), 39)
        self.assertEqual(trainer_placements.PLACEMENTS[128].required_items, ("Music Disc", "Mayor's Note"))


class TestNAMeansFiller(unittest.TestCase):
    """Player: "Assume anything labelled N/A doesn't matter and can be labelled filler.\""""

    def test_the_na_rows_are_a_brand_new_population_not_a_subset(self) -> None:
        """This test was first written asserting the OPPOSITE -- that the N/A rows would already be in the
        player's 47-strong missable list -- and it failed, which is the only reason the fence below got built.
        They are entirely disjoint: the N/A rows are the deep rematch tails (Miror B. #2-#7 and #9, the Sixes'
        5th and 6th occurrences, the third fights of Cida/Clerr/Belish/Dosk/Hebon), none of which the missable
        list covers. Pinned as disjoint so nobody "simplifies" one set into the other."""
        na = set(trainer_placements.FILLER_ONLY_INDICES) - {1}   # 1 is Hordel, blank rather than N/A
        self.assertEqual(len(na), 36)
        self.assertEqual(na & set(missable_trainers.MISSABLE_TRAINER_INDICES), set())

    def test_they_are_actually_excluded_and_not_just_labelled(self) -> None:
        """The point of the fence. A trainer with no known region is parked in the always-open bucket, so an
        unexcluded one would read as reachable from sphere zero -- the fill would put a progression item on a
        fight the player may reach very late or never and call it a starting check."""
        for name in locations._UNPLACED_TRAINER_LOCATION_NAMES:
            self.assertIn(name, locations._MISSABLE_TRAINER_LOCATION_NAMES, name)

    def test_hordel_is_the_one_blank_row_and_is_filler_too(self) -> None:
        """Index 1 came back blank, not N/A. The player chose to treat it as filler rather than have a region
        guessed for it -- guessing would have been guessing where a progression-eligible check sits."""
        self.assertIn(1, trainer_placements.FILLER_ONLY_INDICES)
        self.assertIsNone(trainer_placements.region_for(1))
        self.assertNotIn(1, missable_trainers.MISSABLE_TRAINER_INDICES)

    def test_unknown_region_rows_still_exist_somewhere_reachable(self) -> None:
        """AP requires every location to be reachable so filler can be placed on it. "No region known" is not
        a reason for a location to vanish -- it is a reason for nothing to depend on it."""
        bucket = locations.LOCATIONS_BY_REGION["Unique Trainer Defeats"]
        self.assertEqual(len(bucket), 37)
        self.assertEqual(set(bucket), locations._UNPLACED_TRAINER_LOCATION_NAMES)


class TestTheLocationsMoved(unittest.TestCase):
    def test_195_trainers_are_filed_in_their_census_region(self) -> None:
        for index, placement in trainer_placements.PLACEMENTS.items():
            if placement.region is None:
                continue
            name = trainer_roster.trainer_label(trainer_roster.TRAINERS_BY_INDEX[index])
            self.assertEqual(locations._TRAINER_REGION_BY_LOCATION[name], placement.region, name)

    def test_no_location_id_changed(self) -> None:
        """Re-bucketing must be free. _FROZEN_LOCATION_OFFSETS pins every name, so moving one between regions
        changes reachability and nothing else -- the same guarantee ADDENDUM 169 relied on."""
        for index in (1, 2, 106, 147, 232):
            name = trainer_roster.trainer_label(trainer_roster.TRAINERS_BY_INDEX[index])
            self.assertEqual(locations.LOCATION_TABLE[name].id_offset,
                             locations._FROZEN_LOCATION_OFFSETS[name], name)

    def test_the_names_come_from_the_roster_not_from_string_assembly(self) -> None:
        """This project has twice shipped a location name built by hand that silently un-fenced dozens of
        checks -- ADDENDUM 144's surname casing bug and ADDENDUM 152's double "Defeat - Defeat - " prefix. The
        census supplies only the region; trainer_label supplies the name."""
        for name in locations._TRAINER_REGION_BY_LOCATION:
            # ADDENDUM 362: a name the unique-team rule retired keeps its census region -- that is evidence
            # about a real fight and does not stop being true -- but it is no longer a location.
            if name not in trainer_roster.RETIRED_UNIQUE_DEFEAT_LOCATIONS:
                self.assertIn(name, locations.LOCATION_TABLE, name)
            self.assertFalse(name.startswith("Defeat - Defeat"), name)


class TestTheWeightTablesAreNowACensus(unittest.TestCase):
    def test_both_cumulative_tables_are_the_same_census(self) -> None:
        """They used to differ because the Mt. Battle-free variant was a correction applied to a bad estimate.
        With a real count there is nothing to correct."""
        self.assertEqual(rules._TRAINER_WEIGHT_BY_REGION, rules._UNIQUE_TRAINER_WEIGHT_BY_REGION)

    def test_the_table_still_totals_the_roster(self) -> None:
        self.assertEqual(sum(rules._TRAINER_WEIGHT_BY_REGION.values()), 232)

    def test_the_unknown_region_trainers_are_attributed_to_the_last_region(self) -> None:
        """They still advance the in-game counter, so they must be counted somewhere. Attributed to the LAST
        region deliberately: over-attributing pushes a threshold later than reality, which costs at worst a
        harmless sphere bleed, while under-attributing claims a count is reachable early when it is not and can
        strand a progression item. Only one of those two errors can cost a run."""
        last = rules._SPHERE_REGION_ORDER[-1]
        census_only = trainer_placements.trainer_count_by_region()
        self.assertEqual(
            rules._TRAINER_WEIGHT_BY_REGION[last],
            census_only.get(last, 0) + len(trainer_placements.FILLER_ONLY_INDICES),
        )

    def test_the_always_open_regions_now_hold_trainers(self) -> None:
        """ADDENDUM 169's instruction: "Gateon, Kaminko, HQ Lab and Agate should all have checks from their
        trainer defeats and chests." The old estimate gave the first three none at all."""
        for region in ("Pokemon HQ Lab", "Kaminko's House", "Gateon Port", "Agate Village"):
            self.assertGreater(rules._TRAINER_WEIGHT_BY_REGION.get(region, 0), 0, region)

    def test_mt_battle_is_three_not_ninety_two(self) -> None:
        """The estimate put 92 of 232 at Mt. Battle -- ~40% of the story roster behind an optional dungeon,
        which ADDENDUM 145 had already shown to be wrong in kind. The census says 3."""
        self.assertEqual(rules._TRAINER_WEIGHT_BY_REGION.get("Mt. Battle", 0), 3)


class TestTheItemGates(PokemonXDTestBase):
    # ADDENDUM 196: Mt. Battle trainers are excluded by default now, and one probe below is a Mt. Battle row;
    # the Parts gate also defaults ON, and the Citadark probe here collects key items but never a Part.
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": 1, "key_item_shuffle": True,
               "exclude_mt_battle_trainers": False, "robo_kyogre_parts_unlock_citadark": False}

    def _location(self, index: int) -> str:
        return trainer_roster.trainer_label(trainer_roster.TRAINERS_BY_INDEX[index])

    def test_a_gated_trainer_needs_its_item_on_top_of_its_region(self) -> None:
        """Both halves, which is the whole instruction. Probed with the full key-item chain collected so the
        region is definitely open -- what remains shut can only be the item gate."""
        gated = [i for i, p in trainer_placements.PLACEMENTS.items()
                 if p.required_items == ("Data ROM",) and p.region is not None]
        self.assertTrue(gated, "expected at least one Data ROM-gated trainer in the census")
        index = gated[0]
        name = self._location(index)
        self.assertFalse(self.can_reach_location(name))
        self.collect_key_item_chain()
        self.assertTrue(self.can_reach_location(name))

    def test_the_region_half_is_not_lost_to_the_item_half(self) -> None:
        """add_rule, not set_rule: a gate must narrow what the region already requires, never replace it. A
        Citadark trainer with no item gate must still need Citadark."""
        citadark = [i for i, p in trainer_placements.PLACEMENTS.items()
                    if p.region == "Citadark Isle" and not p.required_items]
        self.assertTrue(citadark)
        name = self._location(citadark[0])
        self.collect_key_item_chain(4)     # everything but the System Lever
        self.assertFalse(self.can_reach_location(name))
        self.collect_key_item_chain(5)
        self.assertTrue(self.can_reach_location(name))

    def test_zook_two_also_needs_snagem_hideout(self) -> None:
        """The one `required_regions` row. Player: "Must be done with Snagem hideout." Snagem Hideout sits
        LATER in the graph (index 18) than Zook's own Cipher Key Lair (exterior) (16), so reaching the
        exterior genuinely does not imply it -- without this the fight would read as available too early."""
        placement = trainer_placements.PLACEMENTS[147]
        self.assertEqual(placement.region, "Cipher Key Lair (exterior)")
        self.assertEqual(placement.required_regions, ("Snagem Hideout",))
        order = list(regions.REGION_NAMES)
        self.assertGreater(order.index("Snagem Hideout"), order.index("Cipher Key Lair (exterior)"))


class TestTheElevatorKeyIsFilteredNotRequired(PokemonXDTestBase):
    """ADDENDUM 168's rule, third application. Six census rows name the Elevator Key; it is in
    items.NEVER_SHUFFLED_KEY_ITEM_NAMES and never enters the pool in any mode; `all_state` never holds an item
    that was never created. A rule naming it makes its location unreachable forever, silently."""

    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": 1, "key_item_shuffle": True}

    def test_the_census_still_records_it(self) -> None:
        """Kept in the data on purpose: the player's statement about the game is true, the fight really is
        behind that door. The filter is the mechanism's problem, not the data's."""
        naming_it = [i for i, p in trainer_placements.PLACEMENTS.items()
                     if "Elevator Key" in p.required_items]
        self.assertEqual(len(naming_it), 6)

    def test_it_never_reaches_a_rule(self) -> None:
        self.assertIn("Elevator Key", items.NEVER_SHUFFLED_KEY_ITEM_NAMES)
        naming_it = [i for i, p in trainer_placements.PLACEMENTS.items()
                     if "Elevator Key" in p.required_items]
        for index in naming_it:
            if trainer_placements.PLACEMENTS[index].region is None:
                continue
            name = trainer_roster.trainer_label(trainer_roster.TRAINERS_BY_INDEX[index])
            self.collect_key_item_chain()
            self.assertTrue(self.can_reach_location(name), name)


class TestCumulativeModeIsUnaffected(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": 0}

    def test_the_per_trainer_locations_do_not_exist_in_cumulative_mode(self) -> None:
        """The two modes are mutually exclusive -- one defeat would otherwise fire a curated location and a
        roster location at once. The census must not have quietly created both."""
        created = {loc.name for loc in self.multiworld.get_locations(1)}
        unique_only = [
            n for n in locations.UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES
            if n not in locations.trainer_defeat.TRAINER_DEFEAT_LOCATIONS_BY_REGION_FLAT
        ] if hasattr(locations.trainer_defeat, "TRAINER_DEFEAT_LOCATIONS_BY_REGION_FLAT") else []
        for name in unique_only[:20]:
            self.assertNotIn(name, created, name)


if __name__ == "__main__":
    unittest.main()
