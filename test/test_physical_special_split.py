"""Physical/Special Split: every move's Generation IX values, matched to its row by name id."""
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


class TestTheWrite(unittest.TestCase):
    def test_every_move_takes_its_gen9_values(self):
        data = _vanilla_table()
        result = S.apply_physical_special_split(data, BASE, len(DEFINITIONS), DEFINITIONS)
        for index, d in enumerate(DEFINITIONS):
            for suffix, _offset, _fmt in S.FIELDS:
                want = d[f"Gen9{suffix}"]
                if suffix == "Type" and want > S.MAX_XD_TYPE:
                    want = d["VanillaType"]
                self.assertEqual(want, _field(data, index, suffix), f"{d['Name']} {suffix}")
        self.assertGreater(result["moves_written"], 100)

    def test_flamethrower_is_special_with_90_power(self):
        data = _vanilla_table()
        S.apply_physical_special_split(data, BASE, len(DEFINITIONS), DEFINITIONS)
        self.assertEqual((2, 90), (_field(data, 53, "Category"), _field(data, 53, "Power")))

    def test_fairy_moves_keep_their_vanilla_type(self):
        data = _vanilla_table()
        result = S.apply_physical_special_split(data, BASE, len(DEFINITIONS), DEFINITIONS)
        self.assertEqual({"SWEET KISS", "CHARM", "MOONLIGHT"}, set(result["types_kept"]))
        self.assertEqual(0, _field(data, 204, "Type"))

    def test_negative_priority_round_trips(self):
        data = _vanilla_table()
        S.apply_physical_special_split(data, BASE, len(DEFINITIONS), DEFINITIONS)
        self.assertEqual(-6, _field(data, 100, "Priority"))   # Teleport

    def test_nothing_outside_the_six_fields_changes(self):
        data = _vanilla_table()
        before = bytes(data)
        S.apply_physical_special_split(data, BASE, len(DEFINITIONS), DEFINITIONS)
        touched = {o + i for _s, o, fmt in S.FIELDS for i in range(struct.calcsize(fmt))}
        for pos, (a, b) in enumerate(zip(before, data)):
            if a != b:
                self.assertIn((pos - BASE) % S.MOVE_ENTRY_SIZE, touched)


class TestTheRefusals(unittest.TestCase):
    def test_a_non_vanilla_row_refuses_the_whole_table(self):
        data = _vanilla_table()
        struct.pack_into(">B", data, BASE + 53 * S.MOVE_ENTRY_SIZE + S.PP_OFFSET, 99)
        before = bytes(data)
        with self.assertRaises(ValueError):
            S.apply_physical_special_split(data, BASE, len(DEFINITIONS), DEFINITIONS)
        self.assertEqual(before, bytes(data))

    def test_an_unknown_name_id_refuses(self):
        data = _vanilla_table()
        struct.pack_into(">I", data, BASE + 53 * S.MOVE_ENTRY_SIZE + S.NAME_ID_OFFSET, 0xDEAD)
        with self.assertRaises(ValueError):
            S.apply_physical_special_split(data, BASE, len(DEFINITIONS), DEFINITIONS)

    def test_a_table_past_the_end_refuses(self):
        with self.assertRaises(ValueError):
            S.apply_physical_special_split(bytearray(0x100), 0, len(DEFINITIONS), DEFINITIONS)


class TestTheClientStillFindsTheTable(unittest.TestCase):
    def test_the_split_leaves_every_fingerprint_move_alone(self):
        """The client proves the live move table with `MOVE_TABLE_FINGERPRINT`; a split seed must still pass."""
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
