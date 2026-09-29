"""
Item definitions for the Pokemon XD: Gale of Darkness apworld.

`game_item_id` is the real XD Bag item id an AP item corresponds to, written into the `[item id][qty]` Bag
record. `game_item_id_verified=True` means it was read back in-game and matched the expected name. Held items
(179-225) and berries (133-175) are the one block not confirmed name-by-name -- only the endpoints
(BrightPowder/Stick, Cheri/Enigma) and the pocket behaviour were -- so their ordering in between is the
documented Gen III item-index table: high-confidence, not individually verified.

Excluded from the pool entirely: Mail (121-132), and the Battle CDs/Discs (347-378 and their 534-565 alias) --
32 named entries each, but one in-game resource (the Disc Case's sub-inventory) whose format is unconfirmed.
ADDENDUM 107 removed 11 more, either "forbidden"/non-functional in Colosseum/XD per their own Bulbapedia
description or trade-evolution-only in a randomizer that can never trade; per-item notes sit with each _SPECS
list.
"""

from dataclasses import dataclass
from enum import Enum

from BaseClasses import Item, ItemClassification

from . import travel_locations


class PokemonXDItem(Item):
    game: str = "Pokemon XD Gale of Darkness"


@dataclass(frozen=True)
class ItemData:
    id_offset: int  # offset from base_id; combined with World.base_id for the real AP item id
    classification: ItemClassification
    # Real in-game Bag item ID (see module docstring for the two confidence tiers).
    game_item_id: int | None = None
    # True only for ids confirmed by a live write test. False is a hypothesis -- do not ship untested.
    game_item_id_verified: bool = False
    # ADDENDUM 99: units of `game_item_id` one received copy delivers in a single write; 1 for everything
    # except the bundles.
    quantity: int = 1
    # ADDENDUM 179: extra real Bag ids this ONE AP item also delivers, for the combined Data ROM & ID Card.
    # They do NOT gate delivery: "never block sending items" outranks confirming the second write. Declared
    # LAST, because every table construction in this file is positional.
    companion_game_item_ids: "tuple[int, ...]" = ()


def _table(specs: list[tuple[str, ItemClassification, int | None, bool]], start_offset: int) -> dict[str, ItemData]:
    """Assign sequential id_offsets in the given order, starting at start_offset."""
    return {
        name: ItemData(start_offset + i, classification, game_item_id, verified)
        for i, (name, classification, game_item_id, verified) in enumerate(specs)
    }


def _bundle_table(
    specs: list[tuple[str, ItemClassification, int | None, bool, int]], start_offset: int
) -> dict[str, ItemData]:
    """Like `_table()`, for entries that also specify a non-default `quantity` -- a 5-tuple rather than a
    4-tuple. A separate helper so the existing 4-tuple _SPECS lists need no changes."""
    return {
        name: ItemData(start_offset + i, classification, game_item_id, verified, quantity)
        for i, (name, classification, game_item_id, verified, quantity) in enumerate(specs)
    }


P = ItemClassification.progression
U = ItemClassification.useful
F = ItemClassification.filler
T = ItemClassification.trap

# Progression.
_KEY_ITEM_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    ("Krane Memo 1", P, 523, True),
    ("Krane Memo 2", P, 524, True),
    ("Krane Memo 3", P, 525, True),
    ("Krane Memo 4", P, 526, True),
    ("Krane Memo 5", P, 527, True),
    ("Voice Case 1", P, 528, True),
    ("Voice Case 2", P, 529, True),
    ("Voice Case 3", P, 530, True),
    ("Voice Case 4", P, 531, True),
    ("Voice Case 5", P, 532, True),
    ("Disc Case", P, 533, True),
    # No confirmed game_item_id as of the 2026-09-02 correction -- previously mismapped to 528 (Voice Case 1).
    ("Ein File S", P, None, False),
    # 15 more real key items added 2026-09-02 from a player-supplied list; none has a confirmed id yet.
    # Most are `useful`, not `progression`: as progression they broke generation (`FillError: Not enough
    # locations for progression items` -- 34 against 18 able to hold one), and no access_rule names them.
    # The Cologne Case was deleted outright; ITEMS_REMOVED_FROM_POOL was not enough, since that set is only
    # read by create_items' PROGRESSION pass. Its offset (12) is reserved and permanently unused.
    ("Data ROM", P, 505, True),
    ("Elevator Key", P, 501, True),
    ("Bonsly Card", U, 502, True),
    ("Bonsly Photo", U, 518, True),
    ("Cry Analyzer", U, 519, True),
    ("Gonzap's Key", U, 504, True),
    ("ID Card", P, 506, True),   # ADDENDUM 134: confirmed live 2026-09-11 -- see items.py header
    ("Machine Part", P, 503, True),
    ("Mayor's Note", P, 509, True),
    ("Moon Shard", U, 517, True),
    ("Miror Radar", U, 510, True),
    ("Music Disc", P, 507, True),
    ("Sun Shard", U, 516, True),
    ("System Lever", P, 508, True),
]
# ADDENDUM 311: stones are filler. No logic ever named one -- the Eeveelution rule deliberately does not,
# since Espeon and Umbreon need none -- so `progression` only forced them into every seed.
_STONE_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    ("Sun Stone", F, 93, True),
    ("Moon Stone", F, 94, True),
    ("Fire Stone", F, 95, True),
    ("Thunder Stone", F, 96, True),
    ("Water Stone", F, 97, True),
    ("Leaf Stone", F, 98, True),
]
_MASTER_BALL_SPEC: list[tuple[str, ItemClassification, int | None, bool]] = [
    ("Master Ball", P, 1, True),
]
# ADDENDUM 104: one progression item per travel_locations.TRAVEL_LOCATION_BITS entry. Receiving one
# live-writes that destination's map-unlock bit, which is what regions.py's graph requires to consider the
# target reachable. No `game_item_id`: the "item" IS the memory write, so give_items() special-cases the
# "Travel Unlock - " prefix before the ordinary Bag path, as traps do.
_TRAVEL_UNLOCK_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    (travel_locations.travel_unlock_item_name(name), P, None, False) for name in travel_locations.TRAVEL_LOCATION_NAMES
]

# Useful.
_VITAMIN_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    ("HP Up", U, 63, True),
    ("Protein", U, 64, True),
    ("Iron", U, 65, True),
    ("Carbos", U, 66, True),
    ("Calcium", U, 67, True),
    ("Zinc", U, 70, True),
    ("PP Max", U, 71, True),
]
# Rare Candy moved to _MEDICINE_SPECS; the list keeps its name because PP Up is still here and the name is
# load-bearing in the id-offset chain. The move also flips `useful` -> `filler`, which is required since
# _RANDOM_FILLER_POOL is built from FILLER_ITEMS alone. The frozen offset (41) is keyed by NAME.
_RARE_CANDY_PP_UP_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    ("PP Up", U, 69, True),
]
# Standard Gen III hold-item index order, ids 179-225 (47 items). Endpoints (BrightPowder=179, Stick=225)
# and the pocket behaviour are live-confirmed; the ordering between them is the documented Gen III table.
# ADDENDUM 107 replaced a `179 + i` position formula with an explicit id per item, because the formula
# shifted every later item's real Bag id whenever an entry was deleted from the middle.
_HELD_ITEM_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    ("BrightPowder", U, 179, True),
    ("White Herb", U, 180, True),
    ("Macho Brace", U, 181, True),
    ("Exp. Share", U, 182, True),
    ("Quick Claw", U, 183, True),
    ("Soothe Bell", U, 184, True),
    ("Mental Herb", U, 185, True),
    ("Choice Band", U, 186, True),
    # "King's Rock": 187 -- removed (trade evolution, Poliwhirl and Slowpoke). id_offset 51 reserved.
    ("SilverPowder", U, 188, True),
    ("Amulet Coin", U, 189, True),
    # "Cleanse Tag": 190 -- removed (non-functional placeholder description). id_offset 54 reserved.
    ("Soul Dew", U, 191, True),
    # "DeepSeaTooth": 192 and "DeepSeaScale": 193 -- removed (trade evolution, Clamperl). Offsets 56, 57.
    # "Smoke Ball": 194 -- removed (non-functional placeholder, same as Cleanse Tag). id_offset 58 reserved.
    ("Everstone", U, 195, True),
    ("Focus Band", U, 196, True),
    ("Lucky Egg", U, 197, True),
    ("Scope Lens", U, 198, True),
    # "Metal Coat": 199 -- removed (trade evolution, Onix->Steelix / Scyther->Scizor). id_offset 63 reserved.
    ("Leftovers", U, 200, True),
    # "Dragon Scale": 201 -- removed (trade evolution, Seadra->Kingdra). id_offset 65 reserved.
    ("Light Ball", U, 202, True),
    ("Soft Sand", U, 203, True),
    ("Hard Stone", U, 204, True),
    ("Miracle Seed", U, 205, True),
    ("BlackGlasses", U, 206, True),
    ("Black Belt", U, 207, True),
    ("Magnet", U, 208, True),
    ("Mystic Water", U, 209, True),
    ("Sharp Beak", U, 210, True),
    ("Poison Barb", U, 211, True),
    ("NeverMeltIce", U, 212, True),
    ("Spell Tag", U, 213, True),
    ("TwistedSpoon", U, 214, True),
    ("Charcoal", U, 215, True),
    ("Dragon Fang", U, 216, True),
    ("Silk Scarf", U, 217, True),
    # "Up-Grade": 218 -- removed on trade-evolution grounds alone (its own description is real and
    # functional). id_offset 82 reserved.
    ("Shell Bell", U, 219, True),
    ("Sea Incense", U, 220, True),
    ("Lax Incense", U, 221, True),
    ("Lucky Punch", U, 222, True),
    ("Metal Powder", U, 223, True),
    ("Thick Club", U, 224, True),
    ("Stick", U, 225, True),
]
# TM01-TM50 (289-338), all live-confirmed. ADDENDUM 311 made them `filler`.
_TM_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    (f"TM{n:02d}", F, 288 + n, True) for n in range(1, 51)
]
# HMs removed: XD has none -- ids 339-346 came from the Gen III table, not this game. Offsets 140-147 stay
# reserved. ram_client's `289 <= game_item_id <= 346` TM routing is left alone: a raw-id range guard.
_HM_SPECS: "list[tuple[str, ItemClassification, int | None, bool]]" = []

# Filler.
_FILLER_BALL_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    ("Ultra Ball", F, 2, True),
    ("Great Ball", F, 3, True),
    ("Poke Ball", F, 4, True),
    ("Safari Ball", F, 5, True),
    ("Net Ball", F, 6, True),
    ("Dive Ball", F, 7, True),
    ("Nest Ball", F, 8, True),
    ("Repeat Ball", F, 9, True),
    ("Timer Ball", F, 10, True),
    ("Luxury Ball", F, 11, True),
    ("Premier Ball", F, 12, True),
]
# ADDENDUM 99: bundle filler -- one received copy delivers MULTIPLE units in one write (see
# ItemData.quantity). Same game_item_id as the single-unit ball above (Ultra=2, Great=3, Poke=4).
_FILLER_BALL_BUNDLE_SPECS: list[tuple[str, ItemClassification, int | None, bool, int]] = [
    ("10 Poke Balls", F, 4, True, 10),
    ("5 Great Balls", F, 3, True, 5),
    ("3 Ultra Balls", F, 2, True, 3),
]
_MEDICINE_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    ("Rare Candy", F, 68, True),   # 2026-09-15: moved here from _RARE_CANDY_PP_UP_SPECS -- see that list
    ("Potion", F, 13, True),
    ("Antidote", F, 14, True),
    ("Burn Heal", F, 15, True),
    ("Ice Heal", F, 16, True),
    ("Awakening", F, 17, True),
    ("Parlyz Heal", F, 18, True),
    ("Full Restore", F, 19, True),
    ("Max Potion", F, 20, True),
    ("Hyper Potion", F, 21, True),
    ("Super Potion", F, 22, True),
    ("Full Heal", F, 23, True),
    ("Revive", F, 24, True),
    ("Max Revive", F, 25, True),
    ("Fresh Water", F, 26, True),
    ("Soda Pop", F, 27, True),
    ("Lemonade", F, 28, True),
    ("Moomoo Milk", F, 29, True),
    ("Energy Powder", F, 30, True),
    ("Energy Root", F, 31, True),
    ("Heal Powder", F, 32, True),
    ("Revival Herb", F, 33, True),
    ("Ether", F, 34, True),
    ("Max Ether", F, 35, True),
    ("Elixir", F, 36, True),
    ("Max Elixir", F, 37, True),
    ("Lava Cookie", F, 38, True),
    ("Berry Juice", F, 44, True),
    ("Sacred Ash", F, 45, True),
]
_FLUTE_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    ("Blue Flute", F, 39, True),
    ("Yellow Flute", F, 40, True),
    ("Red Flute", F, 41, True),
    # "Black Flute" (42) removed (ADDENDUM 107, non-functional placeholder description, unlike Blue/Yellow/Red)
    # and "White Flute" (43) removed (ADDENDUM 99). id_offsets 190 and 191 reserved -- never recycled.
]
_SHOAL_SHARD_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
# "Shoal Shell" (47, offset 193) removed as a non-functional placeholder; Shoal Salt (192) and the four
# colored Shards (194-197) went in ADDENDUM 99. The empty category stays as an empty list literal: the
# offset-chain math tolerates len == 0, and deleting it means touching every downstream reference.
]
_BATTLE_X_ITEM_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    ("Guard Spec.", F, 73, True),
    ("Dire Hit", F, 74, True),
    ("X Attack", F, 75, True),
    ("X Defend", F, 76, True),
    ("X Speed", F, 77, True),
    ("X Accuracy", F, 78, True),
    ("X Special", F, 79, True),
    ("Poke Doll", F, 80, True),
    ("Fluffy Tail", F, 81, True),
]
_REPEL_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
# "Escape Rope" (85, offset 209) removed: Bulbapedia states outright that it cannot be used in Pokemon
# Colosseum and XD. The three real Repel tiers (83, 84, 86) went in ADDENDUM 99. Empty list kept.
]
_MISC_TREASURE_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    ("Tiny Mushroom", F, 103, True),
    ("Big Mushroom", F, 104, True),
    ("Pearl", F, 106, True),
    ("Big Pearl", F, 107, True),
    ("Stardust", F, 108, True),
    ("Star Piece", F, 109, True),
    ("Nugget", F, 110, True),
    # "Heart Scale" (111) removed 2026-09-09 (ADDENDUM 99). id_offset 218 reserved.
]
# Standard Gen III berry index order, ids 133-175, confirmed as a pocket (endpoints named individually in
# the confirmed-ids doc: Cheri 133, Spelon 163, Starf 174, Enigma 175).
#
# Pruned 2026-09-07: Bluk(149) through Enigma(175), 27 of the 43. What remains, Cheri(133) through
# Razz(148), covers every berry with a real effect in this game. The player named that range by NAME, which
# is authoritative over the "#36-#54" ordinal they also gave, since that matches neither the 1-based
# position (Bluk=17) nor the raw id (149).
#
# ADDENDUM 108: kept berries 133-145 used to land in the Items pocket, matching the game's own item-add
# behaviour for that sub-range; resolve_item_pocket routes the whole 133-175 range to Berries now.
_BERRY_NAMES: list[str] = [
    "Cheri Berry", "Chesto Berry", "Pecha Berry", "Rawst Berry", "Aspear Berry", "Leppa Berry", "Oran Berry",
    "Persim Berry", "Lum Berry", "Sitrus Berry", "Figy Berry", "Wiki Berry", "Mago Berry", "Aguav Berry",
    "Iapapa Berry",
    # "Razz Berry" removed (ADDENDUM 99, offset 234). Not Rabuta Berry (161), the chest dummy.
]
_BERRY_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    (name, F, 133 + i, True) for i, name in enumerate(_BERRY_NAMES)
]

# Reserved, NOT in the pool: the dummy item planted in every chest. Kept outside
# _BERRY_NAMES/BERRY_ITEMS/ITEM_TABLE so it can never be placed as a real AP item.
#
# ADDENDUM 31 swapped this from Enigma Berry (175), which "gave junk info" in-game: Enigma has no
# description text wired up outside Gen III's unused E-Reader features. Rabuta (161) has a valid
# description and no other confirmed in-game source once every chest gives it -- unverified, unlike Enigma,
# so if Rabuta turns out obtainable some unpatched vanilla way the chest tracker's "any increase means a
# chest was opened" assumption needs re-checking.
CHEST_DUMMY_GAME_ITEM_ID = 161
CHEST_DUMMY_GAME_ITEM_NAME = "Rabuta Berry"  # this item id's real vanilla display name -- see
# AP_ITEM_RENAME_TARGET_NAMES below (ADDENDUM 113/114, in-game rename).

# ADDENDUM 111: shop randomization by per-slot dummy berry, reusing the berries pruned above -- EXCEPT
# Rabuta (161), reserved for CHEST_DUMMY_GAME_ITEM_ID, since one dummy id shared across both mechanisms
# would corrupt the chest tracker the moment a player bought the shop version. Enigma (175) was dropped too
# (ADDENDUM 117), leaving 26: its live diagnostic showed it as the only one of 28 rename targets failing
# with a MISSING NameID (0) rather than a wrong-but-present one.
#
# Real per-shop slot counts cannot be known at generation time -- only the player's offline ISO patch run
# reads pocket_menu.rel's mart tables -- so a shop is identified by its BERRY ORDER, deterministic rather
# than random. apply_mart_randomization walks every real, non-excluded slot in a fixed order handing out the
# next berry and wrapping at the end; no shop comes close to 26 items (Bulbapedia tops out at 18,
# Mt. Battle), so each gets a distinct, non-repeating slice starting at its own offset.
#
# ADDENDUM 235 moved the list to game_data/shop_berries.py. It used to be written out here AND in
# ram_client.py, and it drifted: ADDENDUM 218 gave berries 169-174 to the chests and only this copy knew.
from .game_data.shop_berries import (  # noqa: E402
    SHOP_BERRY_SPECS as USELESS_BERRY_SPECS,
    SHOP_BERRY_IDS as USELESS_BERRY_IDS,
    SHOP_BERRY_ID_TO_NAME as USELESS_BERRY_ID_TO_NAME,
)

# Per-chest berry identity (ADDENDUM 218). Every chest used to plant the SAME berry, so identity had to come
# from the chest-flag bitfield -- which this project got wrong four separate times (ADDENDA 173, 201, 204,
# 206), because that array is global, carries story flags on chest positions, and its cluster offsets are
# non-monotonic.
#
# A chest's BERRY is its identity now, assigned so that NO TWO CHESTS IN THE SAME ROOM SHARE ONE
# (game_data/chest_berries.py), which makes (room, berry) exact for every chest in the game; the room has
# been validated four independent ways since ADDENDUM 142 and returns None rather than guessing. SEVEN IDS
# SUFFICE because the largest room holds 6 chests, and they must be disjoint from both the 15 pool berries
# (133-147, which Archipelago can SEND) and the shop berries above.
CHEST_BERRY_SPECS: list[tuple[str, int]] = [
    ("Rabuta Berry", 161),    # CHEST_DUMMY_GAME_ITEM_ID -- kept, and now one of seven rather than the only one
    ("Ganlon Berry", 169),
    ("Salac Berry", 170),
    ("Petaya Berry", 171),
    ("Apicot Berry", 172),
    ("Lansat Berry", 173),
    ("Starf Berry", 174),
    # Enigma Berry (175) is deliberately absent: bugged in-game, and the one berry in 133-175 with no
    # working id.
]
CHEST_BERRY_IDS: list[int] = [game_item_id for _name, game_item_id in CHEST_BERRY_SPECS]
CHEST_BERRY_ID_TO_NAME: dict[int, str] = {gid: name for name, gid in CHEST_BERRY_SPECS}

# Assertions rather than tests: a collision here is silent and expensive -- a berry shared between a chest and
# a shop turns a purchase into a chest check, and one shared with the pool turns an AP delivery into one.
assert not (set(CHEST_BERRY_IDS) & set(USELESS_BERRY_IDS)), (
    "a chest berry is also a shop berry -- a shop purchase would register as a chest opening"
)
assert CHEST_DUMMY_GAME_ITEM_ID in CHEST_BERRY_IDS, (
    "the historical chest dummy must remain a chest berry, or already-patched ISOs stop being understood"
)
assert len(set(CHEST_BERRY_IDS)) == len(CHEST_BERRY_IDS), "duplicate chest berry id"

# AP Item in-game rename (ADDENDUM 113/114). iso_patcher.py overwrites each dummy item's real vanilla
# display-name STRING -- never the item id, so in-battle and menu behaviour is untouched -- with
# AP_ITEM_DISPLAY_TEXT, space-padded to the original string's own byte length. An equal-length overwrite,
# never a table rebuild. This dict doubles as the "expected original name" check before any write.
AP_ITEM_RENAME_TARGET_NAMES: dict[int, str] = {
    **USELESS_BERRY_ID_TO_NAME,
    # ADDENDUM 218: all seven chest berries, not just the one former dummy. A chest berry whose real name the
    # player can see is one they may keep, sell or use -- and each of those moves a quantity read as identity.
    **CHEST_BERRY_ID_TO_NAME,
}
AP_ITEM_DISPLAY_TEXT = "AP Item"

# ADDENDUM 168: names that keep their frozen id and datapackage entry but are NO LONGER CREATED into any
# seed's pool -- the flavour key items, and Ein File S, which resolves to no item id in the game at all now
# that the victory condition is Greevil's rematch (story byte 0x78). Gonzap's Key joins them because the
# container it opens is not in the treasure table; its id (504) is recorded anyway. The Krane Memos are the
# subtle one: their five ITEMS leave the pool, their five LOCATIONS stay, because the client detects those.
#
# ADDENDUM 179: the Data ROM (what lets the player LEAVE the Cipher Lab) and the ID Card (what opens doors
# inside it) ship as ONE item, because shuffled independently a player can walk in with one and be stuck in
# a room with no other way out -- which AP logic calls fine, since logic reasons about what is REACHABLE,
# not about what is escapable. Both originals stay in the table with their offsets (13 and 19), out of the
# POOL but not out of existence, because ITEM_ID_TO_NAME must still resolve them for older seeds.
COMBINED_KEY_ITEM_NAME = "Data ROM & ID Card"

# Kept as data rather than inlined: three files translate requirements through it, and a typo in any of
# them would silently drop a gate.
COMBINED_KEY_ITEM_PARTS: "tuple[str, ...]" = ("Data ROM", "ID Card")

_COMBINED_KEY_ITEM_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    # The Data ROM's id (505); the ID Card (506) rides along as a companion id. Both confirmed live.
    (COMBINED_KEY_ITEM_NAME, P, 505, True),
]

# The start_offset is irrelevant -- the real id is pinned at 256 in _FROZEN_ITEM_OFFSETS (ADDENDUM 270).
COMBINED_KEY_ITEMS = _table(_COMBINED_KEY_ITEM_SPECS, 900)
COMBINED_KEY_ITEMS[COMBINED_KEY_ITEM_NAME] = ItemData(
    COMBINED_KEY_ITEMS[COMBINED_KEY_ITEM_NAME].id_offset, P, 505, True,
    companion_game_item_ids=(506,),   # the ID Card -- confirmed live in ADDENDUM 134
)


def requirement_to_pool_item(item_name: str) -> str:
    """Translate a requirement written in terms of the real game into the item that actually grants it.

    Every data table in this project keeps saying "Data ROM" and "ID Card", because that is what the GAME has.
    This is the one place that knows they are delivered together."""
    return COMBINED_KEY_ITEM_NAME if item_name in COMBINED_KEY_ITEM_PARTS else item_name


ITEMS_REMOVED_FROM_POOL: "frozenset[str]" = frozenset({
    "Ein File S",
    "Gonzap's Key",
    "Bonsly Card", "Bonsly Photo", "Cry Analyzer",   # Cologne Case is gone from ITEM_TABLE entirely
    "Moon Shard", "Sun Shard", "Miror Radar",
    "Disc Case",
    "Voice Case 1", "Voice Case 2", "Voice Case 3", "Voice Case 4", "Voice Case 5",
    "Krane Memo 1", "Krane Memo 2", "Krane Memo 3", "Krane Memo 4", "Krane Memo 5",
    # ADDENDUM 179: replaced by COMBINED_KEY_ITEM_NAME. Out of the pool, still in ITEM_TABLE.
    *COMBINED_KEY_ITEM_PARTS,
})

# The items that DO gate something and must be placed reachably. Cross-checked against
# game_data/key_items.py by a test. Declared here rather than beside its table, because a name has to exist
# before it can be referenced.
SCOOTER_ITEM_NAME = "Scooter Upgrade"

GATING_KEY_ITEM_NAMES: "frozenset[str]" = frozenset({
    # ADDENDUM 179: after the packaging there is one item to place rather than two.
    "Machine Part", COMBINED_KEY_ITEM_NAME, "Music Disc", "Mayor's Note", "Elevator Key", "System Lever",
})

# ADDENDUM 273: the Scooter is NOT in the set above. `GATING_KEY_ITEM_NAMES` means one thing -- a real
# story key item, in the pool when `key_item_shuffle` is on -- and the Scooter is neither half: no Bag entry
# (the upgrade is a cutscene), and it follows `shuffle_scooter_upgrade`. It still has to be placed
# reachably and to leave the edge rules when its option is off, both of which key on this set.
OPTION_GATED_PROGRESSION_ITEMS: "frozenset[str]" = frozenset({SCOOTER_ITEM_NAME})

# Excluded from the shuffle even when key_item_shuffle is on -- left in their vanilla locations.
NEVER_SHUFFLED_KEY_ITEM_NAMES: "frozenset[str]" = frozenset({
    "Elevator Key",   # the player reports moving it can lock you in the room
    "Gonzap's Key",   # gates no AP location
})

# Game item ids shop randomization must LEAVE ALONE, matched by id because there is no confirmed per-mart
# layout to target them by position: Agate Village's three Scents, and Poke Snack. All four were sourced
# externally -- rotobash/pokemon-ngc-rando's own item data, cross-checked against Bulbapedia's shop-sales
# listing -- rather than live-ISO confirmed, and the player ruled them correct as given.
POKE_SNACK_ITEM_ID = 511
AGATE_VILLAGE_SCENT_ITEM_IDS: frozenset[int] = frozenset({513, 514, 515})  # Joy Scent, Excite Scent, Vivid Scent
SHOP_EXCLUDED_ITEM_IDS: frozenset[int] = AGATE_VILLAGE_SCENT_ITEM_IDS | frozenset({POKE_SNACK_ITEM_ID})

# Trap.
_TRAP_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    # AP-only effect (no real Bag item id) -- client-side handling TBD; see PokemonXDClient.py.
    ("Itemfinder Malfunction Trap", T, None, False),
]

KEY_ITEMS = _table(_KEY_ITEM_SPECS, 0)
STONE_ITEMS = _table(_STONE_SPECS, len(KEY_ITEMS))
MASTER_BALL_ITEM = _table(_MASTER_BALL_SPEC, len(KEY_ITEMS) + len(STONE_ITEMS))
TRAVEL_UNLOCK_ITEMS = _table(
    _TRAVEL_UNLOCK_SPECS, len(KEY_ITEMS) + len(STONE_ITEMS) + len(MASTER_BALL_ITEM)
)
_prog_count = len(KEY_ITEMS) + len(STONE_ITEMS) + len(MASTER_BALL_ITEM) + len(TRAVEL_UNLOCK_ITEMS)

VITAMIN_ITEMS = _table(_VITAMIN_SPECS, _prog_count)
RARE_CANDY_PP_UP_ITEMS = _table(_RARE_CANDY_PP_UP_SPECS, _prog_count + len(VITAMIN_ITEMS))
HELD_ITEMS = _table(
    _HELD_ITEM_SPECS, _prog_count + len(VITAMIN_ITEMS) + len(RARE_CANDY_PP_UP_ITEMS)
)
TM_ITEMS = _table(
    _TM_SPECS,
    _prog_count + len(VITAMIN_ITEMS) + len(RARE_CANDY_PP_UP_ITEMS) + len(HELD_ITEMS),
)
# Empty since the HMs went; kept as a name so the id-offset chain reads the same at zero.
HM_ITEMS = _table(
    _HM_SPECS,
    _prog_count + len(VITAMIN_ITEMS) + len(RARE_CANDY_PP_UP_ITEMS) + len(HELD_ITEMS) + len(TM_ITEMS),
)
_useful_count = len(VITAMIN_ITEMS) + len(RARE_CANDY_PP_UP_ITEMS) + len(HELD_ITEMS) + len(TM_ITEMS) + len(HM_ITEMS)

_filler_start = _prog_count + _useful_count
FILLER_BALL_ITEMS = _table(_FILLER_BALL_SPECS, _filler_start)
MEDICINE_ITEMS = _table(_MEDICINE_SPECS, _filler_start + len(FILLER_BALL_ITEMS))
FLUTE_ITEMS = _table(_FLUTE_SPECS, _filler_start + len(FILLER_BALL_ITEMS) + len(MEDICINE_ITEMS))
SHOAL_SHARD_ITEMS = _table(
    _SHOAL_SHARD_SPECS, _filler_start + len(FILLER_BALL_ITEMS) + len(MEDICINE_ITEMS) + len(FLUTE_ITEMS)
)
BATTLE_X_ITEMS = _table(
    _BATTLE_X_ITEM_SPECS,
    _filler_start + len(FILLER_BALL_ITEMS) + len(MEDICINE_ITEMS) + len(FLUTE_ITEMS) + len(SHOAL_SHARD_ITEMS),
)
REPEL_ITEMS = _table(
    _REPEL_SPECS,
    _filler_start + len(FILLER_BALL_ITEMS) + len(MEDICINE_ITEMS) + len(FLUTE_ITEMS) + len(SHOAL_SHARD_ITEMS)
    + len(BATTLE_X_ITEMS),
)
MISC_TREASURE_ITEMS = _table(
    _MISC_TREASURE_SPECS,
    _filler_start + len(FILLER_BALL_ITEMS) + len(MEDICINE_ITEMS) + len(FLUTE_ITEMS) + len(SHOAL_SHARD_ITEMS)
    + len(BATTLE_X_ITEMS) + len(REPEL_ITEMS),
)
BERRY_ITEMS = _table(
    _BERRY_SPECS,
    _filler_start + len(FILLER_BALL_ITEMS) + len(MEDICINE_ITEMS) + len(FLUTE_ITEMS) + len(SHOAL_SHARD_ITEMS)
    + len(BATTLE_X_ITEMS) + len(REPEL_ITEMS) + len(MISC_TREASURE_ITEMS),
)
_filler_count = (
    len(FILLER_BALL_ITEMS) + len(MEDICINE_ITEMS) + len(FLUTE_ITEMS) + len(SHOAL_SHARD_ITEMS)
    + len(BATTLE_X_ITEMS) + len(REPEL_ITEMS) + len(MISC_TREASURE_ITEMS) + len(BERRY_ITEMS)
)

# ADDENDUM 99: appended after every other filler bucket rather than threaded into the cumulative-offset
# chain, so adding it touched no downstream `_filler_start + len(...)`.
FILLER_BALL_BUNDLE_ITEMS = _bundle_table(_FILLER_BALL_BUNDLE_SPECS, _filler_start + _filler_count)
_filler_count += len(FILLER_BALL_BUNDLE_ITEMS)

# Currency (ADDENDUM 361), its own category. `game_item_id` is None: Poke Coupons are not a Bag item but a
# u32 in the save block four bytes after money (ram_client.POKECOUPON_OFFSET, proved by a live write), so
# this is an AP-only EFFECT item like the trap and Client.py applies it rather than routing it to a pocket.
# Kept out of _MISC_TREASURE_SPECS for that reason. Frozen at 260.
POKECOUPON_ITEM_NAME = "5000 Poke Coupons"
POKECOUPON_ITEM_AMOUNT = 5000
_POKECOUPON_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    (POKECOUPON_ITEM_NAME, F, None, False),
]
POKECOUPON_ITEMS = _table(_POKECOUPON_SPECS, _filler_start + _filler_count)
_filler_count += len(POKECOUPON_ITEMS)

TRAP_ITEMS = _table(_TRAP_SPECS, _prog_count + _useful_count + _filler_count)

# MacGuffin (ADDENDUM 162): a count-based goal item, winnable once enough are collected. No
# `game_item_id`, like the travel unlocks -- the whole effect is logic plus the client's story-byte
# override. Its own category AFTER traps, because _table() hands out offsets by list position. Frozen 254.
MACGUFFIN_ITEM_NAME = "Robo Kyogre Part"
_MACGUFFIN_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    (MACGUFFIN_ITEM_NAME, P, None, False),
]
MACGUFFIN_ITEMS = _table(_MACGUFFIN_SPECS,
                         _prog_count + _useful_count + _filler_count + len(TRAP_ITEMS))

# Scooter Upgrade (ADDENDUM 273). SS Libra is TWO tiers behind one map icon (story_bytes.AREA_GROUPS): the
# stranded first visit at 0x4E and the real ship at 0x5A. The ladder names the step between them exactly
# (`0x57 -> 0x5A, "scooter upgraded in Gateon"`), so this item stands in for a real story event with a real
# byte, with location shuffle on or off. No `game_item_id` -- the upgrade is a cutscene -- which is also why
# it is NOT in game_data/key_items.py, where everything has a real id and feeds the Bag reconciler.
_SCOOTER_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    (SCOOTER_ITEM_NAME, P, None, False),
]
SCOOTER_ITEMS = _table(_SCOOTER_SPECS,
                       _prog_count + _useful_count + _filler_count + len(TRAP_ITEMS) + len(_MACGUFFIN_SPECS))

# ADDENDUM 302/336: items that exist to be ASKED FOR, never to be placed. `!getitem` resolves a name
# through `World.item_name_to_id`, built from ITEM_TABLE, so an item has to be IN the table to be
# requestable -- but being in the table is ordinarily also what puts it into seeds. This category threads
# that needle by being merged into ITEM_TABLE directly and into none of FILLER_ITEMS, USEFUL_ITEMS or the
# groups, and by being `filler`. It is in NO `ITEM_NAME_GROUPS` entry because a group name is itself
# resolvable by `!getitem`. The underlying ids are the ordinary Master Ball (1) and Rare Candy (68), so both
# route to their single-unit counterparts' pocket; sharing an id is fine, sharing a name would not be.
_GETITEM_ONLY_SPECS: list[tuple[str, ItemClassification, int | None, bool, int]] = [
    ("99 Master Balls", F, 1, True, 99),
    ("99 Rare Candies", F, 68, True, 99),
]
GETITEM_ONLY_ITEMS = _bundle_table(
    _GETITEM_ONLY_SPECS,
    _prog_count + _useful_count + _filler_count + len(TRAP_ITEMS) + len(_MACGUFFIN_SPECS) + len(_SCOOTER_SPECS),
)

#: The names no pool pass may ever draw. Consulted by the asserts below and by create_items' own guard.
GETITEM_ONLY_ITEM_NAMES: "frozenset[str]" = frozenset(GETITEM_ONLY_ITEMS)

KEY_ITEMS_ALL: dict[str, ItemData] = {**KEY_ITEMS, **MASTER_BALL_ITEM, **TRAVEL_UNLOCK_ITEMS}
USEFUL_ITEMS: dict[str, ItemData] = {
    **VITAMIN_ITEMS, **RARE_CANDY_PP_UP_ITEMS, **HELD_ITEMS, **HM_ITEMS,
}
FILLER_ITEMS: dict[str, ItemData] = {
    **FILLER_BALL_ITEMS, **MEDICINE_ITEMS, **FLUTE_ITEMS, **SHOAL_SHARD_ITEMS, **BATTLE_X_ITEMS,
    **REPEL_ITEMS, **MISC_TREASURE_ITEMS, **BERRY_ITEMS, **FILLER_BALL_BUNDLE_ITEMS,
    **TM_ITEMS, **STONE_ITEMS,   # ADDENDUM 311
    **POKECOUPON_ITEMS,          # ADDENDUM 361
}

ITEM_TABLE: dict[str, ItemData] = {
    **KEY_ITEMS_ALL,
    **USEFUL_ITEMS,
    **FILLER_ITEMS,
    **TRAP_ITEMS,
    **MACGUFFIN_ITEMS,
    **COMBINED_KEY_ITEMS,   # ADDENDUM 179
    **SCOOTER_ITEMS,        # ADDENDUM 273
    **GETITEM_ONLY_ITEMS,   # ADDENDUM 302 -- requestable, never placed
}

# STABLE ID FREEZE (ADDENDUM 26). Every id_offset above was, until this addendum, purely a function of LIST
# POSITION in the _SPECS lists, so each of this file's many edits silently RENUMBERED every item defined
# later. A generated multiworld has its ids baked in permanently; a client rebuilt against a newer copy of
# this file then resolves each shifted item to the wrong name or to none, which give_items() treats as "no
# known in-game item id -- nothing to write, but mark it received". The item never reaches the Bag, with no
# error anywhere.
#
# Fix: freeze every name's id_offset below (generated once from this file's own output, 2026-09-07). A
# brand-new name is auto-assigned above the current max -- paste it in immediately, or it drifts.
_FROZEN_ITEM_OFFSETS: dict[str, int] = {
    'Robo Kyogre Part': 254,
    'Krane Memo 1': 0,
    'Krane Memo 2': 1,
    'Krane Memo 3': 2,
    'Krane Memo 4': 3,
    'Krane Memo 5': 4,
    'Voice Case 1': 5,
    'Voice Case 2': 6,
    'Voice Case 3': 7,
    'Voice Case 4': 8,
    'Voice Case 5': 9,
    'Disc Case': 10,
    'Ein File S': 11,
    'Cologne Case': 12,
    'Data ROM': 13,
    'Elevator Key': 14,
    'Bonsly Card': 15,
    'Bonsly Photo': 16,
    'Cry Analyzer': 17,
    "Gonzap's Key": 18,
    'ID Card': 19,
    'Machine Part': 20,
    "Mayor's Note": 21,
    'Moon Shard': 22,
    'Miror Radar': 23,
    'Music Disc': 24,
    'Sun Shard': 25,
    'System Lever': 26,
    'Sun Stone': 27,
    'Moon Stone': 28,
    'Fire Stone': 29,
    'Thunder Stone': 30,
    'Water Stone': 31,
    'Leaf Stone': 32,
    'Master Ball': 33,
    'HP Up': 34,
    'Protein': 35,
    'Iron': 36,
    'Carbos': 37,
    'Calcium': 38,
    'Zinc': 39,
    'PP Max': 40,
    'Rare Candy': 41,
    'PP Up': 42,
    'BrightPowder': 43,
    'White Herb': 44,
    'Macho Brace': 45,
    'Exp. Share': 46,
    'Quick Claw': 47,
    'Soothe Bell': 48,
    'Mental Herb': 49,
    'Choice Band': 50,
    "King's Rock": 51,
    'SilverPowder': 52,
    'Amulet Coin': 53,
    'Cleanse Tag': 54,
    'Soul Dew': 55,
    'DeepSeaTooth': 56,
    'DeepSeaScale': 57,
    'Smoke Ball': 58,
    'Everstone': 59,
    'Focus Band': 60,
    'Lucky Egg': 61,
    'Scope Lens': 62,
    'Metal Coat': 63,
    'Leftovers': 64,
    'Dragon Scale': 65,
    'Light Ball': 66,
    'Soft Sand': 67,
    'Hard Stone': 68,
    'Miracle Seed': 69,
    'BlackGlasses': 70,
    'Black Belt': 71,
    'Magnet': 72,
    'Mystic Water': 73,
    'Sharp Beak': 74,
    'Poison Barb': 75,
    'NeverMeltIce': 76,
    'Spell Tag': 77,
    'TwistedSpoon': 78,
    'Charcoal': 79,
    'Dragon Fang': 80,
    'Silk Scarf': 81,
    'Up-Grade': 82,
    'Shell Bell': 83,
    'Sea Incense': 84,
    'Lax Incense': 85,
    'Lucky Punch': 86,
    'Metal Powder': 87,
    'Thick Club': 88,
    'Stick': 89,
    'TM01': 90,
    'TM02': 91,
    'TM03': 92,
    'TM04': 93,
    'TM05': 94,
    'TM06': 95,
    'TM07': 96,
    'TM08': 97,
    'TM09': 98,
    'TM10': 99,
    'TM11': 100,
    'TM12': 101,
    'TM13': 102,
    'TM14': 103,
    'TM15': 104,
    'TM16': 105,
    'TM17': 106,
    'TM18': 107,
    'TM19': 108,
    'TM20': 109,
    'TM21': 110,
    'TM22': 111,
    'TM23': 112,
    'TM24': 113,
    'TM25': 114,
    'TM26': 115,
    'TM27': 116,
    'TM28': 117,
    'TM29': 118,
    'TM30': 119,
    'TM31': 120,
    'TM32': 121,
    'TM33': 122,
    'TM34': 123,
    'TM35': 124,
    'TM36': 125,
    'TM37': 126,
    'TM38': 127,
    'TM39': 128,
    'TM40': 129,
    'TM41': 130,
    'TM42': 131,
    'TM43': 132,
    'TM44': 133,
    'TM45': 134,
    'TM46': 135,
    'TM47': 136,
    'TM48': 137,
    'TM49': 138,
    'TM50': 139,
    'HM01': 140,
    'HM02': 141,
    'HM03': 142,
    'HM04': 143,
    'HM05': 144,
    'HM06': 145,
    'HM07': 146,
    'HM08': 147,
    'Ultra Ball': 148,
    'Great Ball': 149,
    'Poke Ball': 150,
    'Safari Ball': 151,
    'Net Ball': 152,
    'Dive Ball': 153,
    'Nest Ball': 154,
    'Repeat Ball': 155,
    'Timer Ball': 156,
    'Luxury Ball': 157,
    'Premier Ball': 158,
    'Potion': 159,
    'Antidote': 160,
    'Burn Heal': 161,
    'Ice Heal': 162,
    'Awakening': 163,
    'Parlyz Heal': 164,
    'Full Restore': 165,
    'Max Potion': 166,
    'Hyper Potion': 167,
    'Super Potion': 168,
    'Full Heal': 169,
    'Revive': 170,
    'Max Revive': 171,
    'Fresh Water': 172,
    'Soda Pop': 173,
    'Lemonade': 174,
    'Moomoo Milk': 175,
    'Energy Powder': 176,
    'Energy Root': 177,
    'Heal Powder': 178,
    'Revival Herb': 179,
    'Ether': 180,
    'Max Ether': 181,
    'Elixir': 182,
    'Max Elixir': 183,
    'Lava Cookie': 184,
    'Berry Juice': 185,
    'Sacred Ash': 186,
    'Blue Flute': 187,
    'Yellow Flute': 188,
    'Red Flute': 189,
    'Black Flute': 190,
    'White Flute': 191,
    'Shoal Salt': 192,
    'Shoal Shell': 193,
    'Red Shard': 194,
    'Blue Shard': 195,
    'Yellow Shard': 196,
    'Green Shard': 197,
    'Guard Spec.': 198,
    'Dire Hit': 199,
    'X Attack': 200,
    'X Defend': 201,
    'X Speed': 202,
    'X Accuracy': 203,
    'X Special': 204,
    'Poke Doll': 205,
    'Fluffy Tail': 206,
    'Super Repel': 207,
    'Max Repel': 208,
    'Escape Rope': 209,
    'Repel': 210,
    'Tiny Mushroom': 211,
    'Big Mushroom': 212,
    'Pearl': 213,
    'Big Pearl': 214,
    'Stardust': 215,
    'Star Piece': 216,
    'Nugget': 217,
    'Heart Scale': 218,
    'Cheri Berry': 219,
    'Chesto Berry': 220,
    'Pecha Berry': 221,
    'Rawst Berry': 222,
    'Aspear Berry': 223,
    'Leppa Berry': 224,
    'Oran Berry': 225,
    'Persim Berry': 226,
    'Lum Berry': 227,
    'Sitrus Berry': 228,
    'Figy Berry': 229,
    'Wiki Berry': 230,
    'Mago Berry': 231,
    'Aguav Berry': 232,
    'Iapapa Berry': 233,
    'Razz Berry': 234,
    'Itemfinder Malfunction Trap': 235,
    '10 Poke Balls': 236,
    '5 Great Balls': 237,
    '3 Ultra Balls': 238,
    # ADDENDUM 104 -- pasted in immediately. Order matches travel_locations.TRAVEL_LOCATION_NAMES. Id 239
    # ("Travel Unlock - Gateon Port") retired (ADDENDUM 106): it moved to ALWAYS_OPEN_TRAVEL_BITS. Left
    # unassigned as a record -- a stale frozen entry is inert, _freeze_offsets iterates the CURRENT table.
    'Travel Unlock - Snagem Hideout': 240,
    'Travel Unlock - Outskirt Stand': 241,
    'Travel Unlock - Cave Poke Spot': 242,
    'Travel Unlock - Pyrite Town': 243,
    'Travel Unlock - Phenac City': 244,
    'Travel Unlock - Oasis Poke Spot': 245,
    'Travel Unlock - Realgam Tower': 246,
    'Travel Unlock - Cipher Key Lair': 247,  # was 'Cipher Key Lair'
    'Travel Unlock - Rockground Poke Spot': 248,
    "Travel Unlock - Kaminko's House": 249,
    'Travel Unlock - Cipher Lab': 250,
    'Travel Unlock - Mt. Battle': 251,
    'Travel Unlock - SS Libra': 252,
    'Travel Unlock - Orre Colosseum': 253,
    # ADDENDUM 270: the merged Poke Spots unlock (177) and the combined key item (179) slipped past the
    # paste-it-immediately convention. `next_free` starts at `max(frozen.values()) + 1` and counts in
    # ITEM_TABLE order, so both ids moved whenever anything above them changed. Frozen at the values they
    # currently RESOLVE to, not prettier ones: every seed since ADDENDUM 177 carries 255 for Poke Spots.
    'Travel Unlock - Poke Spots': 255,
    'Data ROM & ID Card': 256,
    'Scooter Upgrade': 257,       # frozen on the commit that added it
    '99 Master Balls': 258,       # frozen on the commit that added it
    '99 Rare Candies': 259,       # frozen on the commit that added it
    '5000 Poke Coupons': 260,     # frozen on the commit that added it
    #
    # Retired by ADDENDUM 177's merge, reserved so nothing can inherit them: 242 (Cave Poke Spot), 245 (Oasis
    # Poke Spot), 248 (Rockground Poke Spot). Their entries stay above, inert.
}


def _freeze_offsets(table: "dict[str, ItemData]", frozen: dict[str, int]) -> "dict[str, ItemData]":
    next_free = (max(frozen.values()) + 1) if frozen else 0
    result: dict[str, ItemData] = {}
    for name, data in table.items():
        offset = frozen[name] if name in frozen else next_free
        if name not in frozen:
            next_free += 1
        # ADDENDUM 179: companion_game_item_ids has to be carried through here too. Rebuilding ItemData
        # field by field silently drops every NEW field, which would reintroduce the Cipher Lab softlock.
        result[name] = ItemData(
            offset, data.classification, data.game_item_id, data.game_item_id_verified,
            quantity=data.quantity, companion_game_item_ids=data.companion_game_item_ids,
        )
    seen: dict[int, str] = {}
    for name, data in result.items():
        if data.id_offset in seen:
            raise RuntimeError(
                f"items.py: id_offset collision -- {name!r} and {seen[data.id_offset]!r} both resolved to "
                f"{data.id_offset}. Fix _FROZEN_ITEM_OFFSETS (this should never happen from ordinary edits)."
            )
        seen[data.id_offset] = name
    return result


ITEM_TABLE = _freeze_offsets(ITEM_TABLE, _FROZEN_ITEM_OFFSETS)


ITEM_NAME_GROUPS: dict[str, set[str]] = {
    "Krane Memos": set(KEY_ITEMS.keys()),
    "Voice Cases": {n for n in KEY_ITEMS if n.startswith("Voice Case")},
    "Evolution Stones": set(STONE_ITEMS.keys()),
    "Balls": {"Master Ball", *FILLER_BALL_ITEMS.keys()},
    "Currency": set(POKECOUPON_ITEMS.keys()),   # ADDENDUM 361
    "Vitamins": set(VITAMIN_ITEMS.keys()),
    "Held Items": set(HELD_ITEMS.keys()),
    "TMs": set(TM_ITEMS.keys()),
    "Berries": set(BERRY_ITEMS.keys()),
    "Travel Unlocks": set(TRAVEL_UNLOCK_ITEMS.keys()),
    "Robo Kyogre Parts": set(MACGUFFIN_ITEMS.keys()),
    "Scooter": set(SCOOTER_ITEMS.keys()),
}


def get_item_name_to_id(base_id: int) -> dict[str, int]:
    return {name: base_id + data.id_offset for name, data in ITEM_TABLE.items()}


def create_item(world, name: str) -> "PokemonXDItem":
    data = ITEM_TABLE[name]
    return PokemonXDItem(name, data.classification, world.item_name_to_id[name], world.player)


# Names eligible for random filler selection: true FILLER_ITEMS only. USEFUL_ITEMS are deliberately NOT in
# this pool -- per Fill.py's `distribute_items_restrictive` a `useful` item can only land on a DEFAULT or
# PRIORITY location, and this world's padding loop generates exactly `len(excludedlocations)` items, all of
# which must be true filler or generation dies with `FillError: Not enough filler items for excluded
# locations`. Measured: about half of 385 draws came back useful.
_RANDOM_FILLER_POOL: list[str] = list(FILLER_ITEMS.keys())
assert MACGUFFIN_ITEM_NAME not in _RANDOM_FILLER_POOL, (
    "the MacGuffin is progression and its count is set by an option -- it must never be drawn as filler"
)

# ADDENDUM 302. Four statements of one property, because it is a property of four separate passes that
# never mention each other: the filler draw, the two force-adds, and the group `!getitem` can resolve.
for _getitem_only in GETITEM_ONLY_ITEM_NAMES:
    assert _getitem_only not in _RANDOM_FILLER_POOL, (
        f"{_getitem_only!r} exists to be requested with !getitem -- it must never be drawn as filler"
    )
    assert ITEM_TABLE[_getitem_only].classification.name not in ("progression", "useful"), (
        f"{_getitem_only!r} must not be progression or useful -- create_items force-adds both, and this "
        "category exists precisely to stay out of every seed"
    )
    assert _getitem_only not in FILLER_ITEMS and _getitem_only not in USEFUL_ITEMS, (
        f"{_getitem_only!r} leaked into a source dict -- being outside all of them IS the mechanism"
    )
    # ADDENDUM 336: and not through a GROUP either -- `!getitem` resolves a group name too. Holds by
    # construction, asserted because that construction is in code which does not mention this.
    assert not any(_getitem_only in _members for _members in ITEM_NAME_GROUPS.values()), (
        f"{_getitem_only!r} is inside an item-name group, so `!getitem <group>` could draw it"
    )
del _getitem_only


# Filler weighting (ADDENDUM 150). The draw used to be flat over all 76 names, so a slot was as likely to be
# a Blue Flute as a Great Ball. In a game whose whole loop is SNAGGING, balls are the one category actually
# consumed. To drop a category entirely, delete it from its _SPECS list rather than weighting it to zero
# here, so the removal is visible where the item is defined. USEFUL_ITEM_MAX_COPIES caps the useful
# force-add: filling every DEFAULT slot with useful items would leave no filler at all.
USEFUL_ITEM_MAX_COPIES = 2

FILLER_WEIGHT_BALL = 10
FILLER_WEIGHT_HEALING = 4
FILLER_WEIGHT_ORDINARY = 1
FILLER_WEIGHT_DEPRIORITISED = 1

# Cures exactly one status condition and nothing else. Named individually rather than pattern-matched on
# "Heal" so that Full Heal/Full Restore (genuinely useful) are not swept up by a substring rule.
STATUS_HEAL_ITEM_NAMES: frozenset[str] = frozenset({
    "Antidote", "Burn Heal", "Ice Heal", "Awakening", "Parlyz Heal", "Heal Powder",
})


def _filler_weight(name: str) -> int:
    if name in FLUTE_ITEMS or name in STATUS_HEAL_ITEM_NAMES:
        return FILLER_WEIGHT_DEPRIORITISED
    if name in FILLER_BALL_ITEMS or name in FILLER_BALL_BUNDLE_ITEMS:
        return FILLER_WEIGHT_BALL
    if name in MEDICINE_ITEMS:
        return FILLER_WEIGHT_HEALING
    return FILLER_WEIGHT_ORDINARY


_RANDOM_FILLER_WEIGHTS: list[int] = [_filler_weight(name) for name in _RANDOM_FILLER_POOL]


# Filler categories (ADDENDUM 311) -- the per-category weights the player sets in their YAML. A weight is
# the CATEGORY's share, not a per-name weight: the draw picks a category by weight, then a name inside it
# uniformly, which is what makes "TMs: 15" mean about 15% of filler whether the category holds 6 names or
# 50. Weight 0 removes a category, the defaults sum to 100, and every filler name is in exactly one.
FILLER_CATEGORIES: "tuple[tuple[str, tuple[str, ...]], ...]" = (
    ("poke_balls", tuple(FILLER_BALL_ITEMS) + tuple(FILLER_BALL_BUNDLE_ITEMS)),
    ("medicine", tuple(n for n in MEDICINE_ITEMS if n not in STATUS_HEAL_ITEM_NAMES)),
    ("status_heals", tuple(n for n in MEDICINE_ITEMS if n in STATUS_HEAL_ITEM_NAMES)),
    ("berries", tuple(BERRY_ITEMS)),
    ("battle_items", tuple(BATTLE_X_ITEMS) + tuple(REPEL_ITEMS)),
    ("treasure", tuple(MISC_TREASURE_ITEMS) + tuple(SHOAL_SHARD_ITEMS)),
    ("flutes", tuple(FLUTE_ITEMS)),
    ("tms", tuple(TM_ITEMS)),
    ("evolution_stones", tuple(STONE_ITEMS)),
    # ADDENDUM 361: its own KIND of thing -- a currency write, not a Bag item. Small default share,
    # because one draw is a Mt. Battle prize tier on its own.
    ("currency", tuple(POKECOUPON_ITEMS)),
)
FILLER_CATEGORY_DEFAULT_WEIGHTS: "dict[str, int]" = {
    "poke_balls": 43, "medicine": 28, "status_heals": 2, "berries": 4, "battle_items": 2, "treasure": 2, "flutes": 1, "tms": 12, "evolution_stones": 4,
    "currency": 2,
}
assert sum(FILLER_CATEGORY_DEFAULT_WEIGHTS.values()) == 100, "the defaults read as percentages"
# Drawn when every category is weighted 0 -- generation must never fail over a filler preference.
FILLER_FALLBACK_ITEM_NAME = "Poke Ball"

_categorised = [name for _key, names in FILLER_CATEGORIES for name in names]
assert sorted(_categorised) == sorted(_RANDOM_FILLER_POOL), (
    "every filler item must be in exactly one filler category: "
    f"missing {sorted(set(_RANDOM_FILLER_POOL) - set(_categorised))}, "
    f"extra {sorted(set(_categorised) - set(_RANDOM_FILLER_POOL))}"
)
assert len(_categorised) == len(set(_categorised)), "a filler item sits in two categories"
assert set(FILLER_CATEGORY_DEFAULT_WEIGHTS) == {key for key, _names in FILLER_CATEGORIES}
del _categorised


def filler_category_weights(world) -> "dict[str, int]":
    """category key -> this seed's weight, read from `filler_weight_{key}`; the default when a world has no
    such option (a test double, or an options object built before ADDENDUM 311)."""
    options = getattr(world, "options", None)
    out: "dict[str, int]" = {}
    for key, _names in FILLER_CATEGORIES:
        option = getattr(options, f"filler_weight_{key}", None)
        out[key] = int(option.value) if option is not None else FILLER_CATEGORY_DEFAULT_WEIGHTS[key]
    return out


def get_random_filler_item_name(world) -> str:
    """Category by weight, then a name in it uniformly -- see FILLER CATEGORIES above. `world.random` is the
    world's own seeded RNG, so a seed stays reproducible."""
    weights = filler_category_weights(world)
    live = [(key, names) for key, names in FILLER_CATEGORIES if names and weights[key] > 0]
    if not live:
        return FILLER_FALLBACK_ITEM_NAME
    _key, names = world.random.choices(live, weights=[weights[key] for key, _n in live], k=1)[0]
    return world.random.choice(names)
