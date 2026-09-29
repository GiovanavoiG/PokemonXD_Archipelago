"""ADDENDUM 340 (2026-09-24): the Snag Machine is two bytes, and neither of them is the story byte.

ADDENDUM 337 excluded Wakin and Gonzap as filler-only because the project could not say how to give or take
the Snag Machine. This session found it: the player opened the bridge standing in front of the pickup, three
full MEM1 dumps were driven through it (two of the identical pre state, one immediately after), and inside
the resolved player-state block the noise between the two identical dumps was ZERO bytes while the pre->post
delta was exactly TWO:

    block +0x00919                        0x00 -> 0x02
    block +0x10732 (story record +0x12)   0x10 -> 0x18  (bit 0x08)

Both bytes were then confirmed against this project's own dump archive in a different save file on a
different boot (BLOCK_BASE 0x80478F00, seventeen days earlier), plus one dump from before the machine exists
and one from deep in the mid-game -- six dumps, three save files, three boots, six-for-six.

WHAT THIS TEST GUARDS, and what it deliberately does not:

  * The six measured (story byte, +0x919, record +0x12) observations are pinned here as a table, so the
    constants can never be edited to something the dumps do not support.
  * `write_snag_machine` must be READ-MODIFY-WRITE at both sites. Record +0x12 lives inside the SAME twenty
    bytes as the travel-unlock bits (travel_locations.TRAVEL_LOCATION_BITS), so a blind byte write there
    would silently relock or unlock map destinations. That is the real bug this file exists to prevent.
  * `read_snag_machine` must return None -- "don't know" -- when the two sites disagree, rather than picking
    a favourite.
  * It does NOT assert that Wakin and Gonzap have been un-excluded. The correlation is six-for-six and the
    write sticks through live play, but nobody has yet walked into a Shadow battle with these bytes cleared
    and confirmed the Snag option is gone. Until that happens ADDENDUM 337's exclusion stands, and the last
    test here pins that it still does.

WHY THIS TEST STUBS `dolphin_memory_engine`: same reason as test_addendum_108_berry_pocket_routing.py --
`ram_client.py` imports it at module level and the real package is not installable in every environment this
project's tests run in. Here the stub is not merely inert: it is a tiny fake memory, so the read-modify-write
behaviour can be asserted for real rather than by reading the source.
"""
from __future__ import annotations

import sys
import types
import unittest

if "dolphin_memory_engine" not in sys.modules:
    _stub = types.ModuleType("dolphin_memory_engine")
    _stub.hook = lambda: None
    _stub.un_hook = lambda: None
    _stub.is_hooked = lambda: False
    _stub.read_bytes = lambda address, length: b""
    _stub.write_bytes = lambda address, data: None
    sys.modules["dolphin_memory_engine"] = _stub

from .. import ram_client, travel_locations


BLOCK_BASE = 0x804795C0

# (label, story byte, +0x919, record +0x12, owned) -- every row is a real dump this session read, named so a
# future reader can go back to the file itself. Do not edit a row without a dump to back it.
MEASURED = (
    ("mem1_pre_pda",                  0x02, 0x00, 0x00, False),
    ("mem1_post_kraneconvo_pre_snag", 0x0A, 0x00, 0x14, False),
    ("mem1_post_snag",                0x0A, 0x02, 0x1C, True),
    ("snagmachine_pre_a",             0x0A, 0x00, 0x10, False),
    ("snagmachine_pre_b",             0x0A, 0x00, 0x10, False),
    ("snagmachine_post",              0x0A, 0x02, 0x18, True),
    ("gio_after_lovrina",             0x2B, 0x02, 0x19, True),
)


class _FakeMemory:
    """A byte-addressed sparse memory that records every write, so a blind byte write is visibly different
    from a read-modify-write instead of having to be taken on trust."""

    def __init__(self, initial: "dict[int, int] | None" = None):
        self.cells: "dict[int, int]" = dict(initial or {})
        self.writes: "list[tuple[int, bytes]]" = []

    def read_bytes(self, address: int, length: int) -> bytes:
        return bytes(self.cells.get(address + i, 0) for i in range(length))

    def write_bytes(self, address: int, data: bytes) -> None:
        self.writes.append((address, bytes(data)))
        for i, value in enumerate(data):
            self.cells[address + i] = value

    def install(self, test: unittest.TestCase) -> None:
        dme = sys.modules["dolphin_memory_engine"]
        for name in ("read_bytes", "write_bytes"):
            test.addCleanup(setattr, dme, name, getattr(dme, name))
        dme.read_bytes = self.read_bytes
        dme.write_bytes = self.write_bytes


def _flag_address() -> int:
    return BLOCK_BASE + ram_client.SNAG_MACHINE_FLAG_OFFSET


def _record_address() -> int:
    return (BLOCK_BASE + ram_client.STORY_RECORD_OFFSET
            + ram_client.SNAG_MACHINE_RECORD_BYTE_OFFSET)


def _memory_for(flag: int, record: int) -> _FakeMemory:
    return _FakeMemory({_flag_address(): flag, _record_address(): record})


class TestConstantsMatchTheDumps(unittest.TestCase):
    def test_offsets_are_the_measured_ones(self):
        self.assertEqual(ram_client.SNAG_MACHINE_FLAG_OFFSET, 0x919)
        self.assertEqual(ram_client.SNAG_MACHINE_FLAG_BIT, 0x02)
        self.assertEqual(ram_client.SNAG_MACHINE_RECORD_BYTE_OFFSET, 0x12)
        self.assertEqual(ram_client.SNAG_MACHINE_RECORD_BIT, 0x08)

    def test_record_byte_is_inside_the_story_record(self):
        self.assertLess(ram_client.SNAG_MACHINE_RECORD_BYTE_OFFSET, ram_client.STORY_RECORD_SIZE)

    def test_flag_offset_is_inside_the_block_and_clear_of_every_named_field(self):
        offset = ram_client.SNAG_MACHINE_FLAG_OFFSET
        self.assertLess(offset, ram_client.STORY_RECORD_OFFSET)
        # The nearest named neighbours below it. Money is 4 bytes; the step counter is 4 bytes.
        self.assertGreater(offset, ram_client.MONEY_OFFSET + 4)
        self.assertGreater(offset, ram_client.STEP_COUNTER_OFFSET + 4)

    def test_every_measured_dump_agrees_with_the_constants(self):
        for label, _story, flag, record, owned in MEASURED:
            with self.subTest(dump=label):
                self.assertEqual(bool(flag & ram_client.SNAG_MACHINE_FLAG_BIT), owned)
                self.assertEqual(bool(record & ram_client.SNAG_MACHINE_RECORD_BIT), owned)

    def test_the_two_sites_never_disagreed_in_any_dump(self):
        for label, _story, flag, record, _owned in MEASURED:
            with self.subTest(dump=label):
                self.assertEqual(bool(flag & ram_client.SNAG_MACHINE_FLAG_BIT),
                                 bool(record & ram_client.SNAG_MACHINE_RECORD_BIT))

    def test_the_story_byte_is_not_the_signal(self):
        """The whole point: three dumps share story byte 0x0A and disagree about the machine."""
        at_0a = [row for row in MEASURED if row[1] == 0x0A]
        self.assertGreaterEqual(len(at_0a), 3)
        self.assertEqual({row[4] for row in at_0a}, {True, False})

    def test_the_record_byte_is_not_a_travel_unlock_byte(self):
        """If +0x12 were a travel byte, writing it would be someone else's business. It is not."""
        claimed = {bit.byte_offset for bit in travel_locations.TRAVEL_LOCATION_BITS.values()}
        claimed |= {bit.byte_offset for bit in travel_locations.ALWAYS_OPEN_TRAVEL_BITS.values()}
        self.assertNotIn(ram_client.SNAG_MACHINE_RECORD_BYTE_OFFSET, claimed)


class TestReadSnagMachine(unittest.TestCase):
    def test_reads_true_when_both_sites_are_set(self):
        _memory_for(0x02, 0x18).install(self)
        self.assertIs(ram_client.read_snag_machine(BLOCK_BASE), True)

    def test_reads_false_when_both_sites_are_clear(self):
        _memory_for(0x00, 0x10).install(self)
        self.assertIs(ram_client.read_snag_machine(BLOCK_BASE), False)

    def test_every_measured_dump_reads_back_its_own_answer(self):
        for label, _story, flag, record, owned in MEASURED:
            with self.subTest(dump=label):
                _memory_for(flag, record).install(self)
                self.assertIs(ram_client.read_snag_machine(BLOCK_BASE), owned)

    def test_a_split_read_is_none_not_a_guess(self):
        for flag, record in ((0x02, 0x10), (0x00, 0x18)):
            with self.subTest(flag=flag, record=record):
                _memory_for(flag, record).install(self)
                self.assertIsNone(ram_client.read_snag_machine(BLOCK_BASE))

    def test_an_unreadable_block_is_none_not_false(self):
        dme = sys.modules["dolphin_memory_engine"]
        self.addCleanup(setattr, dme, "read_bytes", dme.read_bytes)

        def boom(address, length):
            raise RuntimeError("not hooked")

        dme.read_bytes = boom
        self.assertIsNone(ram_client.read_snag_machine(BLOCK_BASE))

    def test_ignores_the_other_bits_of_the_record_byte(self):
        """0x14 and 0x10 are both "not owned" and 0x1C and 0x18 are both "owned" -- the neighbours differ
        between save files and must not change the answer."""
        for record, owned in ((0x14, False), (0x10, False), (0x1C, True), (0x18, True), (0x19, True)):
            with self.subTest(record=record):
                _memory_for(0x02 if owned else 0x00, record).install(self)
                self.assertIs(ram_client.read_snag_machine(BLOCK_BASE), owned)


class TestWriteSnagMachine(unittest.TestCase):
    def _run(self, flag: int, record: int, owned: bool):
        memory = _memory_for(flag, record)
        memory.install(self)
        ok = ram_client.write_snag_machine(BLOCK_BASE, owned)
        return ok, memory

    def test_giving_it_sets_both_sites(self):
        ok, memory = self._run(0x00, 0x10, True)
        self.assertTrue(ok)
        self.assertEqual(memory.cells[_flag_address()], 0x02)
        self.assertEqual(memory.cells[_record_address()], 0x18)

    def test_taking_it_clears_both_sites(self):
        ok, memory = self._run(0x02, 0x18, False)
        self.assertTrue(ok)
        self.assertEqual(memory.cells[_flag_address()], 0x00)
        self.assertEqual(memory.cells[_record_address()], 0x10)

    def test_the_record_write_preserves_every_neighbouring_bit(self):
        """THE bug this file exists to prevent: +0x12 shares a byte with bits that differ per save file, and
        its record shares twenty bytes with the travel-unlock bits."""
        for start in range(0x100):
            with self.subTest(record=start):
                _, memory = self._run(0x00, start, True)
                written = memory.cells[_record_address()]
                self.assertEqual(written & ~ram_client.SNAG_MACHINE_RECORD_BIT & 0xFF,
                                 start & ~ram_client.SNAG_MACHINE_RECORD_BIT & 0xFF)
                self.assertTrue(written & ram_client.SNAG_MACHINE_RECORD_BIT)

    def test_the_clear_also_preserves_every_neighbouring_bit(self):
        for start in range(0x100):
            with self.subTest(record=start):
                _, memory = self._run(0x02, start, False)
                written = memory.cells[_record_address()]
                self.assertEqual(written & ~ram_client.SNAG_MACHINE_RECORD_BIT & 0xFF,
                                 start & ~ram_client.SNAG_MACHINE_RECORD_BIT & 0xFF)
                self.assertFalse(written & ram_client.SNAG_MACHINE_RECORD_BIT)

    def test_the_flag_byte_write_is_also_masked(self):
        _, memory = self._run(0xF0, 0x10, True)
        self.assertEqual(memory.cells[_flag_address()], 0xF2)
        _, memory = self._run(0xF2, 0x18, False)
        self.assertEqual(memory.cells[_flag_address()], 0xF0)

    def test_it_writes_exactly_two_bytes_and_only_the_two(self):
        _, memory = self._run(0x00, 0x10, True)
        self.assertEqual(len(memory.writes), 2)
        self.assertEqual({address for address, _ in memory.writes},
                         {_flag_address(), _record_address()})
        for _address, data in memory.writes:
            self.assertEqual(len(data), 1)

    def test_a_write_round_trips_through_the_reader(self):
        memory = _memory_for(0x00, 0x14)
        memory.install(self)
        self.assertIs(ram_client.read_snag_machine(BLOCK_BASE), False)
        self.assertTrue(ram_client.write_snag_machine(BLOCK_BASE, True))
        self.assertIs(ram_client.read_snag_machine(BLOCK_BASE), True)
        self.assertEqual(memory.cells[_record_address()], 0x1C)
        self.assertTrue(ram_client.write_snag_machine(BLOCK_BASE, False))
        self.assertIs(ram_client.read_snag_machine(BLOCK_BASE), False)
        self.assertEqual(memory.cells[_record_address()], 0x14)

    def test_writing_what_is_already_there_is_a_no_op_in_value(self):
        _, memory = self._run(0x02, 0x18, True)
        self.assertEqual(memory.cells[_flag_address()], 0x02)
        self.assertEqual(memory.cells[_record_address()], 0x18)

    def test_a_failed_write_reports_false_rather_than_raising(self):
        memory = _memory_for(0x00, 0x10)
        memory.install(self)
        dme = sys.modules["dolphin_memory_engine"]

        def boom(address, data):
            raise RuntimeError("not hooked")

        dme.write_bytes = boom
        self.assertFalse(ram_client.write_snag_machine(BLOCK_BASE, True))


class TestAddendum337ExclusionWasLifted(unittest.TestCase):
    """RETARGETED BY ADDENDUM 341.

    This class used to assert Wakin and Gonzap stayed filler-only until an in-battle test happened. That test
    happened, and it went the other way: removing the Snag Machine changed nothing, because the encounter is
    gated by a global story variable and a script flag, not by the machine. ADDENDUM 341 patches the script
    instead and the fights work, so the ruling is lifted.

    What ADDENDUM 340 measured is untouched by that -- the two bytes are still the Snag Machine, and the
    tests above still pin them. What it could NOT establish is settled here in the negative: the two bytes are
    written when the game grants the machine, and nothing observed reads them back."""

    def test_the_ruling_is_lifted_and_the_set_is_empty(self):
        from ..game_data import missable_trainers

        self.assertEqual(missable_trainers.SNAG_MACHINE_BLOCKED_TRAINER_INDICES, frozenset())

    def test_wakin_and_gonzap_are_ordinary_trainers_again(self):
        from ..game_data import missable_trainers

        for index in (144, 145):
            self.assertNotIn(index, missable_trainers.FILLER_ONLY_TRAINER_INDICES, index)
            self.assertNotIn(index, missable_trainers.MISSABLE_TRAINER_INDICES, index)

    def test_removing_the_snag_machine_is_not_what_unblocks_them(self):
        """The negative result, pinned so it is not re-attempted. Tested live: with the machine removed at
        both ADDENDUM 340 sites, the fight still did not start."""
        from ..game_data import missable_trainers

        self.assertFalse(missable_trainers.SNAG_MACHINE_BLOCKED_TRAINER_INDICES,
                         "the Snag Machine ruling is lifted; do not re-fence on that reasoning")


if __name__ == "__main__":
    unittest.main()
