"""ADDENDUM 427 (2026-10-06) -- Reduce Citadark Grind: a Rare Candy for 1 and the CANDY BOX.

Player: "Add an option called "reduce_citadark_grind" that makes one of the gateon expansion items a guaranteed
rebuyable rare candy that costs only 1 dollar. ... investigate making a NEW ITEM (Candy Box), or repurposing one,
that allows you to level up a pokemon X amount of times - see if we can make it apply multiple rare candies at
once using the rare candy's function, to save time. If you can't make a prompt, make it put the pokemon to level
100 OR 99 if it needs to evolve twice, so it can still evolve from levelup."

THE SHELF. Gateon Port Shop's last tier (mart 15, after Gorigan) introduces lines 12-15. Line 15 (Full Restore in
vanilla) becomes a real Rare Candy and line 14 (Max Potion) the Candy Box. Both are ordinary mart lines, so both
are rebuyable forever, and both cost 1. Lines 7-15 were already filler-only (ADDENDUM 387), so taking two of
them costs the seed nothing a seed needs.

THE CANDY BOX is the YELLOW SHARD (item 50), which XD carries over from Ruby/Sapphire with no use and no source.
Three edits make it a Rare Candy that lands on the right level:

  1. common_rel's Items table: its effect-param byte (+0x04) becomes the Rare Candy's (0x25, the param with
     the level-up flag), its price (+0x06) 1, its friendship bytes (+0x24..+0x26) the Rare Candy's 5/3/2, and
     its name "CANDY BOX". Its field-use function pointer (+0x1C) is a REL relocation, so it is NOT edited --
     it stays `0x800A60B4`, the shared "can't use that" handler.

  2. main.dol, that handler's first instruction (`stwu r1,-16(r1)`) becomes a branch to a dispatcher: for the
     Candy Box, in the field, it tail-branches to `menuUseItemListLVUp` -- the Rare Candy's own use routine,
     so the party menu, the stat window, move learning and the evolution check are all the game's. In battle
     (`_getUseFunc`'s own flag at 0x804282E8 is non-zero there) and for every other item it runs the original
     instruction and carries on, so nothing else changes.

  3. main.dol, inside `itemUse2Pokemon`'s level-up branch, `addi r0,r22,1` (new level = old + 1) becomes a call
     that returns old + 1 for every item but the Candy Box, and for the Candy Box the larger of old + 1 and the
     species' target from a 415-byte table: 100, or 99 for every species that can still evolve (ADDENDUM 451;
     it was the 25 with TWO level-up evolutions ahead). The routine then sets the experience for that level, recomputes the stats, and
     `menuUseItemListLVUp` runs one evolution check -- so a Charmander goes to 99 and evolves to Charmeleon,
     and one more Candy Box (or Rare Candy) takes it to 100 and Charizard. ADDENDUM 440: every level-up move
     it passed is offered, in level order, through the game's own learn prompt -- see `learn_code`.

The dispatcher, the level helper and the table sit in `dbgMenuDbgPokemonGet` (0x80066D30, 0x864 bytes): a
debug-menu routine that gives the hero a fixed debug party. Nothing in main.dol branches to it, loads its
address or stores it as data -- it is reachable only from the debug menu, which retail never opens. The patch
checks every original word it replaces, so a different build is refused rather than corrupted.

No quantity prompt: XD's party-menu item flow has no number entry for a use, and building one is a UI the game
does not have. The fallback the player named is what ships.
"""
from __future__ import annotations

import struct

RARE_CANDY_ITEM_ID = 68
RARE_CANDY_NAME_ID = 5057
CANDY_BOX_ITEM_ID = 50
CANDY_BOX_NAME_ID = 5050
CANDY_BOX_VANILLA_NAME = "YELLOW SHARD"
CANDY_BOX_NAME = "CANDY BOX"
#: Both cost 1, per the request.
GRIND_PRICE = 1

#: Items-table row offsets (0x28-byte rows; ADDENDUM 304's layout plus `itemDataBios*` accessors in the DOL).
ITEM_EFFECT_PARAM_OFFSET = 0x04       # itemDataBiosGetItemEffectParam: lbz +4
ITEM_PRICE_OFFSET = 0x06              # u16
ITEM_FRIENDSHIP_OFFSET = 0x24         # itemDataBiosGetUseFriend: three signed bytes
RARE_CANDY_EFFECT_PARAM = 0x25
RARE_CANDY_FRIENDSHIP = bytes((5, 3, 2))


def rare_candy_row_edits() -> "dict[int, bytes]":
    return {ITEM_PRICE_OFFSET: struct.pack(">H", GRIND_PRICE)}


def candy_box_row_edits() -> "dict[int, bytes]":
    return {
        ITEM_EFFECT_PARAM_OFFSET: bytes((RARE_CANDY_EFFECT_PARAM,)),
        ITEM_PRICE_OFFSET: struct.pack(">H", GRIND_PRICE),
        ITEM_FRIENDSHIP_OFFSET: RARE_CANDY_FRIENDSHIP,
    }


# --- the shelf ----------------------------------------------------------------------------------------------
GATEON_SHOP = "Gateon Port Shop"
GATEON_FINAL_MART = 15
#: line -> (the vanilla item that line sells in mart 15, what it sells now)
GATEON_GRIND_LINES: "dict[int, tuple[int, int]]" = {
    15: (19, RARE_CANDY_ITEM_ID),     # Full Restore -> Rare Candy
    14: (20, CANDY_BOX_ITEM_ID),      # Max Potion   -> Candy Box
}
RARE_CANDY_LINE = 15
CANDY_BOX_LINE = 14

#: What the client writes over the Candy Box's description while the Gateon shelf is open. The patch cannot
#: rewrite `pocket_menu.msg` in place (its entry has 29 bytes of slack), so outside a shop the Bag shows the
#: Yellow Shard's own "An item brought over from a faraway place."
CANDY_BOX_DESCRIPTION_LINES = ["Raises a POK\u00e9MON", "to Lv. 100 at once."]
#: ADDENDUM 456: the `equal_to_citadark_entry` wording (the level itself is only known to the patcher).
CANDY_BOX_CITADARK_DESCRIPTION_LINES = ["Raises a POK\u00e9MON", "to Citadark's level."]
#: Reduce Citadark Grind's values (options.ReduceCitadarkGrind).
GRIND_OFF, GRIND_ON, GRIND_CITADARK_ENTRY = 0, 1, 2
#: (offset in pocket_menu.msg, byte budget, description id) -- read out of the Gateon shop-menu dump.
CANDY_BOX_DESCRIPTION_ENTRY = (0x0023CD, 88, 10050)


# --- the level table ----------------------------------------------------------------------------------------
SPECIES_COUNT = 415
#: Internal species ids with two LEVEL-UP evolutions still ahead (methods 4 and 8-13: level, the Tyrogue stat
#: compares, Wurmple's personality split, Nincada), read off XD's own species table in a RAM dump and re-checked
#: against it by the test whenever the dump is on disk. Bulbasaur/Charmander/Squirtle, Caterpie/Weedle/Pidgey,
#: Dratini, the Johto and Hoenn starters, Mareep, Hoppip, Larvitar, Wurmple, Trapinch, Spheal, Slakoth, Whismur,
#: Aron, Ralts, Bagon, Beldum.
TWO_STAGE_LEVEL_EVOLVERS: "tuple[int, ...]" = (
    1, 4, 7, 10, 13, 16, 147, 152, 155, 158, 179, 187, 246, 277, 280, 283, 290, 332, 341, 364, 370, 382, 392,
    395, 398,
)
LEVEL_EVOLUTION_METHODS = frozenset({4, 8, 9, 10, 11, 12, 13})
#: ADDENDUM 429: the same list as `trade_evolutions.NEW_TWO_STAGE_LEVEL_EVOLVERS` (a test holds them equal), kept
#: here so this module stays import-free for the standalone patcher.
TRADE_BY_LEVEL_TWO_STAGE: "tuple[int, ...]" = (60, 63, 66, 74, 92, 116)


#: ADDENDUM 451. Player: "i used candy box on azurill, and it went to 100, not leaving space for azumarill. Ensure
#: that they never go above 99 if they have another evolution left using candy box." Every internal species with at
#: least one evolution entry in XD's own species table (any method -- level, stone, trade, friendship, key item),
#: read off a RAM dump and re-checked against it by the test. 172 of 415. Trade and friendship evolutions becoming
#: level-ups changes no species' membership, so one list serves every option.
EVOLVES_FURTHER: "tuple[int, ...]" = (
    1, 2, 4, 5, 7, 8, 10, 11, 13, 14, 16, 17, 19, 21, 23, 25, 27, 29, 30, 32, 33, 35, 37, 39, 41, 42, 43, 44, 46,
    48, 50, 52, 54, 56, 58, 60, 61, 63, 64, 66, 67, 69, 70, 72, 74, 75, 77, 79, 81, 84, 86, 88, 90, 92, 93, 95, 96,
    98, 100, 102, 104, 109, 111, 113, 116, 117, 118, 120, 123, 129, 133, 137, 138, 140, 147, 148, 152, 153, 155,
    156, 158, 159, 161, 163, 165, 167, 170, 172, 173, 174, 175, 177, 179, 180, 183, 187, 188, 191, 194, 204, 209,
    216, 218, 220, 223, 228, 231, 236, 238, 239, 240, 246, 247, 277, 278, 280, 281, 283, 284, 286, 288, 290, 291,
    293, 295, 296, 298, 299, 301, 304, 306, 309, 311, 313, 315, 318, 323, 326, 328, 330, 332, 333, 335, 337, 339,
    341, 342, 344, 346, 350, 351, 356, 358, 360, 361, 364, 365, 367, 370, 371, 373, 377, 382, 383, 388, 390, 392,
    393, 395, 396, 398, 399,
)


def target_level_table(trade_by_level: bool = False, entry_level: "int | None" = None) -> bytes:
    """One byte per internal species: the level a Candy Box takes it to. ADDENDUM 451: 99 for every species that can
    still evolve, by any method, so the evolution it has left -- and any after it -- always has a level to happen on;
    100 only for a final stage. `trade_by_level` no longer changes the table (kept for the callers' signature).

    ADDENDUM 456: `entry_level` (Reduce Citadark Grind's `equal_to_citadark_entry`) caps every entry at that level --
    the lowest level of any Pokemon on a Citadark Isle trainer, read off the patched ISO. A Pokemon already at or above
    it gets the helper's floor of one level, exactly like a Rare Candy."""
    table = bytearray([100] * SPECIES_COUNT)
    for species in EVOLVES_FURTHER:
        table[species] = 99
    if entry_level is not None:
        if not 1 <= int(entry_level) <= 100:
            raise ValueError(f"Citadark entry level {entry_level} is outside 1-100")
        table = bytearray(min(t, int(entry_level)) for t in table)
    return bytes(table)


# --- the main.dol patch -------------------------------------------------------------------------------------
CAVE_ADDRESS = 0x80066D30                 # dbgMenuDbgPokemonGet, 0x864 bytes, unreferenced in retail
CANT_USE_HANDLER = 0x800A60B4             # the shared field/battle "can't use" handler (items 42-51, 111, ...)
CANT_USE_HANDLER_FIRST_WORD = 0x9421FFF0  # stwu r1,-16(r1)
LVUP_HANDLER = 0x800A5994                 # menuUseItemListLVUp -- the Rare Candy's field-use routine
LEVEL_STEP_ADDRESS = 0x8015FD50           # itemUse2Pokemon: addi r0,r22,1
LEVEL_STEP_WORD = 0x38160001
#: `_getUseFunc`'s field/battle switch: 0 in the field, non-zero in battle.
USE_CONTEXT_FLAG = 0x804282E8

DISPATCH_OFFSET = 0x00
LEVEL_HELPER_OFFSET = 0x24
TABLE_OFFSET = 0x58

#: The vanilla words the patch replaces at CAVE_ADDRESS, in order. Checked before anything is written.
CAVE_ORIGINAL_HEX = (
    "9421ff207c0802a6900100e493e100dc38600000388000024816826d7c601b78386000007c1f037838800001480f186d"
    "7c661b78386100083880008738a00028480da6357fe3fb783881000838a0000038c0000438e00001480e61d538810008"
    "38600000481cdf613860000038800001480f18297c661b78386100083880008638a00028480da5f17fe3fb7838810008"
    "38a0000038c0000438e00001480e61913881000838600000481cdf1d3860000038800001480f17e57c661b7838610008"
    "3880016138a00064480da5ad3861000838800040480d82097fe3fb783881000838a0000038c0000438e00001480e6141"
    "3860000038800001480f17a17c661b78386100083880016238a00064480da569386100083880004d480d81c57fe3fb78"
    "3881000838a0000038c0000438e00001480e60fd3860000038800001480f175d7c661b7838610008388000ac38a00064"
    "480da525386100083880004c480d81817fe3fb783881000838a0000038c0000438e00001480e60b93860000038800001"
    "480f17197c661b7838610008388000fa38a00064480da4e1386100083880001d480d813d7fe3fb783881000838a00000"
    "38c0000438e00001480e60757fe3fb783880000138a0006338c0ffff480e5bed7fe3fb783880000238a0006338c0ffff"
    "480e5bd97fe3fb783880000338a0006338c0ffff480e5bc5"
)


# A minimal Gekko encoder -- only the forms this patch uses, each checked by the test against a disassembler.
def _addi(rd: int, ra: int, simm: int) -> int:
    return (14 << 26) | (rd << 21) | (ra << 16) | (simm & 0xFFFF)


def _lis(rd: int, imm: int) -> int:
    return (15 << 26) | (rd << 21) | (imm & 0xFFFF)


def _cmplwi(ra: int, uimm: int) -> int:
    return (10 << 26) | (ra << 16) | (uimm & 0xFFFF)


def _cmpwi(ra: int, simm: int) -> int:
    return (11 << 26) | (ra << 16) | (simm & 0xFFFF)


def _cmplw(ra: int, rb: int) -> int:
    return (31 << 26) | (ra << 16) | (rb << 11) | (32 << 1)


def _lwz(rd: int, d: int, ra: int) -> int:
    return (32 << 26) | (rd << 21) | (ra << 16) | (d & 0xFFFF)


def _lhz(rd: int, d: int, ra: int) -> int:
    return (40 << 26) | (rd << 21) | (ra << 16) | (d & 0xFFFF)


def _lbzx(rd: int, ra: int, rb: int) -> int:
    return (31 << 26) | (rd << 21) | (ra << 16) | (rb << 11) | (87 << 1)


def _mr(ra: int, rs: int) -> int:
    return (31 << 26) | (rs << 21) | (ra << 16) | (rs << 11) | (444 << 1)


def _b(at: int, target: int, link: bool = False) -> int:
    delta = target - at
    if not -0x2000000 <= delta < 0x2000000 or delta & 3:
        raise ValueError(f"branch from 0x{at:08X} to 0x{target:08X} is out of range")
    return (18 << 26) | (delta & 0x03FFFFFC) | (1 if link else 0)


def _bne(at: int, target: int) -> int:
    delta = target - at
    if not -0x8000 <= delta < 0x8000 or delta & 3:
        raise ValueError(f"conditional branch from 0x{at:08X} to 0x{target:08X} is out of range")
    return (16 << 26) | (4 << 21) | (2 << 16) | (delta & 0xFFFC)


def _bclr_false(cr_bit: int) -> int:
    """Return when cr0 bit `cr_bit` is CLEAR: bit 2 (eq) -> bnelr, 0 (lt) -> bgelr, 1 (gt) -> blelr."""
    return (19 << 26) | (4 << 21) | (cr_bit << 16) | (16 << 1)


BLR = 0x4E800020


def _ha(value: int) -> int:
    return ((value + 0x8000) >> 16) & 0xFFFF


def cave_code() -> "list[int]":
    """The dispatcher and the level helper, as words, laid out from CAVE_ADDRESS."""
    base = CAVE_ADDRESS
    table = base + TABLE_OFFSET
    orig = base + 0x1C
    words = [
        # dispatch (r3 = item id, r4 = the caller's pointer -- both passed through untouched)
        _cmplwi(3, CANDY_BOX_ITEM_ID),                    # +00
        _bne(base + 0x04, orig),                          # +04
        _lis(11, _ha(USE_CONTEXT_FLAG)),                  # +08
        _lwz(11, USE_CONTEXT_FLAG & 0xFFFF, 11),          # +0C
        _cmpwi(11, 0),                                    # +10
        _bne(base + 0x14, orig),                          # +14  in battle: the original handler
        _b(base + 0x18, LVUP_HANDLER),                    # +18  the Rare Candy's routine, as a tail call
        CANT_USE_HANDLER_FIRST_WORD,                      # +1C  orig: the instruction the hook replaced
        _b(base + 0x20, CANT_USE_HANDLER + 4),            # +20
        # level helper (r22 = old level, r26 = item id, r31 = Pokemon*; r3 must survive)
        _addi(0, 22, 1),                                  # +24  the instruction the hook replaced
        _cmplwi(26, CANDY_BOX_ITEM_ID),                   # +28
        _bclr_false(2),                                   # +2C  bnelr
        _lhz(11, 0, 31),                                  # +30  species
        _cmplwi(11, SPECIES_COUNT),                       # +34
        _bclr_false(0),                                   # +38  bgelr: outside the table, plain +1
        _lis(12, _ha(table)),                             # +3C
        _addi(12, 12, table & 0xFFFF),                    # +40
        _lbzx(11, 12, 11),                                # +44  target level
        _cmplw(11, 0),                                    # +48
        _bclr_false(1),                                   # +4C  blelr: never fewer than +1
        _mr(0, 11),                                       # +50
        BLR,                                              # +54
    ]
    assert len(words) * 4 == TABLE_OFFSET
    return words


def cave_bytes(trade_by_level: bool = False, entry_level: "int | None" = None) -> bytes:
    table = target_level_table(trade_by_level, entry_level)
    table += b"\x00" * (-len(table) % 4)
    out = b"".join(struct.pack(">I", w) for w in cave_code()) + table
    assert len(out) == LEARN_OFFSET
    return out + b"".join(struct.pack(">I", w) for w in learn_code())


# --- ADDENDUM 440: every level-up move the Candy Box passes -----------------------------------------------------
# Player: "any chance we can make the candy box allow us to learn the level up moves we pass?"
#
# `menuUseItemListLVUp` (the Rare Candy's field routine, which the Candy Box runs) learns moves after the level-up
# with one loop: `level = pokemonBiosGetLevel(pkm)`, then `pokemonGetOboeWazaDataId(pkm, level, &cursor)` hands
# back each learnset move at EXACTLY that level, and each one the Pokemon does not know goes through
# `evolutionWazaLearn` -- the game's own "wants to learn ... forget a move?" prompt -- and `pokemonWazaCreate`.
# A Rare Candy passes one level, so that is every move it passed. A Candy Box passes up to 99.
#
# Three hooks turn the one level into the range (old level + 1 .. new level), with the loop body untouched:
#   A  0x800A59F0  `bl getPokemonLvupStatus` (before `itemUse2Pokemon`) -> a wrapper that also records the OLD level
#   B  0x800A5B10  `bl pokemonBiosGetLevel` (the loop's level)          -> old + 1 (the new level if nothing was saved)
#   C  0x800A5B9C  `bne loop` (no more moves at this level)             -> next level until the new one, then on to
#                                                                          the evolution check as before
# For a Rare Candy old + 1 IS the new level, so its behaviour is byte-for-byte the game's. The routines and the
# saved level sit after the level table, still inside `dbgMenuDbgPokemonGet`.
LEARN_OFFSET = 0x1F8
OLD_LEVEL_OFFSET = LEARN_OFFSET            # one word: the level before the item
LEARN_WRAP_OFFSET = LEARN_OFFSET + 0x04    # hook A's target
LEARN_START_OFFSET = LEARN_OFFSET + 0x38   # hook B's target
LEARN_NEXT_OFFSET = LEARN_OFFSET + 0x60    # hook C's target
LEARN_END_OFFSET = LEARN_OFFSET + 0x8C
CAVE_SIZE = 0x864

LVUP_STATUS_ADDRESS = 0x800A59F0           # menuUseItemListLVUp+0x5C: bl getPokemonLvupStatus
LVUP_STATUS_WORD = 0x4BFFFDD1
GET_LVUP_STATUS = 0x800A57C0               # getPokemonLvupStatus__FP16MENU_LVUP_STATUSP7Pokemon
LEARN_LEVEL_ADDRESS = 0x800A5B10           # menuUseItemListLVUp+0x17C: bl pokemonBiosGetLevel
LEARN_LEVEL_WORD = 0x480A1495
LEARN_LOOP_ADDRESS = 0x800A5B9C            # menuUseItemListLVUp+0x208: bne (loop body at +0x190)
LEARN_LOOP_WORD = 0x4082FF88
LEARN_LOOP_BODY = 0x800A5B24               # the "already known?" check for the move just found
LEARN_LOOP_CALL = 0x800A5B80               # pokemonGetOboeWazaDataId(pkm, r28, &cursor)
LEARN_LOOP_DONE = 0x800A5BA0               # the evolution check after the loop
POKEMON_LEVEL_OFFSET = 0x11                # pokemonBiosGetLevel: lbz r3,17(r3)

#: The vanilla bytes at CAVE_ADDRESS + LEARN_OFFSET the routines replace (more of the debug party's item grants).
LEARN_ORIGINAL_HEX = (
    "7fe3fb783880000438a0006338c0ffff480e5bb17fe3fb783880000538a0006338c0ffff480e5b9d7fe3fb783880000638a00063"
    "38c0ffff480e5b897fe3fb783880000738a0006338c0ffff480e5b757fe3fb783880000838a0006338c0ffff480e5b617fe3fb78"
    "3880000938a0006338c0ffff480e5b4d7fe3fb783880000a38a0006338c0ffff480e5b39"
)


def _stwu(rs: int, d: int, ra: int) -> int:
    return (37 << 26) | (rs << 21) | (ra << 16) | (d & 0xFFFF)


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


def _blt(at: int, target: int) -> int:
    return _bc(at, target, 12, 0)


MFLR_R0 = 0x7C0802A6
MTLR_R0 = 0x7C0803A6


def _lo(value: int) -> int:
    return value & 0xFFFF


def learn_code() -> "list[int]":
    """The saved level, then routines A, B and C, laid out from CAVE_ADDRESS + LEARN_OFFSET."""
    from_ = CAVE_ADDRESS
    old = from_ + OLD_LEVEL_OFFSET
    a = from_ + LEARN_WRAP_OFFSET
    b = from_ + LEARN_START_OFFSET
    c = from_ + LEARN_NEXT_OFFSET
    words = [0]                                                    # the old level, 0 = none recorded
    words += [                                                     # A: getPokemonLvupStatus(r3, r4), then save
        MFLR_R0,                                                   #    r4's level
        _stwu(1, -16, 1),
        _stw(0, 20, 1),
        _stw(4, 8, 1),                                             # the Pokemon
        _b(a + 0x10, GET_LVUP_STATUS, link=True),
        _lwz(3, 8, 1),
        _lbz(3, POKEMON_LEVEL_OFFSET, 3),
        _lis(11, _ha(old)),
        _stw(3, _lo(old), 11),
        _lwz(0, 20, 1),
        _addi(1, 1, 16),
        MTLR_R0,
        BLR,
    ]
    assert len(words) * 4 == LEARN_START_OFFSET - LEARN_OFFSET
    words += [                                                     # B: r3 = Pokemon -> the first level to learn at
        _lbz(4, POKEMON_LEVEL_OFFSET, 3),                          #    r4 = the new level
        _lis(11, _ha(old)),
        _lwz(3, _lo(old), 11),
        _cmplwi(3, 0),
        _beq(b + 0x10, b + 0x20),                                  #    nothing saved: the new level, as vanilla
        _addi(3, 3, 1),                                            #    old + 1
        _cmplw(3, 4),
        _bclr_false(1),                                            #    blelr: old + 1 <= new
        _mr(3, 4),
        BLR,
    ]
    assert len(words) * 4 == LEARN_NEXT_OFFSET - LEARN_OFFSET
    words += [                                                     # C: cr0 = "no move left at this level"
        _beq(c + 0x00, c + 0x08),
        _b(c + 0x04, LEARN_LOOP_BODY),                             #    a move: the loop body, as vanilla
        _lwz(3, 20, 1),                                            #    the caller's Pokemon
        _lbz(4, POKEMON_LEVEL_OFFSET, 3),
        _cmplw(28, 4),
        _blt(c + 0x14, c + 0x1C),
        _b(c + 0x18, LEARN_LOOP_DONE),                             #    at the new level: on to evolution
        _addi(28, 28, 1),                                          #    next level, cursor back to 0
        _addi(0, 0, 0),                                            #    li r0,0
        _stb(0, 8, 1),
        _b(c + 0x28, LEARN_LOOP_CALL),
    ]
    assert len(words) * 4 == LEARN_END_OFFSET - LEARN_OFFSET
    assert LEARN_END_OFFSET <= CAVE_SIZE
    return words


def dol_patch_words(trade_by_level: bool = False,
                    entry_level: "int | None" = None) -> "tuple[tuple[int, int, int], ...]":
    """(address, expected vanilla word, new word) for every word the Candy Box changes in main.dol."""
    new = cave_bytes(trade_by_level, entry_level)
    original = bytes.fromhex(CAVE_ORIGINAL_HEX + LEARN_ORIGINAL_HEX)
    if len(new) != len(original):
        raise AssertionError(f"cave is {len(new)} bytes but {len(original)} original bytes are recorded")
    words = [
        (CAVE_ADDRESS + i, struct.unpack_from(">I", original, i)[0], struct.unpack_from(">I", new, i)[0])
        for i in range(0, len(new), 4)
    ]
    words.append((CANT_USE_HANDLER, CANT_USE_HANDLER_FIRST_WORD, _b(CANT_USE_HANDLER, CAVE_ADDRESS + DISPATCH_OFFSET)))
    words.append((LEVEL_STEP_ADDRESS, LEVEL_STEP_WORD,
                  _b(LEVEL_STEP_ADDRESS, CAVE_ADDRESS + LEVEL_HELPER_OFFSET, link=True)))
    # ADDENDUM 440: the three move-learning hooks.
    words.append((LVUP_STATUS_ADDRESS, LVUP_STATUS_WORD,
                  _b(LVUP_STATUS_ADDRESS, CAVE_ADDRESS + LEARN_WRAP_OFFSET, link=True)))
    words.append((LEARN_LEVEL_ADDRESS, LEARN_LEVEL_WORD,
                  _b(LEARN_LEVEL_ADDRESS, CAVE_ADDRESS + LEARN_START_OFFSET, link=True)))
    words.append((LEARN_LOOP_ADDRESS, LEARN_LOOP_WORD, _b(LEARN_LOOP_ADDRESS, CAVE_ADDRESS + LEARN_NEXT_OFFSET)))
    return tuple(words)
