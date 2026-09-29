"""Regression coverage for ADDENDUM 99's item-pool changes (player request, verbatim: "Add a '10 pokeballs'
item to the filler to receive, as well as '5 greatballs' and '3 ultra balls'. Remove White Flute, Heart Scale,
Razz Berry, Shoal Salt, all repel levels, and all of the colored shards (blue, green, etc) from the items I can
receive."). Pure data-table checks against items.py -- no MultiWorld/generation needed."""
from __future__ import annotations

import unittest

from .. import items


class TestNewBundleFillerItems(unittest.TestCase):
    def test_10_poke_balls_exists_with_correct_id_and_quantity(self) -> None:
        data = items.ITEM_TABLE["10 Poke Balls"]
        self.assertEqual(data.game_item_id, 4)  # same real Bag item id as the ordinary "Poke Ball"
        self.assertEqual(data.quantity, 10)
        self.assertEqual(data.classification, items.ItemClassification.filler)

    def test_5_great_balls_exists_with_correct_id_and_quantity(self) -> None:
        data = items.ITEM_TABLE["5 Great Balls"]
        self.assertEqual(data.game_item_id, 3)
        self.assertEqual(data.quantity, 5)
        self.assertEqual(data.classification, items.ItemClassification.filler)

    def test_3_ultra_balls_exists_with_correct_id_and_quantity(self) -> None:
        data = items.ITEM_TABLE["3 Ultra Balls"]
        self.assertEqual(data.game_item_id, 2)
        self.assertEqual(data.quantity, 3)
        self.assertEqual(data.classification, items.ItemClassification.filler)

    def test_bundle_items_are_in_the_random_filler_pool(self) -> None:
        for name in ("10 Poke Balls", "5 Great Balls", "3 Ultra Balls"):
            self.assertIn(name, items._RANDOM_FILLER_POOL)

    def test_ordinary_single_ball_items_still_have_quantity_1(self) -> None:
        # ItemData.quantity is a new field (ADDENDUM 99) -- every pre-existing item must default to 1, its
        # implicit behavior before this field existed, not silently pick up some other value.
        for name in ("Poke Ball", "Great Ball", "Ultra Ball", "Master Ball", "Rare Candy"):
            self.assertEqual(items.ITEM_TABLE[name].quantity, 1, f"{name} should still be quantity=1")

    def test_bundle_item_ids_are_frozen_and_unique(self) -> None:
        offsets = {items.ITEM_TABLE[name].id_offset for name in ("10 Poke Balls", "5 Great Balls", "3 Ultra Balls")}
        self.assertEqual(len(offsets), 3, "the 3 new bundle items must not collide on id_offset")
        # No collision with any other item's id_offset either.
        all_offsets = [data.id_offset for data in items.ITEM_TABLE.values()]
        self.assertEqual(len(all_offsets), len(set(all_offsets)), "items.py has a duplicate id_offset somewhere")


class TestRemovedItems(unittest.TestCase):
    REMOVED_NAMES = [
        "White Flute",
        "Heart Scale",
        "Razz Berry",
        "Shoal Salt",
        "Super Repel",
        "Max Repel",
        "Repel",
        "Red Shard",
        "Blue Shard",
        "Yellow Shard",
        "Green Shard",
    ]

    def test_removed_items_are_gone_from_item_table(self) -> None:
        for name in self.REMOVED_NAMES:
            self.assertNotIn(name, items.ITEM_TABLE, f"{name} should have been removed from ITEM_TABLE")

    def test_removed_items_are_gone_from_random_filler_pool(self) -> None:
        for name in self.REMOVED_NAMES:
            self.assertNotIn(name, items._RANDOM_FILLER_POOL, f"{name} should not be drawable as filler")

    def test_removed_items_are_gone_from_item_name_to_id(self) -> None:
        name_to_id = items.get_item_name_to_id(base_id=3_820_000)
        for name in self.REMOVED_NAMES:
            self.assertNotIn(name, name_to_id)

    def test_items_not_named_for_removal_are_untouched(self) -> None:
        # As of ADDENDUM 99, Escape Rope was NOT a "repel level" and Shoal Shell was NOT a "colored shard" --
        # neither was named by the player for removal at the time, so both survived this addendum's pass.
        # (Both were later removed by ADDENDUM 107 on separate "forbidden"/non-functional grounds -- see
        # test_addendum_107_item_removals.py -- so they are deliberately NOT asserted present here anymore.)
        # Every OTHER berry in the previously-kept Cheri-Iapapa range (all but the removed Razz) must survive.
        for name in (
            "Cheri Berry", "Chesto Berry", "Pecha Berry", "Rawst Berry", "Aspear Berry", "Leppa Berry",
            "Oran Berry", "Persim Berry", "Lum Berry", "Sitrus Berry", "Figy Berry", "Wiki Berry",
            "Mago Berry", "Aguav Berry", "Iapapa Berry",
        ):
            self.assertIn(name, items.ITEM_TABLE)
        # Black Flute was later removed by ADDENDUM 107 (see test_addendum_107_item_removals.py) -- Blue/
        # Yellow/Red Flute were confirmed functional and were not touched.
        for name in ("Blue Flute", "Yellow Flute", "Red Flute"):
            self.assertIn(name, items.ITEM_TABLE)


if __name__ == "__main__":
    unittest.main()
