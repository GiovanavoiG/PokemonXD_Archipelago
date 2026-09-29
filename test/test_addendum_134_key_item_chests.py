"""ADDENDUM 134 (2026-09-11): chest randomization must never overwrite a chest whose vanilla contents are a
key item. Player report, verbatim: "key items are turned into berries but are not in the item pool,
softlocking me." The ID Card (game item id 506, confirmed live -- it vanished from a written sweep the moment
the player used it) lives in chest 18, room 8, the Cipher Lab; the old code replaced it with a dummy berry and
the seed had no way to ever give it back."""
from __future__ import annotations

import struct
import unittest

from .. import locations
from ..tools import xd_rel_format as rel


def _chest_entry(item_id: int, quantity: int = 1, room_id: int = 8, model: int = 68) -> bytes:
    entry = bytearray(rel.TREASURE_BOX_ENTRY_SIZE)
    struct.pack_into(">H", entry, rel.TREASURE_BOX_ITEM_ID_OFFSET, item_id)
    entry[rel.TREASURE_BOX_QUANTITY_OFFSET] = quantity
    entry[rel.TREASURE_BOX_MODEL_OFFSET] = model
    struct.pack_into(">H", entry, rel.TREASURE_BOX_ROOM_ID_OFFSET, room_id)
    return bytes(entry)


class TestKeyItemFloor(unittest.TestCase):
    def test_the_floor_sits_below_every_known_key_item_and_above_every_ordinary_one(self) -> None:
        """Verified anchors: ID Card 506, Krane Memo 1-5 523-527, Voice Case 1-5 528-532, Disc Case 533.
        Ordinary consumables/TMs the chests really do hand out are far below (TM38 = 326 is the highest seen
        in the mart pool)."""
        for key_item_id in (501, 506, 523, 527, 528, 532, 533):
            self.assertGreaterEqual(key_item_id, rel.KEY_ITEM_ID_FLOOR)
        for ordinary_id in (1, 13, 21, 24, 93, 148, 298, 326):
            self.assertLess(ordinary_id, rel.KEY_ITEM_ID_FLOOR)

    def test_the_id_card_is_a_progression_item_with_its_confirmed_game_id(self) -> None:
        """It gates the Cipher Lab, so it must be forced into the pool AND be deliverable by the client --
        `useful` + `game_item_id=None` was exactly the combination that produced an unwinnable seed."""
        from ..items import ITEM_TABLE

        data = ITEM_TABLE["ID Card"]
        self.assertEqual(data.game_item_id, 506)
        self.assertTrue(data.game_item_id_verified)
        self.assertEqual(data.classification.name, "progression")


class TestApplyChestDummyItemSkipsKeyItems(unittest.TestCase):
    """Exercised against a synthetic treasure table so the assertions are exact."""

    def _rel_with_chests(self, item_ids: list[int]):
        import types

        entries = b"".join(_chest_entry(i) for i in item_ids)
        fake = types.SimpleNamespace(data=bytearray(entries))
        base = 0

        real = list(range(len(item_ids)))
        orig_indices = rel.real_chest_indices
        orig_item_off = rel.chest_item_id_offset
        orig_qty_off = rel.chest_quantity_offset
        rel.real_chest_indices = lambda r: real
        rel.chest_item_id_offset = lambda r, i: base + i * rel.TREASURE_BOX_ENTRY_SIZE + rel.TREASURE_BOX_ITEM_ID_OFFSET
        rel.chest_quantity_offset = lambda r, i: base + i * rel.TREASURE_BOX_ENTRY_SIZE + rel.TREASURE_BOX_QUANTITY_OFFSET
        self.addCleanup(lambda: (setattr(rel, "real_chest_indices", orig_indices),
                                 setattr(rel, "chest_item_id_offset", orig_item_off),
                                 setattr(rel, "chest_quantity_offset", orig_qty_off)))
        return fake

    def _ids(self, buf: bytearray, count: int) -> list[int]:
        return [struct.unpack_from(">H", buf, i * rel.TREASURE_BOX_ENTRY_SIZE + rel.TREASURE_BOX_ITEM_ID_OFFSET)[0]
                for i in range(count)]

    def test_key_item_chests_keep_their_real_contents(self) -> None:
        vanilla = [21, 506, 24, 523, 13, 533, 2]
        r = self._rel_with_chests(vanilla)
        buf = bytearray(r.data)
        patched = rel.apply_chest_dummy_item(buf, r, 148)
        self.assertEqual(patched, 4)  # only the four ordinary chests
        self.assertEqual(self._ids(buf, len(vanilla)), [148, 506, 148, 523, 148, 533, 148])

    def test_the_id_card_specifically_survives(self) -> None:
        r = self._rel_with_chests([506])
        buf = bytearray(r.data)
        self.assertEqual(rel.apply_chest_dummy_item(buf, r, 148), 0)
        self.assertEqual(self._ids(buf, 1), [506])
        self.assertEqual(buf[rel.TREASURE_BOX_QUANTITY_OFFSET], 1)

    def test_ordinary_chests_still_get_the_dummy_and_quantity_1(self) -> None:
        """ADDENDUM 44's "one check per chest" guarantee must be unaffected by the new skip."""
        r = self._rel_with_chests([21, 24])
        r.data[rel.TREASURE_BOX_QUANTITY_OFFSET] = 3
        buf = bytearray(r.data)
        self.assertEqual(rel.apply_chest_dummy_item(buf, r, 148), 2)
        self.assertEqual(self._ids(buf, 2), [148, 148])
        self.assertEqual(buf[rel.TREASURE_BOX_QUANTITY_OFFSET], 1)

    def test_chest_indices_holding_key_items_reports_what_was_skipped(self) -> None:
        r = self._rel_with_chests([21, 506, 24, 533])
        self.assertEqual(rel.chest_indices_holding_key_items(r), [(1, 506), (3, 533)])
        self.assertEqual(rel.randomizable_chest_count(r), 2)


class TestChestLocationCountMatchesReality(unittest.TestCase):
    def test_the_location_count_equals_what_randomization_can_actually_convert(self) -> None:
        """If these ever drift apart, the highest "Open N Chests" locations become unreachable and generation
        either fails or produces an unwinnable seed.

        RETARGETED 2026-09-13 (ADDENDUM 168), was a flat `== 91` with the derivation only in prose. The count
        dropped 91 -> 90: chest 115 lives in room 175, the debug room (System Lever x10 next to a chest holding
        item id 0 x10), and game_data/chest_regions.EXCLUDED_ROOMS now drops that whole room, so chest 115 is
        not an AP location either. It was never caught by the key-item fence because item id 0 is below
        KEY_ITEM_ID_FLOOR. The arithmetic is spelled out against the real tables rather than hardcoded so the
        next census change fails here with a readable subtraction instead of a bare number mismatch.
        """
        from ..game_data import chest_regions, chest_table

        fenced = [c for c in chest_table.CHESTS if c["item"] >= rel.KEY_ITEM_ID_FLOOR]
        in_dropped_rooms = [c for c in chest_table.CHESTS
                            if c["item"] < rel.KEY_ITEM_ID_FLOOR and c["room"] in chest_regions.EXCLUDED_ROOMS]
        self.assertEqual(len(chest_table.CHESTS), 115)
        self.assertEqual(len(fenced), 24)
        self.assertEqual([c["chest"] for c in in_dropped_rooms], [115])
        # ADDENDUM 174: the arithmetic now lands on CHEST_COVERED_CHEST_COUNT -- how many CHESTS the AP
        # locations cover -- rather than CHEST_LOCATION_COUNT. The two differ by exactly one because chests 108
        # and 113 share an open flag and therefore share a location (see game_data/chest_flags.py). Asserting
        # the relationship rather than just the numbers is what keeps the pair from being quietly forgotten.
        # ADDENDUM 177: five of the fenced chests become checks when KeyItemShuffle is on, and their ids exist
        # unconditionally, so the covered count is the old arithmetic PLUS those five. Asserted as the
        # relationship rather than a bare number so the fence and the exception stay visibly connected.
        from ..game_data import key_item_chests

        converted = len(key_item_chests.SHUFFLED_KEY_ITEM_CHESTS)
        self.assertEqual(converted, 5)
        self.assertEqual(locations.CHEST_COVERED_CHEST_COUNT,
                         len(chest_table.CHESTS) - len(fenced) - len(in_dropped_rooms) + converted)
        self.assertEqual(locations.CHEST_COVERED_CHEST_COUNT, 95)
        # UPDATED 2026-09-15 (ADDENDUM 224): 95, not 94. The 108/113 shared-flag pair was split back into two
        # locations -- identity comes from the chest's own berry now, not from the flag they share.
        self.assertEqual(locations.CHEST_LOCATION_COUNT, 95)

    def test_every_covered_chest_resolves_to_a_location_that_exists(self) -> None:
        """Replaces the old "the highest threshold exists and the next one does not" bound check. A ladder had
        an end to test; a per-chest table instead has to answer for every chest it claims to cover."""
        for chest_id, name in locations.CHEST_ID_TO_LOCATION.items():
            self.assertIn(name, locations.LOCATION_TABLE, chest_id)
        self.assertEqual(len(set(locations.CHEST_ID_TO_LOCATION.values())),
                         locations.CHEST_LOCATION_COUNT)


if __name__ == "__main__":
    unittest.main()
