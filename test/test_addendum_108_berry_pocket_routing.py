"""Regression coverage for ADDENDUM 108 (2026-09-10, player request, verbatim: "Go ahead and modify our code to
put all REMAINING berries in the BERRIES pocket. I don't care that you think they go in the items pocket - put
them in berries."). Pure arithmetic checks against `ram_client.resolve_item_pocket` -- no live Dolphin
connection needed (this module is deliberately loadable standalone, see its own module docstring).

WHY THIS TEST STUBS `dolphin_memory_engine`: same reason as test_chest_count_tracker_debounce.py/test_ram_
client_goal_detection.py -- `ram_client.py` does `import dolphin_memory_engine as dme` at module level, and
that real package isn't installable in every environment this project's tests run in. This test never touches
`dme` at all: `resolve_item_pocket` is pure arithmetic against constants, no I/O."""
from __future__ import annotations

import sys
import types
import unittest

if "dolphin_memory_engine" not in sys.modules:
    _stub = types.ModuleType("dolphin_memory_engine")
    _stub.hook = lambda: None
    _stub.un_hook = lambda: None
    _stub.is_hooked = lambda: False
    _stub.read_bytes = lambda address, length: b""
    _stub.write_bytes = lambda address, data: None
    sys.modules["dolphin_memory_engine"] = _stub

from .. import items, ram_client


class TestAllLiveBerriesRouteToBerriesPocket(unittest.TestCase):
    def _berries_pocket_base(self, block_base: int) -> int:
        return block_base + ram_client.POKEBALL_POCKET_OFFSET + ram_client.BERRIES_POCKET_RELATIVE_START * 4

    def test_every_berry_currently_in_the_pool_routes_to_the_berries_pocket(self) -> None:
        # Cheri(133) through Iapapa(147) -- the full currently-live berry roster (see items.py's _BERRY_NAMES).
        # Before ADDENDUM 108, only Aguav(146)/Iapapa(147) landed here; Cheri-Mago(133-145) fell through to the
        # Items pocket instead. This is the exact regression this addendum exists to fix.
        block_base = 0x9000_0000
        expected = self._berries_pocket_base(block_base), ram_client.BERRIES_SLOT_COUNT
        for name in items._BERRY_NAMES:
            game_item_id = items.ITEM_TABLE[name].game_item_id
            self.assertIsNotNone(game_item_id, f"{name} has no real game_item_id")
            self.assertEqual(
                ram_client.resolve_item_pocket(block_base, game_item_id),
                expected,
                f"{name} (id {game_item_id}) should route to the Berries pocket",
            )

    def test_low_end_and_high_end_of_the_real_berry_range_both_route_to_berries(self) -> None:
        # 133 and 175 are the full real Gen III berry index range's endpoints (Cheri and Enigma) -- both must
        # route to the Berries pocket now, even though most of that range (148-175) is pruned from this
        # project's own pool and never actually gets delivered.
        block_base = 0x9000_0000
        expected = self._berries_pocket_base(block_base), ram_client.BERRIES_SLOT_COUNT
        self.assertEqual(ram_client.resolve_item_pocket(block_base, 133), expected)
        self.assertEqual(ram_client.resolve_item_pocket(block_base, 175), expected)

    def test_ids_just_outside_the_berry_range_do_not_route_to_berries(self) -> None:
        block_base = 0x9000_0000
        berries_pocket = self._berries_pocket_base(block_base), ram_client.BERRIES_SLOT_COUNT
        # 132 is one below Cheri Berry (133) -- must NOT be swept into the Berries pocket by an off-by-one.
        self.assertNotEqual(ram_client.resolve_item_pocket(block_base, 132), berries_pocket)
        # 176 is one above Enigma Berry (175) -- must NOT be swept into the Berries pocket either.
        self.assertNotEqual(ram_client.resolve_item_pocket(block_base, 176), berries_pocket)

    def test_held_items_still_route_to_the_items_pocket_not_berries(self) -> None:
        # Held items (179-225) are adjacent to the berry range but must be unaffected by this addendum --
        # they still belong in the Items pocket, same as before.
        block_base = 0x9000_0000
        items_pocket = block_base + ram_client.ITEMS_POCKET_OFFSET, ram_client.ITEMS_POCKET_MAX_SLOTS
        for name in ("BrightPowder", "Stick"):
            game_item_id = items.ITEM_TABLE[name].game_item_id
            self.assertEqual(ram_client.resolve_item_pocket(block_base, game_item_id), items_pocket)

    def test_rabuta_berry_dummy_item_also_routes_to_berries(self) -> None:
        # Rabuta Berry (game_item_id 161, CHEST_DUMMY_GAME_ITEM_ID) is never a real AP pool item, but it's
        # still a real berry written into the Bag by the chest-fill mechanism -- confirms it falls inside the
        # widened 133-175 routing range too, consistent with every other berry.
        block_base = 0x9000_0000
        expected = self._berries_pocket_base(block_base), ram_client.BERRIES_SLOT_COUNT
        self.assertEqual(
            ram_client.resolve_item_pocket(block_base, items.CHEST_DUMMY_GAME_ITEM_ID), expected
        )


if __name__ == "__main__":
    unittest.main()
