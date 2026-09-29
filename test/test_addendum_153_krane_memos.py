"""ADDENDUM 153 (2026-09-11): the Krane Memos become real.

Player instruction: "Implement the krane memos", against their own ADDENDUM 152 compilation:
    0x10 Story Byte > Krane Memo 1 and 2 > remove from inventory, send 2 AP checks
    0x17 Story Byte > Memo 3 4 and 5 > remove from inventory, send 3 AP checks

The memos have been this world's ONLY progression items since the skeleton was built -- every region past
Phenac City is gated on holding N of them -- but the game hands all five over during the ordinary early story.
So the gating was decorative: you always had the real ones long before Archipelago delivered any. Clearing the
game's copies is what closes that, and the tests below care about the clearing as much as the checks.
"""
from __future__ import annotations

import struct
import unittest

from BaseClasses import LocationProgressType

from . import PokemonXDTestBase
from .. import items, locations, ram_client as rc, regions

BLOCK_BASE = 0x80479380


class TestConstantsMirrorLocations(unittest.TestCase):
    """ram_client.py duplicates these because it cannot import locations.py. ADDENDUM 151's chest-count drift
    is what happens when nothing checks the copies against each other."""

    def test_count_thresholds_and_item_ids_all_match(self) -> None:
        self.assertEqual(rc.KRANE_MEMO_COUNT, locations.KRANE_MEMO_COUNT)
        self.assertEqual(rc.KRANE_MEMO_STORY_THRESHOLDS, locations.KRANE_MEMO_STORY_THRESHOLDS)
        self.assertEqual(rc.KRANE_MEMO_GAME_ITEM_IDS, locations.KRANE_MEMO_GAME_ITEM_IDS)

    def test_location_names_match(self) -> None:
        for n in range(1, locations.KRANE_MEMO_COUNT + 1):
            self.assertEqual(rc.krane_memo_location_name(n), locations.krane_memo_location_name(n))

    def test_the_game_item_ids_are_the_real_bag_ids(self) -> None:
        """523-527, the ids items.py's KEY_ITEM_SPECS uses for Krane Memo 1-5."""
        from .. import items

        for n, item_id in locations.KRANE_MEMO_GAME_ITEM_IDS.items():
            self.assertEqual(items.ITEM_TABLE[f"Krane Memo {n}"].game_item_id, item_id)

    def test_the_thresholds_are_the_players_own_numbers(self) -> None:
        self.assertEqual(locations.KRANE_MEMO_STORY_THRESHOLDS[1], 0x10)
        self.assertEqual(locations.KRANE_MEMO_STORY_THRESHOLDS[2], 0x10)
        for n in (3, 4, 5):
            self.assertEqual(locations.KRANE_MEMO_STORY_THRESHOLDS[n], 0x17)


# ============================================================================================================
# The tracker
# ============================================================================================================
class _Bag:
    """A Key Items pocket holding whichever memo ids are given, so clearing can be observed."""

    def __init__(self, present: "list[int]", write_fails: bool = False) -> None:
        self.slots: list[tuple[int, int]] = [(item_id, 1) for item_id in present]
        while len(self.slots) < rc.KEY_ITEMS_MAX_SLOTS:
            self.slots.append((0, 0))
        self.write_fails = write_fails
        self.writes = 0

    def read(self, address: int, length: int) -> bytes:
        base = BLOCK_BASE + rc.KEY_ITEMS_OFFSET
        raw = b"".join(struct.pack(">HH", i, q) for i, q in self.slots)
        start = address - base
        return raw[start:start + length]

    def write(self, address: int, payload: bytes) -> None:
        if self.write_fails:
            raise RuntimeError("Dolphin went away")
        self.writes += 1
        index = (address - (BLOCK_BASE + rc.KEY_ITEMS_OFFSET)) // 4
        self.slots[index] = struct.unpack(">HH", payload)

    @property
    def item_ids(self) -> "set[int]":
        return {i for i, q in self.slots if i}


class _Patched:
    def __init__(self, bag: _Bag) -> None:
        self.bag = bag

    def __enter__(self):
        self._read, self._write = rc.read_bytes, rc.write_bytes
        rc.read_bytes, rc.write_bytes = self.bag.read, self.bag.write
        return self.bag

    def __exit__(self, *exc):
        rc.read_bytes, rc.write_bytes = self._read, self._write


ALL_MEMO_IDS = [523, 524, 525, 526, 527]


def _poll(tracker, bag, story_byte, times=1):
    fired = []
    with _Patched(bag):
        for _ in range(times):
            fired += tracker.poll(BLOCK_BASE, story_byte)
    return fired


class TestAwarding(unittest.TestCase):
    def test_nothing_fires_before_the_first_threshold(self) -> None:
        tracker, bag = rc.KraneMemoTracker(), _Bag(ALL_MEMO_IDS)
        self.assertEqual(_poll(tracker, bag, 0x0F), [])
        self.assertEqual(bag.item_ids, set(ALL_MEMO_IDS), "nothing should have been taken either")

    def test_the_first_threshold_awards_exactly_two(self) -> None:
        tracker, bag = rc.KraneMemoTracker(), _Bag(ALL_MEMO_IDS)
        self.assertEqual(_poll(tracker, bag, 0x10),
                         ["Story - Krane Memo 1", "Story - Krane Memo 2"])

    def test_the_second_threshold_awards_the_remaining_three(self) -> None:
        tracker, bag = rc.KraneMemoTracker(), _Bag(ALL_MEMO_IDS)
        _poll(tracker, bag, 0x10)
        self.assertEqual(_poll(tracker, bag, 0x17),
                         ["Story - Krane Memo 3", "Story - Krane Memo 4", "Story - Krane Memo 5"])

    def test_each_location_fires_exactly_once_however_long_you_play(self) -> None:
        tracker, bag = rc.KraneMemoTracker(), _Bag(ALL_MEMO_IDS)
        fired = _poll(tracker, bag, 0x17, times=50)
        self.assertEqual(len(fired), 5)
        self.assertEqual(len(set(fired)), 5)

    def test_connecting_late_still_awards_everything_already_earned(self) -> None:
        """The threshold is >=, not ==. An equality test would strand a check permanently, and these are the
        progression-gating locations -- stranding one matters more here than anywhere else."""
        tracker, bag = rc.KraneMemoTracker(), _Bag([])
        self.assertEqual(len(_poll(tracker, bag, 0x2F)), 5)

    def test_skipping_past_a_threshold_between_two_polls_loses_nothing(self) -> None:
        tracker, bag = rc.KraneMemoTracker(), _Bag(ALL_MEMO_IDS)
        _poll(tracker, bag, 0x0F)
        self.assertEqual(len(_poll(tracker, bag, 0x20)), 5)

    def test_an_unreadable_story_byte_is_not_treated_as_zero(self) -> None:
        tracker, bag = rc.KraneMemoTracker(), _Bag(ALL_MEMO_IDS)
        self.assertEqual(_poll(tracker, bag, None), [])


class TestClearing(unittest.TestCase):
    """The half that actually makes memo gating mean something."""

    def test_the_games_own_copies_are_taken_out_of_the_bag(self) -> None:
        tracker, bag = rc.KraneMemoTracker(), _Bag(ALL_MEMO_IDS)
        _poll(tracker, bag, 0x17)
        self.assertEqual(bag.item_ids, set())
        self.assertEqual(tracker.cleared_count, 5)

    def test_only_the_memos_at_a_reached_threshold_are_taken(self) -> None:
        tracker, bag = rc.KraneMemoTracker(), _Bag(ALL_MEMO_IDS)
        _poll(tracker, bag, 0x10)
        self.assertEqual(bag.item_ids, {525, 526, 527})

    def test_other_key_items_are_never_touched(self) -> None:
        tracker, bag = rc.KraneMemoTracker(), _Bag(ALL_MEMO_IDS + [506, 533])
        _poll(tracker, bag, 0x17)
        self.assertEqual(bag.item_ids, {506, 533}, "the ID Card and Disc Case must survive")

    def test_the_check_still_fires_when_the_bag_write_fails(self) -> None:
        """Sending and clearing are independent on purpose. A check that waited on a successful write could be
        lost to a transient failure; a clear that lags just retries."""
        tracker, bag = rc.KraneMemoTracker(), _Bag(ALL_MEMO_IDS, write_fails=True)
        self.assertEqual(len(_poll(tracker, bag, 0x10)), 2)
        self.assertEqual(tracker.cleared_count, 0)

    def test_a_memo_that_arrives_a_poll_late_is_still_cleared(self) -> None:
        """The story byte can plausibly tick over before the item write lands."""
        tracker, bag = rc.KraneMemoTracker(), _Bag([])
        _poll(tracker, bag, 0x10)
        bag.slots[0] = (523, 1)
        _poll(tracker, bag, 0x10)
        self.assertNotIn(523, bag.item_ids)

    def test_retrying_stops_rather_than_scanning_forever(self) -> None:
        """"Not present" and "already cleared" are indistinguishable from RAM, so the retry has to be bounded
        or a memo the player never received would cost a pocket scan every tick for the rest of the session."""
        tracker, bag = rc.KraneMemoTracker(), _Bag([])
        _poll(tracker, bag, 0x17, times=rc.KraneMemoTracker.CLEAR_ATTEMPTS + 20)
        writes_before = bag.writes
        bag.slots[0] = (523, 1)
        _poll(tracker, bag, 0x17, times=5)
        self.assertEqual(bag.writes, writes_before, "should have given up by now")

    def test_a_cleared_memo_is_not_re_cleared_every_poll(self) -> None:
        tracker, bag = rc.KraneMemoTracker(), _Bag(ALL_MEMO_IDS)
        _poll(tracker, bag, 0x17)
        writes = bag.writes
        _poll(tracker, bag, 0x17, times=20)
        self.assertEqual(bag.writes, writes)


class TestDescribe(unittest.TestCase):
    def test_before_anything_happens_it_says_what_to_expect(self) -> None:
        text = rc.KraneMemoTracker().describe()
        self.assertIn("0x10", text)
        self.assertIn("0x17", text)

    def test_after_awarding_it_reports_both_halves(self) -> None:
        tracker, bag = rc.KraneMemoTracker(), _Bag(ALL_MEMO_IDS)
        _poll(tracker, bag, 0x10)
        text = tracker.describe()
        self.assertIn("1, 2", text)
        self.assertIn("Removed from your Bag: 2", text)

    def test_a_memo_stuck_in_the_bag_is_surfaced(self) -> None:
        tracker, bag = rc.KraneMemoTracker(), _Bag([], write_fails=True)
        _poll(tracker, bag, 0x10)
        self.assertIn("Still trying to remove", tracker.describe())


# ============================================================================================================
# World wiring
# ============================================================================================================
class TestWorldWiring(PokemonXDTestBase):
    options = {"randomize_chests": True, "shuffle_trainer_defeats": True}

    def test_all_five_locations_exist(self) -> None:
        all_names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        for name in locations.KRANE_MEMO_LOCATION_NAMES:
            self.assertIn(name, all_names, name)

    def test_they_have_frozen_ids_that_collide_with_nothing(self) -> None:
        ids = [locations.LOCATION_TABLE[n].id_offset for n in locations.KRANE_MEMO_LOCATION_NAMES]
        self.assertEqual(ids, [1413, 1414, 1415, 1416, 1417])
        others = {d.id_offset for n, d in locations.LOCATION_TABLE.items()
                  if n not in set(locations.KRANE_MEMO_LOCATION_NAMES)}
        self.assertFalse(set(ids) & others)

    def test_they_sit_in_regions_the_graph_really_reaches(self) -> None:
        """RETARGETED 2026-09-13 (ADDENDUM 168), was "they sit in regions that need no memo to enter".

        The old assertion read `regions.MEMOS_REQUIRED[regions.REGION_CHAIN.index(region)] == 0`, which guarded
        against a memo location sitting behind a memo gate -- the self-gating restrictive-start failure. That
        failure mode cannot exist any more: the memos are not items (see
        test_the_memo_locations_survive_as_checks_while_the_items_are_gone below), so nothing they gate can gate
        them. MEMOS_REQUIRED is now all zeros, so keeping the old line would have been an assertion that passes
        for the wrong reason.

        The surviving concern is the other half of the same worry: a story check parked in a region the real
        graph never builds is silently unreachable forever. So this now checks each memo location's region is a
        genuine node in regions.REGION_EDGES, and that the location is reachable at all.
        """
        for name in locations.KRANE_MEMO_LOCATION_NAMES:
            self.assertIn(locations.LOCATION_TABLE[name].region, regions.REGION_NAMES, name)
        self.collect_key_item_chain()
        for name in locations.KRANE_MEMO_LOCATION_NAMES:
            self.assertTrue(self.can_reach_location(name), name)

    def test_the_later_memos_are_one_region_further_along(self) -> None:
        early = {locations.LOCATION_TABLE[locations.krane_memo_location_name(n)].region for n in (1, 2)}
        later = {locations.LOCATION_TABLE[locations.krane_memo_location_name(n)].region for n in (3, 4, 5)}
        self.assertEqual(early, {"Outskirt Stand"})
        self.assertEqual(later, {"Phenac City"})

    def test_they_can_hold_progression(self) -> None:
        """They are ordinary story checks, not a count bucket -- nothing should exclude them."""
        for name in locations.KRANE_MEMO_LOCATION_NAMES:
            self.assertEqual(
                self.multiworld.get_location(name, self.player).progress_type,
                LocationProgressType.DEFAULT,
                name,
            )

    def test_all_five_open_exactly_when_their_own_region_does(self) -> None:
        """RETARGETED 2026-09-13 (ADDENDUM 168), was "all five are reachable from the start".

        They used to be reachable turn one because both their regions (Outskirt Stand, Phenac City) were the
        memo ladder's unconditionally-open first two links, and they HAD to be -- a memo location behind a memo
        gate was unfillable. With the memos gone from the pool that constraint is gone with them, and the real
        graph puts both regions well inside the chain: Phenac City needs the Machine Part and the Data ROM, and
        Outskirt Stand is now a LATE region (Cipher Key Lair (exterior) -> Outskirt Stand), needing the Music
        Disc and Mayor's Note on top.

        So what this protects is no longer "turn one" but "at the right time, and not before": none of the five
        is a free sphere-0 check any more, the Phenac trio open at the Data ROM, and the Outskirt Stand pair
        stay shut until the Mayor's Note tier.
        """
        phenac = [locations.krane_memo_location_name(n) for n in (3, 4, 5)]
        outskirt = [locations.krane_memo_location_name(n) for n in (1, 2)]

        for name in locations.KRANE_MEMO_LOCATION_NAMES:
            self.assertFalse(self.can_reach_location(name), f"{name} should not be a sphere-0 check")

        self.collect_key_item_chain(2)  # Machine Part + Data ROM -> Phenac City
        for name in phenac:
            self.assertTrue(self.can_reach_location(name), name)
        for name in outskirt:
            self.assertFalse(self.can_reach_location(name), f"{name} is deeper than Phenac City")

        self.collect_key_item_chain(4)  # + Music Disc + Mayor's Note -> Outskirt Stand
        for name in outskirt:
            self.assertTrue(self.can_reach_location(name), name)

    def test_the_memo_locations_survive_as_checks_while_the_items_are_gone(self) -> None:
        """RETARGETED 2026-09-13 (ADDENDUM 168), was "the memo items still exist and still gate regions".

        That is precisely the model that was retired. The player's objection was that the gating was fiction
        ("Why do these locations require the memos? They're unrelated."), so regions.py now gates on the real
        story key items and items.ITEMS_REMOVED_FROM_POOL drops all five memos out of the pool entirely.

        The half of ADDENDUM 153 that is still real -- and is the part worth protecting, because it is what the
        client's KraneMemoTracker sends -- is the LOCATIONS: five ordinary AP checks that fire off story bytes
        0x10 and 0x17 while the game's own copies are taken out of the Bag. So this asserts the split: locations
        yes, items no, and MEMOS_REQUIRED kept only as a vestigial all-zero import shim.
        """
        pool = [item.name for item in self.multiworld.itempool]
        all_location_names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        for n in range(1, 6):
            item_name = f"Krane Memo {n}"
            self.assertNotIn(item_name, pool, f"{item_name} was retired from the pool in ADDENDUM 168")
            self.assertIn(item_name, items.ITEMS_REMOVED_FROM_POOL, item_name)
            self.assertIn(locations.krane_memo_location_name(n), all_location_names)
        self.assertEqual(set(regions.MEMOS_REQUIRED), {0}, "the memo ladder is vestigial, not live")
        self.assertEqual(len(regions.MEMOS_REQUIRED), len(regions.REGION_CHAIN))


if __name__ == "__main__":
    unittest.main()
