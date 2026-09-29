"""ADDENDUM 265 (2026-09-17): an `Unlock -` check must be credited from a byte the GAME wrote.

Player, with a screenshot of seven checks firing at once: "With location shuffle, checks are sending as we
hover the map because it thinks the story byte has gotten high enough. Can we clamp it so these checks only
send if their byte is acquired in the area you'd usually unlock a new spot?"

## What happened, which is entirely self-inflicted

`AreaStoryByteMemory.poll` is a PRE-LOAD hook (ADDENDUM 177): while the cursor rests on a
destination it writes that destination's entry floor, because once the room loads it has already been built
from the old byte. `enforce_travel_locks` then read the live story byte raw, in the same tick, and credited
every `Unlock -` whose threshold that value now cleared.

Hovering ONE late destination clears many earlier thresholds at once — which is why the screenshot shows
seven. **The client wrote a byte and then congratulated the player for reaching it.**

## The rule already existed, one function over

ADDENDUM 229 hit this from the other side: `observe()` was recording hover-written bytes as an area's
permanent high-water mark. It closed that with `_write_outstanding`, a hard lock, and its comment states the
principle outright — the live byte then *"belongs to a map destination rather than to anywhere the player has
been"*. `enforce_travel_locks` reads the same byte and never got that memo.

So `StoryProgressWitness` is not a new idea. It is ADDENDUM 229's idea applied to the second reader, sharing
the same `_write_outstanding` flag rather than deriving a second one — because two readers with independent
notions of "is a write in the air" is how they come to disagree.

**This is worth a standing sweep of its own**, and the register now carries it: *who else reads a value this
client writes, without asking whether we wrote it?*
"""
from __future__ import annotations

import pathlib
import sys
import types
import unittest

if "dolphin_memory_engine" not in sys.modules:
    _stub = types.ModuleType("dolphin_memory_engine")
    _stub.hook = lambda: None
    _stub.un_hook = lambda: None
    _stub.is_hooked = lambda: False
    _stub.read_bytes = lambda address, length: b""
    _stub.write_bytes = lambda address, data: None
    sys.modules["dolphin_memory_engine"] = _stub

from .. import ram_client as rc
from .. import travel_locations


IN_A_ROOM = 138          # Pokemon HQ Lab interior -- an ordinary gameplay room
MAP = rc.MAP_SCREEN_ROOM_ID


def _credible(witness, value, room=IN_A_ROOM, write=False, override=False):
    return witness.poll(value, room, write, override)


class TestAHoverCannotCreditAnything(unittest.TestCase):
    """The reported bug, in the three shapes it can take."""

    def test_the_map_screen_never_raises_the_mark(self) -> None:
        """Room 910 is a menu whose whole purpose is moving a cursor, and every move rewrites the byte."""
        w = rc.StoryProgressWitness()
        _credible(w, 0x23)
        self.assertEqual(0x23, _credible(w, 0x6E, room=MAP))
        self.assertEqual(0x23, w.high_water)
        self.assertEqual(1, w.suppressed_polls)
        self.assertIn("map screen", w.last_reason or "")

    def test_an_outstanding_hover_write_never_raises_the_mark(self) -> None:
        """The tick after a hover write, before `left_map_screen` settles it. The room may already read as a
        real one here, which is why the map-screen check alone is not enough."""
        w = rc.StoryProgressWitness()
        _credible(w, 0x23)
        self.assertEqual(0x23, _credible(w, 0x6E, write=True))
        self.assertIn("hover write", w.last_reason or "")

    def test_the_parts_override_never_raises_the_mark(self) -> None:
        """ADDENDUM 255 holds the byte at STORY_OVERRIDE_VALUE while the player stands in Gateon with every
        Robo Kyogre Part. That is the client's value, not the story's."""
        w = rc.StoryProgressWitness()
        _credible(w, 0x23)
        self.assertEqual(0x23, _credible(w, rc.STORY_OVERRIDE_VALUE, override=True))
        self.assertIn("override", w.last_reason or "")

    def test_the_seven_check_cascade_cannot_happen(self) -> None:
        """The screenshot, reconstructed: one hover over a late destination clears many thresholds at once.

        Counted against the real threshold table rather than a made-up number, so this measures the actual
        blast radius -- and it is large, which is why a single hover produced seven lines rather than one."""
        thresholds = sorted(
            t for name in travel_locations.TRAVEL_LOCATION_NAMES
            if (t := travel_locations.vanilla_unlock_story_byte(name)) is not None
        )
        self.assertTrue(thresholds)
        hovered = thresholds[-1]
        would_have_fired = [t for t in thresholds if t <= hovered]
        self.assertGreater(len(would_have_fired), 5,
                           "one hover really does clear many thresholds -- that is the bug's shape")

        w = rc.StoryProgressWitness()
        _credible(w, thresholds[0] - 1)          # genuinely early in the story
        _credible(w, hovered, room=MAP)          # the hover
        self.assertLess(w.high_water, thresholds[0],
                        "not one threshold may be crossed by a value we wrote ourselves")


class TestCredibleReadingsStillWork(unittest.TestCase):
    """The fix must not cost a single legitimate credit -- that is the direction this project never trades in."""

    def test_ordinary_play_raises_the_mark(self) -> None:
        w = rc.StoryProgressWitness()
        for value in (0x10, 0x23, 0x24, 0x3A):
            _credible(w, value)
        self.assertEqual(0x3A, w.high_water)
        self.assertEqual(4, w.credible_polls)

    def test_a_hover_between_two_real_readings_changes_nothing(self) -> None:
        w = rc.StoryProgressWitness()
        _credible(w, 0x23)
        _credible(w, 0x6E, room=MAP)
        _credible(w, 0x24)
        self.assertEqual(0x24, w.high_water)

    def test_it_is_a_HIGH_WATER_mark_so_a_legitimate_dip_never_un_credits(self) -> None:
        """The byte moves DOWN on purpose in this project -- the area memory's first-visit floor and the
        Parts override's restore both write lower values. A credit that un-fired on a dip would be worse than
        no clamp at all."""
        w = rc.StoryProgressWitness()
        _credible(w, 0x5A)
        _credible(w, 0x23)
        self.assertEqual(0x5A, w.high_water)

    def test_an_unreadable_byte_decides_nothing(self) -> None:
        w = rc.StoryProgressWitness()
        _credible(w, 0x23)
        self.assertEqual(0x23, _credible(w, None))
        self.assertEqual(0, w.suppressed_polls, "an unreadable byte is not a suppressed one")

    def test_nothing_is_credited_before_any_credible_reading(self) -> None:
        """`high_water` starts below every real threshold, so a client that has not yet taken one good
        reading credits nothing rather than everything."""
        w = rc.StoryProgressWitness()
        self.assertLess(w.high_water, 0)


class TestTheClientWiring(unittest.TestCase):
    """Structural -- `Client.py` is not importable here."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        start = cls.source.index("async def enforce_travel_locks")
        cls.body = cls.source[start:][:cls.source[start:].index("\nasync def ", 1)]

    def test_the_credit_no_longer_reads_the_live_byte_directly(self) -> None:
        """The literal shape of the bug. `read_story_byte` still appears -- as the witness's INPUT -- but its
        result may never be what a threshold is compared against."""
        self.assertIn("ctx.story_progress.poll(", self.body)
        self.assertNotIn("story_value = ram_client.read_story_byte(ctx.block_base)", self.body)

    def test_it_shares_the_area_memory_s_own_write_flag(self) -> None:
        """Re-deriving "is a write in the air" would give the two readers of this byte independent notions of
        it, which is precisely how they come to disagree."""
        self.assertIn("ctx.area_story_memory._write_outstanding", self.body)

    def test_it_also_asks_the_parts_override(self) -> None:
        """ADDENDUM 288 moved this behind `_any_override_holding`, because this client has TWO of these
        overrides and the witness only ever heard about one. Checked as the relationship rather than as one
        function's text: the credit must consult an override helper, and that helper must name both."""
        self.assertIn("_any_override_holding(ctx)", self.body)
        start = self.source.index("def _any_override_holding")
        helper = self.source[start:self.source.index("\ndef ", start + 1)]
        for name in ("story_byte_override", "ss_libra_gate"):
            self.assertIn(name, helper, f"the override fence does not consider {name}")

    def test_the_credit_runs_before_the_writers_in_the_tick(self) -> None:
        """`enforce_travel_locks` sits outside the block-stability gate and both writers sit inside it, so on
        the tick a hover write happens the credit has already read the PRE-write byte. Pinned because
        reordering them would make the first tick of every hover a credible reading of a written value."""
        credit = self.source.index("await enforce_travel_locks(ctx)")
        override = self.source.index("await check_story_byte_override(ctx)")
        memory = self.source.index("await check_area_story_memory(ctx)")
        self.assertLess(credit, override)
        self.assertLess(credit, memory)

    def test_there_is_a_command_that_explains_a_disagreement(self) -> None:
        """`!story` shows the LIVE byte and `!progress` shows what a credit uses. Those answering differently
        is normal and is the whole point, so there has to be somewhere that says which condition is
        suppressing the live value."""
        self.assertIn("def _cmd_progress(self)", self.source)
        self.assertIn("ctx.story_progress.describe()", self.source)


if __name__ == "__main__":
    unittest.main()
