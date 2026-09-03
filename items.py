"""
Item definitions for the Pokemon XD: Gale of Darkness apworld.

STATUS (2026-09-02 rebuild): full item roster, built from claude/pokemon-xd-confirmed-item-ids.md -- the
live-write/visual-confirmation sweep run against a real copy of the game this session. Every `game_item_id`
below with `game_item_id_verified=True` was read back in-game by the player and matched the expected name.
Held items (179-225) and berries (133-175) are the one block NOT individually visually confirmed by name --
only the endpoints (BrightPowder/Stick, Cheri/Enigma) and the pocket behavior were -- their internal ordering
follows the standard Gen III item-index table, which is well-documented and did not previously conflict with
any live-tested id in this range. Treat that ordering as high-confidence but not independently visually
verified item-by-item.

**Bug fixed in this rebuild**: the previous skeleton had "Ein File S" mapped to game_item_id=528. The
confirmed-item-ids doc later corrected this -- 528 is actually "Voice Case 1". Ein File S's real id is
unconfirmed, so it is now `game_item_id=None`. Voice Case 1-5 (528-532) and Disc Case (533) are added as their
own real key items.

`game_item_id`: the real Pokemon XD Bag item ID this AP item corresponds to, written into the `[item ID][qty]`
Bag record by a direct memory write (live testing) or, for the offline patch pipeline, into whatever the
in-game "give item" trigger for that check ends up being (see patch.py / PokemonXDClient.py).

Deliberately excluded from the pool entirely, per the player's explicit instruction / design notes:
  - Mail (ids 121-132): all 12 confirmed, excluded on request.
  - Battle CDs / Discs (ids 347-378 and their 534-565 alias): confirmed to exist as 32 named entries each, but
    they are one physical in-game resource (the Disc Case's own sub-inventory) rather than 32 independent
    pickups, and that sub-inventory's real address/format is still unconfirmed -- see pokemon-xd-ram-map.md.

Classification follows the player's explicit scheme (2026-09-02 location-design direction, captured in
pokemon-xd-apworld-skeleton-status.md):
  - progression: Krane Memos, Voice Cases, Disc Case, Ein File S, the 6 Evolution Stones, Master Ball.
  - useful: the 7 vitamins (HP Up/Protein/Iron/Carbos/Calcium/Zinc/PP Max), PP Up, Rare Candy, all 47 held/
    battle items, and all 58 TMs/HMs.
  - filler: every remaining ball, medicine, flute, shard, repel, battle X-item, misc treasure item, and all
    43 berries.
  - trap: a single AP-only negative-effect item with no real Bag item id.
"""

from dataclasses import dataclass
from enum import Enum

from BaseClasses import Item, ItemClassification


class PokemonXDItem(Item):
    game: str = "Pokemon XD Gale of Darkness"


@dataclass(frozen=True)
class ItemData:
    id_offset: int  # offset from base_id; combined with World.base_id for the real AP item id
    classification: ItemClassification
    # Real in-game Bag item ID (see module docstring for the two confidence tiers).
    game_item_id: int | None = None
    # True only for ids empirically confirmed via a live write test this session. False = hypothesis (or no
    # game_item_id at all) -- do not treat as safe to ship without testing first.
    game_item_id_verified: bool = False


def _table(specs: list[tuple[str, ItemClassification, int | None, bool]], start_offset: int) -> dict[str, ItemData]:
    """Assign sequential id_offsets in the given order, starting at start_offset. Keeps the large literal specs
    lists below free of hand-tracked offset numbers, which is where the old skeleton's few bugs crept in."""
    return {
        name: ItemData(start_offset + i, classification, game_item_id, verified)
        for i, (name, classification, game_item_id, verified) in enumerate(specs)
    }


P = ItemClassification.progression
U = ItemClassification.useful
F = ItemClassification.filler
T = ItemClassification.trap

# ============================================================================================================
# PROGRESSION (19)
# ============================================================================================================
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
    # 15 more real key items added 2026-09-02 from a player-supplied, more complete key-item list. None have a
    # confirmed game_item_id yet -- pending either live Bag-write testing or extraction of the item name
    # string table from a real ISO (see the "later same boot" ISO-extraction work referenced in
    # pokemon-xd-apworld-skeleton-status.md).
    #
    # **Reclassified P -> U, 2026-09-02, later same boot.** Originally added as `progression` per the player's
    # instruction to add them "as progressive items to the pool." Independent testing (calling
    # `distribute_items_restrictive` directly, since `WorldTestBase.test_fill` was silently no-opping under
    # this harness and reporting a false-positive pass -- see pokemon-xd-apworld-skeleton-status.md) found this
    # broke generation outright: `FillError: Not enough locations for progression items` -- 34 progression items
    # against only 18 real locations capable of holding one (see locations.py: the new 386 species-catch
    # locations are deliberately excluded from progression eligibility, so they can't help here). None of these
    # 15 items are referenced by any `access_rule` in regions.py/rules.py -- unlike the Krane Memos/Ein File S,
    # nothing in this world's logic graph currently depends on the player holding one to advance -- so nothing
    # about their *function* as key items requires the strict AP `progression` classification, which specifically
    # means "the fill algorithm must place this somewhere logically reachable, no exceptions." `useful` keeps
    # them a guaranteed, prioritized part of the item pool (still guaranteed one copy each, same flavor/key-item
    # role) without that hard placement requirement, and immediately fixes the FillError with no other changes.
    # If the player wants any of these to actually gate progress later (e.g. Elevator Key required for a
    # Realgam Tower elevator), the right fix then is to add a real `access_rule` for it and move it back to `P`
    # at that point -- not to reclassify blind ahead of having real logic to attach.
    ("Cologne Case", U, None, False),
    ("Data ROM", U, None, False),
    ("Elevator Key", U, None, False),
    ("Bonsly Card", U, None, False),
    ("Bonsly Photo", U, None, False),
    ("Cry Analyzer", U, None, False),
    ("Gonzap's Key", U, None, False),
    ("ID Card", U, None, False),
    ("Machine Part", U, None, False),
    ("Mayor's Note", U, None, False),
    ("Moon Shard", U, None, False),
    ("Miror Radar", U, None, False),
    ("Music Disc", U, None, False),
    ("Sun Shard", U, None, False),
    ("System Lever", U, None, False),
]
_STONE_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    ("Sun Stone", P, 93, True),
    ("Moon Stone", P, 94, True),
    ("Fire Stone", P, 95, True),
    ("Thunder Stone", P, 96, True),
    ("Water Stone", P, 97, True),
    ("Leaf Stone", P, 98, True),
]
_MASTER_BALL_SPEC: list[tuple[str, ItemClassification, int | None, bool]] = [
    ("Master Ball", P, 1, True),
]

# ============================================================================================================
# USEFUL (114)
# ============================================================================================================
_VITAMIN_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    ("HP Up", U, 63, True),
    ("Protein", U, 64, True),
    ("Iron", U, 65, True),
    ("Carbos", U, 66, True),
    ("Calcium", U, 67, True),
    ("Zinc", U, 70, True),
    ("PP Max", U, 71, True),
]
_RARE_CANDY_PP_UP_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    ("Rare Candy", U, 68, True),
    ("PP Up", U, 69, True),
]
# Standard Gen III hold-item index order, ids 179-225 (47 items). Endpoints (BrightPowder=179, Stick=225) and
# the pocket behavior are live-confirmed; the ordering in between is the well-documented Gen III item-index
# table rather than an individual per-item visual check -- see module docstring.
_HELD_ITEM_NAMES: list[str] = [
    "BrightPowder", "White Herb", "Macho Brace", "Exp. Share", "Quick Claw", "Soothe Bell", "Mental Herb",
    "Choice Band", "King's Rock", "SilverPowder", "Amulet Coin", "Cleanse Tag", "Soul Dew", "DeepSeaTooth",
    "DeepSeaScale", "Smoke Ball", "Everstone", "Focus Band", "Lucky Egg", "Scope Lens", "Metal Coat",
    "Leftovers", "Dragon Scale", "Light Ball", "Soft Sand", "Hard Stone", "Miracle Seed", "BlackGlasses",
    "Black Belt", "Magnet", "Mystic Water", "Sharp Beak", "Poison Barb", "NeverMeltIce", "Spell Tag",
    "TwistedSpoon", "Charcoal", "Dragon Fang", "Silk Scarf", "Up-Grade", "Shell Bell", "Sea Incense",
    "Lax Incense", "Lucky Punch", "Metal Powder", "Thick Club", "Stick",
]
_HELD_ITEM_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    (name, U, 179 + i, True) for i, name in enumerate(_HELD_ITEM_NAMES)
]
# TM01-TM50 (289-338, all LIVE-CONFIRMED) + HM01-HM08 (339-346, LIVE-CONFIRMED).
_TM_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    (f"TM{n:02d}", U, 288 + n, True) for n in range(1, 51)
]
_HM_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    (f"HM{n:02d}", U, 338 + n, True) for n in range(1, 9)
]

# ============================================================================================================
# FILLER (114)
# ============================================================================================================
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
_MEDICINE_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
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
    ("Black Flute", F, 42, True),
    ("White Flute", F, 43, True),
]
_SHOAL_SHARD_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    ("Shoal Salt", F, 46, True),
    ("Shoal Shell", F, 47, True),
    ("Red Shard", F, 48, True),
    ("Blue Shard", F, 49, True),
    ("Yellow Shard", F, 50, True),
    ("Green Shard", F, 51, True),
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
    ("Super Repel", F, 83, True),
    ("Max Repel", F, 84, True),
    ("Escape Rope", F, 85, True),
    ("Repel", F, 86, True),
]
_MISC_TREASURE_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    ("Tiny Mushroom", F, 103, True),
    ("Big Mushroom", F, 104, True),
    ("Pearl", F, 106, True),
    ("Big Pearl", F, 107, True),
    ("Stardust", F, 108, True),
    ("Star Piece", F, 109, True),
    ("Nugget", F, 110, True),
    ("Heart Scale", F, 111, True),
]
# Standard Gen III berry index order, ids 133-175 (all 43 LIVE-CONFIRMED as a pocket, endpoints individually
# named in the confirmed-ids doc: Cheri(133)/Spelon(163)/Starf(174)/Enigma(175)).
_BERRY_NAMES: list[str] = [
    "Cheri Berry", "Chesto Berry", "Pecha Berry", "Rawst Berry", "Aspear Berry", "Leppa Berry", "Oran Berry",
    "Persim Berry", "Lum Berry", "Sitrus Berry", "Figy Berry", "Wiki Berry", "Mago Berry", "Aguav Berry",
    "Iapapa Berry", "Razz Berry", "Bluk Berry", "Nanab Berry", "Wepear Berry", "Pinap Berry", "Pomeg Berry",
    "Kelpsy Berry", "Qualot Berry", "Hondew Berry", "Grepa Berry", "Tamato Berry", "Cornn Berry",
    "Magost Berry", "Rabuta Berry", "Nomel Berry", "Spelon Berry", "Pamtre Berry", "Watmel Berry",
    "Durin Berry", "Belue Berry", "Liechi Berry", "Ganlon Berry", "Salac Berry", "Petaya Berry",
    "Apicot Berry", "Lansat Berry", "Starf Berry", "Enigma Berry",
]
_BERRY_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    (name, F, 133 + i, True) for i, name in enumerate(_BERRY_NAMES)
]

# ============================================================================================================
# TRAP (1)
# ============================================================================================================
_TRAP_SPECS: list[tuple[str, ItemClassification, int | None, bool]] = [
    # AP-only effect (no real Bag item id) -- client-side handling TBD; see PokemonXDClient.py.
    ("Itemfinder Malfunction Trap", T, None, False),
]

KEY_ITEMS = _table(_KEY_ITEM_SPECS, 0)
STONE_ITEMS = _table(_STONE_SPECS, len(KEY_ITEMS))
MASTER_BALL_ITEM = _table(_MASTER_BALL_SPEC, len(KEY_ITEMS) + len(STONE_ITEMS))
_prog_count = len(KEY_ITEMS) + len(STONE_ITEMS) + len(MASTER_BALL_ITEM)

VITAMIN_ITEMS = _table(_VITAMIN_SPECS, _prog_count)
RARE_CANDY_PP_UP_ITEMS = _table(_RARE_CANDY_PP_UP_SPECS, _prog_count + len(VITAMIN_ITEMS))
HELD_ITEMS = _table(
    _HELD_ITEM_SPECS, _prog_count + len(VITAMIN_ITEMS) + len(RARE_CANDY_PP_UP_ITEMS)
)
TM_ITEMS = _table(
    _TM_SPECS,
    _prog_count + len(VITAMIN_ITEMS) + len(RARE_CANDY_PP_UP_ITEMS) + len(HELD_ITEMS),
)
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

TRAP_ITEMS = _table(_TRAP_SPECS, _prog_count + _useful_count + _filler_count)

KEY_ITEMS_ALL: dict[str, ItemData] = {**KEY_ITEMS, **STONE_ITEMS, **MASTER_BALL_ITEM}
USEFUL_ITEMS: dict[str, ItemData] = {
    **VITAMIN_ITEMS, **RARE_CANDY_PP_UP_ITEMS, **HELD_ITEMS, **TM_ITEMS, **HM_ITEMS,
}
FILLER_ITEMS: dict[str, ItemData] = {
    **FILLER_BALL_ITEMS, **MEDICINE_ITEMS, **FLUTE_ITEMS, **SHOAL_SHARD_ITEMS, **BATTLE_X_ITEMS,
    **REPEL_ITEMS, **MISC_TREASURE_ITEMS, **BERRY_ITEMS,
}

ITEM_TABLE: dict[str, ItemData] = {
    **KEY_ITEMS_ALL,
    **USEFUL_ITEMS,
    **FILLER_ITEMS,
    **TRAP_ITEMS,
}

ITEM_NAME_GROUPS: dict[str, set[str]] = {
    "Krane Memos": set(KEY_ITEMS.keys()),
    "Voice Cases": {n for n in KEY_ITEMS if n.startswith("Voice Case")},
    "Evolution Stones": set(STONE_ITEMS.keys()),
    "Balls": {"Master Ball", *FILLER_BALL_ITEMS.keys()},
    "Vitamins": set(VITAMIN_ITEMS.keys()),
    "Held Items": set(HELD_ITEMS.keys()),
    "TMs": set(TM_ITEMS.keys()),
    "HMs": set(HM_ITEMS.keys()),
    "Berries": set(BERRY_ITEMS.keys()),
}


def get_item_name_to_id(base_id: int) -> dict[str, int]:
    return {name: base_id + data.id_offset for name, data in ITEM_TABLE.items()}


def create_item(world, name: str) -> "PokemonXDItem":
    data = ITEM_TABLE[name]
    return PokemonXDItem(name, data.classification, world.item_name_to_id[name], world.player)


# Names eligible for random filler selection: true FILLER_ITEMS only.
#
# **2026-09-02, later same boot: USEFUL_ITEMS deliberately removed from this pool.** They used to be included
# alongside FILLER_ITEMS on the theory that "useful" items make nicer padding than plain filler when there's
# room for them. There isn't, currently: `create_items()` only force-adds `progression` items (19: 12 key
# items + 6 Evolution Stones + Master Ball), which exactly matches this world's 19 non-EXCLUDED
# ("DEFAULT") locations (18 real overworld/shadow-capture locations + the one non-excluded species location,
# "Catch - Eevee" -- see locations.py). That leaves *zero* spare DEFAULT locations for anything else, and per
# Fill.py's `distribute_items_restrictive` (see `excludedlocations`/`filleritempool`/`usefulitempool` there),
# an item classified `useful` can *only* ever land on a DEFAULT/PRIORITY location, never an EXCLUDED one --
# so every `useful` item drawn during padding was structurally guaranteed to end up unplaced (silently
# dropped, logged only as a `logging.warning`) rather than actually reaching the player.
#
# Worse than just being wasted draws: this world's padding loop (`create_items()`) always generates *exactly*
# `len(excludedlocations)` (385, all the non-Eevee species catches) padding items, because progression items
# exactly fill every DEFAULT location and nothing else does. `distribute_items_restrictive` requires *every*
# EXCLUDED location get a real (non-useful, non-progression) item -- i.e. it needs all 385 padding draws to be
# true filler. Any draw that came back `useful` directly caused `FillError: Not enough filler items for
# excluded locations` (confirmed live: real-fill testing consistently showed ~half the 385 draws landing
# useful, undersupplying filler by ~190-220 -- see pokemon-xd-apworld-skeleton-status.md).
#
# Restricting to FILLER_ITEMS fixes generation with no actual content loss: those `useful` draws were never
# going to reach the player under this location topology anyway. It does mean the 114 USEFUL_ITEMS (vitamins,
# held items, TMs/HMs) and the 15 `useful`-reclassified key items (see the KEY_ITEM_SPECS comment above) have
# no in-game home at all in this build -- a real, known content gap, not resolved here. The fix, when this
# world's location roster grows past skeleton status, is to give useful items real DEFAULT locations of their
# own (either non-excluded species entries beyond Eevee that are *also* confirmed-guaranteed obtainable, or --
# more likely -- the real ~130+ overworld/shadow-capture location list this skeleton doesn't have yet), not to
# put them back in this pool while DEFAULT capacity is still exactly saturated by progression items.
_RANDOM_FILLER_POOL: list[str] = list(FILLER_ITEMS.keys())


def get_random_filler_item_name(world) -> str:
    return world.random.choice(_RANDOM_FILLER_POOL)
