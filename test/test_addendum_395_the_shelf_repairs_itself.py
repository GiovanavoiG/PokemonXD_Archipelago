"""ADDENDUM 395 (2026-09-29) -- the shelf checks its own work, instead of betting nothing else writes there.

Player, after ADDENDUM 394 moved the Outskirt Stand to room 163: "outskirt stand is still sometimes working,
sometimes not." With a second screenshot of the same shelf back at `AP ITEM 01`..`08`, every price 20.

394 WAS REAL AND WAS NOT THE WHOLE STORY. Room 164 is the exterior and the shop is 163; that fixed the case
where the shelf renamed on the way past and un-renamed on the way in. What it could not explain is
INTERMITTENCY with the room id now right -- "sometimes" is not what a wrong constant produces.

WHAT WAS LEFT. `ItemNameRenamer.poll` and `ItemPriceWriter.poll` write on a room CHANGE and then never look
again:

    if self._last_room_set and room_id == self._last_room:
        return 0

That early-out is a CACHE, and a cache that never re-reads its own entry is a bet that nothing else writes to
those bytes. The shelf reverting to its patch-time names and its patch-time price of 20, with the room
unchanged, is that bet losing. Whatever puts them back -- a menu re-initialising item data, anything -- the
writers had no way to notice, because `_written` still said the job was done.

`ItemDescriptionWriter` has reasoned correctly about this since ADDENDUM 239, for the table it owns:

    "`locate()` detects the table MOVING, but not the table being RELOADED IN PLACE, which is the common case
     ... `_written` still claims every entry holds our text, `_write` skips all of them, and the shelf shows
     vanilla descriptions for the rest of the session."

That is the same sentence, about a different table. The lesson was never carried across.

THE FIX, which is that class's own: each writer remembers ONE entry's exact bytes as it writes them, reads
that one back each poll, and on a mismatch clears its cache and its room latch so the next poll rewrites. One
small read per poll; no change at all in the steady state.

Deliberately NOT done: a blanket rewrite every poll. That would work and would also hide the problem --
`reverts_detected` counts it instead, so `!shops` can say whether the shelf is being put back and how often.
"""
from __future__ import annotations

import struct
import unittest

from .. import ram_client as rc
from ..game_data import item_name_strings as ins
from ..items import USELESS_BERRY_IDS

ROOM = 163


class _FakeRam:
    def __init__(self) -> None:
        self.mem: "dict[tuple[int, int], bytes]" = {}
        self.reads = 0

    def read(self, address: int, length: int) -> bytes:
        self.reads += 1
        return self.mem.get((address, length), b"\x00" * length)

    def write(self, address: int, data: bytes) -> None:
        self.mem[(address, len(data))] = bytes(data)


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        self.ram = _FakeRam()
        self.saved = (rc.read_bytes, rc.write_bytes)
        rc.read_bytes, rc.write_bytes = self.ram.read, self.ram.write

    def tearDown(self) -> None:
        rc.read_bytes, rc.write_bytes = self.saved


class TestTheRenamerRepairsItself(_Case):
    def setUp(self) -> None:
        super().setUp()
        self.renamer = rc.ItemNameRenamer()
        self.renamer.verified = True

    def _revert(self) -> None:
        """What the game does: the entry we wrote no longer holds what we wrote."""
        item_id, payload = self.renamer._canary
        self.ram.mem[(ins.ram_address(item_id), len(payload))] = b"\x00" * len(payload)

    def test_it_writes_on_entering_the_shop(self) -> None:
        self.assertGreater(self.renamer.poll(ROOM, list(USELESS_BERRY_IDS)), 0)

    def test_it_does_nothing_when_nothing_changed(self) -> None:
        """The steady state has to stay free, or this trades one bug for a write every tick."""
        self.renamer.poll(ROOM, list(USELESS_BERRY_IDS))
        for _ in range(5):
            self.assertEqual(0, self.renamer.poll(ROOM, list(USELESS_BERRY_IDS)))

    def test_a_revert_is_noticed_and_undone(self) -> None:
        self.renamer.poll(ROOM, list(USELESS_BERRY_IDS))
        self._revert()
        self.assertGreater(self.renamer.poll(ROOM, list(USELESS_BERRY_IDS)), 0,
                           "the room did not change, so only the canary can have caught this")
        self.assertEqual(1, self.renamer.reverts_detected)

    def test_it_settles_again_after_repairing(self) -> None:
        self.renamer.poll(ROOM, list(USELESS_BERRY_IDS))
        self._revert()
        self.renamer.poll(ROOM, list(USELESS_BERRY_IDS))
        self.assertEqual(0, self.renamer.poll(ROOM, list(USELESS_BERRY_IDS)))

    def test_it_survives_being_reverted_repeatedly(self) -> None:
        self.renamer.poll(ROOM, list(USELESS_BERRY_IDS))
        for _ in range(4):
            self._revert()
            self.assertGreater(self.renamer.poll(ROOM, list(USELESS_BERRY_IDS)), 0)
        self.assertEqual(4, self.renamer.reverts_detected)

    def test_a_failed_read_is_not_treated_as_a_revert(self) -> None:
        """Otherwise a dropped read rewrites all twenty entries, every tick, forever."""
        self.renamer.poll(ROOM, list(USELESS_BERRY_IDS))

        def boom(address, length):
            raise RuntimeError("bridge hiccup")

        rc.read_bytes = boom
        try:
            self.assertEqual(0, self.renamer.poll(ROOM, list(USELESS_BERRY_IDS)))
        finally:
            rc.read_bytes = self.ram.read
        self.assertEqual(0, self.renamer.reverts_detected)

    def test_the_check_is_one_read_not_twenty(self) -> None:
        self.renamer.poll(ROOM, list(USELESS_BERRY_IDS))
        before = self.ram.reads
        self.renamer.poll(ROOM, list(USELESS_BERRY_IDS))
        self.assertEqual(1, self.ram.reads - before)

    def test_a_real_room_change_still_rewrites(self) -> None:
        """The original mechanism must survive the new one."""
        self.renamer.poll(ROOM, list(USELESS_BERRY_IDS))
        self.assertGreater(self.renamer.poll(999, list(USELESS_BERRY_IDS)), 0)


class TestThePriceWriterRepairsItself(_Case):
    def setUp(self) -> None:
        super().setUp()
        self.writer = rc.ItemPriceWriter()
        self.writer.verified = True
        self.writer.table_base = 0x80B20000

    def _prices(self) -> "dict[int, int]":
        return {berry: 120 for berry in USELESS_BERRY_IDS[:4]}

    def _revert(self) -> None:
        item_id, _price = self.writer._canary
        address = self.writer.table_base + item_id * ins.ITEM_ENTRY_SIZE + ins.ITEM_PRICE_OFFSET
        self.ram.mem[(address, 2)] = struct.pack(">H", 20)

    def test_it_writes_then_settles(self) -> None:
        self.assertGreater(self.writer.write(self._prices()), 0)
        self.assertEqual(0, self.writer.write(self._prices()))

    def test_a_revert_is_noticed(self) -> None:
        self.writer.write(self._prices())
        self._revert()
        self.assertFalse(self.writer._canary_still_ours())

    def test_the_canary_holds_when_untouched(self) -> None:
        self.writer.write(self._prices())
        self.assertTrue(self.writer._canary_still_ours())

    def test_a_failed_read_is_not_a_revert(self) -> None:
        self.writer.write(self._prices())

        def boom(address, length):
            raise RuntimeError("bridge hiccup")

        rc.read_bytes = boom
        try:
            self.assertTrue(self.writer._canary_still_ours())
        finally:
            rc.read_bytes = self.ram.read

    def test_no_canary_before_the_first_write(self) -> None:
        self.assertIsNone(self.writer._canary)
        self.assertTrue(self.writer._canary_still_ours())


class TestOneShopCanAnswerToTwoRoomIds(unittest.TestCase):
    """Player: "Wait, now outskirt stand is showing as room 164. I think Outskirt stand might be a weird case
    - just make both count as shop room for writes."

    A room read that flips between two ids from the same spot is a better fit for "sometimes working,
    sometimes not" than anything else offered, and the stand is one place either way."""

    def test_both_ids_are_the_shop(self) -> None:
        from ..game_data import shops

        for room in (163, 164):
            self.assertTrue(rc.is_shop_room(room), room)
            self.assertEqual("Outskirt Stand Shop", shops.shop_for_room(room).name, room)

    def test_the_alias_collapses_onto_the_canonical_id(self) -> None:
        """Every per-room tracker keys off this. Two keys for one shop would split `purchased_by_room`, so a
        line bought under one id would not read as bought under the other."""
        from ..game_data import shops

        self.assertEqual(163, shops.canonical_shop_room(164))
        self.assertEqual(163, shops.canonical_shop_room(163))

    def test_an_unknown_room_is_left_alone(self) -> None:
        from ..game_data import shops

        self.assertEqual(999, shops.canonical_shop_room(999))
        self.assertIsNone(shops.canonical_shop_room(None))

    def test_every_per_room_helper_answers_for_the_alias(self) -> None:
        """The first attempt canonicalised only the room latch, and `short_label_for_room(164)` still returned
        None -- which is exactly what sends the shelf to its generic `AP ITEM NN` fallback."""
        from ..game_data import shops

        for room in (163, 164):
            self.assertEqual("OUTSKRT", shops.short_label_for_room(room), room)
            self.assertEqual(8, rc.shop_slot_count_for_room(room), room)
            self.assertEqual("Outskirt Stand Shop AP Item 1",
                             rc.shop_location_name_for_room(room, 1), room)

    def test_the_shelf_reads_the_same_from_either_id(self) -> None:
        renamer = rc.ItemNameRenamer()
        first = renamer.desired_names(163, list(USELESS_BERRY_IDS))
        second = renamer.desired_names(164, list(USELESS_BERRY_IDS))
        self.assertEqual(first, second)
        self.assertEqual("OUTSKRT 01", first[USELESS_BERRY_IDS[0]])

    def test_a_flipping_read_does_not_rewrite_every_tick(self) -> None:
        """Without the collapse, 163/164/163 looks like three room changes and rewrites the shelf each time."""
        ram = _FakeRam()
        saved = (rc.read_bytes, rc.write_bytes)
        rc.read_bytes, rc.write_bytes = ram.read, ram.write
        try:
            renamer = rc.ItemNameRenamer()
            renamer.verified = True
            self.assertGreater(renamer.poll(163, list(USELESS_BERRY_IDS)), 0)
            for room in (164, 163, 164, 163):
                self.assertEqual(0, renamer.poll(room, list(USELESS_BERRY_IDS)), room)
        finally:
            rc.read_bytes, rc.write_bytes = saved

    def test_no_alias_collides_with_a_real_shop(self) -> None:
        """Asserted at import too, but a test says why: an alias stealing another shop's room would silently
        credit that shop's purchases to the wrong place."""
        from ..game_data import shops

        own = {shop.room_id for shop in shops.CONFIRMED_SHOPS}
        for shop in shops.CONFIRMED_SHOPS:
            for alias in shop.aliases:
                self.assertNotIn(alias, own, f"{shop.name} aliases {alias}")


class TestItIsCountedRatherThanHidden(unittest.TestCase):
    def test_both_writers_expose_the_counter(self) -> None:
        self.assertEqual(0, rc.ItemNameRenamer().reverts_detected)
        self.assertEqual(0, rc.ItemPriceWriter().reverts_detected)

    def test_shops_reports_it(self) -> None:
        import pathlib

        source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        self.assertIn("shelf put back by the game", source)

    def test_the_writers_did_not_become_unconditional(self) -> None:
        """A blanket rewrite every poll would also fix the symptom, and would hide how often it happens."""
        import pathlib

        source = (pathlib.Path(__file__).resolve().parent.parent / "ram_client.py").read_text(encoding="utf-8")
        self.assertIn("if self._last_room_set and room_id == self._last_room:", source)


if __name__ == "__main__":
    unittest.main()
