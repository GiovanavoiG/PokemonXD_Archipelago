"""ADDENDUM 453 / 454 -- the ABILITY SWAP.

Player (453): "Can we make an item that cycles through a pokemon's abilities called ability patch? Add it as an item
that appears in gateon shop after all kyogre parts, make it 2000 dollars, and make it appear regardless of options."
Player (454): "Can you rework it and shorten the name then? Does AbilitySwap fit, or AbilityPatch without a space? I
want it as a use item not held."

THE ITEM is the GREEN SHARD (51). XD carries it over from Ruby/Sapphire with no use and no source in this world, and
its name is eleven letters, so "ABILITYSWAP" fits the name string in place (names are rewritten equal-length only,
so "ABILITY PATCH", thirteen, fits nothing; "ABILITYPATCH" fit only ADDENDUM 453's DEEPSEATOOTH, a hold item). The
shards share the game's "can't use" handler, which ADDENDUM 427 already hooks for the Candy Box (the Yellow Shard).
Its row (XD's Items table, read off a RAM dump):

    price 200 (+0x06), NameID 5051 (+0x10), description 10051 (+0x14),
    field-use and battle-use 0x800A60B4 (+0x1C, +0x20) -- `menuUseItemNoPokecolo`, the shared "can't use" handler

The row edit is the price only (2000). The field-use pointer is a REL relocation and is NOT edited (ADDENDUM 427's
note): the handler it points at is what changes.

HOW IT IS USED. Bag -> Items -> ABILITYSWAP -> USE -> pick a party Pokemon, exactly like an evolution stone. The Bag
offers USE for every Items-pocket item in the field (`_makeActMenu`'s table has no condition on it), and
`_actTukauNormal` calls the item's field-use function as `func(item, &consumed)`: return 0 = used, 1 = not used, and
`*consumed = 1` takes one from the Bag.

THE CODE (main.dol, every replaced word checked first; all or nothing):

  hook   0x800A60B4  `stwu r1,-16(r1)` (the handler's first word) -> `b DISPATCH`.
         With Reduce Citadark Grind's Candy Box in, that word is already `b <Candy Box dispatcher>`; this patch
         then expects that branch instead and chains to it, so both items work and neither patch's order matters
         beyond "Candy Box first", which is how the patcher runs them.

  DISPATCH  item 51 in the field (`_getUseFunc`'s flag 0x804282E8 is 0) -> ROUTINE; anything else -> the word the
            hook replaced (the vanilla `stwu` and a branch back, or the Candy Box's dispatcher).

  ROUTINE   menuUseItemEvolution's shape, with the stone's work swapped for the ability bit:
              slot = menuPocket2OpenPokemonMenu(item, 1)          ; cancelled -> close, return 1
              menuPocket2GetTemochiPokemon(slot, &pkm, &fight)
              old = pokemon_GetTokuseiFlag(pkm)
              pokemon_SetTokuseiFlag(pkm, old ^ 1)                ; forced to 0 for a one-ability species
              if pokemon_GetTokuseiFlag(pkm) == old:              ; nothing changed
                  dispMsg(0xC374)                                 ; "It won't have any effect." -- not used up
              else:
                  playRecoverSE(item); menuPokemonUpdate(); *consumed = 1; result 0
              menuOffScreenSetPriority(0); menuPocket2ClosePokemonMenu(slot); return result

The game's own accessors do the work: `pokemon_GetTokuseiFlag` reads bit 0x40 of `Pokemon` +0x1D and answers 0 when
the species has no second ability (species table +0x33 is 0); `pokemon_SetTokuseiFlag` writes it, forcing 0 there.
In battle the Green Shard stays the "can't use" item it always was.

The code sits in `dbgMenuDbgPokemonGet` (ADDENDUM 427's cave) at +0x300, in the free stretch between the Candy Box's
code (to +0x284) and the conditional catch (+0x800).

THE SHELF. Gateon Port Shop's last tier (mart 15) -- the one the Robo Kyogre Parts open (the Gateon story override
with all Parts held; the post-Gorigan tier when that option is off) -- sells it on line 13 (a Hyper Potion in
vanilla). Always, whatever the options: the shelf write runs even with shops vanilla, and with Randomize Shops on
that line is no longer a check (it was a filler-only restock line, ADDENDUM 387).
"""
from __future__ import annotations

import struct

try:
    from . import candy_box
except ImportError:                       # loaded by path (the standalone patcher): candy_box is a sibling file
    import importlib.util as _ilu
    from pathlib import Path as _Path

    _spec = _ilu.spec_from_file_location("_pokemon_xd_candy_box_standalone",
                                         str(_Path(__file__).with_name("candy_box.py")))
    candy_box = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(candy_box)

ABILITY_PATCH_ITEM_ID = 51
ABILITY_PATCH_NAME_ID = 5051
ABILITY_PATCH_VANILLA_NAME = "GREEN SHARD"
ABILITY_PATCH_NAME = "ABILITYSWAP"
ABILITY_PATCH_PRICE = 2000
ABILITY_PATCH_DISPLAY_NAME = "Ability Swap"

ITEM_PRICE_OFFSET = 0x06              # u16

GATEON_SHOP = "Gateon Port Shop"
GATEON_FINAL_MART = 15
ABILITY_PATCH_LINE = 13
ABILITY_PATCH_LINE_VANILLA_ITEM = 21  # Hyper Potion

#: (offset in pocket_menu.msg, byte budget, description id) -- read out of the Gateon shop-menu dump.
DESCRIPTION_ENTRY = (0x002425, 88, 10051)
DESCRIPTION_LINES = ["Use it to swap a", "POK\u00e9MON's ability."]

#: `Pokemon` +0x1D, bit 0x40 -- pokemon_GetTokuseiFlag / pokemon_SetTokuseiFlag.
ABILITY_FLAG_OFFSET = 0x1D
ABILITY_FLAG_BIT = 0x40

#: Internal species with a SECOND ability (species table +0x33 non-zero), read off XD's own table in a RAM dump and
#: re-checked against it by the test. 129 of 415. Documentation and tests only: the game's accessors decide.
TWO_ABILITY_SPECIES: "frozenset[int]" = frozenset((
    19, 20, 23, 24, 50, 51, 54, 55, 58, 59, 60, 61, 62, 63, 64, 65, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83,
    84, 85, 88, 89, 95, 98, 99, 100, 101, 104, 105, 108, 111, 112, 113, 118, 119, 120, 121, 131, 138, 139, 140, 141,
    142, 143, 161, 162, 163, 164, 165, 166, 167, 168, 170, 171, 175, 176, 177, 178, 183, 184, 185, 186, 190, 193, 194,
    195, 199, 203, 206, 207, 208, 209, 210, 211, 214, 215, 218, 219, 222, 225, 226, 227, 228, 229, 242, 295, 296, 297,
    298, 299, 300, 313, 314, 320, 326, 327, 332, 333, 334, 335, 336, 337, 338, 350, 351, 352, 355, 363, 367, 368, 381,
    382, 383, 384, 386, 392, 393, 394, 413,
))

# --- main.dol -----------------------------------------------------------------------------------------------------
HOOK_ADDRESS = candy_box.CANT_USE_HANDLER            # 0x800A60B4, menuUseItemNoPokecolo
HOOK_VANILLA_WORD = candy_box.CANT_USE_HANDLER_FIRST_WORD
USE_CONTEXT_FLAG = candy_box.USE_CONTEXT_FLAG        # 0x804282E8: 0 in the field
CAVE_OFFSET = 0x300
DISPATCH_ADDRESS = candy_box.CAVE_ADDRESS + CAVE_OFFSET
ROUTINE_ADDRESS = DISPATCH_ADDRESS + 0x20
CODE_SIZE = 0x20 + 0xD0

MENU_OPEN_POKEMON = 0x8002420C          # menuPocket2OpenPokemonMenu(item, 1) -> slot, < 0 when cancelled
MENU_GET_POKEMON = 0x80024148           # menuPocket2GetTemochiPokemon(slot, &pkm, &fightPkm)
MENU_CLOSE_POKEMON = 0x800241E0         # menuPocket2ClosePokemonMenu(slot)
GET_ABILITY_FLAG = 0x801491D0           # pokemon_GetTokuseiFlag(pkm)
SET_ABILITY_FLAG = 0x8014794C           # pokemon_SetTokuseiFlag(pkm, flag)
DISP_MSG = 0x800A481C                   # dispMsg__FUl
PLAY_RECOVER_SE = 0x800A4380            # playRecoverSE__FUl
MENU_POKEMON_UPDATE = 0x80015E80        # menuPokemonUpdate
OFFSCREEN_PRIORITY = 0x80114B8C         # menuOffScreenSetPriority
NO_EFFECT_MSG = 0xC374                  # "It won't have any effect." -- menuUseItemEvolution's

#: The vanilla words at DISPATCH_ADDRESS the code replaces (more of the debug party's item grants). Checked first.
CAVE_ORIGINAL_HEX = (
    "3880008838a0000338c0ffff480e5aad7fe3fb783880008638a0000138c0ffff480e5a997fe3fb783880008738a0000238c0ffff"
    "480e5a857fe3fb783880020038a0000138c0ffff480e5a717fe3fb783880020238a0000138c0ffff480e5a5d7fe3fb7838800203"
    "38a0000138c0ffff480e5a497fe3fb783880020138a0000138c0ffff480e5a357fe3fb783880021538a0000138c0ffff480e5a21"
    "7fe3fb783880021638a0000138c0ffff480e5a0d7fe3fb783880021738a0000138c0ffff480e59f97fe3fb783880021838a00001"
    "38c0ffff480e59e57fe3fb783880021938a0000138c0ffff480e59d17fe3fb783880021a38a0000138c0ffff480e59bd"
)

# A minimal Gekko encoder: the forms this code uses beyond candy_box's, each checked by the test.
def _d_form(op: int, rt: int, ra: int, d: int) -> int:
    return (op << 26) | (rt << 21) | (ra << 16) | (d & 0xFFFF)


def _li(rd: int, simm: int) -> int:
    return _d_form(14, rd, 0, simm)


def _stw(rs: int, d: int, ra: int) -> int:
    return _d_form(36, rs, ra, d)


def _stwu(rs: int, d: int, ra: int) -> int:
    return _d_form(37, rs, ra, d)


def _xori(ra: int, rs: int, uimm: int) -> int:
    return (26 << 26) | (rs << 21) | (ra << 16) | (uimm & 0xFFFF)


def _mflr(rd: int) -> int:
    return (31 << 26) | (rd << 21) | (8 << 16) | (339 << 1)


def _mtlr(rs: int) -> int:
    return (31 << 26) | (rs << 21) | (8 << 16) | (467 << 1)


def _bc(at: int, target: int, bo: int, bi: int) -> int:
    delta = target - at
    if not -0x8000 <= delta < 0x8000 or delta & 3:
        raise ValueError(f"conditional branch from 0x{at:08X} to 0x{target:08X} is out of range")
    return (16 << 26) | (bo << 21) | (bi << 16) | (delta & 0xFFFC)


def _beq(at: int, target: int) -> int:
    return _bc(at, target, 12, 2)


def _blt(at: int, target: int) -> int:
    return _bc(at, target, 12, 0)


def _bne(at: int, target: int) -> int:
    return _bc(at, target, 4, 2)


_b = candy_box._b
_cmplwi = candy_box._cmplwi
_cmpwi = candy_box._cmpwi
_cmplw = candy_box._cmplw
_lis = candy_box._lis
_lwz = candy_box._lwz
_addi = candy_box._addi
_mr = candy_box._mr
_ha = candy_box._ha
BLR = candy_box.BLR
NOP = 0x60000000


def _chain_words(candy_box_in: bool) -> "tuple[int, int]":
    """What runs for every other item: the word the hook replaced, then the way on."""
    at = DISPATCH_ADDRESS + 0x18
    if candy_box_in:
        return (_b(at, candy_box.CAVE_ADDRESS), NOP)
    return (HOOK_VANILLA_WORD, _b(at + 4, HOOK_ADDRESS + 4))


def hook_expected_word(candy_box_in: bool) -> int:
    return _b(HOOK_ADDRESS, candy_box.CAVE_ADDRESS) if candy_box_in else HOOK_VANILLA_WORD


def cave_code(candy_box_in: bool = False) -> "list[int]":
    d = DISPATCH_ADDRESS
    r = ROUTINE_ADDRESS
    words = [
        # DISPATCH (r3 = item id, r4 = &consumed -- both passed through untouched)
        _cmplwi(3, ABILITY_PATCH_ITEM_ID),                # d+00
        _bne(d + 0x04, d + 0x18),                         # d+04
        _lis(11, _ha(USE_CONTEXT_FLAG)),                  # d+08
        _lwz(11, USE_CONTEXT_FLAG & 0xFFFF, 11),          # d+0C
        _cmpwi(11, 0),                                    # d+10
        _beq(d + 0x14, r),                                # d+14  in the field: the routine
        *_chain_words(candy_box_in),                      # d+18, d+1C
    ]
    assert len(words) * 4 == r - d
    close = r + 0x9C
    changed = r + 0x84
    words += [
        # ROUTINE (item, &consumed)
        _stwu(1, -32, 1),                                 # r+00
        _mflr(0),                                         # r+04
        _stw(0, 36, 1),                                   # r+08
        _stw(31, 28, 1),                                  # r+0C
        _stw(30, 24, 1),                                  # r+10
        _stw(29, 20, 1),                                  # r+14
        _stw(28, 16, 1),                                  # r+18
        _mr(28, 3),                                       # r+1C  item
        _mr(29, 4),                                       # r+20  &consumed
        _li(4, 1),                                        # r+24
        _b(r + 0x28, MENU_OPEN_POKEMON, link=True),       # r+28
        _mr(30, 3),                                       # r+2C  slot
        _li(31, 1),                                       # r+30  result: not used
        _cmpwi(30, 0),                                    # r+34
        _blt(r + 0x38, close),                            # r+38  cancelled
        _addi(4, 1, 8),                                   # r+3C  &pkm
        _addi(5, 1, 12),                                  # r+40  &fightPkm
        _b(r + 0x44, MENU_GET_POKEMON, link=True),        # r+44  (r3 = slot)
        _lwz(3, 8, 1),                                    # r+48
        _b(r + 0x4C, GET_ABILITY_FLAG, link=True),        # r+4C
        _mr(31, 3),                                       # r+50  old flag
        _xori(4, 3, 1),                                   # r+54
        _lwz(3, 8, 1),                                    # r+58
        _b(r + 0x5C, SET_ABILITY_FLAG, link=True),        # r+5C
        _lwz(3, 8, 1),                                    # r+60
        _b(r + 0x64, GET_ABILITY_FLAG, link=True),        # r+64
        _cmplw(3, 31),                                    # r+68
        _li(31, 1),                                       # r+6C  result: not used (li leaves cr0 alone)
        _bne(r + 0x70, changed),                          # r+70
        _lis(3, _ha(NO_EFFECT_MSG)),                      # r+74
        _addi(3, 3, NO_EFFECT_MSG & 0xFFFF),              # r+78
        _b(r + 0x7C, DISP_MSG, link=True),                # r+7C
        _b(r + 0x80, close),                              # r+80
        _mr(3, 28),                                       # r+84  changed
        _b(r + 0x88, PLAY_RECOVER_SE, link=True),         # r+88
        _b(r + 0x8C, MENU_POKEMON_UPDATE, link=True),     # r+8C
        _li(0, 1),                                        # r+90
        _stw(0, 0, 29),                                   # r+94  *consumed = 1
        _li(31, 0),                                       # r+98  result: used
        _li(3, 0),                                        # r+9C  close
        _b(r + 0xA0, OFFSCREEN_PRIORITY, link=True),      # r+A0
        _mr(3, 30),                                       # r+A4
        _b(r + 0xA8, MENU_CLOSE_POKEMON, link=True),      # r+A8
        _mr(3, 31),                                       # r+AC
        _lwz(0, 36, 1),                                   # r+B0
        _lwz(31, 28, 1),                                  # r+B4
        _lwz(30, 24, 1),                                  # r+B8
        _lwz(29, 20, 1),                                  # r+BC
        _lwz(28, 16, 1),                                  # r+C0
        _mtlr(0),                                         # r+C4
        _addi(1, 1, 32),                                  # r+C8
        BLR,                                              # r+CC
    ]
    assert words[(changed - d) // 4] == _mr(3, 28)
    assert words[(close - d) // 4] == _li(3, 0)
    assert len(words) * 4 == CODE_SIZE
    return words


def cave_original_words() -> "tuple[int, ...]":
    raw = bytes.fromhex(CAVE_ORIGINAL_HEX)
    return struct.unpack(f">{len(raw) // 4}I", raw)


def dol_patch_words(candy_box_in: bool = False) -> "tuple[tuple[int, int, int], ...]":
    """(address, vanilla, new): the cave, then the hook. All or nothing through `write_dol_words_patch`.
    `candy_box_in`: the Candy Box's main.dol patch went in first, so the hook word is its branch."""
    code = cave_code(candy_box_in)
    original = cave_original_words()
    if len(code) > len(original):
        raise AssertionError("the cave's checked words do not cover the code")
    words = [(DISPATCH_ADDRESS + 4 * i, original[i], new) for i, new in enumerate(code)]
    words.append((HOOK_ADDRESS, hook_expected_word(candy_box_in), _b(HOOK_ADDRESS, DISPATCH_ADDRESS)))
    return tuple(words)


def row_edits() -> "dict[int, bytes]":
    return {ITEM_PRICE_OFFSET: struct.pack(">H", ABILITY_PATCH_PRICE)}


def toggled_flag_byte(byte: int) -> int:
    return (byte ^ ABILITY_FLAG_BIT) & 0xFF


assert len(ABILITY_PATCH_NAME) == len(ABILITY_PATCH_VANILLA_NAME), "names are rewritten equal-length only"
assert len(TWO_ABILITY_SPECIES) == 129
assert CAVE_OFFSET >= candy_box.LEARN_END_OFFSET, "after the Candy Box's code"
assert CAVE_OFFSET + CODE_SIZE <= 0x800, "before the conditional catch (+0x800)"
assert len(cave_original_words()) * 4 >= CODE_SIZE
