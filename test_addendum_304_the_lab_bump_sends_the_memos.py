"""ADDENDUM 304 (2026-09-20) -- the lab bump goes back to 0x0F, and takes the skipped checks with it.

Player: "Make the HQ Lab live bump from 0x0D to 0x0F again - make sure to send the checks for krane memo 1
and 2 when this happens."

THE SECOND CLAUSE IS THE LOAD-BEARING ONE. A bump SKIPS story tiers, and every check this client sends is a
threshold watcher -- so a tier the player never stands in is a tier whose checks never fire. 0x0D -> 0x0F
steps over the beat the first two Krane Memos hang off (`KRANE_MEMO_STORY_THRESHOLDS` puts them at 0x10,
judged against the area's high-water mark, which by ADDENDUM 277 never records our own writes). The memos
gate every region past Phenac City, so silently dropping them is an unwinnable seed, not a lost check.

So the bump declares what it skips, in the table, next to the skip -- and the client sends it at the instant
of the write. The declaration is plain strings because `ram_client` cannot import `locations`; the first test
below is what stops that being a place a rename can rot.
"""
from __future__ import annotations

import unittest

from .. import locations as L
from .. import travel_locations
from ..game_data import story_bytes
from .. import ram_client


def _lab_bump():
    return [b for b in story_bytes.LIVE_STORY_BYTE_BUMPS if b.region == "Pokemon HQ Lab"][0]


class TestTheBumpItself(unittest.TestCase):
    def test_it_targets_0x0F_again(self) -> None:
        self.assertEqual((0x0D, 0x0F), (_lab_bump().when_byte_is, _lab_bump().becomes))

    def test_the_paired_floor_rule_moved_with_it(self) -> None:
        """Two halves of one instruction. A floor below the bump's target would push a returning player back
        through the tier the bump exists to skip -- which is how ADDENDUM 288 had to move both at once."""
        self.assertEqual(_lab_bump().becomes,
                         story_bytes.dynamic_region_floor("Pokemon HQ Lab", {"Pokemon HQ Lab": 0x0D}))

    def test_the_window_catches_a_missed_tick(self) -> None:
        bump = _lab_bump()
        self.assertTrue(bump.applies("Pokemon HQ Lab", 0x0D))
        self.assertTrue(bump.applies("Pokemon HQ Lab", 0x0E), "the value a missed poll would land on")
        self.assertFalse(bump.applies("Pokemon HQ Lab", 0x0F), "never fires at its own target")


class TestWhatItDeclaresItSkips(unittest.TestCase):
    def test_the_declared_names_are_the_real_memo_locations(self) -> None:
        """The table holds plain strings so ram_client can read it without Archipelago imports. This is what
        keeps those strings honest."""
        self.assertEqual((L.krane_memo_location_name(1), L.krane_memo_location_name(2)),
                         _lab_bump().awards_locations)

    def test_those_locations_really_exist_in_the_world(self) -> None:
        for name in _lab_bump().awards_locations:
            self.assertIn(name, L.LOCATION_TABLE, name)

    def test_the_skip_really_does_step_over_their_threshold_witness(self) -> None:
        """Why this addendum exists at all: the bump lands BELOW the memo threshold, and its own write is
        never banked as the area mark, so nothing else would ever award them at the moment of the skip."""
        bump = _lab_bump()
        for memo in (1, 2):
            self.assertGreater(L.KRANE_MEMO_STORY_THRESHOLDS[memo], bump.becomes)

    def test_no_other_bump_claims_to_award_anything(self) -> None:
        """Guards against a future bump inheriting this list by copy-paste."""
        for bump in story_bytes.LIVE_STORY_BYTE_BUMPS:
            if bump.region != "Pokemon HQ Lab":
                self.assertEqual((), bump.awards_locations, bump.region)


class TestTheTrackerAwardsThemOnce(unittest.TestCase):
    def setUp(self) -> None:
        self.tracker = ram_client.KraneMemoTracker()

    def test_award_now_returns_the_names(self) -> None:
        self.assertEqual(["Story - Krane Memo 1", "Story - Krane Memo 2"],
                         self.tracker.award_now(_lab_bump().awards_locations))

    def test_a_second_call_returns_nothing(self) -> None:
        self.tracker.award_now(_lab_bump().awards_locations)
        self.assertEqual([], self.tracker.award_now(_lab_bump().awards_locations))

    def test_the_ordinary_poll_will_not_send_them_again(self) -> None:
        """The whole reason this routes through the tracker instead of sending straight out."""
        self.tracker.award_now(_lab_bump().awards_locations)
        later = self.tracker.poll(block_base=0, story_byte=0x10)
        self.assertEqual([], later)

    def test_the_poll_still_sends_the_other_three(self) -> None:
        """Without this the test above could pass by breaking the tracker."""
        self.tracker.award_now(_lab_bump().awards_locations)
        later = self.tracker.poll(block_base=0, story_byte=0x17)
        self.assertEqual({L.krane_memo_location_name(n) for n in (3, 4, 5)}, set(later))

    def test_an_unknown_name_is_ignored_rather_than_crashing(self) -> None:
        self.assertEqual([], self.tracker.award_now(("Something Else",)))

    def test_a_player_who_never_hits_the_bump_still_gets_them_normally(self) -> None:
        """The bump is travel-shuffle-only, so the ordinary threshold path has to keep working untouched."""
        self.assertEqual({L.krane_memo_location_name(n) for n in (1, 2)},
                         set(ram_client.KraneMemoTracker().poll(block_base=0, story_byte=0x10)))


class TestTheBumperHandsThemToTheCaller(unittest.TestCase):
    def test_a_fresh_bumper_awards_nothing(self) -> None:
        self.assertEqual((), ram_client.LiveStoryByteBumper().last_awarded_locations)

    def test_a_successful_write_publishes_the_list(self) -> None:
        bumper = ram_client.LiveStoryByteBumper()
        written = {}

        def fake_write(address, data):
            written[address] = data

        original = ram_client.write_bytes
        ram_client.write_bytes = fake_write
        try:
            result = bumper.poll(0, "Pokemon HQ Lab", 0x0D, travel_shuffle=True, scooter_shuffle=False)
        finally:
            ram_client.write_bytes = original
        self.assertIsNotNone(result)
        self.assertEqual(0x0F, result[0])
        self.assertEqual(_lab_bump().awards_locations, bumper.last_awarded_locations)
        self.assertTrue(written, "the bump must actually have written the byte")


class TestTheConsequenceIsStated(unittest.TestCase):
    def test_the_bump_now_satisfies_the_always_open_gate(self) -> None:
        """ADDENDUM 280 opens Agate and Gateon at lab 0x0F, and `_always_open_gate` has a LIVE-byte path that
        our own write satisfies. So those two destinations now open at the lab's 0x0D again. Asserted as a
        stated consequence rather than left to be discovered in play."""
        self.assertGreaterEqual(_lab_bump().becomes, travel_locations.ALWAYS_OPEN_GATE_BYTE)


if __name__ == "__main__":
    unittest.main()
