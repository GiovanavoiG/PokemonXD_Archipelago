"""ADDENDUM 172 (2026-09-13): partial bits are cleared too, and the location id is the stable map key.

Two player inputs:
  * "Make sure when you're clearing an area's bit to make it inaccessible, you clear the partially-visible bit
    we discovered before as well."
  * a full `!map` sweep of 16 destinations, which settles the cursor-index-vs-location-id question the map
    table was built to answer."""
from __future__ import annotations

import unittest

from .. import ram_client as rc, travel_locations as tl
from ..game_data import map_destinations as md

BASE = 0x80000000


class _FakeRam:
    def __init__(self, initial: "dict[int, int]" = None) -> None:
        self.byte = dict(initial or {})

    def read(self, address: int, length: int) -> bytes:
        return bytes(self.byte.get(address + i, 0) for i in range(length))

    def write(self, address: int, data: bytes) -> None:
        for i, value in enumerate(data):
            self.byte[address + i] = value


class _Patched:
    def __init__(self, ram: _FakeRam) -> None:
        self.ram = ram

    def __enter__(self) -> _FakeRam:
        self._orig = (rc.read_bytes, rc.write_bytes)
        rc.read_bytes, rc.write_bytes = self.ram.read, self.ram.write
        return self.ram

    def __exit__(self, *exc) -> None:
        rc.read_bytes, rc.write_bytes = self._orig


class TestPartialBits(unittest.TestCase):
    def test_outskirt_stands_measured_combo_is_reproduced_exactly(self) -> None:
        """ADDENDUM 90 measured Outskirt Stand's full access as the 3-bit combo 0x02|0x10|0x20, with the
        full-icon state dropping 0x10. So all_bits must be exactly 0x32 -- not 0x33, which is what the generic
        `full >> 1` derivation would give, and which is why this one entry is recorded rather than derived."""
        bit = tl.TRAVEL_LOCATION_BITS["Outskirt Stand"]
        self.assertEqual(bit.all_bits, 0x02 | 0x10 | 0x20)
        self.assertEqual(bit.partial_bits, 0x10)

    def test_the_derivation_puts_each_partial_directly_beneath_its_full_bit(self) -> None:
        """The record is laid out as 2-bit pairs per destination. Any partial that is not `full >> 1` would
        mean a destination reaching outside its own pair."""
        for name, bit in tl.TRAVEL_LOCATION_BITS.items():
            if bit.measured_partial_bits is not None:
                continue
            self.assertEqual(bit.partial_bits, bit.full_bits >> 1, name)

    def test_no_destination_can_clear_another_ones_bits(self) -> None:
        """The whole reason clearing is per-destination rather than per-byte. If two entries' all_bits ever
        overlapped, re-locking one would silently re-lock a destination the player legitimately received."""
        seen: "dict[int, int]" = {}
        for name, bit in tl.TRAVEL_LOCATION_BITS.items():
            self.assertEqual(seen.get(bit.byte_offset, 0) & bit.all_bits, 0, name)
            seen[bit.byte_offset] = seen.get(bit.byte_offset, 0) | bit.all_bits

    def test_clearing_takes_the_partial_bit_too(self) -> None:
        """The point of the change: clearing only the full-icon bit leaves ADDENDUM 85's in-between state,
        which is not "inaccessible"."""
        bit = tl.TRAVEL_LOCATION_BITS["Mt. Battle"]
        with _Patched(_FakeRam({BASE + bit.byte_offset: bit.all_bits})) as ram:
            self.assertTrue(tl.clear_travel_location_bit(BASE, "Mt. Battle"))
            self.assertEqual(ram.byte[BASE + bit.byte_offset], 0)

    def test_a_lone_partial_bit_is_still_cleared(self) -> None:
        """A destination left half-visible -- partial set, full not -- must still come back locked. Before this
        change the clear would have read as a no-op and left it selectable."""
        bit = tl.TRAVEL_LOCATION_BITS["Mt. Battle"]
        with _Patched(_FakeRam({BASE + bit.byte_offset: bit.partial_bits})) as ram:
            self.assertTrue(tl.clear_travel_location_bit(BASE, "Mt. Battle"))
            self.assertEqual(ram.byte[BASE + bit.byte_offset], 0)

    def test_setting_is_unchanged_and_still_writes_only_the_full_bits(self) -> None:
        """ADDENDUM 85 established the full-icon state is what a legitimately-discovered destination should be
        in. Clearing got wider; granting deliberately did not."""
        bit = tl.TRAVEL_LOCATION_BITS["Pyrite Town"]
        with _Patched(_FakeRam({})) as ram:
            tl.write_travel_location_bit(BASE, "Pyrite Town")
            self.assertEqual(ram.byte[BASE + bit.byte_offset], bit.full_bits)


class TestTheMapIdSweep(unittest.TestCase):
    def test_location_ids_are_unique(self) -> None:
        ids = [d.location_id for d in md.CONFIRMED]
        self.assertEqual(len(set(ids)), len(ids))

    def test_cursor_indices_are_allowed_to_collide(self) -> None:
        """Not a data error -- the player's own sweep has SS Libra and Realgam Tower both at cursor 10. It is
        the index being a position in a shifting list, which is exactly why nothing keys off it."""
        indices = [d.cursor_index for d in md.CONFIRMED]
        self.assertLess(len(set(indices)), len(indices), "the sweep really does contain a collision")

    def test_the_two_corroborated_destinations_kept_their_location_id_across_sessions(self) -> None:
        """Phenac City and the Rock Poke Spot were measured on 2026-09-12 and again in the player's sweep. The
        cursor index moved for both (1 -> 3 and 9 -> 13); the location id did not. That pair of facts is the
        whole argument for keying on location id."""
        self.assertEqual(md.BY_LOCATION_ID[3].name, "Phenac City")
        self.assertEqual(md.BY_LOCATION_ID[15].name, "Rock Poke Spot")

    def test_every_measured_destination_maps_to_a_real_region(self) -> None:
        """ADDENDUM 185 carved out one exception: Orre Colosseum is a real region that is deliberately off the
        story chain, so the map can point at it while the logic never depends on reaching it."""
        from .. import regions, travel_locations

        for destination in md.CONFIRMED:
            if destination.region == travel_locations.ORRE_COLOSSEUM_REGION:
                continue
            self.assertIn(destination.region, regions.REGION_NAMES, destination.name)

    def test_orre_colosseum_points_at_its_own_postgame_region(self) -> None:
        from .. import travel_locations

        orre = next(d for d in md.CONFIRMED if d.name == "Orre Colosseum")
        self.assertEqual(orre.region, travel_locations.ORRE_COLOSSEUM_REGION)

    def test_outskirt_stand_is_cursor_zero_location_zero(self) -> None:
        """Its sweep entry read location id 3, which collided with Phenac City's corroborated 3, so the row was
        parked rather than guessed at. The player corrected it 2026-09-13: "Outskirt should be 0, 0 not 0, 3".
        Both columns are pinned here because the correction touched both."""
        outskirt = md.BY_LOCATION_ID[0]
        self.assertEqual(outskirt.name, "Outskirt Stand")
        self.assertEqual(outskirt.cursor_index, 0)
        self.assertEqual(outskirt.region, "Outskirt Stand")
        self.assertNotIn("Outskirt Stand", md.AWAITING_MEASUREMENT)

    def test_phenac_city_kept_location_id_three(self) -> None:
        """The other half of the same correction: the collision resolved in Phenac's favour, so 3 must still
        resolve to Phenac City and not to Outskirt Stand."""
        self.assertEqual(md.region_for_location_id(3), "Phenac City")

    def test_citadark_isle_is_not_a_map_destination_at_all(self) -> None:
        """Player, 2026-09-13: "Citadark is indeed not a map location." It is entered by Robo Kyogre out of
        Gateon Port, so it is not a missing row waiting to be measured -- it is not a row. It must appear in
        neither half of the table, or a future sweep will go looking for something that does not exist."""
        self.assertNotIn("Citadark Isle", md.AWAITING_MEASUREMENT)
        self.assertNotIn("Citadark Isle", {d.name for d in md.CONFIRMED})

    def test_the_table_is_complete(self) -> None:
        measured, total = md.coverage()
        self.assertEqual(measured, total)
        self.assertEqual(md.AWAITING_MEASUREMENT, ())

    def test_the_id_space_starts_at_zero_and_thirteen_is_genuinely_unassigned(self) -> None:
        """The old lead -- ids run 1..17 with gaps at 8 and 13, so Outskirt Stand is probably 13 -- is dead.
        Cipher Lab filled 8, Outskirt Stand turned out to be 0, and 13 belongs to nothing. Pinned so nobody
        revives the guess."""
        ids = set(md.BY_LOCATION_ID)
        self.assertEqual(min(ids), 0)
        self.assertEqual(sorted(set(range(0, 18)) - ids), [13])

    def test_an_unmeasured_id_resolves_to_none_rather_than_a_guess(self) -> None:
        self.assertIsNone(md.region_for_location_id(13))
        self.assertIsNone(md.region_for_location_id(None))


class TestTheResolverUsesTheStableKey(unittest.TestCase):
    def _reading(self, **kwargs):
        defaults = dict(tag_address=0x810EF4D0, index=99, x=1.0, y=2.0, x_settled=1.0, y_settled=2.0,
                        record_address=0x810F06E0, location_id=9, location_id_mirror=9, second_index=None)
        defaults.update(kwargs)
        # The mirror follows the id unless a test is deliberately making them disagree -- otherwise changing
        # location_id alone would silently produce an INCONSISTENT reading and every assertion would pass for
        # the wrong reason.
        if "location_id" in kwargs and "location_id_mirror" not in kwargs:
            defaults["location_id_mirror"] = kwargs["location_id"]
        return rc.MapCursorReading(**defaults)

    def test_it_resolves_through_the_location_id(self) -> None:
        self.assertEqual(rc.map_destination_region(self._reading(location_id=9)), "Mt. Battle")

    def test_a_wrong_cursor_index_does_not_matter(self) -> None:
        """The index can be anything at all -- it is not the key."""
        self.assertEqual(rc.map_destination_region(self._reading(index=12345, location_id=4)), "Pyrite Town")

    def test_an_unsettled_or_inconsistent_reading_resolves_to_none(self) -> None:
        self.assertIsNone(rc.map_destination_region(self._reading(x=1.0, x_settled=99.0)))
        self.assertIsNone(rc.map_destination_region(self._reading(location_id_mirror=5)))
        self.assertIsNone(rc.map_destination_region(None))


if __name__ == "__main__":
    unittest.main()
