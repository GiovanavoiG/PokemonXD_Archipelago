"""Which berry each chest contains, and therefore which chest an opened berry is.

The invariant is the whole design:

    NO TWO CHESTS IN THE SAME ROOM EVER CONTAIN THE SAME BERRY.

So `(room_id, berry_id)` identifies exactly one chest and nothing here reads a chest-flag bit. The room id
returns None rather than guess, which is what makes it safe to build identity on; the flag bitfield carries
story flags on chest positions with non-monotonic cluster offsets and has been mis-modelled four times.

The assignment is computed from `chest_table.CHESTS` and `items.CHEST_BERRY_IDS` in sorted order and asserted
at import, so a collision fails the load instead of reaching a seed, and being a pure function of two fixed
tables it is identical for every seed and build -- the client has to identify a chest without being told the
seed's assignment. Quantity is always 1; the field exists only because the ISO's chest entry has a slot.
"""
from __future__ import annotations

from .chest_table import CHESTS
# Re-exported so `ram_client` has one import for the whole chest-berry story; it cannot import `locations`.
from ..items import CHEST_BERRY_ID_TO_NAME, CHEST_BERRY_IDS

__all__ = [
    "CHEST_BERRY_IDS", "CHEST_BERRY_ID_TO_NAME", "MAX_CHEST_BERRY_QUANTITY",
    "CHEST_BERRY_ASSIGNMENT", "ROOM_BERRY_TO_CHEST", "CHEST_TO_ROOM",
    "berry_for_chest", "chest_for", "chests_in_room", "berries_used_in_room",
]

# Was 3: every chest cycled 1..3 copies of its berry. Quantity is not part of a chest's identity -- (room,
# berry) already decides -- and a quantity above 1 is visible to the player as "2 AP Items" in the chest
# message, so one check per chest means one berry per chest.
MAX_CHEST_BERRY_QUANTITY = 1


def _assign() -> "dict[int, tuple[int, int]]":
    """chest index -> (berry game item id, quantity). See the module docstring for the invariant."""
    by_room: "dict[int, list[int]]" = {}
    for entry in CHESTS:
        by_room.setdefault(entry["room"], []).append(entry["chest"])

    assignment: "dict[int, tuple[int, int]]" = {}
    uses: "dict[int, int]" = {berry: 0 for berry in CHEST_BERRY_IDS}
    for room in sorted(by_room):
        taken_in_room: "set[int]" = set()
        for chest in sorted(by_room[room]):
            # Least-used berry not already used in this room: an even spread keeps each berry's Bag
            # quantity small and its deltas readable.
            berry = min((b for b in CHEST_BERRY_IDS if b not in taken_in_room),
                        key=lambda b: (uses[b], b))
            taken_in_room.add(berry)
            assignment[chest] = (berry, uses[berry] % MAX_CHEST_BERRY_QUANTITY + 1)
            uses[berry] += 1
    return assignment


CHEST_BERRY_ASSIGNMENT: "dict[int, tuple[int, int]]" = _assign()

# (room_id, berry_id) -> chest index. The lookup the client actually uses.
ROOM_BERRY_TO_CHEST: "dict[tuple[int, int], int]" = {}
CHEST_TO_ROOM: "dict[int, int]" = {entry["chest"]: entry["room"] for entry in CHESTS}
for _chest, (_berry, _qty) in CHEST_BERRY_ASSIGNMENT.items():
    ROOM_BERRY_TO_CHEST[(CHEST_TO_ROOM[_chest], _berry)] = _chest


def berry_for_chest(chest_id: int) -> "tuple[int, int] | None":
    """`(berry id, quantity)` for a chest, or None for a chest this table does not cover."""
    return CHEST_BERRY_ASSIGNMENT.get(chest_id)


def chest_for(room_id: "int | None", berry_id: "int | None") -> "int | None":
    """The chest that berry means in that room, or None for an unknown room or berry, or one no chest in the
    room contains. Same never-guess contract as `read_room_id` and `read_story_byte`."""
    if room_id is None or berry_id is None:
        return None
    return ROOM_BERRY_TO_CHEST.get((room_id, berry_id))


def chests_in_room(room_id: "int | None") -> "tuple[int, ...]":
    if room_id is None:
        return ()
    return tuple(sorted(chest for chest, room in CHEST_TO_ROOM.items() if room == room_id))


def berries_used_in_room(room_id: "int | None") -> "tuple[int, ...]":
    return tuple(sorted({CHEST_BERRY_ASSIGNMENT[c][0] for c in chests_in_room(room_id)
                         if c in CHEST_BERRY_ASSIGNMENT}))


# Assertions rather than tests: a violation here silently credits the wrong check, and a wrong check cannot
# be taken back.
assert len(CHEST_BERRY_ASSIGNMENT) == len(CHESTS), (
    f"every chest needs a berry: {len(CHEST_BERRY_ASSIGNMENT)} assigned, {len(CHESTS)} chests"
)
assert len(ROOM_BERRY_TO_CHEST) == len(CHESTS), (
    "two chests in one room share a berry -- (room, berry) would no longer identify a chest, which is the "
    "one invariant this whole module exists to provide"
)
assert all(berry in CHEST_BERRY_IDS for berry, _ in CHEST_BERRY_ASSIGNMENT.values()), (
    "a chest was assigned a berry outside the reserved set"
)
assert all(1 <= qty <= MAX_CHEST_BERRY_QUANTITY for _, qty in CHEST_BERRY_ASSIGNMENT.values()), (
    "a chest quantity fell outside the 1..MAX range"
)
_max_room = max(len(chests_in_room(r)) for r in set(CHEST_TO_ROOM.values()))
assert _max_room <= len(CHEST_BERRY_IDS), (
    f"a room holds {_max_room} chests but only {len(CHEST_BERRY_IDS)} berries are reserved -- the "
    f"within-room uniqueness invariant cannot be satisfied. Reserve another berry from items.py's shop set "
    f"(it has room for one more before Mt. Battle's 18 slots start repeating)."
)
