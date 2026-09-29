"""ADDENDUM 287 (2026-09-19) -- a Shadow Pokemon stored in two tables must land in both.

Player: "user is reporting a shadow metagross being two-hit by a shadow jumpluff - this seems insane. are we
managing stats correctly upon generating pokemon/scaling trainers?"

IT IS INSANE, AND THERE WERE TWO INDEPENDENT BUGS, EITHER OF WHICH ALONE PRODUCES IT.

A Shadow's level is stored TWICE: at `+0x02` of the DPKM record its DDPK entry points at, and at `+0x02` of
the DDPK record itself. `iso_patcher`'s own comment has said since ADDENDUM 198 that "moving one without the
other would leave a Shadow disagreeing with itself". Both halves were built correctly. Neither reached the
disc.

  1. THE DROPPED KEY. `apply_patch` rebuilds `enhanced_difficulty_plan` field by field from the seed, and the
     rebuild did not list `shadow_level_assignment`. `__init__.py` wrote it; nothing read it. So
     `apply_shadow_level_boost` was unreachable in the real pipeline and the DDPK byte kept its vanilla value
     while the DPKM half of the SAME plan moved. Measured against a real path-scaled seed: all 83 vanilla
     Shadows disagreeing with themselves by a mean of +18 levels, maximum +33.

  2. THE WRONG CONTAINER. Even reached, it wrote `deck_archive.fsys`'s copy of `DeckData_DarkPokemon.bin`.
     ADDENDUM 58 established from live RAM that `common.fsys`'s two copies are the ones the game loads and
     that `deck_archive.fsys`'s "appears to be effectively unused". `write_shadow_multi_trainer_patch` has
     mirrored into all three since; this function never did, because it inherited a docstring written when it
     genuinely had no second container.

  3. AND THE GATE HAD DRIFTED. `generate_early`'s Shadow relevel block says in as many words "The gate is
     generate_output()'s gate". ADDENDUM 266 added `path_level_scaling` to generate_output()'s gate and not to
     this one, so with path scaling on and ED off a Shadow's species was evolved against its VANILLA level and
     then shipped at the path tier.

WHAT MADE ALL THREE SURVIVABLE IS THE SAME THING: every existing test checked the PLAN. `test_addendum_198`
asserts the two planned values match. Nothing asserted that both reach an ISO, and nothing compared the two
gates. So this file tests the JOIN rather than either side of it -- the same move ADDENDUM 243 made for the
`Defeat -` region drift after that class of bug had been found four separate times.
"""
from __future__ import annotations

import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


class TestThePlanKeySurvivesTheSeedBoundary(unittest.TestCase):
    """BUG 1. The seed is JSON and `apply_patch` rebuilds the plan by hand -- a whitelist that silently drops
    whatever the other end adds later."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.patcher = _source("tools/iso_patcher.py")
        cls.world = _source("__init__.py")
        start = cls.patcher.index("enhanced_difficulty_plan_raw = seed.get(")
        cls.rebuild = cls.patcher[start:cls.patcher.index("mt_battle_enhanced_difficulty_plan_raw", start)]

    def test_every_key_the_world_writes_into_the_plan_is_read_back(self) -> None:
        """THE FENCE. Derived from what `__init__.py` actually writes, so a key added there later and not
        here fails the suite instead of being dropped in silence."""
        written = set(re.findall(r'enhanced_difficulty_plan\["([a-z_]+)"\]', self.world))
        self.assertIn("shadow_level_assignment", written, "the world must still build this")
        for key in written:
            self.assertIn(f'"{key}"', self.rebuild,
                          f"__init__.py writes {key!r} into the plan but apply_patch's rebuild drops it")

    def test_the_shadow_levels_are_coerced_to_int_keys(self) -> None:
        """JSON keys come back as strings, and `apply_shadow_level_boost`'s bounds check compares to ints."""
        self.assertRegex(
            self.rebuild,
            r'"shadow_level_assignment":\s*\{\s*\n?\s*int\(k\):\s*int\(v\)',
        )

    def test_a_seed_without_the_key_still_patches(self) -> None:
        """Every seed generated before ADDENDUM 198 lacks it entirely; absent must mean 'no shadow levels',
        never a KeyError partway through a patch that has already begun writing."""
        self.assertIn('enhanced_difficulty_plan_raw.get("shadow_level_assignment") or {}', self.rebuild)


class TestTheWriteReachesTheCopyTheGameReads(unittest.TestCase):
    """BUG 2. ADDENDUM 58's finding, applied to the second writer of the same byte."""

    @classmethod
    def setUpClass(cls) -> None:
        source = _source("tools/iso_patcher.py")
        start = source.index("def write_enhanced_difficulty_patch")
        cls.body = source[start:source.index("\ndef ", start + 1)]
        cls.source = source

    def test_it_writes_common_fsys_as_well_as_deck_archive(self) -> None:
        self.assertIn('find_by_basename(fst2, "common.fsys")', self.body)
        self.assertIn('find_by_basename(fst, "deck_archive.fsys")', self.body)

    def test_it_writes_both_common_fsys_copies(self) -> None:
        for name in ("DeckData_DarkPokemon.bin", "DeckData_DarkPokemon_EU.bin"):
            self.assertIn(name, self.body, name)

    def test_it_refuses_an_unexpected_disc_layout_rather_than_guessing(self) -> None:
        self.assertIn("refusing to guess at a ", self.body)
        self.assertIn("different disc layout", self.body)

    def test_it_reports_what_it_wrote_to_the_second_container(self) -> None:
        self.assertIn("shadow_levels_written_common_fsys", self.body)

    def test_it_does_nothing_at_all_when_there_are_no_shadow_levels(self) -> None:
        """A plan with no Shadow half must not open, decompress and re-encode common.fsys for nothing --
        that file is the slowest thing this pipeline touches."""
        self.assertIn("if shadow_levels:", self.body)

    def test_both_ddpk_writers_agree_about_the_container_count(self) -> None:
        """The relationship, not one function's text: whatever writes a DDPK byte writes three copies."""
        for name in ("def write_enhanced_difficulty_patch", "def write_shadow_multi_trainer_patch"):
            start = self.source.index(name)
            body = self.source[start:self.source.index("\ndef ", start + 1)]
            self.assertIn("common.fsys", body, f"{name} writes a DDPK byte into only one container")

    def test_the_docstring_no_longer_asserts_the_claim_that_caused_this(self) -> None:
        """The sentence that caused this. It was true once; a docstring that stopped being true is how the
        second container got forgotten. It is allowed to survive only as QUOTED history -- if it is ever
        stated as fact again, this fails."""
        claim = "there is no second container to keep in sync"
        if claim in self.body:
            head = self.body[:self.body.index(claim)]
            self.assertIn("It used to say", head,
                          "that claim is stated as fact again; it has been false since ADDENDUM 198")


class TestTheTwoGatesAgree(unittest.TestCase):
    """BUG 3. `generate_early` claims to share `generate_output`'s gate. Compare them rather than trust it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.world = _source("__init__.py")

    def test_the_early_shadow_gate_includes_path_level_scaling(self) -> None:
        start = self.world.index("if shadow_pool is not None:")
        body = self.world[start:start + 4000]
        self.assertIn("path_level_scaling", body,
                      "the Shadow relevel gate must move when generate_output()'s does")

    def test_both_gates_turn_on_the_same_three_things(self) -> None:
        """The two gates are written differently -- `generate_output` pre-computes booleans, `generate_early`
        reads the options inline -- so this compares what they MEAN rather than their text: three disjuncts
        each, covering team padding, ED level scaling and path scaling."""
        early_start = self.world.index("if shadow_pool is not None:")
        early = self.world[early_start:early_start + 4500]
        for option in ("enhanced_difficulty.value", "enhanced_difficulty_level_scaling", "path_level_scaling"):
            self.assertIn(option, early, f"generate_early's Shadow gate does not consider {option}")

        out_start = self.world.index("path_scale_levels = bool(self.options.path_level_scaling)")
        gate = self.world[out_start:out_start + 300]
        for name in ("ed_added_members", "ed_scale_levels", "path_scale_levels"):
            self.assertIn(name, gate, f"generate_output's gate does not consider {name}")
        self.assertEqual(2, gate.count(" or "), "both gates must be a three-way disjunction")

    def test_the_early_pass_uses_the_path_team_average_when_path_scaling_is_on(self) -> None:
        """`shadow_level_assignment` joins on the trainer's team average, so feeding it the VANILLA average
        while the seed fields the path one evolves the species against a level nobody will ever see."""
        start = self.world.index("if shadow_pool is not None:")
        body = self.world[start:start + 4000]
        self.assertIn("build_path_level_plan", body)
        self.assertIn('"team_avg_level"', body)

    def test_the_multiplier_is_not_applied_twice(self) -> None:
        start = self.world.index("if shadow_pool is not None:")
        body = self.world[start:start + 4000]
        self.assertIn("_ed_scale and not _path_scale", body)


class TestTheDamageThisCaused(unittest.TestCase):
    """The arithmetic, against the real vanilla Shadow census, so the size of the bug is on record."""

    @classmethod
    def setUpClass(cls) -> None:
        path = ROOT / "data" / "deckdata_dark_pokemon.json"
        if not path.exists():
            raise unittest.SkipTest("deckdata_dark_pokemon.json not available")
        cls.dark = json.loads(path.read_text(encoding="utf-8"))

    def test_every_vanilla_shadow_has_a_level_worth_moving(self) -> None:
        levels = [row["shadow_level"] for row in self.dark]
        self.assertEqual(83, len(levels))
        self.assertLessEqual(min(levels), 11)
        self.assertGreaterEqual(max(levels), 50)

    def test_the_gap_a_path_scaled_seed_opened(self) -> None:
        """Re-derived rather than asserted from memory. A Shadow left at its vanilla level in a seed whose
        ramp ends at 65 is the reported symptom, and this measures how far apart the two halves got."""
        from ..game_data.real_trainer_data import real_shadow_census, real_trainer_team_census
        from ..randomizer.enhanced_difficulty import shadow_level_assignment
        from ..randomizer.path_level_scaling import build_path_level_plan

        census = real_shadow_census()
        team = real_trainer_team_census()
        if not census or not team:
            self.skipTest("census data not available in this build")
        _, by_trainer = build_path_level_plan(team)
        scaled = [{**row, "team_avg_level": float(by_trainer[row["trainer_index"]])}
                  if row.get("trainer_index") in by_trainer else row for row in census]
        _, ddpk_levels = shadow_level_assignment(scaled, scale_levels=False)
        vanilla = {row["ddpk_index"]: row["shadow_level"] for row in self.dark}
        gaps = [ddpk_levels[i] - vanilla[i] for i in ddpk_levels if i in vanilla]
        self.assertTrue(gaps)
        # RETARGETED (ADDENDUM 315): was 25. The biggest gap used to be a Sixes Shadow matched to the wrong
        # holder (its level-50 rematch tail) on top of the path ramp; with the attribution fixed the largest
        # honest divergence is 17 levels, which is still "tens of levels" for what this test is about -- a
        # Shadow shipped at its vanilla level inside a re-levelled area.
        self.assertGreater(max(gaps), 10, "the two halves really did diverge by tens of levels")

    def test_a_shadow_at_its_vanilla_level_is_frail_enough_to_be_two_hit(self) -> None:
        """The player's own report, as arithmetic. Metagross's base HP is 80; the Gen III formula with the
        zero IVs and EVs every vanilla trainer Pokemon has gives it 54 HP at level 17 and 179 at level 65."""
        from ..game_data.species_base_hp import base_hp, max_hp
        metagross = base_hp(376)
        if metagross is None:
            self.skipTest("base HP census not available in this build")
        self.assertEqual(80, metagross)
        self.assertLess(max_hp(metagross, 17, 0, 0), 60)
        self.assertGreater(max_hp(metagross, 65, 0, 0), 170)


if __name__ == "__main__":
    unittest.main()
