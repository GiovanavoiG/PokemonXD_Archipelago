"""ADDENDUM 446 (2026-10-09) -- the Items pocket overflows into the PC, Poke Spot catch rates, Orre Colosseum.

Player: "Do we have enough info for the item overflow into PC? If so, do it. Catch Rate Scaling should make poke spot
pokemon much easier in general. Remove the travel unlock for Orre Colosseum and ensure no checks are there."
"""
from __future__ import annotations

import os
import struct
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from .. import Client
from .. import ram_client as rc
from ..tools import iso_patcher as ip

BASE = 0x80479000
POTION = 13
NET_BALL = 6
DUMPS = "/mnt/user-data/uploads/PokemonXD-working/bridge/dumps"


class _FakeMemory:
    def __init__(self) -> None:
        self.data: "dict[int, int]" = {}

    def read_bytes(self, address: int, length: int) -> bytes:
        return bytes(self.data.get(address + i, 0) for i in range(length))

    def write_bytes(self, address: int, data: bytes) -> None:
        for i, b in enumerate(data):
            self.data[address + i] = b

    def put(self, address: int, item_id: int, qty: int) -> None:
        self.write_bytes(address, struct.pack(">HH", item_id, qty))


class _Mem(unittest.TestCase):
    def setUp(self) -> None:
        self.mem = _FakeMemory()
        patches = [mock.patch.object(rc, "read_bytes", side_effect=self.mem.read_bytes),
                   mock.patch.object(rc, "write_bytes", side_effect=self.mem.write_bytes)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def fill_items_pocket(self) -> None:
        for i in range(rc.ITEMS_POCKET_MAX_SLOTS):
            self.mem.put(BASE + rc.ITEMS_POCKET_OFFSET + 4 * i, 100 + i, 1)


class TestTheLayout(unittest.TestCase):
    def test_offset_and_capacity(self) -> None:
        self.assertEqual(0xC1B0, rc.PC_ITEMS_OFFSET)
        self.assertEqual(235, rc.PC_ITEMS_MAX_SLOTS)
        self.assertEqual(BASE + 0xC1B0, rc.pc_items_base(BASE))

    @unittest.skipUnless(os.path.exists(f"{DUMPS}/pcitems1.bin") and os.path.exists(f"{DUMPS}/battle1.bin"),
                         "the two captures are not staged here")
    def test_both_captures_hold_the_deposit_at_the_offset_and_nowhere_else(self) -> None:
        for name in ("pcitems1.bin", "battle1.bin"):
            with open(f"{DUMPS}/{name}", "rb") as fh:
                mem = fh.read()
            pointer = struct.unpack(">I", mem[0x4EB6F8:0x4EB6FC])[0]
            base = pointer + 0x140 + 0x40
            at = base - 0x80000000 + rc.PC_ITEMS_OFFSET
            self.assertEqual(bytes.fromhex("0006000500D40001"), mem[at:at + 8], name)
            self.assertEqual(1, mem.count(bytes.fromhex("0006000500D40001")), f"{name}: one live copy only")


class TestValidity(_Mem):
    def test_empty_storage_is_valid(self) -> None:
        self.assertTrue(rc.pc_storage_looks_valid(BASE))

    def test_real_records_are_valid(self) -> None:
        self.mem.put(rc.pc_items_base(BASE), NET_BALL, 5)
        self.mem.put(rc.pc_items_base(BASE) + 4, 212, 1)
        self.assertTrue(rc.pc_storage_looks_valid(BASE))

    def test_garbage_is_refused(self) -> None:
        self.mem.put(rc.pc_items_base(BASE) + 4 * 100, 0x8047, 0x1234)
        self.assertFalse(rc.pc_storage_looks_valid(BASE))
        self.assertIsNone(rc.pc_overflow_target(BASE, POTION))

    def test_only_items_pocket_items_overflow(self) -> None:
        self.assertTrue(rc.overflows_to_pc(BASE, POTION))
        self.assertFalse(rc.overflows_to_pc(BASE, NET_BALL))     # Balls pocket
        self.assertFalse(rc.overflows_to_pc(BASE, 505))          # a key item
        self.assertFalse(rc.overflows_to_pc(BASE, None))


class TestTheDeposit(_Mem):
    def test_stacks_then_first_empty(self) -> None:
        pc = rc.pc_items_base(BASE)
        self.mem.put(pc, NET_BALL, 5)
        self.mem.put(pc + 4, POTION, 3)
        self.assertTrue(rc.give_pc_item(BASE, POTION, 2))
        self.assertEqual((POTION, 5), struct.unpack(">HH", self.mem.read_bytes(pc + 4, 4)))
        self.assertTrue(rc.give_pc_item(BASE, 20, 1))
        self.assertEqual((20, 1), struct.unpack(">HH", self.mem.read_bytes(pc + 8, 4)))

    def test_a_full_record_takes_a_new_slot(self) -> None:
        pc = rc.pc_items_base(BASE)
        self.mem.put(pc, POTION, rc.PC_ITEM_QUANTITY_MAX)
        self.assertTrue(rc.give_pc_item(BASE, POTION, 1))
        self.assertEqual((POTION, 1), struct.unpack(">HH", self.mem.read_bytes(pc + 4, 4)))
        self.assertEqual(rc.PC_ITEM_QUANTITY_MAX + 1, rc.pc_item_quantity(BASE, POTION))

    def test_a_full_pc_writes_nothing(self) -> None:
        pc = rc.pc_items_base(BASE)
        for i in range(rc.PC_ITEMS_MAX_SLOTS):
            self.mem.put(pc + 4 * i, 30 + (i % 150), 1)
        before = dict(self.mem.data)
        self.assertFalse(rc.give_pc_item(BASE, 400, 1))
        self.assertEqual(before, self.mem.data)


class TestTheClientPath(_Mem):
    def ctx(self) -> SimpleNamespace:
        return SimpleNamespace(block_base=BASE, _delivery_counts_pc={}, _delivery_pc_announced=set())

    def test_room_in_the_bag_never_touches_the_pc(self) -> None:
        ctx = self.ctx()
        pocket = BASE + rc.ITEMS_POCKET_OFFSET
        self.assertTrue(Client._give_item_or_pc_overflow(ctx, 0, "Potion", pocket, POTION, 1,
                                                         rc.ITEMS_POCKET_MAX_SLOTS, True))
        self.assertEqual(0, rc.pc_item_quantity(BASE, POTION))
        self.assertEqual(1, rc.find_item_quantity(pocket, rc.ITEMS_POCKET_MAX_SLOTS, POTION))

    def test_a_full_pocket_goes_to_the_pc_and_says_so_once(self) -> None:
        self.fill_items_pocket()
        ctx = self.ctx()
        pocket = BASE + rc.ITEMS_POCKET_OFFSET
        with self.assertLogs("Client", level="INFO") as logs:
            for _ in range(2):
                self.assertTrue(Client._give_item_or_pc_overflow(ctx, 7, "Potion", pocket, POTION, 1,
                                                                 rc.ITEMS_POCKET_MAX_SLOTS, True))
        self.assertEqual(2, rc.pc_item_quantity(BASE, POTION))
        self.assertEqual(1, sum("went to your PC" in line for line in logs.output))

    def test_not_allowed_means_the_old_wait(self) -> None:
        self.fill_items_pocket()
        ctx = self.ctx()
        self.assertFalse(Client._give_item_or_pc_overflow(ctx, 0, "Potion", BASE + rc.ITEMS_POCKET_OFFSET, POTION,
                                                          1, rc.ITEMS_POCKET_MAX_SLOTS, False))
        self.assertEqual(0, rc.pc_item_quantity(BASE, POTION))

    def test_the_count_is_bag_plus_pc_only_when_decided_at_the_baseline(self) -> None:
        ctx = self.ctx()
        pocket = BASE + rc.ITEMS_POCKET_OFFSET
        self.mem.put(pocket, POTION, 2)
        self.mem.put(rc.pc_items_base(BASE), POTION, 5)
        self.assertEqual(2, Client._held_quantity(ctx, 1, pocket, rc.ITEMS_POCKET_MAX_SLOTS, POTION))
        ctx._delivery_counts_pc[1] = True
        self.assertEqual(7, Client._held_quantity(ctx, 1, pocket, rc.ITEMS_POCKET_MAX_SLOTS, POTION))

    def test_the_delivery_loop_decides_once_and_cleans_up(self) -> None:
        source = Path(Client.__file__).read_text(encoding="utf-8")
        body = source.split("async def give_items", 1)[1].split("\ndef force_deliver_pending_items", 1)[0]
        self.assertEqual(1, body.count("ctx._delivery_counts_pc[idx] = ram_client.may_overflow_to_pc("))
        self.assertLess(body.index("_delivery_counts_pc[idx] = "), body.index("_delivery_pending_baseline[idx] = "))
        self.assertIn("ctx._delivery_counts_pc.pop(idx, None)", body)
        self.assertIn("current = _held_quantity(ctx, idx, read_base, read_slots, game_item_id)", body)


class TestPokeSpotCatchRates(unittest.TestCase):
    def test_full_boost_whatever_the_setting(self) -> None:
        rates = {10: 45, 11: 255, 12: 3, 13: 0, 14: 190}
        for scaling in (1, 30, 100):
            plan = ip.plan_pokespot_catch_rate(rates, {10, 11, 12, 13}, scaling)
            self.assertEqual({"10": 255, "12": 255}, plan["catch_rate"], scaling)
            self.assertEqual(2, plan["raised"])
        self.assertNotIn("14", ip.plan_pokespot_catch_rate(rates, {10}, 50)["catch_rate"],
                         "only the species in the spots")

    def test_the_patcher_wires_it_and_max_catch_wins(self) -> None:
        source = Path(ip.__file__).read_text(encoding="utf-8")
        self.assertIn('pokespot_catch_scaling = int(seed.get("catch_rate_scaling") or 0) if not max_catch_rate else 0',
                      source)
        self.assertIn("rel_format.pokespot_species_indices(rel_bytes, rel)", source)
        # after the species reassignment, so the boost lands on the species really in the spots
        self.assertLess(source.index("rel_format.apply_pokespot_species("),
                        source.index("rel_format.pokespot_species_indices(rel_bytes, rel)"))

    def test_the_option_text_says_so(self) -> None:
        from .. import options

        self.assertIn("Wild Poke Spot Pokemon get the highest catch rate wherever they are",
                      " ".join(options.CatchRateScaling.__doc__.split()))


class TestOrreColosseum(unittest.TestCase):
    def test_gone_everywhere(self) -> None:
        from .. import items, locations, travel_locations as tl

        self.assertNotIn("Travel Unlock - Orre Colosseum", items.ITEM_TABLE)
        self.assertNotIn("Unlock - Orre Colosseum", locations.LOCATION_TABLE)
        self.assertNotIn("Orre Colosseum", tl.TRAVEL_LOCATION_BITS)
        self.assertEqual(10, len(tl.TRAVEL_LOCATION_NAMES))
        self.assertFalse([n for n in locations.LOCATION_TABLE if "Orre Colosseum" in n])


if __name__ == "__main__":
    unittest.main()
