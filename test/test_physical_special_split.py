"""Physical/Special Split and Update Moves to Gen 9: each move's Generation IX values, matched to its row by name id."""
from __future__ import annotations

import json
import pathlib
import struct
import unittest

from ..game_data import physical_special_split as S
from ..tools import xd_rel_format as rf

DEFINITIONS = json.loads((pathlib.Path(__file__).resolve().parent.parent / "data" / "move_data.json")
                         .read_text(encoding="utf-8"))["rows"]
BASE = 0x40


def _vanilla_table() -> bytearray:
    """A move table holding every definition's vanilla values, in table order, behind BASE bytes of padding."""
    data = bytearray(BASE + len(DEFINITIONS) * S.MOVE_ENTRY_SIZE)
    for index, d in enumerate(DEFINITIONS):
        row = BASE + index * S.MOVE_ENTRY_SIZE
        for suffix, offset, fmt in S.FIELDS:
            struct.pack_into(fmt, data, row + offset, d[f"Vanilla{suffix}"])
        struct.pack_into(">I", data, row + S.NAME_ID_OFFSET, d["NameId"])
    return data


def _field(data: bytearray, index: int, suffix: str) -> int:
    _, offset, fmt = next(f for f in S.FIELDS if f[0] == suffix)
    return struct.unpack_from(fmt, data, BASE + index * S.MOVE_ENTRY_SIZE + offset)[0]


def _apply(data: bytearray, split: bool = True, gen9_moves: bool = True, definitions=DEFINITIONS) -> dict:
    return S.apply_move_updates(data, BASE, len(definitions), definitions, split=split, gen9_moves=gen9_moves)


def _expected(d: dict, suffix: str, split: bool, gen9_moves: bool) -> int:
    on = split if suffix == "Category" else gen9_moves
    want = d[f"Gen9{suffix}"] if on else d[f"Vanilla{suffix}"]
    return d["VanillaType"] if suffix == "Type" and want > S.MAX_XD_TYPE else want


class TestTheWrite(unittest.TestCase):
    def test_each_option_writes_only_its_own_fields(self):
        for split, gen9_moves in ((True, True), (True, False), (False, True), (False, False)):
            with self.subTest(split=split, gen9_moves=gen9_moves):
                data = _vanilla_table()
                _apply(data, split, gen9_moves)
                for index, d in enumerate(DEFINITIONS):
                    for suffix, _offset, _fmt in S.FIELDS:
                        self.assertEqual(_expected(d, suffix, split, gen9_moves), _field(data, index, suffix),
                                         f"{d['Name']} {suffix}")

    def test_the_split_alone_changes_only_the_category_byte(self):
        data = _vanilla_table()
        before = bytes(data)
        result = _apply(data, split=True, gen9_moves=False)
        for pos, (a, b) in enumerate(zip(before, data)):
            if a != b:
                self.assertEqual(S.CATEGORY_OFFSET, (pos - BASE) % S.MOVE_ENTRY_SIZE)
        self.assertGreater(result["moves_written"], 100)

    def test_flamethrower(self):
        data = _vanilla_table()
        _apply(data, split=True, gen9_moves=False)
        self.assertEqual((2, 95), (_field(data, 53, "Category"), _field(data, 53, "Power")))
        data = _vanilla_table()
        _apply(data, split=False, gen9_moves=True)
        self.assertEqual((0, 90), (_field(data, 53, "Category"), _field(data, 53, "Power")))

    def test_fairy_moves_keep_their_vanilla_type(self):
        for index in (186, 204, 236):   # Sweet Kiss, Charm, Moonlight
            self.assertEqual(DEFINITIONS[index]["VanillaType"], DEFINITIONS[index]["Gen9Type"])
        definitions = [dict(d) for d in DEFINITIONS]
        definitions[204]["Gen9Type"] = 18
        data = _vanilla_table()
        result = _apply(data, definitions=definitions)
        self.assertEqual(["CHARM"], result["types_kept"])
        self.assertEqual(0, _field(data, 204, "Type"))

    def test_negative_priority_round_trips(self):
        data = _vanilla_table()
        _apply(data)
        self.assertEqual(-6, _field(data, 100, "Priority"))   # Teleport

    def test_nothing_outside_the_six_fields_changes(self):
        data = _vanilla_table()
        before = bytes(data)
        _apply(data)
        touched = {o + i for _s, o, fmt in S.FIELDS for i in range(struct.calcsize(fmt))}
        for pos, (a, b) in enumerate(zip(before, data)):
            if a != b:
                self.assertIn((pos - BASE) % S.MOVE_ENTRY_SIZE, touched)


class TestTheRefusals(unittest.TestCase):
    def test_a_non_vanilla_row_refuses_the_whole_table_for_either_option(self):
        """The split alone still proves the five fields it does not write: the table must be vanilla's."""
        for split, gen9_moves in ((True, False), (False, True)):
            data = _vanilla_table()
            struct.pack_into(">B", data, BASE + 53 * S.MOVE_ENTRY_SIZE + S.PP_OFFSET, 99)
            before = bytes(data)
            with self.assertRaises(ValueError):
                _apply(data, split, gen9_moves)
            self.assertEqual(before, bytes(data))

    def test_an_unknown_name_id_refuses(self):
        data = _vanilla_table()
        struct.pack_into(">I", data, BASE + 53 * S.MOVE_ENTRY_SIZE + S.NAME_ID_OFFSET, 0xDEAD)
        with self.assertRaises(ValueError):
            _apply(data)

    def test_a_table_past_the_end_refuses(self):
        with self.assertRaises(ValueError):
            S.apply_move_updates(bytearray(0x100), 0, len(DEFINITIONS), DEFINITIONS, split=True, gen9_moves=True)


class TestTheDolWord(unittest.TestCase):
    def test_the_shadow_check_call_becomes_li_r3_1(self):
        ((address, old, new),) = S.dol_patch_words()
        self.assertEqual(0x8013E820, address)
        self.assertEqual(0x48000001, old & 0xFC000003)                                  # bl
        self.assertEqual(0x8013D03C, address + ((old & 0x03FFFFFC) ^ 0x02000000) - 0x02000000)
        self.assertEqual(0x38600001, new)                                               # li r3,1

    def test_every_shadow_move_already_has_a_category(self):
        """Every move now takes the +0x13 path; the Shadow moves, which always did, must keep theirs."""
        for d in DEFINITIONS[356:374]:
            self.assertIn(d["Gen9Category"], (1, 2), d["Name"])
            self.assertEqual(d["VanillaCategory"], d["Gen9Category"], d["Name"])


class TestTheClientStillFindsTheTable(unittest.TestCase):
    def test_gen9_moves_leaves_every_fingerprint_move_alone(self):
        """The client proves the live move table with `MOVE_TABLE_FINGERPRINT`; a Gen 9 seed must still pass."""
        for index, (pp, power) in rf.MOVE_TABLE_FINGERPRINT.items():
            d = DEFINITIONS[index]
            self.assertEqual((pp, power), (d["Gen9Pp"], d["Gen9Power"]), d["Name"])
            self.assertEqual((pp, power), (d["VanillaPp"], d["VanillaPower"]), d["Name"])

    def test_the_offsets_agree_with_rel_format(self):
        self.assertEqual(rf.MOVE_ENTRY_SIZE, S.MOVE_ENTRY_SIZE)
        self.assertEqual((rf.MOVE_PP_OFFSET, rf.MOVE_TYPE_OFFSET, rf.MOVE_ACCURACY_OFFSET),
                         (S.PP_OFFSET, S.TYPE_OFFSET, S.ACCURACY_OFFSET))
        self.assertEqual(rf.MOVE_BASE_POWER_OFFSET, S.POWER_OFFSET + 1)   # the s16's low byte


if __name__ == "__main__":
    unittest.main()
