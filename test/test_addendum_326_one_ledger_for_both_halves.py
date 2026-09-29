"""ADDENDUM 326 -- the flip-watcher and the party/PC scan count against ONE identity.

Player, with `!purifications` output:

    Purifications: 4 counted (4 distinct species recorded).
      species already counted: 2, 248, 276, 350
      Shadow ids counted (ADDENDUM 320, survives evolution): 1, 84, 85
      counted by the party/PC scan: 3 (purified flag: 3)

Four counts, three Shadows. The scan counted ids 1, 84 and 85 from their records; the flip-watcher counted a
fourth under a species key matching none of them. The two halves read the same Pokemon from different places --
the watcher from PARTY_BASE (the menu struct, which can still hold the previous occupant right after a
purification reorders the party) and the scan from the save record's shadow id -- so each saw something the
other had not counted."""
import struct
import unittest
from unittest import mock

from .. import ram_client as rc

from ..tools.xd_species_index import national_dex_for_live_species

BLOCK = 0x80479000
SHADOW_ID = 84
# The record holds a LIVE species index; what the ledger stores is its National Dex number (ADDENDUM 249).
# Written through the same conversion the reader uses, so the fixture cannot quietly disagree with it.
RECORD_INTERNAL, SECOND_INTERNAL = 216, 217
RECORD_DEX = national_dex_for_live_species(RECORD_INTERNAL)
SECOND_DEX = national_dex_for_live_species(SECOND_INTERNAL)
STALE_DEX = 350


def _record_bytes(species_internal: int, shadow_id: int, purified: int, pid: int = 0xCAFEBABE) -> bytes:
    data = bytearray(0xC4)
    struct.pack_into(">H", data, rc.RECORD_SPECIES_OFFSET, species_internal)
    data[rc.RECORD_LEVEL_OFFSET] = 30
    struct.pack_into(">I", data, rc.RECORD_TRAINER_ID_OFFSET, 0xF9AFB2B3)
    struct.pack_into(">I", data, rc.RECORD_PID_OFFSET, pid)
    struct.pack_into(">H", data, rc.RECORD_SHADOW_ID_OFFSET, shadow_id)
    struct.pack_into(">H", data, rc.RECORD_PURIFIED_FLAG_OFFSET, purified)
    struct.pack_into(">H", data, rc.RECORD_CURRENT_HP_OFFSET, 30)   # ADDENDUM 328
    struct.pack_into(">H", data, rc.RECORD_MAX_HP_OFFSET, 55)
    return bytes(data)


class _Fixture:
    """One purified Shadow in party slot 1, and a flip-watcher that reports a DIFFERENT species for it."""

    def __init__(self, test, record: "bytes | None"):
        self.record = record
        self.address = rc.party_record_address(BLOCK, 1)
        patch_read = mock.patch.object(rc, "read_bytes", side_effect=self._read)
        patch_read.start()
        test.addCleanup(patch_read.stop)

    def _read(self, address, length):
        if address == self.address and self.record is not None:
            return self.record
        return bytes(length)


class TestTheDoubleCount(unittest.TestCase):
    def setUp(self):
        self.tracker = rc.PurificationCountTracker()
        # The scan has already counted this Shadow by its record.
        self.tracker.observe_records([
            rc.ShadowRecord("box", 1, RECORD_DEX, SHADOW_ID, rc.PURIFIED_FLAG_VALUE, 30, 0xF9AFB2B3,
                            0xCAFEBABE, 30, 55),
        ])
        self.tracker.observe_records([
            rc.ShadowRecord("box", 1, RECORD_DEX, SHADOW_ID, rc.PURIFIED_FLAG_VALUE, 30, 0xF9AFB2B3,
                            0xCAFEBABE, 30, 55),
        ])
        self.assertEqual(1, self.tracker.total_purified, "premise: the scan counted it")

    def _flip(self, species):
        """Drive PurificationCountTracker.poll with a flip-watcher that reports `species` in slot 1."""
        with mock.patch.object(rc.NamedPurificationTracker, "poll", return_value=[(species, 1)]):
            return self.tracker.poll(BLOCK)

    def test_the_watcher_no_longer_counts_it_again(self) -> None:
        _Fixture(self, _record_bytes(RECORD_INTERNAL, SHADOW_ID, rc.PURIFIED_FLAG_VALUE))
        self.assertEqual([], self._flip(STALE_DEX), "the stale species must not open a second count")
        self.assertEqual(1, self.tracker.total_purified)

    def test_it_is_the_shadow_id_that_matches_them_up(self) -> None:
        _Fixture(self, _record_bytes(RECORD_INTERNAL, SHADOW_ID, rc.PURIFIED_FLAG_VALUE))
        self._flip(STALE_DEX)
        self.assertEqual({SHADOW_ID}, self.tracker.purified_shadow_ids)
        self.assertNotIn(STALE_DEX, self.tracker.purified_species, "the stale species is not a purification")

    def test_a_genuinely_new_shadow_still_counts(self) -> None:
        _Fixture(self, _record_bytes(SECOND_INTERNAL, 85, rc.PURIFIED_FLAG_VALUE, pid=0x1234))
        crossed = self._flip(SECOND_DEX)
        self.assertEqual([rc.purification_location_name(2)], crossed)
        self.assertEqual({SHADOW_ID, 85}, self.tracker.purified_shadow_ids)

    def test_an_unreadable_record_falls_back_to_the_old_behaviour(self) -> None:
        """Species-only counting can duplicate; dropping a purification cannot be undone. The fallback keeps
        the recoverable direction."""
        _Fixture(self, None)
        self.assertEqual([rc.purification_location_name(2)], self._flip(999))

    def test_the_watcher_adopts_the_id_when_the_species_was_counted_first(self) -> None:
        """The reverse order: the species ledger already has it, so the count is refused AND the ledgers are
        brought into agreement, so the scan cannot count it later either."""
        tracker = rc.PurificationCountTracker()
        tracker.purified_species.add(RECORD_DEX)
        tracker.total_purified = 1
        _Fixture(self, _record_bytes(RECORD_INTERNAL, SHADOW_ID, rc.PURIFIED_FLAG_VALUE))
        with mock.patch.object(rc.NamedPurificationTracker, "poll", return_value=[(RECORD_DEX, 1)]):
            self.assertEqual([], tracker.poll(BLOCK))
        self.assertIn(SHADOW_ID, tracker.purified_shadow_ids)
        self.assertEqual(1, tracker.total_purified)


class TestTheCountsStayHonest(unittest.TestCase):
    def test_the_ledgers_can_never_disagree_about_a_counted_shadow(self) -> None:
        """The property behind both halves: every counted shadow id whose species is known is in both."""
        tracker = rc.PurificationCountTracker()
        for dex, shadow_id in ((276, 1), (350, 84), (248, 85)):
            for _ in range(rc.PURIFICATION_SCAN_CONFIRM_SCANS):
                tracker.observe_records([
                    rc.ShadowRecord("party", 0, dex, shadow_id, rc.PURIFIED_FLAG_VALUE, 30, 1, shadow_id,
                                    20, 44)])
        self.assertEqual({1, 84, 85}, tracker.purified_shadow_ids)
        self.assertEqual({276, 350, 248}, tracker.purified_species)
        self.assertEqual(3, tracker.total_purified)
