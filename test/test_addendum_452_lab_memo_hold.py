"""ADDENDUM 452 (2026-10-09) -- the HQ Lab is held at 0x16 until Krane Memos 3-5 are handed over.

When the Machine Part is gained, HQ Lab's floor is set to 0x16 and HELD THERE NO MATTER WHAT until Krane Memos 3, 4
and 5 have been received.
"""
from __future__ import annotations

import struct
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from .. import Client
from .. import ram_client as rc
from ..game_data import chest_regions

LAB_ROOM = next(room for room, region in chest_regions.ROOM_TO_REGION.items() if region == "Pokemon HQ Lab")
GATEON_ROOM = next(room for room, region in chest_regions.ROOM_TO_REGION.items() if region == "Gateon Port")
BASE = 0x80479000


class _Story:
    def __init__(self, value: int) -> None:
        self.value = value
        self.writes: "list[int]" = []

    def poke(self, _base: int, value: int) -> bool:
        self.value = value
        self.writes.append(value)
        return True


class TestTheHold(unittest.TestCase):
    def setUp(self) -> None:
        self.story = _Story(0x17)
        patcher = mock.patch.object(rc, "poke_story_byte", side_effect=self.story.poke)
        patcher.start()
        self.addCleanup(patcher.stop)

    def poll(self, hold, room=LAB_ROOM):
        return hold.poll(BASE, self.story.value, room)

    def test_armed_pins_the_lab_at_0x16_from_above_and_below(self) -> None:
        hold = rc.LabMemoStoryHold(armed=True)
        self.poll(hold)
        self.assertEqual(0x16, self.story.value)
        self.assertEqual(0x17, hold.declined_value)
        self.story.value = 0x0F
        self.poll(hold)
        self.assertEqual(0x16, self.story.value, "no matter what -- a lower byte is raised too")
        self.story.value = 0x16
        writes = len(self.story.writes)
        self.poll(hold)
        self.assertEqual(writes, len(self.story.writes), "already 0x16: nothing written")

    def test_only_in_the_lab(self) -> None:
        hold = rc.LabMemoStoryHold(armed=True)
        self.poll(hold, room=GATEON_ROOM)
        self.assertEqual(0x17, self.story.value)
        self.assertEqual([], self.story.writes)

    def test_release_gives_back_the_held_step_once(self) -> None:
        hold = rc.LabMemoStoryHold(armed=True)
        self.poll(hold)                       # 0x17 -> 0x16
        hold.armed = False
        self.poll(hold)
        self.assertEqual(0x17, self.story.value)
        self.assertIsNone(hold.declined_value)
        self.poll(hold)
        self.assertEqual([0x16, 0x17], self.story.writes)

    def test_unarmed_does_nothing(self) -> None:
        hold = rc.LabMemoStoryHold(armed=False)
        self.poll(hold)
        self.assertEqual([], self.story.writes)


class TestTheHoverTarget(unittest.TestCase):
    def test_forced_floor_outranks_the_lab_mark(self) -> None:
        memory = rc.AreaStoryByteMemory()
        memory.highest_by_region["Pokemon HQ Lab"] = 0x30
        self.assertEqual(0x30, memory.target_for("Pokemon HQ Lab"))
        memory.forced_floor_by_region["Pokemon HQ Lab"] = 0x16
        self.assertEqual(0x16, memory.target_for("Pokemon HQ Lab"))
        self.assertNotEqual(0x16, memory.target_for("Agate Village"))


class TestTheClientArmsIt(unittest.TestCase):
    def ctx(self, shuffle=True, items=(), checked=(), awarded=()) -> SimpleNamespace:
        names = {v: k for k, v in Client.ITEM_ID_TO_NAME.items()}
        return SimpleNamespace(
            key_item_shuffle=shuffle,
            items_received=[SimpleNamespace(item=names[i]) for i in items],
            checked_locations={Client.LOCATION_NAME_TO_ID[rc.krane_memo_location_name(n)] for n in checked},
            krane_memo_tracker=SimpleNamespace(awarded=set(awarded)),
            area_story_memory=rc.AreaStoryByteMemory(),
            story_progress=SimpleNamespace(high_water=-1),
        )

    def test_machine_part(self) -> None:
        self.assertFalse(Client.machine_part_obtained(self.ctx()))
        self.assertTrue(Client.machine_part_obtained(self.ctx(items=("Machine Part",))))
        vanilla = self.ctx(shuffle=False)
        self.assertFalse(Client.machine_part_obtained(vanilla))
        vanilla.area_story_memory.highest_by_region["Gateon Port"] = 0x16
        self.assertTrue(Client.machine_part_obtained(vanilla))

    def test_memos(self) -> None:
        self.assertFalse(Client.lab_memos_received(self.ctx(checked=(3, 4))))
        self.assertTrue(Client.lab_memos_received(self.ctx(checked=(3, 4, 5))))
        self.assertTrue(Client.lab_memos_received(self.ctx(checked=(3,), awarded=(4, 5))))
        self.assertFalse(Client.lab_memos_received(self.ctx(checked=(1, 2))))

    def test_runs_after_every_other_story_writer(self) -> None:
        source = Path(Client.__file__).read_text(encoding="utf-8")
        loop = source[source.index("await check_scooter_hold(ctx)"):]
        order = [loop.index(name) for name in ("check_music_disc_hold", "check_machine_part_hold",
                                                "check_story_byte_override", "check_area_story_memory",
                                                "check_krane_memos", "check_lab_memo_hold")]
        self.assertEqual(sorted(order), order)
        self.assertIn('"lab_memo_hold_declined": self.lab_memo_hold.declined_value', source)


if __name__ == "__main__":
    unittest.main()
