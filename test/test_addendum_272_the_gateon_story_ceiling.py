"""ADDENDUM 272 (2026-09-18): the Robo Kyogre gate needed a ceiling, not just a lift.

Player: *"Set our byte to 0x6E at max in gateon - live-read our story bytes and ENSURE it never goes above
that in the area unless we have kyogre parts."*

ADDENDUM 271's verification had just established that without the Parts this client writes **nothing** in
Gateon. That makes the gate one-directional: it holds only while the player's own story byte is below the ride
threshold, and the moment ordinary play carries it past, Citadark is open, the Parts are decorative, and the
multiworld's logic is describing a game that no longer exists.

So the byte is clamped to `GATEON_STORY_CEILING` (0x6E) while the player is in Gateon without the Parts.

## Why one function decides, rather than two writers

A lift and a clamp on the same byte in the same rooms is two writers racing over one value -- ADDENDUM 255's
"two writers, one byte", and the same shape as the two-tables bug class (ADDENDA 185/211/241/254). So
`target_for(current)` is the single decision point and `_apply` does what it says. A function cannot race
itself.

## The three things that make a clamp safe to ship

This is the first write in this client that can LOSE progress. Everything else raises a byte or puts back a
value it saved a moment earlier; a clamp writes a lower number into save data.

1. **Save/restore**, exactly as the lift already had -- including on the map hover (ADDENDUM 255), so the byte
   is only low while the player is really in Gateon rooms.
2. **`recover()`**, for the case save/restore cannot cover: the client dying while the clamp is in place. The
   held value is persisted the tick it lands and put back on the next connect. Deliberately narrow -- it
   writes only when the live byte is still exactly the clamp value.
3. **A hard fence at victory.** `story_byte_says_won` is `>= VICTORY_STORY_BYTE`, and ADDENDUM 168 added that
   byte as the backstop for a missed final fight -- "the one failure a player cannot work around". Clamping
   0x78 down to 0x6E would erase it, permanently if the player saved there. A won game does not need the Robo
   Kyogre gated, so the clamp declines.

## And the one that makes it mean what the player asked

*"ENSURE it never goes above that in the area"* is not the same as "clamp it on the way in". A byte that RISES
while the player is standing in Gateon has to be caught too, which is `_hold`. Re-clamping is only safe
because `saved_byte` is raised to the new high FIRST -- the progress is kept for the restore and only the live
value is held down. Without that ordering, re-clamping would quietly eat every advance made inside Gateon.
"""
from __future__ import annotations

import sys
import types
import unittest

if "dolphin_memory_engine" not in sys.modules:
    _stub = types.ModuleType("dolphin_memory_engine")
    _stub.hook = lambda: None
    _stub.un_hook = lambda: None
    _stub.is_hooked = lambda: False
    _stub.read_bytes = lambda address, length: b""
    _stub.write_bytes = lambda address, data: None
    sys.modules["dolphin_memory_engine"] = _stub

from unittest import mock

from .. import ram_client as rc

BASE = 0x80479120
GATEON_ROOM = sorted(rc.GATEON_ROOM_IDS)[0]
ELSEWHERE_ROOM = 910 + 1234   # any room that is neither Gateon nor the map screen


class _WriteCapture:
    """Every story-byte write, in order, as plain ints."""

    def __init__(self, live: int) -> None:
        self.live = live
        self.writes: "list[int]" = []

    def write(self, address: int, payload: bytes) -> None:
        self.writes.append(payload[0])
        self.live = payload[0]

    def read(self, block_base: int) -> "int | None":
        return self.live

    def patch(self):
        return (mock.patch.object(rc, "write_bytes", self.write),
                mock.patch.object(rc, "read_story_byte", self.read))


def _run(override: "rc.StoryByteOverride", live: int, *actions):
    """Drive `override` through a sequence of ('room', id) / ('hover', region) steps against a live byte."""
    cap = _WriteCapture(live)
    w, r = cap.patch()
    with w, r:
        notes = []
        for kind, arg in actions:
            notes.append(override.poll(BASE, arg) if kind == "room" else override.poll_hover(BASE, arg))
    return cap, notes


class TestTheNumbersThemselves(unittest.TestCase):
    def test_the_ceiling_is_the_highest_value_that_still_cannot_ride(self) -> None:
        """0x6E, not the 0x6E of the first cut. 0x77 rides and 0x6E is CONFIRMED NOT ENOUGH (ADDENDUM 268,
        bisected live), so 0x6E gates the Robo Kyogre by measurement -- even though the ladder annotates
        `0x6E -> 0x6E` with `opens_regions=("Citadark Isle",)` and would tell a reader otherwise. That gap is
        268's whole lesson: the ladder records what the byte READS AFTER an event, not what the game CHECKS."""
        self.assertEqual(0x6E, rc.GATEON_STORY_CEILING)
        self.assertLess(rc.GATEON_STORY_CEILING, rc.STORY_OVERRIDE_VALUE)

    def test_it_does_not_close_the_master_ball_chest_or_the_gateon_restock(self) -> None:
        """Why 0x6E was wrong. `0x6E -> 0x6E` is "Robo Kyogre unlocked, Gateon shop restocked, Master Ball
        chest open" -- three things at once, and a ceiling at 0x6E takes all three. The last two carry real AP
        locations, so clamping there blocks checks to enforce a gate. This project does not do that."""
        from ..game_data import story_bytes

        restock = [t for t in story_bytes.TRANSITIONS if "Master Ball" in t.what]
        self.assertEqual(1, len(restock), "the transition this reasoning rests on has moved or been renamed")
        self.assertGreaterEqual(rc.GATEON_STORY_CEILING, restock[0].after,
                                "the ceiling must not sit below the Master Ball chest / Gateon restock tier")

    def test_the_ceiling_is_never_the_unlock_value(self) -> None:
        """Player: "ONLY write to 0x77 if we have the kyogre parts." """
        self.assertNotEqual(rc.STORY_OVERRIDE_VALUE, rc.GATEON_STORY_CEILING)

    def test_it_cannot_reach_victory(self) -> None:
        self.assertLess(rc.GATEON_STORY_CEILING, rc.VICTORY_STORY_BYTE)


class TestWithoutTheParts(unittest.TestCase):
    def test_a_high_byte_is_clamped_on_entering_gateon(self) -> None:
        ov = rc.StoryByteOverride(armed=False)
        cap, _ = _run(ov, 0x77, ("room", GATEON_ROOM))
        self.assertEqual([0x6E], cap.writes)
        self.assertTrue(ov.active)
        self.assertEqual(0x77, ov.saved_byte, "the real value has to be kept or the restore loses it")
        self.assertEqual(1, ov.clamps)

    def test_it_clamps_on_the_hover_too(self) -> None:
        """ADDENDUM 255's pre-load rule: the room is built from the byte as it stands when it loads, so a
        clamp applied on arrival leaves the Robo Kyogre sitting there for that whole visit."""
        ov = rc.StoryByteOverride(armed=False)
        cap, _ = _run(ov, 0x77, ("hover", "Gateon Port"))
        self.assertEqual([0x6E], cap.writes)

    def test_leaving_puts_the_real_value_back(self) -> None:
        ov = rc.StoryByteOverride(armed=False)
        cap, _ = _run(ov, 0x77, ("room", GATEON_ROOM), ("room", ELSEWHERE_ROOM))
        self.assertEqual([0x6E, 0x77], cap.writes)
        self.assertFalse(ov.active)
        self.assertIsNone(ov.saved_byte)

    def test_a_byte_already_below_the_ceiling_is_left_alone(self) -> None:
        """The overwhelmingly common case. A player mid-story must not have their byte touched at all."""
        ov = rc.StoryByteOverride(armed=False)
        cap, _ = _run(ov, 0x16, ("room", GATEON_ROOM), ("hover", "Gateon Port"))
        self.assertEqual([], cap.writes)
        self.assertFalse(ov.active)

    def test_a_byte_exactly_at_the_ceiling_is_left_alone(self) -> None:
        ov = rc.StoryByteOverride(armed=False)
        cap, _ = _run(ov, rc.GATEON_STORY_CEILING, ("room", GATEON_ROOM))
        self.assertEqual([], cap.writes)

    def test_a_byte_that_rises_inside_gateon_is_caught(self) -> None:
        """*"ENSURE it never goes above that in the area"* -- not just on the way in."""
        ov = rc.StoryByteOverride(armed=False)
        cap = _WriteCapture(0x77)
        w, r = cap.patch()
        with w, r:
            ov.poll(BASE, GATEON_ROOM)          # clamps 0x77 -> 0x6E
            cap.live = 0x72                     # something in Gateon advanced the byte under us
            note = ov.poll(BASE, GATEON_ROOM)
        self.assertEqual([0x6E, 0x6E], cap.writes)
        self.assertIn("held back", note)

    def test_progress_made_inside_gateon_is_kept_for_the_restore(self) -> None:
        """The ordering that makes re-clamping safe. Without raising `saved_byte` first, every advance made
        inside Gateon would be silently eaten by the restore."""
        ov = rc.StoryByteOverride(armed=False)
        cap = _WriteCapture(0x77)
        w, r = cap.patch()
        with w, r:
            ov.poll(BASE, GATEON_ROOM)
            cap.live = 0x72
            ov.poll(BASE, GATEON_ROOM)
            self.assertEqual(0x77, ov.saved_byte)
            cap.live = 0x6E
            ov.poll(BASE, ELSEWHERE_ROOM)
        self.assertEqual(0x77, cap.writes[-1])


class TestWithTheParts(unittest.TestCase):
    def test_the_lift_still_works_and_is_never_also_clamped(self) -> None:
        ov = rc.StoryByteOverride(armed=True)
        cap, _ = _run(ov, 0x16, ("room", GATEON_ROOM))
        self.assertEqual([rc.STORY_OVERRIDE_VALUE], cap.writes)
        self.assertEqual(0, ov.clamps)

    def test_a_player_holding_parts_above_the_ceiling_is_not_held_down(self) -> None:
        """The clause in the request: *"unless we have kyogre parts"*. A byte at 0x77 with the Parts in hand
        is already where the override would put it, so nothing is written at all."""
        ov = rc.StoryByteOverride(armed=True)
        cap, _ = _run(ov, rc.STORY_OVERRIDE_VALUE, ("room", GATEON_ROOM))
        self.assertEqual([], cap.writes)
        self.assertEqual(0, ov.clamps)


class TestAWonGameIsNeverClamped(unittest.TestCase):
    """The fence that matters most. ADDENDUM 168 made the story byte the backstop for a missed final fight --
    "the one failure a player cannot work around" -- and a clamp would erase it."""

    def test_victory_is_refused_on_the_way_in(self) -> None:
        ov = rc.StoryByteOverride(armed=False)
        cap, _ = _run(ov, rc.VICTORY_STORY_BYTE, ("room", GATEON_ROOM))
        self.assertEqual([], cap.writes)
        self.assertFalse(ov.active)
        self.assertEqual(1, ov.declined_clamp_won)

    def test_anything_past_victory_is_refused_too(self) -> None:
        ov = rc.StoryByteOverride(armed=False)
        cap, _ = _run(ov, rc.VICTORY_STORY_BYTE + 3, ("room", GATEON_ROOM))
        self.assertEqual([], cap.writes)

    def test_winning_while_standing_in_gateon_releases_the_ceiling(self) -> None:
        ov = rc.StoryByteOverride(armed=False)
        cap = _WriteCapture(0x77)
        w, r = cap.patch()
        with w, r:
            ov.poll(BASE, GATEON_ROOM)           # clamped
            cap.live = rc.VICTORY_STORY_BYTE     # they won in here
            note = ov.poll(BASE, GATEON_ROOM)
        self.assertEqual([0x6E], cap.writes, "the win must not be clamped away")
        self.assertFalse(ov.active)
        self.assertIn("win", note)

    def test_the_seed_can_still_be_won_while_the_ceiling_feature_is_on(self) -> None:
        """End to end against the real predicate, because this is the failure nobody could work around."""
        ov = rc.StoryByteOverride(armed=False)
        cap = _WriteCapture(rc.VICTORY_STORY_BYTE)
        w, r = cap.patch()
        with w, r:
            ov.poll(BASE, GATEON_ROOM)
            self.assertTrue(rc.story_byte_says_won(BASE))


class TestCrashRecovery(unittest.TestCase):
    """`recover()` is what makes the clamp survivable. Save/restore covers leaving Gateon; it cannot cover the
    client being killed while the player is inside it, and that is the case that loses story progress."""

    def test_a_held_value_is_put_back_when_the_byte_is_still_ours(self) -> None:
        ov = rc.StoryByteOverride(armed=False, saved_byte=0x77)
        cap = _WriteCapture(rc.GATEON_STORY_CEILING)
        w, r = cap.patch()
        with w, r:
            note = ov.recover(BASE)
        self.assertEqual([0x77], cap.writes)
        self.assertIsNone(ov.saved_byte)
        self.assertIn("previous session", note)

    def test_it_declines_when_the_player_has_moved_on(self) -> None:
        """Narrow on purpose: anything other than exactly our clamp value means the byte is theirs now, and
        writing would be the clobber rather than the repair."""
        ov = rc.StoryByteOverride(armed=False, saved_byte=0x77)
        cap = _WriteCapture(0x20)
        w, r = cap.patch()
        with w, r:
            self.assertIsNone(ov.recover(BASE))
        self.assertEqual([], cap.writes)

    def test_it_declines_when_there_is_nothing_held(self) -> None:
        ov = rc.StoryByteOverride(armed=False)
        cap = _WriteCapture(rc.GATEON_STORY_CEILING)
        w, r = cap.patch()
        with w, r:
            self.assertIsNone(ov.recover(BASE))
        self.assertEqual([], cap.writes)

    def test_it_never_lowers_anything(self) -> None:
        """A persisted value BELOW the live byte cannot be a clamp we made, so it is not restored."""
        ov = rc.StoryByteOverride(armed=False, saved_byte=0x40)
        cap = _WriteCapture(rc.GATEON_STORY_CEILING)
        w, r = cap.patch()
        with w, r:
            self.assertIsNone(ov.recover(BASE))
        self.assertEqual([], cap.writes)


class TestItStaysOutOfEveryOtherAreasWay(unittest.TestCase):
    def test_no_write_outside_gateon(self) -> None:
        ov = rc.StoryByteOverride(armed=False)
        cap, _ = _run(ov, 0x77, ("room", ELSEWHERE_ROOM), ("hover", "Agate Village"))
        self.assertEqual([], cap.writes)

    def test_the_map_screen_is_still_limbo(self) -> None:
        """ADDENDUM 255: neither applying nor restoring on room 910, or the hover write undoes itself."""
        ov = rc.StoryByteOverride(armed=False)
        cap, _ = _run(ov, 0x77, ("hover", "Gateon Port"), ("room", rc.MAP_SCREEN_ROOM_ID))
        self.assertEqual([0x6E], cap.writes)
        self.assertTrue(ov.active)

    def test_hovering_off_gateon_restores(self) -> None:
        ov = rc.StoryByteOverride(armed=False)
        cap, _ = _run(ov, 0x77, ("hover", "Gateon Port"), ("hover", "Agate Village"))
        self.assertEqual([0x6E, 0x77], cap.writes)

    def test_an_unreadable_byte_writes_nothing(self) -> None:
        ov = rc.StoryByteOverride(armed=False)
        with mock.patch.object(rc, "write_bytes", lambda a, p: self.fail("wrote on an unreadable byte")), \
             mock.patch.object(rc, "read_story_byte", return_value=None):
            self.assertIsNone(ov.poll(BASE, GATEON_ROOM))

    def test_the_ceiling_can_be_turned_off_entirely(self) -> None:
        """`ceiling=None` restores the pre-272 lift-only behaviour, which is what every existing test of this
        class assumes and what a seed that wants no clamping gets."""
        ov = rc.StoryByteOverride(armed=False, ceiling=None)
        cap, _ = _run(ov, 0x77, ("room", GATEON_ROOM))
        self.assertEqual([], cap.writes)
