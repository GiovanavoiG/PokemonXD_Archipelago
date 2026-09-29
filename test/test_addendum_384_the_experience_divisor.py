"""ADDENDUM 384 (2026-09-28) -- the experience formula's own divisor.

Player: "It's base times level over seven - can we just... change the seven? So the division is less
impactful? Modify the exp formula?" then "make the exp multiplier range as high as reasonable with that
option."

WHERE THE SEVEN IS. The award routine is four instructions:

    0x80212C80   7C6301D6   mullw r3,r3,r0     base_exp * level
    0x80212C84   38000007   li    r0,7         <- this
    0x80212C8C   7C0303D6   divw  r0,r3,r0     / 7
    0x80212C9C   7C0383D6   divw  r0,r3,r16    / participants, conditional

The DOL load base (0x800030A0) was solved from `setExp` and `getLevel` -- one of 49 candidate pairings put
both at a sane offset -- and then confirmed by all nine documented accessors landing inside sections. A
measured award corroborates the formula itself: an Eevee at level 11 gained exactly 154, and 98 * 11 / 7 is
154.

WHY THIS CHANGED THE CEILING. Before, the only lever was the species table's base-exp byte, which caps at
255, so asking for 5x delivered about 2.6x and 358 of 386 species were clamped. The divisor is exact: 7/1 is
7.00x with nothing clamped at all. So the tables are now only asked for whatever is left above 700%, which
is why the option's range could go to 1000 (it lands at about 991%) and no further -- by 1200 the gap is 3%.

TWO SOURCES OF TRUTH WOULD BE A BUG (ADDENDA 243/257), so the planner is TOLD what the divisor already
bought (`from_divisor`) and plans only the remainder. The tests below pin that wiring, because a planner
that forgot would silently double-apply the speed-up.
"""
from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from ..game_data import species_stats as ss
from ..tools import iso_patcher as ip

SEC_ADDR = 0x80200000
SEC_LEN = 0x00100000
SEC_FILE = 0x100
DOL_OFF = 0x1000


def _make_iso(path: Path, word_at_target: int = ip.EXP_DIVISOR_EXPECTED_WORD) -> int:
    img = bytearray(DOL_OFF + SEC_FILE + SEC_LEN + 0x100)
    img[0:4] = b"GXXE"
    struct.pack_into(">I", img, ip.DOL_OFFSET_FIELD, DOL_OFF)
    struct.pack_into(">I", img, DOL_OFF + ip.DOL_FILE_OFFSETS, SEC_FILE)
    struct.pack_into(">I", img, DOL_OFF + ip.DOL_LOAD_ADDRESSES, SEC_ADDR)
    struct.pack_into(">I", img, DOL_OFF + ip.DOL_SECTION_SIZES, SEC_LEN)
    target_file = DOL_OFF + SEC_FILE + (ip.EXP_DIVISOR_ADDRESS - SEC_ADDR)
    struct.pack_into(">I", img, target_file, word_at_target)
    path.write_bytes(bytes(img))
    return target_file


class TestTheInstructionIsWhatTheDisassemblySays(unittest.TestCase):
    def test_the_word_replaced_is_li_r0_seven(self) -> None:
        word = ip.EXP_DIVISOR_EXPECTED_WORD
        self.assertEqual(0x38000007, word)
        self.assertEqual(14, word >> 26, "PowerPC opcode 14 is addi, which is `li` when rA is 0")
        self.assertEqual(0, (word >> 21) & 31, "rD = r0")
        self.assertEqual(0, (word >> 16) & 31, "rA = 0, so this is a load-immediate")
        self.assertEqual(7, word & 0xFFFF)

    def test_only_the_immediate_ever_changes(self) -> None:
        for divisor in range(1, 8):
            word = ip.exp_divisor_word(divisor)
            self.assertEqual(ip.EXP_DIVISOR_EXPECTED_WORD & 0xFFFF0000, word & 0xFFFF0000)
            self.assertEqual(divisor, word & 0xFFFF)

    def test_the_vanilla_divisor_round_trips(self) -> None:
        self.assertEqual(ip.EXP_DIVISOR_EXPECTED_WORD, ip.exp_divisor_word(ss.EXP_DIVISOR_VANILLA))


class TestTheRefusalLogic(unittest.TestCase):
    def test_a_sane_divisor_on_the_right_word_is_accepted(self) -> None:
        for divisor in range(1, 8):
            self.assertIsNone(ip.exp_divisor_refusal(ip.EXP_DIVISOR_EXPECTED_WORD, divisor), divisor)

    def test_zero_is_refused_because_divw_by_zero_is_undefined(self) -> None:
        self.assertIsNotNone(ip.exp_divisor_refusal(ip.EXP_DIVISOR_EXPECTED_WORD, 0))

    def test_a_divisor_above_seven_is_refused_because_it_would_slow_the_game_down(self) -> None:
        for divisor in (8, 9, 100):
            self.assertIsNotNone(ip.exp_divisor_refusal(ip.EXP_DIVISOR_EXPECTED_WORD, divisor), divisor)

    def test_a_negative_divisor_is_refused(self) -> None:
        self.assertIsNotNone(ip.exp_divisor_refusal(ip.EXP_DIVISOR_EXPECTED_WORD, -1))

    def test_any_other_word_at_the_address_is_refused(self) -> None:
        """A wrong build, a wrong region, or a wrong address. All three look the same from here, and all
        three mean the next four bytes are not ours to overwrite."""
        for other in (0x4E800020, 0x38000006, 0x38200007, 0x7C0303D6, 0x00000000):
            self.assertIsNotNone(ip.exp_divisor_refusal(other, 1), hex(other))


class TestAgainstARealDolShapedImage(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="a384_"))

    def test_a_good_image_is_patched_and_read_back(self) -> None:
        iso = self.dir / "good.iso"
        target = _make_iso(iso)
        result = ip.write_exp_divisor_patch(iso, 2)
        self.assertTrue(result["applied"], result["reason"])
        self.assertEqual(target, result["file_offset"])
        self.assertEqual(ip.EXP_DIVISOR_EXPECTED_WORD, result["original"])
        self.assertEqual(ip.exp_divisor_word(2), struct.unpack_from(">I", iso.read_bytes(), target)[0])

    def test_nothing_else_in_the_image_moves(self) -> None:
        iso = self.dir / "one.iso"
        target = _make_iso(iso)
        before = bytearray(iso.read_bytes())
        ip.write_exp_divisor_patch(iso, 1)
        after = iso.read_bytes()
        changed = [i for i in range(len(after)) if after[i] != before[i]]
        self.assertTrue(set(changed) <= set(range(target, target + 4)), changed[:8])

    def test_a_wrong_build_is_refused_and_left_byte_identical(self) -> None:
        iso = self.dir / "wrong.iso"
        _make_iso(iso, word_at_target=0x4E800020)
        before = iso.read_bytes()
        result = ip.write_exp_divisor_patch(iso, 1)
        self.assertFalse(result["applied"])
        self.assertIsNotNone(result["reason"])
        self.assertEqual(before, iso.read_bytes())

    def test_patching_twice_is_idempotent_not_an_error(self) -> None:
        iso = self.dir / "twice.iso"
        _make_iso(iso)
        self.assertTrue(ip.write_exp_divisor_patch(iso, 3)["applied"])
        after_once = iso.read_bytes()
        second = ip.write_exp_divisor_patch(iso, 3)
        self.assertTrue(second["applied"])
        self.assertEqual("already patched", second["reason"])
        self.assertEqual(after_once, iso.read_bytes())

    def test_a_missing_file_is_a_reason_not_a_crash(self) -> None:
        result = ip.write_exp_divisor_patch(self.dir / "nope.iso", 2)
        self.assertFalse(result["applied"])
        self.assertIsNotNone(result["reason"])


class TestChoosingTheDivisor(unittest.TestCase):
    def test_vanilla_asks_for_no_patch_at_all(self) -> None:
        self.assertEqual(ss.EXP_DIVISOR_VANILLA, ss.choose_exp_divisor(100))

    def test_it_never_overshoots_what_the_player_asked_for(self) -> None:
        for rate in range(100, ss.RATE_MAX + 1, 5):
            divisor = ss.choose_exp_divisor(rate)
            self.assertLessEqual(ss.divisor_speedup(divisor), rate / ss.RATE_SCALE + 1e-9, rate)

    def test_it_never_goes_outside_the_range_the_writer_accepts(self) -> None:
        for rate in range(0, 3000, 17):
            divisor = ss.choose_exp_divisor(rate)
            self.assertIsNone(ip.exp_divisor_refusal(ip.EXP_DIVISOR_EXPECTED_WORD, divisor), rate)

    def test_it_is_monotonic(self) -> None:
        last = 0.0
        for rate in range(100, ss.RATE_MAX + 1):
            speedup = ss.divisor_speedup(ss.choose_exp_divisor(rate))
            self.assertGreaterEqual(speedup, last, rate)
            last = speedup

    def test_the_exact_rates_land_exactly(self) -> None:
        """7/N for integer N. At these the tables are asked for nothing and nothing is clamped.

        Rounded UP, because the chooser refuses to overshoot: 7/3 is 2.3333x, so a request for 233%
        correctly settles for 4 and lets the tables cover the rest."""
        import math
        for divisor in range(1, 8):
            rate = math.ceil(ss.EXP_DIVISOR_VANILLA / divisor * ss.RATE_SCALE)
            self.assertEqual(divisor, ss.choose_exp_divisor(rate), rate)

    def test_it_settles_for_less_rather_than_overshooting(self) -> None:
        """One percent under an exact rate must drop a rung, not round up into more exp than asked."""
        self.assertEqual(4, ss.choose_exp_divisor(233))
        self.assertEqual(3, ss.choose_exp_divisor(234))

    def test_seven_hundred_percent_is_the_whole_way_down_to_one(self) -> None:
        self.assertEqual(1, ss.choose_exp_divisor(700))
        self.assertEqual(1, ss.choose_exp_divisor(ss.RATE_MAX))

    def test_the_speedup_of_the_vanilla_divisor_is_exactly_one(self) -> None:
        self.assertEqual(1.0, ss.divisor_speedup(ss.EXP_DIVISOR_VANILLA))


class TestThePlannerIsToldWhatTheDivisorAlreadyBought(unittest.TestCase):
    """ADDENDA 243/257: two sources of truth is the bug. Both levers multiply, so the tables must plan
    the REMAINDER or the seed delivers the square of what the player asked for."""

    def setUp(self) -> None:
        self.species = {i: (60 + (i % 40), i % 6) for i in range(1, 300)}

    def test_a_rate_the_divisor_covers_completely_writes_no_bytes(self) -> None:
        for rate, divisor in ((200, 3), (350, 2), (700, 1)):
            plan = ss.plan_experience_rate(self.species, rate, from_divisor=ss.divisor_speedup(divisor))
            self.assertEqual({}, plan["base_exp"], rate)
            self.assertEqual({}, plan["exp_rate"], rate)
            self.assertEqual(1.0, plan["achieved_mean"], rate)

    def test_only_the_remainder_is_asked_of_the_tables(self) -> None:
        plan = ss.plan_experience_rate(self.species, 1000, from_divisor=ss.divisor_speedup(1))
        self.assertLess(plan["achieved_mean"], 1000 / 700 + 0.05)

    def test_the_two_levers_multiply_to_about_what_was_asked(self) -> None:
        for rate in (150, 250, 400, 700, 850, 1000):
            divisor = ss.choose_exp_divisor(rate)
            speedup = ss.divisor_speedup(divisor)
            plan = ss.plan_experience_rate(self.species, rate, from_divisor=speedup)
            delivered = speedup * plan["achieved_mean"]
            self.assertGreater(delivered, rate / ss.RATE_SCALE * 0.95, rate)
            self.assertLess(delivered, rate / ss.RATE_SCALE * 1.02, rate)

    def test_forgetting_to_pass_it_would_be_caught(self) -> None:
        """The failure this wiring exists to prevent, asserted as a difference rather than trusted."""
        forgotten = ss.plan_experience_rate(self.species, 700)["achieved_mean"]
        remembered = ss.plan_experience_rate(self.species, 700, from_divisor=7.0)["achieved_mean"]
        self.assertGreater(forgotten, 2.0)
        self.assertEqual(1.0, remembered)


class TestTheWiring(unittest.TestCase):
    def test_the_world_puts_the_divisor_in_the_seed(self) -> None:
        source = Path(__file__).resolve().parent.parent / "__init__.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn('seed_data["exp_divisor"] = choose_exp_divisor(', text)

    def test_the_patcher_reads_it_back_out_and_tells_the_planner(self) -> None:
        source = Path(__file__).resolve().parent.parent / "tools" / "iso_patcher.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn('from_divisor=species_stats.divisor_speedup(int(seed.get("exp_divisor") or 7))', text)
        self.assertIn("write_exp_divisor_patch(output_path, exp_divisor)", text)

    def test_a_seed_without_the_key_is_vanilla_rather_than_a_crash(self) -> None:
        """Old seeds predate this option. `or 7` is the whole compatibility story; pin it."""
        for seed in ({}, {"exp_divisor": None}, {"exp_divisor": 0}):
            self.assertEqual(7, int(seed.get("exp_divisor") or 7))


if __name__ == "__main__":
    unittest.main()
