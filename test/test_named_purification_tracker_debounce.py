"""Regression coverage for NamedPurificationTracker's ADDENDUM 98/99 debounce.

ADDENDUM 98 (2026-09-07, player report: "still sending purify checks upon opening save menu") shipped a
2-consecutive-poll confirmation window (`_pending_flags`) for a species' purified_flag 0->nonzero transition.
ADDENDUM 99 (2026-09-09, player report AFTER 98 shipped: "The save menu is still sending duplicate/extra checks
for both purifications AND chests") widened that window from 2 polls to `NamedPurificationTracker._CONFIRM_
STREAK` (4) consecutive matching polls, tracked per-species via `_pending_streak` -- see that class's own
docstring for the full reasoning. No test previously existed for this tracker's debounce at all (only
ChestCountTracker's sibling debounce, added the same day as ADDENDUM 98, had one) -- this file adds that
coverage now, already written against the ADDENDUM 99 widened window.

WHY THIS TEST STUBS `dolphin_memory_engine`: same reason as test_chest_count_tracker_debounce.py -- `ram_client.
py` does `import dolphin_memory_engine as dme` at module level, and that real package isn't installable in
every environment this project's tests run in. This test never calls into `dme` at all: it monkeypatches
`ram_client.correlate_party_with_recap` and `ram_client.read_party_members` directly (the two functions
`NamedPurificationTracker.poll()` calls to get live party/recap data) so each test can script an exact
poll-by-poll sequence of purified_flag reads -- including the "jump then revert" and "jump then hold" shapes
this addendum's debounce exists to tell apart -- without needing any real party/recap memory at all."""
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

from .. import ram_client

SWABLU_DEX = 333  # ram_client.SPECIES_NAME_TO_DEX["SWABLU"]
PARTY_INDEX = 0


def _member() -> "ram_client.PartyMember":
    return ram_client.PartyMember(
        party_index=PARTY_INDEX, name="SWABLU", species=333, level=10, max_hp=30, current_hp=30
    )


def _recap(flag: int) -> "ram_client.PartyRecapRecord":
    return ram_client.PartyRecapRecord(
        party_index=PARTY_INDEX, address=0, name="SWABLU", species=333, purified_flag=flag,
        max_hp=30, attack=10, defense=10, sp_attack=10, sp_defense=10, speed=10,
    )


def _poll_sequence(
    tracker: "ram_client.NamedPurificationTracker", flags: list[int]
) -> list[list[tuple[int, int]]]:
    """Runs tracker.poll() once per purified_flag value in `flags`, in order, with read_party_members()/
    correlate_party_with_recap() patched so each poll sees a single occupied slot (party_index 0, species
    SWABLU) whose recap record's purified_flag is that poll's scripted value. Returns the list of
    newly_purified results, one per poll, in the same order."""
    results = []
    members_side_effect = [[_member()] for _ in flags]
    correlate_side_effect = [{PARTY_INDEX: (_recap(flag), "name_match")} for flag in flags]
    with mock.patch.object(ram_client, "read_party_members", side_effect=members_side_effect), \
         mock.patch.object(ram_client, "correlate_party_with_recap", side_effect=correlate_side_effect):
        for _ in flags:
            results.append(tracker.poll(block_base=0))
    return results


class TestNamedPurificationTrackerDebounce(unittest.TestCase):
    def test_first_poll_only_baselines_never_fires(self) -> None:
        tracker = ram_client.NamedPurificationTracker()
        results = _poll_sequence(tracker, [0])
        self.assertEqual(results, [[]])
        self.assertEqual(tracker.last_seen_flags[SWABLU_DEX], 0)

    def test_genuine_purification_confirmed_after_confirm_streak(self) -> None:
        """A real purification: purified_flag flips from 0 to 64 and HOLDS -- must fire exactly once, on the
        poll that completes the ADDENDUM 99 confirm streak (4 consecutive matching polls), not any poll
        before it."""
        tracker = ram_client.NamedPurificationTracker()
        results = _poll_sequence(tracker, [0, 64, 64, 64, 64])
        self.assertEqual(results[0], [])  # baseline
        self.assertEqual(results[1], [])  # candidate seen, streak 1 -- must NOT fire here
        self.assertEqual(results[2], [])  # streak 2
        self.assertEqual(results[3], [])  # streak 3
        self.assertEqual(results[4], [(SWABLU_DEX, PARTY_INDEX)])  # streak 4 -- confirmed
        self.assertEqual(tracker.last_seen_flags[SWABLU_DEX], 64)

    def test_spike_then_revert_glitch_fires_nothing(self) -> None:
        """The exact bug ADDENDUM 98/99 fix: a save-menu-open (or similar) produces a stale/high read that
        then reverts back to the true, unchanged value before the confirm streak completes. Must fire NOTHING."""
        tracker = ram_client.NamedPurificationTracker()
        results = _poll_sequence(tracker, [0, 64, 0])
        self.assertEqual(results, [[], [], []])
        self.assertEqual(tracker.last_seen_flags[SWABLU_DEX], 0)

    def test_spike_held_for_three_polls_then_reverting_still_fires_nothing(self) -> None:
        """ADDENDUM 99's actual motivating case: a glitch that holds steady for MORE than the old 2-poll
        window (but still less than the new 4-poll `_CONFIRM_STREAK`) before reverting. The old debounce would
        have confirmed this at poll 3; the widened one must not."""
        tracker = ram_client.NamedPurificationTracker()
        results = _poll_sequence(tracker, [0, 64, 64, 64, 0])
        self.assertEqual(results, [[], [], [], [], []])
        self.assertEqual(tracker.last_seen_flags[SWABLU_DEX], 0)

    def test_pending_candidate_cleared_once_baseline_reconfirmed(self) -> None:
        """After a spike-then-revert, a LATER genuine purification from the (unchanged) baseline must still
        debounce normally -- confirms the revert path actually clears `_pending_flags`/`_pending_streak` rather
        than leaving stale state that could corrupt a later, real confirmation."""
        tracker = ram_client.NamedPurificationTracker()
        results = _poll_sequence(tracker, [0, 64, 0, 64, 64, 64, 64])
        self.assertEqual(results[:3], [[], [], []])  # baseline, glitch, revert -- nothing fired
        self.assertEqual(results[3], [])  # new genuine candidate 64, streak 1
        self.assertEqual(results[4], [])  # streak 2
        self.assertEqual(results[5], [])  # streak 3
        self.assertEqual(results[6], [(SWABLU_DEX, PARTY_INDEX)])  # streak 4 -- confirmed


if __name__ == "__main__":
    unittest.main()
