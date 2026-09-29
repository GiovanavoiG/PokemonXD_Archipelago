"""ADDENDUM 174 (2026-09-13): the "Open N Chests" ladder is replaced by per-chest locations.

Player instruction: "Replace Open N Chests with those chest ID checks, and integrate their logic using their
locations and the gates I've given you."

The tests worth having here are the ones about the SEAM, not about the formula -- ADDENDUM 173's suite already
pins the bit maths. What can go wrong in a migration like this is: an id shifting under a location that
already exists in someone's seed, the client and the world disagreeing about a name, a chest ending up in the
wrong region, or the shared-flag pair quietly double-crediting.
"""
from __future__ import annotations

import unittest

from BaseClasses import LocationProgressType

from . import PokemonXDTestBase
from .. import locations, ram_client as rc, regions, rules
from ..game_data import chest_flags, chest_names, chest_regions, chest_table
from ..tools import xd_rel_format as rel


class TestTheLadderIsGone(unittest.TestCase):
    def test_no_open_n_chests_location_survives(self) -> None:
        leftovers = [n for n in locations.LOCATION_TABLE
                     if n.startswith("Open ") and n.endswith(" Chests")]
        self.assertEqual(leftovers, [])

    def test_the_synthetic_region_is_gone_too(self) -> None:
        """It was connected straight off Menu because a count is not a place. Per-chest locations are places."""
        self.assertNotIn("Chest Opening", locations.LOCATIONS_BY_REGION)

    def test_the_ladder_helpers_are_removed_rather_than_repurposed(self) -> None:
        """`chest_location_name(count)` is deliberately DELETED, not redefined: counts 1..90 are also valid
        chest ids, so a same-named replacement would have let every stale caller keep running while silently
        meaning something else. The same applies to the client's copy."""
        self.assertFalse(hasattr(locations, "chest_location_name"))
        self.assertFalse(hasattr(rc, "chest_location_name"))
        self.assertFalse(hasattr(locations, "CHEST_LOCATION_TO_COUNT"))

    def test_the_count_tracker_is_deleted(self) -> None:
        """Keeping it would have meant keeping a poller whose entire output is location names the server now
        rejects -- worse than dead code."""
        self.assertFalse(hasattr(rc, "ChestCountTracker"))

    def test_the_retired_sphere_model_is_gone(self) -> None:
        self.assertFalse(hasattr(rules, "_CHEST_WEIGHT_BY_REGION"))


class TestNoExistingLocationIdMoved(unittest.TestCase):
    """The migration's one irreversible risk. Location ids are a seed's contract with its players; a name that
    silently changes id turns every check on it into a check on something else."""

    def test_the_fourteen_formerly_floating_names_are_pinned_where_they_were(self) -> None:
        """These were the only unfrozen names in the table, so they sat at the end and would have shifted the
        moment any new location was appended earlier -- which is exactly what this addendum does. Recorded as
        literals, because reading them back out of the same table they are meant to protect would prove
        nothing."""
        expected = {
            "Catch - Eeveelution (Any)": 1418,
            "Unlock - Snagem Hideout": 1419,
            "Unlock - Outskirt Stand": 1420,
            "Unlock - Cave Poke Spot": 1421,
            "Unlock - Pyrite Town": 1422,
            "Unlock - Phenac City": 1423,
            "Unlock - Oasis Poke Spot": 1424,
            "Unlock - Realgam Tower": 1425,
            "Unlock - Cipher Key Lair": 1426,
            "Unlock - Rockground Poke Spot": 1427,
            "Unlock - Cipher Lab": 1428,
            "Unlock - Mt. Battle": 1429,
            "Unlock - SS Libra": 1430,
            "Unlock - Orre Colosseum": 1431,
        }
        # ADDENDUM 177 retired the three separate Poke Spot unlocks (one "Unlock - Poke Spots" replaced them),
        # so three of these names no longer exist as live locations. What this test protects is that the ones
        # that DO still exist never moved -- a retired name's frozen entry is inert by design, and asserting a
        # dead name's id would just be asserting the tombstone.
        retired_by_177 = {"Unlock - Cave Poke Spot", "Unlock - Oasis Poke Spot",
                          "Unlock - Rockground Poke Spot"}
        for name, offset in expected.items():
            if name in retired_by_177:
                self.assertNotIn(name, locations.LOCATION_TABLE, name)
                self.assertEqual(locations._FROZEN_LOCATION_OFFSETS[name], offset, name)
                continue
            self.assertEqual(locations.LOCATION_TABLE[name].id_offset, offset, name)

    def test_nothing_floats_any_more(self) -> None:
        """With the fourteen pinned AND the 89 new chest locations pinned on the day they were created,
        nothing in the table floats -- so the NEXT person to append a category cannot shift an existing id by
        accident either. Leaving the new names unfrozen would have reproduced exactly the situation this
        addendum had to clean up."""
        unfrozen = [n for n in locations.LOCATION_TABLE
                    if n not in locations._FROZEN_LOCATION_OFFSETS]
        self.assertEqual(unfrozen, [])

    def test_the_new_chest_locations_took_ids_above_everything_that_existed_before(self) -> None:
        """1431 was the highest id in the table before this addendum. Every chest location must sit above it,
        which is what "appended, not inserted" actually means in id terms."""
        for name in locations.CHEST_LOCATION_NAMES:
            self.assertGreater(locations.LOCATION_TABLE[name].id_offset, 1431, name)

    def test_the_retired_ladder_ids_are_never_reissued(self) -> None:
        """1181-1270 held the ladder. A new location landing in that range would inherit an id that a live
        seed still remembers as "Open 37 Chests"."""
        for name in locations.CHEST_LOCATION_NAMES:
            self.assertNotIn(locations.LOCATION_TABLE[name].id_offset, range(1181, 1271), name)


class TestWhichChestsQualify(unittest.TestCase):
    def test_the_filters_are_the_ones_in_force_plus_the_177_exception(self) -> None:
        """ADDENDUM 177 added a fourth clause: the five key-item chests KeyItemShuffle converts are in the table
        even though their vanilla item is above the fence."""
        from ..game_data import key_item_chests

        by_id = {c["chest"]: c for c in chest_table.CHESTS}
        expected = {
            chest_id for chest_id in by_id
            if chest_flags.chest_flag_id(chest_id) is not None
            and chest_id in chest_regions.CHEST_TO_REGION
            and (by_id[chest_id]["item"] < rel.KEY_ITEM_ID_FLOOR
                 or chest_id in key_item_chests.SHUFFLED_KEY_ITEM_CHESTS)
        }
        self.assertEqual(set(locations.CHEST_ID_TO_LOCATION), expected)
        self.assertEqual(len(expected), 95)

    def test_the_key_item_chests_outside_the_177_exception_are_still_not_locations(self) -> None:
        """ADDENDUM 134 exists because overwriting the ID Card deleted it from a seed and softlocked a live run.
        ADDENDUM 177 opened exactly five of those chests -- the ones whose item KeyItemShuffle actually puts in
        the pool, so nothing is deleted. The other nineteen are still out, and that is the half worth pinning:
        the Miror Radar and the Elevator Key would vanish from the seed entirely, and sixteen Battle CDs are not
        key items at all."""
        from ..game_data import key_item_chests

        by_id = {c["chest"]: c for c in chest_table.CHESTS}
        still_out = 0
        for chest_id, chest in by_id.items():
            if chest["item"] < rel.KEY_ITEM_ID_FLOOR:
                continue
            if chest_id in key_item_chests.SHUFFLED_KEY_ITEM_CHESTS:
                continue
            self.assertNotIn(chest_id, locations.CHEST_ID_TO_LOCATION, chest_id)
            still_out += 1
        self.assertEqual(still_out, 19)
        self.assertIn(79, key_item_chests.KEPT_VANILLA, "the Elevator Key chest")
        self.assertIn(77, key_item_chests.KEPT_VANILLA, "the Miror Radar chest")

    def test_the_unflagged_and_excluded_chests_are_out(self) -> None:
        for chest_id in chest_flags.UNFLAGGED_CHEST_IDS:
            self.assertNotIn(chest_id, locations.CHEST_ID_TO_LOCATION)
        for chest_id in chest_regions.EXCLUDED_CHESTS:
            self.assertNotIn(chest_id, locations.CHEST_ID_TO_LOCATION)


class TestTheFormerlySharedFlagPair(unittest.TestCase):
    """Chests 108 and 113 share flag id 1149, so while identity came from the flag array the game could not
    tell them apart -- ADDENDUM 172/174 collapsed them into one location, because two locations would have
    meant two checks for one chest and, far worse, a progression item on 113 released the moment the player
    opened 108 in an earlier region.

    SPLIT AGAIN 2026-09-15 (ADDENDUM 224, player: "Split 108 and 113"). ADDENDUM 218 took the flag array out
    of identity entirely: 108 is in room 171 and 113 in room 172, they hold different berries, and
    (room, berry) names each one exactly. The reason for the merge is gone, so the merge is gone -- and the
    danger it guarded against is gone with it, because opening 108 can no longer credit 113."""

    def test_they_are_two_locations_again(self) -> None:
        self.assertNotEqual(locations.CHEST_ID_TO_LOCATION[108], locations.CHEST_ID_TO_LOCATION[113])

    def test_every_chest_now_has_its_own_location(self) -> None:
        """The gap used to be exactly 1, and that 1 was this pair. There is no gap now."""
        self.assertEqual(locations.CHEST_COVERED_CHEST_COUNT - locations.CHEST_LOCATION_COUNT, 0)
        self.assertEqual(locations.CHEST_COVERED_CHEST_COUNT, 95)
        self.assertEqual(locations.CHEST_LOCATION_COUNT, 95)

    def test_each_is_filed_in_its_own_rooms_region(self) -> None:
        """Under the merge, the location had to sit in the EARLIER region, because the shared bit could be set
        from either room. Split, each one is filed where its own chest actually is."""
        for chest_id in (108, 113):
            name = locations.CHEST_ID_TO_LOCATION[chest_id]
            self.assertEqual(locations.CHEST_LOCATION_TO_REGION[name],
                             chest_regions.CHEST_TO_REGION[chest_id], chest_id)

    def test_opening_one_cannot_credit_the_other(self) -> None:
        """The real safety property the merge existed to provide, now provided by the berry instead: the two
        chests hold DIFFERENT berries in DIFFERENT rooms, so neither lookup can ever return the other."""
        from ..game_data import chest_berries

        berry_108, _ = chest_berries.CHEST_BERRY_ASSIGNMENT[108]
        berry_113, _ = chest_berries.CHEST_BERRY_ASSIGNMENT[113]
        self.assertEqual(chest_berries.chest_for(171, berry_108), 108)
        self.assertEqual(chest_berries.chest_for(172, berry_113), 113)
        self.assertNotEqual(chest_berries.chest_for(171, berry_108),
                            chest_berries.chest_for(172, berry_113))

    def test_the_client_and_the_world_agree_on_both_names(self) -> None:
        for chest_id in (108, 113):
            self.assertEqual(rc.CHEST_ID_TO_LOCATION[chest_id], locations.CHEST_ID_TO_LOCATION[chest_id])


class TestTheClientAndTheWorldAgree(unittest.TestCase):
    """ram_client.py cannot import locations.py, so the name format is genuinely duplicated. A location name
    IS its identity to the server: one character of drift and every chest check is silently rejected."""

    def test_the_id_to_name_tables_are_identical(self) -> None:
        self.assertEqual(rc.CHEST_ID_TO_LOCATION, locations.CHEST_ID_TO_LOCATION)

    def test_the_name_lists_are_identical(self) -> None:
        self.assertEqual(sorted(rc.CHEST_LOCATION_NAMES), sorted(locations.CHEST_LOCATION_NAMES))

    def test_every_client_name_exists_in_the_datapackage(self) -> None:
        for name in rc.CHEST_LOCATION_NAMES:
            self.assertIn(name, locations.LOCATION_TABLE)

    def test_the_name_carries_chest_and_room_not_region(self) -> None:
        """Both halves come from the ISO and never move. The region deliberately does NOT appear: regions are
        a logic decision this project has already revised more than once (ADDENDUM 169 re-bucketed five
        locations), and a location name is frozen forever by its id."""
        # UPDATED 2026-09-16 (ADDENDUM 242). This used to find the first UNNAMED chest and pin its generated
        # form. Chest 23 was the last one, and naming it "Cipher Lab Krane Chest" means EVERY AP chest now
        # carries a real name -- so that search raised StopIteration rather than failing an assertion.
        #
        # The generated form is still the fallback for any chest added without a name, so it is pinned
        # DIRECTLY now instead of through a live example that no longer exists.
        self.assertEqual(locations.chest_location_name_for_ids((999,), 123), "Chest 999 (Room 123)")
        self.assertEqual(
            [chest for chest in sorted(locations.CHEST_ID_TO_LOCATION)
             if chest_names.chest_location_name_override((chest,)) is None
             and "+" not in locations.CHEST_ID_TO_LOCATION[chest]],
            [], "every AP chest is named now -- if one is unnamed again, name it rather than relaxing this")
        self.assertEqual(locations.CHEST_ID_TO_LOCATION[40], "Realgam Tower Crossroads Chest")
        self.assertEqual(locations.CHEST_ID_TO_LOCATION[3], "Player's Room Chest")

        # NARROWED 2026-09-15 (ADDENDUM 219). The original rule was that a chest name never contains its
        # region, because regions are a logic decision this project has revised more than once and a name is
        # frozen forever by its id -- so an encoded region can become a lie the table has to keep telling.
        #
        # That rule cannot survive the player naming the chests themselves: they named them after the places
        # ("Cipher Lab Left Door Chest 1"), which is the whole point of a human label. The risk is accepted
        # deliberately and is smaller than it looks -- these are PLACE names, not graph-node names, and a
        # re-bucketing moves which region node a chest belongs to without moving the chest.
        #
        # So the rule is kept exactly where it still applies: names this project GENERATES must never encode a
        # region, because those are the ones a future edit could produce automatically and without thought.
        for chest_id, name in locations.CHEST_ID_TO_LOCATION.items():
            if chest_names.chest_location_name_override((chest_id,)) is not None:
                continue   # a name the player chose -- exempt, see above
            region = locations.CHEST_LOCATION_TO_REGION.get(name)
            if region is not None:
                self.assertNotIn(region, name)


class TestEachChestIsFiledWhereTheIsoPutsIt(unittest.TestCase):
    def test_every_chest_location_sits_in_its_own_rooms_region(self) -> None:
        by_id = {c["chest"]: c for c in chest_table.CHESTS}
        for chest_id, name in locations.CHEST_ID_TO_LOCATION.items():
            expected = chest_regions.ROOM_TO_REGION[by_id[chest_id]["room"]]
            if chest_id == 113:
                continue  # the shared-flag pair is filed with 108 on purpose -- see TestTheSharedFlagPair
            self.assertEqual(locations.CHEST_LOCATION_TO_REGION[name], expected, chest_id)

    def test_every_region_it_uses_is_a_real_graph_node(self) -> None:
        for region in set(locations.CHEST_LOCATION_TO_REGION.values()):
            self.assertIn(region, regions.REGION_NAMES)

    def test_chests_are_spread_across_the_map_not_pooled(self) -> None:
        """The whole point of the migration. A single bucket would mean the fill learned nothing."""
        self.assertGreater(len(set(locations.CHEST_LOCATION_TO_REGION.values())), 10)


class TestTheItemGates(PokemonXDTestBase):
    options = {"randomize_chests": True, "key_item_shuffle": True}

    def test_the_id_card_chest_needs_the_card_on_top_of_reaching_the_room(self) -> None:
        """The player's own rule: "27 locked behind ID card".

        RESHAPED 2026-09-13 (ADDENDUM 179): the ID Card now ships packaged with the Data ROM, and the Data ROM is
        the chain's second link -- so "collect the whole chain, the chest is still shut" is no longer possible.
        The gate is probed the other way instead, which tests the same thing: one link in (the Machine Part
        only) the chest is shut, and it opens exactly when the packaged item arrives."""
        name = locations.CHEST_ID_TO_LOCATION[27]
        self.collect_key_item_chain(1)   # the Machine Part -- not the packaged card
        self.assertFalse(self.can_reach_location(name))
        self.collect_key_item_chain(2)   # + Data ROM & ID Card
        self.assertTrue(self.can_reach_location(name))

    def test_both_gated_chests_are_real_ap_locations(self) -> None:
        """A gate on a chest that is not a location is a silently dead rule."""
        for chest_id in chest_regions.CHEST_ITEM_GATES:
            self.assertIn(chest_id, locations.CHEST_ID_TO_LOCATION, chest_id)


class TestTheGatesNeverNameAnUncreatedItem(PokemonXDTestBase):
    """ADDENDUM 168's rule, and the reason it needs its own test here: `all_state` never holds an item that was
    never created, so a rule naming one makes its location unreachable forever. On a region edge that announces
    itself by taking the back half of the map with it; on a LOCATION it is silent."""

    options = {"randomize_chests": True, "key_item_shuffle": False}

    def test_the_id_card_chest_is_reachable_with_key_item_shuffle_off(self) -> None:
        """With shuffle off the card sits in its vanilla chest, so reaching the room already implies holding
        it and the requirement is not merely redundant but fatal."""
        self.assertTrue(self.can_reach_location(locations.CHEST_ID_TO_LOCATION[27]))


class TestTheRoboKyogreChest(PokemonXDTestBase):
    options = {"randomize_chests": True, "robo_kyogre_parts_unlock_citadark": False}

    def test_the_master_ball_chest_needs_the_story_chain_even_with_no_parts_in_the_pool(self) -> None:
        """REWRITTEN 2026-09-14 (ADDENDUM 186, player: "Kyogre parts should be IRRELEVANT to any logic except
        being need for citadark/the goal").

        This used to assert the chest was reachable on an EMPTY state whenever the Parts option was off, which
        was true of the old rule and wrong about the game: the Master Ball chest opens on the story transition
        0x6C->0x6E, at the end of the Cipher Key Lair, whether or not any Parts exist. The chest is now gated
        on reaching Citadark Isle -- the region that same transition opens -- so with the Parts option off it
        is reachable exactly when the ordinary key-item chain has been walked, and not before."""
        name = locations.CHEST_ID_TO_LOCATION[2]
        self.assertFalse(self.can_reach_location(name),
                         "the Master Ball chest is not open at the start of the game")
        self.collect_key_item_chain()
        self.assertTrue(self.multiworld.state.can_reach("Citadark Isle", player=self.player))
        self.assertTrue(self.can_reach_location(name),
                        "with no Parts in the pool, the chain alone must be enough")

    def test_no_rule_anywhere_names_the_robo_kyogre_part_except_the_citadark_edge(self) -> None:
        """The point of ADDENDUM 186, pinned as a source fact rather than a behaviour: the Parts are a key to
        one door. A second rule naming them is the drift this exists to stop."""
        import pathlib

        from .. import items
        from ..game_data import chest_names, chest_regions

        for required in chest_regions.CHEST_ITEM_GATES.values():
            self.assertNotIn(items.MACGUFFIN_ITEM_NAME, required)
        rules_src = (pathlib.Path(__file__).resolve().parent.parent / "rules.py").read_text(encoding="utf-8")
        naming = [line.strip() for line in rules_src.splitlines()
                  if "MACGUFFIN_ITEM_NAME" in line and not line.strip().startswith("#")]
        # The only survivor is the assertion that keeps it out of the chest gates.
        self.assertTrue(all("assert" in line or "required" in line for line in naming), naming)


class TestChestsOffEntirely(PokemonXDTestBase):
    options = {"randomize_chests": False}

    def test_no_chest_locations_are_created(self) -> None:
        created = {loc.name for loc in self.multiworld.get_locations(1)}
        for name in locations.CHEST_LOCATION_NAMES:
            self.assertNotIn(name, created)


if __name__ == "__main__":
    unittest.main()
