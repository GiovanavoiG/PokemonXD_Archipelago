"""ADDENDUM 177 (2026-09-13): five things the player asked for after the open-issues review.

The one worth reading carefully is the KeyItemShuffle fix. That option has been DefaultOnToggle for days while
doing only half its job -- it put key items in the pool and never took them out of their chests -- so the tests
here are mostly about the two halves being impossible to get out of step again.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from . import PokemonXDTestBase
from .. import items, locations, ram_client as rc, regions, rules, travel_locations as tl
from ..game_data import (chest_table, key_item_chests, shadow_regions, shops, story_bytes,
                         trainer_placements)
from ..tools import xd_rel_format as rel


# ================================================================================================ Poke Spots
class TestThePokeSpotsAreOneUnlock(unittest.TestCase):
    def test_one_item_one_check_three_bits(self) -> None:
        """Player: "Make sure poke spots are all one item to unlock them when randomized locations is on."

        The instruction was given once before ("Make the Poke Spots one unlock") and only half-done: the three
        spots already shared a REGION, so logic treated them as one place, but each kept its own item and check
        -- meaning two of the three items changed nothing whatsoever about reachability."""
        self.assertIn("Poke Spots", tl.TRAVEL_LOCATION_NAMES)
        self.assertEqual(len([n for n in tl.TRAVEL_LOCATION_NAMES if "Spot" in n]), 1)
        self.assertIn("Unlock - Poke Spots", locations.TRAVEL_UNLOCK_LOCATION_NAMES)
        self.assertEqual(
            tl.travel_unlock_members("Poke Spots"),
            ("Cave Poke Spot", "Oasis Poke Spot", "Rockground Poke Spot"),
        )

    def test_the_physical_bits_survive_the_collapse(self) -> None:
        """The game keeps a bit per spot in a different byte each. Collapsing the BIT table instead of adding a
        layer above it would have meant inventing a multi-byte TravelBit and throwing away the per-spot
        measurements ADDENDUM 85/91 actually confirmed."""
        for spot in tl.travel_unlock_members("Poke Spots"):
            self.assertIn(spot, tl.TRAVEL_LOCATION_BITS)
        bytes_used = {tl.TRAVEL_LOCATION_BITS[s].byte_offset for s in tl.travel_unlock_members("Poke Spots")}
        self.assertEqual(len(bytes_used), 3, "three different bytes -- one write could never have done it")

    def test_the_outskirt_adjacency_follows_the_rename(self) -> None:
        """Its sibling list named "Cave Poke Spot", which is no longer an item anyone can hold -- so the
        adjacency would have been unsatisfiable by that half."""
        self.assertIn("Poke Spots", tl.TRAVEL_LOCATION_ADJACENCY["Outskirt Stand"].sibling_items)
        self.assertNotIn("Cave Poke Spot", tl.TRAVEL_LOCATION_ADJACENCY["Outskirt Stand"].sibling_items)


class TestThePokeSpotItemOpensTheRegion(PokemonXDTestBase):
    options = {"randomize_travel_locations": True}

    def test_one_item_reaches_the_poke_spots(self) -> None:
        """One ITEM, not three -- the point of ADDENDUM 177.

        RETARGETED 2026-09-14 (ADDENDUM 190). The Poke Spots' chain edge carried a Data ROM requirement, and
        suppressing that edge moved the requirement onto the gateway rather than discarding it -- travelling
        to a Poke Spot does not hand you the ID Card. So the unlock is still ONE item for all three spots,
        which is what this test is about, and it is now ANDed with the ROM like the chain edge always was."""
        from ..items import requirement_to_pool_item

        self.assertFalse(self.multiworld.state.can_reach("Poke Spots", player=self.player))
        self.collect_by_name(tl.travel_unlock_item_name("Poke Spots"))
        self.assertFalse(self.multiworld.state.can_reach("Poke Spots", player=self.player),
                         "the suppressed chain edge's Data ROM requirement must survive on the gateway")
        self.collect_by_name(requirement_to_pool_item("Data ROM"))
        self.assertTrue(self.multiworld.state.can_reach("Poke Spots", player=self.player))


# ========================================================================================= key-item chests
class TestKeyItemChestsBecomeChecks(unittest.TestCase):
    def test_the_five_pool_bound_chests_are_the_ones_converted(self) -> None:
        """Player: "Replace those Key Item chests with AP checks if Key_Item_Shuffle is on, except for Elevator
        Key." Five of the 24 fenced chests hold an item that actually enters the pool, and those five are
        exactly where the double-source bug lived."""
        self.assertEqual(sorted(key_item_chests.SHUFFLED_KEY_ITEM_CHESTS), [17, 18, 42, 78, 80])
        for chest_id, item_name in key_item_chests.SHUFFLED_KEY_ITEM_CHESTS.items():
            # ADDENDUM 179: the Data ROM and ID Card were packaged into one item, so their own names left
            # GATING_KEY_ITEM_NAMES. Translated through items.requirement_to_pool_item, which is the one place
            # that knows about the packaging -- the chest table still records what the chest really holds.
            self.assertIn(items.requirement_to_pool_item(item_name), items.GATING_KEY_ITEM_NAMES, chest_id)
            self.assertNotIn(item_name, items.NEVER_SHUFFLED_KEY_ITEM_NAMES, chest_id)

    def test_the_two_cipher_lab_chests_now_both_point_at_the_packaged_item(self) -> None:
        """Chests 17 and 18 hold the Data ROM and the ID Card, which ADDENDUM 179 packaged together -- so both
        chests are still separate CHECKS while the thing they vanilla-hold is one ITEM."""
        self.assertEqual(
            {items.requirement_to_pool_item(key_item_chests.SHUFFLED_KEY_ITEM_CHESTS[c]) for c in (17, 18)},
            {items.COMBINED_KEY_ITEM_NAME},
        )
        self.assertNotEqual(locations.CHEST_ID_TO_LOCATION[17], locations.CHEST_ID_TO_LOCATION[18])

    def test_the_elevator_key_chest_is_the_players_exception_and_also_unsafe(self) -> None:
        """Both reasons hold independently: the player named it, AND the Elevator Key is in
        NEVER_SHUFFLED_KEY_ITEM_NAMES so it never enters the pool -- dummying it would delete it from the seed
        with nothing to replace it."""
        self.assertNotIn(79, key_item_chests.SHUFFLED_KEY_ITEM_CHESTS)
        self.assertIn(79, key_item_chests.KEPT_VANILLA)
        self.assertIn("Elevator Key", items.NEVER_SHUFFLED_KEY_ITEM_NAMES)

    def test_the_miror_radar_chest_is_excluded_on_the_same_softlock_reasoning(self) -> None:
        """NOT named by the player, so this is a judgement and is recorded as one. The Radar is not in the pool
        and is the in-game gate for the Oasis and Cave Poke Spots -- converting chest 77 would delete the only
        copy, which is the exact failure ADDENDUM 134 exists because of."""
        self.assertNotIn(77, key_item_chests.SHUFFLED_KEY_ITEM_CHESTS)
        self.assertIn(77, key_item_chests.KEPT_VANILLA)

    def test_the_battle_cd_chests_are_untouched(self) -> None:
        """Sixteen of the fenced chests hold Battle CDs, which are flavour rather than key items, so the
        instruction does not reach them. Converting them would trade sixteen CDs for sixteen checks -- a real
        trade, and the player's to make rather than a side effect of this one."""
        by_id = {c["chest"]: c for c in chest_table.CHESTS}
        cd_chests = [c for c, chest in by_id.items()
                     if chest["item"] >= rel.KEY_ITEM_ID_FLOOR
                     and c not in key_item_chests.SHUFFLED_KEY_ITEM_CHESTS
                     and c not in key_item_chests.KEPT_VANILLA
                     and c not in (9, 114)]
        # 15, not 16: chest 9 is also a Battle CD but sits in room 145, which chest_regions excludes outright,
        # so it was never a candidate for anything.
        self.assertEqual(len(cd_chests), 15)
        for chest_id in cd_chests:
            self.assertNotIn(chest_id, locations.KEY_ITEM_CHEST_LOCATION_NAMES)

    def test_the_ids_exist_regardless_of_the_option(self) -> None:
        """A location's id must never depend on a YAML setting: the id space is frozen forever, and an
        option-dependent table would renumber every chest after the first conversion."""
        for chest_id in key_item_chests.SHUFFLED_KEY_ITEM_CHESTS:
            name = locations.CHEST_ID_TO_LOCATION[chest_id]
            self.assertIn(name, locations.LOCATION_TABLE)
            self.assertEqual(locations.LOCATION_TABLE[name].id_offset,
                             locations._FROZEN_LOCATION_OFFSETS[name], name)

    def test_the_patcher_and_the_location_table_share_one_list(self) -> None:
        """The two failure modes are both silent: a chest that becomes a check without being dummied hands the
        player the key item AND the AP item, and one dummied without becoming a check deletes the key item from
        the seed. One list is what makes both impossible."""
        self.assertEqual(
            set(key_item_chests.chest_ids_to_convert(True)),
            {c for c, n in locations.CHEST_ID_TO_LOCATION.items()
             if n in locations.KEY_ITEM_CHEST_LOCATION_NAMES},
        )
        self.assertEqual(key_item_chests.chest_ids_to_convert(False), frozenset())

    def test_the_client_can_name_them_either_way(self) -> None:
        """An unrecognised location is deduped at the server; a client that could not NAME a location the seed
        does have would drop the check in silence."""
        for chest_id in key_item_chests.SHUFFLED_KEY_ITEM_CHESTS:
            self.assertIn(chest_id, rc.CHEST_ID_TO_LOCATION)
        self.assertEqual(rc.CHEST_ID_TO_LOCATION, locations.CHEST_ID_TO_LOCATION)


class TestKeyItemChestsOnlyExistWithTheOption(PokemonXDTestBase):
    options = {"randomize_chests": True, "key_item_shuffle": False}

    def test_they_are_not_created_with_the_option_off(self) -> None:
        """With it off the ISO patch leaves the chest holding its real key item, so a location here would
        promise a check the game never fires."""
        created = {loc.name for loc in self.multiworld.get_locations(1)}
        for name in locations.KEY_ITEM_CHEST_LOCATION_NAMES:
            self.assertNotIn(name, created, name)


class TestKeyItemChestsExistWithTheOptionOn(PokemonXDTestBase):
    options = {"randomize_chests": True, "key_item_shuffle": True}

    def test_they_are_created(self) -> None:
        created = {loc.name for loc in self.multiworld.get_locations(1)}
        for name in locations.KEY_ITEM_CHEST_LOCATION_NAMES:
            self.assertIn(name, created, name)


# ================================================================================================== shops
class TestOnlyConfirmedShops(unittest.TestCase):
    def test_every_shop_row_is_confirmed(self) -> None:
        """Three rounds in one day: "just add checks for our confirmed rooms" (I read that as a live `!room`
        reading -> 2), "I gave you pyrite shop, pyrite vending machine, agate shop, phenac shop as well" (-> 6),
        "Go ahead and add those four extras as well" (-> 10). Each round promoted only the rooms actually named,
        which is why it took three."""
        # ADDENDUM 238: every ROW is still confirmed -- the Battle CD shop is confirmed AND excluded,
        # which are deliberately different states. CONFIRMED_SHOPS is what ships.
        self.assertEqual(len(shops.SHOPS), 10)
        self.assertEqual(len(shops.CONFIRMED_SHOPS), 9)
        self.assertEqual([s.room_id for s in shops.EXCLUDED_SHOPS], [61])
        self.assertEqual(len(shops.UNCONFIRMED_SHOPS), 0)
        self.assertEqual(locations.SHOP_LOCATION_COUNT,
                         sum(shop.slot_count for shop in shops.CONFIRMED_SHOPS))
        # These two used to be identical because nothing was ever parked or excluded. They now differ by
        # exactly room 61: ALL_SHOP_ROOM_IDS is every row, SHOP_ROOM_IDS is what actually credits a purchase.
        self.assertEqual(shops.ALL_SHOP_ROOM_IDS - shops.SHOP_ROOM_IDS, {61})
        self.assertEqual(shops.SHOP_ROOM_IDS - shops.ALL_SHOP_ROOM_IDS, set())

    def test_every_confirmed_shop_records_why_it_is_trusted(self) -> None:
        """`source` is now the ONLY place the distinction survives, which is why it is worth having: two rooms
        have an actual live `!room` reading behind them and eight rest on the player's own compilation. Both
        create checks -- but if a shop's checks never fire in play, the eight "player" rooms are where to look and
        21/156 are the control."""
        by_source: "dict[str, list[int]]" = {}
        for shop in shops.SHOPS:
            by_source.setdefault(shop.source, []).append(shop.room_id)
        self.assertEqual(sorted(by_source["live"]), [21, 156])
        self.assertEqual(sorted(by_source["player"]), [50, 61, 103, 104, 119, 121, 134, 164])
        for room_id in by_source["live"]:
            self.assertIn("shop", rc.KNOWN_ROOM_IDS[room_id].lower(), room_id)

    def test_each_shop_has_checks_equal_to_its_randomized_stock(self) -> None:
        """ADDENDUM 178, player instruction: "Give each confirmed shop room ID checks equal to its randomized
        items." The flat 12 was a made-up number applied identically to an 18-line TM shop and a 4-line vending
        machine, so every shop was wrong in one of two directions at once."""
        # ADDENDUM 238c: Agate 8 -> 9 (its Great Ball line arrives with the ONBS crisis and is invisible to a
        # one-shelf count). Every other row already equalled the union across that shop's tiers.
        expected = {21: 18, 50: 12, 61: 9, 103: 12, 104: 6, 119: 4, 121: 12, 134: 9, 156: 15, 164: 8}
        self.assertEqual({shop.room_id: shop.slot_count for shop in shops.SHOPS}, expected)
        for shop in shops.CONFIRMED_SHOPS:
            names = shops.shop_location_names(shop)
            self.assertEqual(len(names), shop.slot_count, shop.name)
            self.assertEqual(names[-1], f"{shop.name} AP Item {shop.slot_count}")
            self.assertNotIn(f"{shop.name} AP Item {shop.slot_count + 1}", locations.LOCATION_TABLE)

    def test_the_counts_reconcile_with_addendum_110s_independent_total(self) -> None:
        """The reason to believe these numbers rather than treat them as another estimate. ADDENDUM 110 summed the
        same shop listing a year earlier and got 117 item lines, 3 Scents and 6 Poke Snacks, leaving 108
        randomizable. These ten rooms sum to 104 -- and the difference is exactly the ONE shop with no room id,
        the Gateon Port Herb Shop's 4 lines. Two derivations, agreeing to the item."""
        # ADDENDUM 238c: 104 -> 105 and 108 -> 109. ADDENDUM 110 counted a shop listing that shows ONE shelf
        # per shop, and Agate's shelf changes twice -- so both derivations were short by Agate's Great Ball
        # line, and they are still two independent derivations agreeing to the item.
        self.assertEqual(sum(shop.slot_count for shop in shops.SHOPS), 105)
        self.assertEqual(shops.UNMAPPED_SHOP_LINE_COUNT, 4)
        self.assertEqual(sum(shop.slot_count for shop in shops.SHOPS)
                         + shops.UNMAPPED_SHOP_LINE_COUNT, 109)

    def test_the_two_shops_that_grew_past_the_old_cap_took_fresh_ids(self) -> None:
        """Mt. Battle sells 18 randomizable lines and Gateon 15, both past the retired 12 -- so those slots are
        new names. Everything at 1..12 keeps the id it already had, which is why shrinking a shop costs nothing
        either: the tail names just go inert."""
        for name in ("Mt. Battle Shop AP Item 18", "Gateon Port Shop AP Item 15"):
            self.assertIn(name, locations.LOCATION_TABLE)
            self.assertGreater(locations.LOCATION_TABLE[name].id_offset, 1646)
        for name in ("Mt. Battle Shop AP Item 1", "Gateon Port Shop AP Item 12"):
            self.assertLess(locations.LOCATION_TABLE[name].id_offset, 1647)

    def test_a_shrunken_shops_tail_names_are_retired_not_reissued(self) -> None:
        """The vending machine sells 4 things, so slots 5..12 are gone from the table but keep their frozen ids --
        a later upward correction reclaims them rather than renumbering."""
        for slot in range(5, 13):
            name = f"Pyrite Vending Machine AP Item {slot}"
            self.assertNotIn(name, locations.LOCATION_TABLE, name)
            self.assertIn(name, locations._FROZEN_LOCATION_OFFSETS, name)

    def test_the_client_caps_on_the_shops_own_count(self) -> None:
        """A purchase past a shop's stock creates no new check -- but it still completes and still clears the Bag,
        which is the "never block the player" half and why a wrong count cannot break a seed."""
        self.assertEqual(rc.shop_slot_count_for_room(119), 4)
        self.assertEqual(rc.shop_slot_count_for_room(21), 18)
        self.assertEqual(rc.shop_slot_count_for_room(138), 0, "not a shop room")

    def test_the_parking_mechanism_still_works_with_nothing_parked(self) -> None:
        """Nothing is parked right now, and that must not have quietly become load-bearing: parking is what makes
        a wrong room id cheap to withdraw, so the empty case has to behave."""
        self.assertEqual(shops.UNCONFIRMED_SHOPS, ())
        self.assertEqual(len(shops.all_shop_location_names()),
                         sum(shop.slot_count for shop in shops.CONFIRMED_SHOPS))

    def test_room_119_holding_a_chest_too_is_not_a_conflict(self) -> None:
        """A RETRACTION, pinned so it is not re-derived. An earlier comment called room 119 suspect because the
        player's compilation lists it twice -- vending machine AND "Pyrite Town Outside" (chest 93) -- and said
        both could not be true. They can: a vending machine and a chest can share an outdoor area, and the chest
        table really does put chest 93 in room 119."""
        self.assertIn(119, shops.SHOP_ROOM_IDS)
        self.assertIn(119, {c["room"] for c in chest_table.CHESTS})
        self.assertEqual([c["chest"] for c in chest_table.CHESTS if c["room"] == 119], [93])

    def test_the_phenac_shop_region_follows_the_players_own_room_table(self) -> None:
        """Corrected with the promotion. This row said "Phenac City" on my own claim that the shop is usable on
        the first visit, which I never had a source for. Their room table puts 103 in Post-Sixes, and the later
        region is the safe direction if the guess was wrong."""
        from ..game_data import chest_regions

        shop = next(s for s in shops.SHOPS if s.room_id == 103)
        self.assertEqual(shop.region, chest_regions.ROOM_TO_REGION[103])
        self.assertEqual(shop.region, "Phenac City (Post-Sixes)")

    def test_an_unconfirmed_room_would_credit_nothing(self) -> None:
        """Vacuously true with all ten confirmed, so the mechanism is exercised directly instead: an id that is
        not a confirmed shop room resolves to None rather than to a guess. 138 is the HQ Lab interior."""
        for shop in shops.UNCONFIRMED_SHOPS:
            self.assertIsNone(shops.shop_for_room(shop.room_id), shop.name)
        self.assertIsNone(shops.shop_for_room(138))
        self.assertIsNone(shops.shop_for_room(None))

    def test_every_shop_location_sits_at_its_originally_frozen_id(self) -> None:
        """The property the parking mechanism exists to protect, and it was tested for real: these 120 locations
        were frozen when all ten shops shipped, then eight were parked, then promoted back in two rounds. Every
        one came back to the id it started at, so none of that renumbered anything."""
        for name in locations.SHOP_ITEM_LOCATIONS:
            self.assertEqual(locations.LOCATION_TABLE[name].id_offset,
                             locations._FROZEN_LOCATION_OFFSETS[name], name)


# ======================================================================================= purification census
class TestPurificationWeightsAreACensus(unittest.TestCase):
    def test_every_vanilla_shadow_resolves_to_a_region(self) -> None:
        """Player: "Use Vanilla shadow pokemon placement & their trainer locations to gate this." All 83."""
        self.assertEqual(shadow_regions.total_shadow_count(), 83)

    def test_the_weights_sum_to_the_ladder_length(self) -> None:
        weights = rules._PURIFICATION_WEIGHT_BY_REGION
        self.assertEqual(sum(weights.values()), locations.PURIFICATION_LOCATION_COUNT)

    def test_the_tombstone_is_gone(self) -> None:
        """The old table carried `"_retired Relic Forest": 0` for a region that stopped existing in ADDENDUM
        169. A census has no tombstones -- a region with no shadows is absent, not present-and-zero."""
        self.assertNotIn("_retired Relic Forest", rules._PURIFICATION_WEIGHT_BY_REGION)
        for region in rules._PURIFICATION_WEIGHT_BY_REGION:
            self.assertIn(region, regions.REGION_NAMES, region)

    def test_the_four_unresolvable_shadows_are_named_not_defaulted(self) -> None:
        """Three of their trainers are not in the 232-story roster, and one is Hordel, whose census row the
        player deliberately left filler-only. Their `area` text is unambiguous, so it is read from there --
        explicitly, rather than silently falling back to a region."""
        self.assertEqual(len(shadow_regions._AREA_FALLBACK), 4)
        self.assertEqual(shadow_regions._AREA_FALLBACK["Hordel"], "Outskirt Stand")
        self.assertIsNone(trainer_placements.region_for(1), "Hordel's trainer row is still filler-only")

    def test_a_repeated_trainer_contributes_its_earliest_region(self) -> None:
        """A shadow is obtainable from the first fight that offers it. Taking the latest region would push
        thresholds deeper than the game does and quietly make the ladder harder."""
        order = list(regions.REGION_NAMES)
        rows = shadow_regions.shadow_regions_in_graph_order()
        positions = [order.index(region) for region, _species in rows]
        self.assertEqual(positions, sorted(positions), "the ladder must be in graph order")


# ================================================================================= per-area story-byte memory
class TestAreaStoryByteMemoryRule(unittest.TestCase):
    def test_a_first_visit_uses_the_areas_floor(self) -> None:
        """Player: "If it's our first time entering the area, use the byte marked as the first visit."

        RETARGETED BY ADDENDUM 331: Phenac is the one area whose icon now deliberately does NOT enter at its
        window floor -- the player asked for the unlocked town on every landing -- so it is the wrong example
        for the general rule. Pyrite is an ordinary area and makes the same point; Phenac's own behaviour is
        asserted right below, so the exception is pinned rather than dropped."""
        memory = rc.AreaStoryByteMemory()
        self.assertEqual(memory.target_for("Pyrite Town"),
                         story_bytes.region_floor("Pyrite Town"))

    def test_phenac_is_entered_at_the_unlocked_town_not_its_window_floor(self) -> None:
        """ADDENDUM 331, the exception the test above used to be written on. Player: "raise the floor and its
        current byte the moment we land in the phenac room id, so that the return trip doesn't kick us out
        again"."""
        memory = rc.AreaStoryByteMemory()
        self.assertEqual(0x3E, story_bytes.region_floor("Phenac City"))
        self.assertEqual(0x41, memory.target_for("Phenac City"))

    def test_a_later_visit_uses_the_highest_reached_there(self) -> None:
        memory = rc.AreaStoryByteMemory()
        floor = story_bytes.region_floor("Phenac City")
        memory.observe("Phenac City", floor + 5)
        self.assertEqual(memory.target_for("Phenac City"), floor + 5)

    def test_the_target_never_drops_below_the_areas_floor(self) -> None:
        """An area's floor is what the story had to have reached for the area to exist at all, so entering
        below it would build a room the game has no state for."""
        memory = rc.AreaStoryByteMemory()
        memory.observe("Citadark Isle", 0x01)
        self.assertEqual(memory.target_for("Citadark Isle"),
                         story_bytes.region_floor("Citadark Isle"))

    def test_an_always_open_area_has_nothing_to_say(self) -> None:
        """No story window means no honest answer, and None is how this class declines."""
        memory = rc.AreaStoryByteMemory()
        # ADDENDUM 279: Gateon has a first-visit byte now -- it always did, this project had just never
        # recorded it. "Nothing to say" was the assumption that let the player walk in carrying another area's
        # byte, which is the whole run of reports 277-279. ADDENDUM 379 moved the value 0x0F -> 0x10 on the
        # player's instruction; what this test is about is that the answer is not None.
        self.assertEqual(0x10, memory.target_for("Gateon Port"))
        self.assertIsNotNone(memory.target_for("Gateon Port"), "the ADDENDUM 279 property, value aside")
        self.assertIsNone(memory.target_for(None))
        self.assertIsNone(memory.target_for("Not A Region"))

    def test_the_high_water_mark_only_ever_rises(self) -> None:
        # RETARGETED 2026-09-26 (ADDENDUM 365): the values are now inside Pyrite's own range. They were 0x40
        # and 0x38, picked as "a big number and a smaller one" to exercise the monotonic rule -- but 0x40 is
        # in PHENAC's window, and `observe` now refuses a byte above the area's ceiling. The rule under test
        # is unchanged; only the numbers used to demonstrate it are ones Pyrite can actually hold.
        memory = rc.AreaStoryByteMemory()
        memory.observe("Pyrite Town", 0x3A)
        memory.observe("Pyrite Town", 0x32)
        self.assertEqual(memory.highest_by_region["Pyrite Town"], 0x3A)

    def test_observing_nothing_changes_nothing(self) -> None:
        memory = rc.AreaStoryByteMemory()
        self.assertFalse(memory.observe(None, 0x40))
        self.assertFalse(memory.observe("Pyrite Town", None))
        self.assertEqual(memory.highest_by_region, {})


class TestAreaStoryByteMemoryPersistence(unittest.TestCase):
    def test_it_round_trips_through_json(self) -> None:
        """The high-water mark is the ONE thing that cannot be recovered by looking at the game -- the save
        holds a single global byte, not a per-area history -- so a client that forgot would send the player back
        to an area's floor and undo their progress there."""
        memory = rc.AreaStoryByteMemory()
        memory.observe("Pyrite Town", 0x40)
        memory.observe("Phenac City", 0x45)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "area.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(memory.to_json(), handle)
            restored = rc.AreaStoryByteMemory()
            with open(path, encoding="utf-8") as handle:
                restored.load_json(json.load(handle))
        self.assertEqual(restored.highest_by_region, memory.highest_by_region)
        self.assertEqual(restored.visited, memory.visited)

    def test_a_corrupt_file_degrades_to_no_memory_rather_than_raising(self) -> None:
        """The cost of degrading is that first visits are re-detected. The cost of raising would be no client."""
        memory = rc.AreaStoryByteMemory()
        memory.load_json({"highest_by_region": "not a dict", "visited": 7})
        self.assertEqual(memory.highest_by_region, {})
        self.assertEqual(memory.visited, set())

    def test_a_remembered_region_counts_as_visited_even_if_the_lists_disagree(self) -> None:
        # ADDENDUM 276: the payload carries a schema now. A file WITHOUT one is written by a client old
        # enough to have poisoned its own marks and is discarded on load, which is asserted in
        # test_addendum_276_*; the property under test here is the backfill, so it uses a current file.
        memory = rc.AreaStoryByteMemory()
        memory.load_json({"schema": rc.AREA_MEMORY_SCHEMA_VERSION,
                          "highest_by_region": {"Pyrite Town": 64}, "visited": []})
        self.assertIn("Pyrite Town", memory.visited)

    def test_writing_is_marked_dirty_so_it_gets_saved(self) -> None:
        memory = rc.AreaStoryByteMemory()
        self.assertFalse(memory.dirty)
        memory.observe("Pyrite Town", 0x3A)   # ADDENDUM 365: in Pyrite's range; 0x40 is Phenac's
        self.assertTrue(memory.dirty)


class TestAreaStoryByteMemoryWiring(unittest.TestCase):
    def setUp(self) -> None:
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Client.py")
        with open(path, encoding="utf-8") as handle:
            self.source = handle.read()

    def test_it_is_armed_by_travel_randomization_alone(self) -> None:
        """REWRITTEN 2026-09-14 (ADDENDUM 196), was "it needs both options".

        There is no second option any more. The player: "Fold the Story_Byte yaml option into location
        shuffle - it is a feature built exclusively for location shuffle." They are right, and the old test
        says why without noticing: with travel randomization OFF the player reaches every area by playing, so
        the global byte is already correct everywhere and the memory has nothing to do. The two flags were
        ANDed at all three call sites and there was never a reason to set them differently."""
        start = self.source.index("async def check_area_story_memory(ctx: PokemonXDContext) -> None:")
        body = self.source[start:self.source.index("\nasync def ", start + 1)]
        self.assertIn("if not ctx.randomize_travel_locations:", body)
        self.assertNotIn("story_byte_area_memory", body)

    def test_the_option_is_gone_entirely(self) -> None:
        """Not merely defaulted off -- removed, so the generated template matches the player's own YAML."""
        from ..options import PokemonXDOptions

        self.assertNotIn("story_byte_area_memory", PokemonXDOptions.type_hints)
        self.assertNotIn("include_traps", PokemonXDOptions.type_hints)
        self.assertNotIn("story_byte_area_memory", self.source)

    def test_the_hook_is_the_map_screen(self) -> None:
        """Writing after the room loads is too late -- the room has already been built from the old byte. This
        is what ADDENDUM 164's cursor hunt and ADDENDUM 172's destination table were for."""
        start = self.source.index("async def check_area_story_memory(ctx: PokemonXDContext) -> None:")
        body = self.source[start:self.source.index("\nasync def ", start + 1)]
        self.assertIn("MAP_SCREEN_ROOM_ID", body)
        self.assertIn("map_destination_region", body)

    def test_it_runs_inside_the_block_stability_gate(self) -> None:
        """It WRITES to the save block, so it belongs behind the ADDENDUM 148 gate with every other block writer
        -- polling a block that is mid-rewrite is what that gate exists to stop. Checked by position relative to
        `if block_is_stable:` rather than to some other call, since the call order inside the gate is not the
        property that matters."""
        gate = self.source.index("if block_is_stable:")
        call = self.source.index("await check_area_story_memory(ctx)")
        self.assertGreater(call, gate)
        # ...and inside the same block, i.e. before the gate's own `if _looks_ingame():` sub-branch ends it.
        # ADDENDUM 353: anchored on the END of the stability block, not on the `if _looks_ingame():`
        # sub-branch that used to close it -- that gate is gone from the main loop. Same property.
        self.assertLess(call, self.source.index("elif not ctx._block_churn_logged:", gate))



if __name__ == "__main__":
    unittest.main()
