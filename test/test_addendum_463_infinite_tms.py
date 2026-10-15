"""ADDENDUM 463 (2026-10-10) -- Infinite TMs.

An option makes TMs infinite-use. One main.dol word: `menuUseItemSkill`'s TM branch sets
the "consumed" flag to 0, as its HM branch already does.
"""
from __future__ import annotations

import json
import pathlib
import struct
import tempfile
import unittest
import zipfile

from . import PokemonXDTestBase
from .. import options
from ..game_data import infinite_tms as T
from ..tools import iso_patcher as ip

REAL_DOL = pathlib.Path("/mnt/user-data/uploads/PokemonXD-working/main_dol.bin")


def _word_reader(data: bytes):
    offs = struct.unpack(">18I", data[0:72]); addrs = struct.unpack(">18I", data[72:144])
    sizes = struct.unpack(">18I", data[144:216])

    def word(address):
        for o, b, z in zip(offs, addrs, sizes):
            if z and b <= address < b + z:
                return struct.unpack_from(">I", data, o + address - b)[0]
        raise ValueError(hex(address))
    return word, offs, addrs, sizes


class TestTheWord(unittest.TestCase):
    def test_li_r0_1_becomes_li_r0_0(self):
        self.assertEqual(((0x800A5158, 0x38000001, 0x38000000),), T.dol_patch_words())

    @unittest.skipUnless(REAL_DOL.is_file(), "needs a real main.dol")
    def test_against_the_real_dol(self):
        data = REAL_DOL.read_bytes()
        word, offs, addrs, sizes = _word_reader(data)
        self.assertEqual(T.VANILLA_WORD, word(T.TM_CONSUMED_ADDRESS))
        self.assertEqual(0x901F0000, word(T.TM_CONSUMED_ADDRESS + 4), "stw r0,0(r31) -- the consumed flag")
        # The HM branch it is made to match: li r0,0 / stw r0,0(r31), behind `cmplwi r0,255; beq` (TM -> +0x10).
        self.assertEqual(T.PATCHED_WORD, word(T.HM_KEPT_WORD_ADDRESS))
        self.assertEqual(0x901F0000, word(T.HM_KEPT_WORD_ADDRESS + 4))
        self.assertEqual(0x280000FF, word(0x800A5144))
        self.assertEqual(0x41820010, word(0x800A5148))
        # wazaMachineProc (0x800A4EE0) is called from this handler and nowhere else.
        callers = []
        for o, b, z in zip(offs, addrs, sizes):
            if not z or b < 0x80000000:
                continue
            for i in range(0, z, 4):
                w = struct.unpack_from(">I", data, o + i)[0]
                if (w >> 26) == 18 and (w & 3) == 1:
                    off = w & 0x03FFFFFC
                    off = off - 0x04000000 if off & 0x02000000 else off
                    if b + i + off == 0x800A4EE0:
                        callers.append(b + i)
        self.assertEqual([0x800A5118], callers)
        self.assertTrue(T.HANDLER <= callers[0] < T.TM_CONSUMED_ADDRESS)


class TestTheOption(unittest.TestCase):
    def test_off_by_default_in_your_pokemon(self):
        self.assertEqual(0, options.InfiniteTMs.default)
        group = next(g for g in options.OPTION_GROUPS if g.name == "Your Pokemon")
        self.assertIn(options.InfiniteTMs, group.options)

    def test_the_patcher_writes_it_only_when_asked(self):
        source = pathlib.Path(ip.__file__).read_text(encoding="utf-8")
        at = source.index('_game_data_module("infinite_tms").dol_patch_words()')
        self.assertIn('if seed.get("infinite_tms"):', source[at - 200:at])


def _seed(world) -> dict:
    world.pre_output()
    with tempfile.TemporaryDirectory() as tmp:
        world.generate_output(tmp)
        with zipfile.ZipFile(next(pathlib.Path(tmp).glob("*.appxd"))) as zf:
            return json.loads(zf.read("seed.json"))


class TestOn(PokemonXDTestBase):
    options = {"infinite_tms": True}

    def test_the_seed_asks_for_it(self):
        self.assertTrue(_seed(self.multiworld.worlds[self.player])["infinite_tms"])


class TestOff(PokemonXDTestBase):
    options = {"infinite_tms": False}

    def test_the_seed_does_not(self):
        self.assertFalse(_seed(self.multiworld.worlds[self.player])["infinite_tms"])
