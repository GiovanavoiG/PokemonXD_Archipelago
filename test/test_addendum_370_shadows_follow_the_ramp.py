"""ADDENDA 370/371 (2026-09-27): Shadows follow the ramp, and the Lair's floor is 0x67.

Player: *"Apparently many trainers shadows are not matched to their team level at all. Please investigate. Also,
make the key lair floor 0x67 by default."*

ADDENDUM 370 -- WHAT WAS WRONG, measured on their seed (AP_84192203482497242093; path scaling on, ED off)
before anything was changed. `max(tier_level, vanilla_shadow_level)` predicted 76 of the 76 checkable shipped
Shadow levels, and 57 of the 83 Shadows had the vanilla half win:

    Cipher Key Lair   tier  2/13 -> level 12   team shipped 11-13   Shadows shipped 28-34
    Citadark Isle     tier  8/13 -> level 33   team shipped 31-34   Shadows shipped 38-50
    Phenac City       tier  3/13 -> level 15   team shipped 14-16   Shadows shipped 20-25

THE CAUSE IS ADDENDUM 317'S VANILLA FLOOR, APPLIED WHERE IT DOES NOT BELONG. Under Enhanced Difficulty a
Shadow's base is its trainer's own VANILLA team average, and "never below the unmodified game's Shadow" is a
sensible bound on that -- none of 317 is being revisited. Under path scaling the base is the region's TIER
LEVEL, which the ramp is explicitly allowed to put far below vanilla: ADDENDUM 296 capped it at 50 and floored
it at 8 so that a late area handed out early is survivable. Flooring a tier level at vanilla does not protect a
Shadow from being too weak; it discards the ramp and leaves a level-28 Shadow on a level-12 team, which is the
inverse of the bug path scaling exists to prevent.

SO THE FLOOR ASKS WHERE THE BASE CAME FROM, per record. `generate_output` marks the records it re-bases with
`"level_source": "path"`; those skip the floor, everything else keeps 317 exactly. Per-record because both
populations live in one census -- the nine teamless Shadows and any trainer with no known region are never in
the path plan and still want the floor.

AND THE SEED NOTE WAS PART OF THE BUG. `describe_resolution` reported the holder's VANILLA team average ("team
avg 11.5" for a Cipher Lab Shadow in a seed whose Cipher Lab tier was 40), because a ShadowHolder knows no
other number. So the notes described a level nobody was writing and the bug looked fine on paper. It now states
the level actually assigned, which is the property that found ADDENDUM 315.

ADDENDUM 371 -- the floor the player asked for conditionally on 2026-09-26 and unconditionally a day later. The
value moves from `AREA_FLOOR_RULES` to `AREA_ENTRY_FLOOR_OVERRIDES`; see `test_addendum_364_*`, retargeted, for
why 0x67 is the right rung, and the override's own comment for what it costs at Zook #2.
"""
from __future__ import annotations

import pathlib
import unittest

from .. import ram_client as rc
from ..game_data import (missable_trainers as mt, real_trainer_data as rtd, shadow_holders as sh,
                         story_bytes as sb, trainer_placements as tp)
from ..randomizer import enhanced_difficulty as ed
from ..randomizer import path_level_scaling as pls

LAIR = "Cipher Key Lair"


def _record(**kw):
    base = {"ddpk_index": 1, "dpkm_index": 10, "trainer_index": 34, "shadow_level": 28, "team_avg_level": 12.0}
    base.update(kw)
    return base


class TestTheFloorOnlyAppliesToAnAverage(unittest.TestCase):
    def test_a_path_based_base_below_vanilla_is_used_as_is(self) -> None:
        """The reported bug, as one record. A Key Lair Shadow whose vanilla level is 28 on a ramp tier of 12."""
        dpkm, ddpk = ed.shadow_level_assignment(
            [_record(level_source="path", team_avg_level=12.0, shadow_level=28)], scale_levels=False)
        self.assertEqual({10: 12}, dpkm)
        self.assertEqual({1: 12}, ddpk)

    def test_the_same_record_without_the_mark_keeps_addendum_317(self) -> None:
        """The control. Identical numbers, no `level_source`, and the vanilla floor still wins -- so this is a
        narrowing of 317's scope and not a repeal of it."""
        _dpkm, ddpk = ed.shadow_level_assignment(
            [_record(team_avg_level=12.0, shadow_level=28)], scale_levels=False)
        self.assertEqual({1: 28}, ddpk)

    def test_a_path_base_above_vanilla_is_unaffected_either_way(self) -> None:
        """Matching UP was never in question, and 43 of the seed's 83 Shadows were in this case -- which is why
        the bug looked like "many" rather than "all"."""
        for source in ({}, {"level_source": "path"}):
            _dpkm, ddpk = ed.shadow_level_assignment(
                [_record(team_avg_level=40.0, shadow_level=17, **source)], scale_levels=False)
            self.assertEqual({1: 40}, ddpk, source)

    def test_a_teamless_shadow_still_keeps_its_own_level(self) -> None:
        """Nine Shadows have no ordinary team member to average. They are not in the path plan, get no mark, and
        fall back to their own level exactly as before."""
        _dpkm, ddpk = ed.shadow_level_assignment(
            [_record(team_avg_level=None, shadow_level=30)], scale_levels=False)
        self.assertEqual({1: 30}, ddpk)

    def test_the_multiplier_still_composes_the_same_way(self) -> None:
        """ADDENDUM 317's other half: the floor is applied to the base BEFORE scaling, so one rule cannot
        produce 22 while the other produces 11. With the mark the base is the ramp's, then scaled."""
        _dpkm, floored = ed.shadow_level_assignment(
            [_record(team_avg_level=12.0, shadow_level=28)], scale_levels=True)
        _dpkm, ramped = ed.shadow_level_assignment(
            [_record(team_avg_level=12.0, shadow_level=28, level_source="path")], scale_levels=True)
        self.assertEqual(floored[1], ed._scaled_level(28, ed.ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER))
        self.assertEqual(ramped[1], ed._scaled_level(12, ed.ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER))


class TestTheWholeCensusUnderTheRamp(unittest.TestCase):
    """The end-to-end shape, over the real 83-Shadow census rather than a fixture."""

    def setUp(self) -> None:
        self.census = rtd.real_shadow_census()
        self.by_trainer = pls.level_by_trainer_index()

    def _assign(self, mark: bool) -> "dict[int, int]":
        rows = []
        for record in self.census:
            index = record.get("trainer_index")
            if index in self.by_trainer:
                row = {**record, "team_avg_level": float(self.by_trainer[index])}
                if mark:
                    row["level_source"] = "path"
                rows.append(row)
            else:
                rows.append(record)
        return ed.shadow_level_assignment(rows, scale_levels=False)[1]

    def test_every_placed_shadow_lands_on_its_regions_tier_level(self) -> None:
        assigned = self._assign(mark=True)
        checked = 0
        for record in self.census:
            index, ddpk = record.get("trainer_index"), record.get("ddpk_index")
            if index not in self.by_trainer or ddpk not in assigned:
                continue
            self.assertEqual(self.by_trainer[index], assigned[ddpk],
                             f"ddpk {ddpk} on trainer {index} ({tp.PLACEMENTS[index].region})")
            checked += 1
        self.assertGreater(checked, 60, "the census stopped covering the population this is about")

    def test_the_bug_is_reproducible_by_dropping_the_mark(self) -> None:
        """A probe rather than a claim: without `level_source` the census diverges, and every divergence is
        upward, which is the direction the player reported.

        On the INTENDED path the damage is small -- each region's tier is roughly where its vanilla levels
        already were, which is why this went unnoticed for so long. `TestTheReportedSeed` below runs the same
        probe on the ordering the player's seed actually had."""
        fixed, broken = self._assign(mark=True), self._assign(mark=False)
        differ = {ddpk for ddpk in fixed if fixed[ddpk] != broken[ddpk]}
        self.assertTrue(differ, "the floor no longer changes any level, so the fix is untested here")
        for ddpk in differ:
            self.assertGreater(broken[ddpk], fixed[ddpk], f"ddpk {ddpk} diverged downward, which is not the bug")


class TestTheReportedSeed(unittest.TestCase):
    """The seed the report came from, replayed as data: AP_84192203482497242093, travel shuffle on, whose own
    sphere ordering put Citadark Isle at rung 8 of 13 and the Cipher Key Lair at rung 2.

    This is the case the intended-path probe above cannot show. A shuffled ordering is where a region's tier and
    its vanilla levels come apart, so it is where a floor at vanilla stops being a safety net and starts being
    the whole answer."""

    ORDER = {   # region -> 0-based rung, straight off that seed's `notes`
        "Agate Village": 0, "Cipher Key Lair": 1, "Cipher Key Lair (exterior)": 1, "Phenac City": 2,
        "Snagem Hideout": 3, "Phenac City (Post-Sixes)": 4, "Pyrite Town": 5, "SS Libra": 6,
        "Citadark Isle": 7, "Mt. Battle": 8, "Cipher Lab": 9, "Poke Spots": 10,
        "Pyrite Town (ONBS)": 11, "Outskirt Stand": 12,
    }

    def setUp(self) -> None:
        self.census = rtd.real_shadow_census()
        self.by_trainer = pls.level_by_trainer_index(tier_by_region=self.ORDER)

    def _assign(self, mark: bool) -> "dict[int, int]":
        rows = []
        for record in self.census:
            index = record.get("trainer_index")
            if index in self.by_trainer:
                row = {**record, "team_avg_level": float(self.by_trainer[index])}
                if mark:
                    row["level_source"] = "path"
                rows.append(row)
            else:
                rows.append(record)
        return ed.shadow_level_assignment(rows, scale_levels=False)[1]

    def test_the_reported_magnitude_comes_back_without_the_mark(self) -> None:
        """57 of the 83 Shadows in that seed had the vanilla floor beat the ramp. The assertion is an order of
        magnitude rather than the exact number, because the census and the ramp both move."""
        fixed, broken = self._assign(mark=True), self._assign(mark=False)
        differ = {ddpk for ddpk in fixed if fixed[ddpk] != broken[ddpk]}
        self.assertGreater(len(differ), 40, "the reported seed had 57 -- this is the bug, restated")
        for ddpk in differ:
            self.assertGreater(broken[ddpk], fixed[ddpk])

    def test_the_three_areas_the_player_would_have_walked_into(self) -> None:
        """Named regions rather than counts, because these are the numbers a player actually sees: a level-12
        Key Lair team with level-28 Shadows on it, and so on."""
        fixed, broken = self._assign(mark=True), self._assign(mark=False)
        for region, rung_level in (("Cipher Key Lair", 12), ("Citadark Isle", 33), ("Phenac City", 15)):
            rows = [r for r in self.census
                    if tp.PLACEMENTS.get(r["trainer_index"]) is not None
                    and tp.PLACEMENTS[r["trainer_index"]].region == region
                    and r["ddpk_index"] in fixed]
            self.assertTrue(rows, region)
            for record in rows:
                ddpk = record["ddpk_index"]
                self.assertEqual(rung_level, fixed[ddpk], f"{region} ddpk {ddpk} is off its own rung")
            self.assertTrue(any(broken[record["ddpk_index"]] > rung_level for record in rows),
                            f"{region} shows none of the reported damage, so this is the wrong fixture")

    def test_no_shadow_ever_outranks_its_own_areas_tier(self) -> None:
        """Stated as the thing the player would see: a Shadow standing on a team the ramp moved must not be
        levelled above the band that team is now in."""
        assigned = self._assign(mark=True)
        for record in self.census:
            index, ddpk = record.get("trainer_index"), record.get("ddpk_index")
            if index in self.by_trainer and ddpk in assigned:
                self.assertLessEqual(assigned[ddpk], pls.LAST_TIER_LEVEL)
                self.assertGreaterEqual(assigned[ddpk], pls.FIRST_TIER_LEVEL)


class TestTheCallSiteReallyMarksThem(unittest.TestCase):
    """FOUND BY PROBING. Every test above supplies `level_source` itself, so deleting the mark from
    `generate_output` left all seventeen of them passing -- the fix would have silently stopped shipping. The
    mark is written deep inside `generate_output`, which no unit test reaches, so it is asserted structurally,
    the same way this project pins `Client.py` behaviour it cannot import."""

    SOURCE = (pathlib.Path(__file__).resolve().parent.parent / "__init__.py").read_text(encoding="utf-8")

    def test_the_shadow_census_rebuild_sets_the_mark(self) -> None:
        rebuild = self.SOURCE[self.SOURCE.index("shadow_census = ["):]
        rebuild = rebuild[:rebuild.index("shadow_dpkm_levels, shadow_ddpk_levels")]
        self.assertIn('"level_source": "path"', rebuild,
                      "generate_output re-bases the census onto the ramp but no longer marks it, so "
                      "ADDENDUM 317's floor will quietly override the ramp again")
        self.assertIn('"team_avg_level": float(by_trainer[record["trainer_index"]])', rebuild,
                      "the mark and the value it describes must be set together")

    def test_the_consumer_reads_the_same_string(self) -> None:
        """Two literals in two files is the drift this project keeps finding, so they are compared rather than
        trusted."""
        consumer = (pathlib.Path(__file__).resolve().parent.parent / "randomizer"
                    / "enhanced_difficulty.py").read_text(encoding="utf-8")
        self.assertIn('record.get("level_source") != "path"', consumer)

    def test_the_note_is_given_the_levels_that_were_written(self) -> None:
        """The other half of ADDENDUM 370: the seed note has to report the assigned level, not the holder's
        vanilla average, or a wrong level is invisible in the patch again."""
        self.assertIn("describe_resolution(shadow_ddpk_levels)", self.SOURCE)


class TestTheSeedNoteSaysWhatWasWritten(unittest.TestCase):
    def test_it_reports_the_assigned_level_when_given_one(self) -> None:
        levels = {ddpk: 40 for ddpk in sh.shadows_held_more_than_once()}
        lines = sh.describe_resolution(levels)
        self.assertTrue(lines)
        for line in lines:
            self.assertIn("written at level 40", line)

    def test_it_still_works_with_nothing_to_report(self) -> None:
        """`!shadowdex`-style callers have no level plan to hand it."""
        self.assertEqual(sh.describe_resolution(), sh.describe_resolution(None))
        for line in sh.describe_resolution():
            self.assertNotIn("written at level", line)


class TestTheKeyLairFloor(unittest.TestCase):
    def test_it_is_0x67_unconditionally(self) -> None:
        self.assertEqual(0x67, sb.AREA_ENTRY_FLOOR_OVERRIDES[LAIR])
        self.assertEqual(0x67, sb.area_entry_floor(LAIR))
        self.assertEqual(0x67, rc.AreaStoryByteMemory().target_for(LAIR))
        self.assertEqual([], [r for r in sb.AREA_FLOOR_RULES if r.target == LAIR])

    def test_it_is_a_rung_inside_the_lairs_own_window(self) -> None:
        window = sb.REGION_STORY_WINDOW[LAIR]
        self.assertTrue(sb.byte_is_reachable(0x67))
        self.assertLessEqual(window.floor, 0x67)
        self.assertLessEqual(0x67, window.ceiling)

    def test_the_unlock_floor_did_not_move_with_it(self) -> None:
        """ADDENDUM 247's split. The icon still APPEARS when the game opens the exterior; only the byte the
        destination is entered at moved. Crediting the unlock at 0x67 would be 247's bug, fourteen bytes late."""
        self.assertEqual(0x5D, sb.area_unlock_floor(LAIR))

    def test_it_cannot_move_a_single_trainer_level(self) -> None:
        """ADDENDUM 329's fence, re-checked because this addendum is exactly the kind of change that broke it
        the first time: an icon instruction ("make Cipher Key Lair's floor 0x64") silently re-ordered the level
        ramp, because `_path_floor` was asking `area_entry_floor`. It asks `region_floor` now."""
        before = pls.level_by_trainer_index()
        original = dict(sb.AREA_ENTRY_FLOOR_OVERRIDES)
        try:
            sb.AREA_ENTRY_FLOOR_OVERRIDES[LAIR] = 0x6A
            self.assertEqual(before, pls.level_by_trainer_index())
        finally:
            sb.AREA_ENTRY_FLOOR_OVERRIDES.clear()
            sb.AREA_ENTRY_FLOOR_OVERRIDES.update(original)

    def test_zook_two_cannot_hold_progression_while_this_floor_stands(self) -> None:
        """WHAT THE FLOOR COSTS, fenced. 0x65 is "Zook beaten at the Lair", so entering at 0x67 stages the
        building past that fight on every visit including the first, and `Defeat - Zook #2` (147) cannot be
        relied on.

        It is already filler-only, and not by accident that needed a new list entry: Zook #1 (9) is on the
        player's own missable compilation and ADDENDUM 188 widened that fence to every occurrence of a marked
        surname. This asserts the two facts together, so that un-fencing Zook later cannot quietly put
        progression behind a fight this floor skips -- the failure would otherwise be an unwinnable seed every
        time rather than a probability."""
        self.assertEqual("Cipher Key Lair (exterior)", tp.PLACEMENTS[147].region)
        self.assertGreater(sb.area_entry_floor(LAIR), 0x65,
                           "if the floor drops to 0x65 or below, Zook #2 is fightable and this fence can go")
        self.assertIn(147, mt.FILLER_ONLY_TRAINER_INDICES,
                      "the Lair's floor skips Zook #2, so his check must not be able to hold progression")
        self.assertIn(148, mt.FILLER_ONLY_TRAINER_INDICES, "Biden #2 stands beside him")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
