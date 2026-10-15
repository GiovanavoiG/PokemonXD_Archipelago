"""ADDENDUM 422 (2026-10-06) -- the Poke Spot level-0 bug's root cause, and the fix.

Every wild Relicanth in one seed was generating at level 0.

`_fightTrainerCreateDeckWildPoke` looks the shown species up in its SPOT's three pool entries for the level
range and leaves the index register uninitialised on a miss. The two "all"-pool slots (vanilla Bonsly and
Munchlax) are not in any spot's three, so a reassigned species there -- Relicanth in this seed -- misses.
"""
from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from ..game_data import pokespot_data
from ..tools import iso_patcher as ip

SEC_ADDR = 0x801F0000
SEC_LEN = 0x00020000
SEC_FILE = 0x100
DOL_OFF = 0x1000
REAL_DOL = Path("/mnt/user-data/uploads/PokemonXD-working/main_dol.bin")


def _make_iso(path: Path, words=None) -> "list[int]":
    img = bytearray(DOL_OFF + SEC_FILE + SEC_LEN + 0x100)
    img[0:4] = b"GXXE"
    struct.pack_into(">I", img, ip.DOL_OFFSET_FIELD, DOL_OFF)
    struct.pack_into(">I", img, DOL_OFF + ip.DOL_FILE_OFFSETS, SEC_FILE)
    struct.pack_into(">I", img, DOL_OFF + ip.DOL_LOAD_ADDRESSES, SEC_ADDR)
    struct.pack_into(">I", img, DOL_OFF + ip.DOL_SECTION_SIZES, SEC_LEN)
    offsets = []
    for i, (address, expected, _new) in enumerate(ip.POKESPOT_LEVEL_INDEX_PATCH):
        off = DOL_OFF + SEC_FILE + (address - SEC_ADDR)
        struct.pack_into(">I", img, off, expected if words is None else words[i])
        offsets.append(off)
    path.write_bytes(bytes(img))
    return offsets


class TestTheInstructions(unittest.TestCase):
    def test_only_the_source_register_changes(self):
        for _address, expected, new in ip.POKESPOT_LEVEL_INDEX_PATCH:
            self.assertEqual(21, expected >> 26, "rlwinm")
            self.assertEqual(31, (expected >> 21) & 31, "was r31")
            self.assertEqual(10, (new >> 21) & 31, "now r10")
            self.assertEqual(expected & 0x001FFFFF, new & 0x001FFFFF, "same destination, shift and mask")

    def test_the_all_pool_is_the_one_no_spot_lists(self):
        pools = {s.pool for s in pokespot_data.VANILLA_POKESPOT_SLOTS}
        self.assertEqual({"rock", "oasis", "cave", "all"}, pools)
        self.assertEqual(2, sum(1 for s in pokespot_data.VANILLA_POKESPOT_SLOTS if s.pool == "all"))
        for pool in ("rock", "oasis", "cave"):
            self.assertEqual(3, sum(1 for s in pokespot_data.VANILLA_POKESPOT_SLOTS if s.pool == pool),
                             "the game's lookup loop is hard-coded to three")


class TestAgainstTheRealDol(unittest.TestCase):
    """When the extracted main.dol is on hand: the loop really is `< 3`, really stores r10 into r31 on a hit,
    and nothing writes r10 between the loop and the two loads."""

    def setUp(self):
        if not REAL_DOL.is_file():
            self.skipTest("main_dol.bin not on this machine")
        data = REAL_DOL.read_bytes()
        sections = []
        for i in range(18):
            off, addr, size = (struct.unpack_from(">I", data, base + i * 4)[0] for base in (0, 0x48, 0x90))
            if size:
                sections.append((addr, size, off))

        def word(address):
            for addr, size, off in sections:
                if addr <= address < addr + size:
                    return struct.unpack_from(">I", data, off + address - addr)[0]
        self.word = word

    def test_the_expected_words_are_on_disc(self):
        for address, expected, _new in ip.POKESPOT_LEVEL_INDEX_PATCH:
            self.assertEqual(expected, self.word(address), hex(address))

    def test_the_loop_shape(self):
        self.assertEqual(0x7D5F5378, self.word(0x801FAF40), "mr r31,r10 -- the hit")
        self.assertEqual(0x28000003, self.word(0x801FAF50), "cmplwi r0,3 -- the bound")
        self.assertEqual(0x39400000, self.word(0x801FAEE8), "li r10,0 -- the loop start")
        for address in range(0x801FAF58, 0x801FAFD8, 4):
            w = self.word(address)
            self.assertNotEqual(18, w >> 26, f"no branch-and-link at {address:#x}") if w & 1 else None
            if w >> 26 in (14, 15, 32, 34, 40, 21, 24):          # D-form/rlwinm writers: rD/rA field
                dest = (w >> 16) & 31 if w >> 26 in (21, 24) else (w >> 21) & 31
                self.assertNotEqual(10, dest, f"r10 written at {address:#x}")

    def test_r31_is_the_callers_hero_pointer_on_entry(self):
        """No write to r31 between the prologue and the loop -- on a miss it really is the caller's value."""
        for address in range(0x801FADF0, 0x801FAF40, 4):
            w = self.word(address)
            if w >> 26 == 31 and ((w >> 1) & 0x3FF) == 444:       # mr / or
                self.assertNotEqual(31, (w >> 16) & 31, f"r31 written at {address:#x}")
            if w >> 26 in (14, 15, 32, 34, 40):
                self.assertNotEqual(31, (w >> 21) & 31, f"r31 written at {address:#x}")


class TestThePatchWrite(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="a422_"))

    def test_both_words_are_written_and_read_back(self):
        iso = self.dir / "good.iso"
        offsets = _make_iso(iso)
        result = ip.write_pokespot_level_index_patch(iso)
        self.assertTrue(result["applied"], result["reason"])
        data = iso.read_bytes()
        for off, (_a, _e, new) in zip(offsets, ip.POKESPOT_LEVEL_INDEX_PATCH):
            self.assertEqual(new, struct.unpack_from(">I", data, off)[0])

    def test_nothing_else_moves(self):
        iso = self.dir / "one.iso"
        offsets = _make_iso(iso)
        before = bytearray(iso.read_bytes())
        ip.write_pokespot_level_index_patch(iso)
        after = iso.read_bytes()
        allowed = {o + i for o in offsets for i in range(4)}
        self.assertTrue({i for i in range(len(after)) if after[i] != before[i]} <= allowed)

    def test_twice_is_idempotent(self):
        iso = self.dir / "twice.iso"
        _make_iso(iso)
        ip.write_pokespot_level_index_patch(iso)
        result = ip.write_pokespot_level_index_patch(iso)
        self.assertTrue(result["applied"])
        self.assertEqual("already patched", result["reason"])

    def test_a_wrong_build_is_refused_whole(self):
        iso = self.dir / "wrong.iso"
        _make_iso(iso, words=[ip.POKESPOT_LEVEL_INDEX_PATCH[0][1], 0x4E800020])
        before = iso.read_bytes()
        result = ip.write_pokespot_level_index_patch(iso)
        self.assertFalse(result["applied"])
        self.assertIn("different build", result["reason"])
        self.assertEqual(before, iso.read_bytes(), "all or nothing -- the first word was not written either")


class TestTheWiring(unittest.TestCase):
    def test_applied_with_the_species_reassignment(self):
        source = (Path(ip.__file__)).read_text(encoding="utf-8")
        block = source.split("# ADDENDUM 422: the wild Poke Spot level lookup", 1)[1][:1200]
        self.assertIn("if pokespot_assignment:", block)
        self.assertIn("write_pokespot_level_index_patch(output_path)", block)
        self.assertIn('summary["pokespot_level_fix_applied"]', block)


if __name__ == "__main__":
    unittest.main()
