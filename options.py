"""ADDENDUM 456 (2026-10-09) -- Reduce Citadark Grind: `equal_to_citadark_entry`.

A `reduce_citadark_grind` choice, `equal_to_citadark_entry`, makes the Candy Box level the party to the
lowest-level Pokemon placed on Citadark Isle, accounting for level scaling and path level scaling.
"""
from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from . import PokemonXDTestBase
from .. import Client
from ..game_data import candy_box as CB
from ..game_data import trainer_placements as tp
from ..options import ReduceCitadarkGrind
from ..tools import iso_patcher as ip
from ..tools import xd_deck_format as deck_format

DUMPS = Path("/mnt/user-data/uploads/PokemonXD-working/bridge/dumps")
PATCHER = Path(ip.__file__).read_text(encoding="utf-8")
CLIENT = Path(Client.__file__).read_text(encoding="utf-8")


class TestTheOption(unittest.TestCase):
    def test_values_and_old_yamls(self) -> None:
        self.assertEqual({"off": 0, "on": 1, "equal_to_citadark_entry": 2},
                         {k: v for k, v in ReduceCitadarkGrind.options.items()
                          if k in ("off", "on", "equal_to_citadark_entry")})
        self.assertEqual(0, ReduceCitadarkGrind.default)
        # A YAML written for the old toggle still means the same thing.
        self.assertEqual(1, ReduceCitadarkGrind.from_any(True).value)
        self.assertEqual(0, ReduceCitadarkGrind.from_any(False).value)
        self.assertEqual(2, ReduceCitadarkGrind.from_any("equal_to_citadark_entry").value)
        self.assertEqual(CB.GRIND_CITADARK_ENTRY, 2)


class TestTheTable(unittest.TestCase):
    def test_capped_at_the_entry_level(self) -> None:
        table = CB.target_level_table(entry_level=48)
        self.assertEqual({48}, set(table))
        self.assertEqual(CB.target_level_table(), CB.target_level_table(entry_level=None))
        high = CB.target_level_table(entry_level=100)
        self.assertEqual(99, high[CB.EVOLVES_FURTHER[0]], "still leaves room for an evolution")
        with self.assertRaises(ValueError):
            CB.target_level_table(entry_level=0)

    def test_only_the_table_changes_in_main_dol(self) -> None:
        plain, entry = CB.dol_patch_words(False), CB.dol_patch_words(False, 41)
        self.assertEqual([a for a, _v, _n in plain], [a for a, _v, _n in entry])
        table_start = CB.CAVE_ADDRESS + CB.TABLE_OFFSET
        table_end = table_start + CB.SPECIES_COUNT
        changed = [a for (a, _v, n1), (_a, _w, n2) in zip(plain, entry) if n1 != n2]
        self.assertTrue(changed)
        self.assertTrue(all(table_start <= a < table_end for a in changed))


def _story_deck() -> bytes:
    """Trainer 1 (not Citadark) at 10; trainer 2 (Citadark) with 30, 45 and a Shadow (DDPK 1) at 25."""
    dtnr_entries, dpkm_entries = 3, 4
    dtnr = bytearray(0x10 + dtnr_entries * 0x38)
    dtnr[0:4] = b"DTNR"
    struct.pack_into(">II", dtnr, 4, len(dtnr), dtnr_entries)
    t1 = 0x10 + 1 * 0x38
    dtnr[t1 + 5] = 1
    struct.pack_into(">H", dtnr, t1 + 0x1C, 1)
    t2 = 0x10 + 2 * 0x38
    dtnr[t2 + 5] = 1
    dtnr[t2 + 4] = 0b100                             # slot 2 is a Shadow
    struct.pack_into(">HHH", dtnr, t2 + 0x1C, 2, 3, 1)
    dpkm = bytearray(0x10 + dpkm_entries * 0x20)
    dpkm[0:4] = b"DPKM"
    struct.pack_into(">II", dpkm, 4, len(dpkm), dpkm_entries)
    for index, level in ((1, 10), (2, 30), (3, 45)):
        struct.pack_into(">HB", dpkm, 0x10 + index * 0x20, 25, level)
    tail = b"".join(bytes(tag) + struct.pack(">I", 0x10) + bytes(8) for tag in (b"DTAI", b"DSTR"))
    return b"DECK" + bytes(12) + bytes(dtnr) + bytes(dpkm) + tail


def _dark_deck(shadow_level: int = 25) -> bytes:
    entries = 2
    ddpk = bytearray(0x10 + entries * 0x18)
    ddpk[0:4] = b"DDPK"
    struct.pack_into(">II", ddpk, 4, len(ddpk), entries)
    rec = 0x10 + 1 * 0x18
    ddpk[rec + 2] = shadow_level
    ddpk[rec + 3] = 1
    struct.pack_into(">H", ddpk, rec + 6, 3)
    return b"DECK" + bytes(12) + bytes(ddpk)


def _iso(files: "list[tuple[bytes, bytes]]") -> bytes:
    fst_offset, data_at = 0x440, 0x800
    count = len(files) + 1
    names = b"".join(name + b"\x00" for name, _c in files)
    fst = bytearray(count * 12) + names
    fst[0] = 1
    struct.pack_into(">I", fst, 8, count)
    cursor, name_cursor, blobs = data_at, 0, b""
    for i, (name, container) in enumerate(files, start=1):
        struct.pack_into(">III", fst, i * 12, name_cursor, cursor, len(container))
        name_cursor += len(name) + 1
        blobs += container
        cursor += len(container)
    iso = bytearray(data_at) + blobs
    struct.pack_into(">II", iso, 0x424, fst_offset, len(fst))
    iso[fst_offset:fst_offset + len(fst)] = fst
    return bytes(iso)


class TestReadingTheLevelOffTheIso(unittest.TestCase):
    def _run(self, shadow_level: int) -> dict:
        from .test_addendum_423_nightmare_citadark import _fsys
        iso = _iso([(b"deck_archive.fsys", _fsys([(b"DeckData_Story.bin", _story_deck())])),
                    (b"common.fsys", _fsys([(b"DeckData_DarkPokemon.bin", _dark_deck(shadow_level))]))])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "copy.iso"
            path.write_bytes(iso)
            return ip.read_citadark_entry_level(path, [2])

    def test_the_shadow_can_be_the_lowest(self) -> None:
        result = self._run(25)
        self.assertEqual((25, 2, 2, "DDPK", 3),
                         (result["level"], result["trainer_index"], result["slot"], result["kind"], result["members"]))

    def test_otherwise_the_lowest_ordinary_member(self) -> None:
        result = self._run(50)
        self.assertEqual((30, "DPKM"), (result["level"], result["kind"]), "trainer 1's level 10 is not Citadark")

    def test_no_trainers_raises(self) -> None:
        from .test_addendum_423_nightmare_citadark import _fsys
        iso = _iso([(b"deck_archive.fsys", _fsys([(b"DeckData_Story.bin", _story_deck())])),
                    (b"common.fsys", _fsys([(b"DeckData_DarkPokemon.bin", _dark_deck())]))])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "copy.iso"
            path.write_bytes(iso)
            with self.assertRaises(ValueError):
                ip.read_citadark_entry_level(path, [])

    @unittest.skipUnless((DUMPS / "deck_story_1.bin").is_file(), "needs the deck dumps")
    def test_vanilla_citadark_starts_at_33(self) -> None:
        story = deck_format.DeckFile(deck_format.lzss_decode((DUMPS / "deck_story_1.bin").read_bytes()))
        dark = deck_format.DarkPokemonFile(deck_format.lzss_decode((DUMPS / "deck_dark_1.bin").read_bytes()))
        levels = []
        for index, placement in tp.PLACEMENTS.items():
            if placement.region != "Citadark Isle" or story.trainer(index) is None:
                continue
            for member in story.trainer(index)["team"]:
                levels.append(member["level"] if member["kind"] == "DPKM"
                              else dark.ddpk_full(member["ddpk_index"])["shadow_level"])
        self.assertEqual(33, min(levels))


class TestThePatcherOrder(unittest.TestCase):
    def test_read_after_every_team_pass_and_before_the_code(self) -> None:
        body = PATCHER[PATCHER.index("def apply_patch("):]
        read = body.index("read_citadark_entry_level(output_path")
        for team_pass in ("write_enhanced_difficulty_patch(output_path", "write_nightmare_citadark_patch(",
                          "write_shadow_multi_trainer_patch(output_path"):
            self.assertLess(body.index(team_pass), read, team_pass)
        self.assertLess(read, body.index("_candy.dol_patch_words(trade_evolutions_by_level"))

    def test_the_client_text(self) -> None:
        self.assertIn("_candy.CANDY_BOX_CITADARK_DESCRIPTION_LINES", CLIENT)
        self.assertTrue(all(len(line) <= 20 for line in CB.CANDY_BOX_CITADARK_DESCRIPTION_LINES))


class TestTheSeed(PokemonXDTestBase):
    options = {"reduce_citadark_grind": "equal_to_citadark_entry", "path_level_scaling": True}

    def test_carries_the_mode_and_the_trainers(self) -> None:
        import json
        import zipfile
        world = self.multiworld.worlds[self.player]
        self.assertEqual(2, world.fill_slot_data()["reduce_citadark_grind"])
        with tempfile.TemporaryDirectory() as tmp:
            world.generate_output(tmp)
            with zipfile.ZipFile(next(Path(tmp).glob("*.appxd"))) as zf:
                seed = json.loads(zf.read("seed.json"))
        self.assertTrue(seed["reduce_citadark_grind"])
        self.assertEqual("citadark_entry", seed["candy_box_target"])
        self.assertEqual(list(range(168, 202)), seed["citadark_trainer_indices"])


class TestTheOldSettingIsUntouched(PokemonXDTestBase):
    options = {"reduce_citadark_grind": True}

    def test_no_entry_keys(self) -> None:
        import json
        import zipfile
        world = self.multiworld.worlds[self.player]
        with tempfile.TemporaryDirectory() as tmp:
            world.generate_output(tmp)
            with zipfile.ZipFile(next(Path(tmp).glob("*.appxd"))) as zf:
                seed = json.loads(zf.read("seed.json"))
        self.assertNotIn("candy_box_target", seed)


if __name__ == "__main__":
    unittest.main()
