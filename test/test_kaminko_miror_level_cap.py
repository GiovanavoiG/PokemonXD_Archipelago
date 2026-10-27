"""Miror B. at Kaminko's: the level cap runs before the Pokemon is written back into the battle's deck record."""
from __future__ import annotations

import pathlib
import struct
import unittest

from ..game_data import kaminko_miror_level as km

DOL = pathlib.Path("/mnt/user-data/uploads/PokemonXD-working/main_dol.bin")
DECK_CREATE_CALL = 0x801FAC40       # bl deckCreate
HERO_CATCH_CALL = 0x801FAC64        # bl heroCatchPokemon


def _word_at(dol: bytes, address: int) -> int:
    offs = struct.unpack(">18I", dol[0:72])
    addrs = struct.unpack(">18I", dol[72:144])
    sizes = struct.unpack(">18I", dol[144:216])
    for o, b, s in zip(offs, addrs, sizes):
        if s and b <= address < b + s:
            return struct.unpack_from(">I", dol, o + address - b)[0]
    raise ValueError(hex(address))


class TestTheHook(unittest.TestCase):
    def test_before_the_write_back(self):
        self.assertLess(km.HOOK_ADDRESS, DECK_CREATE_CALL)
        self.assertLess(km.HOOK_ADDRESS, HERO_CATCH_CALL)

    def test_the_cave_ends_with_the_replaced_instruction(self):
        words = km.cave_words()
        self.assertEqual(km.HOOK_VANILLA_WORD, words[17])
        self.assertEqual(0x7F83E378, words[14], "mr r3,r28: the Pokemon for the level setter")
        hook = km.dol_patch_words()[-1]
        self.assertEqual((km.HOOK_ADDRESS, km.HOOK_VANILLA_WORD), hook[:2])
        self.assertEqual(km.CAVE_ADDRESS, km.HOOK_ADDRESS + ((hook[2] & 0x03FFFFFC) ^ 0x02000000) - 0x02000000
                         if hook[2] & 0x02000000 else km.HOOK_ADDRESS + (hook[2] & 0x03FFFFFC))


@unittest.skipUnless(DOL.is_file(), "needs main.dol")
class TestOnTheRealDol(unittest.TestCase):
    def test_vanilla_words(self):
        dol = DOL.read_bytes()
        for address, vanilla, _new in km.dol_patch_words():
            self.assertEqual(vanilla, _word_at(dol, address), hex(address))

    def test_r25_and_r28_hold_at_the_hook(self):
        dol = DOL.read_bytes()
        # The success path right after the Pokemon is built: clrlwi r3,r25,16, then the deck write-back.
        self.assertEqual(0x5723043E, _word_at(dol, 0x801FAC28))
        self.assertEqual(0x7F85E378, _word_at(dol, 0x801FAC3C), "mr r5,r28 -- the Pokemon goes to deckCreate")


if __name__ == "__main__":
    unittest.main()
