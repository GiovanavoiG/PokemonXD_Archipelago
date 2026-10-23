"""All Pokemon Learn All TMs and Shadow Move TMs."""
from __future__ import annotations

import random
import struct
import unittest
from pathlib import Path

from . import PokemonXDTestBase
from ..game_data import tm_moves

DOL = Path("/mnt/user-data/uploads/PokemonXD-working/main_dol.bin")
COMMON_REL = Path("/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/a263_commonrel.bin")


def _dol_word(data: bytes, address: int) -> int:
    offs = struct.unpack(">18I", data[0:72])
    addrs = struct.unpack(">18I", data[72:144])
    sizes = struct.unpack(">18I", data[144:216])
    for o, b, z in zip(offs, addrs, sizes):
        if z and b <= address < b + z:
            return struct.unpack_from(">I", data, o + address - b)[0]
    raise KeyError(hex(address))


class TestThePlan(unittest.TestCase):
    def test_count_distinct_tms_and_moves(self) -> None:
        for count in range(0, 19):
            plan = tm_moves.plan_shadow_move_tms(random.Random(count), count)
            self.assertEqual(count, len(plan))
            self.assertEqual(count, len({tm for tm, _ in plan}))
            self.assertEqual(count, len({move for _, move in plan}))
            for tm, move in plan:
                self.assertTrue(1 <= tm <= 50)
                self.assertIn(move, tm_moves.SHADOW_MOVE_NAMES)

    def test_words_point_at_the_move_half_of_each_entry(self) -> None:
        words = tm_moves.shadow_move_tm_words([(1, 357), (50, 373)])
        self.assertEqual(((0x804053A4, 264, 357), (0x804053A0 + 49 * 8 + 4, 315, 373)), words)

    def test_a_bad_pair_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            tm_moves.shadow_move_tm_words([(51, 357)])
        with self.assertRaises(ValueError):
            tm_moves.shadow_move_tm_words([(5, 46)])

    def test_the_vanilla_table_matches_main_dol(self) -> None:
        if not DOL.exists():
            self.skipTest("no main.dol here")
        data = DOL.read_bytes()
        for tm, move in enumerate(tm_moves.VANILLA_TM_MOVES, start=1):
            address = tm_moves.TM_TABLE_ADDRESS + (tm - 1) * 8 + 4
            self.assertEqual(move, _dol_word(data, address), f"TM{tm:02d}")

    def test_the_compatibility_bytes_are_where_we_write(self) -> None:
        if not COMMON_REL.exists():
            self.skipTest("no common_rel dump here")
        data = COMMON_REL.read_bytes()
        mew = data[0x29DA8 + 151 * 0x124 + tm_moves.TM_COMPATIBILITY_OFFSET:][:58]
        magikarp = data[0x29DA8 + 129 * 0x124 + tm_moves.TM_COMPATIBILITY_OFFSET:][:58]
        self.assertEqual(b"\x01" * 58, mew)
        self.assertEqual(b"\x00" * 58, magikarp)


class TestOff(PokemonXDTestBase):
    def test_nothing_changes(self) -> None:
        world = self.multiworld.worlds[self.player]
        self.assertEqual([], world._shadow_move_tms)
        self.assertEqual([], world.fill_slot_data()["shadow_move_tm_list"])


class TestOn(PokemonXDTestBase):
    options = {"shadow_move_tms": 7, "all_pokemon_learn_all_tms": True}

    def test_seven_tms_change(self) -> None:
        world = self.multiworld.worlds[self.player]
        self.assertEqual(7, len(world._shadow_move_tms))
        listed = world.fill_slot_data()["shadow_move_tm_list"]
        self.assertEqual(7, len(listed))
        self.assertTrue(all(entry["move"].startswith("Shadow ") for entry in listed))


class TestTheRelEdit(unittest.TestCase):
    def test_sets_fifty_bytes_and_leaves_the_rest(self) -> None:
        from unittest import mock
        from ..tools import xd_rel_format as R

        size = R.POKEMON_STATS_ENTRY_SIZE
        data = bytearray(size * 4)
        data[1 * size + 0x34 + 3] = 1
        data[1 * size + 0x34 + 50] = 1          # an HM byte: untouched either way
        with mock.patch.object(R, "pokemon_stats_base", return_value=0), \
                mock.patch.object(R, "pokemon_stats_count", return_value=4):
            result = R.apply_all_tms_learnable(data, None, [1, 2, 9])
        self.assertEqual(2, result["species_written"])
        for species in (1, 2):
            self.assertEqual(b"\x01" * 50, bytes(data[species * size + 0x34:][:50]))
        self.assertEqual(0, data[2 * size + 0x34 + 50])
        self.assertEqual(b"\x00" * 50, bytes(data[3 * size + 0x34:][:50]))

    def test_refuses_a_different_layout(self) -> None:
        from unittest import mock
        from ..tools import xd_rel_format as R

        data = bytearray(R.POKEMON_STATS_ENTRY_SIZE * 2)
        data[R.POKEMON_STATS_ENTRY_SIZE + 0x34] = 7
        with mock.patch.object(R, "pokemon_stats_base", return_value=0), \
                mock.patch.object(R, "pokemon_stats_count", return_value=2):
            with self.assertRaises(ValueError):
                R.apply_all_tms_learnable(data, None, [1])
