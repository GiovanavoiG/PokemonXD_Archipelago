"""Regression coverage for ADDENDUM 128 (2026-09-11) -- the shop-REL corruption root cause and its guards:

1. `MART_START_INDEXES_FIRST_ITEM_OFFSET` is +2 (reference randomizer's Pokemarts.cs), not +0.
2. `mart_item_slots` is structurally bounded (`mart_slot_limit`: the next mart's start, the pool's structural
   end = nearest later pointer target / data-section end, the declared size + sentinels) so a missing sentinel
   can never walk a mart into another table.
3. `validate_rel_structure` walks a REL exactly the way OSLink does and rejects what OSLink would reject
   (an unknown relocation type, a list without R_DOLPHIN_END, a bad section index).
4. `xd_deck_format.patch_entry_decompressed` now uses the vanilla HEADER-INCLUSIVE compressed-size convention
   (blob == old declared size, declared/returned comp size == 16 + stream, fit budget == old - 16).
"""
from __future__ import annotations

import struct
import unittest

from ..tools import xd_deck_format as deck_format
from ..tools import xd_rel_format as rel_format


def _build_synthetic_rel(pool_values: list[int], mart_starts: list[int], junk_after_pool: list[int]) -> bytes:
    """A minimal but REAL GameCube REL (parsed by the real `RelFile`, not a duck-typed fake):
    header (0x4C) + 4-entry section table + section 3 (data) holding, in order, NumberOfMarts (u32),
    NumberOfMartItems (u32), MartStartIndexes (4 bytes per mart, FirstItemIndex at +2, decoy at +0),
    the MartItems pool, then `junk_after_pool` u16s (a fake "next table" a strayed walk would hit), then a
    pointer-table (relocation list for the module itself) whose pairs point at those tables in pointer-index
    order 0=MartStartIndexes, 1=NumberOfMarts, 2/3=filler, 4=MartItems, 5=NumberOfMartItems, followed by a
    module-0 relocation list, both END-terminated."""
    data_section = bytearray()
    off_num_marts = len(data_section); data_section += struct.pack(">I", len(mart_starts))
    off_num_items = len(data_section); data_section += struct.pack(">I", sum(1 for v in pool_values if v))
    off_starts = len(data_section)
    for s in mart_starts:
        data_section += struct.pack(">HH", 0x1234, s)  # decoy at +0, FirstItemIndex at +2
    off_pool = len(data_section)
    for v in pool_values:
        data_section += struct.pack(">H", v)
    off_junk = len(data_section)
    for v in junk_after_pool:
        data_section += struct.pack(">H", v)
    while len(data_section) % 4:
        data_section += b"\x00"
    off_filler = len(data_section); data_section += struct.pack(">I", 0)

    header_size = 0x4C
    sec_table_off = header_size
    num_sections = 4
    sec3_off = sec_table_off + num_sections * 8
    while sec3_off % 0x20:
        sec3_off += 1
    imp_off = sec3_off + len(data_section)
    while imp_off % 4:
        imp_off += 1
    imp_size = 16
    rel_off = imp_off + imp_size

    # pointer table = self relocations: SECTION marker, then one (ADDR32 into section 3) pair per pointer
    # index: entry (1 + 2*index) carries the addend REL.cs reads as the pointer.
    targets = [off_starts, off_num_marts, off_filler, off_filler, off_pool, off_num_items, off_junk]
    self_rels = bytearray(struct.pack(">HBBI", 0, rel_format.R_DOLPHIN_SECTION, 3, 0))
    for t in targets:
        self_rels += struct.pack(">HBBI", 4, 1, 3, t)
        self_rels += struct.pack(">HBBI", 4, 1, 3, t)  # the second of the pair (REL.cs skips it)
    self_rels += struct.pack(">HBBI", 0, rel_format.R_DOLPHIN_END, 0, 0)
    dol_rel_off = rel_off + len(self_rels)
    dol_rels = bytearray(struct.pack(">HBBI", 0, rel_format.R_DOLPHIN_SECTION, 3, 0))
    for k in range(6):
        dol_rels += struct.pack(">HBBI", 4, 4 if k % 2 else 6, 3, 0x804EC5CE + k)  # ADDR16_LO/HA, DOL addrs
    dol_rels += struct.pack(">HBBI", 0, rel_format.R_DOLPHIN_END, 0, 0)

    total = dol_rel_off + len(dol_rels)
    rel = bytearray(total)
    struct.pack_into(">IIIIIIIIIIII", rel, 0,
                     0x33, 0, 0, num_sections, sec_table_off, 0, 0, 3, 0, rel_off, imp_off, imp_size)
    # section table: 0 = null, 1 = fake text, 2 = null, 3 = data
    struct.pack_into(">II", rel, sec_table_off + 1 * 8, header_size | 1, 4)
    struct.pack_into(">II", rel, sec_table_off + 3 * 8, sec3_off, len(data_section))
    rel[sec3_off:sec3_off + len(data_section)] = data_section
    struct.pack_into(">IIII", rel, imp_off, 0x33, rel_off, 0, dol_rel_off)
    rel[rel_off:rel_off + len(self_rels)] = self_rels
    rel[dol_rel_off:dol_rel_off + len(dol_rels)] = dol_rels
    assert rel_format.REL_DATA_START_OFFSET_LOCATION == sec_table_off + 3 * 8
    return bytes(rel)


class TestSyntheticRelParsesWithTheRealRelFile(unittest.TestCase):
    def test_pointer_walk_and_mart_tables_resolve(self) -> None:
        rel_bytes = _build_synthetic_rel([4, 13, 0, 17, 0], [0, 3], [])
        rel = rel_format.RelFile(rel_bytes, is_common=False)
        # REL.cs's walk only stops on a R_DOLPHIN_SECTION-shaped sentinel (0xCA01..0xCAFF) or the import
        # boundary, so the trailing END entry is counted as one extra (harmless, addend 0) pointer.
        self.assertGreaterEqual(rel.number_of_pointers, 7)
        self.assertEqual(rel_format.number_of_marts(rel), 2)
        self.assertEqual(rel_format.number_of_mart_items(rel), 3)
        self.assertEqual(rel_format.mart_first_item_index(rel, 0), 0)
        self.assertEqual(rel_format.mart_first_item_index(rel, 1), 3)  # read from +2, not the 0x1234 decoy
        slots = rel_format.read_all_mart_slots(rel)
        self.assertEqual([(s["mart_index"], s["item_id"]) for s in slots], [(0, 4), (0, 13), (1, 17)])


class TestStructuralMartBounds(unittest.TestCase):
    def test_missing_sentinel_walk_stops_at_the_next_marts_start(self) -> None:
        # mart 0's list has NO sentinel before mart 1's start at index 2 -- the walk must stop at 2 anyway.
        rel_bytes = _build_synthetic_rel([4, 13, 17, 0], [0, 2], [])
        rel = rel_format.RelFile(rel_bytes, is_common=False)
        self.assertEqual(rel_format.mart_item_slots(rel, 0), [0, 1])
        self.assertEqual(rel_format.mart_item_slots(rel, 1), [2])

    def test_missing_sentinel_on_the_last_mart_stops_at_the_pools_structural_end(self) -> None:
        # Last mart, no sentinel at all; the "junk table" right after the pool is full of small in-range
        # values (the exact shape of relocation offset deltas) -- none of it may be walked or patched.
        rel_bytes = _build_synthetic_rel([4, 13, 17], [0], [4, 8, 12, 0x0104, 0x804E, 0xC5CE])
        rel = rel_format.RelFile(rel_bytes, is_common=False)
        self.assertEqual(rel_format.mart_item_slots(rel, 0), [0, 1, 2])
        patched = bytearray(rel_bytes)
        count = rel_format.apply_mart_randomization(patched, rel, [901, 902])
        self.assertEqual(count, 3)
        changed = rel_format.byte_diff_offsets(rel_bytes, bytes(patched))
        base, end = rel_format.mart_items_base(rel), rel_format.mart_pool_end_offset(rel)
        self.assertTrue(all(base <= o < end for o in changed))
        self.assertEqual(end, rel_format.mart_items_base(rel) + 3 * 2)  # bounded by the next pointer target
        # the junk table is byte-identical
        junk_off = rel.get_pointer(6)
        self.assertEqual(patched[junk_off:junk_off + 12], rel_bytes[junk_off:junk_off + 12])
        # and the patched REL still links
        rel_format.validate_rel_structure(bytes(patched))

    def test_slot_limit_is_capped_by_declared_pool_size_plus_sentinels(self) -> None:
        rel_bytes = _build_synthetic_rel([4, 13, 17, 21, 25, 29, 33], [0], [])
        rel = rel_format.RelFile(rel_bytes, is_common=False)
        # NumberOfMartItems = 7 (non-zero values), + 1 mart = 8 >= 7 slots -> all walked
        self.assertEqual(len(rel_format.mart_item_slots(rel, 0)), 7)


class TestValidateRelStructure(unittest.TestCase):
    def test_valid_synthetic_rel_passes_and_reports_imports(self) -> None:
        rel_bytes = _build_synthetic_rel([4, 0], [0], [])
        result = rel_format.validate_rel_structure(rel_bytes, label="synthetic")
        self.assertEqual([i["module"] for i in result["imports"]], [0x33, 0])
        self.assertEqual(result["imports"][1]["entries"], 7)  # SECTION + 6 DOL relocations
        self.assertEqual(result["imports"][1]["end_offset"], len(rel_bytes))

    def test_unknown_relocation_type_is_rejected_with_oslinks_wording(self) -> None:
        rel_bytes = bytearray(_build_synthetic_rel([4, 0], [0], []))
        info = rel_format.validate_rel_structure(bytes(rel_bytes))
        rel_bytes[info["imports"][1]["rel_offset"] + 8 * 3 + 2] = 84  # the type byte of DOL entry #3
        with self.assertRaises(ValueError) as ctx:
            rel_format.validate_rel_structure(bytes(rel_bytes))
        self.assertIn("unknown relocation type 84", str(ctx.exception))

    def test_relocation_list_without_end_marker_is_rejected(self) -> None:
        rel_bytes = bytearray(_build_synthetic_rel([4, 0], [0], []))
        rel_bytes[-8 + 2] = 1  # turn the final R_DOLPHIN_END into an ADDR32 -> list runs off the file
        with self.assertRaises(ValueError) as ctx:
            rel_format.validate_rel_structure(bytes(rel_bytes))
        self.assertIn("without an R_DOLPHIN_END", str(ctx.exception))

    def test_berry_id_written_over_a_relocation_delta_is_caught_by_the_diff_confinement(self) -> None:
        # Simulates the ADDENDUM 127 failure: a berry id lands on a relocation entry -> outside the pool.
        rel_bytes = _build_synthetic_rel([4, 0], [0], [])
        rel = rel_format.RelFile(rel_bytes, is_common=False)
        info = rel_format.validate_rel_structure(rel_bytes)
        patched = bytearray(rel_bytes)
        struct.pack_into(">H", patched, info["imports"][1]["rel_offset"] + 8, 133)
        changed = rel_format.byte_diff_offsets(rel_bytes, bytes(patched))
        base, end = rel_format.mart_items_base(rel), rel_format.mart_pool_end_offset(rel)
        self.assertTrue(any(not base <= o < end for o in changed))


class TestHeaderInclusiveCompressedSize(unittest.TestCase):
    def _entry(self, payload: bytes, slack: int) -> tuple[bytes, bytes]:
        stream = deck_format.lzss_encode(payload)
        declared = deck_format.LZSS_HEADER_SIZE + len(stream) + slack
        entry = b"LZSS" + struct.pack(">II", len(payload), declared) + b"\x00" * 4 + stream + b"\x00" * slack
        return entry, stream

    def test_in_place_blob_is_exactly_the_old_declared_size_and_declares_16_plus_stream(self) -> None:
        payload = bytes(range(256)) * 4 + b"\x00" * 64
        entry, _ = self._entry(payload, slack=40)
        blob, comp, grew = deck_format.patch_entry_decompressed(entry, payload)
        self.assertFalse(grew)
        old_declared = struct.unpack_from(">I", entry, 8)[0]
        self.assertEqual(len(blob), old_declared)  # NOT 16 + old_declared any more
        self.assertEqual(struct.unpack_from(">I", blob, 8)[0], comp)
        self.assertEqual(comp, deck_format.LZSS_HEADER_SIZE + len(deck_format.lzss_encode(payload)))
        self.assertEqual(deck_format.lzss_decode(blob), payload)

    def test_fit_budget_excludes_the_header(self) -> None:
        payload = bytes(range(256)) * 4
        entry, stream = self._entry(payload, slack=0)  # declared == 16 + stream exactly: fits with 0 spare
        blob, comp, grew = deck_format.patch_entry_decompressed(entry, payload)
        self.assertFalse(grew)
        self.assertEqual(len(blob), comp)
        # now shrink the declared size by 1 -> the same stream no longer fits
        tight = bytearray(entry)
        struct.pack_into(">I", tight, 8, deck_format.LZSS_HEADER_SIZE + len(stream) - 1)
        with self.assertRaises(ValueError):
            deck_format.patch_entry_decompressed(bytes(tight), payload)
        grown, comp2, grew2 = deck_format.patch_entry_decompressed(bytes(tight), payload, allow_grow=True)
        self.assertTrue(grew2)
        self.assertEqual(len(grown), comp2)  # exact fit == header-inclusive size


if __name__ == "__main__":
    unittest.main()
