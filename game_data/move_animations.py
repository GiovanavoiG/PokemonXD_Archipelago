"""ADDENDUM 454 -- Disable Move Animations, without touching the trainer AI, and a live guard on it.

The guard re-applies the setting live, because the animations can otherwise start playing again.

WHAT +0x1E REALLY IS. ADDENDUM 291 zeroed every move's u16 at move-table +0x1E and called it the animation id. The
DOL says otherwise: +0x1E is the move's FUNCTION-DATA id (`wazaDataBiosGetWazaFuncDataId`, `lhz r3,30(r3)`), an
index into `waza_func_data` (0x803FCC88, 375 records of 24 bytes), and each record holds SIX function pointers:

    +0x00 trainer-AI value     +0x04 trainer-AI hit chance    +0x08 trainer-AI damage
    +0x0C trainer-AI damage (FightPokemon form)               +0x10 animation type   +0x14 animation variation

Record 0 is all "Null" functions. So zeroing +0x1E did switch the animations off -- and also gave every move the
AI's Null value (0), Null damage (0) and Null hit chance: the trainer AI was scoring every move as doing nothing.
The animation file itself is a third field (+0x30, `wazaDataBiosGetWazawzxdataId`).

WHAT THIS DOES INSTEAD. The move table stays vanilla (the AI's functions with it). In `waza_func_data`, every
record's two ANIMATION pointers (+0x10, +0x14) become the Null ones (`fightWazaWzxTypeFuncNull`, 0x8022C520, a bare
`blr`; `fightWazaWzxVariationFuncNull`, 0x8022C524, `li r3,0; blr`) -- exactly what record 0 gave every move before,
for the animation and nothing else. `waza_func_data` is initialised data in main.dol (RAM == the DOL's bytes in every
dump); its only writer is `wazaSetStatus`, reached from the debug menu and the script status setter, never in play.

Every word is checked before it is written: each +0x10 must be one of the 19 `fightWazaWzxTypeFunc*` functions and
each +0x14 one of the 18 `fightWazaWzxVariationFunc*` ones, and records 0 and 355 must already be Null.

THE GUARD. A Dolphin save state restores all of MEM1 -- main.dol's data and `common_rel` included -- so a state made
under an earlier build brings that build's animations (and, from a 0.1.1-era build, its zeroed +0x1E) back with it.
With the option on, the client re-reads the 750 words every few seconds and writes the Null pointers back over any
that are not, and puts +0x1E back to its vanilla value (the move's own index) wherever an old state left it 0. Both
are data, not code, so Dolphin's JIT needs no flush.

NOT COVERED: the game also plays a few effects by fixed move id straight from `fightSeqFightEffect` (weather each
turn, and similar), which load the animation file (+0x30) without asking `waza_func_data`. ADDENDUM 291 never
covered those either.
"""
from __future__ import annotations

import struct

WAZA_FUNC_DATA = 0x803FCC88
RECORD_SIZE = 24
RECORD_COUNT = 375                     # 0x2328 bytes, GXXE.map
TYPE_OFFSET = 0x10
VARIATION_OFFSET = 0x14
TYPE_NULL = 0x8022C520                 # fightWazaWzxTypeFuncNull: blr
VARIATION_NULL = 0x8022C524            # fightWazaWzxVariationFuncNull: li r3,0; blr
NULL_RECORDS = (0, 355)                # already Null in vanilla -- the anchor that proves the table

#: Every value a vanilla record holds at +0x10 / +0x14 (read off main.dol; GXXE.map names).
KNOWN_TYPE_FUNCS = frozenset((
    0x8022B88C, 0x8022BA0C, 0x8022BAF8, 0x8022BBF8, 0x8022BC74, 0x8022BCE0, 0x8022BD30, 0x8022BDF4, 0x8022BE50,
    0x8022BEEC, 0x8022BF88, 0x8022C048, 0x8022C140, 0x8022C208, 0x8022C304, 0x8022C354, 0x8022C3C0, 0x8022C46C,
    TYPE_NULL,
))
KNOWN_VARIATION_FUNCS = frozenset((
    0x8022B1F4, 0x8022B208, 0x8022B29C, 0x8022B328, 0x8022B384, 0x8022B3C0, 0x8022B3FC, 0x8022B468, 0x8022B504,
    0x8022B564, 0x8022B5C0, 0x8022B620, 0x8022B6A4, 0x8022B730, 0x8022B79C, 0x8022B7E4, 0x8022C518,
    VARIATION_NULL,
))

#: Move table (common_rel + 0xA2710, 0x38-byte entries): +0x1E, the function-data id. Vanilla value = the move's own
#: index, except the two moves with no function data at all.
MOVE_FUNC_ID_OFFSET = 0x1E
MOVES_WITHOUT_FUNC_DATA = frozenset({0, 355})


def pointer_addresses() -> "list[tuple[int, int]]":
    """(address, the Null value it must hold) for every animation pointer, in address order."""
    out = []
    for index in range(RECORD_COUNT):
        record = WAZA_FUNC_DATA + index * RECORD_SIZE
        out.append((record + TYPE_OFFSET, TYPE_NULL))
        out.append((record + VARIATION_OFFSET, VARIATION_NULL))
    return out


def dol_patch_words(current: "dict[int, int]") -> "tuple[tuple[int, int, int], ...]":
    """(address, expected, new) for `write_dol_words_patch`, from the words as they are now. Raises ValueError unless
    every word is a known animation function (or already Null) and the anchor records are Null."""
    words = []
    for address, null in pointer_addresses():
        value = current[address]
        known = KNOWN_TYPE_FUNCS if null == TYPE_NULL else KNOWN_VARIATION_FUNCS
        if value not in known:
            raise ValueError(f"0x{address:08X} holds 0x{value:08X}, which is not one of the game's animation "
                             "functions -- a different build or region")
        words.append((address, value, null))
    for index in NULL_RECORDS:
        record = WAZA_FUNC_DATA + index * RECORD_SIZE
        if (current[record + TYPE_OFFSET], current[record + VARIATION_OFFSET]) != (TYPE_NULL, VARIATION_NULL):
            raise ValueError(f"waza_func_data record {index} is not the Null record -- not this build's table")
    return tuple(words)


def table_needs_guard(block: bytes) -> "list[tuple[int, int]]":
    """For the live guard: (address, Null value) for every animation pointer in `block` (the whole table, as read
    from RAM) that is a known animation function but not Null. Anything unrecognised is left alone."""
    if len(block) < RECORD_COUNT * RECORD_SIZE:
        return []
    out = []
    for index in range(RECORD_COUNT):
        for offset, null, known in ((TYPE_OFFSET, TYPE_NULL, KNOWN_TYPE_FUNCS),
                                    (VARIATION_OFFSET, VARIATION_NULL, KNOWN_VARIATION_FUNCS)):
            value = struct.unpack_from(">I", block, index * RECORD_SIZE + offset)[0]
            if value != null and value in known:
                out.append((WAZA_FUNC_DATA + index * RECORD_SIZE + offset, null))
    return out


def anchors_ok(block: bytes) -> bool:
    """The live table is this build's: both anchor records Null, and every pointer a known animation function."""
    if len(block) < RECORD_COUNT * RECORD_SIZE:
        return False
    for index in range(RECORD_COUNT):
        t, v = struct.unpack_from(">II", block, index * RECORD_SIZE + TYPE_OFFSET)
        if t not in KNOWN_TYPE_FUNCS or v not in KNOWN_VARIATION_FUNCS:
            return False
    return all(struct.unpack_from(">II", block, i * RECORD_SIZE + TYPE_OFFSET) == (TYPE_NULL, VARIATION_NULL)
               for i in NULL_RECORDS)


def func_id_repairs(moves: bytes, entry_size: int) -> "list[tuple[int, int]]":
    """(entry offset of +0x1E within `moves`, vanilla id) for every move whose function-data id an older build's
    save state left at 0."""
    out = []
    for index in range(len(moves) // entry_size):
        if index in MOVES_WITHOUT_FUNC_DATA:
            continue
        off = index * entry_size + MOVE_FUNC_ID_OFFSET
        if struct.unpack_from(">H", moves, off)[0] == 0:
            out.append((off, index))
    return out


assert len(KNOWN_TYPE_FUNCS) == 19 and len(KNOWN_VARIATION_FUNCS) == 18


# THE ORIGINAL POINTERS, for turning the animations back on live (`/animations on`). One record per 4 digits: the
# index of its +0x10 function in sorted KNOWN_TYPE_FUNCS, then of its +0x14 function in sorted KNOWN_VARIATION_FUNCS.
_TYPE_ORDER = tuple(sorted(KNOWN_TYPE_FUNCS))
_VARIATION_ORDER = tuple(sorted(KNOWN_VARIATION_FUNCS))
_VANILLA_CODES = (
    "1817171617161716171617161716171617161716171617161716151614161716171617161716151617161716171617161716"
    "1716171617161716171617161716171617161716171617161716171607161716171617160716171607161716171617161716"
    "1716171617161716101617161716171617161716171617161716171617161716171617151716161417161316131617161416"
    "1716151617161716171617161716171617161716171617161716171617161716151617161716171617161416141617161716"
    "1416171612161716141614161416141617161716141614161416101614161016141615160716181709161716171617161716"
    "1716171617161716171615161716171614160716141617160716121617161716131617161516021617161716171617161716"
    "0716141617160916171617161416171617161416141617161716171601161716121617131716171617161716171617160916"
    "1716141617161716171617161716141617160716171617160716171617161716111617161716141609161716141617161716"
    "1716071613161416071616121716171614161716171117161716171607161016161016091608101608161716160717161716"
    "1716141617161600171617161716171617161406140614061716171617160716071617161716141617161716171607161716"
    "1716171617161716141617051404171607161716171617161716171617161716141618171416171606161216071605161416"
    "1416171604161416171603031716171617161716121600161416071614161716151617161416141617161716171607161716"
    "1416170217161416171617161716171617161716171617011016071617161716171617161716171617161716071617161716"
    "1716171617161716171617161716171617161416171614161716171614161516171617161716171617160716141617161416"
    "1716171617160716171618171716171617161716171617161716171617161716171607161716171617161716111617161817"
)


def vanilla_pointers() -> "list[tuple[int, int]]":
    """(type function, variation function) for each of the RECORD_COUNT records, as the game ships them."""
    out = []
    for index in range(RECORD_COUNT):
        code = _VANILLA_CODES[index * 4: index * 4 + 4]
        out.append((_TYPE_ORDER[int(code[:2])], _VARIATION_ORDER[int(code[2:])]))
    return out


def table_needs_restore(block: bytes) -> "list[tuple[int, int]]":
    """(address, original value) for every animation pointer in `block` that is not the game's own. Only a known
    animation function is ever replaced, so a table this build does not recognise is left alone."""
    if len(block) < RECORD_COUNT * RECORD_SIZE:
        return []
    out = []
    for index, (type_func, variation_func) in enumerate(vanilla_pointers()):
        for offset, want, known in ((TYPE_OFFSET, type_func, KNOWN_TYPE_FUNCS),
                                    (VARIATION_OFFSET, variation_func, KNOWN_VARIATION_FUNCS)):
            value = struct.unpack_from(">I", block, index * RECORD_SIZE + offset)[0]
            if value != want and value in known:
                out.append((WAZA_FUNC_DATA + index * RECORD_SIZE + offset, want))
    return out


assert len(_VANILLA_CODES) == RECORD_COUNT * 4
assert all(vanilla_pointers()[i] == (TYPE_NULL, VARIATION_NULL) for i in NULL_RECORDS)
