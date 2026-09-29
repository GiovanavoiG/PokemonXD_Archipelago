"""ADDENDUM 379 (2026-09-27): Gateon's first visit is 0x10, Phenac's window reaches 0x41, and neither is the
Robo Kyogre gate.

Player: "Also, raise Gateon's cap by one on first visit. Also make sure Gateon's cap doesn't interfere with the
kyogre parts. Raise Phenac City's cap by one as well."

TWO DIFFERENT NUMBERS ARE CALLED "GATEON'S CAP", and the middle instruction is why that has to be said out loud:

    ALWAYS_OPEN_FIRST_VISIT["Gateon Port"]   0x0F -> 0x10   the byte a FIRST visit writes  <- this one moved
    ram_client.GATEON_STORY_CEILING          0x6E           the Robo Kyogre gate           <- untouched

The second one is load-bearing in a way a comment cannot protect: 0x6E is Citadark Isle's ENTIRE window
(0x6E..0x6E), so raising THAT cap by one would put the clamp above Citadark's own floor and hand the unlock to a
player holding no Parts at all. `TestTheKyogreGateIsUntouched` pins the value, the relationship to Citadark, and
the fact that the two caps cannot be confused for each other by being equal or adjacent.

PHENAC'S RAISE CLOSED A REAL INCONSISTENCY, found while measuring rather than reasoned about. Its derived window
was 0x3E..0x40 while ADDENDUM 331's entry-floor override writes 0x41 on every arrival -- so the byte this client
puts in Phenac sat one rung ABOVE the window the module calls Phenac's. And 0x40 is not a rung the game rests on
at all (`byte_is_reachable(0x40)` is False): the ladder runs 0x3E -> 0x3F -> 0x41, and the derived minus-one rule
landed on the gap. 0x41 is the player's "+1", the byte already being written, and a real rung.
"""
from __future__ import annotations

import unittest

from .. import ram_client as rc
from ..game_data import story_bytes as sb

GATEON = "Gateon Port"
PHENAC = "Phenac City"


class TestGateonsFirstVisit(unittest.TestCase):
    def test_it_is_one_rung_later(self) -> None:
        self.assertEqual(0x10, sb.ALWAYS_OPEN_FIRST_VISIT[GATEON])
        self.assertEqual(0x10, sb.area_entry_floor(GATEON))
        self.assertEqual(0x10, sb.region_floor(GATEON))
        self.assertEqual(0x10, rc.AreaStoryByteMemory().target_for(GATEON))

    def test_0x10_is_a_rung_the_game_rests_on(self) -> None:
        """The ladder has a self-transition there -- "Krane Memos 1 and 2 are in the bag" -- so it is a value the
        story really holds, not a gap like the one Phenac's old ceiling landed in."""
        self.assertTrue(sb.byte_is_reachable(0x10))
        self.assertIn(0x10, {t.after for t in sb.TRANSITIONS})

    def test_the_other_two_always_open_bytes_did_not_move(self) -> None:
        self.assertEqual(0x00, sb.ALWAYS_OPEN_FIRST_VISIT["Pokemon HQ Lab"])
        self.assertEqual(0x03, sb.ALWAYS_OPEN_FIRST_VISIT["Kaminko's House"])

    def test_gateon_still_has_no_static_window(self) -> None:
        """ADDENDUM 279's shape: always-open regions carry a first-visit byte and no window. Raising the byte
        must not have accidentally given Gateon one."""
        self.assertIn(GATEON, sb.ALWAYS_OPEN_REGIONS)
        self.assertNotIn(GATEON, sb.REGION_STORY_WINDOW)

    def test_gateons_later_floor_rules_are_unchanged_and_still_above_it(self) -> None:
        """Both rules have to stay ABOVE the first-visit byte or they can never bind (ADDENDUM 247)."""
        floors = sorted(r.floor for r in sb.AREA_FLOOR_RULES if r.target == GATEON)
        self.assertEqual([0x51, 0x57], floors)
        for floor in floors:
            self.assertGreater(floor, sb.area_entry_floor(GATEON))


class TestTheKyogreGateIsUntouched(unittest.TestCase):
    """The instruction that matters most, because getting it wrong gives away a progression unlock."""

    def test_the_clamp_and_the_lift_are_what_they_were(self) -> None:
        self.assertEqual(0x6E, rc.GATEON_STORY_CEILING)
        self.assertEqual(0x76, rc.STORY_OVERRIDE_VALUE)
        self.assertEqual(rc.GATEON_STORY_CEILING, rc.StoryByteOverride.ceiling)
        self.assertEqual(rc.STORY_OVERRIDE_VALUE, rc.StoryByteOverride.value)

    def test_the_clamp_is_not_above_citadarks_own_floor(self) -> None:
        """WHY THE KYOGRE CAP MAY NOT BE RAISED. Citadark's window is one byte wide, and the clamp sits exactly
        on it: held there, a player without the Parts is at Citadark's floor and no further. One higher and the
        clamp would be past it, which is the unlock the eight Parts are for."""
        citadark = sb.REGION_STORY_WINDOW["Citadark Isle"]
        self.assertEqual(0x6E, citadark.floor)
        self.assertEqual(0x6E, citadark.ceiling)
        self.assertLessEqual(rc.GATEON_STORY_CEILING, citadark.floor)

    def test_the_lift_is_above_the_clamp_or_the_parts_do_nothing(self) -> None:
        self.assertGreater(rc.STORY_OVERRIDE_VALUE, rc.GATEON_STORY_CEILING)

    def test_the_two_gateon_caps_cannot_be_mistaken_for_each_other(self) -> None:
        """They are different numbers for different jobs, and this addendum moved one of them. If they ever
        became equal or adjacent, "raise Gateon's cap" would be genuinely ambiguous in the source as well as in
        the request."""
        self.assertLess(sb.ALWAYS_OPEN_FIRST_VISIT[GATEON] + 1, rc.GATEON_STORY_CEILING)

    def test_the_override_owns_the_byte_while_it_is_active(self) -> None:
        """The interlock that keeps Gateon's floor write from racing the unlock: `check_area_story_memory`
        returns outright while the override is active, so no floor -- 0x10, 0x51 or 0x57 -- can be written over
        the lifted byte, and `observe()` cannot bank it as Gateon's mark either."""
        import pathlib

        source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        block = source[source.index("async def check_area_story_memory"):]
        block = block[:block.index("\nasync def ", 1)]
        self.assertIn("if ctx.story_byte_override.active:", block)
        guarded = block[block.index("if ctx.story_byte_override.active:"):]
        self.assertIn("return", guarded[:guarded.index("room_id = ctx.room_tracker.current")])


class TestPhenacsWindow(unittest.TestCase):
    def test_it_reaches_0x41(self) -> None:
        self.assertEqual(0x41, sb.REGION_STORY_WINDOW[PHENAC].ceiling)
        self.assertEqual(0x3E, sb.REGION_STORY_WINDOW[PHENAC].floor, "the floor must not have moved")

    def test_the_window_now_contains_the_byte_we_actually_write(self) -> None:
        """The inconsistency this closed. ADDENDUM 331's override writes 0x41 on every Phenac arrival, and the
        window said Phenac ended at 0x40 -- so our own arrival state was outside the range the module treats as
        Phenac's, which is what `observe()` and ADDENDUM 365's guard are both built on."""
        entry = sb.area_entry_floor(PHENAC)
        self.assertEqual(0x41, entry)
        self.assertTrue(sb.REGION_STORY_WINDOW[PHENAC].contains(entry))

    def test_the_old_ceiling_was_not_even_a_real_rung(self) -> None:
        """0x3E -> 0x3F -> 0x41: there is no 0x40. The derived minus-one rule landed the ceiling in the gap,
        which is exactly what ADDENDUM 350 added `byte_is_reachable` to catch."""
        self.assertFalse(sb.byte_is_reachable(0x40))
        self.assertTrue(sb.byte_is_reachable(0x41))

    def test_the_other_phenac_tiers_did_not_move(self) -> None:
        self.assertEqual((0x44, 0x45), (sb.REGION_STORY_WINDOW["Phenac City (Mayor's House)"].floor,
                                        sb.REGION_STORY_WINDOW["Phenac City (Mayor's House)"].ceiling))
        # RETARGETED by ADDENDUM 391: Post-Sixes' ceiling moved 0x4D -> 0x4E at the player's instruction. What
        # this test is for is that ADDENDUM 379's Phenac City change did not drag the other tiers with it, and
        # the FLOOR is what proves that -- so the floor stays pinned and the ceiling reads from the override.
        self.assertEqual(0x46, sb.REGION_STORY_WINDOW["Phenac City (Post-Sixes)"].floor)
        self.assertEqual(sb.REGION_CEILING_OVERRIDES["Phenac City (Post-Sixes)"],
                         sb.REGION_STORY_WINDOW["Phenac City (Post-Sixes)"].ceiling)

    def test_it_does_not_reach_the_next_tier(self) -> None:
        """0x41 must stay below the Mayor's House at 0x44, or two tiers of one town overlap for no reason --
        unlike Agate/Mt. Battle, where the single shared rung is the point (ADDENDUM 377)."""
        self.assertLess(sb.REGION_STORY_WINDOW[PHENAC].ceiling,
                        sb.REGION_STORY_WINDOW["Phenac City (Mayor's House)"].floor)


class TestNeitherChangeMovedTheLevelRamp(unittest.TestCase):
    """ADDENDUM 329's fence, re-checked for both edits. Gateon is off the ramp entirely (ADDENDUM 367) and
    Phenac's FLOOR did not move, so no tier can have shifted."""

    def test_the_ramp_is_unchanged(self) -> None:
        from ..randomizer import path_level_scaling as pls

        self.assertIn(GATEON, pls.PATH_EXCLUDED_REGIONS)
        self.assertEqual(0x3E, sb.region_floor(PHENAC))
        known = {r for r in pls.region_by_trainer_index().values() if r}
        tiers = pls.path_tiers(known)
        self.assertEqual(13, len(tiers))
        self.assertIsNone(pls.tier_index(GATEON, tiers, known))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
