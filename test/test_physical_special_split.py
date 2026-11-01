"""Physical/Special Split and Update Moves to Gen 9: each move's Generation IX values, matched to its row by name id."""
from __future__ import annotations

import hashlib
import json
import pathlib
import struct
import unittest
from unittest import mock

from ..game_data import physical_special_split as S
from ..tools import xd_rel_format as rf

DEFINITIONS = json.loads((pathlib.Path(__file__).resolve().parent.parent / "data" / "move_data.json")
                         .read_text(encoding="utf-8"))["rows"]
BASE = 0x40


#: What `_vanilla_table` writes for a field a definition leaves out; the patch must leave it there.
UNLISTED = 7


def _vanilla(d: dict, suffix: str) -> int:
    return d.get(f"Vanilla{suffix}", UNLISTED)


def _vanilla_table(definitions=DEFINITIONS) -> bytearray:
    """A move table holding every definition's vanilla values, in table order, behind BASE bytes of padding."""
    data = bytearray(BASE + len(definitions) * S.MOVE_ENTRY_SIZE)
    for index, d in enumerate(definitions):
        row = BASE + index * S.MOVE_ENTRY_SIZE
        for suffix, offset, fmt in S.FIELDS:
            struct.pack_into(fmt, data, row + offset, _vanilla(d, suffix))
        struct.pack_into(">I", data, row + S.NAME_ID_OFFSET, d["NameId"])
    return data


def _field(data: bytearray, index: int, suffix: str) -> int:
    _, offset, fmt = next(f for f in S.FIELDS if f[0] == suffix)
    return struct.unpack_from(fmt, data, BASE + index * S.MOVE_ENTRY_SIZE + offset)[0]


def _apply(data: bytearray, split: bool = True, gen9_moves: bool = True, definitions=DEFINITIONS) -> dict:
    return S.apply_move_updates(data, BASE, len(definitions), definitions, split=split, gen9_moves=gen9_moves)


def _expected(d: dict, suffix: str, split: bool, gen9_moves: bool) -> int:
    on = split if suffix == "Category" else gen9_moves
    want = d.get(f"Gen9{suffix}", UNLISTED) if on else _vanilla(d, suffix)
    return _vanilla(d, "Type") if suffix == "Type" and want > S.MAX_XD_TYPE else want


class TestTheDefinitions(unittest.TestCase):
    def test_each_row_lists_only_the_fields_gen9_changes_in_pairs(self):
        for d in DEFINITIONS:
            for suffix, _offset, _fmt in S.FIELDS:
                self.assertEqual(f"Vanilla{suffix}" in d, f"Gen9{suffix}" in d, f"{d['Name']} {suffix}")
                if f"Gen9{suffix}" in d:
                    self.assertNotEqual(d[f"Vanilla{suffix}"], d[f"Gen9{suffix}"], f"{d['Name']} {suffix}")


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
            self.assertNotIn("Gen9Type", DEFINITIONS[index])
        definitions = [dict(d) for d in DEFINITIONS]
        definitions[204].update(VanillaType=0, Gen9Type=18)
        data = _vanilla_table(definitions)
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
        """The split alone still proves the listed fields it does not write: the table must be vanilla's."""
        for split, gen9_moves in ((True, False), (False, True)):
            data = _vanilla_table()
            struct.pack_into(">h", data, BASE + 53 * S.MOVE_ENTRY_SIZE + S.POWER_OFFSET, 99)
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


class TestTheDescriptionIds(unittest.TestCase):
    def _table_with_description_ids(self) -> bytearray:
        data = _vanilla_table()
        for index in range(len(DEFINITIONS)):
            struct.pack_into(">I", data, BASE + index * S.MOVE_ENTRY_SIZE + S.DESCRIPTION_ID_OFFSET, 10500 + index)
        return data

    def test_the_split_reports_each_changed_move_by_its_description_id(self):
        result = _apply(self._table_with_description_ids(), split=True, gen9_moves=False)
        changed = {10500 + i: d["Gen9Category"] for i, d in enumerate(DEFINITIONS) if "Gen9Category" in d}
        self.assertEqual(changed, result["descriptions"])
        self.assertEqual(1, result["descriptions"][10501])      # POUND
        self.assertEqual(2, result["descriptions"][10553])      # FLAMETHROWER

    def _with_shadow_moves(self) -> bytearray:
        """The vanilla Shadow rows' category and power: SHADOW RUSH 1/55, SHADOW WAVE 2/50, SHADOW HOLD 2/0."""
        data = self._table_with_description_ids()
        for name, category, power in (("SHADOW RUSH", 1, 55), ("SHADOW WAVE", 2, 50), ("SHADOW HOLD", 2, 0)):
            row = BASE + next(i for i, d in enumerate(DEFINITIONS) if d["Name"] == name) * S.MOVE_ENTRY_SIZE
            data[row + S.CATEGORY_OFFSET] = category
            struct.pack_into(">h", data, row + S.POWER_OFFSET, power)
        return data

    def _description_id(self, name: str) -> int:
        return 10500 + next(i for i, d in enumerate(DEFINITIONS) if d["Name"] == name)

    def test_the_split_reports_each_shadow_move_with_a_power_by_its_own_category(self):
        data = self._with_shadow_moves()
        descriptions = _apply(data, split=True, gen9_moves=False)["descriptions"]
        self.assertEqual(1, descriptions[self._description_id("SHADOW RUSH")])
        self.assertEqual(2, descriptions[self._description_id("SHADOW WAVE")])
        self.assertNotIn(self._description_id("SHADOW HOLD"), descriptions)
        self.assertEqual(1, _field(data, self._description_id("SHADOW RUSH") - 10500, "Category"))   # left as it was

    def test_gen9_moves_alone_reports_none(self):
        self.assertEqual({}, _apply(self._with_shadow_moves(), split=False, gen9_moves=True)["descriptions"])


OVERFLOW_SIZE = 0x200


def _message_table(strings: "dict[int, bytes]", slack: int = 0) -> bytes:
    """A message table holding `strings` (id: text without its terminator), in id order, then `slack` zero bytes."""
    head = S.MESSAGE_PAIRS_OFFSET + len(strings) * S.MESSAGE_PAIR_SIZE
    table = bytearray(head)
    struct.pack_into(">H", table, S.MESSAGE_COUNT_OFFSET, len(strings))
    for index, (string_id, text) in enumerate(sorted(strings.items())):
        struct.pack_into(">II", table, S.MESSAGE_PAIRS_OFFSET + index * S.MESSAGE_PAIR_SIZE, string_id, len(table))
        table += text + b"\x00\x00"
    table += bytes(slack + (-(len(table) + slack) % 4))
    return bytes(table)


def _text(*lines: str) -> bytes:
    return S.LINE_BREAK.join(line.encode("utf-16-be") for line in lines)


def _resolve(table: bytes, overflow: bytes, string_id: int) -> bytes:
    """What the game's lookup returns: the bytes up to the terminator at table + the pair's offset, mod 2^32."""
    count = struct.unpack_from(">H", table, S.MESSAGE_COUNT_OFFSET)[0]
    for index in range(count):
        raw_id, offset = struct.unpack_from(">II", table, S.MESSAGE_PAIRS_OFFSET + index * S.MESSAGE_PAIR_SIZE)
        if raw_id & S.MESSAGE_ID_MASK == string_id:
            address = (S.MESSAGE_TABLE + offset) & 0xFFFFFFFF
            data, at = ((overflow, address - S.DESCRIPTION_OVERFLOW) if address >= S.DESCRIPTION_OVERFLOW
                        else (table, address - S.MESSAGE_TABLE))
            end = at
            while data[end:end + 2] != b"\x00\x00":
                end += 3 if data[end:end + 2] == b"\xff\xff" else 2
            return data[at:end]
    raise KeyError(string_id)


def _patched(table: bytes, overflow: bytes, descriptions: "dict[int, int]") -> "tuple[bytes, bytes]":
    """`table` and `overflow` with `description_patch_words` applied, as their vanilla pins."""
    with mock.patch.multiple(S, MESSAGE_TABLE_SHA1=hashlib.sha1(table).hexdigest(),
                             DESCRIPTION_OVERFLOW_SHA1=hashlib.sha1(overflow).hexdigest()):
        words = S.description_patch_words(table, overflow, descriptions)
    out = {S.MESSAGE_TABLE: bytearray(table), S.DESCRIPTION_OVERFLOW: bytearray(overflow)}
    for address, old, new in words:
        base = S.DESCRIPTION_OVERFLOW if address >= S.DESCRIPTION_OVERFLOW else S.MESSAGE_TABLE
        assert struct.unpack_from(">I", out[base], address - base)[0] == old, hex(address)
        struct.pack_into(">I", out[base], address - base, new)
    return bytes(out[S.MESSAGE_TABLE]), bytes(out[S.DESCRIPTION_OVERFLOW])


class TestTheDescriptions(unittest.TestCase):
    STRINGS = {
        1: _text("SAVE"),
        10501: _text("Pounds the target with", "forelegs or tail."),
        10502: _text("A chopping attack with a", "high critical-hit ratio."),
        10503: _text("Repeatedly slaps the", "target 2 to 5 times."),
        10553: _text("A powerful fire attack that", "may inflict a burn."),
        20000: _text("After the moves"),
    }

    def test_pound_reads_physical_then_its_own_text(self):
        table, overflow = _patched(_message_table(self.STRINGS), bytes(OVERFLOW_SIZE), {10501: 1, 10553: 2})
        self.assertEqual(_text("PHYSICAL", "Pounds the target with", "forelegs or tail."),
                         _resolve(table, overflow, 10501))
        self.assertEqual(_text("SPECIAL", "A powerful fire attack that", "may inflict a burn."),
                         _resolve(table, overflow, 10553))

    def test_every_other_string_still_reads_the_same(self):
        table, overflow = _patched(_message_table(self.STRINGS), bytes(OVERFLOW_SIZE), {10501: 1, 10553: 2})
        for string_id in (1, 10502, 10503, 20000):
            self.assertEqual(self.STRINGS[string_id], _resolve(table, overflow, string_id), string_id)

    def test_what_outgrows_the_table_goes_to_the_overflow(self):
        """No slack: the prefixes push the run's last strings into the overflow."""
        vanilla = _message_table(self.STRINGS)
        table, overflow = _patched(vanilla, bytes(OVERFLOW_SIZE), {10501: 1, 10553: 2})
        self.assertNotEqual(bytes(OVERFLOW_SIZE), overflow)
        self.assertEqual(vanilla[-len(_text("After the moves")) - 2:], table[-len(_text("After the moves")) - 2:])

    def test_what_follows_a_terminator_travels_with_its_string(self):
        """An entry runs to the next one's offset; vanilla has orphaned text there, so none of it is dropped."""
        table, overflow = _patched(_message_table(self.STRINGS, slack=0x40), bytes(OVERFLOW_SIZE), {20000: 1})
        self.assertEqual(_text("PHYSICAL", "After the moves"), _resolve(table, overflow, 20000))
        self.assertIn(_text("PHYSICAL", "After the moves") + bytes(2 + 0x40), overflow)

    def test_too_little_room_refuses(self):
        with self.assertRaises(ValueError):
            _patched(_message_table(self.STRINGS), bytes(4), {10501: 1, 10502: 1, 10503: 1, 10553: 2})

    def test_an_unknown_description_refuses(self):
        with self.assertRaises(ValueError):
            _patched(_message_table(self.STRINGS), bytes(OVERFLOW_SIZE), {10999: 1})

    def test_a_non_vanilla_table_or_overflow_refuses(self):
        table = _message_table(self.STRINGS)
        with self.assertRaises(ValueError):
            S.description_patch_words(table, bytes(OVERFLOW_SIZE), {10501: 1})

    def test_the_overflow_lies_past_the_table(self):
        """Clear of the strings it repoints, and `_resolve` tells the two apart by address."""
        self.assertLessEqual(S.MESSAGE_TABLE + S.MESSAGE_TABLE_SIZE, S.DESCRIPTION_OVERFLOW)


def _bl_target(address, word):
    return address + ((word & 0x03FFFFFC) ^ 0x02000000) - 0x02000000


SHADOW_CHECKS = {0x8013E820, 0x802157E4, 0x802177D4, 0x80229608, 0x8022A074}
AI_MOVE_CHECKS = {0x802E2D60, 0x802E2E7C}


class TestTheDolWord(unittest.TestCase):
    def test_exactly_the_shadow_and_ai_checks_are_patched(self):
        addresses = [a for a, _o, _n in S.dol_patch_words()]
        self.assertEqual(len(set(addresses)), len(addresses))
        self.assertEqual(SHADOW_CHECKS | AI_MOVE_CHECKS, set(addresses))

    def test_every_shadow_check_call_becomes_li_r3_1(self):
        for address, old, new in S.dol_patch_words():
            if address not in SHADOW_CHECKS:
                continue
            self.assertEqual(0x48000001, old & 0xFC000003, hex(address))                # bl
            self.assertEqual(0x8013D03C, _bl_target(address, old), hex(address))        # wazaCheckDarkWaza
            self.assertEqual(0x38600001, new, hex(address))                             # li r3,1

    def test_every_ai_move_check_asks_the_category_byte(self):
        """The AI's `bl zokuseiBiosGetWazaKind` (by type) becomes `bl waza_GetZokuseiKindData` (by +0x13)."""
        for address, old, new in S.dol_patch_words():
            if address not in AI_MOVE_CHECKS:
                continue
            self.assertEqual(0x48000001, old & 0xFC000003, hex(address))                # bl
            self.assertEqual(0x48000001, new & 0xFC000003, hex(address))                # bl
            self.assertEqual(0x80117AC4, _bl_target(address, old), hex(address))        # zokuseiBiosGetWazaKind
            self.assertEqual(0x8013E7F0, _bl_target(address, new), hex(address))        # waza_GetZokuseiKindData

    def test_every_shadow_move_already_has_a_category(self):
        """Every move now takes the +0x13 path; the Shadow moves, which always did, must keep theirs."""
        for d in DEFINITIONS[356:374]:
            self.assertNotIn("Gen9Category", d, d["Name"])


class TestTheClientStillFindsTheTable(unittest.TestCase):
    def test_gen9_moves_leaves_every_fingerprint_move_alone(self):
        """The client proves the live move table with `MOVE_TABLE_FINGERPRINT`; a Gen 9 seed must still pass."""
        for index, (pp, power) in rf.MOVE_TABLE_FINGERPRINT.items():
            d = DEFINITIONS[index]
            self.assertNotIn("Gen9Pp", d, d["Name"])
            self.assertNotIn("Gen9Power", d, d["Name"])

    def test_the_offsets_agree_with_rel_format(self):
        self.assertEqual(rf.MOVE_ENTRY_SIZE, S.MOVE_ENTRY_SIZE)
        self.assertEqual((rf.MOVE_PP_OFFSET, rf.MOVE_TYPE_OFFSET, rf.MOVE_ACCURACY_OFFSET),
                         (S.PP_OFFSET, S.TYPE_OFFSET, S.ACCURACY_OFFSET))
        self.assertEqual(rf.MOVE_BASE_POWER_OFFSET, S.POWER_OFFSET + 1)   # the s16's low byte


if __name__ == "__main__":
    unittest.main()
