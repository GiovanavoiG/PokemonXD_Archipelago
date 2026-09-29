"""ADDENDUM 387 (2026-09-28) -- the shop restock lines hold filler, and the Pit Stop sells a Revive from the start.

Player: "Can we make all of the shop expansion items filler for now, they're inaccessible sometimes. Add
revives to the agate village pit stop in place of something, prior to the expansion. Maybe hyper potions"

Two changes, one cause: a shop is a sequence of MARTS, not one shelf, and anything past the first mart is
only there after the story restocks the shop.

PART ONE -- THE RESTOCK LINES. Thirteen shop checks are introduced by a later mart: Gateon 7..15, Pyrite
11..12, Agate 8..9. `rules.py` gates them on `TIER_GATES`, and those gates are the least certain data in the
shop model -- the mart-to-room mapping is secondary (Bulbapedia, not a census of the ISO), Gateon's earlier
tiers were deduced BY ELIMINATION rather than matched, and three of its lines are gated only because they
share a mart with a line that is annotated. A gate that is too loose puts a check in logic before the
restock that creates it, which is "inaccessible sometimes" seen from the player's chair.

So they are EXCLUDED: still real locations, still firing on purchase, just never REQUIRED. The tier rules
stay in place -- they still keep a restock line out of an early sphere, and dropping them would trade one
wrong answer for another.

PART TWO -- THE REVIVE. An Agate mart takes lines from the FRONT of `AGATE_PIT_STOP_STOCK`, and Agate's
three marts are 7, 8 and 9 lines long. The Revive sat at position 8, so the smallest shelf never carried
one: the item a pit stop most exists to sell was itself behind the expansion. It swaps with the Hyper
Potion, which is the trade the player named. Nothing left the list.

WHY THE SETS ARE DERIVED. Both halves read the mart tiers rather than a typed list, so a shop that gains or
loses a tier -- or a mart whose patchable line count changes -- is covered the day `shop_stock.py` says so.
"""
from __future__ import annotations

import unittest

from BaseClasses import LocationProgressType

from .. import locations as L
from ..game_data import shop_stock as ss
from ..game_data import shops
from . import PokemonXDTestBase

REVIVE = 24
HYPER_POTION = 21


class TestWhichLinesAreRestocks(unittest.TestCase):
    def test_the_thirteen_are_exactly_the_later_tiers(self) -> None:
        self.assertEqual(
            [
                "Agate Village Shop AP Item 8", "Agate Village Shop AP Item 9",
                "Gateon Port Shop AP Item 7", "Gateon Port Shop AP Item 8",
                "Gateon Port Shop AP Item 9", "Gateon Port Shop AP Item 10",
                "Gateon Port Shop AP Item 11", "Gateon Port Shop AP Item 12",
                "Gateon Port Shop AP Item 13", "Gateon Port Shop AP Item 14",
                "Gateon Port Shop AP Item 15",
                "Pyrite Town Shop AP Item 11", "Pyrite Town Shop AP Item 12",
            ],
            sorted(L.FILLER_ONLY_SHOP_LOCATIONS,
                   key=lambda n: (n.rsplit(" AP Item ", 1)[0], int(n.rsplit(" ", 1)[1]))),
        )

    def test_no_opening_shelf_line_is_caught(self) -> None:
        """The failure that would matter: sweeping up line 1 of every shop strips the progression surface of
        the whole shop system rather than of its restocks."""
        for shop in shops.CONFIRMED_SHOPS:
            first = shops.shop_location_name(shop.name, 1)
            self.assertNotIn(first, L.FILLER_ONLY_SHOP_LOCATIONS, shop.name)

    def test_a_shop_with_one_tier_contributes_nothing(self) -> None:
        for name in ("Mt. Battle Shop", "Realgam Tower Shop", "Outskirt Stand Shop",
                     "Phenac City Shop", "Phenac City Shop 2F", "Pyrite Vending Machine"):
            caught = {n for n in L.FILLER_ONLY_SHOP_LOCATIONS if n.startswith(name + " ")}
            self.assertEqual(set(), caught, name)

    def test_it_agrees_with_the_module_that_owns_the_tiers(self) -> None:
        """Derived twice, from the same table, by different code paths -- `gated_shop_lines` is what rules.py
        uses. Every gated line must be in the excluded set; the reverse need not hold, because a tier with no
        known gate still restocks and is excluded here while rules.py can say nothing about it."""
        for shop in shops.CONFIRMED_SHOPS:
            for numbers, _gate in ss.gated_shop_lines(shop.name):
                for number in numbers:
                    self.assertIn(shops.shop_location_name(shop.name, number),
                                  L.FILLER_ONLY_SHOP_LOCATIONS)

    def test_the_tier_rules_were_not_removed(self) -> None:
        """Excluding is not the same as un-gating. A restock line must still stay out of an early sphere."""
        self.assertTrue(any(ss.gated_shop_lines(shop.name) for shop in shops.CONFIRMED_SHOPS))


class TestTheExclusionLands(PokemonXDTestBase):
    options = {"randomize_shops": 1, "agate_village_pit_stop": 0}

    def test_every_restock_line_is_excluded(self) -> None:
        for name in L.FILLER_ONLY_SHOP_LOCATIONS:
            location = self.multiworld.get_location(name, self.player)
            self.assertIs(LocationProgressType.EXCLUDED, location.progress_type, name)

    def test_the_opening_shelf_of_the_same_shop_is_not(self) -> None:
        """Gateon restocks twice and loses nine of fifteen lines to this. The first six must survive, or the
        earliest shop in the game stops being able to hold anything."""
        for slot in range(1, 7):
            name = shops.shop_location_name("Gateon Port Shop", slot)
            location = self.multiworld.get_location(name, self.player)
            self.assertIsNot(LocationProgressType.EXCLUDED, location.progress_type, name)

    def test_nothing_required_is_placed_on_one(self) -> None:
        from Fill import distribute_items_restrictive

        distribute_items_restrictive(self.multiworld)
        for name in L.FILLER_ONLY_SHOP_LOCATIONS:
            item = self.multiworld.get_location(name, self.player).item
            self.assertIsNotNone(item, name)
            self.assertFalse(item.advancement, f"{name} received {item.name}, which the seed may need")


class TestThePitStopRevive(unittest.TestCase):
    def test_every_agate_mart_reaches_the_revive(self) -> None:
        """The whole point. A mart takes lines from the front, so 'in the list' is not 'on the shelf'."""
        for mart in ss.agate_pit_stop_marts():
            shelf = ss.AGATE_PIT_STOP_STOCK[:ss._patchable_count(mart)]
            self.assertIn(REVIVE, shelf, f"mart {mart}")

    def test_the_smallest_mart_is_the_one_that_used_to_miss_it(self) -> None:
        """Named explicitly so the regression is legible: seven lines, and the Revive was the eighth."""
        smallest = min(ss.agate_pit_stop_marts(), key=ss._patchable_count)
        self.assertEqual(7, ss._patchable_count(smallest))
        self.assertIn(REVIVE, ss.AGATE_PIT_STOP_STOCK[:7])

    def test_the_hyper_potion_took_the_revive_s_old_place(self) -> None:
        """A swap, not a deletion -- the player said 'in place of something', so nothing may fall off."""
        self.assertEqual(HYPER_POTION, ss.AGATE_PIT_STOP_STOCK[7])
        self.assertIn(HYPER_POTION, ss.AGATE_PIT_STOP_STOCK)

    def test_nothing_left_the_stock_list(self) -> None:
        self.assertEqual({4, 3, 2, 13, 22, 21, 23, 24, 20}, set(ss.AGATE_PIT_STOP_STOCK))
        self.assertEqual(9, len(ss.AGATE_PIT_STOP_STOCK))
        self.assertEqual(len(set(ss.AGATE_PIT_STOP_STOCK)), len(ss.AGATE_PIT_STOP_STOCK))

    def test_the_three_balls_still_lead(self) -> None:
        """The existing invariant the reorder had to respect -- the smallest mart carries all three."""
        self.assertEqual((4, 3, 2), ss.AGATE_PIT_STOP_STOCK[:3])


if __name__ == "__main__":
    unittest.main()
