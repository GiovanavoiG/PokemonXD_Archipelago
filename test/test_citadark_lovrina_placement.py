"""Lovrina on Citadark 1F is placed on every visit until she is beaten, including after losing to her: the floor's
story windows are opened on the disc, where `preprocess` (which places her) can see them."""
from __future__ import annotations

import pathlib
import struct
import tempfile
import unittest

from .. import ram_client
from ..game_data import citadark_scripts as cd
from ..game_data import shiny_chests as sc
from ..tools import iso_patcher as ip

FSYS = pathlib.Path("/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/maps/D6_fort_1F.fsys")
PATCH = sc.RoomPatch("D6_fort_1F", cd.CITADARK_1F_SIZE, cd._1F_CODE0, cd.CITADARK_1F_WORD_EDITS,
                     cd.CITADARK_1F_ANCHORS, frozenset())


def _word(script: bytes, w: int) -> int:
    return struct.unpack_from(">I", script, cd._1F_CODE0 + 4 * w)[0]


class TestTheEdits(unittest.TestCase):
    def test_one_edit_is_in_preprocess(self):
        # preprocess is w0..w175 on this floor; its `<= 900` at w16 is the one the client patches too late
        self.assertIn(16, {w for w, _o, _n in cd.CITADARK_1F_WORD_EDITS})

    def test_the_patcher_runs_it_every_seed(self):
        src = pathlib.Path(ip.__file__).read_text(encoding="utf-8")
        self.assertIn("lovrina_result = write_citadark_trigger_patch(output_path)", src)


@unittest.skipUnless(FSYS.is_file(), "needs D6_fort_1F.fsys")
class TestOnTheRealFloor(unittest.TestCase):
    def _iso(self, tmp):
        from .test_addendum_456_candy_box_to_citadark_entry import _iso
        path = pathlib.Path(tmp) / "copy.iso"
        path.write_bytes(_iso([(b"D6_fort_1F.fsys", FSYS.read_bytes())]))
        return path

    def _script(self, path):
        reader = ip.open_reader(path)
        try:
            off, length, _rec = ip.find_by_basename(ip.parse_fst(reader), "D6_fort_1F.fsys")
            return reader.read(off, length)
        finally:
            reader.close()

    def test_windows_opened_on_the_disc(self):
        stock = ip._room_entry(FSYS.read_bytes(), 14)[1]
        self.assertEqual((900, 900), (_word(stock, 16), _word(stock, 398)))
        with tempfile.TemporaryDirectory() as tmp:
            path = self._iso(tmp)
            result = ip.write_citadark_trigger_patch(path)
            self.assertTrue(result["applied"], result["reason"])
            container = self._script(path)
            script = ip._room_entry(container, 14)[1]
            self.assertEqual((0x01000384, 0x01000384), (_word(script, 16), _word(script, 398)))
            self.assertEqual(len(stock), len(script))
            self.assertEqual(ip._room_entry(container, 28)[1], ip._room_entry(FSYS.read_bytes(), 28)[1])
            again = ip.write_citadark_trigger_patch(path)
            self.assertEqual((True, "already patched"), (again["applied"], again["reason"]))

    def test_the_client_still_recognises_the_floor(self):
        out = sc.patch_script(ip._room_entry(FSYS.read_bytes(), 14)[1], PATCH)
        spec = next(s for s in ram_client.npc_script_specs() if s.name == "Citadark Isle 1F")
        read = lambda address, length: out[address:address + length]   # noqa: E731
        self.assertTrue(ram_client._npc_script_matches(read, 0, spec))

    def test_with_citadark_admins_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._iso(tmp)
            from .test_addendum_456_candy_box_to_citadark_entry import _iso
            path.write_bytes(_iso([(b"D6_fort_1F.fsys", FSYS.read_bytes()),
                                   (b"D6_fort_3F_1.fsys", FSYS.with_name("D6_fort_3F_1.fsys").read_bytes())]))
            admins = ip.write_citadark_admins_only_patch(path)
            self.assertTrue(admins["applied"], admins["reason"])
            floor_module = ip._room_entry(self._script(path), 28)[1]
            result = ip.write_citadark_trigger_patch(path)
            self.assertTrue(result["applied"], result["reason"])
            container = self._script(path)
            self.assertEqual(floor_module, ip._room_entry(container, 28)[1], "the hidden figures stay hidden")
            self.assertEqual(0x01000384, _word(ip._room_entry(container, 14)[1], 16))


if __name__ == "__main__":
    unittest.main()
