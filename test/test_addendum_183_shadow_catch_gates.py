"""ADDENDUM 183 (2026-09-13): Shadow Pokemon catches are gated by the snag floor and their holder's own logic.

Player instruction, verbatim: "Catch Eevee is the starter pokemon, yes. Eeveelution is accessible so long as
gateon is, which is always. Make shadow pokemon catches excluded UNTIL we have pyrite town and the miror radar
(vanilla location.) Gate the pokemon by which trainer they were given to/their location/their logic. Include
our generated shadow pokemon."

This closes ADDENDUM 182's F1, which made five of ten audited seeds unwinnable: `rules._SPECIES_TO_REGION` is
built from ORDINARY (DPKM) trainer teams, while every species that gets a catch location comes from the DDPK
shadow table or a Poke Spot -- so 61 of 133 catch locations carried no access rule at all, sat in the
always-open `Pokemon Storage` region, and were fully progression-eligible.

The last class here is the important one: it tests the GUARD rather than the fix, because the fix is the kind
that can be half-undone by a later edit without anything failing.
"""
from __future__ import annotations

import unittest

from BaseClasses import Location, LocationProgressType

from . import PokemonXDTestBase
from .. import locations, rules, species
from ..game_data import shadow_regions, trainer_placements


class TestLabelJoin(unittest.TestCase):
    """The label -> trainer -> gate join, tested without a world."""

    def test_a_shadow_slots_location_name_yields_its_trainer_label(self) -> None:
        self.assertEqual(
            shadow_regions.trainer_label_from_location("Shadow Defeat - Spy Naps (Teddiursa)"),
            "Spy Naps",
        )
        # "Miror B." is a two-word surname with a period in it -- the reason the roster match is a longest-
        # suffix search rather than a split on spaces.
        self.assertEqual(
            shadow_regions.trainer_label_from_location("Shadow Defeat - Wanderer Miror B. (Ludicolo)"),
            "Wanderer Miror B.",
        )
        # Anything unrecognised comes back unchanged rather than raising -- it then fails to match a surname
        # and resolves to None, which is an answer the callers handle.
        self.assertEqual(shadow_regions.trainer_label_from_location("nonsense"), "nonsense")

    def test_the_final_boss_resolves_to_citadark_isle(self) -> None:
        """Greevil holds Shadow Lugia. ADDENDUM 182's first pass matched names case-sensitively -- the roster
        is upper-case and the shadow list is title-case -- and silently resolved him to no region at all, which
        is exactly how a Robo Kyogre Part ended up logically obtainable on `Catch - Lugia`. Same casing trap as
        ADDENDUM 144, different file."""
        gate = shadow_regions.gate_for_label("Cipher Boss Greevil")
        self.assertIsNotNone(gate)
        self.assertEqual(gate.region, "Citadark Isle")

    def test_a_trainer_the_census_left_unplaced_resolves_to_none(self) -> None:
        """37 census rows are region=None on purpose. None has to stay None -- inventing a region would put a
        fake requirement on a check, and the caller's job is to make such a location filler-only."""
        unplaced = sorted(trainer_placements.FILLER_ONLY_INDICES)
        self.assertTrue(unplaced)
        for index in unplaced:
            self.assertIsNone(shadow_regions.gate_for_trainer_index(index))

    def test_a_placed_trainer_carries_its_extra_items_and_regions_too(self) -> None:
        """"Their logic" is the whole census row, not just the region."""
        with_items = [i for i in trainer_placements.PLACED_INDICES
                      if (trainer_placements.placement_for(i).required_items
                          or trainer_placements.placement_for(i).required_regions)]
        self.assertTrue(with_items, "no census row carries extra requirements -- this test has nothing to prove")
        for index in with_items:
            placement = trainer_placements.placement_for(index)
            gate = shadow_regions.gate_for_trainer_index(index)
            self.assertIsNotNone(gate)
            self.assertEqual(gate.required_items, tuple(placement.required_items))
            self.assertEqual(gate.required_regions, tuple(placement.required_regions))

    def test_the_purification_ladder_is_unchanged_by_the_refactor(self) -> None:
        """`shadow_regions_in_graph_order` now calls the same `gate_for_label` the catch rules do, instead of
        carrying its own copy of the join. The ladder's own contract must not have moved: rules.py asserts the
        weights sum to exactly PURIFICATION_LOCATION_COUNT."""
        self.assertEqual(shadow_regions.total_shadow_count(), 83)
        weights = shadow_regions.purification_weights(locations.PURIFICATION_LOCATION_COUNT)
        self.assertEqual(sum(weights.values()), locations.PURIFICATION_LOCATION_COUNT)


class TestSnagFloorIsTwoRegionsNotAnItem(unittest.TestCase):
    def test_the_floor_names_pyrite_town_and_the_poke_spots(self) -> None:
        self.assertEqual(rules._SNAG_FLOOR_REGIONS, ("Pyrite Town", "Poke Spots"))

    def test_the_miror_radar_is_never_named_as_an_item_anywhere_in_the_rules(self) -> None:
        """ADDENDUM 168's rule, and the reason the floor is spelled as a region. The Miror Radar is not in the
        pool in ANY mode -- key_item_chests.KEPT_VANILLA leaves chest 77 alone whether or not key_item_shuffle
        is on -- so `state.has("Miror Radar")` would make every shadow catch unreachable forever, silently."""
        import pathlib

        source = (pathlib.Path(__file__).resolve().parent.parent / "rules.py").read_text(encoding="utf-8")
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # the section comment explains exactly this, and says the words
            if "Miror Radar" in stripped and "state.has" in stripped:
                self.fail(f"rules.py names the Miror Radar as an item: {stripped}")

    def test_the_radars_vanilla_chest_really_is_in_the_region_the_floor_names(self) -> None:
        """If chest 77 ever moves region, the floor stops meaning "you have the Radar" and this fails rather
        than quietly gating on the wrong place."""
        from ..game_data import chest_regions, key_item_chests

        self.assertIn(rules._MIROR_RADAR_CHEST_ID, key_item_chests.KEPT_VANILLA)
        self.assertNotIn(rules._MIROR_RADAR_CHEST_ID,
                         key_item_chests.chest_ids_to_convert(shuffle_key_items=True))
        self.assertEqual(chest_regions.CHEST_TO_REGION[rules._MIROR_RADAR_CHEST_ID], "Poke Spots")
        self.assertIn("Poke Spots", rules._SNAG_FLOOR_REGIONS)


class TestCatchGatesInAWorld(PokemonXDTestBase):
    options = {
        "key_item_shuffle": True,
        "shadow_pokemon_expansion": 44,
        "progression_locations": 2,
        "randomize_shadow_species": True,
    }

    def _gates(self):
        return rules._catch_gates_for_species(self.multiworld.worlds[self.player])

    def test_every_obtainable_species_resolves_to_a_source(self) -> None:
        """The bug this addendum fixes was a table keyed on one population and read for another. This asserts
        the two now line up: every species with a catch location has either a gate or an explicit 'unplaceable'
        verdict, and nothing falls between."""
        gates, unplaceable = self._gates()
        known = set(gates) | unplaceable
        missing = []
        for dex in (self.multiworld.worlds[self.player]._obtainable_species_dex or set()):
            if dex == rules._GUARANTEED_EEVEE_DEX:
                continue
            name = species.location_name_for_species(dex)
            try:
                self.multiworld.get_location(name, self.player)
            except KeyError:
                continue
            if dex not in known:
                missing.append(name)
        self.assertEqual(missing, [], "catch locations exist for species with no resolved source at all")

    def test_generated_shadows_are_included(self) -> None:
        """Player: "Include our generated shadow pokemon." With shadow_pokemon_expansion at 44 there are
        expansion-hosted species, and each must resolve through its HOST trainer's index."""
        world = self.multiworld.worlds[self.player]
        hosts = getattr(world, "_shadow_catch_expansion_hosts", {})
        self.assertTrue(hosts, "no generated shadows in this seed -- the test cannot prove anything")
        gates, unplaceable = self._gates()
        for dex, indices in hosts.items():
            self.assertIn(dex, set(gates) | unplaceable)
            if dex in gates:
                placed = [i for i in indices if trainer_placements.region_for(i) is not None]
                if placed:
                    regions_named = {g.region for g in gates[dex] if g != "pokespot"}
                    self.assertTrue(
                        regions_named & {trainer_placements.region_for(i) for i in placed}
                        or any(g == "pokespot" for g in gates[dex]),
                        f"dex {dex} has an expansion host but none of its gates name that host's region",
                    )

    def test_a_shadow_catch_is_closed_on_an_empty_state(self) -> None:
        """The headline: with nothing collected, a shadow-sourced catch must not read as reachable. Before this
        addendum, 61 of them did."""
        gates, _unplaceable = self._gates()
        checked = 0
        for dex, sources in gates.items():
            if dex == rules._GUARANTEED_EEVEE_DEX:
                continue
            if all(source == "pokespot" for source in sources):
                continue  # wild, not snagged -- no floor applies
            name = species.location_name_for_species(dex)
            try:
                location = self.multiworld.get_location(name, self.player)
            except KeyError:
                continue
            self.assertFalse(
                location.can_reach(self.multiworld.state),
                f"{name} is reachable with nothing collected, but its source is a Shadow Pokemon",
            )
            checked += 1
        self.assertGreater(checked, 20, "too few shadow-sourced catches examined to be meaningful")

    def test_an_unplaceable_species_is_filler_only_rather_than_ungated(self) -> None:
        """A species whose every source is a census row the player marked filler-only has no honest gate. The
        safe answer is EXCLUDED -- never 'leave it open and progression-eligible', which is the exact shape
        ADDENDUM 182 found fatal."""
        _gates, unplaceable = self._gates()
        seen = 0
        for dex in unplaceable:
            name = species.location_name_for_species(dex)
            try:
                location = self.multiworld.get_location(name, self.player)
            except KeyError:
                continue
            self.assertEqual(location.progress_type, LocationProgressType.EXCLUDED, name)
            seen += 1
        if not seen:
            self.skipTest("this seed produced no unplaceable species")

    def test_eevee_is_ungated_and_the_eeveelution_check_is_gated_on_gateon(self) -> None:
        eevee = self.multiworld.get_location(locations.GUARANTEED_SPECIES_LOCATION, self.player)
        self.assertIs(eevee.access_rule, Location.access_rule,
                      "Catch - Eevee is the starter and must carry no rule at all")
        self.assertTrue(eevee.can_reach(self.multiworld.state))

        evo = self.multiworld.get_location(locations.EEVEELUTION_LOCATION_NAME, self.player)
        self.assertIsNot(evo.access_rule, Location.access_rule)
        # Gateon Port is always open, so the rule is a no-op today -- written anyway so a future graph change
        # cannot silently move the requirement.
        self.assertTrue(evo.can_reach(self.multiworld.state))
        self.assertEqual(rules._EEVEELUTION_REGION, "Gateon Port")


class TestTheGuard(PokemonXDTestBase):
    """The assertion in set_all_rules, tested by breaking the world on purpose.

    This is the test that matters most. The fix above is a rule table; a later edit can drop a species out of
    it without anything failing, because a MISSING rule is silent by construction. The guard is what converts
    that class of mistake into a generation error, so the guard itself has to be exercised."""

    options = {"progression_locations": 2}

    def test_it_fires_when_a_bucket_location_is_ungated_and_progression_eligible(self) -> None:
        region = self.multiworld.get_region("Pokemon Storage", self.player)
        victim = next(
            (loc for loc in region.locations
             if loc.name != locations.GUARANTEED_SPECIES_LOCATION
             and loc.progress_type != LocationProgressType.EXCLUDED),
            None,
        )
        if victim is None:
            self.skipTest("no gated, progression-eligible catch location in this seed")
        original = victim.access_rule
        victim.access_rule = Location.access_rule  # the exact shape of the ADDENDUM 182 bug
        try:
            with self.assertRaises(AssertionError) as caught:
                rules._assert_no_ungated_progression_in_an_always_open_bucket(
                    self.multiworld.worlds[self.player]
                )
            self.assertIn(victim.name, str(caught.exception))
        finally:
            victim.access_rule = original

    def test_it_passes_on_an_untouched_world(self) -> None:
        rules._assert_no_ungated_progression_in_an_always_open_bucket(self.multiworld.worlds[self.player])

    def test_it_covers_every_bucket_region_the_graph_hangs_off_menu(self) -> None:
        """If a new bucket region is added and not listed here, the guard would not watch it."""
        from .. import regions as region_module

        menu = self.multiworld.get_region("Menu", self.player)
        hung_off_menu = {
            exit_.connected_region.name for exit_ in menu.exits
            if exit_.connected_region is not None
        }
        buckets = {name for name in hung_off_menu
                   if name not in region_module.REGION_NAMES and not name.startswith("Travel Gateway - ")}
        self.assertTrue(buckets <= rules._ALWAYS_OPEN_BUCKET_REGIONS,
                        f"unwatched bucket region(s): {sorted(buckets - rules._ALWAYS_OPEN_BUCKET_REGIONS)}")


if __name__ == "__main__":
    unittest.main()
