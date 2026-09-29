"""ADDENDUM 214 (2026-09-15) -- three item-pool corrections from the playtest issue list.

Player, verbatim:
    "Remove the cologne case from the pool entirely - it's redundant."
    "Move Rare Candies into the medicine category of filler items."
    "Remove HMs from the pool - they don't exist."

The first of those turned up a fourth bug with a wider blast radius, which is tested here too: `create_items`
consulted ITEMS_REMOVED_FROM_POOL only in its PROGRESSION pass, so every `useful`-classified name in that set
was being shipped in seeds anyway.
"""
import unittest

from .. import items


class TestTheCologneCaseIsGone(unittest.TestCase):
    def test_it_is_not_in_the_item_table(self):
        self.assertNotIn("Cologne Case", items.ITEM_TABLE)

    def test_it_is_in_no_category(self):
        for category in (items.KEY_ITEMS, items.KEY_ITEMS_ALL, items.USEFUL_ITEMS, items.FILLER_ITEMS):
            self.assertNotIn("Cologne Case", category)

    def test_its_frozen_offset_is_kept_reserved(self):
        """This module never recycles an id. The offset stays in the frozen table so nothing can inherit it --
        a seed generated before today still resolves id 12 to the item it was generated with."""
        self.assertEqual(items._FROZEN_ITEM_OFFSETS.get("Cologne Case"), 12)

    def test_no_live_item_took_its_offset(self):
        live = [data.id_offset for data in items.ITEM_TABLE.values()]
        self.assertNotIn(12, live, "offset 12 was reserved for the Cologne Case and must stay unused")

    def test_the_phenac_location_of_the_same_name_was_never_the_item(self):
        """RETARGETED BY ADDENDUM 335. `Phenac City - Cologne's Item` was a LOCATION that happened to share a
        word with the removed Cologne Case ITEM, and this test guarded it against being caught by a broad
        rename. The player has since played it and ruled it not real, so it is retired at the census -- but
        the property still worth pinning is that it left for its OWN reason, by name, and took no item offset
        with it."""
        from .. import locations
        from ..game_data import overworld_item_census as census

        self.assertIn("Phenac City - Cologne's Item", census.RETIRED_UNREAL_LOCATIONS)
        self.assertNotIn("Phenac City - Cologne's Item", locations.get_location_name_to_id(1000))
        self.assertIn("Phenac City - Cologne's Item", locations._FROZEN_LOCATION_OFFSETS,
                      "ADDENDUM 26: a retired id is recorded forever and never reassigned")


class TestRareCandyIsMedicineFiller(unittest.TestCase):
    def test_it_is_in_the_medicine_category(self):
        self.assertIn("Rare Candy", items.MEDICINE_ITEMS)

    def test_it_left_the_useful_category(self):
        self.assertNotIn("Rare Candy", items.USEFUL_ITEMS)
        self.assertNotIn("Rare Candy", items.RARE_CANDY_PP_UP_ITEMS)

    def test_it_is_classified_filler_not_useful(self):
        """Category membership alone would not be enough: _RANDOM_FILLER_POOL is built from FILLER_ITEMS, and
        create_items' useful pass selects on classification. Without the reclassification it would sit in a
        filler dict and still never be drawn as filler."""
        self.assertEqual(items.ITEM_TABLE["Rare Candy"].classification.name, "filler")

    def test_it_can_actually_be_drawn_as_filler(self):
        self.assertIn("Rare Candy", items._RANDOM_FILLER_POOL)

    def test_it_picks_up_the_healing_weight(self):
        self.assertEqual(items._filler_weight("Rare Candy"), items.FILLER_WEIGHT_HEALING)

    def test_its_id_offset_survived_the_move_unchanged(self):
        """The whole point of a name-keyed frozen table: moving an item between spec lists must not renumber
        it, or every already-generated multiworld holding a Rare Candy breaks."""
        self.assertEqual(items.ITEM_TABLE["Rare Candy"].id_offset, 41)

    def test_pp_up_stayed_useful(self):
        """Only Rare Candy was asked for. PP Up shared its spec list and must not have been dragged along."""
        self.assertIn("PP Up", items.USEFUL_ITEMS)
        self.assertEqual(items.ITEM_TABLE["PP Up"].classification.name, "useful")

    def test_the_game_item_id_is_unchanged(self):
        self.assertEqual(items.ITEM_TABLE["Rare Candy"].game_item_id, 68)


class TestHMsAreGone(unittest.TestCase):
    def test_no_hm_is_in_the_item_table(self):
        self.assertEqual([name for name in items.ITEM_TABLE if name.startswith("HM")], [])

    def test_the_hm_category_is_empty(self):
        self.assertEqual(len(items.HM_ITEMS), 0)

    def test_the_hm_item_name_group_is_gone_rather_than_empty(self):
        """An empty AP item-name group is worse than no group -- it shows up in the client as a selectable
        category that can never match anything."""
        self.assertNotIn("HMs", items.ITEM_NAME_GROUPS)

    def test_the_tms_are_untouched(self):
        self.assertEqual(len(items.TM_ITEMS), 50)
        self.assertIn("TM50", items.ITEM_TABLE)

    def test_the_eight_frozen_offsets_stay_reserved(self):
        for n in range(1, 9):
            self.assertIn(f"HM{n:02d}", items._FROZEN_ITEM_OFFSETS)
        live = {data.id_offset for data in items.ITEM_TABLE.values()}
        for n in range(1, 9):
            reserved = items._FROZEN_ITEM_OFFSETS[f"HM{n:02d}"]
            self.assertNotIn(reserved, live, f"HM{n:02d}'s offset {reserved} was handed to a live item")


class TestNoIdCollisionsAfterAllThis(unittest.TestCase):
    """The canary for every frozen-id change. `_freeze_offsets` raises on collision at import, so reaching this
    test at all means import succeeded -- but an explicit assertion documents why that matters."""

    def test_every_live_offset_is_unique(self):
        offsets = [data.id_offset for data in items.ITEM_TABLE.values()]
        self.assertEqual(len(offsets), len(set(offsets)))

    def test_the_two_formerly_unfrozen_items_did_not_shift(self):
        """The one way this pass could have broken live seeds silently.

        `_freeze_offsets` hands unfrozen names offsets counting up from max(frozen)+1, IN TABLE ORDER. Two
        names had no frozen entry (added by ADDENDA 177 and 179, above the frozen range). Removing items
        could in principle have renumbered them -- except every item removed here HELD a frozen offset, so
        none of them ever consumed a `next_free` slot. Asserting the actual numbers rather than the reasoning,
        because the reasoning is what would be wrong if this ever broke.

        ADDENDUM 270 (2026-09-18): both names are now IN `_FROZEN_ITEM_OFFSETS`, pinned at these same two
        numbers -- chosen precisely because this test recorded them, so nothing generated before or after the
        freeze disagrees. The assertions below therefore now check a guarantee rather than a coincidence, and
        the "frozen ceiling" assertion that used to stand in for one has been replaced by the direct one: no
        live item may be unfrozen at all. See TestNoLiveItemIdIsAllowedToDrift in the ADDENDUM 270 file."""
        self.assertEqual(items.ITEM_TABLE["Travel Unlock - Poke Spots"].id_offset, 255)
        self.assertEqual(items.ITEM_TABLE["Data ROM & ID Card"].id_offset, 256)
        self.assertEqual(255, items._FROZEN_ITEM_OFFSETS["Travel Unlock - Poke Spots"])
        self.assertEqual(256, items._FROZEN_ITEM_OFFSETS["Data ROM & ID Card"])

    def test_the_name_to_id_map_still_builds(self):
        mapping = items.get_item_name_to_id(1000)
        self.assertEqual(len(mapping), len(items.ITEM_TABLE))
        self.assertNotIn("Cologne Case", mapping)
        self.assertNotIn("HM01", mapping)
        self.assertIn("Rare Candy", mapping)


class TestRemovedItemsStayOutOfTheUsefulPass(unittest.TestCase):
    """The bug the Cologne Case was hiding. ITEMS_REMOVED_FROM_POOL was only honoured by the progression pass,
    so every `useful` name in it shipped in seeds regardless of being listed as removed."""

    @classmethod
    def setUpClass(cls):
        from pathlib import Path

        cls.source = (Path(items.__file__).resolve().parent / "__init__.py").read_text(encoding="utf-8")

    def test_the_useful_pass_filters_on_the_removed_set(self):
        self.assertIn("and name not in items.ITEMS_REMOVED_FROM_POOL", self.source)

    def test_the_set_still_holds_the_names_that_needed_it(self):
        """If these ever leave the set the filter above silently stops protecting anything, so the names are
        pinned here rather than the filter alone."""
        for name in ("Bonsly Card", "Bonsly Photo", "Cry Analyzer", "Moon Shard", "Sun Shard",
                     "Miror Radar", "Gonzap's Key"):
            self.assertIn(name, items.ITEMS_REMOVED_FROM_POOL)
            self.assertIn(name, items.ITEM_TABLE, "still a real item -- just never pooled")


if __name__ == "__main__":
    unittest.main()
