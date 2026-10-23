"""Saving over an older file shows that file's story and travel records for a while. Nothing that reads a story
byte or a travel bit may act on them."""
from __future__ import annotations

import unittest
from pathlib import Path

from .. import ram_client

CLIENT = (Path(__file__).resolve().parents[1] / "Client.py").read_text(encoding="utf-8")


class TestBlockTrust(unittest.TestCase):
    def test_needs_three_settled_polls_in_a_row(self) -> None:
        trust = ram_client.BlockTrust()
        self.assertEqual([False, False, True, True, False, False, False, True],
                         [trust.poll(s) for s in (True, True, True, True, False, True, True, True)])

    def test_reset_starts_over(self) -> None:
        trust = ram_client.BlockTrust()
        for _ in range(5):
            trust.poll(True)
        trust.reset()
        self.assertFalse(trust.poll(True))


class TestTheWitnessConfirms(unittest.TestCase):
    def test_a_single_high_reading_is_not_banked(self) -> None:
        witness = ram_client.StoryProgressWitness(confirm_polls=2)
        for value in (0x16, 0x16):
            witness.poll(value, 1, False, False)
        self.assertEqual(0x16, witness.high_water)
        witness.poll(0x7A, 1, False, False)          # one stray reading
        witness.poll(0x16, 1, False, False)
        self.assertEqual(0x16, witness.high_water)
        witness.poll(0x17, 1, False, False)
        witness.poll(0x17, 1, False, False)
        self.assertEqual(0x17, witness.high_water)

    def test_the_client_uses_two(self) -> None:
        self.assertIn("ram_client.StoryProgressWitness(confirm_polls=2)", CLIENT)


class TestTheLoop(unittest.TestCase):
    def setUp(self) -> None:
        start = CLIENT.index("block_is_stable = ctx.block_trust.poll(")
        self.loop = CLIENT[start:CLIENT.index("elif not ctx._block_churn_logged:", start)]

    def test_trust_comes_first(self) -> None:
        self.assertLess(self.loop.index("block_is_stable = ctx.block_trust.poll("),
                        self.loop.index("await flush_pending_checks(ctx)"))

    def test_travel_readers_and_writers_wait_for_it(self) -> None:
        for call in ("observe_travel_reveals(ctx)", "await sync_travel_locations(ctx)",
                     "await enforce_travel_locks(ctx)"):
            head = self.loop[:self.loop.index(call)]
            self.assertTrue(head.rstrip().endswith("if block_is_stable:") or
                            head.rstrip().endswith("observe_travel_reveals(ctx)"), call)

    def test_the_gate_is_polled_once(self) -> None:
        self.assertEqual(1, self.loop.count("ctx.block_stability.poll(ctx.block_base)"))

    def test_a_reveal_needs_two_reads(self) -> None:
        body = CLIENT[CLIENT.index("def observe_travel_reveals"):CLIENT.index("REALGAM_REVEAL_NAME = ")]
        self.assertIn("if name not in ctx._travel_reveal_candidates:", body)
        self.assertIn("ctx._travel_reveal_candidates = seen_now", body)
