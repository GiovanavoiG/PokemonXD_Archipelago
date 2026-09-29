"""
Location definitions for the Pokemon XD: Gale of Darkness apworld.

Overworld items are 48 field pickups from Bulbapedia's 8-part XD walkthrough -- not exhaustive, and never
cross-checked against an ISO extraction. Every other category (species catches,
purifications, chests, trainer defeats) is detected live by the client rather than by the player reaching a
place, so all of them are filed in an always-reachable region and marked EXCLUDED, and fill never needs one.
"Catch - Eevee" (GUARANTEED_SPECIES_LOCATION) is the single exception. A species with no path to being caught
this seed gets no location at all, unless the build has no Shadow census, which skips that trim.

Trainer-defeat detection is keyed on SURNAME, because an ordinary trainer's species are not globally unique
the way Shadow Pokemon are. It polls the battle roster for HP reaching zero and has never been confirmed
against a real multi-Pokemon ordinary-trainer battle, so whether that struct exposes a team larger than two at
once is still open.
"""

from dataclasses import dataclass

from BaseClasses import Location, LocationProgressType, Region

from . import species, trainer_defeat, travel_locations
from .game_data import missable_trainers, shops, trainer_placements, trainer_roster


class PokemonXDLocation(Location):
    game: str = "Pokemon XD Gale of Darkness"


@dataclass(frozen=True)
class LocationData:
    id_offset: int
    region: str


# The player's cap, not a game limit -- the real obtainable total is unconfirmed by this project.
PURIFICATION_LOCATION_COUNT = 32


def purification_location_name(count: int) -> str:
    """"Purify N Shadow Pokemon" for cumulative count N."""
    return f"Purify {count} Shadow Pokemon"


PURIFICATION_LOCATION_TO_COUNT: dict[str, int] = {
    purification_location_name(n): n for n in range(1, PURIFICATION_LOCATION_COUNT + 1)
}


# Per-chest locations (ADDENDUM 174), replacing the "Open N Chests" ladder. Keyed on CHEST ID and ROOM ID, both
# fixed in the ISO's treasure table; deliberately not the region name, since regions get revised and a location
# name freezes its id forever. Three filters leave exactly 90 chests: it must have an open flag (114 and 115
# have flag id 0); its room must not be in chest_regions.EXCLUDED_ROOMS (175 debug, 145 unknown); and its
# vanilla item must be below xd_rel_format.KEY_ITEM_ID_FLOOR, so the 24 key-item chests keep their real
# contents -- ADDENDUM 134 exists because overwriting the ID Card softlocked a live run.
from .game_data import chest_flags as _chest_flags
from .game_data import key_item_chests as _key_item_chests
from .game_data import chest_regions as _chest_regions
from .game_data import chest_names as _chest_names
from .game_data import chest_table as _chest_table
from .tools import xd_rel_format as _xd_rel_format


def _chest_location_rows() -> "tuple[tuple[tuple[int, ...], int, str], ...]":
    """((chest ids, room id, region), ...) -- one entry per AP chest location, chest id ascending.

    Ids are a tuple for historical reasons (the old 108/113 shared-flag merge); every entry holds one today.
    Built from the ISO-derived tables at import, so regenerating chest_table.py cannot leave this stale."""
    by_id = {chest["chest"]: chest for chest in _chest_table.CHESTS}
    # ADDENDUM 177: eligible UNCONDITIONALLY, since an id must not depend on a YAML setting. Whether they are
    # CREATED is decided in create_regions_and_locations.
    eligible = [
        chest_id for chest_id in sorted(by_id)
        if _chest_flags.chest_flag_id(chest_id) is not None
        and chest_id in _chest_regions.CHEST_TO_REGION
        and (by_id[chest_id]["item"] < _xd_rel_format.KEY_ITEM_ID_FLOOR
             or chest_id in _key_item_chests.SHUFFLED_KEY_ITEM_CHESTS)
    ]
    # 108 and 113 share flag id 1149, so they were merged while identity came from the flag array; identity is
    # (room, berry) since ADDENDUM 218. The flag-id filter stays -- it excludes the two room-175 debug chests.
    rows = []
    for chest_id in eligible:
        rows.append(((chest_id,), by_id[chest_id]["room"], _chest_regions.CHEST_TO_REGION[chest_id]))
    return tuple(rows)


CHEST_LOCATION_ROWS = _chest_location_rows()


def chest_location_name_for_ids(chest_ids: "tuple[int, ...]", room_id: int) -> str:
    """The stable location name for a chest (or, historically, a chest pair).

    Deliberately NOT named `chest_location_name`: that was the ladder's `count -> "Open N Chests"` helper, and
    counts 1..90 are also valid chest ids, so an old caller would keep working while meaning something else."""
    # Shared with ram_client.py -- see game_data/chest_names.py for why the table lives in neither caller.
    override = _chest_names.chest_location_name_override(chest_ids)
    if override is not None:
        return override
    if len(chest_ids) == 1:
        return f"Chest {chest_ids[0]} (Room {room_id})"
    return "Chest " + "+".join(str(c) for c in chest_ids) + f" (Room {room_id})"


CHEST_LOCATION_NAMES: "tuple[str, ...]" = tuple(
    chest_location_name_for_ids(ids, room) for ids, room, _region in CHEST_LOCATION_ROWS
)
_CHEST_LOCATION_NAME_SET = frozenset(CHEST_LOCATION_NAMES)

CHEST_LOCATION_TO_CHEST_IDS: "dict[str, tuple[int, ...]]" = {
    chest_location_name_for_ids(ids, room): ids for ids, room, _region in CHEST_LOCATION_ROWS
}
# chest id -> location name. Both members of a shared-flag pair map to the same name on purpose.
CHEST_ID_TO_LOCATION: "dict[int, str]" = {
    chest_id: chest_location_name_for_ids(ids, room)
    for ids, room, _region in CHEST_LOCATION_ROWS for chest_id in ids
}
CHEST_LOCATION_TO_REGION: "dict[str, str]" = {
    chest_location_name_for_ids(ids, room): region for ids, room, region in CHEST_LOCATION_ROWS
}

CHEST_LOCATION_COUNT = len(CHEST_LOCATION_NAMES)

# How many distinct chests those locations cover -- 90 eligible chests in the ISO's treasure table.
CHEST_COVERED_CHEST_COUNT = len(CHEST_ID_TO_LOCATION)


KEY_ITEM_CHEST_LOCATION_NAMES: "frozenset[str]" = frozenset(
    CHEST_ID_TO_LOCATION[_chest_id]
    for _chest_id in _key_item_chests.SHUFFLED_KEY_ITEM_CHESTS
    if _chest_id in CHEST_ID_TO_LOCATION
)


# ADDENDUM 386 (widening ADDENDUM 385): every SHINY chest is filler-only, not just the ID Card's.
#
# The chest table carries a model id and there are exactly two. Model 36 is the ordinary box, 90 of them.
# Model 68 is the shining object -- 25 of them, and the player's own name for one of these locations is
# "Bonsly Room Shiny Chest", which is where the word comes from. Only six model-68 objects are ever
# randomized at all: the five key-item chests ADDENDUM 177 punched through ADDENDUM 134's item-id floor,
# plus chest 30, whose vanilla contents are Leftovers and so never needed punching.
#
# TWO OF THOSE SIX HAVE INDEPENDENT FAILURE REPORTS and none of the 89 boxes has any. Chest 18 shines in the
# Cipher Lab and refuses to be interacted with; chest 30's check never fires. One theory covers both: the
# shining object does not read the ItemID this project patches, so chest 30 still hands out its Leftovers
# (no berry moves, so the berry trigger sees no pickup) and chest 18 still hands out its ID Card (which the
# player already holds from the packaged AP item, and the game will not give a key item twice, so the object
# goes dead). Unproven -- it needs a dump taken in one of those rooms -- but the class is the pattern.
#
# So none of the six may hold anything the seed needs. They remain real locations and still fire for anyone
# whose game does open them; EXCLUDED only stops fill from REQUIRING one.
#
# DERIVED FROM THE MODEL, never a typed list of ids: a chest that changes model, or a new model-68 object
# that becomes a location, is covered the day the table says so.
SHINY_CHEST_MODEL = 68
SHINY_CHEST_IDS: "tuple[int, ...]" = tuple(sorted(
    _entry["chest"] for _entry in _chest_table.CHESTS if _entry["model"] == SHINY_CHEST_MODEL
))
FILLER_ONLY_CHEST_LOCATIONS: "frozenset[str]" = frozenset(
    CHEST_ID_TO_LOCATION[_cid] for _cid in SHINY_CHEST_IDS if _cid in CHEST_ID_TO_LOCATION
)
assert FILLER_ONLY_CHEST_LOCATIONS, (
    "no shiny chest resolved to a location name, so this exclusion would silently do nothing"
)
# The ID Card chest is the one this started with (ADDENDUM 385); if the model ever stops catching it, that
# is a table change worth failing the import over rather than discovering in someone's seed.
assert CHEST_ID_TO_LOCATION[
    next(_c for _c, _i in _key_item_chests.SHUFFLED_KEY_ITEM_CHESTS.items() if _i == "ID Card")
] in FILLER_ONLY_CHEST_LOCATIONS, "the ID Card chest is no longer caught by the shiny-chest model"


def is_chest_location(location_name: str) -> bool:
    return location_name in _CHEST_LOCATION_NAME_SET


def is_key_item_chest_location(location_name: str) -> bool:
    return location_name in KEY_ITEM_CHEST_LOCATION_NAMES


# 232 is an ISO-extracted count: every ordinary trainer in data/deckdata_story_trainers.json, including
# the ~166 with no decoded display name. See trainer_defeat.py for why only 66 also get a named location.
TRAINER_DEFEAT_COUNT_LOCATION_COUNT = 232

# ADDENDUM 144: one location per roster entry (game_data/trainer_roster.py). In unique mode these REPLACE
# both the cumulative bucket and the 66 curated names -- one defeat must not fire two locations.
UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES: list[str] = [
    'Defeat - Hordel',
    'Defeat - Miror B. #1',
    'Defeat - Miror B. #2',
    'Defeat - Miror B. #3',
    'Defeat - Miror B. #4',
    'Defeat - Miror B. #5',
    'Defeat - Miror B. #6',
    'Defeat - Aferd #1',
    'Defeat - Zook #1',
    'Defeat - Ardos #1',
    'Defeat - Berk',
    'Defeat - Cyle',
    'Defeat - Bost',
    'Defeat - Kilen',
    'Defeat - Chobin #1',
    'Defeat - Laken #1',
    'Defeat - Naps #1',
    'Defeat - Chobin #2',
    'Defeat - Clerr #1',
    'Defeat - Belish #1',
    'Defeat - Cida #1',
    'Defeat - Dosk #1',
    'Defeat - Hebon #1',
    'Defeat - Gorps',
    'Defeat - Jols',
    'Defeat - Ladi',
    'Defeat - Cron',
    'Defeat - Eagun #1',
    'Defeat - Cida #2',
    'Defeat - Miru',
    'Defeat - Cridel',
    'Defeat - Bardo',
    'Defeat - Resix #1',
    'Defeat - Blusix #1',
    'Defeat - Browsix #1',
    'Defeat - Yellosix #1',
    'Defeat - Purpsix #1',
    'Defeat - Greesix #1',
    'Defeat - Resix #2',
    'Defeat - Blusix #2',
    'Defeat - Browsix #2',
    'Defeat - Yellosix #2',
    'Defeat - Purpsix #2',
    'Defeat - Greesix #2',
    'Defeat - Corla',
    'Defeat - Javion',
    'Defeat - Tekot',
    'Defeat - Mesak',
    'Defeat - Nexir',
    'Defeat - Solox',
    'Defeat - Digor',
    'Defeat - Crink',
    'Defeat - Morbit',
    'Defeat - Meda',
    'Defeat - Elrok',
    'Defeat - Coffy',
    'Defeat - Cabol',
    'Defeat - Nopia',
    'Defeat - Klots',
    'Defeat - Naps #2',
    'Defeat - Lovrina #1',
    'Defeat - Cail #1',
    'Defeat - Dobit #1',
    'Defeat - Finol #1',
    'Defeat - Dert #1',
    'Defeat - Raling #1',
    'Defeat - Labet #1',
    'Defeat - Doby #1',
    'Defeat - Aferd #2',
    'Defeat - Aferd #3',
    'Defeat - Laken #2',
    'Defeat - Miror B. #7',
    'Defeat - Rett',
    'Defeat - Mocor',
    'Defeat - Mesin',
    'Defeat - Elox',
    'Defeat - Rixor',
    'Defeat - Torkin',
    'Defeat - Dilly',
    'Defeat - Clerr #2',
    'Defeat - Belish #2',
    'Defeat - Dosk #2',
    'Defeat - Hebon #2',
    'Defeat - Lobar',
    'Defeat - Edlos',
    'Defeat - Feldas',
    'Defeat - Exol',
    'Defeat - Exinn',
    'Defeat - Gonrag',
    'Defeat - Cail #2',
    'Defeat - Pellim',
    'Defeat - Fenton',
    'Defeat - Forgs',
    'Defeat - Kapen',
    'Defeat - Ezoor',
    'Defeat - Ertlig',
    'Defeat - Greck',
    'Defeat - Eloin',
    'Defeat - Fasin',
    'Defeat - Fostin',
    'Defeat - Ezin',
    'Defeat - Faltly',
    'Defeat - Egrog',
    'Defeat - Snattle #1',
    'Defeat - Eroll #1',
    'Defeat - Equin #1',
    'Defeat - Finol #2',
    'Defeat - Dert #2',
    'Defeat - Raling #2',
    'Defeat - Labet #2',
    'Defeat - Doby #2',
    'Defeat - Resix #3',
    'Defeat - Blusix #3',
    'Defeat - Browsix #3',
    'Defeat - Yellosix #3',
    'Defeat - Purpsix #3',
    'Defeat - Greesix #3',
    'Defeat - Resix #4',
    'Defeat - Blusix #4',
    'Defeat - Browsix #4',
    'Defeat - Yellosix #4',
    'Defeat - Purpsix #4',
    'Defeat - Greesix #4',
    'Defeat - Chobin #3',
    'Defeat - Chobin #4',
    'Defeat - Cail #3',
    'Defeat - Chobin #5',
    'Defeat - Smarton #1',
    'Defeat - Quelor',
    'Defeat - Teslor',
    'Defeat - Nopel',
    'Defeat - Kalus',
    'Defeat - Justy',
    'Defeat - Miror B. #8',
    'Defeat - Willie #1',
    'Defeat - Fudlo',
    'Defeat - Gaply',
    'Defeat - Jinok',
    'Defeat - Agrev',
    'Defeat - Jedo',
    'Defeat - Golit',
    'Defeat - Hobble',
    'Defeat - Biden #1',
    'Defeat - Wakin',
    'Defeat - Gonzap',
    'Defeat - Aferd #4',
    'Defeat - Zook #2',
    'Defeat - Biden #2',
    'Defeat - Grezle',
    'Defeat - Humah',
    'Defeat - Ibsol',
    'Defeat - Kollo',
    'Defeat - Gorog',
    'Defeat - Jelstin',
    'Defeat - Lok',
    'Defeat - Kleto',
    'Defeat - Flipis',
    'Defeat - Targ',
    'Defeat - Hospel',
    'Defeat - Snidle',
    'Defeat - Fudler',
    'Defeat - Angic',
    'Defeat - Acrod',
    'Defeat - Smarton #2',
    'Defeat - Gorigan #1',
    'Defeat - Chobin #6',
    'Defeat - Chobin #7',
    'Defeat - Abson',
    'Defeat - Haben',
    'Defeat - Furgy',
    'Defeat - Golos',
    'Defeat - Jetsal',
    'Defeat - Lovrina #2',
    'Defeat - Bastil',
    'Defeat - Litnar',
    'Defeat - Grason',
    'Defeat - Grupel',
    'Defeat - Kimly',
    'Defeat - Nalix',
    'Defeat - Ibran',
    'Defeat - Kulig',
    'Defeat - Jargo',
    'Defeat - Kolest',
    'Defeat - Kolin',
    'Defeat - Karbon',
    'Defeat - Petro',
    'Defeat - Jaymi',
    'Defeat - Gromlet',
    'Defeat - Geftal',
    'Defeat - Leden',
    'Defeat - Snattle #2',
    'Defeat - Kleef',
    'Defeat - Ardos #2',
    'Defeat - Gorigan #2',
    'Defeat - Kolax',
    'Defeat - Eldes',
    'Defeat - Kaller',
    'Defeat - Loket',
    'Defeat - Greevil #1',
    'Defeat - Greevil #2',
    'Defeat - Greevil #3',
    'Defeat - Laken #3',
    'Defeat - Resix #5',
    'Defeat - Blusix #5',
    'Defeat - Browsix #5',
    'Defeat - Yellosix #5',
    'Defeat - Purpsix #5',
    'Defeat - Greesix #5',
    'Defeat - Resix #6',
    'Defeat - Blusix #6',
    'Defeat - Browsix #6',
    'Defeat - Yellosix #6',
    'Defeat - Purpsix #6',
    'Defeat - Greesix #6',
    'Defeat - Cail #4',
    'Defeat - Finol #3',
    'Defeat - Dert #3',
    'Defeat - Raling #3',
    'Defeat - Labet #3',
    'Defeat - Doby #3',
    'Defeat - Miror B. #9',
    'Defeat - Eagun #2',
    'Defeat - Aferd #5',
    'Defeat - Eroll #2',
    'Defeat - Equin #2',
    'Defeat - Willie #2',
    'Defeat - Cida #3',
    'Defeat - Clerr #3',
    'Defeat - Belish #3',
    'Defeat - Dosk #3',
    'Defeat - Hebon #3',
    'Defeat - Dobit #2',
]



def trainer_defeat_count_location_name(count: int) -> str:
    """"Defeat N Trainers" for cumulative count N. Incremented by ram_client.TrainerBattleDefeatTracker for
    every full-roster defeat it detects, named trainer or not."""
    return f"Defeat {count} Trainers"


# Krane memo story locations (ADDENDUM 153). The game hands all five over in the early story, so memo gating
# was decorative; the client now watches the story byte, clears the game's own copies out of the Key Items
# pocket at each threshold and sends these checks. Both regions chosen require ZERO memos to enter, or the
# first memo could have nowhere valid to be placed.
KRANE_MEMO_COUNT = 5

# Treated as ">=", not "==", so connecting mid-playthrough still awards everything already earned.
KRANE_MEMO_STORY_THRESHOLDS: dict[int, int] = {
    1: 0x10,
    2: 0x10,
    3: 0x17,
    4: 0x17,
    5: 0x17,
}


def krane_memo_location_name(memo_number: int) -> str:
    return f"Story - Krane Memo {memo_number}"


KRANE_MEMO_LOCATION_NAMES: list[str] = [
    krane_memo_location_name(n) for n in range(1, KRANE_MEMO_COUNT + 1)
]

# Cleared by the client once the check is sent. Mirrors items.py's KEY_ITEM_SPECS entries for Krane Memo
# 1-5 (523-527), duplicated rather than imported because ram_client.py cannot load items.py.
KRANE_MEMO_GAME_ITEM_IDS: dict[int, int] = {n: 522 + n for n in range(1, KRANE_MEMO_COUNT + 1)}


_UNIQUE_TRAINER_DEFEAT_NAME_SET: frozenset = frozenset(UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES)

# ADDENDUM 362: the list above is the ROSTER, all 232, and what the ids were frozen against; this is the subset
# still live in a seed. They differ by `trainer_roster.RETIRED_UNIQUE_DEFEAT_LOCATIONS`, today
# `Defeat - Chobin #7`, whose frozen id (1347) stays behind inert.
ACTIVE_UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES: list[str] = [
    _n for _n in UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES
    if _n not in trainer_roster.RETIRED_UNIQUE_DEFEAT_LOCATIONS
]

# ADDENDUM 175: regions for the per-trainer locations; the item half is rules.py's
# `_set_trainer_census_rules`. Names come from trainer_roster.trainer_label rather than being reassembled from
# the census -- string-assembly has silently un-fenced dozens of checks twice here.
_TRAINER_REGION_BY_LOCATION: "dict[str, str]" = {}
_UNPLACED_TRAINER_LOCATION_NAMES: "set[str]" = set()
for _index, _placement in trainer_placements.PLACEMENTS.items():
    _trainer = trainer_roster.TRAINERS_BY_INDEX.get(_index)
    if _trainer is None:
        continue
    _name = trainer_roster.trainer_label(_trainer)
    if _placement.region is None:
        _UNPLACED_TRAINER_LOCATION_NAMES.add(_name)
    else:
        _TRAINER_REGION_BY_LOCATION[_name] = _placement.region

assert len(_TRAINER_REGION_BY_LOCATION) + len(_UNPLACED_TRAINER_LOCATION_NAMES) == len(
    UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES
), "the census did not resolve one-to-one onto the roster's location names"

# Per-trainer defeat checks that can be permanently missed, so they must never hold a progression or useful
# item at any `ProgressionLocations` setting: the player's 47 missables, the 39 non-final occurrences of
# repeated story trainers (Mt. Battle's ladder is out of scope) and the 37 census rows marked N/A or blank. An
# unplaced trainer parks in the always-open "Unique Trainer Defeats" bucket, so an unexcluded one would read as
# sphere zero and could hold progression for a fight reached late or never.
_MISSABLE_TRAINER_LOCATION_NAMES: frozenset = frozenset(
    missable_trainers.filler_only_trainer_location_names()
) | frozenset(_UNPLACED_TRAINER_LOCATION_NAMES)


# ADDENDUM 185: the same fence for the 66 named locations, which were never fenced because the set above is
# only applied under `if is_unique_trainer_defeat`. A named location fires on the first win for its surname and
# cannot say which encounter that was, so if ANY row with that surname is missable it is filler-only -- which
# fences seven: the Phenac Sixes, Willie and Zook.
_MISSABLE_SURNAMES: frozenset = frozenset(
    trainer_roster.TRAINERS_BY_INDEX[_index]["name"].upper()
    for _index in missable_trainers.filler_only_trainer_indices()
    if _index in trainer_roster.TRAINERS_BY_INDEX
)

_MISSABLE_NAMED_TRAINER_LOCATIONS: frozenset = frozenset(
    _name for _region, _name, _surname in trainer_defeat.TRAINER_DEFEAT_ROSTER
    if _surname.upper() in _MISSABLE_SURNAMES
)


TRAINER_DEFEAT_COUNT_LOCATION_TO_COUNT: dict[str, int] = {
    trainer_defeat_count_location_name(n): n for n in range(1, TRAINER_DEFEAT_COUNT_LOCATION_COUNT + 1)
}


# Shop-purchase locations (ADDENDUM 110/111, named after SHOPS rather than berries since ADDENDUM 176). Every
# shop slot is patched to a distinct useless berry and buying one sends a check; ram_client.ShopPurchaseTracker
# watches each berry's Bag quantity, dispatches the next unfired occurrence and clears the slot. Names come
# from the live room id (ADDENDUM 142).
#
# game_data/shops.py's per-shop slot count is a CAP, not a census: ADDENDUM 127 found 21 marts in
# pocket_menu.rel against 10 shop rooms with no confirmed mapping, and Bulbapedia gives 117 lines less 3 Agate
# Scents and 6 Poke Snacks, so 108 randomizable slots. An inaccurate cap is survivable: these are EXCLUDED and
# filler-only, and a purchase still clears its dummy item either way.
SHOP_ITEM_BERRY_NAMES: list[str] = [
    "Razz Berry", "Bluk Berry", "Nanab Berry", "Wepear Berry", "Pinap Berry", "Pomeg Berry", "Kelpsy Berry",
    "Qualot Berry", "Hondew Berry", "Grepa Berry", "Tamato Berry", "Cornn Berry", "Magost Berry",
    "Nomel Berry", "Spelon Berry", "Pamtre Berry", "Watmel Berry", "Durin Berry", "Belue Berry",
    "Liechi Berry", "Ganlon Berry", "Salac Berry", "Petaya Berry", "Apicot Berry", "Lansat Berry",
    "Starf Berry",
    # "Enigma Berry" is deliberately absent (ADDENDUM 117, bugged in-game) -- in lockstep with
    # items.USELESS_BERRY_SPECS.
]

SHOP_ITEM_LOCATIONS: list[str] = list(shops.all_shop_location_names())
_SHOP_LOCATION_NAME_SET: frozenset = frozenset(SHOP_ITEM_LOCATIONS)

SHOP_LOCATION_TO_SHOP_AND_SLOT = shops.location_name_to_shop_and_slot()

# ADDENDUM 387: the shop RESTOCK lines are filler-only. Player: "Can we make all of the shop expansion items
# filler for now, they're inaccessible sometimes."
#
# A shop is a sequence of marts, not one shelf. The first mart is open the moment the room is; every later
# one introduces fresh lines when the story restocks it, and `rules.py` gates those on TIER_GATES. Thirteen
# locations are on that footing -- Gateon 7..15, Pyrite 11..12, Agate 8..9 -- and the gates are the least
# certain data in the shop model: the mart-to-room mapping is secondary (Bulbapedia, not a census of the
# ISO), Gateon's earlier tiers were deduced BY ELIMINATION rather than matched, and three of its lines are
# gated only because they share a mart with a line that is annotated. A gate that is too loose puts a check
# in logic before the restock that produces it, which is what "inaccessible sometimes" means from the
# player's side.
#
# So none of them may hold anything a seed needs. They stay real locations and still fire on purchase;
# EXCLUDED only stops fill from REQUIRING one. The tier rules in rules.py are deliberately LEFT IN PLACE --
# they still keep a restock line out of an early sphere, and removing them would be trading one wrong
# answer for another.
#
# Derived from the mart tiers, never a typed list: a shop that gains or loses a tier is covered the day
# `shop_stock.py` says so.
def _filler_only_shop_locations() -> "frozenset[str]":
    from .game_data import shop_stock

    out: "set[str]" = set()
    for shop in shops.CONFIRMED_SHOPS:
        entry = shop_stock.SHOP_MART_TIERS.get(shop.name)
        if entry is None:
            continue
        seen: "set[int]" = set()
        for index, mart in enumerate(entry["marts"]):
            numbers = set(shop_stock.MART_LINE_NUMBERS[mart])
            fresh = numbers - seen
            seen |= numbers
            # A tier that introduces nothing is an alias of an earlier one, not a restock.
            if index == 0 or not fresh:
                continue
            for number in sorted(fresh):
                name = shops.shop_location_name(shop.name, number)
                if name in SHOP_LOCATION_TO_SHOP_AND_SLOT:
                    out.add(name)
    return frozenset(out)


FILLER_ONLY_SHOP_LOCATIONS: "frozenset[str]" = _filler_only_shop_locations()
assert FILLER_ONLY_SHOP_LOCATIONS, (
    "no shop restock line resolved to a location name -- this exclusion would silently do nothing"
)
# An opening-shelf line must never be caught: those are reachable as soon as the room is, and sweeping them
# up would quietly strip the progression surface of every shop rather than of its restocks.
assert shops.shop_location_name("Gateon Port Shop", 1) not in FILLER_ONLY_SHOP_LOCATIONS
assert shops.shop_location_name("Mt. Battle Shop", 1) not in FILLER_ONLY_SHOP_LOCATIONS

SHOP_LOCATION_TO_REGION: "dict[str, str]" = {
    name: shop.region for name, (shop, _slot) in SHOP_LOCATION_TO_SHOP_AND_SLOT.items()
}

SHOP_LOCATION_COUNT = len(SHOP_ITEM_LOCATIONS)


def is_shop_location(location_name: str) -> bool:
    return location_name in _SHOP_LOCATION_NAME_SET


# ADDENDUM 82: one always-present location firing the first time ANY of the 5 real Eeveelutions is newly seen.
# The guaranteed Eevee evolves into exactly one of them and the other four may have no location this seed, so
# without this the player's choice would silently decide whether evolving it earns a check. Exempt from
# ADDENDUM 43's obtainable-species trim, but EXCLUDED: evolving needs a stone or high friendship.
EEVEELUTION_LOCATION_NAME = "Catch - Eeveelution (Any)"

# region name -> its locations, in order. New entries are APPENDED within each region's existing list, so
# no existing id_offset shifts.
LOCATIONS_BY_REGION: dict[str, list[str]] = {
    "Outskirt Stand": [
        "Outskirt Stand - Eevee Gift",  # story gift, not shuffled as a location reward; kept as a landmark event
        # Gateon Port is an early ferry ride from here, and Krane's HQ Lab is physically in Agate
        # Village but reached at the same very-early beat, so both are bucketed here.
        "Outskirt Stand - HQ Lab Potions",
        "Gateon Port - Krabby Club Basement Item",
        # 2026-09-03 verification: no "Post-Battle Revive" at Gateon Port; the real Revive is awarded in
        # Cipher Lab just after Cipher Peon Nexir.
        "Cipher Lab - Nexir Battle Revive",
        # Id 4 ("The Under - Cipher Peon Digor's Item") retired (ADDENDUM 104): "The Under" is not a real
        # reachable area in XD, unlike Colosseum. Never reassigned. Meda's Ether below is a second, distinct
        # Cipher Lab pickup found alongside Digor's.
        "Cipher Lab - Meda's Ether",
        # ADDENDUM 153 -- the two memos the game hands over at story byte 0x10.
        *[krane_memo_location_name(n) for n in (1, 2)],
    ],
    "Phenac City": [
        "Phenac City - Stadium Item",
        "Phenac City - Cologne's Item",
        "Phenac City - Behind the House",
        "Phenac City - Shop Ledge",
        # RENAMED 2026-09-03 per verification: this is an NPC-given Music Disc fetch-quest item, not a box.
        "Phenac City - Pre-Gym Building (Music Disc)",
        # ADDENDUM 153 -- the three memos the game hands over at story byte 0x17.
        *[krane_memo_location_name(n) for n in (3, 4, 5)],
    ],
    "Pyrite Town": [
        "Pyrite Town - Duel Square Item",
        # Id 62 ("The Under - Hidden Item") retired (ADDENDUM 104), never reassigned.
        "Pyrite Town - Jailhouse Item",
        "Pyrite Town - Grand Hotel Rightmost Room",
        "Pyrite Town - Grand Hotel Center Room",
        "Pyrite Town - Grand Hotel Leftmost Room",
        "Pyrite Town - Colosseum Bridge Box",
        "Pyrite Town - ONBS Third Floor Box",
    ],
    # ADDENDUM 184: the manor is walkable from the start but its contents are not -- chests open at story byte
    # 0x53 and the downstairs R&D lab at 0x55, both inside this region's 0x53-0x59 window. These two were
    # bucketed under Realgam Tower (0x41), five story transitions too early.
    "Kaminko's House (Robo Groudon)": [
        "Kaminko's House - Catwalk Diary Pages",
        "Kaminko's House - R&D Lab Basement",
    ],
    "Realgam Tower": [
        "Realgam Tower - Colosseum Clear Reward",
        # 2026-09-03 verification: no Sun Stone anywhere in the manor in two independent sources, so "Chobin's
        # Sun Stone" is gone. Real items are Jovi's diary pages on the catwalks and an Iron in the Libra box.
        "S.S. Libra - Entry Box (Iron)",
        "S.S. Libra - Box Puzzle Top",
        "S.S. Libra - Box Puzzle Bottom",
        # 2026-09-03: real item is a Max Ether; "Second" was ambiguous among four box-puzzle rooms in sequence.
        "S.S. Libra - Third Puzzle Box (Max Ether)",
        # SPLIT 2026-09-03: the final puzzle room actually holds two separate item boxes, not one.
        "S.S. Libra - Final Puzzle Box (Yellow Flute)",
        "S.S. Libra - Final Puzzle Box (TM Flamethrower)",
        "S.S. Libra - Bonsly's Item",
        "S.S. Libra - Bottom Right Box",
    ],
    "Agate Village": [
        "Agate Village - Eagun's Item",
        "Relic Forest - Hidden Item",
        "Agate Village - Entry Chest",
        "Agate Village - Eagun's Cave Ball",
        "Agate Village - Eagun's Cave Potion",
    ],
    "Cipher Key Lair": [
        "Cipher Key Lair - Admin Item",
        "Cipher Key Lair - 1F Center Room",
        "Cipher Key Lair - 1F Upper Left",
        "Cipher Key Lair - Jelstin's Chamber",
        "Cipher Key Lair - B1F South Room",
        "Cipher Key Lair - 2F Center Room",
        "Cipher Key Lair - 2F Bottom Left",
        "Cipher Key Lair - 2F Upper Left",
        "Cipher Key Lair - 3F Moon Door",
        "Cipher Key Lair - 3F Hallway",
        "Cipher Key Lair - 4F Hallway",
        "Cipher Key Lair - 4F Kleto's Room",
        "Cipher Key Lair - 5F Roof",
    ],
    "Citadark Isle": [
        "Citadark Isle - Pre-Boss Item",
        "Citadark Isle - After Furgy",
        "Citadark Isle - Bridge Ultra Balls",
        # 2026-09-03 verification: Citadark was under-represented at 2 boxes; filled out from the same
        # Part 7 source.
        "Citadark Isle - 1F Right Door Room",
        "Citadark Isle - B1F After Grason",
        "Citadark Isle - 2F First Block",
        "Citadark Isle - 2F Far Right Block",
        "Citadark Isle - 3F Near Nalix",
        "Citadark Isle - 3F After Hunter",
        "Citadark Isle - 3F Past Kulig and Jargo",
        "Citadark Isle - 3F-2 Entrance",
        "Citadark Isle - 4F Hidden Room",
        "Citadark Isle - 4F Spiral Path",
        "Citadark Isle - 4F Below Spiral Path",
        "Citadark Isle - 5F Timer Balls",
        "Citadark Isle - 6F Max Ethers",
        "Citadark Isle - 6F Max Revive",
        "Citadark Isle - 6F Full Heals",
        "Citadark Isle - 6F Revives",
        "Citadark Isle - Dome 1F Corner",
        # The event location that gates the win condition (see rules.py / __init__.py completion_condition).
        "Citadark Isle - Defeat Cipher Boss",
    ],
    # Added after the story regions so neither block shifts an existing id_offset.
    "Pokemon Storage": [species.location_name_for_species(n) for n in sorted(species.NATIONAL_DEX)] + [
        EEVEELUTION_LOCATION_NAME,
    ],
    "Shadow Pokemon Purification": [purification_location_name(n) for n in range(1, PURIFICATION_LOCATION_COUNT + 1)],
    # ADDENDUM 175: only the trainers whose region nobody knows -- 37 of the 232, all filler-only. Reachable
    # from the start so they can still receive filler, which AP requires of every location.
    "Unique Trainer Defeats": [
        _name for _name in UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES
        if _name in _UNPLACED_TRAINER_LOCATION_NAMES
    ],
    "Trainer Defeat Count": [
        trainer_defeat_count_location_name(n) for n in range(1, TRAINER_DEFEAT_COUNT_LOCATION_COUNT + 1)
    ],
}

# Travel-unlock locations (ADDENDUM 171). With travel randomization on the client HOLDS each destination's map
# bit clear until its item arrives, so the item grants the access and the story only grants the credit.
# Kaminko's House is absent: one of the four areas the player exempted, and it has no story window of its own.
# Mt. Battle's threshold resolves to 0x24, exactly the value the player quoted independently. EXCLUDED, since
# these fire off a story-byte watch and a seed with travel randomization off never fires them.
TRAVEL_UNLOCK_LOCATION_NAMES: list[str] = [
    travel_locations.travel_unlock_location_name(_name)
    for _name in travel_locations.TRAVEL_LOCATION_NAMES
    if travel_locations.vanilla_unlock_story_byte(_name) is not None
]

# ADDENDUM 356: filed where they are EARNED, not in a bucket off Menu. Each check goes one rung below the
# destination it names, which is where the game raises that icon; `unlock_predecessor_region` derives that from
# the same `area_unlock_floor` the threshold and the client's credit rule use. The old synthetic region is GONE
# rather than unused -- a bucket created here and never connected in regions.py is silently unreachable, which
# is how "Chest Opening" and "Shop Purchases" both regressed.
for _unlock_location in TRAVEL_UNLOCK_LOCATION_NAMES:
    _destination = _unlock_location[len(travel_locations.TRAVEL_UNLOCK_LOCATION_PREFIX):]
    _earned_in = travel_locations.unlock_predecessor_region(_destination)
    # travel_locations refuses a threshold with no predecessor at import; asserted again because a location
    # filed under "" would vanish from the graph rather than merely hold.
    assert _earned_in, f"{_unlock_location}: no predecessor region to file it under"
    LOCATIONS_BY_REGION.setdefault(_earned_in, []).append(_unlock_location)
del _unlock_location, _destination, _earned_in




# ADDENDUM 174: each chest is filed in the region that actually contains it, derived from its own room id in
# the ISO's treasure table -- the region IS the logic, where the retired ladder needed a modelled access rule.
for _chest_location_name, _chest_region in CHEST_LOCATION_TO_REGION.items():
    LOCATIONS_BY_REGION.setdefault(_chest_region, []).append(_chest_location_name)


# ADDENDUM 175: the same for the 195 trainers the census places. Filed in roster order so the generated
# id block below reads in census order.
for _trainer_location_name in UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES:
    _trainer_region = _TRAINER_REGION_BY_LOCATION.get(_trainer_location_name)
    if _trainer_region is not None:
        LOCATIONS_BY_REGION.setdefault(_trainer_region, []).append(_trainer_location_name)


# ADDENDUM 176: and the shops, by their room's own region -- a shop is in a town, so there is nothing
# synthetic left to park them in.
for _shop_location_name, _shop_region in SHOP_LOCATION_TO_REGION.items():
    LOCATIONS_BY_REGION.setdefault(_shop_region, []).append(_shop_location_name)


# ADDENDUM 169: re-bucket the named locations whose own names say where they are. Several were filed under
# "Outskirt Stand" from when that bucket WAS the always-open start, so once ADDENDUM 168 made it a LATE region,
# Gateon Port's and the HQ Lab's own items sat behind the whole key-item chain. Every id is pinned, so a move
# changes reachability and nothing else. The Krane Memo locations stay put: they fire off a bag check, so their
# region is a logic decision rather than a geographic fact.
_REBUCKET_BY_NAME: dict[str, str] = {
    "Outskirt Stand - Eevee Gift": "Pokemon HQ Lab",       # the starting gift, at the lab
    "Outskirt Stand - HQ Lab Potions": "Pokemon HQ Lab",
    "Gateon Port - Krabby Club Basement Item": "Gateon Port",
    "Cipher Lab - Nexir Battle Revive": "Cipher Lab",
    "Cipher Lab - Meda's Ether": "Cipher Lab",
    # ADDENDUM 189: these eight were under "Realgam Tower" (0x41) while the ship's own chests (30-38, rooms
    # 37-41) were already in "SS Libra". Phenac opens the stranded freighter at 0x4E and the real visit is 0x5A,
    # so logic believed half a vessel was reachable from the tournament on -- under key-item shuffle, a live
    # softlock.
    "S.S. Libra - Entry Box (Iron)": "SS Libra",
    "S.S. Libra - Box Puzzle Top": "SS Libra",
    "S.S. Libra - Box Puzzle Bottom": "SS Libra",
    "S.S. Libra - Third Puzzle Box (Max Ether)": "SS Libra",
    "S.S. Libra - Final Puzzle Box (Yellow Flute)": "SS Libra",
    "S.S. Libra - Final Puzzle Box (TM Flamethrower)": "SS Libra",
    "S.S. Libra - Bonsly's Item": "SS Libra",
    "S.S. Libra - Bottom Right Box": "SS Libra",
    # ADDENDUM 194, measured: on a travel-shuffle world with nothing collected, 132 locations are reachable --
    # 79 inside Agate/Gateon/Kaminko/HQ and 53 outside, of which 51 are EXCLUDED. A filler-only location HAS to
    # be reachable or AP has nowhere to put filler, so those are not leaks. The other two are Catch - Eevee (the
    # story gift handed over AT the HQ Lab) and the Eeveelution check, both inside the four; they sat in
    # "Pokemon Storage", the right bucket for a live trigger and the wrong answer to "where is this obtained".
}

# Resolved through the species helper rather than typed, so the names cannot drift from the generated table.
_REBUCKET_BY_NAME[species.location_name_for_species(133)] = "Pokemon HQ Lab"   # Catch - Eevee, the gift
_REBUCKET_BY_NAME[EEVEELUTION_LOCATION_NAME] = "Gateon Port"
for _name, _target in _REBUCKET_BY_NAME.items():
    for _bucket in LOCATIONS_BY_REGION.values():
        if _name in _bucket:
            _bucket.remove(_name)
            break
    LOCATIONS_BY_REGION.setdefault(_target, []).append(_name)


for _region_name, _location_names in trainer_defeat.TRAINER_DEFEAT_LOCATIONS_BY_REGION.items():
    LOCATIONS_BY_REGION[_region_name].extend(_location_names)

# ADDENDUM 252: one "Defeat X (Any)" per re-fightable trainer, added rather than replacing anything. An
# individual fight is missable or post-game; "any defeat" is earned by the first win, which is why these can
# hold progression when their occurrences cannot.
from .game_data import repeatable_trainers  # noqa: E402

for _region_name, _location_names in repeatable_trainers.LOCATIONS_BY_REGION.items():
    LOCATIONS_BY_REGION.setdefault(_region_name, []).extend(_location_names)

# Exact membership, never a prefix test -- see the `is_any_defeat` comment in create_regions_and_locations.
_ANY_DEFEAT_NAME_SET: "frozenset[str]" = frozenset(repeatable_trainers.LOCATION_NAMES)

# ADDENDUM 237/335: retire the Overworld Items that duplicate a per-chest location or were never real. The
# region lists above are left exactly as written, as the record of where these names came from; what changes is
# which of them reach the CURRENT table. `game_data/overworld_item_census.py` holds the census: 115 real
# treasure boxes exist, 95 are already AP chest locations, and 65 Overworld Items had no client detector at all.
#
# PLACED HERE, not beside the region buckets: later passes re-add names into LOCATIONS_BY_REGION, so a filter
# applied earlier is silently undone. This is the last point before the id table is built.
from .game_data.overworld_item_census import RETIRED_LOCATIONS  # noqa: E402

# ADDENDUM 362: the unique-mode labels with no distinct team left to earn them, now that `Defeat - X #N` fires
# on the Nth UNIQUE team -- today only `Defeat - Chobin #7`, whose occurrences 4 and 5 field identical teams.
from .game_data.trainer_roster import RETIRED_UNIQUE_DEFEAT_LOCATIONS  # noqa: E402

_RETIRED_LOCATION_NAMES: frozenset = RETIRED_LOCATIONS | RETIRED_UNIQUE_DEFEAT_LOCATIONS

assert not (RETIRED_LOCATIONS & RETIRED_UNIQUE_DEFEAT_LOCATIONS), (
    "a name is retired by both the overworld census and the unique-defeat derivation -- one of them is wrong "
    "about what it owns"
)

for _region_name, _region_locations in LOCATIONS_BY_REGION.items():
    LOCATIONS_BY_REGION[_region_name] = [
        _n for _n in _region_locations if _n not in _RETIRED_LOCATION_NAMES
    ]

_ALL_LOCATIONS: dict[str, LocationData] = {}
_offset = 0
for _region, _names in LOCATIONS_BY_REGION.items():
    for _name in _names:
        _ALL_LOCATIONS[_name] = LocationData(_offset, _region)
        _offset += 1

# The final "defeat the boss" location is an event: it has no numeric id and always holds the locked
# "Victory" event item (see __init__.py). Keep it out of the real id table.
EVENT_LOCATION_NAME = "Citadark Isle - Defeat Cipher Boss"
LOCATION_TABLE: dict[str, LocationData] = {
    name: data for name, data in _ALL_LOCATIONS.items() if name != EVENT_LOCATION_NAME
}

# STABLE ID FREEZE (ADDENDUM 26). `_offset` above is purely dict-iteration position over LOCATIONS_BY_REGION,
# and the trainer-defeat merge inserts 66 names INTO each story region's existing list rather than appending at
# the end, renumbering everything after each insertion point. A generated multiworld has its ids baked in
# permanently, so a client rebuilt against a newer copy of this file sends the WRONG id for the same name --
# either silently ignored or matching some other location. Fix, identical to items.py: freeze every name's
# id_offset below (generated once from this file's own output, 2026-09-07).
_FROZEN_LOCATION_OFFSETS: dict[str, int] = {
    'Outskirt Stand - Eevee Gift': 0,
    'Outskirt Stand - HQ Lab Potions': 1,
    'Gateon Port - Krabby Club Basement Item': 2,
    'Cipher Lab - Nexir Battle Revive': 3,
    # Id 4 ("The Under - Cipher Peon Digor's Item") retired (ADDENDUM 104). Left unassigned as a record:
    # a stale frozen entry is inert, since _freeze_offsets only iterates the CURRENT table.
    "Cipher Lab - Meda's Ether": 5,
    'Defeat - Cipher Admin Lovrina': 21,
    'Defeat - Wanderer Miror B. (rematch)': 22,
    'Defeat - Rider Willie': 23,
    'Phenac City - Stadium Item': 24,
    "Phenac City - Cologne's Item": 25,
    'Phenac City - Behind the House': 36,
    'Phenac City - Shop Ledge': 37,
    'Phenac City - Pre-Gym Building (Music Disc)': 38,
    'Defeat - Cipher Peon Exinn': 39,
    'Defeat - Cipher Peon Gonrag': 40,
    'Defeat - Cipher Peon Jirel': 41,
    'Defeat - Cipher Peon Resix': 42,
    'Defeat - Cipher Peon Purpsix': 43,
    'Defeat - Cipher Peon Greesix': 44,
    'Defeat - Cipher Peon Yellosix': 45,
    'Defeat - Cipher Peon Browsix': 46,
    'Defeat - Cipher Peon Trita': 47,
    'Defeat - Cipher Peon Kubara': 48,
    'Defeat - Cipher Peon Kuroru': 49,
    'Defeat - Cipher Peon Zanyu': 50,
    'Defeat - Cipher Peon Yaida': 51,
    'Defeat - Cipher Peon Rikoza': 52,
    'Defeat - Cipher Peon Eloin': 53,
    'Defeat - Cipher Peon Fasin': 54,
    'Defeat - Cipher Peon Fostin': 55,
    'Defeat - Cipher Peon Greck': 56,
    'Defeat - Cipher Peon Ezin': 57,
    'Defeat - Cipher Peon Faltly': 58,
    'Defeat - Cipher Peon Egrog': 59,
    'Defeat - Cipher Admin Snattle': 60,
    'Pyrite Town - Duel Square Item': 61,
    # Id 62 ("The Under - Hidden Item") retired 2026-09-09 (ADDENDUM 104) -- inert, see id 4 above.
    'Pyrite Town - Jailhouse Item': 69,
    'Pyrite Town - Grand Hotel Rightmost Room': 70,
    'Pyrite Town - Grand Hotel Center Room': 71,
    'Pyrite Town - Grand Hotel Leftmost Room': 72,
    'Pyrite Town - Colosseum Bridge Box': 73,
    'Pyrite Town - ONBS Third Floor Box': 74,
    'Defeat - Wanderer Miror B. (1st)': 75,
    'Defeat - Cipher Commander Exol': 76,
    'Defeat - Snagem Head Gonzap': 77,
    'Realgam Tower - Colosseum Clear Reward': 78,
    "Kaminko's House - Catwalk Diary Pages": 80,
    "Kaminko's House - R&D Lab Basement": 81,
    'S.S. Libra - Entry Box (Iron)': 82,
    'S.S. Libra - Box Puzzle Top': 83,
    'S.S. Libra - Box Puzzle Bottom': 84,
    'S.S. Libra - Third Puzzle Box (Max Ether)': 85,
    'S.S. Libra - Final Puzzle Box (Yellow Flute)': 86,
    'S.S. Libra - Final Puzzle Box (TM Flamethrower)': 87,
    "S.S. Libra - Bonsly's Item": 88,
    'S.S. Libra - Bottom Right Box': 89,
    'Defeat - Cipher Peon Smarton': 90,
    "Agate Village - Eagun's Item": 91,
    'Relic Forest - Hidden Item': 92,
    'Agate Village - Entry Chest': 94,
    "Agate Village - Eagun's Cave Ball": 95,
    "Agate Village - Eagun's Cave Potion": 96,
    'Defeat - Myth Trainer Eagun': 97,
    'Defeat - Researcher Chobin': 98,
    "Defeat - Robo Groudon (Chobin's mecha)": 99,
    'Cipher Key Lair - Admin Item': 100,
    'Cipher Key Lair - 1F Center Room': 115,
    'Cipher Key Lair - 1F Upper Left': 116,
    "Cipher Key Lair - Jelstin's Chamber": 117,
    'Cipher Key Lair - B1F South Room': 118,
    'Cipher Key Lair - 2F Center Room': 119,
    'Cipher Key Lair - 2F Bottom Left': 120,
    'Cipher Key Lair - 2F Upper Left': 121,
    'Cipher Key Lair - 3F Moon Door': 122,
    'Cipher Key Lair - 3F Hallway': 123,
    'Cipher Key Lair - 4F Hallway': 124,
    "Cipher Key Lair - 4F Kleto's Room": 125,
    'Cipher Key Lair - 5F Roof': 126,
    'Citadark Isle - Pre-Boss Item': 127,
    'Citadark Isle - After Furgy': 164,
    'Citadark Isle - Bridge Ultra Balls': 165,
    'Citadark Isle - 1F Right Door Room': 166,
    'Citadark Isle - B1F After Grason': 167,
    'Citadark Isle - 2F First Block': 168,
    'Citadark Isle - 2F Far Right Block': 169,
    'Citadark Isle - 3F Near Nalix': 170,
    'Citadark Isle - 3F After Hunter': 171,
    'Citadark Isle - 3F Past Kulig and Jargo': 172,
    'Citadark Isle - 3F-2 Entrance': 173,
    'Citadark Isle - 4F Hidden Room': 174,
    'Citadark Isle - 4F Spiral Path': 175,
    'Citadark Isle - 4F Below Spiral Path': 176,
    'Citadark Isle - 5F Timer Balls': 177,
    'Citadark Isle - 6F Max Ethers': 178,
    'Citadark Isle - 6F Max Revive': 179,
    'Citadark Isle - 6F Full Heals': 180,
    'Citadark Isle - 6F Revives': 181,
    'Citadark Isle - Dome 1F Corner': 182,
    'Defeat - Cipher Admin Gorigan': 184,
    'Defeat - Thug Zook': 185,
    'Defeat - Cipher Peon Smarton (Factory Control Room)': 186,
    'Defeat - Navigator Abson': 187,
    'Defeat - Cipher Peon Dimon': 188,
    'Defeat - Chaser Furgy': 189,
    'Defeat - Sailor Toronba': 190,
    'Defeat - Hunter Ransa': 191,
    'Defeat - Cipher Admin Lovrina (Citadark)': 192,
    'Defeat - Cipher Peon Berd': 193,
    'Defeat - Cipher Peon Litnar': 194,
    'Defeat - Cipher Peon Grupel': 195,
    'Defeat - Cipher Peon Fajo': 196,
    'Defeat - Hunter Ogera': 197,
    'Defeat - Cipher Peon Kolest': 198,
    'Defeat - Cipher Peon Uumo': 199,
    'Defeat - Chaser Carol': 200,
    'Defeat - Rider Fego': 201,
    'Defeat - Cipher Peon Antol': 202,
    'Defeat - Cipher Peon Karbon': 203,
    'Defeat - Cipher Peon Petro': 204,
    'Defeat - Cipher Peon Koral': 205,
    'Defeat - Cipher Peon Akante': 206,
    'Defeat - Cipher Peon Gefta': 207,
    'Defeat - Cipher Peon Leden': 208,
    'Defeat - Cipher Admin Snattle (Citadark)': 209,
    'Defeat - Cipher Peon Metring': 210,
    'Defeat - Cipher Admin Ardos': 211,
    'Defeat - Cipher Peon Stron': 212,
    'Defeat - Cipher Admin Gorigan (Citadark, final)': 213,
    'Defeat - Cipher Admin Eldes': 214,
    'Defeat - Legendary Trainer Eagun': 215,
    'Defeat - Wanderer Miror B. (final)': 216,
    'Defeat - Cipher Boss Greevil': 217,
    'Catch - Bulbasaur': 218,
    'Catch - Ivysaur': 219,
    'Catch - Venusaur': 220,
    'Catch - Charmander': 221,
    'Catch - Charmeleon': 222,
    'Catch - Charizard': 223,
    'Catch - Squirtle': 224,
    'Catch - Wartortle': 225,
    'Catch - Blastoise': 226,
    'Catch - Caterpie': 227,
    'Catch - Metapod': 228,
    'Catch - Butterfree': 229,
    'Catch - Weedle': 230,
    'Catch - Kakuna': 231,
    'Catch - Beedrill': 232,
    'Catch - Pidgey': 233,
    'Catch - Pidgeotto': 234,
    'Catch - Pidgeot': 235,
    'Catch - Rattata': 236,
    'Catch - Raticate': 237,
    'Catch - Spearow': 238,
    'Catch - Fearow': 239,
    'Catch - Ekans': 240,
    'Catch - Arbok': 241,
    'Catch - Pikachu': 242,
    'Catch - Raichu': 243,
    'Catch - Sandshrew': 244,
    'Catch - Sandslash': 245,
    'Catch - Nidoran-F': 246,
    'Catch - Nidorina': 247,
    'Catch - Nidoqueen': 248,
    'Catch - Nidoran-M': 249,
    'Catch - Nidorino': 250,
    'Catch - Nidoking': 251,
    'Catch - Clefairy': 252,
    'Catch - Clefable': 253,
    'Catch - Vulpix': 254,
    'Catch - Ninetales': 255,
    'Catch - Jigglypuff': 256,
    'Catch - Wigglytuff': 257,
    'Catch - Zubat': 258,
    'Catch - Golbat': 259,
    'Catch - Oddish': 260,
    'Catch - Gloom': 261,
    'Catch - Vileplume': 262,
    'Catch - Paras': 263,
    'Catch - Parasect': 264,
    'Catch - Venonat': 265,
    'Catch - Venomoth': 266,
    'Catch - Diglett': 267,
    'Catch - Dugtrio': 268,
    'Catch - Meowth': 269,
    'Catch - Persian': 270,
    'Catch - Psyduck': 271,
    'Catch - Golduck': 272,
    'Catch - Mankey': 273,
    'Catch - Primeape': 274,
    'Catch - Growlithe': 275,
    'Catch - Arcanine': 276,
    'Catch - Poliwag': 277,
    'Catch - Poliwhirl': 278,
    'Catch - Poliwrath': 279,
    'Catch - Abra': 280,
    'Catch - Kadabra': 281,
    'Catch - Alakazam': 282,
    'Catch - Machop': 283,
    'Catch - Machoke': 284,
    'Catch - Machamp': 285,
    'Catch - Bellsprout': 286,
    'Catch - Weepinbell': 287,
    'Catch - Victreebel': 288,
    'Catch - Tentacool': 289,
    'Catch - Tentacruel': 290,
    'Catch - Geodude': 291,
    'Catch - Graveler': 292,
    'Catch - Golem': 293,
    'Catch - Ponyta': 294,
    'Catch - Rapidash': 295,
    'Catch - Slowpoke': 296,
    'Catch - Slowbro': 297,
    'Catch - Magnemite': 298,
    'Catch - Magneton': 299,
    "Catch - Farfetch'd": 300,
    'Catch - Doduo': 301,
    'Catch - Dodrio': 302,
    'Catch - Seel': 303,
    'Catch - Dewgong': 304,
    'Catch - Grimer': 305,
    'Catch - Muk': 306,
    'Catch - Shellder': 307,
    'Catch - Cloyster': 308,
    'Catch - Gastly': 309,
    'Catch - Haunter': 310,
    'Catch - Gengar': 311,
    'Catch - Onix': 312,
    'Catch - Drowzee': 313,
    'Catch - Hypno': 314,
    'Catch - Krabby': 315,
    'Catch - Kingler': 316,
    'Catch - Voltorb': 317,
    'Catch - Electrode': 318,
    'Catch - Exeggcute': 319,
    'Catch - Exeggutor': 320,
    'Catch - Cubone': 321,
    'Catch - Marowak': 322,
    'Catch - Hitmonlee': 323,
    'Catch - Hitmonchan': 324,
    'Catch - Lickitung': 325,
    'Catch - Koffing': 326,
    'Catch - Weezing': 327,
    'Catch - Rhyhorn': 328,
    'Catch - Rhydon': 329,
    'Catch - Chansey': 330,
    'Catch - Tangela': 331,
    'Catch - Kangaskhan': 332,
    'Catch - Horsea': 333,
    'Catch - Seadra': 334,
    'Catch - Goldeen': 335,
    'Catch - Seaking': 336,
    'Catch - Staryu': 337,
    'Catch - Starmie': 338,
    'Catch - Mr. Mime': 339,
    'Catch - Scyther': 340,
    'Catch - Jynx': 341,
    'Catch - Electabuzz': 342,
    'Catch - Magmar': 343,
    'Catch - Pinsir': 344,
    'Catch - Tauros': 345,
    'Catch - Magikarp': 346,
    'Catch - Gyarados': 347,
    'Catch - Lapras': 348,
    'Catch - Ditto': 349,
    'Catch - Eevee': 350,
    'Catch - Vaporeon': 351,
    'Catch - Jolteon': 352,
    'Catch - Flareon': 353,
    'Catch - Porygon': 354,
    'Catch - Omanyte': 355,
    'Catch - Omastar': 356,
    'Catch - Kabuto': 357,
    'Catch - Kabutops': 358,
    'Catch - Aerodactyl': 359,
    'Catch - Snorlax': 360,
    'Catch - Articuno': 361,
    'Catch - Zapdos': 362,
    'Catch - Moltres': 363,
    'Catch - Dratini': 364,
    'Catch - Dragonair': 365,
    'Catch - Dragonite': 366,
    'Catch - Mewtwo': 367,
    'Catch - Mew': 368,
    'Catch - Chikorita': 369,
    'Catch - Bayleef': 370,
    'Catch - Meganium': 371,
    'Catch - Cyndaquil': 372,
    'Catch - Quilava': 373,
    'Catch - Typhlosion': 374,
    'Catch - Totodile': 375,
    'Catch - Croconaw': 376,
    'Catch - Feraligatr': 377,
    'Catch - Sentret': 378,
    'Catch - Furret': 379,
    'Catch - Hoothoot': 380,
    'Catch - Noctowl': 381,
    'Catch - Ledyba': 382,
    'Catch - Ledian': 383,
    'Catch - Spinarak': 384,
    'Catch - Ariados': 385,
    'Catch - Crobat': 386,
    'Catch - Chinchou': 387,
    'Catch - Lanturn': 388,
    'Catch - Pichu': 389,
    'Catch - Cleffa': 390,
    'Catch - Igglybuff': 391,
    'Catch - Togepi': 392,
    'Catch - Togetic': 393,
    'Catch - Natu': 394,
    'Catch - Xatu': 395,
    'Catch - Mareep': 396,
    'Catch - Flaaffy': 397,
    'Catch - Ampharos': 398,
    'Catch - Bellossom': 399,
    'Catch - Marill': 400,
    'Catch - Azumarill': 401,
    'Catch - Sudowoodo': 402,
    'Catch - Politoed': 403,
    'Catch - Hoppip': 404,
    'Catch - Skiploom': 405,
    'Catch - Jumpluff': 406,
    'Catch - Aipom': 407,
    'Catch - Sunkern': 408,
    'Catch - Sunflora': 409,
    'Catch - Yanma': 410,
    'Catch - Wooper': 411,
    'Catch - Quagsire': 412,
    'Catch - Espeon': 413,
    'Catch - Umbreon': 414,
    'Catch - Murkrow': 415,
    'Catch - Slowking': 416,
    'Catch - Misdreavus': 417,
    'Catch - Unown': 418,
    'Catch - Wobbuffet': 419,
    'Catch - Girafarig': 420,
    'Catch - Pineco': 421,
    'Catch - Forretress': 422,
    'Catch - Dunsparce': 423,
    'Catch - Gligar': 424,
    'Catch - Steelix': 425,
    'Catch - Snubbull': 426,
    'Catch - Granbull': 427,
    'Catch - Qwilfish': 428,
    'Catch - Scizor': 429,
    'Catch - Shuckle': 430,
    'Catch - Heracross': 431,
    'Catch - Sneasel': 432,
    'Catch - Teddiursa': 433,
    'Catch - Ursaring': 434,
    'Catch - Slugma': 435,
    'Catch - Magcargo': 436,
    'Catch - Swinub': 437,
    'Catch - Piloswine': 438,
    'Catch - Corsola': 439,
    'Catch - Remoraid': 440,
    'Catch - Octillery': 441,
    'Catch - Delibird': 442,
    'Catch - Mantine': 443,
    'Catch - Skarmory': 444,
    'Catch - Houndour': 445,
    'Catch - Houndoom': 446,
    'Catch - Kingdra': 447,
    'Catch - Phanpy': 448,
    'Catch - Donphan': 449,
    'Catch - Porygon2': 450,
    'Catch - Stantler': 451,
    'Catch - Smeargle': 452,
    'Catch - Tyrogue': 453,
    'Catch - Hitmontop': 454,
    'Catch - Smoochum': 455,
    'Catch - Elekid': 456,
    'Catch - Magby': 457,
    'Catch - Miltank': 458,
    'Catch - Blissey': 459,
    'Catch - Raikou': 460,
    'Catch - Entei': 461,
    'Catch - Suicune': 462,
    'Catch - Larvitar': 463,
    'Catch - Pupitar': 464,
    'Catch - Tyranitar': 465,
    'Catch - Lugia': 466,
    'Catch - Ho-Oh': 467,
    'Catch - Celebi': 468,
    'Catch - Treecko': 469,
    'Catch - Grovyle': 470,
    'Catch - Sceptile': 471,
    'Catch - Torchic': 472,
    'Catch - Combusken': 473,
    'Catch - Blaziken': 474,
    'Catch - Mudkip': 475,
    'Catch - Marshtomp': 476,
    'Catch - Swampert': 477,
    'Catch - Poochyena': 478,
    'Catch - Mightyena': 479,
    'Catch - Zigzagoon': 480,
    'Catch - Linoone': 481,
    'Catch - Wurmple': 482,
    'Catch - Silcoon': 483,
    'Catch - Beautifly': 484,
    'Catch - Cascoon': 485,
    'Catch - Dustox': 486,
    'Catch - Lotad': 487,
    'Catch - Lombre': 488,
    'Catch - Ludicolo': 489,
    'Catch - Seedot': 490,
    'Catch - Nuzleaf': 491,
    'Catch - Shiftry': 492,
    'Catch - Taillow': 493,
    'Catch - Swellow': 494,
    'Catch - Wingull': 495,
    'Catch - Pelipper': 496,
    'Catch - Ralts': 497,
    'Catch - Kirlia': 498,
    'Catch - Gardevoir': 499,
    'Catch - Surskit': 500,
    'Catch - Masquerain': 501,
    'Catch - Shroomish': 502,
    'Catch - Breloom': 503,
    'Catch - Slakoth': 504,
    'Catch - Vigoroth': 505,
    'Catch - Slaking': 506,
    'Catch - Nincada': 507,
    'Catch - Ninjask': 508,
    'Catch - Shedinja': 509,
    'Catch - Whismur': 510,
    'Catch - Loudred': 511,
    'Catch - Exploud': 512,
    'Catch - Makuhita': 513,
    'Catch - Hariyama': 514,
    'Catch - Azurill': 515,
    'Catch - Nosepass': 516,
    'Catch - Skitty': 517,
    'Catch - Delcatty': 518,
    'Catch - Sableye': 519,
    'Catch - Mawile': 520,
    'Catch - Aron': 521,
    'Catch - Lairon': 522,
    'Catch - Aggron': 523,
    'Catch - Meditite': 524,
    'Catch - Medicham': 525,
    'Catch - Electrike': 526,
    'Catch - Manectric': 527,
    'Catch - Plusle': 528,
    'Catch - Minun': 529,
    'Catch - Volbeat': 530,
    'Catch - Illumise': 531,
    'Catch - Roselia': 532,
    'Catch - Gulpin': 533,
    'Catch - Swalot': 534,
    'Catch - Carvanha': 535,
    'Catch - Sharpedo': 536,
    'Catch - Wailmer': 537,
    'Catch - Wailord': 538,
    'Catch - Numel': 539,
    'Catch - Camerupt': 540,
    'Catch - Torkoal': 541,
    'Catch - Spoink': 542,
    'Catch - Grumpig': 543,
    'Catch - Spinda': 544,
    'Catch - Trapinch': 545,
    'Catch - Vibrava': 546,
    'Catch - Flygon': 547,
    'Catch - Cacnea': 548,
    'Catch - Cacturne': 549,
    'Catch - Swablu': 550,
    'Catch - Altaria': 551,
    'Catch - Zangoose': 552,
    'Catch - Seviper': 553,
    'Catch - Lunatone': 554,
    'Catch - Solrock': 555,
    'Catch - Barboach': 556,
    'Catch - Whiscash': 557,
    'Catch - Corphish': 558,
    'Catch - Crawdaunt': 559,
    'Catch - Baltoy': 560,
    'Catch - Claydol': 561,
    'Catch - Lileep': 562,
    'Catch - Cradily': 563,
    'Catch - Anorith': 564,
    'Catch - Armaldo': 565,
    'Catch - Feebas': 566,
    'Catch - Milotic': 567,
    'Catch - Castform': 568,
    'Catch - Kecleon': 569,
    'Catch - Shuppet': 570,
    'Catch - Banette': 571,
    'Catch - Duskull': 572,
    'Catch - Dusclops': 573,
    'Catch - Tropius': 574,
    'Catch - Chimecho': 575,
    'Catch - Absol': 576,
    'Catch - Wynaut': 577,
    'Catch - Snorunt': 578,
    'Catch - Glalie': 579,
    'Catch - Spheal': 580,
    'Catch - Sealeo': 581,
    'Catch - Walrein': 582,
    'Catch - Clamperl': 583,
    'Catch - Huntail': 584,
    'Catch - Gorebyss': 585,
    'Catch - Relicanth': 586,
    'Catch - Luvdisc': 587,
    'Catch - Bagon': 588,
    'Catch - Shelgon': 589,
    'Catch - Salamence': 590,
    'Catch - Beldum': 591,
    'Catch - Metang': 592,
    'Catch - Metagross': 593,
    'Catch - Regirock': 594,
    'Catch - Regice': 595,
    'Catch - Registeel': 596,
    'Catch - Latias': 597,
    'Catch - Latios': 598,
    'Catch - Kyogre': 599,
    'Catch - Groudon': 600,
    'Catch - Rayquaza': 601,
    'Catch - Jirachi': 602,
    'Catch - Deoxys': 603,
    'Purify 1 Shadow Pokemon': 604,
    'Purify 2 Shadow Pokemon': 605,
    'Purify 3 Shadow Pokemon': 606,
    'Purify 4 Shadow Pokemon': 607,
    'Purify 5 Shadow Pokemon': 608,
    'Purify 6 Shadow Pokemon': 609,
    'Purify 7 Shadow Pokemon': 610,
    'Purify 8 Shadow Pokemon': 611,
    'Purify 9 Shadow Pokemon': 612,
    'Purify 10 Shadow Pokemon': 613,
    'Purify 11 Shadow Pokemon': 614,
    'Purify 12 Shadow Pokemon': 615,
    'Purify 13 Shadow Pokemon': 616,
    'Purify 14 Shadow Pokemon': 617,
    'Purify 15 Shadow Pokemon': 618,
    'Purify 16 Shadow Pokemon': 619,
    'Purify 17 Shadow Pokemon': 620,
    'Purify 18 Shadow Pokemon': 621,
    'Purify 19 Shadow Pokemon': 622,
    'Purify 20 Shadow Pokemon': 623,
    'Purify 21 Shadow Pokemon': 624,
    'Purify 22 Shadow Pokemon': 625,
    'Purify 23 Shadow Pokemon': 626,
    'Purify 24 Shadow Pokemon': 627,
    'Purify 25 Shadow Pokemon': 628,
    'Purify 26 Shadow Pokemon': 629,
    'Purify 27 Shadow Pokemon': 630,
    'Purify 28 Shadow Pokemon': 631,
    'Purify 29 Shadow Pokemon': 632,
    'Purify 30 Shadow Pokemon': 633,
    'Purify 31 Shadow Pokemon': 634,
    'Purify 32 Shadow Pokemon': 635,
    'Open 1 Chests': 636,
    'Open 2 Chests': 637,
    'Open 3 Chests': 638,
    'Open 4 Chests': 639,
    'Open 5 Chests': 640,
    'Open 6 Chests': 641,
    'Open 7 Chests': 642,
    'Open 8 Chests': 643,
    'Open 9 Chests': 644,
    'Open 10 Chests': 645,
    'Open 11 Chests': 646,
    'Open 12 Chests': 647,
    'Open 13 Chests': 648,
    'Open 14 Chests': 649,
    'Open 15 Chests': 650,
    'Open 16 Chests': 651,
    'Open 17 Chests': 652,
    'Open 18 Chests': 653,
    'Open 19 Chests': 654,
    'Open 20 Chests': 655,
    'Open 21 Chests': 656,
    'Open 22 Chests': 657,
    'Open 23 Chests': 658,
    'Open 24 Chests': 659,
    'Open 25 Chests': 660,
    'Open 26 Chests': 661,
    'Open 27 Chests': 662,
    'Open 28 Chests': 663,
    'Open 29 Chests': 664,
    'Open 30 Chests': 665,
    'Open 31 Chests': 666,
    'Open 32 Chests': 667,
    'Open 33 Chests': 668,
    'Open 34 Chests': 669,
    'Open 35 Chests': 670,
    'Open 36 Chests': 671,
    'Open 37 Chests': 672,
    'Open 38 Chests': 673,
    'Open 39 Chests': 674,
    'Open 40 Chests': 675,
    'Open 41 Chests': 676,
    'Open 42 Chests': 677,
    'Open 43 Chests': 678,
    'Open 44 Chests': 679,
    'Open 45 Chests': 680,
    'Open 46 Chests': 681,
    'Open 47 Chests': 682,
    'Open 48 Chests': 683,
    'Open 49 Chests': 684,
    'Open 50 Chests': 685,
    'Open 51 Chests': 686,
    'Open 52 Chests': 687,
    'Open 53 Chests': 688,
    'Open 54 Chests': 689,
    'Open 55 Chests': 690,
    'Open 56 Chests': 691,
    'Open 57 Chests': 692,
    'Open 58 Chests': 693,
    'Open 59 Chests': 694,
    'Open 60 Chests': 695,
    'Open 61 Chests': 696,
    'Open 62 Chests': 697,
    'Open 63 Chests': 698,
    'Open 64 Chests': 699,
    'Open 65 Chests': 700,
    'Open 66 Chests': 701,
    'Open 67 Chests': 702,
    'Open 68 Chests': 703,
    'Open 69 Chests': 704,
    'Open 70 Chests': 705,
    'Open 71 Chests': 706,
    'Open 72 Chests': 707,
    'Open 73 Chests': 708,
    'Open 74 Chests': 709,
    'Open 75 Chests': 710,
    'Open 76 Chests': 711,
    'Open 77 Chests': 712,
    'Open 78 Chests': 713,
    'Open 79 Chests': 714,
    'Open 80 Chests': 715,
    'Open 81 Chests': 716,
    'Open 82 Chests': 717,
    'Open 83 Chests': 718,
    'Open 84 Chests': 719,
    'Open 85 Chests': 720,
    'Open 86 Chests': 721,
    'Open 87 Chests': 722,
    'Open 88 Chests': 723,
    'Open 89 Chests': 724,
    'Open 90 Chests': 725,
    'Open 91 Chests': 726,
    'Open 92 Chests': 727,
    'Open 93 Chests': 728,
    'Open 94 Chests': 729,
    'Open 95 Chests': 730,
    'Open 96 Chests': 731,
    'Open 97 Chests': 732,
    'Open 98 Chests': 733,
    'Open 99 Chests': 734,
    'Open 100 Chests': 735,
    'Open 101 Chests': 736,
    'Open 102 Chests': 737,
    'Open 103 Chests': 738,
    'Open 104 Chests': 739,
    'Open 105 Chests': 740,
    'Open 106 Chests': 741,
    'Open 107 Chests': 742,
    'Open 108 Chests': 743,
    'Open 109 Chests': 744,
    'Open 110 Chests': 745,
    'Open 111 Chests': 746,
    'Open 112 Chests': 747,
    'Open 113 Chests': 748,
    'Open 114 Chests': 749,
    'Open 115 Chests': 750,
    'Defeat 1 Trainers': 751,
    'Defeat 2 Trainers': 752,
    'Defeat 3 Trainers': 753,
    'Defeat 4 Trainers': 754,
    'Defeat 5 Trainers': 755,
    'Defeat 6 Trainers': 756,
    'Defeat 7 Trainers': 757,
    'Defeat 8 Trainers': 758,
    'Defeat 9 Trainers': 759,
    'Defeat 10 Trainers': 760,
    'Defeat 11 Trainers': 761,
    'Defeat 12 Trainers': 762,
    'Defeat 13 Trainers': 763,
    'Defeat 14 Trainers': 764,
    'Defeat 15 Trainers': 765,
    'Defeat 16 Trainers': 766,
    'Defeat 17 Trainers': 767,
    'Defeat 18 Trainers': 768,
    'Defeat 19 Trainers': 769,
    'Defeat 20 Trainers': 770,
    'Defeat 21 Trainers': 771,
    'Defeat 22 Trainers': 772,
    'Defeat 23 Trainers': 773,
    'Defeat 24 Trainers': 774,
    'Defeat 25 Trainers': 775,
    'Defeat 26 Trainers': 776,
    'Defeat 27 Trainers': 777,
    'Defeat 28 Trainers': 778,
    'Defeat 29 Trainers': 779,
    'Defeat 30 Trainers': 780,
    'Defeat 31 Trainers': 781,
    'Defeat 32 Trainers': 782,
    'Defeat 33 Trainers': 783,
    'Defeat 34 Trainers': 784,
    'Defeat 35 Trainers': 785,
    'Defeat 36 Trainers': 786,
    'Defeat 37 Trainers': 787,
    'Defeat 38 Trainers': 788,
    'Defeat 39 Trainers': 789,
    'Defeat 40 Trainers': 790,
    'Defeat 41 Trainers': 791,
    'Defeat 42 Trainers': 792,
    'Defeat 43 Trainers': 793,
    'Defeat 44 Trainers': 794,
    'Defeat 45 Trainers': 795,
    'Defeat 46 Trainers': 796,
    'Defeat 47 Trainers': 797,
    'Defeat 48 Trainers': 798,
    'Defeat 49 Trainers': 799,
    'Defeat 50 Trainers': 800,
    'Defeat 51 Trainers': 801,
    'Defeat 52 Trainers': 802,
    'Defeat 53 Trainers': 803,
    'Defeat 54 Trainers': 804,
    'Defeat 55 Trainers': 805,
    'Defeat 56 Trainers': 806,
    'Defeat 57 Trainers': 807,
    'Defeat 58 Trainers': 808,
    'Defeat 59 Trainers': 809,
    'Defeat 60 Trainers': 810,
    'Defeat 61 Trainers': 811,
    'Defeat 62 Trainers': 812,
    'Defeat 63 Trainers': 813,
    'Defeat 64 Trainers': 814,
    'Defeat 65 Trainers': 815,
    'Defeat 66 Trainers': 816,
    'Defeat 67 Trainers': 817,
    'Defeat 68 Trainers': 818,
    'Defeat 69 Trainers': 819,
    'Defeat 70 Trainers': 820,
    'Defeat 71 Trainers': 821,
    'Defeat 72 Trainers': 822,
    'Defeat 73 Trainers': 823,
    'Defeat 74 Trainers': 824,
    'Defeat 75 Trainers': 825,
    'Defeat 76 Trainers': 826,
    'Defeat 77 Trainers': 827,
    'Defeat 78 Trainers': 828,
    'Defeat 79 Trainers': 829,
    'Defeat 80 Trainers': 830,
    'Defeat 81 Trainers': 831,
    'Defeat 82 Trainers': 832,
    'Defeat 83 Trainers': 833,
    'Defeat 84 Trainers': 834,
    'Defeat 85 Trainers': 835,
    'Defeat 86 Trainers': 836,
    'Defeat 87 Trainers': 837,
    'Defeat 88 Trainers': 838,
    'Defeat 89 Trainers': 839,
    'Defeat 90 Trainers': 840,
    'Defeat 91 Trainers': 841,
    'Defeat 92 Trainers': 842,
    'Defeat 93 Trainers': 843,
    'Defeat 94 Trainers': 844,
    'Defeat 95 Trainers': 845,
    'Defeat 96 Trainers': 846,
    'Defeat 97 Trainers': 847,
    'Defeat 98 Trainers': 848,
    'Defeat 99 Trainers': 849,
    'Defeat 100 Trainers': 850,
    'Defeat 101 Trainers': 851,
    'Defeat 102 Trainers': 852,
    'Defeat 103 Trainers': 853,
    'Defeat 104 Trainers': 854,
    'Defeat 105 Trainers': 855,
    'Defeat 106 Trainers': 856,
    'Defeat 107 Trainers': 857,
    'Defeat 108 Trainers': 858,
    'Defeat 109 Trainers': 859,
    'Defeat 110 Trainers': 860,
    'Defeat 111 Trainers': 861,
    'Defeat 112 Trainers': 862,
    'Defeat 113 Trainers': 863,
    'Defeat 114 Trainers': 864,
    'Defeat 115 Trainers': 865,
    'Defeat 116 Trainers': 866,
    'Defeat 117 Trainers': 867,
    'Defeat 118 Trainers': 868,
    'Defeat 119 Trainers': 869,
    'Defeat 120 Trainers': 870,
    'Defeat 121 Trainers': 871,
    'Defeat 122 Trainers': 872,
    'Defeat 123 Trainers': 873,
    'Defeat 124 Trainers': 874,
    'Defeat 125 Trainers': 875,
    'Defeat 126 Trainers': 876,
    'Defeat 127 Trainers': 877,
    'Defeat 128 Trainers': 878,
    'Defeat 129 Trainers': 879,
    'Defeat 130 Trainers': 880,
    'Defeat 131 Trainers': 881,
    'Defeat 132 Trainers': 882,
    'Defeat 133 Trainers': 883,
    'Defeat 134 Trainers': 884,
    'Defeat 135 Trainers': 885,
    'Defeat 136 Trainers': 886,
    'Defeat 137 Trainers': 887,
    'Defeat 138 Trainers': 888,
    'Defeat 139 Trainers': 889,
    'Defeat 140 Trainers': 890,
    'Defeat 141 Trainers': 891,
    'Defeat 142 Trainers': 892,
    'Defeat 143 Trainers': 893,
    'Defeat 144 Trainers': 894,
    'Defeat 145 Trainers': 895,
    'Defeat 146 Trainers': 896,
    'Defeat 147 Trainers': 897,
    'Defeat 148 Trainers': 898,
    'Defeat 149 Trainers': 899,
    'Defeat 150 Trainers': 900,
    'Defeat 151 Trainers': 901,
    'Defeat 152 Trainers': 902,
    'Defeat 153 Trainers': 903,
    'Defeat 154 Trainers': 904,
    'Defeat 155 Trainers': 905,
    'Defeat 156 Trainers': 906,
    'Defeat 157 Trainers': 907,
    'Defeat 158 Trainers': 908,
    'Defeat 159 Trainers': 909,
    'Defeat 160 Trainers': 910,
    'Defeat 161 Trainers': 911,
    'Defeat 162 Trainers': 912,
    'Defeat 163 Trainers': 913,
    'Defeat 164 Trainers': 914,
    'Defeat 165 Trainers': 915,
    'Defeat 166 Trainers': 916,
    'Defeat 167 Trainers': 917,
    'Defeat 168 Trainers': 918,
    'Defeat 169 Trainers': 919,
    'Defeat 170 Trainers': 920,
    'Defeat 171 Trainers': 921,
    'Defeat 172 Trainers': 922,
    'Defeat 173 Trainers': 923,
    'Defeat 174 Trainers': 924,
    'Defeat 175 Trainers': 925,
    'Defeat 176 Trainers': 926,
    'Defeat 177 Trainers': 927,
    'Defeat 178 Trainers': 928,
    'Defeat 179 Trainers': 929,
    'Defeat 180 Trainers': 930,
    'Defeat 181 Trainers': 931,
    'Defeat 182 Trainers': 932,
    'Defeat 183 Trainers': 933,
    'Defeat 184 Trainers': 934,
    'Defeat 185 Trainers': 935,
    'Defeat 186 Trainers': 936,
    'Defeat 187 Trainers': 937,
    'Defeat 188 Trainers': 938,
    'Defeat 189 Trainers': 939,
    'Defeat 190 Trainers': 940,
    'Defeat 191 Trainers': 941,
    'Defeat 192 Trainers': 942,
    'Defeat 193 Trainers': 943,
    'Defeat 194 Trainers': 944,
    'Defeat 195 Trainers': 945,
    'Defeat 196 Trainers': 946,
    'Defeat 197 Trainers': 947,
    'Defeat 198 Trainers': 948,
    'Defeat 199 Trainers': 949,
    'Defeat 200 Trainers': 950,
    'Defeat 201 Trainers': 951,
    'Defeat 202 Trainers': 952,
    'Defeat 203 Trainers': 953,
    'Defeat 204 Trainers': 954,
    'Defeat 205 Trainers': 955,
    'Defeat 206 Trainers': 956,
    'Defeat 207 Trainers': 957,
    'Defeat 208 Trainers': 958,
    'Defeat 209 Trainers': 959,
    'Defeat 210 Trainers': 960,
    'Defeat 211 Trainers': 961,
    'Defeat 212 Trainers': 962,
    'Defeat 213 Trainers': 963,
    'Defeat 214 Trainers': 964,
    'Defeat 215 Trainers': 965,
    'Defeat 216 Trainers': 966,
    'Defeat 217 Trainers': 967,
    'Defeat 218 Trainers': 968,
    'Defeat 219 Trainers': 969,
    'Defeat 220 Trainers': 970,
    'Defeat 221 Trainers': 971,
    'Defeat 222 Trainers': 972,
    'Defeat 223 Trainers': 973,
    'Defeat 224 Trainers': 974,
    'Defeat 225 Trainers': 975,
    'Defeat 226 Trainers': 976,
    'Defeat 227 Trainers': 977,
    'Defeat 228 Trainers': 978,
    'Defeat 229 Trainers': 979,
    'Defeat 230 Trainers': 980,
    'Defeat 231 Trainers': 981,
    'Defeat 232 Trainers': 982,
    # ADDENDUM 144 -- per-trainer defeat locations, ids 1181-1412
    'Defeat - Hordel': 1181,
    'Defeat - Miror B. #1': 1182,
    'Defeat - Miror B. #2': 1183,
    'Defeat - Miror B. #3': 1184,
    'Defeat - Miror B. #4': 1185,
    'Defeat - Miror B. #5': 1186,
    'Defeat - Miror B. #6': 1187,
    'Defeat - Aferd #1': 1188,
    'Defeat - Zook #1': 1189,
    'Defeat - Ardos #1': 1190,
    'Defeat - Berk': 1191,
    'Defeat - Cyle': 1192,
    'Defeat - Bost': 1193,
    'Defeat - Kilen': 1194,
    'Defeat - Chobin #1': 1195,
    'Defeat - Laken #1': 1196,
    'Defeat - Naps #1': 1197,
    'Defeat - Chobin #2': 1198,
    'Defeat - Clerr #1': 1199,
    'Defeat - Belish #1': 1200,
    'Defeat - Cida #1': 1201,
    'Defeat - Dosk #1': 1202,
    'Defeat - Hebon #1': 1203,
    'Defeat - Gorps': 1204,
    'Defeat - Jols': 1205,
    'Defeat - Ladi': 1206,
    'Defeat - Cron': 1207,
    'Defeat - Eagun #1': 1208,
    'Defeat - Cida #2': 1209,
    'Defeat - Miru': 1210,
    'Defeat - Cridel': 1211,
    'Defeat - Bardo': 1212,
    'Defeat - Resix #1': 1213,
    'Defeat - Blusix #1': 1214,
    'Defeat - Browsix #1': 1215,
    'Defeat - Yellosix #1': 1216,
    'Defeat - Purpsix #1': 1217,
    'Defeat - Greesix #1': 1218,
    'Defeat - Resix #2': 1219,
    'Defeat - Blusix #2': 1220,
    'Defeat - Browsix #2': 1221,
    'Defeat - Yellosix #2': 1222,
    'Defeat - Purpsix #2': 1223,
    'Defeat - Greesix #2': 1224,
    'Defeat - Corla': 1225,
    'Defeat - Javion': 1226,
    'Defeat - Tekot': 1227,
    'Defeat - Mesak': 1228,
    'Defeat - Nexir': 1229,
    'Defeat - Solox': 1230,
    'Defeat - Digor': 1231,
    'Defeat - Crink': 1232,
    'Defeat - Morbit': 1233,
    'Defeat - Meda': 1234,
    'Defeat - Elrok': 1235,
    'Defeat - Coffy': 1236,
    'Defeat - Cabol': 1237,
    'Defeat - Nopia': 1238,
    'Defeat - Klots': 1239,
    'Defeat - Naps #2': 1240,
    'Defeat - Lovrina #1': 1241,
    'Defeat - Cail #1': 1242,
    'Defeat - Dobit #1': 1243,
    'Defeat - Finol #1': 1244,
    'Defeat - Dert #1': 1245,
    'Defeat - Raling #1': 1246,
    'Defeat - Labet #1': 1247,
    'Defeat - Doby #1': 1248,
    'Defeat - Aferd #2': 1249,
    'Defeat - Aferd #3': 1250,
    'Defeat - Laken #2': 1251,
    'Defeat - Miror B. #7': 1252,
    'Defeat - Rett': 1253,
    'Defeat - Mocor': 1254,
    'Defeat - Mesin': 1255,
    'Defeat - Elox': 1256,
    'Defeat - Rixor': 1257,
    'Defeat - Torkin': 1258,
    'Defeat - Dilly': 1259,
    'Defeat - Clerr #2': 1260,
    'Defeat - Belish #2': 1261,
    'Defeat - Dosk #2': 1262,
    'Defeat - Hebon #2': 1263,
    'Defeat - Lobar': 1264,
    'Defeat - Edlos': 1265,
    'Defeat - Feldas': 1266,
    'Defeat - Exol': 1267,
    'Defeat - Exinn': 1268,
    'Defeat - Gonrag': 1269,
    'Defeat - Cail #2': 1270,
    'Defeat - Pellim': 1271,
    'Defeat - Fenton': 1272,
    'Defeat - Forgs': 1273,
    'Defeat - Kapen': 1274,
    'Defeat - Ezoor': 1275,
    'Defeat - Ertlig': 1276,
    'Defeat - Greck': 1277,
    'Defeat - Eloin': 1278,
    'Defeat - Fasin': 1279,
    'Defeat - Fostin': 1280,
    'Defeat - Ezin': 1281,
    'Defeat - Faltly': 1282,
    'Defeat - Egrog': 1283,
    'Defeat - Snattle #1': 1284,
    'Defeat - Eroll #1': 1285,
    'Defeat - Equin #1': 1286,
    'Defeat - Finol #2': 1287,
    'Defeat - Dert #2': 1288,
    'Defeat - Raling #2': 1289,
    'Defeat - Labet #2': 1290,
    'Defeat - Doby #2': 1291,
    'Defeat - Resix #3': 1292,
    'Defeat - Blusix #3': 1293,
    'Defeat - Browsix #3': 1294,
    'Defeat - Yellosix #3': 1295,
    'Defeat - Purpsix #3': 1296,
    'Defeat - Greesix #3': 1297,
    'Defeat - Resix #4': 1298,
    'Defeat - Blusix #4': 1299,
    'Defeat - Browsix #4': 1300,
    'Defeat - Yellosix #4': 1301,
    'Defeat - Purpsix #4': 1302,
    'Defeat - Greesix #4': 1303,
    'Defeat - Chobin #3': 1304,
    'Defeat - Chobin #4': 1305,
    'Defeat - Cail #3': 1306,
    'Defeat - Chobin #5': 1307,
    'Defeat - Smarton #1': 1308,
    'Defeat - Quelor': 1309,
    'Defeat - Teslor': 1310,
    'Defeat - Nopel': 1311,
    'Defeat - Kalus': 1312,
    'Defeat - Justy': 1313,
    'Defeat - Miror B. #8': 1314,
    'Defeat - Willie #1': 1315,
    'Defeat - Fudlo': 1316,
    'Defeat - Gaply': 1317,
    'Defeat - Jinok': 1318,
    'Defeat - Agrev': 1319,
    'Defeat - Jedo': 1320,
    'Defeat - Golit': 1321,
    'Defeat - Hobble': 1322,
    'Defeat - Biden #1': 1323,
    'Defeat - Wakin': 1324,
    'Defeat - Gonzap': 1325,
    'Defeat - Aferd #4': 1326,
    'Defeat - Zook #2': 1327,
    'Defeat - Biden #2': 1328,
    'Defeat - Grezle': 1329,
    'Defeat - Humah': 1330,
    'Defeat - Ibsol': 1331,
    'Defeat - Kollo': 1332,
    'Defeat - Gorog': 1333,
    'Defeat - Jelstin': 1334,
    'Defeat - Lok': 1335,
    'Defeat - Kleto': 1336,
    'Defeat - Flipis': 1337,
    'Defeat - Targ': 1338,
    'Defeat - Hospel': 1339,
    'Defeat - Snidle': 1340,
    'Defeat - Fudler': 1341,
    'Defeat - Angic': 1342,
    'Defeat - Acrod': 1343,
    'Defeat - Smarton #2': 1344,
    'Defeat - Gorigan #1': 1345,
    'Defeat - Chobin #6': 1346,
    'Defeat - Chobin #7': 1347,
    'Defeat - Abson': 1348,
    'Defeat - Haben': 1349,
    'Defeat - Furgy': 1350,
    'Defeat - Golos': 1351,
    'Defeat - Jetsal': 1352,
    'Defeat - Lovrina #2': 1353,
    'Defeat - Bastil': 1354,
    'Defeat - Litnar': 1355,
    'Defeat - Grason': 1356,
    'Defeat - Grupel': 1357,
    'Defeat - Kimly': 1358,
    'Defeat - Nalix': 1359,
    'Defeat - Ibran': 1360,
    'Defeat - Kulig': 1361,
    'Defeat - Jargo': 1362,
    'Defeat - Kolest': 1363,
    'Defeat - Kolin': 1364,
    'Defeat - Karbon': 1365,
    'Defeat - Petro': 1366,
    'Defeat - Jaymi': 1367,
    'Defeat - Gromlet': 1368,
    'Defeat - Geftal': 1369,
    'Defeat - Leden': 1370,
    'Defeat - Snattle #2': 1371,
    'Defeat - Kleef': 1372,
    'Defeat - Ardos #2': 1373,
    'Defeat - Gorigan #2': 1374,
    'Defeat - Kolax': 1375,
    'Defeat - Eldes': 1376,
    'Defeat - Kaller': 1377,
    'Defeat - Loket': 1378,
    'Defeat - Greevil #1': 1379,
    'Defeat - Greevil #2': 1380,
    'Defeat - Greevil #3': 1381,
    'Defeat - Laken #3': 1382,
    'Defeat - Resix #5': 1383,
    'Defeat - Blusix #5': 1384,
    'Defeat - Browsix #5': 1385,
    'Defeat - Yellosix #5': 1386,
    'Defeat - Purpsix #5': 1387,
    'Defeat - Greesix #5': 1388,
    'Defeat - Resix #6': 1389,
    'Defeat - Blusix #6': 1390,
    'Defeat - Browsix #6': 1391,
    'Defeat - Yellosix #6': 1392,
    'Defeat - Purpsix #6': 1393,
    'Defeat - Greesix #6': 1394,
    'Defeat - Cail #4': 1395,
    'Defeat - Finol #3': 1396,
    'Defeat - Dert #3': 1397,
    'Defeat - Raling #3': 1398,
    'Defeat - Labet #3': 1399,
    'Defeat - Doby #3': 1400,
    'Defeat - Miror B. #9': 1401,
    'Defeat - Eagun #2': 1402,
    'Defeat - Aferd #5': 1403,
    'Defeat - Eroll #2': 1404,
    'Defeat - Equin #2': 1405,
    'Defeat - Willie #2': 1406,
    'Defeat - Cida #3': 1407,
    'Defeat - Clerr #3': 1408,
    'Defeat - Belish #3': 1409,
    'Defeat - Dosk #3': 1410,
    'Defeat - Hebon #3': 1411,
    'Defeat - Dobit #2': 1412,
    # ADDENDUM 153 -- the five Krane Memo story locations, frozen on addition.
    'Story - Krane Memo 1': 1413,
    'Story - Krane Memo 2': 1414,
    'Story - Krane Memo 3': 1415,
    'Story - Krane Memo 4': 1416,
    'Story - Krane Memo 5': 1417,
    # ADDENDUM 110's 90 "Buy N Shop Items" names held ids 983-1072, retired by 111's per-berry redesign; the
    # range stays reserved rather than listed. 111's own 108 replacements start at the next free id, 1073.
    'Buy Shop Item - Razz Berry #1': 1073,
    'Buy Shop Item - Razz Berry #2': 1074,
    'Buy Shop Item - Razz Berry #3': 1075,
    'Buy Shop Item - Razz Berry #4': 1076,
    'Buy Shop Item - Bluk Berry #1': 1077,
    'Buy Shop Item - Bluk Berry #2': 1078,
    'Buy Shop Item - Bluk Berry #3': 1079,
    'Buy Shop Item - Bluk Berry #4': 1080,
    'Buy Shop Item - Nanab Berry #1': 1081,
    'Buy Shop Item - Nanab Berry #2': 1082,
    'Buy Shop Item - Nanab Berry #3': 1083,
    'Buy Shop Item - Nanab Berry #4': 1084,
    'Buy Shop Item - Wepear Berry #1': 1085,
    'Buy Shop Item - Wepear Berry #2': 1086,
    'Buy Shop Item - Wepear Berry #3': 1087,
    'Buy Shop Item - Wepear Berry #4': 1088,
    'Buy Shop Item - Pinap Berry #1': 1089,
    'Buy Shop Item - Pinap Berry #2': 1090,
    'Buy Shop Item - Pinap Berry #3': 1091,
    'Buy Shop Item - Pinap Berry #4': 1092,
    'Buy Shop Item - Pomeg Berry #1': 1093,
    'Buy Shop Item - Pomeg Berry #2': 1094,
    'Buy Shop Item - Pomeg Berry #3': 1095,
    'Buy Shop Item - Pomeg Berry #4': 1096,
    'Buy Shop Item - Kelpsy Berry #1': 1097,
    'Buy Shop Item - Kelpsy Berry #2': 1098,
    'Buy Shop Item - Kelpsy Berry #3': 1099,
    'Buy Shop Item - Kelpsy Berry #4': 1100,
    'Buy Shop Item - Qualot Berry #1': 1101,
    'Buy Shop Item - Qualot Berry #2': 1102,
    'Buy Shop Item - Qualot Berry #3': 1103,
    'Buy Shop Item - Qualot Berry #4': 1104,
    'Buy Shop Item - Hondew Berry #1': 1105,
    'Buy Shop Item - Hondew Berry #2': 1106,
    'Buy Shop Item - Hondew Berry #3': 1107,
    'Buy Shop Item - Hondew Berry #4': 1108,
    'Buy Shop Item - Grepa Berry #1': 1109,
    'Buy Shop Item - Grepa Berry #2': 1110,
    'Buy Shop Item - Grepa Berry #3': 1111,
    'Buy Shop Item - Grepa Berry #4': 1112,
    'Buy Shop Item - Tamato Berry #1': 1113,
    'Buy Shop Item - Tamato Berry #2': 1114,
    'Buy Shop Item - Tamato Berry #3': 1115,
    'Buy Shop Item - Tamato Berry #4': 1116,
    'Buy Shop Item - Cornn Berry #1': 1117,
    'Buy Shop Item - Cornn Berry #2': 1118,
    'Buy Shop Item - Cornn Berry #3': 1119,
    'Buy Shop Item - Cornn Berry #4': 1120,
    'Buy Shop Item - Magost Berry #1': 1121,
    'Buy Shop Item - Magost Berry #2': 1122,
    'Buy Shop Item - Magost Berry #3': 1123,
    'Buy Shop Item - Magost Berry #4': 1124,
    'Buy Shop Item - Nomel Berry #1': 1125,
    'Buy Shop Item - Nomel Berry #2': 1126,
    'Buy Shop Item - Nomel Berry #3': 1127,
    'Buy Shop Item - Nomel Berry #4': 1128,
    'Buy Shop Item - Spelon Berry #1': 1129,
    'Buy Shop Item - Spelon Berry #2': 1130,
    'Buy Shop Item - Spelon Berry #3': 1131,
    'Buy Shop Item - Spelon Berry #4': 1132,
    'Buy Shop Item - Pamtre Berry #1': 1133,
    'Buy Shop Item - Pamtre Berry #2': 1134,
    'Buy Shop Item - Pamtre Berry #3': 1135,
    'Buy Shop Item - Pamtre Berry #4': 1136,
    'Buy Shop Item - Watmel Berry #1': 1137,
    'Buy Shop Item - Watmel Berry #2': 1138,
    'Buy Shop Item - Watmel Berry #3': 1139,
    'Buy Shop Item - Watmel Berry #4': 1140,
    'Buy Shop Item - Durin Berry #1': 1141,
    'Buy Shop Item - Durin Berry #2': 1142,
    'Buy Shop Item - Durin Berry #3': 1143,
    'Buy Shop Item - Durin Berry #4': 1144,
    'Buy Shop Item - Belue Berry #1': 1145,
    'Buy Shop Item - Belue Berry #2': 1146,
    'Buy Shop Item - Belue Berry #3': 1147,
    'Buy Shop Item - Belue Berry #4': 1148,
    'Buy Shop Item - Liechi Berry #1': 1149,
    'Buy Shop Item - Liechi Berry #2': 1150,
    'Buy Shop Item - Liechi Berry #3': 1151,
    'Buy Shop Item - Liechi Berry #4': 1152,
    'Buy Shop Item - Ganlon Berry #1': 1153,
    'Buy Shop Item - Ganlon Berry #2': 1154,
    'Buy Shop Item - Ganlon Berry #3': 1155,
    'Buy Shop Item - Ganlon Berry #4': 1156,
    'Buy Shop Item - Salac Berry #1': 1157,
    'Buy Shop Item - Salac Berry #2': 1158,
    'Buy Shop Item - Salac Berry #3': 1159,
    'Buy Shop Item - Salac Berry #4': 1160,
    'Buy Shop Item - Petaya Berry #1': 1161,
    'Buy Shop Item - Petaya Berry #2': 1162,
    'Buy Shop Item - Petaya Berry #3': 1163,
    'Buy Shop Item - Petaya Berry #4': 1164,
    'Buy Shop Item - Apicot Berry #1': 1165,
    'Buy Shop Item - Apicot Berry #2': 1166,
    'Buy Shop Item - Apicot Berry #3': 1167,
    'Buy Shop Item - Apicot Berry #4': 1168,
    'Buy Shop Item - Lansat Berry #1': 1169,
    'Buy Shop Item - Lansat Berry #2': 1170,
    'Buy Shop Item - Lansat Berry #3': 1171,
    'Buy Shop Item - Lansat Berry #4': 1172,
    'Buy Shop Item - Starf Berry #1': 1173,
    'Buy Shop Item - Starf Berry #2': 1174,
    'Buy Shop Item - Starf Berry #3': 1175,
    'Buy Shop Item - Starf Berry #4': 1176,
    # Ids 1177-1180 ("Buy Shop Item - Enigma Berry #1".."#4") retired 2026-09-11 (ADDENDUM 117, bugged
    # in-game). Left listed and inert -- a stale frozen entry is never reassigned.
    'Buy Shop Item - Enigma Berry #1': 1177,
    'Buy Shop Item - Enigma Berry #2': 1178,
    'Buy Shop Item - Enigma Berry #3': 1179,
    'Buy Shop Item - Enigma Berry #4': 1180,
    # Ids 1181-1270: the 90 retired "Open N Chests" locations, reserved rather than listed. The fourteen
    # entries below had never been frozen and would have shifted on the next append.
    'Catch - Eeveelution (Any)': 1418,
    'Unlock - Snagem Hideout': 1419,
    'Unlock - Outskirt Stand': 1420,
    'Unlock - Cave Poke Spot': 1421,
    'Unlock - Pyrite Town': 1422,
    'Unlock - Phenac City': 1423,
    'Unlock - Oasis Poke Spot': 1424,
    'Unlock - Realgam Tower': 1425,
    'Unlock - Cipher Key Lair': 1426,  # was 'Cipher Key Lair'
    'Unlock - Rockground Poke Spot': 1427,
    'Unlock - Cipher Lab': 1428,
    'Unlock - Mt. Battle': 1429,
    'Unlock - SS Libra': 1430,
    'Unlock - Orre Colosseum': 1431,
    # ADDENDUM 177: the three separate Poke Spot unlocks (ids 1421, 1424, 1427) are inert -- one
    # 'Unlock - Poke Spots' replaces them, because the three spots were already ONE region. Never reissued.
    'Unlock - Poke Spots': 1641,
    # ADDENDUM 177: the five key-item chests that become checks under KeyItemShuffle. Ids are assigned
    # unconditionally -- an id must never depend on a YAML setting -- and only their CREATION is option-gated.
    'Music Disc Chest': 1642,  # was 'Chest 80 (Room 98)'
    'Cipher Key Lair 4F Chest 1': 1643,  # was 'Chest 42 (Room 67)'
    'Lovrina Defeat Item': 1644,  # was 'Cipher Lab Chest 1', was 'Chest 17 (Room 8)'
    'Cipher Lab Chest 2': 1645,  # was 'Chest 18 (Room 8)'
    "Mayor's House Upstairs Chest": 1646,  # was 'Chest 78 (Room 97)'
    # ADDENDUM 178: the slots past the retired flat cap of 12 -- Mt. Battle sells 18 randomizable lines and
    # Gateon Port 15. Shops that shrank keep their 1..12 ids and stop creating the tail names; nothing is
    # reissued, so a corrected count reclaims its own ids.
    'Gateon Port Shop AP Item 13': 1647,
    'Gateon Port Shop AP Item 14': 1648,
    'Gateon Port Shop AP Item 15': 1649,
    'Mt. Battle Shop AP Item 13': 1650,
    'Mt. Battle Shop AP Item 14': 1651,
    'Mt. Battle Shop AP Item 15': 1652,
    'Mt. Battle Shop AP Item 16': 1653,
    'Mt. Battle Shop AP Item 17': 1654,
    'Mt. Battle Shop AP Item 18': 1655,
# ADDENDUM 174: the per-chest locations that replaced the ladder, frozen the day they were created --
# the fourteen above are what happens when a category is added and left floating.
'Phenac City Chest 1': 1432,  # was 'Chest 87 (Room 100)'
    'Phenac City Chest 2': 1433,  # was 'Chest 88 (Room 100)'
    'Phenac Colosseum Chest 1': 1434,  # was 'Chest 89 (Room 107)'
    'Phenac Colosseum Chest 2': 1435,  # was 'Chest 90 (Room 107)'
    'Phenac Colosseum Chest 3': 1436,  # was 'Chest 91 (Room 107)'
    'Pyrite Town Chest': 1437,  # was 'Chest 93 (Room 119)'
    'Pyrite Town Jail Chest': 1438,  # was 'Chest 94 (Room 120)'
    'Pyrite Hotel Chest 1': 1439,  # was 'Chest 95 (Room 117)'
    'Pyrite Hotel Chest 2': 1440,  # was 'Chest 96 (Room 117)'
    'Pyrite Hotel Chest 3': 1441,  # was 'Chest 97 (Room 117)'
    'Realgam Tower Outside Chest': 1442,  # was 'Chest 39 (Room 58)'
    'Realgam Tower Crossroads Chest': 1443,  # was 'Chest 40 (Room 49)'
    'Realgam Tower Main Hall Chest': 1444,  # was 'Chest 41 (Room 59)'
    'Agate Bridge Chest': 1445,  # was 'Chest 10 (Room 132)'
    'Agate Right Side Chest': 1446,  # was 'Chest 11 (Room 132)'
    'Agate Cave Chest 1': 1447,  # was 'Chest 12 (Room 126)'
    'Agate Cave Chest 2': 1448,  # was 'Chest 13 (Room 126)'
    "Behind Eagun's House Chest": 1449,  # was 'Chest 14 (Room 132)'
    'Agate Relic Path Chest': 1450,  # was 'Chest 15 (Room 125)'
    'Cipher Key Lair 1F Chest 1': 1451,  # was 'Chest 43 (Room 64)'
    'Cipher Key Lair 1F Chest 2': 1452,  # was 'Chest 44 (Room 64)'
    'Cipher Key Lair 2F Chest 1': 1453,  # was 'Chest 45 (Room 65)'
    'Cipher Key Lair 2F Chest 2': 1454,  # was 'Chest 46 (Room 65)'
    'Cipher Key Lair 3F Chest 1': 1455,  # was 'Chest 47 (Room 66)'
    'Cipher Key Lair Roof Chest': 1456,  # was 'Chest 48 (Room 70)'
    'Cipher Key Lair 1F Chest 3': 1457,  # was 'Chest 49 (Room 64)'
    'Cipher Key Lair 2F Chest 3': 1458,  # was 'Chest 50 (Room 65)'
    'Cipher Key Lair 3F Chest 2': 1459,  # was 'Chest 51 (Room 66)'
    'Cipher Key Lair 4F Chest 2': 1460,  # was 'Chest 52 (Room 67)'
    'Cipher Key Lair 4F Shiny Chest': 1461,  # was 'Chest 53 (Room 67)'
    'Cipher Key Lair Basement Chest': 1462,  # was '... 5F Chest', was 'Chest 54 (Room 68)'
    'Cipher Key Lair 1F Chest 4': 1463,  # was 'Chest 56 (Room 64)'
    'Citadark Isle Chest 10': 1464,  # was 'Chest 57 (Room 82)'
    'Citadark Isle Chest 19': 1465,  # was 'Chest 58 (Room 88)'
    'Citadark Isle Chest 2': 1466,  # was 'Chest 59 (Room 76)'
    'Citadark Isle Chest 3': 1467,  # was 'Chest 60 (Room 77)'
    'Citadark Isle Chest 4': 1468,  # was 'Chest 61 (Room 77)'
    'Citadark Isle Chest 5': 1469,  # was 'Chest 62 (Room 80)'
    'Citadark Isle Chest 6': 1470,  # was 'Chest 63 (Room 80)'
    'Citadark Isle Chest 7': 1471,  # was 'Chest 64 (Room 80)'
    'Citadark Isle Chest 8': 1472,  # was 'Chest 65 (Room 81)'
    'Citadark Isle Chest 9': 1473,  # was 'Chest 66 (Room 81)'
    'Citadark Isle Chest 11': 1474,  # was 'Chest 67 (Room 83)'
    'Citadark Isle Chest 12': 1475,  # was 'Chest 68 (Room 83)'
    'Citadark Isle Chest 13': 1476,  # was 'Chest 69 (Room 83)'
    'Citadark Isle Chest 14': 1477,  # was 'Chest 70 (Room 84)'
    'Citadark Isle Chest 15': 1478,  # was 'Chest 71 (Room 84)'
    'Citadark Isle Chest 16': 1479,  # was 'Chest 72 (Room 85)'
    'Citadark Isle Chest 17': 1480,  # was 'Chest 73 (Room 85)'
    'Citadark Isle Chest 18': 1481,  # was 'Chest 74 (Room 85)'
    'Citadark Isle Chest 1': 1482,  # was 'Chest 75 (Room 73)'
    'Outside HQ Lab': 1483,  # was 'Chest 1 (Room 143)'
    'Master Ball Chest': 1484,  # was 'Chest 2 (Room 142)'
    "Player's Room Chest": 1485,  # was 'Chest 3 (Room 138)'
    'Gateon Port Chest': 1486,  # was 'Chest 4 (Room 153)'
    'Krabby Klub Basement Chest': 1487,  # was 'Chest 5 (Room 146)'
    'Gateon Tower 1F Chest 1': 1488,  # was 'Chest 6 (Room 158)'
    'Gateon Tower 1F Chest 2': 1489,  # was 'Chest 7 (Room 158)'
    'Gateon Tower 3F Chest': 1490,  # was 'Chest 8 (Room 160)'
    'Cipher Lab Left Door Chest 1': 1491,  # was 'Chest 16 (Room 1)'
    'Cipher Lab Chest 3': 1492,  # was 'Chest 19 (Room 8)'
    'Cipher Lab Left Door Chest 2': 1493,  # was 'Chest 20 (Room 1)'
    'Cipher Lab Chest 4': 1494,  # was 'Chest 21 (Room 8)'
    'Cipher Lab Chest 5': 1495,  # was 'Chest 22 (Room 8)'
    'Chest 23 (Room 9)': 1496,
    # The old name STAYS as a tombstone so 1496 is never reissued. Without carrying the id across, the new
    # name would be unfrozen and free to move, silently repointing this check in every existing seed.
    'Cipher Lab Krane Chest': 1496,  # was 'Chest 23 (Room 9)'
    'Cipher Lab Downstairs Chest 1': 1497,  # was 'Chest 24 (Room 10)'
    'Cipher Lab Downstairs Chest 2': 1498,  # was 'Chest 25 (Room 10)'
    'Cipher Lab Downstairs Chest 3': 1499,  # was 'Chest 26 (Room 10)'
    'Cipher Lab Downstairs Chest 4': 1500,  # was 'Chest 27 (Room 10)'
    'Outside Mt Battle': 1501,  # was 'Chest 29 (Room 20)'
    'Bonsly Room Shiny Chest': 1502,  # chest 30, was 'Bonsly Room Chest 1'; the id stays with the CHEST
    'SS Libra Push Room 4 Chest 1': 1503,  # was 'Chest 31 (Room 41)'
    'SS Libra Push Room 2 Chest 1': 1504,  # was 'Chest 32 (Room 37)'
    'SS Libra Push Room 2 Chest 2': 1505,  # was 'Chest 33 (Room 37)'
    'SS Libra Push Room 1 Chest': 1506,  # was 'Chest 34 (Room 39)'
    'SS Libra Push Room 3 Chest': 1507,  # was 'Chest 35 (Room 40)'
    'SS Libra Push Room 4 Chest 2': 1508,  # was 'Chest 36 (Room 41)'
    'Bonsly Room Chest 1': 1509,  # chest 38, was 'Bonsly Room Shiny Chest'; the id stays with the CHEST
    # ADDENDUM 246: chest 98 is ONBS 3F's FIRST chest (room 110), not the HQ Lab's PDA pickup -- the HQ Lab
    # holds only chests 1, 2 and 3. Both old labels stay as tombstones so 1510 and 1511 are never reissued.
    'Pickup PDA': 1510,
    'ONBS 3F Chest': 1511,
    'ONBS 3F Chest 1': 1510,  # was 'Pickup PDA', once 'Chest 98 (Room 110)'
    'ONBS 3F Chest 2': 1511,  # was 'ONBS 3F Chest', once 'Chest 99 (Room 110)'
    'ONBS 2F Chest': 1512,  # was 'Chest 100 (Room 109)'
    'Snagem 1F Chest 1': 1513,  # was 'Chest 101 (Room 165)'
    'Snagem 1F Chest 2': 1514,  # was 'Chest 102 (Room 165)'
    'Gonzap Room Chest': 1515,  # chest 103, was 'Snagem 2F Chest 1'; the id stays with the CHEST
    'Snagem 2F Chest 2': 1516,  # was 'Chest 104 (Room 166)'
    'Snagem 2F Chest 1': 1517,  # chest 105, was 'Gonzap Room Chest'; the id stays with the CHEST
    'Snagem 3F Chest 1': 1518,  # was 'Chest 106 (Room 167)'
    'Snagem 3F Chest 2': 1519,  # was 'Chest 107 (Room 167)'
    # ADDENDUM 224: the pair was split. 108 KEEPS the pair's id so existing seeds still point at the same
    # check; 113 takes a fresh id above everything. The old merged name stays listed and inert.
    'Chest 108+113 (Room 171)': 1520,
    'Kaminko Crane Room Chest 1': 1520,  # was 'Chest 108 (Room 171)'
    'Kaminko Crane Room Chest 2': 1656,  # was 'Chest 113 (Room 172)'
# ADDENDUM 176: the 120 per-shop locations. Only 24 are LIVE; the other 96 belong to the eight shops whose
# room id has never been read in game (game_data/shops.UNCONFIRMED_SHOPS) and are inert. LEFT HERE rather
# than deleted: flipping a shop's `confirmed` flag after one `!room` reading must give it back the SAME ids.
# ADDENDUM 111's berry occurrence names held 1073-1180 and are inert for the same reason.
'Outskirt Stand Shop AP Item 1': 1521,
    'Outskirt Stand Shop AP Item 2': 1522,
    'Outskirt Stand Shop AP Item 3': 1523,
    'Outskirt Stand Shop AP Item 4': 1524,
    'Outskirt Stand Shop AP Item 5': 1525,
    'Outskirt Stand Shop AP Item 6': 1526,
    'Outskirt Stand Shop AP Item 7': 1527,
    'Outskirt Stand Shop AP Item 8': 1528,
    'Outskirt Stand Shop AP Item 9': 1529,
    'Outskirt Stand Shop AP Item 10': 1530,
    'Outskirt Stand Shop AP Item 11': 1531,
    'Outskirt Stand Shop AP Item 12': 1532,
    'Phenac City Shop AP Item 1': 1533,
    'Phenac City Shop AP Item 2': 1534,
    'Phenac City Shop AP Item 3': 1535,
    'Phenac City Shop AP Item 4': 1536,
    'Phenac City Shop AP Item 5': 1537,
    'Phenac City Shop AP Item 6': 1538,
    'Phenac City Shop AP Item 7': 1539,
    'Phenac City Shop AP Item 8': 1540,
    'Phenac City Shop AP Item 9': 1541,
    'Phenac City Shop AP Item 10': 1542,
    'Phenac City Shop AP Item 11': 1543,
    'Phenac City Shop AP Item 12': 1544,
    'Phenac City Shop 2F AP Item 1': 1545,
    'Phenac City Shop 2F AP Item 2': 1546,
    'Phenac City Shop 2F AP Item 3': 1547,
    'Phenac City Shop 2F AP Item 4': 1548,
    'Phenac City Shop 2F AP Item 5': 1549,
    'Phenac City Shop 2F AP Item 6': 1550,
    'Phenac City Shop 2F AP Item 7': 1551,
    'Phenac City Shop 2F AP Item 8': 1552,
    'Phenac City Shop 2F AP Item 9': 1553,
    'Phenac City Shop 2F AP Item 10': 1554,
    'Phenac City Shop 2F AP Item 11': 1555,
    'Phenac City Shop 2F AP Item 12': 1556,
    'Pyrite Vending Machine AP Item 1': 1557,
    'Pyrite Vending Machine AP Item 2': 1558,
    'Pyrite Vending Machine AP Item 3': 1559,
    'Pyrite Vending Machine AP Item 4': 1560,
    'Pyrite Vending Machine AP Item 5': 1561,
    'Pyrite Vending Machine AP Item 6': 1562,
    'Pyrite Vending Machine AP Item 7': 1563,
    'Pyrite Vending Machine AP Item 8': 1564,
    'Pyrite Vending Machine AP Item 9': 1565,
    'Pyrite Vending Machine AP Item 10': 1566,
    'Pyrite Vending Machine AP Item 11': 1567,
    'Pyrite Vending Machine AP Item 12': 1568,
    'Pyrite Town Shop AP Item 1': 1569,
    'Pyrite Town Shop AP Item 2': 1570,
    'Pyrite Town Shop AP Item 3': 1571,
    'Pyrite Town Shop AP Item 4': 1572,
    'Pyrite Town Shop AP Item 5': 1573,
    'Pyrite Town Shop AP Item 6': 1574,
    'Pyrite Town Shop AP Item 7': 1575,
    'Pyrite Town Shop AP Item 8': 1576,
    'Pyrite Town Shop AP Item 9': 1577,
    'Pyrite Town Shop AP Item 10': 1578,
    'Pyrite Town Shop AP Item 11': 1579,
    'Pyrite Town Shop AP Item 12': 1580,
    'Realgam Tower Shop AP Item 1': 1581,
    'Realgam Tower Shop AP Item 2': 1582,
    'Realgam Tower Shop AP Item 3': 1583,
    'Realgam Tower Shop AP Item 4': 1584,
    'Realgam Tower Shop AP Item 5': 1585,
    'Realgam Tower Shop AP Item 6': 1586,
    'Realgam Tower Shop AP Item 7': 1587,
    'Realgam Tower Shop AP Item 8': 1588,
    'Realgam Tower Shop AP Item 9': 1589,
    'Realgam Tower Shop AP Item 10': 1590,
    'Realgam Tower Shop AP Item 11': 1591,
    'Realgam Tower Shop AP Item 12': 1592,
    'Realgam Battle Sim Shop AP Item 1': 1593,
    'Realgam Battle Sim Shop AP Item 2': 1594,
    'Realgam Battle Sim Shop AP Item 3': 1595,
    'Realgam Battle Sim Shop AP Item 4': 1596,
    'Realgam Battle Sim Shop AP Item 5': 1597,
    'Realgam Battle Sim Shop AP Item 6': 1598,
    'Realgam Battle Sim Shop AP Item 7': 1599,
    'Realgam Battle Sim Shop AP Item 8': 1600,
    'Realgam Battle Sim Shop AP Item 9': 1601,
    'Realgam Battle Sim Shop AP Item 10': 1602,
    'Realgam Battle Sim Shop AP Item 11': 1603,
    'Realgam Battle Sim Shop AP Item 12': 1604,
    'Agate Village Shop AP Item 1': 1605,
    'Agate Village Shop AP Item 2': 1606,
    'Agate Village Shop AP Item 3': 1607,
    'Agate Village Shop AP Item 4': 1608,
    'Agate Village Shop AP Item 5': 1609,
    'Agate Village Shop AP Item 6': 1610,
    'Agate Village Shop AP Item 7': 1611,
    'Agate Village Shop AP Item 8': 1612,
    'Agate Village Shop AP Item 9': 1613,
    'Agate Village Shop AP Item 10': 1614,
    'Agate Village Shop AP Item 11': 1615,
    'Agate Village Shop AP Item 12': 1616,
    'Gateon Port Shop AP Item 1': 1617,
    'Gateon Port Shop AP Item 2': 1618,
    'Gateon Port Shop AP Item 3': 1619,
    'Gateon Port Shop AP Item 4': 1620,
    'Gateon Port Shop AP Item 5': 1621,
    'Gateon Port Shop AP Item 6': 1622,
    'Gateon Port Shop AP Item 7': 1623,
    'Gateon Port Shop AP Item 8': 1624,
    'Gateon Port Shop AP Item 9': 1625,
    'Gateon Port Shop AP Item 10': 1626,
    'Gateon Port Shop AP Item 11': 1627,
    'Gateon Port Shop AP Item 12': 1628,
    'Mt. Battle Shop AP Item 1': 1629,
    'Mt. Battle Shop AP Item 2': 1630,
    'Mt. Battle Shop AP Item 3': 1631,
    'Mt. Battle Shop AP Item 4': 1632,
    'Mt. Battle Shop AP Item 5': 1633,
    'Mt. Battle Shop AP Item 6': 1634,
    'Mt. Battle Shop AP Item 7': 1635,
    'Mt. Battle Shop AP Item 8': 1636,
    'Mt. Battle Shop AP Item 9': 1637,
    'Mt. Battle Shop AP Item 10': 1638,
    'Mt. Battle Shop AP Item 11': 1639,
    'Mt. Battle Shop AP Item 12': 1640,
    # ADDENDUM 252: the 35 "Defeat X (Any)" locations -- see game_data/repeatable_trainers.py. Frozen the
    # day they were created: an id floats exactly once, the moment a name is created.
    'Defeat Willie (Any)': 1657,
    'Defeat Equin (Any)': 1658,
    'Defeat Eroll (Any)': 1659,
    'Defeat Snattle (Any)': 1660,
    'Defeat Cail (Any)': 1661,
    'Defeat Dert (Any)': 1662,
    'Defeat Dobit (Any)': 1663,
    'Defeat Doby (Any)': 1664,
    'Defeat Finol (Any)': 1665,
    'Defeat Labet (Any)': 1666,
    'Defeat Raling (Any)': 1667,
    'Defeat Belish (Any)': 1668,
    'Defeat Cida (Any)': 1669,
    'Defeat Clerr (Any)': 1670,
    'Defeat Dosk (Any)': 1671,
    'Defeat Eagun (Any)': 1672,
    'Defeat Hebon (Any)': 1673,
    'Defeat Gorigan (Any)': 1674,
    'Defeat Greevil (Any)': 1675,
    'Defeat Aferd (Any)': 1676,
    'Defeat Naps (Any)': 1677,
    'Defeat Ardos (Any)': 1678,
    'Defeat Laken (Any)': 1679,
    'Defeat Blusix (Any)': 1680,
    'Defeat Browsix (Any)': 1681,
    'Defeat Greesix (Any)': 1682,
    'Defeat Lovrina (Any)': 1683,
    'Defeat Purpsix (Any)': 1684,
    'Defeat Resix (Any)': 1685,
    'Defeat Yellosix (Any)': 1686,
    'Defeat Smarton (Any)': 1687,
    'Defeat Miror B. (Any)': 1688,
    'Defeat Chobin (Any)': 1689,
    'Defeat Biden (Any)': 1690,
    'Defeat Zook (Any)': 1691,
}


def _freeze_offsets(table: "dict[str, LocationData]", frozen: dict[str, int]) -> "dict[str, LocationData]":
    next_free = (max(frozen.values()) + 1) if frozen else 0
    result: dict[str, LocationData] = {}
    for name, data in table.items():
        offset = frozen[name] if name in frozen else next_free
        if name not in frozen:
            next_free += 1
        result[name] = LocationData(offset, data.region)
    seen: dict[int, str] = {}
    for name, data in result.items():
        if data.id_offset in seen:
            raise RuntimeError(
                f"locations.py: id_offset collision -- {name!r} and {seen[data.id_offset]!r} both resolved "
                f"to {data.id_offset}. Fix _FROZEN_LOCATION_OFFSETS (should never happen from ordinary edits)."
            )
        seen[data.id_offset] = name
    return result


LOCATION_TABLE = _freeze_offsets(LOCATION_TABLE, _FROZEN_LOCATION_OFFSETS)


# The one species-catch location NOT marked EXCLUDED.
GUARANTEED_SPECIES_LOCATION = species.location_name_for_species(133)  # "Catch - Eevee"

def _is_trainer_defeat_count_name(name: str) -> bool:
    # "Defeat N Trainers" -- distinguished from a named "Defeat - {trainer}" location (dash-prefixed) below.
    return name.startswith("Defeat ") and name.endswith(" Trainers") and not name.startswith("Defeat - ")


LOCATION_NAME_GROUPS: dict[str, set[str]] = {
    # "Everything that is not one of the other categories." The chest and shop tests are exact sets: both
    # categories used to have a prefix nothing else could match and both now read like ordinary place names.
    "Overworld Items": {
        name for name in LOCATION_TABLE
        if not name.startswith("Catch - ")
        and not name.startswith("Purify ")
        and not is_chest_location(name)
        and not name.startswith("Defeat - ")
        and not _is_trainer_defeat_count_name(name)
        and not is_shop_location(name)
        and name != "Outskirt Stand - Eevee Gift"
    },
    "Species Catches": {name for name in LOCATION_TABLE if name.startswith("Catch - ")},
    "Shadow Purifications": {name for name in LOCATION_TABLE if name.startswith("Purify ")},
    # Exact sets rather than prefix scans, for the reason above.
    "Chest Openings": {name for name in LOCATION_TABLE if is_chest_location(name)},
    "Trainer Defeats": {name for name in LOCATION_TABLE if name.startswith("Defeat - ")},
    "Trainer Defeat Counts": {name for name in LOCATION_TABLE if _is_trainer_defeat_count_name(name)},
    "Shop Purchases": {name for name in LOCATION_TABLE if is_shop_location(name)},
}


def get_location_name_to_id(base_id: int) -> dict[str, int]:
    return {name: base_id + data.id_offset for name, data in LOCATION_TABLE.items()}


# ADDENDUM 251: the table fingerprint, so a seed and a build can tell each other apart. A seed reported
# unwinnable had been rolled the same day three changes landed (237 retired 52 duplicate Overworld Items, 238
# excluded the Battle CD shop's 9 lines, 242 renamed a chest): 63 of its 685 rows named locations the installed
# build no longer had, five of them holding progression, and the dead ids were simply never sent. Computed FROM
# the table rather than hand-bumped, because those are exactly the changes nobody thinks to bump for. The NAME
# matters as much as the id: a rename that carries its id leaves the id set identical while still invalidating
# an in-flight seed. Not a fence -- the authoritative check is Client.py's own id-set comparison.
def location_table_fingerprint() -> str:
    """A short, stable digest of the location table's (name, id offset) pairs."""
    import hashlib

    payload = "\n".join(f"{name}\t{data.id_offset}" for name, data in sorted(LOCATION_TABLE.items()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


LOCATION_TABLE_FINGERPRINT: str = location_table_fingerprint()


def create_regions_and_locations(world) -> dict[str, Region]:
    """Creates one Region per area and populates it with its (non-event) locations, respecting shuffle options.

    `trainer_defeat_check_count` additionally trims the cumulative "Defeat N Trainers" bucket, which is safe
    because those are always EXCLUDED, and leaves the 66 individually-named locations alone.
    `world._obtainable_species_dex` trims species catches to what this seed can produce; None means no trim."""
    # shuffle_overworld_items was removed as redundant with randomize_chests; overworld items are always in.
    include_overworld = True
    include_chests = bool(world.options.randomize_chests)
    include_shops = bool(world.options.randomize_shops)
    # ADDENDUM 311: Agate Village Pit Stop -- Agate sells real supplies, so its shop checks do not exist.
    pit_stop_shop = (shops.AGATE_PIT_STOP_SHOP_NAME
                     if bool(getattr(world.options, "agate_village_pit_stop", 0)) else None)
    include_trainer_defeats = bool(world.options.shuffle_trainer_defeats)
    # ADDENDUM 270: `Unlock - X` locations exist only when travel randomization does, because
    # `enforce_travel_locks` returns immediately with the option off -- otherwise eleven checks nothing could
    # fire, stranding eleven filler items and the slot below 100%.
    include_travel_unlocks = bool(world.options.randomize_travel_locations)
    trainer_defeat_check_count = int(world.options.trainer_defeat_check_count)
    # ADDENDUM 144: 0 = cumulative (the historical behaviour), 1 = one check per real trainer.
    unique_trainer_defeats = int(getattr(world.options, "trainer_defeat_mode", 0)) == 1
    # None means "no Shadow census this build -- don't trim". getattr guards an older test world that
    # predates the attribute.
    obtainable_species_dex: set[int] | None = getattr(world, "_obtainable_species_dex", None)

    regions: dict[str, Region] = {}
    shuffle_key_items_this_seed = bool(getattr(world.options, "key_item_shuffle", 1))

    for region_name in LOCATIONS_BY_REGION:
        region = Region(region_name, world.player, world.multiworld)
        for location_name in LOCATIONS_BY_REGION[region_name]:
            if location_name == EVENT_LOCATION_NAME:
                continue  # placed separately, as an event, in regions.py
            if location_name == "Outskirt Stand - Eevee Gift":
                continue  # story landmark only in this skeleton; not a shuffled check
            is_species_catch = location_name.startswith("Catch - ")
            is_purification = location_name.startswith("Purify ")
            # Exact set membership, not the retired ladder's prefix test -- a per-chest name cannot be
            # pattern-matched safely against overworld-item names that also mention chests.
            is_chest_opening = is_chest_location(location_name)
            is_travel_unlock = location_name.startswith(travel_locations.TRAVEL_UNLOCK_LOCATION_PREFIX)
            is_unique_trainer_defeat = location_name in _UNIQUE_TRAINER_DEFEAT_NAME_SET
            is_trainer_defeat_named = (location_name.startswith("Defeat - ")
                                       and not is_unique_trainer_defeat)
            is_trainer_defeat_count = _is_trainer_defeat_count_name(location_name)
            # An exact set test: `is_trainer_defeat_named` tests "Defeat - " WITH the dash and these
            # deliberately have none, so a prefix test would be one character from the wrong category.
            is_any_defeat = location_name in _ANY_DEFEAT_NAME_SET
            # ADDENDUM 176: an exact set, not the retired "Buy Shop Item - " prefix.
            is_shop_purchase = is_shop_location(location_name)
            # Species catches and purifications are always included. Chests have their own toggle; both
            # trainer-defeat categories share one, since they run off the same tracker.
            if is_chest_opening:
                if not include_chests:
                    continue
                # ADDENDUM 177: with KeyItemShuffle off the chest still holds its real key item, so a
                # location here would promise a check the game never fires.
                if is_key_item_chest_location(location_name) and not shuffle_key_items_this_seed:
                    continue
            elif is_shop_purchase:
                # ADDENDUM 110: its own toggle (randomize_shops), gated independently of every category.
                if not include_shops:
                    continue
                if pit_stop_shop is not None and SHOP_LOCATION_TO_SHOP_AND_SLOT[location_name][0].name == pit_stop_shop:
                    continue
            elif is_any_defeat:
                # ADDENDUM 252: gated on the SAME toggle as every other trainer-defeat category. These used to
                # fall through to the Overworld Items branch and be gated on `include_overworld`, so with
                # defeats off they were progression-eligible locations nothing could check. They DO survive
                # unique mode: that mode replaces which occurrences get named locations, and "any defeat" is
                # not an occurrence.
                if not include_trainer_defeats:
                    continue
            elif is_unique_trainer_defeat:
                # ADDENDUM 144: only exists in unique mode.
                if not include_trainer_defeats or not unique_trainer_defeats:
                    continue
            elif is_trainer_defeat_named or is_trainer_defeat_count:
                if not include_trainer_defeats:
                    continue
                # ADDENDUM 144: in unique mode the cumulative bucket and the 66 curated names are both
                # replaced by the per-trainer roster -- one defeat would otherwise fire both at once.
                if unique_trainer_defeats:
                    continue
                # ADDENDUM 42: trims the cumulative bucket only; the 66 named locations are untouched.
                if is_trainer_defeat_count and (
                    TRAINER_DEFEAT_COUNT_LOCATION_TO_COUNT[location_name] > trainer_defeat_check_count
                ):
                    continue
            elif is_species_catch:
                # ADDENDUM 43: skip creating the location when the seed has no path to the species. Eevee is
                # exempt, matching its non-EXCLUDED case below, and so is the Eeveelution check -- not a species
                # name, so the lookup below would KeyError. None means no census, hence no trim.
                if (
                    location_name not in (GUARANTEED_SPECIES_LOCATION, EEVEELUTION_LOCATION_NAME)
                    and obtainable_species_dex is not None
                ):
                    dex = species.SPECIES_LOCATION_TO_DEX[location_name]
                    if dex not in obtainable_species_dex:
                        continue
            elif is_travel_unlock:
                # ADDENDUM 270. This one used to fall through to the `include_overworld` branch, which is
                # hard-coded True.
                if not include_travel_unlocks:
                    continue
            elif not is_purification:
                if not include_overworld:
                    continue
            loc_id = world.location_name_to_id[location_name]
            location = PokemonXDLocation(world.player, location_name, loc_id, region)
            # ADDENDUM 150: which categories stay EXCLUDED is the `ProgressionLocations` option's
            # decision rather than a blanket rule. Catch - Eevee is never excluded at any setting.
            scope = int(getattr(world.options, "progression_locations", 2))
            # ADDENDUM 237: `overworld_only` (0) is gone, so this can never be true. Kept as a named
            # constant so the branches below still read as a ladder.
            world_checks_excluded = scope < 1
            everything_excluded = scope < 2
            # A trainer you can permanently walk past, and a purification threshold past the player's cap,
            # are the two cases where ProgressionLocations must not apply at any setting: progression on a
            # check that cannot be re-obtained is an unwinnable seed, not a modelling risk.
            if is_purification:
                cap = int(getattr(world.options, "purification_progression_cap",
                                  PURIFICATION_LOCATION_COUNT))
                if PURIFICATION_LOCATION_TO_COUNT.get(location_name, 0) > cap:
                    location.progress_type = LocationProgressType.EXCLUDED
                    region.locations.append(location)
                    continue
            if is_unique_trainer_defeat and location_name in _MISSABLE_TRAINER_LOCATION_NAMES:
                location.progress_type = LocationProgressType.EXCLUDED
                region.locations.append(location)
                continue
            # ADDENDUM 185: the cumulative-mode counterpart -- a named location inherits its surname's
            # missability.
            if is_trainer_defeat_named and location_name in _MISSABLE_NAMED_TRAINER_LOCATIONS:
                location.progress_type = LocationProgressType.EXCLUDED
                region.locations.append(location)
                continue
            # ADDENDUM 335: the fourteen uncertain Overworld Items that were EXCLUDED here are retired at
            # the census now. WORTH KEEPING IF SUCH A LIST COMES BACK: the exclusion belongs HERE rather
            # than in rules.py, because create_items runs before set_rules, so a later exclusion is
            # invisible to the useful/filler arithmetic and produces `FillError: Not enough filler items
            # for excluded locations`. ADDENDUM 252's always-filler any-defeats are marked here for the
            # same reason.
            if location_name in repeatable_trainers.ALWAYS_FILLER_LOCATIONS:
                location.progress_type = LocationProgressType.EXCLUDED
                region.locations.append(location)
                continue
            # ADDENDUM 171: always filler-only -- fired by a story-byte watch, and never fired at all when
            # randomize_travel_locations is off.
            if is_travel_unlock:
                location.progress_type = LocationProgressType.EXCLUDED
                region.locations.append(location)
                continue
            # ADDENDUM 386: the shiny chests, filler-only for as long as they can refuse to open. Here
            # rather than in rules.py for the reason the ADDENDUM 335 note above gives -- create_items reads
            # these progress types, and a later exclusion starves the filler it needs.
            if location_name in FILLER_ONLY_CHEST_LOCATIONS:
                location.progress_type = LocationProgressType.EXCLUDED
                region.locations.append(location)
                continue
            # ADDENDUM 387: the shop restock lines, for the same reason and in the same place.
            if location_name in FILLER_ONLY_SHOP_LOCATIONS:
                location.progress_type = LocationProgressType.EXCLUDED
                region.locations.append(location)
                continue
            if (
                (is_chest_opening and world_checks_excluded)
                or (is_shop_purchase and world_checks_excluded)
                or (is_trainer_defeat_count and world_checks_excluded)
                or (is_unique_trainer_defeat and world_checks_excluded)
                or (is_purification and everything_excluded)
                or (
                    is_species_catch
                    and location_name != GUARANTEED_SPECIES_LOCATION
                    and everything_excluded
                )
                # ADDENDUM 185: the narrower switch, and it wins over ProgressionLocations in the
                # restrictive direction only. Eevee is the starter and the Eeveelution check fires on
                # evolving it, so neither is a Shadow Pokemon.
                or (
                    is_species_catch
                    and location_name not in (GUARANTEED_SPECIES_LOCATION, EEVEELUTION_LOCATION_NAME)
                    and not bool(getattr(world.options, "shadow_catch_progression", 0))
                )
            ):
                # Never required for logic. EXCLUDED locations still receive items and can still be checked;
                # fill just never *requires* one to be reachable, which is what makes shipping every species
                # and every purification threshold safe. Eevee is the one exception.
                location.progress_type = LocationProgressType.EXCLUDED
            # ADDENDUM 174: Citadark Isle is weighted AWAY from progression. A PER-LOCATION ROLL, not a blanket
            # exclusion, is what "unlikely but possible" means: at the default 10, roughly one Citadark check in
            # ten stays eligible. Rolled off `world.random` so it is seed-deterministic. Applied to every
            # Citadark location, not only the chests; already-EXCLUDED stays excluded.
            if (
                region_name == "Citadark Isle"
                and location.progress_type is not LocationProgressType.EXCLUDED
            ):
                chance = int(getattr(world.options, "citadark_progression_chance", 10))
                if world.random.randrange(100) >= chance:
                    location.progress_type = LocationProgressType.EXCLUDED
            region.locations.append(location)
        regions[region_name] = region
        world.multiworld.regions.append(region)
    return regions
