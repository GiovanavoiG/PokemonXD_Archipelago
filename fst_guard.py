"""In-client watchdog that keeps the in-RAM GameCube FST intact.

Something in the game overwrites the copy of the File String Table the apploader publishes into RAM at boot.
`DVDConvertPathToEntrynum` resolves every `DVDOpen` against that copy and `_fsysForegroundTask` retries a
failed open forever, so one damaged byte inside a file name is a permanent softlock the first time the game
needs that file (Pound/Scratch animations, purification animations). Writing the correct bytes back over the
damaged ranges unsticks a live freeze on the spot; this is that repair, run automatically by the client.

This only ever touches Dolphin's emulated RAM -- it never opens, reads or writes the ISO. Every write is
bounded: only inside `[fst_addr, fst_addr + fst_size)` as published by the apploader, only at offsets that
already disagree with a validated baseline, only bytes copied verbatim out of that baseline, and never when
the damage is large enough that the region is evidently no longer an FST (reboot/unload) -- then the baseline
is dropped and re-taken.

`FstGuard` takes its `read`/`write` callables by injection, so the module-level logic is unit-tested without
`dolphin_memory_engine`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

# The apploader publishes the in-RAM FST's address and size here (GameCube OS globals, os/OSBootInfo /
# __OSFstStart). Both confirmed live.
FST_ADDR_PTR = 0x80000038
FST_SIZE_PTR = 0x8000003C
ARENA_HI_PTR = 0x80000034

MEM1_START = 0x80000000
MEM1_END = 0x81800000

FST_ENTRY_SIZE = 12

# A real XD FST is ~86 KB. Anything outside this band is not an FST and we refuse to work with it. The
# lower bound is deliberately loose -- `validate_fst` is the real gate, and it is far stricter than a size.
MIN_FST_SIZE = 0x40
MAX_FST_SIZE = 0x400000

# Above this many damaged bytes we assume the region stopped being the FST at all (game reset, disc
# swapped, apploader re-running) rather than "the FST got scribbled on", and we re-baseline instead of
# writing 80 KB back into a booting game.
MAX_REPAIRABLE_BYTES = 8192


class FstStatus:
    """Stable strings for logging / the `!fst` command."""
    NO_POINTERS = "no FST published in RAM yet"
    UNREADABLE = "could not read the FST out of RAM"
    INVALID = "the FST in RAM is not structurally valid yet"
    ARMED = "armed"
    ARMED_FROM_DISC = "armed from the ISO's own file table"
    REBASELINED = "re-baselined (new boot)"


def read_u32(read: Callable[[int, int], bytes], address: int) -> int:
    return int.from_bytes(read(address, 4), "big")


def validate_fst(blob: bytes) -> Optional[str]:
    """Return None when `blob` is a structurally sound GameCube FST, else a short reason why it is not.

    Deliberately strict: a corrupted FST -- an embedded NUL in a name, a splatted audio buffer, boot-time
    zeros -- must never become the baseline we repair towards.
    """
    if len(blob) < FST_ENTRY_SIZE:
        return "shorter than one entry"
    if blob[0] != 1 or blob[1:4] != b"\x00\x00\x00":
        return "root entry is not a directory with name offset 0"
    if int.from_bytes(blob[4:8], "big") != 0:
        return "root entry's parent field is not 0"
    count = int.from_bytes(blob[8:12], "big")
    if count < 2 or count > 0x20000:
        return f"implausible entry count {count}"
    strings_off = count * FST_ENTRY_SIZE
    if strings_off >= len(blob):
        return f"entry table ({strings_off}) does not fit in {len(blob)} bytes"
    if blob[-1] != 0:
        return "string table is not NUL-terminated"
    strings_len = len(blob) - strings_off
    covered = bytearray(strings_len)
    covered[0] = 1  # the root entry's empty name is the NUL at string-table offset 0
    for index in range(1, count):
        base = index * FST_ENTRY_SIZE
        flag = blob[base]
        if flag not in (0, 1):
            return f"entry {index} has flag {flag}"
        name_off = int.from_bytes(blob[base + 1:base + 4], "big")
        if name_off >= strings_len:
            return f"entry {index} name offset {name_off} is past the string table"
        end = blob.find(b"\x00", strings_off + name_off)
        if end < 0:
            return f"entry {index} name is not NUL-terminated"
        name = blob[strings_off + name_off:end]
        if not name or len(name) > 255:
            return f"entry {index} has a {len(name)}-byte name"
        for ch in name:
            if ch < 0x20 or ch > 0x7E:
                return f"entry {index} name contains a non-printable byte {ch:#04x}"
        if flag == 1:
            nxt = int.from_bytes(blob[base + 8:base + 12], "big")
            if nxt <= index or nxt > count:
                return f"directory entry {index} has next-index {nxt}"
        covered[name_off:end - strings_off + 1] = b"\x01" * (end - strings_off + 1 - name_off)
    # The live damage writes a NUL into a name, truncating it; the truncated name is still printable ASCII,
    # so the per-name checks cannot see it. What it leaves is an orphaned tail ("\x01age.fsys\x00") nothing
    # references. So every string-table byte no name claims must be zero -- that tolerates a real disc's
    # trailing alignment padding and catches every truncation.
    for i, claimed in enumerate(covered):
        if not claimed and blob[strings_off + i] != 0:
            return f"unreferenced non-zero byte {blob[strings_off + i]:#04x} in the string table at +{i}"
    return None


def diff_ranges(baseline: bytes, current: bytes) -> list[tuple[int, int]]:
    """Contiguous `[start, end)` byte ranges where `current` disagrees with `baseline`."""
    ranges: list[tuple[int, int]] = []
    n = min(len(baseline), len(current))
    start = -1
    for i in range(n):
        if baseline[i] != current[i]:
            if start < 0:
                start = i
        elif start >= 0:
            ranges.append((start, i))
            start = -1
    if start >= 0:
        ranges.append((start, n))
    if len(current) != len(baseline):
        ranges.append((n, max(len(baseline), len(current))))
    return ranges


def damaged_byte_count(ranges: list[tuple[int, int]]) -> int:
    return sum(e - s for s, e in ranges)


def entry_names(blob: bytes) -> list[tuple[int, int, str]]:
    """`(name_start_offset, name_end_offset, name)` for every entry, for reporting which file broke."""
    count = int.from_bytes(blob[8:12], "big")
    strings_off = count * FST_ENTRY_SIZE
    out: list[tuple[int, int, str]] = []
    for index in range(1, count):
        base = index * FST_ENTRY_SIZE
        name_off = strings_off + int.from_bytes(blob[base + 1:base + 4], "big")
        if name_off >= len(blob):
            continue
        end = blob.find(b"\x00", name_off)
        if end < 0:
            continue
        out.append((name_off, end, blob[name_off:end].decode("ascii", "replace")))
    return out


def names_in_range(blob: bytes, start: int, end: int) -> list[str]:
    """Which file names a damaged `[start, end)` range lands inside -- the names that stop resolving."""
    hits: list[str] = []
    for s, e, name in entry_names(blob):
        if start < e and end > s:
            hits.append(name)
    return list(dict.fromkeys(hits))


# Optional authoritative baseline: the FST on the patched ISO itself. The RAM snapshot has one blind spot --
# if the FST is already damaged the first time we look, `validate_fst` correctly refuses to snapshot it, and
# with no baseline the guard sits armed-less while the game spins in its DVDOpen retry loop. The ISO's FST is
# correct by construction and available before the game boots, so when an ISO path is known (Client.py's
# resolution order) it is preferred over any RAM snapshot and never discarded by re-baselining.

FST_OFFSET_FIELD = 0x0424  # GameCube boot header (boot.bin): FST offset and size on the disc
FST_SIZE_FIELD = 0x0428


def read_disc_fst(iso_path) -> bytes:
    """Read the FST out of a plain .iso or .ciso. Imports the already-real-ISO-validated reader from
    `tools/iso_patcher.py` lazily, so nothing here costs anything when no ISO path is configured."""
    from pathlib import Path

    from .tools import iso_patcher

    reader = _reader_factory(iso_patcher)(Path(iso_path))
    try:
        header = reader.read(0, 0x440)
        offset = int.from_bytes(header[FST_OFFSET_FIELD:FST_OFFSET_FIELD + 4], "big")
        size = int.from_bytes(header[FST_SIZE_FIELD:FST_SIZE_FIELD + 4], "big")
        if not (MIN_FST_SIZE <= size <= MAX_FST_SIZE):
            raise ValueError(f"{iso_path}: boot header declares an implausible FST size ({size})")
        return reader.read(offset, size)
    finally:
        close = getattr(reader, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def _reader_factory(iso_patcher):
    """`iso_patcher` has had several spellings for "reader for this path"; find whichever this copy exposes
    rather than hard-coding one that may move again."""
    for name in ("open_reader", "open_disc_reader", "disc_reader", "make_reader"):
        fn = getattr(iso_patcher, name, None)
        if callable(fn):
            return fn
    ciso = getattr(iso_patcher, "CisoReader", None)
    plain = getattr(iso_patcher, "PlainIsoReader", None) or getattr(iso_patcher, "IsoReader", None)

    def fallback(path: str):
        if ciso is not None and str(path).lower().endswith(".ciso"):
            return ciso(path)
        if plain is not None:
            return plain(path)
        raise RuntimeError("iso_patcher exposes no usable disc reader")

    return fallback


@dataclass
class FstGuard:
    """Per-boot baseline + repair loop. Inject `read`/`write`; call `poll()` on every client tick."""

    read: Callable[[int, int], bytes]
    write: Callable[[int, bytes], None]
    log: Callable[[str], None] = lambda message: None

    fst_addr: int = 0
    fst_size: int = 0
    baseline: Optional[bytes] = None
    # An ISO-derived baseline outranks any RAM snapshot: it is correct even when the FST in RAM was already
    # damaged before the client ever looked, which is the case the RAM snapshot alone cannot recover from.
    disc_baseline: Optional[bytes] = None
    disc_source: Optional[str] = None
    repairs: int = 0
    bytes_repaired: int = 0
    last_names: list[str] = field(default_factory=list)
    status: str = FstStatus.NO_POINTERS
    invalid_polls: int = 0
    _invalid_logged: bool = False
    # The "armed, snapshot taken" lines are startup narration, so they go to a sink Client.py gates behind
    # `!verbose`; `log` above carries every repair unconditionally, since a repair means the game was about to
    # softlock. Declared last so no positional FstGuard(...) construction shifts.
    log_verbose: Callable[[str], None] = lambda message: None

    def reset(self) -> None:
        """Forget this boot's RAM snapshot. The ISO baseline deliberately SURVIVES -- it describes the disc,
        not the boot, so it stays valid across resets, save loads and reconnects."""
        self.fst_addr = 0
        self.fst_size = 0
        self.baseline = None
        self.status = FstStatus.NO_POINTERS
        self.invalid_polls = 0
        self._invalid_logged = False

    def set_disc_baseline(self, blob: bytes, source: str) -> str:
        """Install the ISO's own FST as the authoritative baseline. Returns a human-readable status line.
        Refuses anything that does not validate, so a corrupt or wrong file can never become the source of
        truth we write back into the game."""
        reason = validate_fst(blob)
        if reason is not None:
            raise ValueError(f"{source}: this does not look like a valid GameCube FST ({reason})")
        self.disc_baseline = blob
        self.disc_source = source
        self.baseline = None  # re-derive on the next poll, now preferring the disc copy
        return (f"FST guard: using the file table from {source} as the repair reference "
                f"({len(blob)} bytes). Damage present before the client connects is now repairable too.")

    def _read_pointers(self) -> Optional[tuple[int, int]]:
        try:
            addr = read_u32(self.read, FST_ADDR_PTR)
            size = read_u32(self.read, FST_SIZE_PTR)
        except Exception:
            return None
        if not (MEM1_START < addr < MEM1_END):
            return None
        if not (MIN_FST_SIZE <= size <= MAX_FST_SIZE):
            return None
        if addr + size > MEM1_END:
            return None
        return addr, size

    def poll(self) -> dict:
        """One tick. Never raises: the client's item delivery must not be able to break because of this."""
        try:
            return self._poll()
        except Exception as exc:  # pragma: no cover -- defensive; the client keeps running regardless
            return {"status": f"FST guard error: {exc}", "repaired": 0}

    def _poll(self) -> dict:
        pointers = self._read_pointers()
        if pointers is None:
            if self.baseline is not None:
                self.reset()
            self.status = FstStatus.NO_POINTERS
            return {"status": self.status, "repaired": 0}
        addr, size = pointers
        if self.baseline is not None and (addr != self.fst_addr or size != self.fst_size):
            # New boot (or a different disc): the old baseline describes a layout that is gone.
            self.baseline = None
            self.status = FstStatus.REBASELINED
            self._invalid_logged = False
        self.fst_addr, self.fst_size = addr, size

        try:
            current = self.read(addr, size)
        except Exception:
            self.status = FstStatus.UNREADABLE
            return {"status": self.status, "repaired": 0}
        if len(current) != size:
            self.status = FstStatus.UNREADABLE
            return {"status": self.status, "repaired": 0}

        if self.baseline is None:
            # Preferred source: the ISO's own FST. It does not care whether the RAM copy is currently
            # intact, which is what makes damage-before-we-looked repairable.
            if self.disc_baseline is not None and len(self.disc_baseline) == size:
                self.baseline = self.disc_baseline
                self.status = FstStatus.ARMED_FROM_DISC
                self.log_verbose(f"FST guard armed from {self.disc_source}: {size} bytes at {addr:#010x}. Damage to "
                                 f"the in-RAM file table is repaired automatically (this only writes to "
                                 f"Dolphin's memory, never to your ISO).")
                return {"status": self.status, "repaired": 0, "armed": True, "from_disc": True}
            reason = validate_fst(current)
            if reason is not None:
                # Boot-time zeros or already-damaged: either way it must not become what we repair towards.
                # Normal for the first few ticks; if it persists, `!fstiso` is what unblocks it.
                self.status = f"{FstStatus.INVALID} ({reason})"
                self.invalid_polls += 1
                return {"status": self.status, "repaired": 0, "needs_disc_baseline": self.invalid_polls}
            self.invalid_polls = 0
            self.baseline = current
            self.status = FstStatus.ARMED
            self.log_verbose(f"FST guard armed: {size} bytes at {addr:#010x} validated and snapshotted. "
                             f"Damage to the in-RAM file table will be repaired automatically "
                             f"(this only writes to Dolphin's memory, never to your ISO).")
            return {"status": self.status, "repaired": 0, "armed": True}

        if current == self.baseline:
            return {"status": self.status, "repaired": 0}

        ranges = diff_ranges(self.baseline, current)
        total = damaged_byte_count(ranges)
        if total > MAX_REPAIRABLE_BYTES:
            # The region is no longer the FST we are comparing against (mid-reboot, disc unloaded, apploader
            # re-running). Wait it out rather than writing 86 KB into a game that is busy loading. A disc
            # baseline is kept -- it describes the ISO, not this boot.
            if self.disc_baseline is None:
                self.baseline = None
            self.status = FstStatus.REBASELINED
            return {"status": self.status, "repaired": 0, "rebaselined": True, "damaged_bytes": total}

        names: list[str] = []
        repaired_bytes = 0
        failed: list[tuple[int, int]] = []
        for start, end in ranges:
            if start < 0 or end > size or end <= start:
                failed.append((start, end))
                continue
            want = self.baseline[start:end]
            self.write(addr + start, want)
            try:
                got = self.read(addr + start, end - start)
            except Exception:
                got = b""
            if got == want:
                repaired_bytes += end - start
            else:
                failed.append((start, end))
            names.extend(names_in_range(self.baseline, start, end))

        names = list(dict.fromkeys(names))
        self.last_names = names
        self.repairs += 1
        self.bytes_repaired += repaired_bytes
        shown = ", ".join(names[:4]) + (f" (+{len(names) - 4} more)" if len(names) > 4 else "")
        if failed:
            self.log(f"FST guard: repaired {repaired_bytes} of {total} damaged bytes in the in-RAM file "
                     f"table ({len(failed)} range(s) could not be written back). Affected files: "
                     f"{shown or 'none (entry table)'}.")
        else:
            self.log(f"FST guard: repaired {total} damaged byte(s) in the in-RAM file table"
                     + (f" -- restored {shown}." if names else " (entry table)."))
        return {"status": self.status, "repaired": repaired_bytes, "damaged_bytes": total,
                "ranges": ranges, "names": names, "failed": failed}

    def describe(self) -> str:
        if self.baseline is None:
            extra = ""
            if self.disc_baseline is None and self.invalid_polls > 2:
                extra = (" The file table in RAM has not looked intact yet, so there is nothing to repair "
                         "towards -- point the client at your patched ISO with `!fstiso <path>` and it can "
                         "repair it from the disc instead.")
            return f"FST guard: {self.status}.{extra}"
        source = self.disc_source if self.baseline is self.disc_baseline else "a validated RAM snapshot"
        return (f"FST guard: armed on {self.fst_size} bytes at {self.fst_addr:#010x} (reference: {source}); "
                f"{self.repairs} repair pass(es), {self.bytes_repaired} byte(s) restored"
                + (f"; last affected: {', '.join(self.last_names[:4])}" if self.last_names else "")
                + ".")
