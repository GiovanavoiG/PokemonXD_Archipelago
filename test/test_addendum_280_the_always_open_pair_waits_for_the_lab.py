"""ADDENDUM 280 (2026-09-18): Agate and Gateon wait for the lab to reach 0x0F.

Player: *"For location shuffle, let's only unlock Agate and Gateon upon HQ Lab reaching 0x0F. This fixes
plenty of softlocks."*

ADDENDUM 106 made the pair free from turn one, which is right about the ITEM POOL -- neither is a travel
unlock and neither should be. It was wrong about WHEN the map should offer them: the client wrote their bits
on the first poll after `block_base` resolved, before the player had done anything, so travelling out of the
lab's opening beats early was possible and stranded runs.

## A timing gate, not a logic gate

Reaching 0x0F in the lab needs no item from anybody -- it is the opening story, always available. So Agate and
Gateon are exactly as reachable in sphere zero as they were, `regions.py` is untouched, and generation is
unaffected. The gate only decides when the real map catches up with what logic already said.

## Two things that make it actually work

**It CLEARS while shut.** These are genuinely always-open in vanilla, so the game sets the bits itself.
Declining to write them would leave them set and gate nothing -- the same reason `enforce_travel_locks` holds
every unreceived destination clear on every tick.

**It reads the MARK, not the live byte.** The mark only rises from a byte the game wrote while the player was
standing in the lab (ADDENDA 229/275/277/279), so the gate cannot be opened by a hover write, a committed
destination floor, or the live bump -- every one of which would otherwise hand over the map on tick one, which
is the softlock being fixed.
"""
from __future__ import annotations

import pathlib
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

from .. import ram_client as rc, travel_locations as tl
from ..game_data import story_bytes as sb

BASE = 0x80479120


class _Record:
    """A tiny stand-in for the travel-control record, so the bit maths is exercised for real."""

    def __init__(self) -> None:
        self.mem: "dict[int, int]" = {}

    def read(self, address: int, length: int) -> bytes:
        return bytes(self.mem.get(address + i, 0) for i in range(length))

    def write(self, address: int, data: bytes) -> None:
        for i, b in enumerate(data):
            self.mem[address + i] = b

    def patch(self):
        return (mock.patch.object(rc, "read_bytes", self.read),
                mock.patch.object(rc, "write_bytes", self.write))


class TestTheGateConstants(unittest.TestCase):
    def test_it_is_the_lab_at_0x0f(self) -> None:
        self.assertEqual("Pokemon HQ Lab", tl.ALWAYS_OPEN_GATE_AREA)
        self.assertEqual(0x0F, tl.ALWAYS_OPEN_GATE_BYTE)

    def test_the_gate_byte_is_above_the_labs_own_floor(self) -> None:
        """Otherwise it would be satisfied by the entry write and gate nothing -- which is exactly how the
        lab's 0x17 rule was toothless before ADDENDUM 277."""
        self.assertGreater(tl.ALWAYS_OPEN_GATE_BYTE, sb.area_entry_floor("Pokemon HQ Lab"))

    def test_the_pair_is_agate_and_gateon(self) -> None:
        self.assertEqual({"Agate Village", "Gateon Port"}, set(tl.ALWAYS_OPEN_TRAVEL_BITS))


class TestClearingIsWhatMakesItReal(unittest.TestCase):
    def test_the_bits_can_be_cleared_and_written_back(self) -> None:
        rec = _Record()
        r, w = rec.patch()
        with r, w:
            tl.write_always_open_bits(BASE)
            self.assertTrue(tl.read_always_open_bits_set(BASE))
            self.assertTrue(tl.clear_always_open_bits(BASE))
            self.assertFalse(tl.read_always_open_bits_set(BASE))

    def test_clearing_reports_no_change_when_already_clear(self) -> None:
        """So the client can log a transition rather than a line every poll."""
        rec = _Record()
        r, w = rec.patch()
        with r, w:
            self.assertFalse(tl.clear_always_open_bits(BASE))

    def test_it_clears_the_partial_bits_too(self) -> None:
        """A partial bit left standing is ADDENDUM 85's "selectable but no proper icon" state."""
        rec = _Record()
        r, w = rec.patch()
        with r, w:
            for bit in tl.ALWAYS_OPEN_TRAVEL_BITS.values():
                rec.write(BASE + bit.byte_offset, bytes([bit.all_bits]))
            tl.clear_always_open_bits(BASE)
            for bit in tl.ALWAYS_OPEN_TRAVEL_BITS.values():
                self.assertEqual(0, rec.read(BASE + bit.byte_offset, 1)[0] & bit.all_bits)

    def test_clearing_leaves_other_destinations_bits_alone(self) -> None:
        """Several destinations share a byte (ADDENDUM 104), so an overwrite here would re-lock a neighbour."""
        rec = _Record()
        r, w = rec.patch()
        with r, w:
            for bit in tl.TRAVEL_LOCATION_BITS.values():
                address = BASE + bit.byte_offset
                rec.write(address, bytes([rec.read(address, 1)[0] | bit.full_bits]))
            before = dict(rec.mem)
            tl.clear_always_open_bits(BASE)
            for name, bit in tl.TRAVEL_LOCATION_BITS.items():
                address = BASE + bit.byte_offset
                kept = rec.read(address, 1)[0] & bit.full_bits
                shared = any(o.byte_offset == bit.byte_offset and (o.all_bits & bit.full_bits)
                             for o in tl.ALWAYS_OPEN_TRAVEL_BITS.values())
                if not shared:
                    self.assertEqual(bit.full_bits, kept, f"{name} lost its bit to the always-open clear")
            self.assertTrue(before)


class TestTheGateReadsTheMarkNotTheLiveByte(unittest.TestCase):
    """The load-bearing choice. Every other candidate source can be forged by this client's own writes."""

    def _reached(self, marks):
        return sb.highest_in_area(tl.ALWAYS_OPEN_GATE_AREA, marks)

    def test_shut_before_the_lab_has_earned_it(self) -> None:
        mem = rc.AreaStoryByteMemory()
        mem.observe("Pokemon HQ Lab", 0x03)
        self.assertLess(self._reached(mem.highest_by_region), tl.ALWAYS_OPEN_GATE_BYTE)

    def test_open_once_the_game_puts_the_lab_at_0x0f(self) -> None:
        mem = rc.AreaStoryByteMemory()
        mem.observe("Pokemon HQ Lab", 0x0F)
        self.assertGreaterEqual(self._reached(mem.highest_by_region), tl.ALWAYS_OPEN_GATE_BYTE)

    def test_the_live_bumps_own_write_cannot_open_it(self) -> None:
        """ADDENDUM 277 routes the bump through `last_written_*`, so its 0x0D -> 0x0F is refused. Without
        that, the gate would open on the player's first step into the lab -- the softlock, restored."""
        mem = rc.AreaStoryByteMemory()
        mem.last_written_target, mem.last_written_region = 0x0F, "Pokemon HQ Lab"
        mem.observe("Pokemon HQ Lab", 0x0F)
        self.assertIsNone(self._reached(mem.highest_by_region))

    def test_another_areas_high_byte_cannot_open_it(self) -> None:
        """ADDENDUM 279's inheritance guard. Walking in from Agate at 0x19 is not the lab earning 0x0F."""
        mem = rc.AreaStoryByteMemory()
        mem.observe("Agate Village", 0x19)
        mem.observe("Pokemon HQ Lab", 0x19)
        self.assertIsNone(self._reached(mem.highest_by_region))


class TestAddendum282TheGateCanActuallyOpen(unittest.TestCase):
    """Player: *"Lab and story byte reached 0x0F - gateon and agate didn't unlock. why?"*

    Because ADDENDUM 280 read the lab's MARK, and ADDENDUM 277 had already made that mark unable to reach
    0x0F: it routes the live bump's `0x0D -> 0x0F` through `last_written_*`, so `observe` refuses it -- and
    refuses a GAME-set 0x0F too, since the two are the same value in the same region. The mark goes straight
    from absent to 0x10.

    The two addenda genuinely disagree about the same byte, and the disagreement is kept rather than tidied
    away: 277 asks "did the player EARN the Snag Machine tier" and keeps the mark; 280 asks "is the story AT
    that tier" and now reads the live byte."""

    def test_the_mark_really_cannot_reach_the_gate_byte(self) -> None:
        """The measurement the correction rests on. If this ever stops being true, the simpler
        mark-based gate becomes available again and this whole detour can be revisited."""
        mem = rc.AreaStoryByteMemory()
        mem.last_written_target = tl.ALWAYS_OPEN_GATE_BYTE
        mem.last_written_region = tl.ALWAYS_OPEN_GATE_AREA
        for _ in range(3):
            mem.observe(tl.ALWAYS_OPEN_GATE_AREA, tl.ALWAYS_OPEN_GATE_BYTE)
        self.assertIsNone(sb.highest_in_area(tl.ALWAYS_OPEN_GATE_AREA, mem.highest_by_region))

    def test_a_mark_above_the_gate_byte_still_opens_it(self) -> None:
        """The mark path is kept as the first test, not replaced -- a player whose lab mark genuinely got to
        0x10+ should not need to be standing in the lab."""
        mem = rc.AreaStoryByteMemory()
        mem.observe(tl.ALWAYS_OPEN_GATE_AREA, 0x10)
        reached = sb.highest_in_area(tl.ALWAYS_OPEN_GATE_AREA, mem.highest_by_region)
        self.assertGreaterEqual(reached, tl.ALWAYS_OPEN_GATE_BYTE)


class TestAddendum282TheWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")

    def test_the_gate_checks_the_region_before_trusting_the_live_byte(self) -> None:
        """What keeps the live byte honest. A hover write lands on the map screen, where the region is not the
        lab; the Parts override and the scooter hold write in Gateon and the SS Libra."""
        _whole = self.source.split("def _always_open_gate_is_open", 1)[1]
        body = _whole.split(chr(10) + "def ", 1)[0]
        self.assertIn("region != travel_locations.ALWAYS_OPEN_GATE_AREA", body)
        self.assertIn("read_story_byte", body)

    def test_it_latches_so_walking_out_does_not_re_lock(self) -> None:
        _whole = self.source.split("def _always_open_gate_is_open", 1)[1]
        body = _whole.split(chr(10) + "def ", 1)[0]
        self.assertIn("_always_open_gate_latched", body)

    def test_the_latch_is_persisted_and_loaded(self) -> None:
        """Otherwise reconnecting outside the lab re-locks two destinations already earned."""
        self.assertIn('"always_open_gate_latched": self._always_open_gate_latched', self.source)
        self.assertIn('slot_state.get("always_open_gate_latched"', self.source)


class TestTheClientWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")

    def test_the_gate_is_checked_every_poll_not_once_per_block_base(self) -> None:
        """It is a condition that CHANGES DURING PLAY. Behind the reconnect latch it would either open too
        early or never open at all."""
        gate = self.source.index("_always_open_gate_is_open(ctx)")
        latch = self.source.index("_travel_bits_applied_for_block_base != ctx.block_base")
        self.assertLess(gate, latch, "the gate must be evaluated before (and outside) the reconnect latch")

    def test_the_always_open_write_left_the_latch(self) -> None:
        latched = self.source.split("_travel_bits_applied_for_block_base != ctx.block_base", 1)[1][:600]
        self.assertNotIn("write_always_open_bits", latched)

    def test_it_clears_while_shut(self) -> None:
        self.assertIn("clear_always_open_bits(record_base)", self.source)
