"""ADDENDUM 465 (2026-10-11) -- snagged Shadows stay gone on a rematch; the save's Shadow list gets real species.

Trainers with Shadows carry a marker saying which Pokemon are Shadows. Generated Shadows were missing it, which is
also why they respawned infinitely. The flag is tracked down on trainers and set for generated Pokemon, and the
other Shadow behaviours on trainers around it are investigated too.
"""
from __future__ import annotations

import pathlib
import shutil
import struct
import tempfile
import unittest

from ..game_data import shadow_engine as E
from ..tools import iso_patcher as ip
from ..tools import xd_deck_format as deck_format

DOL = pathlib.Path("/mnt/user-data/uploads/PokemonXD-working/main_dol.bin")
DUMPS = pathlib.Path("/mnt/user-data/uploads/PokemonXD-working/bridge/dumps")


def _word_reader(data: bytes):
    offs = struct.unpack(">18I", data[0:72]); addrs = struct.unpack(">18I", data[72:144])
    sizes = struct.unpack(">18I", data[144:216])

    def word(address):
        for o, b, z in zip(offs, addrs, sizes):
            if z and b <= address < b + z:
                return struct.unpack_from(">I", data, o + address - b)[0]
        raise ValueError(hex(address))
    return word


def _branch_target(address: int, word: int) -> int:
    disp = word & 0xFFFC
    return address + (disp - 0x10000 if disp & 0x8000 else disp)


class TestTheRespawnFix(unittest.TestCase):
    def test_the_decision_table(self):
        """Walk the patched block for every (status, fight mode, swap mode) and compare with the intent."""
        code = dict(E.RESPAWN_CONTEXT_WORDS)
        code.update({a: new for a, _v, new in E.RESPAWN_FIX_WORDS})
        BUILD, SKIP, SWAP_BLOCK = 0x801FAB44, 0x801FAB18, 0x801FAB10

        def run(status, fight, swap):
            pc, cr = 0x801FAAF0, None
            for _ in range(20):
                if pc in (BUILD, SKIP, SWAP_BLOCK):
                    return pc
                w = code[pc]
                op = w >> 26
                if op == 11:                       # cmpwi r3,imm
                    cr = (status > (w & 0xFFFF)) - (status < (w & 0xFFFF))
                elif op == 10:                     # cmplwi rN,1
                    reg = (w >> 16) & 31
                    val = {19: fight, 18: swap}[reg]
                    cr = (val > 1) - (val < 1)
                elif op == 16:                     # bc
                    bo, bi = (w >> 21) & 31, (w >> 16) & 31
                    cond = {0: cr < 0, 2: cr == 0}[bi]
                    taken = cond if bo == 12 else not cond
                    if taken:
                        pc = _branch_target(pc, w)
                        continue
                pc += 4
            self.fail("did not reach an outcome")

        for fight in (0, 1, 2):
            for swap in (0, 1, 2):
                for status in (0, 1, 2, 3, 4):
                    got = run(status, fight, swap)
                    if status < 2:
                        want = BUILD
                    elif fight == 1:
                        want = SKIP
                    elif swap == 1:
                        want = SWAP_BLOCK
                    elif status == 2:
                        want = BUILD                    # fled to Miror B: he still fields it, as vanilla
                    else:
                        want = SWAP_BLOCK               # snagged/purified: swap deck 0 -> skipped (new)
                    self.assertEqual(want, got, (status, fight, swap))

    @unittest.skipUnless(DOL.is_file(), "needs a real main.dol")
    def test_against_the_real_dol(self):
        word = _word_reader(DOL.read_bytes())
        for address, vanilla, _new in E.RESPAWN_FIX_WORDS:
            self.assertEqual(vanilla, word(address), hex(address))
        for address, value in E.RESPAWN_CONTEXT_WORDS.items():
            self.assertEqual(value, word(address), hex(address))
        self.assertEqual(0x48000158, word(0x801FAB1C), "the skip path's branch to the routine's end")
        self.assertEqual(0x38600001, word(0x801FAB18))


class TestTheDarkPokemonList(unittest.TestCase):
    @unittest.skipUnless(DOL.is_file(), "needs a real main.dol")
    def test_the_vanilla_table_is_the_dols(self):
        data = DOL.read_bytes()
        word = _word_reader(data)
        table = []
        for i in range(0, 128, 2):
            w = word(E.DARK_POKEMON_LIST_ADDRESS + 2 * i)
            table += [w >> 16, w & 0xFFFF]
        self.assertEqual(list(E.VANILLA_DARK_POKEMON_LIST), table)
        self.assertEqual([E.PLACEHOLDER_SPECIES] * 44, table[84:])

    @unittest.skipUnless((DUMPS / "deck_story_1.bin").is_file(), "needs the deck dumps")
    def test_vanilla_decks_reproduce_the_vanilla_table(self):
        story = deck_format.lzss_decode((DUMPS / "deck_story_1.bin").read_bytes())
        dark = deck_format.lzss_decode((DUMPS / "deck_dark_1.bin").read_bytes())
        species = ip.shadow_species_from_decks(story, dark)
        self.assertEqual(83, len(species))
        self.assertEqual((), E.dark_pokemon_list_words(species), "a vanilla roster must write nothing")

    def test_changed_and_new_entries(self):
        words = E.dark_pokemon_list_words({1: 25, 84: 150, 85: 151})
        by_addr = {a: (v, n) for a, v, n in words}
        self.assertEqual((0 << 16 | 216, 0 << 16 | 25), by_addr[E.DARK_POKEMON_LIST_ADDRESS])   # entry 0 is 0
        self.assertEqual((280 << 16 | 280, 150 << 16 | 151), by_addr[E.DARK_POKEMON_LIST_ADDRESS + 2 * 84])
        self.assertEqual(2, len(words))

    def test_index_zero_and_out_of_range_are_ignored(self):
        self.assertEqual((), E.dark_pokemon_list_words({0: 5, 128: 5, 3: 0}))


@unittest.skipUnless(DOL.is_file(), "needs a real main.dol")
class TestTheWritePath(unittest.TestCase):
    """The real main.dol inside a minimal disc image: header field 0x420 points at it, as on the disc."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.iso = pathlib.Path(self.tmp.name) / "x.iso"
        dol_off = 0x10000
        image = bytearray(dol_off)
        struct.pack_into(">I", image, ip.DOL_OFFSET_FIELD, dol_off)
        self.iso.write_bytes(bytes(image) + DOL.read_bytes())

    def test_both_write_and_read_back(self):
        result = ip.write_dol_words_patch(self.iso, E.RESPAWN_FIX_WORDS)
        self.assertTrue(result["applied"], result["reason"])
        words = E.dark_pokemon_list_words({84: 150})
        result = ip.write_dol_words_patch(self.iso, words)
        self.assertTrue(result["applied"], result["reason"])
        data = self.iso.read_bytes()[0x10000:]
        word = _word_reader(data)
        for address, _v, new in E.RESPAWN_FIX_WORDS:
            self.assertEqual(new, word(address))
        self.assertEqual(150 << 16 | 280, word(E.DARK_POKEMON_LIST_ADDRESS + 2 * 84))


class TestThePatcherRunsIt(unittest.TestCase):
    def test_wired_after_the_deck_passes(self):
        source = pathlib.Path(ip.__file__).read_text(encoding="utf-8")
        body = source.split("def apply_patch(", 1)[1]
        at = body.index("_engine.RESPAWN_FIX_WORDS")
        for earlier in ("write_shadow_multi_trainer_patch(output_path", "write_nightmare_citadark_patch(",
                        "apply_trainer_patch(decompressed"):
            self.assertLess(body.index(earlier), at, earlier)
        self.assertIn("read_final_shadow_species(output_path)", body[at:at + 2000])


if __name__ == "__main__":
    unittest.main()
