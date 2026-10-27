"""Perr's Machine Part check: Gateon's own story value, never a map hover's."""
from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

from .. import Client
from .. import ram_client as rc


def _ctx(travel: bool, gateon: "int | None", story: int, high: int):
    location_id = Client.LOCATION_NAME_TO_ID[Client.PERR_MACHINE_PART_LOCATION_NAME]
    memory = SimpleNamespace(highest_by_region={} if gateon is None else {"Gateon Port": gateon})
    return SimpleNamespace(block_base=0x80479300, checked_locations=set(), randomize_travel_locations=travel,
                           story_progress=SimpleNamespace(high_water=high),
                           machine_part_hold=SimpleNamespace(declined_value=None),
                           area_story_memory=memory, _story=story, _id=location_id)


def _sent(ctx) -> bool:
    sent = []

    async def fake_send(_ctx, names):
        sent.extend(names)
    with mock.patch.object(rc, "read_story_byte", lambda _base: ctx._story), \
            mock.patch.object(Client, "_send_checks", fake_send):
        asyncio.run(Client.check_perr_machine_part(ctx))
    return Client.PERR_MACHINE_PART_LOCATION_NAME in sent


class TestLocationShuffle(unittest.TestCase):
    def test_a_hover_past_it_sends_nothing(self):
        # Gateon is still before the scene; the live byte and its high-water mark carry another area's value.
        self.assertFalse(_sent(_ctx(True, 0x10, 0x40, 0x40)))

    def test_no_gateon_value_yet_sends_nothing(self):
        self.assertFalse(_sent(_ctx(True, None, 0x40, 0x40)))

    def test_gateon_reaching_it_sends(self):
        self.assertTrue(_sent(_ctx(True, Client.PERR_MACHINE_PART_STORY_BYTE, 0x05, 0x05)))


class TestVanillaTravel(unittest.TestCase):
    def test_the_story_byte_is_gateons(self):
        self.assertTrue(_sent(_ctx(False, None, Client.PERR_MACHINE_PART_STORY_BYTE, 0)))

    def test_before_it_sends_nothing(self):
        self.assertFalse(_sent(_ctx(False, None, 0x10, 0x10)))


if __name__ == "__main__":
    unittest.main()
