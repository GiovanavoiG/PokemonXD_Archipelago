"""ADDENDUM 290 (2026-09-19) -- a flaky read locked the catch tracker, permanently.

Player: "After two or three catches in the PC, the checks stop sending automatically. Can we double check our
block structure and that we're actually polling consistently? Is it breaking?"

It was breaking, and it was reproducible in nine lines against `SpeciesCatchTracker` alone -- no emulator, no
block structure, no poll-rate question. Three catches, ONE poll where a couple of slot reads fail, and no
box-only catch ever fires again for the rest of the session.

## Two defects, and it takes both

**1. A partial read was evidence of absence.** `get_box_species_snapshot` returns a SET and silently drops any
slot it could not read, so a transient failure looks exactly like "those Pokemon are gone". A pure SHRINK
sails through guard 2 -- `gained` is empty, so `gained and lost` is False -- and is adopted as the new
baseline. The trap is now armed: the baseline is missing species that are really there.

**2. Distrust never recovered.** The next poll reads correctly and GAINS those species back. More than one of
them trips `len(gained) > _MAX_NEW_BOX_SPECIES_PER_POLL`, so the poll is distrusted -- and a distrusted poll
deliberately does not update `_last_box`, so the next poll makes the identical comparison and fails
identically. Forever.

ADDENDUM 221 described this exact loop and closed the one entrance it had found (party movement). It did not
make the loop non-absorbing, and there was another entrance.

**Why the symptom is "checks stop sending" and not "box catches are late":** `_pending_streak.clear()` ran on
every distrusted poll, so while stuck NOTHING that needs a streak could fire -- including recap candidates,
which guard 2 does not even apply to. Only guard 1's party path still worked, which is the "go open the party
screen" behaviour this tracker exists to remove.

## The two rules this project had already written down

* An unreadable slot is "ask again next poll", never "the answer is no" -- ADDENDA 256, 257, 267. This is the
  fourth time, and the first where it cost a player their checks.
* A glitch is transient by definition, so a reading that holds steady is the truth -- ADDENDUM 154's
  `BlockStabilityGate`, which "is detecting 'the block is currently telling the truth'".
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

import pathlib

from .. import ram_client as rc

PIKACHU, DITTO, SNORLAX, GENGAR = 25, 132, 143, 94


def _primed(*caught: int) -> rc.SpeciesCatchTracker:
    """A tracker that has already credited `caught`, the slow way, through the box."""
    tracker = rc.SpeciesCatchTracker()
    tracker.poll(set(), set(), set())
    box: "set[int]" = set()
    for dex in caught:
        box.add(dex)
        for _ in range(tracker._CONFIRM_STREAK + 1):
            tracker.poll(set(), set(box), set())
    return tracker


class TestTheReportedStall(unittest.TestCase):
    """The player's sequence, start to finish."""

    def test_three_catches_then_a_flaky_poll_then_a_fourth_catch(self) -> None:
        tracker = _primed(PIKACHU, DITTO, SNORLAX)
        self.assertEqual({PIKACHU, DITTO, SNORLAX}, tracker.seen)

        # The flaky poll: two slots did not read. Flagged, so it may not shrink the baseline.
        tracker.poll(set(), {PIKACHU}, set(), box_complete=False)
        self.assertEqual({PIKACHU, DITTO, SNORLAX}, tracker._last_box,
                         "an incomplete scan must never conclude a species has left")
        self.assertEqual(1, tracker.incomplete_polls)

        for _ in range(6):
            self.assertEqual([], tracker.poll(set(), {PIKACHU, DITTO, SNORLAX}, set()))
        self.assertEqual(0, tracker.distrusted_polls, "nothing to distrust -- the baseline never lied")

        fired = None
        for poll in range(1, 12):
            out = tracker.poll(set(), {PIKACHU, DITTO, SNORLAX, GENGAR}, set())
            if out:
                fired = (poll, out)
                break
        self.assertEqual((tracker._CONFIRM_STREAK, [GENGAR]), fired,
                         "the fourth catch must fire on its ordinary streak, not never")

    def test_the_loop_self_heals_even_when_the_read_failure_is_invisible(self) -> None:
        """DEFENCE IN DEPTH. Fix 1 needs the caller to report completeness. If a slot ever decodes to a
        wrong-but-valid name, or a future caller forgets the flag, fix 2 still has to get the player out."""
        tracker = _primed(PIKACHU, DITTO, SNORLAX)
        tracker.poll(set(), {PIKACHU}, set())           # NOT flagged -- the baseline really does shrink
        self.assertEqual({PIKACHU}, tracker._last_box, "this is the trap being armed")

        # And the player keeps playing: a genuinely new catch turns up while the trap is armed, so the
        # distrusted snapshot mixes already-credited species with an unseen one. The repair has to cope.
        fired = None
        for poll in range(1, 20):
            out = tracker.poll(set(), {PIKACHU, DITTO, SNORLAX, GENGAR}, set())
            if out:
                fired = (poll, out)
                break
        self.assertIsNotNone(fired, "before ADDENDUM 290 this never fired again, ever")
        self.assertEqual([GENGAR], fired[1])
        # ADDENDUM 333: no resync is needed for this shape any more. The recovering poll is a PURE GAIN, so
        # it is simply trusted -- the baseline repairs itself on the spot rather than waiting out a distrust
        # run. Gengar still has to serve the long window, because a multi-gain poll is what introduced it.
        self.assertEqual(0, tracker.resyncs)
        self.assertEqual(1, tracker.multi_gain_polls)
        self.assertLessEqual(fired[0], tracker._MULTI_GAIN_CONFIRM_STREAK + 1,
                             "a bounded delay, not a stall")

    def test_the_repair_restores_only_species_already_credited(self) -> None:
        """THE SAFETY PROPERTY, and the one ADDENDUM 146's test forced. The repair does not adopt the
        snapshot -- it puts back the already-sent species the baseline lost, and nothing else. An unseen
        species in the same snapshot is still judged exactly as before."""
        tracker = _primed(PIKACHU, DITTO)
        tracker.poll(set(), {PIKACHU}, set())                  # the trap: baseline loses DITTO
        self.assertEqual({PIKACHU}, tracker._last_box)

        for poll in range(tracker._CONFIRM_STREAK + 1):
            out = tracker.poll(set(), {PIKACHU, DITTO, SNORLAX}, set())
            self.assertEqual([], out, f"poll {poll} must fire nothing")
        # ADDENDUM 333: the recovering poll is a pure gain, so it is trusted and the baseline comes back on
        # its own -- no resync needed. The SAFETY property this test exists for is unchanged and is the
        # assertion below: an unseen species in that snapshot is not credited on the ordinary window.
        self.assertEqual(0, tracker.resyncs)
        self.assertEqual({PIKACHU, DITTO, SNORLAX}, tracker._last_box)
        self.assertNotIn(SNORLAX, tracker.seen,
                         "SNORLAX arrived on a multi-gain poll, so it owes the LONG window")
        self.assertIn(SNORLAX, tracker._slow_candidates)


class TestTheIncompleteSnapshotRule(unittest.TestCase):
    def test_an_incomplete_scan_may_still_add(self) -> None:
        """A name that decoded really is in the box. Incompleteness forbids concluding an ABSENCE, nothing
        more -- holding back a real catch would be the opposite mistake."""
        tracker = _primed(PIKACHU)
        for _ in range(tracker._CONFIRM_STREAK):
            out = tracker.poll(set(), {PIKACHU, DITTO}, set(), box_complete=False)
        self.assertEqual([DITTO], out)

    def test_an_incomplete_scan_never_becomes_the_baseline_on_a_resync(self) -> None:
        tracker = _primed(PIKACHU, DITTO)
        for _ in range(tracker._DISTRUST_RESYNC_POLLS * 2):
            tracker.poll(set(), {SNORLAX, GENGAR}, set(), box_complete=False)
        self.assertEqual(0, tracker.resyncs, "a scan that could not read every slot cannot define the truth")

    def test_the_detailed_snapshot_counts_failures(self) -> None:
        calls = {"n": 0}

        def _read(address, length):
            calls["n"] += 1
            if calls["n"] % 3 == 0:
                raise RuntimeError("bad address")
            return b"\x00" * length

        with mock.patch.object(rc, "read_bytes", _read):
            species, failures = rc.get_box_species_snapshot_detailed(0x80479000, num_boxes=1, slots_per_box=9)
        self.assertEqual(set(), species)
        self.assertEqual(3, failures)

    def test_the_plain_snapshot_still_works_for_every_other_caller(self) -> None:
        with mock.patch.object(rc, "read_bytes", lambda a, n: b"\x00" * n):
            self.assertEqual(set(), rc.get_box_species_snapshot(0x80479000, num_boxes=1, slots_per_box=4))


class TestTheGuardsStillGuard(unittest.TestCase):
    """ADDENDUM 146's whole point was that a false catch is unrecoverable within a seed. None of that moves."""

    def test_a_glitch_burst_still_fires_nothing(self) -> None:
        """RETARGETED BY ADDENDUM 333 to the shape that is still a glitch.

        The fixture used to be a PURE GAIN of three, which that addendum reclassifies as play -- seventeen
        trainers carry two or more Shadows, so a box that gains several species and loses none is a double
        snag with a full party, not the save menu. The save-menu signature is the box reading as a DIFFERENT
        snapshot of itself: it gains AND loses."""
        tracker = _primed(PIKACHU)
        self.assertEqual([], tracker.poll(set(), {DITTO, SNORLAX, GENGAR}, set()))
        self.assertEqual(1, tracker.distrusted_polls)

    def test_a_pure_gain_burst_is_trusted_but_still_fires_nothing_that_poll(self) -> None:
        """ADDENDUM 333's other half. The poll is trusted -- the baseline advances, so the tracker cannot
        lock -- but nothing goes out until the long window has been served."""
        tracker = _primed(PIKACHU)
        self.assertEqual([], tracker.poll(set(), {PIKACHU, DITTO, SNORLAX, GENGAR}, set()))
        self.assertEqual(0, tracker.distrusted_polls)
        self.assertEqual(1, tracker.multi_gain_polls)
        self.assertEqual({PIKACHU, DITTO, SNORLAX, GENGAR}, tracker._last_box, "the baseline advanced")
        for _ in range(tracker._CONFIRM_STREAK):
            self.assertEqual([], tracker.poll(set(), {PIKACHU, DITTO, SNORLAX, GENGAR}, set()),
                             "the ORDINARY window must not be enough for these")

    def test_a_simultaneous_gain_and_loss_is_still_distrusted(self) -> None:
        tracker = _primed(PIKACHU)
        self.assertEqual([], tracker.poll(set(), {DITTO}, set()))
        self.assertEqual(1, tracker.distrusted_polls)

    def test_a_transient_glitch_that_goes_away_never_resyncs(self) -> None:
        """The run counter resets whenever the distrusted snapshot CHANGES, so a flickering glitch -- which is
        what a save-menu open actually looks like -- can never accumulate its way to being adopted.

        UPDATED BY ADDENDUM 333. A flicker gains AND loses on every poll after the first, so it is still
        distrusted throughout and still credits nothing -- which is the property this test is for. What no
        longer holds is the baseline claim: the FIRST poll of the flicker is a pure gain, so it is trusted
        and the baseline moves once. Harmless, and asserted rather than dropped: the flicker's species never
        reach `seen`, because none of them survives two consecutive polls, let alone the long window."""
        tracker = _primed(PIKACHU)
        for i in range(30):
            # Always TWO new species, and different ones every poll -- a flicker, never a steady reading.
            tracker.poll(set(), {PIKACHU, 200 + i, 300 + i}, set())
        self.assertEqual(0, tracker.resyncs)
        self.assertEqual({PIKACHU}, tracker.seen, "and nothing was credited off any of it")
        self.assertGreater(tracker.distrusted_polls, 25, "the flicker is still distrusted, poll after poll")

    def test_the_party_path_is_still_immediate(self) -> None:
        tracker = _primed()
        self.assertEqual([PIKACHU], tracker.poll({PIKACHU}, set(), set()))

    def test_a_distrusted_box_poll_no_longer_resets_a_recap_streak(self) -> None:
        """The reason the symptom was "checks stop sending" rather than "box catches are late". Guard 2 does
        not apply to the recap source, so a box glitch must not touch its progress."""
        tracker = _primed(PIKACHU)
        fired = None
        for poll in range(1, 10):
            # A distrusted box snapshot every single poll, while a real party catch waits on its streak.
            out = tracker.poll(set(), {PIKACHU, DITTO, SNORLAX, GENGAR}, {132})
            if out:
                fired = poll
                break
        self.assertIsNotNone(fired, "the recap catch must still get through a box glitch")


class TestTheClientPassesCompleteness(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = pathlib.Path(__file__).resolve().parent.parent
        source = (root / "Client.py").read_text(encoding="utf-8")
        start = source.index("async def check_species_catches")
        cls.body = source[start:source.index("\nasync def ", start + 1)]
        cls.source = source

    def test_it_uses_the_detailed_scan(self) -> None:
        self.assertIn("get_box_species_snapshot_detailed", self.body)

    def test_it_passes_box_complete(self) -> None:
        self.assertIn("box_complete=", self.body)

    def test_completeness_is_cached_with_the_snapshot(self) -> None:
        """The scan runs on its own ~1s cadence and the snapshot is reused between scans, so its completeness
        has to be reused with it rather than inheriting whatever this poll happened to do."""
        self.assertIn("_last_box_complete", self.body)
        self.assertIn("self._last_box_complete: bool = True", self.source)


if __name__ == "__main__":
    unittest.main()
