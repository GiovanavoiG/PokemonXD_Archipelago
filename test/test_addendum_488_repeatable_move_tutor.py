"""ADDENDUM 488 (2026-10-13) -- the Agate move tutor teaches every move again and again.

Player: "There's a move tutor that teaches moves like icy wind, thunder wave etc, but she only teaches them once. Can we
make it so she doesn't disable them after learning them once?"
"""
from __future__ import annotations

import pathlib
import struct
import unittest

from ..game_data import move_tutor as mt
from ..tools import iso_patcher as ip

DOL = pathlib.Path("/mnt/user-data/uploads/PokemonXD-working/main_dol.bin")


class TestThePatch(unittest.TestCase):
    def test_one_word(self) -> None:
        self.assertEqual(((0x8005E4A8, 0x48141E49, 0x38600000),), mt.dol_patch_words())

    def test_the_vanilla_word_is_the_flag_test(self) -> None:
        disp = mt.CHECK_TAUGHT_VANILLA & 0x03FFFFFC
        self.assertEqual(0x801A02F0, mt.CHECK_TAUGHT_CALL + disp, "bl GSflagTest")
        self.assertEqual(1, mt.CHECK_TAUGHT_VANILLA & 1, "a call")

    @unittest.skipUnless(DOL.is_file(), "needs the player's main.dol")
    def test_matches_the_real_dol(self) -> None:
        data = DOL.read_bytes()
        offs = struct.unpack(">18I", data[0:72])
        addrs = struct.unpack(">18I", data[72:144])
        sizes = struct.unpack(">18I", data[144:216])

        def word(address):
            for o, a, s in zip(offs, addrs, sizes):
                if s and a <= address < a + s:
                    return struct.unpack(">I", data[o + address - a:o + address - a + 4])[0]
            raise KeyError(hex(address))

        for address, vanilla, _new in mt.dol_patch_words():
            self.assertEqual(vanilla, word(address))
        # The stored result is the menu entry's +0x14 "taught" byte, and the refusal reads exactly that byte.
        self.assertEqual(0x7C7AC9AE, word(0x8005E4AC), "stbx r3 -- the result is what gets stored")
        self.assertEqual(0x88030014, word(0x8005ECD8), "menuScriptWazaBasan: lbz r0, 0x14(r3) -- the refusal")

    def test_wired_into_the_patcher(self) -> None:
        body = pathlib.Path(ip.__file__).read_text(encoding="utf-8").split("def apply_patch(", 1)[1]
        self.assertIn('_game_data_module("move_tutor")', body)
        self.assertIn('seed.get("repeatable_move_tutor", True)', body)


if __name__ == "__main__":
    unittest.main()
