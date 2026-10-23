"""ADDENDUM 185 (2026-09-14): five corrections, four of them about what may hold progression.

  1. Browsix, and everything post-Sixes, is gated behind the Music Disc and the Mayor's Note -- the 22 named
     Phenac trainer-defeat locations move into the Disc+Note tier.
  2. All of the Sixes are marked missable in the workbook, so they must not carry anything important -- the
     workbook's Missable? column is the fence again, and the named 66 inherit it (they had never been fenced
     at all).
  3. A toggle for Shadow Pokemon Catch checks being progression/useful or not, default off.
  4. The cap on the progression purification checks option rises to 127, limited to 83 + whatever the player
     selects for Shadow Pokemon Expansion, and a cap higher than what the expansion gives is an error.
  5. Orre Colosseum stays a gettable location, but it and all its trainers/chests leave the logic.
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
    # ADDENDUM 414: the named cumulative check is gone ("it should just be a tally"), so the probe is Egrog's
    # unique-mode check -- the same fight, the same Phenac (Post-Sixes) tier.
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": 1, 
               "key_item_shuffle": True}

    def test_a_phenac_trainer_is_closed_until_both_items_are_held(self) -> None:
        name = "Defeat - Egrog"  # census-confirmed Disc+Note, and not missable
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
        self.assertEqual(len(missable_trainers.MISSABLE_TRAINER_INDICES), 39)  # ADDENDUM 440: +4; 460: -13 now unmissable
        self.assertEqual(len(missable_trainers.UNREDOABLE_TRAINER_INDICES), 149)   # ADDENDUM 440: +4; 460: -6
        # ADDENDUM 407: minus Naps #2, the one mandatory rematch made progression-eligible.
        self.assertEqual(len(missable_trainers.FILLER_ONLY_TRAINER_INDICES), 148)   # ADDENDUM 440: +4; 460: -6
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

        # ADDENDUM 407 unfenced Naps #2 only; the Sixes' #2 fights stay filler.
        for index in (69, 147, 202, 120, 44):   # Aferd #2, Zook #2, Laken #3, Browsix #4, Greesix #2
            self.assertIn(index, missable_trainers.FILLER_ONLY_TRAINER_INDICES,
                          trainer_roster.trainer_label(trainer_roster.TRAINERS_BY_INDEX[index]))

    def test_a_non_missable_named_location_is_not_fenced(self) -> None:
        """Without this the test above could pass by fencing everything."""
        self.assertNotIn("Defeat - Cipher Peon Egrog", locations._MISSABLE_NAMED_TRAINER_LOCATIONS)


class TestNamedFenceInAWorld(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": 0}

    def test_browsix_cannot_hold_the_music_disc_any_more(self) -> None:
        # ADDENDUM 414: in the tally mode Browsix has no check at all. In unique mode his numbered fights are not
        # locations either (numbered rematch checks removed); only his (Any) remains.
        from ..game_data import missable_trainers as mt

        self.assertNotIn("Defeat - Cipher Peon Browsix",
                         {loc.name for loc in self.multiworld.get_locations(self.player)})
        self.assertNotIn("Defeat - Browsix #1", mt.filler_only_trainer_location_names())
        self.assertIn("Defeat - Browsix #1", trainer_roster.REMOVED_DEFEAT_LOCATIONS)
        self.assertNotIn("Defeat - Browsix #1", locations.LOCATION_TABLE)

    def test_it_is_not_a_location_in_the_tally_mode(self) -> None:
        # ADDENDUM 414: cumulative mode is only the tally now; the named check does not exist to hold anything.
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertNotIn("Defeat - Cipher Peon Browsix", names)


class TestShadowCatchToggle(PokemonXDTestBase):
    options = {"shadow_catch_progression": False}

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
    options = {"shadow_catch_progression": True,
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
    """A cap higher than what the seed's expansion gives is checked per seed."""

    def _build(self, cap: int, expansion: int):
        from test.general import gen_steps, setup_multiworld
        from worlds.AutoWorld import AutoWorldRegister

        return setup_multiworld(
            AutoWorldRegister.world_types["Pokemon XD Gale of Darkness"],
            gen_steps, seed=99,
            options={"purification_progression_cap": cap, "shadow_pokemon_expansion": expansion},
        )

    def test_a_cap_above_the_seeds_own_shadow_count_is_rounded_down(self) -> None:
        """ADDENDUM 406 replaced the error: refusals auto-adjust to valid settings instead, and purifications
        are rounded down if the cap is greater than the possible Shadows."""
        with self.assertLogs(level="WARNING") as logged:
            mw = self._build(cap=100, expansion=0)
        world = mw.worlds[1]
        # RETARGETED BY ADDENDUM 479: 75 -- the vanilla Shadows that can be had before the goal.
        self.assertEqual(75, int(world.options.purification_progression_cap))
        self.assertEqual([("purification_progression_cap", 100, 75)], world.option_adjustments)
        self.assertTrue(any("using 75 instead" in line for line in logged.output))
        self.assertEqual(75, world.fill_slot_data()["universal_tracker"]["options"]["purification_progression_cap"])

    def test_the_same_cap_is_fine_once_the_expansion_supplies_the_shadows(self) -> None:
        self._build(cap=100, expansion=44)   # 83 + 44 = 127, so 100 is inside the seed's own bound

    def test_the_boundary_itself_is_allowed(self) -> None:
        self._build(cap=83, expansion=0)


class TestOrreColosseumIsOutOfLogic(unittest.TestCase):
    """ADDENDUM 446 superseded this addendum's Orre half: no travel unlock for Orre Colosseum and no checks there.
    No item, no `Unlock -` check, no region."""

    def test_no_travel_item_and_no_region(self) -> None:
        self.assertNotIn("Orre Colosseum", travel_locations.TRAVEL_LOCATION_TARGET_REGION)
        self.assertNotIn("Orre Colosseum", travel_locations.TRAVEL_LOCATION_NAMES)
        self.assertNotIn(travel_locations.ORRE_COLOSSEUM_REGION, region_module.REGION_NAMES)
        for source, target, _required in region_module.REGION_EDGES:
            self.assertNotEqual(target, travel_locations.ORRE_COLOSSEUM_REGION)
            self.assertNotEqual(source, travel_locations.ORRE_COLOSSEUM_REGION)

    def test_no_check_is_there(self) -> None:
        name = travel_locations.travel_unlock_location_name("Orre Colosseum")
        self.assertNotIn(name, locations.TRAVEL_UNLOCK_LOCATION_NAMES)
        self.assertNotIn(name, locations.LOCATION_TABLE)
        self.assertEqual(1431, locations._FROZEN_LOCATION_OFFSETS[name], "the id stays reserved")

    def test_nothing_else_ever_named_it(self) -> None:
        """There were no Orre Colosseum trainers or chests to strip: no chest room maps to it and no census row
        names it, so the unlock check WAS the whole of its presence in the logic."""
        from ..game_data import chest_regions, trainer_placements

        self.assertNotIn("Orre Colosseum", set(chest_regions.ROOM_TO_REGION.values()))
        self.assertNotIn("Orre Colosseum",
                         {p.region for p in trainer_placements.PLACEMENTS.values() if p.region})


class TestOrreInAWorld(PokemonXDTestBase):
    options = {"randomize_travel_locations": True}

    def test_no_orre_item_or_location_in_a_seed(self) -> None:
        self.assertNotIn("Travel Unlock - Orre Colosseum", {i.name for i in self.multiworld.itempool})
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertFalse({n for n in names if "Orre Colosseum" in n})
        with self.assertRaises(KeyError):
            self.multiworld.get_region(travel_locations.ORRE_COLOSSEUM_REGION, self.player)


if __name__ == "__main__":
    unittest.main()
