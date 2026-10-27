"""`/pokespotforce` puts one of a spot's own Pokemon there, waiting, the way the spawn does."""
from __future__ import annotations

import struct
import unittest
from types import SimpleNamespace
from unittest import mock

from .. import Client
from .. import ram_client as rc
from .local_dumps import DUMPS


def _memory():
    mem = {}
    rows = [(1248, 1251, 1281, 1407, 2299, 1412), (1249, 1252, 1282, 1408, 2300, 1413),
            (1250, 1253, 1283, 1409, 2301, 1414)]
    for k, row in enumerate(rows):
        mem[rc.POKESPOT_SPOT_TABLE + rc.POKESPOT_SPOT_ROW * k] = struct.pack(">6I", *row)
    for spot, species in (("Rock", (27, 207, 332)), ("Oasis", (187, 231, 311)), ("Cave", (41, 382, 194))):
        mem[rc.POKESPOT_POOL_ADDRESSES[spot]] = b"".join(struct.pack(">BBHII", 10, 20, sp, 0, 0) for sp in species)
    mem[rc.POKESPOT_VISITOR_POOL] = b"".join(struct.pack(">BBHII", 10, 10, sp, 0, 0) for sp in (413, 414))

    def read(address, length):
        return mem[address][:length]
    return read


class TestForce(unittest.TestCase):
    def _run(self, *args, room=1):
        flags = {}
        ctx = SimpleNamespace(room_tracker=SimpleNamespace(current=room))
        with mock.patch.object(rc, "read_bytes", _memory()), \
                mock.patch.object(rc, "gs_flag_set", lambda f, v: flags.__setitem__(f, v) or True), \
                mock.patch.object(rc, "gs_flag_get", lambda f: 0):
            lines = Client.force_pokespot_encounter(ctx, args)
        return lines, flags

    def test_by_number(self) -> None:
        lines, flags = self._run("cave", "2")
        self.assertEqual(382, flags[1409])                 # Aron, the spot's second
        self.assertEqual(0, flags[1283])
        self.assertNotEqual(0, flags[2301])
        self.assertIn("Cave", lines[0])

    def test_by_name_and_a_visitor(self) -> None:
        _lines, flags = self._run("rock", "bonsly")
        self.assertEqual(413, flags[1407])

    def test_a_pokemon_that_cant_be_there_is_refused(self) -> None:
        lines, flags = self._run("oasis", "pikachu")
        self.assertEqual({}, flags)
        self.assertIn("can't appear", lines[0])

    def test_random_is_one_of_the_five(self) -> None:
        _lines, flags = self._run("oasis")
        self.assertIn(flags[1408], (187, 231, 311, 413, 414))

    def test_no_arguments_lists_them(self) -> None:
        lines, flags = self._run()
        self.assertEqual({}, flags)
        self.assertEqual(4, len(lines))

    def test_standing_there(self) -> None:
        lines, _flags = self._run("rock", "1", room=90)
        self.assertIn("next time", lines[1])


class TestTheAddressesAreRight(unittest.TestCase):
    def test_against_a_dump(self) -> None:
        path = DUMPS / "mem1_baseline.bin"
        if not path.is_file():
            self.skipTest("no MEM1 dump here")
        mem = path.read_bytes()

        def read(address, length):
            return mem[address - 0x80000000:address - 0x80000000 + length]
        with mock.patch.object(rc, "read_bytes", read):
            self.assertEqual([27, 207, 332, 413, 414], rc.pokespot_candidates("Rock"))
            self.assertEqual([41, 382, 194, 413, 414], rc.pokespot_candidates("Cave"))
            self.assertEqual((1250, 1253, 1283, 1409, 2301, 1414), rc._pokespot_row("Cave"))


if __name__ == "__main__":
    unittest.main()
