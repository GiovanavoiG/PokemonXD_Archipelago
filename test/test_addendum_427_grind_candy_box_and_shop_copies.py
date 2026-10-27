"""ADDENDUM 427 (2026-10-06) -- Reduce Citadark Grind, the Candy Box, Realgam's shelf text, legal Shadow moves.

The "reduce_citadark_grind" option makes one of the Gateon expansion items a guaranteed rebuyable Rare Candy that
costs only 1. The Realgam shop was broken and very slow to write. A NEW ITEM, the Candy Box, puts a Pokemon at
level 100, OR 99 if it still has an evolution ahead, so it can still evolve from a level-up. Shadows get legal
movesets. The TM/move functionality is separate from the enhanced difficulty options -- on by default, not
attached to any option.
"""
from __future__ import annotations

import json
import os
import hashlib
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from . import PokemonXDTestBase
from .. import locations, options
from .. import ram_client
from ..game_data import candy_box as CB
from ..game_data import item_descriptions as D
from ..game_data import shop_stock as S
from ..game_data import shops
from ..tools import iso_patcher as ip
from ..tools import xd_rel_format as rel_format
from .test_addendum_311_pit_stop_and_filler_categories import FakeRel, _real_layout_rel

REAL_DOL = Path("/mnt/user-data/uploads/PokemonXD-working/main_dol.bin")
RAM_DUMP = Path("/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/battle1.bin")
SHOP_DUMP = Path("/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/dump_gateon_shopmenu_20260915.bin")
SHOP_DUMP_BASE = 0x809CECC0


def _dol_word_reader(data: bytes):
    sections = []
    for i in range(18):
        off, addr, size = (struct.unpack_from(">I", data, base + i * 4)[0] for base in (0, 0x48, 0x90))
        if size:
            sections.append((addr, size, off))

    def word(address):
        for addr, size, off in sections:
            if addr <= address < addr + size:
                return struct.unpack_from(">I", data, off + address - addr)[0]
        return None
    return word, sections


# --- the option -------------------------------------------------------------------------------------------------

class TestTheOption(unittest.TestCase):
    def test_it_exists_and_the_moveset_option_does_not(self):
        fields = options.PokemonXDOptions.__dataclass_fields__
        self.assertIn("reduce_citadark_grind", fields)
        self.assertNotIn("shuffle_trainer_movesets", fields)
        self.assertEqual(0, options.ReduceCitadarkGrind.default)

    def test_the_template_carries_it(self):
        text = (Path(__file__).resolve().parent.parent / "data" / "reference_template.yaml").read_text()
        self.assertIn("reduce_citadark_grind:", text)
        self.assertNotIn("shuffle_trainer_movesets", text)

    def test_the_two_lines_are_restock_lines(self):
        names = locations.grind_shop_location_names()
        self.assertEqual({"Gateon Port Shop AP Item 13", "Gateon Port Shop AP Item 14"}, set(names))   # lines 14, 15
        self.assertTrue(names <= locations.FILLER_ONLY_SHOP_LOCATIONS)


class TestGrindOn(PokemonXDTestBase):
    options = {"randomize_shops": True, "reduce_citadark_grind": True}

    def test_the_two_checks_are_gone_and_the_seed_says_so(self):
        world = self.multiworld.worlds[self.player]
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertNotIn("Gateon Port Shop AP Item 13", names)   # line 14, the Candy Box
        self.assertNotIn("Gateon Port Shop AP Item 14", names)   # line 15, the Rare Candy
        self.assertIn("Gateon Port Shop AP Item 12", names)
        world.pre_output()
        with tempfile.TemporaryDirectory() as tmp:
            world.generate_output(tmp)
            with zipfile.ZipFile(next(Path(tmp).glob("*.appxd"))) as zf:
                seed = json.loads(zf.read("seed.json"))
        self.assertTrue(seed["reduce_citadark_grind"])
        self.assertEqual(1, world.fill_slot_data()["reduce_citadark_grind"])


class TestGrindOff(PokemonXDTestBase):
    options = {"randomize_shops": True}

    def test_the_checks_stay(self):
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertIn("Gateon Port Shop AP Item 13", names)
        self.assertIn("Gateon Port Shop AP Item 14", names)
        self.assertNotIn("Gateon Port Shop AP Item 15", names)   # numbered without the Ability Swap's line


# --- the shelf --------------------------------------------------------------------------------------------------

class TestTheShelf(unittest.TestCase):
    def test_the_lines_are_where_the_table_says(self):
        self.assertEqual((140, 19), S.line_pool_index(15, 15))     # Full Restore
        self.assertEqual((139, 20), S.line_pool_index(15, 14))     # Max Potion
        for line, (vanilla, _item) in CB.GATEON_GRIND_LINES.items():
            self.assertEqual(vanilla, S.line_pool_index(CB.GATEON_FINAL_MART, line)[1])
            # Only the last tier carries them, so no earlier Gateon shelf changes.
            for mart in S.SHOP_MART_TIERS[CB.GATEON_SHOP]["marts"][:-1]:
                self.assertNotIn(line, S.MART_LINE_NUMBERS[mart])

    def test_the_writer_puts_both_on_the_shelf_and_nothing_else_moves(self):
        rel, pointers, values = _real_layout_rel()
        before = bytearray(rel.data)
        out = bytearray(rel.data)
        plan = {S.line_pool_index(15, line)[0]: (vanilla, item) for line, (vanilla, item) in CB.GATEON_GRIND_LINES.items()}
        self.assertEqual(2, rel_format.apply_mart_pool_items(out, rel, 15, plan))
        patched = FakeRel(bytes(out), pointers, values)
        shelf = [s["item_id"] for s in rel_format.read_all_mart_slots(patched) if s["mart_index"] == 15]
        self.assertIn(CB.RARE_CANDY_ITEM_ID, shelf)
        self.assertIn(CB.CANDY_BOX_ITEM_ID, shelf)
        changed = rel_format.byte_diff_offsets(bytes(before), bytes(out))
        self.assertLessEqual(len(changed), 4, "two u16 writes and nothing else")

    def test_a_slot_that_is_not_the_marts_or_not_vanilla_is_refused(self):
        rel, _p, _v = _real_layout_rel()
        out = bytearray(rel.data)
        with self.assertRaises(ValueError):
            rel_format.apply_mart_pool_items(out, rel, 15, {0: (21, 68)})        # mart 0's slot
        with self.assertRaises(ValueError):
            rel_format.apply_mart_pool_items(out, rel, 15, {140: (20, 68)})      # wrong vanilla item
        self.assertEqual(bytes(out), rel.data)


class TestTheItemRows(unittest.TestCase):
    def _rel(self):
        data = bytearray(0x2000)
        base = 0x100
        for item_id, name_id in ((CB.RARE_CANDY_ITEM_ID, CB.RARE_CANDY_NAME_ID), (CB.CANDY_BOX_ITEM_ID, CB.CANDY_BOX_NAME_ID)):
            struct.pack_into(">I", data, base + item_id * 0x28 + 0x10, name_id)
        rel = FakeRel(bytes(data), {rel_format.ITEMS_TABLE_POINTER: base},
                      {rel_format.XD_NUMBER_OF_ITEMS_POINTER: 0x200})
        return rel, base

    def test_the_rows_take_their_edits(self):
        rel, base = self._rel()
        out = bytearray(rel.data)
        self.assertTrue(rel_format.apply_item_row_bytes(out, rel, 68, 5057, CB.rare_candy_row_edits()))
        self.assertTrue(rel_format.apply_item_row_bytes(out, rel, 50, 5050, CB.candy_box_row_edits()))
        self.assertEqual(1, struct.unpack_from(">H", out, base + 68 * 0x28 + 6)[0])
        row = out[base + 50 * 0x28:][:0x28]
        self.assertEqual(0x25, row[4])
        self.assertEqual(1, struct.unpack_from(">H", row, 6)[0])
        self.assertEqual(bytes((5, 3, 2)), bytes(row[0x24:0x27]))

    def test_a_row_whose_name_id_disagrees_is_left_alone(self):
        rel, _base = self._rel()
        out = bytearray(rel.data)
        self.assertFalse(rel_format.apply_item_row_bytes(out, rel, 50, 5057, CB.candy_box_row_edits()))
        self.assertEqual(bytes(out), rel.data)

    def test_the_relocated_pointers_and_ids_are_off_limits(self):
        rel, _base = self._rel()
        for offset in (0x10, 0x14, 0x1C, 0x20):
            with self.assertRaises(ValueError):
                rel_format.apply_item_row_bytes(bytearray(rel.data), rel, 50, 5050, {offset: b"\x00"})


# --- the Candy Box's main.dol patch ------------------------------------------------------------------------------

class TestTheLevelTable(unittest.TestCase):
    def test_shape(self):
        table = CB.target_level_table()
        self.assertEqual(CB.SPECIES_COUNT, len(table))
        self.assertEqual({99, 100}, set(table))
        # ADDENDUM 451: 99 for every species that can still evolve, 100 only for a final stage.
        self.assertEqual(len(CB.EVOLVES_FURTHER), table.count(99))
        self.assertEqual(99, table[4])      # Charmander
        self.assertEqual(99, table[5])      # Charmeleon -- one evolution left, so it stops at 99 too
        self.assertEqual(100, table[6])     # Charizard
        self.assertEqual(99, table[350])    # Azurill

    @unittest.skipUnless(RAM_DUMP.is_file(), "needs a RAM dump with XD's species table")
    def test_it_matches_the_games_own_evolution_data(self):
        data = RAM_DUMP.read_bytes()
        word = lambda a: struct.unpack_from(">I", data, a - 0x80000000)[0]
        count, base = word(word(0x804EFE20 - 22508)), word(0x804EFE20 - 22504)
        self.assertEqual(CB.SPECIES_COUNT, count)
        evolutions = {}
        for species in range(count):
            record = data[base - 0x80000000 + species * 0x124:][:0x124]
            evolutions[species] = [(m, t) for m, _p, _c, t in
                                   (struct.unpack_from(">BBHH", record, 0xA6 + 6 * k) for k in range(5)) if m]
        two = tuple(s for s in range(count)
                    if any(m in CB.LEVEL_EVOLUTION_METHODS
                           and any(m2 in CB.LEVEL_EVOLUTION_METHODS for m2, _t in evolutions.get(t, []))
                           for m, t in evolutions[s]))
        self.assertEqual(CB.TWO_STAGE_LEVEL_EVOLVERS, two)
        # ADDENDUM 451: the list the table now uses -- every species with any evolution entry.
        self.assertEqual(CB.EVOLVES_FURTHER, tuple(s for s in range(count) if evolutions[s]))


class TestTheCode(unittest.TestCase):
    def test_every_word_decodes_to_what_the_docstring_says(self):
        code = CB.cave_code()
        base = CB.CAVE_ADDRESS
        self.assertEqual(0x28030032, code[0])            # cmplwi r3,50
        self.assertEqual(0x3D608043, code[2])            # lis r11,0x8043
        self.assertEqual(0x816B82E8, code[3])            # lwz r11,-0x7D18(r11) -> 0x804282E8
        self.assertEqual(CB.CANT_USE_HANDLER_FIRST_WORD, code[7])
        self.assertEqual(0x38160001, code[9])            # addi r0,r22,1
        self.assertEqual(0x281A0032, code[10])           # cmplwi r26,50
        self.assertEqual(0x4C820020, code[11])           # bnelr
        self.assertEqual(0xA17F0000, code[12])           # lhz r11,0(r31)
        self.assertEqual(0x4C800020, code[14])           # bgelr
        self.assertEqual(0x7D6C58AE, code[17])           # lbzx r11,r12,r11
        self.assertEqual(0x4C810020, code[19])           # blelr
        self.assertEqual(0x7D605B78, code[20])           # mr r0,r11
        self.assertEqual(CB.BLR, code[21])

        def target(at, w):
            li = w & 0x03FFFFFC
            if li & 0x02000000:
                li -= 0x04000000
            return (at + li) & 0xFFFFFFFF
        self.assertEqual(CB.LVUP_HANDLER, target(base + 0x18, code[6]))
        self.assertEqual(CB.CANT_USE_HANDLER + 4, target(base + 0x20, code[8]))
        hi, lo = code[15] & 0xFFFF, code[16] & 0xFFFF
        lo = lo - 0x10000 if lo & 0x8000 else lo
        self.assertEqual(base + CB.TABLE_OFFSET, ((hi << 16) + lo) & 0xFFFFFFFF)
        words = {a: n for a, _e, n in CB.dol_patch_words()}
        self.assertEqual(base, target(CB.CANT_USE_HANDLER, words[CB.CANT_USE_HANDLER]))
        self.assertEqual(base + CB.LEVEL_HELPER_OFFSET, target(CB.LEVEL_STEP_ADDRESS, words[CB.LEVEL_STEP_ADDRESS]))
        self.assertEqual(1, words[CB.LEVEL_STEP_ADDRESS] & 1, "bl -- the helper returns")
        self.assertEqual(0, words[CB.CANT_USE_HANDLER] & 1, "b -- the dispatcher keeps the caller's lr")

    def test_the_cave_fits_the_routine_it_replaces(self):
        self.assertLessEqual(len(CB.cave_bytes()), 0x864)


@unittest.skipUnless(REAL_DOL.is_file(), "main_dol.bin not on this machine")
class TestAgainstTheRealDol(unittest.TestCase):
    def setUp(self):
        self.data = REAL_DOL.read_bytes()
        self.word, self.sections = _dol_word_reader(self.data)

    def test_every_expected_word_is_on_disc(self):
        for address, expected, _new in CB.dol_patch_words():
            if expected is not None:
                self.assertEqual(expected, self.word(address), hex(address))
        for start, length, digest in CB.vanilla_digests():
            span = b"".join(struct.pack(">I", self.word(start + i)) for i in range(0, length, 4))
            self.assertEqual(digest, hashlib.sha1(span).hexdigest(), hex(start))

    def test_nothing_reaches_the_cave_except_the_debug_menu(self):
        """No branch, no stored address and no lis/addi pair anywhere in main.dol names 0x80066D30."""
        cave = CB.CAVE_ADDRESS
        hi, lo = (cave + 0x8000) >> 16, cave & 0xFFFF
        for addr, size, _off in self.sections:
            for at in range(addr, addr + size, 4):
                w = self.word(at)
                self.assertNotEqual(cave, w, hex(at))
                if w >> 26 == 18:
                    li = w & 0x03FFFFFC
                    if li & 0x02000000:
                        li -= 0x04000000
                    self.assertNotEqual(cave, (li if w & 2 else at + li) & 0xFFFFFFFF, hex(at))
                if w >> 26 == 15 and w & 0xFFFF == hi:
                    rd = (w >> 21) & 31
                    for k in range(1, 8):
                        w2 = self.word(at + 4 * k)
                        if w2 is None:
                            break
                        self.assertFalse((w2 >> 26) in (14, 24) and ((w2 >> 16) & 31) == rd and w2 & 0xFFFF == lo,
                                         hex(at))

    def test_the_hooked_handler_is_only_reached_through_the_item_table(self):
        for addr, size, _off in self.sections:
            for at in range(addr, addr + size, 4):
                w = self.word(at)
                self.assertNotEqual(CB.CANT_USE_HANDLER, w, hex(at))
                if w >> 26 == 18:
                    li = w & 0x03FFFFFC
                    if li & 0x02000000:
                        li -= 0x04000000
                    self.assertNotEqual(CB.CANT_USE_HANDLER, (li if w & 2 else at + li) & 0xFFFFFFFF, hex(at))

    def test_the_level_step_is_the_level_up_effect(self):
        """`itemUse2Pokemon`: GetLevel into r22, then GrowDataBiosGetExp(level + 1), then SetExp."""
        self.assertEqual(0x7C761B78, self.word(CB.LEVEL_STEP_ADDRESS - 0x38))   # mr r22,r3
        self.assertEqual(0x5404063E, self.word(CB.LEVEL_STEP_ADDRESS + 4))      # rlwinm r4,r0,0,24,31
        self.assertEqual(18, self.word(CB.LEVEL_STEP_ADDRESS + 8) >> 26)        # bl GrowDataBiosGetExp

    def test_the_patch_lands_on_a_disc_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            iso = Path(tmp) / "x.iso"
            dol_off = 0x1000
            img = bytearray(dol_off) + bytearray(self.data)
            img[0:4] = b"GXXE"
            struct.pack_into(">I", img, ip.DOL_OFFSET_FIELD, dol_off)
            iso.write_bytes(bytes(img))
            result = ip.write_dol_words_patch(iso, CB.dol_patch_words(), CB.vanilla_digests())
            self.assertTrue(result["applied"], result["reason"])
            patched = iso.read_bytes()[dol_off:]
            word, _s = _dol_word_reader(patched)
            for address, _expected, new in CB.dol_patch_words():
                self.assertEqual(new, word(address), hex(address))
            changed = sum(1 for a, b in zip(self.data, patched) if a != b)
            self.assertLessEqual(changed, 4 * len(CB.dol_patch_words()))
            again = ip.write_dol_words_patch(iso, CB.dol_patch_words(), CB.vanilla_digests())
            self.assertEqual("already patched", again["reason"])

    def test_a_different_build_is_refused_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            iso = Path(tmp) / "x.iso"
            dol_off = 0x1000
            img = bytearray(dol_off) + bytearray(self.data)
            struct.pack_into(">I", img, ip.DOL_OFFSET_FIELD, dol_off)
            _addr, _size, off = [s for s in self.sections if s[0] <= CB.CAVE_ADDRESS < s[0] + s[1]][0]
            spot = dol_off + off + (CB.CAVE_ADDRESS + 0x40 - _addr)
            img[spot:spot + 4] = b"\xde\xad\xbe\xef"
            iso.write_bytes(bytes(img))
            before = iso.read_bytes()
            result = ip.write_dol_words_patch(iso, CB.dol_patch_words(), CB.vanilla_digests())
            self.assertFalse(result["applied"])
            self.assertEqual(before, iso.read_bytes())


# --- Realgam: every live copy of the description table ------------------------------------------------------------

class _Memory:
    def __init__(self, data: bytearray):
        self.data = data
        self.writes = []

    def read(self, address, length):
        off = address - D.MEM1_START
        return bytes(self.data[off:off + length])

    def write(self, address, payload):
        self.writes.append(address)
        off = address - D.MEM1_START
        self.data[off:off + len(payload)] = payload


def _scouted():
    return {f"Gateon Port Shop AP Item {n}": (f"Thing {n}", None) for n in range(1, 16)}


@unittest.skipUnless(SHOP_DUMP.is_file(), "needs the Gateon shop-menu dump")
class TestEveryCopyIsWritten(unittest.TestCase):
    """The Realgam report: the shelf's descriptions were wrong, and fixed themselves slowly. A reopened menu can
    load a fresh copy of `pocket_menu.msg` while the old one lingers with its magic intact; the writer kept
    answering with the old one, its canary said "still ours", and the shelf showed vanilla text until the old
    copy was overwritten. Every copy is now written."""

    STALE = 0x80600000

    def setUp(self):
        raw = bytearray(SHOP_DUMP.read_bytes())
        span = 0x5000
        off = SHOP_DUMP_BASE - D.MEM1_START
        # The copy the writer already knows about (the hot base) is the STALE one; the dump's own is live.
        raw[self.STALE - D.MEM1_START:self.STALE - D.MEM1_START + span] = raw[off:off + span]
        self.mem = _Memory(raw)
        self.writer = ram_client.ItemDescriptionWriter()
        self.writer.table_base = self.STALE
        self.originals = ram_client.read_bytes, ram_client.write_bytes
        ram_client.read_bytes, ram_client.write_bytes = self.mem.read, self.mem.write

    def tearDown(self):
        ram_client.read_bytes, ram_client.write_bytes = self.originals

    def _poll_until_both(self):
        offset = D.entry_offset(148)
        expected = D.encode_lines(["Thing 1"], D.budget_bytes(148))
        now = 1000.0
        for _ in range(40):
            self.writer.locate(now=now)
            self.writer.poll(156, _scouted(), set())
            live = self.mem.read(SHOP_DUMP_BASE + offset, len(expected))
            stale = self.mem.read(self.STALE + offset, len(expected))
            if live == expected and stale == expected:
                return True
            now += 1.5
        return False

    def test_the_live_copy_is_found_and_written_too(self):
        self.assertTrue(self._poll_until_both())
        self.assertIn(SHOP_DUMP_BASE, self.writer.extra_bases + [self.writer.table_base])

    def test_a_copy_that_is_only_the_magic_is_not_adopted(self):
        junk = 0x80700000
        header = self.mem.read(SHOP_DUMP_BASE, 0x10)
        self.mem.data[junk - D.MEM1_START:junk - D.MEM1_START + 0x10] = header
        self.assertFalse(self.writer._adopt_copy(junk))
        self.assertTrue(self.writer._adopt_copy(SHOP_DUMP_BASE))
        self.assertFalse(self.writer._adopt_copy(SHOP_DUMP_BASE), "once")

    def test_a_lost_primary_hands_over_to_a_copy(self):
        self.writer._adopt_copy(SHOP_DUMP_BASE)
        self.mem.data[self.STALE - D.MEM1_START:self.STALE - D.MEM1_START + 0x10] = bytes(0x10)
        self.assertEqual(SHOP_DUMP_BASE, self.writer.locate(now=5000.0))
        self.assertEqual([], self.writer.extra_bases)

    def test_the_candy_box_is_described_on_its_shelf(self):
        self.writer.table_base = SHOP_DUMP_BASE
        self.writer.fixed_lines_by_room = {156: {CB.CANDY_BOX_ITEM_ID: list(CB.CANDY_BOX_DESCRIPTION_LINES)}}
        self.writer.poll(156, _scouted(), set())
        offset, budget, _sid = CB.CANDY_BOX_DESCRIPTION_ENTRY
        self.assertEqual(D.encode_lines(list(CB.CANDY_BOX_DESCRIPTION_LINES), budget),
                         self.mem.read(SHOP_DUMP_BASE + offset, budget))
        # ...and nowhere else.
        self.assertNotIn(50, self.writer.desired_lines(121, list(ram_client.USELESS_BERRY_IDS), {}, set()))


class TestCopyHelpers(unittest.TestCase):
    def test_text_shapes(self):
        self.assertTrue(D.entry_looks_like_text(D.encode_lines(["Hello", "World"], 88)))
        self.assertFalse(D.entry_looks_like_text(b"\x80\x01\x02\x03" + bytes(84)))
        self.assertFalse(D.entry_looks_like_text(b"\x00A\x00B"), "no terminator")
        self.assertFalse(D.entry_looks_like_text(b"\x00A\x00\x00\x12\x34"), "garbage after the terminator")

    def test_the_candy_box_entry_agrees_with_the_table(self):
        self.assertEqual(CB.CANDY_BOX_DESCRIPTION_ENTRY, D.ITEM_DESCRIPTION_ENTRIES[CB.CANDY_BOX_ITEM_ID])
        self.assertIsNotNone(D.encode_lines(list(CB.CANDY_BOX_DESCRIPTION_LINES), CB.CANDY_BOX_DESCRIPTION_ENTRY[1]))

    def test_the_sweep_now_reaches_everywhere_in_three_scans(self):
        writer = ram_client.ItemDescriptionWriter()
        step = writer._chunk_step()
        sweep = sum(max(1, -(-(high - low) // step)) for low, high in writer._sweep_plan())
        self.assertLessEqual(-(-sweep // writer._CHUNKS_PER_POLL), 3)
        self.assertLessEqual(writer._IDLE_SECONDS_BETWEEN_SCANS, 0.5)


if __name__ == "__main__":
    unittest.main()


class TestThePatcherHalves(unittest.TestCase):
    """The two helpers `apply_patch` calls, against the real mart layout after the real berry pass."""

    def _berried(self):
        from .. import items
        rel, pointers, values = _real_layout_rel()
        out = bytearray(rel.data)
        rel_format.apply_mart_randomization(out, rel, list(items.USELESS_BERRY_IDS),
                                            frozenset(items.SHOP_EXCLUDED_ITEM_IDS), mart_groups=list(S.MART_GROUPS))
        return rel, out, pointers, values

    def _shelf(self, out, pointers, values, mart):
        patched = FakeRel(bytes(out), pointers, values)
        return [s["item_id"] for s in rel_format.read_all_mart_slots(patched) if s["mart_index"] == mart]

    def test_both_lines_when_the_candy_box_is_ready(self):
        rel, out, pointers, values = self._berried()
        before = {m: self._shelf(out, pointers, values, m) for m in S.VANILLA_MARTS}
        self.assertEqual(2, ip.apply_grind_shelf(out, rel, True))
        shelf = self._shelf(out, pointers, values, 15)
        self.assertEqual(CB.RARE_CANDY_ITEM_ID, shelf[140 - 133])
        self.assertEqual(CB.CANDY_BOX_ITEM_ID, shelf[139 - 133])
        for mart in S.VANILLA_MARTS:
            if mart != 15:
                self.assertEqual(before[mart], self._shelf(out, pointers, values, mart), mart)
        # Every other Gateon line keeps its berry, so its check is untouched.
        diff = [i for i, (a, b) in enumerate(zip(before[15], shelf)) if a != b]
        self.assertEqual([139 - 133, 140 - 133], diff)

    def test_only_the_rare_candy_without_the_code(self):
        rel, out, pointers, values = self._berried()
        self.assertEqual(1, ip.apply_grind_shelf(out, rel, False))
        shelf = self._shelf(out, pointers, values, 15)
        self.assertEqual(CB.RARE_CANDY_ITEM_ID, shelf[140 - 133])
        self.assertNotIn(CB.CANDY_BOX_ITEM_ID, shelf)

    def test_rows_without_the_code_leave_the_shard_alone(self):
        data = bytearray(0x2000)
        base = 0x100
        struct.pack_into(">I", data, base + 68 * 0x28 + 0x10, 5057)
        struct.pack_into(">I", data, base + 50 * 0x28 + 0x10, 5050)
        rel = FakeRel(bytes(data), {rel_format.ITEMS_TABLE_POINTER: base},
                      {rel_format.XD_NUMBER_OF_ITEMS_POINTER: 0x200})
        out = bytearray(data)
        self.assertEqual({"rare_candy": True, "candy_box": False}, ip.apply_grind_item_rows(out, rel, False))
        self.assertEqual(bytes(data[base + 50 * 0x28:][:0x28]), bytes(out[base + 50 * 0x28:][:0x28]))


class TestNinetyNineCandyBoxes(unittest.TestCase):
    """ADDENDUM 428: the Candy Box is a fake `/getitem` item, like the 99 Rare Candies."""

    def test_it_is_a_getitem_only_bundle_of_the_candy_box_id(self):
        from .. import items as I
        data = I.ITEM_TABLE["99 Candy Boxes"]
        self.assertIn("99 Candy Boxes", I.GETITEM_ONLY_ITEM_NAMES)
        self.assertEqual(CB.CANDY_BOX_ITEM_ID, data.game_item_id)
        self.assertEqual(99, data.quantity)
        self.assertEqual("filler", data.classification.name)

    def test_its_id_is_frozen_and_nothing_else_moved(self):
        from .. import items as I
        from .. import PokemonXDWorld
        self.assertEqual(I.ITEM_TABLE["99 Rare Candies"].id_offset + 2, I.ITEM_TABLE["99 Candy Boxes"].id_offset)
        ids = [PokemonXDWorld.item_name_to_id[name] for name in I.ITEM_TABLE
               if name not in I.RETIRED_DATAPACKAGE_ITEMS]   # ADDENDUM 443
        self.assertEqual(len(ids), len(set(ids)))

    def test_it_lands_in_the_items_pocket(self):
        base, _slots = ram_client.resolve_item_pocket(0x80000000, CB.CANDY_BOX_ITEM_ID)
        self.assertEqual(0x80000000 + ram_client.ITEMS_POCKET_OFFSET, base)

    def test_the_client_warns_once_without_the_option(self):
        source = (Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        self.assertIn("_note_candy_box_seed(ctx, idx, item_name)", source)
        self.assertIn("99 Candy Boxes", source[source.index("def _cmd_getitem"):][:300])


class TestShadowMovesAreUntouched(unittest.TestCase):
    """Shadow Pokemon keep their Shadow moves.

    The legal-moveset channel writes the four ORDINARY move slots of a DPKM record in DeckData_Story.bin (+0x14,
    the moves a Shadow Pokemon reveals as it is purified). Shadow moves live in the DDPK records of
    DeckData_DarkPokemon.bin, a different file this channel never opens."""

    def test_only_the_dpkm_ordinary_move_slots_change(self):
        from .test_addendum_423_nightmare_citadark import _deck, _record
        from ..tools import xd_deck_format as deck_format
        story = _deck({1: {"ai": 1, "slots": [1]}}, [bytes(0x20), _record(1, 10)], [bytes(0x20)])
        deck = deck_format.DeckFile(story)
        out = ip.apply_trainer_patch(story, deck, None, {1: [33, 45, 0, 0]})
        changed = [i for i, (a, b) in enumerate(zip(story, out)) if a != b]
        start = deck.dpkm_data + 0x20 + 0x14
        self.assertTrue(changed)
        self.assertTrue(all(start <= i < start + 8 for i in changed), changed)

    def test_the_moves_channel_is_story_deck_only(self):
        source = (Path(__file__).resolve().parent.parent / "tools" / "iso_patcher.py").read_text(encoding="utf-8")
        body = source[source.index("def apply_trainer_patch("):source.index("def apply_team_padding_edit(")]
        self.assertNotIn("ddpk", body.lower())
        self.assertNotIn("shadow_moves", body)
