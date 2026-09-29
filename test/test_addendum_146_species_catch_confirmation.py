"""ADDENDUM 146 (2026-09-11): the save-menu glitch reaching "Catch - {species}" locations.

Player report: "Opening the save menu is sending checks for pokemon caught on the previous save -- fix the same
as the other dupe checks?"

Same family as ADDENDUM 98/99, but with a worse failure cost: the chest and purification versions of this bug
sent locations early that were going to be checked anyway, so the server's dedup absorbed them. This one sends
locations that should never have been checked at all, and nothing can take them back. So the tests below are
written around the glitch shapes, not just around "does the streak count to four".
"""
from __future__ import annotations

import unittest

from .. import ram_client as rc

STREAK = rc.SpeciesCatchTracker._CONFIRM_STREAK


def _hold(tracker, party, box, polls):
    """Polls the same pair `polls` times and returns everything fired across them."""
    fired = []
    for _ in range(polls):
        fired += tracker.poll(party, box)
    return fired


class TestPriming(unittest.TestCase):
    def test_the_first_poll_reports_everything_already_owned(self) -> None:
        """A fresh connection (or a reconnect mid-seed) must still send the catches the player already has --
        there is no earlier snapshot to validate a first reading against, and the server dedupes."""
        t = rc.SpeciesCatchTracker()
        self.assertEqual(t.poll({25, 133}, {6, 9}), [6, 9, 25, 133])
        self.assertTrue(t.primed)

    def test_priming_twice_reports_nothing_new(self) -> None:
        t = rc.SpeciesCatchTracker()
        t.poll({25}, {6})
        self.assertEqual(t.poll({25}, {6}), [])


class TestPartyIsUnchanged(unittest.TestCase):
    """Guard 1. The common path -- catch with room in the party -- must not get slower."""

    def test_a_new_party_species_fires_on_the_very_same_poll(self) -> None:
        t = rc.SpeciesCatchTracker()
        t.poll({25}, set())
        self.assertEqual(t.poll({25, 196}, set()), [196])

    def test_it_fires_even_on_a_poll_whose_box_half_is_discarded(self) -> None:
        """The box being untrustworthy says nothing about the live party struct."""
        t = rc.SpeciesCatchTracker()
        t.poll({25}, {6, 9})
        fired = t.poll({25, 196}, {380, 381, 382})  # box gained 3 and lost 2 -> discarded
        self.assertEqual(fired, [196])
        self.assertEqual(t.distrusted_polls, 1)


class TestTheSaveMenuGlitch(unittest.TestCase):
    """Guard 2. The reported symptom: several species from an earlier save arriving together."""

    def _primed(self):
        t = rc.SpeciesCatchTracker()
        t.poll({25}, {6, 9})
        return t

    def test_a_box_snapshot_that_gains_and_loses_at_once_fires_nothing(self) -> None:
        t = self._primed()
        self.assertEqual(t.poll({25}, {143, 248}), [])  # lost 6 and 9, gained two others
        self.assertEqual(t.distrusted_polls, 1)

    def test_more_than_one_new_box_species_in_one_poll_fires_nothing(self) -> None:
        t = self._primed()
        self.assertEqual(t.poll({25}, {6, 9, 143, 248}), [])

    def test_a_glitch_that_holds_open_never_becomes_the_truth(self) -> None:
        """The decisive one. A streak alone would surrender after four polls; discarding the poll outright
        means the menu can stay open all day without a single wrong check going out."""
        t = self._primed()
        self.assertEqual(_hold(t, {25}, {143, 248, 380}, STREAK * 5), [])
        self.assertEqual(t.seen, {6, 9, 25})

    def test_closing_the_menu_resumes_normal_tracking_with_no_intervention(self) -> None:
        t = self._primed()
        _hold(t, {25}, {143, 248, 380}, 10)
        self.assertEqual(t.poll({25}, {6, 9}), [], "back to the trusted snapshot, nothing new")
        fired = _hold(t, {25}, {6, 9, 196}, STREAK)
        self.assertEqual(fired, [196], "a genuine box catch after the glitch still lands")


class TestBoxOnlyConfirmation(unittest.TestCase):
    """Guard 3. Covers the shape guard 2 cannot see: a glitch surfacing exactly one species."""

    def _primed(self):
        t = rc.SpeciesCatchTracker()
        t.poll({25}, {6})
        return t

    def test_a_single_new_box_species_is_not_trusted_immediately(self) -> None:
        t = self._primed()
        self.assertEqual(t.poll({25}, {6, 196}), [])

    def test_it_fires_once_it_has_held_for_the_full_streak(self) -> None:
        t = self._primed()
        fired = _hold(t, {25}, {6, 196}, STREAK)
        self.assertEqual(fired, [196])
        self.assertIn(196, t.seen)

    def test_it_fires_exactly_once_no_matter_how_long_it_stays(self) -> None:
        t = self._primed()
        fired = _hold(t, {25}, {6, 196}, STREAK * 4)
        self.assertEqual(fired, [196])

    def test_a_candidate_that_vanishes_before_confirming_never_fires(self) -> None:
        t = self._primed()
        _hold(t, {25}, {6, 196}, STREAK - 1)
        self.assertEqual(t.poll({25}, {6}), [])
        self.assertNotIn(196, t.seen)

    def test_a_vanished_candidate_restarts_rather_than_resuming(self) -> None:
        t = self._primed()
        _hold(t, {25}, {6, 196}, STREAK - 1)
        t.poll({25}, {6})
        self.assertEqual(_hold(t, {25}, {6, 196}, STREAK - 1), [], "the old progress must not carry over")
        self.assertEqual(t.poll({25}, {6, 196}), [196])


class TestOrdinaryPlayIsNotDisturbed(unittest.TestCase):
    def test_depositing_a_party_member_is_not_a_glitch(self) -> None:
        """Box gains exactly one, loses nothing -- and it was already reported via the party anyway."""
        t = rc.SpeciesCatchTracker()
        t.poll({25, 196}, set())
        self.assertEqual(_hold(t, {25}, {196}, STREAK), [])
        self.assertEqual(t.distrusted_polls, 0)

    def test_withdrawing_or_releasing_is_not_a_glitch(self) -> None:
        """A pure loss is real play (withdraw, release, trade) and carries no risk of a false check."""
        t = rc.SpeciesCatchTracker()
        t.poll({25}, {6, 9})
        self.assertEqual(t.poll({25}, {6}), [])
        self.assertEqual(t.distrusted_polls, 0)

    def test_a_species_can_be_reported_only_once_across_both_halves(self) -> None:
        t = rc.SpeciesCatchTracker()
        t.poll({25}, set())
        self.assertEqual(t.poll({25, 196}, set()), [196])
        self.assertEqual(_hold(t, {25}, {196}, STREAK * 2), [], "already sent via the party")

    def test_results_are_sorted_so_the_log_reads_predictably(self) -> None:
        t = rc.SpeciesCatchTracker()
        self.assertEqual(t.poll({133, 25, 196}, set()), [25, 133, 196])


class TestDescribe(unittest.TestCase):
    def test_before_priming(self) -> None:
        self.assertIn("not primed", rc.SpeciesCatchTracker().describe())

    def test_it_surfaces_the_discard_count_and_pending_candidates(self) -> None:
        t = rc.SpeciesCatchTracker()
        t.poll({25}, {6})
        t.poll({25}, {143, 248})       # discarded
        t.poll({25}, {6, 196})         # one pending
        text = t.describe()
        self.assertIn("discarded as implausible so far: 1", text)
        self.assertIn("#196", text)

    def test_it_never_raises_with_an_empty_tracker_after_priming(self) -> None:
        t = rc.SpeciesCatchTracker()
        t.poll(set(), set())
        self.assertIsInstance(t.describe(), str)


class TestConstantsMatchTheOtherTrackers(unittest.TestCase):
    def test_the_confirm_streak_is_the_one_addendum_99_settled_on(self) -> None:
        # ADDENDUM 174 deleted ChestCountTracker -- the chest signal is a single bit that only turns on, so
        # it needs no confirm streak at all. NamedPurificationTracker is still the live comparison.
        self.assertEqual(rc.SpeciesCatchTracker._CONFIRM_STREAK,
                         rc.NamedPurificationTracker._CONFIRM_STREAK)

    def test_one_new_box_species_per_poll_is_the_ceiling(self) -> None:
        """A catch, a deposit and a withdrawal each move exactly one Pokemon; nothing in normal play moves two
        between two polls a second apart."""
        self.assertEqual(rc.SpeciesCatchTracker._MAX_NEW_BOX_SPECIES_PER_POLL, 1)


if __name__ == "__main__":
    unittest.main()
