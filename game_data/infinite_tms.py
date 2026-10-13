"""ADDENDUM 463 -- Infinite TMs: a TM is never used up, like an HM.

Player: "Can we add an option for TMs to be infinite use?"

Using a TM from the Bag runs `menuUseItemSkill` (0x800A5048), XD's item handler for TMs and HMs. It calls
`wazaMachineProc` to teach the move, and when the Pokemon learned it, writes the caller's "consumed" flag -- the same
`func(item, &consumed)` contract `_actTukauNormal` uses for every Bag item (ADDENDUM 453):

    0x800A5140  clrlwi r0,r30,24          r30 = itemDataBiosGetHidenMachineNo(item)
    0x800A5144  cmplwi r0,255             255 = not an HM, i.e. a TM
    0x800A5148  beq    0x800A5158
    0x800A514C  li     r0,0               HM: consumed = 0, the item stays
    0x800A5150  stw    r0,0(r31)
    0x800A5154  b      0x800A5160
    0x800A5158  li     r0,1               TM: consumed = 1, one is removed      <- this word
    0x800A515C  stw    r0,0(r31)

One immediate: `li r0,1` -> `li r0,0`, and a TM is kept exactly the way an HM is. Nothing else changes -- the
learn/forget flow, the messages, the compatibility check, cancelling. It is the only place the game spends a TM
(`wazaMachineProc` has this one caller), and it is checked against its vanilla word before it is written.
"""
from __future__ import annotations

HANDLER = 0x800A5048          # menuUseItemSkill
TM_CONSUMED_ADDRESS = 0x800A5158
VANILLA_WORD = 0x38000001     # li r0,1
PATCHED_WORD = 0x38000000     # li r0,0
HM_KEPT_WORD_ADDRESS = 0x800A514C   # the HM branch's own `li r0,0`, the instruction this one is made to match


def dol_patch_words() -> "tuple[tuple[int, int, int], ...]":
    """(address, vanilla word, new word)."""
    return ((TM_CONSUMED_ADDRESS, VANILLA_WORD, PATCHED_WORD),)


assert PATCHED_WORD == 0x38000000 and (VANILLA_WORD >> 16) == 0x3800   # li r0,imm (addi r0,0,imm)
