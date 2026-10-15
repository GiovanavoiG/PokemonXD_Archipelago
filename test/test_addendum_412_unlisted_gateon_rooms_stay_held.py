"""ADDENDUM 412 (2026-10-04) -- a room reached from Gateon without the map is still Gateon, unless it is the ride.

Citadark was reachable with only 6/8 Kyogre Parts. The first Citadark travel must not reset the story byte, as it
does not go through the map screen; it is recognisable from the big jump in room IDs.
"""
import unittest

from .. import ram_client as rc
from ..game_data import chest_regions
from .test_addendum_229_map_backout_restore import BLOCK, _LiveByte

GATEON = 153
UNLISTED = 154                    # unnamed, unfiled, inside Gateon's 140-165 neighbourhood
UNRECORDED_DOCK = 72              # ADDENDUM 313's stand-in for the ride's landing room -- the big jump
CITADARK_CHEST_ROOM = min(rc.CITADARK_ROOM_IDS)


class _Base(unittest.TestCase):
    start = 0x76

    def setUp(self):
        self.live = _LiveByte(self.start)
        self.override = rc.StoryByteOverride(write_log=rc.StoryByteWriteLog())

    def tearDown(self):
        self.live.restore_module()

    def walk(self, *rooms):
        notes = [self.override.poll(BLOCK, room) for room in rooms]
        return [n for n in notes if n]


class TestTheReport(_Base):
    """No Parts, a late byte: the case that opened the ride."""

    def test_an_unlisted_gateon_room_no_longer_releases_the_byte(self):
        self.walk(GATEON)
        self.assertEqual(rc.GATEON_STORY_CEILING, self.live.value)
        notes = self.walk(UNLISTED)
        self.assertEqual(rc.GATEON_STORY_CEILING, self.live.value, "held, not restored to 0x76")
        self.assertTrue(self.override.active)
        self.assertIn(f"Room {UNLISTED}", notes[0])
        self.assertEqual({UNLISTED}, self.override.unlisted_gateon_rooms)

    def test_and_walking_back_never_loads_a_known_room_from_the_high_byte(self):
        for room in (GATEON, UNLISTED, GATEON, UNLISTED, 158, UNLISTED):
            self.override.poll(BLOCK, room)
            self.assertEqual(rc.GATEON_STORY_CEILING, self.live.value, room)
        self.assertEqual(0, self.override.restorations)

    def test_a_rise_inside_the_unlisted_room_is_caught_and_kept_for_later(self):
        self.walk(GATEON, UNLISTED)
        self.live.value = 0x77
        self.walk(UNLISTED)
        self.assertEqual(rc.GATEON_STORY_CEILING, self.live.value)
        self.assertEqual(0x77, self.override.saved_byte)

    def test_leaving_through_the_map_still_restores(self):
        self.walk(GATEON, UNLISTED, rc.MAP_SCREEN_ROOM_ID, 132)
        self.assertEqual(0x76, self.live.value)
        self.assertFalse(self.override.active)

    def test_an_unlisted_room_reached_through_the_map_is_a_walk_out(self):
        self.walk(GATEON, rc.MAP_SCREEN_ROOM_ID, UNLISTED)
        self.assertEqual(0x76, self.live.value)
        self.assertFalse(self.override.active)

    def test_a_room_filed_elsewhere_is_not_gateon(self):
        """The HQ Lab sits inside the id neighbourhood but is filed -- never mistaken for Gateon."""
        self.assertEqual("Pokemon HQ Lab", chest_regions.region_for_room(140))
        self.assertFalse(rc.looks_like_unlisted_gateon_room(140))
        self.walk(GATEON, 140)
        self.assertEqual(0x76, self.live.value)

    def test_the_byte_was_never_touched_below_the_ceiling(self):
        self.live.value = 0x6C
        self.walk(GATEON, UNLISTED, GATEON)
        self.assertEqual(0x6C, self.live.value)
        self.assertFalse(self.override.active)


class TestTheFirstRideIsNotAReset(_Base):
    """With the Parts: lift in Gateon, then the ride, which never passes the map screen."""
    start = 0x15

    def setUp(self):
        super().setUp()
        self.override.armed = True

    def test_straight_from_a_known_room(self):
        self.walk(GATEON)
        self.assertEqual(rc.STORY_OVERRIDE_VALUE, self.live.value)
        self.walk(UNRECORDED_DOCK)
        self.assertEqual(rc.CITADARK_ENTRY_FLOOR, self.live.value, "0x71, never back to 0x15")
        self.assertEqual(UNRECORDED_DOCK, self.override.citadark_arrival_room)

    def test_through_an_unlisted_gateon_room_first(self):
        """The case 412 also fixes: before, the unlisted room RESTORED 0x15 and the island loaded from it."""
        self.walk(GATEON, UNLISTED)
        self.assertEqual(rc.STORY_OVERRIDE_VALUE, self.live.value, "the lift is held through it")
        self.walk(UNRECORDED_DOCK)
        self.assertEqual(rc.CITADARK_ENTRY_FLOOR, self.live.value)
        self.assertEqual(0, self.override.restorations)

    def test_landing_in_a_known_citadark_room(self):
        self.walk(GATEON, UNLISTED, CITADARK_CHEST_ROOM)
        self.assertEqual(rc.CITADARK_ENTRY_FLOOR, self.live.value)

    def test_the_jump_is_what_tells_them_apart(self):
        """Gateon's rooms sit in 140-165; Citadark's are 73-88. The ride is the big jump, the rest is Gateon."""
        self.assertTrue(all(r in range(140, 166) for r in rc.GATEON_ROOM_IDS))
        self.assertTrue(all(r < 100 for r in rc.CITADARK_ROOM_IDS))
        self.assertTrue(rc.looks_like_citadark_arrival(UNRECORDED_DOCK))
        self.assertFalse(rc.looks_like_citadark_arrival(UNLISTED))
        self.assertTrue(rc.looks_like_unlisted_gateon_room(UNLISTED))
        self.assertFalse(rc.looks_like_unlisted_gateon_room(UNRECORDED_DOCK))

    def test_parts_reports_the_rooms_it_learned(self):
        self.walk(GATEON, UNLISTED, UNRECORDED_DOCK)
        line = self.override.describe()
        self.assertIn(f"Unlisted rooms held as Gateon (reached without the map): {UNLISTED}", line)
        self.assertIn(f"ride landed in room {UNRECORDED_DOCK}", line)


if __name__ == "__main__":
    unittest.main()
