"""ADDENDUM 476 (2026-10-13) -- Zook beaten at the Cipher Key Lair moves the Lair two steps on.

Player: "when zook is defeated at Cipher Key Lair, can we move the story byte and floor up two steps so that we
don't have to fight him again".
"""
from __future__ import annotations

import pathlib
import unittest

from .. import ram_client as rc
from ..game_data import story_bytes as sb

CLIENT = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
LAIR = "Cipher Key Lair"


class TestTheBump(unittest.TestCase):
    def test_zooks_byte_goes_two_steps_past_the_floor(self) -> None:
        bump = sb.live_bump_for(LAIR, 0x65, travel_shuffle=True, scooter_shuffle=False)
        self.assertIsNotNone(bump)
        self.assertEqual(0x66, bump.becomes)
        self.assertTrue(bump.banks_trigger)
        self.assertEqual(800, sb.story_value_for_byte(sb.AREA_ENTRY_FLOOR_OVERRIDES[LAIR]))
        self.assertEqual(820, sb.story_value_for_byte(0x66), "two story steps above the 800 entry floor")
        self.assertTrue(sb.byte_is_reachable(0x66))

    def test_not_before_zook_and_not_in_vanilla_travel(self) -> None:
        self.assertIsNone(sb.live_bump_for(LAIR, 0x64, travel_shuffle=True, scooter_shuffle=False))
        self.assertIsNone(sb.live_bump_for(LAIR, 0x66, travel_shuffle=True, scooter_shuffle=False))
        self.assertIsNone(sb.live_bump_for(LAIR, 0x65, travel_shuffle=False, scooter_shuffle=True))
        self.assertIsNone(sb.live_bump_for("Snagem Hideout", 0x65, travel_shuffle=True, scooter_shuffle=False))

    def test_the_transition_it_follows(self) -> None:
        lands = {t.after: t.what for t in sb.TRANSITIONS}
        self.assertIn("Zook defeated", lands[0x65])


class TestTheReturnVisit(unittest.TestCase):
    def test_entered_past_him_once_beaten(self) -> None:
        memory = rc.AreaStoryByteMemory()
        self.assertEqual(0x64, memory.target_for(LAIR), "before: his fight is still staged")
        memory.highest_by_region[LAIR] = 0x65
        self.assertEqual(0x66, memory.target_for(LAIR))

    def test_a_later_mark_still_wins(self) -> None:
        memory = rc.AreaStoryByteMemory()
        memory.highest_by_region[LAIR] = 0x69
        self.assertEqual(0x69, memory.target_for(LAIR))

    def test_the_client_banks_the_trigger(self) -> None:
        self.assertIn('getattr(_bump, "banks_trigger", False)', CLIENT)
        self.assertIn("ctx.area_story_memory.highest_by_region[current_region] = ctx.live_story_bumper.last_trigger_byte",
                      CLIENT)

    def test_the_bumper_reports_it(self) -> None:
        written = []
        original = rc.write_story_value if hasattr(rc, "write_story_value") else None
        bumper = rc.LiveStoryByteBumper()
        import unittest.mock as m
        with m.patch.object(rc, "write_bytes", side_effect=lambda a, d: written.append((a, d))), \
                m.patch.object(rc, "read_bytes", side_effect=lambda a, n: bytes(n)):
            result = bumper.poll(0x80479000, LAIR, 0x65, True, False)
        self.assertIsNotNone(result)
        self.assertEqual(0x66, result[0])
        self.assertEqual(0x65, bumper.last_trigger_byte)
        self.assertTrue(bumper.last_bump.banks_trigger)


if __name__ == "__main__":
    unittest.main()
