"""Consolidated regression coverage for the REL-format / AP-Item-rename work: ADDENDUM 112 (iso_patcher's
`_find_rel_entry` base-name fallback), 113/114 (the in-game "AP Item" rename, plus the ADDENDUM 121/123/124/125
follow-ups to it), 115 (RelFile's bounds-checked pointer-table walk), 119 (`scan_bytes_for_item_id_runs`) and
126 (`parse_fsys_all`). Replaces test_addendum_{112,114,115,119,126}_*.py, which shared the same FakeRel /
synthetic-REL scaffolding and the same subject matter.

Everything here guards code that writes to (or decides where to write in) a real game ISO, so the merge was
deliberately conservative: every "skipped safely / not written" path of `apply_item_name_rename` and its text-
search fallback, every bounds check, every 20-bit masking rule, and every regression whose comment records a
live player report is preserved verbatim.

WHAT WAS DROPPED (64 -> 44 tests), and why:
  * `test_expected_names_match_case_and_trailing_space_insensitively` (114) -- an exact duplicate of the text-
    search class's `test_match_is_case_and_trailing_space_insensitive`: same fixture, same item id, same
    `expected_names={11: "  bluk berry  "}` call. The surviving copy asserts strictly more (it also pins
    `resolved_via`).
  * `test_run_length_exactly_at_the_minimum_is_kept` (119) -- exact duplicate of
    `test_finds_a_single_sentinel_terminated_run`'s data and arguments, asserting a subset of its assertions.
  * `test_display_text_is_ap_item` (114) -- asserted only that a constant equals a literal; the assertion
    itself is folded into the surviving `AP_ITEM_RENAME_TARGET_NAMES` test.
  * Near-identical variations merged into one test each, keeping both reasons: the three
    `item_table_index` threshold branches; the two `check_item_struct_resolution_sample` "reason" paths (now
    folded into the never-raises batch test) and its match/mismatch pair; `find_candidate_item_string_tables`'s
    two negative cases and its never-raises scan; `_find_rel_entry`'s two KeyError cases; RelFile's default and
    custom `label`; `scan_bytes_for_item_id_runs`'s single-run/multi-run/leading-zero cases, its explicit and
    defaulted `min_run_length`, and its empty-input/odd-trailing-byte/no-mutation trio.

WHY THIS DOESN'T CONSTRUCT A REAL `RelFile` FOR THE STRING-TABLE TESTS: same reasoning as
test_addendum_111_mart_rel_helpers.py's own FakeRel -- no synthetic/fixture REL binary exists anywhere in this
codebase, and every helper under test only ever calls `rel.data`/`rel.get_pointer()`/`rel.get_value_at_pointer()`,
so a minimal duck-typed fake exercises the real offset arithmetic/decode logic just as faithfully without
needing a real REL header. (The ADDENDUM 115 bounds-check tests below are the exception: they construct a real
`RelFile`, because the header walk itself is what they test.)"""
from __future__ import annotations

import struct
import unittest

from .. import items
from ..tools import iso_patcher
from ..tools import xd_rel_format as rel_format
from ..tools.iso_patcher import _find_rel_entry


# ---------------------------------------------------------------------------------------------------------
# Shared scaffolding
# ---------------------------------------------------------------------------------------------------------


class FakeRel:
    """Duck-typed stand-in for xd_rel_format.RelFile -- see module docstring for why this is used instead of a
    real one. `pointers`/`values_at_pointer` are plain {pointer_table_index: result} dicts."""

    def __init__(self, data: bytes, pointers: dict[int, int], values_at_pointer: dict[int, int]) -> None:
        self.data = data
        self._pointers = pointers
        self._values = values_at_pointer

    def get_pointer(self, index: int) -> int:
        return self._pointers[index]

    def get_value_at_pointer(self, index: int) -> int:
        return self._values[index]


def _utf16be_str(s: str) -> bytes:
    """A normal, cleanly-terminated string-table entry: UTF-16BE text + a 0x0000 terminator."""
    return s.encode("utf-16-be") + b"\x00\x00"


def _u16s(*values: int) -> bytes:
    """A big-endian u16 blob -- the shape `scan_bytes_for_item_id_runs` walks."""
    return b"".join(struct.pack(">H", v) for v in values)


STRING_TABLE_BASE = 0x1000
ITEMS_TABLE_BASE = 0x2000

RAZZ_BERRY = "Razz Berry"  # 10 chars -> 22 bytes total (20 text + 2 terminator)
BLUK_BERRY = "Bluk Berry"  # 10 chars -> 22 bytes total
CUT = "Cut"  # 3 chars -> 8 bytes total (6 text + 2 terminator) -- too short to hold "AP Item"


def _build_synthetic_common_rel(
    xd_number_of_items: int,
    string_entries: "list[tuple[int, bytes]]",
    item_entries: "dict[int, int]",
) -> FakeRel:
    """Builds a synthetic `common_rel.rel`-shaped buffer with a real CommonRelStringTable (pointer index 116)
    and a real Items table (pointer index 70), per xd_rel_format.py's own section docstring for both.

    `string_entries`: `[(masked_or_raw_id, raw_string_bytes_including_terminator_or_escape_sentinel), ...]` --
    packed in order starting right after the record array. Each entry's stored offset is relative to the
    TABLE'S OWN HEADER START (ADDENDUM 125 -- verified against the player's real REL bytes: the first string's
    stored offset is exactly `0x10 + entry_count * 8`), i.e. `header_size + records_size + running total of
    every earlier entry's byte length` -- mirrors how the real table is laid out.
    `item_entries`: `{items_table_index: name_id_to_store}` -- ALREADY the real array index (post-remap, if
    any) within the Items table; this builder writes `name_id_to_store` directly into that index's NameID
    field, unmasked (masking happens on read, in `item_name_id`/`string_table_id_offsets`, not on write)."""
    header_size = rel_format.STRING_TABLE_HEADER_SIZE
    entry_size = rel_format.STRING_TABLE_ENTRY_SIZE
    count = len(string_entries)
    records_size = count * entry_size

    data_blob = bytearray()
    records: list[tuple[int, int]] = []
    for raw_id, raw_bytes in string_entries:
        records.append((raw_id, header_size + records_size + len(data_blob)))  # offset from the table header
        data_blob += raw_bytes

    string_table_total_size = header_size + records_size + len(data_blob)
    max_item_index = max(item_entries.keys()) if item_entries else 0
    items_table_size = (max_item_index + 1) * rel_format.ITEM_ENTRY_SIZE

    total_size = max(STRING_TABLE_BASE + string_table_total_size, ITEMS_TABLE_BASE + items_table_size) + 0x100
    data = bytearray(total_size)

    struct.pack_into(">H", data, STRING_TABLE_BASE + rel_format.STRING_TABLE_ENTRY_COUNT_OFFSET, count)
    for i, (raw_id, off_in_region) in enumerate(records):
        rec_off = STRING_TABLE_BASE + header_size + i * entry_size
        struct.pack_into(">I", data, rec_off, raw_id)
        struct.pack_into(">I", data, rec_off + 4, off_in_region)
    data_region_abs = STRING_TABLE_BASE + header_size + records_size
    data[data_region_abs:data_region_abs + len(data_blob)] = data_blob

    for index, name_id in item_entries.items():
        off = ITEMS_TABLE_BASE + index * rel_format.ITEM_ENTRY_SIZE + rel_format.ITEM_NAME_ID_OFFSET
        struct.pack_into(">I", data, off, name_id)

    return FakeRel(
        bytes(data),
        pointers={
            rel_format.COMMON_REL_STRING_TABLE_POINTER: STRING_TABLE_BASE - rel_format.STRING_TABLE_BLOB_OFFSET,
            rel_format.ITEMS_TABLE_POINTER: ITEMS_TABLE_BASE,
        },
        values_at_pointer={rel_format.XD_NUMBER_OF_ITEMS_POINTER: xd_number_of_items},
    )


def _mk_rel() -> FakeRel:
    """Shared fixture for most tests below:
      - NameID 5 -> "Razz Berry" (renameable, plenty of room)
      - NameID 6 -> "Bluk Berry" (renameable, plenty of room)
      - NameID 7 -> an unterminated escape sequence ("Foo" + 0xFFFF, no clean terminator)
      - NameID 8 -> "Cut" (renameable in principle, but too short a budget for "AP Item")
      XDNumberOfItems (the remap threshold) = 100.
      - item_id 10 -> index 10 (direct, <= threshold) -> NameID 5
      - item_id 11 -> index 11 (direct)                -> NameID 6
      - item_id 12 -> index 12 (direct)                -> NameID 8 (too-short case)
      - item_id 13 -> index 13 (direct)                -> NameID 42 (NOT present in the string table)
      - item_id 14 -> index 14 (direct)                -> NameID 0x900005 (masking check -> masked id 5)
      - item_id 200 -> threshold(100) < 200 < 0x251 -> remapped index 50 -> NameID 7 (escape case)
      - item_id 999 -> not < 0x251 (593) -> direct index 999 -> WAY out of this fixture's allocated Items
        table (only sized up to index 50) -> a real struct.error when read, exercising the defensive
        "could not resolve NameID" except-and-skip path."""
    string_entries = [
        (5, _utf16be_str(RAZZ_BERRY)),
        (6, _utf16be_str(BLUK_BERRY)),
        (7, "Foo".encode("utf-16-be") + b"\xff\xff"),
        (8, _utf16be_str(CUT)),
    ]
    item_entries = {10: 5, 11: 6, 12: 8, 13: 42, 14: 0x900005, 50: 7}
    return _build_synthetic_common_rel(
        xd_number_of_items=100, string_entries=string_entries, item_entries=item_entries
    )


def _mk_rel_with_duplicate_text() -> FakeRel:
    """Two DIFFERENT NameIDs both decoding to the exact same text ("Duplicate Item") -- exercises the ADDENDUM
    121 text search's ambiguity-detection path: when more than one string-table entry matches the expected text
    exactly, which one is really "this item's" name can't be told apart by text content alone, so the item must
    be skipped rather than guessing."""
    string_entries = [
        (30, _utf16be_str("Duplicate Item")),
        (31, _utf16be_str("Duplicate Item")),
    ]
    return _build_synthetic_common_rel(xd_number_of_items=100, string_entries=string_entries, item_entries={})


def _build_rel_with_second_string_table() -> FakeRel:
    """Two SEPARATE string tables in one synthetic REL: pointer 116 (species/move-shaped, no item names --
    mirrors the real confirmed table found live, ADDENDUM 122) and pointer 200 (a hypothetical ITEM name table,
    holding "Potion" and "Master Ball") -- exercises `find_candidate_item_string_tables`'s ability to scan
    every pointer index and correctly single out the one that actually contains known item names, ignoring
    every other (non-string-table, or wrong-category) pointer index."""
    move_rel = _build_synthetic_common_rel(
        xd_number_of_items=100,
        string_entries=[(1, _utf16be_str("Substitute")), (2, _utf16be_str("Nightmare"))],
        item_entries={},
    )
    data = bytearray(move_rel.data)

    item_table_base_addr = len(data) + 0x100
    header_size = rel_format.STRING_TABLE_HEADER_SIZE
    entry_size = rel_format.STRING_TABLE_ENTRY_SIZE
    item_string_entries = [(50, _utf16be_str("Potion")), (51, _utf16be_str("Master Ball"))]
    count = len(item_string_entries)
    records_size = count * entry_size
    data_blob = bytearray()
    records: list[tuple[int, int]] = []
    for raw_id, raw_bytes in item_string_entries:
        records.append((raw_id, header_size + records_size + len(data_blob)))  # offset from the table header
        data_blob += raw_bytes
    table_total = header_size + records_size + len(data_blob)
    data += bytearray((item_table_base_addr - len(data)) + table_total + 0x10)

    struct.pack_into(">H", data, item_table_base_addr + rel_format.STRING_TABLE_ENTRY_COUNT_OFFSET, count)
    for i, (raw_id, off_in_region) in enumerate(records):
        rec_off = item_table_base_addr + header_size + i * entry_size
        struct.pack_into(">I", data, rec_off, raw_id)
        struct.pack_into(">I", data, rec_off + 4, off_in_region)
    data_region_abs = item_table_base_addr + header_size + records_size
    data[data_region_abs:data_region_abs + len(data_blob)] = data_blob

    pointers = dict(move_rel._pointers)
    pointers[200] = item_table_base_addr - rel_format.STRING_TABLE_BLOB_OFFSET
    fake = FakeRel(bytes(data), pointers, move_rel._values)
    fake.number_of_pointers = 201  # scan range must reach pointer index 200
    return fake


def _build_minimal_valid_rel(is_common: bool = False) -> bytes:
    """ADDENDUM 115. The smallest possible buffer that satisfies RelFile.__init__'s real header walk:
    pointer_start and pointer_header both point at in-bounds, self-consistent locations, and
    pointer_end == first_pointer so the pointer-count loop body never has to run (number_of_pointers == 0) --
    a minimal, deliberately trivial, but genuinely VALID REL header, not a fixture that happens to dodge the
    bounds check by accident."""
    data_start_off = (
        rel_format.COMMON_REL_DATA_START_OFFSET_LOCATION if is_common else rel_format.REL_DATA_START_OFFSET_LOCATION
    )
    data = bytearray(0x80)
    struct.pack_into(">I", data, data_start_off, 0)  # data_start = 0
    struct.pack_into(">I", data, rel_format.REL_POINTERS_START_OFFSET_LOCATION, 0x40)  # pointer_start = 0x40
    struct.pack_into(">I", data, rel_format.REL_POINTERS_HEADER_POINTER_1_OFFSET, 0x40)  # pointer_header = 0x40
    first_pointer = 0x40 + rel_format.REL_POINTERS_FIRST_POINTER_OFFSET  # 0x48
    struct.pack_into(">I", data, 0x40 + 0xC, first_pointer)  # pointer_end == first_pointer -> loop never runs
    return bytes(data)


def _build_undersized_garbage_rel() -> bytes:
    """ADDENDUM 115, reproducing the REAL player report exactly: a 544-byte container (far too small to be real
    REL pointer-table data) with a garbage "pointer_header" value at the real REL.cs offset that dereferences
    WAY out of bounds ("unpack_from requires a buffer of at least 369098756 bytes ... actual buffer size is
    544")."""
    data = bytearray(544)
    struct.pack_into(">I", data, rel_format.REL_POINTERS_HEADER_POINTER_1_OFFSET, 369098740)
    return bytes(data)


# The real `pocket_menu.fsys` entry list from the player's report (2026-09-11, ADDENDUM 112), as a minimal
# fixture -- only the names matter for `_find_rel_entry`, so each entry's "value" is an unused placeholder dict.
REAL_POCKET_MENU_ENTRIES: dict[str, dict] = {
    name: {}
    for name in [
        "pocket_menu",
        "temp_csr",
        "uv_pkm_panel_00",
        "uv_pkm_panel_01",
        "uv_pkm_panel_02",
        "uv_pkm_panel_03",
        "uv_pkm_panel_04",
        "uv_pkm_panel_05",
        "uv_pkm_ribbon_00",
        "uv_pkm_status_00",
        "uv_pkm_status_01",
        "uv_pkm_status_02",
        "uv_str_item_00",
    ]
}


def _build_fsys_with_duplicate_base_names() -> bytes:
    """ADDENDUM 126. A tiny synthetic FSYS with two "pocket_menu" entries (one with a full "pocket_menu.rel"
    name at record +0x1C, one without) -- the real shape that made `parse_fsys`, which keys by extension-less
    base name, silently drop the mart REL in favour of its same-named UI-data twin."""
    fsys = bytearray(0x400)
    fsys[0:4] = b"FSYS"
    struct.pack_into(">I", fsys, iso_patcher.FSYS_ENTRY_COUNT_OFF, 2)
    # names
    name_a_off = 0x300
    fsys[name_a_off:name_a_off + 12] = b"pocket_menu\x00"
    full_a_off = 0x320
    fsys[full_a_off:full_a_off + 16] = b"pocket_menu.rel\x00"
    name_b_off = 0x340
    fsys[name_b_off:name_b_off + 12] = b"pocket_menu\x00"
    # records (0x70 apart)
    rec_a = 0x80
    rec_b = 0x80 + 0x70
    struct.pack_into(">I", fsys, iso_patcher.FSYS_OFFSET_ARRAY_OFF, rec_a)
    struct.pack_into(">I", fsys, iso_patcher.FSYS_OFFSET_ARRAY_OFF + 4, rec_b)
    for rec, data_off, decomp, comp, name_off, full_off, fmt in (
        (rec_a, 0x200, 544, 112, name_a_off, full_a_off, 2),
        (rec_b, 0x280, 544, 112, name_b_off, 0, 9),
    ):
        fsys[rec + iso_patcher.FSYS_RECORD_FILE_FORMAT_OFF] = fmt
        struct.pack_into(">I", fsys, rec + iso_patcher.FSYS_RECORD_DATA_OFF, data_off)
        struct.pack_into(">I", fsys, rec + iso_patcher.FSYS_RECORD_DECOMP_SIZE_OFF, decomp)
        struct.pack_into(">I", fsys, rec + iso_patcher.FSYS_RECORD_COMP_SIZE_OFF, comp)
        struct.pack_into(">I", fsys, rec + iso_patcher.FSYS_RECORD_FULL_NAME_OFF, full_off)
        struct.pack_into(">I", fsys, rec + iso_patcher.FSYS_RECORD_NAME_OFF, name_off)
    return bytes(fsys)


# ---------------------------------------------------------------------------------------------------------
# ADDENDUM 124 -- read-only struct-resolution diagnostics
# ---------------------------------------------------------------------------------------------------------


class TestCheckItemStructResolutionSample(unittest.TestCase):
    """ADDENDUM 124 (2026-09-11) -- `check_item_struct_resolution_sample` applies the ORIGINAL, untouched
    item-table struct resolution (no search involved) against a batch of items, to learn whether it works for
    items OTHER than the berries that started this investigation. Uses `_mk_rel()`'s existing fixture (item 10
    -> NameID 5 "Razz Berry", item 11 -> NameID 6 "Bluk Berry", item 13 -> NameID 42 which isn't in the string
    table, item 999 -> out of this fixture's allocated Items-table bounds)."""

    def test_reports_match_and_mismatch_against_the_default_resolution(self) -> None:
        rel = _mk_rel()
        self.assertEqual(
            rel_format.check_item_struct_resolution_sample(rel, {10: RAZZ_BERRY}),
            [{"item_id": 10, "expected": RAZZ_BERRY, "found": RAZZ_BERRY, "match": True}],
        )
        # The same item, asked for under a different expected name: the resolution still FINDS "Razz Berry",
        # and the mismatch is what gets reported -- the diagnostic never rewrites its own expectation.
        mismatched = rel_format.check_item_struct_resolution_sample(rel, {10: "Some Other Name"})
        self.assertEqual(len(mismatched), 1)
        self.assertFalse(mismatched[0]["match"])
        self.assertEqual(mismatched[0]["found"], RAZZ_BERRY)

    def test_reports_a_reason_for_each_failure_mode_and_never_raises_across_a_mixed_batch(self) -> None:
        # Two distinct failure modes in one batch, alongside two good items: item 13's NameID (42) simply isn't
        # in the string table, and item 999 can't have a NameID read for it at all (out of the fixture's Items
        # table). Both must come back as a reported `reason` with `found` None -- and, above all, the whole
        # mixed batch must complete without raising.
        rel = _mk_rel()
        try:
            results = rel_format.check_item_struct_resolution_sample(
                rel, {10: RAZZ_BERRY, 11: BLUK_BERRY, 13: "Whatever", 999: "Whatever"}
            )
        except Exception as exc:  # pragma: no cover -- this is exactly what the test guards against
            self.fail(f"check_item_struct_resolution_sample raised unexpectedly: {exc}")
        self.assertEqual(len(results), 4)
        self.assertEqual(sum(1 for r in results if r["match"]), 2)
        by_id = {r["item_id"]: r for r in results}
        self.assertIsNone(by_id[13]["found"])
        self.assertIn("not found", by_id[13]["reason"])
        self.assertIsNone(by_id[999]["found"])
        self.assertIn("could not resolve NameID", by_id[999]["reason"])


class TestFindCandidateItemStringTables(unittest.TestCase):
    """ADDENDUM 123 (2026-09-11, player report: a live dump of the confirmed pointer-116 string table --
    1931 entries -- had zero matches for any of 27 known real item names, but plenty of recognizable move/
    species name fragments) -- `find_candidate_item_string_tables` scans every pointer index for one that
    actually holds known item names, instead of assuming items share pointer 116's table."""

    def test_finds_the_pointer_index_holding_real_item_names(self) -> None:
        # Also the never-raises guard: every pointer index in [0, 201) is tried, and most resolve to garbage or
        # to missing pointers entirely -- the scan must walk all of them cleanly to reach 200 at all.
        rel = _build_rel_with_second_string_table()
        try:
            results = rel_format.find_candidate_item_string_tables(
                rel, known_item_names={"Potion", "Master Ball"}
            )
        except Exception as exc:  # pragma: no cover -- this is exactly what the test guards against
            self.fail(f"find_candidate_item_string_tables raised unexpectedly: {exc}")
        pointer_indices = {r["pointer_index"] for r in results}
        self.assertIn(200, pointer_indices)
        hit = next(r for r in results if r["pointer_index"] == 200)
        matched_texts = {m["text"] for m in hit["matches"]}
        self.assertEqual(matched_texts, {"Potion", "Master Ball"})
        self.assertTrue(all(m["kind"] == "exact" for m in hit["matches"]))
        self.assertEqual(hit["unique_name_ids"], 2)

    def test_substring_hints_catch_text_that_is_not_an_exact_match(self) -> None:
        # ADDENDUM 124: "Potion" is an exact match; a hint like "ast" (present in "Master Ball" but not an
        # exact full-name match on its own) must be reported separately, tagged "substring".
        rel = _build_rel_with_second_string_table()
        results = rel_format.find_candidate_item_string_tables(
            rel, known_item_names={"Potion"}, substring_hints={"ast"}
        )
        hit = next(r for r in results if r["pointer_index"] == 200)
        by_text = {m["text"]: m["kind"] for m in hit["matches"]}
        self.assertEqual(by_text, {"Potion": "exact", "Master Ball": "substring"})

    def test_reports_nothing_for_tables_that_parse_but_hold_no_item_names(self) -> None:
        # Pointer 116 parses fine (it's a real, well-formed string table) but holds no item names -- must not
        # show up in the results just because it's parseable. And when NO table anywhere holds the wanted text,
        # the result is a plain empty list rather than a best-effort guess.
        rel = _build_rel_with_second_string_table()
        results = rel_format.find_candidate_item_string_tables(rel, known_item_names={"Potion", "Master Ball"})
        pointer_indices = {r["pointer_index"] for r in results}
        self.assertNotIn(rel_format.COMMON_REL_STRING_TABLE_POINTER, pointer_indices)
        self.assertEqual(
            rel_format.find_candidate_item_string_tables(rel, known_item_names={"Not In Here At All"}), []
        )


# ---------------------------------------------------------------------------------------------------------
# ADDENDUM 114/125 -- string-table decode and Items-table index arithmetic
# ---------------------------------------------------------------------------------------------------------


class TestStringTableIdOffsets(unittest.TestCase):
    def test_decodes_every_id_to_the_correct_absolute_offset(self) -> None:
        rel = _mk_rel()
        offsets = rel_format.string_table_id_offsets(rel)
        self.assertEqual(set(offsets.keys()), {5, 6, 7, 8})
        # Each decoded offset must point at exactly that string's own bytes.
        self.assertEqual(
            rel_format.read_string_table_entry_bytes(rel, offsets[5]), RAZZ_BERRY.encode("utf-16-be")
        )
        self.assertEqual(
            rel_format.read_string_table_entry_bytes(rel, offsets[6]), BLUK_BERRY.encode("utf-16-be")
        )

    def test_stored_offsets_are_relative_to_the_table_header_start_not_the_data_region(self) -> None:
        # ADDENDUM 125 regression guard for the real root cause of every live 0/27 rename result: on the
        # player's real REL, the FIRST string's stored offset is exactly 0x10 + entry_count * 8 (the record
        # array's own size), i.e. offsets count from the table header, not from the data region after the
        # records. Measuring from the data region lands every lookup one whole record-array-size too far.
        rel = _mk_rel()
        offsets = rel_format.string_table_id_offsets(rel)
        base = rel_format.string_table_base(rel)
        first_record_off = base + rel_format.STRING_TABLE_HEADER_SIZE
        stored_off = struct.unpack_from(">I", rel.data, first_record_off + 4)[0]
        self.assertEqual(stored_off, rel_format.STRING_TABLE_HEADER_SIZE + 4 * rel_format.STRING_TABLE_ENTRY_SIZE)
        self.assertEqual(offsets[5], base + stored_off)
        self.assertEqual(offsets[5], rel_format.string_table_data_region_base(rel))  # first string starts the region

    def test_ids_are_masked_to_20_bits_on_read(self) -> None:
        # Entry stored with raw id 0x300005 (high bits set) must still be found under masked key 5.
        rel = _build_synthetic_common_rel(
            xd_number_of_items=100,
            string_entries=[(0x300005, _utf16be_str(RAZZ_BERRY))],
            item_entries={},
        )
        offsets = rel_format.string_table_id_offsets(rel)
        self.assertEqual(set(offsets.keys()), {5})


class TestItemTableIndexRemap(unittest.TestCase):
    def test_all_three_threshold_branches_of_the_index_remap(self) -> None:
        # One test per fixture would be three copies of the same one-line call: ids at or below the
        # XDNumberOfItems threshold map straight through; ids strictly between the threshold and 0x251 are
        # shifted down by 150; ids at or above 0x251 map straight through again.
        rel = _mk_rel()
        self.assertEqual(rel_format.item_table_index(rel, 10), 10)
        self.assertEqual(rel_format.item_table_index(rel, 100), 100)  # exactly at the threshold
        self.assertEqual(rel_format.item_table_index(rel, 200), 50)
        self.assertEqual(rel_format.item_table_index(rel, 0x251), 0x251)  # exactly at the upper bound
        self.assertEqual(rel_format.item_table_index(rel, 999), 999)

    def test_item_name_id_is_masked_to_20_bits(self) -> None:
        rel = _mk_rel()
        self.assertEqual(rel_format.item_name_id(rel, 14), 5)  # stored raw 0x900005 -> masked 5


# ---------------------------------------------------------------------------------------------------------
# ADDENDUM 113/114 -- apply_item_name_rename (the actual ISO write) and its skip paths
# ---------------------------------------------------------------------------------------------------------


class TestApplyItemNameRename(unittest.TestCase):
    """The in-game rename itself. Player request, when shop randomization was first proposed: "Try to rename
    those to 'AP Item'." ADDENDUM 113 was research-only (no ISO write attempted); ADDENDUM 114 implements the
    equal-byte-length string-replacement approach that research de-risked. Every "skipped" case below must
    leave the buffer byte-identical -- a partial or over-long write here corrupts the player's ISO."""

    def test_successful_rename_pads_with_spaces_to_the_exact_original_byte_length(self) -> None:
        rel = _mk_rel()
        rel_bytes = bytearray(rel.data)
        result = rel_format.apply_item_name_rename(rel_bytes, rel, [10], replacement_text="AP Item")
        self.assertEqual(result["renamed"], [10])
        self.assertEqual(result["skipped"], [])

        patched_rel = FakeRel(bytes(rel_bytes), rel._pointers, rel._values)
        offsets = rel_format.string_table_id_offsets(patched_rel)
        new_raw = rel_format.read_string_table_entry_bytes(patched_rel, offsets[5])
        new_text = new_raw.decode("utf-16-be")
        self.assertEqual(new_text, "AP Item" + " " * 3)  # "Razz Berry" was 10 chars; "AP Item" is 7 -> 3 spaces
        self.assertEqual(len(new_raw) + 2, len(RAZZ_BERRY.encode("utf-16-be")) + 2)  # identical total byte length

    def test_expected_names_mismatch_is_skipped_and_not_written(self) -> None:
        rel = _mk_rel()
        rel_bytes = bytearray(rel.data)
        original = bytes(rel_bytes)
        result = rel_format.apply_item_name_rename(
            rel_bytes, rel, [11], replacement_text="AP Item", expected_names={11: "Wrong Name"}
        )
        self.assertEqual(result["renamed"], [])
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(result["skipped"][0]["item_id"], 11)
        self.assertIn("expected", result["skipped"][0]["reason"])
        self.assertEqual(bytes(rel_bytes), original)  # untouched

    def test_escape_sequence_string_is_skipped_defensively(self) -> None:
        rel = _mk_rel()
        rel_bytes = bytearray(rel.data)
        original = bytes(rel_bytes)
        result = rel_format.apply_item_name_rename(rel_bytes, rel, [200], replacement_text="AP Item")
        self.assertEqual(result["renamed"], [])
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(result["skipped"][0]["item_id"], 200)
        self.assertIn("0xFFFF", result["skipped"][0]["reason"])
        self.assertEqual(bytes(rel_bytes), original)

    def test_name_id_not_found_in_string_table_is_skipped(self) -> None:
        rel = _mk_rel()
        rel_bytes = bytearray(rel.data)
        result = rel_format.apply_item_name_rename(rel_bytes, rel, [13], replacement_text="AP Item")
        self.assertEqual(result["renamed"], [])
        self.assertEqual(result["skipped"][0]["item_id"], 13)
        self.assertIn("not found", result["skipped"][0]["reason"])

    def test_replacement_too_long_for_original_budget_is_skipped(self) -> None:
        rel = _mk_rel()
        rel_bytes = bytearray(rel.data)
        original = bytes(rel_bytes)
        result = rel_format.apply_item_name_rename(rel_bytes, rel, [12], replacement_text="AP Item")
        self.assertEqual(result["renamed"], [])
        self.assertEqual(result["skipped"][0]["item_id"], 12)
        self.assertIn("does not fit", result["skipped"][0]["reason"])
        self.assertEqual(bytes(rel_bytes), original)

    def test_unresolvable_name_id_is_skipped_not_raised(self) -> None:
        rel = _mk_rel()
        rel_bytes = bytearray(rel.data)
        result = rel_format.apply_item_name_rename(rel_bytes, rel, [999], replacement_text="AP Item")
        self.assertEqual(result["renamed"], [])
        self.assertEqual(result["skipped"][0]["item_id"], 999)
        self.assertIn("could not resolve NameID", result["skipped"][0]["reason"])

    def test_multiple_ids_in_one_call_are_processed_independently(self) -> None:
        rel = _mk_rel()
        rel_bytes = bytearray(rel.data)
        result = rel_format.apply_item_name_rename(
            rel_bytes, rel, [10, 11, 12, 13, 200, 999], replacement_text="AP Item"
        )
        self.assertEqual(sorted(result["renamed"]), [10, 11])
        skipped_ids = {s["item_id"] for s in result["skipped"]}
        self.assertEqual(skipped_ids, {12, 13, 200, 999})

    def test_original_rel_data_is_never_mutated_only_the_bytearray_copy(self) -> None:
        rel = _mk_rel()
        original = bytes(rel.data)
        rel_bytes = bytearray(rel.data)
        rel_format.apply_item_name_rename(rel_bytes, rel, [10], replacement_text="AP Item")
        self.assertEqual(rel.data, original)


class TestApplyItemNameRenameTextSearch(unittest.TestCase):
    """ADDENDUM 121's text search, now the FALLBACK behind the original struct path (ADDENDUM 125 -- the real
    root cause of every live 0/27 was `string_table_id_offsets`'s wrong offset base, fixed and verified against
    the player's real REL bytes; with it fixed the struct path resolves everything, so it's primary again and
    the text search only runs when it fails or mismatches). See `apply_item_name_rename`'s docstring."""

    def test_struct_path_is_primary_and_wins_when_it_matches(self) -> None:
        rel = _mk_rel()
        rel_bytes = bytearray(rel.data)
        result = rel_format.apply_item_name_rename(
            rel_bytes, rel, [10], replacement_text="AP Item", expected_names={10: RAZZ_BERRY}
        )
        self.assertEqual(result["renamed"], [10])
        self.assertEqual(result["resolved_via"][10], {"via": "struct", "name_id": 5})

    def test_struct_mismatch_falls_back_to_text_search(self) -> None:
        # item 10's own struct entry points at NameID 5 ("Razz Berry"); asking for "Bluk Berry" mismatches the
        # struct path, and the fallback text search finds NameID 6 instead -- unique, so it's used.
        rel = _mk_rel()
        rel_bytes = bytearray(rel.data)
        result = rel_format.apply_item_name_rename(
            rel_bytes, rel, [10], replacement_text="AP Item", expected_names={10: BLUK_BERRY}
        )
        self.assertEqual(result["renamed"], [10])
        self.assertEqual(result["resolved_via"][10], {"via": "text-search", "name_id": 6})

    def test_finds_and_renames_by_text_search_even_when_the_item_table_entry_is_missing_or_garbage(self) -> None:
        # item_id 999 has NO entry anywhere in this fixture's (deliberately small) Items table -- the OLD
        # calibration search would have had to except-and-skip just trying to READ a NameID for it. The new
        # text search never looks at the Items table at all for an item with `expected_names`, so this
        # succeeds purely by finding "Bluk Berry" (NameID 6) directly in the string table.
        rel = _mk_rel()
        rel_bytes = bytearray(rel.data)
        result = rel_format.apply_item_name_rename(
            rel_bytes, rel, [999], replacement_text="AP Item", expected_names={999: "Bluk Berry"}
        )
        self.assertEqual(result["renamed"], [999])
        self.assertEqual(result["skipped"], [])
        self.assertEqual(result["resolved_via"][999], {"via": "text-search", "name_id": 6})

        patched_rel = FakeRel(bytes(rel_bytes), rel._pointers, rel._values)
        offsets = rel_format.string_table_id_offsets(patched_rel)
        new_text = rel_format.read_string_table_entry_bytes(patched_rel, offsets[6]).decode("utf-16-be")
        self.assertEqual(new_text, "AP Item" + " " * 3)

    def test_match_is_case_and_trailing_space_insensitive(self) -> None:
        # Covers the expected-name safety check for BOTH paths: a differently-cased, space-padded expected name
        # must still count as a match and be renamed (rather than skipped as a mismatch) -- and here item 11's
        # own struct entry points at NameID 6 ("Bluk Berry"), so the PRIMARY struct path is what resolves it.
        rel = _mk_rel()
        rel_bytes = bytearray(rel.data)
        result = rel_format.apply_item_name_rename(
            rel_bytes, rel, [11], replacement_text="AP Item", expected_names={11: "  bluk berry  "}
        )
        self.assertEqual(result["renamed"], [11])
        self.assertEqual(result["skipped"], [])
        self.assertEqual(result["resolved_via"][11], {"via": "struct", "name_id": 6})

    def test_expected_text_not_found_anywhere_is_skipped_safely_with_no_write(self) -> None:
        rel = _mk_rel()
        rel_bytes = bytearray(rel.data)
        original = bytes(rel_bytes)
        result = rel_format.apply_item_name_rename(
            rel_bytes, rel, [11], replacement_text="AP Item", expected_names={11: "Not Actually There"}
        )
        self.assertEqual(result["renamed"], [])
        self.assertIn("text search found it nowhere", result["skipped"][0]["reason"])
        self.assertIn("struct path resolved NameID 6", result["skipped"][0]["reason"])
        self.assertEqual(bytes(rel_bytes), original)
        self.assertNotIn(11, result["resolved_via"])

    def test_ambiguous_duplicate_text_is_skipped_safely_with_no_write(self) -> None:
        rel = _mk_rel_with_duplicate_text()
        rel_bytes = bytearray(rel.data)
        original = bytes(rel_bytes)
        result = rel_format.apply_item_name_rename(
            rel_bytes, rel, [5], replacement_text="AP Item", expected_names={5: "Duplicate Item"}
        )
        self.assertEqual(result["renamed"], [])
        self.assertEqual(len(result["skipped"]), 1)
        self.assertIn("text search matched 2 different string-table entries", result["skipped"][0]["reason"])
        self.assertEqual(bytes(rel_bytes), original)
        self.assertNotIn(5, result["resolved_via"])

    def test_no_expected_names_means_no_safety_check_and_an_empty_resolved_via(self) -> None:
        # With no expected names there is nothing to verify against and nothing to fall back to, so both items
        # rename straight off the struct path -- and `resolved_via`, which only records verified resolutions,
        # stays empty rather than reporting a resolution that was never actually checked.
        rel = _mk_rel()
        rel_bytes = bytearray(rel.data)
        result = rel_format.apply_item_name_rename(rel_bytes, rel, [10, 11], replacement_text="AP Item")
        self.assertEqual(sorted(result["renamed"]), [10, 11])
        self.assertEqual(result["resolved_via"], {})

    def test_replacement_too_long_for_matched_strings_budget_is_still_skipped(self) -> None:
        # Text search finds NameID 8 ("Cut") by matching its own text as the expected name -- but "Cut" is too
        # short a budget to hold "AP Item", so it must still be skipped by the length check downstream, exactly
        # like the single-path branch already covers for items without expected_names.
        rel = _mk_rel()
        rel_bytes = bytearray(rel.data)
        original = bytes(rel_bytes)
        result = rel_format.apply_item_name_rename(
            rel_bytes, rel, [12], replacement_text="AP Item", expected_names={12: "Cut"}
        )
        self.assertEqual(result["renamed"], [])
        self.assertIn("does not fit", result["skipped"][0]["reason"])
        self.assertEqual(bytes(rel_bytes), original)


class TestApItemRenameTargetNames(unittest.TestCase):
    """items.py's constants feeding apply_item_name_rename's real production usage."""

    def test_target_names_cover_every_useless_berry_and_the_chest_dummy_with_matching_names(self) -> None:
        # WIDENED 2026-09-15 (ADDENDUM 218): all seven chest berries, not just the one former shared dummy.
        # Every id this seed can plant has to be renamed, or a player sees a real berry name on a check item.
        self.assertEqual(
            set(items.AP_ITEM_RENAME_TARGET_NAMES.keys()),
            set(items.USELESS_BERRY_IDS) | set(items.CHEST_BERRY_IDS),
        )
        for game_item_id, name in items.CHEST_BERRY_ID_TO_NAME.items():
            self.assertEqual(items.AP_ITEM_RENAME_TARGET_NAMES[game_item_id], name)
        # The names are the `expected_names` safety check's own input, so each one must still agree with the
        # spec it came from -- a drifted name here silently turns every rename into a skip.
        for game_item_id, name in items.USELESS_BERRY_ID_TO_NAME.items():
            self.assertEqual(items.AP_ITEM_RENAME_TARGET_NAMES[game_item_id], name)
        self.assertEqual(
            items.AP_ITEM_RENAME_TARGET_NAMES[items.CHEST_DUMMY_GAME_ITEM_ID], items.CHEST_DUMMY_GAME_ITEM_NAME
        )
        self.assertEqual(items.CHEST_DUMMY_GAME_ITEM_NAME, "Rabuta Berry")
        self.assertEqual(items.AP_ITEM_DISPLAY_TEXT, "AP Item")  # the player-requested replacement text


# ---------------------------------------------------------------------------------------------------------
# ADDENDUM 112 -- iso_patcher._find_rel_entry
# ---------------------------------------------------------------------------------------------------------


class TestFindRelEntryContainsRelConvention(unittest.TestCase):
    """The ORIGINAL convention (common.fsys's own 'common_rel') must keep working unchanged."""

    def test_a_single_contains_rel_match_wins_even_with_a_basename_fallback_available(self) -> None:
        entries = {"common_rel": {"marker": 1}, "common_csr": {}}
        name, entry = _find_rel_entry(entries, "common.fsys", container_basename="common")
        self.assertEqual(name, "common_rel")
        self.assertEqual(entry, {"marker": 1})

    def test_multiple_contains_rel_matches_still_raise_even_with_a_basename_fallback_available(self) -> None:
        entries = {"foo_rel": {}, "bar_rel": {}, "foo": {}}
        with self.assertRaises(ValueError):
            _find_rel_entry(entries, "foo.fsys", container_basename="foo")


class TestFindRelEntryBasenameFallback(unittest.TestCase):
    """ADDENDUM 112 (2026-09-11) -- the base-name-match fallback for containers whose REL entry name does NOT
    follow `common.fsys`'s "base name + _rel suffix" convention.

    Player report that triggered this fix: a real patch attempt against `pocket_menu.fsys` failed with "has no
    entry with 'rel' in its name," and the error message's own entry dump (the real container's own entry names)
    showed there IS no `*_rel`-suffixed entry at all. Every non-'pocket_menu' name reads as a UI texture/panel/
    status asset, leaving 'pocket_menu' itself -- named identically to the container's own base name, no suffix
    -- as the only plausible REL entry. `REAL_POCKET_MENU_ENTRIES` is that real entry list, used as the
    fixture."""

    def test_pocket_menu_fsys_real_entry_list_resolves_via_the_basename_fallback(self) -> None:
        name, entry = _find_rel_entry(
            REAL_POCKET_MENU_ENTRIES, "pocket_menu.fsys", container_basename="pocket_menu"
        )
        self.assertEqual(name, "pocket_menu")
        self.assertEqual(entry, REAL_POCKET_MENU_ENTRIES["pocket_menu"])

    def test_no_contains_rel_match_still_raises_key_error_with_or_without_a_usable_basename(self) -> None:
        # The fallback must not become a wildcard: with no basename given at all, and with a basename that
        # matches no entry, the lookup still fails loudly rather than guessing at some other entry.
        with self.assertRaises(KeyError):
            _find_rel_entry(REAL_POCKET_MENU_ENTRIES, "pocket_menu.fsys")
        with self.assertRaises(KeyError):
            _find_rel_entry(REAL_POCKET_MENU_ENTRIES, "pocket_menu.fsys", container_basename="not_a_real_entry")

    def test_the_error_message_includes_the_full_entry_list_for_debugging(self) -> None:
        # This dump is how the real container's entry names reached the player report in the first place.
        with self.assertRaises(KeyError) as ctx:
            _find_rel_entry(REAL_POCKET_MENU_ENTRIES, "pocket_menu.fsys")
        self.assertIn("uv_str_item_00", str(ctx.exception))


# ---------------------------------------------------------------------------------------------------------
# ADDENDUM 115 -- RelFile's bounds-checked pointer-table walk
# ---------------------------------------------------------------------------------------------------------


class TestRelFileValidConstruction(unittest.TestCase):
    def test_a_genuinely_valid_minimal_header_constructs_with_zero_pointers_and_keeps_its_label(self) -> None:
        # The bounds check must not reject a real (if trivial) header. The label is carried verbatim because it
        # is what makes the error in TestRelFileBoundsCheckedErrors actionable -- it names the container and
        # entry the bad bytes came from.
        rel = rel_format.RelFile(_build_minimal_valid_rel(), is_common=False)
        self.assertEqual(rel.number_of_pointers, 0)
        self.assertEqual(rel.label, "REL")  # generic default
        labelled = rel_format.RelFile(
            _build_minimal_valid_rel(), is_common=False, label="pocket_menu.fsys entry 'x'"
        )
        self.assertEqual(labelled.label, "pocket_menu.fsys entry 'x'")


class TestRelFileBoundsCheckedErrors(unittest.TestCase):
    """Player report: a real patch attempt crashed with a cryptic "unpack_from requires a buffer of at least
    369098756 bytes for unpacking 4 bytes at offset 369098752 (actual buffer size is 544)" while constructing a
    RelFile for `pocket_menu.fsys`'s `pocket_menu` entry (ADDENDUM 112's fallback guess for that container) --
    544 bytes is far too small to be real REL pointer-table data, so the garbage value read out of it as a
    "pointer_header" dereferenced to an absurd, out-of-bounds offset. RelFile.__init__ now raises a clear,
    actionable ValueError instead of letting that struct.error escape uninformatively."""

    def test_undersized_container_raises_a_clear_value_error_not_a_bare_struct_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            rel_format.RelFile(
                _build_undersized_garbage_rel(), is_common=False, label="pocket_menu.fsys entry 'pocket_menu'"
            )
        message = str(ctx.exception)
        self.assertIn("out of bounds", message)
        self.assertIn("544", message)
        self.assertIn("pocket_menu.fsys entry 'pocket_menu'", message)

    def test_error_is_a_value_error_not_the_raw_struct_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            rel_format.RelFile(_build_undersized_garbage_rel(), is_common=False)
        # struct.error is a sibling of ValueError (both direct Exception subclasses in CPython), not a
        # ValueError itself -- this explicitly guards against a future refactor accidentally letting the raw
        # struct.error leak through uncaught (which the `assertRaises(ValueError)` above alone wouldn't catch,
        # since a bare struct.error would simply fail that assertion with its own, different traceback).
        self.assertNotIsInstance(ctx.exception, struct.error)

    def test_out_of_bounds_negative_offset_is_also_caught(self) -> None:
        # A negative computed offset (e.g. from unsigned/signed arithmetic gone wrong elsewhere) must be
        # rejected the same clear way, not handed to struct.unpack_from to fail on its own terms.
        rel = rel_format.RelFile(_build_minimal_valid_rel(), is_common=False)
        with self.assertRaises(ValueError):
            rel._u32(-1)


# ---------------------------------------------------------------------------------------------------------
# ADDENDUM 119 -- scan_bytes_for_item_id_runs
# ---------------------------------------------------------------------------------------------------------


class TestScanBytesForItemIdRuns(unittest.TestCase):
    """ADDENDUM 119 (2026-09-11, shop/mart location -- read-only candidate scan). A pure byte-scanning utility
    with no REL/pointer dependency (unlike `apply_mart_randomization`/`read_all_mart_slots`), so it's tested
    directly against synthetic byte blobs -- no FakeRel fixture needed."""

    def test_finds_every_sentinel_terminated_run_and_skips_the_words_between_them(self) -> None:
        # Two leading zeros with no preceding run (just skipped), run 1 (3 items + sentinel), a noise word,
        # then run 2 (3 items + sentinel). Each reported run carries its own start offset, its decoded ids, and
        # the offset of the 0x0000 that terminated it.
        data = _u16s(0, 0, 111, 222, 333, 0, 0xDEAD, 444, 555, 666, 0)
        result = rel_format.scan_bytes_for_item_id_runs(
            data, valid_item_ids={111, 222, 333, 444, 555, 666}, min_run_length=3
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["offset"], 4)
        self.assertEqual(result[0]["item_ids"], [111, 222, 333])
        self.assertEqual(result[0]["terminator_offset"], 10)
        self.assertEqual(result[1]["offset"], 14)
        self.assertEqual(result[1]["item_ids"], [444, 555, 666])
        self.assertEqual(result[1]["terminator_offset"], 20)

    def test_run_shorter_than_min_run_length_is_discarded_under_the_default_minimum_too(self) -> None:
        data = _u16s(111, 222, 0)  # only 2 valid ids before the sentinel
        self.assertEqual(
            rel_format.scan_bytes_for_item_id_runs(data, valid_item_ids={111, 222}, min_run_length=3), []
        )
        # Sanity check on the documented default -- the same 2-item run is dropped without passing
        # min_run_length explicitly.
        self.assertEqual(rel_format.scan_bytes_for_item_id_runs(data, valid_item_ids={111, 222}), [])

    def test_run_never_reaching_a_zero_terminator_is_discarded(self) -> None:
        # Ends at EOF with no 0x0000 -- doesn't match the expected sentinel-terminated shape, so it's not
        # reported even though every value is individually a valid item id.
        data = _u16s(111, 222, 333, 444)
        result = rel_format.scan_bytes_for_item_id_runs(data, valid_item_ids={111, 222, 333, 444}, min_run_length=3)
        self.assertEqual(result, [])

    def test_run_broken_by_a_non_valid_non_zero_value_is_discarded_not_split(self) -> None:
        # 111, 222 valid, then 0xBEEF (neither valid nor zero) breaks the run -- it never reaches a sentinel,
        # so nothing is recorded for it, and the scan does NOT try to resume/merge across the break.
        data = _u16s(111, 222, 0xBEEF, 333, 444, 555, 0)
        result = rel_format.scan_bytes_for_item_id_runs(
            data, valid_item_ids={111, 222, 333, 444, 555}, min_run_length=3
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["item_ids"], [333, 444, 555])

    def test_degenerate_input_is_handled_without_error_and_without_mutation(self) -> None:
        # Empty input yields no runs; a buffer whose length isn't a multiple of 2 has its odd trailing byte
        # ignored rather than raising; and the scan is read-only, so the caller's bytes come back unchanged
        # (this runs over real container data straight out of an ISO).
        self.assertEqual(rel_format.scan_bytes_for_item_id_runs(b"", valid_item_ids={111}), [])
        data = _u16s(111, 222, 333, 0) + b"\x01"
        original = bytes(data)
        result = rel_format.scan_bytes_for_item_id_runs(data, valid_item_ids={111, 222, 333}, min_run_length=3)
        self.assertEqual(len(result), 1)
        self.assertEqual(data, original)


# ---------------------------------------------------------------------------------------------------------
# ADDENDUM 126 -- iso_patcher.parse_fsys_all
# ---------------------------------------------------------------------------------------------------------


class TestParseFsysAll(unittest.TestCase):
    """ADDENDUM 126 (2026-09-11): `parse_fsys_all` was added because `parse_fsys` keys its result by
    extension-less base name and so silently drops one of two entries that share a base name -- exactly the
    case for `pocket_menu.fsys`, whose real mart REL (`pocket_menu.rel`, the full name the reference randomizer
    opens it by) was being shadowed by a same-named UI-data twin."""

    def test_parse_fsys_collapses_duplicate_base_names_but_parse_fsys_all_keeps_both(self) -> None:
        fsys = _build_fsys_with_duplicate_base_names()
        collapsed = iso_patcher.parse_fsys(fsys)
        self.assertEqual(list(collapsed.keys()), ["pocket_menu"])  # the documented shadowing
        self.assertEqual(collapsed["pocket_menu"]["data_off"], 0x280)  # the LAST record wins
        every = iso_patcher.parse_fsys_all(fsys)
        self.assertEqual([e["index"] for e in every], [0, 1])
        self.assertEqual([e["data_off"] for e in every], [0x200, 0x280])

    def test_full_name_and_file_format_are_exposed(self) -> None:
        every = iso_patcher.parse_fsys_all(_build_fsys_with_duplicate_base_names())
        self.assertEqual(every[0]["full_name"], "pocket_menu.rel")
        self.assertEqual(every[0]["file_format"], 2)
        self.assertIsNone(every[1]["full_name"])  # +0x1C pointer of 0 -> no full name
        self.assertEqual(every[1]["file_format"], 9)
        self.assertEqual(every[0]["name"], "pocket_menu")
        self.assertEqual(every[1]["name"], "pocket_menu")

    def test_rejects_non_fsys_bytes(self) -> None:
        with self.assertRaises(ValueError):
            iso_patcher.parse_fsys_all(b"NOPE" + b"\x00" * 0x100)


if __name__ == "__main__":
    unittest.main()
