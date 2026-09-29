"""ADDENDUM 235. One label per shelf line, NO CHECK once bought -- and the berry-list drift that fixed a
real, silent chest bug on the way.

Player: "Are the shop berries unique and named differently when we open the shop menu? I want us still
clearing them out of the bag as we get them to avoid clutter. I'd like every shop item to be labelled
differently and change to no check as we purchase them -- scroll down the list and purchase each one once
until they all show no check."
"""
from __future__ import annotations

import unittest
from unittest import mock

from .. import items
from .. import ram_client
from ..game_data import chest_berries, shop_berries, shops


class TestBerryListIsSharedAndDisjoint(unittest.TestCase):
    """The drift this addendum found: `ram_client` still called berries 169-174 shop berries after ADDENDUM
    218 gave them to the chests, so `ShopPurchaseTracker` was watching -- and clearing out of the Bag -- six
    of the seven berries `ChestBerryTracker` needs to identify a chest."""

    def test_the_client_and_the_world_read_the_same_list(self) -> None:
        self.assertEqual(shop_berries.SHOP_BERRY_IDS, items.USELESS_BERRY_IDS)
        self.assertEqual(shop_berries.SHOP_BERRY_IDS, ram_client.USELESS_BERRY_IDS)
        self.assertIs(items.USELESS_BERRY_IDS, ram_client.USELESS_BERRY_IDS,
                      "both sides must reach the same object, not two copies that can drift again")

    def test_no_shop_berry_is_also_a_chest_berry(self) -> None:
        overlap = set(ram_client.USELESS_BERRY_IDS) & set(chest_berries.CHEST_BERRY_IDS)
        self.assertEqual(set(), overlap,
                         "a chest pickup would be cleared by the shop tracker before the chest tracker saw it")

    def test_the_six_berries_addendum_218_moved_are_not_watched_as_shop_berries(self) -> None:
        for berry in (169, 170, 171, 172, 173, 174):
            self.assertNotIn(berry, ram_client.USELESS_BERRY_IDS)
            self.assertIn(berry, chest_berries.CHEST_BERRY_IDS)

    def test_the_rotation_still_outruns_the_biggest_shop(self) -> None:
        biggest = max(shop.slot_count for shop in shops.CONFIRMED_SHOPS)
        self.assertGreater(len(shop_berries.SHOP_BERRY_IDS), biggest,
                           "a berry would repeat inside one mart and stop identifying a line")


class TestShelfLabels(unittest.TestCase):
    def setUp(self) -> None:
        self.renamer = ram_client.ItemNameRenamer()
        self.renamer.verified = True
        self.berries = ram_client.USELESS_BERRY_IDS

    def test_every_line_in_every_shop_is_distinct(self) -> None:
        """ADDENDUM 238c narrowed this. It used to demand 20 distinct labels for 20 berries in every shop,
        which was right when a berry was an arbitrary rotation position and any of them could be the next
        check. A berry index is now a shelf LINE number, so a shop with 15 lines has no line 16-20: those
        berries read NO CHECK, correctly, and share that one text. What must still be distinct is every
        label that names a real line."""
        for shop in shops.CONFIRMED_SHOPS:
            names = self.renamer.desired_names(shop.room_id, self.berries)
            labelled = [text for text in names.values() if text != ram_client.NO_CHECK_NAME]
            self.assertEqual(shop.slot_count, len(labelled), shop.name)
            self.assertEqual(len(labelled), len(set(labelled)),
                             f"{shop.name} shows duplicate shelf labels")

    def test_the_number_is_the_same_one_the_bag_shows(self) -> None:
        """Berry 7 is AP ITEM 07 in the Bag and GATEON 07 on the shelf -- one numbering, learned once. As of
        ADDENDUM 238c/238d it is also the AP location number: GATEON 07 IS `Gateon Port Shop AP Item 7`,
        because the patcher deals berries per shop line and the tracker credits by that index."""
        bag = self.renamer.desired_names(None, self.berries)
        shelf = self.renamer.desired_names(156, self.berries)
        for item_id in self.berries[:shops.SHOPS_BY_ROOM[156].slot_count]:
            self.assertEqual(bag[item_id].split()[-1], shelf[item_id].split()[-1])
        # And the label really is the location name's number.
        from ..game_data.shops import shop_location_name
        line = 7
        self.assertEqual("GATEON 07", shelf[self.berries[line - 1]])
        self.assertEqual("Gateon Port Shop AP Item 7", shop_location_name("Gateon Port Shop", line))

    def test_buying_a_line_greys_only_that_line(self) -> None:
        self.renamer.purchased_by_room = {156: {self.berries[2]}}
        names = self.renamer.desired_names(156, self.berries)
        self.assertEqual(ram_client.NO_CHECK_NAME, names[self.berries[2]])
        self.assertEqual("GATEON 01", names[self.berries[0]])

    def test_buying_every_line_empties_the_shelf(self) -> None:
        """The player's own workflow: scroll down, buy each once, until they all show no check."""
        self.renamer.purchased_by_room = {156: set(self.berries)}
        self.assertEqual({ram_client.NO_CHECK_NAME},
                         set(self.renamer.desired_names(156, self.berries).values()))

    def test_a_purchase_in_one_shop_does_not_grey_another(self) -> None:
        self.renamer.purchased_by_room = {156: set(self.berries)}
        names = self.renamer.desired_names(121, self.berries)
        self.assertEqual("PYRITE 01", names[self.berries[0]])

    def test_a_berry_past_the_shops_line_count_says_no_check(self) -> None:
        """REPLACES `test_an_exhausted_stock_count_greys_everything`. That test asserted the old rule: once a
        ROOM's running counter reached its stock count, every line greyed out. Under line numbering that rule
        is wrong -- a room's count can reach its cap while individual lines are still unbought, and greying a
        live line would tell the player a real check is gone. Greying is per line now. What survives is the
        half that is still true: a berry whose line number is past this shop's stock count names no line of
        this shop, so nothing bought on it can send anything."""
        cap = shops.SHOPS_BY_ROOM[156].slot_count
        names = self.renamer.desired_names(156, self.berries)
        for item_id in self.berries[:cap]:
            self.assertNotEqual(ram_client.NO_CHECK_NAME, names[item_id])
        for item_id in self.berries[cap:]:
            self.assertEqual(ram_client.NO_CHECK_NAME, names[item_id])

    def test_a_full_room_counter_no_longer_greys_a_live_line(self) -> None:
        """The specific regression the rule change prevents."""
        self.renamer.slots_credited_by_room = {156: shops.SHOPS_BY_ROOM[156].slot_count}
        self.assertEqual("GATEON 01", self.renamer.desired_names(156, self.berries)[self.berries[0]])

    def test_every_label_fits_the_budget_in_every_shop(self) -> None:
        from ..game_data import item_name_strings as ins
        for shop in shops.CONFIRMED_SHOPS:
            for text in self.renamer.desired_names(shop.room_id, self.berries).values():
                self.assertLessEqual(len(text), ins.SHOP_BERRY_NAME_BUDGET, f"{shop.name}: {text!r}")


class TestPurchasesStillClearTheBag(unittest.TestCase):
    """The player's standing requirement, restated this addendum: "I want us still clearing them out of the
    bag as we get them to avoid clutter." Guarded here so a future display change cannot quietly drop it."""

    def test_a_confirmed_purchase_clears_the_berry_and_records_the_line(self) -> None:
        # ADDENDUM 259: the confirm window is a DURATION as well as a read count now, so this sequence has to
        # advance a clock -- a tight loop takes no real time at all. One second per poll is exactly
        # POLL_INTERVAL_INGAME, so the expectations below are unchanged in meaning.
        fake_clock = {"t": 0.0}
        tracker = ram_client.ShopPurchaseTracker(clock=lambda: fake_clock["t"])
        berry = ram_client.USELESS_BERRY_IDS[0]
        cleared: "list[int]" = []
        quantities = {b: 0 for b in ram_client.USELESS_BERRY_IDS}

        with mock.patch.object(ram_client, "_batch_item_quantities", lambda *a, **k: dict(quantities)), \
             mock.patch.object(ram_client, "clear_item", lambda *a: cleared.append(a[2]) or True):
            tracker.poll(0x1000, room_id=156)          # baseline
            fake_clock["t"] += 1.0
            quantities[berry] = 1
            for _ in range(ram_client.ShopPurchaseTracker._CONFIRM_STREAK):
                sent = tracker.poll(0x1000, room_id=156)
                fake_clock["t"] += 1.0

        self.assertTrue(sent, "the purchase should have sent a check")
        self.assertIn(berry, cleared, "the berry must be cleared out of the Bag after being counted")
        self.assertIn(berry, tracker.purchased_by_room.get(156, set()))
