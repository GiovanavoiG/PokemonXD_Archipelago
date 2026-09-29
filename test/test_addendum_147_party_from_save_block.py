"""ADDENDUM 147 (2026-09-11): reading the party out of the save block, not the party menu.

Player report: "I still have to open the party screen to get catch checks -- pc is working perfectly. Can we fix
the party?" The asymmetry is the whole diagnosis: the PC-box scan reads BLOCK_BASE-relative save data and needs
no player action, while the party half read PARTY_BASE -- a 0x30-byte record holding name/species/level/HP,
i.e. a menu row, which evidently does not populate a slot until the party screen has drawn it.
"""
from __future__ import annotations

import struct
import unittest

from .. import ram_client as rc

BLOCK_BASE = 0x80479380


def _slot_address(party_index: int) -> int:
    return BLOCK_BASE + rc.PARTY_RECAP_OFFSET + party_index * rc.PARTY_RECAP_STRIDE


class _Block:
    """A synthetic save block holding only what the party records need: name text at offset 0 of each record
    and MaxHP at PARTY_RECAP_MAXHP_OFFSET. Everything else reads as zeros."""

    def __init__(self, slots: "dict[int, tuple[str, int]]", explode_on: "set[int] | None" = None) -> None:
        self.memory: dict[int, int] = {}
        self.explode_on = explode_on or set()
        for party_index, (name, max_hp) in slots.items():
            base = _slot_address(party_index)
            encoded = name.encode("utf-16-be") + b"\x00\x00"
            for offset, byte in enumerate(encoded):
                self.memory[base + offset] = byte
            for offset, byte in enumerate(struct.pack(">H", max_hp)):
                self.memory[base + rc.PARTY_RECAP_MAXHP_OFFSET + offset] = byte

    def read(self, address: int, length: int) -> bytes:
        if address in self.explode_on:
            raise RuntimeError("Dolphin went away")
        return bytes(self.memory.get(address + i, 0) for i in range(length))


class _Patched:
    def __init__(self, block: _Block) -> None:
        self.block = block

    def __enter__(self):
        self._orig = rc.read_bytes
        rc.read_bytes = self.block.read
        return self.block

    def __exit__(self, *exc):
        rc.read_bytes = self._orig


class TestReadingOneSlot(unittest.TestCase):
    def test_a_normal_occupied_slot_resolves(self) -> None:
        with _Patched(_Block({0: ("JOLTEON", 120)})):
            self.assertEqual(rc.read_party_recap_name(BLOCK_BASE, 0), "JOLTEON")
            self.assertEqual(rc.read_party_recap_species(BLOCK_BASE, 0), 135)

    def test_a_ten_character_species_name_is_not_truncated(self) -> None:
        """`read_party_recap_record` reads 0x12 bytes -- 9 characters -- which cuts AERODACTYL to AERODACTY and
        drops it from catch detection entirely. This path reads 0x16, like every other name field in the file."""
        self.assertEqual(len("AERODACTYL"), 10)
        with _Patched(_Block({0: ("AERODACTYL", 110)})):
            self.assertEqual(rc.read_party_recap_name(BLOCK_BASE, 0), "AERODACTYL")
            self.assertEqual(rc.read_party_recap_species(BLOCK_BASE, 0), 142)

    def test_an_empty_slot_is_none_not_a_guess(self) -> None:
        with _Patched(_Block({})):
            self.assertEqual(rc.read_party_recap_name(BLOCK_BASE, 3), "")
            self.assertIsNone(rc.read_party_recap_species(BLOCK_BASE, 3))

    def test_a_nickname_is_skipped_rather_than_misread(self) -> None:
        """Expected and not an error -- a renamed Pokemon simply isn't identifiable from this field."""
        with _Patched(_Block({0: ("SPARKY", 120)})):
            self.assertIsNone(rc.read_party_recap_species(BLOCK_BASE, 0))

    def test_a_real_name_with_an_impossible_maxhp_is_rejected(self) -> None:
        """`read_party_recap_record`'s own docstring says an empty slot's contents are unconfirmed, so the name
        alone cannot establish occupancy. A leftover record has to fail something."""
        for max_hp in (0, 1000, 0xFFFF):
            with _Patched(_Block({0: ("JOLTEON", max_hp)})):
                self.assertIsNone(rc.read_party_recap_species(BLOCK_BASE, 0), max_hp)

    def test_the_maxhp_ceiling_is_the_series_wide_one(self) -> None:
        self.assertEqual(rc.PARTY_RECAP_PLAUSIBLE_MAX_HP, 999)
        with _Patched(_Block({0: ("JOLTEON", 999)})):
            self.assertEqual(rc.read_party_recap_species(BLOCK_BASE, 0), 135)


class TestSnapshot(unittest.TestCase):
    def test_a_full_party_reads_back(self) -> None:
        party = {0: ("JOLTEON", 120), 1: ("TEDDIURSA", 90), 2: ("SPHEAL", 80),
                 3: ("BUTTERFREE", 100), 4: ("MAKUHITA", 130), 5: ("DUSCLOPS", 95)}
        with _Patched(_Block(party)):
            self.assertEqual(len(rc.get_party_recap_species_snapshot(BLOCK_BASE)), 6)

    def test_gaps_between_occupied_slots_do_not_stop_the_scan(self) -> None:
        with _Patched(_Block({0: ("JOLTEON", 120), 4: ("SPHEAL", 80)})):
            self.assertEqual(rc.get_party_recap_species_snapshot(BLOCK_BASE), {135, 363})

    def test_it_stops_at_six_slots(self) -> None:
        """A 7th record would be whatever follows the party array; reading it as a party member would be a
        fabricated catch."""
        self.assertEqual(rc.PARTY_MAX_SLOTS, 6)
        with _Patched(_Block({6: ("MEWTWO", 200)})):
            self.assertEqual(rc.get_party_recap_species_snapshot(BLOCK_BASE), set())

    def test_one_unreadable_slot_never_takes_down_the_scan(self) -> None:
        block = _Block({0: ("JOLTEON", 120), 1: ("SPHEAL", 80)},
                       explode_on={_slot_address(1)})
        with _Patched(block):
            self.assertEqual(rc.get_party_recap_species_snapshot(BLOCK_BASE), {135})

    def test_an_entirely_unreadable_block_returns_empty_rather_than_raising(self) -> None:
        block = _Block({0: ("JOLTEON", 120)}, explode_on={_slot_address(i) for i in range(6)})
        with _Patched(block):
            self.assertEqual(rc.get_party_recap_species_snapshot(BLOCK_BASE), set())


class TestItLinesUpWithTheBoxScan(unittest.TestCase):
    """The two halves are meant to be unioned into one "what the save file says you own" snapshot."""

    def test_the_party_records_use_the_same_record_stride_as_box_slots(self) -> None:
        self.assertEqual(rc.PARTY_RECAP_STRIDE, rc.BOX_SLOT_STRIDE)

    def test_both_read_the_same_number_of_name_bytes(self) -> None:
        with _Patched(_Block({0: ("JOLTEON", 120)})):
            rc.read_party_recap_name(BLOCK_BASE, 0)
        self.assertEqual(rc.PARTY_NAME_MAX_BYTES, 0x16)

    def test_the_party_array_ends_before_box_one_begins(self) -> None:
        """If these ever overlapped, a party member would be counted as a box slot and vice versa."""
        party_end = rc.PARTY_RECAP_OFFSET + rc.PARTY_MAX_SLOTS * rc.PARTY_RECAP_STRIDE
        self.assertLess(party_end, rc.BOX_SLOT_TEXT_ANCHOR_OFFSET)


class TestTheGuardsStillApply(unittest.TestCase):
    """ADDENDUM 146's confirmation guards cover whatever is passed as the save-block half, so the new party
    source inherits them rather than getting its own unguarded path."""

    def test_a_new_save_block_species_still_has_to_hold(self) -> None:
        t = rc.SpeciesCatchTracker()
        t.poll(set(), {135})
        self.assertEqual(t.poll(set(), {135, 363}), [])
        fired = []
        for _ in range(rc.SpeciesCatchTracker._CONFIRM_STREAK - 1):
            fired += t.poll(set(), {135, 363})
        self.assertEqual(fired, [363])

    def test_a_party_base_sighting_still_fires_immediately(self) -> None:
        """PARTY_BASE is not removed -- it remains the fast path when it does populate."""
        t = rc.SpeciesCatchTracker()
        t.poll({135}, {135})
        self.assertEqual(t.poll({135, 363}, {135}), [363])


if __name__ == "__main__":
    unittest.main()
