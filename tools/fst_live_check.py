"""Live in-memory FST check for the `DVDOpen(): file '...' was not found under /.` softlock class.

DVDOpen resolves names against the FST copy the apploader put in RAM at boot (address/size at
0x80000038/0x8000003C), so a lookup by a correct name can only fail if that copy was damaged at runtime.
Measured 2026-09-11 on the player's frozen session: 8 damaged bytes out of 88,408, all 2565 entries
otherwise byte-identical to the disc -- four halfword writes at irregular spacing (296, 40, 50 bytes apart)
inside one 0x184-byte window of the string table, each landing mid-name and leaving a NUL that truncates it:

    0x817f9993  "wzx_hataku_damage.fsys"   byte 12  "am" -> 00 01   (Pound / confusion self-hit)
    0x817f9abb  "wzx_hiduki_look_d.fsys"   byte 18
    0x817f9ae3  "wzx_hiduki_look_f.fsys"   byte 12  (purification)
    0x817f9b15  "wzx_hikkaku_attack.fsys"  byte 15  (Scratch)

Read-only unless --repair, and safe to run while the game sits in the DVDOpen retry loop: the loop retries
forever, so a repair resumes play instead of needing a reset.

USAGE (single line, from the unzipped source's tools folder, exactly like iso_patcher.py):
  py fst_live_check.py --iso "Pokemon XD - patched.ciso" --out fst_live_report.txt
(add `--file name.fsys ...` to check other names; the diff itself covers the WHOLE FST regardless)
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import time
from pathlib import Path

MEM1_START = 0x80000000
MEM1_END = 0x81800000
FST_ADDR_PTR = 0x80000038
FST_SIZE_PTR = 0x8000003C
ARENA_LO_PTR = 0x80000030
ARENA_HI_PTR = 0x80000034
FST_ENTRY_SIZE = 12
MAGICS = (b"FSYS", b"LZSS", b"DECK", b"DTNR", b"DPKM", b"DTAI", b"DSTR", b"DDPK")


def _read_ram(address: int, length: int) -> bytes:
    import dolphin_memory_engine as dme  # imported lazily so --help works without Dolphin/the package installed

    return dme.read_bytes(address, length)


def _write_ram(address: int, data: bytes) -> None:
    import dolphin_memory_engine as dme

    dme.write_bytes(address, data)


def repair(fst_addr: int, ram_fst_size: int, disc_fst: bytes, ranges: list[tuple[int, int]]) -> list[dict]:
    """Write the disc's own bytes back over each damaged range in the in-RAM FST. Only writes bytes copied
    from the ISO the game is running, only where RAM already disagreed, and only inside the FST; each range
    is verified by reading it back."""
    results = []
    for s, e in ranges:
        if s < 0 or e > ram_fst_size or e <= s:
            results.append({"start": s, "end": e, "repaired": False, "reason": "outside the in-RAM FST"})
            continue
        want = disc_fst[s:e]
        _write_ram(fst_addr + s, want)
        got = _read_ram(fst_addr + s, e - s)
        results.append({"start": s, "end": e, "address": fst_addr + s, "wrote": want.hex(),
                        "repaired": got == want, "read_back": got.hex()})
    return results


def _hook() -> None:
    import dolphin_memory_engine as dme

    try:
        dme.un_hook()
    except Exception:
        pass
    dme.hook()
    if not dme.is_hooked():
        raise SystemExit("could not hook Dolphin -- is the game running (the retry loop counts as running)?")


def _iso_patcher():
    """Script-vs-package import fallback, so this runs straight out of the unzipped source."""
    try:
        import iso_patcher  # type: ignore
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import iso_patcher  # type: ignore
    return iso_patcher


def read_disc_fst(iso_path: Path) -> tuple[int, int, bytes]:
    iso_patcher = _iso_patcher()

    reader = iso_patcher.open_reader(iso_path)
    try:
        boot = reader.read(0, iso_patcher.BOOT_HEADER_READ_LEN)
        fst_offset = struct.unpack_from(">I", boot, iso_patcher.FST_OFFSET_FIELD)[0]
        fst_size = struct.unpack_from(">I", boot, iso_patcher.FST_SIZE_FIELD)[0]
        return fst_offset, fst_size, reader.read(fst_offset, fst_size)
    finally:
        reader.close()


def fst_entries(fst: bytes) -> list[dict]:
    """Every entry as {index, is_dir, name_off, f2, f3, name} (name best-effort; never raises on garbage)."""
    if len(fst) < FST_ENTRY_SIZE:
        return []
    count = struct.unpack_from(">I", fst, 8)[0]
    count = min(count, len(fst) // FST_ENTRY_SIZE)
    strings_off = count * FST_ENTRY_SIZE
    out = []
    for i in range(count):
        base = i * FST_ENTRY_SIZE
        flag = fst[base]
        name_off = int.from_bytes(fst[base + 1:base + 4], "big")
        f2, f3 = struct.unpack_from(">II", fst, base + 4)
        start = strings_off + name_off
        end = fst.find(b"\x00", start) if 0 <= start < len(fst) else -1
        name = fst[start:end].decode("ascii", errors="replace") if end != -1 else "<unreadable>"
        out.append({"index": i, "is_dir": flag != 0, "name_off": name_off, "f2": f2, "f3": f3, "name": name,
                    "name_span": (start, end + 1) if end != -1 else None})
    return out


def sdk_lookup(fst: bytes, filename: str) -> dict:
    """Port of the SDK's DVDConvertPathToEntrynum for a root-level file: walks the root directory's entries the
    way OSLink's sibling does (files: i += 1; directories: i = entry.f3), comparing names case-insensitively.
    Returns {found, entry, steps, stopped_reason} -- with the exact index the walk died at when it fails."""
    entries = fst_entries(fst)
    if not entries:
        return {"found": False, "stopped_reason": "FST too short to hold a root entry"}
    root_count = struct.unpack_from(">I", fst, 8)[0]
    want = filename.lower()
    i, steps, visited = 1, 0, set()
    while i < root_count:
        if i in visited or i >= len(entries):
            return {"found": False, "entry": i, "steps": steps,
                    "stopped_reason": f"walk left the table (index {i}, root_count {root_count}, parsed {len(entries)})"}
        visited.add(i)
        e = entries[i]
        steps += 1
        if e["name"].lower() == want:
            return {"found": True, "entry": i, "steps": steps, "name": e["name"], "offset": e["f2"], "length": e["f3"]}
        if e["is_dir"]:
            if e["f3"] <= i:
                return {"found": False, "entry": i, "steps": steps,
                        "stopped_reason": f"directory entry {i} ({e['name']!r}) has next-index {e['f3']} <= itself"}
            i = e["f3"]
        else:
            i += 1
    return {"found": False, "entry": i, "steps": steps,
            "stopped_reason": f"walked the whole root directory ({steps} entries) without a name match"}


def diff_ranges(a: bytes, b: bytes, merge_gap: int = 16) -> list[tuple[int, int]]:
    n = min(len(a), len(b))
    ranges: list[list[int]] = []
    i = 0
    while i < n:
        if a[i] != b[i]:
            j = i
            while j < n and a[j] != b[j]:
                j += 1
            if ranges and i - ranges[-1][1] <= merge_gap:
                ranges[-1][1] = j
            else:
                ranges.append([i, j])
            i = j
        else:
            i += 1
    if len(a) != len(b):
        ranges.append([n, max(len(a), len(b))])
    return [(s, e) for s, e in ranges]


def describe_range(disc_entries: list[dict], strings_off: int, start: int, end: int,
                   disc_fst: bytes = b"", ram_fst: bytes = b"", fst_addr: int = 0) -> dict:
    hit_entries = [e for e in disc_entries if e["index"] * FST_ENTRY_SIZE < end and (e["index"] + 1) * FST_ENTRY_SIZE > start]
    hit_names = [e for e in disc_entries if e["name_span"] and e["name_span"][0] < end and e["name_span"][1] > start]
    d = {
        "start": start, "end": end, "length": end - start,
        "address": fst_addr + start if fst_addr else None,
        "region": "entry table" if start < strings_off else "string table",
        "entries_damaged": [{"index": e["index"], "name": e["name"]} for e in hit_entries[:40]],
        "names_damaged": list(dict.fromkeys(e["name"] for e in hit_names))[:80],
        "names_damaged_count": len({e["name"] for e in hit_names}),
    }
    if disc_fst and ram_fst:
        # a 2-byte difference is a halfword store, 4 a word store; the value written identifies the writer
        d["disc_bytes"] = disc_fst[start:end].hex()
        d["ram_bytes"] = ram_fst[start:end].hex()
        d["ram_value_be"] = int.from_bytes(ram_fst[start:end], "big") if end - start <= 8 else None
        d["disc_value_be"] = int.from_bytes(disc_fst[start:end], "big") if end - start <= 8 else None
        if hit_names:
            e = hit_names[0]
            ns, ne = e["name_span"]
            d["name"] = e["name"]
            d["name_relative_offset"] = start - ns
            d["name_in_ram"] = ram_fst[ns:ne - 1].decode("ascii", errors="replace")
    return d


def scan_for_pointers(read_ram, low: int, high: int, exclude: tuple[int, ...] = ()) -> list[tuple[int, int]]:
    """Scan MEM1 for 4-byte words whose value lands inside [low, high) -- whatever damaged the region very
    likely still holds the address. Returns [(address_of_word, value)], excluding the known OS globals."""
    hits: list[tuple[int, int]] = []
    chunk = 0x100000
    for base in range(MEM1_START, MEM1_END, chunk):
        size = min(chunk, MEM1_END - base)
        try:
            mem = read_ram(base, size)
        except Exception:  # pragma: no cover -- some MEM1 windows can refuse a read, see ram_client's notes
            continue
        for off in range(0, len(mem) - 3, 4):
            value = int.from_bytes(mem[off:off + 4], "big")
            if low <= value < high:
                addr = base + off
                if addr not in exclude:
                    hits.append((addr, value))
            if len(hits) >= 4000:
                return hits
    return hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--iso", required=True, type=Path, help="the PATCHED ISO/CISO the game is running")
    ap.add_argument("--file", nargs="+", default=["wzx_hataku_damage.fsys", "wzx_hiduki_look_f.fsys", "wzx_hikkaku_attack.fsys"],
                    help="file name(s) from the DVDOpen warning (default: every name seen so far)")
    ap.add_argument("--out", type=Path, default=Path("fst_live_report.txt"))
    ap.add_argument("--below", type=lambda s: int(s, 0), default=0x8000, help="bytes of RAM to inspect below the FST")
    ap.add_argument("--repair", action="store_true",
                    help="ADDENDUM 130: write the disc's own bytes back over every damaged range in the in-RAM "
                         "FST. Unsticks a live DVDOpen retry-loop freeze on the spot (the game retries forever, "
                         "so the next retry succeeds) and is safe -- it only ever restores bytes the running ISO "
                         "itself says belong there. Combine with --watch for a live watchdog.")
    ap.add_argument("--scan-pointers", action="store_true",
                    help="also scan all 24MB of MEM1 for words pointing into the damaged region (slow, ~seconds)")
    ap.add_argument("--watch", nargs="?", type=float, const=1.0, default=None, metavar="SECONDS",
                    help="ADDENDUM 130: after the first report, keep re-reading the FST every SECONDS (default 1) "
                         "and print the moment a NEW difference appears -- play normally and it will name the "
                         "exact action that damages the FST. Ctrl+C to stop.")
    args = ap.parse_args(argv)

    fst_offset, fst_size, disc_fst = read_disc_fst(args.iso)
    _hook()
    fst_addr = struct.unpack(">I", _read_ram(FST_ADDR_PTR, 4))[0]
    ram_fst_size = struct.unpack(">I", _read_ram(FST_SIZE_PTR, 4))[0]
    arena_lo = struct.unpack(">I", _read_ram(ARENA_LO_PTR, 4))[0]
    arena_hi = struct.unpack(">I", _read_ram(ARENA_HI_PTR, 4))[0]
    lines = [
        "Pokemon XD Archipelago -- live in-memory FST check (ADDENDUM 129)",
        "=" * 66,
        f"ISO: {args.iso}",
        f"disc FST: offset {fst_offset} size {fst_size}",
        f"RAM  FST: address {fst_addr:#010x} size {ram_fst_size} (0x80000038/3C); arena lo {arena_lo:#010x} hi {arena_hi:#010x}",
    ]
    if not (MEM1_START <= fst_addr < MEM1_END) or ram_fst_size == 0 or ram_fst_size > 0x400000:
        lines.append("!! the FST pointer/size in low memory look wrong -- the game may not be booted, or low memory is damaged")
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines))
        return 2
    ram_fst = _read_ram(fst_addr, ram_fst_size)
    lines.append(f"RAM FST size {'==' if ram_fst_size == fst_size else '!='} disc FST size")

    disc_entries = fst_entries(disc_fst)
    strings_off = struct.unpack_from(">I", disc_fst, 8)[0] * FST_ENTRY_SIZE
    ranges = diff_ranges(disc_fst, ram_fst)
    lines.append(f"differing byte ranges (RAM vs disc): {len(ranges)}")
    described = [describe_range(disc_entries, strings_off, s, e, disc_fst, ram_fst, fst_addr) for s, e in ranges]
    for d in described[:50]:
        lines.append(
            f"  [{d['start']:#x}, {d['end']:#x}) {d['length']} bytes at {d['address']:#010x} in the {d['region']}: "
            f"disc {d.get('disc_bytes')} -> RAM {d.get('ram_bytes')}"
            + (f" (halfword {d['ram_value_be']:#06x})" if d["length"] == 2 else "")
        )
        if d.get("name") is not None:
            lines.append(
                f"    name {d['name']!r} byte {d['name_relative_offset']}; the game now reads it as {d['name_in_ram']!r}"
            )
        if d["entries_damaged"]:
            lines.append("    entries: " + ", ".join(f"#{e['index']} {e['name']}" for e in d["entries_damaged"][:12]))
    if len(described) > 1:
        # spacing is the fingerprint: a regular stride means an array walk, an irregular one per-object writes
        lines.append("  gaps between successive writes: " + ", ".join(
            f"{described[i + 1]['start'] - described[i]['start']}" for i in range(len(described) - 1)))
    for d in described[:50]:
        s, e = d["start"], d["end"]
        lo, hi = max(0, s - 48), min(len(ram_fst), e + 48)
        lines += ["", f"difference at {fst_addr + s:#010x} (FST-relative {s:#x}), context [{lo:#x}, {hi:#x}):"]
        for off in range(lo, hi, 32):
            lines.append(f"  RAM  {off:06X}: {ram_fst[off:off + 32].hex()}")
            lines.append(f"  disc {off:06X}: {disc_fst[off:off + 32].hex()}")

    # Always look up every name the diff itself says is damaged, on top of whatever --file asked for.
    for d in described:
        for n in d["names_damaged"]:
            if n not in args.file:
                args.file.append(n)
    lookups = {}
    for name in args.file:
        lines += ["", f"SDK-style lookup of {name!r}:"]
        for label, blob in (("disc", disc_fst), ("RAM", ram_fst)):
            lookups[f"{label}:{name}"] = sdk_lookup(blob, name)
            lines.append(f"  {label}: {lookups[f'{label}:{name}']}")

    # What sits right below the FST in RAM -- the arena-hi neighbour, the likeliest source of an overrun.
    below_start = max(MEM1_START, fst_addr - args.below)
    below = _read_ram(below_start, fst_addr - below_start)
    found = []
    for magic in MAGICS:
        pos = below.find(magic)
        while pos != -1 and len(found) < 64:
            found.append((below_start + pos, magic.decode()))
            pos = below.find(magic, pos + 1)
    found.sort()
    nonzero_tail = len(below.rstrip(b"\x00"))
    lines += [
        "",
        f"RAM just below the FST ({below_start:#010x}..{fst_addr:#010x}): last non-zero byte at "
        f"{below_start + nonzero_tail:#010x} ({fst_addr - (below_start + nonzero_tail)} zero bytes before the FST)",
        "  magics found: " + (", ".join(f"{m}@{a:#010x}" for a, m in found[:40]) or "none"),
        f"  last 64 bytes before the FST: {below[-64:].hex()}",
    ]
    repairs: list[dict] = []
    if args.repair and ranges:
        repairs = repair(fst_addr, ram_fst_size, disc_fst, ranges)
        ok = sum(1 for r in repairs if r["repaired"])
        lines += ["", f"REPAIR: restored {ok}/{len(repairs)} damaged range(s) from the disc's own FST:"]
        for r in repairs:
            lines.append(f"  {r.get('address', 0):#010x}: wrote {r.get('wrote')} -> "
                         + ("verified" if r["repaired"] else f"FAILED ({r.get('reason') or r.get('read_back')})"))
        if ok:
            lines.append("  if the game was stuck in the DVDOpen retry loop, it should resume within a second.")
        ram_fst = _read_ram(fst_addr, ram_fst_size)
        ranges = diff_ranges(disc_fst, ram_fst)
        lines.append(f"  differing ranges after repair: {len(ranges)}")

    pointer_hits: list[tuple[int, int]] = []
    if args.scan_pointers and ranges:
        low = fst_addr + min(r[0] for r in ranges) - 0x200
        high = fst_addr + max(r[1] for r in ranges) + 0x200
        lines += ["", f"MEM1 words pointing into {low:#010x}..{high:#010x} (who still holds the address?):"]
        pointer_hits = scan_for_pointers(_read_ram, low, high, exclude=(FST_ADDR_PTR,))
        for addr, value in pointer_hits[:60]:
            lines.append(f"  {addr:#010x} -> {value:#010x}")
        if not pointer_hits:
            lines.append("  none -- nothing in memory currently holds a pointer into the damaged window")

    report = {
        "iso": str(args.iso), "fst_addr": fst_addr, "ram_fst_size": ram_fst_size, "disc_fst_size": fst_size,
        "arena_lo": arena_lo, "arena_hi": arena_hi, "diff_ranges": described,
        "lookups": lookups,
        "below_magics": found,
        "pointer_hits": pointer_hits[:200],
        "repairs": repairs,
    }
    args.out.write_text("\n".join(lines) + "\n\nJSON:\n" + json.dumps(report, indent=1) + "\n", encoding="utf-8")
    dump_path = args.out.with_suffix(".ram_fst.bin")
    dump_path.write_bytes(ram_fst)
    lines.append(f"\nfull report: {args.out}; raw RAM FST dump: {dump_path}")
    print("\n".join(lines))

    if args.watch is not None:
        print(f"\nwatching the FST every {args.watch}s -- play normally; every NEW difference is printed with "
              f"the time it appeared. Ctrl+C to stop.")
        # `known` only suppresses re-printing. Seeding it with the startup ranges meant a range damaged AGAIN
        # later was skipped forever, so with --repair it starts empty: repair every difference, every time.
        known: set = set() if args.repair else {(s, e) for s, e in ranges}
        baseline = ram_fst
        try:
            while True:
                time.sleep(args.watch)
                try:
                    now = _read_ram(fst_addr, ram_fst_size)
                except Exception as exc:
                    print(f"  [{time.strftime('%H:%M:%S')}] read failed ({exc}) -- is Dolphin still running?")
                    continue
                current_ranges = diff_ranges(disc_fst, now)
                fresh = [(s, e) for s, e in current_ranges if (s, e) not in known]
                if args.repair and current_ranges and not fresh:
                    # with --repair `known` is empty so this shouldn't fire; repair anyway rather than stay stuck
                    fresh = current_ranges
                for s, e in fresh:
                    known.add((s, e))
                    d = describe_range(disc_entries, strings_off, s, e, disc_fst, now, fst_addr)
                    fixed = ""
                    if args.repair:
                        r = repair(fst_addr, ram_fst_size, disc_fst, [(s, e)])[0]
                        fixed = " -- REPAIRED" if r["repaired"] else " -- REPAIR FAILED"
                        known.discard((s, e))
                    print(f"  [{time.strftime('%H:%M:%S')}] NEW damage at {fst_addr + s:#010x} "
                          f"({e - s} bytes, disc {d['disc_bytes']} -> RAM {d['ram_bytes']}) "
                          f"in {d.get('name')!r} byte {d.get('name_relative_offset')}{fixed}")
                    with args.out.open("a", encoding="utf-8") as fh:
                        fh.write(f"WATCH {time.strftime('%H:%M:%S')} {fst_addr + s:#010x} {e - s}B "
                                 f"{d['disc_bytes']}->{d['ram_bytes']} {d.get('name')!r}{fixed}\n")
                baseline = now
        except KeyboardInterrupt:
            print("  stopped.")
    return 0 if not ranges else 1


if __name__ == "__main__":
    sys.exit(main())
