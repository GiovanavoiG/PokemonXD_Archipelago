"""Regression/coverage test for Enhanced Difficulty's Mt. Battle extension (2026-09-09, ADDENDUM 93, player
request: "make it so that the enhanced difficulty yaml option also randomizes & fills the mt battle trainer
teams").

WHY THIS TEST EXISTS: `write_enhanced_difficulty_mt_battle_patch` (tools/iso_patcher.py) is a genuinely new
code path -- unlike `write_enhanced_difficulty_patch` (which reuses the older, `DeckData_Story.bin`-hardcoded
`write_deck_story_patch`), this function goes through `write_fsys_multi_entry_patch` (the generalized,
entry-name-parameterized writer originally built for Shadow Pokemon Expansion's combined Story+DarkPokemon
write) with a single-entry `edits` list targeting `DeckData_Hundred.bin` instead. This is the first time
anything in this project has ever WRITTEN to `DeckData_Hundred.bin` -- every prior addendum only ever read it
(ADDENDUM 92's live-bridge trainer identification). This test exercises that write end-to-end (growth path
included, mirroring `test_write_enhanced_difficulty_patch_iso.py`'s own regression for the sibling Story-side
function) against a minimal, real-format-shaped synthetic ISO, without needing a real 1GB game ISO.

Deliberately mirrors `test_write_enhanced_difficulty_patch_iso.py`'s structure closely (same synthetic-ISO
construction helpers, re-derived rather than imported so this test has no hidden dependency on that file's own
internals) -- the only real differences are the FSYS entry name (`DeckData_Hundred.bin` instead of
`DeckData_Story.bin`) and the function under test."""
import struct
import tempfile
from pathlib import Path

from ..tools import iso_patcher
from ..tools import xd_deck_format as deck_format


def _build_synthetic_hundred_decompressed() -> bytes:
    """A minimal but real-format DECK/DTNR/DPKM/DTAI/DSTR blob standing in for DeckData_Hundred.bin: one
    trainer (index 1, 5 free team slots) with one real DPKM team member (dpkm_index 1) -- same shape as
    ADDENDUM 92's real trainer_index 1 (party_size 1... here simplified to exercise the same growth path)."""
    dtnr_entries = 2  # index 0 = unused sentinel, index 1 = our one real trainer
    dtnr_size = 0x10 + dtnr_entries * 0x38
    dtnr = bytearray(dtnr_size)
    dtnr[0:4] = b"DTNR"
    struct.pack_into(">I", dtnr, 0x04, dtnr_size)
    struct.pack_into(">I", dtnr, 0x08, dtnr_entries)
    rec_off = 0x10 + 1 * 0x38
    dtnr[rec_off + 0x05] = 1  # trainer_class nonzero -> this slot is a real, used trainer
    struct.pack_into(">H", dtnr, rec_off + 0x1C + 0 * 2, 1)  # team slot 0 -> dpkm_index 1

    dpkm_entries = 2  # index 0 = sentinel, index 1 = the one real team member above
    dpkm_size = 0x10 + dpkm_entries * 0x20
    dpkm = bytearray(dpkm_size)
    dpkm[0:4] = b"DPKM"
    struct.pack_into(">I", dpkm, 0x04, dpkm_size)
    struct.pack_into(">I", dpkm, 0x08, dpkm_entries)
    e1_off = 0x10 + 1 * 0x20
    struct.pack_into(">H", dpkm, e1_off + 0x00, 290)  # Wurmple's internal index (ADDENDUM 92) -- arbitrary here
    dpkm[e1_off + 0x02] = 9  # level, matching ADDENDUM 92's real trainer_index 1

    dtai = bytearray(0x10)
    dtai[0:4] = b"DTAI"
    struct.pack_into(">I", dtai, 0x04, 0x10)

    dstr = bytearray(0x10)
    dstr[0:4] = b"DSTR"
    struct.pack_into(">I", dstr, 0x04, 0x10)

    main_hdr = bytearray(0x10)
    main_hdr[0:4] = b"DECK"

    return bytes(main_hdr) + bytes(dtnr) + bytes(dpkm) + bytes(dtai) + bytes(dstr)


def _build_synthetic_fsys(hundred_decompressed: bytes) -> bytes:
    name = b"DeckData_Hundred.bin\x00"
    record_off = 0x64
    name_off = 0x90
    data_off = 0x100

    stream = deck_format.lzss_encode(hundred_decompressed)
    comp_size = len(stream) + 256  # generous headroom -- keeps the in-place path exercised (the growth+
    # relocation path is already covered by this project's other real-ISO-derived tests), same convention as
    # test_write_enhanced_difficulty_patch_iso.py's own synthetic FSYS builder.
    entry_blob = b"LZSS" + struct.pack(">II", len(hundred_decompressed), comp_size) + b"\x00\x00\x00\x00"
    entry_blob += stream + b"\x00" * (comp_size - len(stream))

    total_len = max(name_off + len(name), data_off + len(entry_blob))
    fsys = bytearray(total_len)
    fsys[0:4] = b"FSYS"
    struct.pack_into(">I", fsys, 0x0C, 1)  # entry_count
    struct.pack_into(">I", fsys, 0x60, record_off)  # offset array[0]
    struct.pack_into(">I", fsys, record_off + 0x04, data_off)
    struct.pack_into(">I", fsys, record_off + 0x08, len(hundred_decompressed))
    struct.pack_into(">I", fsys, record_off + 0x14, comp_size)
    struct.pack_into(">I", fsys, record_off + 0x24, name_off)
    fsys[name_off:name_off + len(name)] = name
    fsys[data_off:data_off + len(entry_blob)] = entry_blob
    return bytes(fsys)


def _build_synthetic_iso(fsys_container: bytes) -> bytes:
    fst_offset = 0x440  # right after BOOT_HEADER_READ_LEN (0x440)
    file_offset = 0x800
    name = b"deck_archive.fsys\x00"
    entry_count = 2  # root dir (index 0) + our one file (index 1)
    string_table_off = entry_count * 12
    fst = bytearray(string_table_off + len(name))
    fst[0] = 1  # root entry: directory
    struct.pack_into(">I", fst, 8, entry_count)  # root's field3 = total FST entry count
    base = 12
    fst[base] = 0  # file entry: not a directory
    struct.pack_into(">I", fst, base + 4, file_offset)
    struct.pack_into(">I", fst, base + 8, len(fsys_container))
    fst[string_table_off:string_table_off + len(name)] = name

    total_len = file_offset + len(fsys_container)
    iso = bytearray(total_len)
    struct.pack_into(">I", iso, 0x424, fst_offset)  # FST_OFFSET_FIELD
    struct.pack_into(">I", iso, 0x428, len(fst))  # FST_SIZE_FIELD
    iso[fst_offset:fst_offset + len(fst)] = fst
    iso[file_offset:file_offset + len(fsys_container)] = fsys_container
    return bytes(iso)


def test_write_enhanced_difficulty_mt_battle_patch_grows_dpkm_section_against_a_real_shaped_iso() -> None:
    hundred_decompressed = _build_synthetic_hundred_decompressed()
    fsys_container = _build_synthetic_fsys(hundred_decompressed)
    iso_bytes = _build_synthetic_iso(fsys_container)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / "synthetic.iso"
        tmp_path.write_bytes(iso_bytes)

        before_deck = deck_format.DeckFile(hundred_decompressed)
        assert before_deck.dpkm_entries == 2
        assert before_deck.trainer(1)["party_size"] == 1

        # Boosts dpkm_index 1's level and adds one brand-new ordinary team member to trainer 1 (which has 5
        # free slots) -- exercises the exact same grow_dpkm_section path the Story-side sibling test regresses,
        # but through write_fsys_multi_entry_patch/DeckData_Hundred.bin instead of write_deck_story_patch/
        # DeckData_Story.bin.
        plan = {
            "level_assignment": {1: 12},
            "new_dpkm_entries": [{"species": 309, "level": 11, "moves": [1, 2, 3, 4]}],  # Wingull's internal id
            "team_slot_plan": [{"trainer_index": 1, "new_entry_pos": 0}],
        }

        result = iso_patcher.write_enhanced_difficulty_mt_battle_patch(tmp_path, plan)
        assert result == {
            "grew": False,  # fits in the generous padding this test's synthetic entry allocated
            "levels_boosted": 1,
            "new_members_added": 1,
            "trainers_padded": 1,
        }

        reader = iso_patcher.open_reader(tmp_path)
        try:
            fst = iso_patcher.parse_fst(reader)
            deck_off, deck_len, _ = iso_patcher.find_by_basename(fst, "deck_archive.fsys")
            fsys_bytes = reader.read(deck_off, deck_len)
            entries = iso_patcher.parse_fsys(fsys_bytes)
            hundred_entry = entries["DeckData_Hundred.bin"]
            hundred_raw = reader.read(deck_off + hundred_entry["data_off"], 0x10 + hundred_entry["comp_size"])
        finally:
            reader.close()

        new_decompressed = deck_format.lzss_decode(hundred_raw)
        after_deck = deck_format.DeckFile(new_decompressed)

        assert after_deck.dpkm_entries == before_deck.dpkm_entries + 1
        assert after_deck.dpkm_full(1)["level"] == 12
        assert after_deck.trainer(1)["party_size"] == 2
        new_member = after_deck.dpkm_full(2)
        assert new_member["species"] == 309
        assert new_member["level"] == 11


def test_write_enhanced_difficulty_mt_battle_patch_rejects_out_of_range_trainer_index() -> None:
    """A seed's mt_battle_enhanced_difficulty_plan referencing a trainer_index this synthetic (1-trainer) ISO
    doesn't have must raise a clear error, not silently do nothing or corrupt an unrelated slot -- mirrors the
    same "different game version/region" guard write_enhanced_difficulty_patch already has for Story."""
    hundred_decompressed = _build_synthetic_hundred_decompressed()
    fsys_container = _build_synthetic_fsys(hundred_decompressed)
    iso_bytes = _build_synthetic_iso(fsys_container)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / "synthetic.iso"
        tmp_path.write_bytes(iso_bytes)

        plan = {
            "level_assignment": {},
            "new_dpkm_entries": [{"species": 1, "level": 5, "moves": [0, 0, 0, 0]}],
            "team_slot_plan": [{"trainer_index": 99, "new_entry_pos": 0}],  # doesn't exist in this synthetic ISO
        }
        try:
            iso_patcher.write_enhanced_difficulty_mt_battle_patch(tmp_path, plan)
        except ValueError as e:
            assert "trainer_index" in str(e)
        else:
            raise AssertionError("expected a ValueError for an out-of-range Mt. Battle trainer_index")
