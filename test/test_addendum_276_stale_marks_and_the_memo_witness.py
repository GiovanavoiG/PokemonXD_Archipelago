"""ADDENDUM 276 (2026-09-18): discarding marks that cannot be trusted, and crediting from the right area.

Two reports, one root.

> *"This is still happening when I hover Agate."* -- with a screenshot of all five Krane Memo checks firing
> at once.
>
> *"The floors are not being tracked correctly - hovering Agate is forcing Kaminko and HQ Lab to 0x19, which
> is softlocking the game."*

## Part 1 -- the memo checks, and why the existing witness was not enough

`check_krane_memos` read the RAW live story byte. Hovering Agate writes its entry floor, 0x19, as a pre-load
hook, and 0x19 clears both memo thresholds (0x10 and 0x17) in one tick.

ADDENDUM 265 had already built `StoryProgressWitness` for exactly this shape of bug and this reader never got
moved onto it. **But the witness alone would not have fixed it either**, and its own docstring says so:
travelling COMMITS the destination's floor, so after a real trip to Agate the byte genuinely is 0x19 in the
save and the witness rises to it honestly.

The player's framing is what closes it: *"wire it so the floors we're tracking are what send checks."* Credit a
threshold from the mark of the area that actually hands the thing over. Krane hands the memos over in his lab,
so the lab's mark is the witness that means something -- and Agate's floor can never raise the lab's mark.

That is only safe because of ADDENDA 229 and 275, which are what keep the marks free of bytes this client
wrote. Without them this would move the bug rather than fix it.

## Part 2 -- the marks already on disk

ADDENDUM 275 stopped a committed hover write becoming another area's mark. It cannot undo the ones already
written, and **there is no way to tell them apart**: a poisoned mark is a plain integer indistinguishable from
a real one. So a player carrying a pre-275 file kept getting 0x19 written on every hover of the HQ Lab or
Kaminko's -- past the end of both their ladders, which is the softlock.

The file is versioned instead, and marks written by a client old enough to have poisoned them are dropped.
Safe in a way a cleverer repair would not be: the marks are a convenience, re-derived from floors the moment
the player walks back into an area, and an area with no mark enters at its floor -- the conservative value.
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

from .. import ram_client as rc
from ..game_data import story_bytes as sb


class TestTheStaleFileIsDiscarded(unittest.TestCase):
    def test_a_pre_275_file_loses_its_marks(self) -> None:
        mem = rc.AreaStoryByteMemory()
        mem.load_json({"highest_by_region": {"Pokemon HQ Lab": 0x19, "Kaminko's House": 0x19},
                       "visited": ["Pokemon HQ Lab", "Kaminko's House"]})
        self.assertEqual({}, mem.highest_by_region)
        self.assertEqual(set(), mem.visited)
        self.assertTrue(mem.discarded_stale_schema)

    def test_and_the_softlock_write_is_gone_with_them(self) -> None:
        """The whole point. With no mark, the lab has no target at all, so the hover writes nothing."""
        mem = rc.AreaStoryByteMemory()
        mem.load_json({"highest_by_region": {"Pokemon HQ Lab": 0x19}, "visited": ["Pokemon HQ Lab"]})
        # ADDENDUM 279: with the marks gone the lab falls back to its FIRST-VISIT floor rather than to
        # nothing -- which is the better answer, and still nowhere near the 0x19 that caused the softlock.
        self.assertEqual(0x00, mem.target_for("Pokemon HQ Lab"))

    def test_a_current_file_is_kept(self) -> None:
        mem = rc.AreaStoryByteMemory()
        mem.load_json({"schema": rc.AREA_MEMORY_SCHEMA_VERSION,
                       "highest_by_region": {"Agate Village": 0x19}, "visited": ["Agate Village"]})
        self.assertEqual({"Agate Village": 0x19}, mem.highest_by_region)
        self.assertFalse(mem.discarded_stale_schema)

    def test_what_we_write_round_trips(self) -> None:
        mem = rc.AreaStoryByteMemory()
        mem.observe("Agate Village", 0x19)
        other = rc.AreaStoryByteMemory()
        other.load_json(mem.to_json())
        self.assertEqual(mem.highest_by_region, other.highest_by_region)
        self.assertFalse(other.discarded_stale_schema)

    def test_a_corrupt_file_still_degrades_quietly(self) -> None:
        mem = rc.AreaStoryByteMemory()
        mem.load_json({"schema": rc.AREA_MEMORY_SCHEMA_VERSION, "highest_by_region": "not a dict"})
        self.assertEqual({}, mem.highest_by_region)


class TestTheMemoWitness(unittest.TestCase):
    def test_the_handover_area_is_the_lab(self) -> None:
        self.assertEqual("Pokemon HQ Lab", rc.KRANE_MEMO_HANDOVER_AREA)

    def test_agates_floor_clears_both_memo_thresholds(self) -> None:
        """Why one hover fired five checks: 0x19 is above 0x10 AND 0x17."""
        agate = rc.AreaStoryByteMemory().target_for("Agate Village")
        for threshold in set(rc.KRANE_MEMO_STORY_THRESHOLDS.values()):
            self.assertGreater(agate, threshold)

    def test_hovering_agate_cannot_raise_the_labs_mark(self) -> None:
        """So the lab's mark is a witness Agate cannot forge -- which is the whole design."""
        mem = rc.AreaStoryByteMemory()
        mem.observe("Pokemon HQ Lab", 0x0F)
        mem.last_written_target, mem.last_written_region = 0x19, "Agate Village"
        mem.observe("Pokemon HQ Lab", 0x19)                 # the committed hover, landing in the lab
        self.assertEqual(0x0F, sb.highest_in_area(rc.KRANE_MEMO_HANDOVER_AREA, mem.highest_by_region))

    def test_only_memos_1_and_2_are_earned_at_that_point(self) -> None:
        mem = rc.AreaStoryByteMemory()
        mem.observe("Pokemon HQ Lab", 0x10)
        witnessed = sb.highest_in_area(rc.KRANE_MEMO_HANDOVER_AREA, mem.highest_by_region)
        earned = [n for n, t in rc.KRANE_MEMO_STORY_THRESHOLDS.items() if witnessed >= t]
        self.assertEqual([1, 2], sorted(earned))

    def test_and_all_five_once_the_lab_really_reaches_0x17(self) -> None:
        mem = rc.AreaStoryByteMemory()
        mem.observe("Pokemon HQ Lab", 0x17)
        witnessed = sb.highest_in_area(rc.KRANE_MEMO_HANDOVER_AREA, mem.highest_by_region)
        earned = [n for n, t in rc.KRANE_MEMO_STORY_THRESHOLDS.items() if witnessed >= t]
        self.assertEqual([1, 2, 3, 4, 5], sorted(earned))

    def test_the_client_falls_back_to_the_live_byte_without_travel_shuffle(self) -> None:
        """With travel randomization off the area memory never runs, so there are no marks -- and the live
        byte is trustworthy there precisely because nothing writes it. Getting this backwards would strand
        five progression-gating checks."""
        import pathlib

        source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        self.assertIn("def _memo_witness", source)
        self.assertIn("if not ctx.randomize_travel_locations:\n        return ctx.story_tracker.current",
                      source)
