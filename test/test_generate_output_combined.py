"""Real-PokemonXDWorld-pipeline test (2026-09-08): exercises the actual `generate_output()` code path -- not
just the randomizer modules in isolation the way test_shadow_expansion.py/test_enhanced_difficulty.py/
test_combined_shadow_and_enhanced_difficulty.py do -- with Shadow Pokemon Expansion (maxed, 44) and Enhanced
Difficulty both turned on in the SAME real seed, alongside species/moveset reassignment and chest
randomization, so the actual `__init__.py` wiring (imports, the `shadow_slots_consumed_by_trainer` hand-off,
`adjust_team_census_for_reserved_slots`) runs for real through a full `MultiWorld`/fill/`generate_output` cycle,
not just the pure-data helpers it calls. This is the closest this project can get to a true end-to-end check
without a real ISO (see the project's own docs for why real ISO writing/patching is validated by the player on
their own machine, never by this dev environment).

Reads the produced `.appxd`'s `seed.json` back out and asserts: no crash through the whole real generation
pipeline; both `new_shadow_pokemon_plans` and `enhanced_difficulty_plan` are actually populated (not silently
skipped); and the same no-overflow invariant `test_combined_shadow_and_enhanced_difficulty.py` checks against
real trainer-census data in isolation also holds for whatever this specific seed's real `self.random`-driven
plans came out to."""
import json
import tempfile
import zipfile
from pathlib import Path

from Fill import distribute_items_restrictive

from . import PokemonXDTestBase


class TestGenerateOutputCombinedShadowAndEnhancedDifficulty(PokemonXDTestBase):
    options = {
        "randomize_shadow_species": True,
        "shuffle_trainer_movesets": True,
        "randomize_chests": True,
        "shuffle_trainer_defeats": True,
        "shadow_pokemon_expansion": 44,
        # ADDENDUM 197: Enhanced Difficulty is a Choice now. "fill_enemy_team" is the setting that
        # reproduces what this option did when it was a plain on/off, and the level scaling it used
        # to carry is its own toggle, so both are set to keep this test exercising what it always did.
        "enhanced_difficulty": "fill_enemy_team",
        "enhanced_difficulty_level_scaling": True,
    }

    def test_generate_output_produces_a_consistent_combined_plan(self) -> None:
        distribute_items_restrictive(self.multiworld)

        with tempfile.TemporaryDirectory() as tmp_dir:
            self.world.generate_output(tmp_dir)
            appxd_files = list(Path(tmp_dir).glob("*.appxd"))
            self.assertEqual(len(appxd_files), 1, f"expected exactly one .appxd output, found {appxd_files}")

            with zipfile.ZipFile(appxd_files[0]) as zf:
                seed_data = json.loads(zf.read("seed.json"))

        shadow_plans = seed_data.get("new_shadow_pokemon_plans")
        self.assertTrue(shadow_plans, "new_shadow_pokemon_plans is empty/None -- Shadow Pokemon Expansion "
                                       "silently produced nothing even though it was set to the max (44)")
        ed_plan = seed_data.get("enhanced_difficulty_plan")
        self.assertTrue(ed_plan, "enhanced_difficulty_plan is empty/None -- Enhanced Difficulty silently "
                                  "produced nothing even though it was enabled")

        shadow_added_by_trainer = {p["trainer_index"]: len(p["new_pokemon"]) for p in shadow_plans}
        ed_added_by_trainer: dict[int, int] = {}
        for step in ed_plan["team_slot_plan"]:
            ed_added_by_trainer[step["trainer_index"]] = ed_added_by_trainer.get(step["trainer_index"], 0) + 1

        # This test doesn't have direct access to each trainer's real free_slots (that's real_trainer_data's
        # own internal census, exercised directly by test_combined_shadow_and_enhanced_difficulty.py) -- but it
        # CAN assert the weaker, still load-bearing invariant that no trainer received a combined new-member
        # count over 6 (the real DTNR hard cap regardless of starting party size), which is exactly the shape
        # of overflow that would make write_enhanced_difficulty_patch's DTNR slot search raise StopIteration.
        for idx in set(shadow_added_by_trainer) & set(ed_added_by_trainer):
            combined = shadow_added_by_trainer[idx] + ed_added_by_trainer[idx]
            self.assertLessEqual(
                combined, 6,
                f"trainer {idx} got {shadow_added_by_trainer[idx]} Shadow Expansion + "
                f"{ed_added_by_trainer[idx]} Enhanced Difficulty new team members ({combined} total) -- "
                "exceeds the real 6-Pokemon team cap"
            )
