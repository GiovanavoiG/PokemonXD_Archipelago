"""ADDENDUM 263 (2026-09-17): money is the second witness, and prices are per shelf line.

Player, two asks in one message: "can we poll for the shop items being received faster? It's currently slow
both to send checks and to update to no check", and "any chance we can modify prices of the berries to make
progressive items more expensive?"

---

## The first one could not be fixed by polling faster, which is the interesting part

ADDENDUM 259 gave the shop path a 0.1s sub-poll and the delay did not move, because the delay was never the
poll rate -- it is the confirm WINDOW, and 259 deliberately made that window rate-proof (a clock floor, so no
tick rate can shorten it). **Two seconds is two seconds however often you look.**

So the window itself had to go, and the only honest way to remove a debounce is to replace it with better
evidence rather than less. Repeating one read N times is what you settle for when there is one signal. There
are two: a shop purchase spends MONEY, always -- nothing in a shop is free -- so a real purchase is a berry
going up and money going down, together.

**Why that is stronger than the debounce rather than a shortcut around it.** The thing the window exists to
survive (ADDENDUM 99) is the save-menu glitch: a read of the save block returning a STALE snapshot and holding
it. Money and the Bag pockets live in the SAME block, so a stale read is internally CONSISTENT -- some older
moment, with that moment's berries and that moment's money. To fake this pair it would have to serve a
snapshot in which a purchase had already happened, which is a real purchase. One signal repeated cannot tell a
stale block from a live one; two signals that must move in opposite directions can.

---

## The second one is constrained by ADDENDUM 238c, and that rules out the obvious approach

Price lives in `common_rel`'s Items table, keyed by ITEM ID. A berry id is not a shop line -- 238c makes berry
index k line k+1 in EVERY shop, which is exactly what makes a purchase identifiable. So Agate line 3 and
Gateon line 3 are the same berry and would be the same price. **A price baked into the ISO is a price per line
NUMBER, globally**, and cannot express "this line holds progression". It would look like the feature and
behave like noise. Writing it live, per room, is the only faithful version.

The Items table was measured over the bridge against the live game (0x80B38CA4 = COMMON_REL_RAM_BASE +
0x01FEE4) and then deliberately NOT hardcoded: the client resolves it from the REL's own pointer table, and
refuses to write anything unless every shop berry's NameID agrees. A wrong base here is not a cosmetic
failure -- it is a write into an arbitrary part of common_rel.
"""
from __future__ import annotations

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


BLOCK = 0x80479000
GATEON_SHOP_ROOM = 156
NOT_A_SHOP_ROOM = 138
RAZZ = 148


class _Shop:
    """A fake Bag plus a money field, both served from one dict -- so a 'stale read' can be modelled the way
    the real glitch behaves: an older snapshot of BOTH, not one field moving on its own."""

    def __init__(self) -> None:
        self.quantities: "dict[int, int]" = {}
        self.money = 10_000
        self.clock_t = 0.0
        self._read_pocket, self._clear = rc.read_pocket, rc.clear_item
        self._read_bytes = rc.read_bytes
        rc.read_pocket = lambda base, slots: [
            rc.BagSlot(index=i, address=0, item_id=item_id, quantity=qty)
            for i, (item_id, qty) in enumerate(self.quantities.items()) if qty > 0
        ]
        rc.clear_item = lambda base, slots, item_id: self.quantities.pop(item_id, None) is not None or True

        def fake_read_bytes(address, length):
            if address == BLOCK + rc.MONEY_OFFSET and length == 4:
                return struct.pack(">I", self.money)
            raise RuntimeError("unexpected read")

        rc.read_bytes = fake_read_bytes

    def restore(self) -> None:
        rc.read_pocket, rc.clear_item, rc.read_bytes = self._read_pocket, self._clear, self._read_bytes

    def tracker(self):
        return rc.ShopPurchaseTracker(clock=lambda: self.clock_t)

    def poll(self, tracker, room=GATEON_SHOP_ROOM, step=0.1):
        out = tracker.poll(BLOCK, room_id=room, berry_ids=[RAZZ])
        self.clock_t += step
        return out


class TestTheCorroboratedFastPath(unittest.TestCase):

    def setUp(self) -> None:
        self.shop = _Shop()
        self.addCleanup(self.shop.restore)

    def test_a_purchase_credits_on_the_very_next_poll(self) -> None:
        """THE ASK. Berry up and money down together -- no window, no streak, one sub-tick."""
        tracker = self.shop.tracker()
        self.assertEqual([], self.shop.poll(tracker))          # baseline
        self.shop.quantities[RAZZ] = 1
        self.shop.money -= 20
        self.assertEqual(["Gateon Port Shop AP Item 1"], self.shop.poll(tracker))
        self.assertEqual(1, tracker.money_corroborated_credits)

    def test_a_berry_rising_with_money_unchanged_still_waits_the_full_window(self) -> None:
        """The fallback is untouched. A berry that arrives some other way -- a gift, a field pickup carried
        into a shop -- has no second witness and gets the debounce it always had."""
        tracker = self.shop.tracker()
        self.shop.poll(tracker)
        self.shop.quantities[RAZZ] = 1                          # money deliberately NOT spent
        for _ in range(tracker._CONFIRM_STREAK + 5):
            self.assertEqual([], self.shop.poll(tracker))
        self.assertEqual(0, tracker.money_corroborated_credits)

    def test_money_going_UP_is_not_corroboration(self) -> None:
        """Selling something is not buying something. Getting this backwards would fire a check on a sale."""
        tracker = self.shop.tracker()
        self.shop.poll(tracker)
        self.shop.quantities[RAZZ] = 1
        self.shop.money += 500
        self.assertEqual([], self.shop.poll(tracker))

    def test_a_berry_rising_outside_a_shop_is_never_corroborated(self) -> None:
        """Money can fall anywhere -- the player used a vending machine, healed, whatever. The room is part of
        the evidence, not a detail."""
        tracker = self.shop.tracker()
        self.shop.poll(tracker, room=NOT_A_SHOP_ROOM)
        self.shop.quantities[RAZZ] = 1
        self.shop.money -= 20
        self.assertEqual([], self.shop.poll(tracker, room=NOT_A_SHOP_ROOM))
        self.assertEqual(0, tracker.money_corroborated_credits)

    def test_the_first_poll_after_connecting_cannot_corroborate_anything(self) -> None:
        """There is no previous money reading to compare against, so "money fell" is unanswerable. Treating
        an absent baseline as a fall is how a reconnect would fire checks for purchases made hours ago."""
        tracker = self.shop.tracker()
        self.shop.quantities[RAZZ] = 3
        self.shop.money = 1
        self.assertEqual([], self.shop.poll(tracker))
        self.assertEqual(0, tracker.money_corroborated_credits)

    def test_a_stale_block_read_cannot_fake_the_pair(self) -> None:
        """The failure mode the window exists for (ADDENDUM 99), modelled honestly.

        The glitch serves an OLDER snapshot of the save block. Both fields come from that one block, so the
        stale reading shows the old berry count AND the old money -- which is a berry that did not rise. The
        pair is unfakeable by a consistent snapshot, which is the entire argument for skipping the window."""
        tracker = self.shop.tracker()
        self.shop.quantities[RAZZ] = 0
        self.shop.money = 10_000
        self.shop.poll(tracker)
        # A real purchase happens...
        self.shop.quantities[RAZZ] = 1
        self.shop.money = 9_980
        self.shop.poll(tracker)                                  # credited, berry cleared, money baselined
        # ...and now the save menu serves the PRE-purchase snapshot of the whole block, repeatedly.
        for _ in range(6):
            self.shop.quantities[RAZZ] = 0
            self.shop.money = 10_000
            self.assertEqual([], self.shop.poll(tracker),
                             "a stale snapshot shows an old berry count and old money -- never a rise")

    def test_a_failed_money_read_falls_back_rather_than_crediting(self) -> None:
        """A read failure is not evidence of anything. It must not be mistaken for "money fell"."""
        tracker = self.shop.tracker()
        self.shop.poll(tracker)
        self.shop.quantities[RAZZ] = 1
        self.shop.money -= 20
        with mock.patch.object(rc, "read_bytes", side_effect=RuntimeError("no dolphin")):
            self.assertEqual([], tracker.poll(BLOCK, room_id=GATEON_SHOP_ROOM, berry_ids=[RAZZ]))


class TestThePriceWriterRefusesRatherThanGuesses(unittest.TestCase):
    """A wrong Items-table base is a write into an arbitrary part of `common_rel`, so the bar is higher than
    for anything else cosmetic in this module."""

    def _writer_over(self, name_id_for) -> "rc.ItemPriceWriter":
        writer = rc.ItemPriceWriter()
        base = ins.COMMON_REL_RAM_BASE
        data_section = base + 0x1CB0
        pointer_table = base + 0xA8098

        def fake_read(address, length):
            if address == base + ins.REL_DATA_SECTION_ADDRESS_OFFSET:
                return struct.pack(">I", data_section)
            if address == base + ins.REL_POINTER_TABLE_ADDRESS_OFFSET:
                return struct.pack(">I", pointer_table)
            entry = (pointer_table + ins.REL_FIRST_POINTER_OFFSET
                     + ins.ITEMS_TABLE_POINTER_INDEX * ins.REL_POINTER_STRIDE
                     + ins.REL_POINTER_VALUE_OFFSET)
            if address == entry:
                return struct.pack(">I", 0x1E234)
            items = data_section + 0x1E234
            for item_id in rc.USELESS_BERRY_IDS:
                if address == items + item_id * ins.ITEM_ENTRY_SIZE + ins.ITEM_NAME_ID_OFFSET:
                    return struct.pack(">I", name_id_for(item_id))
            raise RuntimeError(f"unexpected read at 0x{address:08X}")

        self._patch = mock.patch.object(rc, "read_bytes", side_effect=fake_read)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        return writer

    def test_it_verifies_when_every_name_id_agrees(self) -> None:
        writer = self._writer_over(lambda i: ins.expected_name_id(i))
        self.assertTrue(writer.verify(), writer.verify_failures)
        self.assertIsNotNone(writer.table_base)

    def test_one_wrong_name_id_disables_the_whole_feature(self) -> None:
        """All or nothing. 26 consecutive unrelated structs each carrying exactly the predicted NameID does
        not happen by accident -- so a single disagreement means the base is wrong, not that one entry is
        unusual, and writing the other 25 would be writing 25 unknown addresses."""
        bad = rc.USELESS_BERRY_IDS[7]
        writer = self._writer_over(lambda i: 999 if i == bad else ins.expected_name_id(i))
        self.assertFalse(writer.verify())
        self.assertTrue(any(str(bad) in f for f in writer.verify_failures), writer.verify_failures)

    def test_an_unresolvable_table_is_a_refusal_not_a_fallback(self) -> None:
        writer = rc.ItemPriceWriter()
        with mock.patch.object(rc, "read_bytes", side_effect=RuntimeError("no dolphin")):
            self.assertFalse(writer.verify())
        self.assertIsNone(writer.table_base)


class TestWhatEachLineCosts(unittest.TestCase):

    def test_progression_costs_more_than_useful_costs_more_than_filler(self) -> None:
        """Pinned as an ORDERING, not as three numbers -- the numbers are a tuning knob, the ordering is the
        feature the player asked for."""
        prices = ins.PRICE_BY_CLASSIFICATION
        self.assertGreater(prices["progression"], prices["useful"])
        self.assertGreater(prices["useful"], prices["filler"])

    def test_a_trap_is_priced_like_filler(self) -> None:
        """Deliberate. A conspicuously-priced trap turns a cosmetic feature into a tell."""
        self.assertEqual(ins.PRICE_BY_CLASSIFICATION["filler"],
                         ins.PRICE_BY_CLASSIFICATION["trap"])

    def test_filler_costs_real_money_but_far_less_than_progression(self) -> None:
        """REVERSED 2026-09-17 (ADDENDUM 264). This used to assert filler kept the vanilla 20, on the
        reasoning that an ordinary line should be indistinguishable from the game's own pricing. That is only
        worth anything if some shop line somewhere is still vanilla-priced, and none are -- every patchable
        slot in every shop is a dummy berry. All 20 bought was a shelf that cost nothing.

        What matters is the SPREAD, since that is the only thing a price communicates."""
        prices = ins.PRICE_BY_CLASSIFICATION
        self.assertGreater(prices["filler"], ins.VANILLA_SHOP_BERRY_PRICE,
                           "filler should cost real money now")
        self.assertGreaterEqual(prices["progression"], prices["filler"] * 5,
                                "a progression line has to be a decision, not a rounding difference")

    def test_a_shop_prices_its_own_lines_from_the_scout(self) -> None:
        from ..game_data import shops

        writer = rc.ItemPriceWriter()
        name = shops.shop_location_name(shops.shop_for_room(GATEON_SHOP_ROOM).name, 1)
        desired = writer.desired_prices(GATEON_SHOP_ROOM, {name: "progression"})
        self.assertEqual(ins.PRICE_BY_CLASSIFICATION["progression"], desired[rc.USELESS_BERRY_IDS[0]])
        self.assertEqual(ins.PRICE_BY_CLASSIFICATION["filler"], desired[rc.USELESS_BERRY_IDS[1]])

    def test_leaving_a_shop_puts_every_price_back(self) -> None:
        """Not tidiness. A berry carries its price GLOBALLY, so a 2000 left behind would misprice that line
        number in the next shop the player walks into, before its own poll could correct it."""
        writer = rc.ItemPriceWriter()
        from ..game_data import shops

        name = shops.shop_location_name(shops.shop_for_room(GATEON_SHOP_ROOM).name, 1)
        desired = writer.desired_prices(NOT_A_SHOP_ROOM, {name: "progression"})
        self.assertEqual({ins.VANILLA_SHOP_BERRY_PRICE}, set(desired.values()))

    def test_an_unscouted_line_is_priced_as_filler(self) -> None:
        """A scout that never landed must not make every line look like progression.

        ADDENDUM 264: as FILLER, not as the vanilla restore value. Those were the same number until 264 split
        them, and conflating them would make a shelf whose scout has not landed visibly different from one
        whose has -- exactly the information a price must not leak."""
        from ..game_data import shops

        writer = rc.ItemPriceWriter()
        desired = writer.desired_prices(GATEON_SHOP_ROOM, {})
        lines = shops.shop_for_room(GATEON_SHOP_ROOM).slot_count
        for k, berry in enumerate(rc.USELESS_BERRY_IDS):
            if ins.expected_name_id(berry) is None:
                continue
            if k < lines:
                self.assertEqual(ins.PRICE_BY_CLASSIFICATION["filler"], desired[berry],
                                 f"berry {berry} is line {k + 1} of this shop")
            else:
                # Beyond this shop's line count the berry names no line here at all, so it takes the VANILLA
                # restore value rather than a class price -- see `desired_prices` for why a stale price left
                # on a berry is a real bug.
                self.assertEqual(ins.VANILLA_SHOP_BERRY_PRICE, desired[berry],
                                 f"berry {berry} is not a line of this shop")

    def test_every_price_fits_the_u16_field(self) -> None:
        for name, price in ins.PRICE_BY_CLASSIFICATION.items():
            self.assertLessEqual(price, ins.MAX_ITEM_PRICE, name)
            self.assertGreaterEqual(price, 0, name)


class TestTheMeasurement(unittest.TestCase):
    """What the live bridge read confirmed, recorded as assertions so a later edit cannot quietly contradict
    it."""

    def test_the_table_offset_is_resolved_not_stored(self) -> None:
        """The measured value (0x01FEE4) is in the module comment as evidence, never as a constant -- a
        resolved value is right on any build, a copied one is right until it isn't."""
        import pathlib

        source = pathlib.Path(ins.__file__).read_text(encoding="utf-8")
        self.assertIn("0x01FEE4", source, "the measurement should be recorded as evidence")
        self.assertNotIn("ITEMS_TABLE_OFFSET =", source,
                         "resolve the table from pointer 70; do not store its offset")

    def test_the_berry_name_ids_are_consecutive_from_the_measured_anchor(self) -> None:
        self.assertEqual(5115, ins.expected_name_id(148))
        self.assertEqual(5128, ins.expected_name_id(161))
        self.assertEqual(5141, ins.expected_name_id(174))

    def test_enigma_berry_is_not_vouched_for(self) -> None:
        """Item 175's NameID read as 0 live, independently confirming ADDENDUM 117's removal of it. Including
        it in the verification set would fail every seed."""
        self.assertIsNone(ins.expected_name_id(175))
        self.assertNotIn(175, rc.USELESS_BERRY_IDS)


if __name__ == "__main__":
    unittest.main()
