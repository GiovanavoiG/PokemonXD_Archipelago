"""ADDENDUM 284 (2026-09-19): a COMMITTED travel write is still a write, and still not progress.

Player, with two screenshots -- seven `Unlock -` checks and seven "found their" lines:

    "All of these sent upon visiting Gateon because I visited Realgam first. The story byte wrote to 0x0F
    correctly - is our second tracker not updating correctly?"

## The sequence, and it is exactly seven checks for a reason

Realgam Tower's entry floor is 0x41. Travelling there COMMITS that value -- `left_map_screen(backed_out=
False)` releases `_write_outstanding` precisely because the written byte is what the room is about to be
built from. So on the arrival tick the byte reads 0x41, no write is outstanding, no override is active, and
the room is not the map screen: `StoryProgressWitness` banked it as credible. Travel on to Gateon Port and
the live byte goes back to 0x0F -- correctly, as the player says -- but the high-water mark does not, because
a high-water mark is the one thing that never comes down.

Then ADDENDUM 268's where-are-you guard waves everything through: it asks whether the player's own region
sits strictly BEFORE the threshold on the path, and Gateon's floor (0x0F) is before every threshold there is.
Count the thresholds at or below 0x41 and the answer is seven. It is the screenshot.

## Why the old argument for leaving it was wrong

The 265 docstring said undoing this "would mean refusing credit for byte values the save file really holds".
The save file really holds 0x41 because THIS CLIENT wrote it, seconds earlier. ADDENDUM 277 struck the same
sentence out of `observe()` -- "a byte this client wrote is not a byte to record from ... it holds whether
the player went where we pointed or somewhere else" -- and the credit never got that memo either. That is now
the fourth time this project has found a reader of this byte with no ownership test, so the register's
standing sweep (*who else reads a value this client writes without asking whether we wrote it?*) stands.

## The fix, and its cost

`last_written_target` is passed from the area memory rather than tracked here, for the same reason
`_write_outstanding` already is: two readers with independent notions of "did we write this" is how they come
to disagree. It is never cleared, so the refusal lasts as long as the byte still equals our write.

The cost is one value, held and never dropped: a threshold equal to a floor we wrote waits until the game
advances past it, which is what playing the area does. Real progress is untouched -- play Realgam to 0x43 and
0x43 banks normally, and every threshold beneath it is credited as soon as the player stands somewhere at or
before it.
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
from ..game_data import story_bytes

IN_A_ROOM = 138          # Pokemon HQ Lab interior -- an ordinary gameplay room
MAP = rc.MAP_SCREEN_ROOM_ID

REALGAM_FLOOR = story_bytes.area_entry_floor("Realgam Tower")
GATEON_FLOOR = story_bytes.area_entry_floor("Gateon Port")


def _poll(witness, value, room=IN_A_ROOM, write=False, override=False, ours=None):
    return witness.poll(value, room, write, override, ours)


class TestTheReportedSequence(unittest.TestCase):
    """The player's own words, step by step, against the real floor and threshold tables."""

    def test_realgams_floor_and_the_threshold_count_are_what_was_reported(self) -> None:
        """Seven checks is not a round number -- it is how many thresholds sit at or below 0x41. If the data
        changes this test says so rather than letting the reconstruction below drift into fiction."""
        self.assertEqual(0x41, REALGAM_FLOOR)
        self.assertEqual(0x10, GATEON_FLOOR)   # ADDENDUM 379 -- was 0x0F
        thresholds = [t for name in travel_locations.TRAVEL_LOCATION_NAMES
                      if (t := travel_locations.vanilla_unlock_story_byte(name)) is not None]
        self.assertEqual(7, len([t for t in thresholds if t <= REALGAM_FLOOR]))

    def test_the_arrival_tick_at_realgam_is_not_credible(self) -> None:
        """THE BUG. No write outstanding (the travel committed it), not the map screen, no override -- every
        pre-284 condition says "credible", and the value is ours."""
        w = rc.StoryProgressWitness()
        _poll(w, 0x0F, ours=0x0F)                       # standing in Gateon before the trip
        self.assertEqual(-1, w.high_water)
        for _ in range(10):                             # the room sits there for many ticks
            self.assertLess(_poll(w, REALGAM_FLOOR, ours=REALGAM_FLOOR), REALGAM_FLOOR)
        self.assertGreaterEqual(w.declined_our_own_write, 10)
        self.assertIn("client wrote", w.last_reason or "")

    def test_travelling_back_to_gateon_credits_nothing(self) -> None:
        """The whole reported sequence, end to end: Gateon -> map -> Realgam -> map -> Gateon."""
        w = rc.StoryProgressWitness()
        _poll(w, 0x0F, ours=0x0F)
        _poll(w, REALGAM_FLOOR, room=MAP, write=True, ours=REALGAM_FLOOR)   # hovering Realgam
        for _ in range(5):
            _poll(w, REALGAM_FLOOR, ours=REALGAM_FLOOR)                     # standing in Realgam
        _poll(w, GATEON_FLOOR, room=MAP, write=True, ours=GATEON_FLOOR)     # hovering Gateon
        for _ in range(5):
            _poll(w, GATEON_FLOOR, ours=GATEON_FLOOR)                       # standing in Gateon

        self.assertLess(w.high_water, min(
            t for name in travel_locations.TRAVEL_LOCATION_NAMES
            if (t := travel_locations.vanilla_unlock_story_byte(name)) is not None
        ), "not one `Unlock -` threshold may be cleared by two map trips and no play")

    def test_before_the_fix_the_same_sequence_fired_all_seven(self) -> None:
        """The counterfactual, so this file proves the fix DOES something. Omitting `ours` is the pre-284
        call, and it is left working on purpose (the parameter defaults to None)."""
        w = rc.StoryProgressWitness()
        w.poll(REALGAM_FLOOR, IN_A_ROOM, False, False)
        self.assertEqual(REALGAM_FLOOR, w.high_water)
        fired = [name for name in travel_locations.TRAVEL_LOCATION_NAMES
                 if (t := travel_locations.vanilla_unlock_story_byte(name)) is not None
                 and w.high_water >= t
                 and (GATEON_FLOOR is None or GATEON_FLOOR < t)]
        self.assertEqual(7, len(fired), "the screenshot, reproduced")


class TestRealProgressIsUntouched(unittest.TestCase):
    """The standing rule: a check may be late, never lost. Nothing here may cost a legitimate credit."""

    def test_the_game_advancing_past_our_write_banks_normally(self) -> None:
        w = rc.StoryProgressWitness()
        _poll(w, REALGAM_FLOOR, ours=REALGAM_FLOOR)
        self.assertEqual(REALGAM_FLOOR + 2, _poll(w, REALGAM_FLOOR + 2, ours=REALGAM_FLOOR))
        self.assertEqual(1, w.credible_polls)

    def test_a_held_value_lands_the_moment_the_byte_moves(self) -> None:
        """"Held, not dropped" is the whole defence of refusing a value. Measured: the credit for every
        threshold at or below our write arrives one tick after the game advances."""
        w = rc.StoryProgressWitness()
        for _ in range(50):
            _poll(w, REALGAM_FLOOR, ours=REALGAM_FLOOR)
        self.assertLess(w.high_water, REALGAM_FLOOR)
        _poll(w, REALGAM_FLOOR + 1, ours=REALGAM_FLOOR)
        cleared = [name for name in travel_locations.TRAVEL_LOCATION_NAMES
                   if (t := travel_locations.vanilla_unlock_story_byte(name)) is not None
                   and w.high_water >= t]
        self.assertEqual(7, len(cleared), "everything held is credited on the next real byte")

    def test_a_value_we_never_wrote_is_credible_even_if_it_equals_a_floor(self) -> None:
        """The test is what WE wrote, not whether the number happens to be some area's floor. A player who
        reaches 0x41 by playing, having never travelled to Realgam, is credited for it."""
        w = rc.StoryProgressWitness()
        self.assertEqual(REALGAM_FLOOR, _poll(w, REALGAM_FLOOR, ours=0x0F))

    def test_nothing_written_yet_means_nothing_refused(self) -> None:
        w = rc.StoryProgressWitness()
        self.assertEqual(0x23, _poll(w, 0x23, ours=None))
        self.assertEqual(0, w.declined_our_own_write)

    def test_the_high_water_mark_still_never_comes_down(self) -> None:
        """A refusal is not a rollback. ADDENDUM 265's dip rule is unchanged."""
        w = rc.StoryProgressWitness()
        _poll(w, 0x5A, ours=None)
        _poll(w, 0x0F, ours=0x0F)
        self.assertEqual(0x5A, w.high_water)

    def test_the_older_suppressions_still_win_and_are_still_named(self) -> None:
        """Ordering matters for the diagnostic: on the map screen with our own value, the player should be
        told it is the map screen -- the condition they can see -- not the subtler one."""
        w = rc.StoryProgressWitness()
        _poll(w, 0x41, room=MAP, write=True, ours=0x41)
        self.assertIn("map screen", w.last_reason or "")
        self.assertEqual(0, w.declined_our_own_write)


class TestTheDiagnosticSaysSo(unittest.TestCase):
    def test_describe_reports_the_refusals(self) -> None:
        w = rc.StoryProgressWitness()
        _poll(w, REALGAM_FLOOR, ours=REALGAM_FLOOR)
        text = "\n".join(w.describe())
        self.assertIn("284", text)
        self.assertIn("own write", text)

    def test_describe_is_quiet_when_nothing_was_refused(self) -> None:
        w = rc.StoryProgressWitness()
        _poll(w, 0x23, ours=None)
        self.assertNotIn("284", "\n".join(w.describe()))


class TestTheClientWiring(unittest.TestCase):
    """Structural -- `Client.py` is not importable here."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        start = cls.source.index("async def enforce_travel_locks")
        cls.body = cls.source[start:][:cls.source[start:].index("\nasync def ", 1)]

    def test_the_credit_passes_the_area_memorys_own_last_write(self) -> None:
        """Re-deriving it here would give the two readers of this byte independent notions of what we wrote,
        which is precisely how they came to disagree in the first place."""
        self.assertIn("ctx.area_story_memory.last_written_target", self.body)

    def test_all_four_inputs_are_still_wired(self) -> None:
        for expected in ("ctx.area_story_memory._write_outstanding",
                         # ADDENDUM 288: both overrides, via the shared helper.
                         "_any_override_holding(ctx)",
                         "ctx.area_story_memory.last_written_target"):
            self.assertIn(expected, self.body, expected)
        start = self.source.index("def _any_override_holding")
        helper = self.source[start:self.source.index("\ndef ", start + 1)]
        for name in ("story_byte_override", "ss_libra_gate"):
            self.assertIn(name, helper, f"the override fence does not consider {name}")

    def test_the_witness_is_the_only_source_of_the_credited_value(self) -> None:
        self.assertIn("ctx.story_progress.poll(", self.body)
        self.assertNotIn("story_value = ram_client.read_story_byte(ctx.block_base)", self.body)


if __name__ == "__main__":
    unittest.main()
