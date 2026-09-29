"""ADDENDUM 249 (2026-09-16) -- the PC-box species field is a live index, and was read raw.

`read_party_species` runs its raw field through `xd_species_index.national_dex_for_live_species()`.
`read_box_slot_species`, on the same engine and the same species enum, did not -- it returned the u32
unconverted, bounds-checked against 1-386 and nothing else. `xd_species_index.py` had flagged that exact call
site as "still-open follow-up work, not yet fixed here".

WHY IT IS NOT COSMETIC. 109 raw values in 276-386 resolve to a DIFFERENT National Dex number, and every one of
those wrong numbers names a real `Catch - ` location. The bounds check cannot catch any of them -- they are all
inside 1-386. A wrong catch check is released into a multiworld and cannot be taken back.

THE TRIGGER IS THE NICKNAME CASE. `species_owned_from_block` reads boxes by NAME (ADDENDUM 221) and falls back
to this function only when the name does not resolve to a species -- which is what a nicknamed box Pokemon
looks like, recorded in ADDENDUM 244. The fallback path and the mis-decode path are the same path."""
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
    """Exercised against a faked `read_bytes`, so it tests the function rather than a live game."""

    def setUp(self) -> None:
        self._read = rc.read_bytes
        self.raw = 0

        def fake_read(address, length):
            return struct.pack(">I", self.raw)[:length] if length == 4 else b"\x00" * length

        rc.read_bytes = fake_read

    def tearDown(self) -> None:
        rc.read_bytes = self._read

    def test_a_value_below_the_gap_is_unchanged(self) -> None:
        self.raw = 25   # Pikachu, either way
        self.assertEqual(25, rc.read_box_slot_species(0x80479000, 0))

    def test_a_value_above_the_gap_is_converted(self) -> None:
        raw = next(r for r in range(X.LIVE_INDEX_GAP_START, 387)
                   if X.national_dex_for_live_species(r) not in (None, r))
        self.raw = raw
        self.assertEqual(X.national_dex_for_live_species(raw),
                         rc.read_box_slot_species(0x80479000, 0))
        self.assertNotEqual(raw, rc.read_box_slot_species(0x80479000, 0))

    def test_an_empty_slot_is_still_none(self) -> None:
        self.raw = 0
        self.assertIsNone(rc.read_box_slot_species(0x80479000, 0))

    def test_an_out_of_range_raw_is_still_none(self) -> None:
        self.raw = 9999
        self.assertIsNone(rc.read_box_slot_species(0x80479000, 0))

    def test_a_value_the_table_cannot_resolve_is_dropped_not_guessed(self) -> None:
        """`read_party_species` holds the same contract, for the same reason: a raw value this table cannot
        explain is not evidence of a species."""
        unresolvable = [r for r in range(1, 387) if X.national_dex_for_live_species(r) is None]
        for raw in unresolvable:
            self.raw = raw
            self.assertIsNone(rc.read_box_slot_species(0x80479000, 0), f"raw {raw}")


class TestTheTwoReadersNowAgree(unittest.TestCase):
    def test_the_box_and_party_readers_use_the_same_conversion(self) -> None:
        """The inconsistency WAS the bug -- same engine, same enum, two different answers."""
        import inspect

        box = inspect.getsource(rc.read_box_slot_species)
        party = inspect.getsource(rc.read_party_species)
        self.assertIn("national_dex_for_live_species", box)
        self.assertIn("national_dex_for_live_species", party)

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
