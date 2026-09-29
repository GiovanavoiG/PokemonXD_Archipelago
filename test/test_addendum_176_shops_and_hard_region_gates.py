"""ADDENDUM 176 (2026-09-13): hard region prerequisites, and shops named after shops.

Player instruction: "Gate Cipher Key Lair logically behind Snagem. Gate Snagem logically behind full SS Libra
access. Implement the shops. Replace our current shop checks with those."

The gating half needed a test precisely because the BASE chain already satisfied it and the travel-shuffle
gateway did not -- so "does the graph do this" has two different answers depending on one option, and only one
of them was wrong.
"""
from __future__ import annotations

import unittest

from BaseClasses import LocationProgressType

from . import PokemonXDTestBase
from .. import items as _items, locations, ram_client as rc, regions, rules, travel_locations as tl
from ..game_data import shops


class TestTheHardPrerequisiteTable(unittest.TestCase):
    def test_it_says_what_the_player_asked_for(self) -> None:
        """UPDATED by ADDENDUM 293, then EMPTIED of ADDENDUM 176's own two entries by ADDENDUM 332.

        Both halves of the original instruction -- "Gate Cipher Key Lair logically behind Snagem. Gate Snagem
        logically behind full SS Libra access." -- have since been withdrawn by the player who gave them: the
        Snagem half in ADDENDUM 293, the Key Lair half in ADDENDUM 332 ("Decouple Key Lair from snagem - we no
        longer need snagem to access key lair").

        The TABLE is not empty and the mechanism is not gone: ADDENDUM 324 put the SS Libra's entry in it. So
        what this test guards now is that neither withdrawn constraint has crept back, and that the one live
        entry is the one that is supposed to be there."""
        self.assertNotIn("Cipher Key Lair", tl.TRAVEL_LOCATION_REQUIRED_REGIONS)
        self.assertNotIn("Snagem Hideout", tl.TRAVEL_LOCATION_REQUIRED_REGIONS)
        self.assertEqual({"SS Libra"}, set(tl.TRAVEL_LOCATION_REQUIRED_REGIONS))

    def test_no_prerequisite_anywhere_names_the_ss_libra(self) -> None:
        """ADDENDUM 293, stated as the property rather than as the one entry that used to break it.

        Neither tier of the ship may appear as a hard prerequisite. The upgraded `SS Libra` node is the
        Scooter gate (ADDENDUM 273) and `SS Libra (stranded)` is the failure state ADDENDUM 91 found --
        boarding without the scooter drops the player at Phenac City -- so naming either one puts a
        destination behind the ship, which is what this addendum exists to undo."""
        self.assertIn("SS Libra (stranded)", regions.REGION_NAMES)
        named = {region for needed in tl.TRAVEL_LOCATION_REQUIRED_REGIONS.values() for region in needed}
        self.assertNotIn("SS Libra", named)
        self.assertNotIn("SS Libra (stranded)", named)

    def test_the_key_is_the_travel_name_not_the_region_name(self) -> None:
        """The travel menu spells the destination "Cipher Key Lair"; its region is "Cipher Key Lair". A key
        written as the region name would sit here silently gating nothing, which the module's own assertion is
        there to catch."""
        self.assertIn("Cipher Key Lair", tl.TRAVEL_LOCATION_TARGET_REGION)
        self.assertEqual(tl.TRAVEL_LOCATION_TARGET_REGION["Cipher Key Lair"], "Cipher Key Lair")
        self.assertNotIn("Cipher Key Lair", tl.TRAVEL_LOCATION_REQUIRED_REGIONS)

    def test_it_is_a_hard_and_not_the_adjacency_or(self) -> None:
        """AdjacencyRequirement is satisfiable by a SIBLING ITEM. These are not -- the region must be
        reachable, whatever is held. Kept as separate tables so the two cannot be confused."""
        self.assertNotIn("Snagem Hideout", tl.TRAVEL_LOCATION_ADJACENCY)
        for name in tl.TRAVEL_LOCATION_REQUIRED_REGIONS:
            adjacency = tl.TRAVEL_LOCATION_ADJACENCY.get(name)
            if adjacency is not None:
                self.assertNotEqual(adjacency.regions, tl.TRAVEL_LOCATION_REQUIRED_REGIONS[name])


class TestTheBaseChainAlreadyHeld(PokemonXDTestBase):
    """With travel randomization OFF the story chain runs SS Libra -> Key Lair (exterior) -> Outskirt Stand ->
    Snagem Hideout -> Cipher Key Lair, so both requirements were already true. Asserted so a future edge edit
    cannot quietly drop them and leave only the gateway fix standing.

    UNCHANGED by ADDENDUM 293, and deliberately so: in this mode the ship really IS in front of Snagem,
    because `ram_client.ScooterStoryHold` holds the story byte below the scooter upgrade until the item
    arrives. `regions.TRAVEL_SHUFFLE_REROUTED_EDGES` only applies with travel shuffle on, for this reason."""

    options = {"randomize_travel_locations": False}

    def test_snagem_is_behind_ss_libra(self) -> None:
        order = list(regions.REGION_NAMES)
        self.assertLess(order.index("SS Libra"), order.index("Snagem Hideout"))
        self.assertIn(("Outskirt Stand", "Snagem Hideout", ()), regions.REGION_EDGES)

    def test_the_key_lair_is_behind_snagem(self) -> None:
        self.assertIn(("Snagem Hideout", "Cipher Key Lair", ()), regions.REGION_EDGES)

    def test_neither_is_reachable_without_the_chain(self) -> None:
        self.assertFalse(self.multiworld.state.can_reach("Snagem Hideout", player=self.player))
        self.assertFalse(self.multiworld.state.can_reach("Cipher Key Lair", player=self.player))
        self.collect_key_item_chain()
        self.assertTrue(self.multiworld.state.can_reach("Snagem Hideout", player=self.player))
        self.assertTrue(self.multiworld.state.can_reach("Cipher Key Lair", player=self.player))


class TestTheGatewayBypassIsClosed(PokemonXDTestBase):
    """THE ACTUAL BUG. With travel randomization on, ADDENDUM 104 gives every destination an entrance straight
    off Menu whose only requirement is holding that destination's travel-unlock item -- so the Snagem item alone
    opened Snagem with no SS Libra anywhere, and the Key Lair item opened the Key Lair with no Snagem.

    ADDENDUM 293 (2026-09-20): the Snagem half of that is no longer a bug, because the player withdrew the
    requirement it enforced. The Key Lair half stands. Both are still tested here, one for each direction, so
    the file records the reversal instead of quietly losing a test."""

    options = {"randomize_travel_locations": True}

    def test_the_snagem_item_alone_is_enough_again(self) -> None:
        """REVERSED by ADDENDUM 293, and named so the reversal is impossible to read as a regression.

        ADDENDUM 176 made this assert the OPPOSITE -- the Snagem travel item alone must not open Snagem,
        because SS Libra was a hard prerequisite. The player has withdrawn that prerequisite ("Snagem is no
        longer gated behind SS libra"), so the item alone is the whole requirement now, and it matches what
        the client can deliver: the icon appears on the item, the hover writes 0x62, the player walks in."""
        self.collect_by_name(tl.travel_unlock_item_name("Snagem Hideout"))
        self.assertTrue(self.multiworld.state.can_reach("Snagem Hideout", player=self.player))

    def test_the_key_lair_item_alone_is_now_enough(self) -> None:
        """RETARGETED BY ADDENDUM 332, and the flip is the instruction. Player: "Decouple Key Lair from
        snagem - we no longer need snagem to access key lair."

        This used to assert the opposite -- the item alone was NOT enough -- which was ADDENDUM 176's gate.
        What made it safe to drop is that the state the gate stood in for is now WRITTEN on arrival: the Key
        Lab icon enters at `AREA_ENTRY_FLOOR_OVERRIDES["Cipher Key Lair"]` = 0x64, which is "Gonzap beaten,
        the Lair open" (ADDENDUM 324). The client no longer needs the player to have taken the game's own
        route through the hideout."""
        self.collect_by_name(tl.travel_unlock_item_name("Cipher Key Lair"))
        self.assertTrue(self.multiworld.state.can_reach("Cipher Key Lair", player=self.player))

    def test_the_ship_is_the_gate_that_still_holds(self) -> None:
        """The MECHANISM is what this class is really about, so it is demonstrated on the entry that still
        exists rather than deleted with the one that does not. `TRAVEL_LOCATION_REQUIRED_REGIONS` is a hard
        AND: the SS Libra item alone must not open the ship until Phenac is genuinely cleared."""
        self.collect_by_name(tl.travel_unlock_item_name("SS Libra"))
        self.assertFalse(self.multiworld.state.can_reach("SS Libra", player=self.player))
        self.collect_by_name(tl.travel_unlock_item_name("Phenac City"))
        self.collect_key_item_chain()
        self.assertTrue(self.multiworld.state.can_reach("Phenac City (Post-Sixes)", player=self.player))
        self.assertTrue(self.multiworld.state.can_reach("SS Libra", player=self.player))

    # The whole-pool version of this -- "hold everything except the Scooter Upgrade, and see what is still
    # shut" -- lives in `test_addendum_293_*`, where the class actually turns `shuffle_scooter_upgrade` on.
    # Asserted here it would pass vacuously: with the option off the Scooter is never created, `regions.py`
    # drops it from the SS Libra edge, and "reachable without the Scooter" is true of everything.

    def test_an_unrelated_destination_is_unaffected(self) -> None:
        """The prerequisite table must be narrow. Phenac City has no entry, so its item alone still works --
        the two constraints came from the player's knowledge of the game, not from a general rule."""
        self.collect_by_name(tl.travel_unlock_item_name("Phenac City"))
        self.assertTrue(self.multiworld.state.can_reach("Phenac City", player=self.player))


class TestTheShopTable(unittest.TestCase):
    def test_ten_shops_each_in_its_rooms_region(self) -> None:
        self.assertEqual(len(shops.SHOPS), 10)
        for shop in shops.SHOPS:
            self.assertIn(shop.region, regions.REGION_NAMES, shop.name)

    def test_the_name_format_is_the_players_own(self) -> None:
        """Verbatim from the request: "'Gateon Port Shop AP Item 1' etc.\""""
        self.assertEqual(shops.shop_location_name("Gateon Port Shop", 1), "Gateon Port Shop AP Item 1")
        self.assertIn("Gateon Port Shop AP Item 1", locations.LOCATION_TABLE)

    def test_room_ids_are_unique_and_confirmed_ones_resolve_back(self) -> None:
        """ADDENDUM 177: `shop_for_room` answers for CONFIRMED shops only -- an unconfirmed room must not
        credit anything, because its id has never been read in game and could be wrong."""
        for shop in shops.CONFIRMED_SHOPS:
            self.assertIs(shops.shop_for_room(shop.room_id), shop)
        for shop in shops.UNCONFIRMED_SHOPS:
            self.assertIsNone(shops.shop_for_room(shop.room_id), shop.name)
        self.assertIsNone(shops.shop_for_room(None))
        self.assertIsNone(shops.shop_for_room(138), "the HQ Lab interior is not a shop")

    def test_the_count_is_the_cap_times_the_CONFIRMED_shops(self) -> None:
        """ADDENDUM 177 settled this over three rounds: "just add checks for our confirmed rooms" (I read that as
        a live `!room` reading and shipped 2), then "I gave you pyrite shop, pyrite vending machine, agate shop,
        phenac shop as well" (6), then "Go ahead and add those four extras as well" (10).

        The COUNT is not the interesting assertion -- it moved three times in one day. The relationship is: the
        location count is the cap times however many shops are confirmed, whatever that number is."""
        # ADDENDUM 178: per-shop counts replaced the flat cap, so this is a SUM rather than a product.
        self.assertEqual(locations.SHOP_LOCATION_COUNT,
                         sum(shop.slot_count for shop in shops.CONFIRMED_SHOPS))
        self.assertEqual(len(shops.CONFIRMED_SHOPS) + len(shops.UNCONFIRMED_SHOPS)
                         + len(shops.EXCLUDED_SHOPS), len(shops.SHOPS))
        # 2026-09-15, player: "Exclude the whole battle CD shop." Room 61's nine Battle CD lines leave the
        # location table; the row survives in SHOPS so the mart mapping and the 104-line reconciliation below
        # still hold, but it creates no checks. 104 - 9 = 95.
        # ADDENDUM 238c: 95 -> 96. Agate Village went from 8 lines to 9 once the count became the union
        # across its three tiers rather than one shelf snapshot -- its Great Ball only appears after the ONBS
        # crisis, so no single shelf shows all nine.
        self.assertEqual(locations.SHOP_LOCATION_COUNT, 96)

    def test_the_two_known_shop_rooms_agree_with_the_live_room_names(self) -> None:
        """21 and 156 are the two rooms this project has actually confirmed in game (ram_client's own
        KNOWN_ROOM_IDS calls them a shop). The other eight come from the player's compilation."""
        for room_id in (21, 156):
            self.assertIn(room_id, shops.SHOP_ROOM_IDS)
            self.assertIn("shop", rc.KNOWN_ROOM_IDS[room_id].lower())


class TestTheBerryLadderIsGone(unittest.TestCase):
    def test_no_buy_shop_item_location_survives(self) -> None:
        leftovers = [n for n in locations.LOCATION_TABLE if n.startswith("Buy Shop Item - ")]
        self.assertEqual(leftovers, [])

    def test_the_synthetic_region_is_gone(self) -> None:
        self.assertNotIn("Shop Purchases", locations.LOCATIONS_BY_REGION)

    def test_the_ladder_helpers_are_deleted_not_repurposed(self) -> None:
        for module in (locations, rc):
            self.assertFalse(hasattr(module, "shop_item_location_name"), module.__name__)
        self.assertFalse(hasattr(locations, "SHOP_ITEM_PER_BERRY_CAP"))
        self.assertFalse(hasattr(rc, "SHOP_ITEM_PER_BERRY_CAP"))

    def test_the_retired_model_is_gone(self) -> None:
        self.assertFalse(hasattr(rules, "_SHOP_OCCURRENCE_REGIONS"))

    def test_the_berries_themselves_survive(self) -> None:
        """They are still the in-game mechanism -- what the ISO patch writes into every mart slot and what the
        client watches. Only the location NAMES stopped being about them."""
        self.assertEqual(len(locations.SHOP_ITEM_BERRY_NAMES), 26)
        self.assertIn("Razz Berry", locations.SHOP_ITEM_BERRY_NAMES)

    def test_the_retired_ids_are_never_reissued(self) -> None:
        """1073-1180 held the 108 berry-occurrence locations. A new location inheriting one of those ids would
        inherit a live seed's memory of a berry occurrence."""
        for name in locations.SHOP_ITEM_LOCATIONS:
            self.assertNotIn(locations.LOCATION_TABLE[name].id_offset, range(1073, 1181), name)

    def test_nothing_in_the_table_floats(self) -> None:
        unfrozen = [n for n in locations.LOCATION_TABLE if n not in locations._FROZEN_LOCATION_OFFSETS]
        self.assertEqual(unfrozen, [])


class TestShopsAreGatedByTheirTown(PokemonXDTestBase):
    options = {"randomize_shops": True}

    def test_an_always_open_towns_shop_is_open_and_a_gated_ones_is_not(self) -> None:
        """RETARGETED (ADDENDUM 177): the Outskirt Stand shop is no longer created, so the late probe is
        Mt. Battle -- the other confirmed room, and one behind the Machine Part."""
        self.assertTrue(self.can_reach_location("Gateon Port Shop AP Item 1"))
        self.assertFalse(self.can_reach_location("Mt. Battle Shop AP Item 1"))
        self.collect_key_item_chain(1)  # the Machine Part opens Agate, and Mt. Battle behind it
        self.assertTrue(self.can_reach_location("Mt. Battle Shop AP Item 1"))

    def test_every_slot_of_one_shop_shares_that_shops_gate(self) -> None:
        """PARTLY SUPERSEDED 2026-09-15 (ADDENDUM 238c/238d). The claim this test was written to defend -- that
        slot N of a shop is no deeper than slot 1, because depth is the town -- was right about the OLD model,
        where a slot number was an arbitrary position in a global berry rotation. It is not right any more.
        Berries are now dealt per shop LINE, so slot N is the Nth line that shop ever offers, and a line a
        restock introduces genuinely is deeper than the opening shelf: Gateon's slot 15 is its Full Restore,
        which does not exist until Gorigan is beaten.

        What survives, and is what the test still checks: the OPENING shelf is gated by the town and nothing
        else. Slot 1 of a reachable shop is reachable; slot 1 of an unreachable one is not."""
        self.assertTrue(self.can_reach_location("Gateon Port Shop AP Item 1"))
        self.assertFalse(self.can_reach_location(
            f"Gateon Port Shop AP Item {shops.SHOPS_BY_ROOM[156].slot_count}"))
        for slot in (1, shops.SHOPS_BY_ROOM[21].slot_count):
            self.assertFalse(self.can_reach_location(f"Mt. Battle Shop AP Item {slot}"))


class TestShopsOffEntirely(PokemonXDTestBase):
    options = {"randomize_shops": False}

    def test_no_shop_locations_are_created(self) -> None:
        created = {loc.name for loc in self.multiworld.get_locations(1)}
        for name in locations.SHOP_ITEM_LOCATIONS:
            self.assertNotIn(name, created)


if __name__ == "__main__":
    unittest.main()
