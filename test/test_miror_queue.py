"""`/mirorqueue`: the Shadows the save has queued for Miror B."""
from __future__ import annotations

import struct
import unittest
from types import SimpleNamespace
from unittest import mock

from .. import Client
from .. import ram_client as rc
from .local_dumps import DUMPS


def _dump_reader(name: str):
    path = DUMPS / name
    if not path.is_file():
        return None, None
    mem = path.read_bytes()

    def read(address, length):
        off = address - rc.MEM1_START
        return mem[off:off + length]
    savedata = struct.unpack(">I", read(rc.SAVEDATA_NOW_POINTER, 4))[0]
    return read, savedata + rc.SAVEDATA_HERO_OFFSET + rc.RECORD_TRAINER_NAME_OFFSET


class TestTheQueue(unittest.TestCase):
    def test_it_reads_the_fled_shadows(self) -> None:
        read, block = _dump_reader("mapsel_s1_phenac.bin")
        if read is None:
            self.skipTest("the MEM1 dumps are not on this machine")
        with mock.patch.object(rc, "read_bytes", read):
            queue = rc.read_miror_queue(block)
        self.assertEqual([18, 98, 101], [shadow_id for shadow_id, _s, _e in queue])

    def test_an_empty_queue_is_empty_not_unreadable(self) -> None:
        read, block = _dump_reader("loc_kaminko.bin")
        if read is None:
            self.skipTest("the MEM1 dumps are not on this machine")
        with mock.patch.object(rc, "read_bytes", read):
            self.assertEqual([], rc.read_miror_queue(block))

    def test_garbage_is_unreadable(self) -> None:
        with mock.patch.object(rc, "read_bytes", lambda a, n: b"\x00" * n):
            self.assertIsNone(rc.read_miror_queue(0x80479300))

    def test_the_command_lists_them_in_escape_order(self) -> None:
        ctx = SimpleNamespace(block_base=0x80479300, missable_shadow_pusher=SimpleNamespace(sent=["Mawile"]))
        queue = [(101, 280, 13509), (18, 316, 13000)]
        with mock.patch.object(rc, "read_miror_queue", lambda b: queue), \
                mock.patch.object(rc, "gs_flag_get", lambda f: 91):
            lines = Client.describe_miror_queue(ctx)
        self.assertIn("holding 2 Shadow(s)", lines[0])
        self.assertIn("Oasis Poke Spot", lines[0])
        self.assertIn("Shadow #18", lines[1])
        self.assertIn("Shadow #101", lines[2])
        with mock.patch.object(rc, "read_miror_queue", lambda b: []), mock.patch.object(rc, "gs_flag_get", lambda f: 0):
            self.assertIn("no Shadows queued", Client.describe_miror_queue(ctx)[0])


if __name__ == "__main__":
    unittest.main()
