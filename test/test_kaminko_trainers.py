"""Kaminko Missable Trainers: the rebuilt floor files, and the client's slot filler."""
from __future__ import annotations

import struct
import unittest
from unittest import mock

from .. import ram_client as rc
from ..game_data import kaminko_trainers as kt
from ..game_data import missable_trainers, trainer_roster
from .local_dumps import DUMPS


def _room_files():
    path = DUMPS / "maps" / "S3_out.fsys"
    if not path.is_file():
        return None
    from ..tools import iso_patcher
    from ..tools.xd_deck_format import lzss_decode

    container = path.read_bytes()
    return {e["file_format"]: lzss_decode(container[e["data_off"]:])[:e["decomp_size"]]
            for e in iso_patcher.parse_fsys_all(container) if e["file_format"] in (10, 14, 28)}


class TestTheTable(unittest.TestCase):
    def test_every_trainer_is_missable_and_exists(self) -> None:
        for trainer, _battle, _src in kt.KAMINKO_TRAINERS:
            self.assertIn(trainer, missable_trainers.MISSABLE_TRAINER_INDICES)
            self.assertIn(trainer, trainer_roster.TRAINERS_BY_INDEX)

    def test_the_always_battle_npcs_and_npc_only_fights_are_left_out(self) -> None:
        listed = {t for t, _b, _s in kt.KAMINKO_TRAINERS}
        for trainer in (8, 16, 23, 9, 148):
            self.assertNotIn(trainer, listed)

    def test_slots_are_spread_out(self) -> None:
        for i, (x1, _y1, z1, _a1) in enumerate(kt.SLOT_POSITIONS):
            for x2, _y2, z2, _a2 in kt.SLOT_POSITIONS[i + 1:]:
                self.assertGreaterEqual(((x1 - x2) ** 2 + (z1 - z2) ** 2) ** 0.5, 15)


class TestOnTheRealFiles(unittest.TestCase):
    def setUp(self) -> None:
        self.files = _room_files()
        if self.files is None:
            self.skipTest("the map dumps are not on this machine")

    def test_an_older_build_s_miror_b_is_moved_in(self) -> None:
        for with_trainers in (True, False):
            rel = bytearray(kt.build_floor_rel(self.files[28], with_trainers))
            word = struct.pack(">I", 0x01000000 + kt.MIROR_FUNCTION_INDEX)
            record = rel.find(word) - 0x14
            struct.pack_into(">3f", rel, record + 0x18, -21.0, -0.4, 0.0)          # where he used to stand
            moved = kt.reposition_slots(bytes(rel), with_trainers)
            x, _y, z, _a = kt.MIROR_POSITION
            self.assertEqual((x, z), struct.unpack_from(">f4xf", moved, record + 0x18))
            self.assertLess(z, -20)                                                # in from the entrance
            self.assertGreater(z, min(sz for _sx, _sy, sz, _sa in kt.SLOT_POSITIONS) + 100)   # short of the ring

    def test_the_floor_has_sixteen_characters(self) -> None:
        rel = kt.build_floor_rel(self.files[28])
        _module, relocs = kt._rel_self_relocations(rel)
        data_off, data_size = kt._rel_sections(rel)[3]
        targets = [r for r in relocs if r[4] == 3 and r[5] == 0x224]
        self.assertEqual(3, len(targets))
        self.assertEqual(17, struct.unpack_from(">I", rel, data_off + 0x1FC)[0])
        for k, (x, _y, z, _a) in enumerate(kt.SLOT_POSITIONS):
            record = data_off + 0x224 + (4 + k) * kt.CHARACTER_RECORD_SIZE
            self.assertEqual(kt.SLOT_HIDDEN_FLAGS, rel[record])            # hidden until the script shows it
            self.assertEqual(0x01000000 + kt.VANILLA_FUNCTION_COUNT + k, struct.unpack_from(">I", rel, record + 0x14)[0])
            self.assertEqual((x, z), struct.unpack_from(">f4xf", rel, record + 0x18))
        # the vanilla four are copied unchanged
        self.assertEqual(self.files[28][0x224:0x224 + 4 * 0x24], rel[data_off + 0x224:data_off + 0x224 + 4 * 0x24])

    def test_the_script_keeps_its_own_code_and_adds_twelve_functions(self) -> None:
        old, new = self.files[14], kt.build_floor_script(self.files[14])
        o, n = kt.split_script(old), kt.split_script(new)
        used = struct.unpack_from(">I", o[b"CODE"], 0x14)[0]
        hook = 0x20 + 4 * kt.HERO_MAIN_LOOP_TOP
        self.assertEqual(o[b"CODE"][0x20:hook], n[b"CODE"][0x20:hook])
        self.assertEqual(o[b"CODE"][hook + 4:0x20 + 4 * used], n[b"CODE"][hook + 4:0x20 + 4 * used])
        show_at = struct.unpack_from(">I", n[b"HEAD"], 0x20 + 4 * kt.SHOW_FUNCTION_INDEX)[0]
        self.assertEqual(0x07000000 | show_at, struct.unpack_from(">I", n[b"CODE"], hook)[0])
        self.assertEqual(34, struct.unpack_from(">I", n[b"FTBL"], 0x10)[0])
        self.assertIn(kt.SHOW_FUNCTION_NAME, n[b"FTBL"])
        # every added global is an integer entry exactly like the floor's own first one
        for i in range(7, 7 + kt.GVAR_ADDED):
            self.assertEqual(o[b"GVAR"][0x20:0x28], n[b"GVAR"][0x20 + 8 * i:0x28 + 8 * i], i)
        self.assertEqual(7 + kt.GVAR_ADDED, struct.unpack_from(">I", n[b"GVAR"], 0x10)[0])
        self.assertEqual(21, struct.unpack_from(">I", n[b"GIRI"], 0x10)[0])
        for tag in (b"STRG", b"VECT", b"ARRY"):
            self.assertEqual(o[tag], n[tag])
        self.assertIn(kt.SLOT_FUNCTION_PREFIX + b"11", new)

    def test_messages_keep_the_old_lines(self) -> None:
        new = kt.build_messages(self.files[10], kt.floor_lines({}, True))
        old_entries, new_entries = kt.message_entries(self.files[10]), kt.message_entries(new)
        for sid, text in old_entries.items():
            self.assertEqual(text, new_entries[sid])
        self.assertEqual(len(old_entries) + 3 * len(kt.KAMINKO_TRAINERS) + 4, len(new_entries))
        self.assertEqual(kt.battle_line("RESIX", None), new_entries[kt.MESSAGE_BASE])

    def test_a_trainers_own_line_names_them(self) -> None:
        own = b"\xff\xff\x59" + ": Hi!".encode("utf-16-be") + b"\xff\xff\x03\xff\xff\x59" + ": Go!".encode("utf-16-be")
        line = kt.trainer_lines({"M1_out": {36159: own}})[kt.MESSAGE_BASE]
        self.assertEqual("RESIX: Hi!".encode("utf-16-be") + b"\xff\xff\x03" + "RESIX: Go!".encode("utf-16-be"), line)


def _rows(text: bytes) -> "list[str]":
    """A message's text, split at its control codes (two 0xFF bytes and a code byte)."""
    rows, row, i = [], "", 0
    while i + 1 < len(text):
        unit = struct.unpack_from(">H", text, i)[0]
        if unit == 0xFFFF:
            rows.append(row)
            row, i = "", i + 3
            continue
        row, i = row + chr(unit), i + 2
    return rows + [row]


class TestOnlyJumpIfFalse(unittest.TestCase):
    def test_no_generated_function_uses_jump_if_true(self) -> None:
        """The game's own scripts never branch with 0x0A, so nothing generated here may either."""
        for words in (kt.slot_function_words(3, 100), kt.miror_function_words(100), kt.show_function_words(100)):
            self.assertFalse([w for w in words if w >> 24 == 0x0A and w & 0x00FF0000 == 0])


class TestTheLines(unittest.TestCase):
    def test_every_trainer_says_who_and_where_then_asks(self) -> None:
        lines = kt.trainer_lines({})
        for i, (trainer, _b, _s) in enumerate(kt.KAMINKO_TRAINERS):
            name, home = kt.TRAINER_INTRODUCTIONS[trainer]
            question = lines[kt.MESSAGE_BASE + kt.QUESTION_OFFSET + i]
            self.assertEqual([f"{name}: Hey, you there!", f"I'm {name}, from {home}!", "How about a battle?\x00"], _rows(question))
            self.assertTrue(lines[kt.MESSAGE_BASE + kt.DECLINE_OFFSET + i].endswith(b"\xff\xff\x02\x00\x00"))
            for text in (lines[kt.MESSAGE_BASE + k + i] for k in (0, kt.QUESTION_OFFSET, kt.DECLINE_OFFSET)):
                self.assertNotIn(b"\xff\xff\x59", text)
                for row in _rows(text):
                    self.assertLessEqual(len(row), 44)

    def test_the_names_match_the_roster(self) -> None:
        for trainer, (name, _home) in kt.TRAINER_INTRODUCTIONS.items():
            self.assertEqual(trainer_roster.TRAINERS_BY_INDEX[trainer]["name"], name)

    def test_the_slot_asks_before_it_battles(self) -> None:
        start = 1000
        words = kt.slot_function_words(3, start)
        calls = [i for i, w in enumerate(words) if w == 0x09230049]
        self.assertEqual(3, len(calls))
        self.assertEqual(8, words[calls[0] - 2])          # yes/no
        self.assertEqual(6, words[calls[1] - 2])          # battle
        self.assertEqual(1, words[calls[2] - 2])          # "no"
        for i, w in enumerate(words):
            if w >> 24 in (0x0A, 0x0B, 0x0C):
                self.assertTrue(start <= (w & 0xFFFFFF) < start + len(words))
        self.assertEqual([0x02010000, 0, kt.OP_NOT_EQUAL], words[1:4])      # unless its battle is set -> end
        self.assertEqual((0x0E000000, 0x08000000), tuple(words[(words[4] & 0xFFFFFF) - start:][:2]))
        decline = [w for w in words if w >> 24 == 0x0B][1] & 0xFFFFFF
        self.assertEqual(0x03000000 | (kt.GVAR_MESSAGE_BASE + 3), words[decline - start])
        self.assertEqual(kt.DECLINE_OFFSET, words[decline - start + 2])
        self.assertEqual((0x0E000000, 0x08000000), tuple(words[-2:]))


class TestMirorB(unittest.TestCase):
    def setUp(self) -> None:
        self.files = _room_files()
        if self.files is None:
            self.skipTest("the map dumps are not on this machine")

    def test_he_stands_there_without_the_trainers(self) -> None:
        rel = kt.build_floor_rel(self.files[28], with_trainers=False)
        data_off, _size = kt._rel_sections(rel)[3]
        self.assertEqual(5, struct.unpack_from(">I", rel, data_off + 0x1FC)[0])
        record = data_off + 0x224 + 4 * kt.CHARACTER_RECORD_SIZE
        self.assertEqual((kt.MIROR_MODEL, kt.MIROR_NAME_ID), struct.unpack_from(">HH", rel, record + 6))
        self.assertEqual(0x01000000 + kt.MIROR_FUNCTION_INDEX, struct.unpack_from(">I", rel, record + 0x14)[0])
        script = kt.split_script(kt.build_floor_script(self.files[14], with_trainers=False))
        self.assertEqual(9, struct.unpack_from(">I", script[b"GIRI"], 0x10)[0])
        self.assertEqual(34, struct.unpack_from(">I", script[b"FTBL"], 0x10)[0])
        code, vanilla = script[b"CODE"], kt.split_script(self.files[14])[b"CODE"]
        self.assertEqual(struct.unpack_from(">I", vanilla, 0x20 + 4 * kt.HERO_MAIN_LOOP_TOP),
                         struct.unpack_from(">I", code, 0x20 + 4 * kt.HERO_MAIN_LOOP_TOP))   # no hook, no slots
        self.assertIn(kt.MIROR_FUNCTION_NAME, script[b"FTBL"])
        lines = kt.message_entries(kt.build_messages(self.files[10], kt.floor_lines({}, False)))
        self.assertIn(kt.MIROR_MESSAGE_QUESTION, lines)
        self.assertNotIn(kt.MESSAGE_BASE, lines)

    def test_his_function_waits_asks_and_starts_the_poke_spot_battle(self) -> None:
        start = 500
        words = kt.miror_function_words(start)
        self.assertEqual([0x03000000 | kt.GVAR_MIROR, 0x02010000, 0, kt.OP_NOT_EQUAL], words[:4])
        self.assertEqual(0x0B, words[4] >> 24)
        at = words.index(kt.MIROR_BATTLE)
        self.assertEqual([0x02010000, kt.MIROR_MESSAGE_BATTLE, 0x02010000, 6, 0x11010001, 0x09230049, 0x06040000],
                         words[at + 1:at + 8])
        for w in words:
            if w >> 24 in (0x0A, 0x0B, 0x0C) and w & 0xFFFF0000 in (0x0A000000, 0x0B000000, 0x0C000000):
                self.assertTrue(start <= (w & 0xFFFFFF) < start + len(words))
        self.assertEqual((0x0E000000, 0x08000000), tuple(words[-2:]))
        empty = words[4] & 0xFFFFFF
        self.assertIn(kt.MIROR_MESSAGE_EMPTY, words[empty - start:])

    def test_the_show_function_shows_a_filled_slot_and_hides_an_empty_one(self) -> None:
        start = 900
        self.assertEqual(2 * kt.SLOT_COUNT, sum(1 for w in kt.show_function_words(start, False) if w >> 16 == 0x0303))
        words = kt.show_function_words(start)
        for k in range(kt.SLOT_COUNT):
            obj = 0x03030000 | (kt.SLOT_OBJECT_BASE + k)
            at = [i for i, w in enumerate(words) if w == obj]
            self.assertEqual(3, len(at), k)
            self.assertEqual([0x02010000, 0], words[at[0] - 2:at[0]])          # hide
            self.assertEqual([0x03000000 | (kt.GVAR_MODEL_BASE + k), obj, kt.CHARACTER_SET_MODEL, 0x06020000],
                             words[at[1] - 1:at[1] + 3])                         # its model, just before it shows
            self.assertEqual([0x02010000, 1], words[at[2] - 2:at[2]])          # show
            self.assertEqual([0x09230010, 0x06020000], words[at[0] + 1:at[0] + 3])
        for w in words:
            if w >> 24 in (0x0A, 0x0B, 0x0C):
                self.assertTrue(start <= (w & 0xFFFFFF) <= start + len(words))
        self.assertEqual((0x0E000000, 0x08000000), tuple(words[-2:]))

    def test_the_slots_are_spread_out_and_off_the_middle(self) -> None:
        for x, _y, z, angle in kt.SLOT_POSITIONS:
            self.assertGreaterEqual(abs(x - (-10.0)), 25)                       # the walk up the middle stays clear
            cx, cz = kt.FOUNTAIN_CENTRE
            self.assertGreaterEqual(((x - cx) ** 2 + (z - cz) ** 2) ** 0.5, kt.FOUNTAIN_WALL_RADIUS + 15)   # clear of it
            self.assertTrue(0 <= angle < 360)
        self.assertGreater(len({a for *_p, a in kt.SLOT_POSITIONS}), 6)

    def test_his_lines_fit(self) -> None:
        for text in kt.miror_lines().values():
            self.assertNotIn(b"\xff\xff\x59", text)

    def test_his_model_is_appended_to_the_archive(self) -> None:
        from ..tools import iso_patcher
        from ..tools.xd_deck_format import lzss_decode

        source = DUMPS / "maps" / "S1_out.fsys"
        if not source.is_file():
            self.skipTest("the Outskirt Stand dump is not on this machine")
        s1 = source.read_bytes()
        s3 = (DUMPS / "maps" / "S3_out.fsys").read_bytes()
        model = [e for e in iso_patcher.parse_fsys_all(s1) if e["name"] == kt.MIROR_MODEL_SOURCE[1]][0]
        raw = s1[model["data_off"]:model["data_off"] + 0x10 + model["comp_size"]]
        record = s1[model["record_off"]:model["record_off"] + iso_patcher.FSYS_RECORD_SIZE]
        out = iso_patcher._append_fsys_entry(s3, record, model["name"], raw)
        before, after = iso_patcher.parse_fsys_all(s3), iso_patcher.parse_fsys_all(out)
        self.assertEqual(len(before) + 1, len(after))
        for old, new in zip(before, after):
            self.assertEqual((old["name"], old["file_format"]), (new["name"], new["file_format"]))
            self.assertEqual(lzss_decode(s3[old["data_off"]:])[:old["decomp_size"]],
                             lzss_decode(out[new["data_off"]:])[:new["decomp_size"]])
        added = after[-1]
        self.assertEqual((kt.MIROR_MODEL_SOURCE[1], 4), (added["name"], added["file_format"]))
        self.assertEqual(lzss_decode(raw)[:model["decomp_size"]], lzss_decode(out[added["data_off"]:])[:added["decomp_size"]])
        self.assertEqual(out[0x0:0x2] + record[0:2], s3[0:2] + bytes.fromhex("15ee"))
        self.assertEqual(b"FSYS", out[-4:])
        self.assertEqual(len(out), struct.unpack_from(">I", out, 0x20)[0])
        self.assertEqual(0, len(out) % 32)

    def test_the_model_table_says_105_is_his(self) -> None:
        path = DUMPS / "a263_commonrel.bin"
        if not path.is_file():
            self.skipTest("the common_rel dump is not on this machine")
        table = path.read_bytes()
        base = 155504           # the character model table in that dump: 0x34-byte records, resource id at +4
        self.assertEqual(0x15EE0400, struct.unpack_from(">I", table, base + kt.MIROR_MODEL * 0x34 + 4)[0])
        self.assertEqual(0x17AA0400, struct.unpack_from(">I", table, base + 154 * 0x34 + 4)[0])   # Chobin's


class TestTheClient(unittest.TestCase):
    def _setup(self):
        files = _room_files()
        if files is None:
            self.skipTest("the map dumps are not on this machine")
        blob = bytearray(kt.build_floor_script(files[14]))
        base = 0x80900000
        mem = {"blob": blob}

        def read(address, length):
            return bytes(blob[address - base:address - base + length])

        def write(address, data):
            blob[address - base:address - base + len(data)] = data
        slots = rc.KaminkoTrainerSlots(blob=base)
        offsets = kt.section_offsets(bytes(blob))
        return slots, read, write, blob, base, offsets, mem

    def test_a_fresh_load_is_filled_and_a_win_is_reported(self) -> None:
        slots, read, write, blob, base, offsets, _m = self._setup()
        with mock.patch.object(rc, "read_bytes", read), mock.patch.object(rc, "write_bytes", write):
            self.assertEqual([], slots.poll(True, lambda t: t == 39))
            first = slots.assigned[0]
            self.assertEqual(40, first)                    # Resix #2 was beaten, so Blusix #2 leads
            battle_at = offsets[b"GVAR"] + 0x20 + 8 * kt.GVAR_BATTLE_BASE + 4
            self.assertEqual(321, struct.unpack_from(">I", blob, battle_at)[0])
            self.assertEqual([], slots.poll(True, lambda t: False))
            struct.pack_into(">I", blob, battle_at, 0)    # the script clears it after the win
            self.assertEqual([40], slots.poll(True, lambda t: False))
            self.assertEqual([], slots.poll(True, lambda t: False))

    def test_miror_b_is_told_whether_his_queue_holds_a_shadow(self) -> None:
        slots, read, write, blob, base, offsets, _m = self._setup()
        at = offsets[b"GVAR"] + 0x20 + 8 * kt.GVAR_MIROR + 4
        with mock.patch.object(rc, "read_bytes", read), mock.patch.object(rc, "write_bytes", write):
            slots.set_miror(True, True)
            self.assertEqual(1, struct.unpack_from(">I", blob, at)[0])
            slots.set_miror(True, False)
            self.assertEqual(0, struct.unpack_from(">I", blob, at)[0])
            slots.set_miror(False, True)
            self.assertEqual(0, struct.unpack_from(">I", blob, at)[0])

    def test_only_missed_trainers_fill_the_slots(self) -> None:
        slots, read, write, blob, base, offsets, _m = self._setup()
        missed = {51, 53}
        with mock.patch.object(rc, "read_bytes", read), mock.patch.object(rc, "write_bytes", write):
            slots.poll(True, lambda t: t not in missed)
        self.assertEqual([51, 53] + [None] * (kt.SLOT_COUNT - 2), slots.assigned)

    def test_a_win_over_him_there_sends_nothing(self) -> None:
        self.assertIn("MIROR B.", rc.watched_fight_surnames(kt.FLOOR_ROOM_ID))
        self.assertNotIn("MIROR B.", rc.watched_fight_surnames(1))

    def test_a_reload_is_not_twelve_wins(self) -> None:
        slots, read, write, blob, base, offsets, _m = self._setup()
        with mock.patch.object(rc, "read_bytes", read), mock.patch.object(rc, "write_bytes", write):
            slots.poll(True, lambda t: False)
            gv = offsets[b"GVAR"] + 0x20
            blob[gv:gv + 8 * (7 + kt.GVAR_ADDED)] = bytes(blob[gv:gv + 8 * 7]) + b"\x00\x00\x00\x01\x00\x00\x00\x00" * kt.GVAR_ADDED
            self.assertEqual([], slots.poll(True, lambda t: False))
            self.assertEqual(kt.SLOT_COUNT, sum(1 for t in slots.assigned if t is not None))


if __name__ == "__main__":
    unittest.main()


class TestMissed(unittest.TestCase):
    def _ctx(self, high_water: int, travel: bool = False, area: "dict | None" = None):
        from types import SimpleNamespace
        ctx = SimpleNamespace(missable_autosender=rc.MissableAutoSender(),
                              story_progress=SimpleNamespace(high_water=high_water))
        return ctx

    def test_a_trainer_is_missed_once_its_cap_is_passed(self) -> None:
        from .. import Client
        with mock.patch.object(Client, "_missable_area_progress", lambda ctx: None):
            self.assertFalse(Client._kaminko_trainer_missed(self._ctx(0x2E), 51))     # Digor, Cipher Lab: 0x2F
            self.assertTrue(Client._kaminko_trainer_missed(self._ctx(0x2F), 51))

    def test_every_trainer_has_a_model(self) -> None:
        self.assertEqual({t for t, _b, _s in kt.KAMINKO_TRAINERS}, set(kt.TRAINER_MODELS))
        for model in kt.TRAINER_MODELS.values():
            self.assertEqual(0x0400, model & 0xFFFF)                            # a model file's resource id

    def test_finol_and_eroll_never_wait_there(self) -> None:
        self.assertFalse({64, 105} & {t for t, _b, _s in kt.KAMINKO_TRAINERS})

    def test_the_sixes_bring_their_phenac_team(self) -> None:
        battles = {t: b for t, b, _s in kt.KAMINKO_TRAINERS}
        self.assertEqual([320, 321, 322, 323, 324, 325], [battles[t] for t in range(39, 45)])

    def test_with_location_shuffle_it_is_the_areas_own_progress(self) -> None:
        from .. import Client
        with mock.patch.object(Client, "_missable_area_progress", lambda ctx: (lambda region: 0x10)):
            self.assertFalse(Client._kaminko_trainer_missed(self._ctx(0x7F), 51))
        with mock.patch.object(Client, "_missable_area_progress", lambda ctx: (lambda region: 0x7F)):
            self.assertTrue(Client._kaminko_trainer_missed(self._ctx(-1), 51))

    def test_every_kaminko_trainer_has_a_cap(self) -> None:
        from .. import Client
        with mock.patch.object(Client, "_missable_area_progress", lambda ctx: None):
            for trainer, _b, _s in kt.KAMINKO_TRAINERS:
                self.assertTrue(Client._kaminko_trainer_missed(self._ctx(0xFF), trainer), trainer)
