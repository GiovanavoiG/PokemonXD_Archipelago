"""Items a reloaded save no longer holds are delivered again, judged by the game's play time."""
from __future__ import annotations

import inspect
import struct
import unittest
from types import SimpleNamespace
from unittest import mock

from .. import Client
from .. import ram_client as rc
from .local_dumps import DUMPS


def _reading(playtime: float, count: int = 1, busy: bool = False) -> rc.SaveClockReading:
    return rc.SaveClockReading(playtime, count, busy)


class TestTheReader(unittest.TestCase):
    def _from_dump(self, name: str):
        path = DUMPS / name
        if not path.is_file():
            self.skipTest("the MEM1 dumps are not on this machine")
        mem = path.read_bytes()

        def read(address, length):
            off = address - rc.MEM1_START
            return mem[off:off + length]
        with mock.patch.object(rc, "read_bytes", read):
            return rc.read_save_clock()

    def test_it_reads_play_time_and_the_save_count(self) -> None:
        reading = self._from_dump("loc_kaminko.bin")
        self.assertAlmostEqual(30687.9, reading.playtime, places=1)
        self.assertEqual(21, reading.save_count)
        self.assertFalse(reading.busy)

    def test_play_time_rises_through_a_session(self) -> None:
        times = [self._from_dump(n).playtime for n in ("vis_dump1_pyrite.bin", "vis_dump2_cavespot.bin",
                                                       "vis_dump3_snagem.bin", "vis_dump5_agate.bin")]
        self.assertEqual(sorted(times), times)

    def test_a_running_save_dialog_or_memcard_task_is_busy(self) -> None:
        mem = {}

        def read(address, length):
            return mem.get(address, b"\x00" * length)[:length]
        mem[rc.SAVEDATA_NOW_POINTER] = struct.pack(">I", 0x80479200)
        mem[0x80479200 + rc.SAVEDATA_PLAYTIME_OFFSET] = struct.pack(">d", 100.0)
        mem[rc.MEMCARD_WORK_POINTER] = struct.pack(">I", 0x80478BC8)
        with mock.patch.object(rc, "read_bytes", read):
            self.assertFalse(rc.read_save_clock().busy)
            mem[rc.SAVE_MENU_POINTER] = struct.pack(">I", 0x81000000)
            self.assertTrue(rc.read_save_clock().busy)
            mem[rc.SAVE_MENU_POINTER] = struct.pack(">I", 0)
            mem[0x80478BC8] = struct.pack(">I", 4)
            self.assertTrue(rc.read_save_clock().busy)

    def test_nonsense_reads_as_unreadable(self) -> None:
        mem = {rc.SAVEDATA_NOW_POINTER: struct.pack(">I", 0x80479200),
               0x80479200 + rc.SAVEDATA_PLAYTIME_OFFSET: struct.pack(">d", float("nan"))}
        with mock.patch.object(rc, "read_bytes", lambda a, n: mem.get(a, b"\x00" * n)[:n]):
            self.assertIsNone(rc.read_save_clock())


class TestTheTimeline(unittest.TestCase):
    def test_a_reload_takes_back_what_came_after_the_save(self) -> None:
        t = rc.SaveTimeline()
        t.poll(_reading(100.0, 1), True, wall=0)
        t.stamp(0)
        t.poll(_reading(110.0, 1), True, wall=10)
        t.poll(_reading(112.0, 1, busy=True), True, wall=12)      # saving
        t.poll(_reading(130.0, 2), True, wall=30)                 # saved: #2 at 110
        self.assertEqual(110.0, t.saves[2])
        t.poll(_reading(140.0, 2), True, wall=40)
        t.stamp(1)
        t.poll(_reading(200.0, 2), True, wall=100)
        t.stamp(2)
        point = t.poll(_reading(111.0, 2), True, wall=500)        # save #2 loaded, much later
        self.assertEqual(110.0, point)
        self.assertEqual([1, 2], t.taken_back(point))
        self.assertEqual({0}, set(t.stamps))

    def test_a_reload_nobody_saw_saved_errs_towards_sending_twice(self) -> None:
        t = rc.SaveTimeline()
        t.poll(_reading(1000.0, 3), True, wall=0)
        t.stamp(0)
        t.poll(_reading(1001.0, 3), True, wall=1)
        point = t.poll(_reading(900.0, 3), True, wall=2)          # a save state from before anything we saw
        self.assertLessEqual(point, 900.0 - t.UNKNOWN_SAVE_MIN_ALLOWANCE)
        self.assertEqual([0], t.taken_back(point))

    def test_play_time_going_forward_takes_nothing_back(self) -> None:
        t = rc.SaveTimeline()
        for wall, at in enumerate((10.0, 11.0, 12.5, 12.0)):     # small read jitter is not a reload
            self.assertIsNone(t.poll(_reading(at, 1), True, wall=wall))
        self.assertEqual(0, t.rewinds)

    def test_readings_while_saving_or_untrusted_change_nothing(self) -> None:
        t = rc.SaveTimeline()
        t.poll(_reading(500.0, 4), True, wall=0)
        self.assertIsNone(t.poll(_reading(80.0, 2, busy=True), True, wall=1))    # the card's file, mid-dialog
        self.assertTrue(t.holding())
        self.assertIsNone(t.poll(_reading(80.0, 2), False, wall=2))              # block still settling
        self.assertTrue(t.holding(), "gone back but not judged: nothing new is written yet")
        self.assertEqual(500.0, t.last_playtime)
        self.assertEqual(0, t.rewinds)
        self.assertIsNone(t.poll(_reading(501.0, 4), False, wall=3))             # it was the dialog's copy
        self.assertFalse(t.holding())
        self.assertEqual(0, t.rewinds)

    def test_a_reload_keeps_what_came_before_the_loaded_time(self) -> None:
        """Reload save #5, get the lost items back, play on, then load a save state made after they arrived: only
        what came after the state goes back, not everything since save #5."""
        t = rc.SaveTimeline()
        t.poll(_reading(1000.0, 5), True, wall=0)                 # save #5 is at about 1000
        t.poll(_reading(1100.0, 5), True, wall=100)
        for i in range(10):
            t.stamp(i)                                            # ten items at 1100
        point = t.poll(_reading(1000.0, 5), True, wall=110)       # save #5 reloaded
        self.assertEqual(list(range(10)), t.taken_back(point))
        t.poll(_reading(1002.0, 5), True, wall=112)
        for i in range(10):
            t.stamp(i)                                            # sent again, at 1002
        t.poll(_reading(2935.0, 5), True, wall=2045)              # a save state is made here
        t.poll(_reading(2980.0, 5), True, wall=2090)
        t.stamp(10)                                               # the Timer Ball
        t.poll(_reading(2984.0, 5), True, wall=2094)
        point = t.poll(_reading(2935.0, 5), True, wall=2100)      # the state loaded
        self.assertEqual([10], t.taken_back(point))

    def test_writes_after_a_load_are_stamped_in_the_loaded_time(self) -> None:
        t = rc.SaveTimeline()
        t.poll(_reading(2000.0, 5), True, wall=0)
        t.poll(_reading(1500.0, 5), False, wall=1)                # a state loaded; the block is still settling
        self.assertTrue(t.holding())
        t.poll(_reading(1501.0, 5), True, wall=2)                 # judged
        self.assertFalse(t.holding())
        t.stamp(0)
        self.assertEqual(1501.0, t.stamps[0])

    def test_stamps_follow_the_play_time_while_the_block_settles(self) -> None:
        t = rc.SaveTimeline()
        t.poll(_reading(100.0, 1), True, wall=0)
        t.poll(_reading(160.0, 1), False, wall=60)
        t.stamp(0)
        self.assertEqual(160.0, t.stamps[0], "not the last trusted reading's 100")
        point = t.poll(_reading(130.0, 1), True, wall=70)
        self.assertEqual([0], t.taken_back(point))

    def test_the_save_hold_has_a_ceiling(self) -> None:
        t = rc.SaveTimeline()
        t.poll(_reading(1.0, 0, busy=True), True)
        self.assertTrue(t.holding())
        t.busy_since -= t.BUSY_HOLD_CEILING_SECONDS + 1
        self.assertFalse(t.holding())

    def test_it_round_trips(self) -> None:
        t = rc.SaveTimeline()
        t.poll(_reading(100.0, 1), True, wall=5)
        t.stamp(7)
        t.saves[1] = 50.0
        u = rc.SaveTimeline()
        u.load_json(t.to_json())
        self.assertEqual((100.0, 1, 5.0, {1: 50.0}, {7: 100.0}),
                         (u.last_playtime, u.last_count, u.last_wall, u.saves, u.stamps))
        u.load_json({"saves": {"x": 1}})
        self.assertEqual({}, u.saves)


class TestTheClient(unittest.TestCase):
    def _ctx(self):
        received = [SimpleNamespace(item=Client.ITEM_NAME_TO_ID["Potion"] if hasattr(Client, "ITEM_NAME_TO_ID")
                                    else 0) for _ in range(3)]
        ctx = SimpleNamespace(block_base=0x80479300, items_received=received, given_item_indices={0, 1, 2},
                              save_timeline=rc.SaveTimeline(), _delivery_pending_baseline={}, _delivery_confirm_streak={},
                              _delivery_peak={}, _delivery_counts_pc={}, _delivery_companion_pending={},
                              _delivery_pc_announced=set(), _delivery_warned_indices=set(),
                              _delivery_write_full_warned=set(), saved=0)
        ctx._save_local_state = lambda: setattr(ctx, "saved", ctx.saved + 1)
        return ctx

    def test_a_reload_puts_the_lost_items_back_in_the_queue(self) -> None:
        ctx = self._ctx()
        readings = iter([_reading(100.0, 1), _reading(200.0, 1), _reading(150.0, 1)])
        with mock.patch.object(rc, "read_save_clock", lambda: next(readings)):
            Client.check_save_clock(ctx, True)
            ctx.save_timeline.stamp(0)
            Client.check_save_clock(ctx, True)
            ctx.save_timeline.stamp(1)
            ctx.save_timeline.stamp(2)
            ctx._delivery_pending_baseline[2] = 5
            Client.check_save_clock(ctx, True)
        self.assertEqual({0}, ctx.given_item_indices)
        self.assertEqual({}, ctx._delivery_pending_baseline)
        self.assertEqual(1, ctx.saved)

    def test_give_items_waits_for_a_save_and_stamps_its_writes(self) -> None:
        body = inspect.getsource(Client.give_items)
        self.assertIn("saving = ctx.save_timeline.holding()", body)
        self.assertGreaterEqual(body.count("ctx.save_timeline.stamp(idx)"), 3)
        self.assertIn("ctx.save_timeline.stamp(idx)", inspect.getsource(Client.force_deliver_pending_items))

    def test_it_runs_before_give_items(self) -> None:
        src = inspect.getsource(Client)
        self.assertIn("check_save_clock(ctx, block_is_stable, save_clock)\n                    await give_items(ctx)", src)


if __name__ == "__main__":
    unittest.main()
