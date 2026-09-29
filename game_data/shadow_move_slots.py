"""Which Shadow move is legal in which DDPK move slot. Observed occupancy across all 83 in-use vanilla
entries in DeckData_DarkPokemon.bin, recorded verbatim -- nothing inferred from move names:

    ids 356-366   appear in slot 0.  Five of them (356, 363, 364, 365, 366) appear nowhere else.
    ids 367-373   appear only in slots 1-3.  None is ever in slot 0.

Two classes of move, then: an opening Shadow attack, and secondary moves the heart gauge reveals. A move put
in a slot the game never uses it in comes out unusable -- neither the DPKM nor the DDPK entry carries a PP
field, so PP is set up when the game builds the battle Pokemon, and the symptom is a move reporting no PP.
That is the mechanism the data supports, not a read of the game's code.
"""
from __future__ import annotations

# move id -> the slot indices it is observed in, across all 83 in-use vanilla DDPK entries.
# Measured 2026-09-15 from the player's own deck_dark_1.bin.
SHADOW_MOVE_OBSERVED_SLOTS: "dict[int, tuple[int, ...]]" = {
    356: (0,),
    357: (0, 1, 3),
    358: (0, 1),
    359: (0, 3),
    360: (0, 1),
    361: (0, 2),
    362: (0, 1, 3),
    363: (0,),
    364: (0,),
    365: (0,),
    366: (0,),
    367: (1, 2, 3),
    368: (1, 2, 3),
    369: (1, 2, 3),
    370: (1, 2),
    371: (1, 2),
    372: (1, 2),
    373: (1, 2),
}

# Inverted: slot index -> the move ids ever seen there. What a generator should draw from.
MOVES_LEGAL_IN_SLOT: "dict[int, tuple[int, ...]]" = {
    slot: tuple(sorted(move for move, slots in SHADOW_MOVE_OBSERVED_SLOTS.items() if slot in slots))
    for slot in range(4)
}

ALL_SHADOW_MOVE_IDS: "tuple[int, ...]" = tuple(sorted(SHADOW_MOVE_OBSERVED_SLOTS))


def is_legal_in_slot(move_id: int, slot: int) -> bool:
    """True when this move is observed in this slot in the real vanilla data."""
    return slot in SHADOW_MOVE_OBSERVED_SLOTS.get(move_id, ())


# Read from the move table in vanilla `common_rel.rel` (inside `common.fsys`): pointer-table index 124
# (`Constants.XDMoves` in rotobash/pokemon-ngc-rando), offset 0xA2710 matching its `FirstMoveOffset`,
# declared entry count 375, stride 0x38, base power +0x19, category
# +0x13. The split explains the slot table above: 356-366 are all damaging at 40-120 base power and are
# exactly slot 0's pool, 367-373 are all base power 0 and are exactly slots 1-3's. Slot 0 is THE attack.
SHADOW_MOVE_BASE_POWER: "dict[int, int]" = {
    356: 40, 357: 55, 358: 75, 359: 120, 360: 50, 361: 70, 362: 95,
    363: 75, 364: 75, 365: 75, 366: 80,
    367: 0, 368: 0, 369: 0, 370: 0, 371: 0, 372: 0, 373: 0,
}

# 0 = status, 1 = physical, 2 = special (MoveCategories.cs).
SHADOW_MOVE_CATEGORY: "dict[int, int]" = {
    356: 1, 357: 1, 358: 1, 359: 1, 360: 2, 361: 2, 362: 2,
    363: 2, 364: 2, 365: 2, 366: 1,
    367: 2, 368: 2, 369: 2, 370: 2, 371: 2, 372: 2, 373: 2,
}

ATTACKING_SHADOW_MOVE_IDS: "frozenset[int]" = frozenset(
    move for move, power in SHADOW_MOVE_BASE_POWER.items() if power > 0
)


def is_attacking(move_id: int) -> bool:
    """True when this Shadow move deals damage. An unknown id returns False -- that is the case where we must
    not claim a Shadow Pokemon can attack."""
    return move_id in ATTACKING_SHADOW_MOVE_IDS


def has_attacking_move(shadow_moves: "list[int] | tuple[int, ...]") -> bool:
    """True when at least one non-zero entry in this DDPK moveset deals damage. A Shadow Pokemon cannot use
    its ordinary moves until the heart gauge opens, so this list is its whole offense until then. All 83
    vanilla entries satisfy it."""
    return any(is_attacking(m) for m in shadow_moves if m)


def choose_shadow_moves(rng, count: int = 2) -> "list[int]":
    """`count` distinct Shadow move ids, each legal in the slot it lands in.

    Drawn slot by slot rather than sampled as a set, because the constraint is positional. If distinctness
    cannot be satisfied it repeats a move rather than place an illegal one -- a repeat is cosmetic, an illegal
    placement is unusable. The damaging-move repair never fires while slot 0's pool is all attacks; it is here
    so a future table correction cannot ship Shadows that cannot attack."""
    chosen: "list[int]" = []
    for slot in range(min(count, 4)):
        options = [m for m in MOVES_LEGAL_IN_SLOT[slot] if m not in chosen]
        if not options:
            options = list(MOVES_LEGAL_IN_SLOT[slot])
        if not options:
            break
        chosen.append(rng.choice(options))
    if chosen and not has_attacking_move(chosen):
        attacking = [m for m in MOVES_LEGAL_IN_SLOT[0] if is_attacking(m)]
        if attacking:
            chosen[0] = rng.choice(attacking)
    return chosen


def illegal_placements(shadow_moves: "list[int] | tuple[int, ...]") -> "list[tuple[int, int]]":
    """`(slot, move_id)` for every non-zero move in a slot the vanilla data never puts it in. Empty is the
    correct answer for every vanilla entry and for anything this project generates."""
    return [(slot, move) for slot, move in enumerate(shadow_moves)
            if move and not is_legal_in_slot(move, slot)]


# A generator drawing from an empty slot list would silently produce no moves at all.
assert all(MOVES_LEGAL_IN_SLOT[slot] for slot in range(4)), "a slot has no legal move at all"
assert not (set(MOVES_LEGAL_IN_SLOT[0]) & {367, 368, 369, 370, 371, 372, 373}), (
    "a secondary Shadow move leaked into the slot-0 list -- this is the exact bug ADDENDUM 223 fixed"
)

# Slot 0's pool is entirely damaging, so every generated Shadow gets an attack; slots 1-3's is all status,
# which is why slot 0 has to carry it.
assert all(is_attacking(m) for m in MOVES_LEGAL_IN_SLOT[0]), (
    "a non-damaging Shadow move is in slot 0's legal pool -- a generated Shadow could be left unable to attack"
)
assert not any(is_attacking(m) for m in (367, 368, 369, 370, 371, 372, 373)), (
    "a secondary-slot Shadow move is recorded as damaging -- re-measure against common_rel.rel before trusting"
)
assert set(SHADOW_MOVE_BASE_POWER) == set(SHADOW_MOVE_OBSERVED_SLOTS) == set(SHADOW_MOVE_CATEGORY), (
    "the measured power/category tables and the slot table disagree about which Shadow move ids exist"
)
