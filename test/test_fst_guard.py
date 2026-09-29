"""FST guard coverage -- the in-RAM GameCube file-table watchdog and its offline diagnostic tool.

This file consolidates three former test modules:

* ``test_addendum_131_fst_guard.py`` -- unit coverage for ``fst_guard.py``, the in-client watchdog that
  repairs the in-RAM GameCube FST. Everything here runs against a fake 24 MB RAM dict; no Dolphin, no ISO.
* ``test_addendum_133_fst_guard_disc_baseline.py`` -- the blind spot that let a Dugtrio's Scratch softlock
  through: damage that is already present the first time the watchdog looks. A RAM snapshot can never be
  taken from a damaged FST (by design), so without a second source there is nothing to repair towards.
  These cover the ISO-derived baseline that closes it, plus graceful degradation without
  ``dolphin_memory_engine``.
* ``test_addendum_129_fst_live_check.py`` -- the pure parts of ``tools/fst_live_check.py``: the FST entry
  parser, the SDK-style ``DVDConvertPathToEntrynum`` walk, and the RAM-vs-disc diff/mapping.

What changed in the merge (nothing that covers a safety property of the guard was dropped):

* The two near-identical fake-FST builders and the fake-RAM harness are now one set at the top. The unified
  builder pads past ``MIN_FST_SIZE`` (``fst_guard`` refuses to treat anything smaller as an FST at all);
  the padding entries are appended *after* the caller's names so name-order and entry-index assertions in
  the ``fst_live_check`` tests still hold.
* ``validate_fst``'s accept case and its four reject cases became one test with ``subTest`` blocks -- every
  assertion and every live-incident docstring is preserved, just under one test function.
* "a damaged FST at startup is never snapshotted" (131) was folded into the disc-baseline repair test (133),
  which exercises the same refusal and then goes on to repair from the ISO.
* The three ``describe()`` tests became two: one for the normal armed/repaired/reference-in-use progression,
  and one (kept separate, different state) for the ``!fstiso`` hint a guard that *cannot* arm must print.
* The two ``repair()`` tests and the two ``describe_range()`` tests in the live-check tool were each merged
  into one test that runs both phases.
* Dropped outright: ``test_ram_client_exposes_availability_and_a_safe_is_hooked`` -- ``hasattr`` plus
  substring checks on a constant message, no behaviour. The behavioural half of that concern (the guard
  must never import the native emulator package) is kept below.
"""
from __future__ import annotations

import struct
import unittest

from .. import fst_guard as fg
from ..tools import fst_live_check as flc


# --------------------------------------------------------------------------------------------------
# Shared fixtures
# --------------------------------------------------------------------------------------------------

def _build_fst(names: list[str], subdir: tuple[str, list[str]] | None = None, pad: int = 8) -> bytes:
    """A structurally valid GameCube FST over `names` (plus an optional subdirectory).

    fst_guard refuses to treat anything under MIN_FST_SIZE as an FST at all, so every fixture is padded
    past it with filler entries appended AFTER the caller's names -- name order, entry indices and string
    offsets of the caller's own names are therefore unaffected.
    """
    names = list(names) + [f"pad{i:03d}.fsys" for i in range(pad)]
    entries: list[tuple[int, str, int, int]] = []  # flag, name, f2 (offset), f3 (size / next-index)
    strings = bytearray()
    offs: dict[str, int] = {}

    def off(n: str) -> int:
        if n not in offs:
            offs[n] = len(strings)
            strings.extend(n.encode() + b"\x00")
        return offs[n]

    total = 1 + len(names) + (1 + len(subdir[1]) if subdir else 0)
    off("")
    entries.append((1, "", 0, total))
    for k, n in enumerate(names):
        off(n)
        entries.append((0, n, 0x1000 * (k + 1), 0x800))
    if subdir:
        dname, files = subdir
        off(dname)
        entries.append((1, dname, 0, len(entries) + 1 + len(files)))
        for k, n in enumerate(files):
            off(n)
            entries.append((0, n, 0x9000 + k, 0x40))
    out = bytearray()
    for flag, n, f2, f3 in entries:
        out += bytes([flag]) + offs[n].to_bytes(3, "big") + struct.pack(">II", f2, f3)
    return bytes(out + strings)


class _FakeRam:
    """Byte-addressed sparse RAM with the two FST globals wired up. Records every write."""

    def __init__(self, fst: bytes, addr: int = 0x817EA6A0) -> None:
        self.data: dict[int, int] = {}
        self.addr = addr
        self.poke(fg.FST_ADDR_PTR, struct.pack(">I", addr))
        self.poke(fg.FST_SIZE_PTR, struct.pack(">I", len(fst)))
        self.poke(addr, fst)
        self.writes: list[tuple[int, bytes]] = []

    def poke(self, address: int, blob: bytes) -> None:
        """Change RAM behind the guard's back -- simulated corruption, not a guard write."""
        for i, b in enumerate(blob):
            self.data[address + i] = b

    def read(self, address: int, length: int) -> bytes:
        return bytes(self.data.get(address + i, 0) for i in range(length))

    def write(self, address: int, blob: bytes) -> None:
        self.writes.append((address, blob))
        self.poke(address, blob)


class _GuardCase(unittest.TestCase):
    def _guard(self, ram: _FakeRam) -> tuple[fg.FstGuard, list[str]]:
        logs: list[str] = []
        return fg.FstGuard(read=ram.read, write=ram.write, log=logs.append), logs

    def _guard_split(self, ram: _FakeRam) -> tuple[fg.FstGuard, list[str], list[str]]:
        """ADDENDUM 181: `log` and `log_verbose` are two separate sinks -- the client prints the first
        unconditionally and gates the second behind `!verbose`. Returns both so a test can assert WHICH sink a
        message went to, not merely that it was emitted somewhere."""
        logs: list[str] = []
        verbose: list[str] = []
        guard = fg.FstGuard(read=ram.read, write=ram.write, log=logs.append, log_verbose=verbose.append)
        return guard, logs, verbose


# --------------------------------------------------------------------------------------------------
# validate_fst -- the whole safety story for the snapshot
# --------------------------------------------------------------------------------------------------

class TestValidateFst(unittest.TestCase):
    def test_accepts_a_real_shaped_fst_and_rejects_every_known_corruption_shape(self) -> None:
        """A damaged FST must never be accepted as the baseline we later repair *towards*, so the four
        reject cases below are each a shape seen live:

        * all zeros -- the boot-time case the player's watch log caught at 02:48, where the whole region
          reads as zeros before the apploader has filled it in;
        * an embedded NUL in a name -- the exact live damage from ADDENDUM 130: 'am' -> 00 01 inside
          wzx_hataku_damage.fsys. The truncated name is still printable, so this is caught by the
          zeroed-string-table-tail rule rather than the per-name checks;
        * a PCM-looking audio buffer splatted across the entry table -- the 02:51:49 case;
        * a root entry that is not a directory.
        """
        self.assertIsNone(
            fg.validate_fst(_build_fst(["a.fsys", "wzx_hataku_damage.fsys"], ("sub", ["i.fsys"]))),
            "a real-shaped FST, subdirectory and all, must validate",
        )

        with self.subTest("all zeros (boot, 02:48)"):
            self.assertIsNotNone(fg.validate_fst(bytes(88408)))

        with self.subTest("embedded NUL in a name (ADDENDUM 130 live damage)"):
            fst = bytearray(_build_fst(["wzx_hataku_damage.fsys", "zzz.fsys"]))
            i = fst.index(b"wzx_hataku_damage.fsys") + 12
            fst[i:i + 2] = b"\x00\x01"
            self.assertIsNotNone(fg.validate_fst(bytes(fst)))

        with self.subTest("audio buffer splatted over the entry table (02:51:49)"):
            fst = bytearray(_build_fst([f"f{i:03d}.fsys" for i in range(40)]))
            fst[24:24 + 64] = bytes(range(64))
            self.assertIsNotNone(fg.validate_fst(bytes(fst)))

        with self.subTest("bad root entry"):
            fst = bytearray(_build_fst(["a.fsys"]))
            fst[0] = 0
            self.assertIsNotNone(fg.validate_fst(bytes(fst)))


# --------------------------------------------------------------------------------------------------
# FstGuard against a RAM snapshot
# --------------------------------------------------------------------------------------------------

class TestFstGuard(_GuardCase):
    def test_arms_on_a_valid_fst_and_then_repairs_the_live_damage(self) -> None:
        fst = _build_fst(["wzx_hataku_damage.fsys", "wzx_hiduki_look_f.fsys", "zzz.fsys"])
        ram = _FakeRam(fst)
        guard, logs = self._guard(ram)
        self.assertTrue(guard.poll().get("armed"))
        self.assertEqual(guard.poll()["repaired"], 0)  # quiescent: no writes at all

        # now damage it exactly like the live session did
        i = fst.index(b"wzx_hataku_damage.fsys") + 12
        ram.poke(ram.addr + i, b"\x00\x01")
        ram.writes.clear()
        result = guard.poll()
        self.assertEqual(result["repaired"], 2)
        self.assertEqual(result["names"], ["wzx_hataku_damage.fsys"])
        self.assertEqual(ram.writes, [(ram.addr + i, b"am")])
        self.assertEqual(ram.read(ram.addr, len(fst)), fst)
        self.assertTrue(any("wzx_hataku_damage.fsys" in m for m in logs))
        self.assertEqual(guard.poll()["repaired"], 0)  # and it stays fixed

    def test_never_writes_outside_the_published_fst_region(self) -> None:
        fst = _build_fst(["a.fsys", "b.fsys"])
        ram = _FakeRam(fst)
        guard, _ = self._guard(ram)
        guard.poll()
        ram.poke(ram.addr + 20, b"\xff\xff")
        ram.writes.clear()
        guard.poll()
        for address, blob in ram.writes:
            self.assertGreaterEqual(address, ram.addr)
            self.assertLessEqual(address + len(blob), ram.addr + len(fst))

    def test_boot_zeros_then_arming_once_the_apploader_has_loaded_the_fst(self) -> None:
        """Mirrors the watch log: 02:48 the whole region is zeros, later it is a real FST."""
        fst = _build_fst(["a.fsys", "b.fsys"])
        ram = _FakeRam(bytes(len(fst)))
        guard, _ = self._guard(ram)
        self.assertIsNone(guard.baseline)
        self.assertEqual(ram.writes, [])
        ram.poke(ram.addr, fst)
        self.assertTrue(guard.poll().get("armed"))

    def test_wholesale_replacement_re_baselines_instead_of_writing_the_whole_fst_back(self) -> None:
        fst = _build_fst([f"f{i:03d}.fsys" for i in range(600)])
        self.assertGreater(len(fst), fg.MAX_REPAIRABLE_BYTES)
        ram = _FakeRam(fst)
        guard, _ = self._guard(ram)
        guard.poll()
        ram.poke(ram.addr, bytes(len(fst)))  # game reset: region is zeros again
        ram.writes.clear()
        result = guard.poll()
        self.assertTrue(result.get("rebaselined"))
        self.assertEqual(ram.writes, [])
        self.assertIsNone(guard.baseline)

    def test_implausible_pointers_and_a_new_boot_address_never_produce_writes(self) -> None:
        """Two ways the published pointers stop describing the table we snapshotted: they can be garbage
        (nothing published yet), or they can move because the game rebooted at a different address. Neither
        may ever be treated as damage to repair -- a write in either state lands on unrelated memory."""
        fst = _build_fst(["a.fsys"])
        ram = _FakeRam(fst)
        ram.poke(fg.FST_ADDR_PTR, struct.pack(">I", 0))
        guard, _ = self._guard(ram)
        result = guard.poll()
        self.assertEqual(result["status"], fg.FstStatus.NO_POINTERS)
        self.assertEqual(ram.writes, [])

        ram.poke(fg.FST_ADDR_PTR, struct.pack(">I", ram.addr))
        self.assertTrue(guard.poll().get("armed"))

        ram.poke(fg.FST_ADDR_PTR, struct.pack(">I", 0x817E0000))
        ram.poke(0x817E0000, fst)
        ram.writes.clear()
        guard.poll()
        self.assertEqual(guard.fst_addr, 0x817E0000)
        self.assertEqual(ram.writes, [])

    def test_poll_never_raises_even_when_ram_reads_explode(self) -> None:
        def boom(*_args, **_kwargs):
            raise RuntimeError("Dolphin went away")

        guard = fg.FstGuard(read=boom, write=boom)
        self.assertEqual(guard.poll()["repaired"], 0)

    def test_names_in_range_maps_a_damaged_band_to_every_name_it_touches(self) -> None:
        fst = _build_fst(["wzx_hataku_damage.fsys", "wzx_hiduki_look_f.fsys", "zzz.fsys"])
        s = fst.index(b"wzx_hataku_damage.fsys")
        e = fst.index(b"wzx_hiduki_look_f.fsys") + 4
        self.assertEqual(fg.names_in_range(fst, s, e),
                         ["wzx_hataku_damage.fsys", "wzx_hiduki_look_f.fsys"])

    def test_describe_reports_armed_state_repair_counts_and_the_reference_in_use(self) -> None:
        """`!fst` is the only window the player has into the guard, so it has to say which of the two
        references is actually in force -- the validated RAM snapshot or a named ISO -- as well as how much
        it has repaired and what it repaired."""
        fst = _build_fst(["wzx_hataku_damage.fsys"])
        ram = _FakeRam(fst)
        guard, _ = self._guard(ram)
        self.assertIn("no FST published", guard.describe())
        guard.poll()
        self.assertIn("armed", guard.describe())
        self.assertIn("validated RAM snapshot", guard.describe())

        ram.poke(ram.addr + fst.index(b"wzx_hataku_damage.fsys") + 12, b"\x00\x01")
        guard.poll()
        self.assertIn("2 byte(s) restored", guard.describe())
        self.assertIn("wzx_hataku_damage.fsys", guard.describe())

        guard.set_disc_baseline(fst, "seed.ciso")
        guard.poll()
        self.assertIn("seed.ciso", guard.describe())


# --------------------------------------------------------------------------------------------------
# FstGuard against the ISO's own file table
# --------------------------------------------------------------------------------------------------

class TestDiscBaseline(_GuardCase):
    def test_damage_present_before_the_client_ever_looked_is_repaired_from_the_disc(self) -> None:
        """The Dugtrio case. `wzx_hikkaku_attack.fsys` (Scratch) is already broken in RAM at connect time.

        Two properties in one: a damaged FST at startup is never snapshotted (there is nothing to repair
        towards, and adopting it would make the damage permanent), and once the ISO's own table is supplied
        the guard arms from it and fixes the pre-existing damage on the very next poll.
        """
        good = _build_fst(["wzx_hikkaku_attack.fsys", "other.fsys"])
        broken = bytearray(good)
        i = good.index(b"wzx_hikkaku_attack.fsys") + 15
        broken[i:i + 2] = b"\x00\x03"  # the exact live damage shape from ADDENDUM 130
        ram = _FakeRam(bytes(broken))
        guard, logs, verbose = self._guard_split(ram)

        # Without a disc baseline the guard correctly refuses to snapshot -- and so can never repair.
        result = guard.poll()
        self.assertIsNone(guard.baseline)
        self.assertIn("not structurally valid", result["status"])
        self.assertGreaterEqual(result.get("needs_disc_baseline", 0), 1)
        self.assertEqual(ram.writes, [])

        # With the ISO's own table it arms immediately and fixes the damage on the very next poll.
        guard.set_disc_baseline(good, "my seed.ciso")
        self.assertTrue(guard.poll().get("from_disc"))
        fixed = guard.poll()
        self.assertEqual(fixed["repaired"], 2)
        self.assertEqual(fixed["names"], ["wzx_hikkaku_attack.fsys"])
        self.assertEqual(ram.read(ram.addr, len(good)), good)

        # ADDENDUM 181: arming is narration and goes to the verbose sink; the REPAIR is an event the player
        # must always see, so it stays on the unconditional one. Asserting the split in both directions is
        # what stops a future edit from quietly silencing a repair along with the noise.
        self.assertTrue(any("my seed.ciso" in m for m in verbose),
                        "arming from a disc baseline should be verbose-only narration")
        self.assertFalse(any("armed" in m for m in logs),
                         "the arming message must not reach the unconditional sink")
        self.assertTrue(any("repaired" in m for m in logs),
                        "a real repair must ALWAYS be printed, verbose or not")

    def test_a_disc_baseline_survives_reset_and_a_wholesale_wipe(self) -> None:
        """It describes the ISO, not the boot -- a reset must not throw it away, or the next boot is
        unprotected again."""
        good = _build_fst([f"f{i:03d}.fsys" for i in range(600)])
        ram = _FakeRam(good)
        guard, _ = self._guard(ram)
        guard.set_disc_baseline(good, "seed.ciso")
        guard.poll()
        guard.reset()
        self.assertIsNotNone(guard.disc_baseline)

        ram.poke(ram.addr, bytes(len(good)))  # mid-reboot: region is zeros
        ram.writes.clear()
        guard.poll()          # re-arms from the disc copy (no write -- nothing is compared yet)
        result = guard.poll()  # now sees the wholesale difference
        self.assertTrue(result.get("rebaselined"))
        self.assertEqual(ram.writes, [], "must not write 86 KB into a booting game")
        self.assertIsNotNone(guard.disc_baseline)

        ram.poke(ram.addr, good)  # boot finishes -- still armed against the disc copy, now quiescent
        self.assertEqual(guard.poll()["repaired"], 0)
        self.assertIs(guard.baseline, guard.disc_baseline)
        self.assertIn("seed.ciso", guard.describe())

    def test_a_disc_baseline_of_the_wrong_size_is_ignored_not_written(self) -> None:
        """A different ISO than the one Dolphin has loaded must never be written over this game's table."""
        good = _build_fst(["a.fsys", "b.fsys"])
        other = _build_fst(["a.fsys", "b.fsys", "c.fsys", "d.fsys"])
        self.assertNotEqual(len(good), len(other))
        ram = _FakeRam(good)
        guard, _ = self._guard(ram)
        guard.set_disc_baseline(other, "wrong.ciso")
        result = guard.poll()
        self.assertFalse(result.get("from_disc"))
        self.assertTrue(result.get("armed"))  # falls back to the RAM snapshot, which does validate
        self.assertEqual(ram.writes, [])

    def test_set_disc_baseline_refuses_anything_that_is_not_a_valid_fst(self) -> None:
        guard = fg.FstGuard(read=lambda a, n: b"", write=lambda a, d: None)
        with self.assertRaises(ValueError):
            guard.set_disc_baseline(bytes(4096), "zeros.ciso")
        broken = bytearray(_build_fst(["wzx_hataku_damage.fsys"]))
        j = broken.index(b"wzx_hataku_damage.fsys") + 12
        broken[j:j + 2] = b"\x00\x01"
        with self.assertRaises(ValueError):
            guard.set_disc_baseline(bytes(broken), "damaged.ciso")
        self.assertIsNone(guard.disc_baseline)

    def test_describe_tells_the_player_how_to_unblock_a_guard_that_cannot_arm(self) -> None:
        broken = bytearray(_build_fst(["wzx_hikkaku_attack.fsys"]))
        j = broken.index(b"wzx_hikkaku_attack.fsys") + 15
        broken[j:j + 2] = b"\x00\x03"
        ram = _FakeRam(bytes(broken))
        guard, _ = self._guard(ram)
        for _ in range(4):
            guard.poll()
        self.assertIn("!fstiso", guard.describe())


class TestReadDiscFst(unittest.TestCase):
    def test_reads_the_fst_out_of_a_plain_iso_using_the_boot_header(self) -> None:
        import tempfile
        from pathlib import Path

        fst = _build_fst(["wzx_hataku_damage.fsys", "b.fsys"])
        offset = 0x1000
        image = bytearray(offset + len(fst) + 16)
        struct.pack_into(">I", image, fg.FST_OFFSET_FIELD, offset)
        struct.pack_into(">I", image, fg.FST_SIZE_FIELD, len(fst))
        image[offset:offset + len(fst)] = fst
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "seed.iso"
            path.write_bytes(bytes(image))
            self.assertEqual(fg.read_disc_fst(path), fst)


class TestWithoutDolphinMemoryEngine(unittest.TestCase):
    """Player request: 'ensure the client still functions even if the user doesn't have python installed.'
    The practical form of that is a missing/broken native `dolphin_memory_engine`: it must degrade to one
    clear message, not a raw traceback that makes the whole apworld look broken."""

    def test_the_guard_is_pure_python_and_needs_no_emulator_package(self) -> None:
        """fst_guard must never import dolphin_memory_engine -- it takes read/write by injection."""
        import ast
        tree = ast.parse((__import__("pathlib").Path(fg.__file__)).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module.split(".")[0])
        self.assertNotIn("dolphin_memory_engine", imported)


# --------------------------------------------------------------------------------------------------
# tools/fst_live_check.py -- the offline diagnostic that first identified the damage
# --------------------------------------------------------------------------------------------------

class TestFstLiveCheck(unittest.TestCase):
    def test_sdk_lookup_finds_root_file_and_skips_subdirectories(self) -> None:
        fst = _build_fst(["a.fsys", "wzx_hataku_damage.fsys"], ("sub", ["inner.fsys"]))
        r = flc.sdk_lookup(fst, "WZX_HATAKU_DAMAGE.FSYS")  # case-insensitive like the SDK
        self.assertTrue(r["found"])
        self.assertEqual(r["offset"], 0x2000)
        # the subdirectory's file is skipped by the root walk
        self.assertFalse(flc.sdk_lookup(fst, "inner.fsys")["found"])

    def test_a_damaged_band_is_mapped_to_its_names_and_reported_byte_for_byte(self) -> None:
        """Two halves of the same report. First: a corrupted band must name every entry whose name it
        touches, and names outside the band must still resolve (that asymmetry is what identified the
        corruption as a bounded splat rather than a dead table).

        Second (ADDENDUM 130): the byte VALUES and the name-relative offset are the fingerprint of the
        writer, so the report must carry them, not just 'a name was damaged'.
        """
        fst = _build_fst(["wzx_hataku_attack.fsys", "wzx_hataku_damage.fsys",
                          "wzx_hikkaku_attack.fsys", "zzz.fsys"])
        ram = bytearray(fst)
        strings_off = struct.unpack_from(">I", fst, 8)[0] * flc.FST_ENTRY_SIZE
        # smash the bytes of the 2nd and 3rd names
        e = flc.fst_entries(fst)
        s = e[2]["name_span"][0]
        t = e[3]["name_span"][1]
        for i in range(s, t):
            ram[i] = 0x54
        ranges = flc.diff_ranges(fst, bytes(ram))
        self.assertEqual(len(ranges), 1)
        d = flc.describe_range(e, strings_off, *ranges[0])
        self.assertEqual(d["region"], "string table")
        self.assertEqual(d["names_damaged"], ["wzx_hataku_damage.fsys", "wzx_hikkaku_attack.fsys"])
        self.assertTrue(flc.sdk_lookup(fst, "wzx_hataku_damage.fsys")["found"])
        r = flc.sdk_lookup(bytes(ram), "wzx_hataku_damage.fsys")
        self.assertFalse(r["found"])
        self.assertIn("without a name match", r["stopped_reason"])
        self.assertTrue(flc.sdk_lookup(bytes(ram), "zzz.fsys")["found"])  # names outside the band resolve

        fst = _build_fst(["wzx_hataku_damage.fsys"])
        e = flc.fst_entries(fst)
        ram = bytearray(fst)
        s = e[1]["name_span"][0] + 12  # the live case: byte 12 of the name, "am" -> 00 01
        ram[s:s + 2] = b"\x00\x01"
        (rs, re_), = flc.diff_ranges(fst, bytes(ram))
        d = flc.describe_range(e, struct.unpack_from(">I", fst, 8)[0] * flc.FST_ENTRY_SIZE, rs, re_,
                               fst, bytes(ram), 0x817ea6a0)
        self.assertEqual((d["disc_bytes"], d["ram_bytes"]), ("616d", "0001"))
        self.assertEqual(d["ram_value_be"], 1)
        self.assertEqual(d["name"], "wzx_hataku_damage.fsys")
        self.assertEqual(d["name_relative_offset"], 12)
        self.assertEqual(d["name_in_ram"], "wzx_hataku_d\x00\x01age.fsys")
        self.assertEqual(d["address"], 0x817ea6a0 + rs)

    def test_repair_writes_back_exactly_the_disc_bytes_and_only_inside_the_fst(self) -> None:
        """ADDENDUM 130 rescue path: repair() must write back exactly the disc's bytes, only inside the FST,
        and leave the name resolvable -- which is what unsticks the DVDOpen retry loop. The second half is
        the bound itself: a range that runs past the end of the in-RAM table must be refused outright rather
        than clamped, because everything after the table belongs to the running game."""
        fst = _build_fst(["wzx_hiduki_look_f.fsys", "other.fsys"])
        ram = bytearray(fst)
        s = flc.fst_entries(fst)[1]["name_span"][0] + 12
        ram[s:s + 2] = b"\x00\x01"
        self.assertFalse(flc.sdk_lookup(bytes(ram), "wzx_hiduki_look_f.fsys")["found"])
        written: list[tuple[int, bytes]] = []
        base = 0x817ea6a0

        def fake_write(address: int, data: bytes) -> None:
            written.append((address, data))
            off = address - base
            ram[off:off + len(data)] = data

        orig_w, orig_r = flc._write_ram, flc._read_ram
        flc._write_ram = fake_write
        flc._read_ram = lambda a, n: bytes(ram[a - base:a - base + n])
        try:
            results = flc.repair(base, len(fst), fst, flc.diff_ranges(fst, bytes(ram)))
        finally:
            flc._write_ram, flc._read_ram = orig_w, orig_r
        self.assertEqual([r["repaired"] for r in results], [True])
        self.assertEqual(written, [(base + s, b"\x61\x6d" if fst[s:s + 2] == b"\x61\x6d" else fst[s:s + 2])])
        self.assertEqual(bytes(ram), fst)
        self.assertTrue(flc.sdk_lookup(bytes(ram), "wzx_hiduki_look_f.fsys")["found"])

        # a range that leaves the table is refused, with no write attempted at all
        calls: list = []
        orig_w = flc._write_ram
        flc._write_ram = lambda a, d: calls.append((a, d))
        try:
            results = flc.repair(base, len(fst), fst, [(len(fst) - 1, len(fst) + 8)])
        finally:
            flc._write_ram = orig_w
        self.assertEqual(calls, [])
        self.assertFalse(results[0]["repaired"])
        self.assertIn("outside", results[0]["reason"])

    def test_corrupted_directory_next_index_is_reported(self) -> None:
        fst = _build_fst(["a.fsys"], ("sub", ["inner.fsys"]))
        ram = bytearray(fst)
        dir_index = next(e["index"] for e in flc.fst_entries(fst) if e["is_dir"] and e["index"] > 0)
        struct.pack_into(">I", ram, dir_index * flc.FST_ENTRY_SIZE + 8, 1)  # now points backwards
        r = flc.sdk_lookup(bytes(ram), "nothing.fsys")
        self.assertFalse(r["found"])
        self.assertIn("next-index", r["stopped_reason"])


if __name__ == "__main__":
    unittest.main()
