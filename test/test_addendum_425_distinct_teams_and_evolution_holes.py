"""ADDENDUM 425 (2026-10-06) -- no species twice on one team, and the evolution holes.

The team "shuffle" looked like it swapped IDs: a trainer with two of the same Pokemon in vanilla shuffled to two of
the same Pokemon. It no longer does. Some Pokemon on trainer teams were also NOT evolved despite being at a level
to evolve; those holes are closed.
"""
from __future__ import annotations

import collections
import json
import os
import random
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from . import PokemonXDTestBase
from ..game_data import load_json_data_file
from ..game_data.evolution_data import NATIONAL_DEX_LEVEL_EVOLUTIONS, TRAINER_EVOLUTIONS
from ..game_data.real_trainer_data import load_real_trainer_pools, real_species_pool
from ..randomizer.enhanced_difficulty import evolve_for_final_levels, settle_padding_members
from ..randomizer.team_shuffle import (TeamShuffleOptions, pick_distinct_species, resolve_natural_evolution,
                                       shuffle_teams)
from ..tools import iso_patcher
from ..tools import xd_deck_format as deck_format
from ..tools.xd_species_index import NATIONAL_DEX_TO_INTERNAL_INDEX as INTERNAL

RAM_DUMP = "/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/battle1.bin"

#: Every species XD's own data evolves by something other than a plain level (stone, trade, held item,
#: friendship, beauty, a stat or personality branch) -- read off the game's species table, method != 4.
GAME_NON_LEVEL_EVOLVERS = {25, 30, 33, 35, 37, 39, 42, 44, 58, 61, 64, 67, 70, 75, 79, 90, 93, 95, 102, 113, 117,
                           120, 123, 133, 137, 172, 173, 174, 175, 191, 236, 265, 271, 274, 290, 298, 300, 349, 366}


def _internal(dex: int) -> int:
    return INTERNAL[dex]


class TestTheEvolutionTable(unittest.TestCase):
    def test_every_non_level_evolver_has_a_trainer_threshold(self) -> None:
        covered = set(TRAINER_EVOLUTIONS) | {dex for dex in NATIONAL_DEX_LEVEL_EVOLUTIONS}
        self.assertEqual(set(), GAME_NON_LEVEL_EVOLVERS - covered)

    def test_examples(self) -> None:
        pool = real_species_pool()
        self.assertEqual(_internal(64), resolve_natural_evolution(_internal(64), 36, pool))   # Kadabra stays
        self.assertEqual(_internal(65), resolve_natural_evolution(_internal(63), 37, pool))   # Abra -> Alakazam
        self.assertEqual(_internal(169), resolve_natural_evolution(_internal(41), 40, pool))  # Zubat -> Crobat
        self.assertEqual(_internal(26), resolve_natural_evolution(_internal(172), 30, pool))  # Pichu -> Raichu
        self.assertEqual(_internal(80), resolve_natural_evolution(_internal(79), 37, pool))   # first route, no rng

    def test_branches_take_every_route(self) -> None:
        pool = real_species_pool()
        rng = random.Random(425)
        seen = {resolve_natural_evolution(_internal(133), 30, pool, rng) for _ in range(200)}
        self.assertEqual({_internal(d) for d in (134, 135, 136, 196, 197)}, seen)
        seen = {resolve_natural_evolution(_internal(43), 40, pool, rng) for _ in range(100)}   # Oddish
        self.assertEqual({_internal(45), _internal(182)}, seen)


@unittest.skipUnless(os.path.exists(RAM_DUMP), "needs a RAM dump with XD's species table")
class TestTheLevelTableMatchesTheGame(unittest.TestCase):
    def test_every_single_level_evolution(self) -> None:
        from ..tools.xd_species_index import INTERNAL_INDEX_TO_NATIONAL_DEX
        data = Path(RAM_DUMP).read_bytes()
        word = lambda a: struct.unpack_from(">I", data, a - 0x80000000)[0]
        count, base = word(word(0x804EFE20 - 22508)), word(0x804EFE20 - 22504)
        checked = 0
        for species in range(count):
            record = data[base - 0x80000000 + species * 0x124:][:0x124]
            evolutions = [struct.unpack_from(">BBHH", record, 0xA6 + 6 * k) for k in range(5)]
            evolutions = [e for e in evolutions if e[0]]
            dex = (INTERNAL_INDEX_TO_NATIONAL_DEX.get(species) or (None,))[0]
            if len(evolutions) == 1 and evolutions[0][0] == 4:
                to_dex = INTERNAL_INDEX_TO_NATIONAL_DEX[evolutions[0][3]][0]
                self.assertEqual((to_dex, evolutions[0][2]), NATIONAL_DEX_LEVEL_EVOLUTIONS.get(dex), dex)
                checked += 1
            elif evolutions and dex is not None and not any(e[0] == 4 for e in evolutions):
                self.assertIn(dex, GAME_NON_LEVEL_EVOLVERS)
        self.assertGreater(checked, 120)


class TestDistinctTeams(unittest.TestCase):
    def test_pick_distinct(self) -> None:
        pool = real_species_pool()
        rng = random.Random(1)
        taken = set(list(pool)[:300])
        for _ in range(50):
            self.assertNotIn(pick_distinct_species(rng, list(pool), 50, pool, taken), taken)

    def test_no_shuffled_team_repeats_a_species(self) -> None:
        for seed in range(20):
            species_pool, pools = load_real_trainer_pools()
            shuffle_teams(pools, species_pool, TeamShuffleOptions(legendary_safe=True), random.Random(seed))
            for trainer in pools[0].trainers:
                species = [mon.species_id for mon in trainer.team]
                self.assertEqual(len(species), len(set(species)), (seed, trainer.name))

    def test_each_slot_is_its_own_roll(self) -> None:
        """Vanilla duplicates do not stay duplicates (they never shared a record)."""
        raw = load_json_data_file("deckdata_story_trainers.json")
        doubled = [t for t in raw if len({s["species"] for s in t["team"] if s.get("kind") == "DPKM"})
                   < len([s for s in t["team"] if s.get("kind") == "DPKM"])]
        self.assertGreaterEqual(len(doubled), 10)
        records = [s["dpkm_index"] for t in raw for s in t["team"] if s.get("kind") == "DPKM"]
        self.assertEqual(len(records), len(set(records)))           # no two slots share a DPKM record


class TestPaddingAndMtBattle(unittest.TestCase):
    def test_settle_evolves_and_dedups(self) -> None:
        pool = real_species_pool()
        plan = {"new_dpkm_entries": [{"species": _internal(66), "level": 45, "moves": [1, 2, 3, 4]},
                                     {"species": _internal(67), "level": 45, "moves": [1, 2, 3, 4]}],
                "team_slot_plan": [{"trainer_index": 5, "new_entry_pos": 0}, {"trainer_index": 5, "new_entry_pos": 1}]}
        changed = settle_padding_members(plan, pool, {}, random.Random(0), {5: {_internal(68)}})
        species = [e["species"] for e in plan["new_dpkm_entries"]]
        self.assertEqual(2, changed)
        self.assertEqual(2, len(set(species)))
        self.assertNotIn(_internal(68), species)                    # Machamp is already on the team

    def test_mt_battle_members_evolve_for_their_level(self) -> None:
        pool = real_species_pool()
        out = evolve_for_final_levels({1: _internal(1), 2: _internal(1), 3: _internal(25)}, {1: 40, 2: 10, 3: 31},
                                      pool, random.Random(0))
        self.assertEqual({1: _internal(3), 3: _internal(26)}, out)

    def test_the_patcher_writes_them(self) -> None:
        from .test_addendum_423_nightmare_citadark import _deck, _record
        story = _deck({1: {"ai": 1, "slots": [1, 2]}}, [bytes(0x20), _record(1, 10), _record(4, 10)],
                      [bytes(0x20), bytes(0x20)])
        plan = {"level_assignment": {1: 40}, "new_dpkm_entries": [], "team_slot_plan": [],
                "species_assignment": {1: 3}}
        out = iso_patcher.apply_enhanced_difficulty_story_edit(story, deck_format.DeckFile(story), plan)
        self.assertEqual((3, 40), deck_format.DeckFile(out).dpkm_species_level(1))
        self.assertEqual((4, 10), deck_format.DeckFile(out).dpkm_species_level(2))


def _seed(world) -> dict:
    with tempfile.TemporaryDirectory() as tmp_dir:
        world.generate_output(tmp_dir)
        with zipfile.ZipFile(next(Path(tmp_dir).glob("*.appxd"))) as zf:
            return json.loads(zf.read("seed.json"))


class TestAGeneratedSeed(PokemonXDTestBase):
    options = {"enhanced_difficulty": 3, "enhanced_difficulty_level_scaling": True, "path_level_scaling": True,
               "exclude_mt_battle_trainers": False}

    def test_teams_are_distinct_and_evolved(self) -> None:
        world = self.multiworld.worlds[self.player]
        world.pre_output()
        seed = _seed(world)
        pool = real_species_pool()
        assignment = {int(k): v for k, v in seed["trainer_species_by_dpkm_index"].items()}
        plan = seed["enhanced_difficulty_plan"]
        levels = {int(k): v for k, v in plan["level_assignment"].items()}
        padded = collections.defaultdict(list)
        for entry, slot in zip(plan["new_dpkm_entries"], plan["team_slot_plan"]):
            padded[slot["trainer_index"]].append(entry["species"])
            self.assertEqual(entry["species"], resolve_natural_evolution(entry["species"], entry["level"], pool))
        for trainer in load_json_data_file("deckdata_story_trainers.json"):
            slots = [s for s in trainer["team"] if s.get("kind") == "DPKM"]
            species = [assignment.get(s["dpkm_index"], s["species"]) for s in slots]
            for slot, sp in zip(slots, species):
                level = levels.get(slot["dpkm_index"], slot["level"])
                self.assertEqual(sp, resolve_natural_evolution(sp, level, pool), (trainer["index"], sp, level))
            team = species + padded.get(trainer["index"], [])
            self.assertEqual(len(team), len(set(team)), trainer["index"])
        mt_plan = seed["mt_battle_enhanced_difficulty_plan"]
        self.assertTrue(mt_plan["species_assignment"])
        mt_levels = {int(k): v for k, v in mt_plan["level_assignment"].items()}
        mt_species = {int(k): v for k, v in mt_plan["species_assignment"].items()}
        for trainer in load_json_data_file("mtbattle_trainer_census.json"):
            for slot in trainer["team"]:
                if slot.get("kind") != "DPKM":
                    continue
                sp = mt_species.get(slot["dpkm_index"], slot["species"])
                level = mt_levels.get(slot["dpkm_index"], slot["level"])
                self.assertEqual(sp, resolve_natural_evolution(sp, level, pool))


if __name__ == "__main__":
    unittest.main()
