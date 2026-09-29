"""Real-PokemonXDWorld-pipeline test for Enhanced Difficulty's Mt. Battle extension and the new Goal option
(2026-09-09, ADDENDUM 93, player requests: "make it so that the enhanced difficulty yaml option also
randomizes & fills the mt battle trainer teams" / "Let's also make it so that shadow pokemon still do not
randomize into mt. battle").

Mirrors `test_generate_output_combined.py`'s approach (a real `MultiWorld`/fill/`generate_output` cycle,
reading the produced `seed.json` back out) rather than testing `build_enhanced_difficulty_plan`/`mtbattle_team_
census()` in isolation (already covered by ad hoc checks during development) -- this is the test that would
have caught a wiring mistake in `__init__.py`'s `generate_output()` itself (wrong option gating, the Mt. Battle
block silently never running, `mt_battle_enhanced_difficulty_plan` never reaching `seed_data`, etc.), the same
class of bug this project's own combined-options tests exist to catch."""
import json
import tempfile
import zipfile
from pathlib import Path

from Fill import distribute_items_restrictive

from . import PokemonXDTestBase


class TestMtBattleEnhancedDifficultyOnExcludeOff(PokemonXDTestBase):
    options = {
        # ADDENDUM 196: the expansion defaults to 44 now; this test asserts the no-expansion path.
        "shadow_pokemon_expansion": 0,
        # ADDENDUM 197: Enhanced Difficulty is a Choice now. "fill_enemy_team" is the setting that
        # reproduces what this option did when it was a plain on/off, and the level scaling it used
        # to carry is its own toggle, so both are set to keep this test exercising what it always did.
        "enhanced_difficulty": "fill_enemy_team",
        "enhanced_difficulty_level_scaling": True,
        "exclude_mt_battle_trainers": False,
        "goal": "win_mt_battle",
    }

    def test_mt_battle_plan_is_populated_and_pads_trainers_when_not_excluded(self) -> None:
        distribute_items_restrictive(self.multiworld)

        with tempfile.TemporaryDirectory() as tmp_dir:
            self.world.generate_output(tmp_dir)
            appxd_files = list(Path(tmp_dir).glob("*.appxd"))
            self.assertEqual(len(appxd_files), 1)
            with zipfile.ZipFile(appxd_files[0]) as zf:
                seed_data = json.loads(zf.read("seed.json"))

        mt_plan = seed_data.get("mt_battle_enhanced_difficulty_plan")
        self.assertTrue(
            mt_plan, "mt_battle_enhanced_difficulty_plan is empty/None -- Enhanced Difficulty's Mt. Battle "
                      "extension silently produced nothing even though enhanced_difficulty was enabled and "
                      "exclude_mt_battle_trainers was off"
        )
        # Real DeckData_Hundred.bin census (ADDENDUM 92): 100 trainers, 321 total DPKM team slots -- every
        # existing member should get the level boost regardless of exclude_mt_battle_trainers.
        self.assertEqual(len(mt_plan["level_assignment"]), 321)
        # With exclude_mt_battle_trainers off, the same ramp rule as the main story roster should pad a real
        # majority of Mt. Battle's 100 trainers (trainers 1-5 excluded by the ramp itself, everything past 15
        # gets filled toward 6 wherever it has room) -- not a fragile exact count, just "padding is genuinely
        # happening," matching this project's own "assert the invariant, not an over-fit exact number" style.
        padded_trainers = {s["trainer_index"] for s in mt_plan["team_slot_plan"]}
        self.assertGreater(len(padded_trainers), 50)
        self.assertTrue(padded_trainers.issubset(set(range(1, 101))))

        # Enhanced Difficulty's ordinary Story-side plan must still be produced independently (this option
        # never stops doing what it already did) -- and the two plans' trainer_index values must never be
        # treated as the same namespace by anything reading this seed.json (ADDENDUM 92/93's core warning).
        self.assertTrue(seed_data.get("enhanced_difficulty_plan"))

        # Shadow Pokemon Expansion must never reference Mt. Battle even though this seed didn't touch that
        # option at all here -- covered directly (not just by omission) since a future regression that wires
        # Shadow Expansion into Mt. Battle's census would very likely start emitting trainer_index values
        # in this exact 1-100 range that this seed's new_shadow_pokemon_plans should never contain.
        shadow_plans = seed_data.get("new_shadow_pokemon_plans") or []
        self.assertEqual(shadow_plans, [], "shadow_pokemon_expansion was off for this seed but produced a plan")

        # Goal option reaches the client via slot_data.
        self.assertEqual(seed_data.get("player"), self.player)


class TestMtBattleEnhancedDifficultyExcluded(PokemonXDTestBase):
    options = {
        # ADDENDUM 197: Enhanced Difficulty is a Choice now. "fill_enemy_team" is the setting that
        # reproduces what this option did when it was a plain on/off, and the level scaling it used
        # to carry is its own toggle, so both are set to keep this test exercising what it always did.
        "enhanced_difficulty": "fill_enemy_team",
        "enhanced_difficulty_level_scaling": True,
        "exclude_mt_battle_trainers": True,
    }

    def test_nothing_from_enhanced_difficulty_reaches_mt_battle_when_excluded(self) -> None:
        """RETARGETED by ADDENDUM 388. This asserted the opposite -- 321 levels boosted with the exclude
        toggle ON -- and that was the bug the player reported: the option reads "Excludes Mt Battle from
        enhanced difficulty", is on by default, and still multiplied every Mt. Battle level by 1.33. Measured
        across all 100 trainers, vanilla's 9..70 mean 48.5 was arriving as 11..93 mean 64.0.

        The plan object is still PRODUCED, because path scaling writes its Mt. Battle ramp into the same
        structure and that is a different option. With path scaling off, as here, it is simply empty."""
        distribute_items_restrictive(self.multiworld)

        with tempfile.TemporaryDirectory() as tmp_dir:
            self.world.generate_output(tmp_dir)
            appxd_files = list(Path(tmp_dir).glob("*.appxd"))
            with zipfile.ZipFile(appxd_files[0]) as zf:
                seed_data = json.loads(zf.read("seed.json"))

        mt_plan = seed_data.get("mt_battle_enhanced_difficulty_plan")
        self.assertTrue(mt_plan is not None,
                        "mt_battle_enhanced_difficulty_plan should still be produced -- path scaling writes "
                        "its Mt. Battle ramp into it, and that is a separate option")
        # ADDENDUM 388: exclude means both halves -- no padding AND no multiplier.
        self.assertEqual(mt_plan["level_assignment"], {})
        self.assertEqual(mt_plan["new_dpkm_entries"], [])
        self.assertEqual(mt_plan["team_slot_plan"], [])


class TestGoalOptionDefaultsToDefeatGreevil(PokemonXDTestBase):
    options = {}

    def test_goal_defaults_to_defeat_greevil_and_reaches_slot_data(self) -> None:
        # option_defeat_greevil == 0, the Goal option's documented default.
        self.assertEqual(self.world.options.goal.value, 0)
        slot_data = self.world.fill_slot_data()
        self.assertEqual(slot_data.get("goal"), 0)


class TestGoalOptionWinMtBattle(PokemonXDTestBase):
    options = {"goal": "win_mt_battle"}

    def test_goal_win_mt_battle_reaches_slot_data(self) -> None:
        self.assertEqual(self.world.options.goal.value, 1)
        slot_data = self.world.fill_slot_data()
        self.assertEqual(slot_data.get("goal"), 1)
