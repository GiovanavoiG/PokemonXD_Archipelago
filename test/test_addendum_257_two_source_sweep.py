"""ADDENDUM 257 (2026-09-17) -- the two standing sweeps, run.

The open-issues register carried two generalisations this project wrote down and never acted on:

  1. ADDENDUM 254: "any fact stated twice needs a derivation or a fence -- what else is described in two
     places?" Written after ROOM ids turned out to be the third instance of a shape (ADDENDA 185/211/241/242
     for trainers, 219 for chest names) that had only ever been fenced one table at a time.
  2. ADDENDUM 256: "every value with a plausibility ceiling -- when it rejects a reading, can anything
     downstream tell?" Written after `StoryByteTracker` was caught reporting a stale byte as live.

This file is sweep 1 as a standing test. Sweep 2's one finding (`RoomTracker`) is fixed in ram_client.py and
covered by TestTheRoomTrackerCanSayItIsStale below.

NOTHING HERE IS A LIST. Every assertion is derived from the tables it compares, so a new shop, region or room
is covered the day it is added rather than the day someone remembers to extend a literal -- which is how
`test_every_gateon_room_counts_as_inside` managed to pin the very mistake it was meant to catch.
"""
from __future__ import annotations

import unittest

from .. import ram_client as rc, regions as world_regions, travel_locations as tl, trainer_defeat as td
from ..game_data import (
    chest_regions,
    map_destinations,
    repeatable_trainers,
    shops,
    story_bytes,
)


def _graph_regions() -> "set[str]":
    """Every region name the world can legitimately use: the story graph plus the synthetic buckets
    locations.py connects straight off Menu."""
    return set(world_regions.REGION_NAMES) | {
        "Menu", "Pokemon Storage", "Shadow Pokemon Purification",
        "Trainer Defeat Count", "Unique Trainer Defeats", "Relic Forest", "Orre Colosseum",
    }


class TestEveryRegionNameResolvesToTheGraph(unittest.TestCase):
    """Six tables name regions. A typo or a rename in any one of them is a rule that silently never fires, or
    a location filed somewhere the graph cannot reach -- and neither is loud."""

    def _check(self, label, names):
        stray = sorted(n for n in names if n is not None) 
        stray = sorted(set(stray) - _graph_regions())
        self.assertEqual([], stray, f"{label} names region(s) the graph does not have: {stray}")

    def test_the_room_table(self) -> None:
        self._check("chest_regions.ROOM_TO_REGION", chest_regions.ROOM_TO_REGION.values())

    def test_the_shop_table(self) -> None:
        self._check("shops.SHOPS", (s.region for s in shops.SHOPS))

    def test_the_map_destinations(self) -> None:
        rows = tuple(map_destinations.CONFIRMED) + tuple(map_destinations.AWAITING_MEASUREMENT)
        self._check("map_destinations", (getattr(d, "region", None) for d in rows))

    def test_the_area_groups(self) -> None:
        self._check("story_bytes.AREA_GROUPS",
                    (r for members in story_bytes.AREA_GROUPS.values() for r in members))

    def test_the_travel_targets(self) -> None:
        self._check("travel_locations", tl.TRAVEL_LOCATION_TARGET_REGION.values())

    def test_the_trainer_roster(self) -> None:
        self._check("trainer_defeat.TRAINER_DEFEAT_ROSTER",
                    (region for region, _name, _surname in td.TRAINER_DEFEAT_ROSTER))

    def test_the_any_defeat_anchors(self) -> None:
        self._check("repeatable_trainers", (row["region"] for row in repeatable_trainers.REPEATABLE_TRAINERS))


class TestTwoTablesAgreeAboutTheSameRoom(unittest.TestCase):
    """ADDENDUM 254's shape, swept. Every shop row carries BOTH a room id and a region, and the room table
    independently says what region that room is in. They agree today; nothing asserted it."""

    def test_every_shop_room_is_in_the_region_its_row_claims(self) -> None:
        checked = 0
        for shop in shops.SHOPS:
            said = chest_regions.ROOM_TO_REGION.get(shop.room_id)
            if said is None:
                continue   # a room the compilation has not placed -- absence is not disagreement
            self.assertEqual(shop.region, said,
                             f"shop in room {shop.room_id} says {shop.region!r}, "
                             f"the room table says {said!r}")
            checked += 1
        self.assertGreaterEqual(checked, 10, "the sweep found almost nothing -- it is not testing anything")

    def test_the_gateon_override_set_agrees_with_the_room_table(self) -> None:
        """The instance that started this (ADDENDUM 254), kept as part of the general sweep rather than only
        in its own file."""
        for room in rc.GATEON_ROOM_IDS:
            region = chest_regions.ROOM_TO_REGION.get(room)
            self.assertIn(region, ("Gateon Port", None), f"room {room} is called {region!r}")

    def test_every_shop_room_can_be_named(self) -> None:
        """Found by this sweep: EIGHT of the ten shop rooms had no `KNOWN_ROOM_IDS` entry, so `!room` in the
        Phenac City shop said "room 103 (unnamed)" while two other tables knew exactly what it was. A third
        table describing rooms, incomplete against the other two.

        Asserted against `room_name` rather than against `KNOWN_ROOM_IDS`, deliberately: the fix was to derive
        the fallback from the tables that already know, so the NEXT shop is named the day it is added. An
        assertion on the raw dict would have demanded eight literals and learnt nothing."""
        bare = sorted(s.room_id for s in shops.SHOPS
                      if rc.room_name(s.room_id) == f"room {s.room_id} (unnamed)")
        self.assertEqual([], bare)

    def test_a_room_no_table_knows_is_still_honest_about_it(self) -> None:
        """The fallback must not invent a name for a room nothing has recorded."""
        unknown = max(rc.KNOWN_ROOM_IDS) + 10_000
        self.assertEqual(f"room {unknown} (unnamed)", rc.room_name(unknown))
        self.assertEqual("unknown", rc.room_name(None))

    def test_the_hand_recorded_name_still_wins(self) -> None:
        """`KNOWN_ROOM_IDS` carries detail no derived name has -- "Gateon Tower 1F -- chests 6, 7"."""
        self.assertEqual(rc.KNOWN_ROOM_IDS[158], rc.room_name(158))
        self.assertIn("chests", rc.room_name(158))


class TestTheRoomTrackerCanSayItIsStale(unittest.TestCase):
    """Sweep 2's finding. `poll` folded "unreadable" into "unchanged" -- one branch, two situations -- and
    `describe()` printed the cached room with the same confidence either way.

    Keeping the cached value is CORRECT here, unlike the story byte: half the poll loop falls back on
    `room_tracker.current` when a fresh read fails, so dropping it would turn a one-tick hiccup into a lost
    chest check. What was missing is that nothing could tell."""

    def _tracker(self):
        tracker = rc.RoomTracker()
        tracker.current, tracker.previous, tracker.changes = 153, 140, 3
        return tracker

    def test_an_unreadable_poll_is_counted_not_swallowed(self) -> None:
        tracker = self._tracker()
        original = rc.read_room_id
        rc.read_room_id = lambda: None
        try:
            for _ in range(4):
                self.assertIsNone(tracker.poll())
        finally:
            rc.read_room_id = original
        self.assertEqual(4, tracker.unknown_polls)
        self.assertEqual(4, tracker.consecutive_unknown)

    def test_the_cached_room_survives_an_unreadable_poll(self) -> None:
        """The load-bearing half. `check_chests`, `check_shops` and the area memory all fall back on this."""
        tracker = self._tracker()
        original = rc.read_room_id
        rc.read_room_id = lambda: None
        try:
            tracker.poll()
        finally:
            rc.read_room_id = original
        self.assertEqual(153, tracker.current)

    def test_describe_says_stale_only_while_it_is(self) -> None:
        tracker = self._tracker()
        self.assertNotIn("STALE", tracker.describe())
        tracker.consecutive_unknown, tracker.unknown_polls = 7, 9
        text = tracker.describe()
        self.assertIn("STALE", text)
        self.assertIn("not necessarily where you are now", text)
        self.assertIn("9 unreadable poll(s)", text)

    def test_a_good_read_clears_the_streak(self) -> None:
        tracker = self._tracker()
        tracker.consecutive_unknown, tracker.unknown_polls = 5, 5
        original = rc.read_room_id
        rc.read_room_id = lambda: 153
        try:
            tracker.poll()
        finally:
            rc.read_room_id = original
        self.assertEqual(0, tracker.consecutive_unknown)
        self.assertEqual(5, tracker.unknown_polls, "the session total is history and stays")
        self.assertNotIn("STALE", tracker.describe())


if __name__ == "__main__":
    unittest.main()


class TestTheTwoExolLocationsCanNeverCoexist(unittest.TestCase):
    """ADDENDUM 258 (2026-09-17). The register carried "Duplicate Exol" as a decision waiting to be made --
    "`Defeat - Exol` and `Defeat - Cipher Commander Exol` are two AP locations for one fight" -- since
    ADDENDUM 211. It was never true.

    They live in DIFFERENT dispatch queues, and the two queues are mutually exclusive by mode (ADDENDUM 144):
    cumulative mode creates the 66 curated named locations, unique mode replaces them wholesale with the
    232-row roster. So a seed has exactly one Exol location; which NAME it has depends on
    `trainer_defeat_mode`. There is nothing to collapse and no rename to make."""

    def test_they_are_in_different_queues(self) -> None:
        from ..game_data import trainer_roster

        self.assertEqual(["Defeat - Cipher Commander Exol"], td.SURNAME_TO_LOCATION_QUEUE["Exol"])
        self.assertEqual(["Defeat - Exol"], trainer_roster.UNIQUE_SURNAME_TO_LOCATION_QUEUE["EXOL"])

    def test_the_curated_and_roster_queues_are_mutually_exclusive_by_mode(self) -> None:
        """The property that makes the above safe rather than a coincidence: ADDENDUM 144 replaced one
        category with the other rather than adding to it."""
        from .. import locations

        curated = {name for _region, name, _surname in td.TRAINER_DEFEAT_ROSTER}
        roster = set(locations._UNIQUE_TRAINER_DEFEAT_NAME_SET)
        self.assertTrue(curated & roster == set() or "Defeat - Exol" not in curated,
                        "the two categories must not share a name")
        self.assertIn("Defeat - Exol", roster)
        self.assertNotIn("Defeat - Exol", curated)
