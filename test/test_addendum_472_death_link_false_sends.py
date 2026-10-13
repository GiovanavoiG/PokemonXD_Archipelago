"""ADDENDUM 472 (2026-10-12) -- Death Links sent at full HP, and wipes that sent nothing.

Arc: a death went out "when entering the first fight in the Snagem hideout" with every party member at full HP; the
readout blamed "your team fainting in battle". Zozu: four sent, and some real wipes sent nothing.

The battle flag also reads 1 in menus, so the battle records were sometimes located on a PREVIOUS battle's leftovers.
When the next battle rebuilt that memory, the cached addresses read 0 HP and the watch reported a wipe. The fixes:
  * each read re-checks the record is still the one located (species, a max HP, HP not above it) and forgets it
    otherwise;
  * a wipe must read on two polls in a row (the records hold zero through the white-out's end screens);
  * the save-side "party at 0 HP" edge also needs two polls;
  * a boot whose records sit outside the scan window gets one full-memory locate per battle, instead of never
    answering (a real wipe that sent nothing).
"""
from __future__ import annotations

import struct
import unittest
from unittest import mock

from .. import ram_client as rc
from .test_addendum_417_the_in_battle_kill import BATTLE, BLOCK, MEMBASE, CLIENT, _FakeRam, _image


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.mem, _ = _image()
        ram = _FakeRam(self.mem)
        for p in (mock.patch.object(rc, "read_bytes", side_effect=ram.read),
                  mock.patch.object(rc, "write_bytes", side_effect=ram.write),
                  mock.patch.object(rc, "BATTLE_RECORD_SCAN_WINDOW", len(self.mem)),
                  mock.patch.object(rc, "read_annihilation_flag", return_value=None)):
            p.start()
            self.addCleanup(p.stop)
        self.watch = rc.BattlePartyWatch()
        self.bridge = rc.DeathLinkBridge()
        self.bridge.enabled = True

    def _tick(self, in_battle=True):
        return self.bridge.poll(BLOCK, self.watch.poll(BLOCK, in_battle))

    def _set_hp(self, hp: int) -> None:
        for i in range(3):
            struct.pack_into(">H", self.mem, BATTLE + i * 0x300 + rc.POKEMON_HP_OFFSET, hp)


class TestStaleRecords(_Base):
    def test_a_cleared_record_is_forgotten_not_reported(self) -> None:
        """Arc's case: located on leftovers, then the next battle clears that memory. Full HP, no death."""
        self.assertFalse(self._tick()[0])
        for i in range(3):
            base = BATTLE + i * 0x300
            self.mem[base:base + rc.POKEMON_STRIDE] = bytes(rc.POKEMON_STRIDE)
        for _ in range(5):
            self.assertFalse(self._tick()[0])
        self.assertEqual(0, self.bridge.sends)
        self.assertGreaterEqual(self.watch.stale_resets, 1)

    def test_one_zero_read_mid_rebuild_is_not_a_wipe(self) -> None:
        self.assertFalse(self._tick()[0])
        self._set_hp(0)
        self.assertFalse(self._tick()[0])
        self._set_hp(40)                          # the rebuild finished: everyone is back
        self.assertFalse(self._tick()[0])
        self._set_hp(0)
        self.assertFalse(self._tick()[0])         # streak starts again
        self.assertEqual(0, self.bridge.sends)

    def test_a_real_loss_still_sends_once(self) -> None:
        self._tick()
        self._set_hp(0)
        results = [self._tick()[0] for _ in range(6)]
        self.assertEqual([False, True, False, False, False, False], results)
        self.assertEqual(1, self.bridge.sends_by_battle)

    def test_hp_above_max_is_not_this_record(self) -> None:
        self._tick()
        struct.pack_into(">H", self.mem, BATTLE + rc.POKEMON_HP_OFFSET, 0xFFFF)
        self.assertIsNone(self.watch.poll(BLOCK, True))
        self.assertEqual([], self.watch.addresses)


class TestTheSaveSideEdge(_Base):
    def test_one_read_of_a_zero_party_sends_nothing(self) -> None:
        with mock.patch.object(rc, "party_is_wiped", side_effect=[True, False, False]):
            for _ in range(3):
                self.assertFalse(self.bridge.poll(BLOCK, None)[0])
        self.assertEqual(0, self.bridge.sends)

    def test_a_party_that_stays_down_sends(self) -> None:
        with mock.patch.object(rc, "party_is_wiped", side_effect=[False, True, True, True]):
            sent = [self.bridge.poll(BLOCK, None)[0] for _ in range(4)]
        self.assertEqual([False, False, True, False], sent)
        self.assertEqual(1, self.bridge.sends_by_hp)

    def test_our_own_wipe_is_still_fenced_on_the_first_read(self) -> None:
        self.bridge._ours = True
        with mock.patch.object(rc, "party_is_wiped", side_effect=[True, True]):
            self.assertFalse(self.bridge.poll(BLOCK, None)[0])
        self.assertEqual(1, self.bridge.suppressed)


class TestTheFullMemoryLocate(_Base):
    def test_records_outside_the_window_are_still_found_once(self) -> None:
        with mock.patch.object(rc, "BATTLE_RECORD_SCAN_WINDOW", 0x100), \
                mock.patch.object(rc, "dump_mem1", return_value=bytes(self.mem)) as dump, \
                mock.patch.object(rc, "MEM1_START", MEMBASE):
            self.assertFalse(self._tick()[0])
            self.assertEqual(1, dump.call_count)
            self.assertEqual(3, len(self.watch.addresses))
            self._set_hp(0)
            self._tick()
            self.assertTrue(self._tick()[0])

    def test_only_once_per_battle(self) -> None:
        with mock.patch.object(rc, "BATTLE_RECORD_SCAN_WINDOW", 0x100), \
                mock.patch.object(rc, "dump_mem1", return_value=b"") as dump:
            for _ in range(20):
                self.watch.poll(BLOCK, True)
            self.assertEqual(1, dump.call_count)
            self.watch.poll(BLOCK, False)              # the battle ended
            for _ in range(3):
                self.watch.poll(BLOCK, True)
            self.assertEqual(2, dump.call_count)


class TestTheReadout(unittest.TestCase):
    def test_deathlink_reports_the_watch(self) -> None:
        self.assertIn("Battle watch:", CLIENT)
        self.assertIn("stale record set(s) dropped", CLIENT)


if __name__ == "__main__":
    unittest.main()
