#!/usr/bin/env python3
"""
make_ability_test.py -- one-off diagnostic, not part of the real patch tool.

Like make_moves_test.py (species -> Pikachu, moves -> [Tackle,0,0,0]) but also forces Aferd's packed
nature_gender_ability byte (DPKM +0x1E) to ability slot 0 by clearing the low bit. Builds from a clean
source and writes the true re-encoded compressed size into both the entry's LZSS header and the FSYS record.

Usage:
    python make_ability_test.py --source "Pokemon XD (AP).ciso" --output "Pokemon XD (AP-test6).ciso"
"""
import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import iso_patcher as ip
import xd_deck_format as xdf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    source_path = Path(args.source).resolve()
    output_path = Path(args.output).resolve()

    if output_path == source_path:
        raise ValueError("output must differ from source")
    if output_path.exists() and not args.overwrite:
        raise FileExistsError(f"{output_path} already exists -- pass --overwrite")

    print(f"Copying {source_path} -> {output_path} ...")
    ip.chunked_copy(source_path, output_path)
    print("Copy done.")

    reader = ip.open_reader(output_path)
    try:
        fst = ip.parse_fst(reader)
        deck_archive_off, deck_archive_len = ip.find_by_basename(fst, "deck_archive.fsys")
        fsys_bytes = reader.read(deck_archive_off, deck_archive_len)
        fsys_entries = ip.parse_fsys(fsys_bytes)
        story_entry = fsys_entries["DeckData_Story.bin"]
        abs_entry_off = deck_archive_off + story_entry["data_off"]
        abs_record_comp_size_off = deck_archive_off + story_entry["record_off"] + ip.FSYS_RECORD_COMP_SIZE_OFF
        entry_raw_len = 0x10 + story_entry["comp_size"]
        entry_raw = reader.read(abs_entry_off, entry_raw_len)
    finally:
        reader.close()

    decompressed = xdf.lzss_decode(entry_raw)
    deck = xdf.DeckFile(decompressed)

    dpkm_index = 14
    before = deck.dpkm_full(dpkm_index)
    print(f"BEFORE (dpkm_index={dpkm_index}): {before}")

    buf = bytearray(decompressed)
    off = deck.dpkm_data + dpkm_index * 0x20
    struct.pack_into(">H", buf, off + 0x00, 25)              # species = Pikachu
    struct.pack_into(">HHHH", buf, off + 0x14, 33, 0, 0, 0)   # moves = [Tackle, 0, 0, 0]
    old_byte = buf[off + 0x1E]
    new_byte = old_byte & ~0x01                               # clear ability bit -> slot 0
    buf[off + 0x1E] = new_byte
    modified = bytes(buf)

    after = xdf.DeckFile(modified).dpkm_full(dpkm_index)
    print(f"nature_gender_ability byte: {old_byte} -> {new_byte}")
    print(f"AFTER:  {after}")

    new_entry, real_comp_size = xdf.patch_entry_decompressed(entry_raw, modified)
    print(f"Re-encoded stream: {real_comp_size} bytes (was allocated {story_entry['comp_size']} bytes).")

    redecoded = xdf.lzss_decode(new_entry)
    assert redecoded == modified, "round-trip mismatch -- refusing to write"
    print("Local round-trip verified OK.")

    writer = ip.open_writer(output_path)
    try:
        writer.write(abs_entry_off, new_entry)
        writer.write(abs_record_comp_size_off, struct.pack(">I", real_comp_size))
    finally:
        writer.close()
    print(f"Wrote {len(new_entry)} bytes at offset {abs_entry_off}.")
    print(f"Corrected FSYS record comp_size field at offset {abs_record_comp_size_off} to {real_comp_size}.")

    reader2 = ip.open_reader(output_path)
    try:
        check_raw = reader2.read(abs_entry_off, entry_raw_len)
        check_record_comp_size = struct.unpack(">I", reader2.read(abs_record_comp_size_off, 4))[0]
    finally:
        reader2.close()
    check_decompressed = xdf.lzss_decode(check_raw)
    check_rec = xdf.DeckFile(check_decompressed).dpkm_full(dpkm_index)
    print(f"VERIFIED ON DISK: {check_rec}")
    assert check_record_comp_size == real_comp_size, "FSYS record comp_size field did not stick"
    print(f"VERIFIED ON DISK: FSYS record comp_size = {check_record_comp_size}")
    print("Done. Species=Pikachu, moves=Tackle, ability forced to slot 0, comp_size fields corrected.")


if __name__ == "__main__":
    main()
