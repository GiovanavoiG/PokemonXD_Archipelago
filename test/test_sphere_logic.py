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

        SAME-DAY REVERSAL, and why it is not churn. ADDENDUM 169 first read the player's standing "the only
        locations I want open by default are Kaminko, Gateon, Agate and Pokemon HQ Lab" as applying in every
        mode and put `("Menu", "Agate Village", ())` in regions.REGION_EDGES. The player corrected that within
        the day -- "Leave Agate, Kaminko and Gateon locked by default if travel randomization is off. Let them
        unlock normally." -- so the four-always-open rule now lives ONLY in the randomize_travel_locations-on
        branch of regions.py, and the default graph walks the vanilla route:
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
        # first threshold sat in Agate Village, one key item in. The player's census puts 5 trainers in the
        # Pokemon HQ Lab and 9 in Gateon Port, so "Defeat 1 Trainers" is reachable from the start again -- for
        # the real reason this time, not because the bucket happened to be parked off Menu.
        first_region, _ = _first_region_holding_any(rules._TRAINER_WEIGHT_BY_REGION)
        self.assertEqual(rules._region_for_sphere_count(_TRAINER_THRESHOLDS, 1), first_region)
        self.assertEqual(first_region, "Pokemon HQ Lab")
        self.assertTrue(self.can_reach_location(trainer_defeat_count_location_name(1)))

        # INVERTED 2026-09-13 (ADDENDUM 175). This used to assert that the always-open starting regions carry
        # NO trainer weight, which was true of the estimate and is false of the census -- they hold 21 between
        # them. So the property flips: the bottom of the ladder is open on an empty state precisely BECAUSE
        # those regions hold trainers, which is the outcome the player asked for in ADDENDUM 169 ("Gateon,
        # Kaminko, HQ Lab and Agate should all have checks from their trainer defeats and chests").
        for region_name in ("Pokemon HQ Lab", "Kaminko's House", "Gateon Port"):
            self.assertTrue(self.multiworld.state.can_reach(region_name, player=self.player), region_name)
        self.assertGreater(
            sum(rules._TRAINER_WEIGHT_BY_REGION.get(r, 0)
                for r in ("Pokemon HQ Lab", "Kaminko's House", "Gateon Port")),
            0, "the always-open regions must hold trainer checks -- ADDENDUM 169's instruction")

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
        """Player request: "Make citadark isle the last sphere possible." Confirms the highest-N chest
        location becomes reachable exactly when Citadark Isle itself does, not any region before it.

        RETARGETED 2026-09-13 (ADDENDUM 168): "5 Krane Memos, this skeleton's own Citadark Isle entrance
        requirement" is now the full KEY_ITEM_CHAIN, whose last link (the System Lever) opens Cipher Key Lair
        (deep) and therefore Citadark Isle. Four of five leaves the player at Cipher Key Lair -- the same
        one-edge-short probe the memo version used.
        """
        self.collect_key_item_chain(4)  # everything but the System Lever -- Citadark Isle not yet
        self.assertFalse(self.can_reach_location("Citadark Isle Chest 2"))
        self.assertFalse(self.can_reach_location(DEEPEST_CHEST))
        self.collect_key_item_chain(5)  # + the System Lever -- Citadark Isle now reachable
        self.assertTrue(self.can_reach_location("Citadark Isle Chest 2"))
        self.assertTrue(self.can_reach_location(DEEPEST_CHEST))

    def test_the_top_trainer_threshold_stops_short_of_the_final_sphere(self) -> None:
        """A real consequence of ADDENDUM 161's 114 ceiling, asserted so it is a decision rather than a
        surprise: the trainer ladder no longer reaches the final sphere.

        RETARGETED 2026-09-13 (ADDENDUM 168), was "lands in the Mt. Battle bucket not Citadark". Mt. Battle no
        longer sits at the top of the trainer table -- ADDENDUM 168 moved it off Agate Village (the story bytes
        put it at 0x23 -> 0x24), so in sphere order its 92-threshold block now starts just past Agate Village's
        own capacity rather than at 114. (ADDENDUM 169: that capacity went 4 -> 10 when the unvisited Relic
        Forest weights folded into Agate, so the block runs 11-102 and the 114 ceiling lands in Pyrite Town
        rather than Realgam Tower. The assertions below name neither region, so they did not have to move.)
        The surviving, still-load-bearing half of the original
        assertion is the contrast with chests: the trainer ceiling must NOT require the last region, while the
        top chest threshold must, so "Citadark Isle is the last possible sphere" still holds for the category
        that can express it.
        """
        top_trainer = trainer_defeat_count_location_name(TRAINER_CEILING)
        ceiling_region = rules._region_for_sphere_count(_TRAINER_THRESHOLDS, TRAINER_CEILING)
        self.assertNotEqual(ceiling_region, "Citadark Isle")
        self.assertLess(rules._SPHERE_REGION_ORDER.index(ceiling_region),
                        rules._SPHERE_REGION_ORDER.index("Citadark Isle"))

        # Two links in (Machine Part + Data ROM) is enough for the whole Agate -> Realgam stretch, so the top of
        # the trainer ladder opens there -- while the top chest threshold still waits for the full chain.
        self.collect_key_item_chain(2)
        self.assertTrue(self.can_reach_location(top_trainer))
        self.assertFalse(self.can_reach_location(DEEPEST_CHEST))

    def test_a_count_past_agate_villages_capacity_requires_mt_battle(self) -> None:
        """RETARGETED 2026-09-13 (ADDENDUM 168), was "a count past Cipher Key Lair's capacity requires
        Mt. Battle"; RETARGETED again the same day (ADDENDUM 169); and RETARGETED once more the same day, for
        ADDENDUM 169's own partial reversal.

        SAME-DAY REVERSAL. ADDENDUM 169 briefly made Agate Village unconditionally open in every mode; the
        player corrected it ("Leave Agate, Kaminko and Gateon locked by default if travel randomization is
        off. Let them unlock normally."), so with travel randomization off the Machine Part gates Agate Village
        again and Mt. Battle INHERITS it through Agate rather than carrying a gate of its own.

        The shape this test was written to protect is the sphere-logic boundary: the first threshold past
        region X's cumulative capacity must be the first that needs the NEXT region in sphere order, and that
        next region must really cost something. The reversal splits that into two halves, and both are
        asserted here rather than dropping the half that got weaker:

          * the Agate/Mt. Battle boundary is still the boundary in the THRESHOLD TABLE, and both sides are
            still gated (they are simply gated by the same item now -- the Machine Part opens Agate, and
            Mt. Battle hangs off Agate with no requirement of its own). Asserting the closed-then-open
            transition around it still catches Agate silently re-opening or the Machine Part being demoted to
            flavour, which is what the ADDENDUM 169 version was watching for.
          * the ITEM-SEPARATED boundary -- one region's capacity open while the very next count is not --
            moved up the table to Mt. Battle's capacity vs Pyrite Town, which needs the Data ROM. That is the
            discriminating property, so it is exercised explicitly instead of being lost.

        Every boundary is read out of the live threshold tables rather than copied out of them -- hardcoding
        "4 and 5" is precisely what went stale here the first time.
        """
        capacity_of = dict((region, total) for total, region in _TRAINER_THRESHOLDS)

        agate_capacity = capacity_of["Agate Village"]
        self.assertEqual(rules._region_for_sphere_count(_TRAINER_THRESHOLDS, agate_capacity), "Agate Village")
        self.assertEqual(rules._region_for_sphere_count(_TRAINER_THRESHOLDS, agate_capacity + 1), "Mt. Battle")
        self.assertLessEqual(agate_capacity + 1, TRAINER_CEILING,
                             "the probe past Agate's capacity must be a location this seed really created")

        at_capacity = trainer_defeat_count_location_name(agate_capacity)
        past_capacity = trainer_defeat_count_location_name(agate_capacity + 1)

        # Nothing collected: Agate is behind the Machine Part again, so BOTH sides of this boundary are shut.
        self.assertFalse(self.multiworld.state.can_reach("Agate Village", player=self.player))
        self.assertFalse(self.multiworld.state.can_reach("Mt. Battle", player=self.player))
        self.assertFalse(self.can_reach_location("Agate Bridge Chest"))
        self.assertFalse(self.can_reach_location(at_capacity))
        self.assertFalse(self.can_reach_location(past_capacity))

        self.collect_key_item_chain(1)  # the Machine Part -- opens Agate Village, and Mt. Battle behind it
        self.assertTrue(self.multiworld.state.can_reach("Agate Village", player=self.player))
        self.assertTrue(self.multiworld.state.can_reach("Mt. Battle", player=self.player))
        self.assertTrue(self.can_reach_location("Agate Bridge Chest"))
        self.assertTrue(self.can_reach_location(at_capacity))
        self.assertTrue(self.can_reach_location(past_capacity))

        # The discriminating half: the first boundary where the next region really does cost the next key
        # item. RETARGETED 2026-09-13 (ADDENDUM 175) from Mt. Battle -> Pyrite Town to Cipher Lab -> Pyrite
        # Town, and AGAIN 2026-09-16 (ADDENDUM 240) now that plain Pyrite Town is no longer behind the Data
        # ROM -- the boundary is Pyrite Town -> Poke Spots.
        #
        # That is four retargets, every one of them because this test NAMED a region pair. So it no longer
        # names one: the boundary is FOUND by reachability in the current state -- the first trainer-bearing
        # region this state can reach whose next trainer-bearing region it cannot. Whatever the graph does
        # next, this finds the real Data ROM boundary instead of going stale.
        free_side = next(
            region for _total, region in _TRAINER_THRESHOLDS
            if rules._TRAINER_WEIGHT_BY_REGION.get(region, 0)
            and self.multiworld.state.can_reach(region, player=self.player)
            and _next_region_with_trainers(region)
            and not self.multiworld.state.can_reach(
                _next_region_with_trainers(region), player=self.player)
        )
        gated_side = _next_region_with_trainers(free_side)
        free_capacity = capacity_of[free_side]
        self.assertEqual(rules._region_for_sphere_count(_TRAINER_THRESHOLDS, free_capacity), free_side)
        self.assertEqual(rules._region_for_sphere_count(_TRAINER_THRESHOLDS, free_capacity + 1), gated_side)
        self.assertLessEqual(free_capacity + 1, TRAINER_CEILING,
                             "the probe past that capacity must be a location this seed really created")
        # ADDENDUM 179: the Data ROM ships packaged with the ID Card, so the thing collected below is the
        # chain's second link by name rather than "Data ROM" -- which is exactly why the chain is resolved
        # from items.COMBINED_KEY_ITEM_NAME in one place instead of being typed out in every test.
        self.assertFalse(self.multiworld.state.can_reach(gated_side, player=self.player))
        self.assertTrue(self.can_reach_location(trainer_defeat_count_location_name(free_capacity)))
        self.assertFalse(self.can_reach_location(trainer_defeat_count_location_name(free_capacity + 1)))

        self.collect_key_item_chain(2)   # + the packaged Data ROM & ID Card
        self.assertTrue(self.multiworld.state.can_reach(gated_side, player=self.player))
        self.assertTrue(self.can_reach_location(trainer_defeat_count_location_name(free_capacity + 1)))
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
