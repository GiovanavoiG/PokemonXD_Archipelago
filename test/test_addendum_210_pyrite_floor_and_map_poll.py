"""ADDENDUM 210. Pyrite's second-visit floor, and polling fast while the map cursor is live.

Player, in one message:
  * "if pyrite is at 0x35 or higher, and cave spot is at 0x3B or higher, push pyrite floor to 0x3C"
  * "Please confirm that location shuffle is writing the story bytes based on map cursor polling"
  * "poll FAST when on map for the cursor"

THE RULE ENCODES A CHAIN THAT WAS ALREADY IN `TRANSITIONS`:

    0x2F -> 0x30   Pyrite Town unlocked / FIRST visit           <- Pyrite's static window floor
    0x34 -> 0x35   Data ROM handed over IN PYRITE
    0x39 -> 0x3A   Cave Poke Spot unlocked / first Miror B encounter
    0x3A -> 0x3C   Miror B defeated -- Pyrite VISIT 2, ONBS and the outside chests open

"CAVE POKE SPOT" IS NOT A REGION. Rock, Oasis and Cave all share the region "Poke Spots" in
map_destinations, so a rule naming the Cave Spot would match nothing and silently never fire -- the exact
shape of failure ADDENDA 201/204 were about. The rule names "Poke Spots", which is not a weakening: story
bytes only advance, and 0x3B cannot be reached before 0x3A, which IS the Cave Spot unlock.

WHY THE MAP POLL RATE IS CORRECTNESS, NOT COMFORT: the area-memory write is a PRE-LOAD hook (ADDENDUM 177).
It must land while the cursor is still hovering, because once the room loads it has already been built from
the old byte. At 1.0s a player can move the cursor and press A inside a single poll and arrive at an area
built from the wrong story byte, with nothing afterwards to notice."""
from __future__ import annotations

import unittest
from pathlib import Path

from .. import ram_client
from ..game_data import story_bytes as sb


class TestThePyriteRule(unittest.TestCase):
    def _floor(self, marks):
        return sb.dynamic_region_floor("Pyrite Town", marks)

    def test_both_conditions_push_pyrite_to_0x3C(self) -> None:
        self.assertEqual(0x3C, self._floor({"Pyrite Town": 0x35, "Poke Spots": 0x3B}))

    def test_higher_marks_still_satisfy_it(self) -> None:
        self.assertEqual(0x3C, self._floor({"Pyrite Town": 0x40, "Poke Spots": 0x50}))

    def test_pyrite_below_0x35_does_not(self) -> None:
        self.assertIsNone(self._floor({"Pyrite Town": 0x34, "Poke Spots": 0x3B}))

    def test_the_spots_below_0x3B_do_not(self) -> None:
        self.assertIsNone(self._floor({"Pyrite Town": 0x35, "Poke Spots": 0x3A}))

    def test_neither_alone_is_enough(self) -> None:
        self.assertIsNone(self._floor({"Pyrite Town": 0x35}))
        self.assertIsNone(self._floor({"Poke Spots": 0x3B}))
        self.assertIsNone(self._floor({}))

    def test_it_sits_above_pyrites_first_visit_floor(self) -> None:
        """If it were at or below the static floor it would do nothing at all."""
        self.assertEqual(0x30, sb.region_floor("Pyrite Town"))
        self.assertGreater(0x3C, sb.region_floor("Pyrite Town"))

    def test_onbs_counts_toward_pyrite_because_they_are_one_area(self) -> None:
        self.assertIn("Pyrite Town (ONBS)", sb.AREA_GROUPS["Pyrite Town"])
        self.assertEqual(0x3C, self._floor({"Pyrite Town (ONBS)": 0x3C, "Poke Spots": 0x3C}))

    def test_the_rule_names_a_region_that_actually_exists(self) -> None:
        """The silent-no-op trap: a requirement naming "Cave Poke Spot" would never match anything."""
        from ..game_data import map_destinations
        regions = {d.region for d in map_destinations.BY_LOCATION_ID.values()}
        for rule in sb.AREA_FLOOR_RULES:
            for area, _byte in rule.requires:
                self.assertTrue(
                    area in sb.AREA_GROUPS or area in regions,
                    f"{rule.target}'s rule requires {area!r}, which is neither an area group nor a region",
                )

    def test_the_chain_this_rule_encodes_is_the_real_one(self) -> None:
        """Pinned against TRANSITIONS so a future edit to the story table cannot leave this rule stranded."""
        pairs = {(t.before, t.after): t for t in sb.TRANSITIONS}
        self.assertIn((0x34, 0x35), pairs)
        self.assertIn("Data ROM", pairs[(0x34, 0x35)].what)
        self.assertIn((0x39, 0x3A), pairs)
        self.assertIn("Cave Poke Spot", pairs[(0x39, 0x3A)].what)
        self.assertIn((0x3A, 0x3C), pairs)
        self.assertIn("Pyrite visit 2", pairs[(0x3A, 0x3C)].what)


class TestTheCursorIsWhatDrivesTheWrite(unittest.TestCase):
    """The player's "please confirm" -- asserted rather than answered in prose."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (Path(ram_client.__file__).resolve().parent / "Client.py").read_text(encoding="utf-8")

    def test_the_hovered_region_comes_from_the_map_cursor(self) -> None:
        self.assertIn("hovered_region = ram_client.map_destination_region(ctx.map_cursor_tracker.resolve())",
                      self.source)

    def test_the_cursor_is_only_read_on_the_map_screen(self) -> None:
        self.assertIn("if room_id == ram_client.MAP_SCREEN_ROOM_ID:", self.source)

    def test_the_write_is_gated_on_travel_randomization(self) -> None:
        """It writes save data; with travel randomization off the byte is already right everywhere."""
        block = self.source.split("async def check_area_story_memory", 1)[1].split("async def ", 1)[0]
        self.assertIn("if not ctx.randomize_travel_locations:", block)
        self.assertIn("return", block)

    def test_no_hover_means_no_write(self) -> None:
        """`poll` returns immediately when the cursor is not on a destination."""
        import inspect
        src = inspect.getsource(ram_client.AreaStoryByteMemory.poll)  # noqa: F841
        self.assertIn("if hovered_region is None:", src)
        self.assertIn("return None", src)


class TestTheMapPollsFast(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (Path(ram_client.__file__).resolve().parent / "Client.py").read_text(encoding="utf-8")

    def test_there_is_a_faster_interval_for_the_map(self) -> None:
        # Checked against the SOURCE, not by import: Client.py pulls in Archipelago's CommonClient (and
        # websockets through it), which is not importable in this test environment. Same approach ADDENDUM
        # 181's logging fence already uses on this file.
        # UPDATED 2026-09-15 (ADDENDUM 228): 0.15 -> 0.05. Pinning the literal made this a test of one
        # number; what has to stay true is that a dedicated, faster map interval EXISTS and is fast enough to
        # beat a player moving the cursor and pressing A. Half a tenth of a second is the working threshold.
        self.assertIn("POLL_INTERVAL_MAP_SCREEN = ", self.source)
        import re

        value = float(re.search(r"^POLL_INTERVAL_MAP_SCREEN = ([0-9.]+)", self.source, re.M).group(1))
        self.assertLessEqual(value, 0.1,
                             "the map poll has to land inside the window between the cursor settling and the "
                             "A press -- the area-memory write is a PRE-LOAD hook (ADDENDUM 177)")
        self.assertGreater(value, 0.0)

    def test_it_is_actually_faster_than_the_normal_one(self) -> None:
        """REWRITTEN 2026-09-15 (ADDENDUM 228). This pinned the literal "POLL_INTERVAL_INGAME = 1.0", which
        made it a test of one number rather than of the relationship that matters. The map screen is the one
        place where poll rate is correctness rather than comfort (the area-memory write is a PRE-LOAD hook and
        has to land while the cursor is still hovering), so what has to stay true is that the map poll is
        FASTER -- whatever the ordinary interval becomes."""
        import re

        def value(name: str) -> float:
            match = re.search(rf"^{name} = ([0-9.]+)", self.source, re.M)
            self.assertIsNotNone(match, f"{name} is not defined at module level any more")
            return float(match.group(1))

        ingame = value("POLL_INTERVAL_INGAME")
        on_map = value("POLL_INTERVAL_MAP_SCREEN")
        self.assertLess(on_map, ingame,
                        "the map screen must poll faster than the overworld -- it is racing the player's thumb")
        self.assertLessEqual(on_map, ingame / 2,
                             "and by a real margin, not a rounding difference")

    def test_the_loop_selects_it_by_room(self) -> None:
        self.assertIn("sleep_time = (POLL_INTERVAL_MAP_SCREEN", self.source)
        self.assertIn("if ctx.room_tracker.current == ram_client.MAP_SCREEN_ROOM_ID", self.source)

    def test_the_map_room_id_is_the_one_the_cursor_check_uses(self) -> None:
        """Both the fast poll and the cursor read must key off the same room, or one of them is dead code."""
        self.assertEqual(910, ram_client.MAP_SCREEN_ROOM_ID)


if __name__ == "__main__":
    unittest.main()
