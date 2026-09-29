"""ADDENDUM 213 (2026-09-14) -- the live in-area story-byte bump.

Player instruction, verbatim: "for the 0x0F check, I need it immediately - while you're in the lab. Increase
the floor to 0x0F too."

ADDENDUM 212 built the 0x0D -> 0x0F rule as a FLOOR, which takes effect on the next arrival at the lab. This
addendum adds the second half: a write that happens while the player is standing in the room. Both are needed,
and "too" in the instruction is what says so -- so the first class here pins that the floor survived.
"""
import struct
import unittest

from ..game_data import story_bytes
from .. import ram_client


class TestTheFloorRuleIsStillThere(unittest.TestCase):
    """"Increase the floor to 0x0F too" -- the bump is in addition to ADDENDUM 212's floor, not instead of it.
    Without this test a later refactor could reasonably conclude the floor had been superseded."""

    def test_the_lab_still_has_its_pass_through_floor(self):
        """ADDENDUM 288 moved the target from 0x0F to 0x0E. Read from the bump table rather than written
        twice, so the floor and the bump cannot drift apart again -- they are two halves of one instruction."""
        self.assertEqual(story_bytes.dynamic_region_floor("Pokemon HQ Lab", {"Pokemon HQ Lab": 0x0D}),
                         self._lab_bump().becomes)

    def test_arriving_later_still_gets_the_same_value_without_any_bump(self):
        memory = ram_client.AreaStoryByteMemory()
        memory.observe("Pokemon HQ Lab", 0x0D)
        self.assertEqual(memory.target_for("Pokemon HQ Lab"), self._lab_bump().becomes)

    @staticmethod
    def _lab_bump():
        lab = [b for b in story_bytes.LIVE_STORY_BYTE_BUMPS if b.region == "Pokemon HQ Lab"]
        assert len(lab) == 1
        return lab[0]


class TestTheBumpTable(unittest.TestCase):
    def test_a_bump_only_ever_raises(self):
        for bump in story_bytes.LIVE_STORY_BYTE_BUMPS:
            self.assertGreater(bump.becomes, bump.when_byte_is, bump.what)

    def test_every_bump_names_a_real_region(self):
        for bump in story_bytes.LIVE_STORY_BYTE_BUMPS:
            self.assertIn(bump.region, story_bytes.ALL_KNOWN_REGIONS, bump.what)

    def test_the_lab_bump_is_declared(self):
        lab = [b for b in story_bytes.LIVE_STORY_BYTE_BUMPS if b.region == "Pokemon HQ Lab"]
        self.assertEqual(len(lab), 1)
        # ADDENDUM 304, player: "Make the HQ Lab live bump from 0x0D to 0x0F again". (0x0F was the
        # original ADDENDUM 212/213 target; ADDENDUM 288 moved it to 0x0E for a day.)
        self.assertEqual((lab[0].when_byte_is, lab[0].becomes), (0x0D, 0x0F))

    def test_the_window_is_half_open(self):
        """`when <= live < becomes`. The closed end is what stops it firing at its own target, which is the
        whole reason it cannot loop."""
        bump = story_bytes.LIVE_STORY_BYTE_BUMPS[0]
        self.assertFalse(bump.applies("Pokemon HQ Lab", bump.when_byte_is - 1), "below the window")
        self.assertTrue(bump.applies("Pokemon HQ Lab", bump.when_byte_is), "the trigger value itself")
        self.assertFalse(bump.applies("Pokemon HQ Lab", bump.becomes), "already at the target")
        self.assertFalse(bump.applies("Pokemon HQ Lab", 0x30), "long past it")
        # ADDENDUM 304 RESTORED THE RANGE. ADDENDUM 288 had shrunk it to a single value, which cost the
        # catch-up the section comment argues for: a ~1s poll can land after the game has already moved off
        # the trigger, and with nothing between trigger and target a missed tick meant the bump could never
        # fire at all. With 0x0D -> 0x0F, 0x0E is inside the window and is skipped on purpose.
        self.assertGreater(bump.becomes - bump.when_byte_is, 1, "the window must catch a missed tick")
        self.assertTrue(bump.applies("Pokemon HQ Lab", 0x0E), "a tick missed at 0x0E still bumps")

    def test_it_only_fires_in_its_own_region(self):
        bump = story_bytes.LIVE_STORY_BYTE_BUMPS[0]
        self.assertFalse(bump.applies("Pyrite Town", 0x0D))
        self.assertFalse(bump.applies("Gateon Port", 0x0D))

    def test_the_lookup_never_guesses(self):
        # ADDENDUM 293: the two option arguments are required now. A travel-shuffled seed is the mode this
        # bump has always run in, so that is what these pass.
        self.assertIsNone(story_bytes.live_bump_for(None, 0x0D, True, False),
                          "unknown room -- never write on a guess")
        self.assertIsNone(story_bytes.live_bump_for("Pokemon HQ Lab", None, True, False), "unreadable byte")
        self.assertIsNone(story_bytes.live_bump_for("Agate Village", 0x0D, True, False),
                          "no bump declared there")

    def test_the_lab_bump_is_still_travel_shuffle_only(self):
        """ADDENDUM 293 made the gate DATA, and the value it wrote down for this bump is what the bump has
        always done -- it sat below `check_area_story_memory`'s early return, so a vanilla-travel seed never
        fired it. That was an accident of placement; now it is a decision, and this is the test that stops a
        future edit from quietly switching it on in a mode it has never been played in."""
        lab = story_bytes.LIVE_STORY_BYTE_BUMPS[0]
        self.assertEqual(lab.region, "Pokemon HQ Lab")
        self.assertIs(lab.gate, story_bytes.TRAVEL_SHUFFLE_ONLY)
        self.assertIsNotNone(story_bytes.live_bump_for("Pokemon HQ Lab", 0x0D, True, False))
        self.assertIsNone(story_bytes.live_bump_for("Pokemon HQ Lab", 0x0D, False, False))
        self.assertIsNone(story_bytes.live_bump_for("Pokemon HQ Lab", 0x0D, False, True),
                          "shuffling the Scooter has nothing to do with the lab")


class TestTheBumperWrites(unittest.TestCase):
    def setUp(self):
        self.written: "list[tuple[int, bytes]]" = []
        self._original = ram_client.write_bytes
        ram_client.write_bytes = lambda address, data: self.written.append((address, data))

    def tearDown(self):
        ram_client.write_bytes = self._original

    def test_it_writes_the_target_and_reports_it(self):
        log = ram_client.StoryByteWriteLog()
        bumper = ram_client.LiveStoryByteBumper(write_log=log)
        result = bumper.poll(0x80479000, "Pokemon HQ Lab", 0x0D, True, False)
        self.assertIsNotNone(result)
        new_byte, note = result
        target = story_bytes.LIVE_STORY_BYTE_BUMPS[0].becomes
        self.assertEqual(new_byte, target)
        self.assertEqual(len(self.written), 1)
        # ADDENDUM 350: the write is the whole twelve-bit story variable, not the byte -- the low five bits
        # of this u16 belong to the neighbouring variable and are preserved, and the byte is recoverable as
        # `value >> 3`.
        expected_value = story_bytes.story_value_for_byte(target)
        self.assertIsNotNone(expected_value, "a live bump must name a byte the game can actually hold")
        self.assertEqual(self.written[0][1], struct.pack(">H", expected_value << 5))
        self.assertEqual(self.written[0][1][0], target)
        self.assertIn(f"0x0D -> 0x{target:02X}", note)

    def test_the_write_lands_at_the_story_byte_address(self):
        bumper = ram_client.LiveStoryByteBumper()
        bumper.poll(0x80479000, "Pokemon HQ Lab", 0x0D, True, False)
        expected = 0x80479000 + ram_client.STORY_RECORD_OFFSET + ram_client.STORY_BYTE_OFFSET
        self.assertEqual(self.written[0][0], expected)

    def test_it_is_logged_as_its_own_source(self):
        log = ram_client.StoryByteWriteLog()
        ram_client.LiveStoryByteBumper(write_log=log).poll(0x80479000, "Pokemon HQ Lab", 0x0D, True, False)
        self.assertEqual(log.total, 1)
        entry = log.entries[0]
        self.assertEqual(entry.source, "live bump")
        self.assertEqual((entry.was, entry.now), (0x0D, story_bytes.LIVE_STORY_BYTE_BUMPS[0].becomes))
        self.assertIn("live bump", "\n".join(log.describe()))

    def test_it_does_not_fire_again_once_the_byte_is_at_the_target(self):
        """The half-open window doing its job: this is what makes the bump safe to run every tick."""
        bumper = ram_client.LiveStoryByteBumper()
        bumper.poll(0x80479000, "Pokemon HQ Lab", 0x0D, True, False)
        for _ in range(10):
            self.assertIsNone(bumper.poll(0x80479000, "Pokemon HQ Lab",
                                          story_bytes.LIVE_STORY_BYTE_BUMPS[0].becomes, True, False))
        self.assertEqual(len(self.written), 1)
        self.assertEqual(bumper.applications, 1)

    def test_it_declines_rather_than_hammering_a_byte_that_comes_back(self):
        """If something else owns this byte and puts the old value straight back, fighting it every tick would
        be worse than declining -- and `!areas` says it happened rather than hiding it."""
        bumper = ram_client.LiveStoryByteBumper()
        self.assertIsNotNone(bumper.poll(0x80479000, "Pokemon HQ Lab", 0x0D, True, False))
        for _ in range(5):
            self.assertIsNone(bumper.poll(0x80479000, "Pokemon HQ Lab", 0x0D, True, False))
        self.assertEqual(len(self.written), 1)
        self.assertEqual(bumper.declined_write_failed, 5)
        self.assertIn("came back after we wrote it", "\n".join(bumper.describe()))

    def test_nothing_is_written_anywhere_else(self):
        bumper = ram_client.LiveStoryByteBumper()
        for region in ("Pyrite Town", "Gateon Port", "Agate Village", None):
            self.assertIsNone(bumper.poll(0x80479000, region, 0x0D, True, False))
        self.assertEqual(self.written, [])

    def test_an_unreadable_byte_writes_nothing(self):
        bumper = ram_client.LiveStoryByteBumper()
        self.assertIsNone(bumper.poll(0x80479000, "Pokemon HQ Lab", None, True, False))
        self.assertEqual(self.written, [])

    def test_a_failing_write_never_raises(self):
        ram_client.write_bytes = lambda address, data: (_ for _ in ()).throw(RuntimeError("bus error"))
        bumper = ram_client.LiveStoryByteBumper()
        self.assertIsNone(bumper.poll(0x80479000, "Pokemon HQ Lab", 0x0D, True, False))
        self.assertEqual(bumper.applications, 0)


class TestTheClientWiring(unittest.TestCase):
    """Source-checked, like every other Client.py test in this suite."""

    @classmethod
    def setUpClass(cls):
        from pathlib import Path

        cls.source = (Path(ram_client.__file__).resolve().parent / "Client.py").read_text(encoding="utf-8")

    def test_the_bumper_shares_the_one_write_log(self):
        self.assertIn("ram_client.LiveStoryByteBumper(write_log=self.story_write_log)", self.source)

    def test_it_runs_before_the_area_memory_observes(self):
        """Ordering is load-bearing: observing first would record the pass-through value as the lab's
        high-water mark, and that mark is the one thing that cannot be recovered from the game.

        ADDENDUM 293: scoped to `check_area_story_memory`'s own body. There is a SECOND call site now (the
        vanilla-travel one, which has no area memory to order against), and it happens to sit earlier in the
        file -- so a bare `index()` over the whole source would pass for a reason that has nothing to do with
        the property being tested."""
        start = self.source.index("async def check_area_story_memory(")
        end = self.source.index("async def check_story_byte_override(")
        body = self.source[start:end]
        self.assertLess(body.index("ctx.live_story_bumper.poll("),
                        body.index("ctx.area_story_memory.poll("))

    def test_the_new_value_is_carried_forward_rather_than_re_read(self):
        self.assertIn("story_byte, bump_note = bumped", self.source)

    def test_it_lives_inside_the_travel_gated_poll(self):
        """It writes to save data, so it must sit in the function that already refuses to run with travel
        randomization off and inside the ADDENDUM 148 block-stability gate."""
        start = self.source.index("async def check_area_story_memory(")
        end = self.source.index("async def check_story_byte_override(")
        body = self.source[start:end]
        self.assertIn("if not ctx.randomize_travel_locations:", body)
        self.assertIn("ctx.live_story_bumper.poll(", body)

    def test_areas_reports_it(self):
        self.assertIn("ctx.live_story_bumper.describe()", self.source)


if __name__ == "__main__":
    unittest.main()
