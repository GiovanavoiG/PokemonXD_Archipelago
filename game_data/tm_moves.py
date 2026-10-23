"""TMs: which move each teaches, Shadow moves on TMs, and every species learning every TM.

THE MOVE A TM TEACHES lives in main.dol, `item_waza_machine_no` (0x804053A0): 58 eight-byte entries (a flag word, then
the move id as a u32), TM01-TM50 then eight HM slots XD never uses. `itemDataBiosGetWazaIDByWazaMachineNo` reads it
by the TM item's machine number (Items row +0x18), so changing an entry's move changes what that TM teaches -- the
Bag shows the new move's name, the item keeps its own.

WHO CAN LEARN IT is the species stats table in common_rel: 58 bytes at row +0x34, one per machine, 0 or 1
(`pokemonDataBiosGetWazaMcn`). Shadow Pokemon never use TMs (`wazaMachineProc` refuses them first).

Import-free, so the standalone patcher can load it by path.
"""
from __future__ import annotations

TM_TABLE_ADDRESS = 0x804053A0
TM_TABLE_ENTRY_SIZE = 8
TM_TABLE_MOVE_OFFSET = 4
TM_COUNT = 50
TM_COMPATIBILITY_OFFSET = 0x34

#: TM01-TM50, the vanilla move of each (read off main.dol's table).
VANILLA_TM_MOVES: "tuple[int, ...]" = (
    264, 337, 352, 347, 46, 92, 258, 339, 331, 237, 241, 269, 58, 59, 63, 113, 182, 240, 202, 219,
    218, 76, 231, 85, 87, 89, 216, 91, 94, 247, 280, 104, 115, 351, 53, 188, 201, 126, 317, 332,
    259, 263, 290, 156, 213, 168, 211, 285, 289, 315,
)
assert len(VANILLA_TM_MOVES) == TM_COUNT

#: The 18 Shadow moves, by move id.
SHADOW_MOVE_NAMES: "dict[int, str]" = {
    356: "Shadow Blitz", 357: "Shadow Rush", 358: "Shadow Break", 359: "Shadow End", 360: "Shadow Wave",
    361: "Shadow Rave", 362: "Shadow Storm", 363: "Shadow Fire", 364: "Shadow Bolt", 365: "Shadow Chill",
    366: "Shadow Blast", 367: "Shadow Sky", 368: "Shadow Hold", 369: "Shadow Mist", 370: "Shadow Panic",
    371: "Shadow Down", 372: "Shadow Shed", 373: "Shadow Half",
}
MAX_SHADOW_MOVE_TMS = len(SHADOW_MOVE_NAMES)


def plan_shadow_move_tms(rng, count: int) -> "list[tuple[int, int]]":
    """[(TM number 1-50, Shadow move id), ...] sorted by TM: `count` random TMs, each given a different random
    Shadow move."""
    count = max(0, min(int(count), MAX_SHADOW_MOVE_TMS))
    if count == 0:
        return []
    tms = rng.sample(range(1, TM_COUNT + 1), count)
    moves = rng.sample(sorted(SHADOW_MOVE_NAMES), count)
    return sorted(zip(tms, moves))


def shadow_move_tm_words(plan: "list[tuple[int, int]] | list[list[int]]") -> "tuple[tuple[int, int, int], ...]":
    """(address, vanilla move, new move) words for `write_dol_words_patch`."""
    words = []
    for tm, move in plan:
        tm, move = int(tm), int(move)
        if not 1 <= tm <= TM_COUNT or move not in SHADOW_MOVE_NAMES:
            raise ValueError(f"TM{tm:02d} -> move {move} is not a TM and a Shadow move")
        address = TM_TABLE_ADDRESS + (tm - 1) * TM_TABLE_ENTRY_SIZE + TM_TABLE_MOVE_OFFSET
        words.append((address, VANILLA_TM_MOVES[tm - 1], move))
    return tuple(words)
