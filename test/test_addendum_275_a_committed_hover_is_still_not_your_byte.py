"""ADDENDUM 275 (2026-09-18): a byte written FOR one destination never becomes another one's mark.

Player: *"Hovering Agate is triggering hq lab bytes to progress and skip forward too far."*

ADDENDUM 229 stopped `observe()` recording a hover write WHILE it was outstanding. It did not cover what
happens when that write is **committed** -- and a commit is not a promise that the player went where the
cursor was resting.

## The sequence, which needs no race

1. The cursor rests on Agate Village. The hover write is a pre-load hook, so the client writes Agate's entry
   floor, **0x19**, into the live story byte.
2. The player moves the cursor to another icon and confirms.
3. `left_map_screen` sees a room that is not the one the map was opened from, correctly calls it a trip,
   commits the byte and releases `_write_outstanding`.
4. The next `observe()` records the live byte -- still 0x19, because nothing has re-written it -- against the
   region the player **landed in**.

Land in the Pokemon HQ Lab and its high-water mark becomes 0x19. Permanently, in a file built to outlive the
client, re-applied on every future entry.

## Why the lab is the worst possible place for it to land

The lab has **no static entry floor at all** -- `area_entry_floor("Pokemon HQ Lab")` is None. Its target comes
entirely from rules that top out at 0x17, and from the high-water mark. So a poisoned mark does not compete
with anything; it simply wins, and the lab is entered at a byte past the end of its own ladder. *"Skip forward
too far"* is the precise description.

## The rule

The one ADDENDUM 229 already stated, carried one step further: **a byte this client wrote is not a byte to
record from -- and it does not become one by being committed.** It is still Agate's number, and it only means
something in the area it was written for.
"""
from __future__ import annotations

import sys
import types
import unittest

if "dolphin_memory_engine" not in sys.modules:
    _stub = types.ModuleType("dolphin_memory_engine")
    _stub.hook = _stub.un_hook = lambda: None
    _stub.is_hooked = lambda: False
    _stub.read_bytes = lambda address, length: b""
    _stub.write_bytes = lambda address, data: None
    sys.modules["dolphin_memory_engine"] = _stub

from unittest import mock

from .. import ram_client as rc
from ..game_data import story_bytes as sb

BASE = 0x80479120


class TestTheReportedCase(unittest.TestCase):
    def test_the_lab_has_no_static_floor_which_is_why_a_bad_mark_wins(self) -> None:
        # ADDENDUM 279 gave the lab a first-visit floor (0x00). The premise of this class survives it: 0x01
        # is far below the rules' 0x17, so a poisoned MARK still outranks everything the lab can be given.
        self.assertEqual(0x00, sb.area_entry_floor("Pokemon HQ Lab"))
        top = max(r.floor for r in sb.AREA_FLOOR_RULES if r.target == "Pokemon HQ Lab")
        self.assertEqual(0x17, top, "if the lab's ladder grows, this test's premise needs re-reading")

    def test_agates_floor_really_is_past_the_labs_whole_ladder(self) -> None:
        self.assertEqual(0x19, rc.AreaStoryByteMemory().target_for("Agate Village"))
        self.assertGreater(0x19, 0x17)

    def test_the_committed_hover_no_longer_poisons_the_landed_region(self) -> None:
        """The whole bug, end to end, against the real class."""
        mem = rc.AreaStoryByteMemory()
        mem.observe("Pokemon HQ Lab", 0x0F)
        written = []
        with mock.patch.object(rc, "write_bytes", lambda a, p: written.append(p[0])):
            mem.poll(BASE, "Agate Village", None, 0x0F)          # cursor on Agate -> writes 0x19
        self.assertEqual([0x19], written)
        mem.left_map_screen(BASE, backed_out=False)              # they travelled -- commit, lock released
        self.assertFalse(mem._write_outstanding)

        mem.observe("Pokemon HQ Lab", 0x19)                      # ...but they landed in the LAB
        self.assertEqual(0x0F, mem.highest_by_region["Pokemon HQ Lab"],
                         "Agate's byte must not become the lab's mark")
        self.assertEqual(1, mem.declined_foreign_commit)

    def test_and_the_lab_is_therefore_still_entered_at_its_own_tier(self) -> None:
        mem = rc.AreaStoryByteMemory()
        mem.observe("Pokemon HQ Lab", 0x0F)
        mem.last_written_target, mem.last_written_region = 0x19, "Agate Village"
        mem.observe("Pokemon HQ Lab", 0x19)
        self.assertLessEqual(mem.target_for("Pokemon HQ Lab"), 0x17)


class TestItDoesNotBreakTheHonestCases(unittest.TestCase):
    def test_landing_where_you_hovered_still_records(self) -> None:
        """The overwhelmingly common case: the cursor was on Agate and Agate is where they went."""
        mem = rc.AreaStoryByteMemory()
        with mock.patch.object(rc, "write_bytes", lambda a, p: None):
            mem.poll(BASE, "Agate Village", None, 0x0F)
        mem.left_map_screen(BASE, backed_out=False)
        # ADDENDUM 277: landing where you hovered no longer banks OUR write either -- the mark waits for the
        # game to move the byte. What must still hold is that nothing was corrupted and the area is unvisited
        # rather than wrongly marked.
        self.assertFalse(mem.observe("Agate Village", 0x19))
        self.assertNotIn("Agate Village", mem.highest_by_region)
        self.assertTrue(mem.observe("Agate Village", 0x1A))

    def test_our_own_number_is_refused_even_in_the_area_we_wrote_it_for(self) -> None:
        """RETARGETED by ADDENDUM 277. This used to assert the opposite -- that a byte equal to our write was
        still recorded when the player was standing in the area we wrote it for. That exemption WAS the bug:
        you usually do travel to the icon you hovered, so it excused the commonest case there is, and the
        lab's rule-raised 0x17 came straight back as the lab's own mark.

        The cost is one value, and only while the live byte still IS our write -- see the next test."""
        mem = rc.AreaStoryByteMemory()
        mem.last_written_target, mem.last_written_region = 0x19, "Agate Village"
        self.assertFalse(mem.observe("Agate Village", 0x19))
        self.assertEqual(1, mem.declined_foreign_commit)

    def test_but_the_game_advancing_past_it_is_recorded_normally(self) -> None:
        """Which is what earning a tier actually looks like, and why losing the one value costs nothing."""
        mem = rc.AreaStoryByteMemory()
        mem.last_written_target, mem.last_written_region = 0x19, "Agate Village"
        self.assertTrue(mem.observe("Agate Village", 0x1A))
        self.assertEqual(0x1A, mem.highest_by_region["Agate Village"])

    def test_a_byte_that_is_not_ours_records_anywhere(self) -> None:
        mem = rc.AreaStoryByteMemory()
        mem.last_written_target, mem.last_written_region = 0x19, "Agate Village"
        self.assertTrue(mem.observe("Pokemon HQ Lab", 0x11))
        self.assertEqual(0x11, mem.highest_by_region["Pokemon HQ Lab"])

    def test_nothing_written_yet_records_normally(self) -> None:
        mem = rc.AreaStoryByteMemory()
        self.assertTrue(mem.observe("Pokemon HQ Lab", 0x0F))


class TestEveryDestinationPairThatCouldDoThis(unittest.TestCase):
    """Derived rather than listed: any destination whose floor exceeds another area's whole ladder could have
    poisoned that area the same way. This is the census the fix has to cover, not just Agate and the lab."""

    def test_the_guard_covers_all_of_them(self) -> None:
        from .. import travel_locations as tl

        floors = {}
        for name in tl.TRAVEL_LOCATION_NAMES:
            f = rc.AreaStoryByteMemory().target_for(tl.TRAVEL_LOCATION_TARGET_REGION[name])
            if f is not None:
                floors[name] = f
        self.assertTrue(floors, "no destination floors at all -- has the table changed shape?")
        for name, floor in floors.items():
            mem = rc.AreaStoryByteMemory()
            mem.last_written_target = floor
            mem.last_written_region = tl.TRAVEL_LOCATION_TARGET_REGION[name]
            self.assertFalse(mem.observe("Pokemon HQ Lab", floor),
                             f"a committed {name} hover (0x{floor:02X}) still reaches the lab's mark")


class TestAddendum277TheCycleTheUserDescribed(unittest.TestCase):
    """ADDENDUM 277. Player: *"doing any story progress in Agate is writing to HQ Lab and sending checks early
    again ... I think this applies to our whole system - later areas are writing to the areas before them."*

    The diagnosis was right and the loop is a CYCLE, not a one-way write:

      1. a LATER area's mark satisfies an `AreaFloorRule` for an EARLIER one (Gateon 0x16 raises the lab to
         0x17) -- working as designed;
      2. hovering the lab makes us WRITE 0x17, because that is now its target;
      3. `observe()` banked our own 0x17 as the lab's mark, because ADDENDUM 275 only refused a write made for
         a DIFFERENT region;
      4. the mark then feeds the memo witness, the rules, and `target_for` -- indistinguishable from real play.

    Step 3 was the only wrong link, and 275 excused it for the commonest case there is."""

    def test_the_rule_still_raises_the_floor_which_is_correct(self) -> None:
        """The rule is not the bug. A later area legitimately tells an earlier one where it now sits."""
        mem = rc.AreaStoryByteMemory()
        mem.observe("Pokemon HQ Lab", 0x0F)     # ADDENDUM 277: the Snag Machine rung the 0x17 rule needs
        mem.observe("Gateon Port", 0x16)
        self.assertEqual(0x17, mem.target_for("Pokemon HQ Lab"))

    def test_but_that_floor_never_becomes_the_labs_own_mark(self) -> None:
        mem = rc.AreaStoryByteMemory()
        mem.observe("Pokemon HQ Lab", 0x0F)     # ADDENDUM 277: the Snag Machine rung the 0x17 rule needs
        mem.observe("Gateon Port", 0x16)
        with mock.patch.object(rc, "write_bytes", lambda a, p: None):
            mem.poll(BASE, "Pokemon HQ Lab", None, 0x0F)
        mem.left_map_screen(BASE, backed_out=False)
        mem.observe("Pokemon HQ Lab", 0x17)
        self.assertEqual(0x0F, mem.highest_by_region["Pokemon HQ Lab"])

    def test_and_so_the_memo_witness_does_not_reach_the_3_to_5_threshold(self) -> None:
        """The reported symptom, asserted end to end against the real witness."""
        mem = rc.AreaStoryByteMemory()
        mem.observe("Pokemon HQ Lab", 0x0F)     # ADDENDUM 277: the Snag Machine rung the 0x17 rule needs
        mem.observe("Gateon Port", 0x16)
        with mock.patch.object(rc, "write_bytes", lambda a, p: None):
            mem.poll(BASE, "Pokemon HQ Lab", None, 0x0F)
        mem.left_map_screen(BASE, backed_out=False)
        mem.observe("Pokemon HQ Lab", 0x17)
        def earned(memory):
            witnessed = sb.highest_in_area(rc.KRANE_MEMO_HANDOVER_AREA, memory.highest_by_region)
            return sorted(n for n, t in rc.KRANE_MEMO_STORY_THRESHOLDS.items() if witnessed >= t)

        # The lab's real mark is still 0x0F -- the Snag Machine, genuinely earned, and short of BOTH memo
        # thresholds. So nothing is earned yet. Before ADDENDUM 277 the banked 0x17 credited all five at once.
        self.assertEqual([], earned(mem))
        mem.observe("Pokemon HQ Lab", 0x10)     # the game hands over 1-2, in the lab, for real
        self.assertEqual([1, 2], earned(mem))

        # RESIDUAL, recorded rather than papered over. `last_written_target` is still 0x17 from the hover, so
        # a GAME advance to exactly 0x17 is refused too -- the client cannot tell it from its own write, and
        # in RAM there is nothing to tell them apart by. The mark therefore waits for 0x18.
        mem.observe("Pokemon HQ Lab", 0x17)
        self.assertEqual([1, 2], earned(mem), "the one value we cannot distinguish stays refused")
        mem.observe("Pokemon HQ Lab", 0x18)
        self.assertEqual([1, 2, 3, 4, 5], earned(mem), "and the next real advance pays them all out")

    def test_no_area_can_have_its_mark_set_by_a_write_for_any_other_area(self) -> None:
        """The general form of the player's 'this applies to our whole system'. Derived over every ordered
        pair of regions the memory can write for, so a new area is covered the day it is added."""
        from .. import travel_locations as tl

        regions = sorted({tl.TRAVEL_LOCATION_TARGET_REGION[n] for n in tl.TRAVEL_LOCATION_NAMES}
                         | {"Pokemon HQ Lab", "Kaminko's House", "Gateon Port", "Agate Village"})
        for wrote_for in regions:
            value = rc.AreaStoryByteMemory().target_for(wrote_for)
            if value is None:
                continue
            for landed_in in regions:
                mem = rc.AreaStoryByteMemory()
                mem.last_written_target, mem.last_written_region = value, wrote_for
                self.assertFalse(mem.observe(landed_in, value),
                                 f"a write for {wrote_for} (0x{value:02X}) became {landed_in}'s mark")


class TestAddendum279TheLabsZeroIsAValue(unittest.TestCase):
    """The lab's first-visit byte is 0x00 (player, 2026-09-18), and 0 is falsy in Python.

    This table exists to replace a None that meant "no floor at all", so the one way to reintroduce that bug
    is for some consumer to test truthiness instead of `is None`. Every one of them was checked by hand when
    the value was set; this is the fence that keeps it true."""

    def test_the_lab_floor_is_zero_and_is_not_none(self) -> None:
        floor = sb.area_entry_floor("Pokemon HQ Lab")
        self.assertEqual(0x00, floor)
        self.assertIsNotNone(floor, "0 is falsy -- an `is None` test is the only correct one")

    def test_a_zero_floor_still_produces_a_write(self) -> None:
        """The whole point. If anything in the chain treated 0 as absent, the lab would go back to inheriting
        whatever byte the player walked in carrying."""
        mem = rc.AreaStoryByteMemory()
        written = []
        with mock.patch.object(rc, "write_bytes", lambda a, p: written.append(p[0])):
            note = mem.poll(BASE, "Pokemon HQ Lab", None, 0x19)
        self.assertEqual([0x00], written)
        self.assertEqual(0, mem.declined_no_window, "a 0x00 floor is a floor, not a missing window")
        self.assertIsNotNone(note)

    def test_every_always_open_region_has_a_floor_that_is_not_none(self) -> None:
        for region in sb.ALWAYS_OPEN_REGIONS:
            self.assertIsNotNone(sb.area_entry_floor(region), region)
