"""Every Shadow Pokemon can be purified the ordinary way, Lugia included.

In vanilla the game singles out Lugia (species 249) and the XD001 record (Shadow id 73):
  * a battle, a call and a scent skip species 249 (`fightSeqFightOutPokemonDarkCheckAppear`,
    `fightSeqCallExec`, `menuUseItemScriptCologn`);
  * walking in the party skips Shadow id 73 (`_sodateyaCallBackFunc`);
  * walking in the Purify Chamber skips species 249 (`CReliveStage::heroWalkReliveCallBack`).
So a randomized Lugia, or whatever species lands in record 73, keeps a closed gauge until the chamber's
nine-at-max-tempo event. Each test compares against an immediate; the patch makes that immediate 0xFFFF, which no
species or Shadow id ever is, so the special case never matches. The chamber's own Lugia event is left as it is.
"""
from __future__ import annotations

_NEVER = 0x2800FFFF        # cmplwi r0, 0xFFFF

# (address, vanilla word, new word)
PATCH_WORDS: "tuple[tuple[int, int, int], ...]" = (
    (0x802261DC, 0x280000F9, _NEVER),   # battle: cmplwi r0, 249
    (0x8020F40C, 0x280000F9, _NEVER),   # call: cmplwi r0, 249
    (0x800A53A0, 0x280000F9, _NEVER),   # scent: cmplwi r0, 249
    (0x801ED248, 0x28000049, _NEVER),   # party walking: cmplwi r0, 73 (Shadow id)
    (0x8028D910, 0x280000F9, _NEVER),   # Purify Chamber walking: cmplwi r0, 249
)


def dol_patch_words() -> "tuple[tuple[int, int, int], ...]":
    """(address, vanilla word, new word) for `iso_patcher.write_dol_words_patch`."""
    return PATCH_WORDS
