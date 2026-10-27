"""Mt. Battle's teams are randomized whenever its trainers are checks (Exclude Mt. Battle Trainers off), with or
without the level options, and left alone when they are excluded."""
from __future__ import annotations

import json
import pathlib
import random
import struct
import tempfile
import unittest
import zipfile

from Fill import distribute_items_restrictive

from . import PokemonXDTestBase
from ..game_data import load_json_data_file
from ..game_data.real_moveset_data import load_level_up_moves
from ..game_data.real_trainer_data import real_species_pool
from ..randomizer import mt_battle_shuffle as mbs
from ..tools import iso_patcher as ip
from ..tools import xd_deck_format as deck_format


def _seed(world) -> dict:
    distribute_items_restrictive(world.multiworld)
    with tempfile.TemporaryDirectory() as tmp:
        world.generate_output(tmp)
        path = next(pathlib.Path(tmp).glob("*.appxd"))
        with zipfile.ZipFile(path) as zf:
            return json.loads(zf.read("seed.json"))


def _census():
    return load_json_data_file("mtbattle_trainer_census.json") or []


class TestTheShuffle(unittest.TestCase):
    def setUp(self):
        self.pool = real_species_pool()
        self.moves = load_level_up_moves()
        self.trainers = _census()
        if not (self.pool and self.moves and self.trainers):
            self.skipTest("needs the real census data")

    def test_every_member_rerolled_distinct_per_team(self):
        species = mbs.shuffle_species(self.trainers, {}, self.pool, random.Random(1))
        members = [s for t in self.trainers for s in t["team"] if s.get("kind") == "DPKM"]
        self.assertEqual(len(members), len(species))
        changed = sum(species[s["dpkm_index"]] != s["species"] for s in members)
        self.assertGreater(changed, len(members) * 0.9)
        for t in self.trainers:
            team = [species[s["dpkm_index"]] for s in t["team"] if s.get("kind") == "DPKM"]
            self.assertEqual(len(team), len(set(team)), t["index"])

    def test_legendaries_for_legendaries(self):
        species = mbs.shuffle_species(self.trainers, {}, self.pool, random.Random(2), legendary_safe=True)
        for t in self.trainers:
            for s in t["team"]:
                if s.get("kind") == "DPKM" and s["species"] in self.pool:
                    self.assertEqual(self.pool[s["species"]].is_legendary,
                                     self.pool[species[s["dpkm_index"]]].is_legendary)

    def test_evolved_for_the_final_level(self):
        last = self.trainers[-1]
        levels = {s["dpkm_index"]: 100 for s in last["team"] if s.get("kind") == "DPKM"}
        species = mbs.shuffle_species([last], levels, self.pool, random.Random(3))
        for dpkm, sid in species.items():
            reachable = [t for t, at in self.pool[sid].evolution_options() if at is None or at <= 100]
            self.assertFalse([t for t in reachable if t in self.pool], f"{sid} could still evolve at 100")

    def test_movesets_follow_the_new_species(self):
        species = mbs.shuffle_species(self.trainers, {}, self.pool, random.Random(4))
        moves = mbs.movesets(species, {}, self.trainers, self.moves, random.Random(4))
        self.assertGreater(len(moves), len(species) * 0.95)
        for dpkm, chosen in moves.items():
            self.assertEqual(4, len(chosen))
            self.assertTrue(any(chosen))


class TestOffWithNoLevelOptions(PokemonXDTestBase):
    options = {"exclude_mt_battle_trainers": False, "enhanced_difficulty": "off",
               "enhanced_difficulty_level_scaling": False, "path_level_scaling": False}

    def test_a_species_and_moves_plan(self):
        plan = _seed(self.world)["mt_battle_enhanced_difficulty_plan"]
        self.assertTrue(plan)
        self.assertEqual(({}, [], []), (plan["level_assignment"], plan["new_dpkm_entries"], plan["team_slot_plan"]))
        self.assertGreater(len(plan["species_assignment"]), 300)
        self.assertGreater(len(plan["moves_assignment"]), 300)


class TestOffWithLevelOptions(PokemonXDTestBase):
    options = {"exclude_mt_battle_trainers": False, "enhanced_difficulty": "fill_enemy_team",
               "enhanced_difficulty_level_scaling": True, "path_level_scaling": True}

    def test_padding_avoids_the_new_teams(self):
        seed = _seed(self.world)
        plan = seed["mt_battle_enhanced_difficulty_plan"]
        species = {int(k): v for k, v in plan["species_assignment"].items()}
        self.assertGreater(len(species), 300)
        self.assertGreater(len(plan["moves_assignment"]), 300)
        teams = {int(t["index"]): [species.get(s["dpkm_index"], s["species"]) for s in t["team"]
                                   if s.get("kind") == "DPKM"] for t in _census()}
        for entry, slot in zip(plan["new_dpkm_entries"], plan["team_slot_plan"]):
            teams.setdefault(int(slot["trainer_index"]), []).append(entry["species"])
        repeats = [i for i, team in teams.items() if len(team) != len(set(team))]
        self.assertLessEqual(len(repeats), 2, repeats)


class TestOnIsLeftAlone(PokemonXDTestBase):
    options = {"exclude_mt_battle_trainers": True, "enhanced_difficulty": "off",
               "enhanced_difficulty_level_scaling": False, "path_level_scaling": False}

    def test_no_plan(self):
        self.assertIsNone(_seed(self.world)["mt_battle_enhanced_difficulty_plan"])


DECK = pathlib.Path("/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/deck_archive_full1.bin")


@unittest.skipUnless(DECK.is_file(), "needs deck_archive.fsys")
class TestThePatchWritesThem(unittest.TestCase):
    def test_species_and_moves_land_in_the_hundred_deck(self):
        fsys = DECK.read_bytes()
        entry = ip.parse_fsys(fsys)["DeckData_Hundred.bin"]
        raw = fsys[entry["data_off"]:entry["data_off"] + 0x10 + entry["comp_size"]]
        stock = deck_format.lzss_decode(raw)
        deck = deck_format.DeckFile(stock)
        plan = {"level_assignment": {}, "new_dpkm_entries": [], "team_slot_plan": [],
                "species_assignment": {1: 0x100, 2: 0x101}, "moves_assignment": {1: [33, 45, 0, 0], 2: [52]}}
        out = ip.apply_enhanced_difficulty_story_edit(stock, deck, plan)
        self.assertEqual(len(stock), len(out))
        for dpkm, species, moves in ((1, 0x100, (33, 45, 0, 0)), (2, 0x101, (52, 0, 0, 0))):
            base = deck.dpkm_data + dpkm * 0x20
            self.assertEqual(species, struct.unpack_from(">H", out, base)[0])
            self.assertEqual(moves, struct.unpack_from(">HHHH", out, base + 0x14))
            self.assertEqual(stock[base + 2:base + 0x14], out[base + 2:base + 0x14], "level, IVs, EVs untouched")


if __name__ == "__main__":
    unittest.main()
