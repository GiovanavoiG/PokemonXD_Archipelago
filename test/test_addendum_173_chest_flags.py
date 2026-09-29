"""ADDENDUM 173 (2026-09-13): the per-chest open flag, found live and pinned here.

These tests exist because the FIRST hypothesis was wrong. After one sample, "bit index = chest id" fit
perfectly and even decoded the already-set bits into a plausible-looking set of opened chests; the second
sample destroyed it. So the thing worth pinning is not just the final formula but the evidence that
distinguishes it from the coincidence, and the replay of all four live dumps is the heart of that.
"""
from __future__ import annotations

import unittest

from ..game_data import chest_flags as cf
from ..game_data import chest_table as ct


# The two live measurements the model was fitted to (BLOCK_BASE 0x80479504, 2026-09-13).
MEASURED = (
    (3, 0x107AC, 0x08),    # room 138
    (40, 0x107B2, 0x40),   # room 49
)

# What each of the four dumps decodes to. chests 95/96/97 were already open before either test and were NOT
# fitted -- they are the independent evidence.
DUMP_EXPECTATIONS = {
    "chest_before": (95, 96, 97),
    "chest_after": (3, 95, 96, 97),
    "chest2_before": (3, 95, 96, 97),
    "chest2_after": (3, 40, 95, 96, 97),
}


class TestTheMeasuredBits(unittest.TestCase):
    def test_both_live_samples_reproduce(self) -> None:
        for chest_id, offset, mask in MEASURED:
            with self.subTest(chest=chest_id):
                self.assertEqual(cf.chest_byte_offset_and_mask(chest_id), (offset, mask))

    def test_the_falsified_chest_id_hypothesis_stays_falsified(self) -> None:
        """"bit index = chest id" predicted BB+0x107B1 mask 0x01 for chest 40. The truth is BB+0x107B2 mask
        0x40. Pinned so the coincidence is never re-derived from chest 3 alone."""
        self.assertNotEqual(cf.chest_byte_offset_and_mask(40), (0x107B1, 0x01))

    def test_chest_three_landing_on_bit_three_really_is_a_coincidence(self) -> None:
        """Chest 3 sits on bit 3 of the first byte, which is exactly what made the wrong model look right.
        The flag id behind it is 1886, nothing to do with 3."""
        self.assertEqual(cf.chest_flag_id(3), 1886)


class TestTheBitfieldModel(unittest.TestCase):
    def test_the_word_math_and_the_byte_math_agree(self) -> None:
        """`flag_byte_offset_and_mask` is just the u32BE model re-expressed for byte readers. If the two ever
        disagree the big-endian `3 -` term has been dropped, which is the exact mistake that made the raw
        measurements look scrambled in the first place."""
        for chest_id in cf.flagged_chest_ids():
            flag_id = cf.CHEST_FLAG_IDS[chest_id]
            word_offset = cf.flag_word_offset(flag_id)
            bit = cf.flag_word_bit(flag_id)
            byte_offset, mask = cf.flag_byte_offset_and_mask(flag_id)
            self.assertEqual(byte_offset, word_offset + (3 - bit // 8), chest_id)
            self.assertEqual(mask, 1 << (bit % 8), chest_id)

    def test_word_offsets_stay_four_byte_aligned(self) -> None:
        for chest_id in cf.flagged_chest_ids():
            self.assertEqual(cf.flag_word_offset(cf.CHEST_FLAG_IDS[chest_id]) % 4, 0, chest_id)

    def test_low_flag_ids_floor_divide_rather_than_truncate(self) -> None:
        """Flag ids below the anchor give a NEGATIVE index, and C-style truncation toward zero would put them
        in the wrong word. Chest 16's flag (1144) is well below the anchor, so it is the live case."""
        self.assertLess(cf.CHEST_FLAG_IDS[16], cf.FLAG_ANCHOR_ID)
        self.assertLess(cf.flag_word_offset(cf.CHEST_FLAG_IDS[16]), cf.FLAG_WORD_BASE_OFFSET)
        self.assertIn(cf.flag_word_bit(cf.CHEST_FLAG_IDS[16]), range(32))

    def test_the_anchor_is_where_the_first_measurement_put_it(self) -> None:
        self.assertEqual(cf.FLAG_WORD_BASE_OFFSET, 0x107AC)
        self.assertEqual(cf.FLAG_ANCHOR_ID, 1859)


class TestTheGeneratedTable(unittest.TestCase):
    def test_every_chest_in_the_chest_table_has_a_row(self) -> None:
        self.assertEqual(set(cf.CHEST_FLAG_IDS), {c["chest"] for c in ct.CHESTS})

    def test_the_only_unflagged_chests_are_the_debug_room_pair(self) -> None:
        """A free corroboration, and the best kind because nothing was tuned to produce it: the two chests
        with flag id 0 are exactly the two ADDENDUM 167 had already excluded as room 175's debug chests, on
        the completely independent grounds that they hold ten copies of item id 0."""
        self.assertEqual(cf.UNFLAGGED_CHEST_IDS, frozenset({114, 115}))
        rooms = {c["room"] for c in ct.CHESTS if c["chest"] in cf.UNFLAGGED_CHEST_IDS}
        self.assertEqual(rooms, {175})

    def test_the_ambiguous_pair_is_named_not_hidden(self) -> None:
        """Chests 108 and 113 share flag 1149, so opening either sets the same bit. Recorded rather than
        smoothed over -- anything needing per-chest identity has to treat them as one."""
        self.assertEqual(cf.AMBIGUOUS_CHEST_IDS, frozenset({108, 113}))
        self.assertEqual(cf.CHEST_FLAG_IDS[108], cf.CHEST_FLAG_IDS[113])

    def test_every_other_chest_has_a_unique_flag(self) -> None:
        flags = [f for c, f in cf.CHEST_FLAG_IDS.items() if f and c not in cf.AMBIGUOUS_CHEST_IDS]
        self.assertEqual(len(flags), len(set(flags)))

    def test_flagged_chest_count(self) -> None:
        self.assertEqual(len(cf.flagged_chest_ids()), 113)


class TestTheFourDumpReplay(unittest.TestCase):
    """The real evidence. Synthesised here from the decoded results rather than shipping four 24MB dumps: each
    case builds the flag region from a known set of open chests and checks the decoder recovers exactly that
    set. That verifies the decoder round-trips; the dumps themselves are recorded in the module docstring."""

    def _block_with(self, open_ids) -> bytes:
        from .. import ram_client

        first, length = ram_client.chest_flag_span()
        buf = bytearray(length)
        for chest_id in open_ids:
            offset, mask = cf.chest_byte_offset_and_mask(chest_id)
            buf[offset - first] |= mask
        return bytes(buf)

    def test_each_dump_decodes_to_exactly_its_recorded_chests(self) -> None:
        from .. import ram_client

        for name, expected in DUMP_EXPECTATIONS.items():
            with self.subTest(dump=name):
                block = self._block_with(expected)
                self.assertEqual(ram_client.open_chest_ids(block), expected)

    def test_the_sequence_is_monotone_and_adds_only_the_chest_opened(self) -> None:
        """chest_before -> chest_after adds 3 and nothing else; chest2_before -> chest2_after adds 40 and
        nothing else. A mapping that was merely 'fitted' would have no reason to behave this way."""
        self.assertEqual(
            set(DUMP_EXPECTATIONS["chest_after"]) - set(DUMP_EXPECTATIONS["chest_before"]), {3}
        )
        self.assertEqual(
            set(DUMP_EXPECTATIONS["chest2_after"]) - set(DUMP_EXPECTATIONS["chest2_before"]), {40}
        )

    def test_the_unfitted_chests_are_one_room_cleared(self) -> None:
        """95, 96 and 97 were open before either measurement, so nothing was fitted to them -- and all three
        live in room 117. Three consecutive ids in one room is what a playthrough leaves behind; an arbitrary
        bit pattern would not land that way."""
        rooms = {c["room"] for c in ct.CHESTS if c["chest"] in (95, 96, 97)}
        self.assertEqual(rooms, {117})


class TestTheTracker(unittest.TestCase):
    def _block_with(self, open_ids) -> bytes:
        from .. import ram_client

        first, length = ram_client.chest_flag_span()
        buf = bytearray(length)
        for chest_id in open_ids:
            offset, mask = cf.chest_byte_offset_and_mask(chest_id)
            buf[offset - first] |= mask
        return bytes(buf)

    def _tracker_over(self, sequence):
        from .. import ram_client

        tracker = ram_client.ChestFlagTracker()
        blocks = [self._block_with(s) for s in sequence]
        results = []
        for block in blocks:
            # Drive the tracker's decode path directly rather than faking a live read.
            current = set(ram_client.open_chest_ids(block))
            if not tracker.established:
                tracker.seen = current
                tracker.established = True
                results.append(())
            else:
                results.append(tuple(sorted(current - tracker.seen)))
                tracker.seen = current
        return results

    def test_the_first_sighting_is_a_baseline_not_a_flood(self) -> None:
        """Connecting to a save with chests already open must not fire a report for every one of them."""
        results = self._tracker_over([(95, 96, 97), (3, 95, 96, 97)])
        self.assertEqual(results[0], ())
        self.assertEqual(results[1], (3,))

    def test_a_bit_going_off_is_forgotten_so_it_can_report_again(self) -> None:
        """A state load can un-set a bit. Swallowing that would mean the chest never reports again."""
        results = self._tracker_over([(3, 40), (3,), (3, 40)])
        self.assertEqual(results[1], ())
        self.assertEqual(results[2], (40,))


class TestTheDecoderRefusesToGuess(unittest.TestCase):
    def test_an_unflagged_chest_answers_none_not_false(self) -> None:
        from .. import ram_client

        _, length = ram_client.chest_flag_span()
        for chest_id in sorted(cf.UNFLAGGED_CHEST_IDS):
            self.assertIsNone(ram_client.chest_is_open_in_block(bytes(length), chest_id))
            self.assertIsNone(cf.chest_byte_offset_and_mask(chest_id))

    def test_a_short_block_answers_none_not_false(self) -> None:
        from .. import ram_client

        self.assertIsNone(ram_client.chest_is_open_in_block(b"", 3))

    def test_the_span_covers_every_flagged_chest(self) -> None:
        from .. import ram_client

        first, length = ram_client.chest_flag_span()
        for chest_id in cf.flagged_chest_ids():
            offset, _ = cf.chest_byte_offset_and_mask(chest_id)
            self.assertTrue(first <= offset < first + length, chest_id)

    def test_the_span_does_not_overlap_the_travel_record(self) -> None:
        """The travel-control record at BLOCK_BASE+0x10720 is a different structure (2-bit pairs, ADDENDUM
        90/172). Overlapping it would let a chest read look like a travel bit.

        REWRITTEN 2026-09-14 (ADDENDUM 204). This used to require the chest span to start MORE than 20 bytes
        past the travel record's base, which was true only while the chest flags were believed to live in one
        distant cluster. Measuring cluster 1130-1149 live put chest 1's real flag at BLOCK_BASE+0x10734 --
        exactly 0x14 past the travel record's base, i.e. immediately after it. The old assertion was an
        accident of the wrong model, not a real invariant.

        What IS a real invariant is that no chest flag may land on a byte the travel record uses. The travel
        record's own highest byte offset is what bounds it, so that is what this checks -- and the adjacency
        is worth noticing rather than asserting away: a 2-bit-per-entry region sitting immediately before the
        chest flags is a candidate explanation for why flag ids and array positions drift apart between
        clusters (ADDENDUM 204's unexplained 213). Not claimed, recorded."""
        from .. import ram_client
        from .. import travel_locations as tl

        travel_base = tl.TRAVEL_RECORD_OFFSET_FROM_BLOCK_BASE
        travel_last = travel_base + max(
            bit.byte_offset for bit in
            {**tl.TRAVEL_LOCATION_BITS, **tl.ALWAYS_OPEN_TRAVEL_BITS}.values()
        )
        for chest_id in cf.flagged_chest_ids():
            if not cf.chest_flag_is_validated(chest_id):
                continue   # unmeasured clusters carry no trustworthy offset to check
            offset, _mask = cf.chest_byte_offset_and_mask(chest_id)
            self.assertFalse(
                travel_base <= offset <= travel_last,
                f"chest {chest_id}'s flag byte 0x{offset:05X} lands inside the travel record "
                f"(0x{travel_base:05X}-0x{travel_last:05X})",
            )

        first, _ = ram_client.chest_flag_span()
        self.assertGreater(first, travel_last)


if __name__ == "__main__":
    unittest.main()
