"""ADDENDUM 465 -- what the engine does with a trainer's Shadow Pokemon, and the two places this project fell short.

The hypothesis checked here: trainers with Shadows carry a marker saying which of their Pokemon are Shadows, and a
marker left unset on generated Shadows would explain them respawning infinitely. Below: the marker, the real cause
of the respawn, and the engine's other Shadow behaviours.

THE MARKER IS SET. A trainer row (DTNR) marks its Shadow slots with `shadowMask` at +0x04 (bit i = slot i is a DDPK
index), and `write_shadow_multi_trainer_patch` sets the bit for every slot it fills. The Shadow record (DDPK) marks
itself with +0x03 bit 7, which the engine reads as `DeckDarkPokemon::isScenarioPokemon` (0x8028B9B8); the expansion
writes 0x80 there, the value every vanilla record carries. Neither is why a Shadow comes back.

WHY A SNAGGED SHADOW COMES BACK. Each Shadow has a 0x48-byte record in the save, one per DDPK index (all 128 --
`darkPokemonGetDarkPokemon` bounds-checks 128, `deckInitDarkPokemon` fills 128). Its status (byte 0, bits 5-7) is set
to 2 when the player wins and the Shadow flees to Miror B (`_darkPokemonSetUnderTaker`) and 3 when it is snagged
(`fightActionFlowSyuuryou`); 4 is purified. Building a trainer's team, `_fightTrainerCreateDeckPokemon` (0x801FAA5C)
looks at that status for each Shadow slot, and when it is 2 or more:

    fight mode 1            -> the slot is skipped
    swap mode 1             -> the slot is taken from a swap deck (or skipped when the swap deck is 0)
    neither                 -> the Shadow is built again

Fight mode and swap mode are NOT on the trainer. They are FIGHT_ENCOUNT fields (+0x10, +0x0D, swap deck +0x0E) that
a room script sets with its fight command (`AppScript::cmpFight`) just before the battle, and every fight clears them
to 0. The game never needed them for an ordinary trainer, because no ordinary trainer with a Shadow is fought twice.
This project puts Shadows on trainers that are (re-fightable ones the census missed, Miror B's own teams), and there
the third line rebuilds the Shadow from its deck record -- a fresh, snaggable copy on every rematch.

THE FIX (`RESPAWN_FIX_WORDS`), five words in place, no cave: the same decisions in a different order, with one new
outcome. A Shadow with status 2 (fled to Miror B) and no script mode is still built, exactly as before -- that is how
Miror B fields the Shadows that ran from you (`_fightTrainer_GetUnderTakerDarkPoke` builds them through this same
routine), and it must not change. (ADDENDUM 468, below, narrows that to Miror B.'s own builders.) A Shadow with status 3 or 4 (snagged or purified) and no script mode now falls into
the swap branch, whose swap deck is 0 (cleared every fight), and is skipped -- what fight mode 1 already does in the
vanilla game. Fight mode 1 and swap mode 1 behave exactly as before.

    0x801FAAF0  cmpwi r3,2        status < 2 -> build (unchanged)
    0x801FAAF4  blt   build       (unchanged)
    0x801FAAF8  cmplwi r19,1      fight mode 1 ...  (unchanged)
    0x801FAAFC  beq   skip           ... -> skip               was: bne -> the swap-mode test
    0x801FAB00  cmplwi r18,1      swap mode 1 ...               was: li r3,1
    0x801FAB04  beq   swap           ... -> the swap block     was: b end
    0x801FAB08  cmpwi r3,2        fled to Miror B ...           was: cmplwi r18,1
    0x801FAB0C  beq   build          ... -> build, as vanilla   was: bne build
    0x801FAB10  (swap block)      snagged/purified: swap deck 0 -> skip

r3 still holds the status at 0x801FAB08: nothing between the status call and there writes it.

THE SECOND GAP: `darkPokemonList` (0x804044E8, 128 u16). At new game `deckInitDarkPokemon` stamps every save record's
Pokemon id from this main.dol table, one entry per DDPK index -- for all 83 vanilla Shadows it is exactly the species
of the Shadow's DPKM record (measured against the real decks, 83/83). Entries 84-127, the slots Shadow Pokemon
Expansion fills, all read 280 (Torchic), and a Shadow whose species was randomized keeps its vanilla entry. The record's
id is what the PDA's Shadow Monitor lists, names and sorts by, and what the `cmpDarkPokemon` script command reports. So
`dark_pokemon_list_words` rewrites the table from the FINAL disc: every in-use DDPK record's species. New game only --
an existing save keeps the ids it was started with.
"""
from __future__ import annotations

import struct

RESPAWN_FIX_WORDS: "tuple[tuple[int, int, int], ...]" = (
    (0x801FAAFC, 0x4082000C, 0x4182001C),   # bne +0xC (-> swap-mode test)   -> beq skip (0x801FAB18)
    (0x801FAB00, 0x38600001, 0x28120001),   # li r3,1                        -> cmplwi r18,1
    (0x801FAB04, 0x48000170, 0x4182000C),   # b end                          -> beq swap block (0x801FAB10)
    (0x801FAB08, 0x28120001, 0x2C030002),   # cmplwi r18,1                   -> cmpwi r3,2
    (0x801FAB0C, 0x40820038, 0x41820038),   # bne build                      -> beq build (0x801FAB44)
)
#: The untouched neighbours the five words are reasoned against; asserted by the test on the real main.dol.
RESPAWN_CONTEXT_WORDS: "dict[int, int]" = {
    0x801FAAEC: 0x4BF50809,   # bl DarkPokemon::getStatus
    0x801FAAF0: 0x2C030002,   # cmpwi r3,2
    0x801FAAF4: 0x41800050,   # blt build (0x801FAB44)
    0x801FAAF8: 0x28130001,   # cmplwi r19,1   (fight mode)
    0x801FAB10: 0x56FA043F,   # clrlwi. r26,r23,16   (swap deck number)
    0x801FAB14: 0x4082000C,   # bne swap-from-deck
    0x801FAB18: 0x38600001,   # li r3,1   (skip)
    0x801FAB1C: 0x48000158,   # b end
}

DARK_POKEMON_LIST_ADDRESS = 0x804044E8
DARK_POKEMON_LIST_LENGTH = 128
PLACEHOLDER_SPECIES = 280      # what entries 84-127 hold in the shipped game (internal 280, Torchic)

VANILLA_DARK_POKEMON_LIST: "tuple[int, ...]" = (
    0, 216, 37, 341, 318, 179, 367, 298, 167, 339, 330, 363, 316, 320, 228, 335,
    361, 392, 355, 346, 204, 220, 177, 306, 52, 21, 88, 86, 348, 100, 380, 58,
    46, 90, 15, 17, 12, 114, 20, 49, 70, 24, 57, 97, 55, 322, 82, 85,
    83, 359, 115, 378, 126, 127, 219, 78, 107, 106, 108, 123, 113, 349, 121, 125,
    305, 143, 62, 122, 51, 338, 397, 105, 131, 249, 145, 146, 144, 128, 112, 103,
    149, 175, 286, 165, 280, 280, 280, 280, 280, 280, 280, 280, 280, 280, 280, 280,
    280, 280, 280, 280, 280, 280, 280, 280, 280, 280, 280, 280, 280, 280, 280, 280,
    280, 280, 280, 280, 280, 280, 280, 280, 280, 280, 280, 280, 280, 280, 280, 280,
)
assert len(VANILLA_DARK_POKEMON_LIST) == DARK_POKEMON_LIST_LENGTH


def dark_pokemon_list_words(species_by_ddpk: "dict[int, int]") -> "tuple[tuple[int, int, int], ...]":
    """(address, vanilla word, new word) for every word of the table that changes. `species_by_ddpk` is
    {DDPK index: internal species} for the records in use; index 0 and anything absent keep their vanilla entry."""
    table = list(VANILLA_DARK_POKEMON_LIST)
    for index, species in species_by_ddpk.items():
        if 0 < int(index) < DARK_POKEMON_LIST_LENGTH and 0 < int(species) < 0x10000:
            table[int(index)] = int(species)
    words = []
    for i in range(0, DARK_POKEMON_LIST_LENGTH, 2):
        vanilla = (VANILLA_DARK_POKEMON_LIST[i] << 16) | VANILLA_DARK_POKEMON_LIST[i + 1]
        new = (table[i] << 16) | table[i + 1]
        if new != vanilla:
            words.append((DARK_POKEMON_LIST_ADDRESS + 2 * i, vanilla, new))
    return tuple(words)


assert struct.calcsize(">H") * DARK_POKEMON_LIST_LENGTH == 0x100   # the map's size for `darkPokemonList`


# ---- ADDENDUM 468 ------------------------------------------------------------------------------------------------
# A Shadow (including ADDENDUM 467's copies) leaves every ordinary trainer's team once it is defeated or snagged; a
# defeated one goes to Miror B.
#
# A beaten, unsnagged Shadow gets status 2 (`_darkPokemonSetUnderTaker`, at the end of a battle the player WON -- or
# any battle when the record's +0x15 flag is set -- and only when the record's +0x00 "worth" byte is non-zero). The
# fix above still built a status-2 Shadow, because Miror B. fields the fled ones through this same routine. Now it
# looks at WHO is building the team: an ordinary trainer (`_fightTrainerCreateDeckNormal`, the only caller whose
# return address is 0x801FADBC) skips it, exactly as a snagged one; Miror B.'s Poke Spot and Colosseum builders
# (`_fightTrainerCreateDeckUnderTaker*`, `_fightTrainer_GetUnderTakerDarkPoke`) and the virtual decks still build it.
#
# Room: add modes 1 and 2 (a script hanging one Shadow on one slot) were two byte-for-byte equivalent blocks; mode 2
# now branches into mode 1's, which frees mode 2's body for the four-word caller check.
#
#     0x801FAB0C  beq  callerCheck   status 2, no script mode          (465: beq build)
#     0x801FAB58  bne  0x801FABF0    add mode 1, other slot -> done     (was: bne -> the mode-2 test)
#     0x801FABA8  b    0x801FAB4C    add mode 2 -> mode 1's body        (was: clrlwi r3,r21,24)
#     0x801FABAC  lhz  r0,0x46(r1)   low half of the saved return address
#     0x801FABB0  cmplwi r0,0xADBC   _fightTrainerCreateDeckNormal?
#     0x801FABB4  beq  skip          ... -> skipped: it is with Miror B. now
#     0x801FABB8  b    build         Miror B. / virtual decks build it, as before
#
# Status 3/4 (snagged, purified) still fall into the swap block and are skipped; fight mode 1 / swap mode 1 behave as
# before. The other four callers return to 0x801FB220, 0x801FB5DC, 0x801FB81C and 0x801FB9F0.
FLED_SHADOW_SKIP_ENABLED = True
NORMAL_DECK_RETURN_ADDRESS = 0x801FADBC
FLED_SHADOW_SKIP_WORDS: "tuple[tuple[int, int, int], ...]" = (
    (0x801FAB0C, 0x41820038, 0x418200A0),   # beq build (465)               -> beq caller check (0x801FABAC)
    (0x801FAB58, 0x40820048, 0x40820098),   # bne mode-2 test (0x801FABA0)   -> bne done (0x801FABF0)
    (0x801FABA8, 0x56A3063E, 0x4BFFFFA4),   # clrlwi r3,r21,24               -> b mode 1's body (0x801FAB4C)
    (0x801FABAC, 0x57A0063E, 0xA0010046),   # clrlwi r0,r29,24               -> lhz r0,0x46(r1)
    (0x801FABB0, 0x7C030040, 0x2800ADBC),   # cmplw r3,r0                    -> cmplwi r0,0xADBC
    (0x801FABB4, 0x4082003C, 0x4182FF64),   # bne done                       -> beq skip (0x801FAB18)
    (0x801FABB8, 0x56D5063E, 0x4BFFFF8C),   # clrlwi r21,r22,24              -> b build (0x801FAB44)
)
#: The callers of `_fightTrainerCreateDeckPokemon` (bl site -> return address); only the first is an ordinary trainer.
CREATE_DECK_POKEMON_CALL_SITES: "dict[int, str]" = {
    0x801FADB8: "_fightTrainerCreateDeckNormal",
    0x801FB21C: "_fightTrainerCreateDeckVirtual",
    0x801FB5D8: "_fightTrainerCreateDeckUnderTakerInColosseum",
    0x801FB818: "_fightTrainerCreateDeckUnderTaker",
    0x801FB9EC: "_fightTrainer_GetUnderTakerDarkPoke",
}
assert NORMAL_DECK_RETURN_ADDRESS == 0x801FADB8 + 4
assert len({(a + 4) & 0xFFFF for a in CREATE_DECK_POKEMON_CALL_SITES}) == len(CREATE_DECK_POKEMON_CALL_SITES)

#: A relocated Citadark Shadow keeps its own DDPK record, and Greevil's six (74-79) have worth 0: beaten, they never
#: flee, so they could be neither skipped elsewhere nor met again with Miror B. They get the value every generated
#: Shadow carries.
RELOCATED_SHADOW_WORTH = 128
RELOCATED_SHADOW_WORTH_ENABLED = True   # `iso_patcher.apply_relocated_shadow_worth` writes it

