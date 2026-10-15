"""ADDENDUM 420 (2026-10-05) -- key items you were not sent are removed: proven against the real Bag layout.

Key items were not being removed when they had not been sent -- the Machine Part among them. Every key item in
the pool is removed from the Bag unless Archipelago has sent it.
"""
import struct
import unittest
from types import SimpleNamespace

from .. import ram_client as rc
from ..game_data import key_items

BLOCK = 0x804794C0
# The Key Items pocket exactly as the 2026-10-04 live dump held it: Cologne Case, Machine Part, Miror Radar,
# Data ROM, ID Card, System Lever.
LIVE_KEY_POCKET = [(512, 1), (503, 1), (510, 1), (505, 1), (506, 1), (508, 1)]


class _Mem:
    def __init__(self, size=0x100000, base=0x80400000):
        self.base, self.mem = base, bytearray(size)
        self._r, self._w = rc.read_bytes, rc.write_bytes
        rc.read_bytes = lambda a, n: bytes(self.mem[a - self.base:a - self.base + n])
        rc.write_bytes = lambda a, d: self.mem.__setitem__(slice(a - self.base, a - self.base + len(d)), d)

    def restore(self):
        rc.read_bytes, rc.write_bytes = self._r, self._w

    def put_pocket(self, offset, entries):
        for i, (item, qty) in enumerate(entries):
            struct.pack_into(">HH", self.mem, BLOCK + offset + i * 4 - self.base, item, qty)

    def pocket(self, offset, slots):
        out = [struct.unpack_from(">HH", self.mem, BLOCK + offset + i * 4 - self.base) for i in range(slots)]
        return [e for e in out if e[0]]


class TestTheGameReadsWhereWeWrite(unittest.TestCase):
    """From the DOL: scriptHaveItem -> heroGetStatus(5) -> hero + 0x540, 43 slots; items hero + 0x4C8, 30."""

    def test_the_offsets_agree_with_the_games_own_accessors(self):
        hero_to_block = rc.RECORD_TRAINER_NAME_OFFSET
        self.assertEqual(0x540 - hero_to_block, rc.KEY_ITEMS_OFFSET)
        self.assertEqual(43, rc.KEY_ITEMS_MAX_SLOTS)
        self.assertEqual(0x4C8 - hero_to_block, rc.ITEMS_POCKET_OFFSET)
        self.assertEqual(30, rc.ITEMS_POCKET_MAX_SLOTS)
        self.assertEqual(0x180, rc.SAVEDATA_HERO_OFFSET + rc.RECORD_TRAINER_NAME_OFFSET)

    def test_every_pool_key_item_with_a_bag_entry_is_managed(self):
        self.assertEqual({503, 505, 506, 507, 508, 509}, set(key_items.POLLED_GAME_ITEM_IDS))


class TestTheLiveBag(unittest.TestCase):
    def setUp(self):
        self.mem = _Mem()
        self.mem.put_pocket(rc.KEY_ITEMS_OFFSET, LIVE_KEY_POCKET)

    def tearDown(self):
        self.mem.restore()

    def test_nothing_received_removes_every_pool_key_item(self):
        r = rc.KeyItemReconciler()
        written, cleared = r.poll(BLOCK, frozenset(), key_items.POLLED_GAME_ITEM_IDS)
        self.assertEqual((), written)
        self.assertEqual((503, 505, 506, 508), cleared)
        self.assertEqual([(512, 1), (510, 1)], self.mem.pocket(rc.KEY_ITEMS_OFFSET, 43),
                         "the Cologne Case and Miror Radar are not pool items and stay")

    def test_a_received_machine_part_stays(self):
        r = rc.KeyItemReconciler()
        _w, cleared = r.poll(BLOCK, frozenset({503}), key_items.POLLED_GAME_ITEM_IDS)
        self.assertNotIn(503, cleared)
        self.assertIn((503, 1), self.mem.pocket(rc.KEY_ITEMS_OFFSET, 43))

    def test_one_filed_in_the_items_pocket_is_found_too(self):
        self.mem.put_pocket(rc.ITEMS_POCKET_OFFSET, [(23, 2), (503, 1)])
        r = rc.KeyItemReconciler()
        r.poll(BLOCK, frozenset(), key_items.POLLED_GAME_ITEM_IDS)
        self.assertEqual([(23, 2)], self.mem.pocket(rc.ITEMS_POCKET_OFFSET, 30))


class TestTheBlockBaseTieBreak(unittest.TestCase):
    def setUp(self):
        self._dump = rc.dump_mem1

    def tearDown(self):
        rc.dump_mem1 = self._dump

    def _mem_with(self, blocks, savedata_block):
        mem = bytearray(rc.MEM1_SIZE)
        for block in blocks:
            name = block - rc.RECORD_TRAINER_NAME_OFFSET - rc.MEM1_START
            mem[name:name + 6] = "ASH".encode("utf-16-be")
            marker = block + rc.MONEY_DISPLAY_MARKER_OFFSET - rc.MEM1_START
            mem[marker:marker + 8] = b"\x01" * 8
        struct.pack_into(">I", mem, rc.SAVEDATA_NOW_POINTER - rc.MEM1_START, savedata_block - 0x180)
        return bytes(mem)

    def test_the_games_savedata_wins_among_validated_copies(self):
        rc.dump_mem1 = lambda: self._mem_with([0x80478000, 0x804794C0], 0x804794C0)
        self.assertEqual(0x804794C0, rc.resolve_block_base("ASH"))

    def test_a_pointer_to_nothing_validated_changes_nothing(self):
        rc.dump_mem1 = lambda: self._mem_with([0x80478000, 0x804794C0], 0x80300000)
        self.assertEqual(0x80478000, rc.resolve_block_base("ASH"))


class TestWhereItCameFrom(unittest.TestCase):
    def test_the_readout_names_the_sender(self):
        from .. import Client
        ctx = SimpleNamespace(
            key_item_shuffle=True, slot=1, player_names={1: "Me", 2: "Friend"},
            items_received=[SimpleNamespace(item=Client.ITEM_NAME_TO_ID["Machine Part"], player=2, location=77),
                            SimpleNamespace(item=Client.ITEM_NAME_TO_ID["Music Disc"], player=1, location=5)],
            location_names=SimpleNamespace(lookup_in_slot=lambda loc, player: f"Loc{loc}"))
        lines = Client.key_item_sources(ctx)
        self.assertEqual(["  Machine Part: received from Friend's world (Loc77).",
                          "  Music Disc: received from your own world (Loc5)."], lines)

    def test_off_without_key_item_shuffle(self):
        from .. import Client
        ctx = SimpleNamespace(key_item_shuffle=False, items_received=[])
        self.assertEqual([], Client.key_item_sources(ctx))


if __name__ == "__main__":
    unittest.main()
