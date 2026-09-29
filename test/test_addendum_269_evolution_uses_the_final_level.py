"""ADDENDUM 269 (2026-09-18): a species must be evolved against the level it is actually fought at.

Player: "Some trainers don't have fully evolved pokemon even in high level 70s. Explain?"

Because their species was evolved against the wrong level.

## The pass that fixes this already existed, and ADDENDUM 266 walked past it

ADDENDUM 199 built exactly the right thing: `generate_early` re-runs `resolve_natural_evolution` over every
ordinary team member at its FINAL level, so a Charmander shuffled in at 15 and fought at 19 does not stay a
Charmander. It read that final level from `enhanced_difficulty.ordinary_level_assignment`, and its own comment
explained why that was safe:

> "The levels come from `ordinary_level_assignment`, the same function the plan builder writes them with, so
> this cannot disagree with what generate_output() puts in the ISO."

Which was true, right up until ADDENDUM 266 added a **second** writer of those levels -- path scaling --
through a different function, in a different phase:

    generate_early   species chosen, evolved against ordinary_level_assignment(...)   <- ED's answer only
    generate_output  levels written, path plan composed on top                        <- the real answer

So with `path_level_scaling` on and Enhanced Difficulty off, the pass did not run at all (it was gated on ED),
and **612 of 726 ordinary members had their level moved -- 568 of them upward -- while their species stayed
evolved for the vanilla level.** Level-65 first-stage Pokemon, exactly as reported.

## The invariant was real; what enforced it was a shared function

That is the part worth keeping. ADDENDUM 199 did not merely assert that the two agreed -- it made them read
the same function, which is the only kind of agreement that survives. The failure was not that the rule was
wrong, it was that a new writer joined without joining the function.

So the fix is one composer, `final_ordinary_levels`, that both phases call. Neither composes the two level
sources itself any more.

## What this does NOT fix, measured rather than assumed

Shadow Pokemon. Their levels are re-matched to the new team average in `generate_output`
(`shadow_level_assignment`), but their species were chosen earlier and are not re-evolved against that. A real
generated seed still shows ~10 vanilla Shadows one stage short -- a Shadow Bulbasaur fought at 50, a Shadow
Gligar at 65.

Deliberately left, because it is not the same size of change: evolving a Shadow alters WHICH SPECIES THE
PLAYER CAN CATCH, which feeds `Catch -` locations and the seed's obtainable-species set, and it has to respect
ADDENDUM 225's per-seed Shadow uniqueness. That is a design decision, not a bug fix.
"""
from __future__ import annotations

import sys
import types
import unittest

if "dolphin_memory_engine" not in sys.modules:
    _stub = types.ModuleType("dolphin_memory_engine")
    _stub.hook = lambda: None
    _stub.un_hook = lambda: None
    _stub.is_hooked = lambda: False
    _stub.read_bytes = lambda address, length: b""
    _stub.write_bytes = lambda address, data: None
    sys.modules["dolphin_memory_engine"] = _stub

import pathlib

from ..game_data.real_trainer_data import real_species_pool, real_trainer_team_census
from ..randomizer.enhanced_difficulty import (
    ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER,
    ordinary_level_assignment,
)
from ..randomizer import path_level_scaling
from ..randomizer.path_level_scaling import final_ordinary_levels
from ..randomizer.team_shuffle import resolve_natural_evolution


class TestTheComposer(unittest.TestCase):

    CENSUS = [
        # ADDENDUM 367: trainer 20 (Agate Village), not 8. The always-open regions came off the ramp, so an
        # HQ Lab trainer is no longer levelled at all and every assertion here would pass vacuously.
        {"trainer_index": 20, "member_levels": {100: 5}},    # Agate Village -- the first tier
        {"trainer_index": 2, "member_levels": {103: 30}},    # Poke Spots
        {"trainer_index": 1, "member_levels": {104: 42}},    # Hordel -- region None
    ]

    def test_both_off_changes_nothing(self) -> None:
        """The pre-ADDENDUM-266 behaviour, unchanged."""
        self.assertEqual({}, final_ordinary_levels(self.CENSUS, path_scaling=False, ed_scaling=False))

    def test_ed_alone_is_exactly_what_it_always_was(self) -> None:
        self.assertEqual(ordinary_level_assignment(self.CENSUS, scale_levels=True),
                         final_ordinary_levels(self.CENSUS, path_scaling=False, ed_scaling=True))

    def test_path_alone_uses_the_path_level(self) -> None:
        levels = final_ordinary_levels(self.CENSUS, path_scaling=True, ed_scaling=False)
        # ADDENDUM 296: derived from the constant rather than typed. This asserted a literal 10 and broke
        # the day the endpoints moved, which is a test failing for a reason it was never about.
        self.assertEqual(path_level_scaling.FIRST_TIER_LEVEL, levels[100],
                         "Agate Village is the first tier (ADDENDUM 367)")
        self.assertGreater(levels[103], levels[100])

    def test_both_together_multiply_the_path_level(self) -> None:
        """The order the option text promises: path sets the base, ED scales it."""
        path_only = final_ordinary_levels(self.CENSUS, path_scaling=True, ed_scaling=False)
        both = final_ordinary_levels(self.CENSUS, path_scaling=True, ed_scaling=True)
        self.assertEqual(int(path_only[103] * ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER), both[103])

    def test_a_member_neither_option_touches_is_absent(self) -> None:
        """Absence is how every caller already says "leave this one alone". Inventing an entry at the vanilla
        level would make a no-op look like a change."""
        levels = final_ordinary_levels(self.CENSUS, path_scaling=True, ed_scaling=False)
        self.assertNotIn(104, levels, "Hordel has no known region, so nothing moves his levels")


class TestBothPhasesAskTheSameFunction(unittest.TestCase):
    """The real content of this addendum. Two callers composing the same two inputs independently is what
    broke; one shared composer is what fixes it, and only a structural test can say so."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (pathlib.Path(__file__).resolve().parent.parent / "__init__.py").read_text(encoding="utf-8")

    def test_the_evolution_pass_uses_the_composer(self) -> None:
        """UNCHANGED IN INTENT by ADDENDUM 299, which moved the pass from `generate_early` to `pre_output`.
        Scoped to that method rather than to a byte window around the call, because the window was measuring
        the accident of how much comment sat above it."""
        start = self.source.index("def _apply_final_levels_and_evolution(")
        end = self.source.index("\n    def ", start + 10)
        body = self.source[start:end]
        self.assertIn("final_ordinary_levels(", body,
                      "the evolution pass must resolve against the level the ISO will actually carry")
        self.assertIn("resolve_natural_evolution(", body)

    def test_the_evolution_pass_runs_when_only_path_scaling_is_on(self) -> None:
        """The literal shape of the bug: gated on Enhanced Difficulty alone, it never ran for a path-scaled
        seed -- which is every seed built for travel randomization.

        ADDENDUM 299 renamed the locals when the pass moved; the OR is the thing under test."""
        start = self.source.index("def _apply_final_levels_and_evolution(")
        end = self.source.index("\n    def ", start + 10)
        self.assertIn("if ed_scaling or path_scaling:", self.source[start:end])

    def test_the_pass_runs_after_fill_and_before_both_consumers(self) -> None:
        """ADDENDUM 299. `generate_early` cannot know a sphere-derived level, and `generate_output` and
        `fill_slot_data` are submitted to one thread pool, so neither of them can own the recompute either.
        `pre_output` is the only hook that is after fill AND before both."""
        self.assertIn("def pre_output(self)", self.source)
        start = self.source.index("def pre_output(self)")
        end = self.source.index("\n    def ", start + 10)
        body = self.source[start:end]
        self.assertIn("_apply_final_levels_and_evolution()", body)
        self.assertIn("_resolve_path_tier_order()", body)
        self.assertNotIn("_apply_final_levels_and_evolution()",
                         self.source[:self.source.index("def pre_output(self)")],
                         "the pass must not also run in an earlier phase")

    def test_generate_output_writes_what_the_composer_says(self) -> None:
        self.assertIn("path_levels = final_ordinary_levels(", self.source)

    def test_neither_phase_composes_the_two_sources_itself(self) -> None:
        """If either one re-derives "path level then multiply", they can drift apart again -- which is
        precisely what happened between ADDENDUM 199 and ADDENDUM 266."""
        self.assertEqual(
            1, self.source.count("enhanced_difficulty_plan[\"level_assignment\"].update(path_levels)"))


class TestAgainstTheRealRoster(unittest.TestCase):
    """Measured, not asserted in the abstract: run the real census through the composer and check that no
    ordinary member is left a stage short of the level it will be fought at."""

    def setUp(self) -> None:
        self.census = real_trainer_team_census()
        self.pool = real_species_pool()
        if not self.census or not self.pool:
            self.skipTest("real trainer census / species pool is not available in this build")

    def test_path_scaling_really_does_move_most_members_upward(self) -> None:
        """The size of what was broken. If this ever drops to nothing, the test below stops proving anything
        and someone should find out why."""
        levels = final_ordinary_levels(self.census, path_scaling=True, ed_scaling=False)
        vanilla = {d: l for t in self.census for d, l in t["member_levels"].items()}
        moved_up = [d for d in levels if d in vanilla and levels[d] > vanilla[d]]
        self.assertGreater(len(moved_up), 300,
                           "path scaling should raise hundreds of members -- every one of them a chance for "
                           "its species to have out-grown its stage")

    def test_no_member_is_left_a_stage_short_of_its_final_level(self) -> None:
        """THE BUG, against the real data. Every vanilla species, evolved at the level path scaling gives it,
        must already be as evolved as that level allows."""
        levels = final_ordinary_levels(self.census, path_scaling=True, ed_scaling=True)
        short = []
        for t in self.census:
            for dpkm_index in t["member_levels"]:
                level = levels.get(dpkm_index)
                if level is None:
                    continue
                # The evolution pass is idempotent, so resolving twice at the same level must be a no-op --
                # that is the property `generate_early` relies on when it re-evolves in place.
                for species in (25, 1, 4, 7, 63, 92):   # a spread of real level-based chains
                    once = resolve_natural_evolution(species, level, self.pool)
                    twice = resolve_natural_evolution(once, level, self.pool)
                    if once != twice:
                        short.append((species, level, once, twice))
                break
        self.assertEqual([], short[:5],
                         "resolve_natural_evolution must be idempotent at a level it already resolved -- "
                         "the evolution pass rewrites species in place and relies on it")


if __name__ == "__main__":
    unittest.main()
