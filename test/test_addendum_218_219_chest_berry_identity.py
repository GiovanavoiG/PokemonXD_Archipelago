"""ADDENDA 218 and 219 (2026-09-15) -- the berry IS the chest, and the player's own chest names.

Player, verbatim:
    "Chests are completely broken. Use our recent probes and dumps to derive another system that is 100%
     accurate - place unique berries in the chest like the plan was before, if needed. The shops do not need
     every dummy berry."
    "Below is a list of room IDs, followed by an area descriptor, then chests and suggested chest names. ONLY
     use this to rename chests & reaffirm our logic of what's required."

The tests that matter here are about the INVARIANT and the SEAM, not about the assignment algorithm: what can
go wrong is two chests in a room sharing a berry, a berry shared with the shops or the item pool, a location
id moving under a rename, or the client and the world disagreeing about a name.
"""
import unittest

from .. import items, locations, ram_client as rc
from ..game_data import chest_berries, chest_names, chest_table


class TestTheOneInvariant(unittest.TestCase):
    """(room, berry) must identify exactly one chest. Everything else in ADDENDUM 218 rests on this."""

    def test_no_two_chests_in_a_room_share_a_berry(self):
        by_room: "dict[int, list[int]]" = {}
        for entry in chest_table.CHESTS:
            by_room.setdefault(entry["room"], []).append(entry["chest"])
        for room, chests in by_room.items():
            berries = [chest_berries.CHEST_BERRY_ASSIGNMENT[c][0] for c in chests]
            self.assertEqual(len(berries), len(set(berries)),
                             f"room {room} has two chests with the same berry: {chests}")

    def test_every_chest_has_a_berry(self):
        self.assertEqual(len(chest_berries.CHEST_BERRY_ASSIGNMENT), len(chest_table.CHESTS))

    def test_the_lookup_is_exact_for_every_chest_in_the_game(self):
        """The real end-to-end property: for each chest, its own (room, berry) resolves back to it."""
        for entry in chest_table.CHESTS:
            chest = entry["chest"]
            berry, _qty = chest_berries.CHEST_BERRY_ASSIGNMENT[chest]
            self.assertEqual(chest_berries.chest_for(entry["room"], berry), chest)

    def test_the_lookup_never_guesses(self):
        self.assertIsNone(chest_berries.chest_for(None, 161))
        self.assertIsNone(chest_berries.chest_for(8, None))
        self.assertIsNone(chest_berries.chest_for(99999, 161), "a room with no chests")
        self.assertIsNone(chest_berries.chest_for(8, 133), "a berry no chest in room 8 holds")

    def test_the_assignment_is_deterministic(self):
        """The client identifies a chest without being handed the seed's table, so the assignment must be a
        pure function of fixed data -- the same property the shop rotation has."""
        import importlib

        again = importlib.reload(chest_berries)
        self.assertEqual(again.CHEST_BERRY_ASSIGNMENT, chest_berries.CHEST_BERRY_ASSIGNMENT)


class TestTheBerryNamespaceIsDisjoint(unittest.TestCase):
    """Three sets of berries exist and a collision between any two is a wrong check."""

    def test_no_chest_berry_is_a_shop_berry(self):
        self.assertFalse(set(items.CHEST_BERRY_IDS) & set(items.USELESS_BERRY_IDS),
                         "a shop purchase would register as a chest opening")

    def test_no_chest_berry_is_in_the_item_pool(self):
        pool = {data.game_item_id for data in items.BERRY_ITEMS.values()}
        self.assertFalse(set(items.CHEST_BERRY_IDS) & pool,
                         "an Archipelago-delivered berry would register as a chest opening")

    def test_enough_berries_for_the_biggest_room(self):
        biggest = max(len(chest_berries.chests_in_room(r))
                      for r in set(chest_berries.CHEST_TO_ROOM.values()))
        self.assertLessEqual(biggest, len(items.CHEST_BERRY_IDS))

    def test_the_historical_dummy_is_still_one_of_them(self):
        """An ISO patched before this addendum planted Rabuta in every chest. Keeping it in the set means
        such a save is still understood rather than producing berries the client ignores."""
        self.assertIn(items.CHEST_DUMMY_GAME_ITEM_ID, items.CHEST_BERRY_IDS)

    def test_every_chest_berry_is_renamed_in_game(self):
        for berry in items.CHEST_BERRY_IDS:
            self.assertIn(berry, items.AP_ITEM_RENAME_TARGET_NAMES)


class TestTheTrackerCreditsExactlyOneChest(unittest.TestCase):
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

    # ADDENDUM 262: both of this tracker's windows are DURATIONS now (`_CONFIRM_SECONDS` and
    # `_MAX_PENDING_SECONDS`), so these sequences have to advance a clock -- a tight loop takes no real time
    # at all. One second per poll is exactly POLL_INTERVAL_INGAME, so every expectation below is unchanged in
    # meaning and these tests now pin the real 1s cadence instead of a bare poll count. The clock is kept ON
    # the tracker so successive `settle` calls against the same tracker carry on rather than freezing.
    @staticmethod
    def _clock_for(tracker):
        fake = getattr(tracker, "_test_clock", None)
        if fake is None:
            fake = {"t": 0.0}
            tracker._test_clock = fake
            tracker.clock = lambda: fake["t"]
        return fake

    def settle(self, tracker, room, already=frozenset(), ticks=3):
        fake = self._clock_for(tracker)
        out: "list[str]" = []
        for _ in range(ticks):
            out.extend(tracker.poll(self.BLOCK, room_id=room, already_checked=already))
            fake["t"] += 1.0
        return out

    def test_the_first_poll_is_a_baseline_not_a_pickup(self):
        self.bag[161] = 5
        tracker = rc.ChestBerryTracker()
        self.assertEqual(self.settle(tracker, 143), [])

    def test_a_pickup_credits_the_chest_that_berry_means_in_that_room(self):
        tracker = rc.ChestBerryTracker()
        self.settle(tracker, 8)                       # baseline
        berry, _ = chest_berries.CHEST_BERRY_ASSIGNMENT[17]
        self.bag[berry] = 1
        names = self.settle(tracker, 8)
        self.assertEqual(names, [rc.CHEST_ID_TO_LOCATION[17]])

    def test_the_same_berry_in_a_different_room_credits_a_different_chest(self):
        """The heart of the design: one berry, many chests, disambiguated entirely by room."""
        berry, _ = chest_berries.CHEST_BERRY_ASSIGNMENT[17]
        other_room = next(r for r in set(chest_berries.CHEST_TO_ROOM.values())
                          if r != 8 and berry in chest_berries.berries_used_in_room(r))
        expected = chest_berries.chest_for(other_room, berry)
        tracker = rc.ChestBerryTracker()
        self.settle(tracker, other_room)
        self.bag[berry] = 1
        names = self.settle(tracker, other_room)
        self.assertEqual(names, [rc.CHEST_ID_TO_LOCATION[expected]])

    def test_an_unreadable_room_holds_the_pickup_rather_than_dropping_it(self):
        """The player's standing rule is that checks must not fail to fire. This honours it by DEFERRING --
        which is different from guessing, and is the whole reason nothing has to be guessed."""
        tracker = rc.ChestBerryTracker()
        self.settle(tracker, 8)
        berry, _ = chest_berries.CHEST_BERRY_ASSIGNMENT[17]
        self.bag[berry] = 1
        self.assertEqual(self.settle(tracker, None), [], "nothing may be credited without a room")
        self.assertTrue(tracker.pending, "the pickup must be held, not lost")
        names = self.settle(tracker, 8)
        self.assertEqual(names, [rc.CHEST_ID_TO_LOCATION[17]])
        self.assertFalse(tracker.pending)

    def test_a_berry_in_a_room_holding_no_such_chest_credits_nothing(self):
        """The failure this redesign exists to remove: crediting SOMETHING rather than the right thing. A
        wrong check releases another player's item and cannot be taken back.

        RETARGETED BY ADDENDUM 345. The no-credit half is the guarantee and is unchanged. What changed is
        what happens to the berry: it used to be counted and discarded on the spot, which is how a chest
        opened on the way out of a room went missing in silence. It is now HELD, and reported by name if it
        still cannot be placed. This test asserts the part that matters -- nothing is credited -- and that
        the berry is still in hand rather than gone."""
        tracker = rc.ChestBerryTracker()
        self.settle(tracker, 8)
        foreign = next(b for b in items.CHEST_BERRY_IDS
                       if b not in chest_berries.berries_used_in_room(8))
        self.bag[foreign] = 1
        self.assertEqual(self.settle(tracker, 8), [])
        self.assertEqual(tracker.credits, 0)
        self.assertTrue(tracker.pending or tracker.berries_in_a_room_with_no_such_chest,
                        "it must be held or accounted for, never silently gone")

    def test_the_berry_is_cleared_after_crediting(self):
        """ShopPurchaseTracker's pattern. A berry shared by ~16 chests cannot be tracked by a rising total."""
        tracker = rc.ChestBerryTracker()
        self.settle(tracker, 8)
        berry, _ = chest_berries.CHEST_BERRY_ASSIGNMENT[17]
        self.bag[berry] = 1
        self.settle(tracker, 8)
        self.assertEqual(self.bag[berry], 0)

    def test_a_second_chest_with_the_same_berry_still_credits_after_the_clear(self):
        berry, _ = chest_berries.CHEST_BERRY_ASSIGNMENT[17]
        other_room = next(r for r in set(chest_berries.CHEST_TO_ROOM.values())
                          if r != 8 and berry in chest_berries.berries_used_in_room(r))
        tracker = rc.ChestBerryTracker()
        self.settle(tracker, 8)
        self.bag[berry] = 1
        first = self.settle(tracker, 8)
        self.bag[berry] = 1
        second = self.settle(tracker, other_room)
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertNotEqual(first, second)

    def test_an_already_checked_chest_is_not_resent(self):
        tracker = rc.ChestBerryTracker()
        self.settle(tracker, 8)
        berry, _ = chest_berries.CHEST_BERRY_ASSIGNMENT[17]
        self.bag[berry] = 1
        self.assertEqual(self.settle(tracker, 8, already=frozenset({rc.CHEST_ID_TO_LOCATION[17]})), [])

    def test_a_decrease_never_manufactures_a_pickup(self):
        """The player can eat, sell or toss a berry. None of that is a chest."""
        self.bag[161] = 5
        tracker = rc.ChestBerryTracker()
        self.settle(tracker, 143)
        self.bag[161] = 2
        self.assertEqual(self.settle(tracker, 143), [])

    def test_it_waits_for_the_confirm_streak(self):
        tracker = rc.ChestBerryTracker()
        self.settle(tracker, 8)
        berry, _ = chest_berries.CHEST_BERRY_ASSIGNMENT[17]
        self.bag[berry] = 1
        self.assertEqual(tracker.poll(self.BLOCK, room_id=8, already_checked=frozenset()), [],
                         "a single rise must not be believed -- ADDENDUM 98/99's debounce")

    def test_no_flag_bit_is_consulted_anywhere(self):
        """The point of the redesign, asserted rather than assumed. If identity ever reaches for the flag
        array again, this is what notices."""
        import inspect

        source = inspect.getsource(rc.ChestBerryTracker)
        for forbidden in ("flag_bit_position", "chest_band", "newly_set_positions", "learned_positions"):
            self.assertNotIn(forbidden, source)


class TestAPendingPickupRemembersWhereItHappened(unittest.TestCase):
    """ADDENDUM 226. As first written, `pending` recorded THAT a berry appeared and never WHERE, so a pickup
    made while the room was unreadable was resolved against whatever room came up later. That is the
    credit-the-wrong-chest failure ADDENDUM 218 exists to remove, reintroduced by the back door."""

    BLOCK = 0x80479000

    def setUp(self):
        self.bag = {}
        self._find, self._clear = rc.find_item_quantity, rc.clear_item
        rc.find_item_quantity = lambda base, slots, item_id: self.bag.get(item_id, 0)

        def fake_clear(base, slots, item_id):
            self.bag[item_id] = 0
            return True

        rc.clear_item = fake_clear

    def tearDown(self):
        rc.find_item_quantity, rc.clear_item = self._find, self._clear

    # ADDENDUM 262: both of this tracker's windows are DURATIONS now (`_CONFIRM_SECONDS` and
    # `_MAX_PENDING_SECONDS`), so these sequences have to advance a clock -- a tight loop takes no real time
    # at all. One second per poll is exactly POLL_INTERVAL_INGAME, so every expectation below is unchanged in
    # meaning and these tests now pin the real 1s cadence instead of a bare poll count. The clock is kept ON
    # the tracker so successive `settle` calls against the same tracker carry on rather than freezing.
    @staticmethod
    def _clock_for(tracker):
        fake = getattr(tracker, "_test_clock", None)
        if fake is None:
            fake = {"t": 0.0}
            tracker._test_clock = fake
            tracker.clock = lambda: fake["t"]
        return fake

    def settle(self, tracker, room, ticks=3):
        fake = self._clock_for(tracker)
        out = []
        for _ in range(ticks):
            out.extend(tracker.poll(self.BLOCK, room_id=room, already_checked=frozenset()))
            fake["t"] += 1.0
        return out

    def _berry_in_two_rooms(self):
        """A berry used by chests in two different rooms -- the setup the old code got wrong."""
        for chest, (berry, _q) in chest_berries.CHEST_BERRY_ASSIGNMENT.items():
            room = chest_berries.CHEST_TO_ROOM[chest]
            for other, (berry2, _q2) in chest_berries.CHEST_BERRY_ASSIGNMENT.items():
                if berry2 == berry and chest_berries.CHEST_TO_ROOM[other] != room:
                    if chest in rc.CHEST_ID_TO_LOCATION and other in rc.CHEST_ID_TO_LOCATION:
                        return berry, room, chest, chest_berries.CHEST_TO_ROOM[other], other
        raise unittest.SkipTest("no berry shared across two AP-chest rooms")

    def test_a_pickup_is_credited_to_the_room_it_happened_in(self):
        berry, room_a, chest_a, room_b, _chest_b = self._berry_in_two_rooms()
        tracker = rc.ChestBerryTracker()
        self.settle(tracker, room_a)
        self.bag[berry] = 1
        names = self.settle(tracker, room_a)
        self.assertEqual(names, [rc.CHEST_ID_TO_LOCATION[chest_a]])
        # And walking to the other room afterwards must not credit anything more.
        self.assertEqual(self.settle(tracker, room_b), [])

    def test_a_pickup_made_with_no_room_does_not_credit_a_later_unrelated_room(self):
        """The precise old bug: pick up with the room unreadable, then stand somewhere else that happens to
        use the same berry. Abandoning is the recoverable direction -- a missed check can be re-sent, a wrong
        one has already released another player's item."""
        berry, _room_a, _chest_a, room_b, chest_b = self._berry_in_two_rooms()
        tracker = rc.ChestBerryTracker()
        self.settle(tracker, None)
        self.bag[berry] = 1
        self.settle(tracker, None, ticks=8)     # never readable, long enough to expire
        self.assertGreater(tracker.abandoned_pickups, 0)
        self.assertEqual(self.settle(tracker, room_b), [],
                         "an expired pickup must not credit the room the player wandered into")
        self.assertEqual(tracker.credits, 0)

    def test_a_pickup_with_no_room_still_credits_if_the_room_resolves_promptly(self):
        """The check must not be lost in the ordinary case -- a room unreadable for a poll or two around a
        transition is normal, and the player is still standing where they opened the chest."""
        berry, room_a, chest_a, _room_b, _chest_b = self._berry_in_two_rooms()
        tracker = rc.ChestBerryTracker()
        self.settle(tracker, None)
        self.bag[berry] = 1
        self.settle(tracker, None, ticks=2)
        names = self.settle(tracker, room_a)
        self.assertEqual(names, [rc.CHEST_ID_TO_LOCATION[chest_a]])
        self.assertEqual(tracker.abandoned_pickups, 0)

    def test_a_berry_in_a_room_with_no_such_chest_never_credits_a_room_entered_later(self):
        """It used to be held forever "in case the next poll names the real room", which meant it credited the
        first matching room the player ever walked into, whenever that was.

        RETARGETED BY ADDENDUM 345, and this is the test that forced that addendum's design. The original
        fix for "credits the first matching room ever entered" was to DROP the pickup, which also dropped
        real chests opened on the way out of a room. Holding it again would reintroduce the old bug -- unless
        the candidate rooms are fenced. They are, by SEQUENCE: only rooms seen at or before the berry rose
        are eligible, and `room_a` here is entered afterwards. So the pickup is carried, and `room_a` still
        cannot claim it. Both halves, which the drop could only ever get one of."""
        berry, room_a, _chest_a, _room_b, _chest_b = self._berry_in_two_rooms()
        foreign_room = next(r for r in set(chest_berries.CHEST_TO_ROOM.values())
                            if berry not in chest_berries.berries_used_in_room(r))
        tracker = rc.ChestBerryTracker()
        self.settle(tracker, foreign_room)
        self.bag[berry] = 1
        self.assertEqual(self.settle(tracker, foreign_room), [])
        self.assertEqual(self.settle(tracker, room_a), [],
                         "a room entered after the rise must never claim the pickup")
        self.assertEqual(tracker.credits, 0)

    def test_two_pickups_of_one_berry_in_two_rooms_credit_both_chests(self):
        berry, room_a, chest_a, room_b, chest_b = self._berry_in_two_rooms()
        tracker = rc.ChestBerryTracker()
        self.settle(tracker, room_a)
        self.bag[berry] = 1
        first = self.settle(tracker, room_a)
        self.bag[berry] = 1
        second = self.settle(tracker, room_b)
        self.assertEqual(first, [rc.CHEST_ID_TO_LOCATION[chest_a]])
        self.assertEqual(second, [rc.CHEST_ID_TO_LOCATION[chest_b]])


class TestTheReadWindowCoversWhereTheGameActuallyPutsTheBerry(unittest.TestCase):
    """ADDENDUM 231 (player: chests "are saying that there's 2 AP items in them ... worse, they're not sending
    checks at all").

    The tracker paired the berry sub-window's BASE (array slot 82) with the whole array's slot COUNT (190).
    Two failures from one mispairing: it never looked at slots 0-81, which is where the game's own item-add
    code puts a picked-up berry -- so no chest check ever fired -- and it ran 328 bytes past the end of the
    array, which `_clear` then WROTE into.

    These tests work in SLOT terms rather than by stubbing a flat quantity, because a stub that ignores the
    address is exactly what let the original bug through its own test suite."""

    BLOCK = 0x80479000

    def window(self, berry_id):
        return rc.resolve_item_read_window(self.BLOCK, berry_id)

    def test_the_window_starts_at_the_array_base_not_the_berry_sub_window(self):
        base, _slots = self.window(161)
        self.assertEqual(base, self.BLOCK + rc.POKEBALL_POCKET_OFFSET,
                         "reading from the berry sub-window base skips slots 0-81 entirely")

    def test_the_window_stops_at_the_end_of_the_array(self):
        base, slots = self.window(161)
        self.assertLessEqual(base + slots * 4, self.BLOCK + rc.MONEY_OFFSET,
                             "the read ran past the array into money and beyond")

    def test_a_berry_in_a_low_slot_is_found(self):
        """The reported bug, reproduced at the level it actually happened. Slot 3 is the kind of place a Bag
        filling from the bottom puts a berry, and the old window began at slot 82."""
        base, slots = self.window(161)
        first = (base - self.BLOCK - rc.POKEBALL_POCKET_OFFSET) // 4
        self.assertEqual(first, 0)
        self.assertGreater(slots, 82, "the window must span the low slots AND the berry sub-window")

    def test_the_write_window_is_left_narrow(self):
        """Reads widen; WRITES stay inside the ranges this project confirmed safe. Widening both would be the
        opposite mistake."""
        write_base, write_slots = rc.resolve_item_pocket(self.BLOCK, 161)
        self.assertEqual(write_base,
                         self.BLOCK + rc.POKEBALL_POCKET_OFFSET + rc.BERRIES_POCKET_RELATIVE_START * 4)
        self.assertEqual(write_slots, rc.BERRIES_SLOT_COUNT)

    def test_every_other_pocket_is_unchanged(self):
        for item_id in (13, 68, 225):
            self.assertEqual(self.window(item_id), rc.resolve_item_pocket(self.BLOCK, item_id))
        self.assertEqual(self.window(503), rc.resolve_item_pocket(self.BLOCK, 503))

    def test_an_unknown_id_has_no_window(self):
        self.assertIsNone(self.window(None))

    def test_the_tracker_reads_through_the_window_helper(self):
        """Pinned structurally: the old code combined two calls and that combination WAS the bug."""
        import inspect

        source = inspect.getsource(rc.ChestBerryTracker)
        self.assertIn("resolve_item_read_window(block_base, berry_id)", source)
        self.assertNotIn("POKEBALL_POCKET_ARRAY_SLOT_COUNT", source,
                         "the tracker must not pair a base with a separately-sourced slot count again")


class TestEveryChestGivesExactlyOne(unittest.TestCase):
    """ADDENDUM 231. The player saw "2 AP items" in a chest. ADDENDUM 44 settled this on their own
    instruction -- one chest, one item, one check -- and the quantity dimension broke it for nothing."""

    def test_no_chest_gives_more_than_one(self):
        for chest, (_berry, quantity) in chest_berries.CHEST_BERRY_ASSIGNMENT.items():
            self.assertEqual(quantity, 1, f"chest {chest} hands over {quantity}")

    def test_the_cap_is_one(self):
        self.assertEqual(chest_berries.MAX_CHEST_BERRY_QUANTITY, 1)

    def test_identity_never_depended_on_quantity_anyway(self):
        """Which is why removing it costs nothing: (room, berry) still resolves all 115 chests uniquely."""
        self.assertEqual(len(chest_berries.ROOM_BERRY_TO_CHEST),
                         len(chest_berries.CHEST_BERRY_ASSIGNMENT))


class TestTheSupersededModelIsGone(unittest.TestCase):
    """Dead identity code is how a wrong model comes back: someone reads it and believes it."""

    def test_the_old_trackers_are_deleted(self):
        self.assertFalse(hasattr(rc, "ChestPickupTracker"))
        self.assertFalse(hasattr(rc, "ChestBandTracker"))

    def test_the_flag_tracker_itself_is_kept(self):
        """The flag array is still real save state and still worth reading for diagnostics. What changed is
        that nothing derives IDENTITY from it."""
        self.assertTrue(hasattr(rc, "ChestFlagTracker"))


class TestTheRenames(unittest.TestCase):
    """ADDENDUM 219. A rename is safe; a renumber is not."""

    def test_every_renamed_chest_kept_its_frozen_id(self):
        """The real hazard: `_FROZEN_LOCATION_OFFSETS` is keyed by NAME, so a rename that does not carry its
        entry across leaves the location unfrozen and free to move. That would silently repoint every check
        on it in every existing seed."""
        unfrozen = [n for n in locations.LOCATION_TABLE if n not in locations._FROZEN_LOCATION_OFFSETS]
        self.assertEqual(unfrozen, [])

    def test_the_named_chests_are_all_real_ap_locations(self):
        named = {c for key in chest_names.CHEST_LOCATION_NAME_OVERRIDES for c in key}
        self.assertTrue(named <= set(rc.CHEST_ID_TO_LOCATION))

    def test_the_client_and_the_world_agree_on_every_name(self):
        """They build the string independently -- ram_client cannot import locations -- and the only thing
        between that and every chest check being rejected is that they agree character for character."""
        for chest_id, client_name in rc.CHEST_ID_TO_LOCATION.items():
            self.assertIn(client_name, locations.LOCATION_TABLE, chest_id)

    def test_the_iso_disagreements_were_resolved_in_the_isos_favour(self):
        """Three rows of the player's list did not match the real treasure table. Pinned individually because
        'we checked' is worth nothing without saying what the answer was."""
        room = {c["chest"]: c["room"] for c in chest_table.CHESTS}
        self.assertEqual(room[20], 1, "the second Cipher Lab Left Door chest is 20, not 17")
        self.assertEqual(room[17], 8, "chest 17 is in room 8")
        self.assertEqual(sorted(chest_berries.chests_in_room(8)), [17, 18, 19, 21, 22])

    def test_chest_98_finally_took_the_players_own_list_name(self):
        """ADDENDUM 246 settles the disagreement this test used to pin the other way. ADDENDUM 200 said
        "Pickup PDA", the ADDENDUM 219 list said "CNBS 3F Chest 1", and the ISO was always the tie-breaker:
        chest 98 is in ROOM 110 with chest 99, and rooms 109/110 are ONBS. The player confirmed it from the
        game -- "Pickup PDA is in hq lab right by chest 3, not pyrite town" -- and the lab's three boxes are
        chests 1, 2 and 3, none of them in room 110."""
        self.assertEqual(chest_names.chest_location_name_override((98,)), "ONBS 3F Chest 1")
        self.assertEqual(chest_names.chest_location_name_override((99,)), "ONBS 3F Chest 2")
        room = {c["chest"]: c["room"] for c in chest_table.CHESTS}
        self.assertEqual(room[98], 110)
        self.assertEqual(room[99], 110)
        self.assertNotIn(110, {room[c] for c in (1, 2, 3)})

    def test_the_rename_carried_both_ids_and_left_tombstones(self):
        """Same contract as chest 23's below -- `_FROZEN_LOCATION_OFFSETS` is keyed by NAME, so an id that is
        not carried across silently repoints the check in every existing seed."""
        self.assertEqual(locations.LOCATION_TABLE["ONBS 3F Chest 1"].id_offset, 1510)
        self.assertEqual(locations.LOCATION_TABLE["ONBS 3F Chest 2"].id_offset, 1511)
        self.assertEqual(locations._FROZEN_LOCATION_OFFSETS["Pickup PDA"], 1510)
        self.assertEqual(locations._FROZEN_LOCATION_OFFSETS["ONBS 3F Chest"], 1511)
        self.assertNotIn("Pickup PDA", locations.LOCATION_TABLE)
        self.assertNotIn("ONBS 3F Chest", locations.LOCATION_TABLE)

    def test_the_citadark_numbering_is_the_one_that_was_approved(self):
        """ADDENDUM 230. The 19 Citadark chests are numbered by room order, which means the numbering is a
        FUNCTION of the chest table rather than a list someone typed. If that table ever gains or loses a
        Citadark chest, every later number shifts and 19 locations get silently renamed at once -- so the
        order the player actually approved is pinned here as literals."""
        approved = [75, 59, 60, 61, 62, 63, 64, 65, 66, 57, 67, 68, 69, 70, 71, 72, 73, 74, 58]
        for index, chest in enumerate(approved, 1):
            self.assertEqual(chest_names.chest_location_name_override((chest,)),
                             f"Citadark Isle Chest {index}", f"chest {chest}")

    def test_chest_23_finally_has_its_real_name(self):
        """ADDENDUM 230 left this one generated on purpose -- "Leave 23 for now" -- because room 9 was the one
        Cipher Lab room the player's table did not cover, so any name would have been a guess about WHICH room
        it is, and a name describing the wrong room is worse than none. ADDENDUM 242: the player supplied it.

        The ID IS THE THING THAT MATTERS, not the label. `_FROZEN_LOCATION_OFFSETS` is keyed by name, so a
        rename that does not carry its entry across leaves the location free to move and silently repoints
        this check in every existing seed. 1496 came with it, and the old name stays behind as a tombstone so
        that id can never be reissued."""
        self.assertEqual(chest_names.chest_location_name_override((23,)), "Cipher Lab Krane Chest")
        self.assertEqual(rc.CHEST_ID_TO_LOCATION[23], "Cipher Lab Krane Chest")
        self.assertEqual(locations.LOCATION_TABLE["Cipher Lab Krane Chest"].id_offset, 1496)
        self.assertEqual(locations._FROZEN_LOCATION_OFFSETS["Chest 23 (Room 9)"], 1496)
        self.assertNotIn("Chest 23 (Room 9)", locations.LOCATION_TABLE)

    def test_every_ap_chest_now_has_a_real_name(self):
        """Chest 23 was the last hold-out, so this set is finally empty."""
        named = {c for key in chest_names.CHEST_LOCATION_NAME_OVERRIDES for c in key}
        self.assertEqual(set(rc.CHEST_ID_TO_LOCATION) - named, set())

    def test_onbs_not_cnbs(self):
        names = set(chest_names.CHEST_LOCATION_NAME_OVERRIDES.values())
        self.assertFalse([n for n in names if "CNBS" in n])
        self.assertIn("ONBS 3F Chest 1", names)
        self.assertIn("ONBS 3F Chest 2", names)
        self.assertIn("ONBS 2F Chest", names)

    def test_the_logic_the_list_reaffirms_still_holds(self):
        """The list's second purpose: "reaffirm our logic of what's required." Nothing needed changing -- so
        the point of this test is that it stays that way."""
        from ..game_data import chest_regions

        self.assertEqual(chest_regions.CHEST_ITEM_GATES.get(27), ("ID Card",))
        self.assertEqual(chest_regions.CHEST_REGION_GATES.get(2), ("Citadark Isle",))
        for chest in (98, 99, 100):
            self.assertEqual(chest_regions.CHEST_TO_REGION[chest], "Pyrite Town (ONBS)",
                             "ONBS is reached only through Data ROM -> Poke Spots, which is the "
                             "'Data Rom AND all three Poke Spots' requirement the list states")
            # ADDENDUM 246 (player: "Since it's onbs, it's behind data rom/id card"). The region already
            # says this; the explicit gate is what keeps it true if the region is ever re-parented.
            self.assertEqual(chest_regions.CHEST_ITEM_GATES.get(chest), ("Data ROM", "ID Card"),
                             f"chest {chest} must name the ROM itself, not only inherit it")


if __name__ == "__main__":
    unittest.main()
