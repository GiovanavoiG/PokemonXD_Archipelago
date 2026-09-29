"""ADDENDUM 286 (2026-09-19) -- the monotonic witness a crash-redelivery system needs.

Player: "can we look into an 'item snapshot' system that will redeliver items if the game crashes/the user
closes without a reload? I'm open to ideas on how to handle it."

THE GAP, stated plainly: `give_items` commits an index into `given_item_indices` about five seconds after the
Bag quantity confirms, and that set is client-side state in a local file. Nothing in the chain involves the
player SAVING. The client's "delivered" means "the RAM quantity rose"; the player's means "it is in my save
file". A crash between the two loses the item with the client already counting it given, and nothing can
notice afterwards.

WHAT A FIX NEEDS FIRST is a value that lives in the SAVE BLOCK and only ever rises during play. Then "the
live value is lower than the one recorded when we delivered item N" is proof the game went backwards past
that delivery, and the fix is arithmetic rather than guesswork. This file covers the candidate and, more
importantly, pins that NOTHING DEPENDS ON IT YET -- it is printed by `!progress` for confirmation in play and
read by nothing that makes a decision. An unconfirmed offset that quietly becomes load-bearing is the shape
of bug ADDENDUM 255's 0x6E threshold already cost this project a session over.
"""
from __future__ import annotations

import struct
import sys
import types
import unittest
from unittest import mock

if "dolphin_memory_engine" not in sys.modules:
    _stub = types.ModuleType("dolphin_memory_engine")
    _stub.hook = lambda: None
    _stub.un_hook = lambda: None
    _stub.is_hooked = lambda: False
    _stub.read_bytes = lambda address, length: b""
    _stub.write_bytes = lambda address, data: None
    sys.modules["dolphin_memory_engine"] = _stub

import pathlib

from .. import ram_client as rc

BLOCK = 0x80478F00


class TestTheOffset(unittest.TestCase):
    def test_it_sits_just_past_money_and_is_written_down(self) -> None:
        self.assertEqual(0x908, rc.PROGRESS_COUNTER_OFFSET)
        self.assertGreater(rc.PROGRESS_COUNTER_OFFSET, rc.MONEY_OFFSET)

    def test_it_does_not_overlap_the_money_display_marker(self) -> None:
        """`_looks_like_real_block_base` validates a candidate block against that marker, so anything this
        reads near it must not be the marker itself."""
        marker = rc.MONEY_DISPLAY_MARKER_OFFSET
        self.assertFalse(marker <= rc.PROGRESS_COUNTER_OFFSET < marker + 8)


class TestReading(unittest.TestCase):
    def _read(self, value: bytes):
        return mock.patch.object(rc, "read_bytes", lambda address, length: value[:length])

    def test_a_plain_value_reads_back(self) -> None:
        with self._read(struct.pack(">I", 2369)):
            self.assertEqual(2369, rc.read_progress_counter(BLOCK))

    def test_it_reads_from_the_right_address(self) -> None:
        seen = []

        def _read(address, length):
            seen.append((address, length))
            return struct.pack(">I", 7)

        with mock.patch.object(rc, "read_bytes", _read):
            rc.read_progress_counter(BLOCK)
        self.assertEqual([(BLOCK + 0x908, 4)], seen)

    def test_an_unreadable_counter_answers_None_rather_than_zero(self) -> None:
        """Zero would read as "the counter went backwards" to every future caller, which is the one wrong
        answer this can give. ADDENDUM 256's rule for the story byte, applied here before anything depends
        on it."""
        with mock.patch.object(rc, "read_bytes", side_effect=RuntimeError("no dolphin")):
            self.assertIsNone(rc.read_progress_counter(BLOCK))

    def test_an_implausible_value_is_refused(self) -> None:
        with self._read(struct.pack(">I", 0xFFFFFFFF)):
            self.assertIsNone(rc.read_progress_counter(BLOCK))

    def test_zero_is_a_real_answer_not_a_refusal(self) -> None:
        """A brand-new save really does read zero, and that must not be confused with a failed read."""
        with self._read(struct.pack(">I", 0)):
            self.assertEqual(0, rc.read_progress_counter(BLOCK))

    def test_a_short_read_is_refused_rather_than_padded(self) -> None:
        with mock.patch.object(rc, "read_bytes", lambda address, length: b"\x00\x01"):
            self.assertIsNone(rc.read_progress_counter(BLOCK))


class TestTheRealDumpsItWasDerivedFrom(unittest.TestCase):
    """The twelve-dump sequence that found it, replayed. Skipped where the dumps are not present."""

    DUMPS = "/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/"
    #: (file, block base). All from one 104-minute session on 2026-09-02, in play order.
    SEQUENCE = [
        ("mem1_post_chobin.bin", 0x80478F00), ("mem1_post_optbattle.bin", 0x80478F00),
        ("mem1_pre_krane.bin", 0x80478F00), ("mem1_post_oldman.bin", 0x80478F00),
        ("mem1_pre_snag.bin", 0x80478F00), ("mem1_post_snag.bin", 0x80478F00),
        ("mem1_post_battle_end.bin", 0x80478F00), ("mem1_pre_port.bin", 0x80478F00),
        ("mem1_post_kranememo.bin", 0x80478F00), ("mem1_post_zook.bin", 0x80478F00),
        ("mem1_post_eeveestone.bin", 0x80478F00), ("mem1_post_evolve.bin", 0x80478F00),
    ]

    @classmethod
    def setUpClass(cls) -> None:
        cls.values = []
        for name, base in cls.SEQUENCE:
            path = pathlib.Path(cls.DUMPS) / name
            if not path.exists():
                raise unittest.SkipTest(f"{name} not available")
            with open(path, "rb") as handle:
                handle.seek(base - rc.MEM1_START + rc.PROGRESS_COUNTER_OFFSET)
                cls.values.append(struct.unpack(">I", handle.read(4))[0])

    def test_it_never_goes_backwards(self) -> None:
        for earlier, later in zip(self.values, self.values[1:]):
            self.assertLessEqual(earlier, later, f"the counter fell: {self.values}")

    def test_it_really_moves(self) -> None:
        """A value that never changes is not a witness -- it would answer "no rewind" forever."""
        self.assertGreater(self.values[-1], self.values[0])
        self.assertGreaterEqual(len(set(self.values)), 10)

    def test_it_is_counter_shaped_rather_than_a_pointer_or_bitfield(self) -> None:
        for value in self.values:
            self.assertLessEqual(value, rc.PROGRESS_COUNTER_MAX_PLAUSIBLE)

    def test_it_survives_a_reboot_at_its_saved_value(self) -> None:
        """Two later dumps from two further boots, at two different block bases. The counter and money both
        read exactly what they did before the restart -- which is what a field that lives in the save file
        looks like, and is the property the whole idea rests on."""
        after = []
        for name, base in (("mem1_post_restart.bin", 0x80478F40),
                           ("mem1_post_restart2.bin", 0x80479100)):
            path = pathlib.Path(self.DUMPS) / name
            if not path.exists():
                self.skipTest(f"{name} not available")
            with open(path, "rb") as handle:
                handle.seek(base - rc.MEM1_START + rc.PROGRESS_COUNTER_OFFSET)
                after.append(struct.unpack(">I", handle.read(4))[0])
        self.assertEqual([self.values[-1], self.values[-1]], after)


class TestNothingDependsOnItYet(unittest.TestCase):
    """The point of this addendum. An unconfirmed offset must not become load-bearing by accident."""

    @classmethod
    def setUpClass(cls) -> None:
        root = pathlib.Path(__file__).resolve().parent.parent
        cls.client = (root / "Client.py").read_text(encoding="utf-8")
        cls.ram = (root / "ram_client.py").read_text(encoding="utf-8")

    def test_the_only_caller_is_the_diagnostic_command(self) -> None:
        self.assertEqual(1, self.client.count("read_progress_counter("),
                         "this is a diagnostic until it is confirmed in play; a second caller is a decision")
        start = self.client.index("def _cmd_progress")
        end = self.client.index("\n    def ", start + 1)
        self.assertIn("read_progress_counter(", self.client[start:end])

    def test_nothing_inside_ram_client_consumes_it(self) -> None:
        self.assertEqual(1, self.ram.count("def read_progress_counter"))
        self.assertEqual(0, self.ram.count("read_progress_counter(ctx"))

    def test_the_command_says_it_is_unconfirmed(self) -> None:
        start = self.client.index("def _cmd_progress")
        end = self.client.index("\n    def ", start + 1)
        self.assertIn("UNCONFIRMED", self.client[start:end])

    def test_give_items_still_does_not_read_it(self) -> None:
        start = self.client.index("async def give_items")
        end = self.client.index("\nasync def ", start + 1)
        self.assertNotIn("progress_counter", self.client[start:end])


if __name__ == "__main__":
    unittest.main()
