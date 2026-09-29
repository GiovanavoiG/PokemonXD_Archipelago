"""ADDENDUM 365 (2026-09-26): a ceiling per area, so a foreign byte cannot settle in it.

Player: *"can you add a guard to ensure that areas don't get poisoned? for example, we know cipher lab's byte
doesn't go past 0x2E - if we ever detect it higher in that location, we should write it back to the highest
valid byte that we saw in that area. Do this only for areas you're confident on the range."*

This is the repair for ADDENDUM 363 Part 3 -- a save standing in the Cipher Lab reading 0x3C, six story beats
above anything the lab can reach, with "was 0x28" beside it.

THE TWO HALVES, and the second is the one that makes it safe to ship:

  * THE CEILING IS THE TRIGGER. Derived per area from `REGION_STORY_WINDOW`, widened by the area's own legal
    exits, disqualified where this client's own floor machinery would write above it or where the place has an
    always-open member. Thirteen of eighteen live regions qualify.

  * THE FLOOR-VALUE TEST IS THE DECISION. The mod holds the story byte at "what the room should be built
    from", not "how far the player has got", so a high byte in a low area is NORMAL when they walked there --
    nothing writes on a walk. Clamping on the ceiling alone would roll back a player who strolled from the
    Outskirt Stand into Snagem at 0x6C. So the value must ALSO be one this client writes as a floor somewhere
    else, which is exactly the ADDENDUM 363 ratchet's signature.

NOTHING IS HAND-TYPED, the player's own 0x2E included: the lab's ceiling comes out of the ladder as 0x2F and
is widened to 0x30 by its own exit transition. Loose is the safe direction -- a ceiling too high misses some
poisoning, which is the status quo; one too low ends a run.
"""
from __future__ import annotations

import unittest
from unittest import mock

from .. import ram_client as rc
from ..game_data import chest_regions, story_bytes as sb

LAB = "Cipher Lab"


class TestTheTableIsDerivedNotTyped(unittest.TestCase):
    def test_every_guarded_area_is_a_region_the_client_can_actually_name(self) -> None:
        """A ceiling for a name `region_for_room` never returns is a rule nobody can trigger (ADDENDA
        247/298). `SS Libra (stranded)` and both outer Key Lair tiers are exactly that."""
        live = {chest_regions.region_for_room(room) for room in range(1200)} - {None}
        for region in sb.AREA_GUARD_CEILINGS:
            self.assertIn(region, live, region)

    def test_no_always_open_area_carries_a_ceiling(self) -> None:
        """Kaminko's House is reachable at any point in the story, so the byte while standing there says
        nothing about the place -- and its live name's window stops at 0x59."""
        for region in sb.AREA_GUARD_CEILINGS:
            self.assertNotIn(region, sb.ALWAYS_OPEN_REGIONS, region)
        self.assertNotIn("Kaminko's House (Robo Groudon)", sb.AREA_GUARD_CEILINGS)
        self.assertNotIn("Gateon Port", sb.AREA_GUARD_CEILINGS)
        self.assertNotIn("Pokemon HQ Lab", sb.AREA_GUARD_CEILINGS)

    def test_an_area_whose_own_floor_machinery_writes_higher_is_left_out(self) -> None:
        """Citadark's arrival writes 0x71 against a place whose window is 0x6E-0x6E, so no ceiling can hold
        both it and the guard. Widening to fit would make the guard agree with what it is meant to catch.

        Pyrite is NOT an example of this, though it looked like one while the span was a single tier: its
        0x3C rule sits above `Pyrite Town`'s own 0x30-0x34 window but inside the PLACE's 0x30-0x3D, which is
        the span the guard actually uses."""
        self.assertNotIn("Citadark Isle", sb.AREA_GUARD_CEILINGS)
        # RETARGETED by ADDENDUM 391: was 0x3E. Raising Pyrite Town (ONBS)'s own ceiling to 0x3E widened the
        # PLACE's span, and the guard then adds the exit rung on top, so 0x3F. Looser, which this module's own
        # note calls the safe direction -- "a ceiling too high misses some poisoning while one too low clamps
        # real progress."
        self.assertEqual(sb.AREA_GUARD_CEILINGS["Pyrite Town"], 0x3F)

    def test_a_collapsed_place_is_guarded_as_a_whole(self) -> None:
        """`region_for_room` returns one name for all three Key Lair tiers, so the ceiling must cover the
        whole place. Taking the middle tier's own 0x69 would clamp a player standing in the deep section."""
        self.assertEqual(sb.AREA_GUARD_CEILINGS["Cipher Key Lair"], 0x6E)

    def test_every_tier_of_a_place_is_held_to_the_same_ceiling(self) -> None:
        """The correction the ADDENDA 177/331 tests forced. `region_for_room` returns "Phenac City" for the
        town's rooms all game while the ladder walks it 0x3E -> 0x4D, so a per-tier ceiling of 0x41 would
        clamp an ordinary 0x4C mark. All three names get the place's own ceiling."""
        # RETARGETED by ADDENDUM 391: was 0x4E, now 0x50, because Post-Sixes' own ceiling moved 0x4D -> 0x4E
        # and the place's guard takes the exit rung above that. Still one ceiling shared by all three names,
        # which is what this test is actually about.
        for tier in ("Phenac City", "Phenac City (Mayor's House)", "Phenac City (Post-Sixes)"):
            self.assertEqual(sb.AREA_GUARD_CEILINGS[tier], 0x50, tier)
        self.assertFalse(sb.poisoned_byte("Phenac City", 0x4C))

    def test_the_ceiling_includes_the_areas_own_exit(self) -> None:
        """The lab's window ends at 0x2F and it hands off at 0x2F -> 0x30, a write that can land while the
        player is still inside. Clamping it would break the Pyrite unlock permanently."""
        self.assertEqual(sb.REGION_STORY_WINDOW[LAB].ceiling, 0x2F)
        self.assertEqual(sb.AREA_GUARD_CEILINGS[LAB], 0x30)

    def test_the_special_write_constants_match_ram_clients_own(self) -> None:
        """`SPECIAL_AREA_WRITES` exists so the derivation can see writers that live in ram_client. It must not
        become a second source of truth for their values."""
        self.assertEqual(sb.SPECIAL_AREA_WRITES["Citadark Isle"], rc.CITADARK_ENTRY_FLOOR)
        self.assertEqual(sb.SPECIAL_AREA_WRITES["SS Libra"], rc.SS_LIBRA_SCOOTER_FLOOR)
        self.assertEqual(sb.SPECIAL_AREA_WRITES["Gateon Port"], rc.STORY_OVERRIDE_VALUE)
        self.assertEqual(sb.SPECIAL_AREA_WRITES["Kaminko's House (Robo Groudon)"], rc.SCOOTER_HOLD_FLOOR)

    def test_every_ceiling_is_above_that_areas_own_floor(self) -> None:
        for region, ceiling in sb.AREA_GUARD_CEILINGS.items():
            floor = sb.area_entry_floor(region)
            if floor is not None:
                self.assertLessEqual(floor, ceiling, region)


class TestWhatCountsAsPoisoned(unittest.TestCase):
    def test_the_reported_value(self) -> None:
        """0x3C is Pyrite's visit-2 floor. In the Cipher Lab it is nobody's business but Pyrite's."""
        self.assertTrue(sb.poisoned_byte(LAB, 0x3C))

    def test_a_legal_exit_is_not_poison(self) -> None:
        self.assertFalse(sb.poisoned_byte(LAB, 0x30))

    def test_a_high_byte_that_is_nobodys_floor_is_not_poison(self) -> None:
        """The walked-in case. Nothing in this client writes 0x6C, so a player who strolled into Snagem at
        0x6C is left alone -- clamping them would roll back the endgame."""
        self.assertNotIn(0x6C, sb.OUR_FLOOR_VALUES)
        self.assertFalse(sb.poisoned_byte("Snagem Hideout", 0x6C))

    def test_an_unguarded_area_never_reports_poison(self) -> None:
        for region in ("Gateon Port", "Citadark Isle", "Pokemon HQ Lab",
                       "Kaminko's House (Robo Groudon)"):
            self.assertFalse(sb.poisoned_byte(region, 0x64), region)

    def test_it_never_guesses(self) -> None:
        self.assertFalse(sb.poisoned_byte(None, 0x3C))
        self.assertFalse(sb.poisoned_byte(LAB, None))
        self.assertFalse(sb.poisoned_byte("Not A Region", 0x3C))


class TestTheClamp(unittest.TestCase):
    def _memory(self, mark: "int | None" = 0x28) -> "rc.AreaStoryByteMemory":
        memory = rc.AreaStoryByteMemory()
        if mark is not None:
            memory.visited.add(LAB)
            memory.highest_by_region[LAB] = mark
        return memory

    def test_it_puts_the_reported_save_back(self) -> None:
        memory = self._memory()
        with mock.patch.object(rc, "poke_story_byte", return_value=True) as poke:
            note = memory.clamp_poisoned_byte(0x8000, LAB, 0x3C)
        poke.assert_called_once_with(0x8000, 0x28)
        self.assertIn("0x28", note)
        self.assertEqual(memory.poison_clamps, 1)
        self.assertEqual(memory.last_poison_clamp, (LAB, 0x3C, 0x28))

    def test_it_claims_the_write_so_the_mark_is_not_banked_back(self) -> None:
        """ADDENDA 288/293's one ownership channel. Without this, `observe()` records the value we just wrote
        as the area's mark -- which is the corruption, one step later."""
        memory = self._memory()
        with mock.patch.object(rc, "poke_story_byte", return_value=True):
            memory.clamp_poisoned_byte(0x8000, LAB, 0x3C)
        self.assertEqual(memory.last_written_target, 0x28)
        memory.observe(LAB, 0x28)
        self.assertEqual(memory.highest_by_region[LAB], 0x28)

    def test_with_no_mark_it_declines_rather_than_writing_the_floor(self) -> None:
        """Writing the floor here would be this guard doing the ratchet's job for it."""
        memory = self._memory(mark=None)
        with mock.patch.object(rc, "poke_story_byte") as poke:
            self.assertIsNone(memory.clamp_poisoned_byte(0x8000, LAB, 0x3C))
        poke.assert_not_called()
        self.assertEqual(memory.declined_poison_no_mark, 1)

    def test_it_stands_down_while_another_writer_holds_the_byte(self) -> None:
        memory = self._memory()
        with mock.patch.object(rc, "poke_story_byte") as poke:
            self.assertIsNone(memory.clamp_poisoned_byte(0x8000, LAB, 0x3C, busy=True))
        poke.assert_not_called()
        self.assertEqual(memory.declined_poison_busy, 1)

    def test_it_stands_down_during_a_map_visit(self) -> None:
        """A hover write is SUPPOSED to be another area's floor. That is the feature, and `left_map_screen`
        owns undoing it."""
        memory = self._memory()
        memory._write_outstanding = True
        with mock.patch.object(rc, "poke_story_byte") as poke:
            self.assertIsNone(memory.clamp_poisoned_byte(0x8000, LAB, 0x3C))
        poke.assert_not_called()

    def test_it_never_erases_a_won_game(self) -> None:
        """ADDENDUM 272's rule, for ADDENDUM 272's reason: permanent the moment they save."""
        memory = self._memory()
        with mock.patch.object(rc, "poke_story_byte") as poke:
            self.assertIsNone(memory.clamp_poisoned_byte(0x8000, LAB, rc.VICTORY_STORY_BYTE))
        poke.assert_not_called()

    def test_a_failed_write_reports_nothing_rather_than_claiming_success(self) -> None:
        memory = self._memory()
        with mock.patch.object(rc, "poke_story_byte", side_effect=RuntimeError("no")):
            self.assertIsNone(memory.clamp_poisoned_byte(0x8000, LAB, 0x3C))
        self.assertEqual(memory.poison_clamps, 0)

    def test_it_does_nothing_on_an_ordinary_tick(self) -> None:
        memory = self._memory()
        with mock.patch.object(rc, "poke_story_byte") as poke:
            for byte in (0x26, 0x28, 0x2F, 0x30):
                self.assertIsNone(memory.clamp_poisoned_byte(0x8000, LAB, byte))
        poke.assert_not_called()


class TestObserveRefusesAForeignMark(unittest.TestCase):
    def test_a_byte_above_the_ceiling_is_never_banked(self) -> None:
        """Belt and braces. The clamp normally means observe never sees one, but a poll where the clamp
        declines would otherwise write it into the persisted file, where it outlives the session."""
        memory = rc.AreaStoryByteMemory()
        self.assertFalse(memory.observe(LAB, 0x3C))
        self.assertNotIn(LAB, memory.highest_by_region)
        self.assertEqual(memory.declined_above_ceiling, 1)

    def test_a_byte_inside_the_ceiling_still_records(self) -> None:
        memory = rc.AreaStoryByteMemory()
        self.assertTrue(memory.observe(LAB, 0x2E))
        self.assertEqual(memory.highest_by_region[LAB], 0x2E)

    def test_an_unguarded_area_is_unaffected(self) -> None:
        memory = rc.AreaStoryByteMemory()
        self.assertTrue(memory.observe("Gateon Port", 0x6C))
        self.assertEqual(memory.highest_by_region["Gateon Port"], 0x6C)


class TestTheWiring(unittest.TestCase):
    def test_the_clamp_runs_before_the_memory_poll(self) -> None:
        """Order is the whole wiring: `area_story_memory.poll` opens with `observe()`, so a foreign byte
        reaching it is one with a chance of being persisted. Client.py is not importable under test
        (websockets is not a package here), so this is asserted on the source."""
        import pathlib

        source = (pathlib.Path(__file__).resolve().parents[1] / "Client.py").read_text()
        clamp = source.index("clamp_poisoned_byte(")
        poll = source.index("ctx.area_story_memory.poll(", clamp)
        self.assertLess(clamp, poll)
        self.assertIn("busy=ctx.story_byte_override.active", source)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
