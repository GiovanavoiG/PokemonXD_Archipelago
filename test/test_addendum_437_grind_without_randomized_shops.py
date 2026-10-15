"""ADDENDUM 437 (2026-10-08) -- Reduce Citadark Grind without Randomize Shops.

The reduce-grind check works even when Randomize Shops is off.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
import zipfile

from . import PokemonXDTestBase
from .. import ram_client
from ..game_data import candy_box as CB

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATCHER = (ROOT / "tools" / "iso_patcher.py").read_text(encoding="utf-8")
CLIENT = (ROOT / "Client.py").read_text(encoding="utf-8")


def _seed(world) -> dict:
    world.pre_output()
    with tempfile.TemporaryDirectory() as tmp:
        world.generate_output(tmp)
        with zipfile.ZipFile(next(pathlib.Path(tmp).glob("*.appxd"))) as zf:
            return json.loads(zf.read("seed.json"))


class TestTheSeedWithVanillaShops(PokemonXDTestBase):
    options = {"randomize_shops": False, "reduce_citadark_grind": True}

    def test_the_flag_travels_and_no_shop_berries_do(self):
        seed = _seed(self.multiworld.worlds[self.player])
        self.assertTrue(seed["reduce_citadark_grind"])
        self.assertFalse(seed.get("shop_dummy_item_ids"))
        self.assertEqual(1, self.multiworld.worlds[self.player].fill_slot_data()["reduce_citadark_grind"])

    def test_no_shop_checks_exist(self):
        self.assertFalse([l for l in self.multiworld.get_locations(self.player) if "Shop AP Item" in l.name])


class TestThePatcher(unittest.TestCase):
    def test_the_flag_no_longer_needs_shop_berries(self):
        self.assertIn('reduce_citadark_grind = bool(seed.get("reduce_citadark_grind"))\n', PATCHER)
        self.assertNotIn('bool(seed.get("reduce_citadark_grind")) and bool(shop_dummy_item_ids)', PATCHER)

    def test_the_pocket_menu_pass_runs_for_the_shelf_alone(self):
        # ADDENDUM 453: the Ability Patch's line needs the pass on its own too.
        self.assertIn("if shop_dummy_item_ids or reduce_citadark_grind or ability_patch_row_ready:", PATCHER)
        start = PATCHER.index("if shop_dummy_item_ids or reduce_citadark_grind or ability_patch_row_ready:")
        block = PATCHER[start:PATCHER.index("# Write-set confinement plus a post-patch link check", start)]
        # The berry pass and Agate's real stock stay behind Randomize Shops; the grind shelf does not.
        self.assertIn("            if shop_dummy_item_ids:\n                shop_slots_patched = "
                      "rel_format.apply_mart_randomization(", block)
        self.assertIn("if shop_dummy_item_ids and seed.get(\"agate_village_pit_stop\"):", block)
        self.assertIn("if reduce_citadark_grind:\n                grind_written = apply_grind_shelf(", block)


class TestTheClient(unittest.TestCase):
    def test_slot_data_no_longer_needs_shops(self):
        self.assertIn('self.reduce_citadark_grind = bool(slot_data.get("reduce_citadark_grind"))', CLIENT)
        self.assertNotIn('slot_data.get("reduce_citadark_grind") and slot_data.get("randomize_shops")', CLIENT)

    def test_the_candy_box_description_is_written_with_vanilla_shops(self):
        start = CLIENT.index("async def check_shops(")
        body = CLIENT[start:CLIENT.index("newly_crossed = ctx.shop_tracker.poll", start)]
        self.assertIn("if ctx.reduce_citadark_grind or ctx.ability_patch:", body)   # ADDENDUM 453/454
        self.assertIn("ctx.item_description_writer.poll(room_id, {}, set(), berry_ids=[])", body)

    def test_with_no_berry_lines_only_the_candy_box_is_described(self):
        writer = ram_client.ItemDescriptionWriter()
        writer.fixed_lines_by_room = {156: {CB.CANDY_BOX_ITEM_ID: list(CB.CANDY_BOX_DESCRIPTION_LINES)}}
        desired = writer.desired_lines(156, [], {}, set())
        self.assertEqual([CB.CANDY_BOX_ITEM_ID], list(desired))
        self.assertEqual({}, writer.desired_lines(121, [], {}, set()))


# --- "I had to hit enter to progress the patch after the trade evolutions line. Why?" ------------------------------

class TestThePatchConsoleCannotBePausedByAClick(unittest.TestCase):
    def test_quick_edit_is_cleared_and_extended_flags_set(self):
        from .. import launcher_patch as lp

        default = 0x01F7   # a Windows console's usual input mode: QuickEdit and extended flags both on
        self.assertEqual(0, lp.quick_edit_off(default) & lp.ENABLE_QUICK_EDIT_MODE)
        self.assertTrue(lp.quick_edit_off(default) & lp.ENABLE_EXTENDED_FLAGS)
        self.assertEqual(default & ~0x00C0, lp.quick_edit_off(default) & ~0x00C0)   # nothing else moves

    def test_it_runs_on_the_console_the_patch_allocates(self):
        source = (ROOT / "launcher_patch.py").read_text(encoding="utf-8")
        start = source.index("def _ensure_visible_console")
        body = source[start:source.index("\ndef ", start + 1)]
        self.assertIn("_disable_quick_edit()", body)

    def test_the_wait_is_announced_right_before_it(self):
        start = PATCHER.index("Re-encoding common_rel now")
        self.assertLess(start, PATCHER.index("new_entry_raw, real_comp_size, _grew = deck_format.patch_entry_decompressed("
                                             "entry_raw, bytes(rel_bytes))", start))


if __name__ == "__main__":
    unittest.main()
