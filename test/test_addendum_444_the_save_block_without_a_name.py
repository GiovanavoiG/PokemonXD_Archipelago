"""ADDENDUM 444 (2026-10-09) -- finding the save block without the trainer name.

The yaml name size can grow without losing the search for the player block.
"""
from __future__ import annotations

import glob
import os
import struct
import unittest
from pathlib import Path
from types import SimpleNamespace

from .. import ram_client as rc

DUMPS = "/mnt/user-data/uploads/PokemonXD-working/bridge/dumps"
CLIENT = (Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")


def _mem(blocks: "dict[int, str]", pointer_to: "int | None" = None, money: int = 1234) -> bytes:
    mem = bytearray(rc.MEM1_SIZE)
    for block, name in blocks.items():
        off = block - rc.RECORD_TRAINER_NAME_OFFSET - rc.MEM1_START
        encoded = name.encode("utf-16-be")
        mem[off:off + len(encoded)] = encoded
        struct.pack_into(">I", mem, block + rc.MONEY_OFFSET - rc.MEM1_START, money)
        marker = block + rc.MONEY_DISPLAY_MARKER_OFFSET - rc.MEM1_START
        mem[marker:marker + 8] = b"\x01" * 8
    if pointer_to is not None:
        struct.pack_into(">I", mem, rc.SAVEDATA_NOW_POINTER - rc.MEM1_START,
                         pointer_to - rc.SAVEDATA_HERO_OFFSET - rc.RECORD_TRAINER_NAME_OFFSET)
    return bytes(mem)


class _WithMem(unittest.TestCase):
    def setUp(self):
        self._dump = rc.dump_mem1

    def tearDown(self):
        rc.dump_mem1 = self._dump

    def resolve(self, mem, landmark=None):
        rc.dump_mem1 = lambda: mem
        return rc.resolve_block_base(landmark)


class TestNoNameNeeded(_WithMem):
    def test_the_games_pointer_first(self):
        mem = _mem({0x804794C0: "Gio"}, pointer_to=0x804794C0)
        self.assertEqual(0x804794C0, self.resolve(mem))
        self.assertEqual(0x804794C0, self.resolve(mem, "AVeryLongSlotName"), "the slot name does not matter")

    def test_the_marker_scan_without_a_pointer(self):
        mem = _mem({0x80479100: "MICHAEL"})
        self.assertEqual(0x80479100, self.resolve(mem))
        self.assertEqual(0x80479100, self.resolve(mem, "SomeoneElse"))

    def test_the_mirror_and_look_alikes_are_out_of_range(self):
        mem = _mem({0x80479100: "Gioig", 0x804A17EC: "Gioig", 0x80B5018C: "2"})
        self.assertEqual([0x80479100], rc.find_block_base_candidates(mem))
        self.assertEqual(0x80479100, self.resolve(mem))

    def test_an_unreadable_name_is_not_a_block(self):
        mem = _mem({0x80479100: "襉쀀"})
        self.assertEqual([], rc.find_block_base_candidates(mem))

    def test_a_tie_is_broken_by_the_slot_name(self):
        mem = _mem({0x80478F00: "ASH", 0x80479100: "MISTY"})
        self.assertEqual(0x80479100, self.resolve(mem, "MISTY"))
        self.assertEqual(0x80478F00, self.resolve(mem, None))

    def test_a_pointer_to_nothing_falls_through(self):
        mem = _mem({0x80479100: "Gio"}, pointer_to=0x80300000)
        self.assertEqual(0x80479100, self.resolve(mem))

    def test_nothing_in_game_yet(self):
        self.assertIsNone(self.resolve(bytes(rc.MEM1_SIZE)))
        self.assertIsNone(self.resolve(bytes(rc.MEM1_SIZE), "Gio"))

    def test_the_name_reads_back(self):
        mem = _mem({0x80479100: "Gioig"})
        self.assertEqual("Gioig", rc.trainer_name_at(mem, 0x80479100))


class TestTheClient(unittest.TestCase):
    def test_own_names_come_from_the_save(self):
        from .. import Client
        self.assertEqual({"Gioig"}, Client.own_trainer_names(SimpleNamespace(trainer_name="Gioig", auth="Long Slot Name")))
        self.assertEqual({"Slot"}, Client.own_trainer_names(SimpleNamespace(trainer_name=None, auth="Slot")))
        self.assertEqual(set(), Client.own_trainer_names(SimpleNamespace(trainer_name=None, auth=None)))

    def test_wired(self):
        self.assertIn("ctx.trainer_name = ram_client.read_trainer_name(ctx.block_base) or None", CLIENT)
        self.assertIn("exclude = set(own_trainer_names(ctx))", CLIENT)
        self.assertNotIn("matches your Archipelago slot name exactly", CLIENT)


_REAL = [f for f in sorted(glob.glob(os.path.join(DUMPS, "*.bin"))) if os.path.getsize(f) == rc.MEM1_SIZE]


@unittest.skipUnless(_REAL, "needs full MEM1 dumps")
class TestAgainstRealDumps(_WithMem):
    def test_every_dump_agrees_three_ways(self):
        for path in _REAL:
            with self.subTest(os.path.basename(path)):
                mem = open(path, "rb").read()
                pointed = rc._block_base_from_savedata_pointer(mem)
                scanned = rc.find_block_base_candidates(mem)
                self.assertEqual([pointed], scanned, "the pointer and the scan name the same, single block")
                name = rc.trainer_name_at(mem, pointed)
                self.assertEqual(pointed, rc._resolve_block_base_by_name(mem, name), "and the old name search agrees")
                self.assertEqual(pointed, self.resolve(mem, "NotTheTrainerName"))


if __name__ == "__main__":
    unittest.main()
