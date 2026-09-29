"""ADDENDUM 345 (2026-09-25) -- a chest opened on the way out of a room was dropped in silence.

Player: "I opened a chest and left a room fast enough that it didn't catch it. I want this to NEVER happen.
Is this currently the case?"

It was not. Reproduced against the real chest tables BEFORE anything was changed:

    flagged chest   1 | stay in the room   -> CREDITED
    flagged chest   1 | leave after 0.1s   -> CREDITED
    flagged chest   1 | leave immediately  -> LOST
    unflagged      31 | stay in the room   -> CREDITED
    unflagged      31 | leave after 0.1s   -> LOST
    unflagged      31 | leave immediately  -> LOST

THE MECHANISM. The room was read at CREDIT time, not at pickup time. A rise waits out `_CONFIRM_SECONDS`
(or one poll, when the flag corroborates), and the room captured at the end of that wait is wherever the
player is by then. `chest_for(that room, berry)` names nothing, and the pickup hit a branch that counted it
and returned. ADDENDUM 226's docstring promised "a check is deferred, never dropped" -- true of the branch it
was written about (an UNREADABLE room), not of this one, where the room reads perfectly and says the wrong
thing.

THE TENSION THIS FILE EXISTS TO PIN. "Never lose a check" and "never credit the wrong chest" pull against
each other exactly here, and the original code resolved it by dropping -- safe, and lossy. The resolution is
that the candidate rooms are fenced by SEQUENCE: only rooms the player was in AT OR BEFORE the berry rose can
claim a pickup. A room entered afterwards is not evidence about a chest opened before reaching it. Both
halves are asserted below, and the second half is the one that must never regress.
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

from .. import ram_client as rc
from ..game_data import chest_berries

BLOCK = 0x80479000


class _World:
    """The real chest tables, a Bag, and a flag band -- all driven by the test."""

    def __init__(self) -> None:
        span = rc._validated_flag_span()
        assert span is not None
        self.start, self.length = span
        self.flags = bytearray(self.length)
        self.bag: "dict[int, int]" = {}
        self.now = 1000.0

    def clock(self) -> float:
        return self.now

    def open_chest(self, chest_id: int) -> None:
        for cid, offset, mask in rc._validated_flag_bits():
            if cid == chest_id:
                self.flags[offset - self.start] |= mask

    def read_bytes(self, address, length):
        if address == BLOCK + self.start:
            return bytes(self.flags[:length])
        return b"\x00" * length

    def install(self, test, tracker) -> None:
        for name, value in (("read_bytes", self.read_bytes),
                            ("find_item_quantity", lambda b, s, i: self.bag.get(i, 0)),
                            ("resolve_item_read_window", lambda b, i: (0, 1))):
            test.addCleanup(setattr, rc, name, getattr(rc, name))
            setattr(rc, name, value)
        test.addCleanup(setattr, rc.ChestBerryTracker, "_clear", rc.ChestBerryTracker._clear)
        rc.ChestBerryTracker._clear = lambda self, block, berry: None


_FLAGGED = {c for c, _o, _m in rc._validated_flag_bits()}


def _a_chest(with_flag: bool):
    for chest in sorted(rc.CHEST_ID_TO_LOCATION):
        if (chest in _FLAGGED) != with_flag:
            continue
        pair = chest_berries.berry_for_chest(chest)
        if pair:
            return chest, chest_berries.CHEST_TO_ROOM[chest], pair[0]
    return None


class _Base(unittest.TestCase):
    WITH_FLAG = True

    def setUp(self) -> None:
        picked = _a_chest(self.WITH_FLAG)
        if picked is None:
            self.skipTest("no such chest in this build")
        self.chest, self.room, self.berry = picked
        self.world = _World()
        self.tracker = rc.ChestBerryTracker(clock=self.world.clock)
        self.world.install(self, self.tracker)
        self.elsewhere = [r for r in sorted(set(chest_berries.CHEST_TO_ROOM.values()))
                          if r != self.room]

    def run_polls(self, rooms, seconds_each=0.1):
        got = []
        for room in rooms:
            got += self.tracker._poll(BLOCK, room, frozenset(), chest_berries)
            self.world.now += seconds_each
        return got

    def open_and_walk(self, rooms_after, plant_flag=None):
        """Baseline in the chest's room, open the chest, then poll through `rooms_after`."""
        plant = self.WITH_FLAG if plant_flag is None else plant_flag
        self.world.bag[self.berry] = 0
        self.run_polls([self.room])
        if plant:
            self.world.open_chest(self.chest)
        self.world.bag[self.berry] = 1
        return self.run_polls(rooms_after)


class TestAFlaggedChestNeverNeedsTheRoom(_Base):
    WITH_FLAG = True

    def test_leaving_on_the_very_same_poll_still_credits(self):
        """The reported case, at its worst: the berry is first SEEN in the next room."""
        names = self.open_and_walk([self.elsewhere[0]] * 40)
        self.assertEqual([rc.CHEST_ID_TO_LOCATION[self.chest]], names)

    def test_sprinting_through_three_rooms_still_credits(self):
        names = self.open_and_walk(self.elsewhere[:3] + [self.elsewhere[2]] * 40)
        self.assertEqual([rc.CHEST_ID_TO_LOCATION[self.chest]], names)

    def test_the_room_is_never_consulted_at_all(self):
        """The flag is a per-chest bit. It is the chest's identity, not a hint about it."""
        names = self.open_and_walk([None] * 40)
        self.assertEqual([rc.CHEST_ID_TO_LOCATION[self.chest]], names)
        self.assertEqual(1, self.tracker.placed_by_flag)

    def test_it_is_credited_without_being_placed_from_history(self):
        self.open_and_walk([self.elsewhere[0]] * 40)
        self.assertEqual(0, self.tracker.placed_by_history,
                         "the flag should have answered outright, with no room lookup")


class TestAnUnflaggedChestIsRescuedByTheRoomHistory(_Base):
    WITH_FLAG = False

    def test_leaving_on_the_very_same_poll_still_credits(self):
        names = self.open_and_walk([self.elsewhere[0]] * 40)
        self.assertEqual([rc.CHEST_ID_TO_LOCATION[self.chest]], names)
        self.assertEqual(1, self.tracker.placed_by_history)

    def test_sprinting_through_three_rooms_still_credits(self):
        names = self.open_and_walk(self.elsewhere[:3] + [self.elsewhere[2]] * 40)
        self.assertEqual([rc.CHEST_ID_TO_LOCATION[self.chest]], names)

    def test_staying_put_is_unchanged_and_needs_no_rescue(self):
        names = self.open_and_walk([self.room] * 40)
        self.assertEqual([rc.CHEST_ID_TO_LOCATION[self.chest]], names)
        self.assertEqual(0, self.tracker.placed_by_history)


class TestTheFenceThatKeepsThisHonest(_Base):
    """The half that must never regress. Holding a pickup open is only safe because the candidate rooms are
    bounded -- and the bound is ordering, not a clock."""

    WITH_FLAG = False

    def test_a_room_entered_after_the_rise_can_never_claim_it(self):
        berry = self.berry
        later_room = next((r for r in self.elsewhere
                           if chest_berries.chest_for(r, berry) is not None), None)
        if later_room is None:
            self.skipTest("this berry is used by only one room")
        foreign = next(r for r in self.elsewhere
                       if chest_berries.chest_for(r, berry) is None)
        self.world.bag[berry] = 0
        self.run_polls([foreign])                       # the rise happens HERE
        self.world.bag[berry] = 1
        self.assertEqual([], self.run_polls([foreign] * 30))
        self.assertEqual([], self.run_polls([later_room] * 60),
                         "a room reached afterwards is not evidence about a chest opened before it")
        self.assertEqual(0, self.tracker.credits)

    def test_the_candidate_list_is_fenced_by_sequence_not_by_time(self):
        """A time window is not equivalent: a few polls is milliseconds on a real clock, so any window wide
        enough to rescue a real pickup also admits the room the player wandered into next."""
        self.tracker._remember_room(11)
        self.tracker._remember_room(22)
        entry = {"room": None, "rise_seq": self.tracker._room_seq}
        self.tracker._remember_room(33)                 # entered after the rise
        self.assertIn(11, self.tracker._candidate_rooms(entry))
        self.assertIn(22, self.tracker._candidate_rooms(entry))
        self.assertNotIn(33, self.tracker._candidate_rooms(entry))

    def test_nothing_is_ever_dropped_without_saying_so(self):
        """The silence is what let this survive six addenda: a field nobody read."""
        berry = self.berry
        foreign = next(r for r in self.elsewhere if chest_berries.chest_for(r, berry) is None)
        self.world.bag[berry] = 0
        self.run_polls([foreign])
        self.world.bag[berry] = 1
        self.run_polls([foreign] * 30, seconds_each=1.0)   # past _UNPLACEABLE_HOLD_SECONDS
        self.assertEqual(0, self.tracker.credits)
        self.assertTrue(self.tracker.unplaceable_notices, "an unplaceable berry must be reported")
        self.assertIn("!checked", self.tracker.unplaceable_notices[0])

    def test_an_unplaceable_pickup_is_held_before_it_is_reported(self):
        berry = self.berry
        foreign = next(r for r in self.elsewhere if chest_berries.chest_for(r, berry) is None)
        self.world.bag[berry] = 0
        self.run_polls([foreign])
        self.world.bag[berry] = 1
        self.run_polls([foreign] * 30)                  # 3s -- past the debounce, inside the hold
        self.assertTrue(self.tracker.pending, "it must be carried, not discarded on the spot")
        self.assertEqual([], self.tracker.unplaceable_notices)

    def test_the_client_prints_the_notices(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / "Client.py").read_text(encoding="utf-8")
        self.assertIn("unplaceable_notices", source)


class TestTheRegressionIsNamed(unittest.TestCase):
    def test_the_room_is_captured_at_the_rise_not_at_the_credit(self):
        import pathlib
        source = pathlib.Path(rc.__file__).read_text(encoding="utf-8")
        self.assertIn("self._pending_room[berry_id] = room_id", source)
        self.assertIn('"rise_seq"', source)

    def test_the_history_window_is_bounded(self):
        self.assertGreater(rc.ChestBerryTracker._ROOM_HISTORY_SECONDS, 0)
        self.assertLessEqual(rc.ChestBerryTracker._ROOM_HISTORY_SECONDS, 60.0)


if __name__ == "__main__":
    unittest.main()
