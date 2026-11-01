"""Purification Unlocks: one `Purify Unlock - {species}` item per Shadow species in the seed, and the client's
writes of the AP patch block (ap_patch.py) that make it real in game."""
from __future__ import annotations

import struct
import unittest
from unittest import mock

from BaseClasses import ItemClassification

from . import PokemonXDTestBase
from .. import ap_patch, items, locations, species


class TestUnlockItemTable(unittest.TestCase):
    def test_one_frozen_id_per_species(self) -> None:
        self.assertEqual(len(items.PURIFY_UNLOCK_ITEMS), len(species.NATIONAL_DEX))
        self.assertEqual(items.ITEM_TABLE["Purify Unlock - Bulbasaur"].id_offset, 262)
        self.assertEqual(items.ITEM_TABLE["Purify Unlock - Deoxys"].id_offset, 647)
        for name, dex in items.PURIFY_UNLOCK_ITEM_TO_DEX.items():
            self.assertEqual(items.ITEM_TABLE[name].id_offset, 261 + dex)
            self.assertIsNone(items.ITEM_TABLE[name].game_item_id)

    def test_grouped_and_never_drawn_as_filler(self) -> None:
        self.assertEqual(items.ITEM_NAME_GROUPS["Purify Unlocks"], set(items.PURIFY_UNLOCK_ITEMS))
        self.assertFalse(set(items.PURIFY_UNLOCK_ITEMS) & set(items.FILLER_ITEMS))


class TestApPatchBlock(unittest.TestCase):
    def test_layout(self) -> None:
        self.assertEqual(ap_patch.GIVE_PURIFY_COUNTER_ADDRESS, 0x81700F94)
        self.assertEqual(ap_patch.GIVE_PURIFIED_ADDRESS, 0x81700F96)
        block = ap_patch.purify_unlock_block([12, 3, 12, 0, 200])
        self.assertEqual(len(block), 2 + 2 * ap_patch.NUMBER_OF_SHADOW_POKEMON)
        self.assertEqual(struct.unpack_from(">HHH", block), (2, 3, 12))
        self.assertEqual(set(block[6:]), {0})

    def test_flags(self) -> None:
        self.assertEqual(ap_patch.flags_from_slot_data({}), 0)
        self.assertEqual(ap_patch.flags_from_slot_data({"purification_unlocks": 1}), 1 << ap_patch.FLAG_PURIFY_CHECKS)
        self.assertEqual(ap_patch.flags_from_slot_data({"purification_unlocks": 1, "death_link": 1}),
                         (1 << ap_patch.FLAG_PURIFY_CHECKS) | (1 << ap_patch.FLAG_DEATH_LINK))


class TestApPatchSync(unittest.TestCase):
    def setUp(self) -> None:
        self.memory = bytearray(0x1100)
        self.writes = 0

        def read(address: int, length: int) -> bytes:
            offset = address - ap_patch.AP_DATA_BASE
            return bytes(self.memory[offset:offset + length])

        def write(address: int, data: bytes) -> None:
            self.writes += 1
            offset = address - ap_patch.AP_DATA_BASE
            self.memory[offset:offset + len(data)] = data

        patcher = mock.patch.multiple(ap_patch.ram_client, read_bytes=read, write_bytes=write)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sync = ap_patch.ApPatchSync()
        self.sync.configure({"purification_unlocks": 1, "purify_unlock_ddpks": {"216": [1], "37": [2, 90]}})

    def counter_and_ids(self) -> "tuple[int, list[int]]":
        count = struct.unpack_from(">H", self.memory, 0xF94)[0]
        return count, list(struct.unpack_from(f">{count}H", self.memory, 0xF96))

    def test_writes_received_unlocks_then_holds_still(self) -> None:
        self.assertIsNotNone(self.sync.poll({37}))
        self.assertEqual(self.counter_and_ids(), (2, [2, 90]))
        self.assertEqual(struct.unpack_from(">H", self.memory, 0)[0], 1 << ap_patch.FLAG_PURIFY_CHECKS)
        writes = self.writes
        self.assertIsNone(self.sync.poll({37}))
        self.assertEqual(self.writes, writes)

    def test_a_cleared_block_is_restored(self) -> None:
        self.sync.poll({37, 216})
        self.memory[:] = bytes(len(self.memory))   # a cold boot
        note = self.sync.poll({37, 216})
        self.assertIn("re-applied", note)
        self.assertEqual(self.counter_and_ids(), (3, [1, 2, 90]))

    def test_an_older_seed_is_never_written(self) -> None:
        self.sync.configure({"death_link": 1})
        self.assertIsNone(self.sync.poll({37}))
        self.assertEqual(self.writes, 0)


class TestUnlocksOff(PokemonXDTestBase):
    options = {"purification_unlocks": 0}

    def test_no_unlocks_in_the_pool(self) -> None:
        self.assertFalse([i for i in self.multiworld.itempool if i.name in items.PURIFY_UNLOCK_ITEMS])
        self.assertEqual(self.world.fill_slot_data()["purify_unlock_ddpks"], {})


class TestUnlocksOn(PokemonXDTestBase):
    options = {"purification_unlocks": 1, "purification_checks": 1, "purification_progression_cap": 20,
               "shadow_pokemon_expansion": 10}

    def unlocks(self) -> "list":
        return [i for i in self.multiworld.itempool if i.name in items.PURIFY_UNLOCK_ITEMS]

    def test_one_unlock_per_shadow_species(self) -> None:
        mapping = self.world.fill_slot_data()["purify_unlock_ddpks"]
        self.assertEqual(sorted(i.name for i in self.unlocks()),
                         sorted(items.purify_unlock_item_name(int(dex)) for dex in mapping))
        ddpks = [d for ids in mapping.values() for d in ids]
        self.assertEqual(len(ddpks), len(set(ddpks)))
        self.assertTrue(all(0 < d < 0x80 for d in ddpks))

    def test_expansion_shadows_are_pinned_past_the_vanilla_records(self) -> None:
        pinned = [mon["target_ddpk_index"] for plan in self.world._shadow_expansion_plans or ()
                  for mon in plan["new_pokemon"]]
        self.assertTrue(pinned)
        self.assertEqual(pinned, list(range(84, 84 + len(pinned))))

    def test_progression_unlocks_cover_the_cap(self) -> None:
        progression = [i for i in self.unlocks() if i.classification & ItemClassification.progression]
        self.assertTrue(progression)
        dex_by_ddpk = self.world._shadow_dex_by_ddpk
        chosen = {items.PURIFY_UNLOCK_ITEM_TO_DEX[i.name] for i in progression}
        covered = sum(1 for ddpk, dex in dex_by_ddpk.items()
                      if dex in chosen and ddpk not in self.world._post_goal_ddpks)
        self.assertGreaterEqual(covered, 20)
        self.assertTrue(all(i.classification == ItemClassification.useful or
                            i.classification == ItemClassification.filler
                            for i in self.unlocks() if i not in progression))

    def test_a_progression_rung_needs_its_unlocks(self) -> None:
        state = self.multiworld.get_all_state(False)
        rung = self.multiworld.get_location(locations.purification_location_name(1), self.player)
        self.assertTrue(rung.can_reach(state))
        for item in [i for i in self.unlocks() if i.classification & ItemClassification.progression]:
            state.remove(item)
        self.assertFalse(rung.can_reach(state))
