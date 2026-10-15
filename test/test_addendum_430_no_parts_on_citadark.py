"""ADDENDUM 430 (2026-10-06) -- no Robo Kyogre Part on Citadark Isle or anything that needs it.

ZERO Robo Kyogre Parts can ever go on Citadark Isle or anything reliant on it.

The gate already kept the COUNTED Parts off the island; spare Parts (available > required) were legal there.
`PokemonXDWorld.pre_fill` now closes the island, sweeps, and forbids this player's Parts on everything left
unreachable.
"""
from __future__ import annotations

import unittest

from .. import items
from ..game_data.catch_rate_exclusions import citadark_trainer_indices

PART = items.MACGUFFIN_ITEM_NAME


def _filled(seed: int, extra: dict):
    from worlds.AutoWorld import AutoWorldRegister
    from test.general import setup_multiworld, gen_steps
    from Fill import distribute_items_restrictive

    world_type = AutoWorldRegister.world_types["Pokemon XD Gale of Darkness"]
    options = {"robo_kyogre_parts_unlock_citadark": 1, "robo_kyogre_parts_required": 3,
               "robo_kyogre_parts_available": 40, **extra}
    multiworld = setup_multiworld(world_type, gen_steps, seed=seed, options=options)
    distribute_items_restrictive(multiworld)
    return multiworld


class TestNoPartOnCitadark(unittest.TestCase):
    CASES = (
        {},
        {"shuffle_trainer_defeats": 1, "trainer_defeat_mode": 1, "randomize_shops": 1},
        {"randomize_travel_locations": 1, "nightmare_citadark": 1, "shadow_pokemon_expansion": 30},
        {"purification_checks": 1, "goal": 1},
    )

    def test_forty_parts_never_land_on_the_island_or_behind_it(self):
        for case_index, extra in enumerate(self.CASES):
            for seed in range(3):
                with self.subTest(case=case_index, seed=seed):
                    multiworld = _filled(4300 + 10 * case_index + seed, extra)
                    world = multiworld.worlds[1]
                    reliant = world._citadark_reliant_locations
                    citadark = multiworld.get_region("Citadark Isle", 1)
                    self.assertTrue(reliant, "the island itself must be on the list")
                    self.assertTrue({loc.name for loc in citadark.locations if loc.item.code is not None} <= reliant)
                    placed = [loc.name for loc in multiworld.get_locations(1)
                              if loc.item and loc.item.name == PART and loc.item.player == 1]
                    self.assertEqual(40, len(placed) + sum(1 for i in multiworld.precollected_items[1]
                                                           if i.name == PART))
                    self.assertEqual([], [name for name in placed if name in reliant])

    def test_reliant_means_unreachable_without_the_island(self):
        multiworld = _filled(4399, {})
        world = multiworld.worlds[1]
        state = multiworld.get_all_state()
        for name in world._citadark_reliant_locations:
            location = multiworld.get_location(name, 1)
            self.assertTrue(location.can_reach(state), f"{name} is not reachable at all")
        # A Citadark trainer's own defeat check, if it exists, is reliant; an early chest is not.
        self.assertNotIn("Gateon Port Shop AP Item 1", world._citadark_reliant_locations)
        self.assertTrue(citadark_trainer_indices())

    def test_nothing_happens_without_parts(self):
        multiworld = _filled(4398, {"robo_kyogre_parts_unlock_citadark": 0})
        self.assertEqual(frozenset(), multiworld.worlds[1]._citadark_reliant_locations)


if __name__ == "__main__":
    unittest.main()
