"""ADDENDUM 313 -- Citadark Isle is entered at story byte 0x71, then progresses vanilla.

Player: "Story byte is 0x15 upon entering citadark. That's breaking things. It needs to be 0x71 upon entering
citadark and progress vanilla." The Parts override treated the Robo Kyogre ride as walking out of Gateon and
restored the pre-Gateon byte as the island loaded."""
import unittest

from .. import ram_client as rc
from .test_addendum_229_map_backout_restore import BLOCK, _LiveByte

GATEON = 153
CITADARK_CHEST_ROOM = min(rc.CITADARK_ROOM_IDS)
UNRECORDED_DOCK = 72          # not in the region table -- the shape the ride has to be recognised by
AGATE = 132


class _Base(unittest.TestCase):
    def setUp(self):
        self.live = _LiveByte(0x15)
        self.log = rc.StoryByteWriteLog()
        self.override = rc.StoryByteOverride(write_log=self.log)
        self.override.armed = True

    def tearDown(self):
        self.live.restore_module()

    def enter_gateon(self):
        self.override.poll(BLOCK, GATEON)
        self.assertEqual(rc.STORY_OVERRIDE_VALUE, self.live.value, "premise: the Parts lift is in place")


class TestTheRide(_Base):
    def test_the_players_report_arrives_at_0x71_not_0x15(self):
        self.enter_gateon()
        note = self.override.poll(BLOCK, UNRECORDED_DOCK)
        self.assertEqual(0x71, self.live.value)
        self.assertIn("Citadark", note)
        self.assertFalse(self.override.active)
        self.assertEqual(UNRECORDED_DOCK, self.override.citadark_arrival_room)

    def test_a_known_citadark_room_counts_too(self):
        self.enter_gateon()
        self.override.poll(BLOCK, CITADARK_CHEST_ROOM)
        self.assertEqual(0x71, self.live.value)

    def test_then_the_game_owns_it(self):
        self.enter_gateon()
        self.override.poll(BLOCK, UNRECORDED_DOCK)
        self.live.value = 0x73                     # vanilla progress on the island
        for room in (UNRECORDED_DOCK, CITADARK_CHEST_ROOM, UNRECORDED_DOCK):
            self.override.poll(BLOCK, room)
        self.assertEqual(0x73, self.live.value)

    def test_a_return_trip_keeps_island_progress(self):
        self.live.value = 0x74
        self.enter_gateon()
        self.override.poll(BLOCK, UNRECORDED_DOCK)
        self.assertEqual(0x74, self.live.value)

    def test_a_won_game_is_left_alone(self):
        self.live.value = rc.VICTORY_STORY_BYTE
        self.override.poll(BLOCK, GATEON)
        self.override.poll(BLOCK, UNRECORDED_DOCK)
        self.assertEqual(rc.VICTORY_STORY_BYTE, self.live.value)

    def test_the_write_is_claimed_and_logged(self):
        self.enter_gateon()
        self.override.last_written_value = None
        self.override.poll(BLOCK, UNRECORDED_DOCK)
        self.assertEqual(0x71, self.override.last_written_value)
        self.assertIn("citadark entry", [e.source for e in self.log.entries])


class TestWalkingOutIsStillAWalkOut(_Base):
    def test_via_the_map_restores_as_before(self):
        self.enter_gateon()
        self.override.poll(BLOCK, rc.MAP_SCREEN_ROOM_ID)
        self.override.poll(BLOCK, UNRECORDED_DOCK)   # even an unfiled room, if reached through the map
        self.assertEqual(0x15, self.live.value)

    def test_via_the_map_to_a_real_area(self):
        self.enter_gateon()
        self.override.poll(BLOCK, rc.MAP_SCREEN_ROOM_ID)
        self.override.poll(BLOCK, AGATE)
        self.assertEqual(0x15, self.live.value)

    def test_an_unrecorded_gateon_room_is_not_citadark(self):
        """Gateon Tower 2F and the Krabby Klub floors are not in GATEON_ROOM_IDS; walking into one must not
        read as the ride."""
        for room in (148, 150, 155, 159):
            self.assertFalse(rc.looks_like_citadark_arrival(room), room)


class TestTheFloor(_Base):
    def test_a_session_that_starts_on_the_island(self):
        self.override.poll(BLOCK, CITADARK_CHEST_ROOM)
        self.assertEqual(0x71, self.live.value)

    def test_never_lowers(self):
        self.live.value = 0x75
        self.override.poll(BLOCK, CITADARK_CHEST_ROOM)
        self.assertEqual(0x75, self.live.value)

    def test_not_outside_citadark(self):
        self.override.poll(BLOCK, AGATE)
        self.assertEqual(0x15, self.live.value)


class TestTheNumbers(unittest.TestCase):
    def test_ordering(self):
        self.assertEqual(0x71, rc.CITADARK_ENTRY_FLOOR)
        self.assertLess(rc.GATEON_STORY_CEILING, rc.CITADARK_ENTRY_FLOOR)
        self.assertLess(rc.CITADARK_ENTRY_FLOOR, rc.VICTORY_STORY_BYTE)
        self.assertTrue(rc.CITADARK_ROOM_IDS)
