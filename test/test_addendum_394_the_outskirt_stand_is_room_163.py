"""ADDENDUM 394 (2026-09-29) -- the Outskirt Stand shop is room 163, and an unknown shop room now says so.

Player, with a screenshot of the Outskirt Stand shelf reading AP ITEM 01..08 at 20 each: "Outskirt stand is
breaking. Double check our shop code. I don't want it broken like this at all." Then: "It worked temporarily
and then broke." Then, measured: "Inside outskirt stand is showing as room 163." Then: "It likely worked
because i stepped through 164 (outside) and then went inside and it broke."

THE SCREENSHOT NAMED THE LAYER. Three things were wrong at once and all three were PATCH-TIME values: the
generic `AP ITEM NN` names, every price at the default 20, and the vanilla description ("An item brought over
from a faraway place", where this client's own fallback is "Not scouted yet."). Not one live writer had run.
Every one of them, and `ShopPurchaseTracker` with them, goes through `is_shop_room(room_id)` -- so they do not
fail separately, they fail together, and the single cause is the room id.

WHY IT LOOKED INTERMITTENT, which is the part that would have misled a code read. `ItemNameRenamer.poll` and
`ItemPriceWriter.poll` write on a room CHANGE. Room 164 is the EXTERIOR of the stand and was in the table as
the shop, so walking through it renamed the shelf correctly; stepping inside to 163 fired both writers again
with the not-a-shop fallback and put everything back. "Worked temporarily and then broke" is that, exactly.

`shops.py` predicted this failure in its own section comment -- "if a shop stays silent in play the eight
'player' rooms are where to look and 21/156 are the control" -- because 164 was `source="player"`, vouched
from a room table, not measured. 163 is now `source="live"`, like 21 and 156.

THE SILENT HALF, which matters more than the cosmetics. `ShopPurchaseTracker.poll` does
`shop_room = room_id if is_shop_room(room_id) else None` and credits nothing when it is None, counting the
purchase in `purchases_outside_a_shop`. `!shops` reported that count as "credited nothing, BY DESIGN" -- true
for a berry picked up in a field, and a lie for eight checks lost at a counter, with no room number anywhere
to tell the two apart. The tracker now records WHICH room, and the client warns once per room instead of
waiting for someone to think of running `!shops`.
"""
from __future__ import annotations

import pathlib
import unittest

from .. import ram_client as rc
from ..game_data import chest_regions, shops


class TestTheRoomIdIsTheMeasuredOne(unittest.TestCase):
    def test_the_shop_is_room_163(self) -> None:
        shop = shops.shop_for_room(163)
        self.assertIsNotNone(shop)
        self.assertEqual("Outskirt Stand Shop", shop.name)

    def test_164_is_no_longer_a_shop(self) -> None:
        """The exterior. Leaving it in was what made the shelf rename and then un-rename."""
        self.assertIsNone(shops.shop_for_room(164))
        self.assertFalse(rc.is_shop_room(164))

    def test_it_is_recorded_as_a_live_reading(self) -> None:
        """`source` is what tells a measured id from a vouched one, and this one was measured."""
        self.assertEqual("live", shops.shop_for_room(163).source)

    def test_both_rooms_still_resolve_to_the_same_region(self) -> None:
        """Inside and outside are one place. The story-byte guard reads this map, and the counter used to
        resolve to no region at all."""
        self.assertEqual("Outskirt Stand", chest_regions.ROOM_TO_REGION[163])
        self.assertEqual("Outskirt Stand", chest_regions.ROOM_TO_REGION[164])

    def test_the_shop_still_has_its_eight_lines_and_its_label(self) -> None:
        self.assertEqual(8, rc.shop_slot_count_for_room(163))
        self.assertEqual("OUTSKRT", shops.short_label_for_room(163))

    def test_the_location_ids_did_not_move(self) -> None:
        """A room id is runtime detection only; the ids are keyed by NAME. If these ever move, every existing
        seed's Outskirt Stand checks repoint."""
        from ..locations import get_location_name_to_id

        ids = get_location_name_to_id(0)
        self.assertEqual([1521, 1522, 1523, 1524, 1525, 1526, 1527, 1528],
                         [ids[shops.shop_location_name("Outskirt Stand Shop", n)] for n in range(1, 9)])


class TestEveryWriterAgreedAndThatIsWhyItFailedTogether(unittest.TestCase):
    """ADDENDA 247/298: prove the single cause is real rather than asserting three symptoms."""

    def test_the_rename_falls_all_the_way_back_in_a_non_shop_room(self) -> None:
        from ..items import USELESS_BERRY_IDS

        renamer = rc.ItemNameRenamer()
        inside = renamer.desired_names(163, list(USELESS_BERRY_IDS))
        elsewhere = renamer.desired_names(999, list(USELESS_BERRY_IDS))
        self.assertEqual("OUTSKRT 01", inside[USELESS_BERRY_IDS[0]])
        self.assertTrue(elsewhere[USELESS_BERRY_IDS[0]].startswith("AP ITEM"),
                        "the generic name in the player's screenshot")

    def test_the_name_fits_the_entry(self) -> None:
        """'OUTSKRT 01' is exactly the 10-character budget. One character more and the rename would be skipped
        silently, which would look identical to this bug."""
        from ..game_data import item_name_strings as ins

        for shop in shops.CONFIRMED_SHOPS:
            for slot in (1, shop.slot_count):
                name = f"{shop.short_label} {slot:02d}"
                self.assertLessEqual(len(name), ins.SHOP_BERRY_NAME_BUDGET, f"{shop.name} {name!r}")


class TestAnUnknownShopRoomReportsItself(unittest.TestCase):
    def test_the_tracker_records_the_room(self) -> None:
        tracker = rc.ShopPurchaseTracker()
        self.assertEqual({}, tracker.unknown_shop_rooms)

    def test_the_field_is_per_instance(self) -> None:
        """A mutable default shared across instances would merge two players' reports."""
        first, second = rc.ShopPurchaseTracker(), rc.ShopPurchaseTracker()
        first.unknown_shop_rooms[163] = 1
        self.assertEqual({}, second.unknown_shop_rooms)

    def test_the_client_warns_once_per_room(self) -> None:
        source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        self.assertIn("_warned_unknown_shop_rooms", source)
        self.assertIn("credited NO check", source)

    def test_the_by_design_claim_is_gone(self) -> None:
        """It was true for a field pickup and a lie for eight lost checks, and nothing distinguished them."""
        source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        self.assertNotIn("credited nothing, by design", source)

    def test_shops_names_the_rooms(self) -> None:
        source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        self.assertIn("rooms involved", source)
        self.assertIn("SHOP THIS CLIENT DOES NOT", source)

    def test_the_recording_happens_where_the_credit_is_refused(self) -> None:
        source = (pathlib.Path(__file__).resolve().parent.parent / "ram_client.py").read_text(encoding="utf-8")
        start = source.index("self.purchases_outside_a_shop += delta")
        self.assertIn("unknown_shop_rooms[room_id]", source[start:start + 400])


class TestNoOtherShopIsVouchedForAnUnmeasuredRoom(unittest.TestCase):
    def test_the_remaining_player_sourced_rooms_are_listed(self) -> None:
        """Not a failure -- a standing list. These are the ids that could do this next, and the Outskirt Stand
        is proof the risk is real rather than theoretical."""
        vouched = sorted(s.room_id for s in shops.CONFIRMED_SHOPS if s.source == "player")
        self.assertEqual([50, 103, 104, 119, 121, 134], vouched)

    def test_the_measured_ones_grew_by_one(self) -> None:
        measured = sorted(s.room_id for s in shops.CONFIRMED_SHOPS if s.source == "live")
        self.assertEqual([21, 156, 163], measured)


if __name__ == "__main__":
    unittest.main()
