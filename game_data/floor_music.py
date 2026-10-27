"""A room always starts its own music, even when the story flags its music rows test are not set.

On entering a room, `floorSound_playSound` (0x8012AAF4) walks the room-music table (common_rel, 12-byte rows:
volume +1, room +2, BGM +4, fade +6, GS flag +10) for that room's rows, in order, and plays the first one whose flag
is 0 or set. Nothing matching means nothing is played, so the previous room's music keeps going.

Many rooms have ONLY flag-gated rows, and those flags are set by story events elsewhere: Phenac City (1977/1978, set
by the ONBS and Phenac rescue events), the Pyrite ONBS building (2112/2114/2255), the HQ Lab (1979/2110/2111/2223),
the Cipher Key Lair (2224/2225/2287, set on the S.S. Libra and in the lair), the Snagem Hideout (2280), Kaminko's
House (2118/2119) and the S.S. Libra (2296/2297). Reaching one of these rooms before the event that sets its flag --
which travel and the story floors make possible -- leaves it silent of its own music.

THE FIX. The "nothing matched" exit (`li r3,0` at 0x8012AB70) branches to a short routine that plays the room's
FIRST row unconditionally -- the music the game gives that room on the first visit. Rooms with no rows at all are
untouched (the search returns nothing and the original `li r3,0` result stands), and any room whose flags DO select
a row is untouched because the routine is only reached when none did.

    cave +0x00  mr     r3,r30          r30 = this room (floorGetCurrent, kept across the loop)
    cave +0x04  li     r4,0            search from the top of the table
    cave +0x08  bl     floorSound_SearchTable
    cave +0x0C  cmplwi r3,0
    cave +0x10  beq    +0x10
    cave +0x14  bl     _playSound      the room's first row, flag ignored
    cave +0x18  clrlwi r3,r3,24
    cave +0x1C  b      0x8012AB74      the function's own epilogue (it saved LR, r30 and r31 on entry)
    cave +0x20  li     r3,0
    cave +0x24  b      0x8012AB74

The routine sits at the start of `dbgMenuMemcardDebugSave` (0x8000B850, 0x1E8 bytes), a debug-menu function with no
caller and no pointer to it anywhere in main.dol, and clear of every other routine this patcher writes.

Import-free so the standalone patcher can load it by path.
"""
from __future__ import annotations

PLAY_SOUND = 0x8012AAF4             # floorSound_playSound
SEARCH_TABLE = 0x8012AB8C           # floorSound_SearchTable(room, after_row) -> row or 0
PLAY_ROW = 0x8012AC48               # _playSound(row) -> 1 when it started (or kept) the music
HOOK_ADDRESS = 0x8012AB70           # floorSound_playSound+0x7C: li r3,0 -- nothing matched
EPILOGUE_ADDRESS = 0x8012AB74       # lwz r0,20(r1)
HOOK_VANILLA_WORD = 0x38600000

CAVE_ADDRESS = 0x8000B850           # dbgMenuMemcardDebugSave
CAVE_VANILLA_WORDS = (
    0x9421FFE0, 0x7C0802A6, 0x90010024, 0x93E1001C, 0x93C10018,
    0x93A10014, 0x7C9E2378, 0x3C80802F, 0x7FC3F378, 0x3BA4A0B8,
)


def _branch(at: int, target: int, link: bool = False) -> int:
    offset = target - at
    assert -0x2000000 <= offset < 0x2000000 and offset % 4 == 0
    return 0x48000000 | (offset & 0x03FFFFFC) | (1 if link else 0)


def cave_words() -> "tuple[int, ...]":
    c = CAVE_ADDRESS
    return (
        0x7FC3F378,                                  # mr r3,r30
        0x38800000,                                  # li r4,0
        _branch(c + 0x08, SEARCH_TABLE, link=True),  # bl floorSound_SearchTable
        0x28030000,                                  # cmplwi r3,0
        0x41820010,                                  # beq +0x10
        _branch(c + 0x14, PLAY_ROW, link=True),      # bl _playSound
        0x5463063E,                                  # clrlwi r3,r3,24
        _branch(c + 0x1C, EPILOGUE_ADDRESS),         # b epilogue
        0x38600000,                                  # li r3,0
        _branch(c + 0x24, EPILOGUE_ADDRESS),         # b epilogue
    )


def dol_patch_words() -> "tuple[tuple[int, int, int], ...]":
    """(address, vanilla word, new word): the routine first, then the branch into it."""
    words = [(CAVE_ADDRESS + 4 * i, old, new)
             for i, (old, new) in enumerate(zip(CAVE_VANILLA_WORDS, cave_words()))]
    words.append((HOOK_ADDRESS, HOOK_VANILLA_WORD, _branch(HOOK_ADDRESS, CAVE_ADDRESS)))
    return tuple(words)


assert len(CAVE_VANILLA_WORDS) == len(cave_words()) == 10
