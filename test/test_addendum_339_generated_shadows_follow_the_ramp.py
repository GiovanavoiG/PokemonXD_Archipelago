"""ADDENDUM 339 (2026-09-24): a generated Shadow took its trainer's VANILLA average.

Player: "Can we double check generated shadow scaling - they're still not matching path scaling."

They were not. `shadow_expansion.build_shadow_expansion_plans` levels each new Pokemon at
`avg_level_by_trainer[idx] * level_multiplier`, and that average comes from the team census -- the vanilla
numbers. The multiplier carries Enhanced Difficulty (ADDENDUM 198) and nothing else. The plan is built in
`generate_early`, BEFORE `pre_output` resolves this seed's tier order, so the path plan does not exist yet.

ADDENDUM 269's shape exactly -- two phases, two level sources, no shared function -- and the same fix: settle
the value in the pass that already exists to settle it, after the tier order is known.
"""
import json
import tempfile
import zipfile
import unittest
from pathlib import Path

from Fill import distribute_items_restrictive

from . import PokemonXDTestBase
from ..game_data import real_trainer_data as rtd
from ..randomizer import path_level_scaling as pls


def _levels_by_dpkm(seed):
    return {int(k): v for k, v in seed["enhanced_difficulty_plan"]["level_assignment"].items()}


def _team_of(trainer_index, levels):
    deck = {e["index"]: e for e in rtd.load_json_data_file("deckdata_story_trainers.json")}
    entry = deck.get(trainer_index, {})
    return [levels.get(slot["dpkm_index"], slot["level"])
            for slot in entry.get("team", []) if slot["kind"] == "DPKM"]


class _Seeded(PokemonXDTestBase):
    def _seed(self):
        distribute_items_restrictive(self.multiworld)
        self.world.pre_output()
        with tempfile.TemporaryDirectory() as tmp:
            self.world.generate_output(tmp)
            with zipfile.ZipFile(next(Path(tmp).glob("*.appxd"))) as zf:
                return json.loads(zf.read("seed.json"))


class TestEveryGeneratedShadowSitsOnItsOwnTeam(_Seeded):
    options = {"path_level_scaling": True, "shadow_pokemon_expansion": 44,
               "randomize_travel_locations": True}

    def test_none_is_off_the_team_it_joins(self) -> None:
        """The reported symptom, as the assertion. Before this addendum, 22 of 25 sampled were outside their
        own team's spread -- Pyrite (ONBS) fielding 49-51 with a generated Shadow at 20."""
        seed = self._seed()
        levels = _levels_by_dpkm(seed)
        plans = seed.get("new_shadow_pokemon_plans") or []
        self.assertTrue(plans, "the expansion produced nothing -- this test would pass vacuously")
        for plan in plans:
            team = _team_of(int(plan["trainer_index"]), levels)
            if not team:
                continue      # a Shadow-only host has no ordinary team to sit on
            for mon in plan["new_pokemon"]:
                self.assertGreaterEqual(mon["level"], min(team) - 2,
                                        f"trainer {plan['trainer_index']} team={team}")
                self.assertLessEqual(mon["level"], max(team) + 2,
                                     f"trainer {plan['trainer_index']} team={team}")

    def test_each_matches_the_source_the_vanilla_shadows_use(self) -> None:
        """Not merely "close to the team" -- the SAME function. A generated Shadow and a vanilla one on one
        team at different levels is the disagreement ADDENDUM 287 spent an addendum on."""
        seed = self._seed()
        expected = pls.level_by_trainer_index(tier_by_region=self.world._path_tier_by_region)
        for plan in seed.get("new_shadow_pokemon_plans") or []:
            want = expected.get(int(plan["trainer_index"]))
            if want is None:
                continue
            for mon in plan["new_pokemon"]:
                self.assertEqual(want, mon["level"], f"trainer {plan['trainer_index']}")

    def test_the_pass_actually_moved_something(self) -> None:
        """Guards against the fix silently becoming a no-op."""
        self._seed()
        self.assertGreater(getattr(self.world, "_generated_shadows_relevelled", 0), 0)


class TestWithPathScalingOff(_Seeded):
    options = {"path_level_scaling": False, "shadow_pokemon_expansion": 44,
               "enhanced_difficulty": "fill_enemy_team", "enhanced_difficulty_level_scaling": True}

    def test_the_expansions_own_handling_is_left_alone(self) -> None:
        """With no ramp there is nothing to re-match to, and ADDENDUM 198's multiplier already covers ED. The
        pass must not touch the plan at all."""
        self._seed()
        self.assertEqual(0, getattr(self.world, "_generated_shadows_relevelled", 0))


class TestTheSourceOfTheBug(unittest.TestCase):
    def test_the_expansion_still_only_knows_the_vanilla_average(self) -> None:
        """Recorded rather than fixed at source: the plan is built in `generate_early`, where this seed's tier
        order does not exist yet. If `build_shadow_expansion_plans` ever gains a path-aware parameter, this
        test should fail and the re-level pass should be reconsidered rather than left doubled up."""
        import inspect

        from ..randomizer import shadow_expansion

        signature = inspect.signature(shadow_expansion.build_shadow_expansion_plans)
        self.assertIn("level_multiplier", signature.parameters)
        for name in signature.parameters:
            self.assertNotIn("path", name, "the expansion has become path-aware -- re-check the 339 pass")

    def test_the_relevel_runs_after_the_tier_order_is_resolved(self) -> None:
        """The whole reason it cannot live in `generate_early`."""
        import pathlib

        source = (pathlib.Path(__file__).resolve().parent.parent / "__init__.py").read_text(encoding="utf-8")
        resolve = source.index("self._path_tier_by_region = self._resolve_path_tier_order()")
        apply_pass = source.index("self._apply_final_levels_and_evolution()")
        self.assertLess(resolve, apply_pass)
        self.assertIn("self._relevel_generated_shadows()", source)
