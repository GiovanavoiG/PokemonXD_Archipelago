"""ADDENDUM 203. The patcher no longer goes silent for minutes, and it says what image format it detected.

Player: "patching is hanging here" -- with a screenshot of the console stopped right after the Mt. Battle
line. It was not hanging. The next step LZSS re-encodes the whole of `common_rel` (704,448 bytes on a real
ISO, measured at 29.3s in pure Python on a fast machine, plausibly minutes on a slower one) and printed
NOTHING for its entire duration, while every other step in the patch announces itself.

Then: "Could the issue be that I did not name it .ciso? Can you make the patch enforce a .ciso file
extension?" -- no, and deliberately not. `_detect_and_open` reads the file's MAGIC BYTES. The extension has
never been consulted and must not be: a CISO with no extension is valid input, and enforcing a name would
break plain .iso/.gcm, which this tool explicitly supports. The fix for "I couldn't tell what it detected" is
to print what it detected."""
from __future__ import annotations

import inspect
import struct
import tempfile
import unittest
from pathlib import Path

from ..tools import iso_patcher


class TestFormatComesFromMagicNotTheName(unittest.TestCase):
    def _write(self, name: str, magic: bytes) -> Path:
        path = Path(self.tmp.name) / name
        body = bytearray(0x8000 + 0x10)
        body[0:4] = magic
        if magic == iso_patcher.CISO_MAGIC:
            struct.pack_into(">I", body, 4, 0x200000)   # block size
        path.write_bytes(bytes(body))
        return path

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_a_ciso_with_no_extension_is_still_a_ciso(self) -> None:
        """Exactly the player's file: no extension at all."""
        path = self._write("finalTest2Chests", iso_patcher.CISO_MAGIC)
        reader = iso_patcher.open_reader(path)
        try:
            self.assertIsInstance(reader, iso_patcher.CisoReader)
        finally:
            reader.close()

    def test_a_plain_iso_named_ciso_is_still_a_plain_iso(self) -> None:
        """The reverse, which is why enforcing the extension would be actively wrong."""
        path = self._write("mygame.ciso", b"\x00\x00\x00\x00")
        reader = iso_patcher.open_reader(path)
        try:
            self.assertIsInstance(reader, iso_patcher.PlainIsoReader)
        finally:
            reader.close()

    def test_nothing_in_the_patcher_gates_on_a_file_extension(self) -> None:
        source = Path(iso_patcher.__file__).read_text(encoding="utf-8")
        for forbidden in (".suffix ==", "suffix.lower() ==", 'endswith(".ciso")', 'endswith(".iso")'):
            self.assertNotIn(forbidden, source, f"the patcher must not gate on a filename: {forbidden}")

    def test_the_detected_format_is_reported(self) -> None:
        src = inspect.getsource(iso_patcher.chunked_copy)
        self.assertIn("Source image format:", src)
        self.assertIn("magic bytes, not its extension", src)


class TestTheSlowStepAnnouncesItself(unittest.TestCase):
    """A step that goes quiet for minutes is indistinguishable from a crash."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = Path(iso_patcher.__file__).read_text(encoding="utf-8")

    def test_the_re_encode_warns_before_it_starts(self) -> None:
        self.assertIn("Re-encoding common_rel", self.source)
        self.assertIn("It has not crashed; let it run.", self.source)

    def test_the_warning_precedes_the_work(self) -> None:
        """Printed after the encode it would be useless -- the whole point is the wait beforehand."""
        warn = self.source.index("Re-encoding common_rel")
        work = self.source.index("new_entry_raw, real_comp_size, _grew = deck_format.patch_entry_decompressed")
        self.assertLess(warn, work)

    def test_it_reports_how_long_it_actually_took(self) -> None:
        self.assertIn("common_rel re-encoded in", self.source)

    def test_the_copy_step_still_reports_progress(self) -> None:
        """The one step that already did this right; the re-encode was the outlier."""
        self.assertIn("PROGRESS_EVERY_BYTES", inspect.getsource(iso_patcher.chunked_copy))


if __name__ == "__main__":
    unittest.main()
