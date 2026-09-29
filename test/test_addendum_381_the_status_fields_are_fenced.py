"""ADDENDUM 381 (2026-09-28) -- the two bytes that decide a move's status, and the fence that keeps us off them.

Two player reports drove this: "Poison Fang" put its TARGET to sleep, and "Icy Wind" froze BOTH of its
targets. Both replace the move's real effect rather than adding to it, which is what wrong effect DATA looks
like -- so the first question was whether this project's only move-table write was reaching further than
intended.

It is not, and that is now measured rather than argued. Against `bridge/dumps/a263_commonrel.bin` and 163 MEM1
dumps: 160 have a move table byte-identical to the reference, and the three that differ are from a build with
the animation option on. Those three differ at +0x1E/+0x1F in exactly 358 entries -- all but
`MOVES_WITHOUT_ANIMATIONS` -- and at no other byte of any entry. Effect id and secondary-effect chance are
identical for all 360 moves, Icy Wind and Poison Fang included.

What the hunt did produce is the location of both status fields, which this project did not previously know:

  * +0x05 is the secondary-effect chance as a percentage. 24 of 24 known Gen III chances matched exactly.
  * +0x1D is the effect id in Generation III's own EFFECT_* numbering, found by asking which byte separates
    moves whose effect class is known. Twelve classes, each internally unanimous, all twelve distinct.

`MOVE_ANIMATION_OFFSET` is +0x1E -- one byte past the effect id, written as a u16 covering +0x1E and +0x1F.
Correct today, one byte from a status field forever. So the invariant is enforced: the pass snapshots both
bytes of every move before mutating `common_rel` and refuses to write the blob if either moved. That is 720
bytes in a pass whose LZSS re-encode takes tens of seconds, which is why it can be unconditional.
"""
from __future__ import annotations

import struct
import time
import unittest

from ..game_data import move_status
from ..tools import xd_rel_format as rf

COUNT = 360


class _Rel:
    """The loaded image, addressed the way the measurement addressed it."""

    def __init__(self, data: bytes, base: int = 0, count: int = COUNT) -> None:
        self.data = data
        self._base, self._count = base, count

    def get_pointer(self, index: int) -> int:
        return self._base

    def get_value_at_pointer(self, index: int) -> int:
        return self._count


def _table(**overrides) -> bytearray:
    """A synthetic move table that satisfies both censuses, so a test can then break one byte."""
    buf = bytearray(COUNT * rf.MOVE_ENTRY_SIZE)
    for index in range(COUNT):
        off = index * rf.MOVE_ENTRY_SIZE
        struct.pack_into(">H", buf, off + rf.MOVE_ANIMATION_OFFSET, index)
    for index, (pp, power) in rf.MOVE_TABLE_FINGERPRINT.items():
        off = index * rf.MOVE_ENTRY_SIZE
        buf[off + rf.MOVE_PP_OFFSET] = pp
        buf[off + rf.MOVE_BASE_POWER_OFFSET] = power
    for index, (chance, effect) in move_status.MOVE_STATUS.items():
        off = index * rf.MOVE_ENTRY_SIZE
        buf[off + rf.MOVE_SECONDARY_CHANCE_OFFSET] = chance
        buf[off + rf.MOVE_EFFECT_OFFSET] = effect
    for off, value in overrides.items():
        buf[int(off)] = value
    return buf


class TestTheOffsetsAreTheMeasuredOnes(unittest.TestCase):
    def test_the_two_status_offsets(self) -> None:
        self.assertEqual(0x05, rf.MOVE_SECONDARY_CHANCE_OFFSET)
        self.assertEqual(0x1D, rf.MOVE_EFFECT_OFFSET)

    def test_the_animation_write_is_one_byte_past_the_effect_id(self) -> None:
        """The whole reason this fence exists. If these stop being adjacent, re-read the measurement."""
        self.assertEqual(rf.MOVE_EFFECT_OFFSET + 1, rf.MOVE_ANIMATION_OFFSET)

    def test_the_animation_write_does_not_overlap_either_status_field(self) -> None:
        written = {rf.MOVE_ANIMATION_OFFSET, rf.MOVE_ANIMATION_OFFSET + 1}   # a u16
        self.assertNotIn(rf.MOVE_EFFECT_OFFSET, written)
        self.assertNotIn(rf.MOVE_SECONDARY_CHANCE_OFFSET, written)

    def test_the_census_covers_every_effect_class_it_claims(self) -> None:
        """Twelve distinct effect ids is what made the field identifiable; fewer would not have."""
        effects = {effect for _chance, effect in move_status.MOVE_STATUS.values()}
        self.assertGreaterEqual(len(effects), 12)
        for known in (1, 2, 4, 5, 6, 31, 33, 67, 70, 72, 73, 76):
            self.assertIn(known, effects, f"effect {known} dropped out of the census")


class TestTheStrongerVerification(unittest.TestCase):
    def test_a_table_matching_both_censuses_verifies(self) -> None:
        rel = _Rel(bytes(_table()))
        self.assertTrue(rf.verify_moves_table(rel))
        self.assertTrue(rf.verify_move_status_fields(rel, move_status.MOVE_STATUS))

    def test_a_wrong_effect_id_fails_the_status_check_but_not_the_old_one(self) -> None:
        """The point of adding it: PP and base power cannot see a build that numbers effects differently."""
        off = 196 * rf.MOVE_ENTRY_SIZE + rf.MOVE_EFFECT_OFFSET
        rel = _Rel(bytes(_table(**{str(off): 5})))          # speed down -> freeze
        self.assertTrue(rf.verify_moves_table(rel), "the location check is blind to this")
        self.assertFalse(rf.verify_move_status_fields(rel, move_status.MOVE_STATUS))

    def test_a_wrong_chance_also_fails(self) -> None:
        off = 196 * rf.MOVE_ENTRY_SIZE + rf.MOVE_SECONDARY_CHANCE_OFFSET
        rel = _Rel(bytes(_table(**{str(off): 7})))
        self.assertFalse(rf.verify_move_status_fields(rel, move_status.MOVE_STATUS))

    def test_it_refuses_rather_than_raises_when_the_table_is_unreachable(self) -> None:
        class Broken:
            data = b""
            def get_pointer(self, index): raise ValueError("no pointer table")
            def get_value_at_pointer(self, index): raise ValueError("no pointer table")
        self.assertFalse(rf.verify_move_status_fields(Broken(), move_status.MOVE_STATUS))


class TestTheInvariant(unittest.TestCase):
    def test_the_snapshot_is_two_bytes_per_move(self) -> None:
        snap = rf.move_status_fields(bytes(_table()), 0, COUNT)
        self.assertEqual(2 * COUNT, len(snap))

    def test_the_real_animation_write_does_not_trip_it(self) -> None:
        """THE ONE THAT MATTERS. The write this project actually performs must leave the fence untouched."""
        buf = _table()
        before = rf.move_status_fields(bytes(buf), 0, COUNT)
        result = rf.apply_disable_move_animations(buf, _Rel(bytes(buf)))
        self.assertEqual(COUNT - len(rf.MOVES_WITHOUT_ANIMATIONS), result["animations_cleared"])
        rf.assert_move_status_fields_unchanged(before, rf.move_status_fields(bytes(buf), 0, COUNT))

    def test_one_drifted_effect_byte_is_caught_and_named(self) -> None:
        buf = _table()
        before = rf.move_status_fields(bytes(buf), 0, COUNT)
        buf[196 * rf.MOVE_ENTRY_SIZE + rf.MOVE_EFFECT_OFFSET] = 5
        with self.assertRaises(RuntimeError) as caught:
            rf.assert_move_status_fields_unchanged(before, rf.move_status_fields(bytes(buf), 0, COUNT))
        message = str(caught.exception)
        self.assertIn("move 196", message)
        self.assertIn("effect 70->5", message)

    def test_one_drifted_chance_byte_is_caught(self) -> None:
        buf = _table()
        before = rf.move_status_fields(bytes(buf), 0, COUNT)
        buf[305 * rf.MOVE_ENTRY_SIZE + rf.MOVE_SECONDARY_CHANCE_OFFSET] = 99
        with self.assertRaises(RuntimeError):
            rf.assert_move_status_fields_unchanged(before, rf.move_status_fields(bytes(buf), 0, COUNT))

    def test_a_write_to_a_neighbouring_byte_does_not_trip_it(self) -> None:
        """The fence must bind on the status bytes only, or it would refuse every ordinary patch."""
        buf = _table()
        before = rf.move_status_fields(bytes(buf), 0, COUNT)
        buf[196 * rf.MOVE_ENTRY_SIZE + rf.MOVE_BASE_POWER_OFFSET] = 1
        rf.assert_move_status_fields_unchanged(before, rf.move_status_fields(bytes(buf), 0, COUNT))


class TestItIsCheapEnoughToBeUnconditional(unittest.TestCase):
    def test_snapshot_and_compare_cost(self) -> None:
        """The claim in the module docstring, measured: this has to be free next to a tens-of-seconds encode."""
        buf = bytes(_table())
        start = time.perf_counter()
        for _ in range(20):
            before = rf.move_status_fields(buf, 0, COUNT)
            rf.assert_move_status_fields_unchanged(before, rf.move_status_fields(buf, 0, COUNT))
        per_pass = (time.perf_counter() - start) / 20
        self.assertLess(per_pass, 0.05, f"{per_pass * 1000:.1f}ms per pass is too slow to be unconditional")


class TestTheCallSiteReallyUsesIt(unittest.TestCase):
    """Structural: the helpers existing proves nothing if the patch pass does not call them."""

    def setUp(self) -> None:
        import os
        from ..tools import iso_patcher
        with open(os.path.abspath(iso_patcher.__file__), encoding="utf-8") as fh:
            self.source = fh.read()

    def test_the_pass_snapshots_before_mutating_and_verifies_before_writing(self) -> None:
        snap = self.source.index("move_status_before = rel_format.move_status_fields")
        check = self.source.index("assert_move_status_fields_unchanged")
        write = self.source.index("new_entry_raw, real_comp_size, _grew = deck_format.patch_entry_decompressed")
        self.assertLess(snap, check, "the snapshot must be taken before the comparison")
        self.assertLess(check, write, "the comparison must happen before the blob is written")

    def test_every_common_rel_writer_sits_inside_the_fence(self) -> None:
        snap = self.source.index("move_status_before = rel_format.move_status_fields")
        check = self.source.index("assert_move_status_fields_unchanged")
        fenced = self.source[snap:check]
        for writer in ("apply_chest_dummy_item", "apply_pokespot_species", "apply_experience_rate",
                       "apply_catch_rate", "apply_disable_move_animations", "apply_item_name_rename"):
            self.assertIn(writer, fenced, f"{writer} is outside the status fence")

    def test_the_animation_option_requires_the_status_verification(self) -> None:
        start = self.source.index("if disable_move_animations:")
        body = self.source[start:self.source.index("apply_disable_move_animations(rel_bytes, rel)", start)]
        self.assertIn("verify_move_status_fields", body,
                      "the write nearest the status fields must require the stronger check")


if __name__ == "__main__":
    unittest.main()
