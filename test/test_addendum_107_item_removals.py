"""Regression coverage for ADDENDUM 107's item-pool changes (2026-09-10, player request, verbatim: "Go ahead
and use our item list and walkthroughs/wikis to determine what items are useless. Remove all of them except for
Rabuta berry for our chest checks." Clarified on request: "The Shoal Items, Escape rope, etc all have
'forbidden' in their description and therefore can't be used. Go ahead and remove the trade evolution items
too."). Pure data-table checks against items.py -- no MultiWorld/generation needed.

Two removal grounds, 11 items total:
  1. "Forbidden"/non-functional in Pokemon Colosseum/XD (generic placeholder or explicit "cannot be used"
     description, confirmed per-item via Bulbapedia): Escape Rope, Black Flute, Shoal Shell, Cleanse Tag,
     Smoke Ball.
  2. Trade-evolution-only held items (this randomizer is single-player, trades never happen): King's Rock,
     DeepSeaTooth, DeepSeaScale, Metal Coat, Dragon Scale, Up-Grade.
"""
from __future__ import annotations

import unittest

from .. import items

REMOVED_HELD_ITEMS = [
    "King's Rock", "Cleanse Tag", "DeepSeaTooth", "DeepSeaScale", "Smoke Ball", "Metal Coat", "Dragon Scale",
    "Up-Grade",
]
REMOVED_OTHER_ITEMS = ["Black Flute", "Shoal Shell", "Escape Rope"]
ALL_REMOVED = REMOVED_HELD_ITEMS + REMOVED_OTHER_ITEMS

# Every SURVIVING held item's real Bag game_item_id, in the original 179-225 Gen III item-index order (see
# items.py's _HELD_ITEM_SPECS comment). This is the correctness property that matters most here: the old
# `179 + i` list-position formula would have silently shifted every item's id AFTER a removed one once any
# entry was deleted from the middle of the old _HELD_ITEM_NAMES list. These are spot-checks across items both
# before and after every removed slot.
SURVIVING_HELD_ITEM_IDS = {
    "BrightPowder": 179,
    "White Herb": 180,
    "Choice Band": 186,  # immediately before the first removed item (King's Rock, 187)
    "SilverPowder": 188,  # immediately after King's Rock
    "Amulet Coin": 189,  # immediately before Cleanse Tag (190)
    "Soul Dew": 191,  # immediately after Cleanse Tag, before DeepSeaTooth/DeepSeaScale/Smoke Ball (192-194)
    "Everstone": 195,  # immediately after the DeepSeaTooth/DeepSeaScale/Smoke Ball run
    "Scope Lens": 198,  # immediately before Metal Coat (199)
    "Leftovers": 200,  # between Metal Coat (199) and Dragon Scale (201)
    "Light Ball": 202,  # immediately after Dragon Scale
    "Silk Scarf": 217,  # immediately before Up-Grade (218)
    "Shell Bell": 219,  # immediately after Up-Grade
    "Stick": 225,  # last item in the whole table
}


class TestAddendum107Removals(unittest.TestCase):
    def test_removed_items_are_gone_from_item_table(self) -> None:
        for name in ALL_REMOVED:
            self.assertNotIn(name, items.ITEM_TABLE, f"{name} should have been removed from ITEM_TABLE")

    def test_removed_items_are_gone_from_random_filler_pool(self) -> None:
        for name in ALL_REMOVED:
            self.assertNotIn(name, items._RANDOM_FILLER_POOL, f"{name} should not be drawable as filler")

    def test_removed_items_are_gone_from_item_name_to_id(self) -> None:
        name_to_id = items.get_item_name_to_id(base_id=3_820_000)
        for name in ALL_REMOVED:
            self.assertNotIn(name, name_to_id)

    def test_surviving_held_items_keep_their_correct_real_game_item_id(self) -> None:
        # The regression this test exists to catch: if _HELD_ITEM_SPECS had stayed a list-position-based
        # formula and an entry were deleted from the middle, every item after it would silently point at the
        # WRONG real Bag item. Converting to explicit hardcoded ids (this addendum) avoids that; this test
        # locks the correct ids in place.
        for name, expected_id in SURVIVING_HELD_ITEM_IDS.items():
            self.assertEqual(
                items.ITEM_TABLE[name].game_item_id, expected_id, f"{name} has the wrong real game_item_id"
            )

    def test_no_duplicate_or_gap_breaking_id_offsets_after_removal(self) -> None:
        # The STABLE ID FREEZE mechanism must still produce unique id_offsets for every surviving item after
        # 11 entries are removed from the middle of their spec lists.
        all_offsets = [data.id_offset for data in items.ITEM_TABLE.values()]
        self.assertEqual(len(all_offsets), len(set(all_offsets)), "items.py has a duplicate id_offset somewhere")

    def test_rabuta_berry_still_excluded_and_untouched(self) -> None:
        # Confirms this addendum did not disturb Rabuta Berry's pre-existing protected/excluded role (the
        # player's own "except for Rabuta berry for our chest checks" instruction) -- it was already never a
        # receivable AP item before this pass (reserved as CHEST_DUMMY_GAME_ITEM_ID, ADDENDUM 19/31).
        self.assertNotIn("Rabuta Berry", items.ITEM_TABLE)
        self.assertEqual(items.CHEST_DUMMY_GAME_ITEM_ID, 161)

    def test_held_item_category_shrank_by_exactly_eight(self) -> None:
        self.assertEqual(len(items.HELD_ITEMS), 39)

    def test_shoal_shard_and_repel_categories_are_now_empty(self) -> None:
        # Both categories were already down to a single surviving entry before this addendum (prior removal
        # passes); removing that last entry each leaves them empty rather than deleted outright.
        self.assertEqual(len(items.SHOAL_SHARD_ITEMS), 0)
        self.assertEqual(len(items.REPEL_ITEMS), 0)

    def test_flute_category_shrank_by_exactly_one(self) -> None:
        self.assertEqual(len(items.FLUTE_ITEMS), 3)

    def test_untouched_categories_survive_this_pass(self) -> None:
        # This addendum's research confirmed these categories as functional/correct and deliberately did NOT
        # remove anything from them -- the 15 "mystery" key items, misc treasure, and the berry roster.
        for name in (
            # "Cologne Case" left this list 2026-09-15 -- removed from ITEM_TABLE outright (ADDENDUM 214).
            "Data ROM", "Elevator Key", "Bonsly Card", "Bonsly Photo", "Cry Analyzer",
            "Gonzap's Key", "ID Card", "Machine Part", "Mayor's Note", "Moon Shard", "Miror Radar",
            "Music Disc", "Sun Shard", "System Lever",
        ):
            self.assertIn(name, items.ITEM_TABLE)
        for name in ("Tiny Mushroom", "Big Mushroom", "Pearl", "Big Pearl", "Stardust", "Star Piece", "Nugget"):
            self.assertIn(name, items.ITEM_TABLE)
        for name in (
            "Cheri Berry", "Chesto Berry", "Pecha Berry", "Rawst Berry", "Aspear Berry", "Leppa Berry",
            "Oran Berry", "Persim Berry", "Lum Berry", "Sitrus Berry", "Figy Berry", "Wiki Berry",
            "Mago Berry", "Aguav Berry", "Iapapa Berry",
        ):
            self.assertIn(name, items.ITEM_TABLE)


if __name__ == "__main__":
    unittest.main()
