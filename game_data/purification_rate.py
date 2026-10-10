"""ADDENDUM 450 -- Purification Rate scales what LOWERS the heart gauge, not the gauge itself.

Player: "Rather than edit the shadow gauge itself, can we instead increase the values of the things that reduce it?
Editing the shadow gauge is breaking it."

ADDENDUM 440 shrank every Shadow's heart gauge (DDPK +0x08). That broke the gauge in play. This leaves every gauge
vanilla and multiplies the reductions instead.

WHERE THE REDUCTIONS ARE COMPUTED (retail main.dol, GXXE.map symbols). Every ordinary heart-gauge change goes through
`pokemonAddDpFormPokemonDpFilterId(pokemon, item, filter)`:

    filter 0 battle (ReliveFightout), 1 walking (ReliveWalk), 2 Call, 3 Day Care (ReliveSodateya),
    4 Scents and the like (item buff), 5 a share of the current gauge
    -> DpFilter table byte x item buff x nature rate (Kake / Waru)
    8013EEDC  lfs  f0,-25204(r2)     ; 100.0 -- the last factor
    8013EEE4  fmuls f31,f31,f0
    8013EEEC  bl   pokemonAddDp

The 100.0 at r2-25204 (0x804EDB4C) is shared with `pokemonGetDarkPokemonLevel`, so the constant itself cannot change.
Instead the one `lfs` that reads it here branches to a cave that loads `100 x rate` and comes straight back:

    cave +0x00  lis  r3,0x8006          ; r3 is dead here: 0x8013EEE0 is `mr r3,r31`
    cave +0x04  lfs  f0,0x755C(r3)      ; the float at cave +0x0C
    cave +0x08  b    0x8013EEE0
    cave +0x0C  .float  purification_rate   (100.0 at 100%, 200.0 at 200%, ...)

Battles, walking, Call, the Day Care and Scents all scale together. The Purify Chamber writes the gauge directly
(`setDarkPointDirect`) and is not changed. The cave is the tail of `dbgMenuDbgPokemonGet`, after the Candy Box and the
conditional catch (+0x820).
"""
from __future__ import annotations

import struct

from . import candy_box, conditional_catch

HOOK_ADDRESS = 0x8013EEDC                 # pokemonAddDpFormPokemonDpFilterId+0x1C4
HOOK_VANILLA_WORD = 0xC0029D8C            # lfs f0,-25204(r2)
RETURN_ADDRESS = 0x8013EEE0               # mr r3,r31
CAVE_OFFSET = 0x820
CAVE_ADDRESS = candy_box.CAVE_ADDRESS + CAVE_OFFSET
CONSTANT_ADDRESS = CAVE_ADDRESS + 0x0C
CAVE_VANILLA_WORDS = (0x480E5599, 0x7FE3FB78, 0x38800250, 0x38A00001)
VANILLA_FACTOR = 100.0
RATE_MIN, RATE_MAX = 100, 1000


def _b(at: int, target: int) -> int:
    offset = target - at
    if not -0x2000000 <= offset < 0x2000000:
        raise ValueError(f"b from 0x{at:08X} to 0x{target:08X} is out of range")
    return 0x48000000 | (offset & 0x03FFFFFC)


def _float_word(value: float) -> int:
    return struct.unpack(">I", struct.pack(">f", float(value)))[0]


def cave_words(rate_percent: int) -> "tuple[int, ...]":
    if not RATE_MIN <= int(rate_percent) <= RATE_MAX:
        raise ValueError(f"purification rate {rate_percent}% is outside {RATE_MIN}-{RATE_MAX}")
    high = (CONSTANT_ADDRESS + 0x8000) >> 16
    low = CONSTANT_ADDRESS & 0xFFFF
    return (
        0x3C600000 | high,                                   # lis r3,high
        0xC0030000 | low,                                    # lfs f0,low(r3)
        _b(CAVE_ADDRESS + 0x08, RETURN_ADDRESS),             # b back
        _float_word(VANILLA_FACTOR * int(rate_percent) / 100),
    )


def dol_patch_words(rate_percent: int) -> "tuple[tuple[int, int, int], ...]":
    """(address, vanilla, new): the cave, then the hook. All or nothing through `write_dol_words_patch`."""
    words = [(CAVE_ADDRESS + 4 * i, vanilla, new)
             for i, (vanilla, new) in enumerate(zip(CAVE_VANILLA_WORDS, cave_words(rate_percent)))]
    words.append((HOOK_ADDRESS, HOOK_VANILLA_WORD, _b(HOOK_ADDRESS, CAVE_ADDRESS)))
    return tuple(words)


assert CAVE_OFFSET >= conditional_catch.CAVE_OFFSET + 4 * len(conditional_catch.CAVE_VANILLA_WORDS)
assert CAVE_OFFSET + 4 * len(CAVE_VANILLA_WORDS) <= candy_box.CAVE_SIZE
assert (CONSTANT_ADDRESS & 0xFFFF) < 0x8000, "lfs's displacement is signed; the split above assumes it is positive"
