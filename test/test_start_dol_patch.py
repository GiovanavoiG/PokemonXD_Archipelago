"""The AP patch: `assets/patch.diff` applied to main.dol (Start.dol) with bsdiff4, before any other change.

Against synthetic ISOs, with the vanilla/patched SHA-1s and the diff swapped for ones built from the fixture, so
the step runs for real -- read, hash check, bsdiff4, relocation, header rewrite, read-back -- without a retail
disc. The shipped diff itself is checked for its header and target size."""
from __future__ import annotations

import hashlib
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bsdiff4

from ..tools import iso_patcher

DOL_OFFSET = 0x500
FILE_NAME = b"other.fsys\x00"
FILE_BYTES = bytes(range(256)) * 2


def _dol(sections: "list[bytes]") -> bytes:
    """A DOL whose text sections 0..n hold `sections`, laid out back to back after the 0x100-byte header."""
    head = bytearray(0x100)
    body = b""
    for i, data in enumerate(sections):
        struct.pack_into(">I", head, iso_patcher.DOL_FILE_OFFSETS + i * 4, 0x100 + len(body))
        struct.pack_into(">I", head, iso_patcher.DOL_LOAD_ADDRESSES + i * 4, 0x80003100 + 0x1000 * i)
        struct.pack_into(">I", head, iso_patcher.DOL_SECTION_SIZES + i * 4, len(data))
        body += data
    return bytes(head) + body


VANILLA = _dol([b"\x11" * 0x100])
PATCHED = _dol([b"\x11" * 0x80 + b"\x22" * 0x80, b"\x33" * 0x40])


def _iso(dol: bytes, fst_offset: int) -> bytes:
    """Disc header -> main.dol at DOL_OFFSET -> FST at `fst_offset` -> one file right after it."""
    file_offset = fst_offset + 0x100
    fst = bytearray(2 * 12 + len(FILE_NAME))
    fst[0] = 1
    struct.pack_into(">I", fst, 8, 2)
    struct.pack_into(">II", fst, 12 + 4, file_offset, len(FILE_BYTES))
    fst[24:] = FILE_NAME
    iso = bytearray(file_offset + len(FILE_BYTES))
    iso[0:6] = iso_patcher.EXPECTED_DISC_ID
    struct.pack_into(">III", iso, iso_patcher.DOL_OFFSET_FIELD, DOL_OFFSET, fst_offset, len(fst))
    iso[DOL_OFFSET:DOL_OFFSET + len(dol)] = dol
    iso[fst_offset:fst_offset + len(fst)] = fst
    iso[file_offset:] = FILE_BYTES
    return bytes(iso)


class _FixtureDiff(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "out.iso"
        for target, value in (
            ("START_DOL_VANILLA_SHA1", hashlib.sha1(VANILLA).hexdigest()),
            ("START_DOL_PATCHED_SHA1", hashlib.sha1(PATCHED).hexdigest()),
        ):
            patcher = mock.patch.object(iso_patcher, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(iso_patcher, "read_start_dol_patch",
                                    return_value=bsdiff4.diff(VANILLA, PATCHED))
        patcher.start()
        self.addCleanup(patcher.stop)


class TestWriteStartDolPatch(_FixtureDiff):

    def test_a_dol_that_no_longer_fits_moves_and_the_header_follows_it(self) -> None:
        """The retail layout: main.dol ends exactly where the FST begins."""
        before = _iso(VANILLA, DOL_OFFSET + len(VANILLA))
        self.path.write_bytes(before)
        result = iso_patcher.write_start_dol_patch(self.path)
        self.assertTrue(result["applied"], result["reason"])
        self.assertTrue(result["relocated"])
        after = self.path.read_bytes()
        new_offset = struct.unpack_from(">I", after, iso_patcher.DOL_OFFSET_FIELD)[0]
        self.assertEqual(result["dol_offset"], new_offset)
        self.assertGreaterEqual(new_offset, len(before))
        self.assertEqual(0, new_offset % 32)
        self.assertEqual(PATCHED, after[new_offset:new_offset + len(PATCHED)])
        field = iso_patcher.DOL_OFFSET_FIELD
        self.assertEqual(before[:field] + before[field + 4:], after[:field] + after[field + 4:len(before)],
                         "nothing but the header's DOL offset may change in the original image")

    def test_a_dol_with_room_after_it_is_patched_in_place(self) -> None:
        before = _iso(VANILLA, 0x800)
        self.path.write_bytes(before)
        result = iso_patcher.write_start_dol_patch(self.path)
        self.assertTrue(result["applied"], result["reason"])
        self.assertFalse(result["relocated"])
        after = self.path.read_bytes()
        self.assertEqual(len(before), len(after))
        self.assertEqual(PATCHED, after[DOL_OFFSET:DOL_OFFSET + len(PATCHED)])
        self.assertEqual(before[0x800:], after[0x800:])

    def test_an_already_patched_dol_is_left_alone(self) -> None:
        before = _iso(PATCHED, 0x800)
        self.path.write_bytes(before)
        result = iso_patcher.write_start_dol_patch(self.path)
        self.assertTrue(result["applied"])
        self.assertEqual("already patched", result["reason"])
        self.assertEqual(before, self.path.read_bytes())

    def test_a_foreign_dol_is_refused_and_nothing_is_written(self) -> None:
        before = _iso(_dol([b"\x44" * 0x100]), 0x800)
        self.path.write_bytes(before)
        result = iso_patcher.write_start_dol_patch(self.path)
        self.assertFalse(result["applied"])
        self.assertIn("not the retail NTSC-U one", result["reason"])
        self.assertEqual(before, self.path.read_bytes())

    def test_the_preflight_checks_the_dol(self) -> None:
        self.path.write_bytes(_iso(VANILLA, 0x800))
        self.assertIsNone(iso_patcher.start_dol_refusal(self.path))
        self.path.write_bytes(_iso(PATCHED, 0x800))
        self.assertIsNone(iso_patcher.start_dol_refusal(self.path))
        self.path.write_bytes(_iso(_dol([b"\x44" * 0x100]), 0x800))
        self.assertIn("main.dol is not the retail NTSC-U one", iso_patcher.start_dol_refusal(self.path))
        self.assertIn("main.dol is not the retail NTSC-U one", iso_patcher.preflight_refusal(self.path, None))


class TestTheShippedDiff(unittest.TestCase):

    def test_it_is_a_bsdiff4_patch_to_the_patched_dols_size(self) -> None:
        diff = iso_patcher.read_start_dol_patch()
        self.assertEqual(b"BSDIFF40", diff[:8])
        self.assertEqual(4334756, struct.unpack_from("<q", diff, 24)[0])


class TestItGoesInFirst(unittest.TestCase):

    def test_apply_patch_runs_it_right_after_the_copy(self) -> None:
        source = Path(iso_patcher.__file__).read_text(encoding="utf-8")
        body = source[source.index("def apply_patch("):]
        copy_at = body.index("chunked_copy(source_path, output_path)")
        dol_at = body.index("write_start_dol_patch(output_path)")
        self.assertLess(copy_at, dol_at)
        for first_other_pass in ("if assignment or moves_assignment:", "open_writer(", "write_dol_words_patch("):
            self.assertLess(dol_at, body.index(first_other_pass), first_other_pass)


if __name__ == "__main__":
    unittest.main()
