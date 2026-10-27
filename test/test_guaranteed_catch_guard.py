"""With Guaranteed Catches, the client puts the always-catch code and the 255 catch rates back in a game that lacks
them, never over code it doesn't recognise, and leaves the Shadow rates alone when an exclusion is on."""
from __future__ import annotations

import inspect
import struct
import unittest
from unittest import mock

from .. import Client
from .. import ram_client as rc
from ..game_data import conditional_catch
from ..game_data.item_name_strings import COMMON_REL_RAM_BASE
from ..game_data.wonder_trade_tables import SPECIES
from ..tools import iso_patcher


class _Memory:
    def __init__(self, code_word=rc.ALWAYS_CATCH_VANILLA_WORD, species_rate=45, shadow_rate=120):
        self.mem = bytearray(0x01800000)
        self.put(rc.ALWAYS_CATCH_ADDRESS, struct.pack(">I", code_word))
        for address, vanilla, _new in conditional_catch.dol_patch_words():
            if address != rc.ALWAYS_CATCH_ADDRESS:
                self.put(address, struct.pack(">I", vanilla))
        base = COMMON_REL_RAM_BASE + rc.SPECIES_STATS_REL_OFFSET
        for index, row in SPECIES.items():
            self.put(base + index * 0x124 + 0x0E, struct.pack(">H", row[0]))
            self.put(base + index * 0x124 + 1, bytes([species_rate]))
        self.ddpk = 0x80500000
        self.put(self.ddpk - 0x20, b"DECK")
        self.put(self.ddpk - 0x10, b"DDPK" + struct.pack(">II", 0x60, 4))
        for i in range(1, 4):
            self.put(self.ddpk + i * 0x18, bytes([0, shadow_rate, 10, 0x80 if i < 3 else 0]))

    def put(self, address, data):
        self.mem[address - 0x80000000:address - 0x80000000 + len(data)] = data

    def read(self, address, length):
        return bytes(self.mem[address - 0x80000000:address - 0x80000000 + length])

    def u32(self, address):
        return struct.unpack(">I", self.read(address, 4))[0]

    def patch(self):
        return mock.patch.multiple(rc, read_bytes=self.read, write_bytes=self.put, read_u32=self.u32,
                                   dump_mem1=lambda: bytes(self.mem))


class TestTheGuard(unittest.TestCase):
    def test_constants_match_the_patcher(self) -> None:
        self.assertEqual(iso_patcher.ALWAYS_CATCH_ADDRESS, rc.ALWAYS_CATCH_ADDRESS)
        self.assertEqual(iso_patcher.ALWAYS_CATCH_WORD, rc.ALWAYS_CATCH_WORD)
        self.assertEqual(iso_patcher.ALWAYS_CATCH_EXPECTED_WORD, rc.ALWAYS_CATCH_VANILLA_WORD)

    def test_an_unpatched_game_gets_everything(self) -> None:
        m = _Memory()
        guard = rc.GuaranteedCatchGuard()
        with m.patch():
            notes = guard.poll(False)
            self.assertEqual(rc.ALWAYS_CATCH_WORD, m.u32(rc.ALWAYS_CATCH_ADDRESS))
            base = COMMON_REL_RAM_BASE + rc.SPECIES_STATS_REL_OFFSET
            self.assertTrue(all(m.read(base + i * 0x124 + 1, 1) == b"\xff" for i in SPECIES))
            self.assertEqual(b"\xff", m.read(m.ddpk + 0x18 + 1, 1))
            self.assertEqual(bytes([120]), m.read(m.ddpk + 3 * 0x18 + 1, 1))   # a record not in use stays
            self.assertEqual(3, len(notes))
            self.assertEqual([], guard.poll(False))                            # nothing to do the second time

    def test_unknown_code_is_left_alone(self) -> None:
        m = _Memory(code_word=0x60000000)
        guard = rc.GuaranteedCatchGuard()
        with m.patch():
            notes = guard.poll(False)
            self.assertEqual(0x60000000, m.u32(rc.ALWAYS_CATCH_ADDRESS))
            self.assertIn("left alone", notes[0])

    def test_with_an_exclusion_the_conditional_code_and_no_shadow_rates(self) -> None:
        m = _Memory()
        guard = rc.GuaranteedCatchGuard()
        with m.patch():
            guard.poll(True)
            for address, _vanilla, new in conditional_catch.dol_patch_words():
                self.assertEqual(new, m.u32(address))
            self.assertEqual(bytes([120]), m.read(m.ddpk + 0x18 + 1, 1))

    def test_a_table_that_isnt_the_species_table_is_untouched(self) -> None:
        m = _Memory()
        m.put(COMMON_REL_RAM_BASE + rc.SPECIES_STATS_REL_OFFSET + 0x124 + 0x0E, b"\x00\x00")
        with m.patch():
            self.assertEqual(0, rc.GuaranteedCatchGuard()._species())

    def test_the_client_runs_it_only_with_guaranteed_catches(self) -> None:
        src = inspect.getsource(Client)
        self.assertIn('int(slot_data.get("catch_rate_scaling") or 0) == 2', src)
        self.assertIn("if ctx.catch_guaranteed and time.monotonic() >= ctx._catch_guard_due:", src)


if __name__ == "__main__":
    unittest.main()
