"""ADDENDUM 434 (2026-10-08) -- `Unlock -` checks on the game's travel bits, Krane Memos on removal.

The location unlock checks are sent when any partial travel-visibility bit is detected, rather than via the
story byte. The Krane Memo checks are not sent automatically; each is sent when its memo enters the inventory
and is removed.
"""
from __future__ import annotations

import pathlib
import unittest

from .. import ram_client as rc, travel_locations as tl
from ..game_data import story_bytes

BASE = 0x80479000
CLIENT = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")


class _Memory:
    def __init__(self, test: unittest.TestCase) -> None:
        self.cells: "dict[int, int]" = {}
        for name in ("read_bytes", "write_bytes"):
            test.addCleanup(setattr, rc, name, getattr(rc, name))
        rc.read_bytes = lambda a, n: bytes(self.cells.get(a + i, 0) for i in range(n))

        def write(address, data):
            for i, b in enumerate(data):
                self.cells[address + i] = b

        rc.write_bytes = write

    def set(self, destination: str, value: int) -> None:
        bit = tl.TRAVEL_LOCATION_BITS[destination]
        self.cells[BASE + bit.byte_offset] = value


class TestRevealedByGame(unittest.TestCase):
    def setUp(self) -> None:
        self.mem = _Memory(self)

    def test_a_clear_record_reveals_nothing(self) -> None:
        for name in tl.TRAVEL_LOCATION_NAMES:
            self.assertFalse(tl.revealed_by_game(BASE, name, False), name)
            self.assertFalse(tl.revealed_by_game(BASE, name, True), name)

    def test_locked_any_bit_is_the_game(self) -> None:
        for name in tl.TRAVEL_LOCATION_NAMES:
            for member in tl.travel_unlock_members(name):
                bit = tl.TRAVEL_LOCATION_BITS[member]
                for value in (bit.partial_bits, bit.full_bits):
                    with self.subTest(name=name, member=member, value=hex(value)):
                        self.mem.cells.clear()
                        self.mem.set(member, value)
                        self.assertTrue(tl.revealed_by_game(BASE, name, False))

    def test_granted_only_the_partial_bit_is_news(self) -> None:
        """Our grant holds the full bit set, so it proves nothing; the partial bit is the game's."""
        for name in tl.TRAVEL_LOCATION_NAMES:
            member = tl.travel_unlock_members(name)[0]
            bit = tl.TRAVEL_LOCATION_BITS[member]
            self.mem.cells.clear()
            self.mem.set(member, bit.full_bits)
            self.assertFalse(tl.revealed_by_game(BASE, name, True), name)
            self.mem.set(member, bit.full_bits | bit.partial_bits)
            self.assertTrue(tl.revealed_by_game(BASE, name, True), name)

    def test_a_neighbour_in_the_same_byte_reveals_nothing(self) -> None:
        """Byte 0x08 holds Outskirt Stand, Gateon Port and Snagem: one destination's bits never read as another's."""
        snagem = tl.TRAVEL_LOCATION_BITS["Snagem Hideout"]
        outskirt = tl.TRAVEL_LOCATION_BITS["Outskirt Stand"]
        gateon = tl.ALWAYS_OPEN_TRAVEL_BITS["Gateon Port"]
        self.mem.set("Snagem Hideout", outskirt.all_bits | gateon.all_bits)
        self.assertFalse(tl.revealed_by_game(BASE, "Snagem Hideout", False))
        self.mem.set("Snagem Hideout", snagem.all_bits | gateon.all_bits)
        self.assertFalse(tl.revealed_by_game(BASE, "Outskirt Stand", False))

    def test_one_poke_spot_reveals_the_group(self) -> None:
        self.mem.set("Oasis Poke Spot", tl.TRAVEL_LOCATION_BITS["Oasis Poke Spot"].partial_bits)
        self.assertTrue(tl.revealed_by_game(BASE, "Poke Spots", False))

    def test_it_only_reads(self) -> None:
        writes = []
        rc.write_bytes = lambda a, d: writes.append(a)
        self.mem.set("Pyrite Town", 0xFF)
        tl.revealed_by_game(BASE, "Pyrite Town", False)
        tl.revealed_by_game(BASE, "Pyrite Town", True)
        self.assertEqual([], writes)

    def test_the_lock_and_the_grant_each_erase_the_evidence(self) -> None:
        """Why the read has to come first in the tick."""
        bit = tl.TRAVEL_LOCATION_BITS["Pyrite Town"]
        self.mem.set("Pyrite Town", bit.partial_bits)
        tl.clear_travel_location_bit(BASE, "Pyrite Town")
        self.assertFalse(tl.revealed_by_game(BASE, "Pyrite Town", False))
        self.mem.set("Pyrite Town", bit.partial_bits)
        tl.write_travel_location_bit(BASE, "Pyrite Town")
        self.assertFalse(tl.revealed_by_game(BASE, "Pyrite Town", True))


def _function(header: str) -> str:
    start = CLIENT.index(header)
    rest = CLIENT[start + len(header):]
    ends = [i for i in (rest.find("\nasync def "), rest.find("\ndef "), rest.find("\nclass ")) if i >= 0]
    return CLIENT[start:start + len(header) + min(ends)]


class TestTheClient(unittest.TestCase):
    def test_the_reveal_is_read_before_either_writer(self) -> None:
        observe = CLIENT.index("observe_travel_reveals(ctx)\n                    await sync_travel_locations(ctx)")
        self.assertLess(observe, CLIENT.index("await enforce_travel_locks(ctx)"))

    def test_checks_are_sent_inside_the_block_stability_gate(self) -> None:
        gate = CLIENT.index("if block_is_stable:")
        send = CLIENT.index("await send_travel_reveal_checks(ctx)")
        self.assertLess(gate, send)

    def test_the_lock_no_longer_sends_anything(self) -> None:
        body = _function("async def enforce_travel_locks")
        self.assertNotIn("_send_checks", body)
        self.assertNotIn("_unlock_is_earned", body)
        self.assertIn("clear_travel_location_bit", body)

    def test_observe_uses_the_received_set(self) -> None:
        body = _function("def observe_travel_reveals")
        self.assertIn("travel_locations.revealed_by_game(record_base, name, name in received)", body)
        self.assertNotIn("_send_checks", body)

    def test_a_reveal_survives_a_restart(self) -> None:
        self.assertIn('"travel_revealed": sorted(self.travel_revealed)', CLIENT)
        self.assertIn('slot_state.get("travel_revealed", [])', CLIENT)

    def test_memos_are_checked_off_the_bag_alone(self) -> None:
        body = _function("async def check_krane_memos")
        self.assertIn("ctx.krane_memo_tracker.poll(ctx.block_base)", body)
        for gone in ("story", "witness", "highest_in_area"):
            self.assertNotIn(gone, body.split('"""')[-1], gone)


class TestNoBumpSendsAMemo(unittest.TestCase):
    def test_no_bump_awards_anything(self) -> None:
        for bump in story_bytes.LIVE_STORY_BYTE_BUMPS:
            self.assertEqual((), bump.awards_locations, bump.region)


if __name__ == "__main__":
    unittest.main()
