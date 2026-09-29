"""ADDENDUM 333 (2026-09-24): two Shadows snagged in one battle locked the catch tracker forever.

Player, relaying a report:

> my pokemon apparently stopped registering at one point and then fixed itself ... They stopped sending, and
> then started sending after i got some pokemon out of the pc. And they just stopped sending again, but that
> may be bc of long cutscenes.

And, on the follow-up: "moving the pokemon into his party sends the check even in the pc screen ... any small
changes we can do to notice the pokemon without needing to move it?"

THE TRIGGER NEEDS NO CUTSCENE. `SpeciesCatchTracker` guard 2 discarded any box poll that gained more than one
species at once, justified in its own comment as "a catch, a deposit and a withdrawal each move exactly one
Pokemon". True per EVENT, false per BATTLE: seventeen trainers carry two or more Shadows (Eldes four, Greevil
six), and with a full party both auto-deposit, so the next box scan gains two new species in one poll. A
discarded poll deliberately does not update `_last_box`, so every later poll made the identical comparison and
failed identically, forever.

ADDENDUM 290 fixed the same loop and cannot reach this case: its repair is `gained & self.seen`, species
ALREADY credited, and here the gained species are new.

THE PLAYER'S REPORT CONTAINS THE PROOF. Withdrawing from the PC fired the checks because the PARTY path
bypasses the boxes entirely -- the box baseline was never unstuck, which is why it stopped again on the very
next straight-to-PC catch.
"""
import unittest

from .. import ram_client as rc

# A full party, so a snag auto-deposits.
FULL_PARTY = frozenset({25, 6, 9, 143, 248, 380})
PARAS, GROWLITHE, EXTRA = 46, 58, 196


def _primed() -> "rc.SpeciesCatchTracker":
    tracker = rc.SpeciesCatchTracker()
    tracker.poll(set(FULL_PARTY), set())
    return tracker


class TestTheReportedStall(unittest.TestCase):
    def test_a_double_snag_no_longer_locks_the_box_path(self) -> None:
        """The whole report, as one sequence. Before this addendum every assertion below failed."""
        tracker = _primed()
        fired = []
        for _ in range(tracker._MULTI_GAIN_CONFIRM_STREAK + 2):
            fired += tracker.poll(set(FULL_PARTY), {PARAS, GROWLITHE})
        self.assertEqual([PARAS, GROWLITHE], sorted(fired),
                         "both Shadows must arrive with the Pokemon still sitting in the PC")

    def test_and_ordinary_catches_keep_working_afterwards(self) -> None:
        """The part that made it "stopped registering" rather than "two checks are late": one double snag
        killed every later box catch for the rest of the session."""
        tracker = _primed()
        for _ in range(tracker._MULTI_GAIN_CONFIRM_STREAK + 2):
            tracker.poll(set(FULL_PARTY), {PARAS, GROWLITHE})
        fired = []
        for _ in range(tracker._CONFIRM_STREAK + 1):
            fired += tracker.poll(set(FULL_PARTY), {PARAS, GROWLITHE, EXTRA})
        self.assertEqual([EXTRA], fired, "a single later catch is an ORDINARY gain, on the ordinary window")

    def test_the_baseline_advances_so_nothing_can_absorb(self) -> None:
        tracker = _primed()
        tracker.poll(set(FULL_PARTY), {PARAS, GROWLITHE})
        self.assertEqual({PARAS, GROWLITHE}, tracker._last_box)
        self.assertEqual(0, tracker.distrusted_polls)
        self.assertEqual(1, tracker.multi_gain_polls)

    def test_no_withdrawal_is_needed(self) -> None:
        """The player's follow-up, stated as the assertion: the party is never touched in this test."""
        tracker = _primed()
        fired = []
        for _ in range(tracker._MULTI_GAIN_CONFIRM_STREAK + 2):
            fired += tracker.poll(set(FULL_PARTY), {PARAS, GROWLITHE})
        self.assertTrue(fired)
        self.assertNotIn(PARAS, FULL_PARTY)
        self.assertNotIn(GROWLITHE, FULL_PARTY)


class TestTheLongWindowIsTheSafetyPrice(unittest.TestCase):
    def test_the_ordinary_window_is_not_enough_for_a_multi_gain_species(self) -> None:
        tracker = _primed()
        fired = []
        for _ in range(tracker._CONFIRM_STREAK + 1):
            fired += tracker.poll(set(FULL_PARTY), {PARAS, GROWLITHE})
        self.assertEqual([], fired, "four polls must not be enough -- a pure-gain glitch would clear that")

    def test_the_long_window_is_three_times_the_ordinary_one(self) -> None:
        self.assertEqual(rc.CONFIRM_WINDOW_SECONDS["species_catch_multi"],
                         rc.CONFIRM_WINDOW_SECONDS["species_catch"] * 3)

    def test_both_windows_are_derived_from_a_duration(self) -> None:
        """ADDENDUM 228's rule: a debounce follows the real poll interval, it is never a typed poll count."""
        original = rc.POLL_INTERVAL_SECONDS
        try:
            resolved = rc.set_poll_interval(0.5)
            self.assertEqual(resolved["species_catch_multi"],
                             rc.SpeciesCatchTracker._MULTI_GAIN_CONFIRM_STREAK)
            self.assertGreater(rc.SpeciesCatchTracker._MULTI_GAIN_CONFIRM_STREAK,
                               rc.SpeciesCatchTracker._CONFIRM_STREAK)
        finally:
            rc.set_poll_interval(original)

    def test_a_species_that_vanishes_before_confirming_forgets_it_was_slow(self) -> None:
        """Same rule the ordinary streak has had since ADDENDUM 146 -- a re-appearance restarts."""
        tracker = _primed()
        tracker.poll(set(FULL_PARTY), {PARAS, GROWLITHE})
        self.assertIn(PARAS, tracker._slow_candidates)
        tracker.poll(set(FULL_PARTY), set())
        self.assertNotIn(PARAS, tracker._slow_candidates)


class TestCorroborationOutranksTheSlowWindow(unittest.TestCase):
    """The long window is a BOX suspicion. Another source saying the same thing settles it."""

    def test_the_recap_clears_the_slow_flag(self) -> None:
        tracker = _primed()
        tracker.poll(set(FULL_PARTY), {PARAS, GROWLITHE})
        self.assertIn(PARAS, tracker._slow_candidates)
        fired = []
        for _ in range(tracker._CONFIRM_STREAK):
            fired += tracker.poll(set(FULL_PARTY), {PARAS, GROWLITHE}, recap_species={PARAS})
        self.assertEqual([PARAS], fired, "the save-block party corroborated it -- ordinary window")

    def test_the_party_still_fires_on_the_very_same_poll(self) -> None:
        """Guard 1 is untouched, which is why the player's withdrawal worked even while the box was stuck."""
        tracker = _primed()
        tracker.poll(set(FULL_PARTY), {PARAS, GROWLITHE})
        self.assertEqual([PARAS], tracker.poll(set(FULL_PARTY) | {PARAS}, {GROWLITHE}))


class TestTheGlitchGuardStillGuards(unittest.TestCase):
    def test_a_snapshot_that_gains_and_loses_is_still_distrusted(self) -> None:
        """ADDENDUM 146's actual reported symptom -- the box reading as a DIFFERENT snapshot of itself."""
        tracker = _primed()
        tracker.poll(set(FULL_PARTY), {PARAS})
        for _ in range(tracker._MULTI_GAIN_CONFIRM_STREAK * 2):
            self.assertEqual([], tracker.poll(set(FULL_PARTY), {GROWLITHE, EXTRA, 200}))
        self.assertNotIn(EXTRA, tracker.seen)
        self.assertGreater(tracker.distrusted_polls, 0)

    def test_the_ceiling_constant_still_means_one(self) -> None:
        """It stopped being a distrust test and became a slow-down test; the number itself is unchanged."""
        self.assertEqual(1, rc.SpeciesCatchTracker._MAX_NEW_BOX_SPECIES_PER_POLL)


class TestItIsVisible(unittest.TestCase):
    def test_catches_reports_the_multi_gain_count(self) -> None:
        """`!catches` is how a stuck player found this. It must now say what it did instead."""
        tracker = _primed()
        tracker.poll(set(FULL_PARTY), {PARAS, GROWLITHE})
        text = tracker.describe()
        self.assertIn("gained more than one species at once", text)
        self.assertIn("slow", tracker.describe())
