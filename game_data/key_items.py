"""The real key items, their game item ids, and what each one gates.

The ids were resolved offline from the ISO -- `xd_rel_format.item_name_id` -> `string_table_id_offsets()` ->
UTF-16BE decode names any item id, and enumerating every id resolved 456 items. Cross-checks agree: ID Card
= 506 and Krane Memo 1-5 = 523-527 were confirmed live, and chest 17 resolves to DATA ROM with chest 18 ID
CARD. The same dump identified 534-592 as Battle CD 01-59.

`Ein File S` and `Spot Monitor` have no entry under any id, which is why Ein File S leaves the pool (victory
is defeating Greevil the second time) and the Spot Monitor is granted on entering the Rock Poke Spot.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KeyItem:
    name: str                        # must match items.py's own spelling exactly
    game_item_id: int
    gates: "tuple[str, ...]" = ()    # human-readable, for documentation and `!keyitems`
    in_pool: bool = True             # False = left vanilla, never shuffled
    shuffled: bool = True            # False = stays in its vanilla location even with key-item shuffle on
    note: str = ""


# The nine items that appear in a real access rule, plus the ones deliberately left vanilla.
KEY_ITEMS: "tuple[KeyItem, ...]" = (
    KeyItem("Machine Part", 503, gates=("Agate Village",),
            note="obtained at the Gateon Port parts shop (player, 2026-09-13)"),
    KeyItem("Data ROM", 505, gates=("Cipher Lab", "Pyrite Town", "Poke Spots")),
    KeyItem("ID Card", 506, gates=("Chest 27", "Lovrina 1"),
            note="the only id that was already live-confirmed before this table existed"),
    KeyItem("Music Disc", 507, gates=("Phenac City (Mayor's House)", "Phenac City (Post-Sixes)")),
    KeyItem("Mayor's Note", 509, gates=("Phenac City (Post-Sixes)", "SS Libra (stranded)")),
    KeyItem("Elevator Key", 501, gates=("SS Libra (stranded)",), shuffled=False,
            note="chest 79 stays vanilla -- the player reports taking it out of place locks you in the room"),
    KeyItem("System Lever", 508, gates=("Cipher Key Lair (deep)", "Acrod", "Smarton", "Gorigan 1")),
    KeyItem("Gonzap's Key", 504, in_pool=False, shuffled=False,
            note="left vanilla: the container it opens is not in XDTreasureBoxData, so it gates no AP location"),
)

KEY_ITEM_BY_NAME: "dict[str, KeyItem]" = {k.name: k for k in KEY_ITEMS}
KEY_ITEM_BY_GAME_ID: "dict[int, KeyItem]" = {k.game_item_id: k for k in KEY_ITEMS}

# What the client polls the Key Items pocket for when key-item shuffle is on. Only shuffled items: a vanilla
# item in its vanilla place is the player legitimately holding it.
POLLED_GAME_ITEM_IDS: "frozenset[int]" = frozenset(k.game_item_id for k in KEY_ITEMS if k.shuffled and k.in_pool)

# Items that exist in the game and are NOT part of this world's logic -- recorded so the ids are not re-hunted.
# The player's instruction was to drop all of these from the pool for now.
FLAVOUR_ITEM_IDS: "dict[str, int]" = {
    "Bonsly Card": 502, "Miror Radar": 510, "Cologne Case": 512, "Sun Shard": 516, "Moon Shard": 517,
    "Bonsly Photo": 518, "Cry Analyzer": 519, "Disc Case": 533,
    "Voice Case 1": 528, "Voice Case 2": 529, "Voice Case 3": 530, "Voice Case 4": 531, "Voice Case 5": 532,
}

# The Krane Memos keep their five AP LOCATIONS (ADDENDUM 153, working live) but their ITEMS leave the pool.
KRANE_MEMO_GAME_ITEM_IDS: "dict[int, int]" = {n: 522 + n for n in range(1, 6)}

# Items resolved from the ISO that this project has no use for, kept so they are never mistaken for a gap.
UNUSED_RESOLVED_IDS: "dict[str, int]" = {
    "Safe Key": 500,        # exists in the game; the player's instruction was to ignore it
    "Poke Snack": 511,
    "Joy Scent": 513, "Excite Scent": 514, "Vivid Scent": 515,
}

BATTLE_CD_FIRST_ID = 534
BATTLE_CD_LAST_ID = 592   # Battle CD 01 .. Battle CD 59

assert len(KEY_ITEM_BY_GAME_ID) == len(KEY_ITEMS), "two key items share a game item id"
assert KEY_ITEM_BY_NAME["ID Card"].game_item_id == 506, "the one live-confirmed id must not drift"
assert all(522 < i <= 527 for i in KRANE_MEMO_GAME_ITEM_IDS.values()), "memo ids are 523-527"
