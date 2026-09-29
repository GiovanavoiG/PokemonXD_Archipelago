"""ADDENDUM 309 (2026-09-22) -- item delivery starts on a step, not on the absence of a detected battle.

Player: "Can we attach item delivery to the step counter incrementing? seems much safer than battle
scanning. Check ngc-rando to see if they found the step counter, otherwise scan our dumps - it should mostly
increment and then maybe reset to 0 at intervals."

NOTHING PUBLISHED. Neither rotobash's randomizer nor the public XD RAM research documents a step counter, so
it was found in this project's own MEM1 corpus by requiring the shape a step counter MUST have: unchanged
across every battle and idle pair (nobody walks in a battle), changed across walk pairs. Across the whole save
block exactly one offset qualified -- `+0x908`, u32BE.

The player expected it might reset at intervals. It does not: a plain running total, 0 on a new save and
climbing monotonically through at least 14,765 steps. That makes the gate simpler, not harder.

WHY THIS IS SAFER THAN WHAT IT REPLACES. The battle gate is a detector that can only fail by missing, and
ADDENDUM 294 found it claiming a battle for the whole ten-minute backstop. The step counter moves only when
the player walks in the field -- the one state in which a Bag write is certainly safe.

The dump-backed classes pin the offset against the real corpus and skip, rather than pass, where the dumps are
not present.
"""
from __future__ import annotations

import os
import struct
import unittest
from unittest import mock

from .. import Client
from .. import ram_client as rc

DUMPS = "/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/"


def _gate_reading(values):
    """A StepCounterGate whose reads return `values` in order."""
    seq = iter(values)
    return mock.patch.object(rc, "read_bytes", lambda addr, n: struct.pack(">I", next(seq)))


class TestTheLayout(unittest.TestCase):
    def test_the_offset(self) -> None:
        self.assertEqual(0x908, rc.STEP_COUNTER_OFFSET)

    def test_it_is_inside_the_block_it_is_read_from(self) -> None:
        """Near money (0x8A4), far below the story record (0x10720) -- the same save block every other
        block-relative field in this client already reads."""
        self.assertLess(rc.MONEY_OFFSET, rc.STEP_COUNTER_OFFSET)
        self.assertLess(rc.STEP_COUNTER_OFFSET, rc.STORY_RECORD_OFFSET)

    def test_an_unreadable_block_returns_none_not_zero(self) -> None:
        """None is what hands delivery back to the battle gate. Zero would look like a real reading."""
        self.assertIsNone(rc.read_step_counter(None))
        with mock.patch.object(rc, "read_bytes", side_effect=RuntimeError("not hooked")):
            self.assertIsNone(rc.read_step_counter(0x80479000))


class TestTheGate(unittest.TestCase):
    BASE = 0x80479000

    def _run(self, values, times):
        gate = rc.StepCounterGate()
        out = []
        with _gate_reading(values):
            for t in times:
                out.append(gate.poll(self.BASE, now=t))
        return gate, out

    def test_the_first_poll_only_takes_a_baseline(self) -> None:
        _, out = self._run([100], [0.0])
        self.assertEqual([False], out)

    def test_a_step_opens_it(self) -> None:
        _, out = self._run([100, 101], [0.0, 1.0])
        self.assertEqual([False, True], out)

    def test_standing_still_keeps_it_shut(self) -> None:
        _, out = self._run([100, 100, 100], [0.0, 1.0, 2.0])
        self.assertEqual([False, False, False], out)

    def test_it_closes_again_the_moment_walking_stops(self) -> None:
        _, out = self._run([100, 103, 103], [0.0, 1.0, 2.0])
        self.assertEqual([False, True, False], out)

    def test_a_save_load_that_lowers_the_count_is_not_a_step(self) -> None:
        _, out = self._run([900, 40, 41], [0.0, 1.0, 2.0])
        self.assertEqual([False, False, True], out, "re-baselines on the drop, then works normally")

    def test_a_jump_too_big_to_be_walking_is_not_a_step(self) -> None:
        _, out = self._run([100, 5000], [0.0, 1.0])
        self.assertEqual([False, False], out)

    def test_a_stale_baseline_is_not_trusted(self) -> None:
        """THE BUG THIS PREVENTS. Steps walked minutes ago say nothing about whether a battle is running now;
        without the age check a queued item arriving after a long idle would be written on old walking."""
        _, out = self._run([100, 150], [0.0, 300.0])
        self.assertEqual([False, False], out)

    def test_a_new_block_base_re_baselines(self) -> None:
        gate = rc.StepCounterGate()
        with _gate_reading([100, 101]):
            self.assertFalse(gate.poll(0x80479000, now=0.0))
            self.assertFalse(gate.poll(0x80479380, now=1.0), "different boot -- the old value means nothing")

    def test_unreadable_returns_none_and_forgets_the_baseline(self) -> None:
        gate = rc.StepCounterGate()
        with _gate_reading([100]):
            gate.poll(self.BASE, now=0.0)
        with mock.patch.object(rc, "read_bytes", side_effect=RuntimeError):
            self.assertIsNone(gate.poll(self.BASE, now=1.0))
        with _gate_reading([101]):
            self.assertFalse(gate.poll(self.BASE, now=2.0), "a read gap must not bridge to a false step")

    def test_it_counts_the_polls_it_opened(self) -> None:
        gate, _ = self._run([1, 2, 3, 3], [0.0, 1.0, 2.0, 3.0])
        self.assertEqual(2, gate.advanced_polls)


class TestTheWiring(unittest.TestCase):
    def setUp(self) -> None:
        self.source = open(Client.__file__, encoding="utf-8").read()
        start = self.source.index("async def give_items(")
        self.body = self.source[start:self.source.index("\nasync def ", start + 1)]

    def test_the_gate_is_polled_before_the_nothing_pending_return(self) -> None:
        """Otherwise its baseline goes stale exactly while nothing is queued -- the moment before an item
        arrives. The age check is the second fence on the same failure."""
        poll = self.body.index("ctx.step_gate.poll(ctx.block_base)")
        early = self.body.index("if len(ctx.given_item_indices) >= len(received):")
        self.assertLess(poll, early)

    def test_an_unreadable_counter_falls_back_to_the_battle_gate(self) -> None:
        self.assertIn("if walked is None:", self.body)
        self.assertIn("safe_to_start_new_items = battle_says_safe", self.body)

    def test_the_battle_tracker_is_still_polled_every_tick(self) -> None:
        """Its debounce depends on the calls; a fallback that had not been polled would start cold."""
        self.assertIn("battle_says_safe = ctx.battle_state_tracker.poll(", self.body)

    def test_the_ten_minute_backstop_still_applies(self) -> None:
        """"Never block sending items" -- a player idling in a menu still receives, eventually."""
        self.assertIn("waited < ITEM_DELIVERY_MAX_BATTLE_WAIT_SECONDS", self.body)

    def test_the_context_owns_one_gate(self) -> None:
        self.assertIn("self.step_gate = ram_client.StepCounterGate()", self.source)


def _block(mem: bytes) -> int:
    marker = rc.MONEY_OFFSET + 0xC
    found = []
    i = mem.find(b"\x01" * 8)
    while i != -1:
        base = i - marker
        if 0x470000 <= base <= 0x49FFFF and mem[base + rc.MONEY_OFFSET + 8:base + rc.MONEY_OFFSET + 12] == bytes(4):
            found.append(base)
        i = mem.find(b"\x01" * 8, i + 1)
    assert len(found) == 1, found
    return found[0]


def _steps(name: str) -> int:
    with open(DUMPS + name, "rb") as handle:
        mem = handle.read()
    return struct.unpack_from(">I", mem, _block(mem) + rc.STEP_COUNTER_OFFSET)[0]


@unittest.skipUnless(os.path.exists(DUMPS + "battle1_pre.bin"), "no MEM1 dump corpus in this workspace")
class TestAgainstTheRealCorpus(unittest.TestCase):
    def test_a_battle_takes_no_steps(self) -> None:
        for pre, post in (("battle1_pre.bin", "battle1_post.bin"), ("b2_mid.bin", "b2_end.bin")):
            self.assertEqual(_steps(pre), _steps(post), pre)

    def test_the_map_screen_takes_no_steps(self) -> None:
        self.assertEqual(_steps("mapsel_s1_phenac.bin"), _steps("mapsel_s6_cipherlab2.bin"))

    def test_walking_between_rooms_does(self) -> None:
        walk = [_steps(n) for n in ("loc_hq_1.bin", "loc_gateon.bin", "loc_kaminko.bin", "loc_hq_3.bin")]
        self.assertEqual(sorted(walk), walk)
        self.assertGreater(walk[-1], walk[0])

    def test_a_new_save_starts_at_zero(self) -> None:
        self.assertEqual(0, _steps("mem1_baseline.bin"))

    def test_the_rises_look_like_walking(self) -> None:
        """Small steps room to room -- not a frame counter (thousands a minute) or a play-time clock."""
        a, b = _steps("loc_hq_1.bin"), _steps("loc_hq_3.bin")
        self.assertLess(b - a, 500)


if __name__ == "__main__":
    unittest.main()
