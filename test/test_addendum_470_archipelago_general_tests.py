"""ADDENDUM 470 (2026-10-12) -- two of Archipelago's own general tests failed on aptests.ionium.fyi.

  * `test_item_name_group_has_valid_item`: "Krane Memos" named 'Data ROM' and 'ID Card', the two halves ADDENDUM 443
    took out of the datapackage.
  * `test_itempool_not_modified` (pre_fill): Citadark Story Weight removed Parts from the itempool in pre_fill and
    placed them. The roll and the choice now happen in create_items; the held Parts live in `get_pre_fill_items`
    and pre_fill only places them.

Both are re-run here the way Archipelago runs them, with the Story Weight forced on so the second one bites.
"""
from __future__ import annotations

import unittest

from worlds.AutoWorld import call_all

from . import PokemonXDTestBase
from .. import PokemonXDWorld, items


class TestItemGroups(unittest.TestCase):
    def test_every_group_member_is_in_the_datapackage(self) -> None:
        for group, members in PokemonXDWorld.item_name_groups.items():
            for name in members:
                self.assertIn(name, PokemonXDWorld.item_name_to_id, group)

    def test_no_group_is_an_item(self) -> None:
        for group in PokemonXDWorld.item_name_groups:
            self.assertNotIn(group, PokemonXDWorld.item_name_to_id)

    def test_the_retired_halves_still_hint_the_combined_item(self) -> None:
        for part in items.COMBINED_KEY_ITEM_PARTS:
            self.assertEqual({items.COMBINED_KEY_ITEM_NAME}, PokemonXDWorld.item_name_groups[part])
            # RETARGETED BY ADDENDUM 483: "Krane Memos" is gone (issue #4); "Key Items" holds the combined item.
            self.assertNotIn(part, PokemonXDWorld.item_name_groups["Key Items"])


class _ItempoolNotModified:
    """Archipelago's `test_itempool_not_modified`, on this world with these options."""

    def test_itempool_not_modified(self) -> None:
        multiworld = self._build(("generate_early", "create_regions", "create_items"))
        created = multiworld.itempool.copy()
        for step in ("set_rules", "connect_entrances", "generate_basic", "pre_fill"):
            call_all(multiworld, step)
            self.assertEqual(created, multiworld.itempool, step)

    def _build(self, steps):
        from test.general import setup_multiworld
        return setup_multiworld(PokemonXDWorld, steps, seed=self.seed, options=dict(self.options))


class TestStoryWeightOn(_ItempoolNotModified, unittest.TestCase):
    options = {"randomize_travel_locations": 0, "robo_kyogre_parts_unlock_citadark": 1,
               "citadark_story_weight": 100, "robo_kyogre_parts_available": 10, "robo_kyogre_parts_required": 7}
    seed = 470

    def test_held_parts_are_placed_late_and_counted(self) -> None:
        multiworld = self._build(("generate_early", "create_regions", "create_items"))
        world = multiworld.worlds[1]
        held = list(world._story_bound_part_items)
        self.assertEqual(10 - 7 + 1, len(held))
        self.assertFalse(any(item is other for item in held for other in multiworld.itempool))   # Item == is by name
        self.assertEqual(held, world.get_pre_fill_items())
        in_pool = sum(1 for i in multiworld.itempool if i.name == items.MACGUFFIN_ITEM_NAME)
        self.assertEqual(10, in_pool + len(held))
        # pool + held == locations: nothing is left over or short once pre_fill has placed them
        self.assertEqual(len(multiworld.get_unfilled_locations(1)), len(multiworld.itempool) + len(held))
        for step in ("set_rules", "connect_entrances", "generate_basic", "pre_fill"):
            call_all(multiworld, step)
        self.assertTrue(all(item.location is not None and item.location.locked for item in held))
        self.assertEqual([], world.get_pre_fill_items())
        late = {loc.name for region in world.LATE_STORY_REGIONS
                for loc in multiworld.get_region(region, 1).locations}
        self.assertTrue(all(item.location.name in late for item in held))
        self.assertEqual(len(held), world._story_bound_parts)
        # the all-state still has every Part, held or not
        state = multiworld.get_all_state(False)
        self.assertEqual(10, state.count(items.MACGUFFIN_ITEM_NAME, 1))

    def test_a_second_pre_fill_changes_nothing(self) -> None:
        multiworld = self._build(("generate_early", "create_regions", "create_items", "set_rules",
                                  "connect_entrances", "generate_basic", "pre_fill"))
        world = multiworld.worlds[1]
        where = [item.location for item in world._story_bound_part_items]
        call_all(multiworld, "pre_fill")
        self.assertEqual(where, [item.location for item in world._story_bound_part_items])


class TestStoryWeightOff(_ItempoolNotModified, unittest.TestCase):
    options = {"randomize_travel_locations": 0, "robo_kyogre_parts_unlock_citadark": 1, "citadark_story_weight": 0}
    seed = 471

    def test_nothing_held(self) -> None:
        multiworld = self._build(("generate_early", "create_regions", "create_items"))
        self.assertEqual([], multiworld.worlds[1].get_pre_fill_items())


class TestTravelShuffle(_ItempoolNotModified, unittest.TestCase):
    options = {"randomize_travel_locations": 1, "citadark_story_weight": 100}
    seed = 472


class TestDefaults(_ItempoolNotModified, unittest.TestCase):
    options = {}
    seed = 473


class TestAFullGenerationStillFills(unittest.TestCase):
    def test_fill_and_beatable(self) -> None:
        from Fill import distribute_items_restrictive
        from test.general import gen_steps, setup_multiworld
        for seed in range(3):
            multiworld = setup_multiworld(PokemonXDWorld, gen_steps, seed=4700 + seed,
                                          options={"randomize_travel_locations": 0, "citadark_story_weight": 100,
                                                   "robo_kyogre_parts_unlock_citadark": 1})
            distribute_items_restrictive(multiworld)
            self.assertEqual([], multiworld.get_unfilled_locations(1), seed)
            self.assertEqual([], multiworld.worlds[1].get_pre_fill_items(), seed)
            self.assertTrue(multiworld.can_beat_game(multiworld.get_all_state(False)), seed)


if __name__ == "__main__":
    unittest.main()
