"""ADDENDUM 376 (2026-09-27): a chest opened before the client was watching is deducible, not lost.

Player: "Just wire in whatever makes us not miss chest checks. I feel like you're overcomplicating this - berry
gotten, check room id and berry, send check. should be 3 lines of code?"

THEY ARE RIGHT ABOUT THE LIVE PATH, and after ADDENDUM 375 that is what it is: berry rises, the room plus the
berry names the chest, the check goes. The only thing on top is one confirming read (~0.1s), which exists for
a torn read of the berry's u16 rather than for any game behaviour.

SO THE REAL LOSS WAS SOMEWHERE ELSE, and looking for it is what this addendum is. ADDENDUM 246 found it and
deliberately did not fix it: a berry already in the Bag at the first poll becomes the BASELINE, so a chest
opened before the client connected -- or during a reconnect, or in the minutes before the save block resolves,
which is exactly where the Pokemon HQ Lab's three chests are -- "can NEVER fire. No error, no counter, nothing."
That is a check lost outright, not late, and no amount of faster polling touches it.

THE HOLE IN 246'S REASONING. Its argument is arithmetic: seven berries cover 115 chests, seventeen each, and a
carried berry has no room, so crediting one is "a 1-in-17 guess at a check that cannot be taken back". True when
seventeen candidates are live -- and the candidate set is not seventeen chests, it is seventeen MINUS the ones
already checked, which the server tells us. When that leaves exactly one, there is nothing to guess.

1-in-1 is a deduction. Two or more and this does nothing at all, and ADDENDUM 246's notice fires unchanged.
"""
from __future__ import annotations

import collections
import pathlib
import unittest

from .. import ram_client as rc
from ..game_data import chest_berries

CLIENT = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")


def _chests_for(berry_id: int) -> "list[str]":
    return [name for chest, (assigned, _q) in sorted(chest_berries.CHEST_BERRY_ASSIGNMENT.items())
            if assigned == berry_id
            for name in (rc.CHEST_ID_TO_LOCATION.get(chest),) if name]


class TestTheDeduction(unittest.TestCase):
    def setUp(self) -> None:
        counts = collections.Counter(a for a, _q in chest_berries.CHEST_BERRY_ASSIGNMENT.values())
        self.berry = max(counts, key=lambda b: len(_chests_for(b)))
        self.names = _chests_for(self.berry)
        if len(self.names) < 2:
            self.skipTest("need a berry shared by at least two AP chests")

    def _tracker(self) -> "rc.ChestBerryTracker":
        tracker = rc.ChestBerryTracker()
        tracker.baseline_carried[self.berry] = 1
        return tracker

    def test_one_unchecked_candidate_is_credited(self) -> None:
        """The whole addendum. Everything but one of this berry's chests is already checked, so the berry in the
        Bag can only have come from the one that is left."""
        tracker = self._tracker()
        already = frozenset(self.names[1:])
        self.assertEqual([self.names[0]], tracker.unambiguous_backfill(already))
        self.assertEqual(1, tracker.backfilled_unambiguously)

    def test_two_unchecked_candidates_credit_nothing(self) -> None:
        """ADDENDUM 246's objection, preserved exactly. This is the case where crediting would be a guess."""
        tracker = self._tracker()
        already = frozenset(self.names[2:])
        self.assertEqual([], tracker.unambiguous_backfill(already))
        self.assertEqual(0, tracker.backfilled_unambiguously)

    def test_all_checked_credits_nothing(self) -> None:
        """A berry carried for some other reason -- a berry tree, a shop, an NPC -- once its chests are all
        sent. There is nothing to deduce and nothing is invented."""
        tracker = self._tracker()
        self.assertEqual([], tracker.unambiguous_backfill(frozenset(self.names)))

    def test_nothing_carried_credits_nothing(self) -> None:
        self.assertEqual([], rc.ChestBerryTracker().unambiguous_backfill(frozenset()))

    def test_it_never_returns_a_location_that_is_already_checked(self) -> None:
        """The one thing that would make this worse than doing nothing: re-sending a check, or sending one the
        server has already recorded. Swept over every berry and every subset size of one."""
        for berry in sorted({a for a, _q in chest_berries.CHEST_BERRY_ASSIGNMENT.values()}):
            names = _chests_for(berry)
            if len(names) < 2:
                continue
            for keep in names:
                tracker = rc.ChestBerryTracker()
                tracker.baseline_carried[berry] = 1
                already = frozenset(n for n in names if n != keep)
                out = tracker.unambiguous_backfill(already)
                self.assertEqual([keep], out, f"berry {berry}, keeping {keep}")
                self.assertFalse(set(out) & already)

    def test_the_ambiguous_notice_still_exists_untouched(self) -> None:
        """ADDENDUM 246's mechanism is the answer for the ambiguous case and is not being replaced."""
        tracker = self._tracker()
        self.assertTrue(tracker.backfill_candidates(frozenset(self.names[2:])))
        self.assertTrue(tracker.backfill_notice(frozenset(self.names[2:])))


class TestTheClientSendsThemAndSaysSo(unittest.TestCase):
    """Structural -- `Client.py` is not importable here."""

    def test_the_deduced_checks_are_actually_sent(self) -> None:
        block = CLIENT[CLIENT.index("unambiguous_backfill"):]
        block = block[:block.index("backfill_notice")]
        self.assertIn("_send_checks", block, "deduced but never sent is worse than not deducing")

    def test_the_player_is_told_rather_than_it_happening_silently(self) -> None:
        block = CLIENT[CLIENT.index("unambiguous_backfill"):]
        block = block[:block.index("backfill_notice")]
        self.assertIn("logger.info", block)

    def test_the_ambiguous_notice_is_not_told_about_the_ones_just_sent(self) -> None:
        """Otherwise the player is warned to go and check something the client just credited."""
        block = CLIENT[CLIENT.index("unambiguous_backfill"):]
        block = block[:block.index("backfill_notice") + 40]
        self.assertIn("already = already | frozenset(deduced)", block)

    def test_it_runs_once_per_connect_and_not_every_poll(self) -> None:
        self.assertIn("if tracker.baseline_carried and not tracker.backfill_announced:", CLIENT)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
