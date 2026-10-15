"""ADDENDUM 453 (2026-10-09) -- the ABILITY PATCH, reworked by ADDENDUM 454 into the ABILITY SWAP (a USE item).

The Ability Patch cycles through a Pokemon's abilities. It is sold in the Gateon shop after all the Kyogre parts,
costs 2000, and appears regardless of options.
"""
from __future__ import annotations

import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from . import PokemonXDTestBase
from .. import Client
from .. import locations as L
from .. import ram_client as rc
from ..game_data import ability_patch as AP
from ..game_data import item_descriptions

RAM_DUMP = Path("/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/battle1.bin")


class TestTheData(unittest.TestCase):
    """ADDENDUM 454 reworked it: the Green Shard as ABILITYSWAP, a Bag USE item (see test_addendum_454_*)."""

    def test_name_price_and_line(self) -> None:
        self.assertEqual("ABILITYSWAP", AP.ABILITY_PATCH_NAME)
        self.assertEqual(len(AP.ABILITY_PATCH_VANILLA_NAME), len(AP.ABILITY_PATCH_NAME))
        self.assertEqual(2000, AP.ABILITY_PATCH_PRICE)
        self.assertEqual({6: struct.pack(">H", 2000)}, AP.row_edits())
        self.assertEqual((15, 13), (AP.GATEON_FINAL_MART, AP.ABILITY_PATCH_LINE))
        self.assertEqual(AP.DESCRIPTION_ENTRY, item_descriptions.ITEM_DESCRIPTION_ENTRIES[AP.ABILITY_PATCH_ITEM_ID])
        self.assertTrue(all(len(line) <= 20 for line in AP.DESCRIPTION_LINES))
        self.assertNotIn(192, item_descriptions.ITEM_DESCRIPTION_ENTRIES, "the DeepSeaTooth is vanilla again")

    def test_the_flag_bit(self) -> None:
        self.assertEqual(0x40, AP.toggled_flag_byte(0x00))
        self.assertEqual(0x05, AP.toggled_flag_byte(0x45))

    @unittest.skipUnless(RAM_DUMP.is_file(), "needs a RAM dump with XD's tables")
    def test_against_the_games_own_tables(self) -> None:
        data = RAM_DUMP.read_bytes()
        base = 0x80B38CA4 - 0x80000000
        row = data[base + AP.ABILITY_PATCH_ITEM_ID * 0x28:][:0x28]
        self.assertEqual(AP.ABILITY_PATCH_NAME_ID, struct.unpack_from(">I", row, 0x10)[0])
        self.assertEqual(200, struct.unpack_from(">H", row, 6)[0])
        self.assertEqual(AP.DESCRIPTION_ENTRY[2], struct.unpack_from(">I", row, 0x14)[0])
        self.assertEqual((AP.HOOK_ADDRESS, AP.HOOK_ADDRESS), struct.unpack_from(">II", row, 0x1C),
                         "field and battle use both go through the hooked 'can't use' handler")
        word = lambda a: struct.unpack_from(">I", data, a - 0x80000000)[0]
        count, species_base = word(word(0x804EFE20 - 22508)), word(0x804EFE20 - 22504)
        two = frozenset(s for s in range(count) if data[species_base - 0x80000000 + s * 0x124 + 0x33])
        self.assertEqual(AP.TWO_ABILITY_SPECIES, two)


class TestTheHeldDesignIsGone(unittest.TestCase):
    def test_no_tracker(self) -> None:
        self.assertFalse(hasattr(rc, "AbilityPatchTracker"))
        source = Path(Client.__file__).read_text(encoding="utf-8")
        self.assertNotIn("check_ability_patch", source)
        self.assertNotIn("_field_is_safe", source)


class TestEverySeed(PokemonXDTestBase):
    options = {"randomize_shops": True}

    def test_on_and_the_line_is_not_a_check(self) -> None:
        world = self.multiworld.worlds[self.player]
        self.assertNotIn(L.ability_patch_shop_location_name(),
                         {loc.name for loc in self.multiworld.get_locations(self.player)})
        self.assertTrue(world.fill_slot_data()["ability_patch"])
        world.pre_output() if hasattr(world, "pre_output") else None
        with tempfile.TemporaryDirectory() as tmp:
            world.generate_output(tmp)
            with zipfile.ZipFile(next(Path(tmp).glob("*.appxd"))) as zf:
                self.assertTrue(json.loads(zf.read("seed.json"))["ability_patch"])


class TestVanillaShops(PokemonXDTestBase):
    options = {"randomize_shops": False}

    def test_still_on(self) -> None:
        self.assertTrue(self.multiworld.worlds[self.player].fill_slot_data()["ability_patch"])


if __name__ == "__main__":
    unittest.main()
