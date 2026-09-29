"""ADDENDUM 392 (2026-09-29) -- the Poke Spot level fields are fenced, and an unproven table is refused.

Player: "Another report of wild pokemon being level 0 at the wild spots. Investigate"

ADDENDUM 268 investigated the first one and killed four hypotheses outright: every vanilla slot reads min >= 10
in the live `common_rel`, the assignment only ever names the eleven real slots, Castform has no alternate-form
index, and all 386 dex numbers round-trip through the species index with zero failures. It closed asking for the
seed and the Poke Spot, and got another report instead.

WHAT 268 COULD NOT RULE OUT, and what nothing checked. `apply_pokespot_species` shares one
decompress/mutate/re-encode pass over `common_rel` with the chest writer, the item renamer, the experience
tables and the animation zeroing -- ADDENDUM 43 folded them together on purpose, because that file's LZSS
re-encode budget is finite. The move-status fields got a before/after fence for exactly this hazard in
ADDENDUM 381. The Poke Spot levels never got one.

TWO GUARDS, both already proved out on the move table:

  1. `verify_pokespot_table` -- the eleven vanilla level ranges are a strong fingerprint (nine slots at
     10-20/10-21/10-23, the two "all" slots at 10-10). If `pokespot_pool_base` resolves somewhere else on some
     build, the species write is REFUSED rather than made. That failure mode produces a level-0 encounter
     exactly: a species index below 256, written two bytes early, puts its zero high byte into MinLevel.
  2. `assert_pokespot_levels_unchanged` -- snapshot every level byte before the pass, prove it unchanged after.
     A stray write from ANY writer in that pass now stops the ISO instead of shipping in it.

Neither guard claims to have found the bug. What they do is make the next report diagnostic instead of
anecdotal: either the patcher refuses and names the reason, or the levels on disc are provably vanilla and the
fault is somewhere else entirely -- the client's reading, or the game's own handling of a reassigned species.
"""
from __future__ import annotations

import struct
import unittest

from ..game_data.pokespot_data import VANILLA_POKESPOT_SLOTS
from ..tools import xd_rel_format as rf


class _FakeRel:
    """A REL whose pointer table puts four Poke Spot pools back-to-back, as the real one does."""

    def __init__(self, ranges=None, counts=None, base: int = 0x100) -> None:
        ranges = ranges or rf.POKESPOT_VANILLA_LEVEL_RANGES
        self._counts = counts or {p: len(v) for p, v in ranges.items()}
        self._bases: "dict[str, int]" = {}
        cursor = base
        for pool in ("rock", "oasis", "cave", "all"):
            self._bases[pool] = cursor
            cursor += self._counts.get(pool, 0) * rf.POKESPOT_ENTRY_SIZE
        self.data = bytearray(cursor + 0x40)
        for pool, rows in ranges.items():
            for index, (low, high) in enumerate(rows):
                entry = self._bases[pool] + index * rf.POKESPOT_ENTRY_SIZE
                self.data[entry + rf.POKESPOT_MIN_LEVEL_OFFSET] = low
                self.data[entry + rf.POKESPOT_MAX_LEVEL_OFFSET] = high
                struct.pack_into(">H", self.data, entry + rf.POKESPOT_SPECIES_OFFSET, 27)

    # `pokespot_pool_base` / `pokespot_pool_count` go through these two.
    def get_pointer(self, index: int) -> int:
        for pool, (data_index, _count_index) in rf.POKESPOT_POOL_POINTERS.items():
            if data_index == index:
                return self._bases[pool]
        raise KeyError(index)

    def get_value_at_pointer(self, index: int) -> int:
        for pool, (_data_index, count_index) in rf.POKESPOT_POOL_POINTERS.items():
            if count_index == index:
                return self._counts.get(pool, 0)
        raise KeyError(index)


class TestTheRecordedRangesMatchTheProjectsOwnDecode(unittest.TestCase):
    def test_there_is_a_range_for_every_vanilla_slot(self) -> None:
        recorded = sum(len(v) for v in rf.POKESPOT_VANILLA_LEVEL_RANGES.values())
        self.assertEqual(len(VANILLA_POKESPOT_SLOTS), recorded)
        self.assertEqual(11, recorded)

    def test_the_pools_are_the_same_four(self) -> None:
        self.assertEqual(set(rf.POKESPOT_POOL_POINTERS), set(rf.POKESPOT_VANILLA_LEVEL_RANGES))
        self.assertEqual({s.pool for s in VANILLA_POKESPOT_SLOTS}, set(rf.POKESPOT_VANILLA_LEVEL_RANGES))

    def test_every_slot_count_agrees_with_pokespot_data(self) -> None:
        from collections import Counter
        counted = Counter(s.pool for s in VANILLA_POKESPOT_SLOTS)
        for pool, rows in rf.POKESPOT_VANILLA_LEVEL_RANGES.items():
            self.assertEqual(counted[pool], len(rows), pool)

    def test_no_recorded_range_is_anywhere_near_zero(self) -> None:
        """The whole point. If this table ever contained a zero, the bug would be in the data, not a write."""
        for pool, rows in rf.POKESPOT_VANILLA_LEVEL_RANGES.items():
            for low, high in rows:
                self.assertGreaterEqual(low, rf.POKESPOT_MIN_PLAUSIBLE_LEVEL, pool)
                self.assertGreaterEqual(high, low, pool)

    def test_it_is_the_decode_addendum_268_published(self) -> None:
        """Pinned literally, because these numbers are evidence: they were read off the live `common_rel` and
        cross-checked against two independent vanilla rosters."""
        self.assertEqual(((10, 23), (10, 20), (10, 20)), rf.POKESPOT_VANILLA_LEVEL_RANGES["rock"])
        self.assertEqual(((10, 10), (10, 10)), rf.POKESPOT_VANILLA_LEVEL_RANGES["all"])


class TestTheTableIsVerifiedBeforeAnythingIsWritten(unittest.TestCase):
    def test_a_real_looking_table_verifies(self) -> None:
        self.assertTrue(rf.verify_pokespot_table(_FakeRel()))

    def test_one_wrong_level_byte_fails_it(self) -> None:
        rel = _FakeRel()
        base = rel.get_pointer(rf.POKESPOT_POOL_POINTERS["cave"][0])
        rel.data[base + rf.POKESPOT_MIN_LEVEL_OFFSET] = 9
        self.assertFalse(rf.verify_pokespot_table(rel))

    def test_a_zero_min_level_fails_it(self) -> None:
        """The reported symptom, as a rejection: a table already holding a zero is not one to write into."""
        rel = _FakeRel()
        base = rel.get_pointer(rf.POKESPOT_POOL_POINTERS["rock"][0])
        rel.data[base + rf.POKESPOT_MIN_LEVEL_OFFSET] = 0
        self.assertFalse(rf.verify_pokespot_table(rel))

    def test_a_pool_with_the_wrong_count_fails_it(self) -> None:
        """Writing slot 2 of a pool this build says has one entry is ADDENDUM 268's out-of-bounds case."""
        self.assertFalse(rf.verify_pokespot_table(_FakeRel(counts={"rock": 1, "oasis": 3, "cave": 3, "all": 2})))

    def test_a_table_of_zeros_fails_it(self) -> None:
        """What a mis-resolved pointer most often lands on, and it must never look acceptable."""
        zeros = {pool: tuple((0, 0) for _ in rows)
                 for pool, rows in rf.POKESPOT_VANILLA_LEVEL_RANGES.items()}
        self.assertFalse(rf.verify_pokespot_table(_FakeRel(ranges=zeros)))


class TestTheLevelsAreFencedAcrossThePass(unittest.TestCase):
    def setUp(self) -> None:
        self.rel = _FakeRel()
        self.buffer = bytearray(self.rel.data)

    def test_a_species_write_moves_no_level_byte(self) -> None:
        """The write this fence sits around: species only, every level untouched."""
        before = rf.pokespot_level_fields(self.buffer, self.rel)
        rf.apply_pokespot_species(self.buffer, self.rel, {"rock:0": 133, "cave:2": 200, "all:1": 25})
        rf.assert_pokespot_levels_unchanged(before, rf.pokespot_level_fields(self.buffer, self.rel))

    def test_the_species_really_did_change(self) -> None:
        """ADDENDA 247/298: a fence whose condition can never bind is dead weight. Prove the write happens."""
        rf.apply_pokespot_species(self.buffer, self.rel, {"rock:0": 133})
        offset = rf.pokespot_species_offset(self.rel, "rock", 0)
        self.assertEqual(133, struct.unpack_from(">H", self.buffer, offset)[0])

    def test_a_stray_write_over_a_level_is_caught(self) -> None:
        before = rf.pokespot_level_fields(self.buffer, self.rel)
        base = self.rel.get_pointer(rf.POKESPOT_POOL_POINTERS["oasis"][0])
        self.buffer[base + rf.POKESPOT_MIN_LEVEL_OFFSET] = 0
        with self.assertRaises(AssertionError) as caught:
            rf.assert_pokespot_levels_unchanged(before, rf.pokespot_level_fields(self.buffer, self.rel))
        self.assertIn("level-0", str(caught.exception))
        self.assertIn("NOT written", str(caught.exception))

    def test_the_snapshot_covers_every_slot(self) -> None:
        self.assertEqual(2 * len(VANILLA_POKESPOT_SLOTS),
                         len(rf.pokespot_level_fields(self.buffer, self.rel)))

    def test_a_species_written_two_bytes_early_would_be_caught(self) -> None:
        """The concrete mechanism this addendum is built around: a species index below 256 landing on the level
        bytes puts its zero high byte into MinLevel. Simulated directly, because if the fence did not catch
        this it would be catching nothing worth catching."""
        before = rf.pokespot_level_fields(self.buffer, self.rel)
        base = self.rel.get_pointer(rf.POKESPOT_POOL_POINTERS["rock"][0])
        struct.pack_into(">H", self.buffer, base + rf.POKESPOT_MIN_LEVEL_OFFSET, 133)
        self.assertEqual(0, self.buffer[base + rf.POKESPOT_MIN_LEVEL_OFFSET], "the symptom, reproduced")
        with self.assertRaises(AssertionError):
            rf.assert_pokespot_levels_unchanged(before, rf.pokespot_level_fields(self.buffer, self.rel))


class TestTheReportNamesTheSlot(unittest.TestCase):
    def test_it_lists_every_slot_with_its_expected_range(self) -> None:
        rel = _FakeRel()
        rows = rf.pokespot_level_report(bytearray(rel.data), rel)
        self.assertEqual(len(VANILLA_POKESPOT_SLOTS), len(rows))
        for row in rows:
            self.assertEqual(row["expected"], (row["min_level"], row["max_level"]), row)

    def test_a_bad_slot_is_identifiable(self) -> None:
        rel = _FakeRel()
        buffer = bytearray(rel.data)
        base = rel.get_pointer(rf.POKESPOT_POOL_POINTERS["cave"][0])
        buffer[base + rf.POKESPOT_ENTRY_SIZE + rf.POKESPOT_MIN_LEVEL_OFFSET] = 0
        bad = [r for r in rf.pokespot_level_report(buffer, rel)
               if r["expected"] != (r["min_level"], r["max_level"])]
        self.assertEqual(1, len(bad))
        self.assertEqual(("cave", 1), (bad[0]["pool"], bad[0]["slot_index"]))


class TestThePatcherUsesBoth(unittest.TestCase):
    """Structural: the pass needs a real ISO to reach."""

    def setUp(self) -> None:
        import pathlib
        self.source = (pathlib.Path(__file__).resolve().parent.parent
                       / "tools" / "iso_patcher.py").read_text(encoding="utf-8")

    def test_it_verifies_before_writing(self) -> None:
        self.assertIn("rel_format.verify_pokespot_table(rel)", self.source)
        self.assertIn("pokespot_refused", self.source)

    def test_it_snapshots_before_and_asserts_after(self) -> None:
        self.assertIn("pokespot_levels_before = rel_format.pokespot_level_fields(rel_bytes, rel)", self.source)
        self.assertIn("rel_format.assert_pokespot_levels_unchanged(", self.source)

    def test_the_snapshot_is_taken_before_any_writer_runs(self) -> None:
        snapshot = self.source.index("pokespot_levels_before = rel_format.pokespot_level_fields")
        first_write = self.source.index("rel_format.apply_chest_dummy_item(")
        self.assertLess(snapshot, first_write)

    def test_the_assertion_happens_after_every_writer(self) -> None:
        assertion = self.source.index("rel_format.assert_pokespot_levels_unchanged(")
        for writer in ("rel_format.apply_chest_dummy_item(",
                       "rel_format.apply_pokespot_species(\n"):
            self.assertLess(self.source.index(writer), assertion, writer)

    def test_a_refusal_is_reported_rather_than_silent(self) -> None:
        self.assertIn("Poke Spot species reassignment NOT applied", self.source)


if __name__ == "__main__":
    unittest.main()
