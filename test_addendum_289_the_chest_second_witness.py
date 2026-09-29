"""ADDENDUM 289 (2026-09-19) -- a chest credits on evidence now, not on a clock.

Player: "Can we speed up the chest polling?"

THE POLL RATE WAS NEVER WHAT WAS SLOW, and ADDENDUM 262 already established that: chests have run on the 0.1s
fast sub-loop since then. The two seconds a player waits are `_CONFIRM_SECONDS`, and ADDENDUM 262 deliberately
made that window rate-proof -- two seconds is two seconds however often you look. Which is exactly the wall
ADDENDUM 259 hit for shops, and it gets ADDENDUM 263's answer: replace the window with BETTER EVIDENCE rather
than less of it.

A shop purchase is a berry up AND money down. A chest's second witness is the game's own per-chest "already
opened" bit, measured live in ADDENDUM 173 and located for 96 of the 115 chests, all inside one 132-byte band
-- one read per poll for the whole set.

WHY THE PAIR IS UNFAKEABLE BY THE FAILURE THE WINDOW GUARDS AGAINST. The window exists for the save-menu
glitch, where the block serves a STALE SNAPSHOT. A stale snapshot is internally consistent -- old berry count
AND old flags together -- and a rewind moves a flag SET -> CLEAR. A flag going CLEAR -> SET is the one thing it
cannot produce.

NARROW BY CONSTRUCTION, which is what makes it safe to be fast: an unreadable band, one of the 19 chests with
no measured flag, a first poll with nothing to diff against, or a flip outside the corroboration window all
fall through to the UNTOUCHED streak and clock. **The worst this can do is fail to speed something up**, and
the tests below are mostly about proving that rather than proving the happy path.
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

if "dolphin_memory_engine" not in sys.modules:
    _stub = types.ModuleType("dolphin_memory_engine")
    _stub.hook = lambda: None
    _stub.un_hook = lambda: None
    _stub.is_hooked = lambda: False
    _stub.read_bytes = lambda address, length: b""
    _stub.write_bytes = lambda address, data: None
    sys.modules["dolphin_memory_engine"] = _stub

from .. import ram_client as rc
from ..game_data import chest_berries, chest_flags

BLOCK = 0x80479000


class _Fake:
    """A block with one berry quantity and one flag band, both driven by the test."""

    def __init__(self) -> None:
        start, length = rc._validated_flag_span()
        self.flag_start, self.flag_len = start, length
        self.flags = bytearray(length)
        self.quantities: "dict[int, int]" = {}
        self.now = 1000.0

    def clock(self) -> float:
        return self.now

    def open_chest(self, chest_id: int) -> None:
        offset, mask = chest_flags.chest_byte_offset_and_mask(chest_id)
        self.flags[offset - self.flag_start] |= mask

    def read_bytes(self, address, length):
        base = BLOCK + self.flag_start
        if address == base and length == self.flag_len:
            return bytes(self.flags)
        raise RuntimeError("not the flag band")

    def install(self, test, tracker):
        p1 = mock.patch.object(rc, "read_bytes", self.read_bytes)
        p2 = mock.patch.object(rc, "find_item_quantity",
                               lambda base, slots, berry: self.quantities.get(berry, 0))
        p3 = mock.patch.object(rc, "resolve_item_read_window", lambda base, berry: (base, 1))
        p4 = mock.patch.object(tracker, "_clear", lambda *a, **k: None)
        for p in (p1, p2, p3, p4):
            p.start(); test.addCleanup(p.stop)


def _a_chest_with_a_validated_flag():
    """A (chest_id, room_id, berry_id) triple that both tables agree on."""
    for (room, berry), chest in sorted(chest_berries.ROOM_BERRY_TO_CHEST.items()):
        if chest_flags.chest_flag_is_validated(chest) and chest in rc.CHEST_ID_TO_LOCATION:
            return chest, room, berry
    return None


class TestTheBandIsDerivedNotTyped(unittest.TestCase):
    def test_the_span_covers_every_validated_flag(self) -> None:
        span = rc._validated_flag_span()
        self.assertIsNotNone(span)
        start, length = span
        for _, offset, _ in rc._validated_flag_bits():
            self.assertTrue(start <= offset < start + length)

    def test_only_measured_flags_are_watched(self) -> None:
        """ADDENDUM 201's rule. A chest this module can locate arithmetically but has never measured must not
        be used as evidence for anything."""
        watched = {chest for chest, _, _ in rc._validated_flag_bits()}
        for chest_id in chest_flags.unvalidated_chest_ids():
            self.assertNotIn(chest_id, watched, chest_id)
        self.assertTrue(watched)

    def test_it_is_one_read(self) -> None:
        _, length = rc._validated_flag_span()
        self.assertLess(length, 512, "if this ever grows, stop calling it one cheap read")


class TestTheFastPath(unittest.TestCase):
    def setUp(self) -> None:
        picked = _a_chest_with_a_validated_flag()
        if picked is None:
            self.skipTest("no chest with both a validated flag and an AP location in this build")
        self.chest, self.room, self.berry = picked
        self.fake = _Fake()
        self.tracker = rc.ChestBerryTracker(clock=self.fake.clock)
        self.fake.install(self, self.tracker)

    def _poll(self):
        return self.tracker._poll(BLOCK, self.room, frozenset(), chest_berries)

    def test_a_corroborated_pickup_credits_on_the_very_first_poll(self) -> None:
        """THE POINT. No streak, no two seconds -- the clock never advances in this test at all."""
        self.fake.quantities[self.berry] = 0
        self._poll()                                   # baseline the berry and the flag band
        self.fake.open_chest(self.chest)
        self.fake.quantities[self.berry] = 1
        names = self._poll()
        self.assertEqual([rc.CHEST_ID_TO_LOCATION[self.chest]], names)
        self.assertEqual(1, self.tracker.flag_corroborated)
        self.assertEqual(1000.0, self.fake.now, "credited without any time passing")

    def test_without_the_flag_it_waits_for_the_second_read_and_nothing_else(self) -> None:
        """RETARGETED BY ADDENDUM 375. This asserted the fallback "still waits the full window", and the window
        is gone -- the streak is the debounce now. The fallback itself is untouched, which is this addendum's
        actual claim: a berry rise with no corroborating flag does NOT take the fast path, and is credited on
        the second agreeing read rather than on a clock."""
        self.fake.quantities[self.berry] = 0
        self._poll()
        self.fake.quantities[self.berry] = 1
        self.assertEqual([], self._poll(), "first rise -- streak not met")
        self.assertEqual([rc.CHEST_ID_TO_LOCATION[self.chest]], self._poll(), "second agreeing read credits")
        self.assertEqual(0, self.tracker.flag_corroborated,
                         "this is the SLOW path -- the flag pair must not have been what credited it")

    def test_a_flag_that_was_already_set_corroborates_nothing(self) -> None:
        """Only a CLEAR -> SET transition is evidence. A chest opened long ago must not vouch for a berry
        that turned up now."""
        self.fake.open_chest(self.chest)
        self.fake.quantities[self.berry] = 0
        self._poll()                                   # the flag is set in the very first snapshot
        self.fake.quantities[self.berry] = 1
        self.assertEqual([], self._poll())
        self.assertEqual(0, self.tracker.flag_corroborated)

    def test_the_first_poll_never_corroborates(self) -> None:
        """There is nothing to diff against, so a band full of already-open chests cannot read as a burst of
        openings."""
        self.fake.open_chest(self.chest)
        self.fake.quantities[self.berry] = 1
        self.assertEqual([], self._poll())
        self.assertEqual(0, self.tracker.flag_transitions_seen)

    def test_an_old_flip_expires_rather_than_vouching_later(self) -> None:
        self.fake.quantities[self.berry] = 0
        self._poll()
        self.fake.open_chest(self.chest)
        self._poll()                                   # the flip is seen, no berry yet
        self.assertEqual(1, self.tracker.flag_transitions_seen)
        self.fake.now += self.tracker._FLAG_CORROBORATION_SECONDS + 0.01
        self.fake.quantities[self.berry] = 1
        self.assertEqual([], self._poll(), "the flip is too old to vouch for this berry")
        self.assertEqual(0, self.tracker.flag_corroborated)

    def test_a_flip_a_poll_early_still_vouches(self) -> None:
        """The flag and the berry do not have to land on the same tick -- only within the window."""
        self.fake.quantities[self.berry] = 0
        self._poll()
        self.fake.open_chest(self.chest)
        self._poll()
        self.fake.now += 0.1
        self.fake.quantities[self.berry] = 1
        self.assertEqual([rc.CHEST_ID_TO_LOCATION[self.chest]], self._poll())
        self.assertEqual(1, self.tracker.flag_corroborated)

    def test_another_rooms_chest_does_not_vouch(self) -> None:
        """"Some chest somewhere was opened" would credit a berry to a pickup in a different room. Both the
        EVENT and the IDENTITY have to agree."""
        other = next((c for c, _, _ in rc._validated_flag_bits() if c != self.chest), None)
        if other is None:
            self.skipTest("only one validated chest in this build")
        self.fake.quantities[self.berry] = 0
        self._poll()
        self.fake.open_chest(other)
        self.fake.quantities[self.berry] = 1
        names = self._poll()
        if names:
            self.assertEqual(0, self.tracker.flag_corroborated,
                             "a credit here must have come from the clock, not from another room's flag")

    def test_an_unreadable_band_falls_back_rather_than_crediting(self) -> None:
        self.fake.quantities[self.berry] = 0
        self._poll()
        with mock.patch.object(rc, "read_bytes", side_effect=RuntimeError("no dolphin")):
            self.fake.quantities[self.berry] = 1
            self.assertEqual([], self._poll())
        self.assertGreaterEqual(self.tracker.flag_reads_failed, 1)
        self.assertEqual(0, self.tracker.flag_corroborated)

    def test_a_failed_read_drops_the_snapshot_rather_than_diffing_across_a_gap(self) -> None:
        self.fake.quantities[self.berry] = 0
        self._poll()
        with mock.patch.object(rc, "read_bytes", side_effect=RuntimeError("no dolphin")):
            self._poll()
        self.assertIsNone(self.tracker._flag_bytes)
        # The chest opened DURING the gap; the next poll re-baselines and must not read it as a transition.
        self.fake.open_chest(self.chest)
        self.fake.quantities[self.berry] = 1
        self.assertEqual([], self._poll())
        self.assertEqual(0, self.tracker.flag_corroborated)


class TestTheSlowPathIsUntouched(unittest.TestCase):
    """ADDENDUM 262's two windows keep their opposite treatments -- that asymmetry is load-bearing."""

    def test_the_slow_path_still_has_a_real_window_and_a_real_streak(self) -> None:
        """RETARGETED 2026-09-27 (ADDENDUM 373), which took this window from 2.0 to 0.5 on the player's
        instruction. This addendum's point is not the NUMBER -- it is that the flag pair short-circuits the
        slow path while the slow path stays intact behind it for the ~19 chests with no measured flag. So what
        is asserted is that the slow path is still really there: a window above zero, and the two-read streak
        that `set_poll_interval` could otherwise have collapsed to one when the window went below the poll
        interval."""
        self.assertEqual(0.0, rc.CONFIRM_WINDOW_SECONDS["chest_berry"])   # ADDENDUM 375
        self.assertGreaterEqual(rc.ChestBerryTracker._CONFIRM_STREAK,
                                rc.ChestBerryTracker._MIN_CONFIRM_STREAK)
        self.assertEqual(2, rc.ChestBerryTracker._MIN_CONFIRM_STREAK)

    def test_the_pending_deadline_is_still_a_floor_not_a_ceiling(self) -> None:
        self.assertEqual(4.0, rc.CONFIRM_WINDOW_SECONDS["chest_pending"])
        self.assertGreater(rc.CONFIRM_WINDOW_SECONDS["chest_pending"],
                           rc.CONFIRM_WINDOW_SECONDS["chest_berry"])

    def test_the_corroboration_window_spans_the_gap_between_the_two_signals(self) -> None:
        """RETARGETED BY ADDENDUM 344. This used to assert the corroboration window was SHORTER than the
        debounce it replaces, on the reading that it was a faster substitute for the same job. It is not the
        same job. The debounce waits out a suspect signal; this window waits for the SECOND signal to arrive,
        and the two do not land together -- the flag flips when the chest is opened, the berry lands after the
        animation and the message. A window shorter than the debounce guaranteed the flip was discarded before
        most berries turned up, which is the bug ADDENDUM 344 fixed. It has to be comfortably longer."""
        self.assertGreater(rc.ChestBerryTracker._FLAG_CORROBORATION_SECONDS,
                           rc.CONFIRM_WINDOW_SECONDS["chest_berry"])

    def test_it_is_still_short_enough_not_to_span_leaving_the_room(self) -> None:
        """The other side of the same number. Identity is still required, so a wide window admits no chest a
        narrow one would reject -- but it should not be so wide that it outlives the visit."""
        self.assertLessEqual(rc.ChestBerryTracker._FLAG_CORROBORATION_SECONDS, 15.0)


class TestAddendum344TheWindowSpansTheAnimation(unittest.TestCase):
    """Player, with ADDENDUM 289 already running: "Please speed up the chest polling again."

    ADDENDUM 289's fast path was correct and was firing almost never, because `_FLAG_CORROBORATION_SECONDS`
    was 1.0s and the berry does not reach the Bag within a second of the chest opening. The flip was seen,
    pruned, and the pickup fell through to the very 2.0s clock the fast path exists to skip.
    """

    def setUp(self) -> None:
        picked = _a_chest_with_a_validated_flag()
        if picked is None:
            self.skipTest("no chest with both a validated flag and an AP location in this build")
        self.chest, self.room, self.berry = picked
        self.fake = _Fake()
        self.tracker = rc.ChestBerryTracker(clock=self.fake.clock)
        self.fake.install(self, self.tracker)

    def _poll(self):
        return self.tracker._poll(BLOCK, self.room, frozenset(), chest_berries)

    def test_a_berry_arriving_after_the_animation_still_corroborates(self) -> None:
        """THE POINT OF THE ADDENDUM. At the old 1.0s this fell through to the clock."""
        self.fake.quantities[self.berry] = 0
        self._poll()
        self.fake.open_chest(self.chest)
        self._poll()                                   # the flip is seen; the berry is still coming
        self.fake.now += 2.5                           # opening animation + "obtained" message
        self.fake.quantities[self.berry] = 1
        self.assertEqual([rc.CHEST_ID_TO_LOCATION[self.chest]], self._poll())
        self.assertEqual(1, self.tracker.flag_corroborated)

    def test_the_old_one_second_window_would_not_have(self) -> None:
        """Stated as a test so the regression is named rather than remembered."""
        self.fake.quantities[self.berry] = 0
        self._poll()
        self.fake.open_chest(self.chest)
        self._poll()
        self.fake.now += 2.5
        self.assertGreater(self.fake.now - 1000.0, 1.0,
                           "this gap is exactly what the 1.0s window used to discard")
        self.assertLess(self.fake.now - 1000.0, rc.ChestBerryTracker._FLAG_CORROBORATION_SECONDS)

    def test_a_spent_transition_is_not_counted_as_expired(self) -> None:
        """`flag_transitions_expired` is the instrument for whether the window is wide enough, so it has to
        mean exactly one thing: a flip that was seen and never used."""
        self.fake.quantities[self.berry] = 0
        self._poll()
        self.fake.open_chest(self.chest)
        self.fake.quantities[self.berry] = 1
        self.assertEqual([rc.CHEST_ID_TO_LOCATION[self.chest]], self._poll())
        self.fake.now += rc.ChestBerryTracker._FLAG_CORROBORATION_SECONDS + 1.0
        self._poll()
        self.assertEqual(0, self.tracker.flag_transitions_expired,
                         "a flip that credited a pickup must never also read as wasted")

    def test_an_unused_transition_is_counted(self) -> None:
        self.fake.quantities[self.berry] = 0
        self._poll()
        self.fake.open_chest(self.chest)
        self._poll()
        self.fake.now += rc.ChestBerryTracker._FLAG_CORROBORATION_SECONDS + 0.01
        self._poll()
        self.assertEqual(1, self.tracker.flag_transitions_expired)

    def test_describe_reports_the_instrument(self) -> None:
        text = "\n".join(self.tracker.describe())
        self.assertIn("expired unused", text)
        self.assertIn("6.0s", text)

    def test_one_flip_credits_one_pickup(self) -> None:
        """Spending the transition also stops a single opening vouching for a second berry rise."""
        self.fake.quantities[self.berry] = 0
        self._poll()
        self.fake.open_chest(self.chest)
        self.fake.quantities[self.berry] = 1
        self.assertEqual([rc.CHEST_ID_TO_LOCATION[self.chest]], self._poll())
        self.assertEqual(1, self.tracker.flag_corroborated)
        self.fake.quantities[self.berry] = 1            # the clear put it back to 0; rise again
        self._poll()
        self._poll()
        self.assertEqual(1, self.tracker.flag_corroborated,
                         "the flip was already spent -- a second rise must earn the clock")


if __name__ == "__main__":
    unittest.main()
