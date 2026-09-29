"""ADDENDUM 380 (2026-09-28): a granted destination has its partial bit CLEARED, every poll.

Player: "Ensure that we're scanning the travel bits periodically with location shuffle - right now, unlocking an
area in-game breaks the visuals for the map icons. We need to make sure the partial visibility bits are always
off when we have a location unlocked."

TWO HALVES, AND EITHER ALONE WOULD HAVE LEFT THE BUG.

1. THE MASK. Every CLEAR path in `travel_locations` takes `all_bits` (full | partial) -- ADDENDUM 172 made sure
   of that, because clearing only the full bit leaves ADDENDUM 85's half-drawn in-between state. `_or_write_bit`,
   the only SET path, took `full_bits` alone. So the two directions did not describe the same set of states: a
   clear produced 00, a grant produced full|partial whenever the partial bit was already set. ADDENDUM 172 said
   setting was "deliberately untouched", and its premise -- the partial bit is clear when we grant -- is true only
   on a save where the story has never revealed that area.

2. THE CADENCE. `sync_travel_locations` re-applied received destinations once per block base, so a destination's
   byte was written on boot/save-load and never looked at again. The GAME sets the partial bit itself when the
   story reaches the point that would have unlocked the area in the unmodified game. Fixing only the mask would
   have helped destinations received AFTER that moment and nothing else.

The opposite direction already had the right shape: `enforce_travel_locks` holds every NOT-yet-received
destination clear "every tick", for the same reason -- the game sets them itself, so declining to write gates
nothing. Holding the received ones correct is that same argument; it was the half that was missing.
"""
from __future__ import annotations

import pathlib
import unittest

from .. import ram_client as rc, travel_locations as tl

BASE = 0x80479000
CLIENT = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")


class _Memory:
    """A byte-addressed stand-in for the travel record, so the real bit maths runs."""

    def __init__(self) -> None:
        self.cells: "dict[int, int]" = {}
        self.writes = 0

    def install(self, test: unittest.TestCase) -> None:
        for name in ("read_bytes", "write_bytes"):
            test.addCleanup(setattr, rc, name, getattr(rc, name))
        rc.read_bytes = lambda a, n: bytes(self.cells.get(a + i, 0) for i in range(n))

        def write(address, data):
            self.writes += 1
            for i, b in enumerate(data):
                self.cells[address + i] = b

        rc.write_bytes = write


class TestTheMask(unittest.TestCase):
    def setUp(self) -> None:
        self.mem = _Memory()
        self.mem.install(self)

    def _grant(self, destination: str, starting_byte: int) -> int:
        bit = tl.TRAVEL_LOCATION_BITS[destination]
        address = BASE + bit.byte_offset
        self.mem.cells.clear()
        self.mem.cells[address] = starting_byte
        tl.write_travel_location_bit(BASE, destination)
        return self.mem.cells[address]

    def test_every_starting_state_lands_on_full_only(self) -> None:
        """The reported case is the second row: the game revealed the area, so its partial bit is already set,
        and the old code OR'd the full bit on top and left both."""
        for destination, bit in tl.TRAVEL_LOCATION_BITS.items():
            if destination not in tl.TRAVEL_LOCATION_NAMES:
                continue      # a member of a multi-destination unlock, granted through its own name
            for start in (0x00, bit.partial_bits, bit.full_bits, bit.full_bits | bit.partial_bits):
                with self.subTest(destination=destination, start=hex(start)):
                    got = self._grant(destination, start)
                    self.assertEqual(bit.full_bits, got & bit.full_bits,
                                     "the full bit(s) must end up set")
                    self.assertEqual(0, got & bit.partial_bits,
                                     "the partial bit(s) must end up clear -- this is the reported bug")

    def test_the_set_and_clear_paths_now_describe_the_same_bits(self) -> None:
        """The asymmetry, stated directly: a clear takes `all_bits`, so a grant must account for all of them
        too. If a future edit narrows either one, these stop being inverses and the half-drawn state returns."""
        for destination, bit in tl.TRAVEL_LOCATION_BITS.items():
            self.assertEqual(bit.full_bits | bit.partial_bits, bit.all_bits)
            self.assertEqual(0, bit.full_bits & bit.partial_bits,
                             f"{destination}: the full and partial bits must not overlap, or a grant that "
                             "clears partial would clear part of full")

    def test_a_sibling_sharing_the_byte_is_never_disturbed(self) -> None:
        """Byte 0x08 holds three destinations. Clearing partial bits is a new AND-NOT, which is exactly the kind
        of edit that can reach into a neighbour's pair."""
        outskirt = tl.TRAVEL_LOCATION_BITS["Outskirt Stand"]
        snagem = tl.TRAVEL_LOCATION_BITS["Snagem Hideout"]
        self.assertEqual(outskirt.byte_offset, snagem.byte_offset)
        address = BASE + snagem.byte_offset
        self.mem.cells.clear()
        self.mem.cells[address] = outskirt.all_bits
        tl.write_travel_location_bit(BASE, "Snagem Hideout")
        got = self.mem.cells[address]
        self.assertEqual(snagem.full_bits, got & snagem.full_bits)
        self.assertEqual(outskirt.all_bits, got & outskirt.all_bits,
                         "Outskirt Stand's own pair changed -- the mask reached outside its destination")

    def test_it_writes_nothing_when_the_byte_is_already_correct(self) -> None:
        """What makes per-poll re-assertion free. A steady state must cost reads and no writes."""
        self._grant("Cipher Key Lair", 0x00)
        before = self.mem.writes
        tl.write_travel_location_bit(BASE, "Cipher Key Lair")
        self.assertEqual(before, self.mem.writes)

    def test_a_grant_then_a_clear_returns_to_zero(self) -> None:
        bit = tl.TRAVEL_LOCATION_BITS["Cipher Key Lair"]
        address = BASE + bit.byte_offset
        self.mem.cells.clear()
        self.mem.cells[address] = bit.partial_bits
        tl.write_travel_location_bit(BASE, "Cipher Key Lair")
        tl.clear_travel_location_bit(BASE, "Cipher Key Lair")
        self.assertEqual(0, self.mem.cells[address] & bit.all_bits)

    def test_the_always_open_grant_shares_the_fix(self) -> None:
        """`write_always_open_bits` routes through the same `_or_write_bit`, so Agate and Gateon get the same
        treatment without a second code path to keep in step."""
        self.mem.cells.clear()
        for bit in tl.ALWAYS_OPEN_TRAVEL_BITS.values():
            self.mem.cells[BASE + bit.byte_offset] = bit.partial_bits
        tl.write_always_open_bits(BASE)
        for name, bit in tl.ALWAYS_OPEN_TRAVEL_BITS.items():
            got = self.mem.cells[BASE + bit.byte_offset]
            with self.subTest(name=name):
                self.assertEqual(bit.full_bits, got & bit.full_bits)
                self.assertEqual(0, got & bit.partial_bits)


class TestTheCadence(unittest.TestCase):
    """Structural -- `Client.py` pulls in CommonClient and is not importable here."""

    def setUp(self) -> None:
        start = CLIENT.index("async def sync_travel_locations")
        self.body = CLIENT[start:][:CLIENT[start:].index("\nasync def ", 1)]

    def test_received_destinations_are_re_applied_unconditionally(self) -> None:
        """The loop must not sit behind the block-base gate any more. Asserted by checking the write loop is
        NOT inside that conditional, since that gate is what made this once-per-boot."""
        loop = "for name in ctx.received_travel_locations:"
        self.assertIn(loop, self.body)
        gate = "if ctx._travel_bits_applied_for_block_base != ctx.block_base:"
        self.assertIn(gate, self.body, "the gate should still exist -- for the NOTICE, not for the write")
        self.assertLess(self.body.index(loop), self.body.index(gate),
                        "the re-apply loop is still behind the block-base gate, so it runs once per boot")

    def test_the_reconnect_notice_is_still_one_shot(self) -> None:
        """One line per poll is what ADDENDUM 181 took out of this client, so making the WRITE per-poll must not
        make the message per-poll."""
        gated = self.body[self.body.index("if ctx._travel_bits_applied_for_block_base != ctx.block_base:"):]
        self.assertIn("Re-applied", gated)
        self.assertIn("_travel_bits_applied_for_block_base = ctx.block_base", gated)

    def test_the_unreceived_half_still_holds_clear_every_tick(self) -> None:
        """The shape this addendum copied. If `enforce_travel_locks` ever stopped clearing, the two halves would
        disagree about who owns the byte."""
        start = CLIENT.index("async def enforce_travel_locks")
        body = CLIENT[start:][:CLIENT[start:].index("\nasync def ", 1)]
        self.assertIn("clear_travel_location_bit", body)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
