"""The Escape Rope: a key item that opens the world map."""
from __future__ import annotations

import hashlib
import struct
import unittest
from pathlib import Path
from unittest import mock

from .. import ram_client
from ..game_data import ability_patch, candy_box, escape_rope as ER

DOL = Path("/mnt/user-data/uploads/PokemonXD-working/main_dol.bin")
COMMON_REL = Path("/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/a263_commonrel.bin")
CLIENT = (Path(__file__).resolve().parents[1] / "Client.py").read_text(encoding="utf-8")


def _dol():
    data = DOL.read_bytes()
    offs = struct.unpack(">18I", data[0:72])
    addrs = struct.unpack(">18I", data[72:144])
    sizes = struct.unpack(">18I", data[144:216])

    def at(address: int) -> int:
        for o, b, z in zip(offs, addrs, sizes):
            if z and b <= address < b + z:
                return o + address - b
        raise KeyError(hex(address))
    return data, at


class TestTheCode(unittest.TestCase):
    def test_it_chains_to_the_ability_swap(self) -> None:
        hook = candy_box._b(ER.CANT_USE_HANDLER, ability_patch.DISPATCH_ADDRESS)
        code = ER.cave_code(hook)
        self.assertEqual(ER.CODE_SIZE, len(code) * 4)
        self.assertEqual(ability_patch.DISPATCH_ADDRESS, ER.branch_target(ER.DISPATCH + 0x18, code[6]))

    def test_it_chains_to_the_vanilla_handler(self) -> None:
        code = ER.cave_code(ER.CANT_USE_HANDLER_FIRST_WORD)
        self.assertEqual(ER.CANT_USE_HANDLER_FIRST_WORD, code[6])
        self.assertEqual(ER.CANT_USE_HANDLER + 4, ER.branch_target(ER.DISPATCH + 0x1C, code[7]))

    def test_it_never_chains_to_itself(self) -> None:
        with self.assertRaises(ValueError):
            ER.cave_code(candy_box._b(ER.CANT_USE_HANDLER, ER.DISPATCH))
        with self.assertRaises(ValueError):
            ER.cave_code(0x12345678)

    def test_the_hooks(self) -> None:
        words = {a: (old, new) for a, old, new in ER.dol_patch_words(ER.CANT_USE_HANDLER_FIRST_WORD)}
        self.assertEqual(ER.COMPARE, ER.branch_target(ER.KEY_POCKET_COMPARE, words[ER.KEY_POCKET_COMPARE][1]))
        self.assertEqual(ER.MENU_END, ER.branch_target(ER.FIELD_MENU_END, words[ER.FIELD_MENU_END][1]))
        self.assertEqual(ER.DISPATCH, ER.branch_target(ER.CANT_USE_HANDLER, words[ER.CANT_USE_HANDLER][1]))

    def test_the_menu_end_calls_floor_link_with_the_map(self) -> None:
        code = ER.cave_code(ER.CANT_USE_HANDLER_FIRST_WORD)
        m = (ER.MENU_END - ER.DISPATCH) // 4
        self.assertEqual(ER._li(3, 910), code[m + 6])
        self.assertEqual(ER.FLOOR_LINK, ER.branch_target(ER.MENU_END + 0x20, code[m + 8] & ~1))
        self.assertEqual(1, code[m + 8] & 1)                     # bl
        self.assertEqual(ER.FIELD_MENU_END + 4, ER.branch_target(ER.MENU_END + 0x28, code[m + 10]))

    def test_stays_in_its_stretch_of_the_cave(self) -> None:
        self.assertGreaterEqual(ER.DISPATCH, ability_patch.DISPATCH_ADDRESS + ability_patch.CODE_SIZE)
        self.assertLessEqual(ER.DISPATCH + ER.CODE_SIZE, candy_box.CAVE_ADDRESS + 0x700)

    def test_vanilla_words_match_main_dol(self) -> None:
        if not DOL.exists():
            self.skipTest("no main.dol here")
        data, at = _dol()
        self.assertEqual(ER.CODE_VANILLA_SHA1,
                         hashlib.sha1(data[at(ER.DISPATCH):at(ER.DISPATCH) + ER.CODE_SIZE]).hexdigest())
        for address, word in ((ER.KEY_POCKET_COMPARE, ER.KEY_POCKET_COMPARE_WORD),
                              (ER.FIELD_MENU_END, ER.FIELD_MENU_END_WORD),
                              (ER.CANT_USE_HANDLER, ER.CANT_USE_HANDLER_FIRST_WORD)):
            self.assertEqual(word, struct.unpack_from(">I", data, at(address))[0], hex(address))

    def test_the_item_row(self) -> None:
        self.assertEqual({0: bytes((5, 1, 0, 0))}, ER.row_edits())
        if not COMMON_REL.exists():
            self.skipTest("no common_rel dump here")
        data = COMMON_REL.read_bytes()
        row = data[0x1FEE4 + 85 * 0x28:][:0x28]
        self.assertEqual(ER.VANILLA_ROW_HEAD, row[:4])
        self.assertEqual(ER.ESCAPE_ROPE_NAME_ID, struct.unpack_from(">I", row, 0x10)[0])


class TestTheKeeper(unittest.TestCase):
    def test_only_with_the_code_in(self) -> None:
        keeper = ram_client.EscapeRopeKeeper()
        with mock.patch.object(ram_client, "escape_rope_installed", return_value=False), \
                mock.patch.object(ram_client, "give_item") as give:
            self.assertFalse(keeper.poll(0x80800000))
            give.assert_not_called()

    def test_puts_one_back(self) -> None:
        keeper = ram_client.EscapeRopeKeeper()
        with mock.patch.object(ram_client, "escape_rope_installed", return_value=True), \
                mock.patch.object(ram_client, "find_item_quantity", return_value=0), \
                mock.patch.object(ram_client, "give_item", return_value=True) as give:
            self.assertTrue(keeper.poll(0x80800000))
            give.assert_called_once_with(0x80800000 + ram_client.KEY_ITEMS_OFFSET, 85, 1,
                                         ram_client.KEY_ITEMS_MAX_SLOTS)

    def test_leaves_one_alone(self) -> None:
        keeper = ram_client.EscapeRopeKeeper()
        with mock.patch.object(ram_client, "escape_rope_installed", return_value=True), \
                mock.patch.object(ram_client, "find_item_quantity", return_value=1), \
                mock.patch.object(ram_client, "give_item") as give:
            self.assertFalse(keeper.poll(0x80800000))
            give.assert_not_called()

    def test_installed_reads_the_branch(self) -> None:
        word = candy_box._b(ER.CANT_USE_HANDLER, ER.DISPATCH)
        with mock.patch.object(ram_client, "read_bytes", return_value=struct.pack(">I", word)):
            self.assertTrue(ram_client.escape_rope_installed())
        with mock.patch.object(ram_client, "read_bytes", return_value=struct.pack(">I", 0x9421FFF0)):
            self.assertFalse(ram_client.escape_rope_installed())

    def test_the_client_keeps_it_behind_the_gate(self) -> None:
        gated = CLIENT.split("if block_is_stable:", 1)[1].split("elif not ctx._block_churn_logged:", 1)[0]
        self.assertIn("ctx.escape_rope_keeper.poll(ctx.block_base)", gated)
