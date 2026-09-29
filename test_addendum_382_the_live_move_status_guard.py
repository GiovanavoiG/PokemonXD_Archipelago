"""ADDENDUM 382 (2026-09-28) -- the census checked against live RAM, because a save state outlives the patch.

Player: "It's possible save stats broke them. Can the guard save us on load state?"

No, and that was the right question. ADDENDUM 381's fence lives in `iso_patcher`: it snapshots the two status
bytes of every move, lets the mutation pass run, and refuses to write the blob if either moved. It has done
its job before the player ever boots. A Dolphin save state restores the whole of MEM1, `common_rel` included,
at runtime -- load one made under a different ISO and the move table in memory is that build's. Nothing on
disc is wrong, and nothing the patcher can check would notice.

So the same census is checked against live RAM, once per block base. `block_base` changes on a boot and on a
save load, which is exactly when a state could have landed, and it is one 20KB read rather than anything
per-poll.

THE COVERAGE IS EVERY MOVE, not only the ones with a status. All 360 entries are pinned -- 332 of them carry
an effect id -- so a move GAINING an effect is caught as readily as one losing it.

IT WARNS AND NEVER BLOCKS. Two reasons, and the first is a standing rule of this project: a diagnostic may
never cost a player a check. The second is that a legitimately different build -- another region, a future
revision -- would fail this census while being perfectly playable, so the table's LOCATION is proven against
PP and base power first, and anything short of that returns None rather than crying wolf.
"""
from __future__ import annotations

import struct
import unittest
from unittest import mock

from .. import ram_client as rc
from ..game_data import move_status
from ..tools import xd_rel_format as rf

CENSUS = move_status.MOVE_STATUS
COUNT = max(CENSUS) + 1


def _healthy_table() -> bytearray:
    """A move table that satisfies both the location fingerprint and the census."""
    buf = bytearray(COUNT * rf.MOVE_ENTRY_SIZE)
    for index, (pp, power) in rf.MOVE_TABLE_FINGERPRINT.items():
        off = index * rf.MOVE_ENTRY_SIZE
        buf[off + rf.MOVE_PP_OFFSET] = pp
        buf[off + rf.MOVE_BASE_POWER_OFFSET] = power
    for index, (chance, effect) in CENSUS.items():
        off = index * rf.MOVE_ENTRY_SIZE
        buf[off + rf.MOVE_SECONDARY_CHANCE_OFFSET] = chance
        buf[off + rf.MOVE_EFFECT_OFFSET] = effect
    return buf


def _reading(table: bytes):
    """Patch `read_bytes` so it serves `table` for the move-table read and nothing else."""
    def fake(address: int, length: int) -> bytes:
        return bytes(table[:length]) if length == len(table) else b"\x00" * length
    return mock.patch.object(rc, "read_bytes", fake)


class TestTheCensusCoversEveryMove(unittest.TestCase):
    def test_it_pins_every_entry_not_only_the_status_ones(self) -> None:
        self.assertEqual(360, len(CENSUS))
        self.assertEqual(list(range(360)), sorted(CENSUS))

    def test_most_moves_carry_an_effect_and_all_are_still_pinned(self) -> None:
        with_effects = move_status.moves_with_effects()
        self.assertEqual(332, len(with_effects))
        self.assertLess(len(with_effects), len(CENSUS),
                        "the effect-less moves must be pinned too, or a move gaining one goes unseen")

    def test_a_move_gaining_an_effect_from_nothing_is_covered(self) -> None:
        """The reason coverage is every move rather than every move WITH an effect."""
        blank = [i for i, (chance, effect) in CENSUS.items() if chance == 0 and effect == 0]
        self.assertTrue(blank, "there are entries with no effect; they must still be in the census")
        table = _healthy_table()
        victim = blank[0]
        table[victim * rf.MOVE_ENTRY_SIZE + rf.MOVE_EFFECT_OFFSET] = 1      # gains sleep
        with _reading(table):
            report = rc.live_move_status_report(CENSUS)
        self.assertEqual([victim], [index for index, _was, _now in report["drifted"]])

    def test_the_two_reported_moves_are_pinned_with_their_real_values(self) -> None:
        self.assertEqual((100, 70), CENSUS[196], "Icy Wind: Speed down at 100%")
        self.assertEqual((30, 202), CENSUS[305], "Poison Fang: its own effect at 30%")


class TestTheLiveRead(unittest.TestCase):
    def test_a_healthy_table_reports_no_drift(self) -> None:
        with _reading(_healthy_table()):
            report = rc.live_move_status_report(CENSUS)
        self.assertIsNotNone(report)
        self.assertEqual(len(CENSUS), report["checked"])
        self.assertEqual([], report["drifted"])
        self.assertEqual([], rc.describe_live_move_status(report))

    def test_a_drifted_effect_is_found_and_named(self) -> None:
        table = _healthy_table()
        table[196 * rf.MOVE_ENTRY_SIZE + rf.MOVE_EFFECT_OFFSET] = 5         # Speed down -> freeze
        with _reading(table):
            report = rc.live_move_status_report(CENSUS)
        self.assertEqual([(196, (100, 70), (100, 5))], report["drifted"])
        lines = rc.describe_live_move_status(report)
        self.assertTrue(any("move 196" in line for line in lines))
        self.assertTrue(any("freeze" in line for line in lines))
        self.assertTrue(any("SAVE STATE" in line for line in lines),
                        "the warning has to name the cause the player can act on")

    def test_a_drifted_chance_is_found(self) -> None:
        table = _healthy_table()
        table[305 * rf.MOVE_ENTRY_SIZE + rf.MOVE_SECONDARY_CHANCE_OFFSET] = 99
        with _reading(table):
            report = rc.live_move_status_report(CENSUS)
        self.assertEqual([(305, (30, 202), (99, 202))], report["drifted"])

    def test_it_reports_nothing_when_the_table_is_not_where_it_should_be(self) -> None:
        """A different region or revision is not a corrupted save -- returning None is the honest answer."""
        table = _healthy_table()
        for index in rf.MOVE_TABLE_FINGERPRINT:
            table[index * rf.MOVE_ENTRY_SIZE + rf.MOVE_PP_OFFSET] = 0xFF
        with _reading(table):
            self.assertIsNone(rc.live_move_status_report(CENSUS))

    def test_a_single_disagreeing_fingerprint_move_is_enough_to_stand_down(self) -> None:
        """No "at least N agreed" threshold: the loop returns on the first disagreement, so a count could only
        ever reach the full total. A probe caught that exact dead condition (ADDENDA 247/298)."""
        import inspect
        source = inspect.getsource(rc.live_move_status_report)
        self.assertNotIn("agreed", source, "a count here can never bind -- do not reintroduce it")
        one = sorted(rf.MOVE_TABLE_FINGERPRINT)[0]
        table = _healthy_table()
        table[one * rf.MOVE_ENTRY_SIZE + rf.MOVE_PP_OFFSET] ^= 0xFF
        with _reading(table):
            self.assertIsNone(rc.live_move_status_report(CENSUS))

    def test_an_unreadable_read_is_silent(self) -> None:
        def boom(address, length):
            raise RuntimeError("no game running")
        with mock.patch.object(rc, "read_bytes", boom):
            self.assertIsNone(rc.live_move_status_report(CENSUS))
        self.assertEqual([], rc.describe_live_move_status(None))

    def test_a_short_read_is_silent(self) -> None:
        with mock.patch.object(rc, "read_bytes", lambda a, n: b"\x00" * (n - 1)):
            self.assertIsNone(rc.live_move_status_report(CENSUS))

    def test_the_warning_is_bounded_when_everything_drifts(self) -> None:
        """A save state from another build could drift hundreds of moves; the log must stay readable."""
        table = _healthy_table()
        for index in CENSUS:
            table[index * rf.MOVE_ENTRY_SIZE + rf.MOVE_EFFECT_OFFSET] = 1
        with _reading(table):
            report = rc.live_move_status_report(CENSUS)
        lines = rc.describe_live_move_status(report)
        self.assertLessEqual(len(lines), 11, "one headline, at most eight moves, one 'and N more'")
        self.assertTrue(any("more" in line for line in lines))


class TestTheTableAddressIsMeasuredNotGuessed(unittest.TestCase):
    def test_the_offset_is_the_one_the_dumps_agreed_on(self) -> None:
        self.assertEqual(0xA2710, rc.MOVE_TABLE_REL_OFFSET)

    def test_it_reads_relative_to_the_common_rel_base(self) -> None:
        import inspect
        source = inspect.getsource(rc.live_move_status_report)
        self.assertIn("COMMON_REL_RAM_BASE", source)
        self.assertIn("MOVE_TABLE_REL_OFFSET", source)


class TestItIsWiredOncePerBlockBaseAndNeverBlocks(unittest.TestCase):
    def setUp(self) -> None:
        # Read by path, not imported: Client.py needs `websockets`, which is why the five permanent loader
        # errors exist and why every structural test in this suite reads it as text.
        import pathlib
        self.source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")

    def test_the_check_is_gated_on_the_block_base(self) -> None:
        self.assertIn("_move_status_checked_for_block_base", self.source)
        gate = self.source.index("if ctx._move_status_checked_for_block_base != ctx.block_base:")
        call = self.source.index("describe_live_move_status", gate)
        self.assertLess(gate, call, "the read must sit behind the once-per-block-base gate")

    def test_the_flag_is_cleared_when_the_block_base_is_lost(self) -> None:
        """Otherwise a save load after a disconnect would never be re-checked."""
        self.assertIn("self._move_status_checked_for_block_base = None", self.source)

    def test_it_logs_and_does_not_raise(self) -> None:
        gate = self.source.index("if ctx._move_status_checked_for_block_base != ctx.block_base:")
        body = self.source[gate:gate + 800]
        self.assertIn("logger.warning", body)
        self.assertIn("except Exception", body, "a diagnostic may never stop the poll loop")
        for forbidden in ("return", "raise", "continue"):
            self.assertNotIn(f"                        {forbidden}", body,
                             f"the guard must not {forbidden} -- it warns only")


if __name__ == "__main__":
    unittest.main()
