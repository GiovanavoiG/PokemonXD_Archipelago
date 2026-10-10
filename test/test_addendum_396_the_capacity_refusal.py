"""ADDENDUM 396 (2026-09-29) -- more progression items than locations is refused, not filled.

An Archipelago maintainer rolled a thousand random-option seeds and reported two fill failures:

    Remaining locations are invalid. (6)
    Fill.FillError: Not enough locations for progression items. (32)

    "The first 6 are interesting because I assume you don't have an issue of a too small sphere 1. So I
     assume there's a logic bug somewhere. The others can probably be handled with an OptionError,
     requiring at least X sanities to be on"

THEY ARE ONE FAULT, NOT TWO. A 500-seed roll here reproduced both (20 and 1 against 336 clean seeds), and
every one of the 21 failures had progression items outnumbering the non-EXCLUDED locations able to hold
one. Zero false positives and zero false negatives against that roll: the count IS the diagnosis.

Which of the two errors Archipelago raises is an accident of its own bookkeeping, not a second cause.
`Fill.fill_restrictive` raises `Remaining locations are invalid` only when unplaced items AND unfilled
locations are both left over; its accessibility-cleanup pass hands a placement back when the location turns
out to be unreachable in the swept state, so a seed one item short can end the step with locations in hand
and take that branch. A seed further short runs `defaultlocations` to empty, takes no branch at all, and
surfaces later as `Not enough locations for progression items`. The reproduced `Remaining locations are
invalid` seed was short by exactly one -- 7 progression items, 6 locations -- which is the narrowest
shortfall that can exist. There is no sphere-1 logic bug behind it.

WHICH SEEDS. Every failure had `Randomize Chests`, `Randomize Shops` and `Shuffle Trainer Defeats` all
three off. That leaves catches and purifications as the only large categories, and both are filler-only
below `progression_locations = everything`, so capacity collapsed to 6 (the five Krane Memos and
Catch - Eevee) or, with `everything` but catches still off, to the purification cap.

WHERE THE GUARD LIVES. `create_items` -- because that is the only place in the world where both honest
numbers exist at once. `default_capacity` was already computed there for ADDENDUM 150's useful-item budget,
and `max(0, ...)` was quietly swallowing the shortfall. Computing it in `generate_early` instead would mean
reimplementing locations.py's exclusion ladder and keeping two copies of it honest, which ADDENDA 243 and
257 refuse.

THE GUARD THAT WAS THERE. `generate_early` held a count check that compared every progression ROW in
`ITEM_TABLE` (34) against the whole "Overworld Items" NAME GROUP (51) plus the trainer defeats. Its floor
was 52 against a ceiling of 34, so it could never fire -- the condition-that-cannot-bind ADDENDA 247 and
298 refuse -- and both of its numbers were the wrong ones anyway: the table's progression rows are not a
seed's pool, and a name group is not a location count. It is retired here, not moved.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from BaseClasses import LocationProgressType

from . import PokemonXDTestBase
from .. import items, locations


# ADDENDUM 404: NO LEGAL SEED CAN STARVE ANY MORE. Chests are always checks, and they sit in every area including
# the always-open ones. Measured at the tightest legal options -- shops and trainer defeats off, `world_checks`
# scope, catches and purifications filler-only, Citadark weighting 0, and every progression source turned up
# (40 Robo Kyogre Parts, travel unlocks, key items, the scooter): capacity 76 against 58 progression items, a
# margin of at least 18, and at least 14 eligible locations open in sphere zero. 0 of 30 seeds failed fill.
#
# The guard stays as a backstop. It computes from the real numbers -- the same two `create_items` already had --
# so it is not a condition pretending to protect something; it is the alarm for a future change that grows the
# pool or shrinks a category. The margin is pinned below so that change is noticed here first, not in fill.
TIGHTEST_LEGAL = {
    "randomize_shops": False,
    "shuffle_trainer_defeats": False,
    "citadark_progression_chance": 0,
    "shadow_catch_progression": False,
    "purification_progression_cap": 0,
    "robo_kyogre_parts_unlock_citadark": True,
    "robo_kyogre_parts_available": 40,
    "robo_kyogre_parts_required": 1,
    "randomize_travel_locations": True,
    "key_item_shuffle": True,
    "shuffle_scooter_upgrade": True,
}


class _Options:
    """A stand-in options object for `_capacity_refusal`, which reads attributes and nothing else."""

    def __init__(self, **values) -> None:
        defaults = {"randomize_shops": 1, "shuffle_trainer_defeats": 1, 
                    "shadow_catch_progression": 1, "purification_progression_cap": 30}
        defaults.update(values)
        for key, value in defaults.items():
            setattr(self, key, value)


class _World:
    def __init__(self, **values) -> None:
        self.options = _Options(**values)
        self.player_name = "Tester1"


class TestNoLegalSeedCanStarve(PokemonXDTestBase):
    options = TIGHTEST_LEGAL

    def test_the_tightest_legal_options_still_leave_room(self) -> None:
        """If this margin shrinks, a pool or category change is eating into it -- read why before shipping."""
        eligible = [
            location for location in self.multiworld.get_locations(self.player)
            if location.address is not None and location.progress_type is not LocationProgressType.EXCLUDED
        ]
        progression = sum(1 for item in self.multiworld.itempool if item.player == self.player and item.advancement)
        self.assertGreaterEqual(len(eligible) - progression, 18)

    def test_sphere_zero_has_room_too(self) -> None:
        """The count was never the whole story (ADDENDUM 397): fill also needs somewhere to start."""
        from BaseClasses import CollectionState

        empty = CollectionState(self.multiworld)
        open_now = [
            location for location in self.multiworld.get_locations(self.player)
            if location.address is not None and location.progress_type is not LocationProgressType.EXCLUDED
            and location.can_reach(empty)
        ]
        self.assertGreaterEqual(len(open_now), 14)


class TestTheRefusalIsActionable(unittest.TestCase):
    """A refusal that names a lever the player already pulled reads as a bug in the refusal."""

    def test_the_refusal_reports_a_real_shortfall(self) -> None:
        """Restored. ADDENDUM 397's edit to this file deleted `TestTheStarvedSeedIsRefused` by accident -- a text
        replacement that ran through the class -- and the suite stayed green because a deleted test cannot fail.
        No legal seed can starve now, so the numbers are checked through the builder instead."""
        from .. import _capacity_refusal

        message = _capacity_refusal(_World(), 40, 10)
        self.assertIn("40 progression items but only 10 location", message)
        self.assertIn("To open up 30 more", message)
        self.assertIn("cannot be filled", message)

    def test_it_names_the_categories_that_are_off(self) -> None:
        from .. import _capacity_refusal

        message = _capacity_refusal(_World(randomize_shops=0, shuffle_trainer_defeats=0), 40, 10)
        for phrase in ("Shuffle Trainer Defeats", "Randomize Shops"):
            self.assertIn(phrase, message)
        self.assertNotIn("Randomize Chests", message, "ADDENDUM 404: chests are not an option to turn on")

    def test_it_does_not_name_a_category_that_is_already_on(self) -> None:
        """Asserted against the builder directly.

        No REAL seed can starve with one of the three on -- chests alone open 78 locations against a
        58-item ceiling, and defeats open more -- so there is no world to build that would exercise this.
        Refusing to test it for that reason would leave the branch unread, and a message that tells a
        player to turn on something they already turned on is the most likely way this goes wrong later.
        """
        from .. import _capacity_refusal

        class _Options:
            randomize_chests = 1
            randomize_shops = 0
            shuffle_trainer_defeats = 0
            shadow_catch_progression = 1
            purification_progression_cap = 30

        class _World:
            options = _Options()
            player_name = "Tester1"

        message = _capacity_refusal(_World(), 40, 10)
        self.assertNotIn("Randomize Chests", message)
        self.assertIn("Randomize Shops", message)
        self.assertIn("Shuffle Trainer Defeats", message)

    def test_it_says_so_plainly_when_nothing_is_left_to_widen(self) -> None:
        """Every lever already pulled means the item pool is the problem; the message must not invent one."""
        from .. import _capacity_refusal

        class _Options:
            randomize_chests = 1
            randomize_shops = 1
            shuffle_trainer_defeats = 1
            shadow_catch_progression = 1
            purification_progression_cap = 30

        class _World:
            options = _Options()
            player_name = "Tester1"

        message = _capacity_refusal(_World(), 40, 10)
        self.assertIn("already enabled", message)
        self.assertIn("Robo Kyogre Parts Available", message)

    def test_it_points_at_the_catch_toggle_when_the_scope_is_already_open(self) -> None:
        """With the scope already at `everything`, the next-widest lever is the catch toggle, not the scope."""
        from .. import _capacity_refusal

        message = _capacity_refusal(_World(shadow_catch_progression=0), 40, 10)
        self.assertIn("Shadow Pokemon Catch Checks Can Hold Progression", message)
        self.assertNotIn("set 'Checks That Can Hold Progression'", message)


class TestTheGuardMeasuresWhatFillMeasures(PokemonXDTestBase):
    """The capacity number has to be the one Archipelago's fill will see, or the guard is decoration."""

    options = {}

    def test_capacity_is_the_count_of_non_excluded_locations(self) -> None:
        live = [
            location for location in self.multiworld.get_locations(self.player)
            if location.address is not None
        ]
        capacity = sum(
            1 for location in live if location.progress_type is not LocationProgressType.EXCLUDED
        )
        progression = sum(
            1 for item in self.multiworld.itempool
            if item.player == self.player and item.advancement
        )
        # A default seed is nowhere near the edge; the point is that the two numbers are commensurable.
        self.assertGreater(capacity, progression)

    def test_a_default_seed_is_not_refused(self) -> None:
        self.assertTrue(self.multiworld.itempool)


class TestTheRetiredGuard(unittest.TestCase):
    def test_the_old_count_check_could_never_have_fired(self) -> None:
        """Its ceiling was the table's progression rows; its floor was a name group four times larger."""
        table_progression = sum(
            1 for data in items.ITEM_TABLE.values()
            if data.classification == items.ItemClassification.progression
        )
        old_floor = 1 + len(locations.LOCATION_NAME_GROUPS["Overworld Items"])
        self.assertLessEqual(table_progression, old_floor)

    def test_it_is_gone_from_generate_early(self) -> None:
        source = (Path(__file__).resolve().parent.parent / "__init__.py").read_text(encoding="utf-8")
        self.assertNotIn("available_location_count", source)
        self.assertIn("_capacity_refusal", source)

    def test_the_new_guard_reads_the_capacity_create_items_already_computed(self) -> None:
        """One source of truth: the refusal compares the same two locals the useful-item budget uses."""
        source = (Path(__file__).resolve().parent.parent / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("if len(item_pool) > default_capacity:", source)
        self.assertIn("useful_budget = max(0, default_capacity - len(item_pool))", source)
