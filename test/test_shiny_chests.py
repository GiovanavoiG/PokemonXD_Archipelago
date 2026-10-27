"""The Cipher Lab's ID Card and Data ROM chests stay until opened, whatever the Bag holds."""
from __future__ import annotations

import pathlib
import struct
import tempfile
import unittest

from .. import ram_client
from ..game_data import shiny_chests as SC
from ..tools import iso_patcher as ip

FSYS = pathlib.Path("/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/xd_D1_labo_B1.bin")


def _script() -> bytes:
    return ip._room_entry(FSYS.read_bytes(), 14)[1]


class TestTheEdits(unittest.TestCase):
    def test_flags_are_the_chests_own(self):
        from ..game_data import chest_flags
        self.assertEqual(chest_flags.CHEST_FLAG_IDS[17], SC.OPENED_FLAG[17])
        self.assertEqual(chest_flags.CHEST_FLAG_IDS[18], SC.OPENED_FLAG[18])

    def test_every_has_item_call_becomes_a_flag_test(self):
        news = {w: new for w, _old, new in SC.WORD_EDITS}
        olds = {w: old for w, old, _new in SC.WORD_EDITS}
        calls = [w for w, old in olds.items() if old == 0x092B001C]
        self.assertEqual(4, len(calls))
        for w in calls:
            self.assertEqual(0x09000084, news[w])
            self.assertEqual((0x1103002B, 0x10), (olds[w - 1], news[w - 1] >> 24), "ldncvar obj43 -> a line marker")
            self.assertEqual((0x06020000, 0x06010000), (olds[w + 1], news[w + 1]))
            self.assertIn(news[w - 2], (1139, 1145))

    def test_the_client_lab_patch_is_untouched(self):
        from ..game_data import cipher_lab_scripts as cl
        mine = {w for w, _o, _n in SC.WORD_EDITS}
        self.assertFalse(mine & {w for w, _o, _n in cl.CIPHER_LAB_B1_WORD_EDITS})
        self.assertEqual((cl.CIPHER_LAB_B1_SIZE, cl._B1_CODE0), (SC.SCRIPT_SIZE, SC.CODE0))


@unittest.skipUnless(FSYS.is_file(), "needs D1_labo_B1.fsys")
class TestOnTheRealScript(unittest.TestCase):
    def test_patch_and_refuse(self):
        script = _script()
        out = SC.patch_script(script)
        self.assertEqual(len(script), len(out))
        self.assertTrue(SC.is_patched(out))
        self.assertEqual(out, SC.patch_script(out), "idempotent")
        bad = bytearray(script)
        struct.pack_into(">I", bad, SC.CODE0 + 4 * 115, 0x12345678)
        with self.assertRaises(ValueError):
            SC.patch_script(bytes(bad))

    def test_the_client_still_recognises_the_floor(self):
        out = SC.patch_script(_script())
        spec = next(s for s in ram_client.npc_script_specs() if s.name == "Cipher Lab B1")
        read = lambda address, length: out[address:address + length]   # noqa: E731
        self.assertTrue(ram_client._npc_script_matches(read, 0, spec))

    def test_end_to_end_on_an_iso(self):
        from .test_addendum_456_candy_box_to_citadark_entry import _iso
        iso = _iso([(b"D1_labo_B1.fsys", FSYS.read_bytes())])
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "copy.iso"
            path.write_bytes(iso)
            result = ip.write_shiny_chest_patch(path, {17, 18})
            self.assertTrue(result["applied"], result["reason"])
            reader = ip.open_reader(path)
            try:
                off, length, _rec = ip.find_by_basename(ip.parse_fst(reader), "D1_labo_B1.fsys")
                container = reader.read(off, length)
            finally:
                reader.close()
            self.assertTrue(SC.is_patched(ip._room_entry(container, 14)[1]))
            self.assertEqual(ip._room_entry(container, 28)[1], ip._room_entry(FSYS.read_bytes(), 28)[1])
            again = ip.write_shiny_chest_patch(path, {17, 18})
            self.assertEqual((True, "already patched"), (again["applied"], again["reason"]))


HOUSE = pathlib.Path("/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/maps/M1_houseB_1F.fsys")


@unittest.skipUnless(HOUSE.is_file() and FSYS.is_file(), "needs M1_houseB_1F.fsys and D1_labo_B1.fsys")
class TestTheMusicDiscHouse(unittest.TestCase):
    def test_the_scene_needs_the_disc(self):
        script = ip._room_entry(HOUSE.read_bytes(), 14)[1]
        out = SC.patch_script(script, SC.MUSIC_DISC_HOUSE)
        self.assertEqual(len(script), len(out))
        word = lambda blob, w: struct.unpack_from(">I", blob, SC.MUSIC_DISC_HOUSE.code0 + 4 * w)[0]  # noqa: E731
        self.assertEqual(1454, word(script, 479), "stock: the chest's opened flag")
        self.assertEqual([0x02010000, 507, 0x1103002B, 0x092B001C, 0x06020000], [word(out, w) for w in range(477, 482)])
        self.assertEqual(word(script, 482), word(out, 482), "then `== 1` as before")
        self.assertEqual(0x0D000000, word(out, 476), "the function still opens with its reserve")

    def test_both_rooms_on_one_iso(self):
        from .test_addendum_456_candy_box_to_citadark_entry import _iso
        iso = _iso([(b"D1_labo_B1.fsys", FSYS.read_bytes()), (b"M1_houseB_1F.fsys", HOUSE.read_bytes())])
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "copy.iso"
            path.write_bytes(iso)
            result = ip.write_shiny_chest_patch(path, {17, 18, 80})
            self.assertTrue(result["applied"], result["reason"])
            self.assertEqual(["D1_labo_B1", "M1_houseB_1F"], result["rooms"])
            reader = ip.open_reader(path)
            try:
                fst = ip.parse_fst(reader)
                for patch, name in ((SC.CIPHER_LAB_B1, "D1_labo_B1.fsys"), (SC.MUSIC_DISC_HOUSE, "M1_houseB_1F.fsys")):
                    off, length, _rec = ip.find_by_basename(fst, name)
                    self.assertTrue(SC.is_patched(ip._room_entry(reader.read(off, length), 14)[1], patch), name)
            finally:
                reader.close()


class TestThePatcherRunsIt(unittest.TestCase):
    def test_gated_on_the_shuffled_chests(self):
        src = pathlib.Path(ip.__file__).read_text(encoding="utf-8")
        self.assertIn('_shuffled_chests = set(seed.get("shuffled_key_item_chest_ids") or ())', src)
        self.assertIn("if {17, 18, 80} & _shuffled_chests:", src)
        self.assertIn("write_shiny_chest_patch(output_path, _shuffled_chests)", src)

    def test_which_rooms(self):
        self.assertEqual((), SC.patches_for(set()))
        self.assertEqual((SC.CIPHER_LAB_B1,), SC.patches_for({18}))
        self.assertEqual((SC.MUSIC_DISC_HOUSE,), SC.patches_for({80, 42}))
        self.assertEqual(SC.ROOM_PATCHES, SC.patches_for({17, 18, 42, 78, 80}))


if __name__ == "__main__":
    unittest.main()
