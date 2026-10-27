"""Skip Opening Movie: one main.dol word, the New Game path's floor link, pointed past the opening cutscene."""
from __future__ import annotations

import inspect
import struct
import unittest
from pathlib import Path

from .. import options
from ..game_data import opening_movie as om
from ..tools import iso_patcher

DOL = Path("/mnt/user-data/uploads/PokemonXD-working/main_dol.bin")


def _word(dol: bytes, address: int) -> int:
    offs = struct.unpack(">18I", dol[0:72])
    addrs = struct.unpack(">18I", dol[72:144])
    sizes = struct.unpack(">18I", dol[144:216])
    for off, base, size in zip(offs, addrs, sizes):
        if size and base <= address < base + size:
            return struct.unpack_from(">I", dol, off + address - base)[0]
    raise KeyError(hex(address))


class TestTheWord(unittest.TestCase):
    def setUp(self) -> None:
        if not DOL.is_file():
            self.skipTest("main.dol is not on this machine")
        self.dol = DOL.read_bytes()

    def test_it_is_the_new_game_floor_link(self) -> None:
        self.assertEqual(om.NEW_GAME_FLOOR_VANILLA, _word(self.dol, om.NEW_GAME_FLOOR_LINK))
        self.assertEqual(0x38800000, _word(self.dol, om.NEW_GAME_FLOOR_LINK + 4))              # li r4, 0
        bl = _word(self.dol, om.NEW_GAME_FLOOR_LINK + 8)
        self.assertEqual(0x801202E0, (om.NEW_GAME_FLOOR_LINK + 8 + (bl & 0x03FFFFFC)) & 0xFFFFFFFF)   # floorLink
        # Two calls earlier: the routine that starts a new game's play time.
        bl = _word(self.dol, 0x8002FA54)
        self.assertEqual(0x8002FF74, (0x8002FA54 + (bl & 0x03FFFFFC)) & 0xFFFFFFFF)          # _menuTopNewGame

    def test_the_skip_is_the_floor_the_cutscene_ends_on(self) -> None:
        self.assertEqual(0x38600000 | 141, om.NEW_GAME_FLOOR_SKIP)
        self.assertEqual(0x38600000 | 182, om.NEW_GAME_FLOOR_VANILLA)


class TestTheOption(unittest.TestCase):
    def test_off_by_default_and_wired(self) -> None:
        self.assertEqual(0, options.SkipOpeningMovie.default)
        self.assertIn("skip_opening_movie", options.PokemonXDOptions.__annotations__)
        source = inspect.getsource(iso_patcher)
        self.assertIn('seed.get("skip_opening_movie")', source)
        self.assertEqual(((om.NEW_GAME_FLOOR_LINK, om.NEW_GAME_FLOOR_VANILLA, om.NEW_GAME_FLOOR_SKIP),),
                         om.dol_patch_words())


if __name__ == "__main__":
    unittest.main()
