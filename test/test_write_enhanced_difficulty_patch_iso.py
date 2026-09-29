"""Regression test for a real bug found live (2026-09-08): the player generated a seed with `enhanced_difficulty`
on and ran `iso_patcher.py apply` against their real ISO, and got:

    Could not patch the ISO: resizing the decompressed payload (66132 vs original 51188) is not supported by
    this simple in-place patcher -- it would require adding/removing DTNR/DPKM/DDPK entries, which this
    project's edits never do. Pass allow_decomp_resize=True (NEW, ADDENDUM 51) if the caller genuinely changed
    a section's own entry count...

Root cause: `write_enhanced_difficulty_patch` (tools/iso_patcher.py) called `write_deck_story_patch` without
`allow_decomp_resize=True`. `apply_enhanced_difficulty_story_edit` calls `grow_dpkm_section` whenever a plan
has any `new_dpkm_entries` -- which genuinely changes `DeckData_Story.bin`'s decompressed section layout (a
bigger DPKM section) -- exactly the case `deck_format.patch_entry_decompressed` refuses unless the caller
opts in with `allow_decomp_resize=True`. Every OTHER DPKM-growth call site in this file already passes it;
this one write path was missed when Enhanced Difficulty was first built. None of this project's prior unit/
integration tests caught it because they only ever exercised the plan-building logic
(`build_enhanced_difficulty_plan`) or `generate_output()`'s `seed.json` output -- never the actual ISO
byte-write call (`write_enhanced_difficulty_patch` itself), which needs real (or, here, synthetic-but-
realistically-shaped) FST/FSYS/LZSS container bytes to exercise at all.

This test builds a minimal, real-format-shaped synthetic ISO (a plain, uncompressed image -- valid GameCube
boot header fields, one FST file entry, one FSYS container holding one `DeckData_Story.bin` entry with a
tiny but real, LZSS-encoded, parseable DECK/DTNR/DPKM/DTAI/DSTR blob) and calls
`iso_patcher.write_enhanced_difficulty_patch` against it for real, through the SAME code path the player's
own `apply` run uses -- so a future regression here (dropping `allow_decomp_resize=True` again, or any other
change that breaks this specific growth-write contract) fails this test immediately, without needing a real
1GB game ISO."""
import struct
import tempfile
from pathlib import Path

from ..tools import iso_patcher
from ..tools import xd_deck_format as deck_format


def _build_synthetic_story_decompressed() -> bytes:
    """A minimal but real-format DECK/DTNR/DPKM/DTAI/DSTR blob: one trainer (index 1, 5 free team slots)
    with one real DPKM team member (dpkm_index 1)."""
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
    struct.pack_into(">H", dpkm, e1_off + 0x00, 25)  # species (Pikachu's internal id, arbitrary here)
    dpkm[e1_off + 0x02] = 10  # level

    dtai = bytearray(0x10)
    dtai[0:4] = b"DTAI"
    struct.pack_into(">I", dtai, 0x04, 0x10)

    dstr = bytearray(0x10)
    dstr[0:4] = b"DSTR"
    struct.pack_into(">I", dstr, 0x04, 0x10)

    main_hdr = bytearray(0x10)
    main_hdr[0:4] = b"DECK"

    return bytes(main_hdr) + bytes(dtnr) + bytes(dpkm) + bytes(dtai) + bytes(dstr)


def _build_synthetic_fsys(story_decompressed: bytes) -> bytes:
    name = b"DeckData_Story.bin\x00"
    record_off = 0x64
    name_off = 0x90
    data_off = 0x100

    stream = deck_format.lzss_encode(story_decompressed)
    comp_size = len(stream) + 256  # generous headroom -- a real, unpatched entry's own allocation always has
    # some slack (ADDENDUM 9/10), and this keeps the in-place path exercised rather than the separate
    # growth+relocation path (already covered by this project's other real-ISO-derived tests).
    # A real, unpatched FSYS entry's own internal LZSS header declares the FULL ALLOCATED (padded) compressed
    # size here, matching the container's own record field -- only after an edit does patch_entry_decompressed
    # correct it to the smaller TRUE size (see that function's ADDENDUM 10 fix notes).
    entry_blob = b"LZSS" + struct.pack(">II", len(story_decompressed), comp_size) + b"\x00\x00\x00\x00"
    entry_blob += stream + b"\x00" * (comp_size - len(stream))

    total_len = max(name_off + len(name), data_off + len(entry_blob))
    fsys = bytearray(total_len)
    fsys[0:4] = b"FSYS"
    struct.pack_into(">I", fsys, 0x0C, 1)  # entry_count
    struct.pack_into(">I", fsys, 0x60, record_off)  # offset array[0]
    struct.pack_into(">I", fsys, record_off + 0x04, data_off)
    struct.pack_into(">I", fsys, record_off + 0x08, len(story_decompressed))
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


def test_write_enhanced_difficulty_patch_grows_dpkm_section_against_a_real_shaped_iso() -> None:
    story_decompressed = _build_synthetic_story_decompressed()
    fsys_container = _build_synthetic_fsys(story_decompressed)
    iso_bytes = _build_synthetic_iso(fsys_container)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / "synthetic.iso"
        tmp_path.write_bytes(iso_bytes)

        before_deck = deck_format.DeckFile(story_decompressed)
        assert before_deck.dpkm_entries == 2
        assert before_deck.trainer(1)["party_size"] == 1

        # Boosts dpkm_index 1's level and adds one brand-new ordinary team member to trainer 1 (which has 5
        # free slots) -- the exact shape that broke: a non-empty new_dpkm_entries forces grow_dpkm_section,
        # which changes DeckData_Story.bin's decompressed size.
        plan = {
            "level_assignment": {1: 13},
            "new_dpkm_entries": [{"species": 7, "level": 12, "moves": [1, 2, 3, 4]}],
            "team_slot_plan": [{"trainer_index": 1, "new_entry_pos": 0}],
        }

        # This is the actual regression check: before the fix, this raised AssertionError("resizing the
        # decompressed payload... Pass allow_decomp_resize=True") -- the exact error the player hit live.
        result = iso_patcher.write_enhanced_difficulty_patch(tmp_path, plan)
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
            story_entry = entries["DeckData_Story.bin"]
            story_raw = reader.read(deck_off + story_entry["data_off"], 0x10 + story_entry["comp_size"])
        finally:
            reader.close()

        new_decompressed = deck_format.lzss_decode(story_raw)
        after_deck = deck_format.DeckFile(new_decompressed)

        assert after_deck.dpkm_entries == before_deck.dpkm_entries + 1
        assert after_deck.dpkm_full(1)["level"] == 13
        assert after_deck.trainer(1)["party_size"] == 2
        new_member = after_deck.dpkm_full(2)
        assert new_member["species"] == 7
        assert new_member["level"] == 12
