"""ADDENDUM 458 (2026-10-10) -- the HQ Lab hold no longer lets go on a blind tick.

The HQ Lab guard is meant to hold the byte at 0x16, but it let go: the byte reached 0x19 before the Krane Memos had
been received.

The arming was recomputed every tick from `machine_part_obtained`, which reads False until the server has re-sent the
slot's items after a (re)connect. That tick RELEASED the hold, and the release gave back the byte it had pulled the
lab back from (0x19, persisted from the earlier session). Now the give-back needs the memos, the hold stays latched
once armed, and nothing runs until the server's full item list has arrived.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from .. import Client
from .. import ram_client as rc
from ..game_data import chest_regions

LAB_ROOM = next(room for room, region in chest_regions.ROOM_TO_REGION.items() if region == "Pokemon HQ Lab")
BASE = 0x80479000
SOURCE = Path(Client.__file__).read_text(encoding="utf-8")


class _Story:
    def __init__(self, value: int) -> None:
        self.value = value
        self.writes: "list[int]" = []

    def poke(self, _base: int, value: int) -> bool:
        self.value = value
        self.writes.append(value)
        return True


class TestTheGiveBack(unittest.TestCase):
    def setUp(self) -> None:
        self.story = _Story(0x16)
        patcher = mock.patch.object(rc, "poke_story_byte", side_effect=self.story.poke)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_an_unarmed_tick_without_the_memos_gives_nothing_back(self) -> None:
        """The failure seen in play: lab at our 0x16, 0x19 remembered, hold not armed for a tick, memos NOT handed over."""
        hold = rc.LabMemoStoryHold(armed=False, declined_value=0x19)
        self.assertIsNone(hold.poll(BASE, 0x16, LAB_ROOM, memos_received=False))
        self.assertEqual([], self.story.writes)
        self.assertEqual(0x19, hold.declined_value, "still owed, for when the memos really come")

    def test_the_handover_still_gives_it_back(self) -> None:
        hold = rc.LabMemoStoryHold(armed=False, declined_value=0x19)
        note = hold.poll(BASE, 0x16, LAB_ROOM, memos_received=True)
        self.assertEqual([0x19], self.story.writes)
        self.assertIn("0x19", note)
        self.assertIsNone(hold.declined_value)


class TestTheClientWiring(unittest.TestCase):
    def body(self) -> str:
        return SOURCE.split("async def check_lab_memo_hold", 1)[1].split("\nasync def ", 1)[0]

    def test_waits_for_the_server_items(self) -> None:
        body = self.body()
        self.assertLess(body.index("if not _lab_hold_inputs_ready(ctx):"), body.index("memos = lab_memos_received(ctx)"))
        self.assertIn('elif cmd == "ReceivedItems":', SOURCE)
        self.assertIn("self._items_synced = True", SOURCE)

    def test_latched_until_the_memos(self) -> None:
        body = self.body()
        self.assertIn("machine_part_obtained(ctx) or hold.declined_value is not None or hold.latched", body)
        self.assertIn("memos_received=memos", body)
        self.assertIn('"lab_memo_hold_latched": self.lab_memo_hold.latched', SOURCE)

    def test_readiness(self) -> None:
        import time
        ctx = mock.Mock(spec=["_items_synced", "slot", "_items_sync_deadline"])
        ctx._items_synced, ctx.slot, ctx._items_sync_deadline = False, 1, time.monotonic() + 60
        self.assertFalse(Client._lab_hold_inputs_ready(ctx))
        ctx._items_synced = True
        self.assertTrue(Client._lab_hold_inputs_ready(ctx))
        ctx._items_synced, ctx._items_sync_deadline = False, time.monotonic() - 1
        self.assertTrue(Client._lab_hold_inputs_ready(ctx), "nothing received yet: the empty list is real")
        ctx.slot = None
        self.assertFalse(Client._lab_hold_inputs_ready(ctx))


if __name__ == "__main__":
    unittest.main()
