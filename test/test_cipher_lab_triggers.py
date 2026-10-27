"""The Cipher Lab's trainers fight at any story point; nothing writes the story value."""
from __future__ import annotations

import struct
import unittest
from unittest import mock

from .. import ram_client as rc
from ..game_data import cipher_lab_scripts as cl
from .local_dumps import cipher_lab_script

BASE = 0x80900000


def _specs():
    return {s.name: s for s in rc.npc_script_specs() if s.area == "Cipher Lab"}


class _Memory:
    def __init__(self, blob: bytes) -> None:
        self.mem = bytearray(blob)
        self.writes: "list[tuple[int, bytes]]" = []

    def read(self, address, length):
        return bytes(self.mem[address - BASE:address - BASE + length])

    def write(self, address, data):
        self.writes.append((address, bytes(data)))
        self.mem[address - BASE:address - BASE + len(data)] = data


class TestTheTables(unittest.TestCase):
    def test_every_floor_is_a_spec(self) -> None:
        self.assertEqual({"Cipher Lab 1F", "Cipher Lab B1", "Cipher Lab B2", "Cipher Lab B3"}, set(_specs()))

    def test_no_edit_writes_the_story_variable(self) -> None:
        for _name, _size, _code0, edits, _anchors, _guard in cl.CIPHER_LAB_FLOORS:
            for _word, _stock, patched in edits:
                self.assertNotEqual(0x09000083, patched)   # callstd 0.0x83, setVar

    def test_only_b2_needs_a_guard(self) -> None:
        self.assertEqual({"Cipher Lab B2"}, {n for n, s in _specs().items() if s.guard})


class TestOnTheRealScripts(unittest.TestCase):
    def setUp(self) -> None:
        self.blobs = {f: cipher_lab_script(f) for f in ("1F", "B1", "B2", "B3")}
        if not all(self.blobs.values()):
            self.skipTest("the Cipher Lab script dumps are not on this machine")

    def _patch(self, floor: str):
        spec = _specs()[f"Cipher Lab {floor}"]
        memory = _Memory(self.blobs[floor])
        with mock.patch.object(rc, "read_bytes", memory.read), mock.patch.object(rc, "write_bytes", memory.write), \
                mock.patch.object(rc.time, "sleep", lambda _s: None):
            written = rc.patch_npc_script(BASE, spec)
            again = rc.patch_npc_script(BASE, spec)
        return spec, memory, written, again

    def test_the_stock_scripts_match_and_patch_once(self) -> None:
        for floor in ("1F", "B1", "B2", "B3"):
            spec, memory, written, again = self._patch(floor)
            self.assertEqual(len(spec.patches), written, floor)
            self.assertEqual(0, again, floor)
            for offset, _stock, patched in spec.patches:
                self.assertEqual(patched, memory.mem[offset], floor)

    def test_the_b2_guard_is_put_back(self) -> None:
        spec, memory, _written, _again = self._patch("B2")
        offset, stock, guarded = spec.guard
        self.assertEqual(stock, memory.mem[offset])
        self.assertEqual(guarded, memory.writes[0][1][0], "the guard goes first")
        self.assertEqual((BASE + offset, bytes((stock,))), memory.writes[-1], "and is put back last")

    def test_the_b2_block_is_written_in_one_go(self) -> None:
        _spec, memory, _written, _again = self._patch("B2")
        self.assertLessEqual(len(memory.writes), 5)

    def test_solox_waits_for_lovrinas_scene_and_naps_keeps_his_window(self) -> None:
        _spec, memory, _w, _a = self._patch("B2")
        code0 = cl._B2_CODE0
        words = [struct.unpack_from(">I", memory.mem, code0 + 4 * i)[0] for i in range(565, 625)]
        self.assertIn(0x0000014A, words)   # 330 <= S
        self.assertIn(0x00000154, words)   # S < 340, Naps only
        self.assertIn(0x07000522, words)   # call talk_113_agent1_m (Solox)
        self.assertIn(0x07000632, words)   # call the Naps/Klein event
        self.assertEqual(0x0C000235, struct.unpack_from(">I", memory.mem, code0 + 4 * 564)[0])


if __name__ == "__main__":
    unittest.main()
