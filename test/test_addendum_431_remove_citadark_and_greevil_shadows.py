"""ADDENDUM 431 (2026-10-06) -- Remove Citadark Shadows, Remove Greevil Shadows.

Player: "Make an option to remove shadows from citadark, and an option to remove shadows from greevil. Make sure
both of these redistribute the shadow pokemon amongst the rest of the game."
"""
from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from . import PokemonXDTestBase
from .. import options
from ..game_data import nightmare_citadark as NC
from ..game_data.catch_rate_exclusions import citadark_trainer_indices
from ..game_data.trainer_roster import TRAINERS
from ..tools import iso_patcher
from ..tools import xd_deck_format as deck_format
from .test_addendum_423_nightmare_citadark import _deck, _record
from .test_addendum_424_relocated_citadark_shadows import _dark

GREEVIL = NC.GREEVIL_SHADOW_TRAINERS


def _shadow_slots(trainers) -> int:
    return sum(1 for t in TRAINERS if t["index"] in trainers for s in t["team"] if s["kind"] == "DDPK")


def _seed(world) -> dict:
    world.pre_output()
    with tempfile.TemporaryDirectory() as tmp:
        world.generate_output(tmp)
        with zipfile.ZipFile(next(Path(tmp).glob("*.appxd"))) as zf:
            return json.loads(zf.read("seed.json"))


class TestTheSets(unittest.TestCase):
    def test_options_exist(self):
        fields = options.PokemonXDOptions.__dataclass_fields__
        self.assertIn("remove_citadark_shadows", fields)
        self.assertIn("remove_greevil_shadows", fields)

    def test_which_trainers(self):
        citadark = NC.shadow_removal_trainers(False, True, False)
        self.assertEqual(citadark_trainer_indices() - {199, 200, 201}, citadark)
        self.assertEqual(frozenset({199, 200}), NC.shadow_removal_trainers(False, False, True))
        self.assertEqual(citadark_trainer_indices() - {201}, NC.shadow_removal_trainers(False, True, True))
        self.assertEqual(NC.nightmare_trainer_indices(), NC.shadow_removal_trainers(True, False, False))
        self.assertEqual(frozenset(), NC.shadow_removal_trainers(False, False, False))

    def test_every_island_shadow_is_covered(self):
        both = NC.shadow_removal_trainers(False, True, True)
        self.assertEqual(36, _shadow_slots(citadark_trainer_indices()))
        self.assertEqual(36, len(NC.removed_shadow_ddpks(both)))
        self.assertEqual(7, len(NC.removed_shadow_ddpks(GREEVIL)))
        self.assertEqual(36, len(NC.vacated_slots(both, frozenset())))
        # A Nightmare team replaces its trainer's slots outright, so only Lugia's is left to vacate.
        self.assertEqual([{"trainer_index": 199, "slot": 0, "ddpk_index": 73}],
                         NC.vacated_slots(NC.shadow_removal_trainers(True, False, True), NC.nightmare_trainer_indices()))


class _Base(PokemonXDTestBase):
    expected_trainers: frozenset = frozenset()
    expected_moved = 0
    expected_vacated = 0

    def test_moved_off_and_redistributed(self):
        if type(self) is _Base:
            self.skipTest("base class")
        world = self.multiworld.worlds[self.player]
        self.assertEqual(self.expected_trainers, world._shadow_removal_trainers)
        moved = [s for plan in world._nightmare_relocations for s in plan["shadows"]]
        self.assertEqual(self.expected_moved, len(moved))
        self.assertEqual(self.expected_moved, len({s["ddpk_index"] for s in moved}))
        hosts = {int(plan["trainer_index"]) for plan in world._nightmare_relocations}
        self.assertFalse(hosts & citadark_trainer_indices(), "no Shadow lands back on Citadark Isle")
        self.assertGreater(len(hosts), 5, "spread across the game")
        self.assertEqual(self.expected_vacated, len(world._shadow_vacated_slots))
        seed = _seed(world)
        self.assertEqual(self.expected_vacated, len(seed.get("shadow_vacated_slots") or []))
        expansion_hosts = {int(p["trainer_index"]) for p in seed.get("new_shadow_pokemon_plans") or ()}
        self.assertFalse(expansion_hosts & self.expected_trainers)
        # Every Shadow still counts: 83 purifiable plus the expansion.
        self.assertEqual(83 + sum(len(p["new_pokemon"]) for p in seed.get("new_shadow_pokemon_plans") or ()),
                         world._purification_location_count)


class TestRemoveCitadark(_Base):
    options = {"remove_citadark_shadows": True, "shadow_pokemon_expansion": 20, "randomize_shadow_species": True}
    expected_trainers = citadark_trainer_indices() - {199, 200, 201}
    expected_moved = 29
    expected_vacated = 29


class TestRemoveGreevil(_Base):
    options = {"remove_greevil_shadows": True}
    expected_trainers = frozenset({199, 200})
    expected_moved = 7
    expected_vacated = 7


class TestBoth(_Base):
    options = {"remove_citadark_shadows": True, "remove_greevil_shadows": True, "enhanced_difficulty": 3,
               "path_level_scaling": True}
    expected_trainers = citadark_trainer_indices() - {201}
    expected_moved = 36
    expected_vacated = 36


class TestWithNightmare(_Base):
    options = {"nightmare_citadark": True, "remove_greevil_shadows": True}
    expected_trainers = NC.nightmare_trainer_indices() | {199}
    expected_moved = 36
    expected_vacated = 1


class TestTheVacateEdit(unittest.TestCase):
    def _story(self):
        records = [bytes(0x20), _record(10, 60), _record(11, 60), _record(12, 60)]
        # trainer 1: slot 0 is Shadow DDPK 2 (over DPKM 3), slot 1 an ordinary DPKM 1.
        return _deck({1: {"ai": 1, "slots": [2, 1], "mask": 0b01}}, records, [bytes(0x20), bytes(0x20)])

    def test_the_slot_becomes_an_ordinary_copy_at_the_shadow_level(self):
        story, dark = self._story(), _dark({2: 3})
        out, count = iso_patcher.apply_shadow_vacate_edit(story, dark, [{"trainer_index": 1, "slot": 0,
                                                                         "ddpk_index": 2}])
        self.assertEqual(1, count)
        deck = deck_format.DeckFile(out)
        team = sorted(deck.trainer(1)["team"], key=lambda m: m["slot"])
        self.assertEqual(["DPKM", "DPKM"], [m["kind"] for m in team])
        self.assertEqual((12, 40), deck.dpkm_species_level(team[0]["dpkm_index"]))   # DDPK level 40
        self.assertEqual((12, 60), deck.dpkm_species_level(3), "the Shadow's own record is untouched")
        # ...so the relocation can still hang the Shadow on a host.
        moved, levels = iso_patcher.apply_nightmare_relocation_edit(
            out, dark, [{"trainer_index": 1, "shadows": [{"ddpk_index": 2, "dpkm_index": 3, "level": 15}]}])
        team = deck_format.DeckFile(moved).trainer(1)["team"]
        self.assertEqual(1, sum(1 for m in team if m["kind"] == "DDPK"))
        self.assertEqual({2: 15}, levels)

    def test_a_slot_that_is_not_that_shadow_is_refused(self):
        story, dark = self._story(), _dark({2: 3})
        with self.assertRaises(ValueError):
            iso_patcher.apply_shadow_vacate_edit(story, dark, [{"trainer_index": 1, "slot": 1, "ddpk_index": 2}])


if __name__ == "__main__":
    unittest.main()


class TestOnTheRealDeck(unittest.TestCase):
    """Vacate then relocate, on the real DeckData_Story.bin: Citadark Isle ends with no Shadow at all, every one
    of the 83 is on exactly one trainer, and each emptied slot is an ordinary Pokemon of the Shadow's species."""

    def test_the_island_is_shadow_free(self):
        import random
        from .test_addendum_424_relocated_citadark_shadows import DECK_DUMP, FENCE
        from ..game_data.real_trainer_data import real_trainer_free_slot_census
        if not Path(DECK_DUMP).is_file():
            self.skipTest("needs the deck_archive dump")
        data = Path(DECK_DUMP).read_bytes()
        entries = iso_patcher.parse_fsys(data)

        def dec(name):
            e = entries[name]
            return deck_format.lzss_decode(data[e["data_off"]:e["data_off"] + 0x10 + e["comp_size"]])

        story, dark = dec("DeckData_Story.bin"), dec("DeckData_DarkPokemon.bin")
        trainers = NC.shadow_removal_trainers(False, True, True)
        vacated = NC.vacated_slots(trainers, frozenset())
        plan = NC.plan_relocations(random.Random(431), real_trainer_free_slot_census(), FENCE, trainers=trainers)
        before = deck_format.DeckFile(story)
        out, count = iso_patcher.apply_shadow_vacate_edit(story, dark, vacated)
        out, levels = iso_patcher.apply_nightmare_relocation_edit(out, dark, plan)
        self.assertEqual(36, count)
        self.assertEqual(36, len(levels))
        deck = deck_format.DeckFile(out)
        refs = {}
        for trainer in deck.all_trainers():
            for m in trainer["team"]:
                if m["kind"] == "DDPK":
                    refs.setdefault(m["ddpk_index"], []).append(trainer["index"])
                    self.assertNotIn(trainer["index"], citadark_trainer_indices())
        self.assertEqual(83, len(refs))
        # Only the vanilla re-fights (Miror B., the ONBS crew) name a Shadow twice; every moved one is on one host.
        vanilla = {}
        for trainer in before.all_trainers():
            for m in trainer["team"]:
                if m["kind"] == "DDPK":
                    vanilla.setdefault(m["ddpk_index"], []).append(trainer["index"])
        self.assertEqual({k for k, v in vanilla.items() if len(v) > 1}, {k for k, v in refs.items() if len(v) > 1})
        for p in plan:
            for shadow in p["shadows"]:
                self.assertEqual([p["trainer_index"]], refs[shadow["ddpk_index"]])
        darkfile = deck_format.DarkPokemonFile(dark)
        for v in vacated:
            old = next(m for m in before.trainer(v["trainer_index"])["team"] if m["slot"] == v["slot"])
            new = next(m for m in deck.trainer(v["trainer_index"])["team"] if m["slot"] == v["slot"])
            self.assertEqual("DPKM", new["kind"])
            shadow_record = darkfile.ddpk_full(old["ddpk_index"])["story_deck_index"]
            self.assertEqual(before.dpkm_species_level(shadow_record)[0], deck.dpkm_species_level(new["dpkm_index"])[0])
        self.assertEqual(1, deck.trainer(199)["party_size"])
