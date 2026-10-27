"""Trainer beaten flags as a second witness for defeats, and Citadark's 890-900 windows."""
from __future__ import annotations

import struct
import unittest
from types import SimpleNamespace
from unittest import mock

from .. import Client
from .. import ram_client as rc
from ..game_data import citadark_scripts as cd
from ..game_data import trainer_roster
from ..game_data.trainer_beaten_flags import TRAINER_BEATEN_FLAGS
from .local_dumps import map_script

STORAGE = 0x80500000


class TestTheTable(unittest.TestCase):
    def test_one_flag_per_trainer(self) -> None:
        self.assertEqual(len(TRAINER_BEATEN_FLAGS), len(set(TRAINER_BEATEN_FLAGS.values())))

    def test_every_trainer_exists(self) -> None:
        for index in TRAINER_BEATEN_FLAGS:
            self.assertIn(index, trainer_roster.TRAINERS_BY_INDEX)

    def test_the_ambiguous_ones_are_left_out(self) -> None:
        for index in (18, 127, 139, 140, 141, 142, 164):
            self.assertNotIn(index, TRAINER_BEATEN_FLAGS)

    def test_the_lab_and_citadark_are_covered(self) -> None:
        self.assertEqual(1163, TRAINER_BEATEN_FLAGS[50])    # Solox
        self.assertEqual(1358, TRAINER_BEATEN_FLAGS[173])   # Lovrina #2
        self.assertEqual(1360, TRAINER_BEATEN_FLAGS[176])   # Grason


class TestTheWatcher(unittest.TestCase):
    def _watcher(self, words):
        watcher = rc.TrainerBeatenFlagWatcher(flags={50: 1163, 176: 1360})
        watcher.descriptors = {1163: (1, 3, STORAGE), 1360: (1, 37, STORAGE)}
        raw = struct.pack(">4I", *words)

        def read(address, length):
            return raw[address - STORAGE:address - STORAGE + length].ljust(length, b"\0")
        return watcher, read

    def test_two_reads_confirm(self) -> None:
        watcher, read = self._watcher([1 << 3, 0, 0, 0])
        with mock.patch.object(rc, "read_bytes", read):
            self.assertEqual([], watcher.poll())
            self.assertEqual([50], watcher.poll())
            self.assertEqual([], watcher.poll())

    def test_a_bit_in_the_second_word(self) -> None:
        watcher, read = self._watcher([0, 1 << 5, 0, 0])
        with mock.patch.object(rc, "read_bytes", read):
            watcher.poll()
            self.assertEqual([176], watcher.poll())

    def test_one_read_is_not_enough(self) -> None:
        watcher, read = self._watcher([1 << 3, 0, 0, 0])
        _, clear = self._watcher([0, 0, 0, 0])
        with mock.patch.object(rc, "read_bytes", read):
            watcher.poll()
        with mock.patch.object(rc, "read_bytes", clear):
            self.assertEqual([], watcher.poll())


class TestTheClient(unittest.TestCase):
    def test_a_flag_names_the_trainers_own_check_and_any(self) -> None:
        ctx = SimpleNamespace(checked_locations=set())
        names = Client.beaten_flag_location_names(ctx, [50, 173])
        self.assertIn("Defeat - Solox", names)
        self.assertIn("Defeat - Lovrina #2", names)

    def test_it_runs_inside_the_gate(self) -> None:
        import inspect

        source = inspect.getsource(Client)
        gated = source.split("if block_is_stable:\n                        # FIRST", 1)[1].split(
            "elif not ctx._block_churn_logged:", 1)[0]
        self.assertIn("await check_trainer_beaten_flags(ctx)", gated)


class TestCitadarkOnTheRealScripts(unittest.TestCase):
    def test_the_windows_open_past_900(self) -> None:
        for name, size, code0, edits, anchors, _guard in cd.CITADARK_FLOORS:
            script = map_script({"Citadark Isle 1F": "D6_fort_1F", "Citadark Isle B1": "D6_fort_B1"}[name])
            if script is None:
                self.skipTest("the map dumps are not on this machine")
            self.assertEqual(size, len(script))
            for offset, expected in anchors:
                self.assertEqual(expected, script[offset:offset + len(expected)], name)
            for word, stock, patched in edits:
                self.assertEqual(stock, struct.unpack_from(">I", script, code0 + 4 * word)[0])
                self.assertEqual(900, stock)
                self.assertGreater(patched, 0xFFFFFF)


if __name__ == "__main__":
    unittest.main()
