"""Miror B. outside Kaminko's House fields his regular Pokemon at level 10 at most. His Shadows keep their levels, and
his Poke Spot fights are unchanged.

His team is built by `_fightTrainerCreateDeckUnderTaker`: a regular team off one of his Poke Spot rows, then the
Shadows that fled. Each regular member goes through `_fightTrainerCreateDeckPokemon`, which fills a `Pokemon` from
its deck row (`fightTrainerCreateFightTrainerPokemonDataIdToPokemon`), writes it back into the battle's own deck
record (`deckCreate`) and hands it to the battle party (`heroCatchPokemon`). Before the write-back, a call to a cave
checks that this member is the undertaker's regular team (the return address saved in the builder's frame is
the regular loop's) and that the current floor is the manor's yard (173), and if its level is above 10 sets it to 10
through `_pokemonSetLevelBasisStatus`, which recomputes the stats and keeps the HP full. The write-back then carries
level 10 into the record the battle uses; capping after it left the battle at the row's level.

THE CAVE: `dbgMenuMovieTest` (0x80067A24, 0x148 bytes), a debug-menu entry nothing in the retail game calls or
points to (searched in main.dol and in a live memory dump).
"""
from __future__ import annotations

HOOK_ADDRESS = 0x801FAC28                 # _fightTrainerCreateDeckPokemon+0x1CC: clrlwi r3,r25,16 (before deckCreate)
HOOK_VANILLA_WORD = 0x5723043E
CAVE_ADDRESS = 0x80067A24
CAVE_VANILLA_WORDS = (
    0x9421FFE0, 0x7C0802A6, 0x90010024, 0x93E1001C, 0x93C10018, 0x880DAB3C, 0x7C000774, 0x2C000000, 0x40820014,
    0x38600000, 0x38000001, 0x906DAB38, 0x980DAB3C, 0x3C60803C, 0x3BC00000, 0x3BE358E0, 0x48000010, 0x807F0000,
    0x4817BF99, 0x4809BA79, 0x807F0000, 0x4817C2A5,
)
REGULAR_TEAM_RETURN = 0x801FB81C          # the undertaker's regular-team loop, just after its CreateDeckPokemon call
FLOOR_GET_CURRENT = 0x801262FC
SET_LEVEL_BASIS_STATUS = 0x80143DBC       # _pokemonSetLevelBasisStatus(Pokemon*, level)
KAMINKO_FLOOR = 173
MAX_LEVEL = 10


def _rel(at: int, target: int, link: bool) -> int:
    offset = target - at
    assert -0x2000000 <= offset < 0x2000000
    return 0x48000000 | (offset & 0x03FFFFFC) | (1 if link else 0)


def _bc(at: int, target: int, bo_bi: int) -> int:
    offset = target - at
    assert -0x8000 <= offset < 0x8000
    return bo_bi | (offset & 0xFFFC)


def cave_words() -> "list[int]":
    c = CAVE_ADDRESS
    done = c + 4 * 17
    return [
        0x9421FFF0,                                          # stwu r1,-16(r1)
        0x7C0802A6,                                          # mflr r0
        0x90010014,                                          # stw r0,20(r1)
        0x80010054,                                          # lwz r0,0x54(r1): the builder frame's saved LR
        0x3C600000 | (REGULAR_TEAM_RETURN >> 16),            # lis r3,hi
        0x60630000 | (REGULAR_TEAM_RETURN & 0xFFFF),         # ori r3,r3,lo
        0x7C001840,                                          # cmplw r0,r3
        _bc(c + 4 * 7, done, 0x40820000),                    # bne done
        _rel(c + 4 * 8, FLOOR_GET_CURRENT, True),            # bl floorGetCurrent
        0x2C030000 | KAMINKO_FLOOR,                          # cmpwi r3,173
        _bc(c + 4 * 10, done, 0x40820000),                   # bne done
        0x887C0011,                                          # lbz r3,0x11(r28): level
        0x28030000 | MAX_LEVEL,                              # cmplwi r3,10
        _bc(c + 4 * 13, done, 0x40810000),                   # ble done
        0x7F83E378,                                          # mr r3,r28
        0x38800000 | MAX_LEVEL,                              # li r4,10
        _rel(c + 4 * 16, SET_LEVEL_BASIS_STATUS, True),      # bl _pokemonSetLevelBasisStatus
        HOOK_VANILLA_WORD,                                   # done: clrlwi r3,r25,16 (the instruction the hook replaced)
        0x80010014,                                          # lwz r0,20(r1)
        0x7C0803A6,                                          # mtlr r0
        0x38210010,                                          # addi r1,r1,16
        0x4E800020,                                          # blr
    ]


def dol_patch_words() -> "tuple[tuple[int, int, int], ...]":
    """(address, vanilla, new): the cave, then the hook."""
    words = [(CAVE_ADDRESS + 4 * i, vanilla, new)
             for i, (vanilla, new) in enumerate(zip(CAVE_VANILLA_WORDS, cave_words()))]
    words.append((HOOK_ADDRESS, HOOK_VANILLA_WORD, _rel(HOOK_ADDRESS, CAVE_ADDRESS, True)))
    return tuple(words)


assert len(cave_words()) == len(CAVE_VANILLA_WORDS)
