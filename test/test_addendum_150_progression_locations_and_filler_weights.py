"""ADDENDUM 150 (2026-09-11): filler weighting, and letting checks hold progression at all.

Player request: "Can we weight the filler away from the flutes/status heals and towards the various pokeballs?
Also, can we ensure that every check can be progressive/useful/not filler? It seems like all my trainer defeats
and chests are guaranteed filler, which I don't want. Check shadow purifies & catches too."

Both halves are here because they solve the same complaint from opposite ends: one makes the filler better,
the other makes there be less of it.
"""
from __future__ import annotations

import collections
import random
import unittest

from BaseClasses import LocationProgressType

from . import PokemonXDTestBase
from .. import items, locations, regions, rules
from ._chest_samples import DEEPEST_CHEST, DEEP_NON_CITADARK_CHEST, EARLIEST_CHEST


# ============================================================================================================
# FILLER WEIGHTING
# ============================================================================================================
class _SeededWorld:
    """Just enough of a world for `get_random_filler_item_name`."""

    def __init__(self, seed: int = 1) -> None:
        self.random = random.Random(seed)


def _bucket(name: str) -> str:
    if name in items.FLUTE_ITEMS:
        return "flute"
    if name in items.STATUS_HEAL_ITEM_NAMES:
        return "status heal"
    if name in items.FILLER_BALL_ITEMS or name in items.FILLER_BALL_BUNDLE_ITEMS:
        return "ball"
    if name in items.MEDICINE_ITEMS:
        return "healing"
    return "other"


class TestFillerWeights(unittest.TestCase):
    def test_balls_outweigh_flutes_and_status_heals_per_name(self) -> None:
        for ball in ("Poke Ball", "Great Ball", "Ultra Ball", "10 Poke Balls"):
            for dull in ("Blue Flute", "Yellow Flute", "Red Flute", "Parlyz Heal", "Antidote"):
                self.assertGreater(items._filler_weight(ball), items._filler_weight(dull),
                                   f"{ball} should outweigh {dull}")

    def test_full_restore_is_not_swept_up_as_a_status_heal(self) -> None:
        """A substring rule on "Heal" would have caught Full Heal and Full Restore, which are worth getting."""
        self.assertNotIn("Full Heal", items.STATUS_HEAL_ITEM_NAMES)
        self.assertNotIn("Full Restore", items.STATUS_HEAL_ITEM_NAMES)
        self.assertGreater(items._filler_weight("Full Restore"), items._filler_weight("Parlyz Heal"))

    def test_every_status_heal_named_is_a_real_filler_item(self) -> None:
        for name in items.STATUS_HEAL_ITEM_NAMES:
            self.assertIn(name, items.FILLER_ITEMS, name)

    def test_nothing_is_weighted_to_zero(self) -> None:
        """Removal belongs in the _SPECS lists where the item is defined, not in a silent zero here."""
        self.assertTrue(all(weight > 0 for weight in items._RANDOM_FILLER_WEIGHTS))

    def test_every_filler_name_still_has_a_weight(self) -> None:
        self.assertEqual(len(items._RANDOM_FILLER_WEIGHTS), len(items._RANDOM_FILLER_POOL))

    def test_a_large_draw_lands_where_the_documented_table_says(self) -> None:
        world = _SeededWorld()
        drawn = collections.Counter(
            _bucket(items.get_random_filler_item_name(world)) for _ in range(20000)
        )
        total = sum(drawn.values())
        ball_share = drawn["ball"] / total
        flute_share = drawn["flute"] / total
        status_share = drawn["status heal"] / total
        # RETARGETED (ADDENDUM 311): the share is now the "poke_balls" category weight out of the total, not an
        # accident of per-name weights -- so assert exactly that, rather than the old 45-60% window.
        weights = items.FILLER_CATEGORY_DEFAULT_WEIGHTS
        expected = weights["poke_balls"] / sum(weights.values())
        self.assertAlmostEqual(ball_share, expected, delta=0.02)
        self.assertLess(flute_share, 0.03)
        self.assertLess(status_share, 0.05)
        self.assertGreater(ball_share, (flute_share + status_share) * 10)

    def test_flutes_are_rarer_but_never_impossible(self) -> None:
        world = _SeededWorld(seed=7)
        drawn = {items.get_random_filler_item_name(world) for _ in range(20000)}
        self.assertTrue(drawn & set(items.FLUTE_ITEMS), "a flute must still be reachable")

    def test_the_draw_is_reproducible_for_a_seed(self) -> None:
        """Same guarantee the old flat `choice` had -- AP requires generation be deterministic."""
        a = [items.get_random_filler_item_name(_SeededWorld(99)) for _ in range(50)]
        b = [items.get_random_filler_item_name(_SeededWorld(99)) for _ in range(50)]
        self.assertEqual(a, b)


# ============================================================================================================
# REGION MODELS BEHIND THE NEW NON-EXCLUDED CATEGORIES
# ============================================================================================================
class TestSphereWeightTables(unittest.TestCase):
    def test_purification_weights_come_from_the_real_83_shadow_roster(self) -> None:
        self.assertEqual(sum(rules._PURIFICATION_WEIGHT_BY_REGION.values()),
                         locations.PURIFICATION_LOCATION_COUNT)

    def test_a_region_with_no_shadows_and_no_clamped_ones_carries_no_weight(self) -> None:
        """RETARGETED AGAIN 2026-09-14 (ADDENDUM 184, player: "You can purify in Agate Village"). This used to
        assert Agate Village carried zero, on the grounds that no vanilla shadow is snagged there. That was the
        wrong question: the ladder counts where a shadow can be PURIFIED, and everything snagged before Agate
        can only be purified once Agate is reachable. So Agate now absorbs the seven thresholds that used to
        sit in the always-open regions, and Mt. Battle -- which has no shadows and is past the floor -- is the
        case this assertion is really about.

        The older retargeting note still applies: the table is a census, so a region with no weight is ABSENT
        rather than present-and-zero, and there are no tombstones."""
        self.assertEqual(rules._PURIFICATION_WEIGHT_BY_REGION.get("Mt. Battle", 0), 0)
        self.assertNotIn("_retired Relic Forest", rules._PURIFICATION_WEIGHT_BY_REGION)
        self.assertEqual(rules._PURIFICATION_WEIGHT_BY_REGION.get("Agate Village", 0), 7,
                         "the seven pre-Agate shadows should have been clamped here, not dropped")

    def test_the_purification_ladder_starts_at_the_first_place_that_can_purify(self) -> None:
        """REWRITTEN 2026-09-14 (ADDENDUM 184). The first vanilla shadow really is in the HQ Lab (Teddiursa,
        from Spy Naps in the intro) and that has not changed -- but snagging it is not purifying it. Threshold
        1 is now gated on Agate Village, which is what ADDENDUM 182's F2 was: a seed put the Machine Part on
        "Purify 2 Shadow Pokemon", and the Machine Part is the key to Agate Village."""
        from ..game_data import shadow_regions

        first_region, _species = shadow_regions.shadow_regions_in_graph_order()[0]
        self.assertEqual(first_region, "Pokemon HQ Lab", "where it is SNAGGED is unchanged")
        thresholds = rules._cumulative_region_thresholds(rules._PURIFICATION_WEIGHT_BY_REGION)
        self.assertEqual(rules._region_for_sphere_count(thresholds, 1),
                         shadow_regions.PURIFICATION_FLOOR_REGION)

    def test_every_weight_table_key_is_a_real_region_or_explicitly_retired(self) -> None:
        """NEW 2026-09-13 (ADDENDUM 169) -- the invariant whose absence caused the bug this addendum fixed.

        `_cumulative_region_thresholds` walks `_SPHERE_REGION_ORDER` (= regions.REGION_NAMES) and reads each
        region's weight out of the table with `.get(name, 0)`. A key that is NOT a region name is therefore
        never visited: its weight stays in the table's sum (so the module-level asserts stay happy) but drops
        out of the ordered walk, and every count above the walk's real top silently falls through to
        `_region_for_sphere_count`'s Citadark Isle fallback. That is exactly what "Relic Forest" did to both
        trainer tables -- they summed to 232 while the walk topped out at 226/222.

        So: every key must either be a real region, or be prefixed "_retired " to say out loud that it is a
        deliberately kept-but-unvisited placeholder (and then it must carry zero weight, or it would be
        re-introducing the same silent loss).
        """
        tables = {
            "_TRAINER_WEIGHT_BY_REGION": rules._TRAINER_WEIGHT_BY_REGION,
            "_UNIQUE_TRAINER_WEIGHT_BY_REGION": rules._UNIQUE_TRAINER_WEIGHT_BY_REGION,
            "_PURIFICATION_WEIGHT_BY_REGION": rules._PURIFICATION_WEIGHT_BY_REGION,
        }
        for table_name, table in tables.items():
            for key, weight in table.items():
                if key.startswith("_retired "):
                    self.assertEqual(weight, 0, f"{table_name}[{key!r}] is retired but still carries weight")
                    continue
                self.assertIn(key, regions.REGION_NAMES, f"{table_name}[{key!r}]")

    def test_every_weight_tables_ordered_walk_reaches_its_full_total(self) -> None:
        """NEW 2026-09-13 (ADDENDUM 169) -- the same bug stated as a behaviour rather than as a spelling rule.

        The last entry of each cumulative walk must equal the table's own sum AND the category's real location
        count, and must land on the last region in sphere order. If a future edit reintroduces an unvisited
        key, this fails even if the key happens to be spelled without the "_retired " marker.
        """
        expected = {
            "_TRAINER_WEIGHT_BY_REGION": (rules._TRAINER_WEIGHT_BY_REGION,
                                          locations.TRAINER_DEFEAT_COUNT_LOCATION_COUNT),
            "_UNIQUE_TRAINER_WEIGHT_BY_REGION": (rules._UNIQUE_TRAINER_WEIGHT_BY_REGION,
                                                 locations.TRAINER_DEFEAT_COUNT_LOCATION_COUNT),
            "_PURIFICATION_WEIGHT_BY_REGION": (rules._PURIFICATION_WEIGHT_BY_REGION,
                                               locations.PURIFICATION_LOCATION_COUNT),
        }
        for table_name, (table, real_count) in expected.items():
            walk = rules._cumulative_region_thresholds(table)
            self.assertEqual(walk[-1], (real_count, rules._SPHERE_REGION_ORDER[-1]), table_name)
            self.assertEqual(walk[-1][0], sum(table.values()), table_name)

    def test_mt_battle_holds_almost_none_of_the_story_roster(self) -> None:
        """RETARGETED 2026-09-13 (ADDENDUM 175), and the retarget is the point.

        ADDENDUM 145 found that Mt. Battle's 100 trainers are a separate deck file and are not among the 232
        story trainers -- yet the cumulative estimate gave Mt. Battle 92 of 232, gating ~40% of the roster on
        an optional dungeon. The fix at the time was a second table with Mt. Battle forced to 0 and the rest
        rescaled, which was a correction applied to a bad estimate.

        The player's census replaces the estimate with a count, and it says 3. Not 92, and not 0 either -- a
        handful of story fights really do happen at Mt. Battle. So both tables are now the same census, and
        the property worth asserting is the original CONCERN rather than either of the two old numbers: Mt.
        Battle must not carry a meaningful share of the story roster."""
        share = rules._TRAINER_WEIGHT_BY_REGION.get("Mt. Battle", 0)
        self.assertEqual(share, 3)
        self.assertLess(share / locations.TRAINER_DEFEAT_COUNT_LOCATION_COUNT, 0.05)
        self.assertEqual(rules._UNIQUE_TRAINER_WEIGHT_BY_REGION, rules._TRAINER_WEIGHT_BY_REGION)

    def test_unique_trainer_weights_still_total_the_real_roster(self) -> None:
        self.assertEqual(sum(rules._UNIQUE_TRAINER_WEIGHT_BY_REGION.values()),
                         locations.TRAINER_DEFEAT_COUNT_LOCATION_COUNT)

    def test_the_rescale_preserved_the_relative_ordering_of_every_region(self) -> None:
        """The Mt. Battle share was dropped and the rest rescaled -- every other region must keep its rank.

        RETARGETED 2026-09-13 (ADDENDUM 168): the region list came from `rules._SPHERE_REGION_ORDER`, which is
        now `list(regions.REGION_NAMES)` -- the real 21-region graph -- while these two trainer tables are still
        keyed by the nine names the pre-168 model used, so indexing them by sphere order raised KeyError. The
        rescale invariant is a property of the two TABLES, not of the graph, so it is now checked over their own
        (asserted identical) key sets.
        """
        self.assertEqual(set(rules._TRAINER_WEIGHT_BY_REGION), set(rules._UNIQUE_TRAINER_WEIGHT_BY_REGION),
                         "the rescale must cover exactly the same regions as the table it was derived from")
        others = [r for r in rules._TRAINER_WEIGHT_BY_REGION if r != "Mt. Battle"]
        old = [rules._TRAINER_WEIGHT_BY_REGION[r] for r in others]
        new = [rules._UNIQUE_TRAINER_WEIGHT_BY_REGION[r] for r in others]
        self.assertEqual([sorted(old).index(v) for v in old], [sorted(new).index(v) for v in new])

    def test_every_shop_is_gated_on_a_real_graph_region(self) -> None:
        """REPLACED 2026-09-13 (ADDENDUM 176). This tested `rules._SHOP_OCCURRENCE_REGIONS`, which mapped a
        berry's Nth purchase to a region. The ADDENDUM 168 version of this docstring had already recorded that
        the walk ran BACKWARDS -- the four positions were [17, 10, 6, 9] in graph order, because occurrence 1
        was filed under "Outskirt Stand" as "this world's first shop", which stopped being true when Outskirt
        Stand became a late region. The assertion was dropped at the time rather than restated, and flagged as
        production data the addendum had not carried over.

        It is carried over now, by deleting the model. A shop is in a town, so the town gates it. What this
        still protects is the thing that actually breaks generation: every shop names a region the graph really
        builds, since a stale region name in a `can_reach` is a generation error rather than a mis-shaped
        sphere. The ordering assertion needs no special care any more -- it follows from the graph."""
        from .. import regions
        from ..game_data import shops

        self.assertFalse(hasattr(rules, "_SHOP_OCCURRENCE_REGIONS"))
        for shop in shops.SHOPS:
            self.assertIn(shop.region, regions.REGION_NAMES, shop.name)
        # Shops are spread across the map, not pooled in one region -- which is the whole point of the change.
        self.assertGreater(len(set(shop.region for shop in shops.SHOPS)), 5)


class _ScopeBase(PokemonXDTestBase):
    """Shared helpers for the ProgressionLocations scope cases below.

    RESTORED 2026-09-13: an over-wide replacement in ADDENDUM 176 deleted this class header while retargeting
    the shop test directly above it, and the file stopped importing. Caught immediately by the suite.
    """

    # ADDENDUM 196: every subclass below probes "Defeat N Trainers", which exists only in CUMULATIVE mode --
    # no longer the default once the player's own YAML became the template. Pinned here once rather than in
    # each subclass, since none of them is about the mode.
    options = {"trainer_defeat_mode": 0}

    def progress_type(self, name: str):
        return self.multiworld.get_location(name, self.player).progress_type

    def assert_default(self, name: str) -> None:
        self.assertEqual(self.progress_type(name), LocationProgressType.DEFAULT, name)

    def assert_excluded(self, name: str) -> None:
        self.assertEqual(self.progress_type(name), LocationProgressType.EXCLUDED, name)


class TestEverything(_ScopeBase):
    """The default, and what was asked for."""

    options = {
        "trainer_defeat_mode": 0,
        "randomize_chests": True,
        "shuffle_trainer_defeats": True,
        "progression_locations": 2,
    }

    def test_chests_can_hold_progression(self) -> None:
        """ADDENDUM 174: the deep sample is a Cipher Key Lair chest rather than a Citadark one. Citadark
        checks now get a per-location progression roll (the player's "weighted AWAY from progressives, it's
        okay if it CAN happen" instruction), so a Citadark chest is EXCLUDED in most seeds and would make this
        test flaky in a way that looks like a regression. See test_citadark_is_weighted_away_from_progression
        below for the rule that replaced it."""
        self.assert_default(EARLIEST_CHEST)
        self.assert_default(DEEP_NON_CITADARK_CHEST)

    def test_citadark_is_weighted_away_from_progression(self) -> None:
        """The other half of the same instruction: unlikely, but POSSIBLE. Asserting "this one location is
        excluded" would be asserting a coin flip, so this asserts the distribution instead -- with the default
        chance of 10, the overwhelming majority of Citadark locations must be excluded, and the mechanism must
        be a roll rather than a blanket rule."""
        citadark = [
            loc for loc in self.multiworld.get_locations(1)
            if loc.parent_region is not None and loc.parent_region.name == "Citadark Isle"
            and loc.address is not None
        ]
        self.assertGreater(len(citadark), 10, "no Citadark locations to judge")
        excluded = [loc for loc in citadark if loc.progress_type == LocationProgressType.EXCLUDED]
        self.assertGreater(len(excluded), len(citadark) // 2)

    def test_trainer_defeats_can_hold_progression(self) -> None:
        self.assert_default(locations.trainer_defeat_count_location_name(1))

    def test_purifications_can_hold_progression(self) -> None:
        self.assert_default(locations.purification_location_name(1))

    def test_species_catches_can_hold_progression_only_with_their_own_toggle_on(self) -> None:
        """NARROWED 2026-09-14 (ADDENDUM 185). `progression_locations: everything` used to be enough to open
        the catch checks; it is now necessary but not sufficient, because `shadow_catch_progression` is a
        second, narrower switch and it defaults OFF. This class sets everything but not that, so the catches
        are filler-only here -- and Eevee and the Eeveelution check, which are not Shadow Pokemon, are not."""
        catches = [loc.name for loc in self.multiworld.get_locations(self.player)
                   if loc.name.startswith("Catch - ")]
        self.assertTrue(catches)
        exempt = (locations.GUARANTEED_SPECIES_LOCATION, locations.EEVEELUTION_LOCATION_NAME)
        for name in catches:
            if name in exempt:
                self.assert_default(name)
            else:
                self.assert_excluded(name)

    def test_useful_items_finally_reach_the_pool(self) -> None:
        """They had never been placed in a real seed -- see create_items' own comment. This is the payoff."""
        useful = [item for item in self.multiworld.itempool
                  if item.classification.name == "useful"]
        self.assertTrue(useful, "no useful item made it into the pool")

    def test_useful_items_repeat_up_to_the_cap_but_no_further(self) -> None:
        counts = collections.Counter(
            item.name for item in self.multiworld.itempool
            if item.classification.name == "useful"
        )
        self.assertTrue(counts)
        self.assertLessEqual(max(counts.values()), items.USEFUL_ITEM_MAX_COPIES)

    def test_filler_is_not_starved_out_by_useful_items(self) -> None:
        """The cap exists so the ADDENDUM 150 filler weighting still means something -- a pool with zero
        filler would never deliver a Poke Ball."""
        filler = [item for item in self.multiworld.itempool
                  if item.classification.name in ("filler", "trap")]
        self.assertGreater(len(filler), len(self.multiworld.itempool) // 4)

    def test_the_pool_still_supplies_every_excluded_location_with_filler(self) -> None:
        """The FillError this project hit repeatedly: a `useful` item can never sit on an EXCLUDED location,
        so filler supply must still cover them all."""
        unfilled = self.multiworld.get_unfilled_locations(self.player)
        excluded = sum(1 for loc in unfilled if loc.progress_type == LocationProgressType.EXCLUDED)
        filler = sum(1 for item in self.multiworld.itempool
                     if item.classification.name in ("filler", "trap"))
        self.assertGreaterEqual(filler, excluded)

    def test_the_item_pool_still_exactly_matches_the_location_count(self) -> None:
        self.assertEqual(len(self.multiworld.itempool),
                         len(self.multiworld.get_unfilled_locations(self.player)))


class TestWorldChecks(_ScopeBase):
    options = {
        "trainer_defeat_mode": 0,
        "randomize_chests": True,
        "shuffle_trainer_defeats": True,
        "progression_locations": 1,
    }

    def test_chests_and_trainers_open_but_purifications_stay_shut(self) -> None:
        self.assert_default(EARLIEST_CHEST)
        self.assert_default(locations.trainer_defeat_count_location_name(1))
        self.assert_excluded(locations.purification_location_name(1))


# REMOVED 2026-09-15 (ADDENDUM 237): TestOverworldOnly pinned `progression_locations: 0`, the setting that
# excluded every category except Overworld Items. That option no longer exists -- see options.py's own note
# for why its premise (that Overworld Items were real, detectable checks) turned out to be false. The
# world_checks and everything tiers below are unaffected and still cover the ladder.
class TestSpheresAreRealNotFlat(_ScopeBase):
    """Un-excluding is only sound because these have honest reachability models. If the late thresholds read
    as reachable from turn one, the generator could put an early-needed item on the last chest in the game."""

    options = {
        "trainer_defeat_mode": 0,
        "randomize_chests": True,
        "shuffle_trainer_defeats": True,
        "progression_locations": 2,
    }

    def test_the_first_chest_is_early_and_the_last_is_not(self) -> None:
        self.assertTrue(self.can_reach_location(EARLIEST_CHEST))
        self.assertFalse(self.can_reach_location(DEEPEST_CHEST))

    def test_the_last_purification_is_not_reachable_from_the_start(self) -> None:
        self.assertFalse(self.can_reach_location(
            locations.purification_location_name(locations.PURIFICATION_LOCATION_COUNT)))


if __name__ == "__main__":
    unittest.main()


class TestPurificationProgressionCap(_ScopeBase):
    """ADDENDUM 160 (player request: "can we change the 'purify X pokemon' to make it an option of how many are
    allowed to be progressive/useful? ... This will help mitigate our 'catch every shadow' problem").

    A purification threshold is the one check category a player can be locked out of by playing normally --
    every other check is something you walk up to. So the high thresholds get a dial of their own, on top of
    ProgressionLocations."""

    options = {
        "trainer_defeat_mode": 0,
        "randomize_chests": True,
        "shuffle_trainer_defeats": True,
        "progression_locations": 2,
        "purification_progression_cap": 12,
    }

    def test_thresholds_at_or_below_the_cap_can_hold_progression(self) -> None:
        for count in (1, 6, 12):
            self.assert_default(locations.purification_location_name(count))

    def test_thresholds_above_the_cap_are_filler_only(self) -> None:
        for count in (13, 24, locations.PURIFICATION_LOCATION_COUNT):
            self.assert_excluded(locations.purification_location_name(count))

    def test_the_locations_still_exist_and_still_send(self) -> None:
        """Capped means "no progression or useful item", not "removed" -- crossing the threshold still fires."""
        all_names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        for count in range(1, locations.PURIFICATION_LOCATION_COUNT + 1):
            self.assertIn(locations.purification_location_name(count), all_names)

    def test_it_does_not_touch_the_other_categories(self) -> None:
        self.assert_default(EARLIEST_CHEST)
        self.assert_default(locations.trainer_defeat_count_location_name(1))


class TestPurificationCapAtZero(_ScopeBase):
    options = {
        "trainer_defeat_mode": 0,
        "randomize_chests": True,
        "shuffle_trainer_defeats": True,
        "progression_locations": 2,
        "purification_progression_cap": 0,
    }

    def test_no_purification_check_is_load_bearing(self) -> None:
        for count in (1, locations.PURIFICATION_LOCATION_COUNT):
            self.assert_excluded(locations.purification_location_name(count))


class TestPurificationCapAtMaximum(_ScopeBase):
    options = {
        "trainer_defeat_mode": 0,
        "randomize_chests": True,
        "shuffle_trainer_defeats": True,
        "progression_locations": 2,
        "purification_progression_cap": 32,
    }

    def test_every_threshold_is_eligible_again(self) -> None:
        for count in (1, 16, locations.PURIFICATION_LOCATION_COUNT):
            self.assert_default(locations.purification_location_name(count))


class TestPurificationCapIsMootWhenNothingIsEligible(_ScopeBase):
    """The cap narrows an allowance; it can never grant one ProgressionLocations withheld."""

    options = {
        "trainer_defeat_mode": 0,
        "randomize_chests": True,
        "shuffle_trainer_defeats": True,
        "progression_locations": 1,
        "purification_progression_cap": 32,
    }

    def test_purifications_stay_excluded(self) -> None:
        self.assert_excluded(locations.purification_location_name(1))


class TestTheOptionItself(unittest.TestCase):
    def test_it_spans_the_whole_threshold_ladder_and_defaults_below_the_top(self) -> None:
        from ..options import PurificationProgressionCap

        self.assertEqual(PurificationProgressionCap.range_start, 0)
        # RAISED 2026-09-14 (ADDENDUM 185) from PURIFICATION_LOCATION_COUNT to 127 = the 83 vanilla Shadow
        # Pokemon plus the 44 "Shadow Pokemon Expansion" can add. The ceiling is what the option may promise;
        # the real per-seed bound is checked in generate_early against that seed's own expansion setting.
        self.assertEqual(PurificationProgressionCap.range_end, 127)
        self.assertGreaterEqual(PurificationProgressionCap.range_end,
                                locations.PURIFICATION_LOCATION_COUNT)
        self.assertLess(PurificationProgressionCap.default, locations.PURIFICATION_LOCATION_COUNT,
                        "the default must leave the risky tail of the real ladder filler-only")

    def test_it_is_wired_into_the_options_dataclass(self) -> None:
        from ..options import PokemonXDOptions

        self.assertIn("purification_progression_cap", PokemonXDOptions.__annotations__)
