"""ADDENDUM 246 (2026-09-16) -- chest 98 is ONBS 3F's first chest, and the ONBS chests name the ROM.

Player: "Pickup PDA is in hq lab right by chest 3, not pyrite town - it also didn't fire on my latest seed."
Then: "Go ahead with the rename. ... Since it's onbs, it's behind data rom/id card."

THE LABEL WAS ON THE WRONG CHEST FOR TWO ADDENDA. ADDENDUM 200 renamed chest 98 to "Pickup PDA" on an explicit
instruction. ADDENDUM 219's room list from the same player called it "CNBS 3F Chest 1". The disagreement was
pinned in favour of 200 because a rename invalidates in-flight seeds -- and the ISO, which nobody asked, had
the answer the whole time: chest 98 is in ROOM 110, beside chest 99, and rooms 109/110 are ONBS.

THE HQ LAB CANNOT HOLD A PDA LOCATION, which is the fact that settles it rather than merely supporting it.
The lab's rooms (138-143) contain exactly THREE treasure boxes in the 115-box table: chest 1 (room 143), chest
2 (room 142) and chest 3 (room 138). Room 138 holds chest 3 and nothing else. So whatever the player picks up
beside chest 3 is not a randomizable box, has no AP location, and never did.

THE GATE IS BELT AND BRACES AND THE TEST SAYS SO. The ONBS chests are already behind the Data ROM through
their region -- `Pyrite Town (ONBS)` hangs off `Poke Spots`, and the `Pyrite Town -> Poke Spots` edge has
required the ROM since ADDENDUM 240 moved it off plain Pyrite. Both halves are checked here: that the
requirement is really inherited today, AND that each chest now names it directly, so a future re-parenting of
the region cannot quietly drop it the way ADDENDUM 240 had to fix by hand."""
import unittest

from . import PokemonXDTestBase
from .. import locations, ram_client as rc, regions as world_regions
from ..game_data import chest_names, chest_regions, chest_table

ONBS_CHESTS = (98, 99, 100)


class TestTheIsoWasAlwaysTheTieBreaker(unittest.TestCase):
    def test_chest_98_is_in_room_110_with_chest_99(self) -> None:
        room = {c["chest"]: c["room"] for c in chest_table.CHESTS}
        self.assertEqual(110, room[98])
        self.assertEqual(110, room[99])
        self.assertEqual(109, room[100])

    def test_rooms_109_and_110_are_onbs(self) -> None:
        self.assertEqual("Pyrite Town (ONBS)", chest_regions.ROOM_TO_REGION[109])
        self.assertEqual("Pyrite Town (ONBS)", chest_regions.ROOM_TO_REGION[110])

    def test_the_hq_lab_holds_exactly_three_boxes(self) -> None:
        """The fact that makes "Pickup PDA in the HQ Lab" impossible rather than merely unlikely."""
        lab_rooms = {room for room, region in chest_regions.ROOM_TO_REGION.items()
                     if region == "Pokemon HQ Lab"}
        boxes = sorted(c["chest"] for c in chest_table.CHESTS if c["room"] in lab_rooms)
        self.assertEqual([1, 2, 3], boxes)

    def test_room_138_holds_only_chest_3(self) -> None:
        """The player's own reference point -- "right by chest 3"."""
        self.assertEqual([3], sorted(c["chest"] for c in chest_table.CHESTS if c["room"] == 138))


class TestTheRename(unittest.TestCase):
    def test_both_sides_spell_the_new_names_identically(self) -> None:
        """The ADDENDUM 200 contract: locations.py and ram_client.py build the string independently."""
        for chest, name in ((98, "ONBS 3F Chest 1"), (99, "ONBS 3F Chest 2"), (100, "ONBS 2F Chest")):
            self.assertEqual(name, chest_names.chest_location_name_override((chest,)))
            self.assertEqual(name, locations.CHEST_ID_TO_LOCATION[chest])
            self.assertEqual(name, rc.CHEST_ID_TO_LOCATION[chest])

    def test_the_ids_were_carried_and_the_old_labels_are_tombstones(self) -> None:
        self.assertEqual(1510, locations.LOCATION_TABLE["ONBS 3F Chest 1"].id_offset)
        self.assertEqual(1511, locations.LOCATION_TABLE["ONBS 3F Chest 2"].id_offset)
        self.assertEqual(1510, locations._FROZEN_LOCATION_OFFSETS["Pickup PDA"])
        self.assertEqual(1511, locations._FROZEN_LOCATION_OFFSETS["ONBS 3F Chest"])
        self.assertNotIn("Pickup PDA", locations.LOCATION_TABLE)
        self.assertNotIn("ONBS 3F Chest", locations.LOCATION_TABLE)

    def test_no_live_name_anywhere_still_says_pda(self) -> None:
        self.assertFalse([n for n in locations.LOCATION_TABLE if "PDA" in n])
        self.assertFalse([n for n in rc.CHEST_LOCATION_NAMES if "PDA" in n])


class TestTheGateIsNamedAndInherited(unittest.TestCase):
    def test_every_onbs_chest_names_the_rom_itself(self) -> None:
        for chest in ONBS_CHESTS:
            self.assertEqual(("Data ROM", "ID Card"), chest_regions.CHEST_ITEM_GATES.get(chest),
                             f"chest {chest}")

    def test_the_region_path_still_carries_it_too(self) -> None:
        """Both belts. If this edge ever moves, the explicit gate above is what survives."""
        self.assertIn(("Pyrite Town", "Poke Spots", ("Data ROM",)), world_regions.REGION_EDGES)
        self.assertIn(("Poke Spots", "Pyrite Town (ONBS)", ()), world_regions.REGION_EDGES)


class TestAgainstARealWorld(PokemonXDTestBase):
    options = {"key_item_shuffle": True}

    def _state(self, held):
        from BaseClasses import CollectionState
        state = CollectionState(self.multiworld)
        for name in held:
            state.collect(self.multiworld.worlds[1].create_item(name), prevent_sweep=True)
        state.sweep_for_advancements()
        return state

    def _onbs_locations(self):
        names = {locations.CHEST_ID_TO_LOCATION[c] for c in ONBS_CHESTS}
        return [l for l in self.multiworld.get_locations(1) if l.name in names]

    def test_all_three_exist_under_their_new_names(self) -> None:
        self.assertEqual(3, len(self._onbs_locations()))

    def test_none_of_them_open_without_the_rom(self) -> None:
        without = self._state(["Machine Part"])
        for location in self._onbs_locations():
            self.assertFalse(location.can_reach(without), location.name)

    def test_all_of_them_open_with_it(self) -> None:
        with_rom = self._state(["Machine Part", "Data ROM & ID Card"])
        for location in self._onbs_locations():
            self.assertTrue(location.can_reach(with_rom), location.name)


class TestTheGateSurvivesTheRegionMoving(PokemonXDTestBase):
    """The reason the explicit gate is worth its three lines. Re-parent the ONBS region onto plain Pyrite --
    the exact shape of the ADDENDUM 240 mistake -- and the chests must STILL need the ROM."""

    options = {"key_item_shuffle": True}

    def test_reparenting_onbs_onto_plain_pyrite_does_not_free_the_chests(self) -> None:
        from BaseClasses import CollectionState

        onbs = self.multiworld.get_region("Pyrite Town (ONBS)", 1)
        pyrite = self.multiworld.get_region("Pyrite Town", 1)
        pyrite.connect(onbs, name="TEST re-parent")   # a second, unconditional way in

        state = CollectionState(self.multiworld)
        state.collect(self.multiworld.worlds[1].create_item("Machine Part"), prevent_sweep=True)
        state.sweep_for_advancements()
        self.assertTrue(onbs.can_reach(state), "the test's own premise -- the region is now reachable")

        names = {locations.CHEST_ID_TO_LOCATION[c] for c in ONBS_CHESTS}
        for location in self.multiworld.get_locations(1):
            if location.name in names:
                self.assertFalse(location.can_reach(state),
                                 f"{location.name} lost its Data ROM requirement with the region")


class TestTheBackfillNotice(unittest.TestCase):
    """ADDENDUM 246's second half. A chest opened before the client was watching is lost in silence -- the
    first sighting of its berry is a baseline, not a pickup. These tests pin BOTH halves of the answer: that
    the tracker now notices, and that it still refuses to guess which chest it was."""

    BLOCK = 0x80479000

    def setUp(self):
        self.bag: "dict[int, int]" = {}
        self._find = rc.find_item_quantity
        self._clear = rc.clear_item
        rc.find_item_quantity = lambda base, slots, item_id: self.bag.get(item_id, 0)

        def fake_clear(base, slots, item_id):
            self.bag[item_id] = 0
            return True

        rc.clear_item = fake_clear

    def tearDown(self):
        rc.find_item_quantity = self._find
        rc.clear_item = self._clear

    def settle(self, tracker, room, already=frozenset(), ticks=3):
        # ADDENDUM 262: the tracker's windows are DURATIONS now, so this has to advance a clock -- a tight
        # loop takes no real time at all. One second per poll is exactly POLL_INTERVAL_INGAME, so every
        # expectation below is unchanged in meaning. Kept on the tracker so repeated calls continue.
        fake = getattr(tracker, "_test_clock", None)
        if fake is None:
            fake = {"t": 0.0}
            tracker._test_clock = fake
            tracker.clock = lambda: fake["t"]
        out = []
        for _ in range(ticks):
            out.extend(tracker.poll(self.BLOCK, room_id=room, already_checked=already))
            fake["t"] += 1.0
        return out

    def _berry_of(self, chest):
        from ..game_data import chest_berries
        return chest_berries.CHEST_BERRY_ASSIGNMENT[chest][0]

    def test_a_clean_start_says_nothing(self) -> None:
        tracker = rc.ChestBerryTracker()
        self.settle(tracker, 138)
        self.assertEqual({}, tracker.baseline_carried)
        self.assertEqual([], tracker.backfill_notice())

    def test_a_berry_already_held_is_recorded_not_credited(self) -> None:
        """The exact HQ Lab case: chest 3 opened before the client was running."""
        berry = self._berry_of(3)
        self.bag[berry] = 1
        tracker = rc.ChestBerryTracker()
        self.assertEqual([], self.settle(tracker, 138), "a baseline may never fire a check")
        self.assertEqual({berry: 1}, tracker.baseline_carried)

    def test_the_notice_names_candidates_and_the_fix(self) -> None:
        berry = self._berry_of(3)
        self.bag[berry] = 1
        tracker = rc.ChestBerryTracker()
        self.settle(tracker, 138)
        lines = tracker.backfill_notice()
        self.assertTrue(lines)
        blob = " ".join(lines)
        self.assertIn("!checked", blob)
        self.assertIn("Candidates", blob)
        self.assertIn("Player's Room Chest", blob)

    def test_it_refuses_to_narrow_to_one_chest(self) -> None:
        """Seven berries cover 115 chests. A berry in the Bag carries no room, and the room is the identity,
        so the candidate list is genuinely 17 wide and is never trimmed to look confident."""
        berry = self._berry_of(3)
        self.bag[berry] = 1
        tracker = rc.ChestBerryTracker()
        self.settle(tracker, 138)
        candidates = tracker.backfill_candidates()
        self.assertGreater(len(candidates), 1)
        self.assertIn(rc.CHEST_ID_TO_LOCATION[3], candidates)

    def test_already_checked_locations_are_left_out(self) -> None:
        berry = self._berry_of(3)
        self.bag[berry] = 1
        tracker = rc.ChestBerryTracker()
        self.settle(tracker, 138)
        mine = rc.CHEST_ID_TO_LOCATION[3]
        self.assertNotIn(mine, tracker.backfill_candidates(frozenset({mine})))

    def test_the_notice_does_not_break_normal_crediting_afterwards(self) -> None:
        """The one thing that must not regress: the player's standing rule that checks fire."""
        berry = self._berry_of(3)
        self.bag[berry] = 1
        tracker = rc.ChestBerryTracker()
        self.settle(tracker, 138)
        # The carried berry is NOT cleared -- nothing was credited, so there is nothing to clear, and the
        # baseline stays at 1. A later real pickup takes it to 2, which is the rise the tracker watches for.
        self.bag[berry] = 2
        self.assertEqual([rc.CHEST_ID_TO_LOCATION[3]], self.settle(tracker, 138))

    def test_describe_mentions_it(self) -> None:
        berry = self._berry_of(3)
        self.bag[berry] = 1
        tracker = rc.ChestBerryTracker()
        self.settle(tracker, 138)
        self.assertTrue([l for l in tracker.describe() if "already held at first poll" in l])


if __name__ == "__main__":
    unittest.main()
