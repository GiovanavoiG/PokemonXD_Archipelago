"""ADDENDUM 377 (2026-09-27): Agate's window reaches 0x24, and a return trip is past Eagun.

Player: "Users reported Agate replaying the Eagun cutscene upon revisiting - We need to let the floor for Agate
go high enough to match Mt Battle's entry point. Cap of 0x23 needs to be 0x24 for agate."

WHERE THE 0x23 CAME FROM: nowhere, it was derived. `_build_windows` gives every region "the next region's
opening byte, minus one", and the next opening after Agate's 0x19 is Mt. Battle's 0x24. The ladder:

    0x17 -> 0x19   Agate Village unlocked / first visit   (Eagun, the elder's house, the Relic Stone)
    0x21 -> 0x23   first Shadow Pokemon purified          (which happens AT the Relic Stone, in Agate)
    0x23 -> 0x24   Mt. Battle unlocked / first visit

The minus-one rule models "the next place opened, so this place is done", which is right where the two are
separate errands and wrong here: 0x23 is earned inside Agate and 0x24 is the errand it hands you, so the story
has not left the village at 0x24.

TWO EDITS, AND THE FIRST ONE ALONE FIXES NOTHING -- worth pinning, because the player's instruction names only
the cap. A window ceiling is not what the client writes: `target_for` takes the max of the entry floor, the
area's banked mark and `AREA_FLOOR_RULES`, and never clamps to the ceiling. Raising the ceiling makes 0x24 a
byte this module accepts as Agate's (mark banking, ADDENDUM 365's poison guard); the floor rule is what puts a
revisit there.
"""
from __future__ import annotations

import unittest

from .. import ram_client as rc
from ..game_data import story_bytes as sb

AGATE = "Agate Village"


class TestTheCeiling(unittest.TestCase):
    def test_agate_reaches_mt_battles_opening_byte(self) -> None:
        self.assertEqual(0x24, sb.REGION_STORY_WINDOW[AGATE].ceiling)
        self.assertEqual(0x24, sb.REGION_STORY_WINDOW["Mt. Battle"].floor)
        self.assertEqual(0x19, sb.REGION_STORY_WINDOW[AGATE].floor, "the floor must not have moved")

    def test_the_override_is_what_did_it_rather_than_a_changed_derivation(self) -> None:
        """The minus-one rule is right everywhere else, so this must be one named exception and not a global
        widening. Checked by confirming every OTHER region still ends one below its successor's opening."""
        # ADDENDUM 379 added Phenac City; ADDENDUM 391 added four more at the player's instruction. Asserted
        # WHOLE rather than by membership, on purpose: a new entry cannot appear without someone re-reading why
        # each one is a named exception. Every one of these six is the same case -- the region earns its
        # successor's opening byte while the player is still standing in it.
        self.assertEqual(
            {
                AGATE: 0x24,
                "Phenac City": 0x41,
                "Pyrite Town (ONBS)": 0x3E,
                "Phenac City (Post-Sixes)": 0x4E,
                "Outskirt Stand": 0x62,
                "Snagem Hideout": 0x64,
            },
            dict(sb.REGION_CEILING_OVERRIDES),
        )
        floors = sorted({t.after for t in sb.TRANSITIONS for _r in t.opens_regions})
        for region, window in sb.REGION_STORY_WINDOW.items():
            if region in sb.REGION_CEILING_OVERRIDES:
                continue
            later = [f for f in floors if f > window.floor]
            if later:
                self.assertEqual(later[0] - 1, window.ceiling, f"{region} moved and should not have")

    def test_0x24_is_a_rung_the_game_rests_on(self) -> None:
        self.assertTrue(sb.byte_is_reachable(0x24))

    def test_the_overlap_with_mt_battle_is_deliberate_and_only_one_byte(self) -> None:
        """Agate and Mt. Battle now both contain 0x24. That is the point -- it is the byte Agate hands you and
        the byte Mt. Battle opens on -- and it must not be more than that one rung."""
        agate, mt = sb.REGION_STORY_WINDOW[AGATE], sb.REGION_STORY_WINDOW["Mt. Battle"]
        shared = {b for b in range(agate.floor, agate.ceiling + 1) if mt.contains(b)}
        self.assertEqual({0x24}, shared)


class TestTheReturnTripIsPastEagun(unittest.TestCase):
    def _memory(self, mark: "int | None") -> "rc.AreaStoryByteMemory":
        memory = rc.AreaStoryByteMemory()
        if mark is not None:
            memory.visited.add(AGATE)
            memory.highest_by_region[AGATE] = mark
        return memory

    def test_a_first_visit_still_arrives_at_eagun(self) -> None:
        """The cutscene is Agate's first-visit content and must still happen. This rule is about the revisit."""
        self.assertEqual(0x19, self._memory(None).target_for(AGATE))
        self.assertEqual(0x19, self._memory(0x19).target_for(AGATE))

    def test_a_visit_before_the_purification_is_unchanged(self) -> None:
        self.assertEqual(0x21, self._memory(0x21).target_for(AGATE))

    def test_once_the_relic_stone_purification_happened_a_revisit_is_0x24(self) -> None:
        """The reported bug. 0x21 -> 0x23 is "first Shadow Pokemon purified", which happens at Agate's own
        Relic Stone, so an Agate mark of 0x23 means the player really finished Agate's errand."""
        self.assertEqual(0x24, self._memory(0x23).target_for(AGATE))
        self.assertEqual(0x24, self._memory(0x24).target_for(AGATE))

    def test_a_later_mark_is_not_dragged_back_down(self) -> None:
        self.assertGreaterEqual(self._memory(0x24).target_for(AGATE), 0x24)

    def test_our_own_arrival_write_cannot_satisfy_the_condition(self) -> None:
        """ADDENDUM 277, which is what makes the condition mean "the game moved the byte here" rather than "we
        wrote 0x19 on arrival". Without this the rule would talk itself up on the second visit."""
        memory = rc.AreaStoryByteMemory()
        memory.last_written_target = 0x19
        memory.observe(AGATE, 0x19)
        self.assertNotIn(AGATE, memory.highest_by_region)
        self.assertEqual(0x19, memory.target_for(AGATE))

    def test_the_rule_can_bind_which_is_what_the_ceiling_was_blocking(self) -> None:
        rules = [r for r in sb.AREA_FLOOR_RULES if r.target == AGATE]
        self.assertEqual(1, len(rules))
        self.assertEqual(0x24, rules[0].floor)
        self.assertEqual(((AGATE, 0x23),), rules[0].requires)
        self.assertGreater(rules[0].floor, sb.area_entry_floor(AGATE))
        self.assertLessEqual(rules[0].floor, sb.REGION_STORY_WINDOW[AGATE].ceiling,
                             "a floor rule above its own region's ceiling writes a byte the module does not "
                             "accept as that region's -- which is the cap the player asked to raise")


class TestNothingElseMoved(unittest.TestCase):
    def test_0x24_is_now_a_legitimate_agate_mark(self) -> None:
        """What the ceiling actually governs. Before this, a real 0x24 seen while standing in Agate was above
        the area's accepted range; now it banks, which is what lets the rule fire on a later visit."""
        memory = rc.AreaStoryByteMemory()
        memory.observe(AGATE, 0x24)
        self.assertEqual(0x24, memory.highest_by_region.get(AGATE))

    def test_the_poison_guard_still_catches_a_genuinely_foreign_byte(self) -> None:
        """ADDENDUM 365 is widened by exactly one rung, not disabled. A Pyrite floor standing in Agate is still
        poison."""
        self.assertEqual(0x24, sb.AREA_GUARD_CEILINGS[AGATE])
        self.assertFalse(sb.poisoned_byte(AGATE, 0x24))
        self.assertTrue(sb.poisoned_byte(AGATE, 0x30))

    def test_the_level_ramp_cannot_have_moved(self) -> None:
        """ADDENDUM 329's fence. `_path_floor` reads `region_floor`, which is the window's FLOOR -- and no floor
        moved here. Asserted rather than assumed, because a ceiling edit looks exactly like the kind of change
        that re-ordered the ramp the first time."""
        from ..randomizer import path_level_scaling as pls

        self.assertEqual(0x19, sb.region_floor(AGATE))
        known = {r for r in pls.region_by_trainer_index().values() if r}
        tiers = pls.path_tiers(known)
        self.assertEqual(0, pls.tier_index(AGATE, tiers, known), "Agate is still the ramp's first rung")

    def test_mt_battles_own_floor_and_unlock_are_untouched(self) -> None:
        self.assertEqual(0x24, sb.region_floor("Mt. Battle"))
        self.assertEqual(0x24, sb.area_entry_floor("Mt. Battle"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
