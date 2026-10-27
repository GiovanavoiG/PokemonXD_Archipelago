"""The PC-box species read: the record's own +0x00, the MASTER internal index, never returned raw.

109 master values from 277 up name a DIFFERENT National Dex number, and every one of those wrong numbers names a
real `Catch - ` location, so a raw or mis-converted read is a wrong CHECK rather than a harmless unknown number.
The 48-byte party display record is the one that carries the compacted live index (`national_dex_for_live_species`);
the 0xC4 record does not."""
import struct
import unittest

from .. import ram_client as rc
from ..tools import xd_species_index as X


class TestTheConversionIsNeeded(unittest.TestCase):
    def test_a_hundred_plus_raw_values_mean_a_different_species(self) -> None:
        differing = [raw for raw in range(1, 387)
                     if X.national_dex_for_live_species(raw) not in (None, raw)]
        self.assertGreater(len(differing), 100)
        self.assertTrue(all(raw >= X.LIVE_INDEX_GAP_START for raw in differing),
                        "nothing below the gap should move -- that is what made this survive so long")

    def test_every_wrong_value_would_have_named_a_real_catch_location(self) -> None:
        """Which is why an unconverted read is a wrong CHECK rather than a harmless unknown number."""
        from .. import locations, species

        catches = {n for n in locations.LOCATION_TABLE if n.startswith("Catch - ")}
        landed = 0
        for raw in range(X.LIVE_INDEX_GAP_START, 387):
            real = X.national_dex_for_live_species(raw)
            if real is None or real == raw:
                continue
            name = species.location_name_for_species(raw)
            if name in catches:
                landed += 1
        self.assertGreater(landed, 100, "the mis-decode lands on real checks, not on nothing")

    def test_the_bounds_check_could_never_have_caught_them(self) -> None:
        for raw in range(X.LIVE_INDEX_GAP_START, 387):
            if X.national_dex_for_live_species(raw) not in (None, raw):
                self.assertTrue(1 <= raw <= 386, f"raw {raw} is inside the range the old guard allowed")


class TestTheBoxReadConverts(unittest.TestCase):
    """Exercised against a faked `read_bytes`, so it tests the function rather than a live game. The box record is
    the same 0xC4 record as the party's, and its +0x00 is the MASTER index (`national_dex_for`)."""

    def setUp(self) -> None:
        self._read = rc.read_bytes
        self.raw = 0
        self.asked = []

        def fake_read(address, length):
            self.asked.append((address, length))
            return struct.pack(">H", self.raw)[:length] if length == 2 else b"\x00" * length

        rc.read_bytes = fake_read

    def tearDown(self) -> None:
        rc.read_bytes = self._read

    def test_it_reads_the_records_own_species_field(self) -> None:
        self.raw = 25
        rc.read_box_slot_species(0x80479000, 0)
        self.assertEqual([(rc.box_record_address(0x80479000, 0), 2)], self.asked)

    def test_a_value_below_the_gap_is_unchanged(self) -> None:
        self.raw = 25   # Pikachu, either way
        self.assertEqual(25, rc.read_box_slot_species(0x80479000, 0))

    def test_a_master_value_past_the_gap_is_its_own_species(self) -> None:
        self.raw = 279                                  # Sceptile's master index
        self.assertEqual(254, rc.read_box_slot_species(0x80479000, 0))
        self.raw = 394                                  # Gardevoir's
        self.assertEqual(282, rc.read_box_slot_species(0x80479000, 0))

    def test_an_empty_slot_is_still_none(self) -> None:
        self.raw = 0
        self.assertIsNone(rc.read_box_slot_species(0x80479000, 0))

    def test_a_value_the_table_cannot_resolve_is_dropped_not_guessed(self) -> None:
        for raw in [r for r in range(1, 600) if X.national_dex_for(r) is None] + [413, 414]:
            self.raw = raw
            self.assertIsNone(rc.read_box_slot_species(0x80479000, 0), f"raw {raw}")


class TestTheTwoReadersNowAgree(unittest.TestCase):
    def test_the_box_reader_and_the_live_party_object_use_the_master_index(self) -> None:
        import inspect

        self.assertIn("national_dex_for(raw)", inspect.getsource(rc.read_box_slot_species))
        self.assertIn("national_dex_for", inspect.getsource(rc._read_shadow_record))
        self.assertNotIn("national_dex_for_live_species", inspect.getsource(rc._read_shadow_record))
        self.assertIn("national_dex_for_live_species", inspect.getsource(rc.read_party_species))

    def test_the_recap_reader_needs_no_conversion_because_it_reads_no_number(self) -> None:
        """The other call site `xd_species_index` flagged. It is name-text based end to end, so there was
        nothing to convert -- checked rather than assumed, since "probably fine" is how the box one survived."""
        import inspect

        import ast

        tree = ast.parse(inspect.getsource(rc.read_party_recap_species).lstrip())
        function = tree.body[0]
        body = function.body[1:] if ast.get_docstring(function) else function.body
        names = {n.id for stmt in body for n in ast.walk(stmt) if isinstance(n, ast.Name)}
        self.assertIn("species_dex_from_name", names)
        self.assertNotIn("PARTY_RECAP_SPECIES_OFFSET", names,
                         "the numeric species field is documentation here, never a read")


if __name__ == "__main__":
    unittest.main()
