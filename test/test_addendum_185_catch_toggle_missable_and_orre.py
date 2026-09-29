"""ADDENDUM 185 (2026-09-14): five corrections, four of them about what may hold progression.

  1. "Seed 3 has an issue - browsix, and everything post-sixes, is gated behind the music disc and mayor's
     note." -- the 22 named Phenac trainer-defeat locations move into the Disc+Note tier.
  2. "all of those Sixes are marked missable - can you check the excel spreadsheet again? they shouldn't be
     carrying anything important." -- the workbook's Missable? column is the fence again, and the named 66
     inherit it (they had never been fenced at all).
  3. "Add a toggle for Shadow Pokemon Catch checks being progression/useful or not. Default it off."
  4. "Increase the cap on the progression purification checks option to 127, limit it to 83 + whatever the
     player selects as their option for shadow pokemon expansion. Throw an error if they choose a cap higher
     than what the expansion gives them."
  5. "Leave Orre Colosseum as a gettable location, but remove it/all its trainers/chests from the logic."
"""
from __future__ import annotations

import unittest

from BaseClasses import LocationProgressType
from Options import OptionError

from . import PokemonXDTestBase
from .. import locations, regions as region_module, species, travel_locations
from ..game_data import missable_trainers, trainer_roster
from .. import trainer_defeat
from ..options import PurificationProgressionCap


class TestPhenacIsBehindTheDiscAndNote(unittest.TestCase):
    def test_no_named_trainer_location_is_left_in_the_bare_phenac_tier(self) -> None:
        """Chest 80 -- the Music Disc itself -- lives in plain "Phenac City". A trainer check filed there too
        can be handed the Disc and gated behind it, which is exactly what seed 03 did."""
        bare = [name for region, name, _s in trainer_defeat.TRAINER_DEFEAT_ROSTER if region == "Phenac City"]
        self.assertEqual(bare, [])

    def test_all_22_are_in_the_post_sixes_tier(self) -> None:
        moved = [name for region, name, _s in trainer_defeat.TRAINER_DEFEAT_ROSTER
                 if region == "Phenac City (Post-Sixes)"]
        self.assertEqual(len(moved), 22)
        self.assertIn("Defeat - Cipher Peon Browsix", moved)

    def test_that_tier_really_requires_both_items(self) -> None:
        edge = next(e for e in region_module.REGION_EDGES if e[1] == "Phenac City (Post-Sixes)")
        self.assertEqual(set(edge[2]), {"Music Disc", "Mayor's Note"})


class TestPhenacInAWorld(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": 0, "progression_locations": 2,
               "key_item_shuffle": True}

    def test_a_phenac_trainer_is_closed_until_both_items_are_held(self) -> None:
        name = "Defeat - Cipher Peon Egrog"  # census-confirmed Disc+Note, and not missable
        location = self.multiworld.get_location(name, self.player)
        self.assertFalse(location.can_reach(self.multiworld.state))
        self.collect_key_item_chain(4)  # Machine Part, Data ROM & ID Card, Music Disc, Mayor's Note
        self.assertTrue(location.can_reach(self.multiworld.state))


class TestTheMissableFenceIsBackAndWider(unittest.TestCase):
    def test_the_workbook_column_is_the_fence(self) -> None:
        """WIDENED 2026-09-14 (ADDENDUM 188): the workbook's 47 rows are OCCURRENCES naming 46 trainers, and
        every occurrence of those trainers is fenced -- 101 locations.

        WIDENED AGAIN the same day (ADDENDUM 192) to 150: `Missable?` is one of TWO columns that say a fight
        cannot be redone, and this project had only ever read that one. See
        test_workbook_fence_and_sphere_zero.py, which asserts the fence against the workbook directly rather
        than against a remembered total."""
        self.assertEqual(len(missable_trainers.MISSABLE_TRAINER_INDICES), 47)
        self.assertEqual(len(missable_trainers.FILLER_ONLY_TRAINER_INDICES), 150)   # ADDENDUM 341 lifted 337's +Wakin/+Gonzap
        self.assertTrue(missable_trainers.MISSABLE_TRAINER_INDICES
                        <= missable_trainers.FILLER_ONLY_TRAINER_INDICES)

    def test_the_six_sixes_first_fights_are_in_it(self) -> None:
        for index in (33, 34, 35, 36, 37, 38):
            self.assertIn(index, missable_trainers.FILLER_ONLY_TRAINER_INDICES)

    def test_the_named_66_inherit_their_surname_s_missability(self) -> None:
        """The gap ADDENDUM 152 left and nobody noticed for 33 addenda: the fence was applied under
        `if is_unique_trainer_defeat`, so in CUMULATIVE mode zero of the 66 named locations were fenced."""
        self.assertTrue(locations._MISSABLE_NAMED_TRAINER_LOCATIONS)
        for name in ("Defeat - Cipher Peon Browsix", "Defeat - Cipher Peon Resix",
                     "Defeat - Rider Willie", "Defeat - Thug Zook"):
            self.assertIn(name, locations._MISSABLE_NAMED_TRAINER_LOCATIONS, name)

    def test_a_later_occurrence_of_a_missable_trainer_is_fenced_too(self) -> None:
        """The ADDENDUM 188 correction, stated where it will be looked for. These are the exact locations that
        were carrying the Machine Part, the System Lever and the Mayor's Note in shipped seeds."""
        from .. import species  # noqa: F401  (import kept uniform with the rest of the file)
        from ..game_data import trainer_roster

        for index in (69, 147, 202, 120, 44):   # Aferd #2, Zook #2, Laken #3, Browsix #4, Greesix #2
            self.assertIn(index, missable_trainers.FILLER_ONLY_TRAINER_INDICES,
                          trainer_roster.trainer_label(trainer_roster.TRAINERS_BY_INDEX[index]))

    def test_a_non_missable_named_location_is_not_fenced(self) -> None:
        """Without this the test above could pass by fencing everything."""
        self.assertNotIn("Defeat - Cipher Peon Egrog", locations._MISSABLE_NAMED_TRAINER_LOCATIONS)


class TestNamedFenceInAWorld(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": 0, "progression_locations": 2}

    def test_browsix_cannot_hold_the_music_disc_any_more(self) -> None:
        browsix = self.multiworld.get_location("Defeat - Cipher Peon Browsix", self.player)
        self.assertEqual(browsix.progress_type, LocationProgressType.EXCLUDED)

    def test_it_still_exists_and_can_still_be_checked(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertIn("Defeat - Cipher Peon Browsix", names)


class TestShadowCatchToggle(PokemonXDTestBase):
    options = {"progression_locations": 2, "shadow_catch_progression": False}

    def test_catches_are_filler_only_by_default(self) -> None:
        catches = [loc for loc in self.multiworld.get_locations(self.player)
                   if loc.name.startswith("Catch - ")
                   and loc.name not in (locations.GUARANTEED_SPECIES_LOCATION,
                                        locations.EEVEELUTION_LOCATION_NAME)]
        self.assertTrue(catches)
        for loc in catches:
            self.assertEqual(loc.progress_type, LocationProgressType.EXCLUDED, loc.name)

    def test_the_starter_and_its_evolution_are_untouched_by_the_toggle(self) -> None:
        for name in (locations.GUARANTEED_SPECIES_LOCATION, locations.EEVEELUTION_LOCATION_NAME):
            loc = self.multiworld.get_location(name, self.player)
            self.assertEqual(loc.progress_type, LocationProgressType.DEFAULT, name)

    def test_they_still_exist_and_still_send(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertIn("Catch - Eevee", names)
        self.assertTrue(any(n.startswith("Catch - ") for n in names))


class TestShadowCatchToggleOn(PokemonXDTestBase):
    options = {"progression_locations": 2, "shadow_catch_progression": True,
               "shadow_pokemon_expansion": 44}

    def test_catches_become_eligible_again(self) -> None:
        catches = [loc for loc in self.multiworld.get_locations(self.player)
                   if loc.name.startswith("Catch - ")
                   and loc.progress_type == LocationProgressType.DEFAULT]
        self.assertGreater(len(catches), 20)

    def test_and_they_are_still_gated(self) -> None:
        """The toggle changes whether a catch may hold progression, never whether it is honestly gated. The
        ADDENDUM 183 floor and the holder's own logic still apply."""
        from .. import rules

        gates, _unplaceable = rules._catch_gates_for_species(self.multiworld.worlds[self.player])
        checked = 0
        for dex, sources in gates.items():
            if dex == rules._GUARANTEED_EEVEE_DEX or all(s == "pokespot" for s in sources):
                continue
            try:
                loc = self.multiworld.get_location(species.location_name_for_species(dex), self.player)
            except KeyError:
                continue
            self.assertFalse(loc.can_reach(self.multiworld.state), loc.name)
            checked += 1
        self.assertGreater(checked, 20)


class TestPurificationCap(unittest.TestCase):
    def test_the_ceiling_is_the_most_shadows_a_seed_could_ever_hold(self) -> None:
        from ..game_data import shadow_regions

        self.assertEqual(PurificationProgressionCap.range_end, 127)
        self.assertEqual(shadow_regions.total_shadow_count() + 44, 127,
                         "127 is 83 vanilla + the 44 Shadow Pokemon Expansion can add")

    def test_the_default_still_leaves_the_real_ladders_tail_filler_only(self) -> None:
        self.assertLess(PurificationProgressionCap.default, locations.PURIFICATION_LOCATION_COUNT)


class TestPurificationCapIsValidatedPerSeed(unittest.TestCase):
    """Player: "Throw an error if they choose a cap higher than what the expansion gives them." """

    def _build(self, cap: int, expansion: int):
        from test.general import gen_steps, setup_multiworld
        from worlds.AutoWorld import AutoWorldRegister

        return setup_multiworld(
            AutoWorldRegister.world_types["Pokemon XD Gale of Darkness"],
            gen_steps, seed=99,
            options={"purification_progression_cap": cap, "shadow_pokemon_expansion": expansion},
        )

    def test_a_cap_above_the_seeds_own_shadow_count_is_an_error(self) -> None:
        with self.assertRaises(Exception) as caught:
            self._build(cap=100, expansion=0)
        self.assertIn("Shadow Pokemon to purify", str(caught.exception))

    def test_the_same_cap_is_fine_once_the_expansion_supplies_the_shadows(self) -> None:
        self._build(cap=100, expansion=44)   # 83 + 44 = 127, so 100 is inside the seed's own bound

    def test_the_boundary_itself_is_allowed(self) -> None:
        self._build(cap=83, expansion=0)


class TestOrreColosseumIsOutOfLogic(unittest.TestCase):
    def test_its_travel_item_opens_a_region_of_its_own(self) -> None:
        self.assertEqual(travel_locations.TRAVEL_LOCATION_TARGET_REGION["Orre Colosseum"],
                         travel_locations.ORRE_COLOSSEUM_REGION)

    def test_that_region_is_not_on_the_story_chain(self) -> None:
        self.assertNotIn(travel_locations.ORRE_COLOSSEUM_REGION, region_module.REGION_NAMES)
        for source, target, _required in region_module.REGION_EDGES:
            self.assertNotEqual(target, travel_locations.ORRE_COLOSSEUM_REGION)
            self.assertNotEqual(source, travel_locations.ORRE_COLOSSEUM_REGION)

    def test_the_check_is_still_gettable(self) -> None:
        """Player: "Leave Orre Colosseum as a gettable location". Where the CHECK fires and what the ITEM opens
        are different questions, and this is the one destination where they differ."""
        name = travel_locations.travel_unlock_location_name("Orre Colosseum")
        self.assertIn(name, locations.TRAVEL_UNLOCK_LOCATION_NAMES)
        self.assertIsNotNone(travel_locations.vanilla_unlock_story_byte("Orre Colosseum"))
        self.assertEqual(travel_locations.TRAVEL_UNLOCK_STORY_REGION["Orre Colosseum"], "Realgam Tower")

    def test_nothing_else_ever_named_it(self) -> None:
        """There were no Orre Colosseum trainers or chests to strip: no chest room maps to it and no census row
        names it, so the fold into Realgam Tower WAS the whole of its presence in the logic."""
        from ..game_data import chest_regions, trainer_placements

        self.assertNotIn("Orre Colosseum", set(chest_regions.ROOM_TO_REGION.values()))
        self.assertNotIn("Orre Colosseum",
                         {p.region for p in trainer_placements.PLACEMENTS.values() if p.region})


class TestOrreInAWorld(PokemonXDTestBase):
    options = {"randomize_travel_locations": True}

    def test_the_region_exists_and_holds_nothing(self) -> None:
        region = self.multiworld.get_region(travel_locations.ORRE_COLOSSEUM_REGION, self.player)
        self.assertEqual(list(region.locations), [])

    def test_its_item_is_not_a_second_key_to_realgam_tower(self) -> None:
        """The whole point: before ADDENDUM 185, holding the Orre Colosseum unlock opened Realgam Tower, which
        already had its own key."""
        self.collect_by_name("Travel Unlock - Orre Colosseum")
        self.assertFalse(self.multiworld.state.can_reach("Realgam Tower", player=self.player))


if __name__ == "__main__":
    unittest.main()
