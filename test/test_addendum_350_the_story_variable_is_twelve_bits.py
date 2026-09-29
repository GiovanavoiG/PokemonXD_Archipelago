"""ADDENDUM 350 (2026-09-25): the story byte is eight bits of a twelve-bit variable, and the variable
counts in tens.

Player: "You know how we have that byte bump in cipher lab? I'd like to see if we can avoid it. I wanna load
in at 0x25 and have the cutscenes play but they don't - my guess is the same issues as gonzap."

The guess was right, and it reached further than either of us expected. Field scripts never read the byte at
`STORY_RECORD_OFFSET + STORY_BYTE_OFFSET`. They call builtin 0x85 with the argument 964 -- GS variable 964 --
and that variable is twelve bits wide, of which this project was writing eight.

THE THREE THINGS THIS FILE PINS:

  1. The mapping. `var964 = (u16_be(record+0x00) >> 5) & 0xFFF = (byte << 3) | (record[0x01] >> 5)`,
     derived by disassembling GSflagGet (main.dol GXXE01 0x801A0364) and its worker at 0x801A03E8, and
     confirmed against every full MEM1 dump in the corpus.

  2. The tens rule. Every naturally-saved value in 163 dumps is a multiple of ten, and every value the
     vanilla `S2_building_2F_2` and `D1_out` scripts compare 964 against is a multiple of ten. So roughly one
     byte value in five stands for no state at all, and a floor set to one of those can never be matched.

  3. That nothing this project WRITES is one of those bytes. Three of them were, and each had cost a
     playtest round: Snagem's 0x63, the Cipher Lab's 0x27, and Kaminko's 0x54.

WHY THE OLD FLOORS LOOKED LIKE THEY WORKED, which is the part worth keeping written down. A byte-only write
left the low three bits at whatever the save held, so a byte did not name a value -- it named a RANGE of
eight. Against a `>=` gate an unreachable byte one rung high was a reliable overshoot and the legal byte
below it was a coin flip (Kaminko: 0x54 always cleared 670, 0x53 cleared it three times in eight). Against an
`==` gate nothing was reliable in either direction (Snagem's `hero_main` tests `== 790`; the Cipher Lab's
tests `== 310`). Every report this project received about these floors was true, and every workaround built
on those reports was treating the range, not the value.
"""
import struct
import unittest

from .. import ram_client as rc
from ..game_data import story_bytes as sb


BLOCK = 0x80479380
ADDRESS = BLOCK + rc.STORY_RECORD_OFFSET + rc.STORY_BYTE_OFFSET


class TestTheMapping(unittest.TestCase):
    def test_the_byte_is_the_value_shifted_three(self):
        for value in range(0, 2048, 10):
            self.assertEqual(sb.story_byte_for_value(value), value >> 3)

    def test_a_real_dump_round_trips(self):
        """`gio_after_lovrina.bin`: record+0x00..0x01 = 0x2B 0xC0, story byte 0x2B, variable 350 -- and 350
        is exactly what `win_lovelina_battle` writes to 964 in that map's own script."""
        self.assertEqual((struct.unpack(">H", bytes([0x2B, 0xC0]))[0] >> 5) & 0xFFF, 350)
        self.assertEqual(sb.story_byte_for_value(350), 0x2B)
        self.assertEqual(sb.story_value_for_byte(0x2B), 350)

    def test_the_shift_constants_agree_with_each_other(self):
        self.assertEqual(rc.STORY_VALUE_SHIFT, 5)
        self.assertEqual(sb.STORY_VARIABLE_SHIFT, 3)
        self.assertEqual(rc.STORY_VALUE_NEIGHBOUR_MASK, 0x1F)
        self.assertEqual(rc.STORY_VALUE_STEP, sb.STORY_VARIABLE_STEP)


class TestTheTensRule(unittest.TestCase):
    def test_every_value_a_byte_stands_for_is_a_multiple_of_ten(self):
        for byte in range(0x100):
            value = sb.story_value_for_byte(byte)
            if value is not None:
                self.assertEqual(0, value % 10, hex(byte))
                self.assertEqual(byte, sb.story_byte_for_value(value), hex(byte))

    def test_the_unreachable_bytes_are_the_ones_with_no_multiple_of_ten(self):
        for byte in range(0x100):
            window = range(byte * 8, byte * 8 + 8)
            has_one = any(v % 10 == 0 for v in window)
            self.assertEqual(has_one, sb.byte_is_reachable(byte), hex(byte))

    def test_the_three_floors_this_addendum_retired_are_all_unreachable(self):
        for byte in (0x27, 0x54, 0x63):
            self.assertIsNone(sb.story_value_for_byte(byte), hex(byte))

    def test_the_values_the_vanilla_scripts_test_against(self):
        """Read out of `S2_building_2F_2.fsys` and `D1_out.fsys` (LZSS-decoded from the vanilla ISO), not
        typed from memory. Every one is a multiple of ten and every one round-trips through a real byte."""
        observed = (310, 320, 350, 630, 670, 680, 690, 700, 710, 720, 740, 790, 800, 810, 840, 870, 890, 970)
        for value in observed:
            self.assertEqual(0, value % 10, value)
            byte = sb.story_byte_for_value(value)
            self.assertEqual(value, sb.story_value_for_byte(byte), value)

    def test_every_unreachable_byte_in_the_ladder_is_only_ever_a_passthrough(self):
        """The shape the ladder has to have, and the corroboration that did not come from disassembly.

        Six byte values in this ladder's range stand for no state at all. Every one of them appears ONLY in
        a `passthrough` -- never as a transition's `before` or `after`, never as a floor. That is not a
        coincidence: a passthrough is what the player wrote down when they watched the byte jump by two, and
        a byte jumps by two exactly when the value it skipped was never real.

        (The reverse is not true, and the test says so below: half the passthroughs ARE real rungs, from
        transitions that genuinely cover two story steps. Only one direction of this holds.)"""
        named = {v for t in sb.TRANSITIONS for v in (t.before, t.after)}
        passthroughs = {v for t in sb.TRANSITIONS for v in t.passthrough}
        unreachable = {v for v in named | passthroughs if not sb.byte_is_reachable(v)}
        self.assertEqual({0x45, 0x54, 0x5E, 0x63, 0x68, 0x6D}, unreachable)
        self.assertEqual(set(), unreachable & named,
                         "an unreachable byte has become a transition endpoint -- no event can land there")
        self.assertEqual(unreachable, sb.UNREACHABLE_BYTES_IN_LADDER and set(sb.UNREACHABLE_BYTES_IN_LADDER))

    def test_the_other_passthroughs_are_real_rungs_and_stay(self):
        """0x3D, 0x4B, 0x4D, 0x58, 0x5C and 0x66 all have story values. Their transitions cover two story
        steps each -- 0x65 -> 0x67 is 810 -> 830 -- so those intermediates really were passed through."""
        passthroughs = {v for t in sb.TRANSITIONS for v in t.passthrough}
        real = {v for v in passthroughs if sb.byte_is_reachable(v)}
        self.assertEqual({0x3D, 0x4B, 0x4D, 0x58, 0x5C, 0x66}, real)
        self.assertEqual((810, 820, 830),
                         tuple(sb.story_value_for_byte(b) for b in (0x65, 0x66, 0x67)))


class TestNothingWeWriteIsUnreachable(unittest.TestCase):
    """The fence. Each of these is also asserted at import time in story_bytes; restated here so a failure
    names which table it came from instead of only failing to import."""

    def test_every_window_floor(self):
        for region, window in sb.REGION_STORY_WINDOW.items():
            self.assertTrue(sb.byte_is_reachable(window.floor), f"{region} 0x{window.floor:02X}")

    def test_every_entry_floor_override(self):
        for area, floor in sb.AREA_ENTRY_FLOOR_OVERRIDES.items():
            self.assertTrue(sb.byte_is_reachable(floor), f"{area} 0x{floor:02X}")

    def test_every_area_floor_rule(self):
        for rule in sb.AREA_FLOOR_RULES:
            self.assertTrue(sb.byte_is_reachable(rule.floor), f"{rule.target} 0x{rule.floor:02X}")

    def test_every_live_bump_destination(self):
        for bump in sb.LIVE_STORY_BYTE_BUMPS:
            self.assertTrue(sb.byte_is_reachable(bump.becomes), f"{bump.region} 0x{bump.becomes:02X}")

    def test_the_named_constants_in_the_client(self):
        for name in ("VICTORY_STORY_BYTE", "STORY_OVERRIDE_VALUE", "CITADARK_ENTRY_FLOOR",
                     "GATEON_STORY_CEILING", "SCOOTER_HOLD_FLOOR", "SS_LIBRA_SCOOTER_FLOOR"):
            value = getattr(rc, name, None)
            if value is None:
                continue
            self.assertTrue(sb.byte_is_reachable(value), f"{name} = 0x{value:02X}")


class _Memory:
    """A two-byte window at the story address, so the read-modify-write can be exercised for real."""

    def __init__(self, first: int, second: int) -> None:
        self.cells = bytearray([first, second])
        self.writes: "list[tuple[int, bytes]]" = []

    def install(self, test: unittest.TestCase) -> None:
        test.addCleanup(setattr, rc, "read_bytes", rc.read_bytes)
        test.addCleanup(setattr, rc, "write_bytes", rc.write_bytes)
        rc.read_bytes = self._read
        rc.write_bytes = self._write

    def _read(self, address: int, length: int) -> bytes:
        offset = address - ADDRESS
        if offset < 0 or offset + length > len(self.cells):
            raise ValueError("outside the window this fake models")
        return bytes(self.cells[offset:offset + length])

    def _write(self, address: int, data: bytes) -> None:
        offset = address - ADDRESS
        self.cells[offset:offset + len(data)] = data
        self.writes.append((address, bytes(data)))

    @property
    def value(self) -> int:
        return (struct.unpack(">H", bytes(self.cells))[0] >> 5) & 0xFFF


class TestTheWrite(unittest.TestCase):
    def test_it_sets_the_whole_variable(self):
        memory = _Memory(0x25 * 8 // 8, 0x80)   # some stale low bits
        memory.install(self)
        self.assertTrue(rc.poke_story_byte(BLOCK, 0x26))
        self.assertEqual(310, memory.value)
        self.assertEqual(0x26, memory.cells[0])

    def test_the_stale_low_bits_cannot_survive(self):
        """The bug in one test. Every starting substep must land on the same value."""
        for stale in range(8):
            memory = _Memory(0x24, stale << 5)
            memory.install(self)
            rc.poke_story_byte(BLOCK, 0x62)
            self.assertEqual(790, memory.value, f"stale low bits {stale}")

    def test_the_neighbouring_variables_tail_is_preserved(self):
        """Bits 904..916 are the tail of GS variable 802, which ends where 964 begins. They are 0x00 in all
        155 clean dumps in the corpus, which is exactly why a blind `value << 5` would have looked fine."""
        for tail in (0x00, 0x01, 0x1F, 0x11):
            memory = _Memory(0x00, tail)
            memory.install(self)
            rc.poke_story_byte(BLOCK, 0x26)
            self.assertEqual(310, memory.value)
            self.assertEqual(tail, memory.cells[1] & 0x1F, f"tail 0x{tail:02X}")

    def test_it_writes_two_bytes_at_the_story_address_and_nothing_else(self):
        memory = _Memory(0x00, 0x00)
        memory.install(self)
        rc.poke_story_byte(BLOCK, 0x26)
        self.assertEqual(1, len(memory.writes))
        address, data = memory.writes[0]
        self.assertEqual(ADDRESS, address)
        self.assertEqual(2, len(data))

    def test_an_unreachable_byte_is_written_bare_and_says_so(self):
        """The debug command is the only caller that can reach this. It still writes -- a debug command that
        second-guesses the number typed into it is not a debug command -- but it returns False."""
        memory = _Memory(0x00, 0xE0)
        memory.install(self)
        self.assertFalse(rc.poke_story_byte(BLOCK, 0x27))
        self.assertEqual(0x27, memory.cells[0])
        self.assertEqual(0xE0, memory.cells[1], "the bare write must not disturb the next byte")

    def test_a_failed_read_still_writes(self):
        """`read_bytes` raising must not cost the write -- the low bits are 0x00 in every clean save, so
        assuming them is a far better failure than not writing at all."""
        def _raise(address, length):
            raise RuntimeError("not hooked")
        self.addCleanup(setattr, rc, "read_bytes", rc.read_bytes)
        self.addCleanup(setattr, rc, "write_bytes", rc.write_bytes)
        written: "list[tuple[int, bytes]]" = []
        rc.read_bytes = _raise
        rc.write_bytes = lambda address, data: written.append((address, bytes(data)))
        self.assertTrue(rc.poke_story_byte(BLOCK, 0x26))
        self.assertEqual([(ADDRESS, struct.pack(">H", 310 << 5))], written)


class TestTheReadout(unittest.TestCase):
    """Player: "Can you modify our story byte reporting to include that full value then?\""""

    def _tracker(self, first: int, second: int) -> rc.StoryByteTracker:
        tracker = rc.StoryByteTracker()
        tracker.record = bytes([first, second]) + b"\x00" * 18
        tracker.current = first
        return tracker

    def test_the_value_is_derived_from_the_record_already_read(self):
        self.assertEqual(310, self._tracker(0x26, 0xC0).story_value)
        self.assertEqual(308, self._tracker(0x26, 0x80).story_value)

    def test_story_says_the_value_not_only_the_byte(self):
        text = self._tracker(0x26, 0xC0).describe()
        self.assertIn("0x26", text)
        self.assertIn("310", text)

    def test_a_value_no_script_tests_for_is_called_out(self):
        text = self._tracker(0x26, 0x80).describe()
        self.assertIn("308", text)
        self.assertIn("not a multiple", text.lower())

    def test_a_legal_value_is_not_called_out(self):
        self.assertNotIn("not a multiple", self._tracker(0x26, 0xC0).describe().lower())

    def test_an_unread_record_says_nothing_rather_than_guessing(self):
        self.assertIsNone(rc.StoryByteTracker().story_value)


class TestWhatThisExplains(unittest.TestCase):
    """The three floors, stated as the arithmetic that made each one look right at the time."""

    def test_snagem_needed_an_equality_the_old_floor_could_not_meet(self):
        """`hero_main` in S2_building_2F_2: `if storyvar(964) == 790`."""
        self.assertEqual(790, sb.story_value_for_byte(0x62))
        self.assertNotIn(790, range(0x63 * 8, 0x63 * 8 + 8))
        self.assertEqual(0x62, sb.SNAGEM_BASE_FLOOR)

    def test_the_cipher_lab_needed_one_too(self):
        """`hero_main` in D1_out: `if storyvar(964) == 310`, and `brother_enter` ends `write(964, 320)`."""
        self.assertEqual(310, sb.story_value_for_byte(0x26))
        self.assertEqual(320, sb.story_value_for_byte(0x28))
        self.assertNotIn(310, range(0x27 * 8, 0x27 * 8 + 8))
        self.assertEqual(0x26, sb.area_entry_floor("Cipher Lab"))

    def test_kaminko_was_a_threshold_which_is_why_it_inverted(self):
        """Player: "Kaminko also did not function at 0x53, but did at 0x54."

        Against a `>=` gate at 670 the unreachable byte is a reliable overshoot and the legal one below it is
        a coin flip -- 0x53 meant 664..671, which clears 670 for two of its eight substeps, while 0x54
        meant 672..679, which clears it for all eight. That is the report exactly. It is also why the fix is
        0x53 rather than the next reachable byte up: 0x55 is 680, a different rung entirely."""
        self.assertEqual(670, sb.story_value_for_byte(0x53))
        self.assertEqual(680, sb.story_value_for_byte(0x55))
        self.assertEqual(2, sum(1 for low in range(8) if 0x53 * 8 + low >= 670))
        self.assertEqual(8, sum(1 for low in range(8) if 0x54 * 8 + low >= 670))
        rule = next(r for r in sb.AREA_FLOOR_RULES if r.target == "Kaminko's House")
        self.assertEqual(0x53, rule.floor)
