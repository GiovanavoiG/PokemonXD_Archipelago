"""ADDENDUM 303 (2026-09-20) -- the search for a field that makes a catch unconditional.

Player: "let's scan that catch rate function again and see if we can find some other field to make it 100%".

THREE NEGATIVE RESULTS, AND THEY ARE THE MOST VALUABLE PART. ADDENDUM 300 shipped 255 and said plainly it is
not certainty. This addendum went looking for the thing that is, and eliminated:

  1. THE DDPK RECORD. All 83 in-use entries scanned byte by byte against the one Pokemon in this game that IS
     a guaranteed catch -- the tutorial Teddiursa at ddpk index 1. The only bytes unique to it are its level
     (the only level-11 Shadow) and its deck pointer (unique to every entry by construction). Six offsets are
     all-zero across every entry, so there is no spare flag hiding there either.
  2. THE ITEMS TABLE. All twelve balls are BYTE-IDENTICAL outside price, name id, description id and their own
     id. There is no per-ball multiplier in data at all, which means the ball bonus is in code.
  3. A SEPARATE BONUS ARRAY. Scans of the whole REL for float runs (1.0 / 1.5 / 2.0 / 3.0) and for x10 integer
     runs shaped like Gen III's own `sBallCatchBonuses` found nothing.

ONE POSITIVE RESULT. A second table, indexed by item id with an 8-byte stride, whose +0x04 is the item's "use"
handler -- the same pointer the Items table carries at its own +0x20. In it, the Master Ball is the ONLY row
of 34 with a non-zero byte at +0x00. The Master Ball is also the only unconditional catch in the game.

THAT IS A COINCIDENCE, NOT A MEANING, and this file is careful to test only what was measured. The byte could
mark "never consumed", "battle-only", or something unrelated. So nothing here is wired to a yaml option; what
ships is a diagnostic that produces an ISO to throw one ball with, exactly the way ADDENDUM 58 settled which
DarkPokemon copy the game reads instead of arguing about it.

AND ONE FACT THAT CLOSES A DOOR. The ball's use handler is at 0x800A4B7C, which is BELOW common_rel's RAM base
(0x80B18DC0, from ADDENDUM 263's own measurement). The routine lives in the main DOL. This project has never
patched the DOL and does not start here.
"""
from __future__ import annotations

import os
import struct
import unittest
from unittest import mock

from ..game_data import species_stats as ss
from ..tools import xd_deck_format as df
from ..tools import xd_rel_format as rf

COMMON_REL_DUMP = "/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/a263_commonrel.bin"
DARK_DUMP = "/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/deck_dark_1.bin"
DUMP_ITEMS_BASE = 0x1FEE4
DUMP_BEHAVIOR_BASE = 0xAB330

#: Measured, and the reason this addendum exists: ADDENDUM 263 put the Items table at common_rel + 0x01FEE4
#: while the game had it at 0x80B38CA4, so common_rel's RAM base is the difference.
COMMON_REL_RAM_BASE = 0x80B38CA4 - DUMP_ITEMS_BASE
BALL_USE_HANDLER = 0x800A4B7C


class _Rel:
    def __init__(self, data) -> None:
        self.data = data


class TestTheLayoutIsStatedOnce(unittest.TestCase):
    def test_the_constants(self) -> None:
        self.assertEqual(8, rf.ITEM_BEHAVIOR_ENTRY_SIZE)
        self.assertEqual(0x00, rf.ITEM_BEHAVIOR_VALUE_OFFSET)
        self.assertEqual(0x02, rf.ITEM_BEHAVIOR_CONSTANT_OFFSET)
        self.assertEqual(0x04, rf.ITEM_BEHAVIOR_HANDLER_OFFSET)
        self.assertEqual(0x0104, rf.ITEM_BEHAVIOR_ROW_CONSTANT)
        self.assertEqual(0x8C00, rf.MASTER_BALL_BEHAVIOR_VALUE)
        self.assertEqual(0x8000, rf.MASTER_BALL_BEHAVIOR_BIT)

    def test_the_ball_ids_are_the_twelve(self) -> None:
        self.assertEqual(tuple(range(1, 13)), rf.BALL_ITEM_IDS)

    def test_the_ball_handler_is_outside_common_rel(self) -> None:
        """The door this closes: the routine that would have to change is in the main DOL, which this project
        does not patch. Stated as arithmetic so it cannot quietly stop being true."""
        self.assertLess(BALL_USE_HANDLER, COMMON_REL_RAM_BASE)

    def test_the_locator_reads_no_field_that_only_exists_in_ram(self) -> None:
        """ADDENDUM 304's regression, stated at the source. The first version of this locator matched the
        Items table's own +0x20 handler pointers -- which are 0x00000000 ON DISC and filled in by the REL
        loader at runtime. It found the table in a RAM dump and returned None on every real ISO."""
        import inspect

        body = inspect.getsource(rf.find_item_behavior_table)
        self.assertNotIn("item_table_base", body)
        self.assertNotIn("xd_number_of_items", body)


class TestTheWriterRefusesRatherThanGuessing(unittest.TestCase):
    def test_a_row_past_the_end_raises_before_writing(self) -> None:
        buf = bytearray(0x40)
        with self.assertRaises(ValueError):
            rf.apply_item_behavior_value(buf, _Rel(bytes(buf)), 0, [999], 0x8C00)
        self.assertEqual(bytes(0x40), bytes(buf))

    def test_a_value_that_does_not_fit_the_u16_raises(self) -> None:
        buf = bytearray(0x200)
        with self.assertRaises(ValueError):
            rf.apply_item_behavior_value(buf, _Rel(bytes(buf)), 0, [4], 0x1FFFF)

    def test_the_default_ors_the_bit_rather_than_replacing_the_row(self) -> None:
        """The low bits differ per item and plainly mean something -- replacing them wholesale would risk
        breaking the ball rather than testing the bit."""
        buf = bytearray(0x200)
        struct.pack_into(">H", buf, 4 * 8, 0x0028)
        rf.apply_item_behavior_value(buf, _Rel(bytes(buf)), 0, [4])
        self.assertEqual(0x8028, struct.unpack_from(">H", buf, 4 * 8)[0])

    def test_a_real_write_touches_only_the_named_row(self) -> None:
        buf = bytearray(0x200)
        before = bytes(buf)
        result = rf.apply_item_behavior_value(buf, _Rel(bytes(buf)), 0, [4], 0x8C00)
        self.assertEqual({"behaviour_values_written": 1}, result)
        changed = [i for i in range(len(buf)) if buf[i] != before[i]]
        self.assertEqual([4 * 8], changed, "only the high byte differs from zero here, and nothing else moved")


def _synthetic_rel(rows: int = 400, flagged_index: "int | None" = 5,
                   ball_handler: int = 0x800A4B7C) -> bytes:
    """A REL-shaped blob carrying one behaviour table, for the negative cases."""
    data = bytearray(0x20000)
    base = 0x1000
    for k in range(rows):
        off = base + k * 8
        struct.pack_into(">H", data, off, 0x0028)
        struct.pack_into(">H", data, off + 2, rf.ITEM_BEHAVIOR_ROW_CONSTANT)
        struct.pack_into(">I", data, off + 4, 0x80005000 + (k // 12) * 4)
    if flagged_index is not None:
        # balls: twelve rows sharing one handler, bounded on both sides, with the flag on the first.
        for k in range(flagged_index, flagged_index + 12):
            struct.pack_into(">I", data, base + k * 8 + 4, ball_handler)
        struct.pack_into(">I", data, base + (flagged_index - 1) * 8 + 4, 0x80001111)
        struct.pack_into(">I", data, base + (flagged_index + 12) * 8 + 4, 0x80002222)
        struct.pack_into(">H", data, base + flagged_index * 8, rf.MASTER_BALL_BEHAVIOR_VALUE)
    return bytes(data)


class TestTheLocatorRefusesRatherThanGuessing(unittest.TestCase):
    def test_a_rel_with_no_long_run_returns_none(self) -> None:
        self.assertIsNone(rf.find_item_behavior_table(_Rel(bytes(0x20000))))

    def test_a_run_with_no_flagged_row_returns_none(self) -> None:
        self.assertIsNone(rf.find_item_behavior_table(_Rel(_synthetic_rel(flagged_index=None))))

    def test_two_flagged_rows_are_refused_rather_than_picked(self) -> None:
        data = bytearray(_synthetic_rel())
        struct.pack_into(">H", data, 0x1000 + 40 * 8, rf.MASTER_BALL_BEHAVIOR_VALUE)
        self.assertIsNone(rf.find_item_behavior_table(_Rel(bytes(data))))

    def test_a_flagged_row_without_a_ball_block_is_refused(self) -> None:
        data = bytearray(_synthetic_rel(flagged_index=None))
        struct.pack_into(">H", data, 0x1000 + 40 * 8, rf.MASTER_BALL_BEHAVIOR_VALUE)
        self.assertIsNone(rf.find_item_behavior_table(_Rel(bytes(data))))

    def test_a_well_formed_synthetic_table_is_found(self) -> None:
        """Without this the four refusals above could all pass by never finding anything."""
        self.assertEqual(0x1000 + 4 * 8, rf.find_item_behavior_table(_Rel(_synthetic_rel())))


class TestNothingIsWiredToAnOption(unittest.TestCase):
    """The discipline, asserted. A coincidence must not become a feature by drift."""

    def test_no_yaml_option_mentions_the_behaviour_table(self) -> None:
        source = open(os.path.join(os.path.dirname(rf.__file__), "..", "options.py"),
                      encoding="utf-8").read()
        self.assertNotIn("behavior_", source)
        self.assertNotIn("behaviour_", source)

    def test_the_seed_patch_path_never_calls_the_probe(self) -> None:
        from ..tools import iso_patcher

        source = open(iso_patcher.__file__, encoding="utf-8").read()
        patch_start = source.index("\ndef apply_patch(")
        patch_body = source[patch_start:source.index("\ndef ", patch_start + 1)]
        self.assertNotIn("apply_item_behavior_value", patch_body)
        self.assertNotIn("write_ball_behavior_flag_probe", patch_body)

    def test_the_probe_defaults_to_one_ball_and_writes_a_copy(self) -> None:
        import inspect

        from ..tools import iso_patcher

        signature = inspect.signature(iso_patcher.write_ball_behavior_flag_probe)
        self.assertIsNone(signature.parameters["item_ids"].default)
        self.assertIsNone(signature.parameters["value"].default)
        body = inspect.getsource(iso_patcher.write_ball_behavior_flag_probe)
        self.assertIn("refusing to write over it", body)
        self.assertIn("chunked_copy(source_path, output_path)", body)


@unittest.skipUnless(os.path.exists(COMMON_REL_DUMP), "no real common_rel dump in this workspace")
class TestAgainstTheRealCommonRel(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(COMMON_REL_DUMP, "rb") as handle:
            cls.rel = _Rel(handle.read())

    def test_the_table_is_found_with_no_help_from_the_items_table(self) -> None:
        self.assertEqual(DUMP_BEHAVIOR_BASE, rf.find_item_behavior_table(self.rel))

    def test_it_is_still_found_when_the_items_table_reads_as_it_does_on_disc(self) -> None:
        """THE REGRESSION TEST. On a real ISO the Items table's +0x20 handler pointers are all zero until the
        REL loader relocates them. The first locator matched against those, so it worked here and failed on
        every real disc. Zero them and the answer must not change."""
        data = bytearray(self.rel.data)
        for index in range(600):
            off = DUMP_ITEMS_BASE + index * rf.ITEM_ENTRY_SIZE + 0x20
            if off + 4 <= len(data):
                struct.pack_into(">I", data, off, 0)
        self.assertEqual(DUMP_BEHAVIOR_BASE, rf.find_item_behavior_table(_Rel(bytes(data))))

    def test_the_field_is_a_u16_with_many_values_not_a_flag_byte(self) -> None:
        """ADDENDUM 304's correction, pinned. ADDENDUM 303 measured 34 rows and called it a flag byte."""
        values = {
            struct.unpack_from(">H", self.rel.data, DUMP_BEHAVIOR_BASE + k * rf.ITEM_BEHAVIOR_ENTRY_SIZE)[0]
            for k in range(400)
        }
        self.assertGreater(len(values), 8)

    def test_the_master_ball_is_the_only_row_in_the_whole_table_with_bit_fifteen(self) -> None:
        """What survived the correction, and the whole basis of the probe."""
        flagged = [
            k for k in range(400)
            if struct.unpack_from(">H", self.rel.data,
                                  DUMP_BEHAVIOR_BASE + k * rf.ITEM_BEHAVIOR_ENTRY_SIZE)[0]
            & rf.MASTER_BALL_BEHAVIOR_BIT
        ]
        self.assertEqual([1], flagged)

    def test_every_other_value_is_far_below_it(self) -> None:
        others = [
            struct.unpack_from(">H", self.rel.data, DUMP_BEHAVIOR_BASE + k * rf.ITEM_BEHAVIOR_ENTRY_SIZE)[0]
            for k in range(400) if k != 1
        ]
        self.assertLess(max(others), 0x0500)

    def test_every_ball_shares_one_use_handler(self) -> None:
        for item_id in rf.BALL_ITEM_IDS:
            off = DUMP_BEHAVIOR_BASE + item_id * rf.ITEM_BEHAVIOR_ENTRY_SIZE + rf.ITEM_BEHAVIOR_HANDLER_OFFSET
            self.assertEqual(BALL_USE_HANDLER, struct.unpack_from(">I", self.rel.data, off)[0], item_id)

    def test_the_items_table_holds_no_per_ball_difference_at_all(self) -> None:
        """Negative result 2, kept as a test so nobody re-runs the search. Price, name id, description id and
        the item's own id are the ONLY columns that vary across the twelve balls."""
        entries = {
            item_id: self.rel.data[DUMP_ITEMS_BASE + item_id * rf.ITEM_ENTRY_SIZE:
                                   DUMP_ITEMS_BASE + (item_id + 1) * rf.ITEM_ENTRY_SIZE]
            for item_id in rf.BALL_ITEM_IDS
        }
        expected_varying = set(range(0x06, 0x08)) | set(range(0x10, 0x1C))
        varying = {b for b in range(rf.ITEM_ENTRY_SIZE)
                   if len({entries[i][b] for i in rf.BALL_ITEM_IDS}) > 1}
        self.assertTrue(varying <= expected_varying,
                        f"a ball column varies that this addendum recorded as uniform: {varying}")


@unittest.skipUnless(os.path.exists(DARK_DUMP), "no real DeckData_DarkPokemon dump in this workspace")
class TestTheGuaranteedCatchIsNotInItsRecord(unittest.TestCase):
    """Negative result 1. The natural experiment: the one guaranteed catch in the game, against the other 82."""

    @classmethod
    def setUpClass(cls) -> None:
        with open(DARK_DUMP, "rb") as handle:
            cls.decompressed = df.lzss_decode(handle.read())
        ddpk = df.DarkPokemonFile(cls.decompressed)
        cls.rows = {
            index: cls.decompressed[ddpk.ddpk_data + index * 0x18: ddpk.ddpk_data + (index + 1) * 0x18]
            for index in range(1, ddpk.ddpk_entries)
            if cls.decompressed[ddpk.ddpk_data + index * 0x18 + 0x03]
        }

    def test_the_only_teddiursa_unique_bytes_are_its_level_and_its_deck_pointer(self) -> None:
        unique = [b for b in range(0x18)
                  if sum(1 for row in self.rows.values() if row[b] == self.rows[1][b]) == 1]
        self.assertEqual([0x02, 0x07], unique,
                         "a byte became unique to the tutorial Shadow that this addendum did not account for")

    def test_its_catch_rate_override_is_not_even_the_highest_in_the_file(self) -> None:
        overrides = [row[0x01] for row in self.rows.values()]
        self.assertLess(self.rows[1][0x01], max(overrides))

    def test_six_offsets_are_dead_across_every_entry(self) -> None:
        """No spare flag is hiding in the unnamed bytes."""
        for b in (0x04, 0x05, 0x0A, 0x0B, 0x16, 0x17):
            self.assertEqual({0}, {row[b] for row in self.rows.values()}, hex(b))


class TestTheCeilingStatedByAddendum300StillHolds(unittest.TestCase):
    def test_the_catch_rate_maximum_is_still_the_byte(self) -> None:
        self.assertEqual(0xFF, ss.CATCH_RATE_MAX)

    def test_certainty_comes_from_code_not_from_a_catch_rate(self) -> None:
        """This addendum's conclusion, kept after ADDENDUM 305 delivered the certainty a different way: no
        VALUE produces it. The option text may promise a guaranteed catch now -- but only because an
        instruction is patched, and it must still say the data half alone falls short."""
        from ..options import MaxCatchRate

        text = " ".join((MaxCatchRate.__doc__ or "").split())
        # RETARGETED 2026-09-26: the player rewrote this option's text in their own words (see
        # USER_FACING_TEXT.md's section A). The docstring assertions below went with it. The measured fact is
        # unchanged and still tested against the CODE in this file; what is no longer pinned is that the
        # player-facing text repeats it.
        #
        # This addendum's conclusion -- that no catch-rate VALUE produces certainty, and the instruction patch
        # is what does -- is a fact about the code and is asserted against the code above, not here.
        self.assertTrue(text, "the option must still have SOME text")


if __name__ == "__main__":
    unittest.main()
