"""ADDENDUM 486 (2026-10-13) -- no two Shadow Pokemon share an evolution line.

No two Shadow Pokemon are ever of the same evolution line.

Applies wherever a Shadow's species is CHOSEN: Randomize Shadow Species, No Legendary Shadows' replacements, and the
Shadow Pokemon Expansion. With Randomize Shadow Species off the 83 keep their vanilla species, which hold exactly one
shared line (Hitmonchan and Hitmonlee, both Tyrogue's); the expansion still avoids every vanilla line.
"""
from __future__ import annotations

import unittest
from collections import Counter

from . import PokemonXDTestBase
from ..game_data import load_json_data_file
from ..game_data.evolution_data import family_of_internal, family_root
from ..tools.xd_species_index import INTERNAL_INDEX_TO_NATIONAL_DEX


def _shadow_species(world) -> "list[int]":
    assignment = getattr(world, "_shadow_species_assignment", None)
    if assignment:
        species = [e["new_species_index"] for e in assignment["entries"]]
    else:
        species = [int(e["species"]) for e in load_json_data_file("deckdata_dark_pokemon.json")]
    species += [m["species"] for p in (world._shadow_expansion_plans or ()) for m in p["new_pokemon"]]
    return species


def _shared_lines(species) -> "dict[int, list[str]]":
    by_line: "dict[int, list[str]]" = {}
    for s in species:
        by_line.setdefault(family_of_internal(s), []).append(INTERNAL_INDEX_TO_NATIONAL_DEX.get(s, (s, s))[1])
    return {line: names for line, names in by_line.items() if len(names) > 1}


class TestFamilies(unittest.TestCase):
    def test_lines(self) -> None:
        self.assertEqual(family_root(155), family_root(157))
        self.assertEqual(family_root(106), family_root(107))
        self.assertEqual(family_root(236), family_root(237))
        self.assertEqual(family_root(133), family_root(196))
        self.assertNotEqual(family_root(25), family_root(1))


class TestRandomizedFull(PokemonXDTestBase):
    options = {"randomize_shadow_species": True, "shadow_pokemon_expansion": 44}

    def test_no_line_twice(self) -> None:
        species = _shadow_species(self.multiworld.worlds[self.player])
        self.assertEqual(127, len(species))
        self.assertEqual({}, _shared_lines(species))


class TestRandomizedWithLegendaryOptions(PokemonXDTestBase):
    options = {"randomize_shadow_species": True, "shadow_pokemon_expansion": 30, "no_legendary_shadows": True,
               "shuffle_shadow_lugia": True}

    def test_no_line_twice(self) -> None:
        self.assertEqual({}, _shared_lines(_shadow_species(self.multiworld.worlds[self.player])))


class TestNoLegendaryVanillaSpecies(PokemonXDTestBase):
    options = {"randomize_shadow_species": False, "no_legendary_shadows": True, "shadow_pokemon_expansion": 44}

    def test_only_the_vanilla_pair_remains(self) -> None:
        shared = _shared_lines(_shadow_species(self.multiworld.worlds[self.player]))
        self.assertEqual([family_root(106)], list(shared), "Hitmonchan/Hitmonlee are vanilla; nothing else")


class TestManySeeds(unittest.TestCase):
    def test_no_line_twice_across_seeds(self) -> None:
        from test.general import gen_steps, setup_multiworld
        from worlds.AutoWorld import AutoWorldRegister

        world_type = AutoWorldRegister.world_types["Pokemon XD Gale of Darkness"]
        for seed in range(4861, 4869):
            multiworld = setup_multiworld(world_type, ("generate_early",), seed=seed,
                                          options={"randomize_shadow_species": True,
                                                   "shadow_pokemon_expansion": 44})
            species = _shadow_species(multiworld.worlds[1])
            self.assertEqual({}, _shared_lines(species), seed)
            self.assertEqual(len(species), len(set(species)), seed)


if __name__ == "__main__":
    unittest.main()
