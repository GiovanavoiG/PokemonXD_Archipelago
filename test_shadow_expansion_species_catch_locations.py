"""Regression coverage for ADDENDUM 99's shadow_pokemon_expansion fix (player report: "the created shadow
pokemon do not count for catch checks. I have a shadow swablu and I would have liked a check for Catch -
Swablu as well"). See __init__.py's generate_early() comment for the full root-cause writeup: a species that
ONLY appears via a Shadow Pokemon Expansion-added Shadow Pokemon (never a vanilla Shadow encounter or a Poke
Spot slot) used to be invisible to `_obtainable_species_dex`, so its "Catch - {species}" location was never
even created -- not a detection bug, an existence bug. This test confirms every species Shadow Pokemon
Expansion actually adds this seed gets its own "Catch - {species}" location."""
from __future__ import annotations

from . import PokemonXDTestBase
from .. import species
from ..tools.xd_species_index import national_dex_for


class TestShadowExpansionSpeciesGetCatchLocations(PokemonXDTestBase):
    # Maxed (44, the real disc-format ceiling -- see randomizer/shadow_expansion.py) to give this test the best
    # real chance of adding a species not already covered by the vanilla 83-Shadow-Pokemon roster or the 11
    # Poke Spot slots.
    options = {"shadow_pokemon_expansion": 44}

    def test_every_expansion_added_species_has_its_own_catch_location(self) -> None:
        plans = self.world._shadow_expansion_plans
        if not plans:
            self.skipTest("no real Shadow Pokemon Expansion ISO data available in this build -- nothing to "
                           "check (see __init__.py generate_early()'s own 'don't trim' fallback)")

        expansion_dex_numbers: set[int] = set()
        for plan in plans:
            for mon in plan["new_pokemon"]:
                dex = national_dex_for(mon["species"])
                # species.py's NATIONAL_DEX table (and therefore every "Catch - X" location) only ever covers
                # 1-386 by design -- its own module docstring calls this out explicitly, and
                # xd_species_index.py's internal_index_for_national_dex() docstring separately confirms 387/388
                # (Bonsly/Munchlax) are real, resolvable species that simply sit outside that range. This is a
                # pre-existing species.py scope boundary, not something ADDENDUM 99 touched or could fix without
                # widening species.py itself (out of scope for this player's request, which was specifically
                # about Swablu, dex 333 -- well inside range) -- so skip them here rather than asserting a
                # location that structurally cannot exist.
                if dex is not None and dex in species.NATIONAL_DEX:
                    expansion_dex_numbers.add(dex)

        self.assertTrue(expansion_dex_numbers, "shadow_pokemon_expansion=44 produced a plan with no resolvable "
                                                "species at all -- something upstream of this test is broken")

        all_location_names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        missing = []
        for dex in sorted(expansion_dex_numbers):
            location_name = species.location_name_for_species(dex)
            if location_name not in all_location_names:
                missing.append(location_name)
        self.assertEqual(
            missing, [],
            f"{len(missing)} expansion-added species have NO \"Catch - {{species}}\" location at all this "
            f"seed: {missing} -- this is the exact bug ADDENDUM 99 fixed (a caught/snagged Shadow Pokemon of "
            "one of these species could never fire a check, no matter what, because the location itself "
            "never existed)"
        )

    def test_obtainable_species_dex_includes_expansion_species(self) -> None:
        plans = self.world._shadow_expansion_plans
        if not plans:
            self.skipTest("no real Shadow Pokemon Expansion ISO data available in this build")
        obtainable = self.world._obtainable_species_dex
        self.assertIsNotNone(obtainable)
        for plan in plans:
            for mon in plan["new_pokemon"]:
                dex = national_dex_for(mon["species"])
                if dex is not None:
                    self.assertIn(
                        dex, obtainable,
                        f"expansion-added species dex {dex} is missing from world._obtainable_species_dex"
                    )
