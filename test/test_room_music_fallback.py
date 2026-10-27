"""A room whose music rows are all flag-gated still starts its own music."""
from __future__ import annotations

import pathlib
import struct
import unittest

from ..game_data import floor_music as M
from ..tools import iso_patcher as ip

REAL_DOL = pathlib.Path("/mnt/user-data/uploads/PokemonXD-working/main_dol.bin")


def _reader(data: bytes):
    offs = struct.unpack(">18I", data[0:72]); addrs = struct.unpack(">18I", data[72:144])
    sizes = struct.unpack(">18I", data[144:216])

    def word(address):
        for o, b, z in zip(offs, addrs, sizes):
            if z and b <= address < b + z:
                return struct.unpack_from(">I", data, o + address - b)[0]
        raise ValueError(hex(address))
    return word, offs, addrs, sizes


def _target(at: int, w: int) -> int:
    off = w & 0x03FFFFFC
    return at + (off - 0x04000000 if off & 0x02000000 else off)


class TestTheRoutine(unittest.TestCase):
    def test_branches_land_where_they_should(self):
        words = M.cave_words()
        c = M.CAVE_ADDRESS
        self.assertEqual(M.SEARCH_TABLE, _target(c + 0x08, words[2]))
        self.assertEqual(M.PLAY_ROW, _target(c + 0x14, words[5]))
        self.assertEqual(M.EPILOGUE_ADDRESS, _target(c + 0x1C, words[7]))
        self.assertEqual(M.EPILOGUE_ADDRESS, _target(c + 0x24, words[9]))
        self.assertEqual(1, words[2] & 1)
        self.assertEqual(1, words[5] & 1)
        self.assertEqual(0, words[7] & 1)
        # beq +0x10 from +0x10 lands on the `li r3,0` at +0x20
        self.assertEqual(0x41820010, words[4])
        self.assertEqual(0x38600000, words[8])

    def test_hook_branches_into_the_routine(self):
        hook = [w for w in M.dol_patch_words() if w[0] == M.HOOK_ADDRESS]
        self.assertEqual(1, len(hook))
        _a, old, new = hook[0]
        self.assertEqual(0x38600000, old)
        self.assertEqual(M.CAVE_ADDRESS, _target(M.HOOK_ADDRESS, new))
        self.assertEqual(0, new & 1, "a plain branch -- the routine returns through the function's own epilogue")

    def test_no_other_patch_writes_these_words(self):
        mine = {a for a, _o, _n in M.dol_patch_words()}
        from ..game_data import (candy_box, conditional_catch, escape_rope, infinite_tms, kaminko_miror_level,
                                 purification_rate, text_speed, whiteout_counter)
        others = set()
        for mod in (candy_box, conditional_catch, escape_rope, infinite_tms, kaminko_miror_level,
                    purification_rate, text_speed, whiteout_counter):
            for name in dir(mod):
                fn = getattr(mod, name)
                if name == "dol_patch_words" and callable(fn):
                    try:
                        others |= {a for a, _o, _n in fn()}
                    except TypeError:
                        pass
        self.assertFalse(mine & others)

    def test_the_patcher_writes_it(self):
        src = pathlib.Path(ip.__file__).read_text(encoding="utf-8")
        self.assertIn('_game_data_module("floor_music").dol_patch_words()', src)

    @unittest.skipUnless(REAL_DOL.is_file(), "needs a real main.dol")
    def test_against_the_real_dol(self):
        data = REAL_DOL.read_bytes()
        word, offs, addrs, sizes = _reader(data)
        for address, old, _new in M.dol_patch_words():
            self.assertEqual(old, word(address), hex(address))
        # The loop's exit: cmplwi r31,0 / bne loop / li r3,0, then the epilogue reloading LR, r31 and r30.
        self.assertEqual(0x281F0000, word(M.HOOK_ADDRESS - 8))
        self.assertEqual(0x80010014, word(M.EPILOGUE_ADDRESS))
        self.assertEqual(0x83E1000C, word(M.EPILOGUE_ADDRESS + 4))
        self.assertEqual(0x83C10008, word(M.EPILOGUE_ADDRESS + 8))
        # r30 holds the room from floorGetCurrent for the whole function.
        self.assertEqual(0x7C7E1B78, word(M.PLAY_SOUND + 0x1C))
        # Nothing branches into the cave function.
        for o, b, z in zip(offs, addrs, sizes):
            if not z or b < 0x80000000:
                continue
            for i in range(0, z, 4):
                w = struct.unpack_from(">I", data, o + i)[0]
                if (w >> 26) == 18:
                    at = b + i
                    t = _target(at, w) if not (w & 2) else (w & 0x03FFFFFC)
                    if M.CAVE_ADDRESS <= t < M.CAVE_ADDRESS + 0x1E8:
                        self.assertTrue(M.CAVE_ADDRESS <= at < M.CAVE_ADDRESS + 0x1E8, hex(at))
        self.assertNotIn(struct.pack(">I", M.CAVE_ADDRESS), data)


if __name__ == "__main__":
    unittest.main()
