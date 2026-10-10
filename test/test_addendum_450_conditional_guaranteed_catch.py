"""ADDENDUM 450 (2026-10-09) -- the guarantee follows the catch rate, so the exclusions no longer switch it off."""
from __future__ import annotations

import os
import struct
import unittest
from pathlib import Path

from ..game_data import candy_box, conditional_catch as cc
from ..tools import iso_patcher as ip

DOL = "/mnt/user-data/uploads/PokemonXD-working/main_dol.bin"


class TestTheWords(unittest.TestCase):
    def test_cave(self) -> None:
        words = cc.cave_words()
        self.assertEqual(0x57A0063E, words[0])      # clrlwi r0,r29,24
        self.assertEqual(0x280000FF, words[1])      # cmplwi r0,255
        self.assertEqual(0x40820008, words[2])      # bne +8
        target = cc.CAVE_ADDRESS + 0x0C + (((words[3] & 0x03FFFFFC) ^ 0x02000000) - 0x02000000)
        self.assertEqual(cc.GUARANTEED_PATH, target)
        self.assertEqual(0x4E800420, words[4])      # the original bctr

    def test_hook_branches_to_the_cave(self) -> None:
        address, vanilla, new = cc.dol_patch_words()[-1]
        self.assertEqual((cc.HOOK_ADDRESS, 0x4E800420), (address, vanilla))
        self.assertEqual(cc.CAVE_ADDRESS, address + (((new & 0x03FFFFFC) ^ 0x02000000) - 0x02000000))

    def test_same_guaranteed_path_as_the_action_replay_word(self) -> None:
        self.assertEqual(ip.ALWAYS_CATCH_ADDRESS, cc.HOOK_ADDRESS)
        self.assertEqual(cc.HOOK_ADDRESS + (ip.ALWAYS_CATCH_WORD & 0x03FFFFFC), cc.GUARANTEED_PATH)

    def test_clear_of_the_candy_box(self) -> None:
        self.assertGreaterEqual(cc.CAVE_OFFSET, candy_box.LEARN_END_OFFSET)

    @unittest.skipUnless(os.path.exists(DOL), "no retail main.dol here")
    def test_vanilla_words_match_the_retail_dol(self) -> None:
        data = Path(DOL).read_bytes()
        offs = struct.unpack(">18I", data[0:72])
        addrs = struct.unpack(">18I", data[72:144])
        sizes = struct.unpack(">18I", data[144:216])

        def word(a: int) -> int:
            for o, b, z in zip(offs, addrs, sizes):
                if z and b <= a < b + z:
                    return struct.unpack(">I", data[o + a - b:o + a - b + 4])[0]
            raise ValueError(hex(a))

        for address, vanilla, _new in cc.dol_patch_words():
            self.assertEqual(vanilla, word(address), hex(address))
        # r29 really is the catch rate: both paths end in `mr r29,r3`.
        self.assertEqual(0x7C7D1B78, word(0x802192F0))
        self.assertEqual(0x7C7D1B78, word(0x80219300))


class TestThePatcherUsesIt(unittest.TestCase):
    def test_exclusions_take_the_conditional_branch(self) -> None:
        source = Path(ip.__file__).read_text(encoding="utf-8")
        self.assertIn("write_dol_words_patch(output_path, conditional_catch.dol_patch_words())", source)
        self.assertNotIn("always-catch instruction covers every catch in the game\"}", source)


class TestTheConnectRetryIsQuiet(unittest.TestCase):
    """Player: "Make this error retry silently instead of spamming." The attempt and the failure are each said once
    per run of failures; later retries go to `!verbose`."""

    def test_guarded_by_the_failure_count(self) -> None:
        from .. import Client

        source = Path(Client.__file__).read_text(encoding="utf-8")
        attempt = source.index('logger.info("Attempting to connect to Dolphin...")')
        self.assertIn("if ctx._hook_failures == 0 and not ctx._dolphin_missing_logged:", source[attempt - 160:attempt])
        failed = source.index('logger.info("Connection to Dolphin failed')
        self.assertIn("if ctx._hook_failures == 0:", source[failed - 120:failed])
        self.assertEqual(1, source.count('logger.info("Attempting to connect to Dolphin...")'))
        self.assertIn("ctx._hook_failures = 0", source[failed - 600:failed])   # reset on a good hook


class TestPurificationRateScalesTheReductions(unittest.TestCase):
    """Player: "Rather than edit the shadow gauge itself, can we instead increase the values of the things that
    reduce it? Editing the shadow gauge is breaking it." """

    def test_the_constant_is_the_rate(self) -> None:
        from ..game_data import purification_rate as pr

        for rate in (100, 200, 1000):
            words = pr.cave_words(rate)
            self.assertEqual(float(rate), struct.unpack(">f", struct.pack(">I", words[3]))[0])
        with self.assertRaises(ValueError):
            pr.cave_words(50)

    def test_the_cave_loads_its_own_float_and_returns(self) -> None:
        from ..game_data import purification_rate as pr

        lis, lfs, b, _f = pr.cave_words(300)
        address = ((lis & 0xFFFF) << 16) + ((lfs & 0xFFFF) ^ 0x8000) - 0x8000
        self.assertEqual(pr.CONSTANT_ADDRESS, address)
        self.assertEqual(0x3C600000, lis & 0xFFFF0000)                   # lis r3
        self.assertEqual(0xC0030000, lfs & 0xFFFF0000)                   # lfs f0,d(r3)
        self.assertEqual(pr.RETURN_ADDRESS,
                         pr.CAVE_ADDRESS + 8 + (((b & 0x03FFFFFC) ^ 0x02000000) - 0x02000000))

    def test_caves_do_not_overlap(self) -> None:
        from ..game_data import purification_rate as pr

        cc_words = {a for a, _v, _n in cc.dol_patch_words()}
        pr_words = {a for a, _v, _n in pr.dol_patch_words(200)}
        self.assertFalse(cc_words & pr_words)
        self.assertGreaterEqual(min(pr_words - {pr.HOOK_ADDRESS}), candy_box.CAVE_ADDRESS + candy_box.LEARN_END_OFFSET)

    @unittest.skipUnless(os.path.exists(DOL), "no retail main.dol here")
    def test_vanilla_words_and_r3_is_dead(self) -> None:
        from ..game_data import purification_rate as pr

        data = Path(DOL).read_bytes()
        offs = struct.unpack(">18I", data[0:72])
        addrs = struct.unpack(">18I", data[72:144])
        sizes = struct.unpack(">18I", data[144:216])

        def word(a: int) -> int:
            for o, b, z in zip(offs, addrs, sizes):
                if z and b <= a < b + z:
                    return struct.unpack(">I", data[o + a - b:o + a - b + 4])[0]
            raise ValueError(hex(a))

        for address, vanilla, _new in pr.dol_patch_words(200):
            self.assertEqual(vanilla, word(address), hex(address))
        self.assertEqual(0x7FE3FB78, word(pr.RETURN_ADDRESS))   # mr r3,r31 -- r3 is overwritten right after
        self.assertEqual(0xEFFF0032, word(0x8013EEE4))         # fmuls f31,f31,f0 -- f0 is what the cave loads
