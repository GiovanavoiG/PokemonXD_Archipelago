"""ADDENDUM 148 (2026-09-11): not polling the save block while the save block is being rewritten.

Player report: "Chests and purifications are still sending upon opening the save menu. I think it temporarily
writes to the block and then rewrites it -- ways to avoid this?"

ADDENDUM 98 debounced for 2 polls. ADDENDUM 99 widened that to 4. Both asked "has this value settled?", and a
write-then-rewrite answers yes for as long as the menu is open, so both lost. This asks a different question --
"is the block being rewritten right now?" -- and skips the block-derived trackers entirely for those polls, so
they never see the glitch value at all and have nothing to disbelieve.

The tests below are therefore mostly about the property the previous two fixes lacked: holding out for an
arbitrarily long churn.
"""
from __future__ import annotations

import unittest

from .. import ram_client as rc

BLOCK_BASE = 0x80479380
SIZE = rc.BLOCK_STABILITY_WINDOW_SIZE


class _Window:
    def __init__(self, initial: bytes | None = None) -> None:
        self.content = bytearray(initial if initial is not None else bytes(SIZE))
        self.explode = False

    def read(self, address: int, length: int) -> bytes:
        if self.explode:
            raise RuntimeError("Dolphin went away")
        if address == BLOCK_BASE + rc.BLOCK_STABILITY_WINDOW_OFFSET:
            return bytes(self.content[:length])
        return bytes(length)

    _nonce = 0

    def rewrite(self) -> None:
        """A write burst covering half the window -- what a save does. Alias kept so the ADDENDUM 154 tests
        moved here from their own file read the way they were written."""
        self.change(SIZE // 2)

    def change(self, byte_count: int) -> None:
        """Write `byte_count` bytes of NEW content, the way a rewrite or an item pickup would. Each call uses
        a fresh value so two changes never accidentally cancel out and restore the original -- which they did
        when this flipped bits, quietly turning "three write bursts" into "back where we started"."""
        type(self)._nonce = (type(self)._nonce + 1) % 251 + 1
        for i in range(byte_count):
            self.content[i] = (self.content[i] + type(self)._nonce) % 256


class _Patched:
    def __init__(self, window: _Window) -> None:
        self.window = window

    def __enter__(self):
        self._orig = rc.read_bytes
        rc.read_bytes = self.window.read
        return self.window

    def __exit__(self, *exc):
        rc.read_bytes = self._orig


def _poll(gate, window, times=1):
    results = []
    with _Patched(window):
        for _ in range(times):
            results.append(gate.poll(BLOCK_BASE))
    return results


class TestQuietPlay(unittest.TestCase):
    def test_the_first_poll_is_trusted(self) -> None:
        """There is nothing to compare against, and every tracker baselines on its own first poll anyway."""
        self.assertEqual(_poll(rc.BlockStabilityGate(), _Window()), [True])

    def test_an_unchanging_block_stays_trusted(self) -> None:
        gate, window = rc.BlockStabilityGate(), _Window()
        self.assertTrue(all(_poll(gate, window, 20)))
        self.assertEqual(gate.churn_events, 0)

    def test_opening_a_chest_is_not_a_rewrite(self) -> None:
        """A chest is one u16 quantity: two bytes."""
        gate, window = rc.BlockStabilityGate(), _Window()
        _poll(gate, window)
        window.change(2)
        self.assertEqual(_poll(gate, window), [True])
        self.assertEqual(gate.churn_events, 0)

    def test_several_slot_writes_at_once_are_still_not_a_rewrite(self) -> None:
        """Headroom for the player using items while an AP delivery lands -- four slots, four bytes each."""
        gate, window = rc.BlockStabilityGate(), _Window()
        _poll(gate, window)
        window.change(rc.BLOCK_CHURN_BYTE_THRESHOLD)
        self.assertEqual(_poll(gate, window), [True])
        self.assertEqual(gate.churn_events, 0)


class TestTheSaveMenuRewrite(unittest.TestCase):
    def _primed(self):
        gate, window = rc.BlockStabilityGate(), _Window()
        _poll(gate, window)
        return gate, window

    def test_a_wholesale_rewrite_is_caught(self) -> None:
        gate, window = self._primed()
        window.change(SIZE // 2)
        self.assertEqual(_poll(gate, window), [False])
        self.assertFalse(gate.stable)
        self.assertEqual(gate.churn_events, 1)

    def test_a_churn_that_holds_open_never_gives_in(self) -> None:
        """The property ADDENDUM 98 and 99 both lacked. A debounce surrenders once its window elapses; this
        must still be withholding after the menu has been open for a minute."""
        gate, window = self._primed()
        window.change(SIZE // 2)
        _poll(gate, window)
        for _ in range(60):
            window.change(SIZE // 2)  # keeps flipping -- the block never settles
            self.assertEqual(_poll(gate, window), [False])
        self.assertFalse(gate.stable)

    def test_a_block_rewritten_and_left_there_stays_shut(self) -> None:
        """CHANGED 2026-09-12 (ADDENDUM 154). This used to assert the gate reopened after a couple of quiet
        polls, because ADDENDUM 148 only asked "has it stopped moving?". A three-write save is quiet in the
        gaps between its writes, which is how the player was still getting duplicate checks. The gate now
        reopens only once the window reads like the last TRUSTED content again -- so a block sitting at
        rewritten content stays shut no matter how still it is."""
        gate, window = self._primed()
        window.change(SIZE // 2)
        self.assertEqual(_poll(gate, window), [False])
        self.assertTrue(all(not r for r in _poll(gate, window, 10)))
        self.assertFalse(gate.stable)

    def test_the_escape_valve_eventually_adopts_content_that_never_comes_back(self) -> None:
        """The other side of that coin: content CAN legitimately change during a disturbance (a chest opened
        moments before saving), and then it will never match the old reference. Withholding forever would be
        worse than the bug. After BLOCK_MAX_UNSTABLE_POLLS the gate adopts what is there and reopens."""
        gate, window = self._primed()
        window.change(SIZE // 2)
        results = _poll(gate, window, rc.BLOCK_MAX_UNSTABLE_POLLS + 2)
        self.assertTrue(results[-1], "a stuck gate must self-heal rather than withhold for the session")
        self.assertEqual(gate.rebaselines, 1)

    def test_a_multi_burst_save_is_never_trusted_in_the_gaps(self) -> None:
        """The reported bug, directly: "opening the save menu is two writes, but SAVING is three". Quiet polls
        between bursts must not reopen the gate while the content is still wrong."""
        gate, window = self._primed()
        for _burst in range(3):
            window.change(SIZE // 2)          # a write burst
            _poll(gate, window)
            self.assertTrue(all(not r for r in _poll(gate, window, 3)), "quiet, but still not the truth")
            self.assertFalse(gate.stable)
        self.assertFalse(gate.stable)

    def test_it_reopens_the_moment_the_real_content_is_back(self) -> None:
        """And the reason this is safe mid-sequence: if the block holds the true pre-save content, reading it
        is harmless by definition, whether or not the save has finished."""
        gate, window = self._primed()
        before = bytes(window.content)
        window.change(SIZE // 2)
        _poll(gate, window, 4)
        window.content = bytearray(before)
        results = _poll(gate, window, rc.BLOCK_QUIET_POLLS_AFTER_CHURN + 1)
        self.assertTrue(results[-1])

    def test_the_rewrite_back_is_itself_withheld(self) -> None:
        """The restore is as big a write as the corruption. If it were trusted, the tracker would see the
        block snap back and could read that as an event."""
        self.assertGreaterEqual(rc.BLOCK_QUIET_POLLS_AFTER_CHURN, 1)
        gate, window = self._primed()
        window.change(SIZE // 2)
        _poll(gate, window)
        window.change(SIZE // 2)     # rewritten back
        self.assertEqual(_poll(gate, window), [False])

    def test_the_full_reported_sequence_end_to_end(self) -> None:
        """Quiet play -> menu opens (rewrite) -> menu sits open -> menu closes (rewrite back) -> quiet again.
        Not one poll in the disturbed stretch is handed to a tracker."""
        gate, window = self._primed()
        before = bytes(window.content)
        trusted = []
        trusted += _poll(gate, window, 3)                       # quiet
        window.change(SIZE // 2); trusted += _poll(gate, window)  # opens
        trusted += _poll(gate, window, 4)                        # sits open
        # Closing RESTORES the block -- the Bag does not change because you saved. That restoration is what
        # the gate is actually waiting for (ADDENDUM 154), not merely for the writes to stop.
        window.content = bytearray(before); trusted += _poll(gate, window)
        trusted += _poll(gate, window, 4)                        # quiet again
        self.assertEqual(trusted[:3], [True, True, True])
        self.assertFalse(trusted[3], "the poll the menu opened on must be withheld")
        self.assertFalse(trusted[8], "so must the poll it closed on")
        self.assertTrue(trusted[-1], "and normal service must resume on its own")
        # CHANGED 2026-09-12 (ADDENDUM 154): one save menu is now ONE disturbance. Under ADDENDUM 148 the gate
        # reopened while the menu was still open, so closing it counted as a second, separate churn -- which
        # was the bug wearing a diagnostic hat.
        self.assertEqual(gate.churn_events, 1)

    def test_churn_events_counts_menus_not_polls(self) -> None:
        gate, window = self._primed()
        window.change(SIZE // 2)
        _poll(gate, window, 1)
        _poll(gate, window, 10)      # settled, still the same churn episode
        self.assertEqual(gate.churn_events, 1)


class TestFailureModes(unittest.TestCase):
    def test_an_unreadable_window_is_untrusted_not_trusted(self) -> None:
        """The safe direction: a late check costs seconds, a wrong check cannot be taken back."""
        gate, window = rc.BlockStabilityGate(), _Window()
        _poll(gate, window)
        window.explode = True
        self.assertEqual(_poll(gate, window), [False])

    def test_a_short_read_is_untrusted(self) -> None:
        gate = rc.BlockStabilityGate(window_size=SIZE)
        window = _Window(bytes(SIZE // 2))
        with _Patched(window):
            self.assertFalse(gate.poll(BLOCK_BASE))

    def test_a_read_failure_never_raises_out_of_poll(self) -> None:
        window = _Window()
        window.explode = True
        with _Patched(window):
            self.assertFalse(rc.BlockStabilityGate().poll(BLOCK_BASE))

    def test_reset_drops_the_baseline_but_keeps_the_session_counters(self) -> None:
        gate, window = rc.BlockStabilityGate(), _Window()
        _poll(gate, window)
        window.change(SIZE // 2)
        _poll(gate, window)
        gate.reset()
        self.assertTrue(gate.stable, "a fresh baseline starts trusted")
        self.assertEqual(gate.churn_events, 1, "counters describe the session, not the baseline")
        self.assertEqual(_poll(gate, window), [True])


class TestDescribe(unittest.TestCase):
    def test_it_names_the_state_and_the_window(self) -> None:
        gate, window = rc.BlockStabilityGate(), _Window()
        _poll(gate, window)
        text = gate.describe()
        self.assertIn("stable", text)
        self.assertIn(f"{rc.BLOCK_STABILITY_WINDOW_OFFSET:#x}", text)

    def test_it_says_plainly_when_checks_are_paused(self) -> None:
        gate, window = rc.BlockStabilityGate(), _Window()
        _poll(gate, window)
        window.change(SIZE // 2)
        _poll(gate, window)
        self.assertIn("CHURNING", gate.describe())
        self.assertIn("paused", gate.describe())


class TestTheWindowItself(unittest.TestCase):
    def test_it_watches_the_bag_array_where_the_chest_symptom_lives(self) -> None:
        """Not a proxy for the corruption -- the region the corruption was reported in."""
        self.assertEqual(rc.BLOCK_STABILITY_WINDOW_OFFSET, rc.POKEBALL_POCKET_OFFSET)
        self.assertEqual(rc.BLOCK_STABILITY_WINDOW_SIZE,
                         rc.POKEBALL_POCKET_ARRAY_SLOT_COUNT * 4)

    def test_the_threshold_sits_between_real_play_and_a_rewrite(self) -> None:
        self.assertGreater(rc.BLOCK_CHURN_BYTE_THRESHOLD, 4, "one slot write must not trip it")
        self.assertLess(rc.BLOCK_CHURN_BYTE_THRESHOLD, rc.BLOCK_STABILITY_WINDOW_SIZE // 4)


class TestThreeWriteSave(unittest.TestCase):
    def _primed(self):
        gate, window = rc.BlockStabilityGate(), _Window()
        _poll(gate, window)
        return gate, window

    def test_a_three_burst_save_is_never_trusted_in_its_gaps(self) -> None:
        """The reported bug. Two quiet polls between bursts used to be enough to reopen the gate."""
        gate, window = self._primed()
        for _burst in range(3):
            window.rewrite()
            _poll(gate, window)
            self.assertTrue(all(not r for r in _poll(gate, window, 4)))
            self.assertFalse(gate.stable)

    def test_it_reopens_when_the_block_reads_right_again_not_merely_when_it_stops(self) -> None:
        gate, window = self._primed()
        before = bytes(window.content)
        for _burst in range(3):
            window.rewrite()
            _poll(gate, window, 3)
        window.content = bytearray(before)
        results = _poll(gate, window, rc.BLOCK_QUIET_POLLS_AFTER_CHURN + 1)
        self.assertTrue(results[-1])
        self.assertEqual(gate.rebaselines, 0, "this settled on its own -- no escape valve needed")

    def test_restoring_mid_sequence_is_trusted_because_it_is_safe_to_trust(self) -> None:
        """The gate is not detecting "the save finished" -- it is detecting "the block is telling the truth",
        which is both easier to verify and the thing that actually matters."""
        gate, window = self._primed()
        before = bytes(window.content)
        window.rewrite()
        _poll(gate, window, 2)
        window.content = bytearray(before)          # true content is back, save still going
        self.assertTrue(_poll(gate, window, rc.BLOCK_QUIET_POLLS_AFTER_CHURN + 1)[-1])

    def test_a_longer_save_on_a_slower_machine_is_not_a_new_failure_mode(self) -> None:
        """The reason this is not just "raise the quiet count": duration stops mattering."""
        gate, window = self._primed()
        before = bytes(window.content)
        for _burst in range(6):
            window.rewrite()
            _poll(gate, window, 7)
        self.assertFalse(gate.stable)
        window.content = bytearray(before)
        self.assertTrue(_poll(gate, window, rc.BLOCK_QUIET_POLLS_AFTER_CHURN + 1)[-1])

    def test_content_that_legitimately_changed_is_adopted_rather_than_withheld_forever(self) -> None:
        """A chest opened moments before saving never comes back to the old reference."""
        gate, window = self._primed()
        window.rewrite()
        results = _poll(gate, window, rc.BLOCK_MAX_UNSTABLE_POLLS + 2)
        self.assertTrue(results[-1])
        self.assertEqual(gate.rebaselines, 1)

    def test_the_escape_valve_is_long_enough_to_never_fire_during_a_save(self) -> None:
        self.assertGreaterEqual(rc.BLOCK_MAX_UNSTABLE_POLLS, 30)

    def test_quiet_play_is_unaffected(self) -> None:
        gate, window = self._primed()
        self.assertTrue(all(_poll(gate, window, 20)))
        self.assertEqual(gate.churn_events, 0)

    def test_a_chest_pickup_becomes_the_new_trusted_reference(self) -> None:
        """Otherwise the gate would be measuring every future save against a stale pre-chest snapshot, and a
        correctly restored block would never match it again."""
        gate, window = self._primed()
        window.content[0] = (window.content[0] + 1) % 256   # a chest: one u16 quantity
        window.content[1] = (window.content[1] + 1) % 256
        self.assertTrue(_poll(gate, window)[0], "a chest is not a rewrite")
        after_chest = bytes(window.content)

        window.rewrite()                                     # now save
        _poll(gate, window, 3)
        self.assertFalse(gate.stable)
        window.content = bytearray(after_chest)              # the save restores POST-chest content
        self.assertTrue(_poll(gate, window, rc.BLOCK_QUIET_POLLS_AFTER_CHURN + 1)[-1])
        self.assertEqual(gate.rebaselines, 0)


if __name__ == "__main__":
    unittest.main()
