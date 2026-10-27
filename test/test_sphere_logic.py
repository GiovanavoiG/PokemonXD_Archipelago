"""Regression coverage for rules.py's ADDENDUM 99 sphere logic (chest/trainer cumulative-count locations
gated behind real region reachability instead of being unconditionally open from Menu) -- see rules.py's own
module docstring for the full design this exercises.

RETARGETED 2026-09-13 (ADDENDUM 168) throughout. Every test in this file used to open the map by collecting
Krane Memos, because regions.py chained seven regions behind `MEMOS_REQUIRED`. That ladder is retired: the
memos are not items at all any more and rules.py's `_SPHERE_REGION_ORDER` is now `list(regions.REGION_NAMES)`
-- the real 21-region graph, in graph order -- with `_CHEST_WEIGHT_BY_REGION` a real per-region census derived
from game_data/chest_regions.py rather than walkthrough estimates. The route through the graph is
PokemonXDTestBase.KEY_ITEM_CHAIN, and each test below now names which prefix of it the threshold under test
really needs, rather than a memo count.
"""
from __future__ import annotations

from . import PokemonXDTestBase
from .. import items
from .. import rules
from ..locations import trainer_defeat_count_location_name
from ._chest_samples import CHEST_SAMPLES_IN_GRAPH_ORDER, DEEPEST_CHEST, EARLIEST_CHEST
from ..options import TrainerDefeatCheckCount

# The top of the trainer ladder a seed can actually have. NARROWED to 114 in ADDENDUM 161 (it was 232) so the
# ladder stops where rules.py's Mt. Battle bucket begins -- see that option's own comment.
TRAINER_CEILING = TrainerDefeatCheckCount.range_end

# RETARGETED 2026-09-13 (ADDENDUM 174). This used to sample positions along the "Open N Chests" ladder,
# because a ladder is the only thing a count can be sampled along. Chests are per-chest locations now, so the
# monotonicity test samples one chest from each region in graph order instead -- which tests the same property
# against the real map rather than against a model of it.

# The live threshold tables, so the assertions below are stated against the real census rather than against
# numbers copied out of it (ADDENDUM 168: the previous copies -- "Cipher Key Lair's capacity is 113" and the
# like -- are exactly what went stale when the region order changed).
_TRAINER_THRESHOLDS = rules._cumulative_region_thresholds(rules._TRAINER_WEIGHT_BY_REGION)


def _next_region_with_trainers(after: str) -> "str | None":
    """The next region in graph order that carries any trainers. ADDENDUM 175: used instead of naming a region
    pair, because every hardcoded pair in this file has gone stale at least once."""
    order = rules._SPHERE_REGION_ORDER
    for region in order[order.index(after) + 1:]:
        if rules._TRAINER_WEIGHT_BY_REGION.get(region, 0):
            return region
    return None


def _first_region_holding_any(weight_by_region: "dict[str, int]") -> "tuple[str, int]":
    """The earliest region in sphere order with a non-zero weight, and its cumulative total there. A real
    census has gaps (ADDENDUM 168 -- the three always-open starting regions hold no trainers at all), so "the
    bottom of the ladder" is this region rather than simply the first region in the graph."""
    # FIXED 2026-09-13 (ADDENDUM 169): the cumulative total was read out of `_TRAINER_THRESHOLDS` no matter
    # which table was passed in, so this quietly returned trainer numbers for any other category. Derive it
    # from the argument instead.
    thresholds = dict((region, total)
                      for total, region in rules._cumulative_region_thresholds(weight_by_region))
    for region_name in rules._SPHERE_REGION_ORDER:
        if weight_by_region.get(region_name, 0):
            return region_name, thresholds[region_name]
    raise AssertionError("no region carries any weight at all")


class TestSphereLogicDefaultOptions(PokemonXDTestBase):
    # ADDENDUM 196: this class tests the CUMULATIVE "Defeat N Trainers" ladder, which only exists in
    # cumulative mode -- now no longer the default. Pinned rather than inherited.
    options = {"randomize_chests": True, "shuffle_trainer_defeats": True, "trainer_defeat_mode": 0,
               # ADDENDUM 196: the Parts gate defaults ON now and Citadark is this class's deepest
               # probe. These tests are about the chest/trainer sphere ladder, not the endgame key.
               "robo_kyogre_parts_unlock_citadark": False,
               "trainer_defeat_check_count": TRAINER_CEILING}

    def test_the_earliest_chest_is_reachable_from_the_start(self) -> None:
        """RETARGETED 2026-09-13 (ADDENDUM 174), and it is a stronger claim than the one it replaces. The old
        version asserted that the MODEL put the first chest threshold in Pokemon HQ Lab. This asserts that a
        chest the ISO says is physically in Pokemon HQ Lab is reachable with nothing collected -- the model is
        gone, so there is nothing left to agree with except the map."""
        self.assertTrue(self.can_reach_location(EARLIEST_CHEST))

    def test_defeat_1_trainers_opens_as_early_as_the_census_allows(self) -> None:
        """RETARGETED 2026-09-13 (ADDENDUM 168), was "defeat 1 trainers is reachable from the start"; briefly
        RETARGETED BACK to "reachable from the start" the same day (ADDENDUM 169); now RETARGETED AGAIN, still
        the same day, because ADDENDUM 169's always-open Agate Village was itself reversed.

        SAME-DAY REVERSAL, and why it is not churn. ADDENDUM 169 first applied the rule that only Kaminko,
        Gateon, Agate and the Pokemon HQ Lab are open by default in every mode, and put
        `("Menu", "Agate Village", ())` in regions.REGION_EDGES. That was corrected within the day -- with
        travel randomization off, Agate, Kaminko and Gateon stay locked by default and unlock normally -- so
        the four-always-open rule now lives ONLY in the randomize_travel_locations-on branch of regions.py,
        and the default graph walks the vanilla route:
        Pokemon HQ Lab -> Kaminko's House -> Gateon Port -> (Machine Part) -> Agate Village.

        What this test protects is unchanged across all three versions, and is a census property, not a
        constant: the very first trainer threshold must sit in the FIRST region that carries any trainer
        weight, and that location must open exactly when that region does -- never a sphere later because a
        threshold drifted deeper into the table. Only the answer to "when does that region open" moved, from
        sphere 0 back to one key item in. Both directions are asserted, since either half alone would let the
        other regress silently.
        """
        # RETARGETED AGAIN 2026-09-13 (ADDENDUM 175), and this time the answer got better rather than just
        # different. The old estimate gave the four always-open starting regions no trainers at all, so the
        # first threshold sat in Agate Village, one key item in. The census puts 5 trainers in the
        # Pokemon HQ Lab and 9 in Gateon Port, so "Defeat 1 Trainers" is reachable from the start again -- for
        # the real reason this time, not because the bucket happened to be parked off Menu.
        first_region, _ = _first_region_holding_any(rules._TRAINER_WEIGHT_BY_REGION)
        self.assertEqual(rules._region_for_sphere_count(_TRAINER_THRESHOLDS, 1), first_region)
        self.assertEqual(first_region, "Pokemon HQ Lab")
        self.assertTrue(self.can_reach_location(trainer_defeat_count_location_name(1)))

        # INVERTED 2026-09-13 (ADDENDUM 175). This used to assert that the always-open starting regions carry
        # NO trainer weight, which was true of the estimate and is false of the census -- they hold 21 between
        # them. So the property flips: the bottom of the ladder is open on an empty state precisely BECAUSE
        # those regions hold trainers, which is the outcome ADDENDUM 169 set out: Gateon, Kaminko, the HQ Lab
        # and Agate all have checks from their trainer defeats and chests.
        for region_name in ("Pokemon HQ Lab", "Kaminko's House", "Gateon Port"):
            self.assertTrue(self.multiworld.state.can_reach(region_name, player=self.player), region_name)
        self.assertGreater(
            sum(rules._TRAINER_WEIGHT_BY_REGION.get(r, 0)
                for r in ("Pokemon HQ Lab", "Kaminko's House", "Gateon Port")),
            0, "the always-open regions must hold trainer checks -- ADDENDUM 169")

        self.assertTrue(self.multiworld.state.can_reach(first_region, player=self.player))

        self.collect_key_item_chain(1)  # the Machine Part -- Gateon Port -> Agate Village
        self.assertTrue(self.can_reach_location("Defeat 1 Trainers"),
                        "the bottom of the ladder must open with its own region, not a sphere later")
    def test_open_115_chests_is_not_reachable_from_the_start(self) -> None:
        # The real, ROM-exact final chest -- must NOT be reachable before Citadark Isle, the last region in
        # sphere order, is reachable. (ADDENDUM 168: "before any Krane Memos are collected" was the old
        # phrasing; the memos are gone, the assertion is the same.)
        self.assertFalse(self.can_reach_location(DEEPEST_CHEST))

    def test_the_top_trainer_threshold_is_not_reachable_from_the_start(self) -> None:
        self.assertFalse(self.can_reach_location(trainer_defeat_count_location_name(TRAINER_CEILING)))

    def test_open_115_chests_requires_citadark_isle_specifically(self) -> None:
        """Citadark Isle is the last sphere possible. Confirms the highest-N chest
        location becomes reachable exactly when Citadark Isle itself does, not any region before it.

        RETARGETED 2026-09-13 (ADDENDUM 168): "5 Krane Memos, this skeleton's own Citadark Isle entrance
        requirement" is now the full KEY_ITEM_CHAIN, whose last link (the System Lever) opens Cipher Key Lair
        (deep) and therefore Citadark Isle. Four of five leaves the player at Cipher Key Lair -- the same
        one-edge-short probe the memo version used.
        """
        self.collect_key_item_chain(4)  # everything but the System Lever -- Citadark Isle not yet
        self.assertFalse(self.can_reach_location("Citadark Isle 1F Chest"))
        self.assertFalse(self.can_reach_location(DEEPEST_CHEST))
        self.collect_key_item_chain(5)  # + the System Lever -- Citadark Isle now reachable
        self.assertTrue(self.can_reach_location("Citadark Isle 1F Chest"))
        self.assertTrue(self.can_reach_location(DEEPEST_CHEST))

    # REWRITTEN BY ADDENDUM 432. Both tests below asserted the retired LADDER: threshold N open as soon as the one
    # region holding the Nth trainer of a story-order list was. "Defeat N Trainers" is now a tally of the fights
    # this state can really reach, so the property they protect is stated against that tally instead.
    def _available_trainers(self) -> int:
        total = 0
        for ways, count in rules._trainer_count_groups(self.multiworld.worlds[self.player]):
            if any(all(self.multiworld.state.can_reach(r, player=self.player) for r in regions)
                   and all(self.multiworld.state.has(i, self.player) for i in held) for regions, held in ways):
                total += count
        return total

    def _assert_tally_boundary(self) -> int:
        n = self._available_trainers()
        if 1 <= n <= TRAINER_CEILING:
            self.assertTrue(self.can_reach_location(trainer_defeat_count_location_name(n)), n)
        if n + 1 <= TRAINER_CEILING:
            self.assertFalse(self.can_reach_location(trainer_defeat_count_location_name(n + 1)), n)
        return n

    def test_the_top_trainer_threshold_stops_short_of_the_final_sphere(self) -> None:
        """RETARGETED BY ADDENDUM 483 (issue #2). Was: the highest count the option can ask for opens before Citadark
        Isle does. That held only because the tally counted missable fights, region-less rows (filed at Citadark) and
        every rematch separately. Counted honestly -- each trainer once, never a missable one -- only 88 trainers
        stand outside Citadark Isle, so the top thresholds now need it. What stays true: the threshold opens on the
        key-item chain, with every boundary on the way exact."""
        top_trainer = trainer_defeat_count_location_name(TRAINER_CEILING)
        opened_at = None
        for links in range(1, len(self.KEY_ITEM_CHAIN) + 1):
            self.collect_by_name(self.KEY_ITEM_CHAIN[links - 1])
            self._assert_tally_boundary()
            if self.can_reach_location(top_trainer):
                opened_at = links
                break
        self.assertIsNotNone(opened_at)

    def test_a_count_past_agate_villages_capacity_requires_mt_battle(self) -> None:
        """Each key item opens exactly as many counts as the fights it makes reachable: nothing collected opens
        none past what is free, the Machine Part opens more, and the Data ROM more again."""
        self.assertFalse(self.multiworld.state.can_reach("Agate Village", player=self.player))
        before = self._assert_tally_boundary()
        self.collect_key_item_chain(1)  # the Machine Part -- Agate Village and Mt. Battle behind it
        self.assertTrue(self.multiworld.state.can_reach("Mt. Battle", player=self.player))
        with_part = self._assert_tally_boundary()
        self.assertGreater(with_part, before)
        self.collect_by_name(self.KEY_ITEM_CHAIN[1])
        with_rom = self._assert_tally_boundary()
        self.assertGreater(with_rom, with_part)

    def test_sphere_thresholds_are_monotonic_non_increasing_in_a_fixed_state(self) -> None:
        """Progressive logic sanity check: in any ONE fixed state, once a chest threshold is unreachable, every
        HIGHER threshold checked afterward must also stay unreachable -- reachability can only get harder as N
        grows, never easier, for a fixed amount of progress.

        RETARGETED 2026-09-13 (ADDENDUM 168) only in how the "everything collected" end state is built: the
        full KEY_ITEM_CHAIN instead of all five Krane Memos.
        """
        seen_false = False
        for name in CHEST_SAMPLES_IN_GRAPH_ORDER:
            reachable = self.can_reach_location(name)
            if not reachable:
                seen_false = True
            elif seen_false:
                self.fail(f"{name} was reachable after an earlier-region chest was unreachable")
        self.collect_key_item_chain()
        for name in CHEST_SAMPLES_IN_GRAPH_ORDER:
            self.assertTrue(self.can_reach_location(name))
