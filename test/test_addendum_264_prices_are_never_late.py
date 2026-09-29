"""ADDENDUM 264 (2026-09-17): a price must never arrive after the player is already looking at the shelf.

Player, after seeing ADDENDUM 263's pricing work live: "Make sure this runs early enough that the prices
don't have to update mid-game - can be written basically as soon as block_base is established I believe.
Make progression items 1500 and filler 100 - useful 500 is fine."

Three things came out of that, and only one of them is the obvious one.

## 1. It can run earlier than block_base, because it never needed it

The Items table lives in `common_rel`, which is resident at a fixed base from boot. It has nothing to do with
the save block. So the price pass needed NONE of `check_shops`' preconditions -- not `block_base`, not
ADDENDUM 148's block-stability gate (the save menu rewriting the save block cannot disturb `common_rel`, so
pausing prices while that happened only ever made them late), not `_looks_ingame()`. It now runs beside the
other block-independent checks at the top of the tick.

## 2. Running earlier could not have fixed the actual bug

A price is derived from what the SERVER says each line holds, and that answer arrives asynchronously in its
own `LocationInfo` packet, after `Connected`. The ordinary connect sequence was:

    first price pass -> everything filler, the scout has not landed -> scout lands -> the ROOM has not
    changed -> the room-change-driven poll rewrites nothing

and every shelf stayed filler-priced until the player happened to leave a shop and come back. That IS the
"prices update mid-game" being complained about, and polling sooner just means polling sooner with no data.
**Watching the input is what fixes it.**

The renamer got away with watching only the room because its labels derive from the room and the berry index
-- information the client has the moment it connects. A price does not.

## 3. Per-room cannot be dropped, and the data says so plainly

Price is keyed by item id, and ADDENDUM 238c makes a berry id a shop line NUMBER shared by every shop. In a
real generated seed, **13 of 18 line numbers hold different item classes in different shops** -- line 2 is
progression at the Outskirt Stand and filler in Pyrite, in the same seed. A single set of prices written once
at connect would be wrong for most lines in most shops.

The room is not a latency problem to optimise away; it is part of the answer. What the player actually asked
for -- never watching a price change while standing at a counter -- comes from writing on room ENTRY, which
happens long before anyone can reach a shopkeeper and open a menu.
"""
from __future__ import annotations

import pathlib
import struct
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


GATEON_SHOP_ROOM = 156
NOT_A_SHOP_ROOM = 138


class _Table:
    """A fake Items table that verifies, so the writer's own guards are exercised rather than bypassed."""

    def __init__(self) -> None:
        self.base = ins.COMMON_REL_RAM_BASE
        self.data_section = self.base + 0x1CB0
        self.pointer_table = self.base + 0xA8098
        self.items = self.data_section + 0x1E234
        self.written: "dict[int, int]" = {}
        self._read = rc.read_bytes
        self._write = rc.write_bytes
        rc.read_bytes = self.read
        rc.write_bytes = self.write

    def restore(self) -> None:
        rc.read_bytes, rc.write_bytes = self._read, self._write

    def read(self, address, length):
        if address == self.base + ins.REL_DATA_SECTION_ADDRESS_OFFSET:
            return struct.pack(">I", self.data_section)
        if address == self.base + ins.REL_POINTER_TABLE_ADDRESS_OFFSET:
            return struct.pack(">I", self.pointer_table)
        entry = (self.pointer_table + ins.REL_FIRST_POINTER_OFFSET
                 + ins.ITEMS_TABLE_POINTER_INDEX * ins.REL_POINTER_STRIDE
                 + ins.REL_POINTER_VALUE_OFFSET)
        if address == entry:
            return struct.pack(">I", 0x1E234)
        for item_id in rc.USELESS_BERRY_IDS:
            if address == self.items + item_id * ins.ITEM_ENTRY_SIZE + ins.ITEM_NAME_ID_OFFSET:
                return struct.pack(">I", ins.expected_name_id(item_id))
        raise RuntimeError("unexpected read")

    def write(self, address, payload):
        offset = address - self.items - ins.ITEM_PRICE_OFFSET
        self.written[offset // ins.ITEM_ENTRY_SIZE] = struct.unpack(">H", payload)[0]

    def price_of_line(self, line: int) -> "int | None":
        return self.written.get(rc.USELESS_BERRY_IDS[line - 1])


class TestTheScoutLandingRewritesPrices(unittest.TestCase):
    """THE BUG. Everything here happens without the room ever changing, because that is the situation: the
    player connects while already standing in a shop, or walks in before the scout reply arrives."""

    def setUp(self) -> None:
        self.table = _Table()
        self.addCleanup(self.table.restore)
        self.writer = rc.ItemPriceWriter()
        self.line1 = shops.shop_location_name(shops.shop_for_room(GATEON_SHOP_ROOM).name, 1)

    def test_prices_are_rewritten_when_the_scout_arrives(self) -> None:
        classifications: "dict[str, str]" = {}
        self.assertGreater(self.writer.poll(GATEON_SHOP_ROOM, classifications), 0)
        self.assertEqual(ins.PRICE_BY_CLASSIFICATION["filler"], self.table.price_of_line(1))

        # The LocationInfo reply lands. The room has not changed and never will.
        classifications[self.line1] = "progression"
        self.assertGreater(self.writer.poll(GATEON_SHOP_ROOM, classifications), 0,
                           "the scout answer changed and nothing was rewritten -- the shelf stays filler "
                           "priced until the player leaves and comes back")
        self.assertEqual(ins.PRICE_BY_CLASSIFICATION["progression"], self.table.price_of_line(1))

    def test_an_unchanged_scout_and_room_writes_nothing(self) -> None:
        """The other half: this runs every tick, so a steady state that rewrote would be pure cost."""
        classifications = {self.line1: "progression"}
        self.writer.poll(GATEON_SHOP_ROOM, classifications)
        self.assertEqual(0, self.writer.poll(GATEON_SHOP_ROOM, classifications))
        self.assertEqual(0, self.writer.poll(GATEON_SHOP_ROOM, classifications))

    def test_a_reclassification_that_keeps_the_count_still_rewrites(self) -> None:
        """Size alone would miss this. Not something the scout does today -- which is exactly the kind of
        assumption that stops being true quietly."""
        classifications = {self.line1: "filler"}
        self.writer.poll(GATEON_SHOP_ROOM, classifications)
        classifications[self.line1] = "progression"
        self.assertGreater(self.writer.poll(GATEON_SHOP_ROOM, classifications), 0)
        self.assertEqual(ins.PRICE_BY_CLASSIFICATION["progression"], self.table.price_of_line(1))

    def test_the_room_still_drives_it_too(self) -> None:
        classifications = {self.line1: "progression"}
        self.writer.poll(GATEON_SHOP_ROOM, classifications)
        self.assertGreater(self.writer.poll(NOT_A_SHOP_ROOM, classifications), 0)
        self.assertEqual(ins.VANILLA_SHOP_BERRY_PRICE, self.table.price_of_line(1),
                         "leaving a shop must clear the price, or it misprices that line number in the next")


class TestItRunsWithoutTheSaveBlock(unittest.TestCase):
    """Structural -- `Client.py` is not importable here."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        start = cls.source.index("async def check_shop_prices")
        cls.body = cls.source[start:][:cls.source[start:].index("\nasync def ", 1)]

    def test_the_price_pass_is_its_own_function(self) -> None:
        self.assertIn("async def check_shop_prices(ctx: PokemonXDContext) -> None:", self.source)

    def test_it_does_not_require_block_base(self) -> None:
        """The Items table is in `common_rel`, not the save block. Requiring `block_base` would have delayed
        every price to the first poll after save-data resolution, for no reason at all."""
        self.assertNotIn("ctx.block_base", self.body)

    def test_it_runs_outside_the_block_stability_gate(self) -> None:
        """The save menu rewriting the save block cannot disturb `common_rel`. Pausing prices while that
        happened only ever made them late."""
        call = self.source.index("await check_shop_prices(ctx)")
        gate = self.source.index("if block_is_stable:")
        self.assertLess(call, gate,
                        "the price pass must be called before the block-stability gate, not inside it")

    def test_it_runs_before_check_shops(self) -> None:
        self.assertLess(self.source.index("await check_shop_prices(ctx)"),
                        self.source.index("await check_shops(ctx)\n                        if _looks_ingame")
                        if "await check_shops(ctx)\n                        if _looks_ingame" in self.source
                        else self.source.rindex("await check_shops(ctx)"))

    def test_a_credit_still_refreshes_immediately(self) -> None:
        """A purchase makes a line NO CHECK, and its price must stop advertising the item it no longer sends
        -- in the same poll, not on the next room change."""
        start = self.source.index("async def check_shops(ctx: PokemonXDContext) -> None:")
        body = self.source[start:][:self.source[start:].index("\nasync def ", 1)]
        self.assertIn("ctx.item_price_writer.refresh(room_id, ctx.shop_line_classifications)", body)

    def test_it_still_no_ops_when_shops_are_not_randomized(self) -> None:
        """An unpatched shop sells real items; repricing them would be vandalism."""
        self.assertIn("if not ctx.randomize_shops:", self.body)


class TestTheTunedNumbers(unittest.TestCase):

    def test_the_player_s_numbers(self) -> None:
        self.assertEqual(1500, ins.PRICE_BY_CLASSIFICATION["progression"])
        self.assertEqual(500, ins.PRICE_BY_CLASSIFICATION["useful"])
        self.assertEqual(100, ins.PRICE_BY_CLASSIFICATION["filler"])

    def test_a_trap_follows_filler_rather_than_repeating_its_number(self) -> None:
        """Not a tuning knob, and written as a reference so the two cannot drift apart: a conspicuously
        priced trap turns a cosmetic feature into a tell."""
        self.assertEqual(ins.PRICE_BY_CLASSIFICATION["filler"], ins.PRICE_BY_CLASSIFICATION["trap"])
        source = pathlib.Path(ins.__file__).read_text(encoding="utf-8")
        self.assertIn('"trap": _FILLER_PRICE', source)

    def test_filler_and_the_vanilla_restore_value_are_no_longer_the_same_number(self) -> None:
        """They were until this addendum, and conflating them would make a shelf whose scout has not landed
        visibly different from one whose has."""
        self.assertNotEqual(ins.VANILLA_SHOP_BERRY_PRICE, ins.PRICE_BY_CLASSIFICATION["filler"])


if __name__ == "__main__":
    unittest.main()
