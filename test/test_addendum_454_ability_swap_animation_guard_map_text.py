"""ADDENDUM 454 (2026-10-09) -- the ABILITY SWAP as a USE item, Disable Move Animations without the AI cost (plus a
live guard), and one world-map description per place.

The ability item gets a shorter name and is a USE item, not a held one. Disabled move animations get a live guard,
because the animations could start playing again. Hovering a place on the world map made its description text jump
as the story byte was written, so every description in the ISO is rewritten to one text (the first/earliest) and a
"rewrite" lands on the same text anyway.
"""
from __future__ import annotations

import hashlib
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .. import Client
from .. import ram_client as rc
from ..game_data import ability_patch as AP
from ..game_data import candy_box as CB
from ..game_data import map_descriptions as MD
from ..game_data import move_animations as MA
from ..tools import iso_patcher as ip
from ..tools import xd_deck_format as deck_format

WORKING = Path("/mnt/user-data/uploads/PokemonXD-working")
REAL_DOL = WORKING / "main_dol.bin"
DUMPS = WORKING / "bridge" / "dumps"
PATCHER = Path(ip.__file__).read_text(encoding="utf-8")
CLIENT = Path(Client.__file__).read_text(encoding="utf-8")


def _dol_word_reader():
    data = REAL_DOL.read_bytes()
    sections = []
    for i in range(18):
        off, addr, size = (struct.unpack_from(">I", data, base + i * 4)[0] for base in (0, 0x48, 0x90))
        if size:
            sections.append((addr, size, off))

    def word(address):
        for addr, size, off in sections:
            if addr <= address < addr + size:
                return struct.unpack_from(">I", data, off + address - addr)[0]
        raise KeyError(hex(address))
    return word


def _branch_target(at: int, word: int) -> int:
    if word >> 26 == 16:                             # bc: a 16-bit displacement
        off = word & 0xFFFC
        off = off - 0x10000 if off & 0x8000 else off
        return (at + off) & 0xFFFFFFFF
    off = word & 0x03FFFFFC
    if off & 0x02000000:
        off -= 0x04000000
    return (at + off) & 0xFFFFFFFF


# --- the Ability Swap -------------------------------------------------------------------------------------------
class TestTheItem(unittest.TestCase):
    def test_name_fits_the_green_shard(self) -> None:
        self.assertEqual((51, 5051, "GREEN SHARD", "ABILITYSWAP"),
                         (AP.ABILITY_PATCH_ITEM_ID, AP.ABILITY_PATCH_NAME_ID, AP.ABILITY_PATCH_VANILLA_NAME,
                          AP.ABILITY_PATCH_NAME))
        self.assertEqual("Ability Swap", AP.ABILITY_PATCH_DISPLAY_NAME)

    def test_it_is_not_the_candy_box(self) -> None:
        self.assertNotEqual(CB.CANDY_BOX_ITEM_ID, AP.ABILITY_PATCH_ITEM_ID)


class TestTheCode(unittest.TestCase):
    def test_layout_fits_between_the_candy_box_and_the_conditional_catch(self) -> None:
        self.assertGreaterEqual(AP.CAVE_OFFSET, CB.LEARN_END_OFFSET)
        self.assertLessEqual(AP.CAVE_OFFSET + AP.CODE_SIZE, 0x800)
        for candy in (False, True):
            self.assertEqual(AP.CODE_SIZE // 4, len(AP.cave_code(candy)))

    def test_the_calls_are_the_games_own(self) -> None:
        code = AP.cave_code(False)
        calls = []
        for i, w in enumerate(code):
            if w >> 26 == 18 and w & 1:
                calls.append(_branch_target(AP.DISPATCH_ADDRESS + 4 * i, w))
        self.assertEqual([AP.MENU_OPEN_POKEMON, AP.MENU_GET_POKEMON, AP.GET_ABILITY_FLAG, AP.SET_ABILITY_FLAG,
                          AP.GET_ABILITY_FLAG, AP.DISP_MSG, AP.PLAY_RECOVER_SE, AP.MENU_POKEMON_UPDATE,
                          AP.OFFSCREEN_PRIORITY, AP.MENU_CLOSE_POKEMON], calls)

    def test_dispatch_and_the_chain(self) -> None:
        plain, chained = AP.cave_code(False), AP.cave_code(True)
        self.assertEqual(0x28030033, plain[0], "cmplwi r3,51")
        self.assertEqual(_branch_target(AP.DISPATCH_ADDRESS + 0x14, plain[5]), AP.ROUTINE_ADDRESS,
                         "beq to the routine in the field")
        # Without the Candy Box: the replaced stwu, then back to the handler's second word.
        self.assertEqual(AP.HOOK_VANILLA_WORD, plain[6])
        self.assertEqual(AP.HOOK_ADDRESS + 4, _branch_target(AP.DISPATCH_ADDRESS + 0x1C, plain[7]))
        # With it: on to the Candy Box's dispatcher, which still holds the stwu.
        self.assertEqual(CB.CAVE_ADDRESS, _branch_target(AP.DISPATCH_ADDRESS + 0x18, chained[6]))
        self.assertEqual(plain[:6], chained[:6])
        self.assertEqual(plain[8:], chained[8:])

    def test_the_hook(self) -> None:
        for candy in (False, True):
            hook = AP.dol_patch_words(candy)[-1]
            self.assertEqual(AP.HOOK_ADDRESS, hook[0])
            self.assertEqual(AP.DISPATCH_ADDRESS, _branch_target(AP.HOOK_ADDRESS, hook[2]))
            self.assertEqual(AP.HOOK_VANILLA_WORD if not candy else
                             CB._b(CB.CANT_USE_HANDLER, CB.CAVE_ADDRESS), hook[1])
        self.assertEqual(CB._b(CB.CANT_USE_HANDLER, CB.CAVE_ADDRESS),
                         dict((a, n) for a, _v, n in CB.dol_patch_words(False))[CB.CANT_USE_HANDLER],
                         "what the Candy Box leaves there")

    def test_used_up_only_on_a_change(self) -> None:
        code = AP.cave_code(False)
        store = code.index(0x901D0000)              # stw r0,0(r29): *consumed = 1
        self.assertEqual(0x38000001, code[store - 1])
        self.assertEqual(0x3BE00000, code[store + 1], "result 0: used")
        self.assertEqual(AP.PLAY_RECOVER_SE, _branch_target(AP.DISPATCH_ADDRESS + 4 * (store - 3), code[store - 3]))

    @unittest.skipUnless(REAL_DOL.is_file(), "needs the extracted main.dol")
    def test_against_the_real_dol(self) -> None:
        word = _dol_word_reader()
        for address, vanilla, _new in AP.dol_patch_words(False):
            if vanilla is not None:
                self.assertEqual(vanilla, word(address), hex(address))
        for start, length, digest in AP.vanilla_digests():
            span = b"".join(struct.pack(">I", word(start + i)) for i in range(0, length, 4))
            self.assertEqual(digest, hashlib.sha1(span).hexdigest(), hex(start))
        self.assertEqual(0x5463043E, word(0x80022F88), "_getUseFunc is as mapped")
        self.assertEqual(0x48000000 | ((AP.MENU_OPEN_POKEMON - 0x800A54D8) & 0x03FFFFFC) | 1, word(0x800A54D8),
                         "menuUseItemEvolution opens the party menu the same way")


class TestThePatcher(unittest.TestCase):
    def test_after_the_candy_box_and_before_the_row(self) -> None:
        body = PATCHER[PATCHER.index("def apply_patch("):]
        candy = body.index("candy_box_code_ready = bool(candy_box_dol")
        swap = body.index("_swap.dol_patch_words(candy_box_code_ready)")
        row = body.index("ability_patch_row_ready = apply_ability_patch_row(rel_bytes, rel)")
        self.assertLess(candy, swap)
        self.assertLess(swap, row)
        self.assertIn("if ability_patch_code_ready:\n            ability_patch_row_ready", body)

    def test_the_client_no_longer_handles_it(self) -> None:
        self.assertNotIn("AbilityPatchTracker", CLIENT)
        self.assertIn('self.ability_patch = bool(slot_data.get("ability_patch"))', CLIENT)


# --- Disable Move Animations ------------------------------------------------------------------------------------
def _table(type_func: int = 0x8022C46C, var_func: int = 0x8022C518) -> bytearray:
    block = bytearray(MA.RECORD_COUNT * MA.RECORD_SIZE)
    for i in range(MA.RECORD_COUNT):
        t, v = (MA.TYPE_NULL, MA.VARIATION_NULL) if i in MA.NULL_RECORDS else (type_func, var_func)
        struct.pack_into(">II", block, i * MA.RECORD_SIZE + MA.TYPE_OFFSET, t, v)
    return block


class TestTheAnimationPointers(unittest.TestCase):
    def test_every_pointer_goes_null_and_nothing_else(self) -> None:
        block = _table()
        current = {a: struct.unpack_from(">I", block, a - MA.WAZA_FUNC_DATA)[0] for a, _n in MA.pointer_addresses()}
        words = MA.dol_patch_words(current)
        self.assertEqual(2 * MA.RECORD_COUNT, len(words))
        offsets = {(a - MA.WAZA_FUNC_DATA) % MA.RECORD_SIZE for a, _o, _n in words}
        self.assertEqual({MA.TYPE_OFFSET, MA.VARIATION_OFFSET}, offsets, "the AI's four pointers are never written")
        self.assertEqual({MA.TYPE_NULL, MA.VARIATION_NULL}, {n for _a, _o, n in words})

    def test_an_unknown_word_refuses(self) -> None:
        block = _table()
        current = {a: struct.unpack_from(">I", block, a - MA.WAZA_FUNC_DATA)[0] for a, _n in MA.pointer_addresses()}
        current[MA.WAZA_FUNC_DATA + 5 * MA.RECORD_SIZE + MA.TYPE_OFFSET] = 0x80001234
        with self.assertRaises(ValueError):
            MA.dol_patch_words(current)

    def test_the_guard(self) -> None:
        block = _table()
        self.assertTrue(MA.anchors_ok(bytes(block)))
        needs = MA.table_needs_guard(bytes(block))
        self.assertEqual(2 * (MA.RECORD_COUNT - len(MA.NULL_RECORDS)), len(needs))
        for address, null in needs:
            struct.pack_into(">I", block, address - MA.WAZA_FUNC_DATA, null)
        self.assertEqual([], MA.table_needs_guard(bytes(block)))
        self.assertFalse(MA.anchors_ok(bytes(_table(0x80001234))), "not this build: hands off")

    def test_func_id_repairs(self) -> None:
        moves = bytearray(360 * 0x38)
        for i in range(360):
            struct.pack_into(">H", moves, i * 0x38 + 0x1E, 0 if i in (0, 355, 7, 300) else i)
        self.assertEqual([(7 * 0x38 + 0x1E, 7), (300 * 0x38 + 0x1E, 300)], MA.func_id_repairs(bytes(moves), 0x38))

    @unittest.skipUnless(REAL_DOL.is_file(), "needs the extracted main.dol")
    def test_against_the_real_dol(self) -> None:
        word = _dol_word_reader()
        current = {a: word(a) for a, _n in MA.pointer_addresses()}
        words = MA.dol_patch_words(current)
        self.assertEqual(10, sum(1 for _a, was, new in words if was == new), "the five Null records")
        self.assertEqual(0x4E800020, word(MA.TYPE_NULL), "fightWazaWzxTypeFuncNull: blr")
        self.assertEqual((0x38600000, 0x4E800020), (word(MA.VARIATION_NULL), word(MA.VARIATION_NULL + 4)))
        # wazaDataBiosGetWazaFuncDataId reads +0x1E -- the AI's index too, which is why it is no longer written.
        self.assertEqual(0xA063001E, word(0x8013DB50 + 0x10))

    @unittest.skipUnless((DUMPS / "battle1.bin").is_file(), "needs a RAM dump")
    def test_the_dump_holds_the_dol_table(self) -> None:
        ram = (DUMPS / "battle1.bin").read_bytes()
        block = ram[MA.WAZA_FUNC_DATA - 0x80000000:][:MA.RECORD_COUNT * MA.RECORD_SIZE]
        self.assertTrue(MA.anchors_ok(block))


class _Memory:
    def __init__(self) -> None:
        self.data: "dict[int, int]" = {}

    def read_bytes(self, address: int, length: int) -> bytes:
        return bytes(self.data.get(address + i, 0) for i in range(length))

    def write_bytes(self, address: int, data: bytes) -> None:
        for i, b in enumerate(data):
            self.data[address + i] = b


class TestTheLiveGuard(unittest.TestCase):
    def test_restores_null_pointers_and_func_ids(self) -> None:
        from ..game_data.item_name_strings import COMMON_REL_RAM_BASE
        from ..tools import xd_rel_format as rf
        mem = _Memory()
        mem.write_bytes(MA.WAZA_FUNC_DATA, bytes(_table()))
        base = COMMON_REL_RAM_BASE + rc.MOVE_TABLE_REL_OFFSET
        for index, (pp, power) in rf.MOVE_TABLE_FINGERPRINT.items():
            mem.write_bytes(base + index * 0x38 + rf.MOVE_PP_OFFSET, bytes((pp,)))
            mem.write_bytes(base + index * 0x38 + rf.MOVE_BASE_POWER_OFFSET, bytes((power,)))
        with mock.patch.object(rc, "read_bytes", side_effect=mem.read_bytes), \
                mock.patch.object(rc, "write_bytes", side_effect=mem.write_bytes):
            fixed = rc.guard_move_animations()
            self.assertEqual(2 * (MA.RECORD_COUNT - 2), fixed["pointers"])
            self.assertEqual(358, fixed["func_ids"])
            self.assertEqual({"pointers": 0, "func_ids": 0}, rc.guard_move_animations())
        self.assertEqual(33, struct.unpack(">H", mem.read_bytes(base + 33 * 0x38 + 0x1E, 2))[0])

    def test_hands_off_an_unknown_table(self) -> None:
        mem = _Memory()
        with mock.patch.object(rc, "read_bytes", side_effect=mem.read_bytes), \
                mock.patch.object(rc, "write_bytes", side_effect=mem.write_bytes) as writes:
            self.assertIsNone(rc.guard_move_animations())
            writes.assert_not_called()

    def test_wired_into_the_poll_loop(self) -> None:
        # The guard goes through `animations_disabled(ctx)`, which folds in the `/animations` override.
        self.assertIn("animations_disabled(ctx) and time.monotonic() >= ctx._animation_guard_due:", CLIENT)
        self.assertIn("def animations_disabled(ctx: PokemonXDContext) -> bool:", CLIENT)
        self.assertIn('self.disable_move_animations = bool(slot_data.get("disable_move_animations"))', CLIENT)
        from .. import PokemonXDWorld  # noqa: F401 -- the key travels in slot_data
        source = Path(Client.__file__).with_name("__init__.py").read_text(encoding="utf-8")
        self.assertIn('"disable_move_animations",  # ADDENDUM 454', source)


# --- the world-map descriptions ---------------------------------------------------------------------------------
def _map_table() -> bytes:
    rows = []
    variants = {6: {9: 0xD4FD}, 8: {5: 0xD4FB, 9: 0xD4FE}, 21: {2: 0xD502, 4: 0xD4FA, 13: 0xD503}}
    for index, threshold in enumerate(MD.THRESHOLDS):
        words = list(MD.FIRST_RECORD)
        words[0] = threshold
        for col, mid in variants.get(index, {}).items():
            words[col] = mid
        rows.append(struct.pack(">19I", *words))
    return b"".join(rows)


class TestTheMapTable(unittest.TestCase):
    def test_find_and_rewrite(self) -> None:
        data = bytearray(b"\x11" * 64 + _map_table() + b"\x22" * 32)
        at = MD.find_table(bytes(data))
        self.assertEqual(64, at)
        self.assertEqual(MD.RECORD_COUNT, MD.rewrite(data, at), "every record differs from the target somewhere")
        for index in range(MD.RECORD_COUNT):
            words = struct.unpack_from(">19I", data, at + index * MD.RECORD_SIZE)
            self.assertEqual(MD.THRESHOLDS[index], words[0])
            self.assertEqual(MD.TARGET_IDS, words[1:])
        self.assertEqual(64, MD.find_table(bytes(data)), "still found once rewritten")
        self.assertEqual(0, MD.rewrite(data, at))
        self.assertEqual(b"\x11" * 64, bytes(data[:64]))

    def test_the_three_named_places(self) -> None:
        """SS Libra, the Cipher Lab and the Key Lair use their first clear description."""
        expected = list(MD.FIRST_RECORD[1:])
        expected[MD.CIPHER_LAB_WORD - 1] = 0xD4FD     # CIPHER LAB / CIPHER's old lab back in operation.
        expected[MD.SS_LIBRA_WORD - 1] = 0xD4FF       # S.S. LIBRA / The POKeMON cargo ship that went missing ...
        expected[MD.KEY_LAIR_WORD - 1] = 0xD501       # CIPHER KEY LAIR / A factory made secretly by CIPHER.
        self.assertEqual(tuple(expected), MD.TARGET_IDS)
        self.assertEqual((0xD4EB, 0xD4ED, 0xD4EF), tuple(MD.FIRST_RECORD[w] for w in (9, 11, 13)),
                         "the placeholders they replace: MYSTERY FACILITY, ???, ???")

    @unittest.skipUnless((DUMPS / "mapsel_s1_phenac.bin").is_file(), "needs the map-screen RAM dump")
    def test_the_texts_in_the_dump(self) -> None:
        data = (DUMPS / "mapsel_s1_phenac.bin").read_bytes()
        pairs, at = {}, 0x7DFA50
        while 0xD400 <= struct.unpack_from(">I", data, at)[0] <= 0xD600:
            mid, off = struct.unpack_from(">II", data, at)
            pairs[mid] = off
            at += 8

        def name(mid: int) -> str:
            out, j = "", 0x7DFA40 + pairs[mid]
            while True:
                c = struct.unpack_from(">H", data, j)[0]
                if c in (0, 0xFFFF):
                    return out
                out += chr(c)
                j += 2
        self.assertEqual(("CIPHER LAB", "S.S. LIBRA", "CIPHER KEY LAIR"),
                         tuple(name(MD.TARGET_IDS[w - 1]) for w in (9, 11, 13)))
        self.assertEqual("PHENAC CITY", name(MD.TARGET_IDS[3]))

    def test_a_lookalike_is_refused(self) -> None:
        table = bytearray(_map_table())
        struct.pack_into(">I", table, 5 * MD.RECORD_SIZE, 0x99)
        self.assertIsNone(MD.find_table(bytes(table)))

    @unittest.skipUnless((DUMPS / "mapsel_s1_phenac.bin").is_file(), "needs the map-screen RAM dump")
    def test_against_three_dumps(self) -> None:
        for name, address in (("mapsel_s1_phenac.bin", 0x807DF288), ("reboot_phenac.bin", 0x80A2CA28),
                              ("vis_dump3_snagem.bin", 0x807C30A8)):
            path = DUMPS / name
            if not path.is_file():
                continue
            data = bytearray(path.read_bytes())
            self.assertEqual(address - 0x80000000, MD.find_table(bytes(data)), name)
            self.assertEqual(MD.RECORD_COUNT, MD.rewrite(data, address - 0x80000000), name)

    def test_the_patch_writes_and_reads_back(self) -> None:
        from .test_addendum_423_nightmare_citadark import _fsys
        module = b"\x00" * 0x100 + _map_table() + b"\x00" * 0x40
        fsys = _fsys([(b"world_map", module), (b"other", b"\x01" * 0x80)])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "copy.iso"
            path.write_bytes(_iso_with(b"world_map.fsys", fsys))
            result = ip.write_map_descriptions_patch(path)
            self.assertTrue(result["applied"], result)
            self.assertEqual(("world_map.fsys", MD.RECORD_COUNT), (result["container"], result["records_changed"]))
            reader = ip.open_reader(path)
            try:
                fst = ip.parse_fst(reader)
                off, length, _ = ip.find_by_basename(fst, "world_map.fsys")
                container = reader.read(off, length)
            finally:
                reader.close()
            e = ip.parse_fsys(container)["world_map"]
            data = deck_format.lzss_decode(container[e["data_off"]:e["data_off"] + 0x10 + e["comp_size"]])
            self.assertEqual(len(module), len(data))
            for index in range(MD.RECORD_COUNT):
                self.assertEqual(MD.TARGET_IDS,
                                 struct.unpack_from(">19I", data, 0x100 + index * MD.RECORD_SIZE)[1:])
            again = ip.write_map_descriptions_patch(path)
            self.assertEqual((True, "already patched"), (again["applied"], again["reason"]))

    def test_a_disc_without_it_says_so(self) -> None:
        from .test_addendum_423_nightmare_citadark import _fsys
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "copy.iso"
            path.write_bytes(_iso_with(b"world_map.fsys", _fsys([(b"other", b"\x01" * 0x80)])))
            result = ip.write_map_descriptions_patch(path)
            self.assertFalse(result["applied"])
            self.assertIn("not found", result["reason"])

    def test_every_seed_asks_for_it(self) -> None:
        source = Path(Client.__file__).with_name("__init__.py").read_text(encoding="utf-8")
        self.assertIn('seed_data["map_descriptions_constant"] = True', source)
        self.assertIn('if seed.get("map_descriptions_constant"):', PATCHER)


def _iso_with(name: bytes, container: bytes) -> bytes:
    fst_offset, file_offset = 0x440, 0x800
    name = name + b"\x00"
    fst = bytearray(24 + len(name))
    fst[0] = 1
    struct.pack_into(">I", fst, 8, 2)
    struct.pack_into(">I", fst, 16, file_offset)
    struct.pack_into(">I", fst, 20, len(container))
    fst[24:] = name
    iso = bytearray(file_offset + len(container))
    struct.pack_into(">I", iso, 0x424, fst_offset)
    struct.pack_into(">I", iso, 0x428, len(fst))
    iso[fst_offset:fst_offset + len(fst)] = fst
    iso[file_offset:] = container
    return bytes(iso)


if __name__ == "__main__":
    unittest.main()
