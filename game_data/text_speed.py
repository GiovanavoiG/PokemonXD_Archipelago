"""ADDENDUM 435 -- Text Speed, Hold B To Advance, Battle Speed (main.dol words).

Player: "Build the instant text option if it doesn't exist." Built from the 2026-10-05 investigation
(`pokemon-xd-instant-text-investigation-2026-10-05.md`); every vanilla word below was re-read from the real USA
main.dol and agrees with six MEM1 dumps.

`_msgMainSub` (0x801092B0) draws `r19` characters per frame. Vanilla sets r19 = 1, or the byte at 0x804E834C (3) while
A or B is held -- XD's own "hold to speed up". The speed byte has exactly one reader.

  * TEXT SPEED: make the "nothing held" branch read the speed byte too (0x80109620 `li r19,1` -> `lbz r19,-31444(r13)`)
    and set the byte: 3 for Fast (the held speed, always), 127 for Instant (signed byte -- 127 is the cap). A box
    still stops at every wait code, so it waits for a button press.
  * HOLD B TO ADVANCE: rewrite 0x801095DC..0x80109620 (18 words, same length, no relocation) so the "proceed" byte
    (task+0x45) is `(held & B) | (A or B pressed this frame)` instead of only the press. With Text Speed on, the
    rewrite's own `li r19,1` becomes the speed-byte load, so the two compose.
  * BATTLE SPEED: `fightMainWaitFrame` scales every battle wait by `table[byte @ 0x804E7E20] / 100`, table
    [0,10,25,50,75,100,...]; the byte is 5 (100%). Fast = 3 (50%), Faster = 2 (25%). Move animations are separate.

Import-free so the standalone patcher can load it by path.
"""
from __future__ import annotations

SPEED_BYTE_ADDRESS = 0x804E834C          # the word holding it: 0x03000000
SPEED_BYTE_WORD = 0x03000000
BATTLE_WAIT_ADDRESS = 0x804E7E20         # the word holding it: 0x05000001
BATTLE_WAIT_WORD = 0x05000001

LI_R19_1 = 0x3A600001
LBZ_R19_SPEED = 0x8A6D852C               # lbz r19, -31444(r13)
NO_HELD_BRANCH_ADDRESS = 0x80109620      # `li r19,1` on the path where neither A nor B is held

TEXT_SPEED_NORMAL, TEXT_SPEED_FAST, TEXT_SPEED_INSTANT = 0, 1, 2
TEXT_SPEED_BYTE = {TEXT_SPEED_FAST: 3, TEXT_SPEED_INSTANT: 127}

BATTLE_SPEED_NORMAL, BATTLE_SPEED_FAST, BATTLE_SPEED_FASTER = 0, 1, 2
BATTLE_SPEED_BYTE = {BATTLE_SPEED_FAST: 3, BATTLE_SPEED_FASTER: 2}

#: 0x801095DC..0x80109620, vanilla.
HOLD_B_BLOCK_ADDRESS = 0x801095DC
HOLD_B_VANILLA: "tuple[int, ...]" = (
    0x570006B6,  # rlwinm r0,r24,0,26,27        A|B pressed this frame
    0x808D8528,  # lwz r4,-31448(r13)
    0x28000000,  # cmplwi r0,0
    0x90640010,  # stw r3,16(r4)
    0x41820010,  # beq 0x801095FC
    0x38000001,  # li r0,1
    0x981F0045,  # stb r0,69(r31)               proceed = 1
    0x4800000C,  # b 0x80109604
    0x38000000,  # li r0,0
    0x981F0045,  # stb r0,69(r31)               proceed = 0
    0x4800D47D,  # bl windowGetKeyInfo
    0xA0030000,  # lhz r0,0(r3)                 held keys
    0x540006B6,  # rlwinm r0,r0,0,26,27
    0x2C000000,  # cmpwi r0,0
    0x4182000C,  # beq 0x80109620
    0x8A6D852C,  # lbz r19,-31444(r13)          held: the speed byte
    0x48000008,  # b 0x80109624
    0x3A600001,  # li r19,1                      not held: 1
)
#: The same 18 words, rewritten.
HOLD_B_PATCHED: "tuple[int, ...]" = (
    0x808D8528,  # lwz r4,-31448(r13)
    0x90640010,  # stw r3,16(r4)
    0x4800D49D,  # bl windowGetKeyInfo          (same target, 0x80116A80, from 0x801095E4)
    0xA0030000,  # lhz r0,0(r3)                 held keys
    LI_R19_1,    # li r19,1                     (the speed-byte load instead when Text Speed is on)
    0x540406B7,  # rlwinm. r4,r0,0,26,27        A|B held?
    0x41820008,  # beq +8
    0x8A6D852C,  # lbz r19,-31444(r13)          held: the speed byte
    0x540006B4,  # rlwinm r0,r0,0,26,26         held B
    0x7C00C378,  # or r0,r0,r24                 | A/B pressed this frame
    0x540006B7,  # rlwinm. r0,r0,0,26,27
    0x38000000,  # li r0,0
    0x41820008,  # beq +8
    0x38000001,  # li r0,1
    0x981F0045,  # stb r0,69(r31)               proceed
    0x60000000,  # nop
    0x60000000,  # nop
    0x60000000,  # nop
)
assert len(HOLD_B_VANILLA) == len(HOLD_B_PATCHED) == 18


def dol_patch_words(text_speed: int, hold_b: bool, battle_speed: int) -> "tuple[tuple[int, int, int], ...]":
    """(address, expected vanilla word, new word) for the chosen settings. Empty when all three are off."""
    words: "list[tuple[int, int, int]]" = []
    fast_text = text_speed in TEXT_SPEED_BYTE
    if hold_b:
        block = list(HOLD_B_PATCHED)
        if fast_text:
            block[4] = LBZ_R19_SPEED
        words += [(HOLD_B_BLOCK_ADDRESS + 4 * i, old, new)
                  for i, (old, new) in enumerate(zip(HOLD_B_VANILLA, block)) if old != new]
    elif fast_text:
        words.append((NO_HELD_BRANCH_ADDRESS, LI_R19_1, LBZ_R19_SPEED))
    if fast_text:
        value = TEXT_SPEED_BYTE[text_speed]
        new = (SPEED_BYTE_WORD & 0x00FFFFFF) | (value << 24)
        if new != SPEED_BYTE_WORD:
            words.append((SPEED_BYTE_ADDRESS, SPEED_BYTE_WORD, new))
    if battle_speed in BATTLE_SPEED_BYTE:
        value = BATTLE_SPEED_BYTE[battle_speed]
        words.append((BATTLE_WAIT_ADDRESS, BATTLE_WAIT_WORD, (BATTLE_WAIT_WORD & 0x00FFFFFF) | (value << 24)))
    return tuple(words)
