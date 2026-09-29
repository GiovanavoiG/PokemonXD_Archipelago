"""ADDENDUM 267 (2026-09-17): the shelf must hold through a bad read, and notice a reload in place.

Player: "Current shop is working pretty well - it requires me to purchase an item to update the
prices/descriptions - also, reopening the shop clears everything and no longer updates."

Two symptoms, three causes, and the first two are the same mistake made twice.

## 1. An unreadable room is not "not in a shop"

`read_room_id` answers None rather than guessing when its four replicated copies disagree (ADDENDUM 142),
which is what happens around transitions -- and opening a shop menu is a transition.

Both live writers passed that None straight through to a `desired_*` function whose no-shop branch RESTORES:
`desired_names(None)` hands back the plain numbered names, `desired_prices(None)` puts every berry back to 20.
So one unreadable poll wiped the whole shelf, and while the menu stayed open it stayed wiped.

ADDENDUM 226 settled this for chest pickups in as many words -- an unreadable room is "ask again next poll",
never "the answer is no" -- and the reasoning transfers exactly: **holding costs a poll, restoring on a bad
read costs the shelf.**

## 2. `check_shop_prices` fell back on the wrong condition

It had `try: read_room_id() except: use the cached room`. `read_room_id` does not RAISE on an unreadable
room; it RETURNS None. So the fallback never fired. `check_shops` has had the right shape since ADDENDUM 176
and this function, written three addenda later, did not copy it.

## 3. The description cache could not see a reload in place

This is the "no longer updates" half, and it is the interesting one.

`locate()` detects the table MOVING: it re-reads the magic, and drops the cache when it is gone. It cannot
detect the table being RELOADED AT THE SAME ADDRESS -- which is the common case, since the `.msg` file is read
from disc on every menu open and frequently lands back where it was. The magic still checks out, `locate()`
returns the same base, `_written` still claims every entry holds our text, and `_write` skips all of them.
**Vanilla descriptions for the rest of the session.**

The cache was answering a question it could not actually see. One canary entry, read back each poll, answers
it properly: a reload resets the whole file at once, so one entry is as good a witness as twenty-six.
"""
from __future__ import annotations

import pathlib
import sys
import types
import unittest
from unittest import mock

if "dolphin_memory_engine" not in sys.modules:
    _stub = types.ModuleType("dolphin_memory_engine")
    _stub.hook = lambda: None
    _stub.un_hook = lambda: None
    _stub.is_hooked = lambda: False
    _stub.read_bytes = lambda address, length: b""
    _stub.write_bytes = lambda address, data: None
    sys.modules["dolphin_memory_engine"] = _stub

from .. import ram_client as rc
from ..game_data import item_name_strings as ins
from ..game_data import shops


GATEON = 156
NOT_A_SHOP = 138


class TestAnUnreadableRoomHolds(unittest.TestCase):
    """THE REPORTED BUG. Both writers, because it was the same mistake twice."""

    def setUp(self) -> None:
        self.written: "dict[int, bytes]" = {}
        patch = mock.patch.object(rc, "write_bytes",
                                  lambda address, payload: self.written.__setitem__(address, payload))
        patch.start()
        self.addCleanup(patch.stop)
        # ADDENDUM 395: the writers read one of their own entries back each poll now, so the fake has to
        # answer reads too. Write-only, it reads as zeros and the canary correctly calls that a revert --
        # which would make "an unreadable room writes nothing" fail for an unrelated reason.
        read = mock.patch.object(
            rc, "read_bytes",
            lambda address, length: self.written.get(address, b"\x00" * length)[:length].ljust(length, b"\x00"))
        read.start()
        self.addCleanup(read.stop)

    def _renamer(self):
        renamer = rc.ItemNameRenamer()
        renamer.verified = True
        return renamer

    def test_the_renamer_holds_rather_than_clearing(self) -> None:
        renamer = self._renamer()
        self.assertGreater(renamer.poll(GATEON), 0)
        self.written.clear()
        self.assertEqual(0, renamer.poll(None), "an unreadable room must write nothing at all")
        self.assertEqual({}, self.written)

    def test_the_renamer_still_clears_for_a_room_it_can_really_read(self) -> None:
        """A different statement, and it has to keep working -- otherwise a shelf label follows the player
        out of the shop."""
        renamer = self._renamer()
        renamer.poll(GATEON)
        self.assertGreater(renamer.poll(NOT_A_SHOP), 0)

    def test_a_bad_read_does_not_even_move_the_last_room(self) -> None:
        """If None updated `_last_room`, the next GOOD poll would look like a room change and rewrite the
        whole shelf every time the room flickered. Holding means holding all of it."""
        renamer = self._renamer()
        renamer.poll(GATEON)
        renamer.poll(None)
        self.assertEqual(0, renamer.poll(GATEON), "the shop room was never actually left")

    def test_the_price_writer_holds_too(self) -> None:
        writer = rc.ItemPriceWriter()
        writer.verified = True
        writer.table_base = 0x80B38CA4
        name = shops.shop_location_name(shops.shop_for_room(GATEON).name, 1)
        classifications = {name: "progression"}
        self.assertGreater(writer.poll(GATEON, classifications), 0)
        before = dict(writer._written)
        self.assertEqual(0, writer.poll(None, classifications),
                         "an unreadable room must not restore every price to vanilla")
        self.assertEqual(before, writer._written)

    def test_the_price_writer_still_restores_for_a_readable_non_shop_room(self) -> None:
        """Leaving a shop really must clear: a berry carries its price GLOBALLY, so a 1500 left behind would
        misprice that line number in the next shop (ADDENDUM 263)."""
        writer = rc.ItemPriceWriter()
        writer.verified = True
        writer.table_base = 0x80B38CA4
        name = shops.shop_location_name(shops.shop_for_room(GATEON).name, 1)
        writer.poll(GATEON, {name: "progression"})
        self.assertGreater(writer.poll(NOT_A_SHOP, {name: "progression"}), 0)
        self.assertEqual(ins.VANILLA_SHOP_BERRY_PRICE,
                         writer._written[rc.USELESS_BERRY_IDS[0]])


class TestTheDescriptionCanary(unittest.TestCase):
    """The "no longer updates" half: a table reloaded AT THE SAME ADDRESS is invisible to `locate()`."""

    def setUp(self) -> None:
        self.memory: "dict[int, bytes]" = {}
        self.writer = rc.ItemDescriptionWriter()
        self.writer.table_base = 0x809AECA0
        read = mock.patch.object(rc, "read_bytes", self._read)
        write = mock.patch.object(rc, "write_bytes", self._write)
        read.start(); write.start()
        self.addCleanup(read.stop); self.addCleanup(write.stop)

    def _write(self, address, payload):
        self.memory[address] = payload

    def _read(self, address, length):
        value = self.memory.get(address)
        if value is None:
            raise RuntimeError("nothing written here")
        return value[:length]

    def _desired(self):
        """One short line, deliberately, because this test is about the cache and not about packing.

        HISTORICAL NOTE, kept because it was the first sighting of a real bug: when this test was written the
        three-line `UNKNOWN_DESCRIPTION_LINES` constant did not fit an 88-byte entry, `encode_lines` returned
        None and every write silently skipped. That was worked around HERE, in the fixture, and read as a
        quirk of the test -- but the shipped path used the constant raw too, and the shelf stayed vanilla for
        the player until ADDENDUM 283. The budgets are in BYTES; a line that looks short is 2 bytes a
        character. `test_addendum_283_fallback_descriptions_fit` now measures every constant against the
        smallest entry in the table, which is where that observation belonged."""
        return {rc.USELESS_BERRY_IDS[0]: ["Rare Candy"]}

    def test_a_reload_in_place_is_noticed_and_rewritten(self) -> None:
        """THE BUG. Same base, same magic, different contents -- and before this addendum the cache said
        "already written" forever."""
        base = self.writer.table_base
        self.assertGreater(self.writer._write(base, self._desired()), 0)
        self.assertEqual(0, self.writer._write(base, self._desired()), "steady state writes nothing")

        # The menu is reopened: the .msg is re-read from disc, landing at the same address with vanilla text.
        for address in list(self.memory):
            self.memory[address] = b"\x00" * len(self.memory[address])

        self.assertGreater(self.writer._write(base, self._desired()), 0,
                           "a table reloaded under the cache must be rewritten, not skipped forever")

    def test_the_canary_records_what_was_actually_written(self) -> None:
        base = self.writer.table_base
        self.writer._write(base, self._desired())
        self.assertIsNotNone(self.writer._canary)
        item_id, payload = self.writer._canary
        self.assertIn(item_id, self._desired())
        self.assertTrue(payload)

    def test_a_failed_canary_read_does_not_trigger_a_rewrite_storm(self) -> None:
        """A read failure is not evidence the table was reset. Treating it as one would rewrite all
        twenty-six entries on every failed read, forever."""
        base = self.writer.table_base
        self.writer._write(base, self._desired())
        with mock.patch.object(rc, "read_bytes", side_effect=RuntimeError("no dolphin")):
            self.assertEqual(0, self.writer._write(base, self._desired()))

    def test_a_moved_table_drops_the_canary_too(self) -> None:
        """A canary for an address we no longer trust proves nothing -- keeping it could vouch for a table
        that is not ours."""
        self.writer._write(self.writer.table_base, self._desired())
        self.assertIsNotNone(self.writer._canary)
        with mock.patch.object(rc, "read_bytes", side_effect=RuntimeError("gone")):
            self.writer.locate(now=1e9)
        self.assertIsNone(self.writer._canary)


class TestTheClientFallback(unittest.TestCase):
    """Structural -- `Client.py` is not importable here."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        start = cls.source.index("async def check_shop_prices")
        cls.body = cls.source[start:][:cls.source[start:].index("\nasync def ", 1)]

    def test_it_falls_back_on_a_none_return_not_only_on_an_exception(self) -> None:
        """`read_room_id` RETURNS None; it does not raise. An exception-only fallback never fires."""
        self.assertIn("if room_id is None:", self.body)
        self.assertIn("room_id = ctx.room_tracker.current", self.body)

    def test_it_matches_the_shape_check_shops_has_had_since_addendum_176(self) -> None:
        """Pinned as an agreement between the two functions rather than as one function's text. They read the
        same value for the same purpose, and one of them having a subtly different fallback is how this bug
        happened in the first place."""
        start = self.source.index("async def check_shops(ctx: PokemonXDContext) -> None:")
        shops_body = self.source[start:][:self.source[start:].index("\nasync def ", 1)]
        for fragment in ("room_id = ram_client.read_room_id()",
                         "if room_id is None:",
                         "room_id = ctx.room_tracker.current"):
            self.assertIn(fragment, shops_body, fragment)
            self.assertIn(fragment, self.body, fragment)


if __name__ == "__main__":
    unittest.main()
