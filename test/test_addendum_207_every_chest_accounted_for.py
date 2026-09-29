"""ADDENDUM 207. Every chest in the game is accounted for, and this test keeps it that way.

Player: "Are we certain EVERY chest in the game is accounted for? Double check."

Checked against the real ISO on 2026-09-14, from the player's own extracted `common_rel`:

  * `XDTreasureBoxData` declares **116** entries.
  * Entry 0 is all 28 bytes zero -- the sentinel `xd_rel_format.chest_raw_count` had flagged as a hypothesis
    since 2026-09-07. Now read back and confirmed.
  * Entries **1..115** cross-check byte-for-byte against `chest_table.py` on room id, item id, x/z position
    and the +0x06 flag field: **zero mismatches**, nothing in the ISO missing from the table, nothing in the
    table absent from the ISO.

The ISO bytes are not shipped with this project, so that comparison cannot live in a test. What CAN be pinned
is everything downstream of it: the table's shape, the exact partition of chests into AP locations and
fenced ones, and that every chest falls into a bucket with a stated reason rather than falling through a gap.
That is what this file does -- a chest can never quietly vanish from the accounting again."""
from __future__ import annotations

import unittest

from .. import locations as world_locations
from .. import ram_client
from ..game_data import chest_flags, chest_regions, chest_table, key_item_chests
from ..tools import xd_rel_format

# Confirmed against the real ISO -- see the module docstring.
ISO_RAW_ENTRY_COUNT = 116
REAL_CHEST_COUNT = 115


class TestTheTableIsComplete(unittest.TestCase):
    def test_the_table_holds_every_real_chest(self) -> None:
        ids = sorted(c["chest"] for c in chest_table.CHESTS)
        self.assertEqual(REAL_CHEST_COUNT, len(ids))
        self.assertEqual(list(range(1, REAL_CHEST_COUNT + 1)), ids,
                         "chest ids must be 1..115 with no gaps -- a gap is a chest nobody is tracking")

    def test_the_raw_count_still_means_what_it_did(self) -> None:
        """116 raw entries, entry 0 the all-zero sentinel, so 115 real chests."""
        self.assertEqual(REAL_CHEST_COUNT, ISO_RAW_ENTRY_COUNT - 1)
        self.assertIn("SENTINEL CONFIRMED", xd_rel_format.chest_raw_count.__doc__ or "")

    def test_no_duplicate_chest_ids(self) -> None:
        ids = [c["chest"] for c in chest_table.CHESTS]
        self.assertEqual(len(ids), len(set(ids)))


class TestEveryChestIsInExactlyOneBucket(unittest.TestCase):
    """The real question: not "how many locations" but "is any chest unaccounted for"."""

    def _reasons(self, chest: dict) -> "list[str]":
        cid = chest["chest"]
        reasons = []
        if chest_flags.chest_flag_id(cid) is None:
            reasons.append("no flag")
        if cid not in chest_regions.CHEST_TO_REGION:
            reasons.append("no region")
        if (chest["item"] >= xd_rel_format.KEY_ITEM_ID_FLOOR
                and cid not in key_item_chests.SHUFFLED_KEY_ITEM_CHESTS):
            reasons.append("key item")
        return reasons

    def test_every_chest_is_either_a_location_or_has_a_stated_reason(self) -> None:
        for chest in chest_table.CHESTS:
            cid = chest["chest"]
            is_location = cid in ram_client.CHEST_ID_TO_LOCATION
            reasons = self._reasons(chest)
            if is_location:
                self.assertEqual([], reasons, f"chest {cid} is a location despite {reasons}")
            else:
                self.assertNotEqual([], reasons, f"chest {cid} is not a location and nothing explains why")

    def test_the_partition_adds_up(self) -> None:
        locations = [c for c in chest_table.CHESTS if c["chest"] in ram_client.CHEST_ID_TO_LOCATION]
        fenced = [c for c in chest_table.CHESTS if c["chest"] not in ram_client.CHEST_ID_TO_LOCATION]
        self.assertEqual(REAL_CHEST_COUNT, len(locations) + len(fenced))
        self.assertEqual(95, len(locations))
        self.assertEqual(20, len(fenced))

    def test_the_excluded_rooms_are_the_two_known_ones(self) -> None:
        self.assertEqual({145, 175}, set(chest_regions.EXCLUDED_ROOMS))

    def test_the_debug_room_pair_is_the_only_flagless_pair(self) -> None:
        flagless = {c for c in chest_flags.CHEST_FLAG_IDS if not chest_flags.CHEST_FLAG_IDS[c]}
        self.assertEqual({114, 115}, flagless)
        self.assertEqual({175}, {c["room"] for c in chest_table.CHESTS if c["chest"] in flagless})

    def test_the_five_converted_key_item_chests_really_are_locations(self) -> None:
        """KeyItemShuffle opts these five out of the ADDENDUM 134 fence -- they must actually be locations."""
        for cid in key_item_chests.SHUFFLED_KEY_ITEM_CHESTS:
            self.assertIn(cid, ram_client.CHEST_ID_TO_LOCATION, cid)


class TestTheLocationCountReconciles(unittest.TestCase):
    def test_ninety_five_chests_become_ninety_five_locations(self) -> None:
        """REWRITTEN 2026-09-15 (ADDENDUM 224). This used to assert 95 chests -> 94 locations, because 108 and
        113 share flag id 1149 and ADDENDUM 172 collapsed them into one row rather than risk crediting the
        wrong one. ADDENDUM 218 took the flag array out of identity entirely -- the two chests are in
        different rooms holding different berries -- so the merge was costing a real check for a reason that
        no longer applies. One chest, one location, no exceptions."""
        self.assertEqual(95, world_locations.CHEST_LOCATION_COUNT)
        self.assertEqual(95, len(ram_client.CHEST_ID_TO_LOCATION))
        self.assertEqual(95, len(set(ram_client.CHEST_ID_TO_LOCATION.values())),
                         "every chest must now have a location of its own")
        self.assertNotEqual(ram_client.CHEST_ID_TO_LOCATION[108], ram_client.CHEST_ID_TO_LOCATION[113])

    def test_the_split_pair_kept_one_id_and_minted_one(self) -> None:
        """108 keeps the merged pair's frozen id so existing seeds still point at the same check; 113 is a
        genuinely new location and takes a fresh id above everything that existed."""
        # The generated names were replaced by the player's own labels in ADDENDUM 230; the IDS are what this
        # test is about, and they are unchanged by a rename -- which is the whole point of the frozen table.
        self.assertEqual(world_locations.LOCATION_TABLE["Kaminko Crane Room Chest 1"].id_offset, 1520)
        self.assertEqual(world_locations._FROZEN_LOCATION_OFFSETS["Chest 108+113 (Room 171)"], 1520,
                         "the retired merged name stays listed as a tombstone -- ids are never recycled")
        self.assertEqual(world_locations.LOCATION_TABLE["Kaminko Crane Room Chest 2"].id_offset, 1656)

    def test_every_chest_location_has_an_id_and_a_region(self) -> None:
        for name in world_locations.CHEST_LOCATION_NAMES:
            self.assertIn(name, world_locations.LOCATION_TABLE, name)
            self.assertIn(name, world_locations.CHEST_LOCATION_TO_REGION, name)

    def test_the_world_and_the_client_agree_chest_for_chest(self) -> None:
        self.assertEqual(dict(world_locations.CHEST_ID_TO_LOCATION), dict(ram_client.CHEST_ID_TO_LOCATION))


class TestEveryLocationIsReachableByTheDetector(unittest.TestCase):
    """ADDENDUM 205/206 identify a chest through its room. A location whose room lookup cannot find it could
    never be credited, no matter how the flags behave."""

    def test_every_chest_location_is_findable_from_its_own_room(self) -> None:
        for chest in chest_table.CHESTS:
            name = ram_client.CHEST_ID_TO_LOCATION.get(chest["chest"])
            if name is None:
                continue
            self.assertIn(name, ram_client.chest_locations_in_room(chest["room"]),
                          f"chest {chest['chest']} cannot be found from room {chest['room']}")

    def test_no_room_lookup_returns_a_chest_that_is_not_a_location(self) -> None:
        rooms = {c["room"] for c in chest_table.CHESTS}
        for room in rooms:
            for name in ram_client.chest_locations_in_room(room):
                self.assertIn(name, ram_client.CHEST_LOCATION_NAMES, f"room {room}")


if __name__ == "__main__":
    unittest.main()
