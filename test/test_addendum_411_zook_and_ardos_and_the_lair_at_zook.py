"""ADDENDUM 411 (2026-10-03) -- Ardos #1 and Zook #1 send each other, and the Key Lair enters at Zook.

The Key Lair's entry value (820) drops another step so that it sits at Zook, so he can be fought there. Ardos
#1 firing fires Zook #1, and vice versa.
"""
from __future__ import annotations

import struct
import unittest
from pathlib import Path
from unittest import mock

from BaseClasses import LocationProgressType

from . import PokemonXDTestBase
from .. import locations as L, ram_client as rc
from ..game_data import missable_autosend as ma, missable_trainers as mt, story_bytes as sb, trainer_roster as tr

ZOOK1, ZOOK2, ARDOS1, ARDOS2 = "Defeat - Zook #1", "Defeat - Zook #2", "Defeat - Ardos #1", "Defeat - Ardos #2"
LAIR = "Cipher Key Lair"
CLIENT = (Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")


class TestTheLinkIsRetired(unittest.TestCase):
    """SUPERSEDED by ADDENDUM 436. The two fights where the player does not act are Ardos vs Zook in Gateon and
    Zook vs Biden in the Key Lair. Those fights do NOT send a check, and the #1/#2 checks are removed."""

    def test_no_links_and_no_numbered_checks(self) -> None:
        self.assertEqual({}, tr.DEFEAT_LINKS)
        self.assertEqual([ARDOS1], tr.apply_defeat_links([ARDOS1], set()))
        for label in (ZOOK1, ZOOK2, ARDOS1, ARDOS2):
            self.assertNotIn(label, L.LOCATION_TABLE)
        self.assertEqual([], tr.UNIQUE_SURNAME_TO_LOCATION_QUEUE["ZOOK"])
        self.assertEqual([], tr.UNIQUE_SURNAME_TO_LOCATION_QUEUE["ARDOS"])
        self.assertNotIn(ZOOK1, ma.AUTO_SEND_AT_STORY_BYTE)


class TestTheClientAppliesIt(unittest.TestCase):
    def test_in_the_defeat_poll_unique_mode_only(self) -> None:
        body = CLIENT.split("async def check_trainer_defeats", 1)[1].split("\n# The roster holds THREE", 1)[0]
        self.assertIn("elif ctx.unique_trainer_defeats and newly_completed:", body)
        self.assertIn("trainer_roster.apply_defeat_links(", body)
        self.assertLess(body.index("apply_defeat_links"), body.index("await _send_checks(ctx, newly_completed)"))


class TestTheLairAtZook(unittest.TestCase):
    """820 -> 810: one more step of the story VARIABLE. 810 presents as 0x65, "Zook defeated at the Key Lair"."""

    def test_the_floor_is_810(self) -> None:
        self.assertEqual(0x64, sb.AREA_ENTRY_FLOOR_OVERRIDES[LAIR])   # ADDENDUM 439: 800, Gonzap's rung
        self.assertEqual(800, sb.story_value_for_byte(sb.area_entry_floor(LAIR)))
        self.assertEqual(800 + sb.STORY_VARIABLE_STEP, sb.story_value_for_byte(0x65))

    def test_it_is_zooks_rung(self) -> None:
        zook = [t for t in sb.TRANSITIONS if t.after == 0x65]
        self.assertEqual(1, len(zook))
        self.assertIn("Zook", zook[0].what)
        self.assertEqual(0x64, zook[0].before)

    def test_the_write_sets_the_whole_variable(self) -> None:
        written = {}
        with mock.patch.object(rc, "read_bytes", return_value=struct.pack(">H", 0xFFFF)), \
                mock.patch.object(rc, "write_bytes", side_effect=lambda a, b: written.__setitem__(a, b)):
            self.assertTrue(rc.poke_story_byte(0x1000, sb.area_entry_floor(LAIR)))
        (raw,) = written.values()
        word = struct.unpack(">H", raw)[0]
        self.assertEqual(800, (word >> rc.STORY_VALUE_SHIFT) & 0xFFF)   # ADDENDUM 439
        self.assertEqual(0xFFFF & rc.STORY_VALUE_NEIGHBOUR_MASK, word & rc.STORY_VALUE_NEIGHBOUR_MASK)

    def test_still_above_gonzap_and_inside_the_window(self) -> None:
        window = sb.REGION_STORY_WINDOW[LAIR]
        # ADDENDUM 439: AT Gonzap's rung now, never below it.
        self.assertGreaterEqual(sb.area_entry_floor(LAIR), 0x64, "below 0x64 the Lair would ask for Gonzap")
        self.assertLessEqual(window.floor, 0x65)
        self.assertLessEqual(0x65, window.ceiling)
        self.assertTrue(sb.byte_is_reachable(0x65))

    def test_zook_two_stays_fenced_until_play_says_otherwise(self) -> None:
        self.assertIn(147, mt.FILLER_ONLY_TRAINER_INDICES)

    def test_arrival_and_a_later_mark(self) -> None:
        self.assertEqual(0x64, rc.AreaStoryByteMemory().target_for(LAIR))   # ADDENDUM 439
        memory = rc.AreaStoryByteMemory()
        memory.observe(LAIR, 0x69)
        self.assertEqual(0x69, memory.target_for(LAIR))


if __name__ == "__main__":
    unittest.main()
