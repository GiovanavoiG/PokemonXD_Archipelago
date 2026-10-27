"""ADDENDUM 457 (2026-10-09) -- everything Miror B. is filler-only.

Losing to Miror B. makes him leave, so every Miror B. check (his team's Shadows included) is filler.
"""
from __future__ import annotations

from BaseClasses import LocationProgressType

from . import PokemonXDTestBase
from .. import locations as L
from .. import species
from ..game_data import shadow_regions, trainer_roster


def _assert_all_miror_b_filler(case) -> None:
    world = case.multiworld.worlds[case.player]
    created = {loc.name: loc for loc in case.multiworld.get_locations(case.player)}
    expected = L.miror_b_filler_location_names(world) & set(created)
    case.assertTrue(expected, "some Miror B. check exists in this seed")
    for name in expected:
        if name in (species.location_name_for_species(int(getattr(world, "starter_dex", 133))),
                    L.EEVEELUTION_LOCATION_NAME):
            continue
        case.assertEqual(LocationProgressType.EXCLUDED, created[name].progress_type, name)
    return world, created


class TestTheRows(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": "unique"}

    def test_nine_fights(self) -> None:
        rows = L.miror_b_trainer_indices()
        self.assertEqual(9, len(rows))
        self.assertTrue(all(trainer_roster.TRAINERS_BY_INDEX[i]["name"] == "MIROR B." for i in rows))

    def test_the_any_check_is_a_standing_exclusion(self) -> None:
        from ..game_data import repeatable_trainers as RT
        self.assertIn("Defeat Miror B. (Any)", RT.ALWAYS_FILLER_LOCATIONS)

    def test_his_three_shadows_are_known(self) -> None:
        carried = {ddpk for ddpk, rows in shadow_regions.shadow_carriers().items() if set(rows) & L.miror_b_trainer_indices()}
        self.assertEqual({13, 29, 80}, carried)

    def test_every_defeat_and_catch_is_filler(self) -> None:
        world, created = _assert_all_miror_b_filler(self)
        defeats = {n for n in created if "Miror B." in n}
        self.assertTrue(defeats, "his defeat checks exist in unique mode")
        catches = {n for n in L.miror_b_filler_location_names(world) if n.startswith("Catch - ") and n in created}
        self.assertTrue(catches, "his Shadows' catch checks are covered")


class TestCumulativeMode(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": "cumulative"}

    def test_the_named_any_check(self) -> None:
        _world, created = _assert_all_miror_b_filler(self)
        for name in created:
            if "Miror B." in name:
                self.assertEqual(LocationProgressType.EXCLUDED, created[name].progress_type, name)


class TestWildCatchesNeedOnlyThePokeSpots(PokemonXDTestBase):
    """Wild Pokemon (the catches that are not Shadows) need the Poke Spots and nothing else."""
    options = {"randomize_travel_locations": True}

    def test_the_constant(self) -> None:
        from .. import rules
        self.assertEqual((), rules.WILD_CATCH_ANY_REGIONS)

    def test_a_poke_spot_only_species(self) -> None:
        from .. import rules
        world = self.multiworld.worlds[self.player]
        gates, _unplaceable = rules._catch_gates_for_species(world)
        wild_only = [dex for dex, sources in gates.items() if sources and all(s == "pokespot" for s in sources)
                     and dex != int(getattr(world, "starter_dex", 133))]
        created = {loc.name: loc for loc in self.multiworld.get_locations(self.player)}
        wild_only = [d for d in wild_only if species.location_name_for_species(d) in created]
        self.assertTrue(wild_only, "the vanilla Poke Spot species have no Shadow source")
        name = species.location_name_for_species(wild_only[0])
        self.assertFalse(self.can_reach_location(name))
        self.collect_by_name("Travel Unlock - Poke Spots")
        self.assertTrue(self.can_reach_location(name), "the Poke Spots alone are enough")


class TestRandomizedShadows(PokemonXDTestBase):
    options = {"randomize_shadow_species": True, "shadow_catch_progression": True}

    def test_the_species_now_on_his_teams(self) -> None:
        world, created = _assert_all_miror_b_filler(self)
        dex = L.miror_b_shadow_dex(world)
        self.assertTrue(dex)
        for d in dex:
            name = species.location_name_for_species(d)
            if name in created and name != species.location_name_for_species(int(getattr(world, "starter_dex", 133))):
                self.assertEqual(LocationProgressType.EXCLUDED, created[name].progress_type, name)
