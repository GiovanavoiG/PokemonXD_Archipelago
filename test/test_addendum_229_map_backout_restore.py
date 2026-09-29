"""ADDENDUM 229 (2026-09-15) -- backing out of the map puts the story byte back, before anything records it.

Player, in two messages:
    "I want to restore the story byte when you back out of the map, otherwise it breaks things. This restore
     needs to happen prior to us recording the story byte in an area - if we back out, say, at HQ Lab where
     the flag is 0x0F, and do it while hovering Agate, it can send our HQ Lab byte into the 0x2 range. Avoid
     this at all costs."
    "We can check a back-out by seeing if our room returns to the one we entered the map screen from."

WHY THE ORDERING IS THE WHOLE THING. The damage is not the wrong live byte -- that would be self-correcting,
which is what ADDENDUM 177 reasoned when it chose not to restore. The damage is `observe()` banking that
foreign value as the CURRENT area's high-water mark: a persisted file built to outlive the client, re-applied
on every future entry to that area. One backed-out map screen poisons an area for the rest of the run. So a
late restore is barely better than none, and these tests pin the order as hard as the behaviour.
"""
import unittest

from .. import ram_client as rc
from ..game_data import story_bytes as sb

BLOCK = 0x80479000


class _LiveByte:
    """Stands in for the game's story byte so a real write/read round-trip can be exercised."""

    def __init__(self, value):
        self.value = value
        self._write, self._read = rc.write_bytes, rc.read_story_byte
        rc.write_bytes = lambda address, data: setattr(self, "value", data[0])
        rc.read_story_byte = lambda block_base: self.value

    def restore_module(self):
        rc.write_bytes, rc.read_story_byte = self._write, self._read


class MapBackoutTestBase(unittest.TestCase):
    def setUp(self):
        self.live = _LiveByte(0x0F)
        self.memory = rc.AreaStoryByteMemory()
        self.memory.observe("Pokemon HQ Lab", 0x0F)

    def tearDown(self):
        self.live.restore_module()

    def hover(self, region):
        return self.memory.poll(BLOCK, region, None, self.live.value)


class TestThePlayersExactScenario(MapBackoutTestBase):
    """Standing in HQ Lab at 0x0F, hover Agate, back out."""

    def test_the_hover_write_still_happens(self):
        """It has to -- it is a pre-load hook. The fix is putting it back, not refusing to write."""
        self.hover("Agate Village")
        self.assertEqual(self.live.value, sb.region_floor("Agate Village"))

    def test_backing_out_puts_the_byte_back(self):
        self.hover("Agate Village")
        note = self.memory.left_map_screen(BLOCK, backed_out=True)
        self.assertEqual(self.live.value, 0x0F)
        self.assertEqual(self.memory.restores, 1)
        self.assertIn("restored", note)

    def test_the_lab_mark_is_never_poisoned(self):
        """The thing the player said to avoid at all costs, asserted at the only point it could happen."""
        self.hover("Agate Village")
        self.memory.observe("Pokemon HQ Lab", self.live.value)   # the old failure, fired deliberately
        self.assertEqual(self.memory.highest_by_region["Pokemon HQ Lab"], 0x0F)
        self.memory.left_map_screen(BLOCK, backed_out=True)
        self.memory.observe("Pokemon HQ Lab", self.live.value)
        self.assertEqual(self.memory.highest_by_region["Pokemon HQ Lab"], 0x0F)

    def test_the_lab_still_enters_at_its_own_value_afterwards(self):
        """The end-to-end consequence: a poisoned mark would make the NEXT entry write Agate's floor."""
        self.hover("Agate Village")
        self.memory.observe("Pokemon HQ Lab", self.live.value)
        self.memory.left_map_screen(BLOCK, backed_out=True)
        self.assertEqual(self.memory.target_for("Pokemon HQ Lab"), 0x0F)


class TestObserveIsLockedWhileAWriteIsOutstanding(MapBackoutTestBase):
    """The second, independent defence. The ordering in Client.py is the primary one; this makes a wrong
    ordering harmless rather than merely unlikely."""

    def test_no_region_can_be_recorded_mid_hover(self):
        self.hover("Agate Village")
        self.assertTrue(self.memory._write_outstanding)
        for region in ("Pokemon HQ Lab", "Gateon Port", "Pyrite Town"):
            self.assertFalse(self.memory.observe(region, self.live.value),
                             f"{region} was recorded while a hover write was live")

    def test_the_lock_lifts_on_restore(self):
        self.hover("Agate Village")
        self.memory.left_map_screen(BLOCK, backed_out=True)
        self.assertFalse(self.memory._write_outstanding)
        self.assertTrue(self.memory.observe("Pokemon HQ Lab", 0x10))

    def test_the_lock_lifts_on_travel(self):
        self.hover("Agate Village")
        self.memory.left_map_screen(BLOCK, backed_out=False)
        self.assertFalse(self.memory._write_outstanding)

    def test_a_failed_restore_leaves_the_lock_ON(self):
        """Deliberate. A failed restore means the live byte is still a destination's floor, and recording that
        IS the corruption -- so it records nothing until a later poll fixes it."""
        self.hover("Agate Village")
        rc.write_bytes = lambda address, data: (_ for _ in ()).throw(RuntimeError("bus error"))
        self.assertIsNone(self.memory.left_map_screen(BLOCK, backed_out=True))
        self.assertTrue(self.memory._write_outstanding)
        self.assertFalse(self.memory.observe("Pokemon HQ Lab", 0x19))
        self.assertEqual(self.memory.highest_by_region["Pokemon HQ Lab"], 0x0F)


class TestTravellingIsNotABackOut(MapBackoutTestBase):
    def test_the_written_value_is_kept(self):
        """It is what the destination's room is about to be built from -- restoring would defeat the hook."""
        self.hover("Agate Village")
        self.assertIsNone(self.memory.left_map_screen(BLOCK, backed_out=False))
        self.assertEqual(self.live.value, sb.region_floor("Agate Village"))
        self.assertEqual(self.memory.restores, 0)


class TestSeveralHoversInOneMapVisit(MapBackoutTestBase):
    def test_it_restores_the_pre_map_byte_not_the_previous_hover(self):
        """What a player who backs out wants is the byte they had before opening the map, not whatever the
        hover before last happened to leave behind."""
        floors = []
        for destination in ("Agate Village", "Mt. Battle", "Cipher Lab"):
            self.hover(destination)
            floors.append(self.live.value)
        self.assertEqual(len(set(floors)), 3, "the three hovers really did write different values")
        self.memory.left_map_screen(BLOCK, backed_out=True)
        self.assertEqual(self.live.value, 0x0F)

    def test_the_saved_byte_is_captured_only_once(self):
        self.hover("Agate Village")
        first = self.memory.saved_byte
        self.hover("Mt. Battle")
        self.assertEqual(self.memory.saved_byte, first)


class TestTheQuietCases(MapBackoutTestBase):
    def test_a_map_visit_with_no_hover_restores_nothing(self):
        self.assertIsNone(self.memory.left_map_screen(BLOCK, backed_out=True))
        self.assertEqual(self.live.value, 0x0F)
        self.assertFalse(self.memory._write_outstanding)

    def test_a_hover_that_matched_the_live_byte_never_wrote_and_never_restores(self):
        """`poll` declines when the byte already equals the target, so there is nothing saved to put back."""
        self.live.value = sb.region_floor("Agate Village")
        self.memory.poll(BLOCK, "Agate Village", None, self.live.value)
        self.assertIsNone(self.memory.saved_byte)
        self.assertIsNone(self.memory.left_map_screen(BLOCK, backed_out=True))

    def test_real_progress_is_never_rolled_back(self):
        """Cannot happen on a menu screen, but it is the rule StoryByteOverride._restore already holds and for
        the same reason: clobbering genuine progress is far worse than declining to restore."""
        self.hover("Agate Village")
        self.live.value = 0x60          # something advanced past the saved value by other means
        self.assertIsNone(self.memory.left_map_screen(BLOCK, backed_out=True))
        self.assertEqual(self.live.value, 0x60)
        self.assertEqual(self.memory.declined_restores, 1)

    def test_the_restore_is_logged_as_its_own_source(self):
        log = rc.StoryByteWriteLog()
        memory = rc.AreaStoryByteMemory(write_log=log)
        memory.observe("Pokemon HQ Lab", 0x0F)
        memory.poll(BLOCK, "Agate Village", None, self.live.value)
        memory.left_map_screen(BLOCK, backed_out=True)
        sources = [entry.source for entry in log.entries]
        self.assertIn("map back-out", sources)
        self.assertIn("map back-out", "\n".join(log.describe()))


class TestTheClientWiring(unittest.TestCase):
    """Source-checked: Client.py pulls in Archipelago's CommonClient."""

    @classmethod
    def setUpClass(cls):
        from pathlib import Path

        cls.source = (Path(rc.__file__).resolve().parent / "Client.py").read_text(encoding="utf-8")

    def test_the_room_we_entered_the_map_from_is_remembered(self):
        """The player's own test for a back-out, and the only one available: travelling lands you in the
        DESTINATION's room, backing out lands you in the room you came from."""
        self.assertIn("self._room_before_map", self.source)
        self.assertIn("backed_out = ctx._room_before_map is not None and room_id == ctx._room_before_map",
                      self.source)

    def test_the_restore_runs_before_anything_records(self):
        """The load-bearing half of the instruction. Pinned by POSITION, because a correct call in the wrong
        place is the whole bug."""
        block = self.source.split("async def check_area_story_memory", 1)[1].split("\nasync def ", 1)[0]
        restore_at = block.index("left_map_screen(")
        bump_at = block.index("ctx.live_story_bumper.poll(")
        poll_at = block.index("ctx.area_story_memory.poll(")
        self.assertLess(restore_at, bump_at, "the restore must precede the in-area bump")
        self.assertLess(restore_at, poll_at, "the restore must precede the memory's own observe/poll")

    def test_the_byte_is_re_read_after_a_restore(self):
        """Everything downstream this tick has to work from the restored value, not the foreign one."""
        self.assertIn("story_byte = ram_client.read_story_byte(ctx.block_base)   # re-read", self.source)

    def test_an_unreadable_room_decides_nothing(self):
        """Guessing 'backed out' wrongly rolls back a byte the destination is about to be built from."""
        block = self.source.split("async def check_area_story_memory", 1)[1].split("\nasync def ", 1)[0]
        self.assertIn("elif room_id is not None:", block)


if __name__ == "__main__":
    unittest.main()
