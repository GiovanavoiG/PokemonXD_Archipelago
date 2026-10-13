"""ADDENDUM 429 (2026-10-06) -- Nightmare Greevil, and trade evolutions by level.

Player: "Make an option that makes ONLY Greevil gain one of those nightmare teams. Nightmare_Greevil - also, can
we make an option so that we can evolve trade evolutions by levelup instead, with the same logic as our trainer
team evolutions?"
"""
from __future__ import annotations

import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from . import PokemonXDTestBase
from .. import options
from ..game_data import candy_box as CB
from ..game_data import nightmare_citadark as NC
from ..game_data import trade_evolutions as TE
from ..game_data.evolution_data import NATIONAL_DEX_LEVEL_EVOLUTIONS, TRAINER_EVOLUTIONS
from ..game_data.trainer_roster import TRAINERS as TRAINER_ROSTER
from ..tools import xd_rel_format as rel_format
from .test_addendum_311_pit_stop_and_filler_categories import FakeRel

RAM_DUMP = Path("/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/battle1.bin")


def _seed(world) -> dict:
    world.pre_output()
    with tempfile.TemporaryDirectory() as tmp:
        world.generate_output(tmp)
        with zipfile.ZipFile(next(Path(tmp).glob("*.appxd"))) as zf:
            return json.loads(zf.read("seed.json"))


class TestTheOptions(unittest.TestCase):
    def test_both_exist_off_by_default_and_are_in_the_template(self):
        fields = options.PokemonXDOptions.__dataclass_fields__
        text = (Path(__file__).resolve().parent.parent / "data" / "reference_template.yaml").read_text()
        # Trade Evolutions By Level is default ON since the player's options.py of 2026-10-10.
        for name, cls, default in (("nightmare_greevil", options.NightmareGreevil, 0),
                                   ("trade_evolutions_by_level", options.TradeEvolutionsByLevel, 1)):
            self.assertIn(name, fields)
            self.assertEqual(default, cls.default)
            self.assertIn(f"  {name}:", text)


# --- Nightmare Greevil ---------------------------------------------------------------------------------------

class TestGreevilsFinalFight(unittest.TestCase):
    def test_it_is_greevils_third_row_and_holds_no_shadows(self):
        row = next(t for t in TRAINER_ROSTER if t["index"] == NC.GREEVIL_FINAL_TRAINER)
        self.assertEqual("GREEVIL", row["name"])
        self.assertEqual(3, row["occurrence"])
        self.assertTrue(all(slot["kind"] == "DPKM" for slot in row["team"]))
        self.assertIn(NC.GREEVIL_FINAL_TRAINER, NC.nightmare_trainer_indices())


class TestNightmareGreevil(PokemonXDTestBase):
    options = {"nightmare_greevil": True, "shadow_pokemon_expansion": 20}

    def test_only_greevils_final_fight_takes_a_team(self):
        world = self.multiworld.worlds[self.player]
        self.assertEqual([NC.GREEVIL_FINAL_TRAINER], list(world._nightmare_teams))
        self.assertIn(world._nightmare_teams[NC.GREEVIL_FINAL_TRAINER], NC.TEAM_KEYS)
        self.assertEqual([], world._nightmare_relocations)
        self.assertEqual(frozenset(), world._nightmare_removed_dpkm)
        self.assertEqual(75, world._vanilla_shadow_count)   # RETARGETED BY ADDENDUM 479 (was 83)
        seed = _seed(world)
        self.assertEqual([str(NC.GREEVIL_FINAL_TRAINER)], list(seed["nightmare_citadark_teams"]))
        self.assertFalse(seed.get("nightmare_shadow_relocations"))
        # The rest of Citadark Isle can still host expansion Shadows; Greevil's final fight cannot.
        hosts = {int(plan["trainer_index"]) for plan in seed["new_shadow_pokemon_plans"] or ()}
        self.assertNotIn(NC.GREEVIL_FINAL_TRAINER, hosts)
        # Never padded or scaled: a fixed six at level 100.
        plan = seed.get("enhanced_difficulty_plan") or {}
        self.assertNotIn(NC.GREEVIL_FINAL_TRAINER, {s["trainer_index"] for s in plan.get("team_slot_plan", ())})


class TestNightmareCitadarkWins(PokemonXDTestBase):
    options = {"nightmare_greevil": True, "nightmare_citadark": True}

    def test_citadark_already_covers_greevil(self):
        world = self.multiworld.worlds[self.player]
        self.assertEqual(NC.nightmare_trainer_indices(), frozenset(world._nightmare_teams))


# --- Trade evolutions by level ----------------------------------------------------------------------------------

class TestTheEdits(unittest.TestCase):
    def test_every_level_is_the_trainer_tables(self):
        dex_of = {373: 366, 374: 367, 375: 368}
        for species, _slot, _old, (_method, level, target) in TE.EVOLUTION_EDITS:
            if (species, target) == (79, 80):
                self.assertEqual((80, 37), NATIONAL_DEX_LEVEL_EVOLUTIONS[79])   # Slowbro keeps its own 37
                continue
            self.assertIn((dex_of.get(target, target), level), TRAINER_EVOLUTIONS[dex_of.get(species, species)],
                          species)

    def test_every_trade_becomes_a_level_method_and_branches_are_exclusive(self):
        by_species = {}
        for species, slot, (old_method, _c, _t), (new_method, _l, _tg) in TE.EVOLUTION_EDITS:
            by_species.setdefault(species, []).append(new_method)
            self.assertIn(new_method, CB.LEVEL_EVOLUTION_METHODS)
        self.assertEqual(sorted([11, 12]), sorted(by_species[79]))
        self.assertEqual(sorted([11, 12]), sorted(by_species[373]))

    def test_the_candy_box_list_is_the_same(self):
        self.assertEqual(TE.NEW_TWO_STAGE_LEVEL_EVOLVERS, CB.TRADE_BY_LEVEL_TWO_STAGE)
        # ADDENDUM 451: one table for both -- 99 for anything that can still evolve.
        self.assertEqual(CB.target_level_table(), CB.target_level_table(True))
        self.assertEqual(99, CB.target_level_table(True)[63])      # Abra: Kadabra, then Alakazam
        self.assertEqual(99, CB.target_level_table(True)[64])      # Kadabra
        self.assertEqual(100, CB.target_level_table(True)[65])     # Alakazam
        # ADDENDUM 451: the two Candy Box patches are now identical.
        self.assertEqual(CB.dol_patch_words(False), CB.dol_patch_words(True))


@unittest.skipUnless(RAM_DUMP.is_file(), "needs a RAM dump with XD's species table")
class TestAgainstTheGamesTable(unittest.TestCase):
    def setUp(self):
        data = RAM_DUMP.read_bytes()
        word = lambda a: struct.unpack_from(">I", data, a - 0x80000000)[0]
        self.count, base = word(word(0x804EFE20 - 22508)), word(0x804EFE20 - 22504)
        self.evolutions = {}
        for species in range(self.count):
            record = data[base - 0x80000000 + species * 0x124:][:0x124]
            self.evolutions[species] = [struct.unpack_from(">BBHH", record, 0xA6 + 6 * k) for k in range(5)]

    def test_the_vanilla_values_are_the_games(self):
        for species, slot, old, _new in TE.EVOLUTION_EDITS:
            method, _pad, condition, target = self.evolutions[species][slot]
            self.assertEqual(old, (method, condition, target), species)

    def test_no_trade_evolution_is_left(self):
        edited = {(s, k) for s, k, _o, _n in TE.EVOLUTION_EDITS}
        for species, entries in self.evolutions.items():
            for slot, (method, _p, _c, _t) in enumerate(entries):
                if method in (TE.TRADE, TE.TRADE_ITEM):
                    self.assertIn((species, slot), edited, species)

    def test_the_two_stage_list_follows_from_the_edited_table(self):
        table = {s: [(m, t) for m, _p, _c, t in e if m] for s, e in self.evolutions.items()}
        for species, slot, _old, (method, _cond, target) in TE.EVOLUTION_EDITS:
            entries = [(m, t) for m, _p, _c, t in self.evolutions[species]]
            entries[slot] = (method, target)
            table[species] = [(m, t) for m, t in entries if m]
        level = CB.LEVEL_EVOLUTION_METHODS
        two = {s for s in range(self.count)
               if any(m in level and any(m2 in level for m2, _ in table.get(t, [])) for m, t in table[s])}
        self.assertEqual(set(CB.TWO_STAGE_LEVEL_EVOLVERS) | set(TE.NEW_TWO_STAGE_LEVEL_EVOLVERS), two)


class TestTheWriter(unittest.TestCase):
    def _rel(self, edits=TE.EVOLUTION_EDITS):
        base = 0x40
        data = bytearray(base + 415 * 0x124)
        for species, slot, (method, condition, target), _new in edits:
            struct.pack_into(">BBHH", data, base + species * 0x124 + 0xA6 + slot * 6, method, 0, condition, target)
        return FakeRel(bytes(data), {rel_format.XD_POKEMON_STATS_POINTER: base},
                       {rel_format.XD_NUMBER_OF_POKEMON_POINTER: 415}), base

    def test_writes_every_edit_and_nothing_else(self):
        rel, base = self._rel()
        out = bytearray(rel.data)
        self.assertEqual(len(TE.EVOLUTION_EDITS), rel_format.apply_evolution_edits(out, rel, TE.EVOLUTION_EDITS)
                         ["evolutions_written"])
        for species, slot, _old, new in TE.EVOLUTION_EDITS:
            method, _p, condition, target = struct.unpack_from(">BBHH", out, base + species * 0x124 + 0xA6 + slot * 6)
            self.assertEqual(new, (method, condition, target))
        changed = rel_format.byte_diff_offsets(rel.data, bytes(out))
        allowed = {base + s * 0x124 + 0xA6 + k * 6 + i for s, k, _o, _n in TE.EVOLUTION_EDITS for i in range(6)}
        self.assertTrue(set(changed) <= allowed)
        again = bytearray(out)
        self.assertEqual(0, rel_format.apply_evolution_edits(again, FakeRel(bytes(out), {88: base}, {89: 415}),
                                                             TE.EVOLUTION_EDITS)["evolutions_written"])

    def test_a_different_build_is_refused_whole(self):
        rel, base = self._rel()
        data = bytearray(rel.data)
        struct.pack_into(">B", data, base + 373 * 0x124 + 0xA6 + 6, 9)      # Clamperl's second entry disagrees
        rel = FakeRel(bytes(data), {88: base}, {89: 415})
        out = bytearray(data)
        with self.assertRaises(ValueError):
            rel_format.apply_evolution_edits(out, rel, TE.EVOLUTION_EDITS)
        self.assertEqual(bytes(data), bytes(out))


class TestTheSeedCarriesIt(PokemonXDTestBase):
    options = {"trade_evolutions_by_level": True}

    def test_flag(self):
        world = self.multiworld.worlds[self.player]
        self.assertTrue(_seed(world)["trade_evolutions_by_level"])
        self.assertEqual(1, world.fill_slot_data()["trade_evolutions_by_level"])


if __name__ == "__main__":
    unittest.main()


class TestFriendshipByLevel(unittest.TestCase):
    """ADDENDUM 451. Player: "Change friendship evolutions to just be by level." """

    def test_levels_follow_the_trainer_table(self):
        from ..game_data import evolution_data
        from ..tools.xd_species_index import INTERNAL_INDEX_TO_NATIONAL_DEX as M

        self.assertEqual(7, len(TE.FRIENDSHIP_EVOLUTION_EDITS))
        for species, _slot, (old_method, _c, _t), (method, level, target) in TE.FRIENDSHIP_EVOLUTION_EDITS:
            self.assertEqual((TE.FRIENDSHIP, TE.LEVEL), (old_method, method))
            options = dict(evolution_data.TRAINER_EVOLUTIONS[M[species][0]])
            self.assertEqual(options[M[target][0]], level, species)

    def test_selected_by_the_flags(self):
        self.assertEqual(TE.EVOLUTION_EDITS, TE.evolution_edits())
        self.assertEqual(TE.FRIENDSHIP_EVOLUTION_EDITS, TE.evolution_edits(False, True))
        self.assertEqual(TE.EVOLUTION_EDITS + TE.FRIENDSHIP_EVOLUTION_EDITS, TE.evolution_edits(True, True))


@unittest.skipUnless(RAM_DUMP.is_file(), "needs a RAM dump with XD's species table")
class TestFriendshipAgainstTheGamesTable(TestAgainstTheGamesTable):
    def test_every_friendship_entry_is_edited(self):
        edited = {(s, k): old for s, k, old, _n in TE.FRIENDSHIP_EVOLUTION_EDITS}
        for species, entries in self.evolutions.items():
            for slot, (method, _p, condition, target) in enumerate(entries):
                if method == TE.FRIENDSHIP:
                    self.assertEqual((method, condition, target), edited[(species, slot)], species)
        self.assertEqual(len(edited), sum(1 for e in self.evolutions.values() for m, *_ in e if m == TE.FRIENDSHIP))


class TestTheSeedCarriesFriendship(PokemonXDTestBase):
    def test_on_in_every_seed(self):
        import json
        import tempfile
        import zipfile
        world = self.multiworld.worlds[self.player]
        with tempfile.TemporaryDirectory() as tmp:
            world.generate_output(tmp)
            with zipfile.ZipFile(next(Path(tmp).glob("*.appxd"))) as zf:
                self.assertTrue(json.loads(zf.read("seed.json"))["friendship_evolutions_by_level"])
