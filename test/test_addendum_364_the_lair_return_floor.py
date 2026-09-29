"""ADDENDUM 364 (2026-09-26): the Key Lair's return floor, and the Snagem decoupling it completes.

SUPERSEDED IN PART BY ADDENDUM 371 (2026-09-27): *"make the key lair floor 0x67 by default."*

The player asked for 0x67 conditionally first and unconditionally a day later, so the CONDITION is gone and the
VALUE is the entry floor. This module is kept rather than deleted, retargeted onto what survives -- which is
most of it. Everything 364 established about 0x67 itself (that it is a rung the game rests on, that it lies
inside the Lair's window, that it is above the entry floor the icon used to write) is still exactly why this is
the right number, and the Snagem half at the bottom is untouched and is the half the player asked about. What
went is the rule object and the two tests about a FIRST visit landing lower than a return one, because there is
no longer any difference between the two.

The original request, for the record:

Player: *"After Zook is defeated at key lair (0x64 > 0x65) I'd like the floor to be bumped to 0x67. This
allows us to not need snagem hideout for cipher key lair - did we separate them logically?"*

THE LADDER THIS SITS IN. 0x62 -> 0x64 (Gonzap beaten, Gonzap's Key and the Snag Machine back) -> 0x65 (Zook
beaten at the Lair) -> 0x67 -> 0x69 (entered the Cipher Key Lair) -> 0x6A (System Lever used). ADDENDUM 324's
`AREA_ENTRY_FLOOR_OVERRIDES["Cipher Key Lair"] = 0x64` drops the icon at the courtyard, which is right for a
first visit and two rungs short for every one after it.

WHY THE CONDITION IS THE LAIR'S OWN MARK. Our own writes are never banked as a mark (ADDENDUM 277), so a Lair
mark at or above 0x65 can only mean the GAME moved the byte there while the player stood in the Lair -- "Zook
was really beaten here", not "we wrote 0x64 on arrival". That is the whole reason this is safe to key on, and
it is what `test_our_own_entry_write_does_not_satisfy_it` pins.

AND THE ANSWER TO THE SECOND HALF: yes, with travel randomization ON. ADDENDUM 332 removed the Key Lair's
`TRAVEL_LOCATION_REQUIRED_REGIONS` entry and the region is `gateway_only`, so its chain edge from Snagem is
suppressed outright and its only entrance is its own travel gateway. With travel randomization OFF the
`Snagem Hideout -> Cipher Key Lair` edge is live and Snagem IS required -- which is the unmodified game, and
deliberately not loosened (see the ADDENDUM 293 comment in regions.py: in that mode the ladder is the only
route and `ScooterStoryHold` holds the byte below the upgrade until the item arrives).
"""
from __future__ import annotations

import unittest

from .. import ram_client as rc, regions, travel_locations
from ..game_data import story_bytes as sb
from . import PokemonXDTestBase

LAIR = "Cipher Key Lair"
TIERS = ("Cipher Key Lair (exterior)", "Cipher Key Lair", "Cipher Key Lair (deep)")


class TestTheFloorItself(unittest.TestCase):
    def test_0x67_is_the_floor_and_carries_no_condition(self) -> None:
        """ADDENDUM 371. The value the player asked for twice, now stated as a value: no rule, and 0x67 is what
        the destination is entered at whatever any area's mark says."""
        self.assertEqual(0x67, sb.AREA_ENTRY_FLOOR_OVERRIDES[LAIR])
        self.assertEqual(0x67, sb.area_entry_floor(LAIR))
        self.assertEqual([], [r for r in sb.AREA_FLOOR_RULES if r.target == LAIR],
                         "the Lair's floor is a value now -- a rule here could only sit at or below it, which "
                         "ADDENDUM 247's fence forbids because it can never bind")

    def test_the_rule_it_replaced_could_not_have_survived(self) -> None:
        """Why ADDENDUM 371 is a deletion and not an edit, kept as the arithmetic rather than as a memory:
        364's rule floor and the new entry floor are the SAME number, so `target_for`'s max makes the rule
        unreachable. This is the third time this has happened to a Key Lair/Phenac rule and it is the fence
        working, not three mistakes."""
        self.assertEqual(0x67, sb.area_entry_floor(LAIR), "364's rule floor is now the entry floor")

    def test_0x67_is_a_byte_the_game_rests_on(self) -> None:
        """0x68 is a passthrough of `0x67 -> 0x69` -- a value the ladder moves through and never holds. Using
        it would write a rung that does not exist (ADDENDUM 350)."""
        self.assertTrue(sb.byte_is_reachable(0x67))
        self.assertFalse(sb.byte_is_reachable(0x68))

    def test_it_lands_inside_the_regions_own_window(self) -> None:
        window = sb.REGION_STORY_WINDOW[LAIR]
        self.assertLessEqual(window.floor, 0x67)
        self.assertLessEqual(0x67, window.ceiling)


class TestWhatAVisitNowWrites(unittest.TestCase):
    def _memory(self, **marks: int) -> "rc.AreaStoryByteMemory":
        memory = rc.AreaStoryByteMemory()
        for region, byte in marks.items():
            name = region.replace("_", " ")
            memory.visited.add(name)
            memory.highest_by_region[name] = byte
        return memory

    def test_every_visit_arrives_at_the_doorway_including_the_first(self) -> None:
        """RETARGETED BY ADDENDUM 371, and this is the whole behavioural change. Two tests used to live here --
        a first visit at 0x64 and a return trip at 0x67 -- and they are one test now, because the player asked
        for 0x67 "by default"."""
        self.assertEqual(rc.AreaStoryByteMemory().target_for(LAIR), 0x67)

    def test_a_mark_below_the_floor_cannot_pull_the_arrival_down(self) -> None:
        """The direction that has to hold whatever the floor is. A player who arrived, left without beating
        Zook and came back still lands on the doorway."""
        for byte in (0x64, 0x65):
            memory = self._memory(**{"Cipher Key Lair": byte})
            self.assertEqual(memory.target_for(LAIR), 0x67, hex(byte))

    def test_the_floor_covers_every_tier_of_the_place(self) -> None:
        """An entry floor is recorded against an `AREA_GROUPS` place, not a region, and the Lair is three
        regions -- so the doorway value applies whichever tier the destination resolves to. This is what made
        ADDENDUM 368's level merge and this floor describe the same place."""
        self.assertEqual(TIERS, sb.AREA_GROUPS[LAIR])
        for tier in TIERS:
            self.assertEqual(0x67, sb.area_entry_floor(tier), tier)

    def test_a_later_mark_is_not_dragged_back_down_to_0x67(self) -> None:
        """`target_for` takes the max, so a player deeper in the Lair keeps their own progress."""
        memory = self._memory(**{"Cipher Key Lair": 0x6C})
        self.assertGreaterEqual(memory.target_for(LAIR), 0x6C)

    def test_our_own_entry_write_is_still_never_banked_as_a_mark(self) -> None:
        """ADDENDUM 277's guard, which ADDENDUM 364 leaned on and ADDENDUM 371 no longer needs but must not
        break. `observe` refuses to bank a byte this client wrote, so the arrival write never becomes evidence
        of anything. It mattered when 0x67 was conditional; it is asserted still because the guard protects
        every other conditional rule in the table the same way."""
        memory = rc.AreaStoryByteMemory()
        memory.last_written_target = 0x67
        memory.observe(LAIR, 0x67)
        self.assertNotIn(LAIR, memory.highest_by_region)
        self.assertEqual(memory.target_for(LAIR), 0x67)

    def test_and_a_real_game_advance_in_the_lair_is(self) -> None:
        """The other side of the same guard: once the game moves the byte off our write, it is a real mark, and
        the arrival rises with it rather than dragging the player back to the doorway."""
        memory = rc.AreaStoryByteMemory()
        memory.last_written_target = 0x67
        memory.observe(LAIR, 0x67)          # our own arrival write -- refused
        memory.observe(LAIR, 0x69)          # the game, on entering the Lair -- recorded
        self.assertEqual(memory.highest_by_region.get(LAIR), 0x69)
        self.assertGreaterEqual(memory.target_for(LAIR), 0x69)


# ============================================================================================================
# "did we separate them logically?"
# ============================================================================================================
class TestTheLairIsNotBehindSnagem(PokemonXDTestBase):
    options = {"randomize_travel_locations": True}

    def test_the_only_way_in_is_the_lairs_own_travel_gateway(self) -> None:
        lair = self.multiworld.get_region(LAIR, self.player)
        sources = {e.parent_region.name for e in lair.entrances}
        self.assertNotIn("Snagem Hideout", sources)
        self.assertEqual(sources, {"Travel Gateway - Cipher Key Lair"})

    def test_it_carries_no_hard_region_prerequisite(self) -> None:
        self.assertEqual(travel_locations.required_regions_for("Cipher Key Lair"), ())

    def test_the_region_is_gateway_only_so_its_chain_edge_is_suppressed(self) -> None:
        self.assertIn(LAIR, travel_locations.gateway_only_regions())
        self.assertIn(("Snagem Hideout", LAIR, ()), regions.REGION_EDGES)


class TestVanillaTravelStillRunsThroughSnagem(PokemonXDTestBase):
    options = {"randomize_travel_locations": False}

    def test_the_chain_edge_is_live_when_there_are_no_gateways(self) -> None:
        """Deliberately NOT loosened. With the map offering only what the story unlocked, the ladder is the
        only route, and `ScooterStoryHold` holds the byte below the upgrade until the Scooter arrives -- so
        loosening the graph here would let Fill place the Scooter somewhere it cannot be reached."""
        lair = self.multiworld.get_region(LAIR, self.player)
        sources = {e.parent_region.name for e in lair.entrances}
        self.assertIn("Snagem Hideout", sources)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
