"""The ESCAPE ROPE: a key item that takes you straight to the world map.

THE ITEM is XD's own ESCAPE ROPE (85). It has its name and description but no use: its field-use pointer is the shared
"can't use" handler (`menuUseItemNoPokecolo`, 0x800A60B4) the Candy Box and the Ability Swap already hook. Its row is
made a key item -- pocket 5, "important", not holdable -- the same first four bytes every XD key item carries
(`05 01 00 00`), and the client keeps one in the Key Items pocket.

HOW IT WORKS (main.dol; every replaced word checked first, all or nothing):

  1. DISPATCH, in front of whatever the can't-use handler's first word already is (the Ability Swap's dispatcher in
     every seed): item 85 in the field -> ROUTINE, anything else -> on to that word.
  2. ROUTINE: sets PENDING, leaves the rope in the Bag (*consumed = 0) and returns 3 -- the Bag's "close and hand the
     item back" result, which `_actTukauNormal` gives out of the Key Items pocket only for the Bonsly Card (502).
  3. KEY POCKET: that one compare (0x80023534, `cmplwi r0,502`) becomes a branch that accepts 85 as well.
  4. FIELD MENU END: `menuFieldMain`'s last word before its epilogue (0x8005BFA0, `li r3,0`) -- after the menus are
     closed, the camera and animations unpaused -- branches here: with PENDING set it clears it and calls
     `floorLink(910, 0)`, the same call the world map makes to leave, into floor 910, the map screen.

The code sits in `dbgMenuDbgPokemonGet`'s free stretch at +0x400 (the Ability Swap ends at +0x3F0, the white-out stubs
start at +0x700). Import-free apart from candy_box's encoder, so the standalone patcher can load it by path.
"""
from __future__ import annotations

try:
    from . import candy_box
except ImportError:                       # loaded by path (the standalone patcher): candy_box is a sibling file
    import importlib.util as _ilu
    from pathlib import Path as _Path

    _spec = _ilu.spec_from_file_location("_pokemon_xd_candy_box_standalone_rope",
                                         str(_Path(__file__).with_name("candy_box.py")))
    candy_box = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(candy_box)

ESCAPE_ROPE_ITEM_ID = 85
ESCAPE_ROPE_NAME_ID = 0x13D0
ESCAPE_ROPE_DISPLAY_NAME = "Escape Rope"
#: Description id 10000 + (name id - 5000), in pocket_menu.fsys's message table, and the text it now shows.
ESCAPE_ROPE_DESCRIPTION_ID = 10000 + (ESCAPE_ROPE_NAME_ID - 5000)
ESCAPE_ROPE_DESCRIPTION_LINES = ("Go to map.", "NEW - USE CAUTION")
#: Items row bytes +0x00..+0x03: pocket 5 (Key Items), important, not holdable -- what every key item row has.
KEY_ITEM_ROW_HEAD = bytes((0x05, 0x01, 0x00, 0x00))
VANILLA_ROW_HEAD = bytes((0x02, 0x00, 0x00, 0x01))

MAP_SCREEN_FLOOR = 910
FLOOR_LINK = 0x801202E0                     # floorLink(floor, entrance)
CANT_USE_HANDLER = candy_box.CANT_USE_HANDLER                     # 0x800A60B4
CANT_USE_HANDLER_FIRST_WORD = candy_box.CANT_USE_HANDLER_FIRST_WORD
USE_CONTEXT_FLAG = candy_box.USE_CONTEXT_FLAG                     # 0x804282E8: 0 in the field

KEY_POCKET_COMPARE = 0x80023534             # _actTukauNormal: cmplwi r0,502
KEY_POCKET_COMPARE_WORD = 0x280001F6
KEY_POCKET_CLOSE = 0x80023544               # result 2
KEY_POCKET_STAY = 0x8002353C                # result 0
BONSLY_CARD = 502

FIELD_MENU_END = 0x8005BFA0                 # menuFieldMain: li r3,0 before the epilogue
FIELD_MENU_END_WORD = 0x38600000

CAVE_OFFSET = 0x400
DISPATCH = candy_box.CAVE_ADDRESS + CAVE_OFFSET
ROUTINE = DISPATCH + 0x20
COMPARE = DISPATCH + 0x40
MENU_END = DISPATCH + 0x60
PENDING = DISPATCH + 0x90
CODE_SIZE = 0x94
#: SHA-1 of the vanilla CODE_SIZE bytes at DISPATCH.
CODE_VANILLA_SHA1 = "45798c29d015f6283f70945abed4e0ef6dc4a476"

_b = candy_box._b
_cmplwi = candy_box._cmplwi
_cmpwi = candy_box._cmpwi
_lis = candy_box._lis
_lwz = candy_box._lwz
_ha = candy_box._ha
BLR = candy_box.BLR
NOP = 0x60000000


def _li(rd: int, simm: int) -> int:
    return (14 << 26) | (rd << 21) | (simm & 0xFFFF)


def _stw(rs: int, d: int, ra: int) -> int:
    return (36 << 26) | (rs << 21) | (ra << 16) | (d & 0xFFFF)


def _stb(rs: int, d: int, ra: int) -> int:
    return (38 << 26) | (rs << 21) | (ra << 16) | (d & 0xFFFF)


def _lbz(rd: int, d: int, ra: int) -> int:
    return (34 << 26) | (rd << 21) | (ra << 16) | (d & 0xFFFF)


def _bc(at: int, target: int, bo: int, bi: int) -> int:
    delta = target - at
    if not -0x8000 <= delta < 0x8000 or delta & 3:
        raise ValueError(f"conditional branch from 0x{at:08X} to 0x{target:08X} is out of range")
    return (16 << 26) | (bo << 21) | (bi << 16) | (delta & 0xFFFC)


def _beq(at: int, target: int) -> int:
    return _bc(at, target, 12, 2)


def _bne(at: int, target: int) -> int:
    return _bc(at, target, 4, 2)


def _lo(value: int) -> int:
    return value & 0xFFFF


def branch_target(at: int, word: int) -> "int | None":
    """Where an unconditional `b` (no link) at `at` goes, or None if `word` is not one."""
    if word >> 26 != 18 or word & 3:
        return None
    delta = word & 0x03FFFFFC
    if delta & 0x02000000:
        delta -= 0x04000000
    return (at + delta) & 0xFFFFFFFF


def chain_words(hook_word: int) -> "tuple[int, int]":
    """DISPATCH's last two words: on to whatever the can't-use handler's first word is now."""
    at = DISPATCH + 0x18
    target = branch_target(CANT_USE_HANDLER, hook_word)
    if target == DISPATCH:
        raise ValueError("the Escape Rope's dispatcher is already in front of the can't-use handler")
    if target is not None:
        return _b(at, target), NOP
    if hook_word == CANT_USE_HANDLER_FIRST_WORD:
        return CANT_USE_HANDLER_FIRST_WORD, _b(at + 4, CANT_USE_HANDLER + 4)
    raise ValueError(f"the can't-use handler starts with 0x{hook_word:08X}, which is neither its vanilla word nor a "
                     "branch -- a different build")


def cave_code(hook_word: int) -> "list[int]":
    d, r, c, m = DISPATCH, ROUTINE, COMPARE, MENU_END
    words = [
        # DISPATCH (r3 = item, r4 = &consumed)
        _cmplwi(3, ESCAPE_ROPE_ITEM_ID),               # d+00
        _bne(d + 0x04, d + 0x18),                      # d+04
        _lis(11, _ha(USE_CONTEXT_FLAG)),               # d+08
        _lwz(11, _lo(USE_CONTEXT_FLAG), 11),           # d+0C
        _cmpwi(11, 0),                                 # d+10
        _beq(d + 0x14, r),                             # d+14  in the field: the routine
        *chain_words(hook_word),                       # d+18, d+1C
        # ROUTINE
        _li(0, 1),                                     # r+00
        _lis(11, _ha(PENDING)),                        # r+04
        _stb(0, _lo(PENDING), 11),                     # r+08  PENDING = 1
        _li(0, 0),                                     # r+0C
        _stw(0, 0, 4),                                 # r+10  *consumed = 0: the rope stays
        _li(3, 3),                                     # r+14  close the Bag
        BLR,                                           # r+18
        NOP,                                           # r+1C
        # COMPARE (r0 = item; replaces `cmplwi r0,502`)
        _cmplwi(0, BONSLY_CARD),                       # c+00
        _beq(c + 0x04, c + 0x10),                      # c+04
        _cmplwi(0, ESCAPE_ROPE_ITEM_ID),               # c+08
        _bne(c + 0x0C, c + 0x14),                      # c+0C
        _b(c + 0x10, KEY_POCKET_CLOSE),                # c+10  result 2: close the Bag
        _b(c + 0x14, KEY_POCKET_STAY),                 # c+14  result 0
        NOP, NOP,                                      # c+18, c+1C
        # MENU END (replaces `li r3,0`)
        _lis(11, _ha(PENDING)),                        # m+00
        _lbz(0, _lo(PENDING), 11),                     # m+04
        _cmpwi(0, 0),                                  # m+08
        _beq(m + 0x0C, m + 0x24),                      # m+0C
        _li(0, 0),                                     # m+10
        _stb(0, _lo(PENDING), 11),                     # m+14  PENDING = 0
        _li(3, MAP_SCREEN_FLOOR),                      # m+18
        _li(4, 0),                                     # m+1C
        _b(m + 0x20, FLOOR_LINK, link=True),           # m+20  floorLink(910, 0)
        _li(3, 0),                                     # m+24  the replaced word
        _b(m + 0x28, FIELD_MENU_END + 4),              # m+28
        NOP,                                           # m+2C
        0,                                             # PENDING (+0x90)
    ]
    assert len(words) * 4 == CODE_SIZE
    return words


def dol_patch_words(hook_word: int) -> "tuple[tuple[int, int | None, int], ...]":
    """(address, vanilla or None, new). The code's span is checked by `vanilla_digests`; the three hooks by word."""
    words: "list[tuple[int, int | None, int]]" = [
        (DISPATCH + 4 * i, None, new) for i, new in enumerate(cave_code(hook_word))]
    words += [
        (KEY_POCKET_COMPARE, KEY_POCKET_COMPARE_WORD, _b(KEY_POCKET_COMPARE, COMPARE)),
        (FIELD_MENU_END, FIELD_MENU_END_WORD, _b(FIELD_MENU_END, MENU_END)),
        (CANT_USE_HANDLER, hook_word, _b(CANT_USE_HANDLER, DISPATCH)),
    ]
    return tuple(words)


def vanilla_digests() -> "tuple[tuple[int, int, str], ...]":
    return ((DISPATCH, CODE_SIZE, CODE_VANILLA_SHA1),)


def row_edits() -> "dict[int, bytes]":
    return {0x00: KEY_ITEM_ROW_HEAD}


assert CAVE_OFFSET >= 0x3F0 and CAVE_OFFSET + CODE_SIZE <= 0x700, (
    "between the Ability Swap's code (ends +0x3F0) and the white-out stubs (+0x700)")
