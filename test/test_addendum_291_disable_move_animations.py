"""ADDENDUM 291 (2026-09-20) -- move animations off, and the offset measured rather than borrowed.

Player: "Rotobash found a way to disable animations in game - i'd like this as an option, but they didn't show
how. Can you search/scan for this?"

They did show how, in code rather than in a readme. rotobash/pokemon-ngc-rando has a move pass that zeroes
every move's animation id, and its `Move` class resolves that id to `common_rel` pointer 124, a 0x38-byte
stride, and a u16 at entry offset +0x1E for XD. Four facts -- a pointer index, a stride and two offsets. None
of their code or wording is reproduced in this project; the originals are in `MoveShuffler.cs` and `Move.cs`
in that repository.

**A hardcoded offset from another project is a hypothesis, not a fact about this ISO.** So before a line was
written, a window slid over the whole of the player's own `common_rel` looking for a 0x38-stride table whose
+0x01 and +0x19 reproduce eighteen known Gen III (PP, base power) pairs. Exactly ONE candidate survived, at
0xA2710 -- byte for byte the offset rotobash hardcodes. Type and accuracy then decoded correctly too, which
nothing in the search had asked for.

The measurement also produced two things the source does not state:

  * **the animation id IS the move index** -- move 1 has animation 1, move 16 has animation 16, 359 distinct
    values over 359 entries. A 1:1 table, so slot 0 really is the "no animation" entry and writing 0 is
    unambiguous rather than a guess at a sentinel;
  * **it explains why that project's move pass skips indices 0 and 355**, which its own source does not say:
    those two are the only entries in the whole table whose animation id is already 0. They are skipped
    because there is nothing to do.

The dump-backed class at the end re-derives all of this on every run where the dump is present, and skips
(not silently passes) where it is not.
"""
from __future__ import annotations

import os
import struct
import unittest
from unittest import mock

from ..tools import xd_rel_format as rf

DUMP = "/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/a263_commonrel.bin"
DUMP_MOVES_BASE = 0xA2710
DUMP_MOVE_COUNT = 360


class _Rel:
    def __init__(self, data) -> None:
        self.data = data


class TestTheLayoutIsWrittenDown(unittest.TestCase):
    def test_the_offsets_match_the_source_they_came_from(self) -> None:
        self.assertEqual(124, rf.XD_MOVES_POINTER)
        self.assertEqual(125, rf.XD_NUMBER_OF_MOVES_POINTER)
        self.assertEqual(0x38, rf.MOVE_ENTRY_SIZE)
        self.assertEqual(0x1E, rf.MOVE_ANIMATION_OFFSET)

    def test_the_second_animation_field_is_recorded_and_not_written(self) -> None:
        """Measured, deliberately untouched. The prior art zeroes +0x1E alone and ships it working; guessing
        at a second field on a hunch is how an unmeasured offset becomes load-bearing."""
        self.assertEqual(0x32, rf.MOVE_SECOND_ANIMATION_OFFSET)
        source = open(rf.__file__, encoding="utf-8").read()
        start = source.index("def apply_disable_move_animations")
        body = source[start:source.index("\ndef ", start + 1)]
        self.assertNotIn("MOVE_SECOND_ANIMATION_OFFSET", body)

    def test_the_fingerprint_is_evidence_not_data(self) -> None:
        """It is only ever compared against, never written. If that ever changes, this is the wrong shape."""
        self.assertGreaterEqual(len(rf.MOVE_TABLE_FINGERPRINT), 12)
        source = open(rf.__file__, encoding="utf-8").read()
        start = source.index("def apply_disable_move_animations")
        body = source[start:source.index("\ndef ", start + 1)]
        self.assertNotIn("MOVE_TABLE_FINGERPRINT", body)


class TestTheWriterRefusesRatherThanGuessing(unittest.TestCase):
    def setUp(self) -> None:
        self.base, self.count = 0, 8
        p1 = mock.patch.object(rf, "moves_table_base", lambda rel: self.base)
        p2 = mock.patch.object(rf, "moves_table_count", lambda rel: self.count)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)

    def test_an_unverifiable_table_is_refused(self) -> None:
        self.assertFalse(rf.verify_moves_table(_Rel(bytes(self.count * rf.MOVE_ENTRY_SIZE))))

    def test_a_table_running_past_the_rel_raises_before_any_write(self) -> None:
        rel = _Rel(bytes(self.count * rf.MOVE_ENTRY_SIZE))
        buf = bytearray(rf.MOVE_ENTRY_SIZE)          # far too short for the declared count
        with self.assertRaises(ValueError):
            rf.apply_disable_move_animations(buf, rel)

    def test_it_writes_exactly_the_animation_field(self) -> None:
        buf = bytearray(self.count * rf.MOVE_ENTRY_SIZE)
        for index in range(self.count):
            # Index 0 is the "no animation" slot in the real table, so the fixture matches reality.
            struct.pack_into(">H", buf, index * rf.MOVE_ENTRY_SIZE + rf.MOVE_ANIMATION_OFFSET, index)
            struct.pack_into(">H", buf, index * rf.MOVE_ENTRY_SIZE + rf.MOVE_SECOND_ANIMATION_OFFSET, 99)
            buf[index * rf.MOVE_ENTRY_SIZE + rf.MOVE_BASE_POWER_OFFSET] = 60
        before = bytes(buf)
        result = rf.apply_disable_move_animations(buf, _Rel(before))
        self.assertEqual(self.count - 1, result["animations_cleared"], "index 0 is already silent")
        self.assertEqual(1, result["already_silent"])
        for index in range(self.count):
            entry = index * rf.MOVE_ENTRY_SIZE
            self.assertEqual(0, struct.unpack_from(">H", buf, entry + rf.MOVE_ANIMATION_OFFSET)[0])
            self.assertEqual(99, struct.unpack_from(">H", buf, entry + rf.MOVE_SECOND_ANIMATION_OFFSET)[0])
            self.assertEqual(60, buf[entry + rf.MOVE_BASE_POWER_OFFSET])

    def test_rerunning_it_changes_nothing(self) -> None:
        buf = bytearray(self.count * rf.MOVE_ENTRY_SIZE)
        for index in range(self.count):
            struct.pack_into(">H", buf, index * rf.MOVE_ENTRY_SIZE + rf.MOVE_ANIMATION_OFFSET, index)
        rf.apply_disable_move_animations(buf, _Rel(bytes(buf)))
        settled = bytes(buf)
        self.assertEqual(0, struct.unpack_from(">H", settled, rf.MOVE_ANIMATION_OFFSET)[0])
        again = rf.apply_disable_move_animations(buf, _Rel(settled))
        self.assertEqual(0, again["animations_cleared"])
        self.assertEqual(settled, bytes(buf))


class TestAgainstTheRealCommonRel(unittest.TestCase):
    """Re-derived from the player's own dump on every run where it is present."""

    @classmethod
    def setUpClass(cls) -> None:
        if not os.path.exists(DUMP):
            raise unittest.SkipTest("a263_commonrel.bin not available")
        with open(DUMP, "rb") as handle:
            cls.data = handle.read()
        cls.rel = _Rel(cls.data)
        cls._p1 = mock.patch.object(rf, "moves_table_base", lambda rel: DUMP_MOVES_BASE)
        cls._p2 = mock.patch.object(rf, "moves_table_count", lambda rel: DUMP_MOVE_COUNT)
        cls._p1.start(); cls._p2.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._p1.stop(); cls._p2.stop()

    def _anim(self, index: int) -> int:
        off = DUMP_MOVES_BASE + index * rf.MOVE_ENTRY_SIZE + rf.MOVE_ANIMATION_OFFSET
        return struct.unpack_from(">H", self.data, off)[0]

    def test_the_table_is_where_rotobash_said_and_this_project_measured(self) -> None:
        self.assertTrue(rf.verify_moves_table(self.rel))

    def test_the_search_that_found_it_still_finds_only_one_candidate(self) -> None:
        """THE EVIDENCE. Eighteen known (PP, base power) pairs at a 0x38 stride, over the whole REL."""
        hits = []
        for base in range(0, len(self.data) - DUMP_MOVE_COUNT * rf.MOVE_ENTRY_SIZE, 4):
            for index, (pp, power) in rf.MOVE_TABLE_FINGERPRINT.items():
                off = base + index * rf.MOVE_ENTRY_SIZE
                if (self.data[off + rf.MOVE_PP_OFFSET] != pp
                        or self.data[off + rf.MOVE_BASE_POWER_OFFSET] != power):
                    break
            else:
                hits.append(base)
        self.assertEqual([DUMP_MOVES_BASE], hits)

    def test_the_animation_id_is_the_move_index(self) -> None:
        """Not stated anywhere in rotobash's source; it is what makes writing 0 unambiguous."""
        for index in (1, 2, 7, 16, 63, 200, 354):
            self.assertEqual(index, self._anim(index), index)

    def test_the_two_skipped_entries_are_the_ones_already_silent(self) -> None:
        """Explains the prior art's skip list without its source having had to say so."""
        already = {i for i in range(DUMP_MOVE_COUNT) if self._anim(i) == 0}
        self.assertEqual(rf.MOVES_WITHOUT_ANIMATIONS, already)

    def test_a_real_patch_touches_only_the_animation_field(self) -> None:
        buf = bytearray(self.data)
        result = rf.apply_disable_move_animations(buf, self.rel)
        self.assertEqual(358, result["animations_cleared"])
        self.assertEqual(2, result["already_silent"])
        changed = [i for i in range(len(buf)) if buf[i] != self.data[i]]
        self.assertTrue(changed)
        table_end = DUMP_MOVES_BASE + DUMP_MOVE_COUNT * rf.MOVE_ENTRY_SIZE
        for i in changed:
            self.assertTrue(DUMP_MOVES_BASE <= i < table_end, hex(i))
            self.assertIn((i - DUMP_MOVES_BASE) % rf.MOVE_ENTRY_SIZE,
                          (rf.MOVE_ANIMATION_OFFSET, rf.MOVE_ANIMATION_OFFSET + 1), hex(i))

    def test_nothing_that_decides_a_battle_moves(self) -> None:
        buf = bytearray(self.data)
        rf.apply_disable_move_animations(buf, self.rel)
        for offset in (rf.MOVE_PP_OFFSET, rf.MOVE_TYPE_OFFSET, rf.MOVE_ACCURACY_OFFSET,
                       rf.MOVE_BASE_POWER_OFFSET, rf.MOVE_SECOND_ANIMATION_OFFSET):
            for index in range(DUMP_MOVE_COUNT):
                at = DUMP_MOVES_BASE + index * rf.MOVE_ENTRY_SIZE + offset
                self.assertEqual(self.data[at], buf[at], f"offset 0x{offset:02X} move {index}")


class TestTheOptionAndItsWiring(unittest.TestCase):
    def test_the_option_exists_and_is_off_by_default(self) -> None:
        from ..options import DisableMoveAnimations, PokemonXDOptions
        self.assertEqual(0, DisableMoveAnimations.default)
        self.assertIn("disable_move_animations", PokemonXDOptions.__annotations__)

    def test_the_seed_carries_a_flag_rather_than_a_plan(self) -> None:
        import pathlib
        world = (pathlib.Path(__file__).resolve().parent.parent / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('seed_data["disable_move_animations"] = bool(', world)

    def test_the_patcher_verifies_before_it_writes(self) -> None:
        import pathlib
        patcher = (pathlib.Path(__file__).resolve().parent.parent
                   / "tools" / "iso_patcher.py").read_text(encoding="utf-8")
        start = patcher.index("if disable_move_animations:")
        # Anchored on the next option's block rather than a byte count: ADDENDUM 381 added a second refusal
        # branch here and a fixed window silently stopped covering the apply call.
        body = patcher[start:patcher.index('exp_result = {"base_exp_written"', start)]
        self.assertIn("verify_moves_table", body)
        verify_at = body.index("verify_moves_table")
        apply_at = body.index("apply_disable_move_animations")
        self.assertLess(verify_at, apply_at, "the table must be proven before a byte goes in")
        # ADDENDUM 381: and the status census too, since this write lands one byte past the effect id.
        self.assertLess(body.index("verify_move_status_fields"), apply_at)

    def test_it_shares_the_one_common_rel_pass(self) -> None:
        """common_rel's LZSS re-encode is the slowest step in the whole patch; a second one for two bytes per
        move would be the wrong trade. Same reasoning ADDENDUM 285 recorded."""
        import pathlib
        patcher = (pathlib.Path(__file__).resolve().parent.parent
                   / "tools" / "iso_patcher.py").read_text(encoding="utf-8")
        self.assertEqual(1, patcher.count("apply_disable_move_animations(rel_bytes, rel)"))
        self.assertIn("or experience_rate != 100 or disable_move_animations", patcher)


if __name__ == "__main__":
    unittest.main()
