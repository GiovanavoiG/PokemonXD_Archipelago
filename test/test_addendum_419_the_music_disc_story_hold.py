"""ADDENDUM 419 (2026-10-05) -- the Music Disc is a story byte, so Phenac is capped below the pickup without it.

Player: "Apparently the music disc is a fake item, and the action that takes it is actually determined via story
byte. Let's add a system to ensure that our story byte is forced capped to before the music disc if we don't have
it in Phenac."
"""
import unittest
from pathlib import Path

from .. import ram_client as rc
from ..game_data import chest_regions, story_bytes as sb
from .test_addendum_229_map_backout_restore import BLOCK, _LiveByte

CLIENT = (Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
CHEST_80_ROOM = 98            # Phenac City -- the pickup
MAYORS_HOUSE = 96             # Phenac City (Mayor's House) -- the handover
REALGAM = 49                  # Realgam Tower, whose window also spans 0x41..0x43
# ADDENDUM 441: chest 80's own room now holds one step lower (0x3F), so the hold's ordinary behaviour is pinned in
# another Phenac town room. The disc room's own rule is test_addendum_441.
PHENAC_TOWN = 94


class _Base(unittest.TestCase):
    start = 0x41

    def setUp(self):
        self.live = _LiveByte(self.start)
        self.log = rc.StoryByteWriteLog()
        self.hold = rc.MusicDiscStoryHold(enabled=True, write_log=self.log)

    def tearDown(self):
        self.live.restore_module()

    def poll(self, room, checked=False):
        return self.hold.poll(BLOCK, self.live.value, room, checked)


class TestTheTable(unittest.TestCase):
    def test_the_bytes_are_the_ladders(self):
        self.assertTrue(rc._music_disc_ladder_agrees())
        self.assertEqual(0x41, rc.MUSIC_DISC_HOLD_FLOOR)
        self.assertEqual((0x42, 0x43), rc.MUSIC_DISC_HOLD_BAND)

    def test_chest_80_is_the_disc_and_sits_in_phenac(self):
        self.assertEqual("Phenac City", chest_regions.region_for_room(CHEST_80_ROOM))
        self.assertIn(rc.MUSIC_DISC_CHEST_ID, rc.CHEST_ID_TO_LOCATION)

    def test_phenac_rooms(self):
        self.assertTrue(rc.is_phenac_room(CHEST_80_ROOM))
        self.assertTrue(rc.is_phenac_room(MAYORS_HOUSE))
        self.assertFalse(rc.is_phenac_room(REALGAM))
        self.assertFalse(rc.is_phenac_room(None))
        self.assertEqual("Realgam Tower", chest_regions.region_for_room(REALGAM))
        self.assertTrue(sb.REGION_STORY_WINDOW["Realgam Tower"].contains(0x42), "why the hold is fenced to Phenac")


class TestWithoutTheDisc(_Base):
    def test_opening_chest_80_is_pulled_back(self):
        self.live.value = 0x42
        note = self.poll(PHENAC_TOWN)
        self.assertEqual(0x41, self.live.value)
        self.assertIn("Music Disc", note)
        self.assertEqual(0x41, self.hold.last_written_value)
        self.assertEqual(["music disc hold"], [e.source for e in self.log.entries])

    def test_a_handover_is_pulled_back_too(self):
        self.live.value = 0x43
        self.poll(MAYORS_HOUSE)
        self.assertEqual(0x41, self.live.value)
        self.assertEqual(0x43, self.hold.declined_value)

    def test_at_the_floor_nothing_is_written(self):
        self.assertIsNone(self.poll(PHENAC_TOWN))
        self.assertEqual(0, self.hold.holds)

    def test_past_the_band_is_progress_not_a_hold(self):
        self.live.value = 0x44
        self.poll(MAYORS_HOUSE)
        self.assertEqual(0x44, self.live.value)
        self.assertEqual(1, self.hold.declined_out_of_band)

    def test_outside_phenac_it_does_nothing(self):
        self.live.value = 0x42
        self.poll(REALGAM)
        self.poll(None)
        self.assertEqual(0x42, self.live.value)

    def test_off_for_a_seed_without_shuffled_key_items(self):
        self.hold.enabled = False
        self.live.value = 0x42
        self.poll(PHENAC_TOWN)
        self.assertEqual(0x42, self.live.value)


class TestTheDiscArrives(_Base):
    def test_the_held_step_is_given_back(self):
        self.live.value = 0x43
        self.poll(MAYORS_HOUSE)
        self.hold.disc_held = True
        note = self.poll(MAYORS_HOUSE)
        self.assertEqual(0x43, self.live.value)
        self.assertIn("0x43", note)
        self.assertEqual(1, self.hold.grants)
        self.assertEqual(0x43, self.hold.last_written_value, "the grant is a RAISE this client owns")
        self.assertIsNone(self.hold.declined_value)
        self.assertIsNone(self.poll(MAYORS_HOUSE), "once")

    def test_the_grant_waits_for_phenac(self):
        self.live.value = 0x42
        self.poll(PHENAC_TOWN)
        self.hold.disc_held = True
        self.poll(REALGAM)
        self.assertEqual(0x41, self.live.value)
        self.poll(PHENAC_TOWN)
        self.assertEqual(0x42, self.live.value)

    def test_with_the_disc_the_game_moves_freely(self):
        self.hold.disc_held = True
        for value in (0x42, 0x43, 0x44):
            self.live.value = value
            self.poll(MAYORS_HOUSE)
            self.assertEqual(value, self.live.value)
        self.assertEqual(0, self.hold.holds)

    def test_never_held_and_chest_shut_writes_nothing(self):
        self.hold.disc_held = True
        self.assertIsNone(self.poll(PHENAC_TOWN))
        self.assertEqual(0x41, self.live.value)

    def test_after_a_restart_a_checked_chest_80_is_enough(self):
        """The memory of what was held is gone, but the pickup happened and the chest cannot open twice."""
        self.hold.disc_held = True
        self.poll(PHENAC_TOWN, checked=True)
        self.assertEqual(0x42, self.live.value)

    def test_a_byte_that_moved_on_is_not_overwritten(self):
        self.live.value = 0x42
        self.poll(PHENAC_TOWN)
        self.hold.disc_held = True
        self.live.value = 0x3F            # somewhere else's value, e.g. a reload
        self.poll(PHENAC_TOWN)
        self.assertEqual(0x3F, self.live.value)


class TestTheClient(unittest.TestCase):
    def test_it_runs_before_the_area_memory_and_claims_its_writes(self):
        loop = CLIENT.split("                        await check_scooter_hold(ctx)", 1)[1]
        self.assertLess(loop.index("await check_music_disc_hold(ctx)"), loop.index("await check_area_story_memory(ctx)"))
        body = CLIENT.split("def _poll_item_story_hold", 1)[1].split("\nasync def ", 1)[0]
        self.assertIn("_claim_story_write(ctx, hold)", body)          # ADDENDUM 421: shared by both holds
        self.assertIn("ctx.room_tracker.current", body)
        self.assertIn("ctx.music_disc_hold, MUSIC_DISC_ITEM_NAME", CLIENT)

    def test_it_follows_key_item_shuffle(self):
        self.assertIn("self.music_disc_hold.enabled = self.key_item_shuffle", CLIENT)

    def test_the_keyitems_command_reports_it(self):
        self.assertIn("logger.info(ctx.music_disc_hold.describe())", CLIENT)


if __name__ == "__main__":
    unittest.main()
