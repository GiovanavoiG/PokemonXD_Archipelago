"""
ADDENDUM 295 (2026-09-20) -- a tier is where the team SITS, not what every member IS.

Player: *"Can we revisit the path level scaling? Seems to just be following vanilla."* and, in the same
breath, the fix: *"Equate our scaled level to that trainer's average - for each level on their team above or
below the average, make it that many above or below our scaled level. This still gives trainers level variety
despite being scaled."*

## What the ramp was doing, measured before changing anything

Against the real 227-trainer census, with `path_level_scaling` on and Enhanced Difficulty off:

* **612 of 726 team members re-levelled**, 567 of them upward, mean delta **+14.9**.
* The seed's `enhanced_difficulty_plan.level_assignment` carried **695** entries (612 path + 83 Shadow) and
  the `.appxd` contained it.

So the ramp was not following vanilla, and the plan was reaching the seed file. What it *was* doing is
flattening: `build_path_level_plan` wrote the tier's level to **every** member of a trainer's team, so the
whole game came out on twelve distinct numbers. A Cipher Lab team the disc fields as 10/11/10 arrived as
25/25/25.

## Why that reads as "vanilla" even though the numbers moved

Two things at once, and only the second is a defect:

1. **The early tiers sit close to vanilla by arithmetic.** Tier 1 is level 10 and tier 2 is 15, and the
   unmodified game's opening hours run 5–15. A player early in a run is looking at numbers the ramp and the
   vanilla curve happen to agree on. That is the ramp working as specified — the player chose 10 → 65.
2. **Flattening removes the one cue that says anything changed.** Vanilla teams have shape — an ace a level
   or two above the rest. A row of identical numbers is the single most visible tell that a mod touched the
   levels, and the old ramp deleted it, leaving a team that was *both* near-vanilla in magnitude *and*
   featureless. Nothing about it announced itself.

## What this addendum does

The offset is measured against the team's own vanilla average, which is the only baseline that makes the
arithmetic mean out: 23/25/28 against a mean of 25.33 is −2.33/−0.33/+2.67, and at a tier of 40 that is
38/40/43. The spread is preserved exactly, the team still lands where the path says, and **every number out
is a number the disc's own data already implied** — nothing is invented.

Measured after: **12 distinct planned levels became 38**, the mean delta is unchanged at +14.9 (the ramp's
placement did not move, only its shape), and the same Cipher Lab team now arrives as 25/26/25.

## The returned average is now measured rather than asserted

`build_path_level_plan`'s second return value exists so `enhanced_difficulty.shadow_level_assignment` can
re-match a Shadow to its trainer's team average. It used to be the tier — true, because every member *was*
the tier. It is not true now: rounding each offset independently and clamping at the ends can move the real
mean a fraction off. So it is computed from the levels actually assigned. A Shadow matched to a number no
member of its team holds is the same class of disagreement ADDENDUM 287 spent an addendum on.

## What this does NOT fix, stated plainly

Vanilla XD teams are *themselves* nearly flat — Cipher Lab's are 10/11/10 and 9/9/9/8/9, so the recovered
spread is usually ±1 and at most ±2 in the early game. This gives back exactly the variety the source data
has and not one level more. If the wanted feel is wider than that, the lever is a multiplier on the offset,
and that is a design decision rather than a bug fix.
"""
from __future__ import annotations

import unittest

from ..game_data.real_trainer_data import real_trainer_team_census
from ..randomizer.path_level_scaling import (
    FIRST_TIER_LEVEL,
    LAST_TIER_LEVEL,
    MAX_LEVEL,
    MIN_LEVEL,
    PINNED_TRAINER_LEVELS,
    _spread_over_team,
    build_mt_battle_path_level_plan,
    build_path_level_plan,
    describe,
)


class TestTheSpreadItself(unittest.TestCase):
    def test_it_places_the_average_at_the_tier_and_keeps_every_offset(self) -> None:
        """The player's sentence, as arithmetic. Mean 25.33; offsets -2.33/-0.33/+2.67 onto a tier of 40."""
        out = _spread_over_team(40, {1: 23, 2: 25, 3: 28})
        self.assertEqual(out, {1: 38, 2: 40, 3: 43})
        self.assertAlmostEqual(sum(out.values()) / 3, 40.33, places=2)

    def test_a_flat_team_stays_flat(self) -> None:
        self.assertEqual(_spread_over_team(30, {1: 9, 2: 9, 3: 9}), {1: 30, 2: 30, 3: 30})

    def test_an_odd_span_is_not_collapsed_by_bankers_rounding(self) -> None:
        """The bug this test suite found on its own first run. Python's `round()` rounds halves to EVEN, so
        vanilla 9/10 at a tier of 20 gives 19.5 and 20.5 and `round()` answers 20 for both -- flattening the
        team, which is the one thing this addendum exists to stop. Most two-member teams in this game have an
        odd span, so it was not an edge case."""
        self.assertEqual(_spread_over_team(20, {1: 9, 2: 10}), {1: 20, 2: 21})
        self.assertEqual(_spread_over_team(30, {1: 4, 2: 5, 3: 6, 4: 7}), {1: 29, 2: 30, 3: 31, 4: 32})

    def test_a_one_member_team_is_unchanged_by_construction(self) -> None:
        """Worth pinning because most of the early game is one-member teams: the spread costs nothing there
        rather than needing a special case."""
        for vanilla in (1, 5, 50, 100):
            self.assertEqual(_spread_over_team(17, {9: vanilla}), {9: 17})

    def test_the_gap_between_members_is_preserved_exactly(self) -> None:
        out = _spread_over_team(50, {1: 10, 2: 14})
        self.assertEqual(max(out.values()) - min(out.values()), 4)

    def test_it_clamps_rather_than_running_off_either_end(self) -> None:
        low = _spread_over_team(FIRST_TIER_LEVEL, {1: 1, 2: 99})
        self.assertGreaterEqual(min(low.values()), MIN_LEVEL)
        high = _spread_over_team(LAST_TIER_LEVEL, {1: 1, 2: 99})
        self.assertLessEqual(max(high.values()), MAX_LEVEL)

    def test_an_empty_team_is_empty(self) -> None:
        self.assertEqual(_spread_over_team(40, {}), {})


class TestAgainstTheRealCensus(unittest.TestCase):
    """The measurements in this file's docstring, as assertions, against the real 227-trainer census."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.census = real_trainer_team_census()
        cls.vanilla = {}
        cls.team = {}
        for row in cls.census:
            members = {int(k): int(v) for k, v in (row.get("member_levels") or {}).items()}
            cls.team[row["trainer_index"]] = members
            cls.vanilla.update(members)
        cls.levels, cls.averages = build_path_level_plan(cls.census)

    def test_the_census_is_really_there(self) -> None:
        """A vacuously-passing version of every test below is the failure mode that matters most here."""
        self.assertGreater(len(self.census), 200)
        self.assertGreater(len(self.levels), 500)

    def test_the_ramp_is_not_following_vanilla(self) -> None:
        """The player's report, tested directly. It was not true before this addendum either -- the mean
        delta is unchanged by the spread, which is the point: placement did not move, shape did."""
        deltas = [self.levels[d] - self.vanilla[d] for d in self.levels]
        # ADDENDUM 296 lowered the ramp from 10-65 to 8-50, which took the mean delta from +14.9 to +5.9.
        # The threshold moved with it and is deliberately well below the measured value: this test is "the
        # ramp is not vanilla", not "the ramp is exactly this steep", and pinning the steepness here would
        # make every future balance decision look like a regression.
        self.assertGreater(sum(deltas) / len(deltas), 3.0)
        # ADDENDUM 296: 5% became 15%, because the measured figure went from 0.2% to 6.7% when the ramp
        # dropped to 8-50. That rise is not a fault, it is arithmetic -- a gentler ramp passes closer to the
        # vanilla curve, so more members coincide with where they already were. Worth knowing when judging
        # "it feels vanilla": at these endpoints about one team member in fifteen genuinely IS its vanilla
        # level, by coincidence rather than by anything failing to apply.
        self.assertLess(sum(1 for d in deltas if d == 0) / len(deltas), 0.15,
                        "almost nothing should land back on its vanilla level")

    def test_teams_are_no_longer_flat(self) -> None:
        """THE REGRESSION. Before this addendum every member of a team got the tier's level, so the whole
        game came out on twelve distinct numbers."""
        distinct = len(set(self.levels.values()))
        self.assertGreater(distinct, 25,
                           "the plan is back to one level per tier -- the spread is not being applied")
        varied = [t for t, members in self.team.items()
                  if len(set(members.values())) > 1
                  and all(d in self.levels for d in members)]
        self.assertTrue(varied, "no multi-level team in the census -- this test proves nothing")
        kept = [t for t in varied if len({self.levels[d] for d in self.team[t]}) > 1]
        self.assertGreater(len(kept) / len(varied), 0.9,
                           "teams that had internal variety in vanilla must keep it")

    def test_every_team_keeps_its_exact_vanilla_span(self) -> None:
        """Rounding may move a member by one, but the difference between the highest and lowest member is
        the shape of the team and must survive."""
        for trainer_index, members in self.team.items():
            if not members or not all(d in self.levels for d in members):
                continue
            if trainer_index in PINNED_TRAINER_LEVELS:
                continue
            new = [self.levels[d] for d in members]
            if min(new) > MIN_LEVEL and max(new) < MAX_LEVEL:   # unclamped teams only
                self.assertEqual(
                    max(new) - min(new), max(members.values()) - min(members.values()),
                    f"trainer {trainer_index} changed shape: {sorted(members.values())} -> {sorted(new)}",
                )

    def test_the_reported_average_is_the_one_actually_assigned(self) -> None:
        """It used to be the tier, which was true only while every member WAS the tier. A Shadow is matched
        to this number, so it has to be a number the team really holds."""
        for trainer_index, average in self.averages.items():
            members = self.team.get(trainer_index) or {}
            assigned = [self.levels[d] for d in members if d in self.levels]
            self.assertTrue(assigned)
            self.assertAlmostEqual(average, sum(assigned) / len(assigned), places=6)

    def test_a_pinned_trainer_is_still_flat_and_still_pinned(self) -> None:
        """A pin is a single number for that fight, not a band centred on one -- the player's words for
        Chobin #1 were "always level 5"."""
        for trainer_index, pinned in PINNED_TRAINER_LEVELS.items():
            members = self.team.get(trainer_index) or {}
            if not members:
                continue
            self.assertEqual({self.levels[d] for d in members}, {pinned})

    def test_trainers_with_no_placement_are_still_absent(self) -> None:
        """Absence is how the patcher is told to leave a trainer alone. 36 trainers have no region -- 30 of
        them the postgame Orre Colosseum block, deliberately out of logic since ADDENDUM 185."""
        untouched = {d for d in self.vanilla if d not in self.levels}
        self.assertGreater(len(untouched), 50)
        self.assertLess(len(untouched), 200)


class TestMtBattleGotTheSameTreatment(unittest.TestCase):
    def test_its_teams_keep_their_shape_too(self) -> None:
        """Mt. Battle already varies BETWEEN trainers, which made it easy to argue it needed nothing -- but a
        hundred teams of identical numbers is the same flatness, and a per-trainer climb is not a substitute
        for the shape a team came with."""
        census = [
            {"trainer_index": 1, "member_levels": {10: 5, 11: 7}},
            {"trainer_index": 100, "member_levels": {20: 40, 21: 44, 22: 42}},
        ]
        levels, averages = build_mt_battle_path_level_plan(census)
        self.assertEqual(levels[11] - levels[10], 2)
        self.assertEqual(max(levels[20], levels[21], levels[22]) - min(levels[20], levels[21], levels[22]), 4)
        self.assertLess(averages[1], averages[100], "the 1-to-100 ramp still climbs")

    def test_an_empty_census_is_still_empty(self) -> None:
        self.assertEqual(build_mt_battle_path_level_plan([]), ({}, {}))


class TestTheSeedNoteExplainsIt(unittest.TestCase):
    def test_the_ramp_description_says_the_tier_is_an_average(self) -> None:
        """This list goes into the seed notes. A reader seeing "level 40" beside a team of 38/40/43 should
        find the explanation in the same place as the number."""
        text = "\n".join(describe())
        self.assertIn("average", text)
        # The worked example in the note has to be a tier that really exists and the numbers the code really
        # produces, or the note teaches something the seed does not do. Derived, not typed.
        from ..randomizer.path_level_scaling import _spread_over_team, level_for_tier
        tier = level_for_tier(8, 12)
        spread = _spread_over_team(tier, {1: 23, 2: 25, 3: 28})
        self.assertIn("/".join(str(spread[k]) for k in (1, 2, 3)), text)
        self.assertIn(f"level-{tier} tier", text)


if __name__ == "__main__":
    unittest.main()
