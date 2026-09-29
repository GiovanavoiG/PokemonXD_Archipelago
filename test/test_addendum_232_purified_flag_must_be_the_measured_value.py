"""ADDENDUM 232 (2026-09-15) -- only the measured purified value counts as a purification.

Second player report, relayed: "shadow purifications are still being sent out at weird times. Apparently it
happened upon opening the party/pc, when pokemon were close to purification."

"CLOSE TO PURIFICATION" IS THE WHOLE DIAGNOSIS. This is a FALSE POSITIVE, not the duplicate ADDENDUM 220
fixed -- and ADDENDUM 220 makes it worse rather than better, because its species ledger banks the false one
permanently, so the REAL purification for that species can never count afterwards.

The detector tested `flag != 0`. The field's own documentation has said since 2026-09-03 that the only value
ever measured on a real purification is 64, and has carried this caveat the whole time:

    "NOT yet confirmed: whether 64 specifically means 'purified' (vs. e.g. a small counter/enum where a later
     event might produce a different nonzero value)"

A Pokemon close to purification is exactly where a counter or gauge-derived field holds a nonzero value that
is not 64, and opening the party or PC is what refreshes the recap record and makes it visible. The caveat was
right; the code just never honoured it.
"""
import unittest

from .. import ram_client as rc


class _Record:
    def __init__(self, flag):
        self.purified_flag = flag
        self.name = "SHADOW"


class _Member:
    def __init__(self, species, index=0):
        self.reliable_species = species
        self.species = species
        self.party_index = index
        # ADDENDUM 236: the pairing check reads the member's own name, and a real
        # PartyMember always has one. Matches the record's name so this fake stays a self-consistent pairing,
        # which is what these tests have always meant it to be.
        self.name = "SHADOW"


class PurifiedFlagTestBase(unittest.TestCase):
    SPECIES = 158

    def setUp(self):
        self._members, self._correlate = rc.read_party_members, rc.correlate_party_with_recap
        rc.read_party_members = lambda party_base=None, max_slots=None: [_Member(self.SPECIES)]

    def tearDown(self):
        rc.read_party_members, rc.correlate_party_with_recap = self._members, self._correlate

    def run_flags(self, flags, tracker=None):
        tracker = tracker or rc.NamedPurificationTracker()
        fired = []
        for flag in flags:
            rc.correlate_party_with_recap = (
                lambda block_base, party_base, max_slots, f=flag: {0: (_Record(f), "ok")}
            )
            fired += tracker.poll(0)
        return tracker, fired


class TestOnlyTheMeasuredValueFires(PurifiedFlagTestBase):
    def test_the_constant_is_the_value_that_was_actually_observed(self):
        self.assertEqual(rc.PURIFIED_FLAG_VALUE, 64)

    def test_a_real_purification_still_fires(self):
        """The thing that must not break while fixing the false positives."""
        _tracker, fired = self.run_flags([0] + [64] * 8)
        self.assertEqual(fired, [(self.SPECIES, 0)])

    def test_a_close_to_purification_value_never_fires(self):
        """The reported bug. Any nonzero used to be enough."""
        for value in (1, 2, 16, 32, 63, 65, 128, 255):
            tracker, fired = self.run_flags([0] + [value] * 8)
            self.assertEqual(fired, [], f"flag {value} fired a purification")
            self.assertEqual(tracker.unrecognised_flag_values.get(value), 8, f"flag {value} was not recorded")

    def test_an_intermediate_value_does_not_block_the_real_one(self):
        """The failure this fix must not introduce: a Pokemon that passes through an intermediate value on
        its way to being purified still has to count when it gets there."""
        _tracker, fired = self.run_flags([0] + [32] * 4 + [64] * 8)
        self.assertEqual(fired, [(self.SPECIES, 0)])

    def test_an_intermediate_value_does_not_advance_the_baseline(self):
        """The mechanism behind the test above: `last_seen_flags` must stay 0 through the intermediate
        readings, or the 0 -> 64 transition is never seen."""
        tracker, _fired = self.run_flags([0] + [32] * 4)
        self.assertEqual(tracker.last_seen_flags[self.SPECIES], 0)

    def test_zero_is_still_not_a_purification(self):
        tracker, fired = self.run_flags([0] * 6)
        self.assertEqual(fired, [])
        self.assertEqual(tracker.unrecognised_flag_values, {})

    def test_the_first_sighting_is_still_only_a_baseline(self):
        """A recap record stale at 64 from an earlier occupant must not fire on the poll it is first seen."""
        _tracker, fired = self.run_flags([64] * 8)
        self.assertEqual(fired, [], "a species first seen already at 64 has not been observed purifying")

    def test_the_confirm_streak_still_applies(self):
        _tracker, fired = self.run_flags([0, 64])
        self.assertEqual(fired, [], "one reading of 64 is not enough on its own")


class TestTheUnrecognisedValuesAreReported(PurifiedFlagTestBase):
    """The open question in PARTY_RECAP_PURIFIED_FLAG_OFFSET's comment is what these values mean. Recording
    them turns a live report into evidence instead of leaving the next person to guess again."""

    def test_they_are_counted_per_value(self):
        tracker, _fired = self.run_flags([0] + [32] * 3 + [16] * 2)
        self.assertEqual(tracker.unrecognised_flag_values, {32: 3, 16: 2})

    def test_the_count_tracker_prints_them(self):
        tracker, _fired = self.run_flags([0] + [32] * 3)
        counter = rc.PurificationCountTracker()
        counter.tracker = tracker
        text = "\n".join(counter.describe())
        self.assertIn("NOT 64", text)
        self.assertIn("32", text)
        self.assertIn("worth reporting", text)

    def test_nothing_is_printed_when_there_is_nothing_to_report(self):
        counter = rc.PurificationCountTracker()
        self.assertNotIn("NOT 64", "\n".join(counter.describe()))


class TestTheFalsePositiveWouldHavePoisonedTheLedger(PurifiedFlagTestBase):
    """Why this mattered more than an extra check: ADDENDUM 220 records every counted species permanently, so
    a false positive does not merely add a wrong check -- it also consumes that species, and the real
    purification later is then rejected as a duplicate."""

    def test_a_false_positive_would_have_consumed_the_species(self):
        counter = rc.PurificationCountTracker()
        counter.purified_species.add(self.SPECIES)          # as a false positive would have left it
        tracker, _fired = self.run_flags([0] + [64] * 8)
        counter.tracker = tracker
        self.assertEqual(counter.poll(0), [],
                         "this is what the real purification would have hit afterwards")

    def test_with_the_fix_the_species_is_still_available(self):
        tracker, _fired = self.run_flags([0] + [32] * 8)
        counter = rc.PurificationCountTracker()
        counter.tracker = tracker
        self.assertEqual(counter.poll(0), [])
        self.assertNotIn(self.SPECIES, counter.purified_species,
                         "an unrecognised flag value must not consume the species")


if __name__ == "__main__":
    unittest.main()
