"""ADDENDUM 305 (2026-09-20) -- always-catch, folded into the max_catch_rate option.

Player: "I want it baked into the max catch rate option so that it works."

WHAT IT WRITES, and where every number came from. The player supplied a community Action Replay code
(06QM-1V0H-C6RG9 / DB0T-3ZXB-NUH6D) which Dolphin decrypts to `04219324 48000154`. AR type 04 is a 32-bit
RAM write and the address field ORs with 0x80000000, so the target is 0x80219324; the value 0x48000154 is a
PowerPC `b +0x154`, an unconditional branch 85 instructions forward, replacing a conditional so the capture
never takes its failure path.

THIS CLOSES ADDENDUM 300'S OPEN QUESTION RATHER THAN REOPENING IT. Both catch-rate fields are bytes that cap
at 255, and 255 is not certainty because the Gen III roll multiplies the rate by a health term worth a third
at full HP. That the guarantee must live in code was already the conclusion from this project's own evidence
(the tutorial Teddiursa is a certainty at catch rate 120) and is confirmed outside it -- The Cave of
Dragonflies documents Colosseum/XD as using the standard Gen III formula, with Colosseum hard-coding its
tutorial capture. So this is the missing half, not a contradiction.

WRITING INTO THE EXECUTABLE IS A DIFFERENT RISK CLASS FROM EVERY OTHER WRITE THIS PROJECT MAKES. A wrong
table offset gives a wrong item; a wrong code offset gives arbitrary instructions. So the refusal logic is
pure and tested here in its own right, and the end-to-end tests below build a real DOL-shaped image and
check both that a good one is patched and that a bad one is left completely untouched.
"""
from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from ..tools import iso_patcher as ip

SEC_ADDR = 0x80100000
SEC_LEN = 0x00200000
SEC_FILE = 0x100
DOL_OFF = 0x1000
ORIGINAL = 0x4E800420         # bctr -- measured on the real NTSC-U disc (ADDENDUM 306)


def _make_iso(path: Path, word_at_target: int = ORIGINAL,
              sec_addr: int = SEC_ADDR, sec_len: int = SEC_LEN) -> int:
    img = bytearray(DOL_OFF + SEC_FILE + sec_len + 0x100)
    img[0:4] = b"GXXE"
    struct.pack_into(">I", img, ip.DOL_OFFSET_FIELD, DOL_OFF)
    struct.pack_into(">I", img, DOL_OFF + ip.DOL_FILE_OFFSETS, SEC_FILE)
    struct.pack_into(">I", img, DOL_OFF + ip.DOL_LOAD_ADDRESSES, sec_addr)
    struct.pack_into(">I", img, DOL_OFF + ip.DOL_SECTION_SIZES, sec_len)
    target_file = DOL_OFF + SEC_FILE + (ip.ALWAYS_CATCH_ADDRESS - sec_addr)
    if 0 <= target_file < len(img) - 4:
        struct.pack_into(">I", img, target_file, word_at_target)
    path.write_bytes(bytes(img))
    return target_file


class TestTheNumbersComeFromTheCode(unittest.TestCase):
    def test_the_address_is_the_ar_address(self) -> None:
        self.assertEqual(0x80000000 | 0x219324, ip.ALWAYS_CATCH_ADDRESS)

    def test_the_word_is_an_unconditional_branch(self) -> None:
        self.assertEqual(18, ip.ALWAYS_CATCH_WORD >> 26, "PowerPC opcode 18 is `b`")
        self.assertEqual(0, (ip.ALWAYS_CATCH_WORD >> 1) & 1, "relative, not absolute")
        self.assertEqual(0, ip.ALWAYS_CATCH_WORD & 1, "a jump, not a call")

    def test_it_jumps_forward_the_distance_the_code_specifies(self) -> None:
        self.assertEqual(0x154, ip.ALWAYS_CATCH_WORD & 0x03FFFFFC)

    def test_it_only_ever_overwrites_the_exact_measured_word(self) -> None:
        """ADDENDUM 306. This was a category test ("is it a conditional branch?") and the category was
        guessed wrong -- the real disc holds `bctr`. An exact word is both safer and stricter."""
        self.assertEqual(0x4E800420, ip.ALWAYS_CATCH_EXPECTED_WORD)
        self.assertEqual(19, ip.ALWAYS_CATCH_EXPECTED_WORD >> 26)
        self.assertEqual(528, (ip.ALWAYS_CATCH_EXPECTED_WORD >> 1) & 1023, "bcctr")
        self.assertEqual(20, (ip.ALWAYS_CATCH_EXPECTED_WORD >> 21) & 31, "BO=20 -- unconditional")


class TestTheRefusalLogic(unittest.TestCase):
    def test_the_measured_word_is_accepted(self) -> None:
        self.assertIsNone(ip.always_catch_refusal(ORIGINAL, SEC_ADDR, SEC_LEN))

    def test_any_other_word_is_refused(self) -> None:
        for other in (0x38600001, 0x40820154, 0x48000010, 0x4E800020, 0x60000000):
            self.assertIsNotNone(ip.always_catch_refusal(other, SEC_ADDR, SEC_LEN), hex(other))

    def test_a_conditional_branch_is_refused_now(self) -> None:
        """The value the first version of this guard REQUIRED. Kept as a test so the regression is explicit:
        accepting a category let a wrong revision through while rejecting the right disc."""
        self.assertIsNotNone(ip.always_catch_refusal(0x40820154, SEC_ADDR, SEC_LEN))

    def test_a_jump_leaving_the_section_is_refused(self) -> None:
        tight = ip.ALWAYS_CATCH_ADDRESS - SEC_ADDR + 0x10
        self.assertIsNotNone(ip.always_catch_refusal(ORIGINAL, SEC_ADDR, tight))


class TestAgainstARealDolShapedImage(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="a305_"))

    def test_a_good_image_is_patched_and_verified(self) -> None:
        iso = self.dir / "good.iso"
        target = _make_iso(iso)
        result = ip.write_always_catch_code_patch(iso)
        self.assertTrue(result["applied"], result["reason"])
        self.assertEqual(target, result["file_offset"])
        self.assertEqual(ORIGINAL, result["original"])
        self.assertEqual(ip.ALWAYS_CATCH_WORD,
                         struct.unpack_from(">I", iso.read_bytes(), target)[0])

    def test_nothing_else_in_the_image_moves(self) -> None:
        iso = self.dir / "one.iso"
        target = _make_iso(iso)
        before = bytearray(iso.read_bytes())
        ip.write_always_catch_code_patch(iso)
        after = iso.read_bytes()
        changed = [i for i in range(len(after)) if after[i] != before[i]]
        self.assertTrue(set(changed) <= set(range(target, target + 4)), changed[:8])

    def test_a_wrong_build_is_refused_and_left_untouched(self) -> None:
        iso = self.dir / "wrong.iso"
        _make_iso(iso, word_at_target=0x38600001)
        before = iso.read_bytes()
        result = ip.write_always_catch_code_patch(iso)
        self.assertFalse(result["applied"])
        self.assertIn("not the 0x4E800420", result["reason"])
        self.assertEqual(before, iso.read_bytes(), "a refused patch must not write a single byte")

    def test_an_address_outside_every_section_is_refused(self) -> None:
        iso = self.dir / "elsewhere.iso"
        _make_iso(iso, sec_addr=0x80400000)
        before = iso.read_bytes()
        result = ip.write_always_catch_code_patch(iso)
        self.assertFalse(result["applied"])
        self.assertIn("not inside any section", result["reason"])
        self.assertEqual(before, iso.read_bytes())

    def test_running_it_twice_is_idempotent(self) -> None:
        iso = self.dir / "twice.iso"
        _make_iso(iso)
        ip.write_always_catch_code_patch(iso)
        after_first = iso.read_bytes()
        second = ip.write_always_catch_code_patch(iso)
        self.assertTrue(second["applied"])
        self.assertEqual("already patched", second["reason"])
        self.assertEqual(after_first, iso.read_bytes())

    def test_a_garbage_file_is_reported_not_raised(self) -> None:
        iso = self.dir / "junk.iso"
        iso.write_bytes(b"\x00" * 0x200)
        result = ip.write_always_catch_code_patch(iso)
        self.assertFalse(result["applied"])
        self.assertIsNotNone(result["reason"])


class TestItIsGatedOnTheOption(unittest.TestCase):
    def test_the_seed_patch_runs_it_under_max_catch_rate(self) -> None:
        source = open(ip.__file__, encoding="utf-8").read()
        start = source.index("    if max_catch_rate:")
        block = source[start:source.index("\n    # Shop/mart randomization", start)]
        self.assertIn("write_always_catch_code_patch(output_path)", block)

    def test_a_seed_without_the_option_never_reaches_it(self) -> None:
        source = open(ip.__file__, encoding="utf-8").read()
        self.assertEqual(1, source.count("write_always_catch_code_patch(output_path)"))

    def test_the_option_still_exists_and_is_off_by_default(self) -> None:
        from ..options import MaxCatchRate, PokemonXDOptions

        self.assertEqual(0, MaxCatchRate.default)
        self.assertIn("max_catch_rate", PokemonXDOptions.__annotations__)


if __name__ == "__main__":
    unittest.main()
