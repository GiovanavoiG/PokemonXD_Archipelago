"""ADDENDUM 464 (2026-10-11) -- the HQ Lab hold waits for 0x0F and Krane Memos 1-2.

The Machine Part clamp activated too early. The clamp to 0x16 now applies only once the HQ Lab story byte has
reached 0x0F, the Machine Part is held, and both Krane Memo 1 and Memo 2 have been received.
"""
from __future__ import annotations

import asyncio
import types
import unittest
from pathlib import Path
from unittest import mock

from .. import Client
from .. import ram_client as rc
from ..game_data import chest_regions

LAB_ROOM = next(room for room, region in chest_regions.ROOM_TO_REGION.items() if region == "Pokemon HQ Lab")
OTHER_ROOM = next(room for room, region in chest_regions.ROOM_TO_REGION.items() if region == "Gateon Port")
BASE = 0x80479000


class TestTheLatch(unittest.TestCase):
    def test_the_constants(self):
        self.assertEqual(0x0F, rc.LAB_MEMO_ARM_FLOOR)
        self.assertEqual((1, 2), rc.LAB_MEMO_ARM_MEMOS)

    def test_below_0f_is_not_enough(self):
        hold = rc.LabMemoStoryHold()
        self.assertFalse(hold.note_lab_progress(LAB_ROOM, 0x0D, None))
        self.assertFalse(hold.lab_reached)

    def test_0f_in_the_lab_at_all_latches_even_the_bump(self):
        hold = rc.LabMemoStoryHold()
        self.assertTrue(hold.note_lab_progress(LAB_ROOM, 0x0F, None))
        self.assertFalse(hold.note_lab_progress(LAB_ROOM, 0x0D, None), "latched once, stays latched")
        self.assertTrue(hold.lab_reached)

    def test_another_areas_byte_does_not_count(self):
        hold = rc.LabMemoStoryHold()
        self.assertFalse(hold.note_lab_progress(OTHER_ROOM, 0x19, None))

    def test_the_labs_mark_counts_from_anywhere(self):
        hold = rc.LabMemoStoryHold()
        self.assertTrue(hold.note_lab_progress(OTHER_ROOM, 0x19, 0x10))


def _ctx(*, room=LAB_ROOM, travel=True):
    ctx = types.SimpleNamespace()
    ctx.lab_memo_hold = rc.LabMemoStoryHold()
    ctx.block_base = BASE
    ctx.area_story_memory = rc.AreaStoryByteMemory()
    ctx.randomize_travel_locations = travel
    ctx.story_progress = types.SimpleNamespace(high_water=None)
    ctx.room_tracker = types.SimpleNamespace(current=room)
    ctx.saves = 0

    def save():
        ctx.saves += 1
    ctx._save_local_state = save
    return ctx


class TestTheClient(unittest.TestCase):
    def setUp(self):
        self.story = {"value": 0x0D, "writes": []}
        self.memos_1_2 = False
        self.machine_part = True

        def poke(_base, value):
            self.story["value"] = value
            self.story["writes"].append(value)
            return True
        p = mock.patch.multiple(rc, poke_story_byte=mock.DEFAULT, read_story_byte=mock.DEFAULT)
        mocks = p.start()
        self.addCleanup(p.stop)
        mocks["poke_story_byte"].side_effect = poke
        mocks["read_story_byte"].side_effect = lambda _b: self.story["value"]

        def memos(_ctx, numbers=None):
            return self.memos_1_2 if numbers == rc.LAB_MEMO_ARM_MEMOS else False   # 3-5 never handed over here
        patches = [mock.patch.object(Client, "_lab_hold_inputs_ready", return_value=True),
                   mock.patch.object(Client, "lab_memos_received", side_effect=memos),
                   mock.patch.object(Client, "machine_part_obtained", side_effect=lambda _c: self.machine_part),
                   mock.patch.object(Client, "_note"), mock.patch.object(Client, "_save_story_write_log")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tick(self, ctx):
        asyncio.run(Client.check_lab_memo_hold(ctx))

    def test_machine_part_early_does_not_clamp_a_0x0d_lab(self):
        """The report: the Machine Part arrives while the lab is still at 0x0D."""
        ctx = _ctx()
        self.tick(ctx)
        self.assertFalse(ctx.lab_memo_hold.armed)
        self.assertEqual([], self.story["writes"])
        self.assertNotIn(rc.LAB_MEMO_HOLD_AREA, ctx.area_story_memory.forced_floor_by_region)

    def test_0f_without_memos_1_and_2_does_not_clamp(self):
        ctx = _ctx()
        self.story["value"] = 0x0F
        self.tick(ctx)
        self.assertTrue(ctx.lab_memo_hold.lab_reached)
        self.assertFalse(ctx.lab_memo_hold.armed)
        self.assertEqual([], self.story["writes"], "the memo 1-2 handover would be skipped")

    def test_0f_then_memos_1_and_2_clamps(self):
        ctx = _ctx()
        self.story["value"] = 0x0F
        self.tick(ctx)
        self.memos_1_2 = True
        self.story["value"] = 0x10
        self.tick(ctx)
        self.assertTrue(ctx.lab_memo_hold.armed)
        # The hold only pulls the lab DOWN to 0x16: a lab still below it is left to the story.
        self.assertEqual([], self.story["writes"])
        self.assertEqual(rc.LAB_MEMO_HOLD_BYTE, ctx.area_story_memory.forced_floor_by_region[rc.LAB_MEMO_HOLD_AREA])
        self.assertGreaterEqual(ctx.saves, 1, "the latch is persisted")
        self.story["value"] = rc.LAB_MEMO_HOLD_BYTE + 1
        self.tick(ctx)
        self.assertEqual([rc.LAB_MEMO_HOLD_BYTE], self.story["writes"])

    def test_memos_1_and_2_without_0f_does_not_clamp(self):
        ctx = _ctx(room=OTHER_ROOM)
        self.memos_1_2 = True
        self.tick(ctx)
        self.assertFalse(ctx.lab_memo_hold.armed)

    def test_no_machine_part_no_clamp(self):
        ctx = _ctx()
        self.story["value"] = 0x10
        self.memos_1_2, self.machine_part = True, False
        self.tick(ctx)
        self.assertTrue(ctx.lab_memo_hold.lab_reached)
        self.assertFalse(ctx.lab_memo_hold.armed)
        self.assertEqual([], self.story["writes"])

    def test_vanilla_travel_uses_the_story_high_water(self):
        ctx = _ctx(room=OTHER_ROOM, travel=False)
        ctx.story_progress.high_water = 0x15
        self.memos_1_2 = True
        self.tick(ctx)
        self.assertTrue(ctx.lab_memo_hold.lab_reached)
        self.assertTrue(ctx.lab_memo_hold.armed)


class TestPersisted(unittest.TestCase):
    def test_saved_and_loaded(self):
        source = Path(Client.__file__).read_text(encoding="utf-8")
        self.assertIn('"lab_memo_lab_reached": self.lab_memo_hold.lab_reached', source)
        self.assertIn('self.lab_memo_hold.lab_reached = bool(slot_state.get("lab_memo_lab_reached", False))', source)


if __name__ == "__main__":
    unittest.main()
