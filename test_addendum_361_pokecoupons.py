"""ADDENDUM 361 (2026-09-25): 5000 Poke Coupons, as a filler item in its own category.

Player: *"Can you find our pokecoupons field? It should probably be near money as it's just another
currency."* Then, after a live write proved it: *"Wire it in as a filler item in its own category."*

WHERE IT IS, and it is derived rather than searched for:

    heroBiosGetPokecoupon    (0x8014DCE8)  ->  lwz r3, 2280(r3)  = hero + 0x8E8
    heroBiosGetPokecouponAll (0x8014DCA0)  ->  lwz r3, 2284(r3)  = hero + 0x8EC

`HERO_OFFSET_FROM_BLOCK` is -0x40, so hero + 0x8E4 is BLOCK_BASE + 0x8A4 -- `MONEY_OFFSET`, measured
independently long before this. That identity anchors the other two, and 0 -> 5000 showing up on the PDA
proved it. The player's guess ("probably near money") was exactly right.

BOTH FIELDS ARE RAISED. `heroAddPokecoupon` (0x8014C7F8) bumps hero status 13 AND 14; `heroDecPokecoupon`
lowers 14 only on a negative delta. So the lifetime total never falls when you spend, and it is what Mt.
Battle's prize tiers read -- raising the balance alone would hand out coupons that buy nothing.

IT IS NOT A BAG ITEM. `game_item_id` is None, so it never routes to a pocket and never confirms a quantity.
Client.py applies it as an EFFECT, the same shape as the Itemfinder Malfunction Trap -- which is why this
addendum turned that special case into `EFFECT_ITEM_NAMES` rather than adding a second one beside it.
"""
from __future__ import annotations

import pathlib
import struct
import unittest
from unittest import mock

from .. import items
from .. import ram_client as rc


ROOT = pathlib.Path(__file__).resolve().parent.parent
CLIENT = (ROOT / "Client.py").read_text(encoding="utf-8")
BLOCK = 0x804792C0


class FakeBlock:
    def __init__(self, money=30245, balance=0, total=0):
        self.mem = {}
        self.w32(BLOCK + rc.MONEY_OFFSET, money)
        self.w32(BLOCK + rc.POKECOUPON_OFFSET, balance)
        self.w32(BLOCK + rc.POKECOUPON_TOTAL_OFFSET, total)

    def read(self, a, n): return bytes(self.mem.get(a + i, 0) for i in range(n))
    def write(self, a, d):
        for i, b in enumerate(d):
            self.mem[a + i] = b
    def w32(self, a, v): self.write(a, struct.pack(">I", v))
    def r32(self, a): return struct.unpack(">I", self.read(a, 4))[0]

    def __enter__(self):
        self._p = mock.patch.multiple(rc, read_bytes=self.read, write_bytes=self.write)
        self._p.start()
        return self

    def __exit__(self, *e): self._p.stop()


class TestTheOffsets(unittest.TestCase):
    def test_the_coupons_sit_immediately_after_money(self):
        """The player's guess, and the whole reason the derivation was findable."""
        self.assertEqual(rc.MONEY_OFFSET + 4, rc.POKECOUPON_OFFSET)
        self.assertEqual(rc.MONEY_OFFSET + 8, rc.POKECOUPON_TOTAL_OFFSET)

    def test_the_hero_relative_offsets_reconcile_with_the_dol(self):
        """hero + 0x8E8 and + 0x8EC, as the two accessors load them, against a block-relative MONEY_OFFSET
        that was measured years of addenda ago. If either constant ever moves, this stops agreeing."""
        hero = rc.HERO_OFFSET_FROM_BLOCK
        self.assertEqual(0x8E4, rc.MONEY_OFFSET - hero)
        self.assertEqual(0x8E8, rc.POKECOUPON_OFFSET - hero)
        self.assertEqual(0x8EC, rc.POKECOUPON_TOTAL_OFFSET - hero)

    def test_the_cap_is_the_games_own(self):
        """`lis r5,0x0099; addi r0,r5,-27009` in both setters."""
        self.assertEqual((0x0099 << 16) - 27009, rc.POKECOUPON_MAX)
        self.assertEqual(9999999, rc.POKECOUPON_MAX)


class TestReadAndAdd(unittest.TestCase):
    def test_a_plain_add_raises_both_fields(self):
        with FakeBlock() as m:
            self.assertEqual((0, 0), rc.read_pokecoupons(BLOCK))
            self.assertEqual((5000, 5000), rc.add_pokecoupons(BLOCK, 5000))
            self.assertEqual(5000, m.r32(BLOCK + rc.POKECOUPON_OFFSET))
            self.assertEqual(5000, m.r32(BLOCK + rc.POKECOUPON_TOTAL_OFFSET))

    def test_it_does_not_touch_money(self):
        with FakeBlock(money=30245) as m:
            rc.add_pokecoupons(BLOCK, 5000)
            self.assertEqual(30245, m.r32(BLOCK + rc.MONEY_OFFSET))

    def test_the_lifetime_total_can_already_exceed_the_balance(self):
        """The ordinary state after spending: 14 stayed put while 13 came down. Adding must keep both
        moving by the same amount rather than resynchronising them."""
        with FakeBlock(balance=100, total=9000) as m:
            self.assertEqual((5100, 14000), rc.add_pokecoupons(BLOCK, 5000))

    def test_both_fields_clamp_at_the_games_cap(self):
        with FakeBlock(balance=rc.POKECOUPON_MAX - 10, total=rc.POKECOUPON_MAX - 1) as m:
            self.assertEqual((rc.POKECOUPON_MAX, rc.POKECOUPON_MAX), rc.add_pokecoupons(BLOCK, 5000))

    def test_a_negative_delta_floors_at_zero_rather_than_wrapping(self):
        """These are u32 fields; an unclamped subtraction would wrap to ~4 billion, which is exactly the
        underflow ADDENDUM 359 hit on a different counter."""
        with FakeBlock(balance=100, total=100) as m:
            self.assertEqual((0, 0), rc.add_pokecoupons(BLOCK, -5000))
            self.assertEqual(0, m.r32(BLOCK + rc.POKECOUPON_OFFSET))


class TestTheItem(unittest.TestCase):
    def test_it_exists_with_the_name_and_amount_asked_for(self):
        self.assertEqual("5000 Poke Coupons", items.POKECOUPON_ITEM_NAME)
        self.assertEqual(5000, items.POKECOUPON_ITEM_AMOUNT)
        self.assertIn(items.POKECOUPON_ITEM_NAME, items.ITEM_TABLE)

    def test_it_is_filler_and_drawable(self):
        from BaseClasses import ItemClassification

        data = items.ITEM_TABLE[items.POKECOUPON_ITEM_NAME]
        self.assertEqual(ItemClassification.filler, data.classification)
        self.assertIn(items.POKECOUPON_ITEM_NAME, items.FILLER_ITEMS)
        self.assertIn(items.POKECOUPON_ITEM_NAME, items._RANDOM_FILLER_POOL)

    def test_it_has_no_bag_id(self):
        """It is not an item in the game at all -- it is a u32 in the save block."""
        self.assertIsNone(items.ITEM_TABLE[items.POKECOUPON_ITEM_NAME].game_item_id)

    def test_its_id_is_frozen_and_pasted_in(self):
        """This file's own convention: paste the assigned offset immediately rather than leaving it to
        `next_free`, which moves the moment anyone adds a frozen entry above it (ADDENDUM 270)."""
        self.assertEqual(260, items._FROZEN_ITEM_OFFSETS[items.POKECOUPON_ITEM_NAME])
        self.assertEqual(260, items.ITEM_TABLE[items.POKECOUPON_ITEM_NAME].id_offset)

    def test_it_is_its_own_category_as_asked(self):
        categories = dict(items.FILLER_CATEGORIES)
        self.assertEqual((items.POKECOUPON_ITEM_NAME,), categories["currency"])
        elsewhere = [key for key, names in items.FILLER_CATEGORIES
                     if key != "currency" and items.POKECOUPON_ITEM_NAME in names]
        self.assertEqual([], elsewhere)

    def test_the_weights_still_read_as_percentages(self):
        self.assertEqual(100, sum(items.FILLER_CATEGORY_DEFAULT_WEIGHTS.values()))
        self.assertEqual(2, items.FILLER_CATEGORY_DEFAULT_WEIGHTS["currency"])

    def test_the_option_exists_and_matches_the_default(self):
        """options.py and items.py have to agree; a test already holds the other nine together."""
        from .. import options

        self.assertEqual(items.FILLER_CATEGORY_DEFAULT_WEIGHTS["currency"],
                         options.FillerWeightCurrency.default)
        self.assertIn("filler_weight_currency", options.PokemonXDOptions.__annotations__)


class TestTheDelivery(unittest.TestCase):
    """Structural -- `Client.py` is not importable here."""

    def test_it_is_an_effect_item_not_a_bag_item(self):
        self.assertIn("EFFECT_ITEM_NAMES = TRAP_ITEM_NAMES | {items.POKECOUPON_ITEM_NAME}", CLIENT)

    def test_both_delivery_sites_go_through_the_dispatcher(self):
        """There are two -- the poll loop's `give_items` and `!getitem`. Adding an effect item to one and
        not the other is how an item becomes undeliverable by one route only."""
        self.assertEqual(2, CLIENT.count("if item_name in EFFECT_ITEM_NAMES:"))
        self.assertEqual(2, CLIENT.count("_apply_effect_item(ctx, item_name)"))
        self.assertEqual(0, CLIENT.count("if item_name in TRAP_ITEM_NAMES:\n                _apply"))

    def test_the_effect_raises_both_fields_through_ram_client(self):
        body = CLIENT[CLIENT.index("def _apply_pokecoupon_item"):CLIENT.index("def _apply_effect_item")]
        self.assertIn("ram_client.add_pokecoupons(ctx.block_base, items.POKECOUPON_ITEM_AMOUNT)", body)

    def test_a_failed_write_never_breaks_the_delivery_loop(self):
        body = CLIENT[CLIENT.index("def _apply_pokecoupon_item"):CLIENT.index("def _apply_effect_item")]
        self.assertIn("except Exception:", body)
        self.assertIn("if ctx.block_base is None:", body)


if __name__ == "__main__":
    unittest.main()
