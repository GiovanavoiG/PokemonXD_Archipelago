"""The save clock feeds the save-block trust: nothing reads the story, travel or flags while a save or load is under
way, or right after another save's data comes in."""
from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace

from .. import Client
from .. import ram_client as rc


def _reading(playtime: float, count: int = 1, busy: bool = False) -> rc.SaveClockReading:
    return rc.SaveClockReading(playtime, count, busy)


class TestContinuity(unittest.TestCase):
    def test_ordinary_play_follows_on(self):
        c = rc.SaveClockContinuity()
        for wall, at in enumerate((100.0, 101.0, 102.2, 101.9, 106.0)):
            self.assertFalse(c.poll(_reading(at), wall=wall), at)
        self.assertEqual(0, c.breaks)

    def test_going_back_is_a_break(self):
        c = rc.SaveClockContinuity()
        c.poll(_reading(500.0), wall=0)
        self.assertTrue(c.poll(_reading(200.0), wall=1))
        self.assertFalse(c.poll(_reading(201.0), wall=2), "only the one tick")

    def test_jumping_ahead_is_a_break(self):
        c = rc.SaveClockContinuity()
        c.poll(_reading(100.0), wall=0)
        self.assertTrue(c.poll(_reading(900.0), wall=1))      # a later save loaded
        self.assertFalse(c.poll(_reading(901.0), wall=2))

    def test_a_long_gap_allows_more_play(self):
        c = rc.SaveClockContinuity()
        c.poll(_reading(100.0), wall=0)
        self.assertFalse(c.poll(_reading(300.0), wall=60), "a minute away at up to 4x speed")

    def test_busy_readings_are_skipped(self):
        c = rc.SaveClockContinuity()
        c.poll(_reading(500.0), wall=0)
        self.assertFalse(c.poll(_reading(80.0, busy=True), wall=1))   # the card's file, mid-dialog
        self.assertFalse(c.poll(_reading(502.0), wall=2), "the dialog closed and the live data is back")
        self.assertEqual(0, c.breaks)

    def test_the_card_file_left_behind_is_caught(self):
        c = rc.SaveClockContinuity()
        c.poll(_reading(500.0), wall=0)
        c.poll(_reading(80.0, busy=True), wall=1)
        self.assertTrue(c.poll(_reading(80.0), wall=2))


def _ctx():
    return SimpleNamespace(clock_continuity=rc.SaveClockContinuity(), save_distrust={"saving": 0, "clock jump": 0})


class TestTheGate(unittest.TestCase):
    def test_saving_holds_trust(self):
        ctx = _ctx()
        self.assertFalse(Client.save_clock_allows_trust(ctx, _reading(10.0, busy=True)))
        self.assertEqual(1, ctx.save_distrust["saving"])

    def test_a_jump_holds_trust(self):
        ctx = _ctx()
        self.assertTrue(Client.save_clock_allows_trust(ctx, _reading(10.0)))
        self.assertFalse(Client.save_clock_allows_trust(ctx, _reading(5000.0)))
        self.assertEqual(1, ctx.save_distrust["clock jump"])

    def test_an_unreadable_clock_leaves_it_to_the_block_gate(self):
        self.assertTrue(Client.save_clock_allows_trust(_ctx(), None))

    def test_a_held_tick_restarts_the_settle_count(self):
        trust = rc.BlockTrust()
        for _ in range(3):
            trust.poll(True)
        self.assertTrue(trust.poll(True))
        self.assertFalse(trust.poll(True & False))
        self.assertEqual([False, False, True], [trust.poll(True) for _ in range(3)])


class TestTheLoop(unittest.TestCase):
    def setUp(self):
        src = inspect.getsource(Client)
        start = src.index("save_clock = read_save_clock_safely(ctx)")
        self.loop = src[start:start + 4000]

    def test_both_signals_feed_the_trust_every_tick(self):
        head = self.loop[:self.loop.index("await flush_pending_checks(ctx)")]
        self.assertIn("block_is_stable = ctx.block_trust.poll(", head)
        self.assertIn("ctx.block_stability.poll(ctx.block_base))\n", head)
        # `&`, not `and`: the continuity tracker has to see every reading.
        self.assertIn("& save_clock_allows_trust(ctx, save_clock)", head)

    def test_the_timeline_uses_the_same_reading(self):
        self.assertIn("check_save_clock(ctx, block_is_stable, save_clock)", self.loop)


class TestTheMargin(unittest.TestCase):
    def test_five_seconds(self):
        self.assertEqual(5.0, rc.SaveTimeline.UNKNOWN_SAVE_MIN_ALLOWANCE)


if __name__ == "__main__":
    unittest.main()
