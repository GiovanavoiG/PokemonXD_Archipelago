"""ADDENDA 373/374 (2026-09-27): the chest window is 0.5s, and the room overrules a wrong flag.

Player: "Shorten the 2 seconds." Then: "there are two chests with the same label - one in key lair and one in
snagem. They are both labelled snagem 3f chest 1. That's what I want fixed."

ADDENDUM 373 -- `CONFIRM_WINDOW_SECONDS["chest_berry"]` 2.0 -> 0.5. ADDENDUM 372 measured that this window is
the whole remaining wait for the ~19 chests with no measured open-flag; a flagged chest short-circuits it on
ADDENDUM 289's pair and never reaches it.

THE TRAP THIS SET, which is the real work of 373. `set_poll_interval` derives `_CONFIRM_STREAK` from this very
value through `polls_for_seconds`, and at the 1.0s outer cadence `ceil(0.5 / 1.0)` is **1**. So lowering the
clock would have collapsed the read streak to "believe the first reading" at the same moment it shortened the
clock -- two of the three defences gone from one edit, with nothing in any log. `_MIN_CONFIRM_STREAK` is the
floor; the tests below are the fence.

ADDENDUM 374 -- WHAT THE DUPLICATE LABEL ACTUALLY IS. Checked before changing anything, and it is none of the
obvious things: `CHEST_LOCATION_NAME_OVERRIDES` has no repeated value, no two chests resolve to one string
through `locations.chest_location_name_for_ids`, and the ROOM path is correct -- a berry-161 rise credits
`Cipher Key Lair 1F Chest 3` from room 64 and `Snagem 3F Chest 1` from room 167, including with the room
unreadable and Snagem in the recent history.

That leaves one path: `_corroborating_chest` returns the chest whose BIT flipped and, by ADDENDUM 345's design,
never consults the room. Correct when the bit is measured correctly, and silently wrong when it is not -- a
mis-attributed bit renames every pickup that flips it, wherever the player is standing. So the room now
overrules the flag when the two disagree, which cannot lose a check (the room's answer IS the slow path's
answer) and makes the disagreement visible instead of silent.
"""
from __future__ import annotations

import pathlib
import unittest

from .. import ram_client as rc
from ..game_data import chest_berries, chest_names as cn, chest_table
from .test_addendum_345_a_chest_opened_on_the_way_out import _World

BLOCK = 0x80479000
CLIENT = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")


class TestTheWindowCameDownWithoutTakingTheStreakWithIt(unittest.TestCase):
    def test_the_clock_is_gone_and_the_streak_is_the_debounce(self) -> None:
        """ADDENDUM 375. The clock is removed rather than shortened again -- it is an ADDENDUM 111 number that
        predates ADDENDUM 148's gate and never caught the glitch it was widened for. The constant stays so
        re-arming it is one number."""
        self.assertEqual(0.0, rc.CONFIRM_WINDOW_SECONDS["chest_berry"])
        self.assertIn("chest_berry", rc.CONFIRM_WINDOW_SECONDS)

    def test_the_streak_is_what_is_left_and_the_gate_cannot_replace_it(self) -> None:
        """Not "nothing", and the reason is the gate's own threshold rather than its location. ADDENDUM 148
        watches the SAME packed array the berries sit in and reacts only to churn above 16 bytes -- it has to
        be blind to small changes, because a real chest opening is one. So a two-byte spurious move (a torn
        read of this berry's u16 quantity) passes the gate untouched, and two agreeing reads is the only thing
        that catches it.

        Asserted as the relationship rather than as prose: the gate's window really does cover the berries, and
        its threshold really is well above the two bytes a chest moves."""
        self.assertGreaterEqual(rc.ChestBerryTracker._CONFIRM_STREAK, 2)
        self.assertEqual(rc.POKEBALL_POCKET_OFFSET, rc.BLOCK_STABILITY_WINDOW_OFFSET)
        window = range(rc.BLOCK_STABILITY_WINDOW_OFFSET,
                       rc.BLOCK_STABILITY_WINDOW_OFFSET + rc.BLOCK_STABILITY_WINDOW_SIZE)
        self.assertIn(rc.POKEBALL_POCKET_OFFSET + 82 * 4, window,
                      "the berries are inside the gate's own window, so the gate is not independent evidence "
                      "-- its THRESHOLD is what makes it a different question")
        self.assertGreater(rc.BLOCK_CHURN_BYTE_THRESHOLD, 2,
                           "a threshold at or below two bytes would flag every real chest opening as churn")

    def test_the_pending_deadline_is_still_far_above_it(self) -> None:
        """The two run in opposite directions -- one guards against firing early, the other bounds how long a
        real pickup is held. Shortening the debounce must not drag the abandonment deadline down with it."""
        self.assertEqual(4.0, rc.CONFIRM_WINDOW_SECONDS["chest_pending"])
        self.assertGreater(rc.CONFIRM_WINDOW_SECONDS["chest_pending"],
                           rc.CONFIRM_WINDOW_SECONDS["chest_berry"])

    def test_the_streak_floor_survives_the_real_poll_interval(self) -> None:
        """THE ONE THAT MATTERS. `polls_for_seconds(0.5)` at a 1.0s cadence is 1, and a streak of one is the
        absence of a debounce. Driven through the real entry point rather than asserted on the constant."""
        original = rc.POLL_INTERVAL_SECONDS
        try:
            for interval in (1.0, 0.5, 0.1, 0.05):
                resolved = rc.set_poll_interval(interval)
                self.assertGreaterEqual(resolved["chest_berry"], rc.ChestBerryTracker._MIN_CONFIRM_STREAK,
                                        f"the streak collapsed at a {interval}s cadence")
                self.assertGreaterEqual(rc.ChestBerryTracker._CONFIRM_STREAK, 2,
                                        f"two agreeing reads is the ADDENDUM 209 guarantee ({interval}s)")
        finally:
            rc.set_poll_interval(original)

    def test_the_floor_is_the_value_the_class_documents(self) -> None:
        self.assertEqual(2, rc.ChestBerryTracker._MIN_CONFIRM_STREAK)

    def test_a_single_read_still_cannot_credit(self) -> None:
        """What the streak floor buys, stated as behaviour: one poll showing a rise is never enough, however
        long the clock has been running."""
        picked = next(((c, r, chest_berries.berry_for_chest(c)[0])
                       for c, r in sorted(chest_berries.CHEST_TO_ROOM.items())
                       if chest_berries.berry_for_chest(c)), None)
        if picked is None:
            self.skipTest("no berry assignments in this build")
        chest, room, berry = picked
        world = _World()
        tracker = rc.ChestBerryTracker(clock=world.clock)
        world.install(self, tracker)
        rc.ChestBerryTracker._clear = lambda self, b, x: None
        world.bag[berry] = 0
        tracker._poll(BLOCK, room, frozenset(), chest_berries)
        world.now += 30.0                      # the clock is long past the window
        world.bag[berry] = 1
        self.assertEqual([], tracker._poll(BLOCK, room, frozenset(), chest_berries),
                         "one read credited a chest -- the streak floor is not holding")


class TestTheRoomOverrulesAWrongFlag(unittest.TestCase):
    """ADDENDUM 374. Built on the real pair the player met: chests 49 (Cipher Key Lair 1F, room 64) and 106
    (Snagem 3F, room 167) both carry berry 161, and 106 has a measured flag while the Key Lair 1F chests 43, 44
    and 56 have none."""

    BERRY = 161
    KEY_LAIR, SNAGEM = 49, 106

    def test_the_fixture_is_the_real_pair(self) -> None:
        room = {e["chest"]: e["room"] for e in chest_table.CHESTS}
        self.assertEqual(self.BERRY, chest_berries.berry_for_chest(self.KEY_LAIR)[0])
        self.assertEqual(self.BERRY, chest_berries.berry_for_chest(self.SNAGEM)[0])
        self.assertEqual(64, room[self.KEY_LAIR])
        self.assertEqual(167, room[self.SNAGEM])

    def _tracker(self):
        world = _World()
        tracker = rc.ChestBerryTracker(clock=world.clock)
        world.install(self, tracker)
        rc.ChestBerryTracker._clear = lambda self, b, x: None
        return world, tracker

    def test_a_flag_naming_a_chest_in_another_room_loses_to_the_room(self) -> None:
        """The reported symptom, reproduced as the mechanism: Snagem chest 106's bit flips while the player is
        standing in Cipher Key Lair 1F. Before this addendum the flag won and "Snagem 3F Chest 1" fired in the
        Key Lair; now the room's own chest is credited and the disagreement is reported."""
        world, tracker = self._tracker()
        world.bag[self.BERRY] = 0
        tracker._poll(BLOCK, 64, frozenset(), chest_berries)   # baseline, in Key Lair 1F
        world.open_chest(self.SNAGEM)                          # the WRONG chest's bit moves
        world.bag[self.BERRY] = 1
        got: "list[str]" = []
        for _ in range(40):
            got += tracker._poll(BLOCK, 64, frozenset(), chest_berries)
            world.now += 0.05
        self.assertEqual(["Cipher Key Lair 1F Chest 3"], got[:1],
                         "the flag's chest was credited while the player stood in another room")
        self.assertEqual(1, tracker.flag_disagreed_with_room)
        self.assertTrue(tracker.flag_room_disagreements)
        self.assertIn("106", tracker.flag_room_disagreements[0])

    def test_an_agreeing_flag_is_untouched(self) -> None:
        """ADDENDUM 345 is narrowed, not rolled back. When the bit and the room name the same chest -- which is
        every correctly measured flag -- the fast path behaves exactly as it did."""
        world, tracker = self._tracker()
        world.bag[self.BERRY] = 0
        tracker._poll(BLOCK, 167, frozenset(), chest_berries)
        world.open_chest(self.SNAGEM)
        world.bag[self.BERRY] = 1
        got: "list[str]" = []
        for _ in range(40):
            got += tracker._poll(BLOCK, 167, frozenset(), chest_berries)
            world.now += 0.05
        self.assertEqual(["Snagem 3F Chest 1"], got[:1])
        self.assertEqual(0, tracker.flag_disagreed_with_room)

    def test_the_flag_still_wins_when_the_room_says_nothing(self) -> None:
        """The half of ADDENDUM 345 that makes leaving the room irrelevant. An unreadable room is not a
        disagreement, so the flag's identity still stands on its own."""
        world, tracker = self._tracker()
        world.bag[self.BERRY] = 0
        tracker._poll(BLOCK, 167, frozenset(), chest_berries)
        world.open_chest(self.SNAGEM)
        world.bag[self.BERRY] = 1
        got: "list[str]" = []
        for _ in range(40):
            got += tracker._poll(BLOCK, None, frozenset(), chest_berries)
            world.now += 0.05
        self.assertEqual(["Snagem 3F Chest 1"], got[:1])
        self.assertEqual(0, tracker.flag_disagreed_with_room)

    def test_nothing_is_ever_lost_to_the_guard(self) -> None:
        """The guard's safety argument: it redirects a credit, never withholds one."""
        world, tracker = self._tracker()
        world.bag[self.BERRY] = 0
        tracker._poll(BLOCK, 64, frozenset(), chest_berries)
        world.open_chest(self.SNAGEM)
        world.bag[self.BERRY] = 1
        got: "list[str]" = []
        for _ in range(200):
            got += tracker._poll(BLOCK, 64, frozenset(), chest_berries)
            world.now += 0.05
        self.assertEqual(1, len(got), "exactly one credit, and it is the room's")
        self.assertEqual(0, tracker.abandoned_pickups)


class TestTheClientSurfacesIt(unittest.TestCase):
    """Structural -- `Client.py` is not importable here. A counter nobody reads is how the last six of these
    survived, which is ADDENDUM 345's own closing note."""

    def test_the_disagreement_list_is_drained_rather_than_left_to_grow(self) -> None:
        """RETARGETED BY ADDENDUM 378. This asserted the disagreement was PRINTED as a warning, and the player
        has since had it removed: "the fix for Cipher Key Lair 1F Chest 3 worked - remove the debug message."

        What has to stay true is the part that was never about the message. The list is appended to on every
        disagreement, so a client that stopped reading it would leak -- and the COUNTER has to survive, because
        it is the only thing that could tell anyone a chest's flag is wrong again. On-demand output through
        `!chests` is what ADDENDUM 181 exempts, so that is where it lives now."""
        self.assertIn("flag_room_disagreements", CLIENT)
        block = CLIENT[CLIENT.index("if ctx.chest_berry_tracker.flag_room_disagreements:"):]
        self.assertIn("flag_room_disagreements.clear()", block[:400],
                      "the list is appended to every disagreement and must still be drained")
        self.assertNotIn("logger.warning", block[:400],
                         "ADDENDUM 378 removed the per-occurrence warning")

    def test_chests_reports_the_count(self) -> None:
        listing = CLIENT[CLIENT.index("def _cmd_chests"):]
        listing = listing[:listing.index("def _cmd_chestflags")]
        self.assertIn("flag_disagreed_with_room", listing)
        self.assertIn("chestflags", listing, "the report should name the command that measures the real bit")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
