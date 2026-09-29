"""ADDENDUM 164 (2026-09-12): the map screen's highlighted destination.

Every number here was read live on 2026-09-12 -- six full MEM1 dumps over two identical laps of Phenac City,
the Rock Poke Spot and the Cipher Lab. ADDENDUM 138 is the standing lesson in this project about believing a
bare address that merely looks convincing, so these tests are written around the failure modes rather than the
happy path: the decoy tag hit, a stale cached address, redundant copies disagreeing, and a reading taken while
the map camera was still panning."""
from __future__ import annotations

import struct
import unittest

from .. import ram_client as rc

# --- exactly what the live dumps held ---------------------------------------------------------------------
TAG_ADDRESS = 0x810ED690        # where the real cursor object sat on that boot
RECORD_ADDRESS = 0x810EE8A0     # constant across all three destinations -- a shared "highlighted" slot
SECOND_SIGNATURE_ADDRESS = 0x810ED734
DECOY_TAG_ADDRESS = 0x8080BAB0

# destination -> (cursor index, location id, map x, map y)
LIVE = {
    "Phenac City":    (1, 3, 44.0, 16.0),
    "Rock Poke Spot": (9, 15, 70.0, -9.0),
    "Cipher Lab":     (6, 8, 21.0, -19.0),
}


class _FakeMem1:
    """A sparse stand-in for MEM1 that can serve both the full 24 MiB scan read and small targeted reads."""

    def __init__(self) -> None:
        self.buffer = bytearray(rc.MEM1_SIZE)
        self.reads: list[tuple[int, int]] = []

    # -- construction helpers
    def put(self, address: int, data: bytes) -> None:
        off = address - rc.MEM1_START
        self.buffer[off:off + len(data)] = data

    def put_u32(self, address: int, value: int) -> None:
        self.put(address, struct.pack(">I", value))

    def put_f32(self, address: int, value: float) -> None:
        self.put(address, struct.pack(">f", value))

    def place_cursor(self, index: int, location_id: int, x: float, y: float, *,
                     tag_address: int = TAG_ADDRESS, record_address: int = RECORD_ADDRESS,
                     settled: bool = True, location_id_mirror: "int | None" = None) -> None:
        self.put(tag_address, rc.MAP_CURSOR_TAG)
        self.put_u32(tag_address + rc.MAP_CURSOR_INDEX_OFFSET, index)
        self.put_f32(tag_address + rc.MAP_CURSOR_X_OFFSET, x)
        self.put_f32(tag_address + rc.MAP_CURSOR_Y_OFFSET, y)
        # When the camera is still panning, the live position has not yet reached the settled target.
        self.put_f32(tag_address + rc.MAP_CURSOR_X_SETTLED_OFFSET, x if settled else x + 25.0)
        self.put_f32(tag_address + rc.MAP_CURSOR_Y_SETTLED_OFFSET, y if settled else y + 25.0)
        self.put_u32(tag_address + rc.MAP_CURSOR_RECORD_POINTER_OFFSET, record_address)
        self.put_u32(record_address + rc.MAP_RECORD_LOCATION_ID_OFFSET, location_id)
        self.put_u32(record_address + rc.MAP_RECORD_LOCATION_ID_MIRROR_OFFSET,
                     location_id if location_id_mirror is None else location_id_mirror)

    def place_second_object(self, index: int) -> None:
        self.put_u32(SECOND_SIGNATURE_ADDRESS - rc.MAP_CURSOR_SECOND_INDEX_BACK_OFFSET, index)
        self.put(SECOND_SIGNATURE_ADDRESS, rc.MAP_CURSOR_SECOND_SIGNATURE)

    def place_decoy(self) -> None:
        """The one other tag hit in real MEM1. It failed BOTH fences live: an absurd index and a record
        pointer of 0x00000100, so it is reproduced exactly rather than as a convenient near-miss."""
        self.put(DECOY_TAG_ADDRESS, rc.MAP_CURSOR_TAG)
        self.put_u32(DECOY_TAG_ADDRESS + rc.MAP_CURSOR_INDEX_OFFSET, 2155920132)
        self.put_u32(DECOY_TAG_ADDRESS + rc.MAP_CURSOR_RECORD_POINTER_OFFSET, 0x00000100)

    # -- the read_bytes replacement
    def read(self, address: int, length: int) -> bytes:
        self.reads.append((address, length))
        off = address - rc.MEM1_START
        if off < 0 or off + length > len(self.buffer):
            raise RuntimeError(f"read outside MEM1: 0x{address:08X}+{length}")
        return bytes(self.buffer[off:off + length])

    @property
    def full_scans(self) -> int:
        return sum(1 for _, length in self.reads if length == rc.MEM1_SIZE)


class _Patched:
    """Swaps rc.read_bytes for the fake, and makes any WRITE an immediate failure -- this feature is
    read-only and must stay that way."""

    def __init__(self, mem: _FakeMem1) -> None:
        self.mem = mem

    def __enter__(self) -> _FakeMem1:
        self._read, self._write = rc.read_bytes, rc.write_bytes

        def _no_writes(address: int, data: bytes) -> None:
            raise AssertionError(f"ADDENDUM 164 must never write to memory (tried 0x{address:08X})")

        rc.read_bytes, rc.write_bytes = self.mem.read, _no_writes
        return self.mem

    def __exit__(self, *exc) -> None:
        rc.read_bytes, rc.write_bytes = self._read, self._write


def _mem_for(destination: str, **kwargs) -> _FakeMem1:
    index, location_id, x, y = LIVE[destination]
    mem = _FakeMem1()
    mem.place_cursor(index, location_id, x, y, **kwargs)
    mem.place_second_object(index)
    mem.place_decoy()
    return mem


class TestDecodingTheLiveValues(unittest.TestCase):
    def test_every_live_destination_decodes_to_what_was_observed(self) -> None:
        for name, (index, location_id, x, y) in LIVE.items():
            with self.subTest(name), _Patched(_mem_for(name)):
                reading = rc.MapCursorTracker().resolve()
                self.assertIsNotNone(reading)
                self.assertEqual(reading.index, index)
                self.assertEqual(reading.location_id, location_id)
                self.assertEqual((reading.x, reading.y), (x, y))
                self.assertEqual(reading.tag_address, TAG_ADDRESS)
                self.assertEqual(reading.record_address, RECORD_ADDRESS)
                self.assertTrue(reading.settled)
                self.assertTrue(reading.consistent)

    def test_the_three_destinations_are_distinguishable_in_both_id_spaces(self) -> None:
        """The whole point of the two-lap experiment: neither id collides across destinations, so either one
        could serve as a key once it is known which is stable."""
        self.assertEqual(len({v[0] for v in LIVE.values()}), len(LIVE))
        self.assertEqual(len({v[1] for v in LIVE.values()}), len(LIVE))

    def test_the_decoy_tag_hit_is_rejected(self) -> None:
        with _Patched(_mem_for("Phenac City")):
            readings = rc.scan_map_cursor()
        self.assertEqual([r.tag_address for r in readings], [TAG_ADDRESS])

    def test_the_second_object_supplies_the_cross_check(self) -> None:
        with _Patched(_mem_for("Cipher Lab")):
            reading = rc.scan_map_cursor()[0]
        self.assertEqual(reading.second_index, LIVE["Cipher Lab"][0])

    def test_the_cross_check_object_is_optional(self) -> None:
        """It was present on the boot this was found on and absent on the very next one (zero hits), so its
        absence must cost nothing -- not the reading, and not `consistent`."""
        mem = _FakeMem1()
        mem.place_cursor(*LIVE["Phenac City"])
        mem.place_decoy()
        with _Patched(mem):
            reading = rc.scan_map_cursor()[0]
        self.assertIsNone(reading.second_index)
        self.assertTrue(reading.consistent)
        self.assertEqual(reading.index, LIVE["Phenac City"][0])

    def test_the_values_are_the_same_after_a_reboot_only_the_address_moves(self) -> None:
        """Live, across a real reboot: the object moved 0x810ED690 -> 0x810EF4D0 and its record moved with
        it, but Phenac City still read index 1 / location id 3 / x 44.0 / y 16.0."""
        index, location_id, x, y = LIVE["Phenac City"]
        moved_tag, moved_record = 0x810EF4D0, 0x810F06E0
        mem = _FakeMem1()
        mem.place_cursor(index, location_id, x, y, tag_address=moved_tag, record_address=moved_record)
        mem.place_decoy()
        with _Patched(mem):
            reading = rc.MapCursorTracker().resolve()
        self.assertEqual(reading.tag_address, moved_tag)
        self.assertEqual(reading.record_address, moved_record)
        self.assertEqual((reading.index, reading.location_id, reading.x, reading.y),
                         (index, location_id, x, y))


class TestRefusingToGuess(unittest.TestCase):
    def test_a_disagreeing_second_object_is_reported_not_hidden(self) -> None:
        mem = _mem_for("Rock Poke Spot")
        mem.place_second_object(LIVE["Rock Poke Spot"][0] + 1)
        with _Patched(mem):
            reading = rc.scan_map_cursor()[0]
        self.assertFalse(reading.consistent)

    def test_a_disagreeing_location_id_mirror_is_reported(self) -> None:
        with _Patched(_mem_for("Phenac City", location_id_mirror=99)):
            reading = rc.scan_map_cursor()[0]
        self.assertFalse(reading.consistent)

    def test_a_reading_taken_mid_pan_is_flagged_unsettled(self) -> None:
        with _Patched(_mem_for("Phenac City", settled=False)):
            reading = rc.scan_map_cursor()[0]
        self.assertFalse(reading.settled)
        self.assertTrue(reading.consistent)   # unsettled is not the same failure as inconsistent

    def test_an_implausible_index_is_not_a_reading(self) -> None:
        mem = _FakeMem1()
        mem.place_cursor(rc.MAP_CURSOR_INDEX_MAX_PLAUSIBLE + 1, 3, 44.0, 16.0)
        with _Patched(mem):
            self.assertEqual(rc.scan_map_cursor(), [])

    def test_a_record_pointer_outside_mem1_is_not_a_reading(self) -> None:
        mem = _FakeMem1()
        mem.place_cursor(1, 3, 44.0, 16.0)
        mem.put_u32(TAG_ADDRESS + rc.MAP_CURSOR_RECORD_POINTER_OFFSET, 0x00000100)
        with _Patched(mem):
            self.assertEqual(rc.scan_map_cursor(), [])

    def test_nan_coordinates_are_not_a_reading(self) -> None:
        mem = _FakeMem1()
        mem.place_cursor(1, 3, 44.0, 16.0)
        mem.put(TAG_ADDRESS + rc.MAP_CURSOR_X_OFFSET, b"\x7f\xc0\x00\x00")  # NaN
        with _Patched(mem):
            self.assertEqual(rc.scan_map_cursor(), [])

    def test_an_empty_map_yields_nothing_rather_than_a_default(self) -> None:
        with _Patched(_FakeMem1()):
            self.assertIsNone(rc.MapCursorTracker().resolve())

    def test_an_unreadable_mem1_yields_nothing_rather_than_raising(self) -> None:
        class _Dead:
            def read(self, address: int, length: int) -> bytes:
                raise RuntimeError("Dolphin went away")

        orig = rc.read_bytes
        rc.read_bytes = _Dead().read
        try:
            self.assertEqual(rc.scan_map_cursor(), [])
            self.assertIsNone(rc.MapCursorTracker().resolve())
        finally:
            rc.read_bytes = orig


class TestTheAddressIsACacheNotAConstant(unittest.TestCase):
    def test_the_second_resolve_does_not_rescan_mem1(self) -> None:
        tracker = rc.MapCursorTracker()
        with _Patched(_mem_for("Phenac City")) as mem:
            tracker.resolve()
            self.assertEqual(mem.full_scans, 1)
            tracker.resolve()
            self.assertEqual(mem.full_scans, 1)
        self.assertEqual(tracker.scans, 1)
        self.assertEqual(tracker.cache_hits, 1)

    def test_a_stale_cached_address_triggers_a_rescan_instead_of_nonsense(self) -> None:
        """A new boot moves the object. The cached address must be re-validated against the tag, not trusted."""
        tracker = rc.MapCursorTracker()
        with _Patched(_mem_for("Phenac City")):
            tracker.resolve()
        moved = 0x81100000
        mem = _FakeMem1()
        mem.place_cursor(*LIVE["Cipher Lab"][:2], *LIVE["Cipher Lab"][2:], tag_address=moved)
        mem.place_second_object(LIVE["Cipher Lab"][0])
        with _Patched(mem):
            reading = tracker.resolve()
        self.assertEqual(reading.tag_address, moved)
        self.assertEqual(reading.index, LIVE["Cipher Lab"][0])
        self.assertEqual(tracker.cache_misses, 1)

    def test_reading_a_wrong_address_directly_returns_none(self) -> None:
        with _Patched(_mem_for("Phenac City")):
            self.assertIsNone(rc.read_map_cursor_at(TAG_ADDRESS + 4))

    def test_no_fixed_address_for_this_object_is_exported(self) -> None:
        """Deliberate: ADDENDUM 140 retracted a bare address that looked convincing. Anything that resolves
        this object has to go through the tag."""
        exported = [n for n in dir(rc) if n.startswith("MAP_CURSOR") and n.endswith("ADDRESS")]
        self.assertEqual(exported, [])


class TestTheReadout(unittest.TestCase):
    def test_the_map_screen_room_id_is_the_one_in_the_room_table(self) -> None:
        self.assertEqual(rc.KNOWN_ROOM_IDS[rc.MAP_SCREEN_ROOM_ID], "map screen")

    def test_off_the_map_screen_the_readout_says_the_numbers_are_stale(self) -> None:
        with _Patched(_mem_for("Phenac City")):
            lines = rc.MapCursorTracker().describe(room_id=153)
        self.assertTrue(any("not on the map screen" in line for line in lines))

    def test_on_the_map_screen_the_readout_gives_a_line_to_record(self) -> None:
        with _Patched(_mem_for("Rock Poke Spot")):
            lines = rc.MapCursorTracker().describe(room_id=rc.MAP_SCREEN_ROOM_ID)
        joined = "\n".join(lines)
        self.assertIn("RECORD THIS", joined)
        self.assertIn("index 9", joined)
        self.assertIn("location id 15", joined)

    def test_an_unsettled_reading_is_not_offered_for_recording(self) -> None:
        with _Patched(_mem_for("Phenac City", settled=False)):
            lines = rc.MapCursorTracker().describe(room_id=rc.MAP_SCREEN_ROOM_ID)
        joined = "\n".join(lines)
        self.assertIn("STILL PANNING", joined)
        self.assertNotIn("RECORD THIS", joined)

    def test_cipher_lab_gets_the_room_id_coincidence_flagged(self) -> None:
        """Cipher Lab's location id is 8, which is also a real room id. The readout should point that out --
        it is the cheapest available clue about which id space is the stable one."""
        with _Patched(_mem_for("Cipher Lab")):
            joined = "\n".join(rc.MapCursorTracker().describe(room_id=rc.MAP_SCREEN_ROOM_ID))
        self.assertIn("may BE the room id", joined)

    def test_unknown_room_is_reported_as_unknown(self) -> None:
        with _Patched(_mem_for("Phenac City")):
            lines = rc.MapCursorTracker().describe(room_id=None)
        self.assertTrue(any("Room is unknown" in line for line in lines))


class TestNothingElseChanged(unittest.TestCase):
    def test_the_poll_loop_does_not_read_the_map_cursor(self) -> None:
        """`!map` is the only caller. If this ever fails it is because the tracker was wired into the poll
        loop -- which is a real decision to make deliberately, not to arrive at by accident."""
        import pathlib
        source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text()
        body = source.split("async def dolphin_sync_task", 1)
        self.assertEqual(len(body), 2, "dolphin_sync_task not found in Client.py")
        self.assertNotIn("map_cursor_tracker", body[1])


if __name__ == "__main__":
    unittest.main()
