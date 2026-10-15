"""ADDENDUM 484 (2026-10-13) -- the white-out is counted at the top, and our own death is never sent back.

The Death Link check sends at the top of the annihilation function, not at the end, and never sends a duplicate --
even when a Death Link is received out of battle and the white-out happens at the start of a battle.
"""
from __future__ import annotations

import pathlib
import struct
import unittest
from unittest import mock

from .. import ram_client as rc
from ..game_data import whiteout_counter as wc

DOL = pathlib.Path("/mnt/user-data/uploads/PokemonXD-working/main_dol.bin")
BLOCK = 0x80400000


class TestTheHookIsAtTheTop(unittest.TestCase):
    def test_the_sites_are_the_first_instruction_of_each_white_out(self) -> None:
        self.assertEqual((0x801F0E10, 0x801F10B4), tuple(site for site, _v, _i in wc.HOOK_SITES))
        # Both come BEFORE the recovery call ADDENDUM 475 hooked, in the same branch.
        for (site, _v, _i), legacy in zip(wc.HOOK_SITES, sorted(wc.LEGACY_HOOK_WORDS)):
            self.assertLess(site, legacy)
            self.assertLess(legacy - site, 0x40, "the same white-out branch")

    def test_the_recovery_calls_go_back_to_vanilla(self) -> None:
        patched = {address: new for address, _vanilla, new in wc.dol_patch_words()}
        for site, vanilla in wc.LEGACY_HOOK_VANILLA_WORDS.items():
            self.assertEqual(vanilla, patched[site], "two hooks on one white-out would count it twice")

    def test_the_counter_did_not_move(self) -> None:
        self.assertEqual(0x80067444, wc.COUNTER_ADDRESS)

    @unittest.skipUnless(DOL.is_file(), "needs a real main.dol")
    def test_each_stub_counts_once_and_returns_with_r3_as_the_game_set_it(self) -> None:
        """Run the patched words: a tiny interpreter over the real main.dol."""
        data = DOL.read_bytes()
        offs = struct.unpack(">18I", data[0:72])
        addrs = struct.unpack(">18I", data[72:144])
        sizes = struct.unpack(">18I", data[144:216])
        mem = {}

        def word(address):
            if address in mem:
                return mem[address]
            for o, a, s in zip(offs, addrs, sizes):
                if s and a <= address < a + s:
                    return struct.unpack(">I", data[o + address - a:o + address - a + 4])[0]
            raise KeyError(hex(address))

        for address, vanilla, new in wc.dol_patch_words():
            self.assertIn(word(address), (vanilla, new), hex(address))
            mem[address] = new
        for site, _vanilla, immediate in wc.HOOK_SITES:
            regs = {3: 0xDEAD, 11: 0, 12: 0}
            pc, lr, before = site, None, word(wc.COUNTER_ADDRESS)
            for _ in range(10):
                w = word(pc)
                op = w >> 26
                rd, ra = (w >> 21) & 31, (w >> 16) & 31
                simm = struct.unpack(">h", struct.pack(">H", w & 0xFFFF))[0]
                if op == 18:                                   # b / bl
                    disp = w & 0x03FFFFFC
                    disp = disp - 0x04000000 if disp & 0x02000000 else disp
                    if w & 1:
                        lr = pc + 4
                    pc = (pc + disp) & 0xFFFFFFFF
                    continue
                if w == 0x4E800020:                            # blr
                    pc = lr
                    break
                if op == 15:                                   # addis / lis
                    regs[rd] = ((regs.get(ra, 0) if ra else 0) + (simm << 16)) & 0xFFFFFFFF
                elif op == 14:                                 # addi / li
                    regs[rd] = ((regs.get(ra, 0) if ra else 0) + simm) & 0xFFFFFFFF
                elif op == 32:                                 # lwz
                    regs[rd] = word((regs[ra] + simm) & 0xFFFFFFFF)
                elif op == 36:                                 # stw
                    mem[(regs[ra] + simm) & 0xFFFFFFFF] = regs[rd]
                else:
                    self.fail(f"unexpected instruction 0x{w:08X} at 0x{pc:08X}")
                pc += 4
            self.assertEqual(site + 4, pc)
            self.assertEqual(immediate, regs[3])
            self.assertEqual(before + 1, word(wc.COUNTER_ADDRESS))


class _Ram:
    def __init__(self, legacy=False):
        self.words = {site: (wc.HOOK_VANILLA_WORDS[site] if legacy else word) for site, word in wc.hook_words().items()}
        self.words.update({site: (word if legacy else wc.LEGACY_HOOK_VANILLA_WORDS[site])
                           for site, word in wc.LEGACY_HOOK_WORDS.items()})
        self.words[wc.COUNTER_ADDRESS] = 0

    def read(self, address, length):
        return struct.pack(">I", self.words[address])


class TestOlderISOsStillCount(unittest.TestCase):
    def test_both_layouts_are_read(self) -> None:
        for legacy in (False, True):
            ram = _Ram(legacy)
            watch = rc.WhiteoutCounterWatch()
            with mock.patch.object(rc, "read_bytes", side_effect=ram.read):
                self.assertEqual(0, watch.poll())
                ram.words[wc.COUNTER_ADDRESS] = 1
                self.assertEqual(1, watch.poll(), legacy)


class TestNoDuplicateDeath(unittest.TestCase):
    def setUp(self) -> None:
        self.bridge = rc.DeathLinkBridge(enabled=True)
        self.party = {"wiped": False}
        p = mock.patch.object(rc, "party_is_wiped", side_effect=lambda base: self.party["wiped"])
        p.start()
        self.addCleanup(p.stop)
        w = mock.patch.object(rc, "wipe_party", side_effect=self._wipe)
        w.start()
        self.addCleanup(w.stop)

    def _wipe(self, base):
        was = self.party["wiped"]
        self.party["wiped"] = True
        return 0 if was else 3

    def test_received_out_of_battle_then_white_out_at_the_next_battle(self) -> None:
        self.assertIsNotNone(self.bridge.receive(BLOCK, "someone else", in_battle=False))
        for _ in range(5):                                     # walking around with a fainted party
            self.assertFalse(self.bridge.poll(BLOCK, None, whiteouts=0)[0])
        # THE RACE: the client read the counter (no change), then the battle started and the game whited out --
        # counted, healed -- and THEN the client read the party: conscious, in the same poll.
        self.party["wiped"] = False
        self.assertFalse(self.bridge.poll(BLOCK, None, whiteouts=0)[0])
        self.assertFalse(self.bridge.poll(BLOCK, None, whiteouts=1)[0], "our own death, not sent back")
        self.assertEqual(0, self.bridge.sends)
        self.assertEqual(1, self.bridge.suppressed)
        # The next white-out is the player's own.
        self.assertTrue(self.bridge.poll(BLOCK, None, whiteouts=1)[0])

    def test_the_counter_seen_with_no_block_base_still_counts(self) -> None:
        self.bridge.receive(BLOCK, "x", in_battle=False)
        self.party["wiped"] = False
        self.assertFalse(self.bridge.poll(None, None, whiteouts=1)[0], "the warp's floor change: fenced, not lost")
        self.assertEqual(1, self.bridge.suppressed)
        self.assertTrue(self.bridge.poll(None, None, whiteouts=1)[0], "and a real one during a floor change sends")

    def test_two_deaths_received_before_one_white_out(self) -> None:
        self.bridge.receive(BLOCK, "a", in_battle=False)
        self.bridge.receive(BLOCK, "b", in_battle=False)        # party already down -- nothing more to wipe
        self.party["wiped"] = False
        self.assertFalse(self.bridge.poll(BLOCK, None, whiteouts=1)[0])
        self.assertEqual(0, self.bridge.sends)

    def test_healing_at_a_center_instead_releases_the_fence(self) -> None:
        self.bridge.receive(BLOCK, "x", in_battle=False)
        self.party["wiped"] = False                            # healed at a Pokemon Center -- no white-out
        for _ in range(rc.DeathLinkBridge.FENCE_RELEASE_POLLS):
            self.bridge.poll(BLOCK, None, whiteouts=0)
        self.assertFalse(self.bridge._ours)
        self.assertTrue(self.bridge.poll(BLOCK, None, whiteouts=1)[0], "a later white-out is theirs")

    def test_a_received_death_in_battle(self) -> None:
        with mock.patch.object(rc, "wipe_battle_party", return_value=2):
            self.bridge.receive(BLOCK, "x", in_battle=True)
        self.party["wiped"] = False
        self.assertFalse(self.bridge.poll(BLOCK, None, whiteouts=0)[0])
        self.assertFalse(self.bridge.poll(BLOCK, None, whiteouts=1)[0])
        self.assertEqual(0, self.bridge.sends)

    def test_two_white_outs_in_one_poll_one_ours(self) -> None:
        self.bridge.receive(BLOCK, "x", in_battle=False)
        self.assertTrue(self.bridge.poll(BLOCK, None, whiteouts=2)[0])
        self.assertEqual((1, 1), (self.bridge.sends, self.bridge.suppressed))


if __name__ == "__main__":
    unittest.main()
