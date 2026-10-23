"""ADDENDUM 488 -- the Agate move tutor teaches every move as often as you like.

HOW SHE WORKS (main.dol, `menuScript.o`). Her twelve moves are common.rel's TutorMoves table, `wazaoshie_data`
(r13 - 0x7634; its count at r13 - 0x7638), 12 bytes a row: move id, the story value that unlocks it, and an
"already taught" GS flag.
  * `_checkWaza2` (0x8005E414) builds her menu: every unlocked row, each with `GSflagTest(row.taught_flag)` stored
    in the menu entry's +0x14 byte (0x8005E4A8 / 0x8005E4AC). When every unlocked move tests taught it returns 0,
    the "nothing left to teach" answer.
  * `menuScriptWazaBasan` (0x8005EC30) refuses a pick whose +0x14 byte is set -- that is the "taught once" lock.
  * `menuScriptSetWazaOboetaFlag` (0x8005EBBC) sets the flag after a move is learned.

THE PATCH. One word: the `bl GSflagTest` in `_checkWaza2` becomes `li r3, 0`. Every entry reads "not taught", so
nothing is refused and the menu is never empty. The flag is still SET after a lesson (the game's own bookkeeping is
left alone) -- it is just never read -- so a save where moves were already taught is unlocked too. The story unlocks
(which moves she offers when) are untouched.
"""
from __future__ import annotations

CHECK_TAUGHT_CALL = 0x8005E4A8          # _checkWaza2+0x94: bl GSflagTest(row.taught_flag)
CHECK_TAUGHT_VANILLA = 0x48141E49       # bl 0x801A02F0 (GSflagTest)
CHECK_TAUGHT_NEVER = 0x38600000         # li r3, 0 -- "not taught", every time


# Her rows unlock with the story (`GSflagGet(964)` against each row's value); the `blt` that skips a locked row
# becomes a nop, so all twelve are offered from the first visit.
UNLOCK_SKIP_BRANCH = 0x8005E484         # _checkWaza2+0x70: blt +0x48 (row not unlocked yet)
UNLOCK_SKIP_VANILLA = 0x41800048
UNLOCK_SKIP_NEVER = 0x60000000          # nop


def unlock_all_patch_words() -> "tuple[tuple[int, int, int], ...]":
    """Every row offered regardless of story progress."""
    return ((UNLOCK_SKIP_BRANCH, UNLOCK_SKIP_VANILLA, UNLOCK_SKIP_NEVER),)


def dol_patch_words() -> "tuple[tuple[int, int, int], ...]":
    """(address, vanilla word, new word) for `iso_patcher.write_dol_words_patch`."""
    return ((CHECK_TAUGHT_CALL, CHECK_TAUGHT_VANILLA, CHECK_TAUGHT_NEVER),)
