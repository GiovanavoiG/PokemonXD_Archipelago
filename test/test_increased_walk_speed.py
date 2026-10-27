"""Increased Walk Speed: one main.dol float, written only when the option is on."""
from __future__ import annotations

import pathlib
import struct
import unittest

from ..game_data import walk_speed as W
from ..tools import iso_patcher as ip
from .test_room_music_fallback import REAL_DOL, _reader


class TestTheWord(unittest.TestCase):
    def test_thirty_becomes_sixty(self):
        ((address, old, new),) = W.dol_patch_words()
        self.assertEqual((30.0, 60.0), (struct.unpack(">f", struct.pack(">I", old))[0],
                                        struct.unpack(">f", struct.pack(">I", new))[0]))

    def test_no_other_patch_writes_it(self):
        from ..game_data import (candy_box, conditional_catch, escape_rope, floor_music, infinite_tms,
                                 kaminko_miror_level, purification_rate, text_speed, whiteout_counter)
        others = set()
        for mod in (candy_box, conditional_catch, escape_rope, floor_music, infinite_tms, kaminko_miror_level,
                    purification_rate, text_speed, whiteout_counter):
            fn = getattr(mod, "dol_patch_words", None)
            if callable(fn):
                try:
                    others |= {a for a, _o, _n in fn()}
                except TypeError:
                    pass
        self.assertNotIn(W.WALK_SPEED_ADDRESS, others)

    def test_the_patcher_writes_it_only_when_asked(self):
        src = pathlib.Path(ip.__file__).read_text(encoding="utf-8")
        self.assertIn('if seed.get("increased_walk_speed"):', src)
        self.assertIn('_game_data_module("walk_speed").dol_patch_words()', src)

    @unittest.skipUnless(REAL_DOL.is_file(), "needs a real main.dol")
    def test_against_the_real_dol(self):
        word, _offs, _addrs, _sizes = _reader(REAL_DOL.read_bytes())
        self.assertEqual(W.VANILLA_WORD, word(W.WALK_SPEED_ADDRESS))


if __name__ == "__main__":
    unittest.main()
