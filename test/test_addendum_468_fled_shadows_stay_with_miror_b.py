"""ADDENDUM 468 (2026-10-11) -- a beaten Shadow goes to Miror B. and leaves every trainer's team.

A beaten Shadow goes to Miror B. The point of copying it onto later teams is that a player who arrives later in
the story, and whose first fight against a trainer is that trainer's second team, still meets the Shadow just as
on the first team. Once it is defeated or snagged it is removed from every team; if defeated, it goes to Miror B.
"""
from __future__ import annotations

import pathlib
import struct
import unittest

from ..game_data import shadow_engine as E
from ..tools import iso_patcher as ip
from ..tools import xd_deck_format as deck_format
from .test_addendum_465_shadow_engine import DOL, _branch_target, _word_reader

DECK_DUMP = pathlib.Path("/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/deck_archive_full1.bin")
BUILD, SKIP, SWAP_BLOCK = 0x801FAB44, 0x801FAB18, 0x801FAB10
NORMAL, OTHERS = E.NORMAL_DECK_RETURN_ADDRESS, [a + 4 for a in E.CREATE_DECK_POKEMON_CALL_SITES if a + 4 != 0x801FADBC]


def _run(code: "dict[int, int]", status: int, fight: int, swap: int, caller: int) -> int:
    """Interpret the patched block: cmpwi r3 / cmplwi r19|r18|r0 / lhz r0,0x46(r1) / bc / b."""
    regs = {19: fight, 18: swap, 0: None}
    pc, cr = 0x801FAAF0, None
    for _ in range(40):
        if pc in (BUILD, SKIP, SWAP_BLOCK):
            return pc
        w = code[pc]
        op = w >> 26
        if op == 11:                                   # cmpwi r3,imm
            imm = w & 0xFFFF
            cr = (status > imm) - (status < imm)
        elif op == 10:                                 # cmplwi rN,imm
            val, imm = regs[(w >> 16) & 31], w & 0xFFFF
            cr = (val > imm) - (val < imm)
        elif op == 40:                                 # lhz r0,0x46(r1): low half of the saved return address
            assert w == 0xA0010046, hex(w)
            regs[0] = caller & 0xFFFF
        elif op == 16:                                 # bc
            bo, bi = (w >> 21) & 31, (w >> 16) & 31
            cond = {0: cr < 0, 2: cr == 0}[bi]
            if (cond if bo == 12 else not cond):
                pc = _branch_target(pc, w)
                continue
        elif op == 18:                                 # b
            disp = w & 0x03FFFFFC
            pc += disp - 0x04000000 if disp & 0x02000000 else disp
            continue
        else:
            raise AssertionError(f"unexpected word {w:08X} at {pc:08X}")
        pc += 4
    raise AssertionError("did not reach an outcome")


def _code() -> "dict[int, int]":
    code = dict(E.RESPAWN_CONTEXT_WORDS)
    code.update({a: new for a, _v, new in E.RESPAWN_FIX_WORDS})
    code.update({a: new for a, _v, new in E.FLED_SHADOW_SKIP_WORDS})
    return code


class TestTheDecisionTable(unittest.TestCase):
    def test_every_case(self) -> None:
        code = _code()
        for caller in [NORMAL] + OTHERS:
            for fight in (0, 1, 2):
                for swap in (0, 1, 2):
                    for status in (0, 1, 2, 3, 4):
                        got = _run(code, status, fight, swap, caller)
                        if status < 2:
                            want = BUILD
                        elif fight == 1:
                            want = SKIP
                        elif swap == 1:
                            want = SWAP_BLOCK
                        elif status == 2:
                            want = SKIP if caller == NORMAL else BUILD   # with Miror B. only
                        else:
                            want = SWAP_BLOCK                            # snagged/purified (465)
                        self.assertEqual(want, got, (hex(caller), status, fight, swap))

    def test_it_rewrites_465s_last_word(self) -> None:
        by_addr = {a: (v, n) for a, v, n in E.RESPAWN_FIX_WORDS}
        self.assertEqual(by_addr[0x801FAB0C][1], E.FLED_SHADOW_SKIP_WORDS[0][1])

    def test_the_add_modes_share_one_body(self) -> None:
        """Mode 2 jumps into mode 1's body; mode 1's wrong-slot exit no longer falls into mode 2's test."""
        words = {a: n for a, _v, n in E.FLED_SHADOW_SKIP_WORDS}
        self.assertEqual(0x801FABF0, _branch_target(0x801FAB58, words[0x801FAB58]))
        disp = words[0x801FABA8] & 0x03FFFFFC
        self.assertEqual(0x801FAB4C, 0x801FABA8 + (disp - 0x04000000 if disp & 0x02000000 else disp))


@unittest.skipUnless(DOL.is_file(), "needs a real main.dol")
class TestAgainstTheRealDol(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = DOL.read_bytes()
        cls.word = staticmethod(_word_reader(cls.data))

    def test_vanilla_words(self) -> None:
        for address, vanilla, _new in E.FLED_SHADOW_SKIP_WORDS[1:]:
            self.assertEqual(vanilla, self.word(address), hex(address))
        self.assertEqual(E.FLED_SHADOW_SKIP_WORDS[0][1], next(n for a, _v, n in E.RESPAWN_FIX_WORDS if a == 0x801FAB0C))

    def test_the_two_add_mode_bodies_match(self) -> None:
        """Mode 1 (0x801FAB4C..0x801FAB98) and mode 2 (0x801FABA8..0x801FABEC) make the same four calls in order and
        leave the same two results in r25/r26 -- the merge drops nothing."""
        def calls(start, end):
            return [_branch_target_b(a, self.word(a)) for a in range(start, end, 4) if self.word(a) >> 26 == 18
                    and self.word(a) & 1]
        self.assertEqual(calls(0x801FAB4C, 0x801FAB9C), calls(0x801FABA8, 0x801FABF0))
        self.assertEqual(4, len(calls(0x801FAB4C, 0x801FAB9C)))
        self.assertEqual(0x7C7A1B78, self.word(0x801FAB98))       # mr r26,r3   (mode 1)
        self.assertEqual(0x7C7A1B78, self.word(0x801FABEC))       # mr r26,r3   (mode 2)

    def test_the_only_callers(self) -> None:
        """Every `bl _fightTrainerCreateDeckPokemon` in main.dol, so the return-address test cannot miss one."""
        offs = struct.unpack(">18I", self.data[0:72]); addrs = struct.unpack(">18I", self.data[72:144])
        sizes = struct.unpack(">18I", self.data[144:216])
        found = []
        for o, b, z in list(zip(offs, addrs, sizes))[:7]:            # the text sections
            for i in range(0, z, 4):
                w = struct.unpack_from(">I", self.data, o + i)[0]
                if w >> 26 == 18 and w & 3 == 1 and _branch_target_b(b + i, w) == 0x801FAA5C:
                    found.append(b + i)
        self.assertEqual(sorted(E.CREATE_DECK_POKEMON_CALL_SITES), found)
        self.assertEqual(0x48000000 | ((0x801FAA5C - 0x801FADB8) & 0x03FFFFFC) | 1, self.word(0x801FADB8))


def _branch_target_b(address: int, w: int) -> int:
    disp = w & 0x03FFFFFC
    return address + (disp - 0x04000000 if disp & 0x02000000 else disp)


@unittest.skipUnless(DOL.is_file(), "needs a real main.dol")
class TestTheWritePath(unittest.TestCase):
    def test_after_465(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            iso = pathlib.Path(tmp) / "x.iso"
            image = bytearray(0x10000)
            struct.pack_into(">I", image, ip.DOL_OFFSET_FIELD, 0x10000)
            iso.write_bytes(bytes(image) + DOL.read_bytes())
            self.assertFalse(ip.write_dol_words_patch(iso, E.FLED_SHADOW_SKIP_WORDS)["applied"])   # needs 465 first
            self.assertTrue(ip.write_dol_words_patch(iso, E.RESPAWN_FIX_WORDS)["applied"])
            result = ip.write_dol_words_patch(iso, E.FLED_SHADOW_SKIP_WORDS)
            self.assertTrue(result["applied"], result["reason"])
            word = _word_reader(iso.read_bytes()[0x10000:])
            code = {a: word(a) for a in range(0x801FAAF0, 0x801FABC0, 4)}
        for caller in [NORMAL] + OTHERS:
            self.assertEqual(SKIP if caller == NORMAL else BUILD, _run(code, 2, 0, 0, caller), hex(caller))
            self.assertEqual(SWAP_BLOCK, _run(code, 3, 0, 0, caller))
            self.assertEqual(BUILD, _run(code, 1, 0, 0, caller))


class TestThePatcher(unittest.TestCase):
    def test_wired_after_465_and_only_when_it_went_in(self) -> None:
        body = pathlib.Path(ip.__file__).read_text(encoding="utf-8").split("def apply_patch(", 1)[1]
        respawn = body.index("write_dol_words_patch(output_path, _engine.RESPAWN_FIX_WORDS)")
        fled = body.index("write_dol_words_patch(output_path, _engine.FLED_SHADOW_SKIP_WORDS)")
        self.assertLess(respawn, fled)
        self.assertIn('if respawn_result["applied"] and getattr(_engine, "FLED_SHADOW_SKIP_ENABLED", False):',
                      body[respawn:fled])


# --- relocated Shadows that would never flee -----------------------------------------------------------------------

class TestTheWorthByte(unittest.TestCase):
    def test_only_zero_and_in_use(self) -> None:
        from .test_addendum_424_relocated_citadark_shadows import _dark
        dark = bytearray(_dark({2: 5, 3: 6, 4: 7}))
        dark[0x20 + 3 * 0x18] = 40                                    # DDPK 3 already flees
        out, changed = ip.apply_relocated_shadow_worth(bytes(dark), [2, 3, 5, 0, 200])
        self.assertEqual([2], changed)                                 # 5 is not in use; 0 and 200 out of range
        self.assertEqual(128, out[0x20 + 2 * 0x18])
        self.assertEqual(40, out[0x20 + 3 * 0x18])
        self.assertEqual(0, out[0x20 + 4 * 0x18])                     # not listed
        self.assertEqual(len(dark), len(out))

    @unittest.skipUnless(DECK_DUMP.is_file(), "needs a real deck_archive.fsys dump")
    def test_greevils_six_on_the_real_file(self) -> None:
        from ..game_data import nightmare_citadark as nc
        data = DECK_DUMP.read_bytes()
        e = ip.parse_fsys(data)["DeckData_DarkPokemon.bin"]
        dark = deck_format.lzss_decode(data[e["data_off"]:e["data_off"] + 0x10 + e["comp_size"]])
        relocated = sorted(nc.removed_shadow_ddpks())
        out, changed = ip.apply_relocated_shadow_worth(dark, relocated)
        self.assertEqual([74, 75, 76, 77, 78, 79], changed)
        d = deck_format.DarkPokemonFile(out)
        for index in relocated:
            self.assertNotEqual(0, out[d.ddpk_data + index * 0x18], index)
        self.assertEqual(0, out[d.ddpk_data + 73 * 0x18])               # Lugia stays with Greevil, unchanged
        self.assertEqual(sum(a != b for a, b in zip(dark, out)), 6)

    def test_generated_shadows_already_flee(self) -> None:
        source = pathlib.Path(ip.__file__).read_text(encoding="utf-8")
        body = source[source.index("def _overwrite_ddpk_entry_bytes"):]
        self.assertIn("dark_buf[off + 0x00] = 128", body[:2000])

    def test_wired_into_every_copy(self) -> None:
        source = pathlib.Path(ip.__file__).read_text(encoding="utf-8")
        body = source[source.index("def write_nightmare_citadark_patch"):]
        body = body[:body.index("\ndef ")]
        self.assertEqual(2, body.count("apply_relocated_shadow_worth("))


if __name__ == "__main__":
    unittest.main()
