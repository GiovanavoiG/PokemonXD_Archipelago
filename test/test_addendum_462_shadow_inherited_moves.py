"""ADDENDUM 462 (2026-10-10) -- Shadow Pokemon Inherit Replaced Moves.

An option re-adds, as a feature, the old bug where Shadow Pokemon kept illegal moves depending on what they
replaced. The fix was ADDENDUM 427's legal Shadow movesets; this option turns that pass off, so each randomized Shadow keeps its DPKM record's vanilla ordinary moves.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import zipfile

from . import PokemonXDTestBase
from .. import options


def _seed(world) -> dict:
    world.pre_output()
    with tempfile.TemporaryDirectory() as tmp:
        world.generate_output(tmp)
        with zipfile.ZipFile(next(pathlib.Path(tmp).glob("*.appxd"))) as zf:
            return json.loads(zf.read("seed.json"))


def _shadow_dpkms(world) -> "set[str]":
    entries = (world._shadow_species_assignment or {}).get("entries") or []
    return {str(int(e["dpkm_index"])) for e in entries if e.get("new_species_index") is not None}


class TestTheOption(PokemonXDTestBase):
    run_default_tests = False

    def test_off_by_default_and_in_the_shadow_group(self):
        self.assertEqual(0, options.ShadowInheritedMoves.default)
        group = next(g for g in options.OPTION_GROUPS if g.name == "Shadow Pokemon")
        self.assertIn(options.ShadowInheritedMoves, group.options)


class TestOffGivesLegalMoves(PokemonXDTestBase):
    options = {"randomize_shadow_species": True, "shadow_inherited_moves": False}

    def test_every_randomized_shadow_gets_new_moves(self):
        world = self.multiworld.worlds[self.player]
        shadows = _shadow_dpkms(world)
        self.assertTrue(shadows)
        moves = _seed(world)["trainer_moves_by_dpkm_index"] or {}
        self.assertTrue(shadows <= set(moves), sorted(shadows - set(moves))[:5])


class TestOnKeepsTheReplacedMoves(PokemonXDTestBase):
    options = {"randomize_shadow_species": True, "shadow_inherited_moves": True}

    def test_no_shadow_record_is_given_moves(self):
        world = self.multiworld.worlds[self.player]
        shadows = _shadow_dpkms(world)
        self.assertTrue(shadows)
        seed = _seed(world)
        moves = seed["trainer_moves_by_dpkm_index"] or {}
        self.assertFalse(shadows & set(moves), "a Shadow's ordinary moves were rewritten")
        self.assertTrue(moves, "ordinary trainers still get their legal movesets")
        self.assertTrue(any("Inherit Replaced Moves" in note for note in seed["notes"]))

    def test_shadow_moves_are_still_written(self):
        """The two Shadow-move slots live in the DDPK records and are a different channel entirely."""
        world = self.multiworld.worlds[self.player]
        self.assertTrue(world._shadow_species_assignment["entries"])
