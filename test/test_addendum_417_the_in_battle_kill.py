"""ADDENDUM 417 (2026-10-04) -- Death Link kills in battle, on the battle's own copy of the party.

Measured live with the player: zeroing the save-side party did nothing in battle (opening the party restored
everyone), zeroing the HP display did nothing, zeroing the battle records at 0x804A2128 + i*0x300 (+0x04) made the
player white out. These tests pin the finder and the receive path against a synthetic memory image shaped like that
capture.
"""
from __future__ import annotations

import struct
import unittest
from pathlib import Path
from unittest import mock

from .. import ram_client as rc

BLOCK = 0x804794C0
MEMBASE = BLOCK - 0x100      # the image starts a little below the block: the live party sits at BLOCK - 0x10
CLIENT = (Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")


def _record(species: int, hp: int, level: int, max_hp: int, salt: int) -> bytearray:
    raw = bytearray(rc.POKEMON_STRIDE)
    struct.pack_into(">H", raw, 0, species)
    struct.pack_into(">H", raw, rc.POKEMON_HP_OFFSET, hp)
    raw[rc.POKEMON_LEVEL_OFFSET] = level
    struct.pack_into(">H", raw, rc.POKEMON_MAXHP_OFFSET, max_hp)
    for k in range(2, 0x18, 2):          # five stats + EVs, unique per Pokemon
        struct.pack_into(">H", raw, rc.POKEMON_MAXHP_OFFSET + k, salt * 7 + k)
    return raw


TEAM = [(354, 124, 47, 124, 1), (128, 163, 56, 163, 2), (201, 52, 19, 52, 3)]
MIRROR = 0x2831C + 0x100  # mirror party, relative to MEMBASE (this boot: 0x804A17DC)
BATTLE = 0x28C68 + 0x100  # battle records, relative to MEMBASE (this boot: 0x804A2128)


def _image(with_battle: bool = True) -> "tuple[bytearray, list[rc.LivePartyMember]]":
    mem = bytearray(0x40000)
    members = []
    for i, spec in enumerate(TEAM):
        raw = _record(*spec)
        live = rc.party_slot_address(BLOCK, i)
        mem[live - MEMBASE:live - MEMBASE + len(raw)] = raw
        members.append(rc.LivePartyMember(index=i, address=live, raw=bytes(raw)))
        mirror = MIRROR + i * 0xC4
        mem[mirror:mirror + len(raw)] = raw
        if with_battle:
            record = BATTLE + i * 0x300
            struct.pack_into(">I", mem, record - 4, MEMBASE + mirror)
            mem[record:record + len(raw)] = raw
    return mem, members


class TestTheFinder(unittest.TestCase):
    def test_it_finds_exactly_the_battle_records(self) -> None:
        mem, members = _image()
        self.assertEqual([MEMBASE + BATTLE + i * 0x300 for i in range(3)],
                         rc.find_battle_party_records(bytes(mem), MEMBASE, members))

    def test_not_the_live_record_and_not_the_mirror(self) -> None:
        mem, members = _image(with_battle=False)
        self.assertEqual([], rc.find_battle_party_records(bytes(mem), MEMBASE, members))

    def test_two_candidates_for_one_pokemon_writes_neither(self) -> None:
        mem, members = _image()
        extra = BATTLE + 6 * 0x300
        struct.pack_into(">I", mem, extra - 4, MEMBASE + MIRROR)
        mem[extra:extra + rc.POKEMON_STRIDE] = members[0].raw
        found = rc.find_battle_party_records(bytes(mem), MEMBASE, members)
        self.assertNotIn(MEMBASE + BATTLE, found)
        self.assertEqual(2, len(found))


class _FakeRam:
    def __init__(self, mem: bytearray) -> None:
        self.mem = mem

    def read(self, address: int, length: int) -> bytes:
        o = address - MEMBASE
        return bytes(self.mem[o:o + length])

    def write(self, address: int, data: bytes) -> None:
        o = address - MEMBASE
        self.mem[o:o + len(data)] = data


class TestTheReceivePath(unittest.TestCase):
    def _bridge(self, mem):
        ram = _FakeRam(mem)
        patches = [mock.patch.object(rc, "read_bytes", side_effect=ram.read),
                   mock.patch.object(rc, "write_bytes", side_effect=ram.write),
                   mock.patch.object(rc, "BATTLE_RECORD_SCAN_WINDOW", len(mem))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        bridge = rc.DeathLinkBridge()
        bridge.enabled = True
        return bridge

    def _hp(self, mem, offset):
        return struct.unpack_from(">H", mem, offset + rc.POKEMON_HP_OFFSET)[0]

    def test_in_battle_it_zeroes_the_battle_records_and_fences_the_loop(self) -> None:
        mem, _members = _image()
        bridge = self._bridge(mem)
        note = bridge.receive(BLOCK, "test", in_battle=True)
        self.assertIn("white out now", note)
        self.assertEqual([0, 0, 0], [self._hp(mem, BATTLE + i * 0x300) for i in range(3)])
        self.assertTrue(bridge._ours)
        self.assertEqual(1, bridge.battle_wipes)

    def test_outside_battle_the_battle_records_are_never_touched(self) -> None:
        mem, _members = _image()
        bridge = self._bridge(mem)
        bridge.receive(BLOCK, "test", in_battle=False)
        self.assertEqual([124, 163, 52], [self._hp(mem, BATTLE + i * 0x300) for i in range(3)])
        self.assertEqual(0, bridge.battle_wipes)


class TestTheSendSide(unittest.TestCase):
    """The player whited out and no Death Link went: the save-side party is healed before it reads zero, and the
    derived annihilation flag does not read on their build. The battle records do."""

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

    def _faint_all(self) -> None:
        for i in range(3):
            struct.pack_into(">H", self.mem, BATTLE + i * 0x300 + rc.POKEMON_HP_OFFSET, 0)

    def _tick(self, in_battle=True):
        return self.bridge.poll(BLOCK, self.watch.poll(BLOCK, in_battle))

    def test_a_loss_in_battle_sends_once(self) -> None:
        self.assertEqual((False, None), self._tick())
        self._faint_all()
        sent, note = self._tick()
        self.assertTrue(sent)
        self.assertIn("fainted in battle", note)
        self.assertFalse(self._tick()[0], "edge-triggered: one loss, one death")
        self.assertEqual(1, self.bridge.sends_by_battle)

    def test_leftover_zeros_outside_a_seen_battle_never_send(self) -> None:
        """After a loss the records stay zero. Opening the bag (battle flag 1) must not read that as a death."""
        self._faint_all()
        self.assertEqual(None, self.watch.poll(BLOCK, True))
        self.assertFalse(self._tick()[0])

    def test_nothing_is_read_outside_a_battle(self) -> None:
        self._faint_all()
        self.assertIsNone(self.watch.poll(BLOCK, False))
        self.assertEqual([], self.watch.addresses)

    def test_our_own_in_battle_kill_is_not_sent_back(self) -> None:
        self._tick()
        self.bridge.receive(BLOCK, "someone else", in_battle=True)
        sent, _note = self._tick()
        self.assertFalse(sent)
        self.assertEqual(1, self.bridge.suppressed)


class TestTheClient(unittest.TestCase):
    def test_the_send_side_reads_the_battle_records(self) -> None:
        self.assertIn("ctx.battle_party_watch.poll(ctx.block_base, in_battle)", CLIENT)
        self.assertIn("ctx.death_link_bridge.poll(ctx.block_base, battle_wiped)", CLIENT)

    def test_on_deathlink_passes_the_battle_flag(self) -> None:
        body = CLIENT.split("def on_deathlink", 1)[1].split("\n    def ", 1)[0]
        self.assertIn("ram_client.read_battle_ui_flag() == 1", body)
        self.assertIn("in_battle=in_battle", body)


if __name__ == "__main__":
    unittest.main()
