"""Quick Purification Ceremony: the ceremony's effect loads and lookups return nothing; the rest is untouched."""
from __future__ import annotations

import pathlib
import unittest

from ..game_data import quick_ceremony as Q
from ..tools import iso_patcher as ip
from .test_room_music_fallback import REAL_DOL, _reader


def _branch_target(address: int, word: int) -> "int | None":
    if (word >> 26) != 18 or (word & 3) != 1:     # bl
        return None
    offset = word & 0x03FFFFFC
    if offset & 0x02000000:
        offset -= 0x04000000
    return address + offset


class TestTheSites(unittest.TestCase):
    def test_every_site_is_a_call_inside_the_ceremony(self):
        targets = {"Sequence_GetWaza": Q.SEQUENCE_GET_WAZA, "Sequence_LoadWaza": Q.SEQUENCE_LOAD_WAZA}
        for address, vanilla, name in Q.SITES:
            self.assertTrue(Q.CEREMONY_START <= address < Q.CEREMONY_END, hex(address))
            self.assertEqual(targets[name], _branch_target(address, vanilla), hex(address))

    def test_seven_lookups_and_three_loads(self):
        names = [name for _a, _v, name in Q.SITES]
        self.assertEqual((7, 3), (names.count("Sequence_GetWaza"), names.count("Sequence_LoadWaza")))

    def test_each_becomes_li_r3_0(self):
        self.assertTrue(all(new == 0x38600000 for _a, _v, new in Q.dol_patch_words()))

    def test_no_other_patch_writes_these_words(self):
        from ..game_data import (candy_box, conditional_catch, escape_rope, floor_music, infinite_tms,
                                 kaminko_miror_level, purification_rate, text_speed, walk_speed, whiteout_counter)
        mine = {a for a, _o, _n in Q.dol_patch_words()}
        for mod in (candy_box, conditional_catch, escape_rope, floor_music, infinite_tms, kaminko_miror_level,
                    purification_rate, text_speed, walk_speed, whiteout_counter):
            fn = getattr(mod, "dol_patch_words", None)
            if callable(fn):
                try:
                    self.assertFalse(mine & {a for a, _o, _n in fn()}, mod.__name__)
                except TypeError:
                    pass

    def test_the_patcher_writes_it_only_when_asked(self):
        src = pathlib.Path(ip.__file__).read_text(encoding="utf-8")
        self.assertIn('if seed.get("quick_purification_ceremony"):', src)
        self.assertIn('_game_data_module("quick_ceremony").dol_patch_words()', src)


@unittest.skipUnless(REAL_DOL.is_file(), "needs a real main.dol")
class TestOnTheRealDol(unittest.TestCase):
    def setUp(self):
        self.word = _reader(REAL_DOL.read_bytes())[0]

    def test_vanilla_words(self):
        for address, vanilla, _new in Q.dol_patch_words():
            self.assertEqual(vanilla, self.word(address), hex(address))

    def test_the_sequence_calls_cope_with_nothing(self):
        # WazaSequence_Start, _IsActive and _Free each open `mr. r31,r3` and return at once on a null handle.
        for function in (0x801D06E8, 0x801D0230, 0x801D04BC):
            self.assertEqual(0x7C7F1B79, self.word(function + 0x10), hex(function))

    def test_five_lookups_test_their_result(self):
        guarded = [a for a, _v, name in Q.SITES if name == "Sequence_GetWaza"
                   and (self.word(a + 4) & 0xFFE0FFFF) == 0x7C601B79]       # mr. rX,r3
        self.assertEqual(5, len(guarded))

    def test_no_load_result_is_used(self):
        # The instruction after each load overwrites r3 or does not read it.
        for address, _v, name in Q.SITES:
            if name == "Sequence_LoadWaza":
                after = self.word(address + 4)
                self.assertNotIn(after & 0xFFE0FFFF, (0x7C601B78, 0x7C601B79), hex(address))   # mr rX,r3


if __name__ == "__main__":
    unittest.main()
