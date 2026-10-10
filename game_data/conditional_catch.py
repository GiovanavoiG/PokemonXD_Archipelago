"""ADDENDUM 450 -- guaranteed catches that spare Citadark Isle / Greevil without switching the guarantee off.

Player: "Didn't we find a way to write this in memory so that these didn't break the catch rate elsewhere?"

WHY THE EXCLUSIONS USED TO COST THE GUARANTEE (ADDENDUM 416). The guarantee is the community Action Replay word at
0x80219324: `b +0x154` over `WS_BALL_THROW`'s ball-bonus `bctr`, straight to `li r28,4` (four shakes -- the path a
Master Ball takes). It fires for every throw in the game, so an exclusion could only work by leaving it off.

WHAT `WS_BALL_THROW` HOLDS AT THAT INSTRUCTION (disassembled from the retail main.dol, GXXE.map symbols):

    802192E8  pokemonIsDarkPokemon(target) ?
    802192EC    bl darkPokemonBiosGetHokakuritu   ; the Shadow's DDPK catch-rate override
    802192FC  : bl pokemonDB_GetGet                ; the species-table catch rate
    80219300/F0  mr r29,r3                         ; r29 = THE catch rate this throw uses
    80219324  bctr                                 ; ball-bonus dispatch (CTR already loaded)
    80219478  li r28,4 ; b ...                     ; the guaranteed path (+0x154)

So the guarantee can be made to follow the DATA: branch to it only when this target's catch rate is 255. Guaranteed
Catches puts every species and every Shadow at 255 -- except the records the Citadark / Greevil exclusions leave
vanilla. Those take the ordinary roll; everything else is still certain. No client, no room tracking, no RAM write
at play time: five words in a cave and one branch, all written into the ISO and checked against the vanilla words
first.

THE CAVE: the tail of `dbgMenuDbgPokemonGet` (0x80066D30, 0x864 bytes, unreferenced in retail -- the same function
`candy_box` already uses up to +0x284). +0x800 is far past that.

    +0x00  clrlwi r0,r29,24     ; r0 is dead here: the dispatch target is already in CTR
    +0x04  cmplwi r0,255
    +0x08  bne   +0x08
    +0x0C  b     0x80219478     ; the guaranteed path
    +0x10  bctr                 ; the original instruction, unchanged
"""
from __future__ import annotations

from . import candy_box

HOOK_ADDRESS = 0x80219324              # WS_BALL_THROW+0x118
HOOK_VANILLA_WORD = 0x4E800420         # bctr
GUARANTEED_PATH = 0x80219478           # WS_BALL_THROW+0x26C: li r28,4
CAVE_OFFSET = 0x800
CAVE_ADDRESS = candy_box.CAVE_ADDRESS + CAVE_OFFSET
#: The vanilla words at CAVE_ADDRESS (more of the debug menu's item grants), read off the retail main.dol.
CAVE_VANILLA_WORDS = (0x3880024E, 0x38A00001, 0x38C0FFFF, 0x480E55AD, 0x7FE3FB78)
CATCH_RATE_MAX = 0xFF


def _b(at: int, target: int) -> int:
    offset = target - at
    if not -0x2000000 <= offset < 0x2000000:
        raise ValueError(f"b from 0x{at:08X} to 0x{target:08X} is out of range")
    return 0x48000000 | (offset & 0x03FFFFFC)


def cave_words() -> "tuple[int, ...]":
    return (
        0x57A0063E,                                  # clrlwi r0,r29,24
        0x28000000 | CATCH_RATE_MAX,                 # cmplwi r0,255
        0x40820008,                                  # bne +8
        _b(CAVE_ADDRESS + 0x0C, GUARANTEED_PATH),    # b guaranteed
        HOOK_VANILLA_WORD,                           # bctr
    )


def dol_patch_words() -> "tuple[tuple[int, int, int], ...]":
    """(address, vanilla, new): the cave, then the hook. Written all or nothing by `write_dol_words_patch`."""
    words = [(CAVE_ADDRESS + 4 * i, vanilla, new)
             for i, (vanilla, new) in enumerate(zip(CAVE_VANILLA_WORDS, cave_words()))]
    words.append((HOOK_ADDRESS, HOOK_VANILLA_WORD, _b(HOOK_ADDRESS, CAVE_ADDRESS)))
    return tuple(words)


# The guaranteed path is the same one the unconditional Action Replay word reaches.
assert HOOK_ADDRESS + 0x154 == GUARANTEED_PATH
assert candy_box.LEARN_END_OFFSET <= CAVE_OFFSET and CAVE_OFFSET + 4 * len(CAVE_VANILLA_WORDS) <= candy_box.CAVE_SIZE
assert len(cave_words()) == len(CAVE_VANILLA_WORDS)
