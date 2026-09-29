"""ADDENDUM 389 (2026-09-28) -- one failed read stopped killing shop descriptions, and NO CHECK survives a reboot.

Player: "The vending machine in pyrite town (the small shop) is not updating its descriptions with ap items."
Then: "In fact, all the shops break after the first one of a session. I also heard reports that they do not
keep the 'no check' indicator after reboot."

The second message is what identified both bugs. "The first one of a session works" is the shape of a
session-scoped kill switch, and "not after reboot" is the shape of state that was never persisted.

FAULT ONE -- ONE FAILED MEM1 READ DISABLED THE FEATURE FOR THE SESSION.

`ItemDescriptionWriter` has to SEARCH for the description table, because it moves and is only resident while a
menu is open. That search reads megabytes of MEM1 in chunks. Both read paths did this:

    except Exception:
        self.enabled = False                      # <- for the rest of the session
        self.last_error = "MEM1 read failed during description table search"

So a single unlucky read -- the menu closing mid-sweep, a chunk landing somewhere the bridge would not serve
-- turned every shop after the first one generic, permanently, with nothing said. The first shop worked
because it was found before any sweep had a chance to fail.

The class's own canary already reasons correctly about exactly this: "A failed read is not evidence the table
was reset. 'Still ours' skips a rewrite this poll and asks again next poll." The search did the opposite. It
now counts the failure in `read_failures` and comes back next poll, and `_scan_slice` advances its cursor
past the bad chunk so a permanently unreadable address costs one chunk per sweep instead of the feature.

A failed WRITE still disables, and that is kept deliberately: a bridge that cannot write is not going to
start working, and retrying a write every poll against a dead bridge is not free.

FAULT TWO -- THE NO CHECK MARKER WAS SESSION STATE.

`ShopPurchaseTracker.purchased_by_room` says what it is in its own comment: "berry ids already bought there
this session". It is never persisted, so a reboot emptied it and every bought line went back to advertising
an AP item it could no longer send.

`bought_berries_in_room` DERIVES the set from the server's checked locations instead -- authoritative, replayed
in full on reconnect, and free across a reboot. It is the argument `should_have_key_item_ids` already makes for
the key-item reconciler: "an incrementally-maintained set is a second copy of the truth that can drift."

It is UNIONED with the session tracker rather than replacing it, because a purchase credited this tick has not
reached `checked_locations` yet and the shelf is meant to advance while the player is still standing at it.
"""
from __future__ import annotations

import pathlib
import types
import unittest

from .. import ram_client as rc
from ..game_data import item_descriptions as ids
from ..game_data import shops
from ..items import USELESS_BERRY_IDS

BASE = ids.MEASURED_BAND_LOW_START + 0x1000
SIZE = 0x8000


class _FakeMem1:
    """Just enough MEM1 to hold the description table, with switchable read failures."""

    def __init__(self) -> None:
        self.table = bytearray(SIZE)
        self.clock = 1000.0
        self.big_reads_fail = False
        self.writes_fail = False
        self.load()

    def load(self) -> None:
        """What a menu open does: the table is re-read from disc, so every entry is vanilla again."""
        self.table = bytearray(SIZE)
        magic_at = ids.MSG_MAGIC_OFFSET
        self.table[magic_at:magic_at + len(ids.MSG_MAGIC)] = ids.MSG_MAGIC
        for berry in USELESS_BERRY_IDS:
            offset = ids.entry_offset(berry)
            if offset is not None:
                self.table[offset:offset + 12] = b"VANILLA\x00\x00\x00\x00\x00"

    def read(self, address: int, length: int) -> bytes:
        if self.big_reads_fail and length > 1024:
            raise RuntimeError("MEM1 read failed (the menu closed mid-sweep)")
        out = bytearray(length)
        for i in range(length):
            here = address + i
            if BASE <= here < BASE + SIZE:
                out[i] = self.table[here - BASE]
        return bytes(out)

    def write(self, address: int, data: bytes) -> None:
        if self.writes_fail:
            raise RuntimeError("MEM1 write failed")
        for i, byte in enumerate(data):
            here = address + i
            if BASE <= here < BASE + SIZE:
                self.table[here - BASE] = byte


def _scout(shop_name: str, slots: int) -> "dict[str, tuple[str, str | None]]":
    return {shops.shop_location_name(shop_name, n): (f"Item {n}", "Someone")
            for n in range(1, slots + 1)}


class _WriterCase(unittest.TestCase):
    def setUp(self) -> None:
        self.mem = _FakeMem1()
        self._saved = (rc.read_bytes, rc.write_bytes, rc.time)
        rc.read_bytes = self.mem.read
        rc.write_bytes = self.mem.write
        rc.time = types.SimpleNamespace(monotonic=lambda: self.mem.clock)
        self.writer = rc.ItemDescriptionWriter()

    def tearDown(self) -> None:
        rc.read_bytes, rc.write_bytes, rc.time = self._saved

    def run_polls(self, room: int, shop_name: str, slots: int, count: int = 20,
                  step: float = 0.5, purchased=()) -> int:
        before = self.writer.writes
        for _ in range(count):
            self.mem.clock += step
            self.writer.poll(room, _scout(shop_name, slots), set(purchased))
        return self.writer.writes - before


class TestTheFirstShopAlwaysWorked(_WriterCase):
    """The control: prove the fake reproduces the working case before testing the broken one."""

    def test_a_shop_gets_its_descriptions(self) -> None:
        self.assertEqual(18, self.run_polls(21, "Mt. Battle Shop", 18))
        self.assertTrue(self.writer.enabled)

    def test_a_second_shop_does_too(self) -> None:
        self.run_polls(21, "Mt. Battle Shop", 18)
        self.mem.load()                      # the next menu open reloads the table from disc
        self.assertEqual(4, self.run_polls(119, "Pyrite Vending Machine", 4))


class TestAFailedSearchReadIsNotFatal(_WriterCase):
    def _force_a_sweep(self) -> None:
        """Make the next polls actually search: forget where the table was and every address it has been."""
        self.writer.table_base = None
        self.writer._hot_bases.clear()

    def test_the_feature_stays_enabled(self) -> None:
        self.run_polls(21, "Mt. Battle Shop", 18)
        self._force_a_sweep()
        self.mem.big_reads_fail = True
        self.run_polls(21, "Mt. Battle Shop", 18, count=10, step=2.0)
        self.assertTrue(self.writer.enabled, "one bad read must not switch descriptions off for the session")

    def test_the_failures_are_counted_and_reported(self) -> None:
        """Silence is what made this take a player report to find."""
        self.run_polls(21, "Mt. Battle Shop", 18)
        self._force_a_sweep()
        self.mem.big_reads_fail = True
        self.run_polls(21, "Mt. Battle Shop", 18, count=10, step=2.0)
        self.assertGreater(self.writer.read_failures, 0)
        self.assertIsNotNone(self.writer.last_error)

    def test_a_later_shop_still_works_once_reads_recover(self) -> None:
        """The player-visible promise: shop two is not collateral damage from shop one's sweep."""
        self.run_polls(21, "Mt. Battle Shop", 18)
        self._force_a_sweep()
        self.mem.big_reads_fail = True
        self.run_polls(21, "Mt. Battle Shop", 18, count=10, step=2.0)
        self.mem.big_reads_fail = False
        self.mem.load()
        self.assertEqual(4, self.run_polls(119, "Pyrite Vending Machine", 4))
        self.assertTrue(self.writer.enabled)

    def test_the_sweep_cursor_moves_past_a_bad_chunk(self) -> None:
        """Otherwise one permanently unreadable address stalls the sweep on that chunk forever, which is the
        same outage wearing a different hat."""
        self._force_a_sweep()
        self.mem.big_reads_fail = True
        seen = set()
        for _ in range(6):
            self.mem.clock += 2.0
            self.writer.poll(21, _scout("Mt. Battle Shop", 18), set())
            seen.add(self.writer._scan_cursor)
        self.assertGreater(len(seen), 1, f"the cursor never moved: {seen}")


class TestAFailedWriteStillDisables(_WriterCase):
    def test_it_gives_up_on_a_bridge_that_cannot_write(self) -> None:
        """Kept deliberately. A write failure is not bad luck on one address -- retrying every poll against a
        dead bridge costs traffic for a cosmetic that is not coming back."""
        self.mem.writes_fail = True
        self.run_polls(21, "Mt. Battle Shop", 18)
        self.assertFalse(self.writer.enabled)
        self.assertIsNotNone(self.writer.last_error)

    def test_the_search_and_the_write_are_told_apart(self) -> None:
        """The two paths now behave differently, so the source must not have collapsed back into one rule."""
        source = (pathlib.Path(__file__).resolve().parent.parent / "ram_client.py").read_text(encoding="utf-8")
        start = source.index("class ItemDescriptionWriter")
        end = source.index("class ", start + 10)
        body = source[start:end]
        self.assertEqual(1, body.count("self.enabled = False"),
                         "only the WRITE path may disable this feature")
        self.assertIn("self.read_failures += 1", body)


class TestTheNoCheckMarkerIsDerived(unittest.TestCase):
    """Structural: `bought_berries_in_room` lives in `Client.py`, which needs `websockets` to import."""

    def setUp(self) -> None:
        self.source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(
            encoding="utf-8")

    def test_the_helper_exists(self) -> None:
        self.assertIn("def bought_berries_in_room(", self.source)

    def test_it_reads_the_servers_checked_locations(self) -> None:
        start = self.source.index("def bought_berries_in_room(")
        body = self.source[start:start + 1800]
        self.assertIn("ctx.checked_locations", body)
        self.assertIn("LOCATION_NAME_TO_ID", body)
        self.assertIn("shops.shop_location_name", body)

    def test_it_unions_rather_than_replaces(self) -> None:
        """A purchase credited this tick has not reached `checked_locations` yet, and the shelf is supposed to
        advance while the player is still at the counter."""
        start = self.source.index("def bought_berries_in_room(")
        body = self.source[start:start + 1800]
        self.assertIn("purchased_by_room", body)
        self.assertIn("out = set(live)", body)

    def test_the_description_writer_is_given_the_derived_set(self) -> None:
        self.assertIn("bought_berries_in_room(ctx, room_id)", self.source)
        self.assertNotIn(
            "ctx.shop_tracker.purchased_by_room.get(room_id, set()) if room_id is not None else set(),",
            self.source,
            "the description call site must no longer take the session-only dict",
        )

    def test_the_renamer_is_given_it_too(self) -> None:
        """The NO CHECK greying on the shelf LABEL has the same reboot problem as the description."""
        start = self.source.index("renamer.purchased_by_room")
        body = self.source[start:start + 400]
        self.assertIn("bought_berries_in_room(ctx, room_id)", body)

    def test_a_shop_slot_maps_to_the_berry_that_names_it(self) -> None:
        """The numbering this depends on, asserted against the data rather than assumed: line N is berry N."""
        for shop in shops.CONFIRMED_SHOPS:
            self.assertLessEqual(shop.slot_count, len(USELESS_BERRY_IDS), shop.name)


if __name__ == "__main__":
    unittest.main()
