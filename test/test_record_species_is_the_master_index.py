"""The 0xC4 Pokemon record's +0x00 is the game's MASTER internal species index, in party and box alike."""
from __future__ import annotations

import struct
import unittest
from unittest import mock

from .. import ram_client as rc
from ..tools import xd_species_index as X
from .local_dumps import DUMPS


def _records(mem: bytes):
    """(record offset, master index) for every record whose two name fields both spell a Gen 3 species."""
    for index, (dex, name) in X.INTERNAL_INDEX_TO_NATIONAL_DEX.items():
        if not name or dex <= 251:
            continue
        pat = name.upper().encode("utf-16-be") + b"\x00\x00"
        at = mem.find(pat)
        while at != -1:
            rec = at - rc.RECORD_TEXT_ANCHOR_OFFSET
            if rec >= 0 and mem[rec + 0x64:rec + 0x64 + len(pat)] == pat:
                yield rec, index
            at = mem.find(pat, at + 1)


class TestAgainstTheDumps(unittest.TestCase):
    def test_every_gen3_record_holds_its_master_index(self) -> None:
        path = DUMPS / "loc_kaminko.bin"
        if not path.is_file():
            self.skipTest("the MEM1 dumps are not on this machine")
        mem = path.read_bytes()
        found = list(_records(mem))
        self.assertGreaterEqual(len(found), 8)
        for rec, index in found:
            self.assertEqual(index, struct.unpack_from(">H", mem, rec)[0], hex(rec))

    def test_the_shadow_scan_names_them_right(self) -> None:
        path = DUMPS / "loc_kaminko.bin"
        if not path.is_file():
            self.skipTest("the MEM1 dumps are not on this machine")
        mem = path.read_bytes()

        def read(address, length):
            off = address - rc.MEM1_START
            return mem[off:off + length]
        with mock.patch.object(rc, "read_bytes", read):
            for rec, index in list(_records(mem))[:20]:
                record = rc._read_shadow_record(rc.MEM1_START + rec, "box", 0)
                self.assertEqual(X.national_dex_for(index), record.dex, hex(rec))


class TestTheConversion(unittest.TestCase):
    def test_sceptile_is_sceptile(self) -> None:
        data = bytearray(0xC4)
        struct.pack_into(">H", data, rc.RECORD_SPECIES_OFFSET, 279)
        data[rc.RECORD_LEVEL_OFFSET] = 26
        with mock.patch.object(rc, "read_bytes", lambda a, n: bytes(data[:n])):
            self.assertEqual(254, rc._read_shadow_record(0x80479000, "party", 0).dex)


if __name__ == "__main__":
    unittest.main()
