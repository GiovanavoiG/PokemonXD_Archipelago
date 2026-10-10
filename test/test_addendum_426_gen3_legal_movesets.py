"""ADDENDUM 426 (2026-10-06) -- every trainer move is one that species can have in Gen III.

Player: "i saw a few pokemon use Focus Punch despite not being able to learn it. Can we ensure that the move pool
we're using is 1. From Gen 3 and 2. The TM move we teach them is one they actually can learn? Also, allow for them
to pull from egg/tutor moves as well." ... "Make sure that's all for their gen 3 moveset."
"""
from __future__ import annotations

import json
import os
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from . import PokemonXDTestBase
from ..game_data import load_json_data_file
from ..randomizer.team_shuffle import species_move_compat

RAM_DUMP = "/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/battle1.bin"


def _legal(species: int, level: int, learnset: "list[tuple[int, int]]") -> "set[int]":
    compat = species_move_compat().get(species, {})
    moves = {move for lvl, move in learnset if lvl <= level}
    # Legality, not the level-30 design rule: a TM is learnable at any level.
    return moves | set(compat.get("tutor", [])) | set(compat.get("egg", [])) | set(compat.get("tm", []))


class TestTheData(unittest.TestCase):
    def test_shape(self) -> None:
        data = load_json_data_file("species_move_compat.json")
        self.assertEqual(58, len(data["tm_moves"]))                      # 50 TMs + 8 HMs
        self.assertEqual(264, data["tm_moves"][0])                       # TM01 Focus Punch
        self.assertEqual([34, 38, 69, 102, 138, 86, 164, 196, 207, 143, 120, 171], data["tutor_moves"])
        every = {m for entry in data["species"].values() for kind in entry.values() for m in kind}
        self.assertLessEqual(max(every), 354)                            # Gen III moves, no Shadow moves

    def test_level_up_moves_are_gen3_ids(self) -> None:
        learnsets = load_json_data_file("species_level_up_moves.json")
        self.assertLessEqual(max(m for v in learnsets.values() for _l, m in v), 354)

    def test_examples(self) -> None:
        compat = species_move_compat()
        self.assertNotIn(264, compat[129]["tm"] if 129 in compat else [])   # Magikarp: no Focus Punch
        self.assertIn(264, compat[143]["tm"])                                # Snorlax: yes
        self.assertIn(90, compat[143]["egg"])                                # Snorlax egg move Fissure
        self.assertEqual(compat[172]["egg"], compat[26]["egg"])              # Raichu inherits Pichu's


@unittest.skipUnless(os.path.exists(RAM_DUMP), "needs a RAM dump with XD's species and move tables")
class TestTheDataMatchesTheGame(unittest.TestCase):
    def test_against_the_live_tables(self) -> None:
        data = Path(RAM_DUMP).read_bytes()
        word = lambda a: struct.unpack_from(">I", data, a - 0x80000000)[0]
        count, base = word(word(0x804EFE20 - 22508)), word(0x804EFE20 - 22504)
        shipped = load_json_data_file("species_move_compat.json")
        tms = [word(0x804053A0 + i * 8 + 4) & 0xFFFF for i in range(58)]
        self.assertEqual(tms, shipped["tm_moves"])
        learnsets = load_json_data_file("species_level_up_moves.json")
        for species in range(count):
            record = data[base - 0x80000000 + species * 0x124:][:0x124]
            entry = shipped["species"].get(str(species), {"tm": [], "tutor": [], "egg": []})
            self.assertEqual(sorted(tms[i] for i in range(58) if record[0x34 + i]), entry["tm"], species)
            self.assertEqual(sorted(shipped["tutor_moves"][i] for i in range(12) if record[0x6E + i]),
                             entry["tutor"], species)
            own_eggs = {m for m in struct.unpack_from(">8H", record, 0x7E) if m}
            self.assertTrue(own_eggs <= set(entry["egg"]), species)
            level_up = [(record[0xC4 + 4 * k], struct.unpack_from(">H", record, 0xC4 + 4 * k + 2)[0])
                        for k in range(20)]
            self.assertEqual([[lvl, mv] for lvl, mv in level_up if mv], learnsets[str(species)], species)


class TestASeed(PokemonXDTestBase):
    options = {"randomize_shadow_species": True, "enhanced_difficulty": 3, "enhanced_difficulty_level_scaling": True,
               "shadow_pokemon_expansion": 20}

    def test_every_generated_move_is_legal(self) -> None:
        world = self.multiworld.worlds[self.player]
        world.pre_output()
        with tempfile.TemporaryDirectory() as tmp_dir:
            world.generate_output(tmp_dir)
            with zipfile.ZipFile(next(Path(tmp_dir).glob("*.appxd"))) as zf:
                seed = json.loads(zf.read("seed.json"))
        learnsets = {int(k): v for k, v in load_json_data_file("species_level_up_moves.json").items()}
        species = {int(k): v for k, v in seed["trainer_species_by_dpkm_index"].items()}
        levels = {int(k): v for k, v in seed["enhanced_difficulty_plan"]["level_assignment"].items()}
        raw_levels = {s["dpkm_index"]: s["level"] for t in load_json_data_file("deckdata_story_trainers.json")
                      for s in t["team"] if s.get("kind") == "DPKM"}
        # ADDENDUM 427: the Shadows' records ride the same channel.
        shadows = {int(e["dpkm_index"]): e["new_species_index"] for e in world._shadow_species_assignment["entries"]}
        shadow_levels = {mon.index: mon.level for t in world._shadow_species_assignment["pool"].trainers
                         for mon in t.team}
        checked = shadow_checked = 0
        for dpkm, moves in seed["trainer_moves_by_dpkm_index"].items():
            dpkm = int(dpkm)
            if dpkm in shadows:
                sp, level = shadows[dpkm], levels.get(dpkm, shadow_levels[dpkm])
                shadow_checked += 1
            else:
                sp, level = species[dpkm], levels.get(dpkm, raw_levels[dpkm])
            legal = _legal(sp, level, learnsets[sp])
            for move in moves:
                if move:
                    self.assertIn(move, legal, (dpkm, sp, level, move))
                    checked += 1
        for entry in seed["enhanced_difficulty_plan"]["new_dpkm_entries"]:
            legal = _legal(entry["species"], entry["level"], learnsets[entry["species"]])
            for move in entry["moves"]:
                self.assertIn(move, legal, entry)
        for plan in seed["new_shadow_pokemon_plans"] or ():
            for mon in plan["new_pokemon"]:
                legal = _legal(mon["species"], mon["level"], learnsets[mon["species"]])
                for move in mon["moves"]:
                    self.assertIn(move, legal, mon)
        self.assertGreater(checked, 2000)
        self.assertGreaterEqual(shadow_checked, 80)          # every vanilla Shadow slot got legal moves



class TestAPathScaledSeed(TestASeed):
    """Path scaling re-levels padding and generated Shadows after their moves were first picked."""
    options = {**TestASeed.options, "path_level_scaling": True}


if __name__ == "__main__":
    unittest.main()
