"""ADDENDUM 139 (2026-09-11): live story-byte readout and automatic change logging.

Player request: "Can you wire in a feature to check my story byte too?" Sixteen checkpoints have been captured
by hand so far, each one a bridge round trip plus a manual doc edit. The client can just watch it."""
from __future__ import annotations

import unittest
from unittest import mock

from .. import ram_client as rc

BLOCK_BASE = 0x80479380

# Real records from pokemon-xd-story-flags.md, checkpoints 13-16 of the current playthrough.
CKPT_13 = bytes.fromhex("280000000a400626082020003fcc002a8a011964")
CKPT_14 = bytes.fromhex("2bc000000a400626082020003fcc002a8a011964")
CKPT_15 = bytes.fromhex("2d0000000a400626082020003fcc002a8a011964")
CKPT_16 = bytes.fromhex("2f8000000a400626082020003fcc002a8a011964")


class _FakeRam:
    def __init__(self, record: bytes, explode: bool = False) -> None:
        self.record = record
        self.explode = explode

    def read(self, address: int, length: int) -> bytes:
        if self.explode:
            raise RuntimeError("Dolphin went away")
        if address == BLOCK_BASE + rc.STORY_RECORD_OFFSET:
            return self.record[:length]
        return bytes(length)


class _Patched:
    def __init__(self, record: bytes, explode: bool = False) -> None:
        self.fake = _FakeRam(record, explode)

    def __enter__(self):
        self._orig = rc.read_bytes
        rc.read_bytes = self.fake.read
        return self.fake

    def __exit__(self, *exc):
        rc.read_bytes = self._orig


class TestReadStoryByte(unittest.TestCase):
    def test_it_reads_the_real_recorded_checkpoints(self) -> None:
        for record, expected in ((CKPT_13, 0x28), (CKPT_14, 0x2B), (CKPT_15, 0x2D), (CKPT_16, 0x2F)):
            with _Patched(record):
                self.assertEqual(rc.read_story_byte(BLOCK_BASE), expected)

    def test_the_full_record_is_available_verbatim(self) -> None:
        """The story-flags doc records the whole 20-byte blob, so `!story` has to be able to print it."""
        with _Patched(CKPT_15):
            self.assertEqual(rc.read_story_record(BLOCK_BASE).hex(), CKPT_15.hex())

    def test_a_failing_read_returns_none_rather_than_raising(self) -> None:
        with _Patched(CKPT_13, explode=True):
            self.assertIsNone(rc.read_story_byte(BLOCK_BASE))

    def test_0xff_is_rejected_as_implausible(self) -> None:
        """0xFF has only ever been seen as a deliberate test write (checkpoint 12), never as real progress --
        so it must not be reported as a story value the player might act on."""
        with _Patched(b"\xff" + CKPT_13[1:]):
            self.assertIsNone(rc.read_story_byte(BLOCK_BASE))


class TestStoryByteTracker(unittest.TestCase):
    def _poll(self, tracker, record):
        with _Patched(record):
            return tracker.poll(BLOCK_BASE)

    def test_the_first_sighting_is_not_an_advance(self) -> None:
        t = rc.StoryByteTracker()
        self.assertIsNone(self._poll(t, CKPT_13))
        self.assertEqual(t.current, 0x28)
        self.assertEqual(t.advances, 0)

    def test_the_real_checkpoint_sequence_reports_each_advance_once(self) -> None:
        t = rc.StoryByteTracker()
        seen = []
        for record in (CKPT_13, CKPT_13, CKPT_14, CKPT_14, CKPT_15, CKPT_16, CKPT_16):
            got = self._poll(t, record)
            if got:
                seen.append(got)
        self.assertEqual(seen, [(0x28, 0x2B), (0x2B, 0x2D), (0x2D, 0x2F)])
        self.assertEqual(t.advances, 3)
        self.assertEqual(t.current, 0x2F)

    def test_neighbour_drift_alone_is_never_reported_as_progress(self) -> None:
        """+0x01 went 0x00 -> 0xC0 -> 0x00 across real checkpoints with no player action. Only +0x00 counts."""
        drifted = bytes([CKPT_15[0], 0xC0]) + CKPT_15[2:]
        t = rc.StoryByteTracker()
        self._poll(t, CKPT_15)
        self.assertIsNone(self._poll(t, drifted), "a neighbour moving is not a story advance")
        self.assertEqual(t.advances, 0)
        self.assertEqual(t.record, drifted, "but the record shown by !story is still kept current")

    def test_an_unreadable_poll_does_not_disturb_the_tracked_value(self) -> None:
        t = rc.StoryByteTracker()
        self._poll(t, CKPT_14)
        with _Patched(CKPT_14, explode=True):
            self.assertIsNone(t.poll(BLOCK_BASE))
        self.assertEqual(t.current, 0x2B)

    def test_describe_names_a_known_landmark_and_shows_the_record(self) -> None:
        t = rc.StoryByteTracker()
        self._poll(t, CKPT_14)
        text = t.describe()
        self.assertIn("0x2B", text)
        self.assertIn("Lovrina defeated", text)
        self.assertIn(CKPT_14.hex(), text)
        self.assertIn("drift", text, "the +0x01 caveat must travel with the readout")

    def test_describe_before_any_read(self) -> None:
        self.assertIn("not read yet", rc.StoryByteTracker().describe())

    def test_every_landmark_is_a_value_the_doc_actually_recorded(self) -> None:
        for value in rc.STORY_BYTE_LANDMARKS:
            self.assertLessEqual(value, rc.STORY_BYTE_MAX_PLAUSIBLE)
        self.assertEqual(rc.STORY_BYTE_LANDMARKS[0x2D], "Purify Chamber unlocked")

    def test_the_record_offset_matches_travel_locations(self) -> None:
        """These are duplicated constants -- if they ever drift apart the story byte silently reads garbage."""
        from .. import travel_locations

        self.assertEqual(rc.STORY_RECORD_OFFSET, travel_locations.TRAVEL_RECORD_OFFSET_FROM_BLOCK_BASE)


if __name__ == "__main__":
    unittest.main()


class TestAnImplausibleByteIsUnreadableNotUnchanged(unittest.TestCase):
    """ADDENDUM 256 (2026-09-17). Player, after 0xFF had been written into the byte by hand: "Why does /story
    still show 0x6E in the arch client?"

    Because `poll` bailed on the implausible value before updating anything and `describe()` then reported
    `self.current` -- the last value it happened to trust, minutes stale -- with nothing marking it as old. The
    reasonable conclusion was that the write had not taken.

    Refusing to ADVANCE on an implausible value stays right (logging a transition to 0xFF would be inventing
    one). Presenting a stale number as the live one is the part that misled."""

    def _tracker_at(self, value):
        tracker = rc.StoryByteTracker()
        tracker.current, tracker.previous, tracker.advances = value, 0x43, 1
        return tracker

    def test_an_implausible_byte_does_not_become_the_current_value(self) -> None:
        tracker = self._tracker_at(0x6E)
        tracker.last_implausible = 0xFF
        self.assertEqual(0x6E, tracker.current, "the last trusted value is still worth keeping")

    def test_describe_says_unreadable_rather_than_the_stale_number(self) -> None:
        tracker = self._tracker_at(0x6E)
        tracker.last_implausible = 0xFF
        text = tracker.describe()
        self.assertIn("0xFF", text)
        self.assertIn("UNREADABLE", text)
        self.assertNotIn("Story byte: 0x6E", text, "the stale value must not lead the line")
        self.assertIn("history, not what is in memory now", text)

    def test_a_plausible_byte_clears_the_flag_and_reports_normally(self) -> None:
        tracker = self._tracker_at(0x6E)
        tracker.last_implausible = 0xFF
        record = bytearray(20)
        record[rc.STORY_BYTE_OFFSET] = 0x70
        with mock.patch.object(rc, "read_story_record", return_value=bytes(record)):
            change = tracker.poll(BLOCK_BASE)
        self.assertEqual((0x6E, 0x70), change)
        self.assertIsNone(tracker.last_implausible)
        self.assertIn("Story byte: 0x70", tracker.describe())

    def test_polling_an_implausible_byte_records_it_and_reports_no_advance(self) -> None:
        tracker = self._tracker_at(0x6E)
        record = bytearray(20)
        record[rc.STORY_BYTE_OFFSET] = 0xFF
        with mock.patch.object(rc, "read_story_record", return_value=bytes(record)):
            self.assertIsNone(tracker.poll(BLOCK_BASE), "0xFF is not an advance")
        self.assertEqual(0xFF, tracker.last_implausible)
        self.assertEqual(0x6E, tracker.current)
        self.assertIn("UNREADABLE", tracker.describe())
