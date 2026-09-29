r"""
Pokemon XD: Gale of Darkness -- standalone offline patch-application tool, the other half of the apworld's
output. `generate_output` writes a small `.appxd` seed (a zip holding `seed.json`) and never touches the
player's ISO; this script runs locally against their own copy to produce a patched image, with no dependency
on the Archipelago core, `dolphin_memory_engine` or a running emulator.

Scope: trainer team species and movesets, and chest/shop/Poke Spot randomization. Item placement is the live
client's job. Teams must be patched on disc because a trainer's team is reloaded from disk data at battle
init, so species-only RAM edits don't stick.

SAFETY: the source ISO is never opened write-capable. Every entry point copies source -> a NEW destination
first (refusing the source path itself, or an existing output without --overwrite) and only ever opens the
destination for writing.

USAGE:
    python3 iso_patcher.py apply --source "Pokemon XD.iso" --output "Pokemon XD (AP).iso" --seed my_seed.appxd

    Always as a SCRIPT PATH, never `-m`: this module's home is inside the `pokemon_xd` package and its
    standalone fallback resolves siblings from the script's own directory, so `-m` gives it neither parent.
    Quote paths containing spaces. Source may be a plain .iso/.gcm or a .ciso, auto-detected from magic bytes;
    the seed may be the `.appxd` zip or a bare `seed.json`.
"""

from __future__ import annotations

import argparse
import json
import random
import os
import struct
import sys
import time
import zipfile
from pathlib import Path

# This file must import cleanly from inside a zip: an installed `.apworld` (e.g.
# `D:\Archipelago\custom_worlds\pokemon_xd.apworld`) is one, and `spec_from_file_location` bottoms out in a plain
# OS read that cannot see into it. So `__package__` is the signal, checked up front, rather than
# `try: relative / except ImportError:`, which cannot tell "no package" from "package present, module broken".
# The by-path branches are only for `python tools/iso_patcher.py`.
_PACKAGE_ROOT = __package__.rpartition(".")[0] if __package__ else ""

if __package__:
    from . import xd_deck_format as deck_format
    from . import xd_species_index as species_index
    from . import xd_rel_format as rel_format
else:  # pragma: no cover - standalone execution from within tools/
    try:
        import xd_deck_format as deck_format
        import xd_species_index as species_index
        import xd_rel_format as rel_format
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import xd_deck_format as deck_format
        import xd_species_index as species_index
        import xd_rel_format as rel_format


def _game_data_module(name: str):
    """Return `pokemon_xd/game_data/<name>.py`, package-first so the zip case works.

    The by-path branch can only load a game_data module with no package imports of its own:
    `shadow_move_slots` is dependency-free, `shop_stock` reaches for `..items` and would fail -- harmless,
    since standalone execution never reached that path anyway."""
    if _PACKAGE_ROOT:
        import importlib

        return importlib.import_module(f"{_PACKAGE_ROOT}.game_data.{name}")

    import importlib.util as _ilu

    path = Path(__file__).resolve().parent.parent / "game_data" / f"{name}.py"
    spec = _ilu.spec_from_file_location(f"_pokemon_xd_{name}_standalone", str(path))
    module = _ilu.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Shadow-move legality/power table (ADDENDUM 233), resolved once so every call site shares one handle.
_shadow_move_slots = _game_data_module("shadow_move_slots")


# Disc image reader/writer, duplicated from iso_bridge.py so nothing from that file is needed here. Keep in sync.

CISO_MAGIC = b"CISO"
CISO_HEADER_SIZE = 0x8000
CISO_MAP_SIZE = CISO_HEADER_SIZE - 4 - 4  # 0x7FF8
PROGRESS_EVERY_BYTES = 64 * 1024 * 1024


class CisoReader:
    def __init__(self, path: Path):
        self.f = open(path, "rb")
        magic = self.f.read(4)
        if magic != CISO_MAGIC:
            raise ValueError(f"{path} does not start with CISO magic (got {magic!r})")
        self.block_size = struct.unpack("<I", self.f.read(4))[0]
        block_map_raw = self.f.read(CISO_MAP_SIZE)
        self.block_present = list(block_map_raw)
        self.total_blocks = len(self.block_present)
        physical_index = 0
        self.virtual_to_physical: dict[int, int] = {}
        for i, present in enumerate(self.block_present):
            if present == 1:
                self.virtual_to_physical[i] = physical_index
                physical_index += 1
        self.virtual_size = self.total_blocks * self.block_size

    def read(self, virtual_offset: int, length: int) -> bytes:
        out = bytearray()
        pos = virtual_offset
        remaining = length
        while remaining > 0:
            block_idx = pos // self.block_size
            block_off = pos % self.block_size
            chunk_len = min(remaining, self.block_size - block_off)
            physical = self.virtual_to_physical.get(block_idx)
            if physical is None:
                out.extend(b"\x00" * chunk_len)
            else:
                file_pos = CISO_HEADER_SIZE + physical * self.block_size + block_off
                self.f.seek(file_pos)
                out.extend(self.f.read(chunk_len))
            pos += chunk_len
            remaining -= chunk_len
        return bytes(out)

    def close(self) -> None:
        self.f.close()


class PlainIsoReader:
    """For an uncompressed .iso/.gcm -- byte offset in the file IS the virtual disc offset."""

    def __init__(self, path: Path):
        self.f = open(path, "rb")
        self.f.seek(0, 2)
        self.virtual_size = self.f.tell()

    def read(self, virtual_offset: int, length: int) -> bytes:
        self.f.seek(virtual_offset)
        return self.f.read(length)

    def close(self) -> None:
        self.f.close()


class CisoWriter(CisoReader):
    """Read/write access to a CISO copy. Writes go to the already-allocated physical block for a virtual
    offset, and refuse outright if that block is a sparse hole -- real game-data regions like
    deck_archive.fsys are always physically present."""

    def __init__(self, path: Path):
        self.f = open(path, "r+b")
        magic = self.f.read(4)
        if magic != CISO_MAGIC:
            raise ValueError(f"{path} does not start with CISO magic (got {magic!r})")
        self.block_size = struct.unpack("<I", self.f.read(4))[0]
        block_map_raw = self.f.read(CISO_MAP_SIZE)
        self.block_present = list(block_map_raw)
        self.total_blocks = len(self.block_present)
        physical_index = 0
        self.virtual_to_physical = {}
        for i, present in enumerate(self.block_present):
            if present == 1:
                self.virtual_to_physical[i] = physical_index
                physical_index += 1
        self.virtual_size = self.total_blocks * self.block_size

    def write(self, virtual_offset: int, data: bytes) -> None:
        pos = virtual_offset
        remaining = len(data)
        src_off = 0
        while remaining > 0:
            block_idx = pos // self.block_size
            block_off = pos % self.block_size
            chunk_len = min(remaining, self.block_size - block_off)
            physical = self.virtual_to_physical.get(block_idx)
            if physical is None:
                raise ValueError(
                    f"virtual block {block_idx} (offset {pos}) has no physical storage in this CISO -- it's a "
                    "sparse/all-zero hole. Writing there would require growing the file and rewriting the "
                    "block map, which this tool deliberately does not support (and should never be needed for "
                    "real game-data regions)."
                )
            file_pos = CISO_HEADER_SIZE + physical * self.block_size + block_off
            self.f.seek(file_pos)
            self.f.write(data[src_off:src_off + chunk_len])
            pos += chunk_len
            remaining -= chunk_len
            src_off += chunk_len
        self.f.flush()

    def ensure_region_allocated(self, virtual_offset: int, length: int) -> list[int]:
        """The one opt-in path allowed to grow the CISO's block map (`write()` still refuses holes): each hole
        in the range gets a zero-filled physical block appended and its block-present byte flipped immediately.
        Present blocks are untouched. Returns the newly allocated indices. Format invariant: the Nth present block by virtual index always occupies physical slot N, because a
        reader recomputes physical_index from scratch by scanning present blocks in increasing virtual order.
        So appending is only safe strictly after the highest present block -- claiming a hole with present data
        after it makes a reopened reader compute different positions, and the write appears to vanish. This
        refuses anything else."""
        if length <= 0:
            return []
        first_block = virtual_offset // self.block_size
        last_block = (virtual_offset + length - 1) // self.block_size
        if last_block >= self.total_blocks:
            raise ValueError(
                f"region [{virtual_offset}, {virtual_offset + length}) spans block {last_block}, beyond this "
                f"CISO's virtual block count ({self.total_blocks}) -- refusing to invent new virtual address "
                "space that doesn't already exist in this disc image's own header."
            )
        highest_present = max((i for i, p in enumerate(self.block_present) if p), default=-1)
        if first_block <= highest_present:
            raise RuntimeError(
                f"refusing to allocate blocks [{first_block}, {last_block}] -- block {highest_present} (or "
                "another block with a higher virtual index) is already present, so appending new physical "
                "data at the end of the file would break this CISO's physical-order-matches-virtual-order "
                "invariant and corrupt data on the next read. Only a run strictly AFTER every currently-"
                "present block can be safely claimed this way."
            )
        newly_allocated = []
        for block_idx in range(first_block, last_block + 1):
            if self.block_present[block_idx]:
                continue
            physical_index = len(self.virtual_to_physical)
            file_pos = CISO_HEADER_SIZE + physical_index * self.block_size
            self.f.seek(file_pos)
            self.f.write(b"\x00" * self.block_size)
            self.block_present[block_idx] = 1
            self.virtual_to_physical[block_idx] = physical_index
            self.f.seek(8 + block_idx)  # magic(4) + block_size(4) + block_present[block_idx]
            self.f.write(bytes([1]))
            newly_allocated.append(block_idx)
        self.f.flush()
        return newly_allocated


class PlainIsoWriter(PlainIsoReader):
    def __init__(self, path: Path):
        self.f = open(path, "r+b")
        self.f.seek(0, 2)
        self.virtual_size = self.f.tell()

    def write(self, virtual_offset: int, data: bytes) -> None:
        self.f.seek(virtual_offset)
        self.f.write(data)
        self.f.flush()

    def ensure_region_allocated(self, virtual_offset: int, length: int) -> list[int]:
        """No-op: a plain .iso/.gcm has no block map and seek-past-EOF + write already zero-fills the gap.
        Present so callers can treat both writers identically."""
        return []


def _detect_and_open(path: Path, mode: str):
    with open(path, "rb") as probe:
        magic = probe.read(4)
    is_ciso = magic == CISO_MAGIC
    if mode == "r":
        return CisoReader(path) if is_ciso else PlainIsoReader(path)
    if mode == "w":
        return CisoWriter(path) if is_ciso else PlainIsoWriter(path)
    raise ValueError(mode)


def open_reader(path: Path):
    return _detect_and_open(path, "r")


def open_writer(path: Path):
    return _detect_and_open(path, "w")


def chunked_copy(src: Path, dest: Path, chunk_size: int = 16 * 1024 * 1024) -> int:
    """Full-file copy with progress printouts -- the mandatory first step of `apply_patch()`. Never opens
    `src` in a write-capable mode."""
    src_size = src.stat().st_size
    # Format comes from magic bytes, never the name; logged because players otherwise blame the extension.
    with open(src, "rb") as _probe:
        _fmt = "CISO (block-mapped)" if _probe.read(4) == CISO_MAGIC else "plain ISO/GCM"
    print(f"Source image format: {_fmt} -- detected from the file's magic bytes, not its extension.")
    print(f"Copying {src} ({src_size / 1e6:.1f} MB) -> {dest} ...")
    t0 = time.time()
    copied = 0
    next_progress_at = PROGRESS_EVERY_BYTES
    with open(src, "rb") as fsrc, open(dest, "wb") as fdst:
        while True:
            chunk = fsrc.read(chunk_size)
            if not chunk:
                break
            fdst.write(chunk)
            copied += len(chunk)
            if copied >= next_progress_at:
                elapsed = time.time() - t0
                rate = copied / elapsed / 1e6 if elapsed > 0 else 0
                print(f"  {copied / 1e6:.1f} / {src_size / 1e6:.1f} MB ({elapsed:.1f}s, ~{rate:.0f} MB/s)")
                next_progress_at += PROGRESS_EVERY_BYTES
    elapsed = time.time() - t0
    print(f"Copy done: {dest} ({dest.stat().st_size / 1e6:.1f} MB in {elapsed:.1f}s)")
    return copied


# GameCube FST parsing, byte-exact per the standard disc layout. A generic lookup rather than the hardcoded
# deck_archive.fsys offset earlier work measured (531229248), wrong for another disc revision or region.

BOOT_HEADER_READ_LEN = 0x440  # comfortably covers the fst_offset/fst_size fields at 0x0424/0x0428
FST_OFFSET_FIELD = 0x0424
FST_SIZE_FIELD = 0x0428
FST_ENTRY_SIZE = 12
FST_RECORD_FILE_OFFSET_OFF = 4  # within one 12-byte FST record: field2 (file_offset for a file entry)
FST_RECORD_FILE_LENGTH_OFF = 8  # within one 12-byte FST record: field3 (file_length for a file entry)


def parse_fst(reader) -> dict[str, tuple[int, int, int]]:
    """Returns {path: (file_offset, file_length, record_abs_off)} for every FILE entry, keyed by both full
    path ("misc/deck_archive.fsys") and bare filename. A bare name is only added if unclaimed; see
    find_by_basename() for the ambiguity-safe lookup. Directories are walked but not returned.
    `record_abs_off` is the absolute ISO offset of the file's own 12-byte FST record, so
    `+ FST_RECORD_FILE_OFFSET_OFF` / `+ FST_RECORD_FILE_LENGTH_OFF` are where its disc-level offset and
    length live -- needed only when relocating or resizing a whole disc-level file."""
    boot = reader.read(0, BOOT_HEADER_READ_LEN)
    fst_offset = struct.unpack_from(">I", boot, FST_OFFSET_FIELD)[0]
    fst_size = struct.unpack_from(">I", boot, FST_SIZE_FIELD)[0]
    fst_bytes = reader.read(fst_offset, fst_size)

    def read_entry(i: int) -> tuple[int, int, int, int]:
        base = i * FST_ENTRY_SIZE
        flag = fst_bytes[base]
        name_off = int.from_bytes(fst_bytes[base + 1:base + 4], "big")
        field2 = struct.unpack_from(">I", fst_bytes, base + 4)[0]
        field3 = struct.unpack_from(">I", fst_bytes, base + 8)[0]
        return flag, name_off, field2, field3

    # Root entry (index 0) is always a directory; its own "field3" (next_index) is the total entry count.
    _root_flag, _root_name_off, _root_parent, num_entries = read_entry(0)
    string_table_off = num_entries * FST_ENTRY_SIZE

    def read_name(name_off: int) -> str:
        start = string_table_off + name_off
        end = fst_bytes.index(b"\x00", start)
        return fst_bytes[start:end].decode("ascii", errors="replace")

    files: dict[str, tuple[int, int, int]] = {}
    path_parts: list[str] = []
    dir_end_stack: list[int] = []  # end index (exclusive) for each currently-open directory, innermost last

    i = 1
    while i < num_entries:
        while dir_end_stack and i >= dir_end_stack[-1]:
            dir_end_stack.pop()
            path_parts.pop()
        flag, name_off, field2, field3 = read_entry(i)
        name = read_name(name_off)
        if flag == 1:  # directory: field2=parent_index (unused here), field3=next_index (end of subtree)
            path_parts.append(name)
            dir_end_stack.append(field3)
            i += 1
        else:  # file: field2=file_offset, field3=file_length
            full_path = "/".join(path_parts + [name])
            record_abs_off = fst_offset + i * FST_ENTRY_SIZE
            files[full_path] = (field2, field3, record_abs_off)
            i += 1
    return files


def find_by_basename(files: dict[str, tuple[int, int, int]], basename: str) -> tuple[int, int, int]:
    """Look up a file by bare filename, whatever directory it sits in. KeyError if absent, ValueError if two
    files share the name -- never silently picks one."""
    matches = [(path, span) for path, span in files.items() if path.rsplit("/", 1)[-1] == basename]
    if not matches:
        raise KeyError(f"no file named {basename!r} found on this disc")
    if len(matches) > 1:
        raise ValueError(
            f"{basename!r} is ambiguous on this disc -- found at {[p for p, _ in matches]}; "
            "pass a full path instead of a bare filename."
        )
    return matches[0][1]


def _find_rel_entry(
    fsys_entries: dict[str, dict], container_label: str, container_basename: str | None = None
) -> tuple[str, dict]:
    """Locate the one REL pointer-table entry in a `parse_fsys()`-decoded container by naming convention.

    `common.fsys` uses the `_rel` suffix ("common_rel", live-verified). `pocket_menu.fsys` does not: its real
    entry list is ['pocket_menu', 'temp_csr', 'uv_pkm_panel_00'..'05', 'uv_pkm_ribbon_00',
    'uv_pkm_status_00'..'02', 'uv_str_item_00'], where every name but the first reads as a UI texture. So a bare
    base-name match is a FALLBACK only, and a reasoned guess rather than a confirmed one."""
    matches = [(name, entry) for name, entry in fsys_entries.items() if "rel" in name.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            f"{container_label} has more than one entry with 'rel' in its name -- can't tell which is the "
            f"real REL pointer table without a live ISO check: {[n for n, _ in matches]}."
        )
    if container_basename is not None and container_basename in fsys_entries:
        return container_basename, fsys_entries[container_basename]
    raise KeyError(
        f"{container_label} has no entry with 'rel' in its name, and no entry named "
        f"{container_basename!r} either -- expected exactly one REL pointer-table entry (mirroring "
        f"common.fsys's own 'common_rel'), found none among: {sorted(fsys_entries)}. This needs a live ISO "
        "check to identify the real entry name."
    )


def find_free_region(writer, length: int, *, block_align: int = 32) -> int:
    """Find an offset for an unused region of at least `length` bytes. Relocating the one growing file touches
    exactly one FST record and leaves every other file where it is, rather than cascading every offset.
    CISO: only the run strictly after the highest-index present block is ever offered -- physical block order
    must follow virtual order (see `CisoWriter.ensure_region_allocated`), so an interior hole with present data
    after it corrupts the next read. RuntimeError if that trailing run is too short.
    Plain .iso/.gcm: no block map, so "free" means past current EOF.
    """
    if isinstance(writer, CisoWriter):
        need_blocks = -(-length // writer.block_size)  # ceil division
        highest_present = max((i for i, p in enumerate(writer.block_present) if p), default=-1)
        run_start = highest_present + 1
        run_len = writer.total_blocks - run_start
        if run_len >= need_blocks:
            return run_start * writer.block_size
        raise RuntimeError(
            f"no free trailing region of {length} bytes ({need_blocks} blocks of {writer.block_size}) found "
            f"after the last currently-present block (index {highest_present} of {writer.total_blocks}) -- "
            "this CISO's disc image genuinely has no room after its own used data to relocate the grown "
            "deck_archive.fsys container into."
        )
    offset = writer.virtual_size
    if offset % block_align:
        offset += block_align - (offset % block_align)
    return offset


# .fsys container parsing. Format documented in pokemon-xd-iso-patch-progress.md.

FSYS_ENTRY_COUNT_OFF = 0x0C
FSYS_OFFSET_ARRAY_OFF = 0x60
FSYS_RECORD_DATA_OFF = 0x04
FSYS_RECORD_DECOMP_SIZE_OFF = 0x08
FSYS_RECORD_COMP_SIZE_OFF = 0x14
FSYS_RECORD_NAME_OFF = 0x24
FSYS_RECORD_FILE_FORMAT_OFF = 0x02  # 1-byte file type ("File Format")
FSYS_RECORD_FULL_NAME_OFF = 0x1C  # pointer to the full "name.ext" string, when present
FSYS_ENTRY_ALIGN = 32  # every real entry's data_off in the captured containers is an exact multiple of 32,
                        # with zero exceptions -- see rebuild_fsys_container_grown.


def parse_fsys_all(fsys_bytes: bytes) -> list[dict]:
    """Like `parse_fsys` but returns every entry as a list in record order, plus `file_format` (1-byte type at
    record +0x02) and `full_name` (the "name.ext" string at the +0x1C pointer, or None).
    `parse_fsys` keys by the extension-less base name at +0x24, so two entries sharing a base name silently
    overwrite each other and the LAST record wins. In `pocket_menu.fsys` the survivor decodes to 22x22-texture
    descriptors, not the mart REL -- which is why this list form exists."""
    if fsys_bytes[0:4] != b"FSYS":
        raise ValueError(f"expected FSYS magic at offset 0, got {fsys_bytes[0:4]!r}")
    entry_count = struct.unpack_from(">I", fsys_bytes, FSYS_ENTRY_COUNT_OFF)[0]
    out: list[dict] = []
    for i in range(entry_count):
        record_off = struct.unpack_from(">I", fsys_bytes, FSYS_OFFSET_ARRAY_OFF + i * 4)[0]
        data_off = struct.unpack_from(">I", fsys_bytes, record_off + FSYS_RECORD_DATA_OFF)[0]
        decomp_size = struct.unpack_from(">I", fsys_bytes, record_off + FSYS_RECORD_DECOMP_SIZE_OFF)[0]
        comp_size = struct.unpack_from(">I", fsys_bytes, record_off + FSYS_RECORD_COMP_SIZE_OFF)[0]
        name_off = struct.unpack_from(">I", fsys_bytes, record_off + FSYS_RECORD_NAME_OFF)[0]
        name_end = fsys_bytes.index(b"\x00", name_off)
        name = fsys_bytes[name_off:name_end].decode("ascii", errors="replace")
        file_format = fsys_bytes[record_off + FSYS_RECORD_FILE_FORMAT_OFF]
        full_name = None
        try:
            full_off = struct.unpack_from(">I", fsys_bytes, record_off + FSYS_RECORD_FULL_NAME_OFF)[0]
            if 0 < full_off < len(fsys_bytes):
                full_end = fsys_bytes.index(b"\x00", full_off)
                cand = fsys_bytes[full_off:full_end].decode("ascii", errors="replace")
                if cand and all(32 <= ord(c) < 127 for c in cand) and len(cand) < 128:
                    full_name = cand
        except (ValueError, struct.error):
            full_name = None
        out.append({
            "index": i,
            "name": name,
            "full_name": full_name,
            "file_format": file_format,
            "data_off": data_off,
            "decomp_size": decomp_size,
            "comp_size": comp_size,
            "record_off": record_off,
        })
    return out


def parse_fsys(fsys_bytes: bytes) -> dict[str, dict]:
    """Returns {entry_name: {"data_off", "decomp_size", "comp_size", "record_off"}} for every entry in one
    .fsys container; all offsets are absolute within `fsys_bytes`.
    `record_off + FSYS_RECORD_COMP_SIZE_OFF` is where the entry's declared compressed size lives IN THE
    CONTAINER -- a separate field from the same-named one inside the entry's own LZSS payload header. A caller
    that changes an entry's real compressed size must write both, or the container and payload disagree."""
    if fsys_bytes[0:4] != b"FSYS":
        raise ValueError(f"expected FSYS magic at offset 0, got {fsys_bytes[0:4]!r}")
    entry_count = struct.unpack_from(">I", fsys_bytes, FSYS_ENTRY_COUNT_OFF)[0]
    entries: dict[str, dict] = {}
    for i in range(entry_count):
        record_off = struct.unpack_from(">I", fsys_bytes, FSYS_OFFSET_ARRAY_OFF + i * 4)[0]
        data_off = struct.unpack_from(">I", fsys_bytes, record_off + FSYS_RECORD_DATA_OFF)[0]
        decomp_size = struct.unpack_from(">I", fsys_bytes, record_off + FSYS_RECORD_DECOMP_SIZE_OFF)[0]
        comp_size = struct.unpack_from(">I", fsys_bytes, record_off + FSYS_RECORD_COMP_SIZE_OFF)[0]
        name_off = struct.unpack_from(">I", fsys_bytes, record_off + FSYS_RECORD_NAME_OFF)[0]
        name_end = fsys_bytes.index(b"\x00", name_off)
        name = fsys_bytes[name_off:name_end].decode("ascii", errors="replace")
        entries[name] = {
            "data_off": data_off,
            "decomp_size": decomp_size,
            "comp_size": comp_size,
            "record_off": record_off,
        }
    return entries


def real_entry_span(entries: dict[str, dict], name: str, container_len: int) -> tuple[int, int]:
    """Returns `(start, end)` -- the real safe on-disk range this entry occupies, bounded by the next entry's
    `data_off` (or `container_len`), never by `16 + comp_size`. In the real captured `deck_archive.fsys` some pairs (e.g. `DeckData_DarkPokemon.bin` and its `_EU.bin`,
    identical comp/decomp sizes) have a declared footprint overlapping the next entry's data by a few bytes --
    the disc-build tool shared identical trailing compressed bytes. So `16 + comp_size` is wrong both as a copy
    boundary and as a did-this-change boundary; the next `data_off` holds regardless of overlap or padding."""
    target_off = entries[name]["data_off"]
    later = sorted(e["data_off"] for e in entries.values() if e["data_off"] > target_off)
    end = later[0] if later else container_len
    return target_off, end


def _grew_against_real_span(
    container_bytes: bytes, entry_name: str, new_entry_raw: bytes, grew: bool
) -> bool:
    """Re-answer "does this need the growth path" against the real on-disk span, since
    `patch_entry_decompressed`'s `grew` compares against the OLD DECLARED `comp_size`. One-directional on
    purpose: True can become False when the exact-fit blob fits the real gap, but a False
    never becomes True -- that case needs the trim-and-retry only the caller can do. The 32-byte padding
    `rebuild_fsys_container_grown` applies is deliberately not applied here, or a blob equal to the real span
    would report up to 31 bytes of growth nothing needs."""
    if not grew:
        return False
    entries = parse_fsys(container_bytes)
    start, end = real_entry_span(entries, entry_name, len(container_bytes))
    return len(new_entry_raw) > (end - start)


def _refuse_in_place_overrun(container_bytes: bytes, entry_name: str, new_entry_raw: bytes) -> None:
    """An in-place write must never pass the real next-entry `data_off`: declared footprints in this container
    can overlap the next entry's data, so the declared size is not a safe bound. Raises rather than truncating
    -- not fitting here means the growth decision was wrong, and writing less would corrupt a neighbour."""
    entries = parse_fsys(container_bytes)
    start, end = real_entry_span(entries, entry_name, len(container_bytes))
    limit = end - start
    if len(new_entry_raw) > limit:
        raise RuntimeError(
            f"in-place write for {entry_name} ({len(new_entry_raw)} bytes) would exceed its real on-disk "
            f"span to the next entry ({limit} bytes) -- this should have been caught as a growth case; "
            "refusing rather than risk corrupting a neighboring entry."
        )


def rebuild_fsys_container_grown(container_bytes: bytes, target_entry_name: str, new_entry_blob: bytes) -> bytes:
    """Rebuild a whole .fsys container with one entry replaced by `new_entry_blob`, which must be strictly
    larger than that entry's real on-disk span. Every entry past the target shifts forward by `delta` via
    literal byte-copying, so no padding/alignment/overlap convention has to be rediscovered:

        new_container = container_bytes[:target_data_off] + new_entry_blob + container_bytes[next_entry_data_off:]

    `old_span` is the real gap to the next `data_off`, not `16 + comp_size`: `DeckData_DarkPokemon.bin`'s
    declared footprint (16+1084 = 1100) runs 12 bytes into `DeckData_DarkPokemon_EU.bin`'s header, so the
    declared size would discard bytes the neighbour needs.

    `new_entry_blob` is zero-padded to a multiple of 32 first. Every `data_off` in the real captured
    `deck_archive.fsys` and `common.fsys` is 32-aligned with zero exceptions and the game's disc-read code
    relies on it: a real 5-new-Shadow edit produced `delta=5`, which knocked every downstream entry off its
    boundary and gave `_fsysForegroundTask:ERROR_FILEOPEN` while decoding correctly offline. The padding is
    inert, since the record's `comp_size` still declares the true length.

    Shifted entries' `data_off` fields are rewritten; the target's record is the caller's job. Total length
    grows by `delta`, so the caller must relocate the container and update BOTH fields of its outer FST record."""
    entries = parse_fsys(container_bytes)
    if target_entry_name not in entries:
        raise KeyError(f"{target_entry_name!r} not found in this container's {len(entries)} entries")
    target_data_off, next_entry_data_off = real_entry_span(entries, target_entry_name, len(container_bytes))
    old_span = next_entry_data_off - target_data_off
    # Keep every downstream data_off 32-aligned; see docstring.
    if len(new_entry_blob) % FSYS_ENTRY_ALIGN:
        new_entry_blob = new_entry_blob + b"\x00" * (FSYS_ENTRY_ALIGN - len(new_entry_blob) % FSYS_ENTRY_ALIGN)
    new_footprint = len(new_entry_blob)
    delta = new_footprint - old_span
    if delta <= 0:
        raise ValueError(
            f"new_entry_blob ({new_footprint} bytes) is not larger than {target_entry_name}'s real on-disk "
            f"span to the next entry ({old_span} bytes) -- use the plain in-place write path instead of this "
            "function when growth isn't actually needed."
        )

    new_container = bytearray(
        container_bytes[:target_data_off] + new_entry_blob + container_bytes[next_entry_data_off:]
    )

    for name, entry in entries.items():
        if name == target_entry_name or entry["data_off"] <= target_data_off:
            continue
        new_data_off = entry["data_off"] + delta
        struct.pack_into(">I", new_container, entry["record_off"] + FSYS_RECORD_DATA_OFF, new_data_off)

    assert len(new_container) == len(container_bytes) + delta
    return bytes(new_container)


# Real-move-usage extraction.

def extract_story_trainer_moves(source_path: Path) -> list[dict]:
    """READ-ONLY. Returns every real trainer's ordinary (DPKM) team from `DeckData_Story.bin`, including each
    member's equipped moves (`dpkm_full()`'s `moves`, +0x14), which `data/deckdata_story_trainers.json` never
    captured.

    Supplies a whitelist of moves a real vanilla trainer already uses safely. "Can learn by leveling" is not
    "some vanilla trainer attacks with it": XD has no wild encounters and every moveset is hand-authored, so a
    learnset move may never be exercised in the shipped game. Trainer 26's randomized Treecko froze on Pound
    (`wzx_hataku_damage.fsys` DVDOpen-retry-looping) with the disc data verified byte-identical to vanilla.
    Returns `[{"index", "team": [{"dpkm_index", "species", "level", "moves"}, ...]}, ...]`, DPKM slots
    only."""
    source_path = Path(source_path).resolve()
    reader = open_reader(source_path)
    try:
        fst = parse_fst(reader)
        deck_off, deck_len, _ = find_by_basename(fst, "deck_archive.fsys")
        deck_bytes = reader.read(deck_off, deck_len)
        deck_entries = parse_fsys(deck_bytes)
        story = deck_entries["DeckData_Story.bin"]
        story_raw = deck_bytes[story["data_off"]: story["data_off"] + 0x10 + story["comp_size"]]
    finally:
        reader.close()
    story_decompressed = deck_format.lzss_decode(story_raw)
    deck = deck_format.DeckFile(story_decompressed)

    trainers: list[dict] = []
    for t in deck.all_trainers():
        team = []
        for slot in t["team"]:
            if slot["kind"] != "DPKM":
                continue
            full = deck.dpkm_full(slot["dpkm_index"])
            team.append({
                "dpkm_index": slot["dpkm_index"],
                "species": full["species"],
                "level": full["level"],
                "moves": full["moves"],
            })
        if team:
            trainers.append({"index": t["index"], "team": team})
    return trainers


# Seed loading

def load_seed(seed_path: Path) -> dict:
    """Accepts either a bare seed.json, or a .appxd (or any zip) containing one."""
    if zipfile.is_zipfile(seed_path):
        with zipfile.ZipFile(seed_path) as zf:
            with zf.open("seed.json") as f:
                return json.load(f)
    with open(seed_path, encoding="utf-8") as f:
        return json.load(f)


# The actual patch: trainer-team species randomization inside DeckData_Story.bin

def apply_trainer_patch(
    decompressed: bytes,
    deck: deck_format.DeckFile,
    species_assignment: dict[int, int] | None,
    moves_assignment: dict[int, list[int]] | None,
) -> bytes:
    """Returns a new decompressed DeckData_Story.bin with species and/or moveset edits applied in one pass --
    both target the same entry, so doing them separately would mean two decompress/recompress round trips.

    `species_assignment`: `dpkm_index -> new_species`, u16BE at the DPKM record's +0x00. `moves_assignment`:
    `dpkm_index -> [4 move ids]`, 4x u16BE at +0x14, padded/truncated to 4 (0 = empty) in case a hand-edited
    seed.json differs. Either may be None; every other byte (level, IVs/EVs, item, happiness) is untouched."""
    buf = bytearray(decompressed)
    if species_assignment:
        for dpkm_index, new_species in species_assignment.items():
            off = deck.dpkm_data + dpkm_index * 0x20
            struct.pack_into(">H", buf, off, new_species)
    if moves_assignment:
        for dpkm_index, moves in moves_assignment.items():
            off = deck.dpkm_data + dpkm_index * 0x20 + 0x14
            padded = (list(moves) + [0, 0, 0, 0])[:4]
            struct.pack_into(">HHHH", buf, off, *padded)
    return bytes(buf)


def apply_team_padding_edit(
    decompressed: bytes,
    deck: deck_format.DeckFile,
    trainer_index: int,
    new_dpkm_index: int,
    species: int,
    level: int,
    moves: list[int] | None = None,
) -> bytes:
    """Give one trainer one additional team member; the diagnostic-scale building block, not the seed-driven
    feature.

    `new_dpkm_index` must be an unused DPKM entry (species reads 0). The measured free list in the real
    DeckData_Story.bin is `[0, 15, 64, 68, 69, 71, 76, 83, 324, 330, 331, 334, 340, 348]`, minus index 0, which
    is the reserved sentinel in the DTNR array. Other DPKM fields stay at the free entry's all-zero sentinel. Fills the first empty DTNR team slot and
    leaves `shadow_mask` alone: an unused slot's bit is already clear and this adds an ordinary member."""
    buf = bytearray(decompressed)
    trainer = deck.trainer(trainer_index)
    if trainer is None:
        raise ValueError(f"trainer index {trainer_index} is an empty/unused DTNR slot -- nothing to pad")
    if trainer["party_size"] >= 6:
        raise ValueError(f"trainer index {trainer_index} already has a full 6-Pokemon team")
    used_slots = {member["slot"] for member in trainer["team"]}
    new_slot = next(slot for slot in range(6) if slot not in used_slots)

    existing_species, _existing_level = deck.dpkm_species_level(new_dpkm_index)
    if existing_species != 0:
        raise ValueError(
            f"dpkm_index {new_dpkm_index} is not free (its species field already reads {existing_species}) -- "
            "refusing to overwrite an existing Pokemon's data. See this project's capacity analysis for the "
            "real list of currently-free DPKM indices."
        )

    dtnr_base = deck.dtnr_data + trainer_index * 0x38
    struct.pack_into(">H", buf, dtnr_base + 0x1C + new_slot * 2, new_dpkm_index)

    dpkm_off = deck.dpkm_data + new_dpkm_index * 0x20
    struct.pack_into(">H", buf, dpkm_off + 0x00, species)
    struct.pack_into(">B", buf, dpkm_off + 0x02, level)
    if moves:
        padded = (list(moves) + [0, 0, 0, 0])[:4]
        struct.pack_into(">HHHH", buf, dpkm_off + 0x14, *padded)
    return bytes(buf)


def apply_team_padding_borrow_edit(
    decompressed: bytes,
    deck: deck_format.DeckFile,
    trainer_index: int,
    borrow_dpkm_index: int,
) -> bytes:
    """Safer sibling of `apply_team_padding_edit()` that writes no new DPKM data: it points the trainer's
    next-empty DTNR slot at `borrow_dpkm_index`, an already-populated entry, adding a second pointer to it.
    The real DeckData_Story.bin has zero free DPKM entries, so the other function can never succeed against it.

    A DTNR record's team-slot array is a fixed 6 x u16BE block whatever the party size, so the decompressed
    size does not change and the growth path is almost certainly not needed. The borrowed member is not unique:
    this checks whether the game accepts a trainer with more members than it shipped with."""
    buf = bytearray(decompressed)
    trainer = deck.trainer(trainer_index)
    if trainer is None:
        raise ValueError(f"trainer index {trainer_index} is an empty/unused DTNR slot -- nothing to pad")
    if trainer["party_size"] >= 6:
        raise ValueError(f"trainer index {trainer_index} already has a full 6-Pokemon team")
    used_slots = {member["slot"] for member in trainer["team"]}
    new_slot = next(slot for slot in range(6) if slot not in used_slots)

    borrow_species, _borrow_level = deck.dpkm_species_level(borrow_dpkm_index)
    if borrow_species == 0:
        raise ValueError(
            f"dpkm_index {borrow_dpkm_index} has no real data (its species field reads 0) -- refusing to "
            "borrow an empty/sentinel entry as a team member. Pick a dpkm_index that's already in use by a "
            "real trainer or shadow Pokemon."
        )

    dtnr_base = deck.dtnr_data + trainer_index * 0x38
    struct.pack_into(">H", buf, dtnr_base + 0x1C + new_slot * 2, borrow_dpkm_index)
    return bytes(buf)


# Genuine DPKM-section growth: unlike everything above, this changes the DECOMPRESSED section layout.

def grow_dpkm_section(decompressed: bytes, deck: deck_format.DeckFile, new_entries: list[dict]) -> tuple[bytes, list[int]]:
    """Append `len(new_entries)` new DPKM records to the end of the DPKM section, growing it past its
    823-entry count -- the only way to create a genuinely new Pokemon, since the real ISO has no free
    (species==0) entries.

    Each entry needs `"species"` and `"level"`; optional keys mirror `DeckFile.dpkm_full()`'s names and
    default to the all-zero shape real free entries have. `ai_role` defaults to 1: 0 was never observed on a
    real battle-used Pokemon. Returns `(new_decompressed, new_dpkm_indices)`. Riskier than everything else: every other edit only changes the COMPRESSED footprint, while this
    changes the decompressed layout -- the DPKM header's entry count (+0x08) and byte size (+0x04) grow and
    DTAI/DSTR shift. `DeckFile.__init__` copes by walking the chain by declared size; whether the GAME reads
    the count dynamically is untested. Boot-crash is a live possibility, so use a disposable copy."""
    old_dpkm_entries = deck.dpkm_entries
    new_indices = [old_dpkm_entries + i for i in range(len(new_entries))]

    new_records = bytearray()
    for entry in new_entries:
        rec = bytearray(0x20)
        struct.pack_into(">H", rec, 0x00, entry["species"])
        rec[0x02] = entry["level"]
        rec[0x03] = entry.get("happiness", 0)
        struct.pack_into(">H", rec, 0x04, entry.get("item", 0))
        rec[0x06] = entry.get("ai_role", 1)
        rec[0x07] = entry.get("is_key_strategic", 0)
        ivs = (list(entry.get("ivs", [])) + [0] * 6)[:6]
        rec[0x08:0x0E] = bytes(ivs)
        evs = (list(entry.get("evs", [])) + [0] * 6)[:6]
        rec[0x0E:0x14] = bytes(evs)
        moves = (list(entry.get("moves", [])) + [0, 0, 0, 0])[:4]
        struct.pack_into(">HHHH", rec, 0x14, *moves)
        struct.pack_into(">H", rec, 0x1C, entry.get("shininess", 0))
        rec[0x1E] = entry.get("nature_gender_ability", 0)
        rec[0x1F] = entry.get("combo_bitfield", 0)
        new_records += rec

    buf = bytearray(decompressed)
    insert_at = deck.dtai_hdr  # DTAI immediately follows DPKM's data -- insert right before it.
    buf[insert_at:insert_at] = bytes(new_records)

    new_dpkm_entries = old_dpkm_entries + len(new_entries)
    new_dpkm_size = deck.dpkm_size + len(new_records)
    struct.pack_into(">I", buf, deck.dpkm_hdr + 0x04, new_dpkm_size)
    struct.pack_into(">I", buf, deck.dpkm_hdr + 0x08, new_dpkm_entries)

    return bytes(buf), new_indices


def apply_team_padding_new_entry_edit(
    decompressed: bytes,
    deck: deck_format.DeckFile,
    trainer_index: int,
    species: int,
    level: int,
    moves: list[int] | None = None,
) -> tuple[bytes, int]:
    """`grow_dpkm_section` (one new entry) plus a DTNR team-slot write: a genuinely new team member rather
    than `apply_team_padding_borrow_edit`'s duplicate. See `grow_dpkm_section` for the risk.

    Returns `(new_decompressed, new_dpkm_index)`. Raises if the trainer is empty or already full."""
    trainer = deck.trainer(trainer_index)
    if trainer is None:
        raise ValueError(f"trainer index {trainer_index} is an empty/unused DTNR slot -- nothing to pad")
    if trainer["party_size"] >= 6:
        raise ValueError(f"trainer index {trainer_index} already has a full 6-Pokemon team")
    used_slots = {member["slot"] for member in trainer["team"]}
    new_slot = next(slot for slot in range(6) if slot not in used_slots)

    grown_decompressed, new_indices = grow_dpkm_section(
        decompressed, deck, [{"species": species, "level": level, "moves": moves or []}]
    )
    new_dpkm_index = new_indices[0]

    buf = bytearray(grown_decompressed)
    dtnr_base = deck.dtnr_data + trainer_index * 0x38
    struct.pack_into(">H", buf, dtnr_base + 0x1C + new_slot * 2, new_dpkm_index)
    return bytes(buf), new_dpkm_index


# "Enhanced difficulty": ramp-based bulk team padding + level boost + Shadow Pokemon across all 232 trainers.

def apply_level_boost(decompressed: bytes, deck: deck_format.DeckFile, level_assignment: dict[int, int]) -> bytes:
    """Write a new `level` byte (DPKM record +0x02) per `dpkm_index -> new_level`. Nothing else changes and
    the file's size is fixed, so none of `grow_dpkm_section`'s risk applies."""
    buf = bytearray(decompressed)
    for dpkm_index, new_level in level_assignment.items():
        off = deck.dpkm_data + dpkm_index * 0x20 + 0x02
        buf[off] = max(1, min(100, new_level))
    return bytes(buf)


def apply_shadow_level_boost(ddpk_decompressed: bytes, ddpk: deck_format.DarkPokemonFile,
                             shadow_level_assignment: "dict[int, int]") -> bytes:
    """The DDPK counterpart of `apply_level_boost`: a new `shadow_level` byte (DDPK record +0x02) per
    `ddpk_index -> new_level`, in place, no resize. A Shadow Pokemon's level is stored twice -- here and in the DPKM record its `story_deck_index` points at --
    and the two are normally equal, so moving one without the other leaves a Shadow disagreeing with itself.
    Refuses an out-of-range index rather than writing past the section."""
    buf = bytearray(ddpk_decompressed)
    for ddpk_index, new_level in shadow_level_assignment.items():
        if not 0 <= ddpk_index < ddpk.ddpk_entries:
            raise ValueError(
                f"shadow_level_assignment references ddpk_index {ddpk_index}, but this ISO's "
                f"DeckData_DarkPokemon.bin has {ddpk.ddpk_entries} entries -- this seed was likely generated "
                "against a different game version/region than this ISO."
            )
        buf[ddpk.ddpk_data + ddpk_index * 0x18 + 0x02] = max(1, min(100, new_level))
    return bytes(buf)


def apply_shadow_catch_rate(ddpk_decompressed: bytes, ddpk: deck_format.DarkPokemonFile,
                            target: int = 0xFF) -> "tuple[bytes, int]":
    """Raise every in-use Shadow Pokemon's `catch_rate_override` (+0x01) to `target`. Returns
    `(new_decompressed, entries_raised)`. Separate from the species stats table because a Shadow snag is never checked against the species catch
    rate -- the DDPK record carries its own override, vanilla mostly 190. Scope is every in-use entry read off
    the file right now, not a generation-time list, because Shadow Expansion and Enhanced Difficulty bring new
    entries into use earlier in the same run. Index 0 is the reserved sentinel. Never lowers."""
    target = max(1, min(0xFF, int(target)))
    buf = bytearray(ddpk_decompressed)
    raised = 0
    in_use = 0
    for index in range(1, ddpk.ddpk_entries):
        off = ddpk.ddpk_data + index * 0x18
        if off + 0x18 > len(buf):
            raise ValueError(
                f"DDPK entry {index} ends at 0x{off + 0x18:X}, past this DeckData_DarkPokemon.bin's "
                f"0x{len(buf):X} decompressed bytes -- refusing to write off the end of the file"
            )
        if buf[off + 0x03] == 0:
            continue                      # free slot -- nothing is catchable there
        in_use += 1
        if buf[off + 0x01] >= target:
            continue                      # already at the target -- counted as covered, not as raised
        buf[off + 0x01] = target
        raised += 1
    return bytes(buf), (raised, in_use)


def apply_dark_pokemon_edit(ddpk_decompressed: bytes, ddpk: deck_format.DarkPokemonFile, assignments: list[dict]) -> bytes:
    """Write new Shadow Pokemon data into existing unused (`in_use == 0`) DDPK entries. The real
    `DeckData_DarkPokemon.bin` has 44 free ones, so this file never needs growing. Each assignment needs `"ddpk_index"` (free) and `"story_deck_index"` (a real DPKM index, usually just
    allocated by `grow_dpkm_section`, where this Shadow's species/level live). Optional `"shadow_level"`
    (defaults to that entry's level), `"shadow_moves"`, and the per-field overrides, each defaulting to a real
    observed value rather than a guess."""
    buf = bytearray(ddpk_decompressed)
    for a in assignments:
        idx = a["ddpk_index"]
        off = ddpk.ddpk_data + idx * 0x18
        existing = ddpk.ddpk_full(idx)
        if existing["in_use"] != 0:
            raise ValueError(f"DDPK index {idx} is already in use -- refusing to overwrite a real Shadow Pokemon")
        buf[off + 0x00] = a.get("flee_weight", 128)
        buf[off + 0x01] = a.get("catch_rate_override", 190)
        buf[off + 0x02] = a.get("shadow_level", 0)  # caller should normally pass the real level explicitly
        buf[off + 0x03] = 128  # in_use -- the one real value observed for every used entry in the real file
        struct.pack_into(">H", buf, off + 0x06, a["story_deck_index"])
        struct.pack_into(">H", buf, off + 0x08, a.get("heart_gauge", 2000))
        struct.pack_into(">H", buf, off + 0x0A, a.get("bonus_exp", 0))
        moves = (list(a.get("shadow_moves", [])) + [0, 0, 0, 0])[:4]
        # A Shadow cannot use its DPKM entry's ordinary moves until the heart gauge opens, so these four ids
        # are its whole offense. Checked here, where every caller funnels through, because the mistake caught is
        # a DPKM level-up moveset (ids 1-354) handed over instead. All 83 vanilla entries pass both halves.
        _sms = _shadow_move_slots
        nonzero = [m for m in moves if m]
        stray = [m for m in nonzero if m not in _sms.SHADOW_MOVE_OBSERVED_SLOTS]
        if stray:
            raise ValueError(
                f"DDPK index {idx}: shadow_moves {moves} contains {stray}, which are not Shadow move ids "
                f"(the real ones are {min(_sms.ALL_SHADOW_MOVE_IDS)}-{max(_sms.ALL_SHADOW_MOVE_IDS)}) -- an "
                "ordinary DPKM moveset was almost certainly passed here by mistake."
            )
        if nonzero and not _sms.has_attacking_move(nonzero):
            raise ValueError(
                f"DDPK index {idx}: shadow_moves {moves} are all status moves -- this Shadow Pokemon would "
                "have no way to deal damage until it is purified."
            )
        struct.pack_into(">HHHH", buf, off + 0x0C, *moves)
        buf[off + 0x14] = a.get("aggression", 4)
        buf[off + 0x15] = a.get("always_flee", 0)
    return bytes(buf)


def compute_enhanced_difficulty_plan(
    deck: deck_format.DeckFile, ddpk: deck_format.DarkPokemonFile, level_boost: int = 3
) -> dict:
    """Compute the ramp-based enhanced-difficulty plan without writing anything, so it can be tested apart
    from the byte-writing. Ramp: trainer 1-5 gains +1 member, 6-15 gains +2, 16-232 fills to 6, all capped at 6. Existing members get
    a flat `level_boost` (default +3, clamped 1-100); new members get the trainer's ORIGINAL average plus
    `level_boost`, landing in the same band as the boosted team. Up to 44 new slots (the real free DDPK count)
    become Shadow, one per trainer, spent on the 16-232 band in ascending order. Species are deterministic, not
    per-seed.

    Returns `{"level_assignment", "new_dpkm_entries", "team_slot_plan", "ddpk_slots_used"}`; `new_entry_pos`
    indexes `new_dpkm_entries`, which `grow_dpkm_section` allocates in the same order."""
    level_assignment: dict[int, int] = {}
    new_dpkm_entries: list[dict] = []
    team_slot_plan: list[dict] = []

    free_ddpk = [i for i in range(ddpk.ddpk_entries) if ddpk.ddpk_full(i)["in_use"] == 0 and i != 0]
    ddpk_slots_used: list[int] = []

    for trainer_index in range(1, deck.dtnr_entries):
        trainer = deck.trainer(trainer_index)
        if trainer is None:
            continue
        dpkm_members = [m for m in trainer["team"] if m["kind"] == "DPKM"]
        if dpkm_members:
            avg_level = round(sum(m["level"] for m in dpkm_members) / len(dpkm_members))
        else:
            avg_level = 10  # all-Shadow team, nothing to average -- floor
        for m in dpkm_members:
            level_assignment[m["dpkm_index"]] = m["level"] + level_boost

        current_size = trainer["party_size"]
        if 1 <= trainer_index <= 5:
            add_count = max(0, min(1, 6 - current_size))
        elif 6 <= trainer_index <= 15:
            add_count = max(0, min(2, 6 - current_size))
        else:
            add_count = max(0, 6 - current_size)
        if add_count == 0:
            continue

        new_member_level = min(100, avg_level + level_boost)
        wants_shadow = (16 <= trainer_index <= 232) and bool(free_ddpk)
        for i in range(add_count):
            entry_pos = len(new_dpkm_entries)
            species = (trainer_index * 191 + i * 97 + 29) % 411 + 1
            moves = [
                (trainer_index * 5 + i * 3 + 1) % 354 + 1, (trainer_index * 7 + i * 11 + 2) % 354 + 1,
                (trainer_index * 13 + i * 17 + 3) % 354 + 1, (trainer_index * 19 + i * 23 + 5) % 354 + 1,
            ]
            new_dpkm_entries.append({"species": species, "level": new_member_level, "moves": moves})
            if wants_shadow and i == 0 and free_ddpk:
                ddpk_index = free_ddpk.pop(0)
                ddpk_slots_used.append(ddpk_index)
                team_slot_plan.append({"trainer_index": trainer_index, "kind": "shadow", "new_entry_pos": entry_pos,
                                        "ddpk_index": ddpk_index})
            else:
                team_slot_plan.append({"trainer_index": trainer_index, "kind": "ordinary", "new_entry_pos": entry_pos})

    return {
        "level_assignment": level_assignment,
        "new_dpkm_entries": new_dpkm_entries,
        "team_slot_plan": team_slot_plan,
        "ddpk_slots_used": ddpk_slots_used,
    }


def apply_enhanced_difficulty_edit(
    decompressed: bytes,
    deck: deck_format.DeckFile,
    ddpk_decompressed: bytes,
    ddpk: deck_format.DarkPokemonFile,
    plan: dict,
) -> tuple[bytes, bytes]:
    """Applies a plan from `compute_enhanced_difficulty_plan` to real decompressed `DeckData_Story.bin` and
    `DeckData_DarkPokemon.bin` blobs, in the correct order (level boost -> DPKM growth -> DTNR team-slot
    writes -> DDPK writes). Returns `(new_story_decompressed, new_dark_pokemon_decompressed)`."""
    boosted = apply_level_boost(decompressed, deck, plan["level_assignment"])
    boosted_deck = deck_format.DeckFile(boosted)  # re-parse: same layout, only level bytes changed

    grown, new_indices = grow_dpkm_section(boosted, boosted_deck, plan["new_dpkm_entries"])
    buf = bytearray(grown)

    used_slot_by_trainer: dict[int, set[int]] = {}
    for trainer_index in range(1, deck.dtnr_entries):
        t = deck.trainer(trainer_index)
        if t is not None:
            used_slot_by_trainer[trainer_index] = {m["slot"] for m in t["team"]}

    ddpk_assignments = []
    for step in plan["team_slot_plan"]:
        trainer_index = step["trainer_index"]
        used_slots = used_slot_by_trainer.setdefault(trainer_index, set())
        new_slot = next(slot for slot in range(6) if slot not in used_slots)
        used_slots.add(new_slot)
        dtnr_base = boosted_deck.dtnr_data + trainer_index * 0x38
        new_dpkm_index = new_indices[step["new_entry_pos"]]

        if step["kind"] == "ordinary":
            struct.pack_into(">H", buf, dtnr_base + 0x1C + new_slot * 2, new_dpkm_index)
        else:
            ddpk_index = step["ddpk_index"]
            struct.pack_into(">H", buf, dtnr_base + 0x1C + new_slot * 2, ddpk_index)
            shadow_mask_off = dtnr_base + 0x04
            buf[shadow_mask_off] |= (1 << new_slot)
            entry = plan["new_dpkm_entries"][step["new_entry_pos"]]
            ddpk_assignments.append({
                "ddpk_index": ddpk_index, "story_deck_index": new_dpkm_index,
                # Real Shadow ids, not the DPKM moveset: ordinary ids in these slots get no Shadow 2x and sit
                # where the game never uses them.
                "shadow_level": entry["level"],
                "shadow_moves": entry.get("shadow_moves") or _shadow_move_slots.choose_shadow_moves(
                    random.Random(new_dpkm_index), 2),
            })

    new_ddpk_decompressed = apply_dark_pokemon_edit(ddpk_decompressed, ddpk, ddpk_assignments)
    return bytes(buf), new_ddpk_decompressed


# Enhanced Difficulty, per-seed pipeline version. Ordinary-Pokemon-only: it never touches
# `DeckData_DarkPokemon.bin`, unlike `apply_enhanced_difficulty_edit` above. Shadow expansion is its own option.

def apply_enhanced_difficulty_story_edit(decompressed: bytes, deck: deck_format.DeckFile, plan: dict) -> bytes:
    """Apply a `build_enhanced_difficulty_plan()` plan to a decompressed `DeckData_Story.bin`: level boost,
    `grow_dpkm_section` for the new members, then a DTNR team-slot write each. Result goes straight to
    `write_deck_story_patch()`. Every `plan["team_slot_plan"]` entry here is implicitly ordinary -- no `"kind"` field to branch on, unlike
    `compute_enhanced_difficulty_plan`'s output."""
    boosted = apply_level_boost(decompressed, deck, plan["level_assignment"])
    boosted_deck = deck_format.DeckFile(boosted)  # re-parse: same layout, only level bytes changed

    grown, new_indices = grow_dpkm_section(boosted, boosted_deck, plan["new_dpkm_entries"])
    buf = bytearray(grown)

    used_slot_by_trainer: dict[int, set[int]] = {}
    for trainer_index in range(1, deck.dtnr_entries):
        t = deck.trainer(trainer_index)
        if t is not None:
            used_slot_by_trainer[trainer_index] = {m["slot"] for m in t["team"]}

    for step in plan["team_slot_plan"]:
        trainer_index = step["trainer_index"]
        used_slots = used_slot_by_trainer.setdefault(trainer_index, set())
        new_slot = next(slot for slot in range(6) if slot not in used_slots)
        used_slots.add(new_slot)
        dtnr_base = boosted_deck.dtnr_data + trainer_index * 0x38
        new_dpkm_index = new_indices[step["new_entry_pos"]]
        struct.pack_into(">H", buf, dtnr_base + 0x1C + new_slot * 2, new_dpkm_index)

    return bytes(buf)


def write_enhanced_difficulty_patch(output_path: Path, plan: dict) -> dict:
    """Read `DeckData_Story.bin` fresh from `output_path` (always a copy, never the original), apply `plan`
    via `apply_enhanced_difficulty_story_edit`, then write and verify through `write_deck_story_patch`.

    The `shadow_level_assignment` branch writes DDPK levels, and there are THREE copies of
    `DeckData_DarkPokemon.bin` on the disc -- the game reads `common.fsys`'s two -- so all three are written.
    Returns `{"grew", "levels_boosted", "new_members_added", "trainers_padded"}`."""
    output_path = Path(output_path).resolve()

    reader = open_reader(output_path)
    try:
        fst = parse_fst(reader)
        deck_off, deck_len, deck_record_off = find_by_basename(fst, "deck_archive.fsys")
        deck_fsys_bytes = reader.read(deck_off, deck_len)
        deck_entries = parse_fsys(deck_fsys_bytes)
        story_entry = deck_entries["DeckData_Story.bin"]
        story_raw = reader.read(deck_off + story_entry["data_off"], 0x10 + story_entry["comp_size"])
        # Only read when there is something to write, so a plan with no Shadow levels stays single-entry.
        dark_entry = dark_raw = None
        if plan.get("shadow_level_assignment"):
            dark_entry = deck_entries["DeckData_DarkPokemon.bin"]
            dark_raw = reader.read(deck_off + dark_entry["data_off"], 0x10 + dark_entry["comp_size"])
    finally:
        reader.close()

    story_decompressed = deck_format.lzss_decode(story_raw)
    deck = deck_format.DeckFile(story_decompressed)

    unknown_indices = sorted(i for i in plan["level_assignment"] if i >= deck.dpkm_entries)
    if unknown_indices:
        raise ValueError(
            f"seed's enhanced_difficulty_plan references dpkm_index values out of range for this ISO's "
            f"DeckData_Story.bin ({deck.dpkm_entries} entries): "
            f"{unknown_indices[:10]}{'...' if len(unknown_indices) > 10 else ''} "
            "-- this seed was likely generated against a different game version/region than this ISO."
        )
    trainer_indices = sorted({step["trainer_index"] for step in plan["team_slot_plan"]})
    unknown_trainers = [t for t in trainer_indices if deck.trainer(t) is None]
    if unknown_trainers:
        raise ValueError(
            f"seed's enhanced_difficulty_plan references trainer_index values with no team on this ISO: "
            f"{unknown_trainers[:10]}{'...' if len(unknown_trainers) > 10 else ''} "
            "-- this seed was likely generated against a different game version/region than this ISO."
        )

    new_decompressed = apply_enhanced_difficulty_story_edit(story_decompressed, deck, plan)

    # `allow_decomp_resize=True` because growing the DPKM section shifts DTAI/DSTR and changes the decompressed
    # size, which `patch_entry_decompressed` refuses by default; harmless when nothing grows.
    shadow_levels = plan.get("shadow_level_assignment") or {}
    if shadow_levels and dark_raw is not None:
        dark_decompressed = deck_format.lzss_decode(dark_raw)
        ddpk = deck_format.DarkPokemonFile(dark_decompressed)
        new_dark = apply_shadow_level_boost(dark_decompressed, ddpk, shadow_levels)
        patch_result = write_fsys_multi_entry_patch(
            output_path, deck_off, deck_len, deck_record_off, deck_fsys_bytes,
            [
                {"name": "DeckData_Story.bin", "entry_raw": story_raw,
                 "new_decompressed": new_decompressed, "allow_decomp_resize": True},
                {"name": "DeckData_DarkPokemon.bin", "entry_raw": dark_raw,
                 "new_decompressed": new_dark, "allow_decomp_resize": False},
            ],
        )
    else:
        patch_result = write_deck_story_patch(
            output_path, deck_off, deck_len, deck_record_off,
            deck_fsys_bytes, story_entry, story_raw, new_decompressed,
            allow_decomp_resize=True,
        )
    # The same byte in the copy the game reads: common.fsys's DeckData_DarkPokemon.bin and its _EU variant. The
    # ISO is re-read fresh rather than reusing Pass 1's bytes, since Pass 1 may have relocated a container.
    common_written = 0
    if shadow_levels:
        reader = open_reader(output_path)
        try:
            fst2 = parse_fst(reader)
            common_off, common_len, common_record_off = find_by_basename(fst2, "common.fsys")
            common_fsys_bytes = reader.read(common_off, common_len)
            common_entries = parse_fsys(common_fsys_bytes)
            missing = [n for n in ("DeckData_DarkPokemon.bin", "DeckData_DarkPokemon_EU.bin")
                       if n not in common_entries]
            if missing:
                raise ValueError(
                    "common.fsys on this ISO is missing " + ", ".join(missing) + " -- refusing to guess at a "
                    "different disc layout. Found: " + ", ".join(sorted(common_entries))
                )
            common_dark_entry = common_entries["DeckData_DarkPokemon.bin"]
            common_dark_raw = reader.read(
                common_off + common_dark_entry["data_off"], 0x10 + common_dark_entry["comp_size"])
            common_eu_entry = common_entries["DeckData_DarkPokemon_EU.bin"]
            common_eu_raw = reader.read(
                common_off + common_eu_entry["data_off"], 0x10 + common_eu_entry["comp_size"])
        finally:
            reader.close()

        common_dark_decompressed = deck_format.lzss_decode(common_dark_raw)
        common_eu_decompressed = deck_format.lzss_decode(common_eu_raw)
        new_common_dark = apply_shadow_level_boost(
            common_dark_decompressed, deck_format.DarkPokemonFile(common_dark_decompressed), shadow_levels)
        new_common_eu = apply_shadow_level_boost(
            common_eu_decompressed, deck_format.DarkPokemonFile(common_eu_decompressed), shadow_levels)
        write_fsys_multi_entry_patch(
            output_path, common_off, common_len, common_record_off, common_fsys_bytes,
            [
                {"name": "DeckData_DarkPokemon.bin", "entry_raw": common_dark_raw,
                 "new_decompressed": new_common_dark, "allow_decomp_resize": False},
                {"name": "DeckData_DarkPokemon_EU.bin", "entry_raw": common_eu_raw,
                 "new_decompressed": new_common_eu, "allow_decomp_resize": False},
            ],
            container_name="common.fsys",
        )
        common_written = len(shadow_levels) * 2

    return {
        "grew": patch_result["grew"],
        "levels_boosted": len(plan["level_assignment"]),
        "shadow_levels_written": len(shadow_levels),
        "shadow_levels_written_common_fsys": common_written,
        "new_members_added": len(plan["new_dpkm_entries"]),
        "trainers_padded": len(trainer_indices),
    }


# Always-catch, as a single instruction in the executable. From a community Action Replay code
# `06QM-1V0H-C6RG9 / DB0T-3ZXB-NUH6D`, decrypted `04219324 48000154`: AR type 04 is a 32-bit RAM write with the
# address OR'd by 0x80000000, giving 0x80219324, and 0x48000154 is `b +0x154`, an unconditional branch 340 bytes
# forward, over the capture-failure path.
#
# Code is the only place a guarantee can live: the catch rate is a byte in two tables, both capped at 255, and
# 255 is not certainty because the Gen III roll multiplies it by a health term worth a third at full HP.
# Colosseum hard-codes its tutorial capture, which is why XD's tutorial Teddiursa is certain at catch rate 120.
#
# A wrong offset here is arbitrary code, so this refuses unless the word there is the exact expected one, the
# jump lands in the same DOL section, and the write reads back.
DOL_OFFSET_FIELD = 0x0420
DOL_SECTION_COUNT = 18
DOL_FILE_OFFSETS = 0x00
DOL_LOAD_ADDRESSES = 0x48
DOL_SECTION_SIZES = 0x90

#: Straight from the decrypted AR code. Address and instruction word, nothing derived.
ALWAYS_CATCH_ADDRESS = 0x80219324
ALWAYS_CATCH_WORD = 0x48000154
# The guard names the exact word measured on the real disc, not a category: "is it a conditional branch" would
# accept any revision's, and the word there is not a conditional branch but a computed dispatch.
#: The word this address holds on the NTSC-U disc the AR code was written for. `bctr` (opcode 19, XO 528,
#: BO 20). Measured on a real ISO, 2026-09-20.
ALWAYS_CATCH_EXPECTED_WORD = 0x4E800420


# ADDENDUM 384: the experience formula's divisor, the one operand in it that is not a byte in a table.
#
#     0x80212C80  mullw r3,r3,r0     base_exp * level
#     0x80212C84  li    r0,7         <- this instruction's immediate
#     0x80212C8C  divw  r0,r3,r0     / 7
#
# Located by solving main.dol's load base from two functions this project had already documented -- `setExp`
# (`stw r4,0x20(r3); blr`) and `getLevel` (`lbz r3,0x11(r3); blr`), which agree on 0x800030A0 out of 49
# candidate pairings -- then confirming all nine documented accessors decode there, and taking the only two
# `li rX,7` instructions in the whole DOL that feed a division. The other one is a modulo on an unrelated
# halfword. The DOL's own section table puts 0x80212C84 at file offset 0x20FBE4, where the word reads
# 0x38000007. A measured award corroborates the formula: an Eevee at level 11 gained exactly 154, and
# 98 * 11 / 7 = 154.
#
# Only the immediate changes, so this is a one-instruction edit with no code cave and no branch, and every
# consequence is the game's own: levels, stat recalculation and the fanfare all happen where they always did.
EXP_DIVISOR_ADDRESS = 0x80212C84
#: `li r0,N`. The opcode and registers are fixed; N is the low halfword.
EXP_DIVISOR_WORD_BASE = 0x38000000
EXP_DIVISOR_EXPECTED_WORD = 0x38000007


def exp_divisor_word(divisor: int) -> int:
    return EXP_DIVISOR_WORD_BASE | (int(divisor) & 0xFFFF)


def exp_divisor_refusal(original_word: int, divisor: int) -> "str | None":
    """None when it is safe to write, else why not. Pure, so it is testable without an ISO."""
    if not 1 <= int(divisor) <= 7:
        return (f"divisor {divisor} is outside 1..7 -- 0 is an undefined `divw` on PowerPC and anything "
                f"above 7 would SLOW experience down, which this option never does")
    if original_word != EXP_DIVISOR_EXPECTED_WORD:
        return (f"the word at 0x{EXP_DIVISOR_ADDRESS:08X} is 0x{original_word:08X}, not the "
                f"0x{EXP_DIVISOR_EXPECTED_WORD:08X} (`li r0,7`) this replaces -- a different build or region")
    return None


def write_exp_divisor_patch(output_path: Path, divisor: int) -> dict:
    """Write the experience formula's divisor into `output_path`'s main.dol. Never raises.

    `{"applied", "reason", "address", "file_offset", "original", "divisor"}`. A refusal is a skipped feature,
    not a failed patch: the seed still works, experience is just the vanilla rate."""
    output_path = Path(output_path).resolve()
    result = {"applied": False, "reason": None, "address": EXP_DIVISOR_ADDRESS,
              "file_offset": None, "original": None, "divisor": int(divisor)}
    want = exp_divisor_word(divisor)
    try:
        reader = open_reader(output_path)
        try:
            dol_offset = struct.unpack(">I", reader.read(DOL_OFFSET_FIELD, 4))[0]
            sections = dol_sections(reader, dol_offset)
            holder = [sec for sec in sections if sec[2] <= EXP_DIVISOR_ADDRESS < sec[2] + sec[3]]
            if not holder:
                result["reason"] = (f"0x{EXP_DIVISOR_ADDRESS:08X} is not inside any section of this ISO's "
                                    "main.dol")
                return result
            _i, sec_file, sec_addr, _sec_len = holder[0]
            file_offset = dol_offset + sec_file + (EXP_DIVISOR_ADDRESS - sec_addr)
            original = struct.unpack(">I", reader.read(file_offset, 4))[0]
        finally:
            reader.close()
        result["file_offset"] = file_offset
        result["original"] = original
        if original == want:
            result["applied"] = True
            result["reason"] = "already patched"
            return result
        refusal = exp_divisor_refusal(original, divisor)
        if refusal:
            result["reason"] = refusal
            return result
        writer = open_writer(output_path)
        try:
            writer.write(file_offset, struct.pack(">I", want))
        finally:
            writer.close()
        verify = open_reader(output_path)
        try:
            back = struct.unpack(">I", verify.read(file_offset, 4))[0]
        finally:
            verify.close()
        if back != want:
            result["reason"] = "read-back verification failed -- the divisor did not stick"
            return result
        result["applied"] = True
        return result
    except Exception as exc:
        result["reason"] = f"{type(exc).__name__}: {exc}"
        return result


def _move_status_census() -> "dict[int, tuple[int, int]]":
    """`game_data.move_status.MOVE_STATUS`, through this file's usual package/loose-script fallback."""
    try:
        from ..game_data.move_status import MOVE_STATUS
    except ImportError:                                  # running as `python tools/iso_patcher.py`
        _package_root_on_path()
        from game_data.move_status import MOVE_STATUS    # type: ignore
    return MOVE_STATUS


def _package_root_on_path() -> None:
    """Put `<apworld>/pokemon_xd` on sys.path so the loose-script import fallbacks below work.

    Those fallbacks assume the package root is importable, which it is not under
    `python .../tools/iso_patcher.py`: sys.path[0] is `tools/` and `game_data` is its sibling. Without it the
    failure lands mid-patch, after the output ISO has been written to. Idempotent."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)


def dol_sections(reader, dol_offset: int) -> "list[tuple[int, int, int, int]]":
    """[(index, file_offset, load_address, length)] for every non-empty section of a GameCube main.dol."""
    head = reader.read(dol_offset, 0x100)
    out = []
    for i in range(DOL_SECTION_COUNT):
        file_off = struct.unpack_from(">I", head, DOL_FILE_OFFSETS + i * 4)[0]
        load_addr = struct.unpack_from(">I", head, DOL_LOAD_ADDRESSES + i * 4)[0]
        length = struct.unpack_from(">I", head, DOL_SECTION_SIZES + i * 4)[0]
        if length:
            out.append((i, file_off, load_addr, length))
    return out


def always_catch_refusal(original_word: int, load_address: int, length: int) -> "str | None":
    """None when it is safe to write, else the reason it is not. Pure, so it can be tested without an ISO."""
    if original_word != ALWAYS_CATCH_EXPECTED_WORD:
        return (f"the word at 0x{ALWAYS_CATCH_ADDRESS:08X} is 0x{original_word:08X}, not the "
                f"0x{ALWAYS_CATCH_EXPECTED_WORD:08X} this code replaces -- a different build or region")
    target = ALWAYS_CATCH_ADDRESS + (ALWAYS_CATCH_WORD & 0x03FFFFFC)
    if not load_address <= target < load_address + length:
        return (f"the patched branch would jump to 0x{target:08X}, outside the section it lives in")
    return None


def write_always_catch_code_patch(output_path: Path) -> dict:
    """Apply the always-catch instruction to `output_path`'s main.dol. Never raises; returns what it did.

    `{"applied": bool, "reason": str|None, "address": int, "file_offset": int|None, "original": int|None}`.
    A refusal is a skipped feature, not a failed patch -- see this section's header."""
    output_path = Path(output_path).resolve()
    result = {"applied": False, "reason": None, "address": ALWAYS_CATCH_ADDRESS,
              "file_offset": None, "original": None}
    try:
        reader = open_reader(output_path)
        try:
            dol_offset = struct.unpack(">I", reader.read(DOL_OFFSET_FIELD, 4))[0]
            sections = dol_sections(reader, dol_offset)
            holder = [s for s in sections if s[2] <= ALWAYS_CATCH_ADDRESS < s[2] + s[3]]
            if not holder:
                result["reason"] = (f"0x{ALWAYS_CATCH_ADDRESS:08X} is not inside any section of this ISO's "
                                    "main.dol")
                return result
            _i, sec_file, sec_addr, sec_len = holder[0]
            file_offset = dol_offset + sec_file + (ALWAYS_CATCH_ADDRESS - sec_addr)
            original = struct.unpack(">I", reader.read(file_offset, 4))[0]
        finally:
            reader.close()
        result["file_offset"] = file_offset
        result["original"] = original
        if original == ALWAYS_CATCH_WORD:
            result["applied"] = True
            result["reason"] = "already patched"
            return result
        refusal = always_catch_refusal(original, sec_addr, sec_len)
        if refusal:
            result["reason"] = refusal
            return result
        writer = open_writer(output_path)
        try:
            writer.write(file_offset, struct.pack(">I", ALWAYS_CATCH_WORD))
        finally:
            writer.close()
        verify = open_reader(output_path)
        try:
            back = struct.unpack(">I", verify.read(file_offset, 4))[0]
        finally:
            verify.close()
        if back != ALWAYS_CATCH_WORD:
            result["reason"] = "read-back verification failed -- the instruction did not stick"
            return result
        result["applied"] = True
        return result
    except Exception as exc:     # a diagnostic-grade feature must not sink an otherwise-good patch
        result["reason"] = f"{type(exc).__name__}: {exc}"
        return result


def write_max_catch_rate_shadow_patch(output_path: Path, target: int = 0xFF) -> dict:
    """Raise every in-use Shadow Pokemon's catch-rate override to `target` in all three DarkPokemon copies.

    Returns `{"archive_raised", "common_raised", "common_eu_raised"}`. Refuses rather than guessing if the
    entries are not where they were measured."""
    output_path = Path(output_path).resolve()

    # ---- Pass 1: deck_archive.fsys's own copy ----
    reader = open_reader(output_path)
    try:
        fst = parse_fst(reader)
        deck_off, deck_len, deck_record_off = find_by_basename(fst, "deck_archive.fsys")
        deck_fsys_bytes = reader.read(deck_off, deck_len)
        deck_entries = parse_fsys(deck_fsys_bytes)
        if "DeckData_DarkPokemon.bin" not in deck_entries:
            raise ValueError(
                "deck_archive.fsys on this ISO has no DeckData_DarkPokemon.bin -- refusing to guess at a "
                "different disc layout. Found: " + ", ".join(sorted(deck_entries))
            )
        dark_entry = deck_entries["DeckData_DarkPokemon.bin"]
        dark_raw = reader.read(deck_off + dark_entry["data_off"], 0x10 + dark_entry["comp_size"])
    finally:
        reader.close()

    dark_decompressed = deck_format.lzss_decode(dark_raw)
    new_dark, (archive_raised, archive_total) = apply_shadow_catch_rate(
        dark_decompressed, deck_format.DarkPokemonFile(dark_decompressed), target)
    write_fsys_multi_entry_patch(
        output_path, deck_off, deck_len, deck_record_off, deck_fsys_bytes,
        [{"name": "DeckData_DarkPokemon.bin", "entry_raw": dark_raw,
          "new_decompressed": new_dark, "allow_decomp_resize": False}],
    )

    # ---- Pass 2: common.fsys's two copies -- the ones the game reads ----
    reader = open_reader(output_path)
    try:
        fst2 = parse_fst(reader)
        common_off, common_len, common_record_off = find_by_basename(fst2, "common.fsys")
        common_fsys_bytes = reader.read(common_off, common_len)
        common_entries = parse_fsys(common_fsys_bytes)
        missing = [n for n in ("DeckData_DarkPokemon.bin", "DeckData_DarkPokemon_EU.bin")
                   if n not in common_entries]
        if missing:
            raise ValueError(
                "common.fsys on this ISO is missing " + ", ".join(missing) + " -- refusing to guess at a "
                "different disc layout. Found: " + ", ".join(sorted(common_entries))
            )
        common_dark_entry = common_entries["DeckData_DarkPokemon.bin"]
        common_dark_raw = reader.read(
            common_off + common_dark_entry["data_off"], 0x10 + common_dark_entry["comp_size"])
        common_eu_entry = common_entries["DeckData_DarkPokemon_EU.bin"]
        common_eu_raw = reader.read(
            common_off + common_eu_entry["data_off"], 0x10 + common_eu_entry["comp_size"])
    finally:
        reader.close()

    common_dark_decompressed = deck_format.lzss_decode(common_dark_raw)
    common_eu_decompressed = deck_format.lzss_decode(common_eu_raw)
    new_common_dark, (common_raised, common_total) = apply_shadow_catch_rate(
        common_dark_decompressed, deck_format.DarkPokemonFile(common_dark_decompressed), target)
    new_common_eu, (common_eu_raised, _eu_total) = apply_shadow_catch_rate(
        common_eu_decompressed, deck_format.DarkPokemonFile(common_eu_decompressed), target)
    write_fsys_multi_entry_patch(
        output_path, common_off, common_len, common_record_off, common_fsys_bytes,
        [
            {"name": "DeckData_DarkPokemon.bin", "entry_raw": common_dark_raw,
             "new_decompressed": new_common_dark, "allow_decomp_resize": False},
            {"name": "DeckData_DarkPokemon_EU.bin", "entry_raw": common_eu_raw,
             "new_decompressed": new_common_eu, "allow_decomp_resize": False},
        ],
        container_name="common.fsys",
    )

    return {
        "archive_raised": archive_raised,
        "common_raised": common_raised,
        "common_eu_raised": common_eu_raised,
        "common_in_use": common_total,
        "archive_in_use": archive_total,
    }


# Enhanced Difficulty, Mt. Battle extension: `DeckData_Hundred.bin` (Mt. Battle's 100-trainer table) instead of
# `DeckData_Story.bin`, same plan shape and edit function. Uses `write_fsys_multi_entry_patch()` with a one-entry
# list, since `write_deck_story_patch()` hardcodes "DeckData_Story.bin" including its verification messages.

def write_enhanced_difficulty_mt_battle_patch(output_path: Path, plan: dict) -> dict:
    """Same contract as `write_enhanced_difficulty_patch()`, against `DeckData_Hundred.bin`. `plan` must be
    built against `mtbattle_team_census()`'s output -- Mt. Battle has its OWN `trainer_index`/`dpkm_index`
    namespace, so a Story-table plan would either raise below or silently hit in-range indices that mean
    something else entirely. Returns `{"grew", "levels_boosted", "new_members_added", "trainers_padded"}`."""
    output_path = Path(output_path).resolve()

    reader = open_reader(output_path)
    try:
        fst = parse_fst(reader)
        deck_off, deck_len, deck_record_off = find_by_basename(fst, "deck_archive.fsys")
        deck_fsys_bytes = reader.read(deck_off, deck_len)
        deck_entries = parse_fsys(deck_fsys_bytes)
        hundred_entry = deck_entries["DeckData_Hundred.bin"]
        hundred_raw = reader.read(deck_off + hundred_entry["data_off"], 0x10 + hundred_entry["comp_size"])
    finally:
        reader.close()

    hundred_decompressed = deck_format.lzss_decode(hundred_raw)
    deck = deck_format.DeckFile(hundred_decompressed)

    unknown_indices = sorted(i for i in plan["level_assignment"] if i >= deck.dpkm_entries)
    if unknown_indices:
        raise ValueError(
            f"seed's mt_battle_enhanced_difficulty_plan references dpkm_index values out of range for this "
            f"ISO's DeckData_Hundred.bin ({deck.dpkm_entries} entries): "
            f"{unknown_indices[:10]}{'...' if len(unknown_indices) > 10 else ''} "
            "-- this seed was likely generated against a different game version/region than this ISO."
        )
    trainer_indices = sorted({step["trainer_index"] for step in plan["team_slot_plan"]})
    unknown_trainers = [t for t in trainer_indices if deck.trainer(t) is None]
    if unknown_trainers:
        raise ValueError(
            f"seed's mt_battle_enhanced_difficulty_plan references trainer_index values with no team on this "
            f"ISO's DeckData_Hundred.bin: {unknown_trainers[:10]}{'...' if len(unknown_trainers) > 10 else ''} "
            "-- this seed was likely generated against a different game version/region than this ISO."
        )

    new_decompressed = apply_enhanced_difficulty_story_edit(hundred_decompressed, deck, plan)

    edits = [{
        "name": "DeckData_Hundred.bin", "entry_raw": hundred_raw, "new_decompressed": new_decompressed,
        "allow_decomp_resize": True,
    }]
    patch_result = write_fsys_multi_entry_patch(
        output_path, deck_off, deck_len, deck_record_off, deck_fsys_bytes, edits,
    )
    return {
        "grew": patch_result["per_entry"]["DeckData_Hundred.bin"]["grew"],
        "levels_boosted": len(plan["level_assignment"]),
        "new_members_added": len(plan["new_dpkm_entries"]),
        "trainers_padded": len(trainer_indices),
    }


def write_deck_story_patch(
    output_path: Path,
    deck_archive_off: int,
    deck_archive_len: int,
    deck_archive_record_off: int,
    fsys_bytes: bytes,
    story_entry: dict,
    entry_raw: bytes,
    new_decompressed: bytes,
    allow_decomp_resize: bool = False,
) -> dict:
    """Shared write+read-back-verify for one DeckData_Story.bin edit inside `deck_archive.fsys`.

    Encodes the edit exactly once and branches on the returned `grew` afterward, never re-encoding to retry --
    that is what structurally rules out the old double-encode bug. A blob that does not fit rebuilds the
    container via `rebuild_fsys_container_grown()`, relocates it to free trailing space, then verifies both the
    grown entry and every other entry still decoding to what it did before. Returns `{"grew", "real_comp_size", "old_comp_size"}`, plus the new container offset/length when it grew."""
    abs_entry_off = deck_archive_off + story_entry["data_off"]
    abs_record_comp_size_off = deck_archive_off + story_entry["record_off"] + FSYS_RECORD_COMP_SIZE_OFF
    abs_record_decomp_size_off = deck_archive_off + story_entry["record_off"] + FSYS_RECORD_DECOMP_SIZE_OFF
    real_decomp_size = len(new_decompressed)

    new_entry_raw, real_comp_size, grew = deck_format.patch_entry_decompressed(
        entry_raw, new_decompressed, allow_grow=True, allow_decomp_resize=allow_decomp_resize
    )

    # "grew" has two meanings: `patch_entry_decompressed` compares against the OLD DECLARED `comp_size`, while
    # `rebuild_fsys_container_grown` measures the REAL span to the next `data_off`. They differ when the
    # container has slack, especially after an earlier pass shrank the declared size in place, and in that window
    # the growth path would refuse to relocate a container that need not grow. Re-check against the real span.
    grew = _grew_against_real_span(fsys_bytes, "DeckData_Story.bin", new_entry_raw, grew)
    result = {"grew": grew, "real_comp_size": real_comp_size, "old_comp_size": story_entry["comp_size"]}

    if not grew:
        # Never write past the real next-entry data_off, or a blob over it reaches into the neighbour.
        _refuse_in_place_overrun(fsys_bytes, "DeckData_Story.bin", new_entry_raw)
        # The LZSS header and the FSYS record keep separate copies of the compressed size, and whichever the
        # game consults must not be told to read past the real data into the zero padding -- that mismatch caused
        # the Aferd freeze and the Chobin crash. The decompressed-size copy is synced for the same reason.
        writer = open_writer(output_path)
        try:
            writer.write(abs_entry_off, new_entry_raw)
            writer.write(abs_record_comp_size_off, struct.pack(">I", real_comp_size))
            writer.write(abs_record_decomp_size_off, struct.pack(">I", real_decomp_size))
        finally:
            writer.close()

        verify_reader = open_reader(output_path)
        try:
            reread = verify_reader.read(abs_entry_off, len(new_entry_raw))
            reread_record_comp_size = verify_reader.read(abs_record_comp_size_off, 4)
            reread_record_decomp_size = verify_reader.read(abs_record_decomp_size_off, 4)
        finally:
            verify_reader.close()
        if reread != new_entry_raw:
            raise RuntimeError("read-back verification failed -- the trainer-data write did not stick")
        if deck_format.lzss_decode(reread) != new_decompressed:
            raise RuntimeError(
                "read-back verification failed -- re-decoded trainer-data bytes don't match the intended patch"
            )
        if struct.unpack(">I", reread_record_comp_size)[0] != real_comp_size:
            raise RuntimeError(
                "read-back verification failed -- DeckData_Story.bin's FSYS record comp_size didn't stick"
            )
        if struct.unpack(">I", reread_record_decomp_size)[0] != real_decomp_size:
            raise RuntimeError(
                "read-back verification failed -- DeckData_Story.bin's FSYS record decomp_size didn't stick"
            )
        return result

    # Growth path: rebuild the container with this entry grown, then relocate it.
    fsys_entries = parse_fsys(fsys_bytes)
    new_container = rebuild_fsys_container_grown(fsys_bytes, "DeckData_Story.bin", new_entry_raw)
    new_container_buf = bytearray(new_container)
    struct.pack_into(
        ">I", new_container_buf, story_entry["record_off"] + FSYS_RECORD_COMP_SIZE_OFF, real_comp_size
    )
    struct.pack_into(
        ">I", new_container_buf, story_entry["record_off"] + FSYS_RECORD_DECOMP_SIZE_OFF, real_decomp_size
    )
    new_container = bytes(new_container_buf)

    writer = open_writer(output_path)
    try:
        new_offset = find_free_region(writer, len(new_container))
        writer.ensure_region_allocated(new_offset, len(new_container))
        writer.write(new_offset, new_container)
        writer.write(deck_archive_record_off + FST_RECORD_FILE_OFFSET_OFF, struct.pack(">I", new_offset))
        writer.write(
            deck_archive_record_off + FST_RECORD_FILE_LENGTH_OFF, struct.pack(">I", len(new_container))
        )
    finally:
        writer.close()

    verify_reader = open_reader(output_path)
    try:
        reread_container = verify_reader.read(new_offset, len(new_container))
        reread_fst = parse_fst(verify_reader)
    finally:
        verify_reader.close()
    if reread_container != new_container:
        raise RuntimeError(
            "read-back verification failed -- the relocated, grown deck_archive.fsys container's on-disc "
            "bytes don't match what was written"
        )
    reread_off, reread_len, _ = find_by_basename(reread_fst, "deck_archive.fsys")
    if reread_off != new_offset or reread_len != len(new_container):
        raise RuntimeError(
            f"read-back verification failed -- deck_archive.fsys's FST record reads offset={reread_off}, "
            f"length={reread_len}; expected offset={new_offset}, length={len(new_container)}"
        )
    reread_entries = parse_fsys(reread_container)
    reread_story = reread_entries["DeckData_Story.bin"]
    reread_story_raw = reread_container[
        reread_story["data_off"]: reread_story["data_off"] + 0x10 + reread_story["comp_size"]
    ]
    if deck_format.lzss_decode(reread_story_raw) != new_decompressed:
        raise RuntimeError(
            "read-back verification failed -- re-decoded (relocated) trainer-data bytes don't match the "
            "intended patch"
        )
    if reread_story["decomp_size"] != real_decomp_size:
        raise RuntimeError(
            "read-back verification failed -- DeckData_Story.bin's FSYS record decomp_size didn't stick"
        )
    # Every other entry must still decode to exactly what it did before. Compared over each entry's real span,
    # not `16+comp_size`: declared footprints here overlap into the next entry, so the declared bound would
    # false-flag an untouched neighbour as soon as the entry after it is legitimately edited.
    for name in fsys_entries:
        if name == "DeckData_Story.bin":
            continue
        orig_start, orig_end = real_entry_span(fsys_entries, name, len(fsys_bytes))
        orig_raw = fsys_bytes[orig_start:orig_end]
        reread_start, reread_end = real_entry_span(reread_entries, name, len(reread_container))
        reread_raw = reread_container[reread_start:reread_end]
        if reread_raw != orig_raw:
            raise RuntimeError(
                f"read-back verification failed -- entry {name!r} inside deck_archive.fsys changed during "
                "growth/relocation, but it was never supposed to be touched"
            )
    result["new_container_offset"] = new_offset
    result["new_container_length"] = len(new_container)
    return result


def write_fsys_multi_entry_patch(
    output_path: Path,
    deck_archive_off: int,
    deck_archive_len: int,
    deck_archive_record_off: int,
    fsys_bytes: bytes,
    edits: list[dict],
    container_name: str = "deck_archive.fsys",
) -> dict:
    """`write_deck_story_patch()` over several entries in one FSYS container, for when `DeckData_Story.bin`
    and `DeckData_DarkPokemon.bin` change together. Separate from that function so the single-entry path stays
    untouched.

    The `deck_archive_*` parameters are just the target container's offset/length/FST-record-offset;
    `common.fsys` goes through here too, and `container_name` (default `"deck_archive.fsys"`) tells the growth
    path which basename to look up in the reread FST.

    `edits`: `{"name", "entry_raw", "new_decompressed", "allow_decomp_resize"}` per entry, encoded
    independently. If none grow, each is written in place; if any grows, the container is rebuilt and relocated
    ONCE, not once per entry, and a non-growing but changed entry's bytes are substituted into the rebuilt
    container before the single write. Returns `{"grew", "per_entry": {...}}`, plus the new container
    offset/length when it grew."""
    fsys_entries = parse_fsys(fsys_bytes)
    encoded = {}
    for edit in edits:
        name = edit["name"]
        new_entry_raw, real_comp_size, grew = deck_format.patch_entry_decompressed(
            edit["entry_raw"], edit["new_decompressed"], allow_grow=True,
            allow_decomp_resize=edit.get("allow_decomp_resize", False),
        )
        # A `grew=False` blob is zero-padded out to `16+old_comp_size`, which can exceed the entry's REAL span
        # when an overlapping next entry shrinks it -- DeckData_DarkPokemon.bin's real span is 1088 bytes,
        # limited by its 12-byte overlap with _EU.bin, against a 1100-byte declared footprint. Unhandled, that
        # reaches the in-place path and is refused there, which is safe but not a fix.
        if not grew:
            real_start, real_end = real_entry_span(fsys_entries, name, len(fsys_bytes))
            real_span_limit = real_end - real_start
            # Only when the padded blob misses the real span: trim to the exact-fit size (the trimmed bytes
            # were always meaningless padding) and re-check, escalating to growth only if that still misses.
            # The common case keeps the padded blob untouched.
            if len(new_entry_raw) > real_span_limit:
                # `real_comp_size` is header-inclusive, so it IS the exact-fit length.
                exact_fit = new_entry_raw[:real_comp_size]
                if len(exact_fit) > real_span_limit:
                    new_entry_raw = exact_fit
                    grew = True
                else:
                    new_entry_raw = exact_fit
        else:
            # Mirror image: `grew=True` only means the content exceeds the OLD DECLARED footprint, not the real
            # span. The two disagree when two separate passes in one `apply_patch()` run touch the same entry --
            # the first shrinks the declared comp_size in place, leaving the real span slack, and the second
            # re-encodes something bigger than the shrunk declaration but well inside that slack. A `grew=True`
            # blob is already exact-fit, so if it fits the real span this is an in-place write.
            grew = _grew_against_real_span(fsys_bytes, name, new_entry_raw, grew)
        encoded[name] = {
            "new_entry_raw": new_entry_raw,
            "real_comp_size": real_comp_size,
            "real_decomp_size": len(edit["new_decompressed"]),
            "new_decompressed": edit["new_decompressed"],
            "grew": grew,
            "old_comp_size": fsys_entries[name]["comp_size"],
        }

    any_grew = any(e["grew"] for e in encoded.values())
    result = {
        "grew": any_grew,
        "per_entry": {
            name: {"grew": e["grew"], "real_comp_size": e["real_comp_size"], "old_comp_size": e["old_comp_size"]}
            for name, e in encoded.items()
        },
    }

    if not any_grew:
        # Every entry fits its original allocation -- write each in place, no relocation. Guarded against the
        # real next-entry data_off, not `16+comp_size`, because declared footprints here overlap the next
        # entry's data (see real_entry_span).
        for name, e in encoded.items():
            _refuse_in_place_overrun(fsys_bytes, name, e["new_entry_raw"])
        writer = open_writer(output_path)
        try:
            for name, e in encoded.items():
                entry = fsys_entries[name]
                abs_entry_off = deck_archive_off + entry["data_off"]
                abs_comp_off = deck_archive_off + entry["record_off"] + FSYS_RECORD_COMP_SIZE_OFF
                abs_decomp_off = deck_archive_off + entry["record_off"] + FSYS_RECORD_DECOMP_SIZE_OFF
                writer.write(abs_entry_off, e["new_entry_raw"])
                writer.write(abs_comp_off, struct.pack(">I", e["real_comp_size"]))
                writer.write(abs_decomp_off, struct.pack(">I", e["real_decomp_size"]))
        finally:
            writer.close()

        verify_reader = open_reader(output_path)
        try:
            for name, e in encoded.items():
                entry = fsys_entries[name]
                abs_entry_off = deck_archive_off + entry["data_off"]
                reread = verify_reader.read(abs_entry_off, len(e["new_entry_raw"]))
                if reread != e["new_entry_raw"]:
                    raise RuntimeError(f"read-back verification failed -- {name}'s write did not stick")
                if deck_format.lzss_decode(reread) != e["new_decompressed"]:
                    raise RuntimeError(f"read-back verification failed -- {name} re-decoded content mismatch")
        finally:
            verify_reader.close()
        return result

    # Growth path: rebuild once per growing entry, substitute any changed non-growing entry, relocate ONCE.
    new_container = fsys_bytes
    for name, e in encoded.items():
        if e["grew"]:
            new_container = rebuild_fsys_container_grown(new_container, name, e["new_entry_raw"])
    new_container_buf = bytearray(new_container)
    current_entries = parse_fsys(bytes(new_container_buf))
    for name, e in encoded.items():
        entry = current_entries[name]
        if not e["grew"]:
            # Footprint unchanged -- substitute in place across the entry's REAL span, never `0x10 + comp_size`.
            # The demotion above can leave a blob that fits the real span but exceeds a stale declared comp_size,
            # and a slice sized off that stale value would silently RESIZE the buffer (`buf[a:b] = data` changes
            # length when the sizes differ), shifting every later entry. Padding to the real span keeps it zero.
            real_start, real_end = real_entry_span(current_entries, name, len(new_container_buf))
            span_footprint = real_end - real_start
            assert len(e["new_entry_raw"]) <= span_footprint, (
                f"{name}: blob ({len(e['new_entry_raw'])} bytes) exceeds its real on-disk span "
                f"({span_footprint} bytes) after being routed to the non-growth substitution path -- this "
                "should be unreachable (both the ADDENDUM 54 and ADDENDUM 70 real-span checks above are "
                "supposed to prevent it)."
            )
            padded = e["new_entry_raw"] + b"\x00" * (span_footprint - len(e["new_entry_raw"]))
            new_container_buf[entry["data_off"]: entry["data_off"] + span_footprint] = padded
        struct.pack_into(">I", new_container_buf, entry["record_off"] + FSYS_RECORD_COMP_SIZE_OFF, e["real_comp_size"])
        struct.pack_into(">I", new_container_buf, entry["record_off"] + FSYS_RECORD_DECOMP_SIZE_OFF, e["real_decomp_size"])
    new_container = bytes(new_container_buf)

    writer = open_writer(output_path)
    try:
        new_offset = find_free_region(writer, len(new_container))
        writer.ensure_region_allocated(new_offset, len(new_container))
        writer.write(new_offset, new_container)
        writer.write(deck_archive_record_off + FST_RECORD_FILE_OFFSET_OFF, struct.pack(">I", new_offset))
        writer.write(deck_archive_record_off + FST_RECORD_FILE_LENGTH_OFF, struct.pack(">I", len(new_container)))
    finally:
        writer.close()

    verify_reader = open_reader(output_path)
    try:
        reread_container = verify_reader.read(new_offset, len(new_container))
        reread_fst = parse_fst(verify_reader)
    finally:
        verify_reader.close()
    if reread_container != new_container:
        raise RuntimeError(
            f"read-back verification failed -- the relocated, grown {container_name} container's on-disc "
            "bytes don't match what was written"
        )
    reread_off, reread_len, _ = find_by_basename(reread_fst, container_name)
    if reread_off != new_offset or reread_len != len(new_container):
        raise RuntimeError(
            f"read-back verification failed -- {container_name}'s FST record reads offset={reread_off}, "
            f"length={reread_len}; expected offset={new_offset}, length={len(new_container)}"
        )
    reread_entries = parse_fsys(reread_container)
    for edit in edits:
        name = edit["name"]
        reread_entry = reread_entries[name]
        reread_raw = reread_container[
            reread_entry["data_off"]: reread_entry["data_off"] + 0x10 + reread_entry["comp_size"]
        ]
        if deck_format.lzss_decode(reread_raw) != edit["new_decompressed"]:
            raise RuntimeError(
                f"read-back verification failed -- re-decoded (relocated) {name} content doesn't match the "
                "intended patch"
            )
    # Unedited entries must still decode as before, compared over the real span -- a declared span that overlaps
    # into an edited neighbour would false-flag.
    edited_names = {edit["name"] for edit in edits}
    for name in fsys_entries:
        if name in edited_names:
            continue
        orig_start, orig_end = real_entry_span(fsys_entries, name, len(fsys_bytes))
        orig_raw = fsys_bytes[orig_start:orig_end]
        reread_start, reread_end = real_entry_span(reread_entries, name, len(reread_container))
        reread_raw = reread_container[reread_start:reread_end]
        if reread_raw != orig_raw:
            raise RuntimeError(
                f"read-back verification failed -- entry {name!r} inside deck_archive.fsys changed during "
                "growth/relocation, but it was never supposed to be touched"
            )
    result["new_container_offset"] = new_offset
    result["new_container_length"] = len(new_container)
    return result


def apply_patch(source_path: Path, output_path: Path, seed_path: Path, overwrite: bool = False) -> dict:
    """Copy `source_path` to `output_path`, then apply whichever ISO-side patches this seed carries --
    trainer species/movesets, chests, shops, Poke Spots, item renames, Shadow expansion, enhanced difficulty
    (Story and Mt. Battle), experience rate, move animations, catch rate. Each seed key's own handling is
    commented at its read below. Returns a summary dict; every step is read back and re-decoded first."""
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()
    seed_path = Path(seed_path)

    if output_path == source_path:
        raise ValueError("output path must be different from the source ISO -- refusing to write over it")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} already exists -- pass --overwrite to replace it")

    seed = load_seed(seed_path)
    assignment_raw = seed.get("trainer_species_by_dpkm_index")
    moves_assignment_raw = seed.get("trainer_moves_by_dpkm_index")
    chest_dummy_item_id = seed.get("chest_dummy_item_id")
    # `.get` with a default so an older seed patches exactly as it did before this field existed.
    shuffled_key_item_chest_ids = seed.get("shuffled_key_item_chest_ids") or []
    # {chest index: [berry id, quantity]}, the per-chest identity that replaced the single shared dummy berry.
    # Absent in an older seed, where `apply_chest_dummy_item` falls back to `chest_dummy_item_id` for every
    # chest -- an older seed must keep producing the ISO it always produced.
    chest_berry_assignment_raw = seed.get("chest_berry_assignment") or {}
    chest_berry_assignment = {
        int(chest): (int(pair[0]), int(pair[1]))
        for chest, pair in chest_berry_assignment_raw.items()
        if isinstance(pair, (list, tuple)) and len(pair) == 2
    }
    # shop_dummy_item_ids is a fixed list (the 26 "useless" berries), not a scalar: every real shop slot gets
    # one by rotation, so the repeating berry order identifies which shop a slot belongs to at runtime.
    # shop_excluded_item_ids (Agate's Scent items and Poke Snack) is never overwritten, in any mart or slot.
    shop_dummy_item_ids_raw = seed.get("shop_dummy_item_ids")
    shop_dummy_item_ids = [int(i) for i in shop_dummy_item_ids_raw] if shop_dummy_item_ids_raw else None
    shop_excluded_item_ids_raw = seed.get("shop_excluded_item_ids")
    shop_excluded_item_ids = (
        {int(i) for i in shop_excluded_item_ids_raw} if shop_excluded_item_ids_raw else set()
    )
    # Only the percentage travels in the seed; the plan is built below against THIS ISO's stats table.
    experience_rate = int(seed.get("experience_rate") or 100)
    # Zero every move's animation id. A flag, not a plan: one u16 per move against this ISO's own move table.
    disable_move_animations = bool(seed.get("disable_move_animations"))
    # Raise every catch rate to 255. Both halves, stats table and in-use DDPK overrides, come off THIS ISO.
    max_catch_rate = bool(seed.get("max_catch_rate"))

    pokespot_assignment_raw = seed.get("pokespot_species_by_slot")
    # {game_item_id -> that item's real vanilla display name}. One field, not two, so a rename target's id and
    # its expected name cannot drift apart: the keys say what to rename and the values are
    # `apply_item_name_rename`'s `expected_names` check.
    item_rename_target_names_raw = seed.get("item_rename_target_names")
    item_rename_target_names = (
        {int(k): v for k, v in item_rename_target_names_raw.items()} if item_rename_target_names_raw else None
    )
    # {game_item_id: display name} for every item this apworld knows. Never drives a write -- only gives the
    # shop-file diagnostic scan a known-valid-id universe.
    known_item_id_names_raw = seed.get("known_item_id_names")
    known_item_id_names = (
        {int(k): v for k, v in known_item_id_names_raw.items()} if known_item_id_names_raw else {}
    )
    assignment = {int(k): int(v) for k, v in assignment_raw.items()} if assignment_raw else None
    moves_assignment = (
        {int(k): [int(m) for m in v] for k, v in moves_assignment_raw.items()} if moves_assignment_raw else None
    )
    pokespot_assignment = (
        {str(k): int(v) for k, v in pokespot_assignment_raw.items()} if pokespot_assignment_raw else None
    )
    # {"trainer_index", "new_pokemon": [...]} plans, the shape write_shadow_multi_trainer_patch() consumes,
    # built per-seed from the world's own RNG. None when the target count was 0 or the real ISO data was not
    # available at generation time.
    shadow_expansion_plans_raw = seed.get("new_shadow_pokemon_plans")
    shadow_expansion_plans = (
        [{"trainer_index": int(p["trainer_index"]), "new_pokemon": p["new_pokemon"]} for p in shadow_expansion_plans_raw]
        if shadow_expansion_plans_raw else None
    )
    # {"level_assignment": {dpkm_index: new_level}, "new_dpkm_entries": [...], "team_slot_plan": [...]}, the
    # shape write_enhanced_difficulty_patch() consumes. None when the option was off or the census data was not
    # available at generation time.
    enhanced_difficulty_plan_raw = seed.get("enhanced_difficulty_plan")
    enhanced_difficulty_plan = (
        {
            "level_assignment": {int(k): int(v) for k, v in enhanced_difficulty_plan_raw["level_assignment"].items()},
            "new_dpkm_entries": enhanced_difficulty_plan_raw["new_dpkm_entries"],
            "team_slot_plan": [
                {"trainer_index": int(s["trainer_index"]), "new_entry_pos": int(s["new_entry_pos"])}
                for s in enhanced_difficulty_plan_raw["team_slot_plan"]
            ],
            # This field-by-field rebuild is a whitelist, so any key added at the generation end and not listed
            # here is silently dropped. Dropping this one left all 83 vanilla Shadows' DDPK levels at vanilla
            # while the DPKM half moved -- measured at a mean of +18 levels' disagreement, maximum +33.
            # `int(k)` because JSON keys are strings.
            "shadow_level_assignment": {
                int(k): int(v)
                for k, v in (enhanced_difficulty_plan_raw.get("shadow_level_assignment") or {}).items()
            },
        }
        if enhanced_difficulty_plan_raw else None
    )
    # Same shape as enhanced_difficulty_plan, against DeckData_Hundred.bin, from mtbattle_team_census()'s own
    # index namespace.
    mt_battle_enhanced_difficulty_plan_raw = seed.get("mt_battle_enhanced_difficulty_plan")
    mt_battle_enhanced_difficulty_plan = (
        {
            "level_assignment": {
                int(k): int(v) for k, v in mt_battle_enhanced_difficulty_plan_raw["level_assignment"].items()
            },
            "new_dpkm_entries": mt_battle_enhanced_difficulty_plan_raw["new_dpkm_entries"],
            "team_slot_plan": [
                {"trainer_index": int(s["trainer_index"]), "new_entry_pos": int(s["new_entry_pos"])}
                for s in mt_battle_enhanced_difficulty_plan_raw["team_slot_plan"]
            ],
        }
        if mt_battle_enhanced_difficulty_plan_raw else None
    )

    chunked_copy(source_path, output_path)

    summary = {
        "output": str(output_path),
        "trainer_slots_patched": 0,
        "trainer_movesets_patched": 0,
        "chests_patched": 0,
        "shop_slots_patched": 0,
        "shop_randomization_error": None,
        "shop_diagnostic_file": None,
        "shop_mart_census": None,
        "shop_pocket_menu_entries": None,
        "shop_pocket_menu_attempts": None,
        "shop_rel_structure": None,
        "shop_write_set": None,
        "shop_item_id_scan": {},
        "shop_mart_rel_scan": {},
        "pokespot_slots_patched": 0,
        "items_renamed": 0,
        "items_rename_resolved_via": {},
        "items_rename_diagnostic_file": None,
        "shadow_pokemon_added": 0,
        "enhanced_difficulty_levels_boosted": 0,
        "enhanced_difficulty_new_members": 0,
        "mt_battle_enhanced_difficulty_levels_boosted": 0,
        "mt_battle_enhanced_difficulty_new_members": 0,
    }

    if assignment or moves_assignment:
        reader = open_reader(output_path)
        try:
            fst = parse_fst(reader)
            deck_archive_off, deck_archive_len, deck_archive_record_off = find_by_basename(
                fst, "deck_archive.fsys"
            )
            fsys_bytes = reader.read(deck_archive_off, deck_archive_len)
            fsys_entries = parse_fsys(fsys_bytes)
            story_entry = fsys_entries["DeckData_Story.bin"]
            entry_raw_len = 0x10 + story_entry["comp_size"]
            entry_raw = reader.read(deck_archive_off + story_entry["data_off"], entry_raw_len)
        finally:
            reader.close()

        decompressed = deck_format.lzss_decode(entry_raw)
        deck = deck_format.DeckFile(decompressed)

        unknown_indices = sorted(
            i for i in set(assignment or {}) | set(moves_assignment or {}) if i >= deck.dpkm_entries
        )
        if unknown_indices:
            raise ValueError(
                f"seed references dpkm_index values out of range for this ISO's DeckData_Story.bin "
                f"({deck.dpkm_entries} entries): "
                f"{unknown_indices[:10]}{'...' if len(unknown_indices) > 10 else ''} "
                "-- this seed was likely generated against a different game version/region than this ISO."
            )

        new_decompressed = apply_trainer_patch(decompressed, deck, assignment, moves_assignment)
        # Growth is safe here: relocating deck_archive.fsys with zero content change was confirmed on real
        # hardware, clearing disc position of the old black-screen report (the reverted DP encoder stays the
        # suspect). Write/verify/grow logic lives in `write_deck_story_patch()`.
        patch_result = write_deck_story_patch(
            output_path, deck_archive_off, deck_archive_len, deck_archive_record_off,
            fsys_bytes, story_entry, entry_raw, new_decompressed,
        )
        if patch_result["grew"]:
            print(
                f"deck_archive.fsys grew from {deck_archive_len} to {patch_result['new_container_length']} bytes "
                f"(DeckData_Story.bin's re-encoded stream, {patch_result['real_comp_size']} bytes, didn't fit "
                f"its original {patch_result['old_comp_size']}-byte allocation) and was relocated from ISO "
                f"offset {deck_archive_off} to {patch_result['new_container_offset']}. Every other entry inside "
                "the container was re-verified byte-identical to before."
            )
        else:
            print(
                f"FSYS record comp_size corrected to the real re-encoded length "
                f"({patch_result['real_comp_size']} bytes, was {patch_result['old_comp_size']}) so the "
                "decompressor never reads into the zero-padding filler."
            )

        if assignment:
            print(f"Patched {len(assignment)} trainer Pokemon species assignments into {output_path}.")
        if moves_assignment:
            print(f"Patched {len(moves_assignment)} trainer Pokemon movesets into {output_path}.")

        summary["trainer_slots_patched"] = len(assignment) if assignment else 0
        summary["trainer_movesets_patched"] = len(moves_assignment) if moves_assignment else 0
        summary["deck_archive_grew"] = patch_result["grew"]
    else:
        print(
            "This seed has no trainer_species_by_dpkm_index or trainer_moves_by_dpkm_index data (older seed, "
            "or both trainer-team randomization and moveset shuffle were unavailable/off when it was "
            "generated) -- trainer data left untouched."
        )

    # Shadow expansion is a separate step from the species/moves pass, which only replaces an existing DPKM slot
    # and never adds a team slot or DDPK entry. Every pass re-reads the container's current on-disk bytes, so the
    # ordering here is readability, not correctness.
    if shadow_expansion_plans:
        shadow_result = write_shadow_multi_trainer_patch(output_path, shadow_expansion_plans)
        summary["shadow_pokemon_added"] = sum(len(p["new_pokemon"]) for p in shadow_expansion_plans)
        summary["shadow_expansion_per_trainer"] = shadow_result["per_trainer"]
        print(f"Applied {summary['shadow_pokemon_added']} new Shadow Pokemon across {len(shadow_expansion_plans)} trainers into {output_path}.")
    else:
        print(
            "This seed has no new_shadow_pokemon_plans data (shadow_pokemon_expansion was 0/off, or the "
            "required real ISO census data wasn't available when this seed was generated) -- no new Shadow "
            "Pokemon were added."
        )

    # Enhanced Difficulty: ordinary Pokemon only, and a third pass over DeckData_Story.bin in one run. That
    # three-way interaction has exposed two real container-growth bugs, so it has its own regression test.
    if enhanced_difficulty_plan:
        ed_result = write_enhanced_difficulty_patch(output_path, enhanced_difficulty_plan)
        summary["enhanced_difficulty_levels_boosted"] = ed_result["levels_boosted"]
        summary["enhanced_difficulty_new_members"] = ed_result["new_members_added"]
        summary["enhanced_difficulty_trainers_padded"] = ed_result["trainers_padded"]
        print(
            f"Applied Enhanced Difficulty: boosted {ed_result['levels_boosted']} existing team members' levels "
            f"and added {ed_result['new_members_added']} new ordinary team members across "
            f"{ed_result['trainers_padded']} trainers into {output_path}."
        )
    else:
        print(
            "This seed has no enhanced_difficulty_plan data (enhanced_difficulty was off, or the required real "
            "ISO census data wasn't available when this seed was generated) -- trainer levels/team sizes left "
            "untouched by Enhanced Difficulty."
        )

    # The Mt. Battle half of Enhanced Difficulty: DeckData_Hundred.bin, gated by the same YAML option.
    if mt_battle_enhanced_difficulty_plan:
        mt_ed_result = write_enhanced_difficulty_mt_battle_patch(output_path, mt_battle_enhanced_difficulty_plan)
        summary["mt_battle_enhanced_difficulty_levels_boosted"] = mt_ed_result["levels_boosted"]
        summary["mt_battle_enhanced_difficulty_new_members"] = mt_ed_result["new_members_added"]
        summary["mt_battle_enhanced_difficulty_trainers_padded"] = mt_ed_result["trainers_padded"]
        print(
            f"Applied Enhanced Difficulty to Mt. Battle: boosted {mt_ed_result['levels_boosted']} existing team "
            f"members' levels and added {mt_ed_result['new_members_added']} new ordinary team members across "
            f"{mt_ed_result['trainers_padded']} Mt. Battle trainers into {output_path}."
        )
    else:
        print(
            "This seed has no mt_battle_enhanced_difficulty_plan data (enhanced_difficulty was off, or the "
            "required real Mt. Battle ISO census data wasn't available when this seed was generated) -- Mt. "
            "Battle trainer levels/team sizes left untouched."
        )

    # Chest randomization, Poke Spot species and the AP Item rename all live in the SAME common_rel.rel blob and
    # share one decompress/mutate/re-encode/write/verify pass: that blob has a finite LZSS re-encoded-size
    # budget, and all three edits are fixed-size overwrites, never table rebuilds.
    if (chest_dummy_item_id is not None or pokespot_assignment or item_rename_target_names
            or experience_rate != 100 or disable_move_animations or max_catch_rate):
        reader = open_reader(output_path)
        try:
            fst = parse_fst(reader)
            common_off, common_len, _common_record_off = find_by_basename(fst, "common.fsys")
            common_bytes = reader.read(common_off, common_len)
            fsys_entries = parse_fsys(common_bytes)
            rel_entry = fsys_entries["common_rel"]
            abs_entry_off = common_off + rel_entry["data_off"]
            abs_record_comp_size_off = common_off + rel_entry["record_off"] + FSYS_RECORD_COMP_SIZE_OFF
            entry_raw_len = 0x10 + rel_entry["comp_size"]
            entry_raw = reader.read(abs_entry_off, entry_raw_len)
        finally:
            reader.close()

        decompressed = deck_format.lzss_decode(entry_raw)
        rel = rel_format.RelFile(decompressed, is_common=True)
        rel_bytes = bytearray(decompressed)
        # ADDENDUM 381: snapshot the two bytes per move that decide its status (effect id +0x1D, secondary
        # chance +0x05) and prove them unchanged before the blob is written. Every writer below is bounded,
        # but the animation write lands one byte past the effect id, so the invariant is enforced rather than
        # trusted. 720 bytes in a pass whose re-encode takes tens of seconds.
        # ADDENDUM 392: the Poke Spot levels get the same before/after fence the move-status fields got in
        # ADDENDUM 381, and for the same reason -- every writer below shares this one pass over `rel_bytes`.
        pokespot_levels_before = None
        try:
            pokespot_levels_before = rel_format.pokespot_level_fields(rel_bytes, rel)
        except Exception:
            pass
        move_status_before = None
        try:
            _ms_base = rel_format.moves_table_base(rel)
            _ms_count = rel_format.moves_table_count(rel)
            move_status_before = rel_format.move_status_fields(rel_bytes, _ms_base, _ms_count)
        except Exception:
            pass          # no locatable move table on this build: nothing to fence, and nothing writes it
        # This step LZSS re-encodes all of common_rel -- 704,448 bytes on a real ISO, measured at 29.3s in pure
        # Python on a fast machine. Silence that long reads as a crash, hence the announcement.
        print(
            f"Re-encoding common_rel ({len(decompressed):,} bytes) for the chest/Poke Spot/item-name patch. "
            f"This is the slowest step in the whole patch -- pure-Python LZSS, tens of seconds to a few "
            f"minutes, with no output until it finishes. It has not crashed; let it run."
        )
        _encode_t0 = time.time()
        chests_patched = 0
        pokespot_slots_patched = 0
        items_renamed = 0
        items_rename_skipped: list[dict] = []
        if chest_dummy_item_id is not None:
            # `shuffled_key_item_chest_ids` opts the five pool-bound key-item chests out of the fence.
            chests_patched = rel_format.apply_chest_dummy_item(
                rel_bytes, rel, int(chest_dummy_item_id),
                also_convert=frozenset(shuffled_key_item_chest_ids or ()),
                per_chest=chest_berry_assignment or None,
            )
        pokespot_refused = None
        if pokespot_assignment:
            # ADDENDUM 392: prove this really is the Poke Spot table before writing a species into it. A
            # pointer that resolved two bytes early would put a species index's zero high byte into MinLevel,
            # which is exactly the level-0 encounter being reported.
            if not rel_format.verify_pokespot_table(rel):
                pokespot_refused = (
                    "the Poke Spot table on this ISO did not reproduce this project's eleven known vanilla "
                    "level ranges, so the wild-encounter species reassignment was skipped rather than writing "
                    "a species into an unverified location"
                )
            else:
                pokespot_slots_patched = rel_format.apply_pokespot_species(
                    rel_bytes, rel, pokespot_assignment)
        # Experience rate and move animations, same re-encode pass, both refusing an unproven table.
        anim_result = {"animations_cleared": 0, "already_silent": 0, "moves": 0}
        anim_refused = None
        if disable_move_animations:
            # ADDENDUM 381: this write lands one byte past the effect id, so it needs the stronger of the two
            # checks -- not just "is this the move table" but "does this build number its effects the way the
            # census says", because the answer is what makes writing next to them safe.
            if not rel_format.verify_moves_table(rel):
                anim_refused = (
                    "the move table on this ISO did not reproduce this project's known Gen III PP and base-"
                    "power values, so the disable-move-animations option was skipped rather than writing "
                    "zeros into an unverified location"
                )
            elif not rel_format.verify_move_status_fields(rel, _move_status_census()):
                anim_refused = (
                    "the move table is where the pointer says, but its effect ids and secondary-effect "
                    "chances did not match this project's census, so this build numbers move effects "
                    "differently than measured -- the disable-move-animations option was skipped rather "
                    "than writing a byte away from status data whose layout is not understood"
                )
            else:
                anim_result = rel_format.apply_disable_move_animations(rel_bytes, rel)
        exp_result = {"base_exp_written": 0, "exp_rate_written": 0}
        exp_plan: dict = {}
        exp_refused = None
        if experience_rate != 100:
            try:
                from ..game_data import species_stats
                from ..game_data.species_base_hp import all_base_hp
                from .xd_species_index import INTERNAL_INDEX_TO_NATIONAL_DEX
            except ImportError:  # running as a loose script rather than inside the package
                _package_root_on_path()
                from game_data import species_stats                          # type: ignore
                from game_data.species_base_hp import all_base_hp            # type: ignore
                from xd_species_index import INTERNAL_INDEX_TO_NATIONAL_DEX  # type: ignore
            dex_by_index = {i: v[0] for i, v in INTERNAL_INDEX_TO_NATIONAL_DEX.items()}
            # A wrong base writes into an arbitrary part of common_rel, so prove the table against the base-HP
            # census before any byte goes in. Failure disables the feature rather than writing anyway.
            if rel_format.verify_species_stats_table(rel, all_base_hp(), dex_by_index):
                # ADDENDUM 384: the divisor is spent first, so the bytes are only asked for the remainder.
                exp_plan = species_stats.plan_experience_rate(
                    rel_format.read_species_experience(rel), experience_rate,
                    from_divisor=species_stats.divisor_speedup(int(seed.get("exp_divisor") or 7)),
                )
                exp_result = rel_format.apply_experience_rate(rel_bytes, rel, exp_plan)
            else:
                exp_refused = (
                    "the Pokemon stats table on this ISO did not match this project's own base-HP census, so "
                    "the experience-rate option was skipped rather than writing experience bytes into an "
                    "unverified location"
                )
        # The catch rate, same pass. Both this and the experience rate write single bytes into the SAME
        # 0x124-byte stats entry, so "is this really the stats table" is one question with one answer.
        catch_result = {"catch_rate_written": 0}
        catch_plan: dict = {}
        catch_refused = None
        if max_catch_rate:
            try:
                from ..game_data import species_stats
                from ..game_data.species_base_hp import all_base_hp
                from .xd_species_index import INTERNAL_INDEX_TO_NATIONAL_DEX
            except ImportError:  # running as a loose script rather than inside the package
                _package_root_on_path()
                from game_data import species_stats                          # type: ignore
                from game_data.species_base_hp import all_base_hp            # type: ignore
                from xd_species_index import INTERNAL_INDEX_TO_NATIONAL_DEX  # type: ignore
            dex_by_index = {i: v[0] for i, v in INTERNAL_INDEX_TO_NATIONAL_DEX.items()}
            if rel_format.verify_species_stats_table(rel, all_base_hp(), dex_by_index):
                catch_plan = species_stats.plan_catch_rate(rel_format.read_species_catch_rates(rel))
                catch_result = rel_format.apply_catch_rate(rel_bytes, rel, catch_plan)
            else:
                catch_refused = (
                    "the Pokemon stats table on this ISO did not match this project's own base-HP census, so "
                    "the max-catch-rate option's ordinary-species half was skipped rather than writing catch "
                    "rates into an unverified location"
                )
        items_rename_resolved_via: dict = {}
        if item_rename_target_names:
            rename_result = rel_format.apply_item_name_rename(
                rel_bytes, rel, list(item_rename_target_names.keys()), expected_names=item_rename_target_names
            )
            items_renamed = len(rename_result["renamed"])
            items_rename_skipped = rename_result["skipped"]
            items_rename_resolved_via = rename_result.get("resolved_via", {})
        if pokespot_levels_before is not None:
            rel_format.assert_pokespot_levels_unchanged(
                pokespot_levels_before, rel_format.pokespot_level_fields(rel_bytes, rel))
        if move_status_before is not None:
            rel_format.assert_move_status_fields_unchanged(
                move_status_before, rel_format.move_status_fields(rel_bytes, _ms_base, _ms_count)
            )
        # allow_grow left False: common_rel.rel relocation is out of scope, so this raises if it does not fit.
        new_entry_raw, real_comp_size, _grew = deck_format.patch_entry_decompressed(entry_raw, bytes(rel_bytes))
        print(f"  common_rel re-encoded in {time.time() - _encode_t0:.1f}s "
              f"({real_comp_size:,} bytes; original allocation {rel_entry['comp_size']:,}).")

        writer = open_writer(output_path)
        try:
            writer.write(abs_entry_off, new_entry_raw)
            writer.write(abs_record_comp_size_off, struct.pack(">I", real_comp_size))
        finally:
            writer.close()

        verify_reader = open_reader(output_path)
        try:
            reread = verify_reader.read(abs_entry_off, len(new_entry_raw))
            reread_record_comp_size = verify_reader.read(abs_record_comp_size_off, 4)
        finally:
            verify_reader.close()
        if reread != new_entry_raw:
            raise RuntimeError(
                "read-back verification failed -- the chest/Poke Spot/item-rename common_rel write did not "
                "stick"
            )
        redecoded = deck_format.lzss_decode(reread)
        if redecoded != bytes(rel_bytes):
            raise RuntimeError(
                "read-back verification failed -- re-decoded common_rel table bytes don't match the intended "
                "patch"
            )
        if struct.unpack(">I", reread_record_comp_size)[0] != real_comp_size:
            raise RuntimeError(
                "read-back verification failed -- common_rel's FSYS record comp_size didn't stick"
            )

        if chest_dummy_item_id is not None:
            print(
                f"Patched {chests_patched} chest item drops to dummy item id {chest_dummy_item_id} into "
                f"{output_path}."
            )
        if pokespot_assignment:
            if pokespot_refused:
                print(f"Poke Spot species reassignment NOT applied -- {pokespot_refused}.")
            else:
                print(f"Patched {pokespot_slots_patched} Poke Spot wild-encounter species into {output_path}.")
        if disable_move_animations:
            if anim_refused:
                print(f"Move animations NOT disabled: {anim_refused}.")
            else:
                print(f"Disabled move animations: cleared {anim_result['animations_cleared']} of "
                      f"{anim_result['moves']} move animation ids "
                      f"({anim_result['already_silent']} already had none) in {output_path}.")
                summary["move_animations_cleared"] = anim_result["animations_cleared"]
        if experience_rate != 100:
            if exp_refused:
                print(f"Experience rate NOT applied: {exp_refused}.")
            else:
                from_ = species_stats.describe_plan(exp_plan)
                print(f"{from_} Wrote {exp_result['base_exp_written']} base-experience byte(s) and "
                      f"{exp_result['exp_rate_written']} experience-group byte(s) into {output_path}.")
                summary["experience_rate"] = experience_rate
                summary["experience_base_exp_written"] = exp_result["base_exp_written"]
                summary["experience_exp_rate_written"] = exp_result["exp_rate_written"]
                summary["experience_achieved_mean"] = round(float(exp_plan.get("achieved_mean", 1.0)), 3)
        if max_catch_rate:
            if catch_refused:
                print(f"Max catch rate NOT applied to ordinary species: {catch_refused}.")
            else:
                print(f"{species_stats.describe_catch_rate_plan(catch_plan)} Wrote "
                      f"{catch_result['catch_rate_written']} catch-rate byte(s) into {output_path}.")
                summary["catch_rate_species_written"] = catch_result["catch_rate_written"]
        if item_rename_target_names:
            print(
                f"Renamed {items_renamed}/{len(item_rename_target_names)} dummy items to 'AP Item' into "
                f"{output_path}."
            )
            for skip in items_rename_skipped:
                print(f"  - item {skip['item_id']} NOT renamed: {skip['reason']}")
            # NameIDs come from searching the string table for the known-correct text; surfaced for cross-checking.
            if items_rename_resolved_via:
                print(f"  Rename text search: {len(items_rename_resolved_via)} item(s) resolved by matching "
                      f"their known-correct name directly in the string table (NameID shown):")
                for item_id, info in sorted(items_rename_resolved_via.items()):
                    print(f"    item {item_id}: NameID {info['name_id']}")
            # When the search misses every target across all 1931 string-table entries (pointer index 116), the
            # table may hold species names and not item names -- a wrongly-computed item read once landed on a
            # valid species name, which proves the first, not the second. So dump it read-only rather than guess.
            if items_rename_skipped:
                try:
                    all_strings = rel_format.string_table_id_offsets(rel)
                    rename_diag_lines = [
                        "Pokemon XD Archipelago -- AP Item rename diagnostic",
                        "=" * 52,
                        "",
                        f"Renamed {items_renamed}/{len(item_rename_target_names)} dummy items.",
                        "",
                        "Skipped items:",
                    ]
                    for skip in items_rename_skipped:
                        rename_diag_lines.append(f"  item {skip['item_id']}: {skip['reason']}")
                    rename_diag_lines.append("")
                    # Real item names do live in this table ("Krane Memo 4" is in both pointer 102 and 116), just
                    # not every item under its reference spelling -- hence a "berry" substring pass. Read-only.
                    if known_item_id_names:
                        candidate_tables = rel_format.find_candidate_item_string_tables(
                            rel, known_item_names=set(known_item_id_names.values()), substring_hints={"berry"}
                        )
                        if candidate_tables:
                            rename_diag_lines.append(
                                "NEW (ADDENDUM 123/124) -- scanned every pointer index in this REL for one "
                                "containing real, known item names (not just the 27 rename targets) or any "
                                "text merely CONTAINING \"berry\" -- found candidate(s):"
                            )
                            for cand in candidate_tables:
                                degenerate_note = (
                                    "  <-- mostly repeats the same few NameIDs; likely a coincidental/garbage "
                                    "parse of this pointer index, not a real distinct-entry table"
                                    if cand["unique_name_ids"] < len(cand["matches"]) / 2
                                    else ""
                                )
                                rename_diag_lines.append(
                                    f"  pointer index {cand['pointer_index']} ({cand['entry_count']} entries) "
                                    f"-- {len(cand['matches'])} hit(s), {cand['unique_name_ids']} unique "
                                    f"NameID(s){degenerate_note}:"
                                )
                                for m in cand["matches"]:
                                    rename_diag_lines.append(
                                        f"    NameID {m['name_id']} [{m['kind']}]: {m['text']!r}"
                                    )
                        else:
                            rename_diag_lines.append(
                                "NEW (ADDENDUM 123/124) -- scanned every pointer index in this REL for one "
                                "containing real, known item names (not just the 27 rename targets) or any "
                                "text merely containing \"berry\" -- found NONE at all. Berry item display "
                                "names likely live outside this REL entirely (a different file/container)."
                            )
                        rename_diag_lines.append("")
                    # `item_name_id()`'s struct resolution is not broken across the board, so sample items other
                    # than the berry targets to tell "specific to berries" from "broken universally". Read-only.
                    non_target_samples = {
                        item_id: name
                        for item_id, name in sorted(known_item_id_names.items())[:15]
                        if item_id not in item_rename_target_names
                    }
                    if non_target_samples:
                        control_results = rel_format.check_item_struct_resolution_sample(rel, non_target_samples)
                        matches = sum(1 for r in control_results if r["match"])
                        rename_diag_lines.append(
                            f"NEW (ADDENDUM 124) -- sanity check: does the ORIGINAL item-table struct "
                            f"resolution (unchanged formula, no search involved) work for items OTHER than the "
                            f"27 berry targets? {matches}/{len(control_results)} sample item(s) matched:"
                        )
                        for r in control_results:
                            if r["found"] is not None:
                                status = "MATCH" if r["match"] else "MISMATCH"
                                rename_diag_lines.append(
                                    f"  item {r['item_id']} (expected {r['expected']!r}): {status} -- found "
                                    f"{r['found']!r}"
                                )
                            else:
                                rename_diag_lines.append(
                                    f"  item {r['item_id']} (expected {r['expected']!r}): {r['reason']}"
                                )
                        rename_diag_lines.append("")
                    rename_diag_lines.append(
                        f"Full dump of this REL's own CommonRelStringTable (pointer index "
                        f"{rel_format.COMMON_REL_STRING_TABLE_POINTER}) -- {len(all_strings)} entries, "
                        f"(NameID: decoded text; an entry that hits an 0xFFFF escape/unterminated run before a "
                        f"real 0x0000 terminator decodes only its bytes up to that point):"
                    )
                    for name_id in sorted(all_strings):
                        try:
                            raw = rel_format.read_string_table_entry_bytes(rel, all_strings[name_id])
                            text = raw.decode("utf-16-be", errors="replace")
                        except Exception as decode_exc:
                            text = f"<decode error: {decode_exc}>"
                        rename_diag_lines.append(f"  {name_id}: {text!r}")
                    rename_diag_path = output_path.parent / f"{output_path.stem}_rename_diagnostic.txt"
                    rename_diag_path.write_text("\n".join(rename_diag_lines), encoding="utf-8")
                    print(f"  Rename diagnostic data (full string table dump, {len(all_strings)} entries) "
                          f"written to: {rename_diag_path}")
                    summary["items_rename_diagnostic_file"] = str(rename_diag_path)
                except Exception as diag_exc:
                    print(f"  (could not write rename diagnostic file: {diag_exc})")
        summary["chests_patched"] = chests_patched
        summary["pokespot_slots_patched"] = pokespot_slots_patched
        summary["pokespot_refused"] = pokespot_refused
        summary["items_renamed"] = items_renamed
        summary["items_rename_skipped"] = items_rename_skipped
        summary["items_rename_resolved_via"] = items_rename_resolved_via
    else:
        print(
            "This seed has no chest_dummy_item_id, pokespot_species_by_slot, or item_rename_target_names data "
            "(chest randomization was off, no Poke Spot reassignment was present, and no dummy-item rename "
            "targets were present) -- common_rel's chest/Poke Spot/item-name tables left untouched."
        )

    # The Shadow half of max-catch-rate, deliberately after the passes that bring new DDPK entries into use:
    # `apply_shadow_catch_rate` covers whatever reads in_use when it runs.
    if max_catch_rate:
        catch_shadow = write_max_catch_rate_shadow_patch(output_path)
        print(
            f"Max catch rate: all {catch_shadow['common_in_use']} in-use Shadow Pokemon are now at 255 "
            f"in common.fsys's DeckData_DarkPokemon.bin "
            f"({catch_shadow['common_raised']} raised, "
            f"{catch_shadow['common_in_use'] - catch_shadow['common_raised']} already there; "
            f"{catch_shadow['common_eu_raised']} raised in its _EU copy, "
            f"{catch_shadow['archive_raised']} in deck_archive.fsys's) in {output_path}."
        )
        summary["catch_rate_shadows_written"] = catch_shadow["common_raised"]
        summary["catch_rate_shadows_in_use"] = catch_shadow["common_in_use"]
        summary["catch_rate_shadows_written_archive"] = catch_shadow["archive_raised"]
        summary["catch_rate_shadows_written_common_eu"] = catch_shadow["common_eu_raised"]
        # The instruction that makes a catch unconditional, under the same option rather than a second toggle.
        always_catch = write_always_catch_code_patch(output_path)
        if always_catch["applied"]:
            print(f"Max catch rate: always-catch instruction written at "
                  f"0x{always_catch['address']:08X} (was 0x{always_catch['original']:08X})"
                  + (" -- already present." if always_catch["reason"] else "."))
        else:
            print(f"Max catch rate: always-catch instruction NOT applied -- {always_catch['reason']}. "
                  "The catch-rate tables above are still at 255.")
        summary["always_catch_applied"] = always_catch["applied"]
        summary["always_catch_reason"] = always_catch["reason"]

    # ADDENDUM 384: the experience formula's own divisor, outside the common_rel pass because it lives in
    # main.dol. Spent before the species bytes, so most rates now cost the tables nothing.
    exp_divisor = int(seed.get("exp_divisor") or 7)
    if exp_divisor != 7:
        divisor_result = write_exp_divisor_patch(output_path, exp_divisor)
        if divisor_result["applied"]:
            print(f"Experience rate: formula divisor set to {exp_divisor} at "
                  f"0x{divisor_result['address']:08X} -- experience is "
                  f"{7 / exp_divisor:.2f}x before the species tables"
                  + (" (already present)." if divisor_result["reason"] else "."))
        else:
            print(f"Experience rate: the formula divisor was NOT changed -- {divisor_result['reason']}. "
                  "The species tables below still apply.")
        summary["exp_divisor"] = exp_divisor
        summary["exp_divisor_applied"] = divisor_result["applied"]
        summary["exp_divisor_reason"] = divisor_result["reason"]

    # Shop/mart randomization: every slot gets one of the 26 useless berries, rotated per slot. The mart table
    # lives in `pocket_menu.fsys`, a separate container from `common.fsys`, so this is its own
    # read/mutate/re-encode/write/verify pass rather than part of the chest/Poke Spot one.
    shop_slots_patched = 0
    shop_randomization_error = None
    if shop_dummy_item_ids:
        # Wrapped because this container is the least-confirmed thing here: the base-name-fallback
        # "pocket_menu" entry decompresses to 544 bytes, far too small for REL pointer-table data. A failure here
        # must not discard the passes already applied and verified, so it is skipped with a warning.
        try:
            reader = open_reader(output_path)
            try:
                fst = parse_fst(reader)
                pm_off, pm_len, _pm_record_off = find_by_basename(fst, "pocket_menu.fsys")
                pm_bytes = reader.read(pm_off, pm_len)
                pm_fsys_entries = parse_fsys(pm_bytes)
                # The mart REL's full name is "pocket_menu.rel", but `parse_fsys` keys by extension-less base
                # name, so a container holding it and a `pocket_menu.<ext>` UI entry keeps only the last -- the
                # 544-byte survivor decodes to 22x22-texture descriptors. So enumerate every entry and let the
                # oracle below pick.
                pm_all_entries = parse_fsys_all(pm_bytes)
                pm_candidates = [
                    e for e in pm_all_entries if e["name"] == "pocket_menu" or (e["full_name"] or "").startswith("pocket_menu")
                ]
                if not pm_candidates:
                    pm_rel_name, pm_rel_entry = _find_rel_entry(
                        pm_fsys_entries, "pocket_menu.fsys", container_basename="pocket_menu"
                    )
                    pm_candidates = [dict(pm_rel_entry, index=-1, name=pm_rel_name, full_name=None, file_format=None)]
                pm_candidates.sort(key=lambda e: 0 if (e["full_name"] or "").lower().endswith(".rel") else 1)
                summary["shop_pocket_menu_entries"] = [
                    {k: e[k] for k in ("index", "name", "full_name", "file_format", "data_off", "decomp_size", "comp_size")}
                    for e in pm_all_entries
                ]
                pm_candidate_raws = []
                for e in pm_candidates:
                    abs_entry_off = pm_off + e["data_off"]
                    raw_len = 0x10 + max(e["comp_size"], e["decomp_size"])
                    pm_candidate_raws.append((e, abs_entry_off, reader.read(abs_entry_off, raw_len)))
            finally:
                reader.close()

            # First candidate that decodes as a REL and passes the plausibility oracle is the real mart REL.
            pm_attempts: list[str] = []
            pm_chosen = None
            for e, abs_entry_off, entry_raw in pm_candidate_raws:
                label = f"pocket_menu.fsys entry #{e['index']} {e['full_name'] or e['name']!r} (format {e['file_format']})"
                try:
                    # Honour the payload's own magic: "LZSS" decodes, anything else is stored raw.
                    is_lzss = entry_raw[:4] == b"LZSS"
                    decompressed = deck_format.lzss_decode(entry_raw) if is_lzss else bytes(entry_raw[: e["decomp_size"]])
                    # A full OSLink-style walk first rejects non-REL data and proves the decode.
                    cand_structure = rel_format.validate_rel_structure(decompressed, label=label)
                    # pocket_menu.rel's own filename does not contain "common_rel" -- always is_common=False.
                    cand_rel = rel_format.RelFile(decompressed, is_common=False, label=label)
                    mart_count = rel_format.number_of_marts(cand_rel)
                    if mart_count <= 0 or mart_count > 64:
                        raise ValueError(f"NumberOfMarts={mart_count} is not plausible")
                    slots = rel_format.read_all_mart_slots(cand_rel)
                    slot_ids = [s_["item_id"] for s_ in slots]
                    census = [
                        {
                            "mart_index": s_["mart_index"],
                            "pool_index": s_["pool_index"],
                            "item": f"{s_['item_id']} ({known_item_id_names.get(s_['item_id'], '?')})",
                        }
                        for s_ in slots
                    ]
                    # Plausibility oracle: at least half the slots must be items this apworld knows by name
                    # (real marts are full of Potions and Poke Balls; a garbage parse is not) and at least one a
                    # real vanilla id (1..0x251). Out-of-range ids are not fatal -- the real pocket_menu.rel has
                    # 21 marts / 284 walked slots with junk past one mart's real end, never written.
                    out_of_range = sorted({i for i in slot_ids if not 1 <= i < rel_format.ITEM_REMAP_THRESHOLD_ID})
                    in_range_count = sum(1 for i in slot_ids if 1 <= i < rel_format.ITEM_REMAP_THRESHOLD_ID)
                    known_count = sum(1 for i in slot_ids if i in known_item_id_names)
                    if not slots or in_range_count == 0 or (known_item_id_names and known_count * 2 < len(slot_ids)):
                        raise ValueError(
                            f"NumberOfMarts={mart_count}, {len(slots)} slot(s), {known_count} known by name, "
                            f"out-of-range ids {out_of_range[:20]}; slots: {census[:12]}"
                        )
                    pm_chosen = (e, abs_entry_off, entry_raw, is_lzss, decompressed, cand_rel, mart_count, census,
                                 cand_structure)
                    pm_attempts.append(
                        f"{label}: OK -- NumberOfMarts={mart_count}, {len(slots)} slot(s), {known_count} known by "
                        f"name, {len(slot_ids) - in_range_count} junk slot(s) will be left untouched; REL structure "
                        f"valid ({len(cand_structure['imports'])} import(s): "
                        + ", ".join(f"module {i['module']} x{i['entries']} relocations" for i in cand_structure["imports"])
                        + ")"
                    )
                    break
                except Exception as cand_exc:
                    pm_attempts.append(f"{label}: not the mart REL ({cand_exc})")
            summary["shop_pocket_menu_attempts"] = pm_attempts
            if pm_chosen is None:
                raise ValueError(
                    "no entry in pocket_menu.fsys decoded as a plausible mart REL -- tried: " + " | ".join(pm_attempts)
                )
            (pm_rel_entry, pm_abs_entry_off, pm_entry_raw, pm_is_lzss, pm_decompressed, pm_rel, pm_mart_count,
             pm_census, pm_structure) = pm_chosen
            pm_rel_name = pm_rel_entry["full_name"] or pm_rel_entry["name"]
            pm_abs_record_comp_size_off = pm_off + pm_rel_entry["record_off"] + FSYS_RECORD_COMP_SIZE_OFF
            summary["shop_mart_census"] = pm_census
            summary["shop_rel_structure"] = pm_structure
            pm_rel_bytes = bytearray(pm_decompressed)
            # MART_GROUPS switches to per-shop-line assignment, so a shelf line keeps one berry across every
            # tier of its shop and a restock's new berries are exactly its new lines. Unclaimed marts fall
            # through to a single-mart group. Routed through `_game_data_module`: a bare relative import here
            # takes the whole shop pass down.
            _SHOP_MART_GROUPS = _game_data_module("shop_stock").MART_GROUPS

            shop_slots_patched = rel_format.apply_mart_randomization(
                pm_rel_bytes, pm_rel, shop_dummy_item_ids, frozenset(shop_excluded_item_ids),
                mart_groups=list(_SHOP_MART_GROUPS),
            )
            # Agate Village Pit Stop: Agate's marts sell real supplies instead of berries. After the berry pass
            # so it only replaces Agate's own slots, and Agate is its own mart group, so no other shop's berry
            # numbering moves.
            if seed.get("agate_village_pit_stop"):
                _stock = _game_data_module("shop_stock")
                pit_stop_written = rel_format.apply_mart_fixed_stock(
                    pm_rel_bytes, pm_rel, _stock.agate_pit_stop_marts(), _stock.AGATE_PIT_STOP_STOCK,
                    frozenset(shop_excluded_item_ids),
                )
                summary["agate_pit_stop_slots"] = pit_stop_written
                print(f"Agate Village Pit Stop: {pit_stop_written} shelf line(s) now sell real balls and medicine.")
            # Write-set confinement plus a post-patch link check: every changed byte inside the MartItems pool's
            # extent, and the result still passing the OSLink walk. Either failure aborts before any disc write.
            pm_pool_base = rel_format.mart_items_base(pm_rel)
            pm_pool_end = rel_format.mart_pool_end_offset(pm_rel)
            pm_changed = rel_format.byte_diff_offsets(bytes(pm_decompressed), bytes(pm_rel_bytes))
            pm_stray = [o for o in pm_changed if not pm_pool_base <= o < pm_pool_end]
            summary["shop_write_set"] = {
                "pool_base": pm_pool_base,
                "pool_end": pm_pool_end,
                "changed_bytes": len(pm_changed),
                "first_changed": pm_changed[0] if pm_changed else None,
                "last_changed": pm_changed[-1] if pm_changed else None,
            }
            if pm_stray:
                raise RuntimeError(
                    f"refusing to write: {len(pm_stray)} patched byte(s) fall OUTSIDE the MartItems pool "
                    f"[{pm_pool_base:#x}, {pm_pool_end:#x}) (first stray offset {pm_stray[0]:#x}) -- the mart walk "
                    "strayed into another table, which is exactly what corrupted the shop REL's relocation table "
                    "in the ADDENDUM 127 build"
                )
            rel_format.validate_rel_structure(bytes(pm_rel_bytes), label=f"patched {pm_rel_name}")
            if pm_is_lzss:
                # allow_grow left False: this only overwrites existing 2-byte item-id fields, never grows.
                pm_new_entry_raw, pm_real_comp_size, _pm_grew = deck_format.patch_entry_decompressed(
                    pm_entry_raw, bytes(pm_rel_bytes)
                )
            else:
                # Uncompressed entry: a same-length overwrite, so comp_size stays as it was.
                pm_new_entry_raw = bytes(pm_rel_bytes)
                pm_real_comp_size = pm_rel_entry["comp_size"]
            # Never write past this entry's real span to the next data_off, same rule as the deck path.
            pm_later_offs = sorted(x["data_off"] for x in pm_all_entries if x["data_off"] > pm_rel_entry["data_off"])
            pm_span = (pm_later_offs[0] if pm_later_offs else len(pm_bytes)) - pm_rel_entry["data_off"]
            if len(pm_new_entry_raw) > pm_span:
                raise RuntimeError(
                    f"refusing to write: new {pm_rel_name} blob ({len(pm_new_entry_raw)} bytes) exceeds the entry's "
                    f"physical span to the next entry ({pm_span} bytes)"
                )

            writer = open_writer(output_path)
            try:
                writer.write(pm_abs_entry_off, pm_new_entry_raw)
                if pm_is_lzss:
                    writer.write(pm_abs_record_comp_size_off, struct.pack(">I", pm_real_comp_size))
            finally:
                writer.close()

            verify_reader = open_reader(output_path)
            try:
                pm_reread = verify_reader.read(pm_abs_entry_off, len(pm_new_entry_raw))
                pm_reread_record_comp_size = verify_reader.read(pm_abs_record_comp_size_off, 4)
            finally:
                verify_reader.close()
            if pm_reread != pm_new_entry_raw:
                raise RuntimeError(
                    "read-back verification failed -- the shop/mart pocket_menu_rel write did not stick"
                )
            pm_redecoded = deck_format.lzss_decode(pm_reread) if pm_is_lzss else bytes(pm_reread)
            if pm_redecoded != bytes(pm_rel_bytes):
                raise RuntimeError(
                    "read-back verification failed -- re-decoded pocket_menu_rel table bytes don't match the "
                    "intended patch"
                )
            if struct.unpack(">I", pm_reread_record_comp_size)[0] != pm_real_comp_size:
                raise RuntimeError(
                    "read-back verification failed -- pocket_menu.fsys's REL entry FSYS record comp_size "
                    "didn't stick"
                )

            print(
                f"Patched {shop_slots_patched} shop item slots (entry {pm_rel_name!r}, "
                f"{'LZSS' if pm_is_lzss else 'uncompressed'}, {pm_mart_count} marts) across "
                f"{len(shop_dummy_item_ids)} rotating dummy berry ids into {output_path}. "
                f"{len(shop_excluded_item_ids)} excluded item id(s) (Agate Village Scents, Poke Snack) left "
                f"untouched."
            )
            # Print the vanilla mart census once, so the real per-shop layout is on record for the client.
            by_mart: dict[int, list[str]] = {}
            for c in pm_census:
                by_mart.setdefault(c["mart_index"], []).append(c["item"])
            for mart_index in sorted(by_mart):
                print(f"  mart {mart_index}: {', '.join(by_mart[mart_index])}")
            summary["shop_slots_patched"] = shop_slots_patched
            # Always leave the shop diagnostic next to the ISO, success included: the chosen entry's complete
            # raw bytes plus REL structure, mart starts and write set, so the next report can be analysed
            # offline from real bytes rather than a console screenshot.
            try:
                ok_lines = [
                    "Pokemon XD Archipelago -- shop/mart randomization diagnostic",
                    "=" * 63,
                    "",
                    f"Status: OK -- patched {shop_slots_patched} slot(s) in {pm_rel_name!r} ({pm_mart_count} marts)",
                    "",
                    "pocket_menu.fsys entries (index, base name, full name, file-format byte, data_off, decomp/comp size):",
                ]
                for x in summary["shop_pocket_menu_entries"] or []:
                    ok_lines.append(
                        f"  #{x['index']}: {x['name']!r} full={x['full_name']!r} format={x['file_format']} "
                        f"data_off={x['data_off']} decomp={x['decomp_size']} comp={x['comp_size']}"
                    )
                ok_lines += ["", "Mart-REL candidates tried, in order:"]
                ok_lines += [f"  {a}" for a in pm_attempts]
                ok_lines += ["", "Decoded REL structure (ADDENDUM 128 validator):", f"  header: {pm_structure['header']}"]
                for si, s in enumerate(pm_structure["sections"]):
                    if s["size"]:
                        ok_lines.append(f"  section {si}: offset {s['offset']:#x} size {s['size']:#x} exec={s['exec']}")
                for imp in pm_structure["imports"]:
                    ok_lines.append(
                        f"  import module {imp['module']}: relocations at {imp['rel_offset']:#x}, {imp['entries']} "
                        f"entries, END at {imp['end_offset'] - 8:#x}"
                    )
                ok_lines += [
                    "",
                    f"MartStartIndexes at {rel_format.mart_start_indexes_base(pm_rel):#x}, MartItems pool at "
                    f"{pm_pool_base:#x}..{pm_pool_end:#x} (structural end), NumberOfMartItems="
                    f"{rel_format.number_of_mart_items(pm_rel)}, NumberOfMarts={pm_mart_count}",
                    f"Write set: {summary['shop_write_set']}",
                    "",
                    "Per-mart vanilla census (FirstItemIndex read at entry +2 per the reference randomizer):",
                ]
                for mart_index in range(pm_mart_count):
                    start_idx = rel_format.mart_first_item_index(pm_rel, mart_index)
                    ok_lines.append(
                        f"  mart {mart_index} (start {start_idx}, limit {rel_format.mart_slot_limit(pm_rel, mart_index)}): "
                        + ", ".join(by_mart.get(mart_index, []))
                    )
                pm_entry_span_bytes = pm_entry_raw[: pm_rel_entry["comp_size"] if pm_is_lzss else pm_rel_entry["decomp_size"]]
                ok_lines += [
                    "",
                    f"Raw ORIGINAL bytes of {pm_rel_name!r} (FSYS record data_off={pm_rel_entry['data_off']} "
                    f"comp={pm_rel_entry['comp_size']} decomp={pm_rel_entry['decomp_size']}, at ISO offset "
                    f"{pm_abs_entry_off}), hex, ALL {len(pm_entry_span_bytes)} bytes -- for offline analysis:",
                ]
                raw_hex = pm_entry_span_bytes.hex()
                for i in range(0, len(raw_hex), 64):
                    ok_lines.append(f"  {i // 2:06X}: {raw_hex[i:i + 64]}")
                ok_lines += ["", f"New entry written: {len(pm_new_entry_raw)} bytes, declared comp_size {pm_real_comp_size}"]
                ok_path = output_path.parent / f"{output_path.stem}_shop_diagnostic.txt"
                ok_path.write_text("\n".join(ok_lines) + "\n", encoding="utf-8")
                summary["shop_diagnostic_file"] = str(ok_path)
                print(f"  Shop diagnostic (structure, census, full raw entry bytes) written to: {ok_path}")
            except Exception as diag_exc:  # pragma: no cover -- diagnostics are best-effort, never fatal
                print(f"  (could not write the shop diagnostic file: {diag_exc})")
        except Exception as exc:
            shop_slots_patched = 0
            shop_randomization_error = str(exc)
            # Best-effort diagnostics: parse_fsys/parse_fst report real sizes without decoding anything, so a
            # failure can still identify the real container in this same attempt. entry_sizes covers
            # pocket_menu.fsys's entries, which all look like Bag-menu UI textures; fst_listing covers the whole
            # disc, so a mart container elsewhere can be found by name without a second run.
            entry_sizes = None
            try:
                entry_sizes = {name: entry["decomp_size"] for name, entry in pm_fsys_entries.items()}
            except NameError:
                pass
            # Dump the candidate entries' raw bytes so the real thing can be analysed offline.
            pm_hex_dump = None
            try:
                pm_hex_dump = {
                    "entries": summary.get("shop_pocket_menu_entries"),
                    "attempts": summary.get("shop_pocket_menu_attempts"),
                    "candidates": [
                        {
                            "label": f"#{e['index']} {e['full_name'] or e['name']!r} (format {e['file_format']})",
                            "record": {k: e[k] for k in ("data_off", "decomp_size", "comp_size", "record_off")},
                            "abs_entry_off": abs_entry_off,
                            # The whole entry -- an offline decode needs every byte.
                            "raw_hex": entry_raw[: max(e["comp_size"], 0x10 + 2048)].hex(),
                        }
                        for e, abs_entry_off, entry_raw in pm_candidate_raws
                    ],
                }
            except NameError:
                pass
            fst_listing = None
            try:
                fst_listing = {path: length for path, (_off, length, _rec) in fst.items()}
            except NameError:
                pass
            # The FST dump surfaced 7 per-town "shop"-named containers (M1_shop_1F.fsys etc.) that may hold the
            # real mart data. Three read-only scans, increasingly specific: list each one's FSYS entries;
            # decompress every entry (nothing here is confirmed to use the "rel" naming convention) and look for
            # runs of known item ids; and try each container's base-name entry as a `RelFile` against the
            # confirmed mart pointer walk. The last is speculative, since pointer-index meanings are plausibly
            # scoped per REL kind, but cheap. Nothing here writes.
            shop_file_scan = None
            shop_item_id_scan = {}
            valid_item_ids = set(known_item_id_names.keys())
            shop_mart_rel_scan = {}
            _MART_SCAN_MAX_PLAUSIBLE_MART_COUNT = 500
            if fst_listing:
                shop_named_files = sorted(
                    p for p in fst_listing if "shop" in p.lower() and p.lower().endswith(".fsys")
                )
                if shop_named_files:
                    shop_file_scan = {}
                    reader2 = open_reader(output_path)
                    try:
                        for path in shop_named_files:
                            try:
                                off, length, _rec = fst[path]
                                raw = reader2.read(off, length)
                                inner_entries = parse_fsys(raw)
                                shop_file_scan[path] = {
                                    name: e["decomp_size"] for name, e in inner_entries.items()
                                }
                                if valid_item_ids:
                                    for entry_name, entry_meta in inner_entries.items():
                                        try:
                                            entry_abs_off = off + entry_meta["data_off"]
                                            entry_raw_len = 0x10 + entry_meta["comp_size"]
                                            entry_raw = reader2.read(entry_abs_off, entry_raw_len)
                                            entry_decompressed = deck_format.lzss_decode(entry_raw)
                                        except Exception:
                                            continue  # not every entry need be LZSS-compressed data at all
                                        runs = rel_format.scan_bytes_for_item_id_runs(
                                            entry_decompressed, valid_item_ids, min_run_length=3
                                        )
                                        if runs:
                                            shop_item_id_scan.setdefault(path, {})[entry_name] = [
                                                {
                                                    "offset": run["offset"],
                                                    "items": [
                                                        f"{iid} ({known_item_id_names.get(iid, '?')})"
                                                        for iid in run["item_ids"]
                                                    ],
                                                }
                                                for run in runs
                                            ]
                                own_entry_name = path.rsplit("/", 1)[-1]
                                if own_entry_name.lower().endswith(".fsys"):
                                    own_entry_name = own_entry_name[: -len(".fsys")]
                                own_entry_meta = inner_entries.get(own_entry_name)
                                if own_entry_meta is not None:
                                    try:
                                        own_abs_off = off + own_entry_meta["data_off"]
                                        own_raw_len = 0x10 + own_entry_meta["comp_size"]
                                        own_raw = reader2.read(own_abs_off, own_raw_len)
                                        own_decompressed = deck_format.lzss_decode(own_raw)
                                        own_rel = rel_format.RelFile(
                                            own_decompressed, is_common=False,
                                            label=f"{path} entry '{own_entry_name}'"
                                        )
                                        mart_count = rel_format.number_of_marts(own_rel)
                                        if mart_count <= 0 or mart_count > _MART_SCAN_MAX_PLAUSIBLE_MART_COUNT:
                                            shop_mart_rel_scan[path] = (
                                                f"decoded as a REL, but its own NumberOfMarts value "
                                                f"({mart_count}) is not plausible -- not a real mart table"
                                            )
                                        else:
                                            slots = rel_format.read_all_mart_slots(own_rel)
                                            shop_mart_rel_scan[path] = {
                                                "number_of_marts": mart_count,
                                                "slots": [
                                                    {
                                                        "mart_index": s["mart_index"],
                                                        "pool_index": s["pool_index"],
                                                        "item": (
                                                            f"{s['item_id']} "
                                                            f"({known_item_id_names.get(s['item_id'], '?')})"
                                                        ),
                                                    }
                                                    for s in slots
                                                ],
                                            }
                                    except Exception as mart_exc:
                                        shop_mart_rel_scan[path] = f"not a valid mart-table REL ({mart_exc})"
                            except Exception as inner_exc:
                                shop_file_scan[path] = f"could not parse as FSYS ({inner_exc})"
                    finally:
                        reader2.close()
            # To a file, not the console: the full FST listing alone is 2562 entries.
            diagnostic_lines = [
                "Pokemon XD Archipelago -- shop/mart randomization diagnostic",
                "=" * 63,
                "",
                f"Error: {shop_randomization_error}",
                "",
            ]
            if entry_sizes:
                diagnostic_lines.append("pocket_menu.fsys entries (name: decompressed size in bytes):")
                for name, size in entry_sizes.items():
                    diagnostic_lines.append(f"  {name}: {size}")
                diagnostic_lines.append("")
            if pm_hex_dump:
                if pm_hex_dump.get("entries"):
                    diagnostic_lines.append(
                        "NEW (ADDENDUM 126) -- EVERY entry in pocket_menu.fsys (index, base name, full name, "
                        "file-format byte, data_off, decomp/comp size) -- duplicates of a base name are the point:"
                    )
                    for e in pm_hex_dump["entries"]:
                        diagnostic_lines.append(
                            f"  #{e['index']}: {e['name']!r} full={e['full_name']!r} format={e['file_format']} "
                            f"data_off={e['data_off']} decomp={e['decomp_size']} comp={e['comp_size']}"
                        )
                    diagnostic_lines.append("")
                if pm_hex_dump.get("attempts"):
                    diagnostic_lines.append("Mart-REL candidates tried (ADDENDUM 126), in order:")
                    for a in pm_hex_dump["attempts"]:
                        diagnostic_lines.append(f"  {a}")
                    diagnostic_lines.append("")
                for cand in pm_hex_dump.get("candidates") or []:
                    diagnostic_lines.append(
                        f"Raw bytes of candidate {cand['label']} (FSYS record {cand['record']}, at ISO offset "
                        f"{cand['abs_entry_off']}), hex, first {len(cand['raw_hex']) // 2} bytes -- for offline analysis:"
                    )
                    raw_hex = cand["raw_hex"]
                    for i in range(0, len(raw_hex), 64):
                        diagnostic_lines.append(f"  {i // 2:06X}: {raw_hex[i:i + 64]}")
                    diagnostic_lines.append("")
            if shop_file_scan:
                diagnostic_lines.append(
                    "Per-town \"shop\"-named on-disc container internal entries "
                    "(name: decompressed size in bytes):"
                )
                for path, inner in shop_file_scan.items():
                    diagnostic_lines.append(f"  {path}:")
                    if isinstance(inner, dict):
                        for name, size in inner.items():
                            diagnostic_lines.append(f"    {name}: {size}")
                    else:
                        diagnostic_lines.append(f"    {inner}")
                diagnostic_lines.append("")
            if shop_item_id_scan:
                diagnostic_lines.append(
                    "NEW (ADDENDUM 119) -- candidate mart/shop item-id lists found by pattern-matching every "
                    "shop-named container's own internal entries for runs of 3+ consecutive KNOWN, VALID item "
                    "ids ending in a 0x0000 sentinel (this is a read-only scan -- nothing below was written to "
                    "the ISO; these are just candidates worth a human eyeball on the actual in-game shop "
                    "contents):"
                )
                for path, entries in shop_item_id_scan.items():
                    diagnostic_lines.append(f"  {path}:")
                    for entry_name, runs in entries.items():
                        diagnostic_lines.append(f"    {entry_name}:")
                        for run in runs:
                            diagnostic_lines.append(f"      @0x{run['offset']:X}: {', '.join(run['items'])}")
                diagnostic_lines.append("")
            elif known_item_id_names and shop_file_scan:
                diagnostic_lines.append(
                    "NEW (ADDENDUM 119): scanned every shop-named container's internal entries for candidate "
                    "item-id lists (3+ consecutive known item ids ending in a 0x0000 sentinel) -- found none. "
                    "Either the real mart data uses a different shape than expected (not a flat sentinel-"
                    "terminated id list), lives somewhere other than these 7 containers, or is compressed/"
                    "encoded in a way this scan didn't decode."
                )
                diagnostic_lines.append("")
            if shop_mart_rel_scan:
                diagnostic_lines.append(
                    "NEW (ADDENDUM 119) -- second, separate attempt: tried decoding each shop-named "
                    "container's OWN entry (matching its own base name) as a REL and running the ALREADY-"
                    "CONFIRMED mart-table pointer walk against it (same code pocket_menu.fsys's patch attempt "
                    "uses). Speculative -- pointer-index MEANINGS are plausibly scoped per REL kind, so this "
                    "isn't guaranteed to apply to a town map's own REL -- but read-only and cheap to rule out:"
                )
                for path, result in shop_mart_rel_scan.items():
                    if isinstance(result, dict):
                        diagnostic_lines.append(
                            f"  {path}: NumberOfMarts={result['number_of_marts']}, "
                            f"{len(result['slots'])} real slot(s):"
                        )
                        for slot in result["slots"]:
                            diagnostic_lines.append(
                                f"    mart {slot['mart_index']} / pool {slot['pool_index']}: {slot['item']}"
                            )
                    else:
                        diagnostic_lines.append(f"  {path}: {result}")
                diagnostic_lines.append("")
            if fst_listing:
                diagnostic_lines.append(f"Full on-disc file list (path: length in bytes), {len(fst_listing)} entries:")
                for path, length in fst_listing.items():
                    diagnostic_lines.append(f"  {path}: {length}")
                diagnostic_lines.append("")
            diagnostic_path = output_path.parent / f"{output_path.stem}_shop_diagnostic.txt"
            shop_diagnostic_written = False
            try:
                diagnostic_path.write_text("\n".join(diagnostic_lines), encoding="utf-8")
                shop_diagnostic_written = True
            except OSError:
                pass  # best-effort -- fall back to the console dump below if the file can't be written
            print(
                f"WARNING: shop/mart randomization FAILED and was SKIPPED -- every other patch in this run "
                f"(trainers, chests, Poke Spots, AP Item rename) still applied and verified normally. Error: "
                f"{shop_randomization_error}"
            )
            if shop_diagnostic_written:
                print(f"  Diagnostic data (entry sizes, shop-file scan, full disc file list) written to: {diagnostic_path}")
            else:
                # Fallback: couldn't write the file (e.g. read-only folder) -- still get the data out somehow.
                if entry_sizes:
                    print(f"  pocket_menu.fsys entries (name: decompressed size in bytes): {entry_sizes}")
                if shop_file_scan:
                    print(f"  Per-town shop-file internal entries: {shop_file_scan}")
                if shop_item_id_scan:
                    print(f"  Candidate mart/shop item-id lists (ADDENDUM 119 scan): {shop_item_id_scan}")
                if shop_mart_rel_scan:
                    print(f"  Own-entry REL mart-table attempt (ADDENDUM 119): {shop_mart_rel_scan}")
                if fst_listing:
                    print(
                        f"  Full on-disc file list (path: length in bytes), {len(fst_listing)} entries: "
                        f"{fst_listing}"
                    )
            summary["shop_diagnostic_file"] = str(diagnostic_path) if shop_diagnostic_written else None
            summary["shop_item_id_scan"] = shop_item_id_scan
            summary["shop_mart_rel_scan"] = shop_mart_rel_scan
        summary["shop_randomization_error"] = shop_randomization_error
    else:
        print("This seed has no shop_dummy_item_ids data (shop randomization was off) -- shops left untouched.")

    print("Read-back verification passed for every patch step applied above.")
    return summary


# Diagnostic-only: relocation isolation test.

def apply_relocation_isolation_test(source_path: Path, output_path: Path, overwrite: bool = False) -> dict:
    """DIAGNOSTIC ONLY. Relocates `deck_archive.fsys` to free trailing disc space with its bytes copied
    VERBATIM -- no decode, no re-encode, no content change -- so only its FST record's offset field changes.
    No encoder is invoked at all, which is the point: it isolates the act of moving the file."""
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()

    if output_path == source_path:
        raise ValueError("output path must be different from the source ISO -- refusing to write over it")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} already exists -- pass --overwrite to replace it")

    chunked_copy(source_path, output_path)

    reader = open_reader(output_path)
    try:
        fst = parse_fst(reader)
        deck_archive_off, deck_archive_len, deck_archive_record_off = find_by_basename(fst, "deck_archive.fsys")
        container_bytes = reader.read(deck_archive_off, deck_archive_len)
    finally:
        reader.close()

    # Refuse rather than relocate bytes this tool can't account for.
    fsys_entries = parse_fsys(container_bytes)
    if "DeckData_Story.bin" not in fsys_entries:
        raise ValueError(
            "deck_archive.fsys on this disc doesn't contain a recognizable DeckData_Story.bin entry -- refusing "
            "to relocate a container this tool can't verify the shape of."
        )

    writer = open_writer(output_path)
    try:
        new_offset = find_free_region(writer, len(container_bytes))
        writer.ensure_region_allocated(new_offset, len(container_bytes))  # no-op for a plain ISO
        writer.write(new_offset, container_bytes)
        record_file_offset_off = deck_archive_record_off + FST_RECORD_FILE_OFFSET_OFF
        writer.write(record_file_offset_off, struct.pack(">I", new_offset))
        # File length is deliberately left untouched -- content is byte-identical, so it hasn't changed.
    finally:
        writer.close()

    verify_reader = open_reader(output_path)
    try:
        reread_container = verify_reader.read(new_offset, len(container_bytes))
        reread_fst = parse_fst(verify_reader)
    finally:
        verify_reader.close()

    if reread_container != container_bytes:
        raise RuntimeError(
            "read-back verification failed -- the relocated deck_archive.fsys container's on-disc bytes at the "
            "new location don't match what was written. Refusing to consider this a valid test result -- "
            "something is wrong with the relocation write itself, not (yet) a question about real-hardware "
            "boot behavior."
        )
    reread_off, reread_len, _ = find_by_basename(reread_fst, "deck_archive.fsys")
    if reread_off != new_offset or reread_len != deck_archive_len:
        raise RuntimeError(
            f"read-back verification failed -- deck_archive.fsys's FST record reads offset={reread_off}, "
            f"length={reread_len} after the patch; expected offset={new_offset}, length={deck_archive_len}."
        )

    print(
        f"Relocation isolation test applied to {output_path}: deck_archive.fsys moved from ISO offset "
        f"{deck_archive_off} to {new_offset} (length unchanged, {deck_archive_len} bytes; content byte-"
        "identical to the source -- zero gameplay content differs from vanilla). Read-back verification "
        "passed. This ISO should be indistinguishable from vanilla in every way EXCEPT deck_archive.fsys's "
        "disc position -- boot it and confirm the main menu renders correctly and at least one real trainer "
        "battle (which also exercises DeckData_DarkPokemon.bin / Shadow Pokemon data from the same relocated "
        "container) works normally, to test whether relocating this specific file is itself safe on real "
        "hardware."
    )
    return {
        "output": str(output_path),
        "old_offset": deck_archive_off,
        "new_offset": new_offset,
        "length": deck_archive_len,
    }


# Diagnostic-only: common.fsys-ONLY relocation isolation test.

def apply_common_fsys_relocation_isolation_test(
    source_path: Path, output_path: Path, overwrite: bool = False,
) -> dict:
    """DIAGNOSTIC ONLY -- `apply_relocation_isolation_test` for `common.fsys`. `deck_archive.fsys` is not
    opened or referenced at all. Chasing a splash-screen freeze whose signature is the game's own `_fsysForegroundTask:ERROR_FILEOPEN:10`
    looping, with the FST separately verified byte-clean. deck_archive.fsys relocating alone is safe, so the game
    finds it by FST lookup; `common.fsys` may instead be loaded from a hardcoded offset in the executable, which
    an FST parser cannot see is wrong."""
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()

    if output_path == source_path:
        raise ValueError("output path must be different from the source ISO -- refusing to write over it")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} already exists -- pass --overwrite to replace it")

    chunked_copy(source_path, output_path)

    reader = open_reader(output_path)
    try:
        fst = parse_fst(reader)
        common_off, common_len, common_record_off = find_by_basename(fst, "common.fsys")
        container_bytes = reader.read(common_off, common_len)
    finally:
        reader.close()

    fsys_entries = parse_fsys(container_bytes)
    for required in ("DeckData_DarkPokemon.bin", "DeckData_DarkPokemon_EU.bin"):
        if required not in fsys_entries:
            raise ValueError(
                f"common.fsys on this disc doesn't contain a recognizable {required} entry -- refusing to "
                "relocate a container this tool can't verify the shape of."
            )

    writer = open_writer(output_path)
    try:
        new_offset = find_free_region(writer, len(container_bytes))
        writer.ensure_region_allocated(new_offset, len(container_bytes))  # no-op for a plain ISO
        writer.write(new_offset, container_bytes)
        record_file_offset_off = common_record_off + FST_RECORD_FILE_OFFSET_OFF
        writer.write(record_file_offset_off, struct.pack(">I", new_offset))
        # File length is deliberately left untouched -- content is byte-identical, so it hasn't changed.
    finally:
        writer.close()

    verify_reader = open_reader(output_path)
    try:
        reread_container = verify_reader.read(new_offset, len(container_bytes))
        reread_fst = parse_fst(verify_reader)
    finally:
        verify_reader.close()

    if reread_container != container_bytes:
        raise RuntimeError(
            "read-back verification failed -- the relocated common.fsys container's on-disc bytes at the new "
            "location don't match what was written. Refusing to consider this a valid test result -- "
            "something is wrong with the relocation write itself, not (yet) a question about real boot "
            "behavior."
        )
    reread_off, reread_len, _ = find_by_basename(reread_fst, "common.fsys")
    if reread_off != new_offset or reread_len != common_len:
        raise RuntimeError(
            f"read-back verification failed -- common.fsys's FST record reads offset={reread_off}, "
            f"length={reread_len} after the patch; expected offset={new_offset}, length={common_len}."
        )

    print(
        f"common.fsys-ONLY relocation isolation test applied to {output_path}: common.fsys moved from ISO "
        f"offset {common_off} to {new_offset} (length unchanged, {common_len} bytes; content byte-identical "
        "to the source -- zero gameplay content differs from vanilla). deck_archive.fsys was never opened by "
        "this function and is byte-identical to the source ISO. Read-back verification passed. Boot this ISO "
        "and watch the Nintendo splash screen closely: a repeating '_fsysForegroundTask:ERROR_FILEOPEN' in "
        "Dolphin's log at this point would confirm common.fsys's relocation alone (independent of any Shadow "
        "Pokemon content, independent of deck_archive.fsys also moving) is what the game can't follow; a "
        "clean boot rules that out."
    )
    return {
        "output": str(output_path),
        "old_offset": common_off,
        "new_offset": new_offset,
        "length": common_len,
    }


# Diagnostic-only: BOTH-containers relocation isolation test.

def apply_dual_relocation_isolation_test(
    source_path: Path, output_path: Path, overwrite: bool = False,
) -> dict:
    """DIAGNOSTIC ONLY -- both relocation isolation tests in ONE build, zero content change either side. Each
    alone already boots clean; no build had relocated both without also changing Shadow data, which confounded
    "two relocations" with "content growth"."""
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()

    if output_path == source_path:
        raise ValueError("output path must be different from the source ISO -- refusing to write over it")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} already exists -- pass --overwrite to replace it")

    chunked_copy(source_path, output_path)

    # ---- Pass 1: relocate deck_archive.fsys, zero content change ----
    reader = open_reader(output_path)
    try:
        fst = parse_fst(reader)
        deck_off, deck_len, deck_record_off = find_by_basename(fst, "deck_archive.fsys")
        deck_bytes = reader.read(deck_off, deck_len)
    finally:
        reader.close()

    deck_entries = parse_fsys(deck_bytes)
    if "DeckData_Story.bin" not in deck_entries:
        raise ValueError(
            "deck_archive.fsys on this disc doesn't contain a recognizable DeckData_Story.bin entry -- "
            "refusing to relocate a container this tool can't verify the shape of."
        )

    writer = open_writer(output_path)
    try:
        deck_new_offset = find_free_region(writer, len(deck_bytes))
        writer.ensure_region_allocated(deck_new_offset, len(deck_bytes))
        writer.write(deck_new_offset, deck_bytes)
        writer.write(deck_record_off + FST_RECORD_FILE_OFFSET_OFF, struct.pack(">I", deck_new_offset))
    finally:
        writer.close()

    # ---- Pass 2: relocate common.fsys, zero content change (fresh reader/writer, sees Pass 1's changes) ----
    reader = open_reader(output_path)
    try:
        fst2 = parse_fst(reader)
        common_off, common_len, common_record_off = find_by_basename(fst2, "common.fsys")
        common_bytes = reader.read(common_off, common_len)
    finally:
        reader.close()

    common_entries = parse_fsys(common_bytes)
    for required in ("DeckData_DarkPokemon.bin", "DeckData_DarkPokemon_EU.bin"):
        if required not in common_entries:
            raise ValueError(
                f"common.fsys on this disc doesn't contain a recognizable {required} entry -- refusing to "
                "relocate a container this tool can't verify the shape of."
            )

    writer = open_writer(output_path)
    try:
        common_new_offset = find_free_region(writer, len(common_bytes))
        writer.ensure_region_allocated(common_new_offset, len(common_bytes))
        writer.write(common_new_offset, common_bytes)
        writer.write(common_record_off + FST_RECORD_FILE_OFFSET_OFF, struct.pack(">I", common_new_offset))
    finally:
        writer.close()

    # ---- Verify both, independently, straight from the final file ----
    verify_reader = open_reader(output_path)
    try:
        reread_fst = parse_fst(verify_reader)
        reread_deck = verify_reader.read(deck_new_offset, len(deck_bytes))
        reread_common = verify_reader.read(common_new_offset, len(common_bytes))
    finally:
        verify_reader.close()

    if reread_deck != deck_bytes:
        raise RuntimeError(
            "read-back verification failed -- the relocated deck_archive.fsys container's on-disc bytes "
            "don't match what was written."
        )
    if reread_common != common_bytes:
        raise RuntimeError(
            "read-back verification failed -- the relocated common.fsys container's on-disc bytes don't "
            "match what was written."
        )
    d_off, d_len, _ = find_by_basename(reread_fst, "deck_archive.fsys")
    if d_off != deck_new_offset or d_len != deck_len:
        raise RuntimeError(
            f"read-back verification failed -- deck_archive.fsys's FST record reads offset={d_off}, "
            f"length={d_len}; expected offset={deck_new_offset}, length={deck_len}."
        )
    c_off, c_len, _ = find_by_basename(reread_fst, "common.fsys")
    if c_off != common_new_offset or c_len != common_len:
        raise RuntimeError(
            f"read-back verification failed -- common.fsys's FST record reads offset={c_off}, "
            f"length={c_len}; expected offset={common_new_offset}, length={common_len}."
        )
    if d_off < c_off + c_len and c_off < d_off + d_len:
        raise RuntimeError(
            f"the two relocated containers overlap on disc: deck_archive.fsys=[{d_off}, {d_off + d_len}), "
            f"common.fsys=[{c_off}, {c_off + c_len}) -- refusing to consider this a valid test result."
        )

    print(
        f"Dual relocation isolation test applied to {output_path}: deck_archive.fsys moved {deck_off} -> "
        f"{deck_new_offset} ({deck_len} bytes), common.fsys moved {common_off} -> {common_new_offset} "
        f"({common_len} bytes). Both content byte-identical to the source -- zero gameplay content differs "
        "from vanilla, only disc position for both files. Read-back verification passed, no overlap between "
        "the two new regions. Boot this ISO and watch the Nintendo splash screen: a repeating "
        "'_fsysForegroundTask:ERROR_FILEOPEN' here would confirm two simultaneous relocations (independent of "
        "any content growth) is what breaks; a clean boot instead points at content growth combined with "
        "relocation as the real remaining variable."
    )
    return {
        "output": str(output_path),
        "deck_archive_old_offset": deck_off, "deck_archive_new_offset": deck_new_offset,
        "common_fsys_old_offset": common_off, "common_fsys_new_offset": common_new_offset,
    }


# Diagnostic-only: real DarkPokemon content growth + relocation, ZERO Story.bin change.

def apply_darkpokemon_content_relocation_test(
    source_path: Path, output_path: Path, num_new_entries: int = 5, borrow_dpkm_index: int = 1,
    overwrite: bool = False,
) -> dict:
    """DIAGNOSTIC ONLY -- isolates DarkPokemon content growth, the only one of the three things a real
    content-bearing build changes at once that crosses the real safe span (in the failing build Story.bin's own
    comp size actually shrank). Writes `num_new_entries` real DDPK entries (default 5, the measured minimum that crosses the threshold) into
    free padding slots (84+) in all three DarkPokemon copies, with real shadow moves and an existing DPKM index
    BORROWED as `story_deck_index`. Nothing is linked to a trainer and `DeckData_Story.bin` is never opened."""
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()

    if output_path == source_path:
        raise ValueError("output path must be different from the source ISO -- refusing to write over it")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} already exists -- pass --overwrite to replace it")
    if num_new_entries < 1:
        raise ValueError("num_new_entries must be at least 1")

    chunked_copy(source_path, output_path)

    # ---- Pass 1: deck_archive.fsys -- ONLY DeckData_DarkPokemon.bin edited. DeckData_Story.bin untouched. ----
    reader = open_reader(output_path)
    try:
        fst = parse_fst(reader)
        deck_off, deck_len, deck_record_off = find_by_basename(fst, "deck_archive.fsys")
        deck_fsys_bytes = reader.read(deck_off, deck_len)
        deck_entries = parse_fsys(deck_fsys_bytes)
        dark_entry = deck_entries["DeckData_DarkPokemon.bin"]
        dark_raw = reader.read(deck_off + dark_entry["data_off"], 0x10 + dark_entry["comp_size"])
    finally:
        reader.close()

    dark_decompressed = deck_format.lzss_decode(dark_raw)
    ddpk = deck_format.DarkPokemonFile(dark_decompressed)

    # borrow_dpkm_index is trusted at face value -- verifying it would mean opening the entry this test leaves
    # alone.

    free_ddpk = [i for i in range(ddpk.ddpk_entries) if i != 0 and not ddpk.ddpk_full(i)["in_use"]]
    if len(free_ddpk) < num_new_entries:
        raise ValueError(
            f"only {len(free_ddpk)} free DDPK indices available, need {num_new_entries}"
        )
    target_indices = free_ddpk[:num_new_entries]
    # Each slot rotates through its OWN measured legal list: 368, 370 and 372 never appear in slot 0 in any
    # vanilla entry, and 364 and 366 never appear outside it. The rotation is fixed rather than seed-random so
    # the same seed patches identically.
    _slots = _shadow_move_slots

    slot0_pool = list(_slots.MOVES_LEGAL_IN_SLOT[0])
    slot1_pool = list(_slots.MOVES_LEGAL_IN_SLOT[1])

    new_dark_decompressed = dark_decompressed
    for i, ddpk_index in enumerate(target_indices):
        shadow_moves = [slot0_pool[i % len(slot0_pool)], slot1_pool[i % len(slot1_pool)]]
        new_dark_decompressed = _overwrite_ddpk_entry_bytes(
            new_dark_decompressed, ddpk, ddpk_index, borrow_dpkm_index, 10 + i, shadow_moves
        )

    deck_patch_result = write_fsys_multi_entry_patch(
        output_path, deck_off, deck_len, deck_record_off, deck_fsys_bytes,
        [{"name": "DeckData_DarkPokemon.bin", "entry_raw": dark_raw, "new_decompressed": new_dark_decompressed,
          "allow_decomp_resize": False}],
    )

    # ---- Pass 2: common.fsys -- both DarkPokemon copies, same content, mirrored ----
    reader = open_reader(output_path)
    try:
        fst2 = parse_fst(reader)
        common_off, common_len, common_record_off = find_by_basename(fst2, "common.fsys")
        common_fsys_bytes = reader.read(common_off, common_len)
        common_entries = parse_fsys(common_fsys_bytes)
        if "DeckData_DarkPokemon.bin" not in common_entries or "DeckData_DarkPokemon_EU.bin" not in common_entries:
            raise ValueError(
                "common.fsys on this ISO doesn't contain both expected DarkPokemon entries -- refusing to "
                "guess at a different disc layout."
            )
        common_dark_entry = common_entries["DeckData_DarkPokemon.bin"]
        common_dark_raw = reader.read(common_off + common_dark_entry["data_off"], 0x10 + common_dark_entry["comp_size"])
        common_eu_entry = common_entries["DeckData_DarkPokemon_EU.bin"]
        common_eu_raw = reader.read(common_off + common_eu_entry["data_off"], 0x10 + common_eu_entry["comp_size"])
    finally:
        reader.close()

    common_dark_decompressed = deck_format.lzss_decode(common_dark_raw)
    common_ddpk = deck_format.DarkPokemonFile(common_dark_decompressed)
    common_eu_decompressed = deck_format.lzss_decode(common_eu_raw)
    common_eu_ddpk = deck_format.DarkPokemonFile(common_eu_decompressed)

    new_common_dark_decompressed = common_dark_decompressed
    new_common_eu_decompressed = common_eu_decompressed
    for i, ddpk_index in enumerate(target_indices):
        if common_ddpk.ddpk_full(ddpk_index)["in_use"] or common_eu_ddpk.ddpk_full(ddpk_index)["in_use"]:
            raise ValueError(
                f"ddpk_index {ddpk_index} is ALREADY in-use in one of common.fsys's DarkPokemon copies -- "
                "unexpected mismatch with deck_archive.fsys's copy, refusing rather than guessing."
            )
        # Same rotation as the deck_archive copy: these copies must stay byte-identical.
        shadow_moves = [slot0_pool[i % len(slot0_pool)], slot1_pool[i % len(slot1_pool)]]
        new_common_dark_decompressed = _overwrite_ddpk_entry_bytes(
            new_common_dark_decompressed, common_ddpk, ddpk_index, borrow_dpkm_index, 10 + i, shadow_moves
        )
        new_common_eu_decompressed = _overwrite_ddpk_entry_bytes(
            new_common_eu_decompressed, common_eu_ddpk, ddpk_index, borrow_dpkm_index, 10 + i, shadow_moves
        )

    common_patch_result = write_fsys_multi_entry_patch(
        output_path, common_off, common_len, common_record_off, common_fsys_bytes,
        [
            {"name": "DeckData_DarkPokemon.bin", "entry_raw": common_dark_raw,
             "new_decompressed": new_common_dark_decompressed, "allow_decomp_resize": False},
            {"name": "DeckData_DarkPokemon_EU.bin", "entry_raw": common_eu_raw,
             "new_decompressed": new_common_eu_decompressed, "allow_decomp_resize": False},
        ],
        container_name="common.fsys",
    )

    print(
        f"DarkPokemon-content-only relocation test applied to {output_path}: {num_new_entries} new DDPK "
        f"entries ({target_indices}) written into all three DarkPokemon copies, each borrowing dpkm_index "
        f"{borrow_dpkm_index} for its species/level data. DeckData_Story.bin was NEVER opened, read, or "
        "written by this function -- no DPKM growth, no team-slot/DTNR changes, nothing linked to any "
        f"trainer. deck_archive.fsys: {'grew' if deck_patch_result['grew'] else 'fit in place'}. common.fsys: "
        f"{'grew' if common_patch_result['grew'] else 'fit in place'}. Boot this ISO and watch the Nintendo "
        "splash screen: a repeating '_fsysForegroundTask:ERROR_FILEOPEN' here would isolate the cause to "
        "DarkPokemon.bin's real content growth + relocation itself; a clean boot points at Story.bin's DPKM "
        "growth or DTNR team-slot writes (combined with relocation) as the remaining suspect."
    )
    return {
        "output": str(output_path),
        "target_ddpk_indices": target_indices,
        "deck_archive_grew": deck_patch_result["grew"],
        "common_fsys_grew": common_patch_result["grew"],
    }


# Diagnostic-only: single-trainer team-padding growth+relocation checkpoint.

def apply_team_padding_isolation_test(
    source_path: Path,
    output_path: Path,
    trainer_index: int,
    new_dpkm_index: int,
    species: int,
    level: int,
    moves: list[int] | None = None,
    overwrite: bool = False,
) -> dict:
    """DIAGNOSTIC ONLY. Gives one trainer one extra team member, to cover growing deck_archive.fsys's content
    AND relocating it together. Writing a real Pokemon into a previously-all-zero DPKM entry compresses worse
    than the zero region did, which crosses the threshold without forcing it. If it still fits in place this
    says so rather than reporting a success that tested nothing."""
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()

    if output_path == source_path:
        raise ValueError("output path must be different from the source ISO -- refusing to write over it")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} already exists -- pass --overwrite to replace it")

    chunked_copy(source_path, output_path)

    reader = open_reader(output_path)
    try:
        fst = parse_fst(reader)
        deck_archive_off, deck_archive_len, deck_archive_record_off = find_by_basename(fst, "deck_archive.fsys")
        fsys_bytes = reader.read(deck_archive_off, deck_archive_len)
        fsys_entries = parse_fsys(fsys_bytes)
        story_entry = fsys_entries["DeckData_Story.bin"]
        entry_raw_len = 0x10 + story_entry["comp_size"]
        entry_raw = reader.read(deck_archive_off + story_entry["data_off"], entry_raw_len)
    finally:
        reader.close()

    decompressed = deck_format.lzss_decode(entry_raw)
    deck = deck_format.DeckFile(decompressed)
    before_trainer = deck.trainer(trainer_index)
    if before_trainer is None:
        raise ValueError(f"trainer index {trainer_index} is an empty/unused DTNR slot on this ISO")

    new_decompressed = apply_team_padding_edit(
        decompressed, deck, trainer_index, new_dpkm_index, species, level, moves
    )

    patch_result = write_deck_story_patch(
        output_path, deck_archive_off, deck_archive_len, deck_archive_record_off,
        fsys_bytes, story_entry, entry_raw, new_decompressed,
    )

    after_deck = deck_format.DeckFile(new_decompressed)
    after_trainer = after_deck.trainer(trainer_index)

    if patch_result["grew"]:
        print(
            f"Trainer {trainer_index}'s new team member (species {species}, level {level}) made "
            f"DeckData_Story.bin's re-encoded stream {patch_result['real_comp_size']} bytes -- didn't fit its "
            f"original {patch_result['old_comp_size']}-byte allocation, so deck_archive.fsys was grown to "
            f"{patch_result['new_container_length']} bytes and relocated from ISO offset {deck_archive_off} to "
            f"{patch_result['new_container_offset']}. This is the exact growth+relocation combination that has "
            "not yet been confirmed on real hardware -- boot this ISO and fight (or otherwise encounter) "
            f"trainer index {trainer_index} (was a {before_trainer['party_size']}-Pokemon team, now "
            f"{after_trainer['party_size']}) and confirm the battle plays correctly with the new team member "
            "present, and that the main menu and other battles still work normally too."
        )
    else:
        print(
            f"Trainer {trainer_index}'s new team member fit in DeckData_Story.bin's existing allocation on this "
            "ISO without needing to grow/relocate deck_archive.fsys at all -- this run didn't actually exercise "
            "the growth+relocation path this test exists to check. Try a different trainer_index/new_dpkm_index "
            "combination (or add moves too) to force it, or accept that this specific edit simply had enough "
            "headroom and pick a larger one."
        )

    return {
        "output": str(output_path),
        "trainer_index": trainer_index,
        "new_dpkm_index": new_dpkm_index,
        "species": species,
        "level": level,
        "party_size_before": before_trainer["party_size"],
        "party_size_after": after_trainer["party_size"],
        "grew": patch_result["grew"],
    }


# Diagnostic-only: growth-forcing checkpoint, the corrected replacement for the team-padding approach above.

def apply_growth_checkpoint_test(
    source_path: Path, output_path: Path, reference_trainer_index: int, overwrite: bool = False
) -> dict:
    """DIAGNOSTIC ONLY. Replaces `apply_team_padding_isolation_test()` as the growth+relocation checkpoint,
    on two measurements against the real ISO:

    1. No reusable free DPKM slot exists. A direct scan of the real decoded `DeckData_Story.bin` found exactly
       one entry with species==0 (index 0) out of 823 -- the indices an earlier analysis called free (15, 64,
       68, 69, 71, 76, 83, 324, 330, 331, 334, 340, 348) all hold real data, mostly identical species+level
       pairs, almost certainly Poke Spot encounters. Index 0 is the DTNR empty-slot sentinel.
    2. One trainer's edit cannot overflow the budget: the real file has roughly 700 bytes of headroom and a
       team's species+moves costs 4-8 bytes each. Species-only across nearly all 823 entries still fits;
       overflow needs species AND moves across roughly 240+.

    So it reassigns species+moves across a deterministic subset -- every 3rd index (`candidates[::3]`) outside
    `reference_trainer_index`'s team and index 0, species `(index * 97 + 13) % 411 + 1`, moves
    `(index * {3,7,11,13} + {1,2,3,5}) % 354 + 1`, always inside the real 1-411 and 1-354 ranges -- leaving that
    one trainer untouched as a before/after reference. Many other trainers change; the point is the mechanism."""
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()

    if output_path == source_path:
        raise ValueError("output path must be different from the source ISO -- refusing to write over it")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} already exists -- pass --overwrite to replace it")

    chunked_copy(source_path, output_path)

    reader = open_reader(output_path)
    try:
        fst = parse_fst(reader)
        deck_archive_off, deck_archive_len, deck_archive_record_off = find_by_basename(fst, "deck_archive.fsys")
        fsys_bytes = reader.read(deck_archive_off, deck_archive_len)
        fsys_entries = parse_fsys(fsys_bytes)
        story_entry = fsys_entries["DeckData_Story.bin"]
        entry_raw_len = 0x10 + story_entry["comp_size"]
        entry_raw = reader.read(deck_archive_off + story_entry["data_off"], entry_raw_len)
    finally:
        reader.close()

    decompressed = deck_format.lzss_decode(entry_raw)
    deck = deck_format.DeckFile(decompressed)
    before_reference = deck.trainer(reference_trainer_index)
    if before_reference is None:
        raise ValueError(f"trainer index {reference_trainer_index} is an empty/unused DTNR slot on this ISO")

    reference_dpkm_indices = {m["dpkm_index"] for m in before_reference["team"] if m["kind"] == "DPKM"}
    exclude = {0} | reference_dpkm_indices
    candidates = [i for i in range(deck.dpkm_entries) if i not in exclude]
    chosen = candidates[::3]

    species_assignment = {idx: (idx * 97 + 13) % 411 + 1 for idx in chosen}
    moves_assignment = {
        idx: [(idx * 3 + 1) % 354 + 1, (idx * 7 + 2) % 354 + 1, (idx * 11 + 3) % 354 + 1, (idx * 13 + 5) % 354 + 1]
        for idx in chosen
    }
    new_decompressed = apply_trainer_patch(decompressed, deck, species_assignment, moves_assignment)

    patch_result = write_deck_story_patch(
        output_path, deck_archive_off, deck_archive_len, deck_archive_record_off,
        fsys_bytes, story_entry, entry_raw, new_decompressed,
    )

    after_deck = deck_format.DeckFile(new_decompressed)
    after_reference = after_deck.trainer(reference_trainer_index)
    reference_unchanged = before_reference == after_reference

    if patch_result["grew"]:
        print(
            f"Reassigned species+moves on {len(chosen)} of {deck.dpkm_entries} DPKM entries (trainer index "
            f"{reference_trainer_index}'s own team deliberately excluded, left completely vanilla) -- this made "
            f"DeckData_Story.bin's re-encoded stream {patch_result['real_comp_size']} bytes, which didn't fit "
            f"its original {patch_result['old_comp_size']}-byte allocation, so deck_archive.fsys was grown to "
            f"{patch_result['new_container_length']} bytes and relocated from ISO offset {deck_archive_off} to "
            f"{patch_result['new_container_offset']}. This IS the growth+relocation combination that has not "
            f"yet been confirmed on real hardware. Boot this ISO and confirm: the main menu renders correctly; "
            f"trainer index {reference_trainer_index}'s battle looks and plays EXACTLY as it always has (its "
            f"team was deliberately left untouched -- {'confirmed unchanged by this tool' if reference_unchanged else 'WARNING: this tool itself found it changed, which would be a bug -- do not treat this as a valid test'}"
            f"); and at least one OTHER battle (any trainer whose team looks different -- that's expected, real, "
            "valid data, not corruption) also plays correctly."
        )
    else:
        print(
            "This reassignment did not actually overflow DeckData_Story.bin's allocation on this specific ISO "
            "-- deck_archive.fsys was NOT grown/relocated, so this run didn't exercise the path this test exists "
            "to check. This is unexpected given this project's own measurements against a real dump of this "
            "file -- if you see this, the ISO's DeckData_Story.bin may differ from what this tool was built "
            "against (different region/revision), and the growth threshold would need to be re-measured."
        )

    return {
        "output": str(output_path),
        "reference_trainer_index": reference_trainer_index,
        "dpkm_entries_reassigned": len(chosen),
        "reference_trainer_unchanged": reference_unchanged,
        "grew": patch_result["grew"],
    }


# Diagnostic-only: borrow-based team padding -- does the game accept an extra team member at all.

def apply_team_padding_borrow_test(
    source_path: Path,
    output_path: Path,
    trainer_index: int,
    borrow_dpkm_index: int | None = None,
    overwrite: bool = False,
) -> dict:
    """DIAGNOSTIC ONLY. Real-hardware checkpoint for `apply_team_padding_borrow_edit()`. `borrow_dpkm_index`
    defaults to the trainer's own first team member, the lowest-risk choice: it gets a duplicate of a Pokemon it
    already has and no other trainer's data is touched."""
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()

    if output_path == source_path:
        raise ValueError("output path must be different from the source ISO -- refusing to write over it")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} already exists -- pass --overwrite to replace it")

    chunked_copy(source_path, output_path)

    reader = open_reader(output_path)
    try:
        fst = parse_fst(reader)
        deck_archive_off, deck_archive_len, deck_archive_record_off = find_by_basename(fst, "deck_archive.fsys")
        fsys_bytes = reader.read(deck_archive_off, deck_archive_len)
        fsys_entries = parse_fsys(fsys_bytes)
        story_entry = fsys_entries["DeckData_Story.bin"]
        entry_raw_len = 0x10 + story_entry["comp_size"]
        entry_raw = reader.read(deck_archive_off + story_entry["data_off"], entry_raw_len)
    finally:
        reader.close()

    decompressed = deck_format.lzss_decode(entry_raw)
    deck = deck_format.DeckFile(decompressed)
    before_trainer = deck.trainer(trainer_index)
    if before_trainer is None:
        raise ValueError(f"trainer index {trainer_index} is an empty/unused DTNR slot on this ISO")

    if borrow_dpkm_index is None:
        dpkm_members = [m for m in before_trainer["team"] if m["kind"] == "DPKM"]
        if not dpkm_members:
            raise ValueError(
                f"trainer index {trainer_index} has no ordinary (non-Shadow) team member to borrow from -- "
                "pass --borrow-dpkm-index explicitly."
            )
        borrow_dpkm_index = dpkm_members[0]["dpkm_index"]

    new_decompressed = apply_team_padding_borrow_edit(decompressed, deck, trainer_index, borrow_dpkm_index)

    patch_result = write_deck_story_patch(
        output_path, deck_archive_off, deck_archive_len, deck_archive_record_off,
        fsys_bytes, story_entry, entry_raw, new_decompressed,
    )

    after_deck = deck_format.DeckFile(new_decompressed)
    after_trainer = after_deck.trainer(trainer_index)
    borrowed_species, borrowed_level = deck.dpkm_species_level(borrow_dpkm_index)

    print(
        f"Trainer index {trainer_index} went from a {before_trainer['party_size']}-Pokemon team to "
        f"{after_trainer['party_size']}, by pointing its new slot at dpkm_index {borrow_dpkm_index} (internal "
        f"species {borrowed_species}, level {borrowed_level}) -- an EXISTING Pokemon's real data, not newly "
        f"invented data, so this doesn't need a free DPKM slot at all. "
        + (
            f"This edit grew and relocated deck_archive.fsys ({patch_result['old_comp_size']} -> "
            f"{patch_result['real_comp_size']} bytes)."
            if patch_result["grew"]
            else "This edit fit in DeckData_Story.bin's existing allocation -- no growth/relocation needed."
        )
        + f" Boot this ISO and fight (or otherwise encounter) trainer index {trainer_index}: confirm the battle "
        "shows and correctly uses all "
        f"{after_trainer['party_size']} team members (not just the original "
        f"{before_trainer['party_size']}), and that nothing else (main menu, other battles) is affected."
    )

    return {
        "output": str(output_path),
        "trainer_index": trainer_index,
        "borrow_dpkm_index": borrow_dpkm_index,
        "borrowed_species": borrowed_species,
        "borrowed_level": borrowed_level,
        "party_size_before": before_trainer["party_size"],
        "party_size_after": after_trainer["party_size"],
        "grew": patch_result["grew"],
    }


# Exploratory, higher-risk: new DPKM entries via section growth. See grow_dpkm_section() -- this changes the
# decompressed section layout, and whether the game tolerates that is unconfirmed.

def apply_team_padding_new_species_test(
    source_path: Path,
    output_path: Path,
    trainer_index: int,
    species: int,
    level: int,
    moves: list[int] | None = None,
    overwrite: bool = False,
) -> dict:
    """EXPLORATORY diagnostic for `apply_team_padding_new_entry_edit()`. Gives one trainer a brand-new team
    member with genuinely new data by growing the DPKM section past its entry count. Read
    `grow_dpkm_section()` first: this is the first change to DeckData_Story.bin's decompressed section layout,
    so run it against a disposable copy and expect a crash or black screen as a real possible outcome."""
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()

    if output_path == source_path:
        raise ValueError("output path must be different from the source ISO -- refusing to write over it")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} already exists -- pass --overwrite to replace it")

    chunked_copy(source_path, output_path)

    reader = open_reader(output_path)
    try:
        fst = parse_fst(reader)
        deck_archive_off, deck_archive_len, deck_archive_record_off = find_by_basename(fst, "deck_archive.fsys")
        fsys_bytes = reader.read(deck_archive_off, deck_archive_len)
        fsys_entries = parse_fsys(fsys_bytes)
        story_entry = fsys_entries["DeckData_Story.bin"]
        entry_raw_len = 0x10 + story_entry["comp_size"]
        entry_raw = reader.read(deck_archive_off + story_entry["data_off"], entry_raw_len)
    finally:
        reader.close()

    decompressed = deck_format.lzss_decode(entry_raw)
    deck = deck_format.DeckFile(decompressed)
    before_trainer = deck.trainer(trainer_index)
    if before_trainer is None:
        raise ValueError(f"trainer index {trainer_index} is an empty/unused DTNR slot on this ISO")
    before_dpkm_entries = deck.dpkm_entries

    new_decompressed, new_dpkm_index = apply_team_padding_new_entry_edit(
        decompressed, deck, trainer_index, species, level, moves
    )

    patch_result = write_deck_story_patch(
        output_path, deck_archive_off, deck_archive_len, deck_archive_record_off,
        fsys_bytes, story_entry, entry_raw, new_decompressed, allow_decomp_resize=True,
    )

    after_deck = deck_format.DeckFile(new_decompressed)
    after_trainer = after_deck.trainer(trainer_index)

    print(
        f"DPKM section grew from {before_dpkm_entries} to {after_deck.dpkm_entries} entries (new index "
        f"{new_dpkm_index}, species {species}, level {level}). Trainer index {trainer_index} went from a "
        f"{before_trainer['party_size']}-Pokemon team to {after_trainer['party_size']}, with a genuinely NEW, "
        f"uniquely-specified team member (not a duplicate of an existing Pokemon). "
        + (
            f"This also grew and relocated deck_archive.fsys ({patch_result['old_comp_size']} -> "
            f"{patch_result['real_comp_size']} bytes)."
            if patch_result["grew"]
            else "This fit within DeckData_Story.bin's existing compressed allocation."
        )
        + " THIS IS EXPLORATORY: boot this ISO and watch closely for a crash or black screen at the main "
        f"menu FIRST, before anything else -- if it boots cleanly, fight (or otherwise encounter) trainer "
        f"index {trainer_index} and confirm the new team member is really usable, then check at least one "
        "other, untouched battle and the main menu again."
    )

    return {
        "output": str(output_path),
        "trainer_index": trainer_index,
        "new_dpkm_index": new_dpkm_index,
        "species": species,
        "level": level,
        "dpkm_entries_before": before_dpkm_entries,
        "dpkm_entries_after": after_deck.dpkm_entries,
        "party_size_before": before_trainer["party_size"],
        "party_size_after": after_trainer["party_size"],
        "grew": patch_result["grew"],
    }


# Isolated single-trainer Shadow checkpoint. The 232-trainer run softlocked: trainer 26's battle played
# animations but never entered battle-init (0x80874F54 read 0 throughout). An ORDINARY new member already works.

def apply_team_padding_shadow_edit(
    decompressed: bytes, deck: deck_format.DeckFile,
    ddpk_decompressed: bytes, ddpk: deck_format.DarkPokemonFile,
    trainer_index: int, species: int, level: int, moves: list[int] | None = None,
    shadow_moves: list[int] | None = None,
) -> tuple[bytes, bytes, int]:
    """Give one trainer one new Shadow Pokemon: first empty team slot, first free (`in_use == 0`) DDPK entry,
    one new DPKM entry via `grow_dpkm_section` for its species/level/moves, the DDPK index written into the team
    slot with that slot's shadow-mask bit set, and the DDPK entry written by `apply_dark_pokemon_edit`. Refuses
    an empty trainer, a full team, or no free DDPK capacity. Returns `(new_story_decompressed,
    new_dark_pokemon_decompressed, ddpk_index_used)`."""
    t = deck.trainer(trainer_index)
    if t is None:
        raise ValueError(f"trainer_index {trainer_index} is an empty/unused DTNR slot")
    used_slots = {m["slot"] for m in t["team"]}
    free_slots = [s for s in range(6) if s not in used_slots]
    if not free_slots:
        raise ValueError(f"trainer {trainer_index} already has a full 6-member team -- no empty slot to use")
    new_slot = free_slots[0]

    free_ddpk = [i for i in range(1, ddpk.ddpk_entries) if not ddpk.ddpk_full(i)["in_use"]]
    if not free_ddpk:
        raise ValueError("no free DDPK entries available in this DeckData_DarkPokemon.bin")
    ddpk_index = free_ddpk[0]

    moves = list(moves) if moves else [0, 0, 0, 0]
    grown, new_indices = grow_dpkm_section(decompressed, deck, [{"species": species, "level": level, "moves": moves}])
    new_dpkm_index = new_indices[0]

    buf = bytearray(grown)
    dtnr_base = deck.dtnr_data + trainer_index * 0x38
    struct.pack_into(">H", buf, dtnr_base + 0x1C + new_slot * 2, ddpk_index)
    buf[dtnr_base + 0x04] |= (1 << new_slot)

    assignment = [{
        "ddpk_index": ddpk_index, "story_deck_index": new_dpkm_index,
        # `moves` is the DPKM moveset; Shadow moves are a separate id range, hence `shadow_moves`.
        "shadow_level": level,
        "shadow_moves": shadow_moves or _shadow_move_slots.choose_shadow_moves(random.Random(level), 2),
    }]
    new_dark_decompressed = apply_dark_pokemon_edit(ddpk_decompressed, ddpk, assignment)
    return bytes(buf), new_dark_decompressed, ddpk_index


def apply_team_padding_shadow_test(
    source_path: Path, output_path: Path, trainer_index: int, species: int, level: int,
    moves: list[int] | None = None, overwrite: bool = False,
) -> dict:
    """EXPLORATORY diagnostic -- isolates writing a genuinely new Shadow Pokemon into a previously-empty team
    slot, the one mechanism the full-scale run never had confirmed before it softlocked."""
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()

    if output_path == source_path:
        raise ValueError("output path must be different from the source ISO -- refusing to write over it")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} already exists -- pass --overwrite to replace it")

    chunked_copy(source_path, output_path)

    reader = open_reader(output_path)
    try:
        fst = parse_fst(reader)
        deck_archive_off, deck_archive_len, deck_archive_record_off = find_by_basename(fst, "deck_archive.fsys")
        fsys_bytes = reader.read(deck_archive_off, deck_archive_len)
        fsys_entries = parse_fsys(fsys_bytes)
        story_entry = fsys_entries["DeckData_Story.bin"]
        story_raw = reader.read(deck_archive_off + story_entry["data_off"], 0x10 + story_entry["comp_size"])
        dark_entry = fsys_entries["DeckData_DarkPokemon.bin"]
        dark_raw = reader.read(deck_archive_off + dark_entry["data_off"], 0x10 + dark_entry["comp_size"])
    finally:
        reader.close()

    story_decompressed = deck_format.lzss_decode(story_raw)
    deck = deck_format.DeckFile(story_decompressed)
    dark_decompressed = deck_format.lzss_decode(dark_raw)
    ddpk = deck_format.DarkPokemonFile(dark_decompressed)

    before_trainer = deck.trainer(trainer_index)
    if before_trainer is None:
        raise ValueError(f"trainer_index {trainer_index} is an empty/unused DTNR slot on this ISO")

    new_story_decompressed, new_dark_decompressed, ddpk_index = apply_team_padding_shadow_edit(
        story_decompressed, deck, dark_decompressed, ddpk, trainer_index, species, level, moves=moves,
    )

    patch_result = write_fsys_multi_entry_patch(
        output_path, deck_archive_off, deck_archive_len, deck_archive_record_off, fsys_bytes,
        [
            {"name": "DeckData_Story.bin", "entry_raw": story_raw, "new_decompressed": new_story_decompressed,
             "allow_decomp_resize": True},
            {"name": "DeckData_DarkPokemon.bin", "entry_raw": dark_raw, "new_decompressed": new_dark_decompressed,
             "allow_decomp_resize": False},
        ],
    )

    after_deck = deck_format.DeckFile(new_story_decompressed)
    after_trainer = after_deck.trainer(trainer_index)

    print(
        f"Trainer {trainer_index}: party size {before_trainer['party_size']} -> {after_trainer['party_size']}, "
        f"new member is a Shadow Pokemon (DDPK index {ddpk_index}, species {species}, level {level}). "
        f"DeckData_Story.bin: {'grew' if patch_result['per_entry']['DeckData_Story.bin']['grew'] else 'fit in place'} "
        f"({patch_result['per_entry']['DeckData_Story.bin']['old_comp_size']} -> "
        f"{patch_result['per_entry']['DeckData_Story.bin']['real_comp_size']} bytes). "
        f"DeckData_DarkPokemon.bin: {'grew' if patch_result['per_entry']['DeckData_DarkPokemon.bin']['grew'] else 'fit in place'} "
        f"({patch_result['per_entry']['DeckData_DarkPokemon.bin']['old_comp_size']} -> "
        f"{patch_result['per_entry']['DeckData_DarkPokemon.bin']['real_comp_size']} bytes). "
        "Boot this ISO, watch the main menu FIRST, then start a battle against this exact trainer and watch "
        "closely for the same softlock signature (animation plays, battle never actually starts)."
    )

    return {
        "output": str(output_path),
        "trainer_index": trainer_index,
        "party_size_before": before_trainer["party_size"],
        "party_size_after": after_trainer["party_size"],
        "ddpk_index_used": ddpk_index,
        "grew": patch_result["grew"],
        "per_entry": patch_result["per_entry"],
    }


# That checkpoint did not crash, but the new Shadow was absent from trainer 26's live roster. It combined the
# shadow_mask + DDPK slot write with a DDPK `story_deck_index` pointing at a freshly grown DPKM entry (growth was
# only confirmed through a DIRECT DTNR slot). This isolates the first by borrowing instead of growing.

def apply_team_padding_shadow_borrow_edit(
    decompressed: bytes, deck: deck_format.DeckFile,
    ddpk_decompressed: bytes, ddpk: deck_format.DarkPokemonFile,
    trainer_index: int, borrow_dpkm_index: int | None = None,
    shadow_level: int | None = None, moves: list[int] | None = None,
    shadow_moves: list[int] | None = None,
) -> tuple[bytes, bytes, int, int]:
    """Give one trainer one new Shadow Pokemon without growing the DPKM section: the new DDPK entry's
    `story_deck_index` points at `borrow_dpkm_index`, an existing populated entry, defaulting to the trainer's
    own first ordinary member. With zero genuinely free in-bounds DPKM entries in the real file, borrowing the
    trainer's own is the only option needing no new DPKM data; the borrowed bytes are never touched, only a
    second pointer (through a DDPK indirection rather than a direct DTNR slot) is added.

    So `DeckData_Story.bin`'s edit is a same-size DTNR-slot write and growth is unlikely; only
    `DeckData_DarkPokemon.bin` gains real content. Returns `(new_story_decompressed,
    new_dark_pokemon_decompressed, ddpk_index_used, borrow_dpkm_index_used)`."""
    t = deck.trainer(trainer_index)
    if t is None:
        raise ValueError(f"trainer_index {trainer_index} is an empty/unused DTNR slot")
    used_slots = {m["slot"] for m in t["team"]}
    free_slots = [s for s in range(6) if s not in used_slots]
    if not free_slots:
        raise ValueError(f"trainer {trainer_index} already has a full 6-member team -- no empty slot to use")
    new_slot = free_slots[0]

    if borrow_dpkm_index is None:
        dpkm_members = [m for m in t["team"] if m["kind"] == "DPKM"]
        if not dpkm_members:
            raise ValueError(
                f"trainer {trainer_index} has no ordinary DPKM team member to borrow from by default -- pass "
                "borrow_dpkm_index explicitly"
            )
        borrow_dpkm_index = dpkm_members[0]["dpkm_index"]

    borrow_species, borrow_level = deck.dpkm_species_level(borrow_dpkm_index)
    if borrow_species == 0:
        raise ValueError(
            f"dpkm_index {borrow_dpkm_index} has no real data (its species field reads 0) -- refusing to "
            "borrow an empty/sentinel entry as this Shadow Pokemon's underlying data."
        )
    if shadow_level is None:
        shadow_level = borrow_level

    free_ddpk = [i for i in range(1, ddpk.ddpk_entries) if not ddpk.ddpk_full(i)["in_use"]]
    if not free_ddpk:
        raise ValueError("no free DDPK entries available in this DeckData_DarkPokemon.bin")
    ddpk_index = free_ddpk[0]

    buf = bytearray(decompressed)
    dtnr_base = deck.dtnr_data + trainer_index * 0x38
    struct.pack_into(">H", buf, dtnr_base + 0x1C + new_slot * 2, ddpk_index)
    buf[dtnr_base + 0x04] |= (1 << new_slot)

    moves = list(moves) if moves else [0, 0, 0, 0]
    assignment = [{
        "ddpk_index": ddpk_index, "story_deck_index": borrow_dpkm_index,
        # `moves` is the DPKM moveset, not the Shadow moveset -- see the sibling helper above.
        "shadow_level": shadow_level,
        "shadow_moves": shadow_moves or _shadow_move_slots.choose_shadow_moves(
            random.Random(shadow_level), 2),
    }]
    new_dark_decompressed = apply_dark_pokemon_edit(ddpk_decompressed, ddpk, assignment)
    return bytes(buf), new_dark_decompressed, ddpk_index, borrow_dpkm_index


def apply_team_padding_shadow_borrow_test(
    source_path: Path, output_path: Path, trainer_index: int, borrow_dpkm_index: int | None = None,
    shadow_level: int | None = None, moves: list[int] | None = None, overwrite: bool = False,
) -> dict:
    """EXPLORATORY diagnostic -- isolates the shadow_mask/DDPK write from DPKM-section growth by borrowing an
    existing DPKM entry instead of creating one. See `apply_team_padding_shadow_borrow_edit`."""
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()

    if output_path == source_path:
        raise ValueError("output path must be different from the source ISO -- refusing to write over it")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} already exists -- pass --overwrite to replace it")

    chunked_copy(source_path, output_path)

    reader = open_reader(output_path)
    try:
        fst = parse_fst(reader)
        deck_archive_off, deck_archive_len, deck_archive_record_off = find_by_basename(fst, "deck_archive.fsys")
        fsys_bytes = reader.read(deck_archive_off, deck_archive_len)
        fsys_entries = parse_fsys(fsys_bytes)
        story_entry = fsys_entries["DeckData_Story.bin"]
        story_raw = reader.read(deck_archive_off + story_entry["data_off"], 0x10 + story_entry["comp_size"])
        dark_entry = fsys_entries["DeckData_DarkPokemon.bin"]
        dark_raw = reader.read(deck_archive_off + dark_entry["data_off"], 0x10 + dark_entry["comp_size"])
    finally:
        reader.close()

    story_decompressed = deck_format.lzss_decode(story_raw)
    deck = deck_format.DeckFile(story_decompressed)
    dark_decompressed = deck_format.lzss_decode(dark_raw)
    ddpk = deck_format.DarkPokemonFile(dark_decompressed)

    before_trainer = deck.trainer(trainer_index)
    if before_trainer is None:
        raise ValueError(f"trainer_index {trainer_index} is an empty/unused DTNR slot on this ISO")

    new_story_decompressed, new_dark_decompressed, ddpk_index, borrow_dpkm_index_used = apply_team_padding_shadow_borrow_edit(
        story_decompressed, deck, dark_decompressed, ddpk, trainer_index,
        borrow_dpkm_index=borrow_dpkm_index, shadow_level=shadow_level, moves=moves,
    )

    patch_result = write_fsys_multi_entry_patch(
        output_path, deck_archive_off, deck_archive_len, deck_archive_record_off, fsys_bytes,
        [
            {"name": "DeckData_Story.bin", "entry_raw": story_raw, "new_decompressed": new_story_decompressed,
             "allow_decomp_resize": False},
            {"name": "DeckData_DarkPokemon.bin", "entry_raw": dark_raw, "new_decompressed": new_dark_decompressed,
             "allow_decomp_resize": False},
        ],
    )

    after_deck = deck_format.DeckFile(new_story_decompressed)
    after_trainer = after_deck.trainer(trainer_index)
    borrow_species, _ = deck.dpkm_species_level(borrow_dpkm_index_used)

    print(
        f"Trainer {trainer_index}: party size {before_trainer['party_size']} -> {after_trainer['party_size']}, "
        f"new member is a Shadow Pokemon (DDPK index {ddpk_index}) whose data BORROWS existing dpkm_index "
        f"{borrow_dpkm_index_used} (species {borrow_species}) -- no DPKM growth needed for this edit. "
        f"DeckData_Story.bin: {'grew' if patch_result['per_entry']['DeckData_Story.bin']['grew'] else 'fit in place'} "
        f"({patch_result['per_entry']['DeckData_Story.bin']['old_comp_size']} -> "
        f"{patch_result['per_entry']['DeckData_Story.bin']['real_comp_size']} bytes). "
        f"DeckData_DarkPokemon.bin: {'grew' if patch_result['per_entry']['DeckData_DarkPokemon.bin']['grew'] else 'fit in place'} "
        f"({patch_result['per_entry']['DeckData_DarkPokemon.bin']['old_comp_size']} -> "
        f"{patch_result['per_entry']['DeckData_DarkPokemon.bin']['real_comp_size']} bytes). "
        "Boot this ISO, watch the main menu FIRST, then start a battle against this exact trainer and check "
        "whether the third (Shadow) team member actually appears this time."
    )

    return {
        "output": str(output_path),
        "trainer_index": trainer_index,
        "party_size_before": before_trainer["party_size"],
        "party_size_after": after_trainer["party_size"],
        "ddpk_index_used": ddpk_index,
        "borrow_dpkm_index_used": borrow_dpkm_index_used,
        "grew": patch_result["grew"],
        "per_entry": patch_result["per_entry"],
    }


# The borrow test also produced no third Pokemon, ruling out the indirection. But an unedited vanilla Shadow
# trainer (DTNR 33, "RESIX", Houndour at DDPK 14) does load, so the blocker is never-before-used indices (84+) --
# consistent with a save-resident pool. So point a slot at an EXISTING in-use index: no new data in either file,
# only a second DTNR pointer, hence the single-entry write path.

def apply_team_padding_shadow_reuse_edit(
    decompressed: bytes, deck: deck_format.DeckFile,
    ddpk: deck_format.DarkPokemonFile,
    trainer_index: int, reuse_ddpk_index: int,
) -> bytes:
    """Give one trainer one new Shadow Pokemon by pointing a new team slot at an EXISTING in-use DDPK entry
    that another real trainer already owns, rather than allocating a fresh index. Only `DeckData_Story.bin` is
    touched -- the team-slot write plus its shadow-mask bit; the DDPK entry's own bytes are never written.

    Tests the "caught pool" hypothesis: if loading is gated by a save-resident pool keyed on DDPK index rather
    than by trainer or story progress, an already-in-pool index behaves differently from a fresh one. A
    `reuse_ddpk_index` that is not in use is refused, since that reproduces the fresh-index case."""
    t = deck.trainer(trainer_index)
    if t is None:
        raise ValueError(f"trainer_index {trainer_index} is an empty/unused DTNR slot")
    used_slots = {m["slot"] for m in t["team"]}
    free_slots = [s for s in range(6) if s not in used_slots]
    if not free_slots:
        raise ValueError(f"trainer {trainer_index} already has a full 6-member team -- no empty slot to use")
    new_slot = free_slots[0]

    reuse_entry = ddpk.ddpk_full(reuse_ddpk_index)
    if not reuse_entry["in_use"]:
        raise ValueError(
            f"ddpk_index {reuse_ddpk_index} is NOT marked in-use -- this diagnostic exists specifically to "
            "test reusing an EXISTING, already-in-use DDPK entry (part of the game's real Shadow Pokemon "
            "'pool', per the user's own hypothesis), not a fresh/never-used one. Use "
            "team-padding-shadow-borrow-test for the fresh-index case."
        )

    buf = bytearray(decompressed)
    dtnr_base = deck.dtnr_data + trainer_index * 0x38
    struct.pack_into(">H", buf, dtnr_base + 0x1C + new_slot * 2, reuse_ddpk_index)
    buf[dtnr_base + 0x04] |= (1 << new_slot)
    return bytes(buf)


def apply_team_padding_shadow_reuse_test(
    source_path: Path, output_path: Path, trainer_index: int, reuse_ddpk_index: int,
    overwrite: bool = False,
) -> dict:
    """DIAGNOSTIC ONLY. Real-hardware checkpoint for `apply_team_padding_shadow_reuse_edit()`."""
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()

    if output_path == source_path:
        raise ValueError("output path must be different from the source ISO -- refusing to write over it")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} already exists -- pass --overwrite to replace it")

    chunked_copy(source_path, output_path)

    reader = open_reader(output_path)
    try:
        fst = parse_fst(reader)
        deck_archive_off, deck_archive_len, deck_archive_record_off = find_by_basename(fst, "deck_archive.fsys")
        fsys_bytes = reader.read(deck_archive_off, deck_archive_len)
        fsys_entries = parse_fsys(fsys_bytes)
        story_entry = fsys_entries["DeckData_Story.bin"]
        entry_raw_len = 0x10 + story_entry["comp_size"]
        entry_raw = reader.read(deck_archive_off + story_entry["data_off"], entry_raw_len)
        dark_entry = fsys_entries["DeckData_DarkPokemon.bin"]
        dark_raw = reader.read(deck_archive_off + dark_entry["data_off"], 0x10 + dark_entry["comp_size"])
    finally:
        reader.close()

    decompressed = deck_format.lzss_decode(entry_raw)
    deck = deck_format.DeckFile(decompressed)
    dark_decompressed = deck_format.lzss_decode(dark_raw)
    ddpk = deck_format.DarkPokemonFile(dark_decompressed)

    before_trainer = deck.trainer(trainer_index)
    if before_trainer is None:
        raise ValueError(f"trainer index {trainer_index} is an empty/unused DTNR slot on this ISO")

    new_decompressed = apply_team_padding_shadow_reuse_edit(
        decompressed, deck, ddpk, trainer_index, reuse_ddpk_index
    )

    patch_result = write_deck_story_patch(
        output_path, deck_archive_off, deck_archive_len, deck_archive_record_off,
        fsys_bytes, story_entry, entry_raw, new_decompressed,
    )

    after_deck = deck_format.DeckFile(new_decompressed)
    after_trainer = after_deck.trainer(trainer_index)
    reuse_entry = ddpk.ddpk_full(reuse_ddpk_index)
    reuse_species, _ = deck.dpkm_species_level(reuse_entry["story_deck_index"])

    print(
        f"Trainer {trainer_index}: party size {before_trainer['party_size']} -> {after_trainer['party_size']}, "
        f"new member REUSES ddpk_index {reuse_ddpk_index} -- an EXISTING, already-in-use Shadow Pokemon entry "
        f"(story_deck_index {reuse_entry['story_deck_index']}, species {reuse_species}, shadow_level "
        f"{reuse_entry['shadow_level']}) some OTHER real trainer already owns. DeckData_DarkPokemon.bin is not "
        "touched at all -- only a second DTNR pointer is added, mirroring apply_team_padding_borrow_edit's "
        "ordinary-Pokemon borrow trick but for a Shadow Pokemon. "
        + (
            f"DeckData_Story.bin grew and relocated ({patch_result['old_comp_size']} -> "
            f"{patch_result['real_comp_size']} bytes)."
            if patch_result["grew"]
            else "DeckData_Story.bin fit in its existing allocation -- no growth/relocation needed."
        )
        + f" Boot this ISO and fight trainer index {trainer_index}: if the reused Shadow Pokemon appears and "
        "loads correctly this time (unlike ADDENDUM 54/55's freshly-allocated DDPK indices), that's strong "
        "evidence for a save-resident 'pool' that only recognizes originally-shipped DDPK indices -- exactly "
        "the user's own hypothesis."
    )

    return {
        "output": str(output_path),
        "trainer_index": trainer_index,
        "reuse_ddpk_index": reuse_ddpk_index,
        "party_size_before": before_trainer["party_size"],
        "party_size_after": after_trainer["party_size"],
        "grew": patch_result["grew"],
    }


# Reusing in-use index 14 on a different trainer works. The real DeckData_DarkPokemon.bin declares 128 entries
# but only 1-83 are in_use, 84-127 being contiguous padding, and 83 is exactly the canonical vanilla Shadow
# count -- so something outside deck_archive.fsys, likely a fixed-size table in the executable, recognizes only
# 1-83 whatever in_use says. Index 14 working could still be about its original ROM bytes, so overwrite an
# in-range entry with this project's own field pattern and point a second trainer at it: still working is
# decisive.

def apply_team_padding_shadow_overwrite_edit(
    decompressed: bytes, deck: deck_format.DeckFile,
    ddpk_decompressed: bytes, ddpk: deck_format.DarkPokemonFile,
    trainer_index: int, target_ddpk_index: int,
    story_deck_index: int | None = None, shadow_level: int | None = None, moves: list[int] | None = None,
) -> tuple[bytes, bytes, int]:
    """Like the reuse edit, but FIRST overwrites `target_ddpk_index`'s own bytes with the field pattern
    `apply_dark_pokemon_edit` uses for new entries (flee_weight 128, catch_rate_override 190, in_use 128,
    heart_gauge 2000, aggression 4, always_flee 0). `story_deck_index` defaults to the trainer's first ordinary
    member, so no DPKM growth is needed.

    SAFETY: this overwrites a real in-use DDPK entry in place, so whichever other trainer owned it shows wrong
    Shadow data for the rest of that ISO -- disposable test copies only. Returns
    `(new_story_decompressed, new_dark_pokemon_decompressed, target_ddpk_index)`."""
    t = deck.trainer(trainer_index)
    if t is None:
        raise ValueError(f"trainer_index {trainer_index} is an empty/unused DTNR slot")
    used_slots = {m["slot"] for m in t["team"]}
    free_slots = [s for s in range(6) if s not in used_slots]
    if not free_slots:
        raise ValueError(f"trainer {trainer_index} already has a full 6-member team -- no empty slot to use")
    new_slot = free_slots[0]

    existing = ddpk.ddpk_full(target_ddpk_index)
    if not existing["in_use"]:
        raise ValueError(
            f"ddpk_index {target_ddpk_index} is NOT marked in-use -- this diagnostic is specifically for "
            "overwriting a REAL, already-in-range entry to test whether the index value alone matters. Use "
            "team-padding-shadow-borrow-test to author a genuinely free/new entry instead."
        )

    if story_deck_index is None:
        dpkm_members = [m for m in t["team"] if m["kind"] == "DPKM"]
        if not dpkm_members:
            raise ValueError(
                f"trainer {trainer_index} has no ordinary DPKM team member to borrow story_deck_index from by "
                "default -- pass story_deck_index explicitly."
            )
        story_deck_index = dpkm_members[0]["dpkm_index"]

    borrow_species, borrow_level = deck.dpkm_species_level(story_deck_index)
    if borrow_species == 0:
        raise ValueError(
            f"dpkm_index {story_deck_index} has no real data (its species field reads 0) -- refusing to use "
            "an empty/sentinel entry as this Shadow Pokemon's underlying data."
        )
    if shadow_level is None:
        shadow_level = borrow_level

    buf = bytearray(decompressed)
    dtnr_base = deck.dtnr_data + trainer_index * 0x38
    struct.pack_into(">H", buf, dtnr_base + 0x1C + new_slot * 2, target_ddpk_index)
    buf[dtnr_base + 0x04] |= (1 << new_slot)

    moves = list(moves) if moves else [0, 0, 0, 0]
    dark_buf = bytearray(ddpk_decompressed)
    off = ddpk.ddpk_data + target_ddpk_index * 0x18
    dark_buf[off + 0x00] = 128  # flee_weight -- same default apply_dark_pokemon_edit uses for a new entry
    dark_buf[off + 0x01] = 190  # catch_rate_override
    dark_buf[off + 0x02] = shadow_level
    dark_buf[off + 0x03] = 128  # in_use -- unchanged (was already 128), written explicitly for clarity
    struct.pack_into(">H", dark_buf, off + 0x06, story_deck_index)
    struct.pack_into(">H", dark_buf, off + 0x08, 2000)  # heart_gauge
    struct.pack_into(">H", dark_buf, off + 0x0A, 0)      # bonus_exp
    struct.pack_into(">HHHH", dark_buf, off + 0x0C, *moves[:2], 0, 0)
    dark_buf[off + 0x14] = 4  # aggression
    dark_buf[off + 0x15] = 0  # always_flee

    return bytes(buf), bytes(dark_buf), target_ddpk_index


def apply_team_padding_shadow_overwrite_test(
    source_path: Path, output_path: Path, trainer_index: int, target_ddpk_index: int,
    story_deck_index: int | None = None, shadow_level: int | None = None, moves: list[int] | None = None,
    overwrite: bool = False,
) -> dict:
    """DIAGNOSTIC ONLY. Real-hardware checkpoint for `apply_team_padding_shadow_overwrite_edit()` -- read its
    safety note first. Overwrites a real in-range DDPK entry with project-authored data, to tell whether index
    14 working was about the index value (<=83) or about untouched original ROM bytes."""
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()

    if output_path == source_path:
        raise ValueError("output path must be different from the source ISO -- refusing to write over it")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} already exists -- pass --overwrite to replace it")

    chunked_copy(source_path, output_path)

    reader = open_reader(output_path)
    try:
        fst = parse_fst(reader)
        deck_archive_off, deck_archive_len, deck_archive_record_off = find_by_basename(fst, "deck_archive.fsys")
        fsys_bytes = reader.read(deck_archive_off, deck_archive_len)
        fsys_entries = parse_fsys(fsys_bytes)
        story_entry = fsys_entries["DeckData_Story.bin"]
        story_raw = reader.read(deck_archive_off + story_entry["data_off"], 0x10 + story_entry["comp_size"])
        dark_entry = fsys_entries["DeckData_DarkPokemon.bin"]
        dark_raw = reader.read(deck_archive_off + dark_entry["data_off"], 0x10 + dark_entry["comp_size"])
    finally:
        reader.close()

    story_decompressed = deck_format.lzss_decode(story_raw)
    deck = deck_format.DeckFile(story_decompressed)
    dark_decompressed = deck_format.lzss_decode(dark_raw)
    ddpk = deck_format.DarkPokemonFile(dark_decompressed)

    before_trainer = deck.trainer(trainer_index)
    if before_trainer is None:
        raise ValueError(f"trainer_index {trainer_index} is an empty/unused DTNR slot on this ISO")

    # The target entry's original owner, for the report: that trainer's Shadow looks wrong on this test ISO.
    original_owner = None
    for i in range(deck.dtnr_entries):
        ot = deck.trainer(i)
        if ot is None:
            continue
        if any(m["kind"] == "DDPK" and m["ddpk_index"] == target_ddpk_index for m in ot["team"]):
            original_owner = i
            break

    new_story_decompressed, new_dark_decompressed, ddpk_index = apply_team_padding_shadow_overwrite_edit(
        story_decompressed, deck, dark_decompressed, ddpk, trainer_index, target_ddpk_index,
        story_deck_index=story_deck_index, shadow_level=shadow_level, moves=moves,
    )

    patch_result = write_fsys_multi_entry_patch(
        output_path, deck_archive_off, deck_archive_len, deck_archive_record_off, fsys_bytes,
        [
            {"name": "DeckData_Story.bin", "entry_raw": story_raw, "new_decompressed": new_story_decompressed,
             "allow_decomp_resize": False},
            {"name": "DeckData_DarkPokemon.bin", "entry_raw": dark_raw, "new_decompressed": new_dark_decompressed,
             "allow_decomp_resize": False},
        ],
    )

    after_deck = deck_format.DeckFile(new_story_decompressed)
    after_trainer = after_deck.trainer(trainer_index)

    print(
        f"Trainer {trainer_index}: party size {before_trainer['party_size']} -> {after_trainer['party_size']}, "
        f"new member points at ddpk_index {ddpk_index} -- a REAL, in-range (<=83) entry that has been "
        "OVERWRITTEN with this project's own new-entry field pattern (not its original vanilla content). "
        + (
            f"NOTE: ddpk_index {ddpk_index} originally belonged to trainer index {original_owner} -- that "
            "trainer's Shadow Pokemon will show wrong/overwritten data on THIS test ISO only. "
            if original_owner is not None else ""
        )
        + f"DeckData_Story.bin: {'grew' if patch_result['per_entry']['DeckData_Story.bin']['grew'] else 'fit in place'}. "
        f"DeckData_DarkPokemon.bin: {'grew' if patch_result['per_entry']['DeckData_DarkPokemon.bin']['grew'] else 'fit in place'}. "
        f"Boot this ISO and fight trainer index {trainer_index}: if the overwritten-but-in-range Shadow "
        "Pokemon still appears and works, that's decisive evidence the boundary is about the raw DDPK index "
        "value alone (<=83), not about anything special in the original ROM-authored bytes -- pointing "
        "squarely at a hardcoded table/limit somewhere outside deck_archive.fsys."
    )

    return {
        "output": str(output_path),
        "trainer_index": trainer_index,
        "target_ddpk_index": target_ddpk_index,
        "original_owner_trainer_index": original_owner,
        "party_size_before": before_trainer["party_size"],
        "party_size_after": after_trainer["party_size"],
        "grew": patch_result["grew"],
        "per_entry": patch_result["per_entry"],
    }


# The answer: live RAM showed the game using vanilla data for DDPK 83 after the overwrite, while an on-disk
# check (`verify_ddpk83.py`) confirmed the write DID land in `deck_archive.fsys`. `common.fsys` carries its own
# `DeckData_DarkPokemon.bin` plus a `DeckData_DarkPokemon_EU.bin`, and those are what the game loads for Shadow
# battle data. So write all three copies plus the Story team slot, via one `write_fsys_multi_entry_patch()` per
# disc-level container, each verifying its own read-back.

def _overwrite_ddpk_entry_bytes(
    ddpk_decompressed: bytes, ddpk: deck_format.DarkPokemonFile, target_ddpk_index: int,
    story_deck_index: int, shadow_level: int, moves: list[int],
) -> bytes:
    """Overwrite one in-use DDPK entry with the field pattern `apply_dark_pokemon_edit` uses for new entries.
    Separate so byte-for-byte identical content can go into all three DarkPokemon copies in one pass. Validates
    nothing -- callers check in_use and team-slot state."""
    dark_buf = bytearray(ddpk_decompressed)
    off = ddpk.ddpk_data + target_ddpk_index * 0x18
    dark_buf[off + 0x00] = 128  # flee_weight
    dark_buf[off + 0x01] = 190  # catch_rate_override
    dark_buf[off + 0x02] = shadow_level
    dark_buf[off + 0x03] = 128  # in_use
    struct.pack_into(">H", dark_buf, off + 0x06, story_deck_index)
    struct.pack_into(">H", dark_buf, off + 0x08, 2000)  # heart_gauge
    struct.pack_into(">H", dark_buf, off + 0x0A, 0)      # bonus_exp
    struct.pack_into(">HHHH", dark_buf, off + 0x0C, *moves[:2], 0, 0)
    dark_buf[off + 0x14] = 4  # aggression
    dark_buf[off + 0x15] = 0  # always_flee
    return bytes(dark_buf)


# The one byte the Master Ball does not share, a DIAGNOSTIC rather than a feature. The catch rate caps at 255 in
# both places it lives, no DDPK field explains the game's one guaranteed catch, and all twelve balls are
# byte-identical in the Items table. The one positive result: a per-item behaviour table where the Master Ball is
# the only row of 34 with a non-zero byte at +0x00 -- a coincidence, not a proof, since the byte could mean
# "never consumed". One throw settles it, and this produces an ISO to throw with.

def write_ball_behavior_flag_probe(
    source_path: Path, output_path: Path, item_ids: "list[int] | None" = None,
    value: int | None = None, overwrite: bool = False,
) -> dict:
    """DIAGNOSTIC. Copies `source_path` to `output_path` and writes `value` into the behaviour-table flag byte
    of each item in `item_ids`, defaulting to the Poke Ball alone and to the Master Ball's own value.

    The Poke Ball alone is the deliberate default: it is the weakest ball in the game, so if it starts
    catching full-health Pokemon on the first throw, the byte's meaning is not ambiguous. Leaving the other
    eleven untouched keeps a control in the same ISO. Returns `{"table_base", "before", "after", "written"}`,
    or raises if the behaviour table cannot be located -- it is never written to on faith."""
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()
    if output_path == source_path:
        raise ValueError("output path must be different from the source ISO -- refusing to write over it")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} already exists -- pass --overwrite to replace it")

    ids = [int(i) for i in (item_ids if item_ids else [4])]
    flag = None if value is None else int(value)

    chunked_copy(source_path, output_path)

    reader = open_reader(output_path)
    try:
        fst = parse_fst(reader)
        common_off, common_len, _record_off = find_by_basename(fst, "common.fsys")
        common_bytes = reader.read(common_off, common_len)
        fsys_entries = parse_fsys(common_bytes)
        rel_entry = fsys_entries["common_rel"]
        abs_entry_off = common_off + rel_entry["data_off"]
        abs_record_comp_size_off = common_off + rel_entry["record_off"] + FSYS_RECORD_COMP_SIZE_OFF
        entry_raw = reader.read(abs_entry_off, 0x10 + rel_entry["comp_size"])
    finally:
        reader.close()

    decompressed = deck_format.lzss_decode(entry_raw)
    rel = rel_format.RelFile(decompressed, True)
    rel_bytes = bytearray(decompressed)

    base = rel_format.find_item_behavior_table(rel)
    if base is None:
        raise ValueError(
            "the per-item behaviour table could not be located on this ISO -- no offset reproduced a long "
            "enough run of the Items table's own use-handler pointers, so nothing was written"
        )
    before = rel_format.read_item_behavior_values(rel, base, ids)
    result = rel_format.apply_item_behavior_value(rel_bytes, rel, base, ids, flag)

    new_entry_raw, real_comp_size, _grew = deck_format.patch_entry_decompressed(entry_raw, bytes(rel_bytes))
    writer = open_writer(output_path)
    try:
        writer.write(abs_entry_off, new_entry_raw)
        writer.write(abs_record_comp_size_off, struct.pack(">I", real_comp_size))
    finally:
        writer.close()

    verify = open_reader(output_path)
    try:
        reread = verify.read(abs_entry_off, len(new_entry_raw))
    finally:
        verify.close()
    if deck_format.lzss_decode(reread) != bytes(rel_bytes):
        raise RuntimeError("read-back verification failed -- the behaviour-flag write did not stick")

    after = rel_format.read_item_behavior_values(
        rel_format.RelFile(bytes(rel_bytes), True), base, ids)
    print(
        f"Behaviour-value probe written to {output_path}: table at 0x{base:X}, "
        f"{result['behaviour_values_written']} item(s) changed. "
        f"before={ {k: hex(v) for k, v in before.items()} } "
        f"after={ {k: hex(v) for k, v in after.items()} } "
        f"(Master Ball reads {hex(rel_format.MASTER_BALL_BEHAVIOR_VALUE)})."
    )
    print(
        "  THIS IS AN EXPERIMENT. Throw the patched ball at a FULL-HEALTH Pokemon. If it catches first try, "
        "the byte means what ADDENDUM 303 suspects; if nothing changes, it does not, and the finding is a "
        "dead end rather than a feature."
    )
    return {"table_base": base, "before": before, "after": after,
            "written": result["behaviour_values_written"]}


def apply_team_padding_shadow_common_test(
    source_path: Path, output_path: Path, trainer_index: int, target_ddpk_index: int,
    story_deck_index: int | None = None, shadow_level: int | None = None, moves: list[int] | None = None,
    overwrite: bool = False,
) -> dict:
    """DIAGNOSTIC -- see the section note above. Edits `target_ddpk_index` identically across all three
    DarkPokemon copies plus the usual `DeckData_Story.bin` team-slot write. `story_deck_index` defaults to the
    trainer's first ordinary member. An unfamiliar `common.fsys` layout is refused rather than half-patched."""
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()

    if output_path == source_path:
        raise ValueError("output path must be different from the source ISO -- refusing to write over it")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} already exists -- pass --overwrite to replace it")

    chunked_copy(source_path, output_path)

    # ---- Pass 1: deck_archive.fsys (DeckData_Story.bin + DeckData_DarkPokemon.bin) ----
    reader = open_reader(output_path)
    try:
        fst = parse_fst(reader)
        deck_off, deck_len, deck_record_off = find_by_basename(fst, "deck_archive.fsys")
        deck_fsys_bytes = reader.read(deck_off, deck_len)
        deck_entries = parse_fsys(deck_fsys_bytes)
        story_entry = deck_entries["DeckData_Story.bin"]
        story_raw = reader.read(deck_off + story_entry["data_off"], 0x10 + story_entry["comp_size"])
        dark_entry = deck_entries["DeckData_DarkPokemon.bin"]
        dark_raw = reader.read(deck_off + dark_entry["data_off"], 0x10 + dark_entry["comp_size"])
    finally:
        reader.close()

    story_decompressed = deck_format.lzss_decode(story_raw)
    deck = deck_format.DeckFile(story_decompressed)
    dark_decompressed = deck_format.lzss_decode(dark_raw)
    ddpk = deck_format.DarkPokemonFile(dark_decompressed)

    before_trainer = deck.trainer(trainer_index)
    if before_trainer is None:
        raise ValueError(f"trainer_index {trainer_index} is an empty/unused DTNR slot on this ISO")
    used_slots = {m["slot"] for m in before_trainer["team"]}
    free_slots = [s for s in range(6) if s not in used_slots]
    if not free_slots:
        raise ValueError(f"trainer {trainer_index} already has a full 6-member team -- no empty slot to use")
    new_slot = free_slots[0]

    existing = ddpk.ddpk_full(target_ddpk_index)
    if not existing["in_use"]:
        raise ValueError(
            f"ddpk_index {target_ddpk_index} is NOT marked in-use in deck_archive.fsys's own copy -- this "
            "diagnostic is specifically for overwriting a REAL, already-in-range entry."
        )

    if story_deck_index is None:
        dpkm_members = [m for m in before_trainer["team"] if m["kind"] == "DPKM"]
        if not dpkm_members:
            raise ValueError(
                f"trainer {trainer_index} has no ordinary DPKM team member to borrow story_deck_index from by "
                "default -- pass story_deck_index explicitly."
            )
        story_deck_index = dpkm_members[0]["dpkm_index"]

    borrow_species, borrow_level = deck.dpkm_species_level(story_deck_index)
    if borrow_species == 0:
        raise ValueError(
            f"dpkm_index {story_deck_index} has no real data (its species field reads 0) -- refusing to use "
            "an empty/sentinel entry as this Shadow Pokemon's underlying data."
        )
    if shadow_level is None:
        shadow_level = borrow_level
    moves = list(moves) if moves else [0, 0, 0, 0]

    new_story_buf = bytearray(story_decompressed)
    dtnr_base = deck.dtnr_data + trainer_index * 0x38
    struct.pack_into(">H", new_story_buf, dtnr_base + 0x1C + new_slot * 2, target_ddpk_index)
    new_story_buf[dtnr_base + 0x04] |= (1 << new_slot)
    new_story_decompressed = bytes(new_story_buf)

    new_dark_decompressed = _overwrite_ddpk_entry_bytes(
        dark_decompressed, ddpk, target_ddpk_index, story_deck_index, shadow_level, moves
    )

    deck_patch_result = write_fsys_multi_entry_patch(
        output_path, deck_off, deck_len, deck_record_off, deck_fsys_bytes,
        [
            {"name": "DeckData_Story.bin", "entry_raw": story_raw, "new_decompressed": new_story_decompressed,
             "allow_decomp_resize": False},
            {"name": "DeckData_DarkPokemon.bin", "entry_raw": dark_raw, "new_decompressed": new_dark_decompressed,
             "allow_decomp_resize": False},
        ],
    )

    # ---- Pass 2: common.fsys (DeckData_DarkPokemon.bin + DeckData_DarkPokemon_EU.bin) ----
    reader = open_reader(output_path)
    try:
        fst2 = parse_fst(reader)
        common_off, common_len, common_record_off = find_by_basename(fst2, "common.fsys")
        common_fsys_bytes = reader.read(common_off, common_len)
        common_entries = parse_fsys(common_fsys_bytes)
        if "DeckData_DarkPokemon.bin" not in common_entries or "DeckData_DarkPokemon_EU.bin" not in common_entries:
            raise ValueError(
                "common.fsys on this ISO doesn't contain both expected DarkPokemon entries -- refusing to "
                "guess at a different disc layout. Found: " + ", ".join(sorted(common_entries))
            )
        common_dark_entry = common_entries["DeckData_DarkPokemon.bin"]
        common_dark_raw = reader.read(common_off + common_dark_entry["data_off"], 0x10 + common_dark_entry["comp_size"])
        common_eu_entry = common_entries["DeckData_DarkPokemon_EU.bin"]
        common_eu_raw = reader.read(common_off + common_eu_entry["data_off"], 0x10 + common_eu_entry["comp_size"])
    finally:
        reader.close()

    common_dark_decompressed = deck_format.lzss_decode(common_dark_raw)
    common_ddpk = deck_format.DarkPokemonFile(common_dark_decompressed)
    common_existing = common_ddpk.ddpk_full(target_ddpk_index)
    if not common_existing["in_use"]:
        raise ValueError(
            f"ddpk_index {target_ddpk_index} is NOT marked in-use in common.fsys's DeckData_DarkPokemon.bin -- "
            "unexpected mismatch with deck_archive.fsys's copy, refusing rather than guessing."
        )
    new_common_dark_decompressed = _overwrite_ddpk_entry_bytes(
        common_dark_decompressed, common_ddpk, target_ddpk_index, story_deck_index, shadow_level, moves
    )

    common_eu_decompressed = deck_format.lzss_decode(common_eu_raw)
    common_eu_ddpk = deck_format.DarkPokemonFile(common_eu_decompressed)
    new_common_eu_decompressed = _overwrite_ddpk_entry_bytes(
        common_eu_decompressed, common_eu_ddpk, target_ddpk_index, story_deck_index, shadow_level, moves
    )

    common_patch_result = write_fsys_multi_entry_patch(
        output_path, common_off, common_len, common_record_off, common_fsys_bytes,
        [
            {"name": "DeckData_DarkPokemon.bin", "entry_raw": common_dark_raw,
             "new_decompressed": new_common_dark_decompressed, "allow_decomp_resize": False},
            {"name": "DeckData_DarkPokemon_EU.bin", "entry_raw": common_eu_raw,
             "new_decompressed": new_common_eu_decompressed, "allow_decomp_resize": False},
        ],
        container_name="common.fsys",
    )

    after_deck = deck_format.DeckFile(new_story_decompressed)
    after_trainer = after_deck.trainer(trainer_index)

    print(
        f"Trainer {trainer_index}: party size {before_trainer['party_size']} -> {after_trainer['party_size']}, "
        f"new member points at ddpk_index {target_ddpk_index}, now consistently overwritten in ALL THREE "
        f"DarkPokemon copies on this disc: deck_archive.fsys's own, common.fsys's DeckData_DarkPokemon.bin, "
        f"and common.fsys's DeckData_DarkPokemon_EU.bin -- story_deck_index {story_deck_index} (species "
        f"{borrow_species}), shadow_level {shadow_level}. "
        f"deck_archive.fsys: {'grew' if deck_patch_result['grew'] else 'fit in place'}. "
        f"common.fsys: {'grew' if common_patch_result['grew'] else 'fit in place'}. "
        f"Boot this ISO and fight trainer index {trainer_index}: if the Shadow Pokemon appears and works now, "
        "common.fsys's copy was the missing piece -- deck_archive.fsys's own DarkPokemon section can very "
        "likely be ignored entirely for real Shadow Pokemon creation going forward."
    )

    return {
        "output": str(output_path),
        "trainer_index": trainer_index,
        "target_ddpk_index": target_ddpk_index,
        "story_deck_index": story_deck_index,
        "species": borrow_species,
        "shadow_level": shadow_level,
        "party_size_before": before_trainer["party_size"],
        "party_size_after": after_trainer["party_size"],
        "deck_archive_grew": deck_patch_result["grew"],
        "common_fsys_grew": common_patch_result["grew"],
        "deck_archive_per_entry": deck_patch_result["per_entry"],
        "common_fsys_per_entry": common_patch_result["per_entry"],
    }


# Genuinely NEW Shadow rather than a reuse: an in-use index clobbers whichever other trainers share it -- DDPK 83
# belongs to trainer 12 too, and several are shared by difficulty-tier duplicates. This uses one of the 44 clean
# padding slots (84-127), needing no resize, so the addition is purely additive.

def apply_team_padding_shadow_new_slot_test(
    source_path: Path, output_path: Path, trainer_index: int, target_ddpk_index: int,
    story_deck_index: int | None = None, shadow_level: int | None = None, moves: list[int] | None = None,
    overwrite: bool = False,
) -> dict:
    """DIAGNOSTIC, like `apply_team_padding_shadow_common_test` but `target_ddpk_index` must be a FREE padding
    slot (in_use == 0 in all three copies, normally 84-127), so no other trainer's data is touched.
    `story_deck_index` defaults to the trainer's first ordinary member."""
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()

    if output_path == source_path:
        raise ValueError("output path must be different from the source ISO -- refusing to write over it")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} already exists -- pass --overwrite to replace it")

    chunked_copy(source_path, output_path)

    # ---- Pass 1: deck_archive.fsys (DeckData_Story.bin + DeckData_DarkPokemon.bin) ----
    reader = open_reader(output_path)
    try:
        fst = parse_fst(reader)
        deck_off, deck_len, deck_record_off = find_by_basename(fst, "deck_archive.fsys")
        deck_fsys_bytes = reader.read(deck_off, deck_len)
        deck_entries = parse_fsys(deck_fsys_bytes)
        story_entry = deck_entries["DeckData_Story.bin"]
        story_raw = reader.read(deck_off + story_entry["data_off"], 0x10 + story_entry["comp_size"])
        dark_entry = deck_entries["DeckData_DarkPokemon.bin"]
        dark_raw = reader.read(deck_off + dark_entry["data_off"], 0x10 + dark_entry["comp_size"])
    finally:
        reader.close()

    story_decompressed = deck_format.lzss_decode(story_raw)
    deck = deck_format.DeckFile(story_decompressed)
    dark_decompressed = deck_format.lzss_decode(dark_raw)
    ddpk = deck_format.DarkPokemonFile(dark_decompressed)

    if not (0 <= target_ddpk_index < ddpk.ddpk_entries):
        raise ValueError(
            f"ddpk_index {target_ddpk_index} is out of range for this ISO's DarkPokemon table "
            f"(0..{ddpk.ddpk_entries - 1})"
        )

    before_trainer = deck.trainer(trainer_index)
    if before_trainer is None:
        raise ValueError(f"trainer_index {trainer_index} is an empty/unused DTNR slot on this ISO")
    used_slots = {m["slot"] for m in before_trainer["team"]}
    free_slots = [s for s in range(6) if s not in used_slots]
    if not free_slots:
        raise ValueError(f"trainer {trainer_index} already has a full 6-member team -- no empty slot to use")
    new_slot = free_slots[0]

    existing = ddpk.ddpk_full(target_ddpk_index)
    if existing["in_use"]:
        raise ValueError(
            f"ddpk_index {target_ddpk_index} is ALREADY in-use in deck_archive.fsys's own copy -- this "
            "diagnostic is specifically for a genuinely free/never-used slot. Use "
            "team-padding-shadow-common-test if overwriting an existing entry is what you actually want, or "
            "pick a different index (indices 84-127 are confirmed clean padding on the stock ISO)."
        )

    if story_deck_index is None:
        dpkm_members = [m for m in before_trainer["team"] if m["kind"] == "DPKM"]
        if not dpkm_members:
            raise ValueError(
                f"trainer {trainer_index} has no ordinary DPKM team member to borrow story_deck_index from by "
                "default -- pass story_deck_index explicitly."
            )
        story_deck_index = dpkm_members[0]["dpkm_index"]

    borrow_species, borrow_level = deck.dpkm_species_level(story_deck_index)
    if borrow_species == 0:
        raise ValueError(
            f"dpkm_index {story_deck_index} has no real data (its species field reads 0) -- refusing to use "
            "an empty/sentinel entry as this Shadow Pokemon's underlying data."
        )
    if shadow_level is None:
        shadow_level = borrow_level
    moves = list(moves) if moves else [0, 0, 0, 0]

    new_story_buf = bytearray(story_decompressed)
    dtnr_base = deck.dtnr_data + trainer_index * 0x38
    struct.pack_into(">H", new_story_buf, dtnr_base + 0x1C + new_slot * 2, target_ddpk_index)
    new_story_buf[dtnr_base + 0x04] |= (1 << new_slot)
    new_story_decompressed = bytes(new_story_buf)

    new_dark_decompressed = _overwrite_ddpk_entry_bytes(
        dark_decompressed, ddpk, target_ddpk_index, story_deck_index, shadow_level, moves
    )

    deck_patch_result = write_fsys_multi_entry_patch(
        output_path, deck_off, deck_len, deck_record_off, deck_fsys_bytes,
        [
            {"name": "DeckData_Story.bin", "entry_raw": story_raw, "new_decompressed": new_story_decompressed,
             "allow_decomp_resize": False},
            {"name": "DeckData_DarkPokemon.bin", "entry_raw": dark_raw, "new_decompressed": new_dark_decompressed,
             "allow_decomp_resize": False},
        ],
    )

    # ---- Pass 2: common.fsys (DeckData_DarkPokemon.bin + DeckData_DarkPokemon_EU.bin) ----
    reader = open_reader(output_path)
    try:
        fst2 = parse_fst(reader)
        common_off, common_len, common_record_off = find_by_basename(fst2, "common.fsys")
        common_fsys_bytes = reader.read(common_off, common_len)
        common_entries = parse_fsys(common_fsys_bytes)
        if "DeckData_DarkPokemon.bin" not in common_entries or "DeckData_DarkPokemon_EU.bin" not in common_entries:
            raise ValueError(
                "common.fsys on this ISO doesn't contain both expected DarkPokemon entries -- refusing to "
                "guess at a different disc layout. Found: " + ", ".join(sorted(common_entries))
            )
        common_dark_entry = common_entries["DeckData_DarkPokemon.bin"]
        common_dark_raw = reader.read(common_off + common_dark_entry["data_off"], 0x10 + common_dark_entry["comp_size"])
        common_eu_entry = common_entries["DeckData_DarkPokemon_EU.bin"]
        common_eu_raw = reader.read(common_off + common_eu_entry["data_off"], 0x10 + common_eu_entry["comp_size"])
    finally:
        reader.close()

    common_dark_decompressed = deck_format.lzss_decode(common_dark_raw)
    common_ddpk = deck_format.DarkPokemonFile(common_dark_decompressed)
    common_existing = common_ddpk.ddpk_full(target_ddpk_index)
    if common_existing["in_use"]:
        raise ValueError(
            f"ddpk_index {target_ddpk_index} is ALREADY in-use in common.fsys's DeckData_DarkPokemon.bin -- "
            "unexpected mismatch with deck_archive.fsys's copy, refusing rather than guessing."
        )
    new_common_dark_decompressed = _overwrite_ddpk_entry_bytes(
        common_dark_decompressed, common_ddpk, target_ddpk_index, story_deck_index, shadow_level, moves
    )

    common_eu_decompressed = deck_format.lzss_decode(common_eu_raw)
    common_eu_ddpk = deck_format.DarkPokemonFile(common_eu_decompressed)
    common_eu_existing = common_eu_ddpk.ddpk_full(target_ddpk_index)
    if common_eu_existing["in_use"]:
        raise ValueError(
            f"ddpk_index {target_ddpk_index} is ALREADY in-use in common.fsys's DeckData_DarkPokemon_EU.bin -- "
            "unexpected mismatch with the other two copies, refusing rather than guessing."
        )
    new_common_eu_decompressed = _overwrite_ddpk_entry_bytes(
        common_eu_decompressed, common_eu_ddpk, target_ddpk_index, story_deck_index, shadow_level, moves
    )

    common_patch_result = write_fsys_multi_entry_patch(
        output_path, common_off, common_len, common_record_off, common_fsys_bytes,
        [
            {"name": "DeckData_DarkPokemon.bin", "entry_raw": common_dark_raw,
             "new_decompressed": new_common_dark_decompressed, "allow_decomp_resize": False},
            {"name": "DeckData_DarkPokemon_EU.bin", "entry_raw": common_eu_raw,
             "new_decompressed": new_common_eu_decompressed, "allow_decomp_resize": False},
        ],
        container_name="common.fsys",
    )

    after_deck = deck_format.DeckFile(new_story_decompressed)
    after_trainer = after_deck.trainer(trainer_index)

    print(
        f"Trainer {trainer_index}: party size {before_trainer['party_size']} -> {after_trainer['party_size']}, "
        f"new member points at PREVIOUSLY-UNUSED ddpk_index {target_ddpk_index} (no other trainer's data "
        f"touched), now populated consistently in ALL THREE DarkPokemon copies on this disc: "
        f"deck_archive.fsys's own, common.fsys's DeckData_DarkPokemon.bin, and common.fsys's "
        f"DeckData_DarkPokemon_EU.bin -- story_deck_index {story_deck_index} (species {borrow_species}), "
        f"shadow_level {shadow_level}. "
        f"deck_archive.fsys: {'grew' if deck_patch_result['grew'] else 'fit in place'}. "
        f"common.fsys: {'grew' if common_patch_result['grew'] else 'fit in place'}. "
        f"Boot this ISO and fight trainer index {trainer_index}: if the Shadow Pokemon appears and works, this "
        "confirms BOTH that common.fsys was the missing piece AND that a genuinely new (not reused) DDPK slot "
        "works, of which there are currently 44 free (84-127) to build real new content into."
    )

    return {
        "output": str(output_path),
        "trainer_index": trainer_index,
        "target_ddpk_index": target_ddpk_index,
        "story_deck_index": story_deck_index,
        "species": borrow_species,
        "shadow_level": shadow_level,
        "party_size_before": before_trainer["party_size"],
        "party_size_after": after_trainer["party_size"],
        "deck_archive_grew": deck_patch_result["grew"],
        "common_fsys_grew": common_patch_result["grew"],
        "deck_archive_per_entry": deck_patch_result["per_entry"],
        "common_fsys_per_entry": common_patch_result["per_entry"],
    }


# A Shadow in free DDPK slot 84 borrowing trainer 26's own Cacnea data worked in-game, so this combines all three
# confirmed mechanisms -- DPKM growth, the free-slot Shadow, the common.fsys mirroring -- several times over.

def apply_team_padding_shadow_full_team_test(
    source_path: Path, output_path: Path, trainer_index: int, new_pokemon: list[dict],
    overwrite: bool = False,
) -> dict:
    """DIAGNOSTIC: gives one trainer several brand-new Shadow Pokemon in one pass, each with new
    species/level/moves via `grow_dpkm_section`, each in its own free DDPK slot, mirrored across all three
    DarkPokemon copies. `new_pokemon`: one dict per Shadow, filled into free team slots in order and into free
    DDPK indices from 84
    up unless it names its own `"target_ddpk_index"`. Needs `"species"` and `"level"`. Optional: `"moves"` for
    the underlying DPKM record (3 by convention, from the measured LZSS budget for bulk moveset edits),
    `"shadow_level"` (defaults to the new entry's level), `"shadow_moves"` (up to 2 ids; the confirmed Shadow
    range is 356-373), and the usual
    `"catch_rate_override"`/`"heart_gauge"`/`"bonus_exp"`/`"aggression"`/`"always_flee"`/`"flee_weight"`.

    Read `grow_dpkm_section()` first -- growing the DPKM section is the higher-risk part. Disposable copy."""
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()

    if output_path == source_path:
        raise ValueError("output path must be different from the source ISO -- refusing to write over it")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} already exists -- pass --overwrite to replace it")
    if not new_pokemon:
        raise ValueError("new_pokemon is empty -- nothing to add")

    chunked_copy(source_path, output_path)

    # ---- Pass 1: deck_archive.fsys (DeckData_Story.bin -- grow DPKM + team slots; DeckData_DarkPokemon.bin) ----
    reader = open_reader(output_path)
    try:
        fst = parse_fst(reader)
        deck_off, deck_len, deck_record_off = find_by_basename(fst, "deck_archive.fsys")
        deck_fsys_bytes = reader.read(deck_off, deck_len)
        deck_entries = parse_fsys(deck_fsys_bytes)
        story_entry = deck_entries["DeckData_Story.bin"]
        story_raw = reader.read(deck_off + story_entry["data_off"], 0x10 + story_entry["comp_size"])
        dark_entry = deck_entries["DeckData_DarkPokemon.bin"]
        dark_raw = reader.read(deck_off + dark_entry["data_off"], 0x10 + dark_entry["comp_size"])
    finally:
        reader.close()

    story_decompressed = deck_format.lzss_decode(story_raw)
    deck = deck_format.DeckFile(story_decompressed)
    dark_decompressed = deck_format.lzss_decode(dark_raw)
    ddpk = deck_format.DarkPokemonFile(dark_decompressed)

    before_trainer = deck.trainer(trainer_index)
    if before_trainer is None:
        raise ValueError(f"trainer_index {trainer_index} is an empty/unused DTNR slot on this ISO")
    used_slots = {m["slot"] for m in before_trainer["team"]}
    free_slots = [s for s in range(6) if s not in used_slots]
    if len(new_pokemon) > len(free_slots):
        raise ValueError(
            f"trainer {trainer_index} only has {len(free_slots)} free team slot(s), but {len(new_pokemon)} "
            "new Shadow Pokemon were requested"
        )

    # One DDPK index each: explicit `target_ddpk_index` honoured, the rest from the lowest unclaimed free ones.
    all_free_ddpk = [i for i in range(ddpk.ddpk_entries) if i != 0 and not ddpk.ddpk_full(i)["in_use"]]
    explicit = [p.get("target_ddpk_index") for p in new_pokemon]
    seen_explicit: set[int] = set()
    for idx in explicit:
        if idx is None:
            continue
        if idx in seen_explicit:
            raise ValueError(f"target_ddpk_index {idx} was requested more than once in this call")
        seen_explicit.add(idx)
        if idx not in all_free_ddpk:
            raise ValueError(f"target_ddpk_index {idx} is not a genuinely free DDPK slot on this ISO")
    auto_pool = [i for i in all_free_ddpk if i not in seen_explicit]
    ddpk_indices: list[int] = []
    for idx in explicit:
        if idx is not None:
            ddpk_indices.append(idx)
        else:
            if not auto_pool:
                raise ValueError("ran out of genuinely-free DDPK indices to auto-assign")
            ddpk_indices.append(auto_pool.pop(0))

    grown_story_decompressed, new_dpkm_indices = grow_dpkm_section(
        story_decompressed, deck,
        [{"species": p["species"], "level": p["level"], "moves": p.get("moves", [])} for p in new_pokemon],
    )

    new_story_buf = bytearray(grown_story_decompressed)
    dtnr_base = deck.dtnr_data + trainer_index * 0x38  # DTNR itself never moves; see grow_dpkm_section
    # A Shadow team slot stores the DDPK index, not the DPKM index -- the DPKM entry is only reachable through
    # the DDPK entry's own story_deck_index -- and the slot's shadow_mask bit must be set or both DeckFile and
    # the game read it as an ordinary DPKM reference.
    for slot, ddpk_index in zip(free_slots, ddpk_indices):
        struct.pack_into(">H", new_story_buf, dtnr_base + 0x1C + slot * 2, ddpk_index)
        new_story_buf[dtnr_base + 0x04] |= (1 << slot)
    new_story_decompressed = bytes(new_story_buf)

    new_dark_decompressed = dark_decompressed
    # The DDPK section never grows, only its 128 allocated slots get marked in_use, so one parsed `ddpk`
    # serves every entry's offset math.
    for p, dpkm_index, ddpk_index in zip(new_pokemon, new_dpkm_indices, ddpk_indices):
        shadow_level = p.get("shadow_level", p["level"])
        shadow_moves = p.get("shadow_moves") or [0, 0]
        new_dark_decompressed = _overwrite_ddpk_entry_bytes(
            new_dark_decompressed, ddpk, ddpk_index, dpkm_index, shadow_level, shadow_moves
        )

    deck_patch_result = write_fsys_multi_entry_patch(
        output_path, deck_off, deck_len, deck_record_off, deck_fsys_bytes,
        [
            {"name": "DeckData_Story.bin", "entry_raw": story_raw, "new_decompressed": new_story_decompressed,
             "allow_decomp_resize": True},
            {"name": "DeckData_DarkPokemon.bin", "entry_raw": dark_raw, "new_decompressed": new_dark_decompressed,
             "allow_decomp_resize": False},
        ],
    )

    # ---- Pass 2: common.fsys (DeckData_DarkPokemon.bin + DeckData_DarkPokemon_EU.bin) ----
    reader = open_reader(output_path)
    try:
        fst2 = parse_fst(reader)
        common_off, common_len, common_record_off = find_by_basename(fst2, "common.fsys")
        common_fsys_bytes = reader.read(common_off, common_len)
        common_entries = parse_fsys(common_fsys_bytes)
        if "DeckData_DarkPokemon.bin" not in common_entries or "DeckData_DarkPokemon_EU.bin" not in common_entries:
            raise ValueError(
                "common.fsys on this ISO doesn't contain both expected DarkPokemon entries -- refusing to "
                "guess at a different disc layout. Found: " + ", ".join(sorted(common_entries))
            )
        common_dark_entry = common_entries["DeckData_DarkPokemon.bin"]
        common_dark_raw = reader.read(common_off + common_dark_entry["data_off"], 0x10 + common_dark_entry["comp_size"])
        common_eu_entry = common_entries["DeckData_DarkPokemon_EU.bin"]
        common_eu_raw = reader.read(common_off + common_eu_entry["data_off"], 0x10 + common_eu_entry["comp_size"])
    finally:
        reader.close()

    common_dark_decompressed = deck_format.lzss_decode(common_dark_raw)
    common_ddpk = deck_format.DarkPokemonFile(common_dark_decompressed)
    common_eu_decompressed = deck_format.lzss_decode(common_eu_raw)
    common_eu_ddpk = deck_format.DarkPokemonFile(common_eu_decompressed)

    new_common_dark_decompressed = common_dark_decompressed
    new_common_eu_decompressed = common_eu_decompressed
    for p, dpkm_index, ddpk_index in zip(new_pokemon, new_dpkm_indices, ddpk_indices):
        if common_ddpk.ddpk_full(ddpk_index)["in_use"]:
            raise ValueError(
                f"ddpk_index {ddpk_index} is ALREADY in-use in common.fsys's DeckData_DarkPokemon.bin -- "
                "unexpected mismatch with deck_archive.fsys's copy, refusing rather than guessing."
            )
        if common_eu_ddpk.ddpk_full(ddpk_index)["in_use"]:
            raise ValueError(
                f"ddpk_index {ddpk_index} is ALREADY in-use in common.fsys's DeckData_DarkPokemon_EU.bin -- "
                "unexpected mismatch with the other copies, refusing rather than guessing."
            )
        shadow_level = p.get("shadow_level", p["level"])
        shadow_moves = p.get("shadow_moves") or [0, 0]
        new_common_dark_decompressed = _overwrite_ddpk_entry_bytes(
            new_common_dark_decompressed, common_ddpk, ddpk_index, dpkm_index, shadow_level, shadow_moves
        )
        new_common_eu_decompressed = _overwrite_ddpk_entry_bytes(
            new_common_eu_decompressed, common_eu_ddpk, ddpk_index, dpkm_index, shadow_level, shadow_moves
        )

    common_patch_result = write_fsys_multi_entry_patch(
        output_path, common_off, common_len, common_record_off, common_fsys_bytes,
        [
            {"name": "DeckData_DarkPokemon.bin", "entry_raw": common_dark_raw,
             "new_decompressed": new_common_dark_decompressed, "allow_decomp_resize": False},
            {"name": "DeckData_DarkPokemon_EU.bin", "entry_raw": common_eu_raw,
             "new_decompressed": new_common_eu_decompressed, "allow_decomp_resize": False},
        ],
        container_name="common.fsys",
    )

    after_deck = deck_format.DeckFile(new_story_decompressed)
    after_trainer = after_deck.trainer(trainer_index)

    print(
        f"Trainer {trainer_index}: party size {before_trainer['party_size']} -> {after_trainer['party_size']}. "
        f"Added {len(new_pokemon)} genuinely NEW Shadow Pokemon (new dpkm_indices {new_dpkm_indices}, "
        f"ddpk_indices {ddpk_indices}), consistently populated across ALL THREE DarkPokemon copies. "
        f"deck_archive.fsys: {'grew' if deck_patch_result['grew'] else 'fit in place'}. "
        f"common.fsys: {'grew' if common_patch_result['grew'] else 'fit in place'}. "
        f"THIS COMBINES DPKM GROWTH (ADDENDUM 51) WITH MULTIPLE NEW SHADOW SLOTS (ADDENDUM 60) IN ONE EDIT -- "
        f"watch closely for a crash or black screen at the main menu first, before anything else, then fight "
        f"trainer index {trainer_index} and confirm all {after_trainer['party_size']} team members are usable."
    )

    return {
        "output": str(output_path),
        "trainer_index": trainer_index,
        "new_dpkm_indices": new_dpkm_indices,
        "ddpk_indices": ddpk_indices,
        "party_size_before": before_trainer["party_size"],
        "party_size_after": after_trainer["party_size"],
        "deck_archive_grew": deck_patch_result["grew"],
        "common_fsys_grew": common_patch_result["grew"],
        "deck_archive_per_entry": deck_patch_result["per_entry"],
        "common_fsys_per_entry": common_patch_result["per_entry"],
    }


# Trainer 26's full 6-member team with 4 new-species Shadows worked in-game, so: the same across several
# trainers in one pass.

def apply_team_padding_shadow_multi_trainer_test(
    source_path: Path, output_path: Path, trainer_plans: list[dict],
    overwrite: bool = False,
) -> dict:
    """DIAGNOSTIC, `apply_team_padding_shadow_full_team_test` over several trainers: `trainer_plans` is a list
    of `{"trainer_index", "new_pokemon": [...]}`, each `new_pokemon` entry the same shape as there. DPKM growth
    happens ONCE for the whole batch in plan order, and DDPK indices come from one shared free pool, so two
    trainers in a call cannot collide with each other or with a real entry. Same DPKM-growth caveat --
    disposable copy."""
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()

    if output_path == source_path:
        raise ValueError("output path must be different from the source ISO -- refusing to write over it")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} already exists -- pass --overwrite to replace it")

    chunked_copy(source_path, output_path)
    return write_shadow_multi_trainer_patch(output_path, trainer_plans)


def write_shadow_multi_trainer_patch(output_path: Path, trainer_plans: list[dict]) -> dict:
    """The multi-trainer Shadow patch, without the copy step, so the per-seed pipeline can apply it to an ISO
    that has already been copied and partly patched.

    `output_path` must already exist and be writable -- a copy of some source ISO, never the original; the caller
    owns making that copy."""
    output_path = Path(output_path).resolve()
    if not trainer_plans:
        raise ValueError("trainer_plans is empty -- nothing to add")
    plan_trainer_indices = [p["trainer_index"] for p in trainer_plans]
    if len(set(plan_trainer_indices)) != len(plan_trainer_indices):
        raise ValueError(f"a trainer index was repeated across multiple plans: {plan_trainer_indices}")

    # ---- Pass 1: deck_archive.fsys (DeckData_Story.bin -- grow DPKM + team slots; DeckData_DarkPokemon.bin) ----
    reader = open_reader(output_path)
    try:
        fst = parse_fst(reader)
        deck_off, deck_len, deck_record_off = find_by_basename(fst, "deck_archive.fsys")
        deck_fsys_bytes = reader.read(deck_off, deck_len)
        deck_entries = parse_fsys(deck_fsys_bytes)
        story_entry = deck_entries["DeckData_Story.bin"]
        story_raw = reader.read(deck_off + story_entry["data_off"], 0x10 + story_entry["comp_size"])
        dark_entry = deck_entries["DeckData_DarkPokemon.bin"]
        dark_raw = reader.read(deck_off + dark_entry["data_off"], 0x10 + dark_entry["comp_size"])
    finally:
        reader.close()

    story_decompressed = deck_format.lzss_decode(story_raw)
    deck = deck_format.DeckFile(story_decompressed)
    dark_decompressed = deck_format.lzss_decode(dark_raw)
    ddpk = deck_format.DarkPokemonFile(dark_decompressed)

    before_trainers = {}
    per_trainer_free_slots: dict[int, list[int]] = {}
    for plan in trainer_plans:
        t_idx = plan["trainer_index"]
        before = deck.trainer(t_idx)
        if before is None:
            raise ValueError(f"trainer_index {t_idx} is an empty/unused DTNR slot on this ISO")
        before_trainers[t_idx] = before
        used_slots = {m["slot"] for m in before["team"]}
        free_slots = [s for s in range(6) if s not in used_slots]
        if len(plan["new_pokemon"]) > len(free_slots):
            raise ValueError(
                f"trainer {t_idx} only has {len(free_slots)} free team slot(s), but "
                f"{len(plan['new_pokemon'])} new Shadow Pokemon were requested for it"
            )
        per_trainer_free_slots[t_idx] = free_slots

    # Flatten in plan order, so DPKM growth and DDPK-index resolution each happen once for the batch.
    flat_new_pokemon: list[dict] = []
    flat_trainer_for_entry: list[int] = []
    for plan in trainer_plans:
        for p in plan["new_pokemon"]:
            flat_new_pokemon.append(p)
            flat_trainer_for_entry.append(plan["trainer_index"])

    all_free_ddpk = [i for i in range(ddpk.ddpk_entries) if i != 0 and not ddpk.ddpk_full(i)["in_use"]]
    explicit = [p.get("target_ddpk_index") for p in flat_new_pokemon]
    seen_explicit: set[int] = set()
    for idx in explicit:
        if idx is None:
            continue
        if idx in seen_explicit:
            raise ValueError(f"target_ddpk_index {idx} was requested more than once across this batch")
        seen_explicit.add(idx)
        if idx not in all_free_ddpk:
            raise ValueError(f"target_ddpk_index {idx} is not a genuinely free DDPK slot on this ISO")
    auto_pool = [i for i in all_free_ddpk if i not in seen_explicit]
    ddpk_indices: list[int] = []
    for idx in explicit:
        if idx is not None:
            ddpk_indices.append(idx)
        else:
            if not auto_pool:
                raise ValueError("ran out of genuinely-free DDPK indices to auto-assign across this batch")
            ddpk_indices.append(auto_pool.pop(0))

    grown_story_decompressed, new_dpkm_indices = grow_dpkm_section(
        story_decompressed, deck,
        [{"species": p["species"], "level": p["level"], "moves": p.get("moves", [])} for p in flat_new_pokemon],
    )

    new_story_buf = bytearray(grown_story_decompressed)
    # Same shadow_mask/DDPK-index convention, per trainer, against its own slice of ddpk_indices.
    cursor = 0
    for plan in trainer_plans:
        t_idx = plan["trainer_index"]
        count = len(plan["new_pokemon"])
        this_trainer_ddpk = ddpk_indices[cursor:cursor + count]
        dtnr_base = deck.dtnr_data + t_idx * 0x38
        for slot, ddpk_index in zip(per_trainer_free_slots[t_idx], this_trainer_ddpk):
            struct.pack_into(">H", new_story_buf, dtnr_base + 0x1C + slot * 2, ddpk_index)
            new_story_buf[dtnr_base + 0x04] |= (1 << slot)
        cursor += count
    new_story_decompressed = bytes(new_story_buf)

    new_dark_decompressed = dark_decompressed
    for p, dpkm_index, ddpk_index in zip(flat_new_pokemon, new_dpkm_indices, ddpk_indices):
        shadow_level = p.get("shadow_level", p["level"])
        shadow_moves = p.get("shadow_moves") or [0, 0]
        new_dark_decompressed = _overwrite_ddpk_entry_bytes(
            new_dark_decompressed, ddpk, ddpk_index, dpkm_index, shadow_level, shadow_moves
        )

    deck_patch_result = write_fsys_multi_entry_patch(
        output_path, deck_off, deck_len, deck_record_off, deck_fsys_bytes,
        [
            {"name": "DeckData_Story.bin", "entry_raw": story_raw, "new_decompressed": new_story_decompressed,
             "allow_decomp_resize": True},
            {"name": "DeckData_DarkPokemon.bin", "entry_raw": dark_raw, "new_decompressed": new_dark_decompressed,
             "allow_decomp_resize": False},
        ],
    )

    # ---- Pass 2: common.fsys (DeckData_DarkPokemon.bin + DeckData_DarkPokemon_EU.bin) ----
    reader = open_reader(output_path)
    try:
        fst2 = parse_fst(reader)
        common_off, common_len, common_record_off = find_by_basename(fst2, "common.fsys")
        common_fsys_bytes = reader.read(common_off, common_len)
        common_entries = parse_fsys(common_fsys_bytes)
        if "DeckData_DarkPokemon.bin" not in common_entries or "DeckData_DarkPokemon_EU.bin" not in common_entries:
            raise ValueError(
                "common.fsys on this ISO doesn't contain both expected DarkPokemon entries -- refusing to "
                "guess at a different disc layout. Found: " + ", ".join(sorted(common_entries))
            )
        common_dark_entry = common_entries["DeckData_DarkPokemon.bin"]
        common_dark_raw = reader.read(common_off + common_dark_entry["data_off"], 0x10 + common_dark_entry["comp_size"])
        common_eu_entry = common_entries["DeckData_DarkPokemon_EU.bin"]
        common_eu_raw = reader.read(common_off + common_eu_entry["data_off"], 0x10 + common_eu_entry["comp_size"])
    finally:
        reader.close()

    common_dark_decompressed = deck_format.lzss_decode(common_dark_raw)
    common_ddpk = deck_format.DarkPokemonFile(common_dark_decompressed)
    common_eu_decompressed = deck_format.lzss_decode(common_eu_raw)
    common_eu_ddpk = deck_format.DarkPokemonFile(common_eu_decompressed)

    new_common_dark_decompressed = common_dark_decompressed
    new_common_eu_decompressed = common_eu_decompressed
    for p, dpkm_index, ddpk_index in zip(flat_new_pokemon, new_dpkm_indices, ddpk_indices):
        if common_ddpk.ddpk_full(ddpk_index)["in_use"]:
            raise ValueError(
                f"ddpk_index {ddpk_index} is ALREADY in-use in common.fsys's DeckData_DarkPokemon.bin -- "
                "unexpected mismatch with deck_archive.fsys's copy, refusing rather than guessing."
            )
        if common_eu_ddpk.ddpk_full(ddpk_index)["in_use"]:
            raise ValueError(
                f"ddpk_index {ddpk_index} is ALREADY in-use in common.fsys's DeckData_DarkPokemon_EU.bin -- "
                "unexpected mismatch with the other copies, refusing rather than guessing."
            )
        shadow_level = p.get("shadow_level", p["level"])
        shadow_moves = p.get("shadow_moves") or [0, 0]
        new_common_dark_decompressed = _overwrite_ddpk_entry_bytes(
            new_common_dark_decompressed, common_ddpk, ddpk_index, dpkm_index, shadow_level, shadow_moves
        )
        new_common_eu_decompressed = _overwrite_ddpk_entry_bytes(
            new_common_eu_decompressed, common_eu_ddpk, ddpk_index, dpkm_index, shadow_level, shadow_moves
        )

    common_patch_result = write_fsys_multi_entry_patch(
        output_path, common_off, common_len, common_record_off, common_fsys_bytes,
        [
            {"name": "DeckData_DarkPokemon.bin", "entry_raw": common_dark_raw,
             "new_decompressed": new_common_dark_decompressed, "allow_decomp_resize": False},
            {"name": "DeckData_DarkPokemon_EU.bin", "entry_raw": common_eu_raw,
             "new_decompressed": new_common_eu_decompressed, "allow_decomp_resize": False},
        ],
        container_name="common.fsys",
    )

    after_deck = deck_format.DeckFile(new_story_decompressed)
    per_trainer_summary = {}
    cursor = 0
    for plan in trainer_plans:
        t_idx = plan["trainer_index"]
        count = len(plan["new_pokemon"])
        after_trainer = after_deck.trainer(t_idx)
        per_trainer_summary[t_idx] = {
            "party_size_before": before_trainers[t_idx]["party_size"],
            "party_size_after": after_trainer["party_size"],
            "new_dpkm_indices": new_dpkm_indices[cursor:cursor + count],
            "ddpk_indices": ddpk_indices[cursor:cursor + count],
        }
        cursor += count

    print(
        f"Batch of {len(trainer_plans)} trainer(s), {len(flat_new_pokemon)} new Shadow Pokemon total: "
        + "; ".join(
            f"trainer {t_idx} {s['party_size_before']} -> {s['party_size_after']} "
            f"(ddpk {s['ddpk_indices']})" for t_idx, s in per_trainer_summary.items()
        )
        + f". deck_archive.fsys: {'grew' if deck_patch_result['grew'] else 'fit in place'}. "
        f"common.fsys: {'grew' if common_patch_result['grew'] else 'fit in place'}. "
        "Boot and fight each trainer listed above in order; watch the main menu first for a crash or black "
        "screen before anything else."
    )

    return {
        "output": str(output_path),
        "per_trainer": per_trainer_summary,
        "deck_archive_grew": deck_patch_result["grew"],
        "common_fsys_grew": common_patch_result["grew"],
        "deck_archive_per_entry": deck_patch_result["per_entry"],
        "common_fsys_per_entry": common_patch_result["per_entry"],
    }


# Exploratory, largest-scale diagnostic: "enhanced difficulty" across all 232 trainers at once, roughly 500x the
# scale of the confirmed single-entry DPKM growth and the first growth+relocation with a decompressed-size change.

def apply_enhanced_difficulty_test(source_path: Path, output_path: Path, overwrite: bool = False) -> dict:
    """EXPLORATORY diagnostic, not wired into the seed-driven pipeline. Runs
    `compute_enhanced_difficulty_plan()` / `apply_enhanced_difficulty_edit()` against a real ISO: every one of
    the 232 trainers gets its ramp team addition, every existing member a flat level boost, and up to 44 new
    slots become real Shadow Pokemon from this file's free DDPK capacity.

    The largest change this project makes to a real ISO. Species and levels are a deterministic placeholder, not
    per-seed: the point is whether the mechanism survives a real boot at scale -- roughly 500 new DPKM entries
    and up to 44 new Shadows in one pass, very likely growing and relocating deck_archive.fsys for both
    DeckData_Story.bin and DeckData_DarkPokemon.bin together. Disposable copy only. Watch the main menu first,
    then spot-check early, mid and late trainers by DTNR index -- a problem in one story region need not show up
    at the menu or in a single battle."""
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()

    if output_path == source_path:
        raise ValueError("output path must be different from the source ISO -- refusing to write over it")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} already exists -- pass --overwrite to replace it")

    chunked_copy(source_path, output_path)

    reader = open_reader(output_path)
    try:
        fst = parse_fst(reader)
        deck_archive_off, deck_archive_len, deck_archive_record_off = find_by_basename(fst, "deck_archive.fsys")
        fsys_bytes = reader.read(deck_archive_off, deck_archive_len)
        fsys_entries = parse_fsys(fsys_bytes)
        story_entry = fsys_entries["DeckData_Story.bin"]
        story_raw = reader.read(deck_archive_off + story_entry["data_off"], 0x10 + story_entry["comp_size"])
        dark_entry = fsys_entries["DeckData_DarkPokemon.bin"]
        dark_raw = reader.read(deck_archive_off + dark_entry["data_off"], 0x10 + dark_entry["comp_size"])
    finally:
        reader.close()

    story_decompressed = deck_format.lzss_decode(story_raw)
    deck = deck_format.DeckFile(story_decompressed)
    dark_decompressed = deck_format.lzss_decode(dark_raw)
    ddpk = deck_format.DarkPokemonFile(dark_decompressed)

    plan = compute_enhanced_difficulty_plan(deck, ddpk)
    new_story_decompressed, new_dark_decompressed = apply_enhanced_difficulty_edit(
        story_decompressed, deck, dark_decompressed, ddpk, plan
    )

    patch_result = write_fsys_multi_entry_patch(
        output_path, deck_archive_off, deck_archive_len, deck_archive_record_off, fsys_bytes,
        [
            {"name": "DeckData_Story.bin", "entry_raw": story_raw, "new_decompressed": new_story_decompressed,
             "allow_decomp_resize": True},
            {"name": "DeckData_DarkPokemon.bin", "entry_raw": dark_raw, "new_decompressed": new_dark_decompressed,
             "allow_decomp_resize": False},
        ],
    )

    after_deck = deck_format.DeckFile(new_story_decompressed)
    shadow_count = sum(1 for s in plan["team_slot_plan"] if s["kind"] == "shadow")

    print(
        f"Enhanced difficulty applied across {len(set(s['trainer_index'] for s in plan['team_slot_plan']))} "
        f"trainers: DPKM section grew from {deck.dpkm_entries} to {after_deck.dpkm_entries} entries "
        f"({len(plan['new_dpkm_entries'])} new team members total, {shadow_count} of them genuine new Shadow "
        f"Pokemon using {len(plan['ddpk_slots_used'])} of this file's real free DDPK slots), plus a +3 level "
        f"boost on every existing team member. "
        + (
            f"DeckData_Story.bin: {'grew' if patch_result['per_entry']['DeckData_Story.bin']['grew'] else 'fit in place'}"
            f" ({patch_result['per_entry']['DeckData_Story.bin']['old_comp_size']} -> "
            f"{patch_result['per_entry']['DeckData_Story.bin']['real_comp_size']} bytes). "
            f"DeckData_DarkPokemon.bin: {'grew' if patch_result['per_entry']['DeckData_DarkPokemon.bin']['grew'] else 'fit in place'}"
            f" ({patch_result['per_entry']['DeckData_DarkPokemon.bin']['old_comp_size']} -> "
            f"{patch_result['per_entry']['DeckData_DarkPokemon.bin']['real_comp_size']} bytes)."
        )
        + " THIS IS THE LARGEST, LEAST-TESTED CHANGE YET: watch the main menu FIRST, then spot-check a handful "
        "of early, mid, and late trainers (by DTNR index) -- not just one."
    )

    return {
        "output": str(output_path),
        "trainers_touched": len(set(s["trainer_index"] for s in plan["team_slot_plan"])),
        "new_dpkm_entries": len(plan["new_dpkm_entries"]),
        "new_shadow_pokemon": shadow_count,
        "dpkm_entries_before": deck.dpkm_entries,
        "dpkm_entries_after": after_deck.dpkm_entries,
        "grew": patch_result["grew"],
        "per_entry": patch_result["per_entry"],
    }


# READ-ONLY diagnostic: splash-screen freeze investigation.

def inspect_relocation(path: Path, check_file: str | None = None) -> dict:
    """READ-ONLY -- never opens `path` write-capable. Run against an already-patched ISO/CISO showing a
    real-hardware problem, since an offline reproduction of the freezing edit against a real CISO fixture
    completed cleanly. Reports: deck_archive.fsys/common.fsys's current FST offset and length; for a CISO, `block_size`,
    `total_blocks`, `virtual_size` and the highest present block; whether either container's byte range
    overlaps ANY other file the FST lists; and an independent re-parse/re-decode of both, trusting no earlier
    verification."""
    path = Path(path).resolve()
    reader = open_reader(path)
    try:
        fst = parse_fst(reader)
        all_files = sorted(
            ((name, off, length) for name, (off, length, _rec) in fst.items()),
            key=lambda t: t[1],
        )
        deck_off, deck_len, _ = find_by_basename(fst, "deck_archive.fsys")
        common_off, common_len, _ = find_by_basename(fst, "common.fsys")

        overlaps = []
        for i, (name, off, length) in enumerate(all_files):
            for other_name, other_off, other_length in all_files[i + 1:]:
                if off < other_off + other_length and other_off < off + length:
                    overlaps.append({"a": name, "a_range": [off, off + length],
                                      "b": other_name, "b_range": [other_off, other_off + other_length]})

        # A corrupted FST *name* -- a wrong record_off write clobbering an unrelated entry -- leaves the count
        # and overlap checks above clean, so scan every decoded name for anything implausible as a filename.
        suspicious_names = [
            {"raw_name_repr": repr(name), "offset": off, "length": length}
            for name, off, length in all_files
            if not name or any(ch not in
                "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-()/ " for ch in name)
        ]

        report = {
            "path": str(path),
            "is_ciso": isinstance(reader, CisoReader),
            "deck_archive_offset": deck_off, "deck_archive_length": deck_len,
            "common_fsys_offset": common_off, "common_fsys_length": common_len,
            "num_files_on_disc": len(all_files),
            "any_fst_file_overlaps": overlaps,
            "suspicious_fst_names": suspicious_names,
        }

        if check_file:
            # `fst` is keyed by full path, so a direct .get() would miss a file in a subdirectory.
            try:
                cf_off, cf_len, cf_record_off = find_by_basename(fst, check_file)
                cf_bytes = reader.read(cf_off, min(cf_len, 16))
                report["check_file"] = {
                    "name": check_file,
                    "found": True,
                    "offset": cf_off,
                    "length": cf_len,
                    "record_off": cf_record_off,
                    "first_16_bytes": cf_bytes.hex(),
                }
            except (KeyError, ValueError) as exc:
                report["check_file"] = {"name": check_file, "found": False, "error": str(exc)}
        if isinstance(reader, CisoReader):
            highest_present = max((i for i, p in enumerate(reader.block_present) if p), default=-1)
            report.update({
                "block_size": reader.block_size,
                "total_blocks": reader.total_blocks,
                "virtual_size": reader.virtual_size,
                "highest_present_block": highest_present,
                "highest_present_block_end_offset": (highest_present + 1) * reader.block_size,
                "deck_archive_end_block": -(-(deck_off + deck_len) // reader.block_size),
                "common_fsys_end_block": -(-(common_off + common_len) // reader.block_size),
            })

        deck_bytes = reader.read(deck_off, deck_len)
        common_bytes = reader.read(common_off, common_len)
    finally:
        reader.close()

    problems = []
    try:
        deck_entries = parse_fsys(deck_bytes)
        story = deck_entries["DeckData_Story.bin"]
        story_raw = deck_bytes[story["data_off"]: story["data_off"] + 0x10 + story["comp_size"]]
        deck_format.lzss_decode(story_raw)
        dark = deck_entries["DeckData_DarkPokemon.bin"]
        dark_raw = deck_bytes[dark["data_off"]: dark["data_off"] + 0x10 + dark["comp_size"]]
        deck_format.lzss_decode(dark_raw)
    except Exception as exc:
        problems.append(f"deck_archive.fsys re-parse/decode failed: {exc!r}")
    try:
        common_entries = parse_fsys(common_bytes)
        for nm in ("DeckData_DarkPokemon.bin", "DeckData_DarkPokemon_EU.bin"):
            e = common_entries[nm]
            raw = common_bytes[e["data_off"]: e["data_off"] + 0x10 + e["comp_size"]]
            deck_format.lzss_decode(raw)
    except Exception as exc:
        problems.append(f"common.fsys re-parse/decode failed: {exc!r}")
    report["problems_found"] = problems
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    apply_cmd = sub.add_parser("apply", help="Apply a seed's trainer-species patch to a new ISO copy.")
    apply_cmd.add_argument("--source", required=True, help="Path to your own, legally-owned source ISO/CISO.")
    apply_cmd.add_argument("--output", required=True, help="Path for the new, patched ISO copy (must differ from --source).")
    apply_cmd.add_argument("--seed", required=True, help="Path to the .appxd seed file (or a bare seed.json).")
    apply_cmd.add_argument("--overwrite", action="store_true", help="Replace --output if it already exists.")
    apply_cmd.add_argument(
        "--result-json", default=None,
        help="NEW 2026-09-09 (ADDENDUM 73): optional path to write apply_patch()'s summary dict as JSON after "
             "a successful run. Used by launcher_patch.py to hand the result back to the Launcher's own "
             "process when this command is run as a separate, visible-console subprocess (so the player gets "
             "live progress output) rather than in-process -- not needed for ordinary direct CLI use.",
    )

    reloc_cmd = sub.add_parser(
        "relocation-test",
        help="DIAGNOSTIC ONLY: relocate deck_archive.fsys to a new disc offset with zero content changes, to "
             "test in isolation whether moving that file is itself safe on real hardware (see ADDENDUM 46 / "
             "apply_relocation_isolation_test's own docstring for why this exists).",
    )
    reloc_cmd.add_argument("--source", required=True, help="Path to your own, legally-owned source ISO/CISO.")
    reloc_cmd.add_argument("--output", required=True, help="Path for the new, relocated-only ISO copy (must differ from --source).")
    reloc_cmd.add_argument("--overwrite", action="store_true", help="Replace --output if it already exists.")

    pad_cmd = sub.add_parser(
        "team-padding-test",
        help="DIAGNOSTIC ONLY: give ONE trainer ONE extra team member, to test the growth+relocation "
             "combination on real hardware. SUPERSEDED as of ADDENDUM 48's own real-hardware run: this ISO has "
             "no genuinely free DPKM index to use (see apply_growth_checkpoint_test's docstring), and a "
             "single-trainer edit is too small to ever overflow the real allocation on its own regardless. Use "
             "growth-checkpoint-test instead -- kept only in case a future, differently-sized ISO/edit changes "
             "either of those facts.",
    )
    pad_cmd.add_argument("--source", required=True, help="Path to your own, legally-owned source ISO/CISO.")
    pad_cmd.add_argument("--output", required=True, help="Path for the new, team-padded ISO copy (must differ from --source).")
    pad_cmd.add_argument("--trainer-index", type=int, required=True, help="DTNR trainer index to give an extra team member.")
    pad_cmd.add_argument("--dpkm-index", type=int, required=True, help="A currently-FREE DPKM index for the new Pokemon's data.")
    pad_cmd.add_argument("--species", type=int, required=True, help="Internal species id for the new team member.")
    pad_cmd.add_argument("--level", type=int, required=True, help="Level for the new team member.")
    pad_cmd.add_argument("--overwrite", action="store_true", help="Replace --output if it already exists.")

    growth_cmd = sub.add_parser(
        "growth-checkpoint-test",
        help="DIAGNOSTIC ONLY (ADDENDUM 48 corrected checkpoint): reassign species+moves across roughly a "
             "third of DeckData_Story.bin's roster (deterministic, always-valid data) to genuinely force "
             "deck_archive.fsys to grow and relocate, while leaving ONE reference trainer completely "
             "untouched as an easy before/after check. See apply_growth_checkpoint_test's own docstring.",
    )
    growth_cmd.add_argument("--source", required=True, help="Path to your own, legally-owned source ISO/CISO.")
    growth_cmd.add_argument("--output", required=True, help="Path for the new, growth-tested ISO copy (must differ from --source).")
    growth_cmd.add_argument("--reference-trainer-index", type=int, required=True, help="DTNR trainer index to leave completely untouched as your before/after reference.")
    growth_cmd.add_argument("--overwrite", action="store_true", help="Replace --output if it already exists.")

    borrow_cmd = sub.add_parser(
        "team-padding-borrow-test",
        help="DIAGNOSTIC ONLY (ADDENDUM 49 follow-up): give ONE trainer an extra team member by pointing it "
             "at an EXISTING Pokemon's data (no free DPKM slot needed). Tests whether the game accepts/uses a "
             "trainer with more team members than it shipped with -- the missing prerequisite before real "
             "(newly-invented-data) team padding is worth building on top of DPKM-section growth.",
    )
    borrow_cmd.add_argument("--source", required=True, help="Path to your own, legally-owned source ISO/CISO.")
    borrow_cmd.add_argument("--output", required=True, help="Path for the new, padded ISO copy (must differ from --source).")
    borrow_cmd.add_argument("--trainer-index", type=int, required=True, help="DTNR trainer index to give an extra team member.")
    borrow_cmd.add_argument("--borrow-dpkm-index", type=int, default=None, help="An EXISTING, already-populated DPKM index to reuse. Defaults to the trainer's own first team member.")
    borrow_cmd.add_argument("--overwrite", action="store_true", help="Replace --output if it already exists.")

    new_species_cmd = sub.add_parser(
        "team-padding-new-species-test",
        help="EXPLORATORY, HIGHER-RISK DIAGNOSTIC (ADDENDUM 51): give ONE trainer a genuinely NEW, uniquely-"
             "specified team member by growing the DPKM section itself past its current entry count -- the "
             "first thing in this project to change DeckData_Story.bin's decompressed section layout, not "
             "just its compressed footprint. Whether the game's own code tolerates this is UNKNOWN and "
             "UNTESTED. Always run against a disposable ISO copy. See grow_dpkm_section()'s docstring.",
    )
    new_species_cmd.add_argument("--source", required=True, help="Path to your own, legally-owned source ISO/CISO.")
    new_species_cmd.add_argument("--output", required=True, help="Path for the new, padded ISO copy (must differ from --source).")
    new_species_cmd.add_argument("--trainer-index", type=int, required=True, help="DTNR trainer index to give the new team member.")
    new_species_cmd.add_argument("--species", type=int, required=True, help="Internal species id for the new team member.")
    new_species_cmd.add_argument("--level", type=int, required=True, help="Level for the new team member.")
    new_species_cmd.add_argument("--moves", default=None, help="NEW (2026-09-09): comma-separated move ids for the new team member, e.g. 1 for Pound alone. Defaults to no moves (an empty/unusable moveset) if omitted, matching this command's prior behavior.")
    new_species_cmd.add_argument("--overwrite", action="store_true", help="Replace --output if it already exists.")

    shadow_cmd = sub.add_parser(
        "team-padding-shadow-test",
        help="EXPLORATORY DIAGNOSTIC (ADDENDUM 54): give ONE trainer ONE new Shadow Pokemon, isolating the "
             "one mechanism ADDENDUM 52's full-scale run never got real-hardware confirmation for before it "
             "softlocked. Nothing else is touched -- no level boost, no other trainers.",
    )
    shadow_cmd.add_argument("--source", required=True, help="Path to your own, legally-owned source ISO/CISO.")
    shadow_cmd.add_argument("--output", required=True, help="Path for the new, shadow-tested ISO copy (must differ from --source).")
    shadow_cmd.add_argument("--trainer-index", type=int, required=True, help="DTNR trainer index to give the new Shadow Pokemon.")
    shadow_cmd.add_argument("--species", type=int, required=True, help="Internal species id for the new Shadow Pokemon.")
    shadow_cmd.add_argument("--level", type=int, required=True, help="Level for the new Shadow Pokemon.")
    shadow_cmd.add_argument("--overwrite", action="store_true", help="Replace --output if it already exists.")

    shadow_borrow_cmd = sub.add_parser(
        "team-padding-shadow-borrow-test",
        help="EXPLORATORY DIAGNOSTIC (ADDENDUM 55): give ONE trainer ONE new Shadow Pokemon whose data BORROWS "
             "an existing DPKM entry instead of growing the DPKM section -- isolates the shadow_mask/DDPK-write "
             "mechanism alone, since ADDENDUM 54's version (which combined that with DPKM growth) came back "
             "from real hardware with no crash but the new Shadow Pokemon simply not appearing in battle.",
    )
    shadow_borrow_cmd.add_argument("--source", required=True, help="Path to your own, legally-owned source ISO/CISO.")
    shadow_borrow_cmd.add_argument("--output", required=True, help="Path for the new, shadow-borrow-tested ISO copy (must differ from --source).")
    shadow_borrow_cmd.add_argument("--trainer-index", type=int, required=True, help="DTNR trainer index to give the new Shadow Pokemon.")
    shadow_borrow_cmd.add_argument("--borrow-dpkm-index", type=int, default=None, help="An EXISTING, already-populated DPKM index for this Shadow Pokemon to reuse. Defaults to the trainer's own first ordinary team member.")
    shadow_borrow_cmd.add_argument("--shadow-level", type=int, default=None, help="Level for the DDPK entry. Defaults to the borrowed DPKM entry's own level.")
    shadow_borrow_cmd.add_argument("--overwrite", action="store_true", help="Replace --output if it already exists.")

    shadow_reuse_cmd = sub.add_parser(
        "team-padding-shadow-reuse-test",
        help="EXPLORATORY DIAGNOSTIC (ADDENDUM 56): give ONE trainer ONE new Shadow Pokemon by pointing a new "
             "team slot at an EXISTING, already-in-use DDPK index (one some other real trainer already owns) "
             "instead of a fresh/never-used one. Directly tests the 'caught pool' hypothesis -- that a "
             "save-resident flag/pool, not story progress, gates which DDPK indices the game will actually "
             "load in battle -- after ADDENDUM 54/55's fresh-index Shadow Pokemon both failed to appear.",
    )
    shadow_reuse_cmd.add_argument("--source", required=True, help="Path to your own, legally-owned source ISO/CISO.")
    shadow_reuse_cmd.add_argument("--output", required=True, help="Path for the new, shadow-reuse-tested ISO copy (must differ from --source).")
    shadow_reuse_cmd.add_argument("--trainer-index", type=int, required=True, help="DTNR trainer index to give the reused Shadow Pokemon.")
    shadow_reuse_cmd.add_argument("--reuse-ddpk-index", type=int, required=True, help="An EXISTING, already-in-use DDPK index to reuse (e.g. 14, the RESIX Houndour confirmed working live).")
    shadow_reuse_cmd.add_argument("--overwrite", action="store_true", help="Replace --output if it already exists.")

    shadow_overwrite_cmd = sub.add_parser(
        "team-padding-shadow-overwrite-test",
        help="EXPLORATORY DIAGNOSTIC (ADDENDUM 57): give ONE trainer ONE new Shadow Pokemon by pointing a new "
             "team slot at an EXISTING, real, in-range (<=83) DDPK index whose own content is first "
             "OVERWRITTEN with this project's own new-entry field pattern. Disambiguates whether ADDENDUM "
             "56's success with a reused index was about the raw index value or the untouched original ROM "
             "bytes. WARNING: this deliberately corrupts another real trainer's real Shadow Pokemon data on "
             "this one disposable test ISO -- never the player's real file. Read the function docstring.",
    )
    shadow_overwrite_cmd.add_argument("--source", required=True, help="Path to your own, legally-owned source ISO/CISO.")
    shadow_overwrite_cmd.add_argument("--output", required=True, help="Path for the new, shadow-overwrite-tested ISO copy (must differ from --source).")
    shadow_overwrite_cmd.add_argument("--trainer-index", type=int, required=True, help="DTNR trainer index to give the overwritten Shadow Pokemon.")
    shadow_overwrite_cmd.add_argument("--target-ddpk-index", type=int, required=True, help="An EXISTING, real, in-range (<=83) DDPK index to overwrite and reuse (e.g. 83).")
    shadow_overwrite_cmd.add_argument("--overwrite", action="store_true", help="Replace --output if it already exists.")

    shadow_common_cmd = sub.add_parser(
        "team-padding-shadow-common-test",
        help="DIAGNOSTIC (ADDENDUM 58) -- THE LEADING CANDIDATE FIX: edits an existing, in-range DDPK entry "
             "consistently across ALL THREE on-disc DarkPokemon copies (deck_archive.fsys's own, plus "
             "common.fsys's DeckData_DarkPokemon.bin AND DeckData_DarkPokemon_EU.bin) -- common.fsys's copies "
             "were found to be untouched, 100% vanilla in live RAM even after ADDENDUM 57's deck_archive.fsys-"
             "only overwrite, strongly suggesting THAT is what the game actually reads for Shadow Pokemon "
             "battle data. Same team-slot/shadow-mask write on trainer_index as every prior Shadow addendum.",
    )
    shadow_common_cmd.add_argument("--source", required=True, help="Path to your own, legally-owned source ISO/CISO.")
    shadow_common_cmd.add_argument("--output", required=True, help="Path for the new, shadow-common-tested ISO copy (must differ from --source).")
    shadow_common_cmd.add_argument("--trainer-index", type=int, required=True, help="DTNR trainer index to give the new Shadow Pokemon.")
    shadow_common_cmd.add_argument("--target-ddpk-index", type=int, required=True, help="An EXISTING, real, in-range (<=83) DDPK index to overwrite and reuse in all three copies (e.g. 83).")
    shadow_common_cmd.add_argument("--overwrite", action="store_true", help="Replace --output if it already exists.")

    shadow_new_slot_cmd = sub.add_parser(
        "team-padding-shadow-new-slot-test",
        help="DIAGNOSTIC (ADDENDUM 60): give ONE trainer a genuinely NEW Shadow Pokemon in a currently-FREE "
             "DDPK padding slot (84-127) -- unlike team-padding-shadow-common-test/-overwrite-test, this "
             "never touches any other real trainer's existing Shadow Pokemon data, since nothing currently "
             "points at the slot it uses. Same all-three-DarkPokemon-copies mirroring as ADDENDUM 58.",
    )
    shadow_new_slot_cmd.add_argument("--source", required=True, help="Path to your own, legally-owned source ISO/CISO.")
    shadow_new_slot_cmd.add_argument("--output", required=True, help="Path for the new, shadow-new-slot-tested ISO copy (must differ from --source).")
    shadow_new_slot_cmd.add_argument("--trainer-index", type=int, required=True, help="DTNR trainer index to give the new Shadow Pokemon.")
    shadow_new_slot_cmd.add_argument("--target-ddpk-index", type=int, required=True, help="A currently-FREE DDPK index to populate (e.g. 84 -- the first of 44 confirmed-clean padding slots, 84-127).")
    shadow_new_slot_cmd.add_argument("--story-deck-index", type=int, default=None, help="An EXISTING, already-populated DPKM index to use for this Shadow Pokemon's species/moveset. Defaults to trainer_index's own first ordinary team member.")
    shadow_new_slot_cmd.add_argument("--shadow-level", type=int, default=None, help="Level for the DDPK entry. Defaults to the borrowed/chosen DPKM entry's own level.")
    shadow_new_slot_cmd.add_argument("--overwrite", action="store_true", help="Replace --output if it already exists.")

    shadow_full_team_cmd = sub.add_parser(
        "team-padding-shadow-full-team-test",
        help="DIAGNOSTIC (ADDENDUM 61): give ONE trainer MULTIPLE brand-new Shadow Pokemon in one pass -- "
             "each a genuinely new species (via DPKM growth, ADDENDUM 51) in its own free DDPK slot "
             "(ADDENDUM 60), mirrored across all three DarkPokemon copies (ADDENDUM 58). Reads the list of "
             "new Shadow Pokemon to add from a JSON file (a plain list of {species, level, ...} dicts -- see "
             "apply_team_padding_shadow_full_team_test()'s own docstring for every supported key).",
    )
    shadow_full_team_cmd.add_argument("--source", required=True, help="Path to your own, legally-owned source ISO/CISO.")
    shadow_full_team_cmd.add_argument("--output", required=True, help="Path for the new, shadow-full-team-tested ISO copy (must differ from --source).")
    shadow_full_team_cmd.add_argument("--trainer-index", type=int, required=True, help="DTNR trainer index to give the new Shadow Pokemon team members.")
    shadow_full_team_cmd.add_argument("--new-pokemon-json", required=True, help="Path to a JSON file containing a list of new-Shadow-Pokemon dicts (species/level/moves/shadow_level/shadow_moves/...).")
    shadow_full_team_cmd.add_argument("--overwrite", action="store_true", help="Replace --output if it already exists.")

    shadow_multi_trainer_cmd = sub.add_parser(
        "team-padding-shadow-multi-trainer-test",
        help="DIAGNOSTIC (ADDENDUM 62): like team-padding-shadow-full-team-test, but for MULTIPLE trainers "
             "in one pass -- reads a JSON file containing a list of {trainer_index, new_pokemon: [...]} plans, "
             "one per trainer, so several trainers can be given new Shadow Pokemon and fought back-to-back on "
             "one ISO.",
    )
    shadow_multi_trainer_cmd.add_argument("--source", required=True, help="Path to your own, legally-owned source ISO/CISO.")
    shadow_multi_trainer_cmd.add_argument("--output", required=True, help="Path for the new, shadow-multi-trainer-tested ISO copy (must differ from --source).")
    shadow_multi_trainer_cmd.add_argument("--trainer-plans-json", required=True, help="Path to a JSON file containing a list of {trainer_index, new_pokemon: [...]} plan dicts.")
    shadow_multi_trainer_cmd.add_argument("--overwrite", action="store_true", help="Replace --output if it already exists.")

    enhanced_cmd = sub.add_parser(
        "enhanced-difficulty-test",
        help="EXPLORATORY, LARGEST-SCALE DIAGNOSTIC (ADDENDUM 52): applies ramp-based team padding + level "
             "boost + Shadow Pokemon across ALL 232 real trainers at once (~500 new DPKM entries, up to 44 "
             "new Shadow Pokemon). The biggest, least-tested change this project has made to a real ISO -- "
             "not yet wired into seed generation. Always run against a disposable ISO copy.",
    )
    enhanced_cmd.add_argument("--source", required=True, help="Path to your own, legally-owned source ISO/CISO.")
    enhanced_cmd.add_argument("--output", required=True, help="Path for the new, enhanced-difficulty ISO copy (must differ from --source).")
    enhanced_cmd.add_argument("--overwrite", action="store_true", help="Replace --output if it already exists.")

    ball_flag_cmd = sub.add_parser(
        "ball-behavior-flag-probe",
        help="DIAGNOSTIC ONLY (ADDENDUM 303): set the per-item behaviour flag byte that ONLY the Master Ball "
             "carries on the ball(s) you name, so one throw can settle whether that byte is what makes a "
             "catch unconditional. Writes a copy; never a feature until a live test says so.",
    )
    ball_flag_cmd.add_argument("--source", required=True, help="Path to your own, legally-owned source ISO/CISO.")
    ball_flag_cmd.add_argument("--output", required=True, help="Path for the new probe ISO copy (must differ from --source).")
    ball_flag_cmd.add_argument("--item-ids", default="4", help="Comma-separated ball item ids to flag. Default 4 (Poke Ball) -- the weakest ball, so a first-throw catch on a full-health target is unambiguous. 1=Master 2=Ultra 3=Great 4=Poke.")
    ball_flag_cmd.add_argument("--value", default=None, help="u16 to write outright. Default is to OR in bit 15 (0x8000) instead, which is the only bit the Master Ball sets and no other item does -- safer than replacing the low bits, which differ per item and plainly mean something.")
    ball_flag_cmd.add_argument("--overwrite", action="store_true", help="Replace --output if it already exists.")

    common_reloc_cmd = sub.add_parser(
        "common-fsys-relocation-test",
        help="DIAGNOSTIC ONLY (ADDENDUM 65): relocate ONLY common.fsys to a new disc offset with ZERO content "
             "change (deck_archive.fsys untouched) -- isolates whether common.fsys's relocation ALONE is what "
             "the game can't follow (the ADDENDUM 63/66 splash-screen freeze's leading hypothesis), "
             "independent of deck_archive.fsys also relocating or any Shadow Pokemon content at all.",
    )
    common_reloc_cmd.add_argument("--source", required=True, help="Path to your own, legally-owned source ISO/CISO.")
    common_reloc_cmd.add_argument("--output", required=True, help="Path for the new, common.fsys-relocated-only ISO copy (must differ from --source).")
    common_reloc_cmd.add_argument("--overwrite", action="store_true", help="Replace --output if it already exists.")

    dual_reloc_cmd = sub.add_parser(
        "dual-relocation-test",
        help="DIAGNOSTIC ONLY (ADDENDUM 66): relocate BOTH deck_archive.fsys AND common.fsys in one build, "
             "EACH with ZERO content change -- isolates whether two simultaneous relocations (independent of "
             "any Shadow Pokemon content or DPKM growth) is what the game can't follow, now that common.fsys "
             "alone (ADDENDUM 65) is confirmed safe.",
    )
    dual_reloc_cmd.add_argument("--source", required=True, help="Path to your own, legally-owned source ISO/CISO.")
    dual_reloc_cmd.add_argument("--output", required=True, help="Path for the new, dual-relocated-only ISO copy (must differ from --source).")
    dual_reloc_cmd.add_argument("--overwrite", action="store_true", help="Replace --output if it already exists.")

    dark_content_cmd = sub.add_parser(
        "darkpokemon-content-relocation-test",
        help="DIAGNOSTIC ONLY (ADDENDUM 67): write real new DDPK entries (default 5, borrowing an existing "
             "DPKM entry's data -- no DPKM growth) into free padding slots across all three DarkPokemon "
             "copies, forcing the same real content-growth relocation as ADDENDUM 62/63, but WITHOUT touching "
             "DeckData_Story.bin at all (no team-slot writes, not linked to any trainer) -- isolates whether "
             "DarkPokemon-side growth+relocation alone (independent of Story.bin) is what breaks.",
    )
    dark_content_cmd.add_argument("--source", required=True, help="Path to your own, legally-owned source ISO/CISO.")
    dark_content_cmd.add_argument("--output", required=True, help="Path for the new, darkpokemon-content-relocation-tested ISO copy (must differ from --source).")
    dark_content_cmd.add_argument("--num-new-entries", type=int, default=5, help="How many new DDPK entries to write (default 5 -- the exact minimal count that crosses the relocation threshold, per ADDENDUM 63).")
    dark_content_cmd.add_argument("--borrow-dpkm-index", type=int, default=1, help="An existing, real (non-empty) DPKM index to use as every new DDPK entry's story_deck_index (default 1). Never grows or touches DeckData_Story.bin.")
    dark_content_cmd.add_argument("--overwrite", action="store_true", help="Replace --output if it already exists.")

    inspect_cmd = sub.add_parser(
        "inspect-relocation",
        help="READ-ONLY DIAGNOSTIC (ADDENDUM 64): never writes anything -- run this directly against an "
             "already-patched ISO/CISO that's showing a real-hardware problem (e.g. the splash-screen freeze). "
             "Reports deck_archive.fsys/common.fsys's current disc position, CISO block-map facts, whether "
             "either relocated container overlaps any other real file on the disc, and independently re-"
             "verifies both containers still parse/decode cleanly straight from this read.",
    )
    inspect_cmd.add_argument("--iso", required=True, help="Path to the ISO/CISO to inspect (never modified).")
    inspect_cmd.add_argument("--check-file", default=None, help="NEW (2026-09-09): also report this exact FST filename's current offset/length/first bytes, and scan every FST entry's decoded name for anything non-printable/garbage (a corrupted-name symptom the overlap check alone can miss).")

    extract_moves_cmd = sub.add_parser(
        "extract-story-trainer-moves",
        help="READ-ONLY (2026-09-09, trainer-26-Treecko-Pound freeze investigation): dumps every real "
             "trainer's ordinary (DPKM) team roster INCLUDING each member's real, currently-equipped moves, "
             "read directly off your ISO/CISO -- see extract_story_trainer_moves()'s own docstring for why "
             "this is needed. Safe to run against your original, unpatched source ISO.",
    )
    extract_moves_cmd.add_argument("--source", required=True, help="Path to your own, legally-owned source ISO/CISO (never modified).")
    extract_moves_cmd.add_argument("--output", required=True, help="Path for the output JSON file.")

    dump_dpkm_cmd = sub.add_parser(
        "dump-dpkm",
        help="READ-ONLY (2026-09-09): dumps the FULL dpkm_full() record (every field, not just species/level/"
             "moves) for one or more specific dpkm_index values, read directly off any ISO/CISO. Never writes "
             "anything.",
    )
    dump_dpkm_cmd.add_argument("--iso", required=True, help="Path to the ISO/CISO to read (never modified).")
    dump_dpkm_cmd.add_argument("--indices", required=True, help="Comma-separated dpkm_index values, e.g. 912,913,914.")

    args = parser.parse_args(argv)
    if args.command == "apply":
        summary = apply_patch(Path(args.source), Path(args.output), Path(args.seed), overwrite=args.overwrite)
        result_json = getattr(args, "result_json", None)
        if result_json:
            # Written only on success -- a raised exception never reaches here, which is how the caller tells
            # success from failure.
            with open(result_json, "w", encoding="utf-8") as f:
                json.dump(summary, f)
    elif args.command == "relocation-test":
        apply_relocation_isolation_test(Path(args.source), Path(args.output), overwrite=args.overwrite)
    elif args.command == "team-padding-test":
        apply_team_padding_isolation_test(
            Path(args.source), Path(args.output), args.trainer_index, args.dpkm_index, args.species, args.level,
            overwrite=args.overwrite,
        )
    elif args.command == "growth-checkpoint-test":
        apply_growth_checkpoint_test(
            Path(args.source), Path(args.output), args.reference_trainer_index, overwrite=args.overwrite
        )
    elif args.command == "team-padding-borrow-test":
        apply_team_padding_borrow_test(
            Path(args.source), Path(args.output), args.trainer_index,
            borrow_dpkm_index=args.borrow_dpkm_index, overwrite=args.overwrite,
        )
    elif args.command == "team-padding-new-species-test":
        moves = [int(x) for x in args.moves.split(",")] if args.moves else None
        apply_team_padding_new_species_test(
            Path(args.source), Path(args.output), args.trainer_index, args.species, args.level,
            moves=moves, overwrite=args.overwrite,
        )
    elif args.command == "team-padding-shadow-test":
        apply_team_padding_shadow_test(
            Path(args.source), Path(args.output), args.trainer_index, args.species, args.level,
            overwrite=args.overwrite,
        )
    elif args.command == "team-padding-shadow-borrow-test":
        apply_team_padding_shadow_borrow_test(
            Path(args.source), Path(args.output), args.trainer_index,
            borrow_dpkm_index=args.borrow_dpkm_index, shadow_level=args.shadow_level,
            overwrite=args.overwrite,
        )
    elif args.command == "team-padding-shadow-reuse-test":
        apply_team_padding_shadow_reuse_test(
            Path(args.source), Path(args.output), args.trainer_index, args.reuse_ddpk_index,
            overwrite=args.overwrite,
        )
    elif args.command == "team-padding-shadow-overwrite-test":
        apply_team_padding_shadow_overwrite_test(
            Path(args.source), Path(args.output), args.trainer_index, args.target_ddpk_index,
            overwrite=args.overwrite,
        )
    elif args.command == "team-padding-shadow-common-test":
        apply_team_padding_shadow_common_test(
            Path(args.source), Path(args.output), args.trainer_index, args.target_ddpk_index,
            overwrite=args.overwrite,
        )
    elif args.command == "team-padding-shadow-new-slot-test":
        apply_team_padding_shadow_new_slot_test(
            Path(args.source), Path(args.output), args.trainer_index, args.target_ddpk_index,
            story_deck_index=args.story_deck_index, shadow_level=args.shadow_level,
            overwrite=args.overwrite,
        )
    elif args.command == "team-padding-shadow-full-team-test":
        with open(args.new_pokemon_json, "r", encoding="utf-8") as f:
            new_pokemon = json.load(f)
        apply_team_padding_shadow_full_team_test(
            Path(args.source), Path(args.output), args.trainer_index, new_pokemon,
            overwrite=args.overwrite,
        )
    elif args.command == "team-padding-shadow-multi-trainer-test":
        with open(args.trainer_plans_json, "r", encoding="utf-8") as f:
            trainer_plans = json.load(f)
        apply_team_padding_shadow_multi_trainer_test(
            Path(args.source), Path(args.output), trainer_plans,
            overwrite=args.overwrite,
        )
    elif args.command == "enhanced-difficulty-test":
        apply_enhanced_difficulty_test(Path(args.source), Path(args.output), overwrite=args.overwrite)
    elif args.command == "ball-behavior-flag-probe":
        write_ball_behavior_flag_probe(
            Path(args.source), Path(args.output),
            item_ids=[int(x, 0) for x in str(args.item_ids).split(",") if x.strip()],
            value=(int(str(args.value), 0) if args.value is not None else None),
            overwrite=args.overwrite,
        )
    elif args.command == "common-fsys-relocation-test":
        apply_common_fsys_relocation_isolation_test(Path(args.source), Path(args.output), overwrite=args.overwrite)
    elif args.command == "dual-relocation-test":
        apply_dual_relocation_isolation_test(Path(args.source), Path(args.output), overwrite=args.overwrite)
    elif args.command == "darkpokemon-content-relocation-test":
        apply_darkpokemon_content_relocation_test(
            Path(args.source), Path(args.output), num_new_entries=args.num_new_entries,
            borrow_dpkm_index=args.borrow_dpkm_index, overwrite=args.overwrite,
        )
    elif args.command == "inspect-relocation":
        report = inspect_relocation(Path(args.iso), check_file=args.check_file)
        print(json.dumps(report, indent=2))
    elif args.command == "extract-story-trainer-moves":
        trainers = extract_story_trainer_moves(Path(args.source))
        with open(args.output, "w") as f:
            json.dump(trainers, f, indent=1)
        print(f"wrote {len(trainers)} trainers to {args.output}")
    elif args.command == "dump-dpkm":
        indices = [int(x) for x in args.indices.split(",")]
        reader = open_reader(Path(args.iso))
        try:
            fst = parse_fst(reader)
            deck_off, deck_len, _ = find_by_basename(fst, "deck_archive.fsys")
            deck_bytes = reader.read(deck_off, deck_len)
            deck_entries = parse_fsys(deck_bytes)
            story = deck_entries["DeckData_Story.bin"]
            story_raw = deck_bytes[story["data_off"]: story["data_off"] + 0x10 + story["comp_size"]]
        finally:
            reader.close()
        story_decompressed = deck_format.lzss_decode(story_raw)
        deck = deck_format.DeckFile(story_decompressed)
        out = {str(i): deck.dpkm_full(i) for i in indices}
        print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
