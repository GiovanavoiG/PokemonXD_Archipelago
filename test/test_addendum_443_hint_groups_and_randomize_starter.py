"""ADDENDUM 443 (2026-10-09) -- "!hint ID Card", and Randomize Starter.

Player: "Can you make it so if someone types "!hint ID Card" it will hint Data Rom & ID Card? Also, add a setting to
randomize our starter pokemon. Make it have 3 options, off, random_no_legendary, and true_random." Then: "And ensure
that the randomized starter has at least one attacking move."
"""
from __future__ import annotations

import json
import pathlib
import random
import struct
import tempfile
import unittest
import zipfile

from BaseClasses import LocationProgressType

from . import PokemonXDTestBase
from .. import PokemonXDWorld, items, locations, species
from ..game_data import starter as S
from ..game_data.real_moveset_data import load_level_up_moves
from ..game_data.real_trainer_data import LEGENDARY_NATIONAL_DEX
from ..tools.xd_species_index import internal_index_for_national_dex

REAL_DOL = pathlib.Path("/mnt/user-data/uploads/PokemonXD-working/main_dol.bin")


class TestTheHintGroups(unittest.TestCase):
    def test_both_halves_name_the_combined_item(self):
        for part in ("ID Card", "Data ROM"):
            self.assertEqual({items.COMBINED_KEY_ITEM_NAME}, set(PokemonXDWorld.item_name_groups[part]))
            self.assertNotIn(part, PokemonXDWorld.item_name_to_id, "a group may not also be an item name")
        self.assertIn(items.COMBINED_KEY_ITEM_NAME, PokemonXDWorld.item_name_to_id)

    def test_the_server_can_resolve_it(self):
        """The server matches `!hint` text against item AND group names; an exact name is a perfect match, and a
        group is checked before an item, so "ID Card" hints every item in the group."""
        self.assertIn("ID Card", PokemonXDWorld.all_item_and_group_names)
        self.assertIn("Data ROM", PokemonXDWorld.all_item_and_group_names)

    def test_the_old_ids_stay_reserved_and_resolvable_by_the_client(self):
        full = items.get_item_name_to_id(1000, include_retired=True)
        self.assertIn("ID Card", full)
        self.assertNotIn(full["ID Card"], set(items.get_item_name_to_id(1000).values()))
        source = (pathlib.Path(items.__file__).parent / "Client.py").read_text(encoding="utf-8")
        self.assertIn("get_item_name_to_id(BASE_ID, include_retired=True)", source)


class TestTheStarterPatch(unittest.TestCase):
    def test_the_words(self):
        words = S.dol_patch_words(internal_index_for_national_dex(25), [84, 45, 0, 0])
        self.assertEqual((0x801CECF0, 0x38600085, 0x38600019), words[0])
        self.assertEqual((0x801CED00, 0x38C00021, 0x38C00054), words[1])
        self.assertEqual((0x801CED04, 0x38A00027, 0x38A0002D), words[2])
        self.assertEqual((0x801CED08, 0x3880002C, 0x38800000), words[3])
        self.assertEqual((0x801CED0C, 0x3800001C, 0x38000000), words[4])

    @unittest.skipUnless(REAL_DOL.is_file(), "needs the player's main.dol")
    def test_against_the_real_dol(self):
        data = REAL_DOL.read_bytes()
        offs = struct.unpack(">18I", data[0:72]); addrs = struct.unpack(">18I", data[72:144])
        sizes = struct.unpack(">18I", data[144:216])

        def word(address):
            for o, b, z in zip(offs, addrs, sizes):
                if z and b <= address < b + z:
                    return struct.unpack_from(">I", data, o + address - b)[0]
        for address, vanilla, _new in S.dol_patch_words(1, [33, 0, 0, 0]):
            self.assertEqual(vanilla, word(address), hex(address))
        # The record the immediates fill goes to Hero::pokemonGet, and the level stays 10.
        self.assertEqual(0x3900000A, word(0x801CECF8))
        self.assertEqual(0x4BF83D71, word(0x801CED70))


class TestTheChoice(unittest.TestCase):
    def test_pools(self):
        self.assertEqual(386, len(S.candidate_dex(S.TRUE_RANDOM)))
        no_leg = S.candidate_dex(S.NO_LEGENDARY)
        self.assertFalse(set(no_leg) & LEGENDARY_NATIONAL_DEX)
        self.assertEqual(386 - len(LEGENDARY_NATIONAL_DEX), len(no_leg))
        self.assertIsNone(S.plan(random.Random(1), S.OFF))

    def test_every_species_gets_an_attacking_move(self):
        level_up = load_level_up_moves()
        for dex in range(1, 387):
            internal = internal_index_for_national_dex(dex)
            moves = S.starter_moves(random.Random(dex), internal, level_up)
            self.assertTrue(1 <= len(moves) <= 4, dex)
            self.assertTrue(any(S.is_damaging(m) for m in moves), f"dex {dex}: {moves}")
            self.assertEqual(len(moves), len(set(moves)), dex)

    def test_the_eevee_line(self):
        self.assertEqual({133, 134, 135, 136, 196, 197}, set(S.evolution_line(133)))
        self.assertEqual({4, 5, 6}, set(S.evolution_line(4)))


def _seed(world) -> dict:
    world.pre_output()
    with tempfile.TemporaryDirectory() as tmp:
        world.generate_output(tmp)
        with zipfile.ZipFile(next(pathlib.Path(tmp).glob("*.appxd"))) as zf:
            return json.loads(zf.read("seed.json"))


class TestRandomized(PokemonXDTestBase):
    options = {"randomize_starter": "random_no_legendary"}

    def test_the_world(self):
        world = self.multiworld.worlds[self.player]
        dex = world.starter_dex
        self.assertNotIn(dex, LEGENDARY_NATIONAL_DEX)
        created = {loc.name: loc for loc in self.multiworld.get_locations(self.player)}
        starter_loc = created.get(species.location_name_for_species(dex))
        if dex != 133:
            self.assertIsNotNone(starter_loc)
            self.assertEqual(LocationProgressType.EXCLUDED, starter_loc.progress_type)
            self.assertTrue(starter_loc.can_reach(self.multiworld.get_all_state(False)))
            self.assertNotIn(locations.EEVEELUTION_LOCATION_NAME, created)
        seed = _seed(world)
        self.assertEqual(dex, seed["starter"]["dex"])
        self.assertTrue(any(S.is_damaging(m) for m in seed["starter"]["moves"]))
        self.assertEqual(sorted(S.evolution_line(dex)), world.fill_slot_data()["starter_line_dex"])


class TestTrueRandom(PokemonXDTestBase):
    options = {"randomize_starter": "true_random"}

    def test_generates(self):
        self.assertTrue(1 <= self.multiworld.worlds[self.player].starter_dex <= 386)


class TestOff(PokemonXDTestBase):
    def test_eevee_as_before(self):
        world = self.multiworld.worlds[self.player]
        self.assertEqual(133, world.starter_dex)
        created = {loc.name: loc for loc in self.multiworld.get_locations(self.player)}
        self.assertNotEqual(LocationProgressType.EXCLUDED, created[locations.GUARANTEED_SPECIES_LOCATION].progress_type)
        self.assertIn(locations.EEVEELUTION_LOCATION_NAME, created)
        self.assertIsNone(_seed(world)["starter"])


if __name__ == "__main__":
    unittest.main()
