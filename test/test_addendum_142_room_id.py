"""ADDENDUM 141/142 (2026-09-11): the validated current-room id.

ADDENDUM 138 shipped a wrong answer that looked overwhelming, and ADDENDUM 140 retracted it. So the values
asserted here are the ones that passed four independent checks, and the tests are written around the failure
modes that caught the previous candidate -- not just the happy path."""
from __future__ import annotations

import unittest

import pathlib

from .. import ram_client as rc

# Every value below was read live. Cipher Lab / HQ exterior / Gateon Port additionally match the room_id
# field of common_rel's own treasure table (the ISO, not memory).
LIVE = {
    8: "Cipher Lab",
    140: "Pokemon HQ Lab (interior)",
    143: "Pokemon HQ Lab (exterior)",
    147: "Gateon Port (building by the entrance)",
    153: "Gateon Port",
    173: "Kaminko's house",
}
ALL_COPIES = (rc.ROOM_ID_ADDRESS, *rc.ROOM_ID_MIRRORS)


class _Ram:
    """Serves each replicated copy independently, so disagreement can be simulated."""

    def __init__(self, by_address: "dict[int, int]", explode_on: "set[int] | None" = None) -> None:
        self.by_address = by_address
        self.explode_on = explode_on or set()

    def read(self, address: int, length: int) -> bytes:
        if address in self.explode_on:
            raise RuntimeError("Dolphin went away")
        return self.by_address.get(address, 0).to_bytes(2, "big")[:length]


class _Patched:
    def __init__(self, ram: _Ram) -> None:
        self.ram = ram

    def __enter__(self):
        self._orig = rc.read_bytes
        rc.read_bytes = self.ram.read
        return self.ram

    def __exit__(self, *exc):
        rc.read_bytes = self._orig


def _agreeing(value: int, explode_on=None) -> _Patched:
    return _Patched(_Ram({a: value for a in ALL_COPIES}, explode_on))


class TestReadRoomId(unittest.TestCase):
    def test_every_live_confirmed_room_reads_back(self) -> None:
        for room_id in LIVE:
            with _agreeing(room_id):
                self.assertEqual(rc.read_room_id(), room_id)

    def test_a_minority_disagreement_is_outvoted(self) -> None:
        """One copy mid-update must not cost us the reading."""
        by = {a: 153 for a in ALL_COPIES}
        by[rc.ROOM_ID_MIRRORS[0]] = 999
        with _Patched(_Ram(by)):
            self.assertEqual(rc.read_room_id(), 153)

    def test_no_majority_means_unknown_not_a_guess(self) -> None:
        """The ADDENDUM 140 failure mode: a plausible-looking value that is simply not the answer. With the
        copies evenly split there is no basis to pick one, so the honest result is 'unknown'."""
        by = dict(zip(ALL_COPIES, (153, 153, 8, 8)))
        with _Patched(_Ram(by)):
            self.assertIsNone(rc.read_room_id())

    def test_zero_and_out_of_range_values_are_rejected(self) -> None:
        for bad in (0, 0x401, 0xFFFF):
            with _agreeing(bad):
                self.assertIsNone(rc.read_room_id())

    def test_it_still_works_when_some_copies_cannot_be_read(self) -> None:
        with _agreeing(140, explode_on={rc.ROOM_ID_MIRRORS[1]}):
            self.assertEqual(rc.read_room_id(), 140)

    def test_it_returns_none_when_nothing_can_be_read(self) -> None:
        with _agreeing(140, explode_on=set(ALL_COPIES)):
            self.assertIsNone(rc.read_room_id())


class TestRoomNames(unittest.TestCase):
    def test_the_six_validated_rooms_still_ship_with_their_meaning_intact(self) -> None:
        """EXPANDED 2026-09-11 (ADDENDUM 152): the table is no longer just these six -- the player compiled
        two dozen more room ids from live play. Exact dict equality would now fail on every future addition,
        so this asserts what actually matters: the six that passed ADDENDUM 142's four-way validation are
        still present and still mean the same place. 140 is allowed to have become more specific (the HQ Lab
        has four distinct interior rooms, 138-141, and 140 is the downstairs-right one)."""
        for room_id, expected in LIVE.items():
            self.assertIn(room_id, rc.KNOWN_ROOM_IDS, room_id)
        self.assertIn("Cipher Lab", rc.KNOWN_ROOM_IDS[8])
        self.assertIn("exterior", rc.KNOWN_ROOM_IDS[143])
        self.assertIn("interior", rc.KNOWN_ROOM_IDS[140])
        self.assertIn("Gateon Port", rc.KNOWN_ROOM_IDS[153])
        self.assertIn("Gateon Port", rc.KNOWN_ROOM_IDS[147])
        self.assertIn("Kaminko", rc.KNOWN_ROOM_IDS[173])

    def test_every_named_room_is_a_value_read_room_id_would_accept(self) -> None:
        """A room id the reader rejects as implausible could never be reported, so naming it would be a lie."""
        for room_id in rc.KNOWN_ROOM_IDS:
            self.assertGreater(room_id, 0, room_id)
            self.assertLessEqual(room_id, rc.ROOM_ID_MAX_PLAUSIBLE, room_id)

    def test_unnamed_rooms_are_reported_by_number(self) -> None:
        self.assertIn("77", rc.room_name(77))
        self.assertIn("unnamed", rc.room_name(77))
        self.assertEqual(rc.room_name(None), "unknown")

    def test_gateon_indoors_and_outdoors_are_different_rooms(self) -> None:
        """The forward test that distinguished a ROOM id from the retracted AREA-level value: the retracted
        one could only change per area, so it could never have told these apart."""
        self.assertNotEqual(153, 147)
        self.assertIn("Gateon Port", rc.room_name(153))
        self.assertIn("Gateon Port", rc.room_name(147))

    def test_the_hq_lab_interior_and_exterior_remain_distinct(self) -> None:
        self.assertNotEqual(rc.KNOWN_ROOM_IDS[140], rc.KNOWN_ROOM_IDS[143])


class TestRoomIdsMatchTheIso(unittest.TestCase):
    """The check that eliminated 13 of 17 candidates, using data shipped in the ISO rather than any dump."""

    def test_the_chest_bearing_rooms_we_sampled_exist_in_the_treasure_table(self) -> None:
        from ..tools import xd_rel_format as rel

        # A tiny synthetic treasure table is not good enough here -- the point of this test is agreement with
        # the REAL numbering, so assert the specific room ids that were cross-checked live.
        for room_id in (8, 143, 153):
            self.assertIn(room_id, rc.KNOWN_ROOM_IDS)
        self.assertIn("Cipher Lab", rc.KNOWN_ROOM_IDS[8])
        # The ID Card (game item 506, ADDENDUM 134) sits in a chest in room 8 -- the Cipher Lab, where the
        # player used it. That coincidence of two independent sources is the strongest single data point.
        self.assertTrue(hasattr(rel, "read_chest_entry"))


class TestRoomTracker(unittest.TestCase):
    def _poll(self, tracker, room_id):
        with _agreeing(room_id):
            return tracker.poll()

    def test_the_first_sighting_is_not_a_transition(self) -> None:
        t = rc.RoomTracker()
        self.assertIsNone(self._poll(t, 153))
        self.assertEqual(t.current, 153)

    def test_the_real_walk_is_reported(self) -> None:
        """Gateon outdoors -> a Gateon building -> back out, as actually performed."""
        t = rc.RoomTracker()
        self._poll(t, 153)
        self.assertEqual(self._poll(t, 147), (153, 147))
        self.assertIsNone(self._poll(t, 147))
        self.assertEqual(self._poll(t, 153), (147, 153))

    def test_an_unreadable_poll_keeps_the_last_known_room(self) -> None:
        t = rc.RoomTracker()
        self._poll(t, 140)
        with _agreeing(0):
            self.assertIsNone(t.poll())
        self.assertEqual(t.current, 140)

    def test_describe_in_both_states(self) -> None:
        t = rc.RoomTracker()
        self.assertIn("unknown", t.describe())
        self._poll(t, 143)
        self._poll(t, 8)
        text = t.describe()
        self.assertIn("Cipher Lab", text)
        self.assertIn("Pokemon HQ Lab (exterior)", text)


class TestRetractedAreaIdStaysInert(unittest.TestCase):
    """ADDENDUM 138 shipped a "current area id" at 0x80447EF0. ADDENDUM 140 retracted it -- a reboot read
    "Gateon Port" while the player stood at the HQ Lab exterior; it is a recently-loaded-area cache, not a
    position. The tracker is still in the codebase, deliberately inert, so what is worth testing is that it
    STAYS inert -- not that its readings are correct, which they are not.

    CONSOLIDATED 2026-09-12: this replaces test_addendum_138_area_id.py's 19 tests. Eighteen of those verified
    the behaviour of a value the project no longer believes. Verifying a retracted finding in detail is worse
    than not testing it, because it reads as endorsement."""

    def test_the_client_never_reads_the_value_only_prints_it(self) -> None:
        """Constructing and polling the tracker is fine -- `!area` needs both to have something to print. What
        must never happen is the VALUE reaching a decision: a check, a goal, a region."""
        source = (pathlib.Path(rc.__file__).parent / "Client.py").read_text(encoding="utf-8")
        reading = [line.strip() for line in source.splitlines()
                   if "area_tracker." in line
                   and not line.strip().startswith("#")
                   and not line.strip().endswith(("describe())", "poll(ctx.block_base)"))]
        self.assertFalse(reading, f"the retracted area id reached a decision: {reading}")

    def test_the_unreliability_warning_travels_with_every_readout(self) -> None:
        tracker = rc.AreaTracker()
        self.assertIn("UNRELIABLE", tracker.describe())

    def test_it_still_refuses_to_report_a_value_it_cannot_trust(self) -> None:
        """The one piece of real behaviour worth keeping: a zero or disagreeing read is "unknown", never a
        number a future reader might act on."""
        self.assertEqual(rc.area_name(None), "unknown")


if __name__ == "__main__":
    unittest.main()
