"""ADDENDUM 128 (2026-09-11): end-to-end coverage of `iso_patcher.apply_patch`'s shop/mart pass against a
synthetic ISO whose only file is a `pocket_menu.fsys` shaped like the real one (entry #0 = LZSS-compressed
`pocket_menu.rel` (format 0x1C), entry #1 = a same-base-name `pocket_menu.msg` twin stored immediately after it
at the next 32-byte boundary). Verifies the whole chain the ADDENDUM 127 build got wrong: the REL is found,
structurally validated, patched only inside the MartItems pool, re-encoded with header-inclusive sizes into
EXACTLY its original footprint (the neighbouring msg entry is byte-identical afterwards), re-validated, and the
always-on diagnostic file carries the complete raw entry bytes."""
from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path

from ..tools import iso_patcher, xd_deck_format as deck_format, xd_rel_format as rel_format
from .test_addendum_128_rel_validation_and_mart_bounds import _build_synthetic_rel

FSYS_ALIGN = 0x20


def _build_pocket_menu_fsys(rel_decompressed: bytes) -> tuple[bytes, dict]:
    stream = deck_format.lzss_encode(rel_decompressed)
    comp_size = deck_format.LZSS_HEADER_SIZE + len(stream) + 24  # header-inclusive, with a little slack
    rel_blob = b"LZSS" + struct.pack(">II", len(rel_decompressed), comp_size) + b"\x00" * 4 + stream
    rel_blob += b"\x00" * (comp_size - len(rel_blob))
    msg_blob = b"MSG!" + bytes(range(1, 61))  # raw (uncompressed) twin, 64 bytes

    names = {"base": b"pocket_menu\x00", "rel_full": b"pocket_menu.rel\x00", "msg_full": b"pocket_menu.msg\x00"}
    name_table_off = 0x200
    base_off = name_table_off
    rel_full_off = base_off + len(names["base"])
    msg_full_off = rel_full_off + len(names["rel_full"])
    data0 = 0x300
    data1 = data0 + comp_size
    data1 += (-data1) % FSYS_ALIGN
    total = data1 + len(msg_blob)
    total += (-total) % FSYS_ALIGN
    fsys = bytearray(total)
    fsys[0:4] = b"FSYS"
    struct.pack_into(">I", fsys, iso_patcher.FSYS_ENTRY_COUNT_OFF, 2)
    rec0, rec1 = 0x80, 0x80 + 0x70
    struct.pack_into(">I", fsys, iso_patcher.FSYS_OFFSET_ARRAY_OFF, rec0)
    struct.pack_into(">I", fsys, iso_patcher.FSYS_OFFSET_ARRAY_OFF + 4, rec1)
    for rec, fmt, data_off, decomp, comp, full_off in (
        (rec0, 0x1C, data0, len(rel_decompressed), comp_size, rel_full_off),
        (rec1, 0x0A, data1, len(msg_blob), len(msg_blob), msg_full_off),
    ):
        fsys[rec + iso_patcher.FSYS_RECORD_FILE_FORMAT_OFF] = fmt
        struct.pack_into(">I", fsys, rec + iso_patcher.FSYS_RECORD_DATA_OFF, data_off)
        struct.pack_into(">I", fsys, rec + iso_patcher.FSYS_RECORD_DECOMP_SIZE_OFF, decomp)
        struct.pack_into(">I", fsys, rec + iso_patcher.FSYS_RECORD_COMP_SIZE_OFF, comp)
        struct.pack_into(">I", fsys, rec + iso_patcher.FSYS_RECORD_FULL_NAME_OFF, full_off)
        struct.pack_into(">I", fsys, rec + iso_patcher.FSYS_RECORD_NAME_OFF, base_off)
    fsys[base_off:base_off + len(names["base"])] = names["base"]
    fsys[rel_full_off:rel_full_off + len(names["rel_full"])] = names["rel_full"]
    fsys[msg_full_off:msg_full_off + len(names["msg_full"])] = names["msg_full"]
    fsys[data0:data0 + len(rel_blob)] = rel_blob
    fsys[data1:data1 + len(msg_blob)] = msg_blob
    return bytes(fsys), {"rec0": rec0, "data0": data0, "data1": data1, "comp_size": comp_size, "msg": msg_blob}


def _build_iso(fsys_container: bytes) -> bytes:
    fst_offset = 0x440
    file_offset = 0x800
    name = b"pocket_menu.fsys\x00"
    entry_count = 2
    string_table_off = entry_count * 12
    fst = bytearray(string_table_off + len(name))
    fst[0] = 1
    struct.pack_into(">I", fst, 8, entry_count)
    struct.pack_into(">I", fst, 12 + 4, file_offset)
    struct.pack_into(">I", fst, 12 + 8, len(fsys_container))
    fst[string_table_off:] = name
    iso = bytearray(file_offset + len(fsys_container))
    struct.pack_into(">I", iso, 0x424, fst_offset)
    struct.pack_into(">I", iso, 0x428, len(fst))
    iso[fst_offset:fst_offset + len(fst)] = fst
    iso[file_offset:] = fsys_container
    return bytes(iso)


class TestShopPassEndToEnd(unittest.TestCase):
    def test_shop_pass_patches_only_the_pool_keeps_the_footprint_and_writes_the_diagnostic(self) -> None:
        # 3 marts: [4, 13, 0] [17, 21, 0] [1, 0]; then junk that looks like relocation entries.
        pool = [4, 13, 0, 17, 21, 0, 1, 0]
        rel_dec = _build_synthetic_rel(pool, [0, 3, 6], [4, 8, 0x0104, 0x804E, 0xC5CE, 12])
        fsys, layout = _build_pocket_menu_fsys(rel_dec)
        iso = _build_iso(fsys)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src, out, seed = tmp / "src.iso", tmp / "out.iso", tmp / "seed.json"
            src.write_bytes(iso)
            seed.write_text(json.dumps({
                "shop_dummy_item_ids": [133, 134, 135],
                "shop_excluded_item_ids": [21],
                "known_item_id_names": {"4": "Poke Ball", "13": "Potion", "17": "Antidote", "1": "Master Ball"},
            }))
            summary = iso_patcher.apply_patch(src, out, seed)
            self.assertIsNone(summary["shop_randomization_error"])
            self.assertEqual(summary["shop_slots_patched"], 4)  # 4,13,17,1 (21 excluded)
            self.assertEqual(summary["shop_rel_structure"]["header"]["id"], 0x33)

            patched_iso = out.read_bytes()
            container_off = 0x800
            entries = iso_patcher.parse_fsys_all(patched_iso[container_off:])
            rel_entry = entries[0]
            new_comp = rel_entry["comp_size"]
            entry_raw = patched_iso[container_off + layout["data0"]: container_off + layout["data0"] + layout["comp_size"]]
            # header-inclusive sizes: record == LZSS header field == 16 + stream, never larger than before
            self.assertEqual(struct.unpack_from(">I", entry_raw, 8)[0], new_comp)
            self.assertLessEqual(new_comp, layout["comp_size"])
            redecoded = deck_format.lzss_decode(entry_raw)
            self.assertEqual(len(redecoded), len(rel_dec))
            rel_format.validate_rel_structure(redecoded)
            rel = rel_format.RelFile(redecoded, is_common=False)
            base = rel_format.mart_items_base(rel)
            new_pool = [struct.unpack_from(">H", redecoded, base + i * 2)[0] for i in range(len(pool))]
            # ADDENDUM 238c: berries are now dealt PER SHOP LINE within a group, so every group restarts at
            # dummy_item_ids[0] instead of continuing one global rotation. On this fixture the real shop table
            # claims mart 1 (Phenac 1F) and mart 2 (Phenac 2F); mart 0 is unclaimed and falls through to its
            # own single-mart group. So mart 0 gets 133, 134 (two distinct lines), and marts 1 and 2 each get
            # 133 for their single patchable line. Under the retired global rotation mart 2 landed on 135.
            self.assertEqual(new_pool, [133, 134, 0, 133, 21, 0, 133, 0])
            # every changed byte is inside the pool; the fake "next table" and the relocation lists are intact
            changed = rel_format.byte_diff_offsets(rel_dec, redecoded)
            end = rel_format.mart_pool_end_offset(rel)
            self.assertTrue(changed and all(base <= o < end for o in changed))
            # the neighbouring msg entry was not touched (no 16-byte overshoot past the REL's footprint)
            msg_off = container_off + layout["data1"]
            self.assertEqual(patched_iso[msg_off:msg_off + len(layout["msg"])], layout["msg"])
            # the always-on diagnostic exists and carries the whole original entry as hex
            diag = Path(summary["shop_diagnostic_file"])
            text = diag.read_text(encoding="utf-8")
            self.assertIn("Status: OK", text)
            self.assertIn("mart 2 (start 6", text)
            original_entry = iso[container_off + layout["data0"]: container_off + layout["data0"] + layout["comp_size"]]
            self.assertIn(original_entry[:32].hex(), text)
            dumped_hex = "".join(
                line.split(": ", 1)[1]
                for line in text.splitlines()
                if line.startswith("  ") and ": " in line and len(line.split(": ", 1)[0].strip()) == 6
            )
            self.assertIn(original_entry.hex(), dumped_hex)


if __name__ == "__main__":
    unittest.main()
