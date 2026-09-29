"""
Pokemon XD: Gale of Darkness -- Archipelago client, RAM-access layer.

Talks to a live, unmodified Dolphin process: hooking, block-base resolution, Bag pocket read/write,
party/species detection, purification detection, and item-pocket routing for delivering received items.
`pokemon-xd-ram-map.md` is the source of truth for every constant here.

Two addressing regimes, and mixing them up is the classic bug:
  - The player-state block (money, Bag pockets, key items, party summary) is one contiguous allocation that
    relocates on every boot but is stable for the whole of one boot. Resolve its base once per connection via
    a trainer-name landmark search and cache it; there is no pointer chain.
  - The overworld party struct and most story/flag addresses are fixed and do not relocate.

Bag pockets are packed arrays of 4-byte `[item id: u16BE][quantity: u16BE]` records, empty slots all-zero,
pickups appended to the next open slot. Read and write are both live-validated for the Items and Poke Ball
pockets. Key Items holds the same record shape but has never been write-tested.

Box reads are best-effort only -- see the caveat on `read_box_slot_species` before polling them.

Imports nothing beyond the standard library plus `dolphin_memory_engine`; in particular it does not import
the Archipelago core, so it stays loadable standalone (see `_load_location_name_for_species`).
"""

from __future__ import annotations

import os
import struct
import time
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar

# `dolphin_memory_engine` is a native extension and may be missing or mismatched. Guard the import so a bad
# wheel doesn't take Client.py down with a bare traceback; anything needing live memory calls _require_dme().
try:
    import dolphin_memory_engine as dme
    DOLPHIN_IMPORT_ERROR: "str | None" = None
except Exception as _dme_exc:  # noqa: BLE001 -- ImportError, OSError from a bad wheel, anything
    dme = None  # type: ignore[assignment]
    DOLPHIN_IMPORT_ERROR = str(_dme_exc)

DOLPHIN_MISSING_MESSAGE = (
    "Pokemon XD needs the 'dolphin-memory-engine' package to talk to Dolphin, and it could not be loaded "
    f"({DOLPHIN_IMPORT_ERROR}). Install it into the SAME Python that runs Archipelago -- from your "
    "Archipelago folder: ArchipelagoLauncher \"Install Package\" -> dolphin-memory-engine, or "
    "'<Archipelago>/python -m pip install dolphin-memory-engine'. Everything else (generating a seed, "
    "patching an ISO) works without it."
)


def dolphin_available() -> bool:
    """True when live-memory access is possible at all. Lets callers degrade gracefully instead of raising."""
    return dme is not None


def _require_dme():
    if dme is None:
        raise RuntimeError(DOLPHIN_MISSING_MESSAGE)
    return dme


MEM1_START = 0x80000000
MEM1_SIZE = 0x1800000  # 24 MiB

# Dolphin's "Enable Emulated Memory Size Override" makes hooking impossible, not just harder: DME finds the
# emulated RAM by matching a region whose size equals the MEM1 size it was built with, so the override hides
# it and hook() fails before any address here is read. Fixing it needs an upstream DME change (expose the MEM1
# size, or read Dolphin's SystemInfo). Affects every Dolphin-based AP client, so just say so when it fails.
DOLPHIN_MEMORY_OVERRIDE_HINT = (
    "If you have 'Enable Emulated Memory Size Override' turned on in Dolphin (Options > Configuration > "
    "Advanced), turn it OFF -- the library this client uses to read Dolphin's memory finds that memory by "
    "its size, so the override makes it invisible and no connection is possible. This affects every "
    "Archipelago client that talks to Dolphin, not just this one."
)

# Landmark for resolving the player-state block base each connection. The trainer name is arbitrary player input,
# so nothing can be hardcoded: setup tells the player to use their AP slot name as the in-game trainer name and
# callers pass that in as `landmark`. The constant below is this project's test save only, never a fallback. (XD's
# name-entry screen has its own unmeasured length/charset limit, so the slot name must be short and alphanumeric.)
TRAINER_NAME_LANDMARK = "DAVID"  # test save only -- pass the connected slot name instead

# Offsets below are relative to BLOCK_BASE == (trainer-name address + RECORD_TRAINER_NAME_OFFSET). Derived
# from the original session's addresses; see pokemon-xd-ram-map.md's Bag/party-array sections.
RECORD_TRAINER_NAME_OFFSET = 0x40          # measured 2026-09-02 against the known Items-pocket address
RECORD_SPECIES_NAME_OFFSET_1 = 0x3E        # first copy of the species name (UTF-16BE) -- NOT re-verified against
RECORD_SPECIES_NAME_OFFSET_2 = 0x52        # the corrected base yet; these two are from the OTHER (party-recap)
RECORD_STATS_BLOCK_OFFSET = 0x80           # struct and still relative to THAT record's own base, not BLOCK_BASE
PARTY_RECORD_STRIDE = 0xC2                 # -- provisional -- only 2 slots observed, NOT confirmed general

MONEY_OFFSET = 0x8A4                       # u32BE, plain Pokedollar total (not an [id][qty] record) -- CONFIRMED
MONEY_DISPLAY_MARKER_OFFSET = MONEY_OFFSET + 0xC  # 8 bytes of 0x01 immediately following 4 bytes of zero
# Poke Coupons sit four bytes past money. heroBiosGetPokecoupon (0x8014DCE8) reads hero+0x8E8 and
# heroBiosGetPokecouponAll (0x8014DCA0) reads hero+0x8EC; with HERO_OFFSET_FROM_BLOCK == -0x40 that anchors
# off MONEY_OFFSET, and a live 0 -> 5000 write showed up on the PDA.
#
# Write both: heroAddPokecoupon (0x8014C7F8) raises status 13 and 14, heroDecPokecoupon lowers 14 only on a
# negative delta, so the lifetime total never falls when you spend -- and Mt. Battle's prize tiers read it.
POKECOUPON_OFFSET = MONEY_OFFSET + 0x4          # u32BE, the spendable balance
POKECOUPON_TOTAL_OFFSET = MONEY_OFFSET + 0x8    # u32BE, the lifetime total the prize tiers read
# from `lis r5,0x0099; addi r0,r5,-27009` in both of the game's own setters, which also refuse negatives.
POKECOUPON_MAX = 9999999


def read_pokecoupons(block_base: int) -> "tuple[int, int]":
    """(balance, lifetime total). Raises on a bad read, like the money reader it sits beside."""
    return (struct.unpack(">I", read_bytes(block_base + POKECOUPON_OFFSET, 4))[0],
            struct.unpack(">I", read_bytes(block_base + POKECOUPON_TOTAL_OFFSET, 4))[0])


def add_pokecoupons(block_base: int, amount: int) -> "tuple[int, int]":
    """Add `amount` to both fields the way `heroAddPokecoupon` does; returns the new (balance, total).

    Clamped to [0, POKECOUPON_MAX] like the game's own setters, so a delivered item can never leave the save
    somewhere the game would refuse to put it."""
    balance, total = read_pokecoupons(block_base)
    new = tuple(max(0, min(POKECOUPON_MAX, value + amount)) for value in (balance, total))
    write_bytes(block_base + POKECOUPON_OFFSET, struct.pack(">I", new[0]))
    write_bytes(block_base + POKECOUPON_TOTAL_OFFSET, struct.pack(">I", new[1]))
    return new
# u32BE running total of steps walked on this save; measured across ~150 MEM1 dumps (see StepCounterGate).
# Unchanged by battles and menus, rises room to room while walking, 0 on a new save.
STEP_COUNTER_OFFSET = 0x908
                                            # MONEY_DISPLAY_MARKER_OFFSET: confirmed live 2026-09-02, likely
                                            # per-digit "visible" flags for the money widget. Used by
                                            # `_looks_like_real_block_base` as a structural check, since a
                                            # money-range test alone is too weak.
ITEMS_POCKET_OFFSET = 0x488                # packed [id][qty] array -- CONFIRMED (Potion/Antidote/stones/etc.)
POKEBALL_POCKET_OFFSET = 0x5AC             # packed [id][qty] array -- confirmed Poke Ball + Great Ball test
KEY_ITEMS_OFFSET = 0x500                   # packed [id][qty] array -- confirmed live (Krane Memo 1/2)

# Slot counts below come from the gap to the next known field, with the bytes in between live-checked all-zero
# to the boundary. They bound the safe read/write range; they do not prove the gap holds no padding or some
# unmapped pocket.
ITEMS_POCKET_MAX_SLOTS = 30                # (KEY_ITEMS_OFFSET - ITEMS_POCKET_OFFSET) / 4, all-zero past slot 3
KEY_ITEMS_MAX_SLOTS = 43                   # gap-derived upper bound, not slot-by-slot checked; real count is
                                            # surely smaller -- this is only "safe not to write past"
POKEBALL_POCKET_MAX_SLOTS = 8              # a guess. The gap to MONEY_OFFSET is 0x2F8 (190 slots), far too big
                                            # for a ball pocket, so something unmapped (TM case? Battle CDs?)
                                            # likely sits in between -- don't treat that gap as ball capacity

# --- Overworld party struct. Fixed address, safe to poll continuously. ---
# Not relative to BLOCK_BASE: an independently-anchored region that stayed put across two full Dolphin restarts and
# two different save files. If it stops matching, re-derive it by dumping memory and searching for an owned species'
# name text. LAZILY INITIALIZED: all-zero until the player opens the Party/Status screen once per boot (catching and
# PC-box use do not populate it), so an all-zero read means "not initialized yet", not "empty party".
PARTY_BASE = 0x804280E8
PARTY_SLOT_STRIDE = 0x30                   # 48 bytes -- confirmed live with 2 real slots (Jolteon, Teddiursa)
PARTY_SPECIES_OFFSET = 0x26                # u16BE, NOT a u32 at +0x24: +0x24/+0x25 read 0 for most Pokemon but
                                            # came back 0x0144 on one that had battled, so a u32 read there can
                                            # silently return a bogus species. Confirmed against 135 and 216.
                                            # Also NOT a National Dex # directly: dex # only holds for species
                                            # 1-251, and 252+ is a compacted internal index (master index minus
                                            # 25, the reserved slots 252-276 being absent from this encoding).
                                            # Always go through
                                            # tools/xd_species_index.national_dex_for_live_species().
PARTY_MAX_SLOTS = 6                        # only 2 slots independently confirmed; the rest extrapolate the stride
PARTY_NAME_MAX_BYTES = 0x16                # from slot start, UTF-16BE null-terminated. The live nickname, unlike
                                            # the recap record's name, which only updates on slot refresh.
PARTY_LEVEL_OFFSET = 0x17                  # u8
PARTY_MAXHP_OFFSET = 0x18                  # u16BE
PARTY_CURHP_OFFSET = 0x1A                  # u16BE

# --- PC box storage. Addressing formula confirmed; the numeric species sub-field's sync timing is not --
# see the caveat on BOX_SLOT_SPECIES_OFFSET before using it for anything time-sensitive. ---
# Relative to BLOCK_BASE (like the Bag pockets), unlike PARTY_BASE above.
BOX_SLOT_TEXT_ANCHOR_OFFSET = 0x9B2        # Box 1 Slot 1's recap-shaped record, text anchor from BLOCK_BASE
BOX_SLOT_STRIDE = 0xC4                     # 196 bytes, confirmed for 3 consecutive slots in one box
BOX_PADDING_PER_BOX = 0x14                 # each box boundary adds this on top of 30*BOX_SLOT_STRIDE, so box N's
                                            # slot-0 anchor is BOX_SLOT_TEXT_ANCHOR_OFFSET +
                                            # N*(30*BOX_SLOT_STRIDE + BOX_PADDING_PER_BOX). Verified exactly at
                                            # one boundary (+0x14) and seven (+0x8C). It's a per-box header, not
                                            # the relocating buffer it first looked like, so a full 8x30 sweep is
                                            # addressable.
BOX_SLOT_SPECIES_OFFSET = 0x30             # from the slot's own text anchor, same field shape as the party struct
                                            # and the recap record. Can lag the name-text fields badly: read a
                                            # stale species for one slot deposited into moments earlier while
                                            # another equally recent slot read right. Possibly tied to which box
                                            # was last viewed rather than deposit order. Don't trust it just after
                                            # a deposit; the name-text formula above is solid regardless.


# --- Party "recap" record. One 196-byte slot per current party member, same stride as the box array, relative
# to BLOCK_BASE -- a different block from the compact party struct at PARTY_BASE, which has no room for stats
# or a purification flag. It persists once written (does not zero when its scene closes) but only refreshes
# per-slot when a recap-worthy event fires for that member: catch, evolution, battle end, purification. A slot
# untouched since boot can read stale data indefinitely, so trust it right after it changes, not on any poll.
PARTY_RECAP_OFFSET = 0x3E                  # party slot 0's record base from BLOCK_BASE; record N is
                                            # PARTY_RECAP_OFFSET + N*PARTY_RECAP_STRIDE
PARTY_RECAP_STRIDE = 0xC4                  # identical to BOX_SLOT_STRIDE, very likely the same array walked by
                                            # party position instead of box/slot position
PARTY_RECAP_SPECIES_OFFSET = 0x32          # u16BE, UNRELIABLE -- same stale-species signature as
                                            # BOX_SLOT_SPECIES_OFFSET, and purification doesn't re-sync it even
                                            # while refreshing the fields below. Use read_party_species instead;
                                            # this is exposed for debugging only.
PARTY_RECAP_MAXHP_OFFSET = 0x42            # u16BE. Runs ahead of PARTY_BASE's MaxHP right after a purification,
                                            # so it's the more current value at that moment.
PARTY_RECAP_STAT_OFFSETS = {               # u16BE each, matched the player's reported stats exactly across two
    "attack": 0x44,                        # purification events (Teddiursa, Poochyena)
    "defense": 0x46,
    "sp_attack": 0x48,
    "sp_defense": 0x4a,
    "speed": 0x4c,
}
# Match this value exactly, never `flag != 0`: a Pokemon close to purification can leave some other nonzero
# value here, and opening the party or PC refreshes the recap record, which is how spurious purifications used
# to get sent.
PURIFIED_FLAG_VALUE = 0x40                 # 64 -- the only value ever observed on a real purification
PARTY_RECAP_PURIFIED_FLAG_OFFSET = 0x2e    # u16BE, the purification signal. 0 before, 64 immediately after;
                                            # confirmed for two Pokemon (Teddiursa, Poochyena) and stable across
                                            # an idle re-check. Prefer it over the stat block, which is five
                                            # fields that could each drift for unrelated reasons. Unconfirmed
                                            # whether the flag is save-persisted or boot-scoped.


# Species name -> National Dex #, read off the game's own menu-text table (English NTSC-U): exact dex order from
# BULBASAUR through DEOXYS, then EGG and BAD EGG, then type and ability names. A fixed property of the release, so
# hardcoded rather than walked from memory. Validated 11/11 against species confirmed via PARTY_BASE.
#
# Use this instead of BOX_SLOT_SPECIES_OFFSET or PARTY_RECAP_SPECIES_OFFSET, which index some other table entirely
# (Ledyba read 60, Baltoy 317 -- not a fixed shift). Call `species_dex_from_name`, which handles an unknown name.
# A few keys carry the game's own glyphs verbatim (Nidoran gender symbols, Farfetch'd, "MR. MIME"); only the
# plain-ASCII names were live-verified through the UTF-16BE decode, so flag a mismatch on one of those.
SPECIES_NAME_TO_DEX: dict[str, int] = {
    "BULBASAUR": 1,  "IVYSAUR": 2,  "VENUSAUR": 3,  "CHARMANDER": 4,
    "CHARMELEON": 5,  "CHARIZARD": 6,  "SQUIRTLE": 7,  "WARTORTLE": 8,
    "BLASTOISE": 9,  "CATERPIE": 10,  "METAPOD": 11,  "BUTTERFREE": 12,
    "WEEDLE": 13,  "KAKUNA": 14,  "BEEDRILL": 15,  "PIDGEY": 16,
    "PIDGEOTTO": 17,  "PIDGEOT": 18,  "RATTATA": 19,  "RATICATE": 20,
    "SPEAROW": 21,  "FEAROW": 22,  "EKANS": 23,  "ARBOK": 24,
    "PIKACHU": 25,  "RAICHU": 26,  "SANDSHREW": 27,  "SANDSLASH": 28,
    "NIDORAN♀": 29,  "NIDORINA": 30,  "NIDOQUEEN": 31,  "NIDORAN♂": 32,
    "NIDORINO": 33,  "NIDOKING": 34,  "CLEFAIRY": 35,  "CLEFABLE": 36,
    "VULPIX": 37,  "NINETALES": 38,  "JIGGLYPUFF": 39,  "WIGGLYTUFF": 40,
    "ZUBAT": 41,  "GOLBAT": 42,  "ODDISH": 43,  "GLOOM": 44,
    "VILEPLUME": 45,  "PARAS": 46,  "PARASECT": 47,  "VENONAT": 48,
    "VENOMOTH": 49,  "DIGLETT": 50,  "DUGTRIO": 51,  "MEOWTH": 52,
    "PERSIAN": 53,  "PSYDUCK": 54,  "GOLDUCK": 55,  "MANKEY": 56,
    "PRIMEAPE": 57,  "GROWLITHE": 58,  "ARCANINE": 59,  "POLIWAG": 60,
    "POLIWHIRL": 61,  "POLIWRATH": 62,  "ABRA": 63,  "KADABRA": 64,
    "ALAKAZAM": 65,  "MACHOP": 66,  "MACHOKE": 67,  "MACHAMP": 68,
    "BELLSPROUT": 69,  "WEEPINBELL": 70,  "VICTREEBEL": 71,  "TENTACOOL": 72,
    "TENTACRUEL": 73,  "GEODUDE": 74,  "GRAVELER": 75,  "GOLEM": 76,
    "PONYTA": 77,  "RAPIDASH": 78,  "SLOWPOKE": 79,  "SLOWBRO": 80,
    "MAGNEMITE": 81,  "MAGNETON": 82,  "FARFETCH'D": 83,  "DODUO": 84,
    "DODRIO": 85,  "SEEL": 86,  "DEWGONG": 87,  "GRIMER": 88,
    "MUK": 89,  "SHELLDER": 90,  "CLOYSTER": 91,  "GASTLY": 92,
    "HAUNTER": 93,  "GENGAR": 94,  "ONIX": 95,  "DROWZEE": 96,
    "HYPNO": 97,  "KRABBY": 98,  "KINGLER": 99,  "VOLTORB": 100,
    "ELECTRODE": 101,  "EXEGGCUTE": 102,  "EXEGGUTOR": 103,  "CUBONE": 104,
    "MAROWAK": 105,  "HITMONLEE": 106,  "HITMONCHAN": 107,  "LICKITUNG": 108,
    "KOFFING": 109,  "WEEZING": 110,  "RHYHORN": 111,  "RHYDON": 112,
    "CHANSEY": 113,  "TANGELA": 114,  "KANGASKHAN": 115,  "HORSEA": 116,
    "SEADRA": 117,  "GOLDEEN": 118,  "SEAKING": 119,  "STARYU": 120,
    "STARMIE": 121,  "MR. MIME": 122,  "SCYTHER": 123,  "JYNX": 124,
    "ELECTABUZZ": 125,  "MAGMAR": 126,  "PINSIR": 127,  "TAUROS": 128,
    "MAGIKARP": 129,  "GYARADOS": 130,  "LAPRAS": 131,  "DITTO": 132,
    "EEVEE": 133,  "VAPOREON": 134,  "JOLTEON": 135,  "FLAREON": 136,
    "PORYGON": 137,  "OMANYTE": 138,  "OMASTAR": 139,  "KABUTO": 140,
    "KABUTOPS": 141,  "AERODACTYL": 142,  "SNORLAX": 143,  "ARTICUNO": 144,
    "ZAPDOS": 145,  "MOLTRES": 146,  "DRATINI": 147,  "DRAGONAIR": 148,
    "DRAGONITE": 149,  "MEWTWO": 150,  "MEW": 151,  "CHIKORITA": 152,
    "BAYLEEF": 153,  "MEGANIUM": 154,  "CYNDAQUIL": 155,  "QUILAVA": 156,
    "TYPHLOSION": 157,  "TOTODILE": 158,  "CROCONAW": 159,  "FERALIGATR": 160,
    "SENTRET": 161,  "FURRET": 162,  "HOOTHOOT": 163,  "NOCTOWL": 164,
    "LEDYBA": 165,  "LEDIAN": 166,  "SPINARAK": 167,  "ARIADOS": 168,
    "CROBAT": 169,  "CHINCHOU": 170,  "LANTURN": 171,  "PICHU": 172,
    "CLEFFA": 173,  "IGGLYBUFF": 174,  "TOGEPI": 175,  "TOGETIC": 176,
    "NATU": 177,  "XATU": 178,  "MAREEP": 179,  "FLAAFFY": 180,
    "AMPHAROS": 181,  "BELLOSSOM": 182,  "MARILL": 183,  "AZUMARILL": 184,
    "SUDOWOODO": 185,  "POLITOED": 186,  "HOPPIP": 187,  "SKIPLOOM": 188,
    "JUMPLUFF": 189,  "AIPOM": 190,  "SUNKERN": 191,  "SUNFLORA": 192,
    "YANMA": 193,  "WOOPER": 194,  "QUAGSIRE": 195,  "ESPEON": 196,
    "UMBREON": 197,  "MURKROW": 198,  "SLOWKING": 199,  "MISDREAVUS": 200,
    "UNOWN": 201,  "WOBBUFFET": 202,  "GIRAFARIG": 203,  "PINECO": 204,
    "FORRETRESS": 205,  "DUNSPARCE": 206,  "GLIGAR": 207,  "STEELIX": 208,
    "SNUBBULL": 209,  "GRANBULL": 210,  "QWILFISH": 211,  "SCIZOR": 212,
    "SHUCKLE": 213,  "HERACROSS": 214,  "SNEASEL": 215,  "TEDDIURSA": 216,
    "URSARING": 217,  "SLUGMA": 218,  "MAGCARGO": 219,  "SWINUB": 220,
    "PILOSWINE": 221,  "CORSOLA": 222,  "REMORAID": 223,  "OCTILLERY": 224,
    "DELIBIRD": 225,  "MANTINE": 226,  "SKARMORY": 227,  "HOUNDOUR": 228,
    "HOUNDOOM": 229,  "KINGDRA": 230,  "PHANPY": 231,  "DONPHAN": 232,
    "PORYGON2": 233,  "STANTLER": 234,  "SMEARGLE": 235,  "TYROGUE": 236,
    "HITMONTOP": 237,  "SMOOCHUM": 238,  "ELEKID": 239,  "MAGBY": 240,
    "MILTANK": 241,  "BLISSEY": 242,  "RAIKOU": 243,  "ENTEI": 244,
    "SUICUNE": 245,  "LARVITAR": 246,  "PUPITAR": 247,  "TYRANITAR": 248,
    "LUGIA": 249,  "HO-OH": 250,  "CELEBI": 251,  "TREECKO": 252,
    "GROVYLE": 253,  "SCEPTILE": 254,  "TORCHIC": 255,  "COMBUSKEN": 256,
    "BLAZIKEN": 257,  "MUDKIP": 258,  "MARSHTOMP": 259,  "SWAMPERT": 260,
    "POOCHYENA": 261,  "MIGHTYENA": 262,  "ZIGZAGOON": 263,  "LINOONE": 264,
    "WURMPLE": 265,  "SILCOON": 266,  "BEAUTIFLY": 267,  "CASCOON": 268,
    "DUSTOX": 269,  "LOTAD": 270,  "LOMBRE": 271,  "LUDICOLO": 272,
    "SEEDOT": 273,  "NUZLEAF": 274,  "SHIFTRY": 275,  "TAILLOW": 276,
    "SWELLOW": 277,  "WINGULL": 278,  "PELIPPER": 279,  "RALTS": 280,
    "KIRLIA": 281,  "GARDEVOIR": 282,  "SURSKIT": 283,  "MASQUERAIN": 284,
    "SHROOMISH": 285,  "BRELOOM": 286,  "SLAKOTH": 287,  "VIGOROTH": 288,
    "SLAKING": 289,  "NINCADA": 290,  "NINJASK": 291,  "SHEDINJA": 292,
    "WHISMUR": 293,  "LOUDRED": 294,  "EXPLOUD": 295,  "MAKUHITA": 296,
    "HARIYAMA": 297,  "AZURILL": 298,  "NOSEPASS": 299,  "SKITTY": 300,
    "DELCATTY": 301,  "SABLEYE": 302,  "MAWILE": 303,  "ARON": 304,
    "LAIRON": 305,  "AGGRON": 306,  "MEDITITE": 307,  "MEDICHAM": 308,
    "ELECTRIKE": 309,  "MANECTRIC": 310,  "PLUSLE": 311,  "MINUN": 312,
    "VOLBEAT": 313,  "ILLUMISE": 314,  "ROSELIA": 315,  "GULPIN": 316,
    "SWALOT": 317,  "CARVANHA": 318,  "SHARPEDO": 319,  "WAILMER": 320,
    "WAILORD": 321,  "NUMEL": 322,  "CAMERUPT": 323,  "TORKOAL": 324,
    "SPOINK": 325,  "GRUMPIG": 326,  "SPINDA": 327,  "TRAPINCH": 328,
    "VIBRAVA": 329,  "FLYGON": 330,  "CACNEA": 331,  "CACTURNE": 332,
    "SWABLU": 333,  "ALTARIA": 334,  "ZANGOOSE": 335,  "SEVIPER": 336,
    "LUNATONE": 337,  "SOLROCK": 338,  "BARBOACH": 339,  "WHISCASH": 340,
    "CORPHISH": 341,  "CRAWDAUNT": 342,  "BALTOY": 343,  "CLAYDOL": 344,
    "LILEEP": 345,  "CRADILY": 346,  "ANORITH": 347,  "ARMALDO": 348,
    "FEEBAS": 349,  "MILOTIC": 350,  "CASTFORM": 351,  "KECLEON": 352,
    "SHUPPET": 353,  "BANETTE": 354,  "DUSKULL": 355,  "DUSCLOPS": 356,
    "TROPIUS": 357,  "CHIMECHO": 358,  "ABSOL": 359,  "WYNAUT": 360,
    "SNORUNT": 361,  "GLALIE": 362,  "SPHEAL": 363,  "SEALEO": 364,
    "WALREIN": 365,  "CLAMPERL": 366,  "HUNTAIL": 367,  "GOREBYSS": 368,
    "RELICANTH": 369,  "LUVDISC": 370,  "BAGON": 371,  "SHELGON": 372,
    "SALAMENCE": 373,  "BELDUM": 374,  "METANG": 375,  "METAGROSS": 376,
    "REGIROCK": 377,  "REGICE": 378,  "REGISTEEL": 379,  "LATIAS": 380,
    "LATIOS": 381,  "KYOGRE": 382,  "GROUDON": 383,  "RAYQUAZA": 384,
    "JIRACHI": 385,  "DEOXYS": 386,  "EGG": 387,  "BAD EGG": 388,
}


def species_dex_from_name(name: str) -> int | None:
    """National Dex # for a species (or EGG/BAD EGG) name as decoded from any UTF-16BE name field here.

    Returns None for an unrecognized string rather than raising, since callers pass arbitrary just-read names
    that may be nicknames. Use this for box/recap records instead of their raw numeric species fields. Do NOT
    use it for PARTY_BASE's PARTY_SPECIES_OFFSET, which is a numeric live index rather than a name -- resolve
    that with xd_species_index.national_dex_for_live_species() (see `PartyMember.national_dex`)."""
    return SPECIES_NAME_TO_DEX.get(name.strip().upper())


# --- Low-level Dolphin access ---

def hook() -> bool:
    """(Re)hook to a running Dolphin process. Un-hooks first, swallowing errors: repeated hook() calls from a
    long-running process can otherwise get stuck -- a known dolphin_memory_engine issue."""
    _require_dme()
    try:
        dme.un_hook()
    except Exception:
        pass
    dme.hook()
    return dme.is_hooked()


def is_hooked() -> bool:
    """Cheap check for an existing hook. Unlike hook() it does not un-hook/re-hook, so this is what a polling
    loop calls every tick."""
    if dme is None:
        return False
    return dme.is_hooked()


def read_bytes(address: int, length: int) -> bytes:
    return _require_dme().read_bytes(address, length)


def write_bytes(address: int, data: bytes) -> None:
    _require_dme().write_bytes(address, data)


def dump_mem1() -> bytes:
    """Full MEM1 read, chunked (mirrors bridge.py's dump command). Slow (~seconds) -- only used for the
    one-time landmark search, never in a polling loop."""
    chunks = []
    chunk_size = 0x10000
    for offset in range(0, MEM1_SIZE, chunk_size):
        size = min(chunk_size, MEM1_SIZE - offset)
        chunks.append(read_bytes(MEM1_START + offset, size))
    return b"".join(chunks)


# --- Resolving the player-state block's current base ---

def _looks_like_real_block_base(candidate: int, mem: bytes) -> bool:
    """Validates a candidate BLOCK_BASE: the MONEY_DISPLAY_MARKER_OFFSET signature (8 bytes of 0x01 at a
    fixed offset past money) plus a plausible money value.

    The marker is the load-bearing half. "Money looks plausible" alone accepts any run of zeroes -- a false
    candidate beside the unrelated 0x8042xxxx party region (money=0, empty first Items slot) passed that way
    live. An exact 8-byte 0x01 run at an exact offset rejects it and still accepts the real block."""
    def u32(addr: int) -> int:
        off = addr - MEM1_START
        return struct.unpack(">I", mem[off:off + 4])[0]

    money = u32(candidate + MONEY_OFFSET)
    if not (0 <= money <= 99_999_999):
        return False
    off = candidate + MONEY_DISPLAY_MARKER_OFFSET - MEM1_START
    return mem[off:off + 8] == b"\x01" * 8


def resolve_block_base(landmark: str) -> int | None:
    """One-time-per-connection full-memory scan for `landmark` -- which must be the connected player's slot
    name, per the setup convention on TRAINER_NAME_LANDMARK, never a hardcoded guess. Returns the resolved
    BLOCK_BASE, or None if no occurrence validates (not in-game yet, trainer name doesn't match the slot name,
    or XD's name-entry screen altered it).

    Checks EVERY occurrence, not just the first: one dump held nine copies of the trainer name (the real block
    plus several transient recap records), and the lowest-addressed one -- what a naive `bytes.find()` returns
    -- was inside the unrelated 0x8042xxxx party region.

    Several can also validate: of those nine, two passed -- the real 0x8047xxxx block and a structurally
    identical 0x804Axxxx mirror with less reliable sync timing (the same mirror the ram-map doc records for the
    Poke Ball pocket). So a validated candidate in 0x8047xxxx-0x8049xxxx wins; one outside that range is
    returned only if nothing inside it validated.

    Not cached here: resolve once at connect time and reuse while Dolphin stays hooked to the same boot."""
    mem = dump_mem1()
    needle = landmark.encode("utf-16-be")
    validated: list[int] = []
    idx = mem.find(needle)
    while idx != -1:
        trainer_name_addr = MEM1_START + idx
            # BLOCK_BASE sits after the trainer name in memory, not before it.
        candidate = trainer_name_addr + RECORD_TRAINER_NAME_OFFSET
        if _looks_like_real_block_base(candidate, mem):
            validated.append(candidate)
        idx = mem.find(needle, idx + 1)
    if not validated:
        return None
    preferred = [c for c in validated if 0x80470000 <= c <= 0x8049FFFF]
    return preferred[0] if preferred else validated[0]


# --- Bag pocket read/write (live-confirmed for Items + Poke Ball pockets; Key Items unconfirmed) ---

@dataclass
class BagSlot:
    index: int
    address: int
    item_id: int
    quantity: int

    @property
    def empty(self) -> bool:
        return self.item_id == 0 and self.quantity == 0


def read_pocket(pocket_base: int, max_slots: int) -> list[BagSlot]:
    raw = read_bytes(pocket_base, max_slots * 4)
    slots = []
    for i in range(max_slots):
        item_id, qty = struct.unpack_from(">HH", raw, i * 4)
        slots.append(BagSlot(i, pocket_base + i * 4, item_id, qty))
    return slots


# A Bag slot's quantity is a u16, so packing `slot.quantity + quantity` straight into it raised struct.error once a
# slot reached 65535 -- inside the one path that must never get stuck. A slot gets there because `give_items`
# re-calls `give_item` every poll while an item stays unconfirmed, roughly eighteen hours at a one-second poll. So
# the arithmetic saturates here and Client.py stops retrying a slot that cannot grow. 0xFFFF is what the four-byte
# format holds; the game's own per-item cap is unknown, and if it is lower `bag_slot_is_saturated` never fires.
BAG_SLOT_QUANTITY_MAX = 0xFFFF


def write_slot(slot_address: int, item_id: int, quantity: int) -> None:
    """Writes one Bag slot. Both fields are clamped into the u16 they pack into rather than raising: a
    struct.error here aborts a delivery, and no caller prefers that to the largest value the slot can hold."""
    write_bytes(slot_address, struct.pack(
        ">HH",
        max(0, min(int(item_id), BAG_SLOT_QUANTITY_MAX)),
        max(0, min(int(quantity), BAG_SLOT_QUANTITY_MAX)),
    ))


def bag_slot_is_saturated(pocket_base: int, max_slots: int, item_id: int) -> bool:
    """True when `item_id`'s slot is already at the largest quantity the format can hold, so no further
    `give_item` can change it. Lets the delivery confirm loop tell "this write has not landed yet" from "this
    write can never land" -- identical to a before/after quantity check, opposite situations for the caller."""
    # Any slot at the ceiling, not the total: `give_item` writes into one slot, so 70000 spread over two
    # slots is still growable.
    return any(
        slot.item_id == item_id and slot.quantity >= BAG_SLOT_QUANTITY_MAX
        for slot in read_pocket(pocket_base, max_slots)
    )


def give_item(pocket_base: int, item_id: int, quantity: int, max_slots: int) -> bool:
    """Increments quantity if item_id is already in this pocket, else writes it into the first empty slot.
    Returns False when the item is absent and the pocket is full; the caller decides what to do then.

    Only live-validated for the Items and Poke Ball pockets -- re-validate before trusting it elsewhere."""
    slots = read_pocket(pocket_base, max_slots)
    for slot in slots:
        if slot.item_id == item_id and not slot.empty:
                # Saturating add: this used to pack slot.quantity + quantity straight into a u16.
            write_slot(slot.address, item_id, min(slot.quantity + quantity, BAG_SLOT_QUANTITY_MAX))
            return True
    for slot in slots:
        if slot.empty:
            write_slot(slot.address, item_id, quantity)
            return True
    return False  # pocket full


def find_item_quantity(pocket_base: int, max_slots: int, item_id: int) -> int:
    """Total quantity held for `item_id` across this window (0 if absent -- the format has no "present with
    quantity 0"; a slot is either positive or the all-zero `empty` sentinel).

    SUMS every matching slot, because one id can legitimately occupy two: writes go through
    `resolve_item_pocket`'s narrow window (slot 82 and up for a berry) while reads go through the whole
    190-slot array, since the game's own item-add code fills from slot 0 upward. Returning the first match
    meant an item the player already owned reported a frozen count, the delivery confirm never fired, and the
    re-write every poll eventually overflowed the u16. `clear_item` clears every matching slot for the same
    reason -- a leftover slot reads as a fresh pickup next poll and credits a check nobody earned."""
    return sum(slot.quantity for slot in read_pocket(pocket_base, max_slots) if slot.item_id == item_id)


def give_item_verified(pocket_base: int, item_id: int, quantity: int, max_slots: int) -> bool:
    """`give_item` plus a real before/after Bag read: records this item's quantity, writes, re-reads the same
    slot range, and only reports success if the quantity rose by at least `quantity`.

    False on a full pocket AND on a write that produced no detectable change, so the caller's untouched-until-
    confirmed retry queue (Client.py's `given_item_indices`) retries it next poll.

    Both reads bracket the single `give_item` call with no await point between them -- read-write-read back to
    back, not a sampled comparison -- so nothing can realistically confound them. The one case it cannot rule
    out is the reverse: a write that stuck but the read-back missed, where retrying double-gives. That would be
    a Dolphin read/write inconsistency, a different bug, and is out of scope here."""
    before = find_item_quantity(pocket_base, max_slots, item_id)
    wrote = give_item(pocket_base, item_id, quantity, max_slots)
    if not wrote:
        return False  # pocket full -- give_item() never touched memory, nothing to verify
    after = find_item_quantity(pocket_base, max_slots, item_id)
    return after >= before + quantity


def clear_item(pocket_base: int, max_slots: int, item_id: int) -> bool:
    """Empties the slots holding `item_id` in this pocket via `write_slot(address, 0, 0)`, matching
    `BagSlot.empty`'s sentinel. True if anything was cleared, False if the item wasn't present.

    `ShopPurchaseTracker` clears a confirmed-purchased berry after each detection, because a shop can be
    bought from indefinitely and the dummy item's quantity has to return to 0 or the next purchase looks
    already-counted. `ChestCountTracker` deliberately never clears -- a chest opens once, so its berry total
    just accumulates."""
    # Clears EVERY matching slot, not just the first: `find_item_quantity` sums, and one id can occupy two
    # slots, so a leftover leaves a positive total while the caller resets its baseline to 0 -- which the next
    # poll reads as a fresh pickup and credits a check nobody earned.
    cleared = False
    for slot in read_pocket(pocket_base, max_slots):
        if slot.item_id == item_id and not slot.empty:
            write_slot(slot.address, 0, 0)
            cleared = True
    return cleared


def clear_item_verified(pocket_base: int, max_slots: int, item_id: int) -> "bool | None":
    """`clear_item` with a read-back, the mirror of `give_item_verified`.

    True when the item was present and is now gone, None when it was never there (nothing to do, not a
    failure), False when a clear was issued and the item is still readable -- a write that did not stick.

    The third answer exists because `clear_item` reports True the moment it issues the write. Its only
    repeating caller, `KeyItemReconciler`, is stateless and re-clears next poll anyway, so the cost was never
    a stuck state -- it was `!keyitems` showing a clear count climbing beside an item still in the Bag."""
    before = find_item_quantity(pocket_base, max_slots, item_id)
    if before <= 0:
        return None
    clear_item(pocket_base, max_slots, item_id)
    return find_item_quantity(pocket_base, max_slots, item_id) <= 0


# Key items are SEARCHED in every pocket they could be in, but still WRITTEN only to the routed one. A write window
# must be narrow because a wrong write corrupts a save; a read window must be as wide as the item could plausibly
# be, because the game's own item-add code does not use this client's windows.
#
# "Key items live in the Key Items pocket" is weaker evidence than it looks: every id resolved in 501-533 has a
# key-item NAME, but that says nothing about which pocket the game files it in, and this pocket has never been
# write-tested -- the only gating key item ever seen there live is the ID Card (506). Looking in both is free, since
# item ids are one global namespace, so id 503 in the Items pocket IS the Machine Part and no new writes are made.
def key_item_search_windows(block_base: int, item_id: int) -> "tuple[tuple[int, int], ...]":
    """Every (base, slots) window a managed key item could physically be sitting in.

    Routed window first, so a diagnostic printing the first hit prints the expected one. Duplicates dropped."""
    windows: "list[tuple[int, int]]" = []
    routed = resolve_item_pocket(block_base, item_id)
    if routed is not None:
        windows.append(routed)
    for candidate in ((block_base + KEY_ITEMS_OFFSET, KEY_ITEMS_MAX_SLOTS),
                      (block_base + ITEMS_POCKET_OFFSET, ITEMS_POCKET_MAX_SLOTS)):
        if candidate not in windows:
            windows.append(candidate)
    return tuple(windows)


def pocket_label(block_base: int, pocket_base: int) -> str:
    """A human name for a pocket base, for `!keyitems`. Unknown bases print their address rather than a
    guess -- the whole point of the readout is to say where something really is."""
    known = {
        block_base + ITEMS_POCKET_OFFSET: "Items",
        block_base + KEY_ITEMS_OFFSET: "Key Items",
        block_base + POKEBALL_POCKET_OFFSET: "Balls/TMs/Berries",
    }
    return known.get(pocket_base, f"0x{pocket_base:08X}")


# Confirm windows are DURATIONS in seconds, converted to poll counts from whatever interval the client runs
# (`Client.py` calls `set_poll_interval()` at startup; these defaults are the behaviour at a 1-second cadence). They
# ride out the save-menu glitch, which lasts wall-clock time, not a number of polls -- counted in polls, halving the
# poll interval would silently halve every window without touching a line that mentions a streak.
CONFIRM_WINDOW_SECONDS: "dict[str, float]" = {
    "species_catch": 4.0,     # ADDENDUM 99/146 -- the save-menu box glitch
    # The LONG window, for a box poll that gained more than one species at once. Three times the ordinary one:
    # see `SpeciesCatchTracker._MULTI_GAIN_CONFIRM_STREAK`.
    "species_catch_multi": 12.0,
    "purification": 4.0,      # ADDENDUM 99 -- same incident, recap records
    # 2.0 rather than 4.0, for the same reason as `chest_berry`: the 4.0 predates the block-stability gate, and
    # `check_shops` only runs when that gate says the block is not being rewritten, so this window is the second
    # line and not the first. One dict entry, so re-arming it is one edit.
    "shop_purchase": 2.0,     # ADDENDUM 111/218/259 -- same debounce, per berry, second line
    "battle_state": 3.0,      # ADDENDUM 202 -- consecutive clear polls before believing a battle ended
    # 0.0 -- the streak and the block-stability gate are the debounce; time never was. A longer window cannot win
    # against a write-then-rewrite, which answers "has this settled?" with yes for as long as the menu is open. The
    # constant is kept so re-arming it is one number.
    #
    # What holds the line: the block-stability gate asks a different QUESTION rather than the same one for longer --
    # it watches the same packed [id][qty] array the chest berries live in and calls the block untrustworthy when
    # more than BLOCK_CHURN_BYTE_THRESHOLD (16) bytes of it move between polls, where a save-menu rewrite moves far
    # more and opening a chest moves two. And `_CONFIRM_STREAK`'s two agreeing reads catch what the gate cannot: it
    # is deliberately blind to small changes, so a torn read of this berry's own u16 sails through it. Firing on the
    # FIRST sighting was not taken, because a torn read would then send a location the player never earned.
    #
    # THE TRAP THIS NUMBER SETS: `set_poll_interval` derives `_CONFIRM_STREAK` from this value, and at a 1.0s outer
    # cadence `ceil(0.5 / 1.0)` is 1 -- so lowering the clock would silently collapse guard 2 to "believe the first
    # reading" from one edit, with nothing in any log. `_MIN_CONFIRM_STREAK` is the floor that stops it, and
    # `_check_confirm_streak_floor` refuses the module at import if it is bypassed.
    "chest_berry": 0.0,
    # How long a pickup waits for a readable room. NOTE THE DIRECTION: the others guard against firing a check
    # TOO EARLY, so cutting one short risks a phantom. This one bounds how long a REAL pickup is held before being
    # abandoned, so cutting it short DROPS A CHECK THE PLAYER EARNED -- which is why the chest tracker treats it as
    # a floor on real elapsed time and never on a poll count.
    "chest_pending": 4.0,
}

POLL_INTERVAL_SECONDS: float = 1.0   # what the client is actually running; set by set_poll_interval()


def polls_for_seconds(seconds: float) -> int:
    """How many polls cover `seconds` at the live cadence. Never below 1 -- a window of zero polls would mean
    'believe the first reading', which is the absence of a debounce rather than a short one."""
    import math

    interval = POLL_INTERVAL_SECONDS if POLL_INTERVAL_SECONDS > 0 else 1.0
    return max(1, math.ceil(seconds / interval))


def set_poll_interval(seconds: float) -> "dict[str, int]":
    """Tell this module how often the client polls, and re-derive every debounce from its real duration.

    Called once at client startup. Returns the resulting poll counts so the caller can log them -- a debounce
    that silently changed length is precisely what this function exists to prevent, so it is made visible
    rather than merely made correct."""
    global POLL_INTERVAL_SECONDS
    if not seconds or seconds <= 0:
        return {}
    POLL_INTERVAL_SECONDS = float(seconds)
    resolved = {name: polls_for_seconds(window) for name, window in CONFIRM_WINDOW_SECONDS.items()}
    SpeciesCatchTracker._CONFIRM_STREAK = resolved["species_catch"]
    SpeciesCatchTracker._MULTI_GAIN_CONFIRM_STREAK = resolved["species_catch_multi"]
    NamedPurificationTracker._CONFIRM_STREAK = resolved["purification"]
    ShopPurchaseTracker._CONFIRM_STREAK = resolved["shop_purchase"]
    BattleStateTracker.CONFIRM_POLLS = resolved["battle_state"]
    # ADDENDUM 373: never below the tracker's own floor. A window shorter than the poll interval resolves to a
    # single poll, and a streak of one is not a debounce -- see `CONFIRM_WINDOW_SECONDS["chest_berry"]`.
    resolved["chest_berry"] = max(resolved["chest_berry"], ChestBerryTracker._MIN_CONFIRM_STREAK)
    ChestBerryTracker._CONFIRM_STREAK = resolved["chest_berry"]
    ChestBerryTracker._MAX_PENDING_POLLS = resolved["chest_pending"]
    return resolved


# --- Item-pocket routing. Maps a real Bag `game_item_id` (items.py / pokemon-xd-confirmed-item-ids.md) to a
# pocket array plus a slot window inside it that this session confirmed safe to write:
#   1. Balls (1-12)        -> Balls+TMs pocket, slots 0-11
#   2. TMs/HMs (289-346)   -> Balls+TMs pocket, slots 16-74. NEVER 75-81: writing a non-Ball/TM id there
#                             produces corrupted display.
#   3. Berries (133-175)   -> Berries pocket at POKEBALL_POCKET_OFFSET + 82*4, windowed to slots 82-124 so it
#                             never touches the reserved 129-140 sub-range. Vanilla puts 133-145 in the Items
#                             pocket, but this client writes by raw address and the player asked for every
#                             berry in the Berries tab, so all of them route here.
#   4. Key items (500-533) -> Key Items pocket, slots 0-42.
#   5. Everything else with a confirmed id (13-225) -> Items pocket, slots 0-29.
#   6. `game_item_id is None` (Ein File S, the unresolved key items, the trap item) -> no RAM write;
#      `route_and_give_item` returns None so Client.py can announce-only or apply a client-side effect.

BALLS_SLOT_COUNT = 12                        # pocket-relative slots 0-11
TM_HM_POCKET_RELATIVE_START = 16             # pocket-relative slot 16 ...
TM_HM_SLOT_COUNT = 59                        # ... through 74 inclusive -- NEVER 75-81
BERRIES_POCKET_RELATIVE_START = 82           # "at or before pocket-relative slot 82" per the confirmed doc
BERRIES_SLOT_COUNT = 43                      # 82-124 inclusive, short of the reserved 129-140 range

# Full confirmed extent of the shared Poke Ball/TM/Berries array: (MONEY_OFFSET - POKEBALL_POCKET_OFFSET)/4. Read
# windows use this rather than a sub-window, because the narrow berry window above is a safe-WRITE zone for this
# client while a chest pickup is inserted by the game's own item-add code, which fills from low slots upward.
POKEBALL_POCKET_ARRAY_SLOT_COUNT = (MONEY_OFFSET - POKEBALL_POCKET_OFFSET) // 4  # 190


def resolve_item_pocket(block_base: int, game_item_id: int | None) -> tuple[int, int] | None:
    """Pure routing lookup: `(pocket_base, max_slots)` for `game_item_id`, or None when it is None.

    Split out of `route_and_give_item` so `Client.give_items()` can drive its own write/verify timing across
    separate polls. Does no I/O -- arithmetic against the confirmed-safe ranges documented above."""
    if game_item_id is None:
        return None
    if 1 <= game_item_id <= BALLS_SLOT_COUNT:
        return block_base + POKEBALL_POCKET_OFFSET, BALLS_SLOT_COUNT
    if 289 <= game_item_id <= 346:
        return block_base + POKEBALL_POCKET_OFFSET + TM_HM_POCKET_RELATIVE_START * 4, TM_HM_SLOT_COUNT
    # The full berry index range, not just the 146-175 the vanilla game files here: the player asked for every
    # berry this pool can produce to land in the Berries tab.
    if 133 <= game_item_id <= 175:
        return block_base + POKEBALL_POCKET_OFFSET + BERRIES_POCKET_RELATIVE_START * 4, BERRIES_SLOT_COUNT
    # 500-533, verified rather than assumed: every id resolved in 501-533 is a key item (Elevator Key 501 through
    # Disc Case 533, no non-key item in the span), and 500 is the Safe Key, resolved but unused. The range used to
    # stop at 523, so every gating key item (501-519) fell through to the Items pocket while the game keeps them in
    # Key Items -- so the reconciler read the wrong array and a key item Archipelago sent went where the game's
    # gating checks never look.
    if 500 <= game_item_id <= 533:
        return block_base + KEY_ITEMS_OFFSET, KEY_ITEMS_MAX_SLOTS
    # Default: the Items pocket, which tolerates any item id -- correct for the documented 13-225 range and a
    # safe fallback for any other real id this table does not special-case.
    return block_base + ITEMS_POCKET_OFFSET, ITEMS_POCKET_MAX_SLOTS


def resolve_item_read_window(block_base: int, game_item_id: "int | None") -> "tuple[int, int] | None":
    """Where to READ an item from: `(base address, slot count)`, or None when the id has no pocket.

    Returns base and count together so they cannot be mispaired. An earlier version returned only a count and
    every caller paired it with the narrow WRITE base from `resolve_item_pocket`; for a berry that base is array
    slot 82, so a 190-slot read from there both missed slots 0-81 -- exactly where the game's own item-add code
    puts a berry picked out of a chest, so no chest check ever fired -- and ran 328 bytes past the end of the
    array into money, which `_clear` would have written into on a match.

    Read and write extents are different questions. The narrow per-category windows above are what this client
    is confirmed safe to WRITE into; where an id can legitimately be FOUND is wider, because the game fills the
    Bag from low slots upward. A baseline read through the write window reports 0 for an item the player already
    owns, and the confirm that follows compares against a number that was never true.

    Only the shared Poke Ball / TM / Berries array is widened, since its sub-windows are carved out of one
    larger confirmed array. Items and Key Items are their own arrays, already read at full extent."""
    pocket = resolve_item_pocket(block_base, game_item_id)
    if pocket is None:
        return None
    in_shared_array = (
        1 <= game_item_id <= BALLS_SLOT_COUNT
        or 289 <= game_item_id <= 346
        or 133 <= game_item_id <= 175
    )
    if in_shared_array:
        # The array BASE, not the sub-window base. This is the whole bug in one line.
        return block_base + POKEBALL_POCKET_OFFSET, POKEBALL_POCKET_ARRAY_SLOT_COUNT
    return pocket


def route_and_give_item(block_base: int, game_item_id: int | None, quantity: int = 1) -> bool | None:
    """Delivers one AP-placed item into the right pocket in a single call: write, then immediately re-verify.
    True when confirmed by the re-read, False on a full pocket or an unconfirmed read-back, None when
    `game_item_id` is None.

    `Client.give_items()` no longer uses this: an immediate same-call verify can report a false positive,
    because it reads back the exact bytes just written microseconds earlier, before anything else could touch
    that memory. The live client spreads write and verify across separate polls using `resolve_item_pocket` /
    `find_item_quantity` / `give_item` directly. Kept as a correct single-shot helper for callers that do not
    need the cross-poll timing."""
    pocket = resolve_item_pocket(block_base, game_item_id)
    if pocket is None:
        return None
    pocket_base, max_slots = pocket
    return give_item_verified(pocket_base, game_item_id, quantity, max_slots)


# --- Money (plain u32BE, not a pocket record) ---

def read_money(block_base: int) -> int:
    return struct.unpack(">I", read_bytes(block_base + MONEY_OFFSET, 4))[0]


def write_money(block_base: int, value: int) -> None:
    write_bytes(block_base + MONEY_OFFSET, struct.pack(">I", value))


# --- Monotonic progress counter: the witness a redelivery system needs. ---
# `give_items` commits an index to client-side state once the Bag quantity confirms the write, and nothing in that
# chain involves the player SAVING -- so a crash in between loses the item with the client still counting it given,
# undetectably. Detecting that needs a save-block value that only ever rises.
#
# Found offline across twelve MEM1 dumps from one 104-minute session (block base 0x80478F00 in all twelve): every
# u32 and u16 in block+0x0000..0x9000 tested for "never decreases, rises at three or more steps, ends below a
# plausible ceiling". Exactly one u32 survived -- 1094 -> 2369 over the session, rising at ten of eleven steps, the
# exception being the Eevee-stone-to-evolution cutscene, so it counts player actions rather than time. Flat across
# two reboots while money was flat too, which is what a save-resident value looks like. Not yet confirmed in play
# and deliberately not load-bearing: `!progress` prints it, nothing decides on it.
PROGRESS_COUNTER_OFFSET = 0x908       # u32BE; the high half is zero in every dump examined
PROGRESS_COUNTER_MAX_PLAUSIBLE = 0x00FFFFFF


def read_progress_counter(block_base: int) -> "int | None":
    """The save block's monotonic progress counter, or None when it cannot be read or reads implausibly.

    Refuses rather than guessing: "the read failed" must never look like "the counter went backwards"."""
    try:
        value = struct.unpack(">I", read_bytes(block_base + PROGRESS_COUNTER_OFFSET, 4))[0]
    except Exception:
        return None
    if value > PROGRESS_COUNTER_MAX_PLAUSIBLE:
        return None
    return value


# --- Species detection: party + PC box ---
# Goal: notice a National Dex # appearing somewhere the player owns it that was not seen before, and turn it into a
# "Catch - {species}" check. Two sources, very different confidence: `read_party_species` is confirmed at a stable
# address and safe to poll continuously, while `read_box_slot_species` is best-effort only -- the per-slot stride is
# confirmed but whether a slot NOT currently displayed in the box UI holds real data is not, and the ram-map doc
# reads the evidence as a single relocating "currently viewed" buffer. A blind sweep risks false negatives and,
# worse, false positives, so only pass it slot indices the caller has reason to think are on screen now.

# `species` from this struct was once thought unreliable: a member reading name="SPHEAL" with correct level and HP
# read species=316, Gulpin's dex #, in two dumps minutes apart. Never a desync -- 316 + 25 (the live-index gap) is
# 341, and xd_species_index.national_dex_for(341) == 363 == Spheal. So it is fine through
# `national_dex_for_live_species()` (see `PartyMember.national_dex`), which is preferable to name-based lookup since
# that stops working once a member is renamed, as purification invites. Cache a species BEFORE any rename.

def read_party_species(party_base: int = PARTY_BASE, max_slots: int = PARTY_MAX_SLOTS) -> list[int]:
    """National Dex # of every non-empty party slot, in slot order.

    Resolves the raw field through `xd_species_index.national_dex_for_live_species()`: it is only a dex # as-is
    for species 1-251. All-zero slots ("never filled") are skipped, as is a raw value the conversion cannot
    resolve -- defensive, and not expected for real game data."""
    national_dex_for_live_species = _load_xd_species_index().national_dex_for_live_species
    species: list[int] = []
    for i in range(max_slots):
        slot_species_addr = party_base + i * PARTY_SLOT_STRIDE + PARTY_SPECIES_OFFSET
        raw = struct.unpack(">H", read_bytes(slot_species_addr, 2))[0]
        if raw == 0:
            continue
        dex_number = national_dex_for_live_species(raw)
        if dex_number is not None:
            species.append(dex_number)
    return species


@dataclass
class PartyMember:
    """One occupied PARTY_BASE slot. `name`, `level`, `max_hp`, `current_hp` are continuously live-synced.
    `species` is the raw field in RAM's own compacted indexing, NOT a National Dex # for species 252+ -- use
    `national_dex` unless you specifically want the raw live index."""

    party_index: int
    name: str  # current nickname if the player set one, else the species' default display name
    species: int  # raw numeric field, live RAM's own compacted index -- see national_dex for the resolved value
    level: int
    max_hp: int
    current_hp: int

    @property
    def national_dex(self) -> int | None:
        """Real National Dex # for this member. The recommended way to identify a party member's species: it
        keeps working after a rename, which `reliable_species` does not."""
        return _load_xd_species_index().national_dex_for_live_species(self.species)

    @property
    def reliable_species(self) -> int | None:
        """species_dex_from_name(self.name); None when `name` is a nickname rather than a species name. Kept
        for compatibility -- prefer `national_dex`, which has no post-rename gap."""
        return species_dex_from_name(self.name)


def read_party_members(party_base: int = PARTY_BASE, max_slots: int = PARTY_MAX_SLOTS) -> list[PartyMember]:
    """Like read_party_species, but full per-slot info including the current name/nickname -- the reliable half
    of the two-structure correlation in read_purified_party_members. Skips empty slots the same way."""
    members = []
    for i in range(max_slots):
        slot_addr = party_base + i * PARTY_SLOT_STRIDE
        species = struct.unpack(">H", read_bytes(slot_addr + PARTY_SPECIES_OFFSET, 2))[0]
        if species == 0:
            continue
        name = read_bytes(slot_addr, PARTY_NAME_MAX_BYTES).decode("utf-16-be", errors="replace").split("\x00")[0]
        level = read_bytes(slot_addr + PARTY_LEVEL_OFFSET, 1)[0]
        max_hp = struct.unpack(">H", read_bytes(slot_addr + PARTY_MAXHP_OFFSET, 2))[0]
        current_hp = struct.unpack(">H", read_bytes(slot_addr + PARTY_CURHP_OFFSET, 2))[0]
        members.append(PartyMember(i, name, species, level, max_hp, current_hp))
    return members


def read_box_slot_species(block_base: int, slot_index: int, slots_per_box: int = 30) -> int | None:
    """National Dex # at a flat box slot index (0 = Box 1 Slot 1), using the confirmed addressing formula
    including the per-box padding term.

    None for a zero read -- an empty slot OR a just-deposited Pokemon whose species sub-field has not synced, and
    those two are not distinguishable from this read alone -- or a raw value outside 1-386. The raw field is a LIVE
    INDEX and is converted before it is returned.

    Still not safe in a blind background sweep: not because the address might be wrong, but because the species
    sub-field can read stale data for some uncharacterised window after a deposit. Prefer the party struct for
    anything that must fire promptly, and treat box reads as a slower-cadence or explicitly-triggered check."""
    box_idx, local_slot_idx = divmod(slot_index, slots_per_box)
    text_anchor = (
        block_base
        + BOX_SLOT_TEXT_ANCHOR_OFFSET
        + box_idx * (slots_per_box * BOX_SLOT_STRIDE + BOX_PADDING_PER_BOX)
        + local_slot_idx * BOX_SLOT_STRIDE
    )
    # This field is a LIVE INDEX, not a National Dex number, and was once returned raw behind a 1-386 bounds check.
    # 109 raw values in 276-386 resolve to a DIFFERENT dex number under the conversion and every one of those wrong
    # numbers names a real `Catch - ` location -- all inside 1-386, which is what makes this shape of bug survive a
    # bounds check. The trigger is narrow and real: `species_owned_from_block` reads boxes BY NAME and falls back
    # here only when the name does not resolve, which is precisely what a NICKNAMED box Pokemon does. A value the
    # conversion cannot resolve is DROPPED, not passed through.
    raw = struct.unpack(">I", read_bytes(text_anchor + BOX_SLOT_SPECIES_OFFSET, 4))[0]
    if raw == 0 or raw > 386:
        return None
    return _load_xd_species_index().national_dex_for_live_species(raw)


def read_box_slot_name(block_base: int, slot_index: int, slots_per_box: int = 30) -> str:
    """Name text at a flat box slot index's own text anchor, same addressing as `read_box_slot_species`. Returns ""
    for an empty slot. Reads PARTY_NAME_MAX_BYTES (0x16), matching the party struct's own convention, with anything
    past the null terminator discarded."""
    box_idx, local_slot_idx = divmod(slot_index, slots_per_box)
    text_anchor = (
        block_base
        + BOX_SLOT_TEXT_ANCHOR_OFFSET
        + box_idx * (slots_per_box * BOX_SLOT_STRIDE + BOX_PADDING_PER_BOX)
        + local_slot_idx * BOX_SLOT_STRIDE
    )
    raw = read_bytes(text_anchor, PARTY_NAME_MAX_BYTES)
    return raw.decode("utf-16-be", errors="replace").split("\x00")[0]


def read_box_slot_species_by_name(block_base: int, slot_index: int, slots_per_box: int = 30) -> int | None:
    """Species at a box slot, resolved from the slot's NAME TEXT rather than the numeric field.

    `read_box_slot_species` reads BOX_SLOT_SPECIES_OFFSET, which is unreliable for a slot recently deposited into --
    exactly the case that matters here, since a fresh catch with a full party is auto-routed straight to the PC and
    never touches the party struct. Name text has been correct in every structure tested in this project, unlike any
    raw numeric species field.

    None for an empty slot or a name that is not a real species, a nickname being the expected non-error case."""
    name = read_box_slot_name(block_base, slot_index, slots_per_box)
    if not name:
        return None
    return species_dex_from_name(name)


# No real box-COUNT ceiling has been confirmed -- only that the addressing formula holds through Box 8 (seven
# boundaries, two independent data points). Set generously past that: over-scanning is cheap (an out-of-range slot
# will almost never decode to an exact uppercase species name, and per-slot read failures are caught) while
# under-scanning would silently miss real catches in a later box.
PC_BOX_SCAN_COUNT = 12
PC_BOX_SLOTS_PER_BOX = 30


def get_box_species_snapshot_detailed(
    block_base: int,
    num_boxes: int = PC_BOX_SCAN_COUNT,
    slots_per_box: int = PC_BOX_SLOTS_PER_BOX,
) -> "tuple[set[int], int]":
    """`(species, slots that could not be read)`.

    The plain `get_box_species_snapshot` swallows a failed slot read and moves on, which is right as far as it goes:
    one bad address must not take down the scan. What was missing is that the CALLER could not tell "this species is
    no longer in the boxes" from "the slot it lives in did not read this poll", because a set has no way to say
    incomplete."""
    owned: set[int] = set()
    failures = 0
    for slot_index in range(num_boxes * slots_per_box):
        try:
            dex_number = read_box_slot_species_by_name(block_base, slot_index, slots_per_box)
        except Exception:
            failures += 1
            continue
        if dex_number is not None:
            owned.add(dex_number)
    return owned, failures


def get_box_species_snapshot(
    block_base: int,
    num_boxes: int = PC_BOX_SCAN_COUNT,
    slots_per_box: int = PC_BOX_SLOTS_PER_BOX,
) -> set[int]:
    """Every PC box slot's species (name-text based), as a set of National Dex #s.

    Runs every poll beside the party-only snapshot, and covers a Pokemon sitting in the PC that has never been
    in the party this boot (auto-deposited on a full-party catch). Each slot is read in its own try/except so
    one bad read is "no data this slot" rather than a lost poll. Local DME reads are microseconds, so the full
    sweep every poll costs nothing meaningful."""
    owned: set[int] = set()
    for slot_index in range(num_boxes * slots_per_box):
        try:
            dex_number = read_box_slot_species_by_name(block_base, slot_index, slots_per_box)
        except Exception:
            continue
        if dex_number is not None:
            owned.add(dex_number)
    return owned


@dataclass
class SpeciesCatchTracker:
    """Decides which "Catch - {X}" checks to send, with the save-menu glitch guarded against.

    Opening the save menu can make the PC-box name-text scan briefly read a previously-saved box layout. Firing off
    that snapshot sent catches the player never made this seed, and unlike stale chest or purification reads the
    server does not dedupe them away -- those locations really had never been checked. A false catch is unrecoverable
    within a seed; a late one is only late.

    Three layered guards: the party half is untouched, since PARTY_BASE is continuously live and has never been
    implicated, so a species seen there fires on the same poll; a structurally implausible box poll is discarded whole
    and does NOT become the new baseline, so a glitch snapshot can never be mistaken for the truth however long the
    menu stays open; and a surviving box-only candidate must hold for `_CONFIRM_STREAK` consecutive trusted polls,
    which covers the shape guard 2 cannot see. A heuristic, not a root-cause fix: there is still no live "is a menu
    open" signal to gate on.

    The first poll primes, reporting everything currently owned, so a fresh connection or mid-seed reconnect sends the
    catches the player already has. Safe -- the server dedupes, and there is no earlier snapshot."""

    seen: set = None                     # type: ignore[assignment]  # dex numbers already reported
    _last_box: set = None                # type: ignore[assignment]  # last TRUSTED box snapshot; None until primed
    _pending_streak: dict = None         # type: ignore[assignment]  # box-only dex number -> consecutive trusted polls
    primed: bool = False
    distrusted_polls: int = 0            # diagnostics only -- surfaced by !catches

    # Consecutive trusted polls a box-only candidate must survive, matching the other trackers. ClassVar, not a
    # dataclass field: `set_poll_interval()` re-derives it at startup, and a field default is captured at class
    # creation, so a class-attribute assignment would not reach new instances.
    _CONFIRM_STREAK: ClassVar[int] = 4
    # More new box species than this in one poll means more than one thing happened since the last scan. 1,
    # because a catch, a deposit and a withdrawal each move exactly one Pokemon. Not a distrust test -- a
    # slow-down test; see below.
    _MAX_NEW_BOX_SPECIES_PER_POLL: int = 1

    # "A catch moves exactly one Pokemon" is true per EVENT and false per BATTLE: seventeen trainers carry more than
    # one Shadow (Eldes four, Greevil six), and snagging two with a full party auto-deposits both, so the next box
    # scan gains two species in one poll. Guard 2 discarded that poll, and a discarded poll does not update
    # `_last_box`, so every later poll made the identical failing comparison forever.
    #
    # So guard 2's two clauses do different jobs: gained AND lost is the box reading as a different snapshot of
    # itself and stays distrusted, while a pure gain of more than one is play and is trusted so the baseline
    # advances. The price is that species introduced by a multi-gain poll owe `_MULTI_GAIN_CONFIRM_STREAK` instead
    # -- a glitch is transient by definition and falls out of a window that wide, while two Shadows in the PC do not.
    _MULTI_GAIN_CONFIRM_STREAK: ClassVar[int] = 12

    #: Species introduced by a multi-gain poll and not yet confirmed -- they owe the long streak.
    _slow_candidates: set = None         # type: ignore[assignment]
    multi_gain_polls: int = 0            # diagnostics only -- surfaced by !catches

    # Guard 2 used to be ABSORBING, and a flaky read was the key that locked it. Two defects, both needed:
    # `get_box_species_snapshot` returns a set and silently drops slots it could not read, so a transient failure
    # looked exactly like "those Pokemon are gone" -- and a pure shrink passes guard 2 and became the baseline,
    # missing species that really are there. The next correct poll gains them back, which distrusts it, and a
    # distrusted poll does not update `_last_box`, so the comparison repeats identically forever. Worse,
    # `_pending_streak.clear()` runs each distrusted poll, so nothing needing a streak can fire.
    #
    # Two rules fix it. An unreadable slot is "ask again next poll", never "the answer is no": an incomplete
    # snapshot may ADD a species but never conclude a loss and never become a baseline. And a glitch is transient,
    # so an identical distrusted snapshot repeating `_DISTRUST_RESYNC_POLLS` times is re-adopted as the baseline,
    # firing nothing -- turning a permanent stall into a bounded delay.
    _DISTRUST_RESYNC_POLLS: ClassVar[int] = 5

    _distrust_run: int = 0
    _distrusted_snapshot: set = None     # type: ignore[assignment]
    resyncs: int = 0                     # times a steady distrusted snapshot was re-adopted
    incomplete_polls: int = 0            # polls where at least one box slot could not be read

    def __post_init__(self) -> None:
        if self.seen is None:
            self.seen = set()
        if self._pending_streak is None:
            self._pending_streak = {}
        if self._slow_candidates is None:
            self._slow_candidates = set()

    def poll(self, party_species: "set[int]", box_species: "set[int]",
             recap_species: "set[int] | None" = None,
             box_complete: bool = True) -> "list[int]":
        """Dex numbers whose "Catch - {X}" location should be sent on this poll, ascending. Never raises; callers
        pass snapshots they already read.

        The three sources have different failure modes and get different treatment. Mixing the block party into
        `box_species` put party-shaped data through guard 2, whose premise is that real play mutates the boxes one slot
        at a time -- a withdrawal makes the boxes lose a species and the recap gain one in the same poll, which guard 2
        read as the glitch, so managing just-caught Pokemon drove the tracker into a distrust loop. So:

          * `party_species` (PARTY_BASE)  -- continuously live, never implicated, empty until a menu opens. Trusted.
          * `box_species`   (PC boxes)    -- where the glitch was seen. Guards 2 and 3, against a box-only snapshot.
          * `recap_species` (block party) -- guard 3 but NOT guard 2: a party legitimately gains and loses several
                                            members at once, so the structural test only produced false distrust.

        `recap_species=None` keeps the old two-argument behaviour rather than silently changing what a caller
        measures."""
        party_species = set(party_species)
        box_species = set(box_species)
        recap_species = set(recap_species) if recap_species is not None else set()

        if not self.primed:
            # First sighting: no prior snapshot exists, so there is nothing to validate against. Report
            # everything and adopt it as the baseline.
            self.primed = True
            self._last_box = box_species
            newly = sorted((party_species | box_species | recap_species) - self.seen)
            self.seen |= set(newly)
            return newly

        newly_seen: set[int] = set()

        # Guard 1: the party struct is trusted as it always was.
        for dex_number in party_species - self.seen:
            newly_seen.add(dex_number)

        # Guard 2: is this poll's BOX snapshot structurally believable? Boxes only -- see the docstring.
        previous_box = self._last_box if self._last_box is not None else set()
        # An INCOMPLETE scan cannot testify to an absence: species in the previous baseline are carried
        # forward, so a failed slot read can never shrink it. It can still ADD -- a name that decoded is there.
        if not box_complete:
            self.incomplete_polls += 1
            box_species = box_species | previous_box
        gained = box_species - previous_box
        lost = previous_box - box_species
        # Gained AND lost is the box reading as a different snapshot of itself: distrusted. A pure gain of more
        # than one is play (two Shadows in one battle), so it is trusted and the baseline advances; the species
        # it brought owe the long streak instead.
        trustworthy = not (gained and lost)
        multi_gain = trustworthy and len(gained) > self._MAX_NEW_BOX_SPECIES_PER_POLL
        if multi_gain:
            self.multi_gain_polls += 1
            self._slow_candidates |= (gained - self.seen)
        healed = False
        if not trustworthy:
            self.distrusted_polls += 1
            # REPAIR THE BASELINE, do not adopt the snapshot: a bare "a steady reading is the truth" rule would
            # adopt a glitch snapshot of never-caught species and eventually send them. The stall's signature is
            # narrower -- the baseline is missing species we have ALREADY CREDITED because their slots failed to read
            # once -- and putting only `gained & self.seen` back cannot send a check by construction.
            if self._distrusted_snapshot == box_species:
                self._distrust_run += 1
            else:
                self._distrusted_snapshot = set(box_species)
                self._distrust_run = 1
            recoverable = gained & self.seen
            if self._distrust_run >= self._DISTRUST_RESYNC_POLLS and box_complete and recoverable:
                self._last_box = previous_box | recoverable
                self._distrusted_snapshot = None
                self._distrust_run = 0
                self.resyncs += 1
                healed = True
        else:
            self._last_box = box_species
            self._distrusted_snapshot = None
            self._distrust_run = 0

        # Guard 3: anything not already trusted has to hold for _CONFIRM_STREAK consecutive polls. Box
        # candidates only count on a trusted poll; recap candidates are not subject to guard 2 at all, so they
        # accumulate regardless -- which is what stops a PC withdrawal from resetting a real catch's streak.
        candidates = (recap_species - self.seen - party_species)
        if trustworthy:
            candidates |= (box_species - self.seen - party_species)
        # ADDENDUM 290: a distrusted BOX poll says nothing about the RECAP source, which guard 2 does not even
        # apply to. Clearing the whole streak dict meant one flaky box read reset a real party catch's
        # progress every single poll, so while stuck nothing could ever reach the streak at all.
        for dex_number in list(self._pending_streak):
            if dex_number not in candidates:
                self._pending_streak.pop(dex_number, None)
        # ADDENDUM 333: a slow candidate that stopped being a candidate at all forgets it was ever slow, so a
        # re-appearance restarts from scratch rather than resuming -- the rule ADDENDUM 146's
        # `test_a_vanished_candidate_restarts_rather_than_resuming` already fixed for the ordinary streak.
        self._slow_candidates &= (candidates | self.seen)
        # The RECAP outranks the slow window entirely: that window exists to outlast a pure-gain BOX glitch, and the
        # save-block party is a different source guard 2 does not apply to, so a species it also reports has
        # corroboration the box suspicion cannot speak to. Without this a real party catch inherited the slow window
        # from an unrelated multi-gain poll.
        self._slow_candidates -= recap_species
        if healed:
            # The repair is a baseline correction, not an observation. Box candidates from the poll that
            # triggered it wait for the next one, which will be judged against a baseline that describes
            # reality again -- `recoverable` only ever holds already-credited species, so nothing is lost.
            candidates &= recap_species
        for dex_number in candidates:
            streak = self._pending_streak.get(dex_number, 0) + 1
            # ADDENDUM 333: a species a multi-gain poll introduced owes the long window; everything else owes
            # the ordinary one. Resolved per species rather than per poll, so one double-snag never slows
            # down the ordinary catches happening around it.
            required = (self._MULTI_GAIN_CONFIRM_STREAK if dex_number in self._slow_candidates
                        else self._CONFIRM_STREAK)
            if streak >= required:
                newly_seen.add(dex_number)
                self._pending_streak.pop(dex_number, None)
                self._slow_candidates.discard(dex_number)
            else:
                self._pending_streak[dex_number] = streak

        self.seen |= newly_seen
        # A species confirmed through the party this poll should not also be sitting in the queue.
        for dex_number in newly_seen:
            self._pending_streak.pop(dex_number, None)
            self._slow_candidates.discard(dex_number)
        return sorted(newly_seen)

    def describe(self) -> str:
        if not self.primed:
            return "Species catches: not primed yet (no party/box snapshot read)."
        pending = ", ".join(
            f"#{dex} ({streak}/"
            f"{self._MULTI_GAIN_CONFIRM_STREAK if dex in self._slow_candidates else self._CONFIRM_STREAK}"
            f"{' slow' if dex in self._slow_candidates else ''})"
            for dex, streak in sorted(self._pending_streak.items())
        ) or "none"
        return (
            f"Species catches: {len(self.seen)} species reported. "
            f"Box snapshot holds {len(self._last_box or set())} species. "
            f"Awaiting confirmation: {pending}. "
            f"Box polls discarded as implausible so far: {self.distrusted_polls} "
            f"(save-menu glitch guard, ADDENDUM 146). "
            f"ADDENDUM 290: {self.incomplete_polls} poll(s) had an unreadable box slot (carried forward "
            f"rather than read as a loss), {self.resyncs} re-sync(s) after a steady distrusted snapshot. "
            f"ADDENDUM 333: {self.multi_gain_polls} poll(s) gained more than one species at once (two "
            f"Shadows snagged in one battle, typically) -- trusted, but those species hold for "
            f"{self._MULTI_GAIN_CONFIRM_STREAK} polls rather than {self._CONFIRM_STREAK}."
        )


@dataclass
class PartyRecapRecord:
    """One party member's 196-byte "recap" record -- see the PARTY_RECAP_* constants' comments above for the
    full derivation and caveats (in particular: `species` is NOT reliable, and any single field here should be
    read as "possibly stale" unless it's known to have just changed -- this whole record only refreshes
    per-slot on a recap-worthy event, it isn't continuously live-synced like PARTY_BASE)."""

    party_index: int
    address: int
    name: str
    species: int  # unreliable, see PARTY_RECAP_SPECIES_OFFSET
    purified_flag: int  # 0 observed pre-purification, 64 (0x40) observed post-purification (2x confirmed)
    max_hp: int
    attack: int
    defense: int
    sp_attack: int
    sp_defense: int
    speed: int


def read_party_recap_record(block_base: int, party_index: int) -> PartyRecapRecord:
    """Reads party slot `party_index`'s recap record. Does NOT check the slot is occupied -- an empty slot's
    record contents are untested, so cross-reference read_party_species for which indices are real."""
    address = block_base + PARTY_RECAP_OFFSET + party_index * PARTY_RECAP_STRIDE
    raw = read_bytes(address, PARTY_RECAP_STRIDE)
    name = raw[0:0x12].decode("utf-16-be", errors="replace").split("\x00")[0]
    species = struct.unpack(">H", raw[PARTY_RECAP_SPECIES_OFFSET:PARTY_RECAP_SPECIES_OFFSET + 2])[0]
    purified_flag = struct.unpack(
        ">H", raw[PARTY_RECAP_PURIFIED_FLAG_OFFSET:PARTY_RECAP_PURIFIED_FLAG_OFFSET + 2]
    )[0]
    max_hp = struct.unpack(">H", raw[PARTY_RECAP_MAXHP_OFFSET:PARTY_RECAP_MAXHP_OFFSET + 2])[0]
    stats = {
        stat_name: struct.unpack(">H", raw[off:off + 2])[0]
        for stat_name, off in PARTY_RECAP_STAT_OFFSETS.items()
    }
    return PartyRecapRecord(
        party_index=party_index,
        address=address,
        name=name,
        species=species,
        purified_flag=purified_flag,
        max_hp=max_hp,
        attack=stats["attack"],
        defense=stats["defense"],
        sp_attack=stats["sp_attack"],
        sp_defense=stats["sp_defense"],
        speed=stats["speed"],
    )


# The party is read out of the SAVE BLOCK, not just PARTY_BASE. PARTY_BASE is a menu row (name / species / level /
# MaxHP / CurHP) and does not populate a slot for a Pokemon never drawn on the party screen -- i.e. a fresh catch,
# which is why catches used to need the player to open the party screen while the PC scan worked unattended. The
# save-block records live at PARTY_RECAP_OFFSET with PARTY_RECAP_STRIDE, same format and name-text-at-offset-0
# convention as the box array. PARTY_BASE stays as the fast path and the two are unioned under the confirmation
# guards, so either one lagging is covered by the other.
def read_party_recap_name(block_base: int, party_index: int) -> str:
    """Name text of party slot `party_index`'s save-block record, or "" for an empty slot.

    Reads PARTY_NAME_MAX_BYTES (0x16), not the 0x12 `read_party_recap_record` uses, which truncates a
    10-character species name (AERODACTYL, BUTTERFREE) at 9 and would drop those species from detection."""
    address = block_base + PARTY_RECAP_OFFSET + party_index * PARTY_RECAP_STRIDE
    raw = read_bytes(address, PARTY_NAME_MAX_BYTES)
    return raw.decode("utf-16-be", errors="replace").split("\x00")[0]


# A record whose MaxHP is outside this range is not an occupied slot. An empty slot's record contents are
# untested, so the name alone cannot call a slot occupied. 999 is the series HP ceiling.
PARTY_RECAP_PLAUSIBLE_MAX_HP = 999


def read_party_recap_species(block_base: int, party_index: int) -> "int | None":
    """National Dex # for party slot `party_index`, read from the save block rather than PARTY_BASE.

    Name-text based, because the record's own PARTY_RECAP_SPECIES_OFFSET is unreliable. None for an empty slot,
    an implausible MaxHP, or a name that is not a species -- a nickname being the expected case for the last."""
    name = read_party_recap_name(block_base, party_index)
    if not name:
        return None
    dex_number = species_dex_from_name(name)
    if dex_number is None:
        return None
    address = block_base + PARTY_RECAP_OFFSET + party_index * PARTY_RECAP_STRIDE
    max_hp = struct.unpack(
        ">H", read_bytes(address + PARTY_RECAP_MAXHP_OFFSET, 2)
    )[0]
    if not 0 < max_hp <= PARTY_RECAP_PLAUSIBLE_MAX_HP:
        return None
    return dex_number


def get_party_recap_species_snapshot(block_base: int, max_slots: int = PARTY_MAX_SLOTS) -> "set[int]":
    """National Dex #s in the save block's party records. Union this with `get_box_species_snapshot` for "what
    the save file says you own", independent of which menus the player opened. Per-slot try/except."""
    owned: "set[int]" = set()
    for party_index in range(max_slots):
        try:
            dex_number = read_party_recap_species(block_base, party_index)
        except Exception:
            continue
        if dex_number is not None:
            owned.add(dex_number)
    return owned


@dataclass
class PurificationTracker:
    """Reports a party index once when its purification flag is newly non-zero.

    Keyed by (party_index, flag_value) and treating "flag went from its last-seen value to a new non-zero value"
    as the event, rather than hardcoding 0 -> 64: only two data points exist for that transition.

    Pass only currently-occupied indices (cross-reference read_party_species) -- an empty slot's recap contents
    are untested and could trigger falsely."""

    last_seen_flags: dict[int, int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.last_seen_flags is None:
            self.last_seen_flags = {}

    def poll(self, block_base: int, occupied_party_indices: list[int]) -> list[int]:
        newly_purified = []
        for party_index in occupied_party_indices:
            record = read_party_recap_record(block_base, party_index)
            previous = self.last_seen_flags.get(party_index, 0)
            if record.purified_flag != 0 and previous == 0:
                newly_purified.append(party_index)
            self.last_seen_flags[party_index] = record.purified_flag
        return newly_purified


# Same-index correlation between PARTY_BASE and the recap records is trustworthy and is the primary signal. One live
# rename test settled both questions: purifying Ledyba and renaming it in one action left PARTY_BASE's `name`
# reading "LEDYBA" long after the rename while the recap's name updated immediately, so "trust PARTY_BASE's name,
# reject on mismatch" reported a real purification as unmatched. The same bracket swapped Ledyba and Poochyena with
# no purification for Poochyena and Poochyena's recap record moved with it byte for byte, so recap index tracks
# current party position. Name comparison is a diagnostic only, never grounds to discard a match.

def correlate_party_with_recap(
    block_base: int,
    party_base: int = PARTY_BASE,
    max_slots: int = PARTY_MAX_SLOTS,
) -> dict[int, tuple[PartyRecapRecord, str]]:
    """For every occupied PARTY_BASE slot, its recap record at the SAME index -- confirmed to track party
    position across a manual reorder, so it is trusted unconditionally and never rejected on a name mismatch.

    Returns {party_index: (recap_record, name_status)}, where name_status is "name_match" or "name_differs".
    "name_differs" is informational: PARTY_BASE lags a recent rename, which does not make the record wrong."""
    members = read_party_members(party_base, max_slots)
    all_recaps = [read_party_recap_record(block_base, i) for i in range(max_slots)]
    correlation: dict[int, tuple[PartyRecapRecord, str]] = {}
    for member in members:
        same_index = all_recaps[member.party_index]
        status = "name_match" if same_index.name == member.name else "name_differs"
        correlation[member.party_index] = (same_index, status)
    return correlation


@dataclass
class NamedPurificationTracker:
    """Like PurificationTracker, but keyed by SPECIES (from PARTY_BASE via read_party_members).

    Not by position: a live bracket where a reorder coincided with a real purification got it wrong both ways -- it
    missed Ledyba's purification, because the slot Ledyba moved into already read 64 from Poochyena's earlier one, and
    falsely re-reported Poochyena, because the slot it moved into read 0 from Ledyba's pre-purification state. Not by
    name either: purification invites a rename, and the recap's name field updates immediately while PARTY_BASE's does
    not. Species is the one identity stable across battle, level-up, reorder and rename.

    Known limitation: two party members of the same species collide, since nothing more specific (a PID) has ever been
    located for a live party member.

    `renamed_slots` (party_index -> recap's current name) after each poll lists slots where the recap name disagrees
    with PARTY_BASE's -- "just renamed, PARTY_BASE hasn't caught up", not an error."""

    # Nonzero values that are NOT the measured purified value, with counts. Never fired on; `!purifications`
    # prints them so the field can be characterised from real play.
    unrecognised_flag_values: "dict[int, int]" = field(default_factory=dict)
    # Recap records skipped because their own name named a different species than the slot they paired with.
    # Nonzero means positional pairing really does slip.
    mismatched_recap_pairings: int = 0
    battle_polls_skipped: int = 0
    _consecutive_battle_skips: int = 0
    # Last poll's (party_index, raw species) tuple. A change resets every pending confirm streak -- see poll().
    _last_party_signature: "tuple | None" = None
    party_changes_seen: int = 0
    # ~15 minutes at the 1-second in-game poll. Longer than any real fight, short enough that a stuck battle
    # signal self-heals instead of silently switching purification checks off for the run.
    MAX_CONSECUTIVE_BATTLE_SKIPS: ClassVar[int] = 900
    last_seen_flags: dict[int, int] = None  # type: ignore[assignment]  # keyed by species, NOT party_index
    renamed_slots: dict[int, str] = None  # type: ignore[assignment]
    # A 0->nonzero flag transition must hold for `_CONFIRM_STREAK` consecutive polls. A recap slot only refreshes
    # when a recap-worthy event fires for THAT member, and opening the save menu is suspected to be one -- so a
    # species already purified before this slot's new occupant took it over baselines at 0 and then jumps to its
    # real value on an unrelated screen transition, indistinguishable one poll at a time from a real purification. A
    # 2-poll window only rules out a single-tick blip, not a menu glitch that holds its wrong read steady. Biased
    # toward slow-but-correct: AP dedup means under-reporting can only delay a threshold, never duplicate one.
    _pending_flags: dict[int, int] = None  # type: ignore[assignment]  # species -> flag seen last poll, unconfirmed
    _pending_streak: dict[int, int] = None  # type: ignore[assignment]  # species -> consecutive matching polls
    # ClassVar, not a dataclass field: `set_poll_interval()` re-derives it from a duration at startup, and a
    # field default is captured at class creation, so a class-attribute assignment would not reach new instances.
    _CONFIRM_STREAK: ClassVar[int] = 4

    def __post_init__(self) -> None:
        if self.last_seen_flags is None:
            self.last_seen_flags = {}
        if self.renamed_slots is None:
            self.renamed_slots = {}
        if self._pending_flags is None:
            self._pending_flags = {}
        if self._pending_streak is None:
            self._pending_streak = {}

    def poll(self, block_base: int, party_base: int = PARTY_BASE, max_slots: int = PARTY_MAX_SLOTS,
             in_battle: bool = False) -> list[tuple[int, int]]:
        """`in_battle` skips the whole pass. A Pokemon does not become purified mid-fight, and a battle is when
        PARTY_BASE and the recap records are least trustworthy (a full battle relocates the block). Safe in one
        direction only, which is why it is allowed: `last_seen_flags` is not advanced while skipping, so a flag
        that really did flip is still 0 -> 64 when the battle ends. The gate can delay, never drop."""
        if in_battle and self._consecutive_battle_skips < self.MAX_CONSECUTIVE_BATTLE_SKIPS:
            self.battle_polls_skipped += 1
            self._consecutive_battle_skips += 1
            # Cleared too: it means "any slot renamed since the last poll", so leaving a pre-battle value
            # standing for a whole fight would make it quietly wrong rather than empty.
            self.renamed_slots = {}
            return []
        # The gate has a ceiling: `has_unresolved_battle()` has gotten stuck permanently True on a stale roster
        # record before. A suppression that can last forever is the same class of failure as blocking delivery,
        # so past the ceiling the gate is ignored and a stuck signal costs a delay only.
        self._consecutive_battle_skips = 0
        newly_purified: list[tuple[int, int]] = []
        self.renamed_slots = {}
        members = read_party_members(party_base, max_slots)
        members_by_index = {m.party_index: m for m in members}
        # A confirm streak may not span a party change. Depositing COMPACTS the party, so slot 2's Pokemon becomes
        # slot 1's while the recap records do not move in lockstep, and an already-purified record then reads 64
        # against a species sitting at 0. The recap-name check below catches that only when the stale record's name
        # is a real species name, not when that Pokemon was nicknamed, so the streak is fenced instead: any add,
        # remove, swap or reorder resets every pending candidate. The RAW species field is used on purpose -- a
        # movement detector, not an identity -- because it does not change when a Pokemon is renamed.
        signature = tuple((m.party_index, m.species) for m in members)
        if self._last_party_signature is not None and signature != self._last_party_signature:
            self._pending_flags.clear()
            self._pending_streak.clear()
            self.party_changes_seen += 1
        self._last_party_signature = signature
        for party_index, (record, name_status) in correlate_party_with_recap(block_base, party_base, max_slots).items():
            if name_status == "name_differs":
                self.renamed_slots[party_index] = record.name
            member = members_by_index[party_index]
            # Name lookup first, then `national_dex`, then the raw field. Falling straight from the name lookup to
            # `member.species` was the bug: a rename (which purification invites) flips `reliable_species` to None
            # and drops the tracker onto the raw live index, a DIFFERENT id namespace, so the key changed
            # mid-Pokemon and the purification never fired. `national_dex` resolves that raw field through the
            # species index, so it stays in dex namespace across a rename, and all 386 values that resolve both ways
            # agree. Name still goes first so this path stays byte-identical for un-renamed Pokemon and the
            # persisted species ledger cannot be re-keyed.
            species = member.reliable_species
            if species is None:
                species = getattr(member, "national_dex", None)
            if species is None:
                species = member.species
            # The recap record must corroborate that it belongs to THIS Pokemon before its flag counts.
            # `correlate_party_with_recap` pairs slot i with record i unconditionally, which is right for its own job
            # and wrong here: a purified record carries 64, so a pairing off by one slot shows an unpurified species
            # a 0 -> 64 transition out of nothing, and four polls of that is a second and a half. Two ways to
            # corroborate -- the record's name IS this slot's name (covering a nicknamed Pokemon, where no species
            # lookup is possible), or it resolves to exactly this species. Rejecting only a record naming a DIFFERENT
            # species left the nicknamed case open. Costs a delay, never a loss: the one legitimate mismatch is the
            # rename, which resolves once PARTY_BASE catches up.
            record_species = species_dex_from_name(record.name)
            pairing_ok = (record.name == member.name) or (
                record_species is not None and species is not None and record_species == species
            )
            if not pairing_ok:
                self._pending_flags.pop(species, None)
                self._pending_streak.pop(species, None)
                self.mismatched_recap_pairings += 1
                continue
            if species not in self.last_seen_flags:
                # First sighting: purified_flag may already be nonzero because this slot's record is stale
                # from an earlier, already-purified occupant. Baseline only, never fire.
                self.last_seen_flags[species] = record.purified_flag
                continue
            previous = self.last_seen_flags[species]
            flag = record.purified_flag
            # Only the MEASURED value counts. `flag != 0` fired on any nonzero, so a field that is not a clean
            # boolean produced purifications for Pokemon that had not been purified. A non-64 nonzero is recorded and
            # printed by `!purifications` rather than fired on, and `last_seen_flags` is not advanced for it, so the
            # species still fires when it reaches 64. Strict on purpose: a false purification releases someone
            # else's item unrecoverably AND banks the species so the real one never counts.
            if flag != 0 and flag != PURIFIED_FLAG_VALUE and previous == 0:
                self.unrecognised_flag_values[flag] = self.unrecognised_flag_values.get(flag, 0) + 1
                self._pending_flags.pop(species, None)
                self._pending_streak.pop(species, None)
                continue
            if flag == PURIFIED_FLAG_VALUE and previous == 0:
                # Not trusted until the SAME value repeats for `_CONFIRM_STREAK` polls. previous stays 0 until
                # then, so every poll in between re-runs this comparison instead of accepting the jump.
                if self._pending_flags.get(species) == flag:
                    streak = self._pending_streak.get(species, 1) + 1
                    if streak >= self._CONFIRM_STREAK:
                        newly_purified.append((species, party_index))
                        self.last_seen_flags[species] = flag
                        self._pending_flags.pop(species, None)
                        self._pending_streak.pop(species, None)
                    else:
                        self._pending_streak[species] = streak
                else:
                    self._pending_flags[species] = flag
                    self._pending_streak[species] = 1
                continue
            self.last_seen_flags[species] = flag
            self._pending_flags.pop(species, None)
            self._pending_streak.pop(species, None)
        return newly_purified


# Mirrors locations.py's PURIFICATION_LOCATION_COUNT and purification_location_name. Duplicated rather than
# imported because locations.py pulls in BaseClasses/Region, which breaks standalone loading. Keep in sync.
PURIFICATION_LOCATION_COUNT = 32


def purification_location_name(count: int) -> str:
    return f"Purify {count} Shadow Pokemon"


# --- The Shadow record itself, in the party AND in the PC. ---
# `NamedPurificationTracker` watches party recap records and needs to SEE a 0 -> 64 flip while connected, so it
# misses a Shadow purified in the chamber (which returns it to the PC), one purified before the client
# connected, and a flag already 64 at attach. Reading STATE off both party and PC covers all three.
#
# Measured against the Teddiursa purification bracket (dump_pre/post_purify_teddiursa_20260903.bin) and the PC
# deposit (dump_post_teddiursa_pc_20260902.bin):
#
#     party slot 2, pre  : species 216, level 11, shadow id 1, purified flag 0
#     party slot 2, post : species 216, level 13, shadow id 1, purified flag 64
#     box slot 0         : species 216, level 11, shadow id 1, purified flag 0
#
#   1. A PC box slot is the SAME record as a party recap record -- same 0xC4 stride, same offsets, so the
#      existing addressing works.
#   2. The shadow id SURVIVES purification. "shadow id != 0" means "was snagged as a Shadow", not "still is" --
#      the identity the species clause wants, and the wrong thing to test for purity.
#   3. The purified flag is the state: 0 -> 64 on the purified individual, nothing else moved.
#
# The offsets below are record-relative, where the older constants are relative to the text anchor 0x4E in (the
# nickname field). That is also why PARTY_RECAP_SPECIES_OFFSET always read garbage: anchor+0x32 is record 0x80,
# the first MOVE, not a species. The species field is at the record's own +0x00 and reads correctly.
RECORD_TEXT_ANCHOR_OFFSET = 0x4E          # record start -> the nickname/text anchor the box+recap constants use
RECORD_SPECIES_OFFSET = 0x00              # u16BE LIVE index (convert, never use raw -- see ADDENDUM 249)
RECORD_LEVEL_OFFSET = 0x11                # u8
RECORD_CURRENT_HP_OFFSET = 0x04           # u16BE (ADDENDUM 328 -- part of the "is this a Pokemon at all" gate)
RECORD_MAX_HP_OFFSET = 0x90               # u16BE
RECORD_TRAINER_ID_OFFSET = 0x24           # u32BE (TID+SID). Every Pokemon on one save shares it
RECORD_PID_OFFSET = 0x28                  # u32BE personality value -- the per-INDIVIDUAL tag (ADDENDUM 320)
RECORD_SHADOW_ID_OFFSET = 0xBA            # u16BE. Nonzero = snagged as a Shadow, and STAYS nonzero afterwards
RECORD_PURIFIED_FLAG_OFFSET = 0x7C        # u16BE == text anchor + PARTY_RECAP_PURIFIED_FLAG_OFFSET (0x2E)
assert RECORD_PURIFIED_FLAG_OFFSET - RECORD_TEXT_ANCHOR_OFFSET == PARTY_RECAP_PURIFIED_FLAG_OFFSET, (
    "the record-relative and anchor-relative purified flag must be the same byte -- one of them has moved"
)


@dataclass(frozen=True)
class ShadowRecord:
    """One party or PC record, read for the two fields purification detection needs."""

    source: str          # "party" or "box"
    slot: int
    dex: "int | None"    # National Dex, converted; None when the raw value does not resolve
    shadow_id: int
    purified_flag: int
    level: int = 0            # ADDENDUM 320 -- part of the plausibility gate
    trainer_id: int = 0       # ADDENDUM 320 -- u32BE TID+SID
    pid: int = 0              # ADDENDUM 320 -- the individual tag, measured stable across evolution
    cur_hp: int = 0           # ADDENDUM 328
    max_hp: int = 0           # ADDENDUM 328

    @property
    def looks_like_a_pokemon(self) -> bool:
        """Does this record hold a Pokemon at all?

        The scan walks 360 box slots and most of a fresh save's boxes are not real records, so a slot of
        arbitrary bytes only has to land on a plausible level and species number to look like a Pokemon -- which
        is how three purifications fired for species the player did not own.

        A real record agrees with itself across five independent fields and junk almost never does: species
        resolves, level in range, max HP in range, current HP not above it, and a nonzero PID and trainer id
        (both zero in an empty slot, never zero on a real Pokemon)."""
        return (
            self.dex is not None
            and 1 <= self.level <= 100
            and 1 <= self.max_hp <= 999
            and 0 <= self.cur_hp <= self.max_hp
            and self.pid != 0
            and self.trainer_id != 0
        )

    @property
    def was_snagged_as_shadow(self) -> bool:
        return self.shadow_id != 0

    @property
    def is_purified(self) -> bool:
        """A Shadow this save has purified. Only the measured value counts (ADDENDUM 232's rule)."""
        return self.was_snagged_as_shadow and self.purified_flag == PURIFIED_FLAG_VALUE


def _read_shadow_record(record_address: int, source: str, slot: int) -> "ShadowRecord | None":
    from .tools import xd_species_index

    try:
        data = read_bytes(record_address, 0xC4)
    except Exception:
        return None
    if len(data) < 0xC4:
        return None
    raw_species = struct.unpack_from(">H", data, RECORD_SPECIES_OFFSET)[0]
    if raw_species == 0:
        return None  # empty slot
    dex = xd_species_index.national_dex_for_live_species(raw_species)
    return ShadowRecord(
        source=source,
        slot=slot,
        dex=dex,
        shadow_id=struct.unpack_from(">H", data, RECORD_SHADOW_ID_OFFSET)[0],
        purified_flag=struct.unpack_from(">H", data, RECORD_PURIFIED_FLAG_OFFSET)[0],
        level=data[RECORD_LEVEL_OFFSET],
        cur_hp=struct.unpack_from(">H", data, RECORD_CURRENT_HP_OFFSET)[0],
        max_hp=struct.unpack_from(">H", data, RECORD_MAX_HP_OFFSET)[0],
        trainer_id=struct.unpack_from(">I", data, RECORD_TRAINER_ID_OFFSET)[0],
        pid=struct.unpack_from(">I", data, RECORD_PID_OFFSET)[0],
    )


def party_record_address(block_base: int, slot: int) -> int:
    """The RECORD's own start for a party slot -- the text anchor the older constants use, minus 0x4E."""
    return block_base + PARTY_RECAP_OFFSET + slot * PARTY_RECAP_STRIDE - RECORD_TEXT_ANCHOR_OFFSET


def box_record_address(block_base: int, slot_index: int, slots_per_box: int = 30) -> int:
    """Same addressing `read_box_slot_species` uses (including the per-box padding), as a record start."""
    box_idx, local_slot_idx = divmod(slot_index, slots_per_box)
    return (
        block_base
        + BOX_SLOT_TEXT_ANCHOR_OFFSET
        + box_idx * (slots_per_box * BOX_SLOT_STRIDE + BOX_PADDING_PER_BOX)
        + local_slot_idx * BOX_SLOT_STRIDE
        - RECORD_TEXT_ANCHOR_OFFSET
    )


def scan_shadow_records(block_base: int, box_slots: "list[int] | None" = None,
                        party_slots: int = PARTY_MAX_SLOTS) -> "list[ShadowRecord]":
    """Every occupied party and (optionally) PC record, read for shadow id + purified flag. Never raises: a
    slot that cannot be read is simply absent, which under-reports rather than inventing a purification."""
    out: "list[ShadowRecord]" = []
    for slot in range(party_slots):
        record = _read_shadow_record(party_record_address(block_base, slot), "party", slot)
        if record is not None:
            out.append(record)
    for slot_index in (box_slots or []):
        record = _read_shadow_record(box_record_address(block_base, slot_index), "box", slot_index)
        if record is not None:
            out.append(record)
    return out


# --- The Shadow ID is the identity, and five guards stand behind it. ---
# Measured, not assumed (the Eevee stone bracket mem1_pre_eeveestone.bin / mem1_post_evolve.bin, plus the Teddiursa
# purification bracket):
#
#     evolving Eevee     : species 133 -> 135, PID CFFBB772 unchanged, shadow id 0 unchanged
#     purifying Teddiursa: species 216 unchanged, PID 41882587 unchanged, shadow id 1 unchanged
#
# Evolution moves the species and nothing else, so the shadow id (the DDPK slot the game assigned at snag time) is a
# per-Shadow tag and the PID a per-individual one, both written by the game. Keying the ledger on the shadow id is
# what makes an evolved purified Shadow countable -- a species ledger loses it when Totodile becomes Croconaw -- and
# retires the same-species collision. The species ledger stays, because rule 2 has no shadow id to work with and an
# older client's saved ledger is keyed that way.
#
# Missing a purification is the bad outcome, so every guard either rejects something that cannot be a real record or
# makes the tracker wait and look again. None can blacklist a Shadow permanently.
#   1. Plausibility: level 1-100, shadow id inside the DDPK table's range, and the exactly-measured purified value
#      for the flag rule. The species is deliberately NOT required to resolve.
#   2. PID cross-check: the same shadow id later carrying a different PID is a misread, not a second purification.
#   3. Trainer id: every Pokemon on one save shares it, so a disagreeing record is skipped for that scan.
#   4. A second look: a purified state is permanent, so there is nothing to miss by confirming it over two scans.
#   5. The cap: never more than the game has Shadows, never past PURIFICATION_LOCATION_COUNT.
DDPK_MAX_PLAUSIBLE_ID = 255          # the DDPK table is a small array (83 in use in the vanilla data); an id
                                     # past this is garbage, not a Shadow
PURIFICATION_SCAN_CONFIRM_SCANS = 2  # guard 4 -- see above for why confirming costs nothing here


def dominant_trainer_id(records: "list[ShadowRecord]") -> "int | None":
    """Guard 3's reference value: the save's own trainer id, taken from the PARTY only.

    "Whatever id at least two records agree on" across the whole scan let junk outvote the save -- a fresh save
    has one party Pokemon against 360 box slots of leftover memory. The party is the one place every record is
    certainly the player's. Falls back to the old majority when no party record is readable, and None (guard
    off, rule 2 disabled -- see `observe_records`) when neither answers."""
    counts: "dict[int, int]" = {}
    for record in records:
        if record.source == "party" and record.trainer_id and record.looks_like_a_pokemon:
            counts[record.trainer_id] = counts.get(record.trainer_id, 0) + 1
    if counts:
        return max(counts.items(), key=lambda kv: kv[1])[0]
    counts = {}
    for record in records:
        if record.trainer_id and record.looks_like_a_pokemon:
            counts[record.trainer_id] = counts.get(record.trainer_id, 0) + 1
    if not counts:
        return None
    best, seen = max(counts.items(), key=lambda kv: kv[1])
    return best if seen >= 2 else None


@dataclass
class PurificationCountTracker:
    """Turns individual purification EVENTS (from NamedPurificationTracker) into the cumulative
    "Purify N Shadow Pokemon" location names, up to PURIFICATION_LOCATION_COUNT. `poll()` returns every
    threshold newly crossed this call -- normally 0 or 1, but the loop handles more in case a poll was delayed.

    `total_purified` counts only what this instance observed live while connected. It does not retroactively
    account for a Shadow purified before the client connected (no lifetime counter has been found in RAM) or for
    a purified Pokemon since moved to the PC (the flag lives in the party recap record). So connect near the
    start of a session for an accurate count. Safe either way on the protocol side: the server dedupes, so a
    client that re-derives the count differently across a reconnect can only under-report a threshold, never
    fire one early."""

    # One species, one purification, forever. A longer confirm streak was never going to fix the duplicates:
    # the recap record refreshes to the member's TRUE flag, so a species purified before the client ever looked
    # can flip 0 -> 64 at any later screen transition and HOLD, which no number of agreeing polls distinguishes
    # from a real purification. The species, though, is unique -- a given Totodile can only be purified once, so
    # a second report of that Totodile is a re-observation however convincing it looks. `purified_species` is the
    # ledger; the count still drives the checks.
    #
    # A species key would under-count only if two SHADOW Pokemon shared a species, and they cannot.
    # ADDENDUM 225: all 127 Shadows in a maximal seed (83 vanilla + 44 generated) have distinct species by
    # construction -- the 83 vanilla slots already are, `TeamShuffler._picked_shadow_species` keeps the reassignment
    # one-to-one, and `build_shadow_expansion_plans` draws its 44 from what is left of the union. Load-bearing now,
    # so test_addendum_224_225 guards it. The residual limit is ordinary party members, which are not purifiable.

    tracker: NamedPurificationTracker = None  # type: ignore[assignment]
    total_purified: int = 0
    # Species ids this tracker has already counted. The ledger, not the count.
    purified_species: "set[int]" = field(default_factory=set)
    # Re-observations rejected because the species was already counted -- what `!purifications` shows to say the
    # deduplication is doing something.
    duplicate_species_rejected: int = 0
    dirty: bool = False
    # ADDENDUM 318: how many the party/PC scan counted that the flip-watcher never saw, and why.
    scan_counted: int = 0
    scan_reasons: "dict[str, int]" = field(default_factory=dict)
    # The Shadow-id ledger (survives evolution), the PID each id was first seen with, the pending second look, and
    # what each guard rejected. Every counter here is a CLAIM about live data that `!purifications` prints.
    purified_shadow_ids: "set[int]" = field(default_factory=set)
    # ADDENDUM 325: what the LAST call to observe_records actually counted, as text, so the client can say it
    # out loud. A count that surprises the player has to be traceable to the record that caused it.
    last_counts: "list[str]" = field(default_factory=list)
    shadow_pids: "dict[int, int]" = field(default_factory=dict)
    pending_confirmations: "dict[str, int]" = field(default_factory=dict)
    guard_rejections: "dict[str, int]" = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.tracker is None:
            self.tracker = NamedPurificationTracker()

    def poll(self, block_base: int, party_base: int = PARTY_BASE, max_slots: int = PARTY_MAX_SLOTS,
             in_battle: bool = False) -> list[str]:
        """`in_battle` passes straight through -- see NamedPurificationTracker.poll for why skipping mid-battle
        can only delay a real purification, never drop one."""
        newly_purified = self.tracker.poll(block_base, party_base, max_slots, in_battle=in_battle)
        newly_crossed: list[str] = []
        for species, party_index in newly_purified:
            # Ask the SHADOW LEDGER before counting. This watcher takes its species from PARTY_BASE, which does
            # not populate until the party screen has drawn it and whose slot can still hold the previous
            # occupant right after a purification reorders the party; the scan takes its identity from the
            # record's shadow id. When the two disagree about one Pokemon, each ledger sees something it has not
            # counted and the purification counts twice. So read the record for the slot the flip was seen in.
            # An unreadable record falls through to species-only behaviour, which can duplicate but never drop.
            record = _read_shadow_record(party_record_address(block_base, party_index), "party", party_index)
            if record is not None and record.was_snagged_as_shadow:
                if record.shadow_id in self.purified_shadow_ids:
                    self.duplicate_species_rejected += 1
                    continue
                if record.dex is not None and record.dex in self.purified_species:
                    self.purified_shadow_ids.add(record.shadow_id)
                    self.shadow_pids.setdefault(record.shadow_id, record.pid)
                    self.duplicate_species_rejected += 1
                    self.dirty = True
                    continue
                self.purified_shadow_ids.add(record.shadow_id)
                if record.pid:
                    self.shadow_pids[record.shadow_id] = record.pid
                if record.dex is not None:
                    self.purified_species.add(record.dex)
            elif species in self.purified_species:
                # Already counted. This is the save-menu re-observation the player kept seeing.
                self.duplicate_species_rejected += 1
                continue
            self.purified_species.add(species)
            self.dirty = True
            if self.total_purified >= PURIFICATION_LOCATION_COUNT:
                continue  # capped -- the species is still recorded, so it can never be counted later either
            self.total_purified += 1
            newly_crossed.append(purification_location_name(self.total_purified))
        return newly_crossed

    # The scan-based half. The flip-watcher above is the fastest signal, but it structurally cannot see a
    # purification that happened in the chamber or before the client connected. This reads the STATE of every
    # party and PC record instead, so those are counted the first time the record is seen.
    #
    # Two rules, in this order because fact beats inference:
    #   1. `record.is_purified` -- shadow id nonzero AND the measured flag. A fact about the individual.
    #   2. Fallback: a species this seed makes a Shadow, owned as an ordinary Pokemon (no shadow id). Sound
    #      because generation guarantees Poke Spot and Shadow species never overlap, so a Shadow species in the
    #      box cannot have come from a wild spot, and because the species clause counts each one once.
    def observe_records(self, records: "list[ShadowRecord]",
                        seed_shadow_dex: "set[int] | frozenset[int] | None" = None,
                        shadow_count_cap: "int | None" = None,
                        obtainable_elsewhere_dex: "set[int] | frozenset[int] | None" = None,
                        trusted_owned_dex: "set[int] | frozenset[int] | None" = None) -> "list[str]":
        """Counts whatever the scan proves, keyed by Shadow id (ADDENDUM 320) and deduped by species as well.
        Returns newly crossed location names."""
        shadow_dex = seed_shadow_dex or frozenset()
        expected_trainer = dominant_trainer_id(records)
        self.last_counts = []
        seen_keys: "set[str]" = set()
        newly_crossed: "list[str]" = []

        def reject(reason: str) -> None:
            self.guard_rejections[reason] = self.guard_rejections.get(reason, 0) + 1

        for record in records:
            # Is this a Pokemon at all? Before either rule, since both are statements ABOUT a Pokemon -- a box
            # slot of leftover bytes with a plausible level is not a Pokemon that was purified.
            if not record.looks_like_a_pokemon:
                if record.is_purified or (record.dex is not None and record.dex in shadow_dex):
                    reject("record does not look like a real Pokemon")
                continue
            # ---- what would this record mean, if it is trustworthy? ------------------------------------
            if record.is_purified:
                key, reason = f"shadow:{record.shadow_id}", "purified flag"
            elif record.dex is not None and record.dex in shadow_dex and not record.was_snagged_as_shadow:
                # Rule 2 infers "this species can ONLY be had by purifying one", so it must not fire for a
                # species the seed also hands out another way -- the guaranteed Eevee and its evolutions, or a
                # Poke Spot species in a seed generated before the overlap was forbidden.
                if record.dex in (obtainable_elsewhere_dex or frozenset()):
                    reject("a Shadow species this seed also gives out another way")
                    continue
                # Rule 2 also needs the CATCH scan to have seen the player own the species: that scan has its
                # own guards against a bad box poll, and this is the difference between "a Shadow species is in
                # this record" and "the player owns one". With no trusted set yet, rule 2 declines.
                if record.dex not in (trusted_owned_dex or frozenset()):
                    reject("rule 2 without the catch scan having seen the player own that species")
                    continue
                if expected_trainer is None:
                    reject("rule 2 with no party record to say whose save this is")
                    continue
                key, reason = f"species:{record.dex}", "a Shadow species owned as an ordinary Pokemon"
            else:
                continue

            # ---- guard 1: plausibility ------------------------------------------------------------------
            if not 1 <= record.level <= 100:
                reject("implausible level")
                continue
            if record.was_snagged_as_shadow and not 1 <= record.shadow_id <= DDPK_MAX_PLAUSIBLE_ID:
                reject("shadow id out of range")
                continue
            # ---- guard 3: the save's own trainer id ------------------------------------------------------
            if expected_trainer is not None and record.trainer_id != expected_trainer:
                reject("trainer id mismatch")
                continue
            # ---- guard 2: the PID cross-check ------------------------------------------------------------
            if record.was_snagged_as_shadow and record.pid:
                known = self.shadow_pids.get(record.shadow_id)
                if known is not None and known != record.pid:
                    reject("PID disagrees with this Shadow id")
                    continue

            # Already counted? Both ledgers, because the species one may carry an older client's state.
            if key.startswith("shadow:") and record.shadow_id in self.purified_shadow_ids:
                self.duplicate_species_rejected += 1
                continue
            if record.dex is not None and record.dex in self.purified_species:
                # Counted under the species key (ADDENDUM 318, or the flip-watcher). Record the id so the
                # ledgers agree from here on, but do not count it twice.
                if record.was_snagged_as_shadow:
                    self.purified_shadow_ids.add(record.shadow_id)
                    self.shadow_pids.setdefault(record.shadow_id, record.pid)
                    self.dirty = True
                self.duplicate_species_rejected += 1
                continue

            # ---- guard 4: a second look ------------------------------------------------------------------
            seen_keys.add(key)
            seen = self.pending_confirmations.get(key, 0) + 1
            self.pending_confirmations[key] = seen
            if seen < PURIFICATION_SCAN_CONFIRM_SCANS:
                continue

            # ---- counted -------------------------------------------------------------------------------
            self.pending_confirmations.pop(key, None)
            if record.was_snagged_as_shadow:
                self.purified_shadow_ids.add(record.shadow_id)
                if record.pid:
                    self.shadow_pids[record.shadow_id] = record.pid
            if record.dex is not None:
                self.purified_species.add(record.dex)
            self.scan_counted += 1
            self.scan_reasons[reason] = self.scan_reasons.get(reason, 0) + 1
            self.last_counts.append(
                f"{record.source} slot {record.slot}: species {record.dex}, shadow id {record.shadow_id} "
                f"({reason})"
            )
            self.dirty = True
            # ---- guard 5: the caps ----------------------------------------------------------------------
            if shadow_count_cap is not None and self.total_purified >= shadow_count_cap:
                reject("past this seed's Shadow count")
                continue
            if self.total_purified >= PURIFICATION_LOCATION_COUNT:
                continue
            self.total_purified += 1
            newly_crossed.append(purification_location_name(self.total_purified))

        # A pending key that did NOT show up this scan loses its streak -- one flicker should not accumulate
        # across minutes into a confirmation. A real purified record is present on every scan, so this costs
        # a genuine one nothing.
        for key in [k for k in self.pending_confirmations if k not in seen_keys]:
            self.pending_confirmations.pop(key, None)
        return newly_crossed

    def describe(self) -> "list[str]":
        lines = [f"Purifications: {self.total_purified} counted "
                 f"({len(self.purified_species)} distinct species recorded)."]
        if self.purified_species:
            lines.append("  species already counted: "
                         + ", ".join(str(s) for s in sorted(self.purified_species)))
        if self.purified_shadow_ids:
            lines.append("  Shadow ids counted (ADDENDUM 320, survives evolution): "
                         + ", ".join(str(i) for i in sorted(self.purified_shadow_ids)))
        if self.guard_rejections:
            lines.append("  scan guards rejected: "
                         + ", ".join(f"{reason} x{count}"
                                     for reason, count in sorted(self.guard_rejections.items())))
        if self.pending_confirmations:
            lines.append(f"  awaiting a second look: {len(self.pending_confirmations)} "
                         "(each counts on the next scan that still shows it)")
        if self.scan_counted:
            lines.append(f"  counted by the party/PC scan: {self.scan_counted} ("
                         + ", ".join(f"{reason}: {count}" for reason, count in sorted(self.scan_reasons.items()))
                         + ") -- purifications the party flag-watcher alone would have missed (ADDENDUM 318)")
        if self.duplicate_species_rejected:
            lines.append(f"  re-observations rejected as already-counted: {self.duplicate_species_rejected} "
                         f"(this is the ADDENDUM 220 fix working -- each would have been a duplicate check)")
        # Nonzero values that are NOT the measured purified value. Each would have been a wrong check before.
        # Printed so the player can report what a Pokemon CLOSE to purification reads, which is what would let
        # this rule widen on evidence.
        unrecognised = getattr(self.tracker, "unrecognised_flag_values", None) or {}
        if unrecognised:
            lines.append(f"  purified-flag values seen that are NOT {PURIFIED_FLAG_VALUE} (never counted): "
                         + ", ".join(f"{value} x{count}" for value, count in sorted(unrecognised.items())))
            lines.append("    ^ worth reporting: this is the field's uncharacterised behaviour, captured live.")
        # The three guards that stop a mis-paired recap record becoming a check. Each counter is a claim about
        # live behaviour, so one sitting at zero in real play is how the claim gets falsified.
        mismatched = getattr(self.tracker, "mismatched_recap_pairings", 0)
        if mismatched:
            lines.append(f"  recap records skipped as belonging to a different Pokemon: {mismatched} "
                         "(each would have been read against the wrong species' purified flag)")
        party_changes = getattr(self.tracker, "party_changes_seen", 0)
        if party_changes:
            lines.append(f"  party changes that reset a pending confirmation: {party_changes} "
                         "(a deposit, withdrawal, swap or reorder -- a streak may not span one)")
        battle_skips = getattr(self.tracker, "battle_polls_skipped", 0)
        if battle_skips:
            lines.append(f"  polls skipped because a battle was in progress: {battle_skips} "
                         "(purification cannot happen mid-fight; skipping delays a real one, never drops it)")
        return lines

    def to_json(self) -> dict:
        return {"total_purified": self.total_purified,
                "purified_species": sorted(self.purified_species),
                # Saved alongside the species ledger rather than replacing it, so an older state file still
                # loads and a newer one still means something to an older client.
                "purified_shadow_ids": sorted(self.purified_shadow_ids),
                "shadow_pids": {str(k): v for k, v in sorted(self.shadow_pids.items())}}

    def load_json(self, data: dict) -> None:
        """Tolerant, like every other loader here: a corrupt file degrades to 'nothing counted yet' rather
        than taking the client down. Under-counting is recoverable; refusing to start is not."""
        try:
            self.purified_species = {int(s) for s in (data.get("purified_species") or [])}
            self.total_purified = max(int(data.get("total_purified") or 0), 0)
            self.purified_shadow_ids = {int(s) for s in (data.get("purified_shadow_ids") or [])}
            self.shadow_pids = {int(k): int(v) for k, v in (data.get("shadow_pids") or {}).items()}
            self.pending_confirmations = {}
            self.dirty = False
        except Exception:
            self.purified_species = set()
            self.total_purified = 0
            self.purified_shadow_ids = set()
            self.shadow_pids = {}
            self.pending_confirmations = {}
            self.dirty = False


# --- Per-chest location names, mirrored from locations.py for the same standalone-loadability reason as
# PURIFICATION_LOCATION_COUNT. Both sides derive from the same game_data tables, so only the name format and the
# eligibility filter are duplicated; test_addendum_174 asserts the two tables match name for name. Replaces the
# "Open N Chests" ladder, which is gone rather than deprecated: counts 1..90 are also valid chest ids, so a helper
# keeping the old name would have let stale callers run while quietly meaning something else.


# ADDENDUM 382: the live move-status guard.
#
# ADDENDUM 381 fenced the PATCHER off the two bytes that decide a move's status (effect id +0x1D, secondary
# chance +0x05). That fence is gone by the time anyone plays, and the player asked the right question about
# what happens next: a Dolphin save state restores the whole of MEM1, `common_rel` included. Load a state made
# under a different ISO and the move table in memory is that build's, not this one's -- nothing on disc is
# wrong and nothing the patcher can check would notice.
#
# So the same census is checked against live RAM. The move table sits at COMMON_REL_RAM_BASE + 0xA2710, which
# is not a guess: it is where the table was read in all 163 MEM1 dumps, every one of them decoding correct
# PP, base power and accuracy there.
#
# IT WARNS, IT NEVER BLOCKS. A diagnostic must not cost a player a check, and a legitimately different build
# (another region, a future revision) would fail this census while being perfectly playable. So the location
# is proven first against PP and base power, and a census failure only ever produces a line of text.
MOVE_TABLE_REL_OFFSET = 0xA2710


def live_move_status_report(census: "dict[int, tuple[int, int]]") -> "dict | None":
    """Compare every move's status bytes in live RAM against `census`.

    Returns None when the table cannot be located or proven -- unreadable RAM, no game running, or a build
    whose PP and base power do not match, which is not something to cry wolf about. Otherwise a dict with
    `checked` and `drifted`, the latter a list of (move index, (was_chance, was_effect), (now_chance,
    now_effect)) in index order. An empty `drifted` is the healthy answer."""
    from .game_data.item_name_strings import COMMON_REL_RAM_BASE
    from .tools import xd_rel_format as rel_format

    base = COMMON_REL_RAM_BASE + MOVE_TABLE_REL_OFFSET
    count = max(census) + 1
    try:
        table = read_bytes(base, count * rel_format.MOVE_ENTRY_SIZE)
    except Exception:
        return None                    # no game, or the region is not mapped yet
    if len(table) != count * rel_format.MOVE_ENTRY_SIZE:
        return None

    # Prove the location before trusting a single status byte, the same way the patcher does. Every
    # fingerprint entry must agree -- no "at least N" threshold, because the loop returns on the first
    # disagreement, so a count could only ever come out at the full total (ADDENDA 247/298: a condition that
    # cannot bind does not belong here). An unmapped region reads as zeros and fails on the first move.
    for index, (pp, power) in rel_format.MOVE_TABLE_FINGERPRINT.items():
        off = index * rel_format.MOVE_ENTRY_SIZE
        if off + rel_format.MOVE_ENTRY_SIZE > len(table):
            return None
        if (table[off + rel_format.MOVE_PP_OFFSET] != pp
                or table[off + rel_format.MOVE_BASE_POWER_OFFSET] != power):
            return None

    drifted = []
    for index in sorted(census):
        off = index * rel_format.MOVE_ENTRY_SIZE
        now = (table[off + rel_format.MOVE_SECONDARY_CHANCE_OFFSET],
               table[off + rel_format.MOVE_EFFECT_OFFSET])
        if now != census[index]:
            drifted.append((index, census[index], now))
    return {"checked": len(census), "drifted": drifted}


def describe_live_move_status(report: "dict | None") -> "list[str]":
    """Lines to log for a report, or nothing at all when it is healthy. Names the moves, because "your move
    table is wrong" is not something a player can act on and "Icy Wind now freezes" is."""
    if not report or not report["drifted"]:
        return []
    from .game_data.move_status import describe_effect

    drifted = report["drifted"]
    lines = [
        f"WARNING: {len(drifted)} of {report['checked']} moves have status data in memory that does not "
        f"match this build. Battles will apply the wrong effects. The usual cause is a Dolphin SAVE STATE "
        f"made with a different ISO -- reload from an in-game save rather than a state.",
    ]
    for index, (was_chance, was_effect), (now_chance, now_effect) in drifted[:8]:
        detail = []
        if was_effect != now_effect:
            detail.append(f"{describe_effect(was_effect)} -> {describe_effect(now_effect)}")
        if was_chance != now_chance:
            detail.append(f"{was_chance}% -> {now_chance}%")
        lines.append(f"  move {index}: " + ", ".join(detail))
    if len(drifted) > 8:
        lines.append(f"  ... and {len(drifted) - 8} more")
    return lines


def _chest_location_index() -> "tuple[dict[int, str], tuple[str, ...]]":
    from .game_data import chest_flags, chest_regions, chest_table, key_item_chests
    from .tools import xd_rel_format

    by_id = {chest["chest"]: chest for chest in chest_table.CHESTS}
    by_flag: "dict[int, list[int]]" = {}
    for chest_id in sorted(by_id):
        if chest_flags.chest_flag_id(chest_id) is None:
            continue
        if chest_id not in chest_regions.CHEST_TO_REGION:
            continue
        # The five KeyItemShuffle chests are in the table unconditionally, matching locations.py: the client
        # must be able to NAME them however the seed was generated. The server rejects an unrecognised location,
        # whereas a client that cannot name one the seed does have drops the check silently.
        if (by_id[chest_id]["item"] >= xd_rel_format.KEY_ITEM_ID_FLOOR
                and chest_id not in key_item_chests.SHUFFLED_KEY_ITEM_CHESTS):
            continue
        by_flag.setdefault(chest_flags.CHEST_FLAG_IDS[chest_id], []).append(chest_id)
    id_to_name: "dict[int, str]" = {}
    names: "list[str]" = []
    # One row PER CHEST, not per flag id -- see locations._chest_location_rows. `by_flag` is still built above
    # because constructing it is what applies the eligibility filters; only the grouping changed.
    for chest_id in sorted(cid for ids in by_flag.values() for cid in ids):
        name = chest_location_name_for_ids((chest_id,), by_id[chest_id]["room"])
        names.append(name)
        id_to_name[chest_id] = name
    return id_to_name, tuple(names)


def chest_location_name_for_ids(chest_ids: "tuple[int, ...]", room_id: int) -> str:
    """Must format identically to locations.chest_location_name_for_ids -- a location name IS its identity to
    the server, so a one-character difference here means every chest check is silently rejected."""
    # The renamed ones come from game_data/chest_names.py, which both sides import precisely because this file
    # cannot import locations.py and a hand-mirrored table is the failure above waiting to happen.
    from .game_data import chest_names

    override = chest_names.chest_location_name_override(chest_ids)
    if override is not None:
        return override
    if len(chest_ids) == 1:
        return f"Chest {chest_ids[0]} (Room {room_id})"
    return "Chest " + "+".join(str(c) for c in chest_ids) + f" (Room {room_id})"


CHEST_ID_TO_LOCATION, CHEST_LOCATION_NAMES = _chest_location_index()
CHEST_LOCATION_COUNT = len(CHEST_LOCATION_NAMES)


# The reserved dummy item every randomized chest gives; mirrors items.py's CHEST_DUMMY_GAME_ITEM_ID. Rabuta Berry
# (161) rather than Enigma Berry (175), which "gave junk info" in-game -- an E-Reader / Battle-Frontier item with no
# description wired up. Rabuta is ISO-confirmed and, like Enigma, sits in the pruned Bluk-Enigma range so it is
# never placed as a real AP item: that is what makes "this item's quantity rose" an unambiguous "a chest was opened"
# signal. (Open caveat: Rabuta's "never otherwise enters the Bag" property has not been re-confirmed live.)
CHEST_DUMMY_GAME_ITEM_ID = 161


# find_item_quantity() lives up next to give_item()/give_item_verified(); same function.


# --- Block-stability gate: do not poll the block-derived trackers while the block is being rewritten. ---
# Opening the save menu appears to write the block and then rewrite it, which no debounce can win against: a
# per-value "has this settled?" answers yes for as long as the menu stays open. What a block-wide rewrite does give
# is something a per-value debounce cannot see -- it moves a lot of memory at once, where a real event moves almost
# nothing (a chest is one u16, an item use or an AP delivery one 4-byte slot). Skipping the poll means the tracker
# never sees the glitch value at all, so the comparison after the menu closes is old-vs-old and produces nothing.
#
# The witness is the Bag's own item array: the quietest large region in the block and exactly where the chest
# symptom shows up, so it is the corruption rather than a proxy for it. Purifications read the recap records but are
# gated on the same signal, on the theory that one rewrite touches both -- if they ever glitch while the Bag stays
# quiet, that theory is wrong and this needs a second window.
BLOCK_STABILITY_WINDOW_OFFSET = POKEBALL_POCKET_OFFSET
BLOCK_STABILITY_WINDOW_SIZE = POKEBALL_POCKET_ARRAY_SLOT_COUNT * 4   # the whole packed [id][qty] array

# Bytes that may differ between two consecutive polls before the block is called unstable. A chest is 2 bytes,
# any single slot rewrite is 4; this leaves room for several at once (the player using items while an AP
# delivery lands) and still sits far below a wholesale rewrite of a 760-byte array.
BLOCK_CHURN_BYTE_THRESHOLD = 16

# Consecutive SETTLED polls required before the block is trusted again -- see BlockStabilityGate.poll for what
# settled means. The rewrite BACK is itself a churn poll, so this must be at least 1.
BLOCK_QUIET_POLLS_AFTER_CHURN = 2

# Saving is three writes where opening the menu is two, and "has the block stopped moving?" answers yes in every gap
# between bursts, so two quiet polls slip through the lull mid-save and raising the count loses the same argument
# with a bigger number. So the gate asks whether the block holds the RIGHT CONTENT again: the Bag does not change
# because you saved, so when the sequence finishes the item array must read exactly as it did before the menu opened.
# It detects "the block is currently telling the truth", not "the save is finished". Escape valve: content that
# legitimately changed during the disturbance never matches the old baseline, so after this many unstable polls the
# gate re-baselines. ~60 seconds -- longer than any save, short enough to self-heal.
BLOCK_MAX_UNSTABLE_POLLS = 60


def _byte_difference(a: bytes, b: bytes) -> int:
    """How many bytes differ between two equal-length windows. Pulled out so the gate reads the same comparing
    against the previous poll or against the last trusted content."""
    return sum(1 for x, y in zip(a, b) if x != y)


@dataclass
class BlockStabilityGate:
    """Watches a quiet window of the save block and reports whether it is being rewritten right now.

    `poll()` returns True when the block looks trustworthy this tick. It never raises: an unreadable window
    returns False, the safe direction -- a false "unstable" costs a check arriving a second late, a false
    "stable" costs a location checked that should never have been."""

    window_offset: int = BLOCK_STABILITY_WINDOW_OFFSET
    window_size: int = BLOCK_STABILITY_WINDOW_SIZE
    churn_threshold: int = BLOCK_CHURN_BYTE_THRESHOLD
    quiet_polls_required: int = BLOCK_QUIET_POLLS_AFTER_CHURN

    max_unstable_polls: int = BLOCK_MAX_UNSTABLE_POLLS

    stable: bool = True
    churn_events: int = 0          # times the block has started churning this session
    suppressed_polls: int = 0      # polls the gate has withheld
    last_churn_bytes: int = 0      # size of the most recent churn, for diagnostics
    peak_churn_bytes: int = 0
    rebaselines: int = 0           # ADDENDUM 154: times the escape valve fired
    _previous: "bytes | None" = None
    # The last window content this gate was willing to call the truth. A disturbance ends when the block reads
    # like this again, not merely when it stops moving.
    _trusted: "bytes | None" = None
    _quiet_polls: int = 0
    _unstable_polls: int = 0

    def poll(self, block_base: int) -> bool:
        try:
            window = read_bytes(block_base + self.window_offset, self.window_size)
        except Exception:
            self.suppressed_polls += 1
            return False
        if len(window) != self.window_size:
            self.suppressed_polls += 1
            return False

        previous = self._previous
        self._previous = window
        if previous is None:
            # Nothing to compare against yet. Trust this tick: every tracker baselines on its own first poll,
            # so nothing here can fire a check.
            self._trusted = window
            return True

        differing = _byte_difference(previous, window)
        if differing > self.churn_threshold:
            if self.stable:
                self.churn_events += 1
            self.stable = False
            self._quiet_polls = 0
            self._unstable_polls = 0
            self.last_churn_bytes = differing
            self.peak_churn_bytes = max(self.peak_churn_bytes, differing)
            self.suppressed_polls += 1
            return False

        if self.stable:
            # Quiet and already trusted: this IS the truth, so it becomes the reference a future disturbance
            # has to return to.
            self._trusted = window
            return True

        # Settled means "matches the last trusted content again", not "matches the previous poll": a multi-burst
        # save is quiet in the gaps between bursts, so poll-to-poll agreement reopens the gate mid-save.
        self._unstable_polls += 1
        trusted = self._trusted
        if trusted is not None and _byte_difference(trusted, window) > self.churn_threshold:
            self._quiet_polls = 0
            if self._unstable_polls >= self.max_unstable_polls:
                # The content genuinely changed during the disturbance and will never match the old reference.
                # Adopt what is there rather than withhold forever.
                self._trusted = window
                self.stable = True
                self.rebaselines += 1
                return True
            self.suppressed_polls += 1
            return False

        self._quiet_polls += 1
        if self._quiet_polls >= self.quiet_polls_required:
            self.stable = True
            self._trusted = window
            return True
        self.suppressed_polls += 1
        return False

    def reset(self) -> None:
        """Drop the baseline (a reconnect, or the save block relocating). Counters are kept -- they describe
        the session, not the current baseline."""
        self._previous = None
        self._trusted = None
        self.stable = True
        self._quiet_polls = 0
        self._unstable_polls = 0

    def describe(self) -> str:
        state = "stable" if self.stable else "CHURNING -- block-derived checks are paused"
        return (
            f"Save block: {state}. "
            f"Watching {self.window_size} bytes at BLOCK_BASE+{self.window_offset:#x} (the Bag item array); "
            f"more than {self.churn_threshold} bytes changing between polls counts as a rewrite. "
            f"Rewrites seen this session: {self.churn_events} "
            f"(largest {self.peak_churn_bytes} bytes, most recent {self.last_churn_bytes}). "
            f"Polls withheld: {self.suppressed_polls}. "
            f"Re-baselined after a disturbance that never settled back: {self.rebaselines}."
        )


# ChestCountTracker is gone: it turned the dummy berry's running quantity into "Open N Chests" names, which no
# longer exist in the datapackage. `ChestFlagTracker` replaces it and reports chest IDs.
#
# Two of its scars were consequences of having no per-chest identity rather than bugs: the confirm-streak
# debounce (a Bag quantity can flicker mid-write and a count cannot tell a flicker from a chest), and the ISO
# patch forcing every chest's Quantity to 1 (a 3-quantity chest otherwise produced three checks). That patch
# stays -- one chest is one check either way -- but is no longer load-bearing. A flag bit has neither problem:
# one bit that only turns on, and it names the chest.

# Shop berries come from the one shared `game_data` module, which `ram_client` can import directly. This used
# to be a hand-copied duplicate of items.py's list and had gone stale: it still listed berries 169-174 as shop
# berries after they became CHEST berries, so ShopPurchaseTracker was watching -- and clearing out of the Bag --
# six of the seven berries ChestBerryTracker needs to identify a chest.
from .game_data.shop_berries import (  # noqa: E402
    SHOP_BERRY_SPECS as USELESS_BERRY_SPECS,
    SHOP_BERRY_IDS as USELESS_BERRY_IDS,
    SHOP_BERRY_ID_TO_NAME as USELESS_BERRY_ID_TO_NAME,
)

# --- Shop locations are named after SHOPS, and the room id is what names them. ---
# Mirrors game_data/shops.py, which this module CAN import (pure data, no Archipelago dependency), so nothing
# here is a hand-copied number that can drift. `shop_item_location_name(berry_name, occurrence)` is deleted
# rather than kept: its output no longer exists in the datapackage, so a stale caller would send rejected
# checks.


def shop_location_name_for_room(room_id: int, slot: int) -> "str | None":
    from .game_data import shops

    shop = shops.shop_for_room(room_id)
    return None if shop is None else shops.shop_location_name(shop.name, slot)


def shop_slot_count_for_room(room_id: int) -> int:
    """Per shop, not a flat cap. 0 for anything that is not a confirmed shop room."""
    from .game_data import shops

    return shops.slot_count_for_room(room_id)


def is_shop_room(room_id: "int | None") -> bool:
    from .game_data import shops

    return room_id is not None and room_id in shops.SHOP_ROOM_IDS and not shops.is_disabled_shop_room(room_id)


def _batch_item_quantities(pocket_base: int, slot_count: int, item_ids: "set[int] | frozenset[int]") -> dict[int, int]:
    """Single-pass pocket scan for several tracked item ids at once. `ShopPurchaseTracker.poll()` needs every
    useless berry's live quantity each poll, and `find_item_quantity` per berry would mean that many full
    190-slot scans. Returns {item_id: quantity}, defaulting every requested id to 0 like `find_item_quantity`."""
    result = {item_id: 0 for item_id in item_ids}
    for slot in read_pocket(pocket_base, slot_count):
        if not slot.empty and slot.item_id in result:
            result[slot.item_id] = slot.quantity
    return result


# What a shelf line reads once it has nothing left to send. Eight characters, so it fits the ten-character
# budget of even the shortest shop berry.
NO_CHECK_NAME = "NO CHECK"


@dataclass
class ItemNameRenamer:
    """Renames the dummy shop berries in RAM, live, so the shop screen says which AP check a purchase sends.

    Writes on a room CHANGE, before any menu opens, and only for berries whose text differs from what this
    instance last wrote. Writing early sidesteps the open question of whether the game caches a string into a
    text buffer when a menu opens, and keeps a steady-state poll at zero writes.

    `verify()` runs once and reads the bytes at every address it intends to write, refusing unless all of them
    have the exact shape of a string-table entry. A wrong base would scribble UTF-16 over whatever else lives at
    0x80B18DC0, so the failure mode is "off, and said so once". The check is content-agnostic on purpose.

    Non-blocking by construction: nothing here touches item delivery, and a failed write disables renaming for
    the session and leaves every other tracker alone. Cosmetics must never cost a check."""

    enabled: bool = True
    verified: bool = False
    verify_failures: "list[str]" = field(default_factory=list)
    writes: int = 0
    _written: "dict[int, str]" = field(default_factory=dict)
    _last_room: "int | None" = field(default=None)
    _last_room_set: bool = False
    # Mirrored from ShopPurchaseTracker each poll, as plain fields rather than a reference, so this class never
    # reaches into another tracker's state.
    slots_credited_by_room: "dict[int, int]" = field(default_factory=dict)
    purchased_by_room: "dict[int, set[int]]" = field(default_factory=dict)

    def verify(self, berry_ids: "list[int]") -> bool:
        """Read-only. True when every berry's name entry is where `item_name_strings` says it is."""
        from .game_data import item_name_strings as ins

        self.verify_failures = []
        for item_id in berry_ids:
            address = ins.ram_address(item_id)
            budget = ins.budget_chars(item_id)
            if address is None or budget is None:
                self.verify_failures.append(f"item {item_id}: no recorded name-string offset")
                continue
            try:
                raw = read_bytes(address, budget * 2 + 2)
            except Exception as exc:  # pragma: no cover - live-Dolphin failure path
                self.verify_failures.append(f"item {item_id}: read at {address:#010x} failed ({exc})")
                continue
            if not ins.is_plausible_entry_bytes(raw, budget):
                self.verify_failures.append(
                    f"item {item_id}: bytes at {address:#010x} are not a string-table entry"
                )
        self.verified = not self.verify_failures
        if not self.verified:
            self.enabled = False
        return self.verified

    def desired_names(self, room_id: "int | None", berry_ids: "list[int]") -> "dict[int, str]":
        """What every berry should be called right now. Pure -- no reads or writes, so the policy is testable
        without Dolphin.

        The number IS the line and also the check: the patcher deals berries per shop line (berry index k+1 is
        shelf line k+1 in every shop) and the tracker credits by that index, so "GATEON 07" is literally
        `Gateon Port Shop AP Item 7` and buying out of order changes nothing. An earlier version labelled every
        berry in a shop with the same next-check text, which was accurate but useless at a twelve-line shelf.

        NO CHECK appears in two cases: the berry has already been bought in this room this session (buy each line
        once and the shelf empties, which is the workflow asked for), or its line number is past this shop's
        recorded stock count so no line answers to it. Greying is per line, not per room -- a room's count can
        reach its cap while individual lines remain unbought, and greying a live line out would tell the player a
        real check is gone."""

        from .game_data import item_name_strings as ins
        from .game_data import shops

        if room_id is not None and is_shop_room(room_id):
            label = shops.short_label_for_room(room_id)
            if label is not None:
                cap = shop_slot_count_for_room(room_id)
                bought = self.purchased_by_room.get(room_id, set())
                names = {}
                for item_id in berry_ids:
                    # The CANONICAL index, for the same reason ShopPurchaseTracker uses it: `berry_ids` may be
                    # a subset, and a subset index would silently renumber the whole shelf.
                    line = USELESS_BERRY_IDS.index(item_id) + 1
                    names[item_id] = (NO_CHECK_NAME if (item_id in bought or line > cap)
                                      else f"{label} {line:02d}")
                return names
        return {item_id: ins.numbered_name(USELESS_BERRY_IDS.index(item_id) + 1)
                for item_id in berry_ids}

    def _credited_for(self, room_id: int) -> int:
        return self.slots_credited_by_room.get(room_id, 0)

    def poll(self, room_id: "int | None", berry_ids: "list[int]" = USELESS_BERRY_IDS) -> int:
        """Writes any names that changed. Returns how many entries were rewritten (0 in the steady state).

        An UNREADABLE room is not "not in a shop". `read_room_id` returns None rather than a guess when its four
        replicated copies disagree, which they do around transitions -- and opening a shop menu is a transition.
        Passing that None through to `desired_names` hit its no-shop branch and wiped the whole shelf, and it
        stayed wiped while the room stayed unreadable. So None HOLDS: no write, no state change, ask again next
        poll. Only a readable non-shop room clears the labels.

        The steady-state early-out is kept: a room that has not changed does nothing."""
        if not self.enabled or not self.verified:
            return 0
        if room_id is None:
            return 0
        if self._last_room_set and room_id == self._last_room:
            return 0
        self._last_room = room_id
        self._last_room_set = True
        return self._write(self.desired_names(room_id, berry_ids))

    def refresh(self, room_id: "int | None", berry_ids: "list[int]" = USELESS_BERRY_IDS) -> int:
        """Rewrite without waiting for a room change -- used right after a purchase is credited, so the shelf
        advances while the player is still standing at it."""
        if not self.enabled or not self.verified:
            return 0
        return self._write(self.desired_names(room_id, berry_ids))

    def _write(self, desired: "dict[int, str]") -> int:
        from .game_data import item_name_strings as ins

        written = 0
        for item_id, text in desired.items():
            if self._written.get(item_id) == text:
                continue
            address = ins.ram_address(item_id)
            budget = ins.budget_chars(item_id)
            if address is None or budget is None:
                continue
            payload = ins.encode_name(text, budget)
            if payload is None:
                # Should be unreachable (shops.py asserts every live name fits at import time), but a name that
                # does not fit is skipped rather than truncated into something misleading.
                continue
            try:
                write_bytes(address, payload)
            except Exception:  # pragma: no cover - live-Dolphin failure path
                self.enabled = False
                return written
            self._written[item_id] = text
            written += 1
        self.writes += written
        return written


@dataclass
class ShopPurchaseTracker:
    """Watches every useless berry's Bag quantity independently and keeps a separate occurrence count per berry, so
    buying each shop item once sends one AP check. The berry is the signal; the room is the identity.

    Mirrors `trainer_defeat.SURNAME_TO_LOCATION_QUEUE`'s "cannot identify occurrence N directly, but can count
    occurrences in order" pattern, scoped per berry id, with the same debounce as the other trackers.

    A confirmed purchase CLEARS that berry's slot and resets its own `last_seen_quantity` to 0. That is a necessity:
    a shop slot can be bought from indefinitely, so without clearing there is no way to tell leftover stock from a
    fresh purchase. Requires the seed's shop ISO patch, without which no quantity ever moves.

    Counts only increases observed live by this instance. Safe on the protocol side -- the server dedupes, so this can
    only under-report a threshold. Not yet live-verified: the shop ISO patch itself (xd_rel_format.py's mart
    pointer-table indices are unconfirmed against a real ISO), and that a real purchase's berry lands inside the
    scanned pocket array the way chest pickups were confirmed to."""

    last_seen_quantity: dict[int, int] = field(default_factory=dict)
    # Keyed by SHOP ROOM id, not berry id: the berry is the signal, the room is the identity.
    slots_credited: dict[int, int] = field(default_factory=dict)
    # {shop room id: berry ids already bought there this session}. Display state for the live rename only --
    # nothing about which check fires reads this.
    purchased_by_room: "dict[int, set[int]]" = field(default_factory=dict)
    purchases_outside_a_shop: int = 0
    # ADDENDUM 394: {room id: berry increases seen there} for rooms this client does not list as a shop. The
    # COUNT alone said "credited nothing, by design", which is only true when the room really is not a shop.
    # When it is a shop whose id this project has wrong, the same counter was reporting a silent loss of every
    # check in that shop as intended behaviour. The room id is the one datum that tells the two apart.
    unknown_shop_rooms: "dict[int, int]" = field(default_factory=dict)
    _initialized: "set[int]" = field(default_factory=set)
    _pending_quantity: dict[int, int] = field(default_factory=dict)
    _pending_streak: dict[int, int] = field(default_factory=dict)
    # `self.clock()` when this berry's current candidate quantity was first seen; see `_CONFIRM_SECONDS`.
    _pending_since: dict[int, float] = field(default_factory=dict)
    # The clock the duration floor is measured against, injectable so a test can drive it: the debounce tests
    # poll in a tight loop where no real time passes, so an undrivable floor could only ever be disabled. Not a
    # ClassVar -- monkeypatching one in a single test would leak into every other.
    clock: "Callable[[], float]" = time.monotonic
    # ClassVar, not a dataclass field: `set_poll_interval()` re-derives it from a duration at startup, and a
    # field default is captured at class creation, so a class-attribute assignment would not reach new instances.
    _CONFIRM_STREAK: ClassVar[int] = 4

    # A wall-clock floor, because this tracker no longer runs at one fixed rate: Client.py polls it several times per
    # outer tick inside a shop room, so a pure poll count would confirm a purchase in a fraction of the real time the
    # window covers. A candidate must satisfy BOTH `_CONFIRM_STREAK` agreeing reads and `_CONFIRM_SECONDS` of elapsed
    # time. A clock floor can only delay a credit, never advance one, which is why it is a floor and not a replacement.
    _CONFIRM_SECONDS: ClassVar[float] = CONFIRM_WINDOW_SECONDS["shop_purchase"]

    # Money is a second witness, and it lets a corroborated purchase skip the window entirely: a shop purchase always
    # spends money, so a genuine one is a berry up and money down together. That is stronger evidence than repeating a
    # read, not a shortcut around it -- the glitch the window survives is a STALE read of the save block, and money and
    # the Bag live in the same block, so a stale snapshot is internally consistent and would have to show a moment in
    # which the purchase had already happened. Narrow on purpose: needs a readable shop room, a berry strictly up,
    # money strictly down since our own previous poll, and a live baseline for both.
    _last_money: "int | None" = None
    money_corroborated_credits: int = 0

    def poll(
        self,
        block_base: int,
        room_id: "int | None" = None,
        pocket_offset: int = POKEBALL_POCKET_OFFSET,
        slot_count: int = POKEBALL_POCKET_ARRAY_SLOT_COUNT,
        berry_ids: "list[int]" = USELESS_BERRY_IDS,
    ) -> list[str]:
        pocket_base = block_base + pocket_offset
        quantities = _batch_item_quantities(pocket_base, slot_count, set(berry_ids))
        newly_crossed: list[str] = []

        # The second witness. Read once per poll, before anything is decided, and compared against OUR OWN
        # previous reading -- "did money go down since we last looked" is the only form of the question a
        # purchase answers. A failed read is evidence of nothing: `money_fell` stays False and every berry takes
        # the ordinary debounced path. The baseline still updates, so one bad read costs one poll.
        money_fell = False
        try:
            money = struct.unpack(">I", read_bytes(block_base + MONEY_OFFSET, 4))[0]
        except Exception:
            money = None
        if money is not None:
            money_fell = self._last_money is not None and money < self._last_money
            self._last_money = money

        for item_id in berry_ids:
            quantity = quantities[item_id]
            if item_id not in self._initialized:
                # First poll after connecting: baseline only. Per berry, not globally, so a berry first seen
                # mid-session still baselines cleanly instead of being compared against an implicit 0.
                self.last_seen_quantity[item_id] = quantity
                self._initialized.add(item_id)
                continue
            last_seen = self.last_seen_quantity.get(item_id, 0)
            if quantity == last_seen:
                self._pending_quantity.pop(item_id, None)
                self._pending_streak.pop(item_id, None)
                self._pending_since.pop(item_id, None)
                continue
            if quantity < last_seen:
                # A decrease is legitimate here -- our own clear-after-detection racing a poll, or the player
                # using the dummy item. Accept it as this berry's new baseline; never fire on a non-increase.
                self.last_seen_quantity[item_id] = quantity
                self._pending_quantity.pop(item_id, None)
                self._pending_streak.pop(item_id, None)
                self._pending_since.pop(item_id, None)
                continue
            # quantity > last_seen: a candidate increase for this berry, debounced independently per berry id.
            # The corroborated fast path is taken only when money fell this same poll and the room is a real
            # shop; everything else falls through to the floors below.
            corroborated = money_fell and is_shop_room(room_id)
            if not corroborated:
                if self._pending_quantity.get(item_id) != quantity:
                    self._pending_quantity[item_id] = quantity
                    self._pending_streak[item_id] = 1
                    self._pending_since[item_id] = self.clock()
                    continue
                self._pending_streak[item_id] = self._pending_streak.get(item_id, 0) + 1
                if self._pending_streak[item_id] < self._CONFIRM_STREAK:
                    continue
                # The duration half of the same window. `_pending_since` can only be missing for a candidate
                # predating the field, which cannot happen in one process -- treat it as "now" and re-decide.
                since = self._pending_since.get(item_id)
                if since is None:
                    self._pending_since[item_id] = self.clock()
                    continue
                if (self.clock() - since) < self._CONFIRM_SECONDS:
                    continue
            else:
                self.money_corroborated_credits += 1
            delta = quantity - last_seen
            # The room decides which shop this was, and an UNREADABLE room id needs care: `read_room_id` returns
            # None when its four copies disagree, and a purchase confirms about two seconds after it happens while
            # the player is still in the shop. So None is a transient read failure, not "not in a shop" -- leave the
            # increase pending and do not clear the berry, since clearing would silently eat the check.
            if room_id is None:
                continue
            shop_room = room_id if is_shop_room(room_id) else None
            if shop_room is None:
                # A real room that is not a shop. A dummy berry can go up outside any shop (a gift, a field
                # pickup) and crediting a guess would send a check for a purchase that never happened. The berry
                # is still cleared below, because "counted stock vs fresh purchase" needs the slot to empty.
                #
                # ADDENDUM 394: remember WHERE. Eight of the ten shop rooms are `source="player"` rather than a
                # live `!room` reading, and shops.py says in as many words that a shop going silent is where to
                # look. A wrong id makes every live writer fall back AND every purchase there credit nothing,
                # which is what the Outskirt Stand report looked like.
                self.purchases_outside_a_shop += delta
                self.unknown_shop_rooms[room_id] = self.unknown_shop_rooms.get(room_id, 0) + delta
            else:
                # THE BERRY IS THE LINE NUMBER. `apply_mart_randomization` assigns `dummy_item_ids[k]` to the
                # (k+1)th distinct line a shop ever offers and holds it across every tier, so berry index k+1 IS
                # shelf line k+1 in every shop -- crediting the next uncredited slot instead would mis-order, since
                # buying Agate's line 3 first would credit line 1. Crediting by the berry's own index also means
                # purchases need not be seen in shelf order and re-buying a line is idempotent. Always the CANONICAL
                # list, never the `berry_ids` argument, which may be a subset and would renumber the shelf.
                line = USELESS_BERRY_IDS.index(item_id) + 1
                cap = shop_slot_count_for_room(shop_room)
                if line <= cap:
                    name = shop_location_name_for_room(shop_room, line)
                    # `delta` is deliberately ignored: buying three of one line is still one check.
                    if name is not None and item_id not in self.purchased_by_room.get(shop_room, ()):
                        newly_crossed.append(name)
                    self.slots_credited[shop_room] = max(self.slots_credited.get(shop_room, 0), line)
                else:
                    # A berry above this shop's line count cannot be one of its lines, but can still reach the
                    # Bag here (a gift opened in a shop), so it is counted like a purchase outside a shop.
                    self.purchases_outside_a_shop += delta
                # Which shelf lines have been bought in this room this session: drives the rename's greying,
                # and doubles as the idempotence record above.
                self.purchased_by_room.setdefault(shop_room, set()).add(item_id)
            # Remove this berry now that its purchases are converted into checks, and reset ITS baseline to 0
            # (not `quantity`) to match, since the slot is now expected to be empty.
            clear_item(pocket_base, slot_count, item_id)
            self.last_seen_quantity[item_id] = 0
            self._pending_quantity.pop(item_id, None)
            self._pending_streak.pop(item_id, None)
            self._pending_since.pop(item_id, None)
        return newly_crossed


@dataclass
class StoryProgressWitness:
    """The highest story byte the GAME put there -- never one this client wrote. `Unlock -` checks credit against
    this high-water mark, not the live byte, because `AreaStoryByteMemory.poll` writes a map destination's entry floor
    while the cursor rests on it: reading the live byte in the same tick fired seven earlier thresholds off one hover.

    Credible needs all four: off the map screen (on room 910 every cursor move rewrites the byte); no hover write
    outstanding (reuses `AreaStoryByteMemory._write_outstanding`, so the two readers cannot disagree); the Robo Kyogre
    Parts override not holding the byte; and not a value we wrote (`last_written_target`, passed in rather than
    re-derived, and deliberately not cleared on commit -- without it, travelling to Realgam commits 0x41, the witness
    banks it once the room loads, and travelling on to Gateon, floor 0x0F, waves every threshold through).

    A high-water mark, not a live value: the byte legitimately moves DOWN (a first-visit floor, the override's
    restore) and a credit that un-fired on a dip would be worse than useless. The cost is one value -- a threshold
    equal to a floor we wrote is HELD until the game advances past it, which is what playing the area does."""

    high_water: int = -1
    credible_polls: int = 0
    suppressed_polls: int = 0
    last_suppressed_value: "int | None" = None
    last_reason: "str | None" = None
    declined_our_own_write: int = 0

    def poll(self, story_byte: "int | None", room_id: "int | None",
             write_outstanding: bool, override_active: bool,
             last_written_value: "int | None" = None) -> int:
        """Feed one tick's reading. Returns the high-water mark, which is what a credit compares against.

        `last_written_value` is `AreaStoryByteMemory.last_written_target`. It defaults to None so a caller that
        cannot supply it degrades rather than raising, but every live caller passes it."""
        if story_byte is None:
            self.last_reason = "story byte unreadable"
            return self.high_water
        reason: "str | None" = None
        if room_id == MAP_SCREEN_ROOM_ID:
            reason = "on the map screen"
        elif write_outstanding:
            reason = "a hover write is outstanding"
        elif override_active:
            reason = "the Robo Kyogre Parts override is holding the byte"
        elif last_written_value is not None and story_byte == last_written_value:
            # Our own write is never evidence -- the same rule the area memory applies, second reader.
            self.declined_our_own_write += 1
            reason = "this value is the one the client wrote (a travel or hover commit)"
        if reason is not None:
            self.suppressed_polls += 1
            self.last_suppressed_value = story_byte
            self.last_reason = reason
            return self.high_water
        self.credible_polls += 1
        self.last_reason = None
        if story_byte > self.high_water:
            self.high_water = story_byte
        return self.high_water

    def describe(self) -> "list[str]":
        lines = [
            "Story progress (what `Unlock -` checks are credited from):",
            ("  highest credible byte: "
             + ("none seen yet" if self.high_water < 0 else f"0x{self.high_water:02X}")),
            f"  credible polls: {self.credible_polls}, suppressed: {self.suppressed_polls}",
        ]
        if self.declined_our_own_write:
            lines.append(f"  Declined {self.declined_our_own_write} reading(s) that were this client's own "
                         f"write (ADDENDUM 284) -- a committed travel floor is not story progress.")
        if self.last_reason:
            value = ("?" if self.last_suppressed_value is None
                     else f"0x{self.last_suppressed_value:02X}")
            lines.append(f"  right now: NOT credible ({self.last_reason}); live byte reads {value}")
        return lines


@dataclass
class ItemPriceWriter:
    """Prices each shop shelf line by what it actually sends.

    Has to be live and per room rather than patched into the ISO: price lives in common_rel's global Items
    table, keyed by ITEM ID, and berry index k is line k+1 in EVERY shop. So Agate line 3 and Gateon line 3 are
    the same berry and would necessarily share a price. A patch-time price is a price per line number, globally,
    which cannot say "this line holds progression and that one doesn't".

    Live works for the same reason the rename does: common_rel is permanently resident at a fixed base, and the
    room says which shop the player is in, so berry k is repriced on entry from what THAT shop's line k holds.

    The table is resolved from the REL's own pointer table (index 70), never from a stored offset. A wrong base
    here is a write into an arbitrary part of common_rel, so `verify()` checks the resolved table against every
    shop berry's known NameID and the feature stays off unless all of them agree."""

    enabled: bool = True
    verified: bool = False
    table_base: "int | None" = None
    verify_failures: "list[str]" = field(default_factory=list)
    writes: int = 0
    _written: "dict[int, int]" = field(default_factory=dict)
    _last_room: "int | None" = None
    _last_room_set: bool = False
    _last_fingerprint: "tuple[int, int] | None" = None

    def resolve(self) -> "int | None":
        """The Items table's RAM address, from the REL's own pointer table. None if anything is unreadable.

        Cached: the REL does not move once loaded, so this is a handful of reads once per session."""
        from .game_data import item_name_strings as ins

        if self.table_base is not None:
            return self.table_base
        try:
            base = ins.COMMON_REL_RAM_BASE
            data_section = struct.unpack(
                ">I", read_bytes(base + ins.REL_DATA_SECTION_ADDRESS_OFFSET, 4))[0]
            pointer_table = struct.unpack(
                ">I", read_bytes(base + ins.REL_POINTER_TABLE_ADDRESS_OFFSET, 4))[0]
        except Exception:
            return None
        if not (MEM1_START <= data_section < MEM1_START + MEM1_SIZE
                and MEM1_START <= pointer_table < MEM1_START + MEM1_SIZE):
            return None
        entry = (pointer_table + ins.REL_FIRST_POINTER_OFFSET
                 + ins.ITEMS_TABLE_POINTER_INDEX * ins.REL_POINTER_STRIDE
                 + ins.REL_POINTER_VALUE_OFFSET)
        try:
            relative = struct.unpack(">I", read_bytes(entry, 4))[0]
        except Exception:
            return None
        resolved = data_section + relative
        if not MEM1_START <= resolved < MEM1_START + MEM1_SIZE:
            return None
        self.table_base = resolved
        return resolved

    def verify(self, berry_ids: "list[int]" = USELESS_BERRY_IDS) -> bool:
        """Every shop berry's entry must carry the NameID it is supposed to. All or nothing.

        26 consecutive unrelated structs each holding exactly the predicted NameID does not happen by accident,
        so agreement is strong evidence the base is right -- and one disagreement means writing nothing, ever,
        this session."""
        from .game_data import item_name_strings as ins

        self.verify_failures = []
        base = self.resolve()
        if base is None:
            self.verify_failures.append("could not resolve the Items table from the REL pointer table")
            self.verified = False
            return False
        for item_id in berry_ids:
            expected = ins.expected_name_id(item_id)
            if expected is None:
                continue
            try:
                raw = struct.unpack(
                    ">I", read_bytes(base + item_id * ins.ITEM_ENTRY_SIZE + ins.ITEM_NAME_ID_OFFSET, 4))[0]
            except Exception:
                self.verify_failures.append(f"item {item_id}: entry unreadable")
                self.verified = False
                return False
            if (raw & ins.ITEM_NAME_ID_MASK) != expected:
                self.verify_failures.append(
                    f"item {item_id}: NameID {raw & ins.ITEM_NAME_ID_MASK} != {expected} -- "
                    "the resolved Items table is not the Items table")
                self.verified = False
                return False
        self.verified = True
        return True

    def desired_prices(
        self,
        room_id: "int | None",
        classifications: "dict[str, str]",
        berry_ids: "list[int]" = USELESS_BERRY_IDS,
    ) -> "dict[int, int]":
        """What each berry should cost while the player stands in `room_id`. Pure -- no reads, no writes.

        Outside a shop every berry returns to its vanilla 20. Not tidiness: price is global per item, so leaving
        a 2000 on one would misprice that line number in the next shop entered, before its own poll corrects it."""
        from .game_data import item_name_strings as ins
        from .game_data import shops

        shop = shops.shop_for_room(room_id) if room_id is not None else None
        out: "dict[int, int]" = {}
        for item_id in berry_ids:
            if ins.expected_name_id(item_id) is None:
                continue
            price = ins.VANILLA_SHOP_BERRY_PRICE
            if shop is not None:
                line = USELESS_BERRY_IDS.index(item_id) + 1
                if line <= shop.slot_count:
                    name = shops.shop_location_name(shop.name, line)
                    # An unscouted line prices as FILLER, not as the vanilla restore value. Conflating the two
                    # would make a shelf whose scout has not landed visibly different from one whose has, which
                    # is exactly what the price must not leak.
                    price = ins.PRICE_BY_CLASSIFICATION.get(
                        classifications.get(name, "filler"),
                        ins.PRICE_BY_CLASSIFICATION["filler"])
            out[item_id] = max(0, min(int(price), ins.MAX_ITEM_PRICE))
        return out

    def poll(
        self,
        room_id: "int | None",
        classifications: "dict[str, str]",
        berry_ids: "list[int]" = USELESS_BERRY_IDS,
    ) -> int:
        """One tick. Returns how many prices were written (0 in the steady state).

        Rewrites on a room change, and also when the SCOUT changes. The renamer only needs the room, because its
        labels come from the room and the berry index, which the client has at connect time. A price comes from
        what the server says each line holds, and that arrives asynchronously after `Connected` -- so without
        watching it, the first pass priced everything as filler and nothing was rewritten until the player left a
        shop and came back.

        The scout is compared by a cheap fingerprint rather than a copy of the map: this runs every tick and the
        map has one entry per shop line in the seed."""
        if not self.enabled:
            return 0
        if not self.verified and not self.verify(berry_ids):
            self.enabled = False
            return 0
        # An unreadable room HOLDS rather than restoring. `desired_prices(None)` puts every berry back to 20,
        # so one bad read at a counter wiped the whole shelf -- and `read_room_id` returns None exactly around
        # transitions like opening a shop menu.
        if room_id is None:
            return 0
        fingerprint = self._fingerprint(classifications)
        if (self._last_room_set and room_id == self._last_room
                and fingerprint == self._last_fingerprint):
            return 0
        self._last_room = room_id
        self._last_room_set = True
        self._last_fingerprint = fingerprint
        return self.write(self.desired_prices(room_id, classifications, berry_ids))

    @staticmethod
    def _fingerprint(classifications: "dict[str, str]") -> "tuple[int, int]":
        """A cheap stand-in for "has the scout answer changed": size plus a hash over the items. Size alone
        would miss a line being re-classified without the count moving."""
        return (len(classifications), hash(frozenset(classifications.items())))

    def refresh(self, room_id: "int | None", classifications: "dict[str, str]",
                berry_ids: "list[int]" = USELESS_BERRY_IDS) -> int:
        """Rewrite without waiting for a room change -- used right after a purchase is credited, so a line that
        just became NO CHECK stops being priced like the item it no longer sends."""
        if not self.enabled or not self.verified:
            return 0
        return self.write(self.desired_prices(room_id, classifications, berry_ids))

    def write(self, desired: "dict[int, int]") -> int:
        from .game_data import item_name_strings as ins

        base = self.table_base
        if base is None:
            return 0
        written = 0
        for item_id, price in desired.items():
            if self._written.get(item_id) == price:
                continue
            try:
                write_bytes(base + item_id * ins.ITEM_ENTRY_SIZE + ins.ITEM_PRICE_OFFSET,
                            struct.pack(">H", price))
            except Exception:
                # Cosmetic, like every live write here: one failure disables the feature for the session
                # rather than retrying into a loop.
                self.enabled = False
                return written
            self._written[item_id] = price
            written += 1
        self.writes += written
        return written


@dataclass
class ItemDescriptionWriter:
    """Writes the real AP item a shop line will send into that line's DESCRIPTION, live, while the menu is open.

    Needs the server's answer about what each line holds (`ctx.scouted_shop_items`) and the description table's
    location in RAM. That table is awkward where the name table in the resident `common_rel` is not:

      * IT MOVES. Seen at 0x809CECC0, 0x8099DC60, 0x80D81B60 and 0x809AECA0, and no u32 in MEM1 holds its address
        in more than one dump, so it has to be SEARCHED for. Its magic occurs exactly once in 24 MB, which is what
        makes that search safe.
      * IT IS NOT ALWAYS THERE. It loads when a menu opens and lingers briefly after; with the menu shut it is gone.
      * IT IS RELOADED FROM DISC ON EVERY MENU OPEN, wiping our writes -- so this writes while the menu is open and
        rewrites whenever the table reappears or moves.

    The search stays cheap by re-probing confirmed bases first (one 8-byte read each, unthrottled), walking the two
    measured bands on every scan so the resumable sweep's cursor cannot decide how long the common case takes, and
    backing the sweep off to `_IDLE_SECONDS_BETWEEN_SCANS` once a full pass proves the table is not resident.

    Only runs in a shop room, and non-blocking by construction. ADDENDUM 389: a failed READ no longer disables
    anything -- it is counted and retried, because the search reads megabytes of MEM1 and one unlucky read while
    a menu closed used to turn every shop after the first one generic for the rest of the session. Only a failed
    WRITE disables, and that is a bridge that is not going to work anyway."""

    enabled: bool = True
    table_base: "int | None" = None
    writes: int = 0
    scans: int = 0
    failed_scans: int = 0
    # ADDENDUM 389: failed MEM1 reads during the search. Counted, never fatal -- see `_read_window`.
    read_failures: int = 0
    reloads_detected: int = 0
    last_error: "str | None" = None
    _written: "dict[int, tuple[int, tuple[str, ...]]]" = field(default_factory=dict)
    _last_scan_at: float = 0.0
    _scan_cursor: int = 0
    # (item_id, the exact bytes we wrote there). See `_canary_still_ours`.
    _canary: "tuple[int, bytes] | None" = None
    # Addresses this table has been confirmed at THIS SESSION, most recent first, probed with one 8-byte read
    # each before any chunk scanning. See `locate`.
    _hot_bases: "list[int]" = field(default_factory=list)
    hot_hits: int = 0
    # Current gap between chunk scans. Starts active and drops to idle after a full sweep finds nothing, which is
    # proof the table is not resident and the menu is shut.
    _scan_interval: float = 0.25

    # A scan reads MEM1 in chunks. 0x10000 is the chunk size `dump_mem1` already established as trustworthy
    # against dolphin_memory_engine.
    _CHUNK: ClassVar[int] = 0x10000
    # The scan is RESUMABLE, which is the important part: MEM1 is 24 MB, ~380 reads at 64 KB a chunk, and doing them
    # in one tick would stall the loop that is also delivering items and sending checks. 32 rather than 24 so the two
    # measured bands (26 chunks apart) fall inside a SINGLE slice.
    _CHUNKS_PER_POLL: ClassVar[int] = 32
    # Two rates, because `check_shops` runs at POLL_INTERVAL_FAST but a single throttle meant the search advanced
    # at a fixed chunks-per-second regardless. `_ACTIVE` is the rate while the table might be there; `_IDLE` is
    # the rate after a full sweep has proved it is not -- the state of a player standing in a shop with the menu
    # shut, which otherwise cost 2 MB of reads a second indefinitely.
    _MIN_SECONDS_BETWEEN_SCANS: ClassVar[float] = 0.25
    _IDLE_SECONDS_BETWEEN_SCANS: ClassVar[float] = 1.0
    # How many confirmed bases to keep and re-probe. Eight 8-byte reads is free next to a chunk, and the table
    # lands back on a recent address often enough that this is the fast path in practice.
    _HOT_BASES_KEPT: ClassVar[int] = 8

    def locate(self, now: "float | None" = None) -> "int | None":
        """The table's current base, or None if this poll's slice of the search did not reach it.

        The sweep runs whether or not the menu is open (`poll` gates on being in a shop room, not on the table
        existing), so the cursor is at an effectively random point when the player finally opens the menu. Putting
        the measured bands at the front of the search plan only helps when the cursor is at zero, which it almost
        never is -- hence hot bases and per-scan band probing rather than a front-loaded plan.

        The `.msg` file is reloaded from disc on every menu open and frequently lands back at an address it has
        used before, which is the premise of the canary too. So a reopen of the same shop menu is found on the
        next poll for the cost of a few reads, with no scan and no throttle."""
        from .game_data import item_descriptions as ids

        if self.table_base is not None:
            try:
                header = read_bytes(self.table_base, ids.MSG_MAGIC_OFFSET + len(ids.MSG_MAGIC))
            except Exception:  # pragma: no cover - live-Dolphin failure path
                header = b""
            if ids.looks_like_table(header):
                return self.table_base
            # Gone or moved. Either way every edit at the old base is void, so the write cache is dropped --
            # keeping it would make the next write a no-op against a table that is vanilla again.
            self._remember_base(self.table_base)   # ADDENDUM 357: it was real here once; it may be again
            self.table_base = None
            self._written.clear()
            self._canary = None   # ADDENDUM 267: a canary for an address we no longer trust proves nothing
            self.reloads_detected += 1
            self._scan_cursor = 0
            # The table is reloaded from disc at a new address on every menu open, so this is the moment a
            # search is most worth doing and least worth delaying. Waiving the throttle for one poll takes the
            # reopen case from "up to a second before the search starts" to "next tick".
            self._last_scan_at = 0.0
            self._scan_interval = self._MIN_SECONDS_BETWEEN_SCANS

        # Free, and deliberately outside the throttle: a handful of 8-byte reads is not what the throttle is
        # for, and this is the path that makes a reopen feel instant.
        hot = self._probe_hot_bases()
        if hot is not None:
            self.hot_hits += 1
            self.table_base = hot
            self._scan_cursor = 0
            self._scan_interval = self._MIN_SECONDS_BETWEEN_SCANS
            self._remember_base(hot)
            return hot

        now = time.monotonic() if now is None else now
        if now - self._last_scan_at < self._scan_interval:
            return None
        self._last_scan_at = now

        # The likeliest 28 chunks, every scan, regardless of where the sweep is.
        found = self._probe_bands()
        if found is None:
            found = self._scan_slice()
        if found is not None:
            self.table_base = found
            self._scan_cursor = 0
            self._scan_interval = self._MIN_SECONDS_BETWEEN_SCANS
            self._remember_base(found)
        return found

    def _remember_base(self, base: int) -> None:
        """Record `base` as somewhere this table has really lived, most recent first, bounded."""
        if base in self._hot_bases:
            self._hot_bases.remove(base)
        self._hot_bases.insert(0, base)
        del self._hot_bases[self._HOT_BASES_KEPT:]

    def _probe_hot_bases(self) -> "int | None":
        """Any remembered address that holds the table right now, or None. One 8-byte read each; a failed read
        is not an error, the address simply is not it today."""
        from .game_data import item_descriptions as ids

        length = ids.MSG_MAGIC_OFFSET + len(ids.MSG_MAGIC)
        for base in list(self._hot_bases):
            try:
                if ids.looks_like_table(read_bytes(base, length)):
                    return base
            except Exception:  # pragma: no cover - live-Dolphin failure path
                continue
        return None

    def _band_plan(self) -> "list[tuple[int, int]]":
        """The two MEASURED bands: 28 chunks holding all 18 corpus observations. Walked in full every scan."""
        from .game_data import item_descriptions as ids

        return [
            (ids.MEASURED_BAND_LOW_START, ids.MEASURED_BAND_LOW_END),
            (ids.MEASURED_BAND_HIGH_START, ids.MEASURED_BAND_HIGH_END),
        ]

    def _sweep_plan(self) -> "list[tuple[int, int]]":
        """Everything the bands do not cover, likeliest first -- the resumable half.

        An ORDERING, never a bound: eighteen observations do not fence a moving allocation, so a miss in the
        bands falls through to the rest of MEM1 rather than concluding the table is not loaded."""
        from .game_data import item_descriptions as ids

        return [
            (ids.LIKELY_BASE_LOW, ids.MEASURED_BAND_LOW_START),
            (ids.MEASURED_BAND_LOW_END, ids.MEASURED_BAND_HIGH_START),
            (ids.MEASURED_BAND_HIGH_END, ids.LIKELY_BASE_HIGH),
            (ids.MEM1_START, ids.LIKELY_BASE_LOW),
            (ids.LIKELY_BASE_HIGH, ids.MEM1_END),
        ]

    def _search_plan(self) -> "list[tuple[int, int]]":
        """The whole ordering, bands first, as one list -- and the statement that it tiles MEM1 with no gap and
        no overlap. The two halves are walked separately, at different rates."""
        return self._band_plan() + self._sweep_plan()

    def _chunk_step(self) -> int:
        """Chunks OVERLAP by the magic's own length, so a magic straddling a boundary is still found; without it
        the search would miss the table roughly one time in sixteen thousand."""
        from .game_data import item_descriptions as ids

        return max(1, self._CHUNK - (ids.MSG_MAGIC_OFFSET + len(ids.MSG_MAGIC)))

    def _read_window(self, low: int, high: int) -> "int | None":
        """Walk one address window in full. None means "not in here", and a read failure disables."""
        from .game_data import item_descriptions as ids

        step = self._chunk_step()
        address = low
        while address < high:
            try:
                chunk = read_bytes(address, min(self._CHUNK, high - address))
            except Exception:  # pragma: no cover - live-Dolphin failure path
                # ADDENDUM 389: a failed read is NOT evidence this feature cannot work, and it used to
                # disable descriptions for the whole session. `_canary_still_ours` already reasons this way
                # ("a failed read is not evidence the table was reset"); the search did the opposite, so one
                # unlucky read while a menu closed mid-sweep turned every later shop generic.
                self.read_failures += 1
                self.last_error = "MEM1 read failed during description table search"
                return None
            found = ids.search_chunk_for_base(chunk, address)
            if found is not None:
                return found
            address += step
        return None

    def _probe_bands(self) -> "int | None":
        for low, high in self._band_plan():
            found = self._read_window(low, high)
            if found is not None:
                return found
            if not self.enabled:
                return None
        return None

    def _scan_slice(self) -> "int | None":
        """Search the next `_CHUNKS_PER_POLL` chunks of the SWEEP, continuing where the last poll stopped.

        The measured bands are not in here -- they are probed in full on every scan, so this cursor's position
        cannot decide how long the common case takes."""
        from .game_data import item_descriptions as ids

        step = self._chunk_step()
        plan = self._sweep_plan()
        total = sum(max(1, -(-(high - low) // step)) for low, high in plan)
        if self._scan_cursor == 0:
            self.scans += 1

        done = 0
        while done < self._CHUNKS_PER_POLL:
            if self._scan_cursor >= total:
                # A full pass found nothing, so the table is not resident (the usual case -- the menu is shut).
                # Stop reading megabytes a second to keep proving it.
                self.failed_scans += 1
                self._scan_cursor = 0
                self._scan_interval = self._IDLE_SECONDS_BETWEEN_SCANS
                return None
            index = self._scan_cursor
            address = None
            for low, high in plan:
                chunks = max(1, -(-(high - low) // step))
                if index < chunks:
                    address = low + index * step
                    limit = high
                    break
                index -= chunks
            if address is None:  # pragma: no cover - unreachable while total matches the plan
                self._scan_cursor = 0
                return None
            size = min(self._CHUNK, limit - address)
            try:
                chunk = read_bytes(address, size)
            except Exception:  # pragma: no cover - live-Dolphin failure path
                # ADDENDUM 389, same reasoning as `_read_window`: count it and come back next poll. The
                # cursor has already advanced past the bad chunk below, so a permanently unreadable address
                # costs one chunk per sweep rather than the feature.
                self.read_failures += 1
                self.last_error = "MEM1 read failed during description table search"
                self._scan_cursor += 1
                return None
            self._scan_cursor += 1
            done += 1
            found = ids.search_chunk_for_base(chunk, address)
            if found is not None:
                return found
        return None

    def desired_lines(
        self,
        room_id: "int | None",
        berry_ids: "list[int]",
        scouted: "dict[str, tuple[str, str | None]]",
        purchased: "set[int]",
    ) -> "dict[int, list[str]]":
        """What each berry's description should say right now. Pure -- no reads, no writes.

        The numbering is `ItemNameRenamer`'s and `ShopPurchaseTracker`'s, not a third one: berry index k+1 is
        shelf line k+1 is `<Shop> AP Item k+1`. That is what makes naming a specific AP item here honest --
        before per-shop-line berries, which check a line sent depended on the order the player bought in."""
        from .game_data import item_descriptions as ids
        from .game_data import shops

        if room_id is None or not is_shop_room(room_id):
            return {}
        shop = shops.shop_for_room(room_id)
        if shop is None:
            return {}
        out: "dict[int, list[str]]" = {}
        for item_id in berry_ids:
            budget = ids.budget_bytes(item_id)
            if budget is None:
                continue
            try:
                line = USELESS_BERRY_IDS.index(item_id) + 1
            except ValueError:
                continue
            if line > shop.slot_count:
                continue   # names no line of this shop -- leave its vanilla description alone
            # The two fallback constants go through the budget too. Measured raw they overrun every shop berry's
            # entry -- UNKNOWN_DESCRIPTION_LINES is 104 bytes and NO_CHECK_DESCRIPTION_LINES 92, against a
            # SHOP_BERRY_DESCRIPTION_BUDGET of 88 -- and `encode_lines` returns None over budget while `_write`
            # treats None as "skip, leave `_written` alone", so the entry silently kept whatever was there.
            if item_id in purchased:
                out[item_id] = ids.fit_lines(list(ids.NO_CHECK_DESCRIPTION_LINES), budget)
                continue
            entry = scouted.get(shops.shop_location_name(shop.name, line))
            if entry is None:
                out[item_id] = ids.fit_lines(list(ids.UNKNOWN_DESCRIPTION_LINES), budget)
                continue
            item_name, player_name = entry
            out[item_id] = ids.describe_ap_item(item_name, player_name, budget)
        return out

    def poll(
        self,
        room_id: "int | None",
        scouted: "dict[str, tuple[str, str | None]]",
        purchased: "set[int]",
        berry_ids: "list[int]" = USELESS_BERRY_IDS,
    ) -> int:
        """One tick. Returns how many entries were written (usually zero)."""
        if not self.enabled or room_id is None or not is_shop_room(room_id):
            return 0
        desired = self.desired_lines(room_id, berry_ids, scouted, purchased)
        if not desired:
            return 0
        base = self.locate()
        if base is None:
            return 0
        return self._write(base, desired)

    def _canary_still_ours(self, base: int) -> bool:
        """Is the ONE entry we last wrote still holding what we wrote?

        `locate()` detects the table MOVING, but not the table being RELOADED IN PLACE, which is the common case:
        the `.msg` file is read from disc every menu open and frequently lands back at the same address. The magic
        still checks out, `_written` still claims every entry holds our text, `_write` skips all of them, and the
        shelf shows vanilla descriptions for the rest of the session.

        One canary is enough -- a reload resets the whole file at once -- where reading back all ~26 entries
        every poll would be real traffic for a cosmetic."""
        from .game_data import item_descriptions as ids

        if self._canary is None:
            return True
        item_id, expected = self._canary
        offset = ids.entry_offset(item_id)
        if offset is None:
            return True
        try:
            return read_bytes(base + offset, len(expected)) == expected
        except Exception:  # pragma: no cover - live-Dolphin failure path
            # A failed read is not evidence the table was reset. "Still ours" skips a rewrite this poll and asks
            # again next poll; "reset" would rewrite all 26 entries on every failed read.
            return True

    def _write(self, base: int, desired: "dict[int, list[str]]") -> int:
        from .game_data import item_descriptions as ids

        # Before trusting the cache, check the table has not been reloaded under it.
        if not self._canary_still_ours(base):
            self._written.clear()
            self.reloads_detected += 1

        written = 0
        for item_id, lines in desired.items():
            key = (base, tuple(lines))
            if self._written.get(item_id) == key:
                continue
            offset = ids.entry_offset(item_id)
            budget = ids.budget_bytes(item_id)
            if offset is None or budget is None:
                continue
            payload = ids.encode_lines(lines, budget)
            if payload is None:
                # Unreachable for text `wrap_description` produced -- it budgets in bytes precisely so this
                # cannot happen -- but an oversized payload is SKIPPED rather than truncated. A truncation here
                # is the one that runs past the entry, which put AP text over the cancel button the first time.
                continue
            try:
                write_bytes(base + offset, payload)
            except Exception as exc:  # pragma: no cover - live-Dolphin failure path
                self.enabled = False
                self.last_error = str(exc)
                return written
            self._written[item_id] = key
            # Remember one entry's exact bytes so the next poll can tell a reload-in-place from a table that
            # still holds our text. Any entry will do, since a reload resets the whole file.
            self._canary = (item_id, payload)
            written += 1
            self.writes += 1
        return written


def get_owned_species_snapshot(
    block_base: int,
    party_base: int = PARTY_BASE,
    box_slots_to_check: list[int] | None = None,
) -> set[int]:
    """The confirmed-safe party read, plus an OPTIONAL explicit list of box slot indices to best-effort check.

    Deliberately not "all 386 slots" by default -- see `read_box_slot_species`'s caveat; the default
    box_slots_to_check=None skips box reading entirely. Returns the National Dex #s observed across whichever
    sources were checked.

    Party species come from each member's `national_dex` property (the raw field resolved through the live-index
    conversion). Falls back to name-based `reliable_species` only when the raw value will not resolve at all --
    defensive, not preferred."""
    owned: set[int] = set()
    for member in read_party_members(party_base):
        dex_number = member.national_dex
        if dex_number is None:
            dex_number = member.reliable_species
        if dex_number is not None:
            owned.add(dex_number)

    if box_slots_to_check:
        for slot_index in box_slots_to_check:
            # By NAME rather than the raw numeric field, whose own docstring flags it unreliable for a slot
            # recently deposited into -- the single most important case here, since a catch with a full party is
            # auto-routed straight to the PC and never touches the party struct.
            dex_number = read_box_slot_species_by_name(block_base, slot_index)
            if dex_number is None:
                dex_number = read_box_slot_species(block_base, slot_index)
            if dex_number is not None:
                owned.add(dex_number)
    return owned


@dataclass
class SpeciesTracker:
    """Reports each newly-seen owned species exactly once, as `SPECIES_LOCATION_TO_DEX` location names.

    Sends nothing itself -- `poll()` returns the names that just became justified and the caller decides."""

    seen_dex_numbers: set[int] = None  # type: ignore[assignment]  # set to a fresh set() in __post_init__

    def __post_init__(self) -> None:
        if self.seen_dex_numbers is None:
            self.seen_dex_numbers = set()

    def poll(
        self,
        block_base: int,
        party_base: int = PARTY_BASE,
        box_slots_to_check: list[int] | None = None,
    ) -> list[str]:
        """Snapshots, diffs against everything seen before, and returns the `"Catch - {species}"` names for
        whatever is newly seen. Each species is reported once per tracker instance however often it reappears."""
        location_name_for_species = _load_location_name_for_species()
        current = get_owned_species_snapshot(block_base, party_base, box_slots_to_check)
        newly_seen = current - self.seen_dex_numbers
        self.seen_dex_numbers |= newly_seen
        return [location_name_for_species(dex_number) for dex_number in sorted(newly_seen)]


def _load_location_name_for_species():
    """Returns `location_name_for_species` from pokemon_xd/species.py.

    `__package__` decides how. Loaded as part of the real apworld package -- which is how this is ever reached in a
    real session -- a plain relative import is correct and zip-safe. Always loading species.py by raw file path to
    avoid triggering `pokemon_xd/__init__.py` assumed `Path(__file__)` names a real file on disk; inside an installed
    `.apworld` zip it does not, and `SourceFileLoader.get_data()` raised FileNotFoundError in a player's client. (The
    avoidance saves nothing there anyway: Python imports a submodule's parent package first regardless.)

    The raw-path loader remains only for standalone execution, where `__package__` is empty and `__file__` really is
    an on-disk path.
    """
    if __package__:
        from . import species
        return species.location_name_for_species

    import importlib.util
    from pathlib import Path

    # species.py is ram_client.py's sibling inside pokemon_xd/, not a child of a further "pokemon_xd" subfolder.
    species_path = Path(__file__).resolve().parent / "species.py"
    spec = importlib.util.spec_from_file_location("_pokemon_xd_species_standalone", species_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.location_name_for_species


def _load_xd_species_index():
    """Returns the `tools/xd_species_index` module. Same `__package__`-gated rule as
    `_load_location_name_for_species`, and this is the function whose raw-file-path loader actually raised
    FileNotFoundError inside a player's installed `.apworld` zip."""
    if __package__:
        from .tools import xd_species_index
        return xd_species_index

    import importlib.util
    from pathlib import Path

    index_path = Path(__file__).resolve().parent / "tools" / "xd_species_index.py"
    spec = importlib.util.spec_from_file_location("_pokemon_xd_species_index_standalone", index_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- Battle roster detection. ---
# An opposing trainer's own battle roster, found by byte-signature scan. Discovered via a live trainer battle
# (Chaser Laken, level 6 Metagross + Wailmer) bracketed with three memory dumps; see pokemon-xd-ram-map.md's
# "battle roster struct" section. Used for "Defeat - {trainer}" / "Defeat N Trainers" detection.
#
# One record per opponent Pokemon currently in the battle, offsets from the signature's own start:
#   +0x00  4 bytes  `80 83 30 b8` -- a shared class/vtable pointer, identical in every record seen; part of the
#          signature only.
#   +0x04  4 bytes  `0b 03 02 02` -- record-kind marker, also identical everywhere.
#   +0x08  0x16 bytes (11 UTF-16BE chars)  the opposing TRAINER's surname only, no class or title ("LAKEN" for
#          "Chaser Laken"), which matches shadow_pokemon_list.json's `"trainer"` field on its last word. This is
#          what TrainerBattleDefeatTracker keys on.
#   +0x1e  0x16 bytes  the Pokemon's species name.
#   +0x34  0x16 bytes  the same species name again -- the same name-duplication-one-field-later convention as
#          PARTY_RECAP_OFFSET, almost certainly the engine's general record-writing habit.
#   -0x2c  u16BE  the Pokemon's CURRENT HP. Confirmed for Metagross and Wailmer across a full battle: both read
#          exactly 0 immediately after fainting.
#
# No stable anchor or pointer chain to this struct was found despite scanning ~16MB for word-aligned pointers
# targeting it, so it is relocated by signature scan every time.
#
# MULTIPLE COPIES EXIST AND ONLY ONE TRACKS LIVE HP. Two hits for one Pokemon ~0x900 bytes apart: one stayed pinned
# at MaxHP for the whole battle, the other tracked damage to 0. So take the MINIMUM current HP across every record
# sharing a species text in one scan -- a stale copy can only overstate HP, never understate it.
#
# STALE RECORDS FROM EARLIER BATTLES THIS BOOT ARE NOT CLEARED and still match the signature: a 10MB dump held 22
# hits of which only 4 were the live battle, the rest leftovers (Chobin, Aferd, Zook) in an evenly-strided cluster
# around 0x80a39000-0x80a63000. Hence TrainerBattleDefeatTracker requires an observed HP-drop transition.

BATTLE_ROSTER_SIGNATURE = bytes.fromhex("808330b80b030202")  # `80 83 30 b8` (shared pointer) + `0b 03 02 02`
                                                              # (record marker) -- see section docstring above.

# Scans the ENTIRE 24MB of MEM1 every poll tick rather than a bounded window: three boots put the roster at three
# widely separated addresses (0x80a396e4, 0x80831e54, and a third outside even a 10 MiB window), so this is an
# unbounded problem. Safe as a single un-chunked read_bytes(), because dump_mem1()'s "~seconds" cost is its 384
# separate 64KB dme calls and not the data volume. Gated behind shuffle_trainer_defeats. Not independently timed
# against the 1-second poll budget; if it proves too slow, the fallback is a one-time-per-battle scan with the
# address cached, not another fixed window.
#
# A single read over this range CAN raise RuntimeError from dolphin_memory_engine -- seen once in the lower part of
# MEM1, then succeeding moments later, so transient. Deliberately not caught here: Client.py's
# check_trainer_defeats catches it, because letting it propagate would look like a lost Dolphin connection.
BATTLE_ROSTER_SCAN_BASE = MEM1_START
BATTLE_ROSTER_SCAN_SIZE = MEM1_SIZE  # 24 MiB -- the entire MEM1 address space, see comment above

BATTLE_ROSTER_TRAINER_NAME_OFFSET = 0x08     # from the signature's own start (the `80 83 30 b8` word)
BATTLE_ROSTER_NAME_FIELD_WIDTH = 0x16        # 22 bytes -- matches PARTY_RECAP_OFFSET's own name-dup stride
BATTLE_ROSTER_SPECIES_NAME_OFFSET_1 = BATTLE_ROSTER_TRAINER_NAME_OFFSET + BATTLE_ROSTER_NAME_FIELD_WIDTH  # 0x1e
BATTLE_ROSTER_SPECIES_NAME_OFFSET_2 = BATTLE_ROSTER_SPECIES_NAME_OFFSET_1 + BATTLE_ROSTER_NAME_FIELD_WIDTH  # 0x34
BATTLE_ROSTER_CURRENT_HP_OFFSET = -0x2C      # relative to the signature's own start (`sig - 0x2c` == the
                                              # `0b 03 02 02` marker at `sig + 0x04`, minus 0x30)
BATTLE_ROSTER_NAME_MAX_CHARS = BATTLE_ROSTER_NAME_FIELD_WIDTH // 2  # 11 -- field width is in bytes, UTF-16BE
                                                                     # is 2 bytes/char


def _read_utf16be_field(data: bytes, offset: int, max_chars: int = BATTLE_ROSTER_NAME_MAX_CHARS) -> str:
    """Decodes a fixed-width, null-terminated UTF-16BE field out of an already-read buffer -- `offset` is
    relative to `data`'s start, not a live address. Battle-roster records are read as one big buffer for speed."""
    raw = data[offset:offset + max_chars * 2]
    return raw.decode("utf-16-be", errors="replace").split("\x00")[0]


# The level axis of a team fingerprint ships but is DORMANT: no level field has been located in the roster
# record. `describe_battle_roster_bytes` exists to find one -- a byte that equals the Pokemon's level in several
# records across two different battles is the candidate, and it should be forward-tested on a fresh boot before
# being believed.
BATTLE_ROSTER_DUMP_BEFORE = 0x40
BATTLE_ROSTER_DUMP_AFTER = 0x40


def describe_battle_roster_bytes(limit: int = 4) -> "list[str]":
    """Human-readable hex around each live battle-roster record, for locating fields not yet decoded. Read-only
    and bounded; never raises."""
    lines: list[str] = []
    try:
        records = scan_battle_roster()
    except Exception as error:
        return [f"Could not scan the battle roster: {error}"]
    if not records:
        return ["No battle-roster records found -- run this during a battle."]
    for record in records[:limit]:
        start = record.address - BATTLE_ROSTER_DUMP_BEFORE
        length = BATTLE_ROSTER_DUMP_BEFORE + BATTLE_ROSTER_DUMP_AFTER
        try:
            raw = read_bytes(start, length)
        except Exception as error:
            lines.append(f"{record.trainer_name}/{record.species_name}: unreadable ({error})")
            continue
        lines.append(
            f"{record.trainer_name} / {record.species_name} @ {record.address:#010x} "
            f"(current HP {record.current_hp})"
        )
        for row in range(0, length, 16):
            offset = -BATTLE_ROSTER_DUMP_BEFORE + row
            chunk = raw[row:row + 16]
            lines.append(f"   {offset:+#06x}  {chunk.hex(' ')}")
    return lines


@dataclass
class BattleRosterRecord:
    """One decoded battle-roster record; see the section comment above for the byte layout. Its sole consumer,
    TrainerBattleDefeatTracker, keys on `trainer_name` (the surname). `species_dex` was used by the removed
    species-keyed ShadowDefeatTracker."""

    address: int
    trainer_name: str
    species_name: str
    current_hp: int

    @property
    def species_dex(self) -> int | None:
        """National Dex # for this record's species, via SPECIES_NAME_TO_DEX. None for a record whose species
        field did not decode -- the expected outcome for the coincidental signature hits a full-MEM1 scan turns
        up, which callers skip rather than treat as an error."""
        return species_dex_from_name(self.species_name)


# Roster records are grouped by ADDRESS PROXIMITY, not by surname. A post-battle dump held twelve records
# carrying the surname LOVRINA in three separate places:
#
#   0x804a87c0 SCEPTILE 72 | 0x804a8884 KINGDRA 72 | 0x804a8948 XATU 67 | 0x804a8a0c KOFFING 55
#   0x804a8ad0 CUBONE  60   <- a stale pre-battle copy, still at full HP
#   0x804a9048 KOFFING  0 | 0x804a9348 CUBONE 0 | 0x804a9648 SCEPTILE 0 | 0x804a9c48 XATU 0
#   0x804a9f48 KINGDRA  0   <- the real post-battle copy, her whole team at zero
#   0x804af5c8 LOMBRE  53   <- a stray, 0x5680 from either copy
#   0x80831e54 KOFFING 55   <- another stray, in a different region entirely
#
# The min-across-duplicates rule handled the stale copy fine. LOMBRE killed it: a stray with a species not even
# on the team it files under and no zeroed twin anywhere, so "every slot confirmed zero" could never be true and
# Lovrina was uncountable however long the player waited. Same shape for BARDO (HP [0, 34, 36, 39, 41, 42]), so
# not a one-off. A real roster is CONTIGUOUS -- strides of 0xC4 and 0x300 -- while strays are thousands of bytes
# away, so the battle is judged on the largest such run.

BATTLE_ROSTER_CLUSTER_MAX_GAP = 0x1000
"""Two roster records more than this far apart belong to different clusters. Comfortably above the largest
stride seen inside one real battle's records (0x600) and far below the distance to either observed stray
(0x5680 and ~0x389000)."""


def dominant_roster_cluster(
    records: "list[BattleRosterRecord]",
    max_gap: int = BATTLE_ROSTER_CLUSTER_MAX_GAP,
) -> "list[BattleRosterRecord]":
    """The largest run of `records` whose addresses are each within `max_gap` of their neighbour -- the one real
    roster, with strays dropped. Ties break toward the LOWEST address, so this never depends on scan order."""
    if not records:
        return []
    ordered = sorted(records, key=lambda r: r.address)
    clusters: list[list[BattleRosterRecord]] = [[ordered[0]]]
    for record in ordered[1:]:
        if record.address - clusters[-1][-1].address <= max_gap:
            clusters[-1].append(record)
        else:
            clusters.append([record])
    best = max(clusters, key=lambda c: (len(c), -c[0].address))
    return best


def scan_battle_roster(
    scan_base: int = BATTLE_ROSTER_SCAN_BASE,
    scan_size: int = BATTLE_ROSTER_SCAN_SIZE,
) -> list[BattleRosterRecord]:
    """Full-MEM1 read plus signature scan, decoding every match into a BattleRosterRecord -- including matches
    that are not real records, which callers filter via `.species_dex is not None`.

    One un-chunked read_bytes() per poll tick, and not free: gate it behind `shuffle_trainer_defeats`, since
    there is nothing to detect otherwise. Client.py's `check_trainer_defeats` is the sole caller."""
    data = read_bytes(scan_base, scan_size)
    records: list[BattleRosterRecord] = []
    idx = data.find(BATTLE_ROSTER_SIGNATURE)
    while idx != -1:
        hp_offset = idx + BATTLE_ROSTER_CURRENT_HP_OFFSET
        if 0 <= hp_offset <= len(data) - 2:
            trainer_name = _read_utf16be_field(data, idx + BATTLE_ROSTER_TRAINER_NAME_OFFSET)
            species_name = _read_utf16be_field(data, idx + BATTLE_ROSTER_SPECIES_NAME_OFFSET_1)
            current_hp = struct.unpack_from(">H", data, hp_offset)[0]
            records.append(BattleRosterRecord(scan_base + idx, trainer_name, species_name, current_hp))
        idx = data.find(BATTLE_ROSTER_SIGNATURE, idx + 1)
    return records


@dataclass
class TrainerBattleDefeatTracker:
    """The sole battle-roster HP tracker. Two outputs per poll: a named "Defeat - {trainer}" location for the ~66
    trainers with a real display name and story placement (`trainer_defeat.SURNAME_TO_LOCATION_QUEUE`), and one more
    count toward the cumulative "Defeat N Trainers" bucket, which fires for every detected defeat named or not --
    that is how the other ~166 trainers with no decoded name text get coverage.

    Keyed by trainer SURNAME, not species: two Peons can both run a Zubat, and surname is the only trainer identity
    the roster exposes. "Defeated" means every currently-visible record sharing that surname reads HP 0, and a slot
    counts as dead only off an observed poll-over-poll drop to 0 confirmed on a second poll -- a slot whose first
    sighting already reads 0 is baselined and never counted, so a stale leftover cannot masquerade as a kill. Slots
    dedupe by (surname, species_name) taking the MIN HP, so a team with two Pokemon of one species collapses into one
    slot and can under-count how many are still alive.

    It trusts that the roster exposes a trainer's ENTIRE team at once, confirmed only for a 2-Pokemon team (Chaser
    Laken: Metagross + Wailmer, both visible before Metagross was sent out). If it only exposes active/on-deck
    Pokemon this would fire early rather than never.

    Re-arms per surname once the roster clears, so a rematch is detectable. A repeat surname then dispatches on
    distinct TEAMS, not on wins: each win reduces to an identity via `_team_identity`, and the Nth new identity checks
    off queue entry N-1, so beating one colosseum rematch three times yields one check. A win past the end of a queue
    still counts toward the cumulative bucket.

    `last_confirmed_surnames` and `defeat_count` are public so Client.py's Goal auto-detection can react by surname
    and by running total without its own scan.
    """

    _min_hp_seen: dict[tuple[str, str], int] = field(default_factory=dict)
    _baselined: set[tuple[str, str]] = field(default_factory=set)
    _pending_zero: set[tuple[str, str]] = field(default_factory=set)
    _fired: set[tuple[str, str]] = field(default_factory=set)
    _awaiting_clear: set[str] = field(default_factory=set)
    _surname_queue_position: dict[str, int] = field(default_factory=dict)
    # A RECORD rather than a decision: which of each surname's queue entries have been dispatched. Under
    # unique-team counting the Nth distinct team always takes queue[N-1], so this set is by construction
    # {0 .. N-1} and nothing reads it to choose anything. Kept because the defeat report prints it, and because a
    # set that is always contiguous is a cheap fence on that claim.
    _claimed_queue_indices: dict[str, set[int]] = field(default_factory=dict)
    # Per surname, the identity of every distinct team already beaten, in the order beaten. A list, not a set,
    # because its LENGTH is the dispatch position and its order is what `to_json` round-trips.
    _beaten_team_ids: "dict[str, list[str]]" = field(default_factory=dict)
    # ADDENDUM 157: (surname, species) -> the highest HP ever observed for that slot, i.e. its MaxHP.
    _max_hp_seen: dict[tuple[str, str], int] = field(default_factory=dict)
    fingerprint_matches: int = 0
    # Wins thrown away because the team had already been beaten. Reported by `!teams`, and the first number to
    # look at if a player says a defeat check did not fire.
    rematches_ignored: int = 0
    _defeat_count: int = 0

    # Consecutive polls a baselined-but-unresolved key has gone with NO observed HP movement. Reset on a fresh
    # baseline, a genuine drop, or a pending-zero confirmation. This is what stops `has_unresolved_battle()` sticking
    # True for the rest of a boot: a battle that ends WITHOUT the enemy team reaching 0 -- a loss or blackout --
    # leaves a stale record frozen at nonzero HP, and stale roster records are never cleared from memory, so the
    # vanish-based purge never fires for them. The symptom was items always taking the full delivery ceiling.
    _polls_without_progress: dict[tuple[str, str], int] = field(default_factory=dict)
    # 30s rather than 60: generous enough to survive a player deliberating at the move-select menu in a real fight,
    # while bounding a genuinely stuck record to under a minute. This window is the tracker healing ITSELF from a
    # stale record; ITEM_DELIVERY_MAX_BATTLE_WAIT_SECONDS is the caller giving up on the tracker's answer entirely,
    # and must stay comfortably longer.
    STALE_NO_PROGRESS_POLLS: ClassVar[int] = 30  # ~30 real seconds, at the tracker's 1s poll cadence

    # The surname of every trainer newly confirmed-defeated on the MOST RECENT poll, in confirmation order;
    # cleared and rebuilt each poll, never accumulated. Public because Mt. Battle goal detection needs to know
    # WHICH surname was confirmed, and `poll()`'s return value only carries location names, which loses that
    # identity for the ~166 trainers with no named location.
    last_confirmed_surnames: list[str] = field(default_factory=list)
    # {surname: stray records dropped as out-of-cluster on the last poll}. Diagnostic only, surfaced by
    # !trainers so a future miss of this shape is recognisable on sight.
    last_strays_dropped: dict[str, int] = field(default_factory=dict)

    @property
    def defeat_count(self) -> int:
        """The running cumulative confirmed-defeat count, so Client.py's goal detection need not reach into a
        private field."""
        return self._defeat_count


    def poll(
        self,
        surname_to_location_queue: dict[str, list[str | None]],
        count_location_name: Callable[[int], str],
        records: list[BattleRosterRecord] | None = None,
        count_location_max: int | None = None,
        exclude_surnames: "frozenset[str] | set[str]" = frozenset(),
        team_fingerprints: "dict[str, list[str]] | None" = None,
    ) -> list[str]:
        """`records`: pass an already-scanned `scan_battle_roster()` result to reuse it. Omit it and this calls
        `scan_battle_roster()` itself, for a standalone caller or a test.

        `count_location_max` caps how high a cumulative "Defeat N Trainers" name this will hand back, matching
        `options.TrainerDefeatCheckCount`'s per-seed trim of that category: a seed that only created up to
        "Defeat 50 Trainers" must never be asked to check 51. None means uncapped. `self._defeat_count` still
        increments past the cap -- it is this tracker's own total -- and the named per-surname dispatch is
        unaffected either way.

        A surname's queue may contain `None` entries (`trainer_defeat.GREEVIL_DECOY_BATTLE_SENTINEL`). A `None`
        still consumes a queue position on a confirmed kill, so the queue advances rather than sticking, but is
        never returned in `completed`, so it can never become a location check or reach goal detection. The
        cumulative count and `last_confirmed_surnames` are unaffected."""
        self.last_confirmed_surnames = []
        # Match surnames CASE-INSENSITIVELY. The roster reports NPC names upper case ("LOVRINA", "BARDO") while
        # `trainer_defeat.SURNAME_TO_LOCATION_QUEUE` is keyed title case, so every key missed and the named
        # "Defeat - {trainer}" locations had never fired -- only the cumulative counter did. It also broke Greevil
        # goal detection, which dispatches through this same queue.
        queue_by_upper = {key.upper(): value for key, value in surname_to_location_queue.items()}
        if records is None:
            records = scan_battle_roster()
        # ADDENDUM 135: group by surname, then keep only that surname's LARGEST CONTIGUOUS run of records --
        # the one real battle roster. A single far-flung stray used to gate the whole trainer off ever being
        # counted; see dominant_roster_cluster's own comment for the live Lovrina evidence.
        records_by_surname: dict[str, list[BattleRosterRecord]] = {}
        for record in records:
            if record.species_dex is None:
                continue  # not a real record -- see BattleRosterRecord.species_dex's own docstring
            surname = record.trainer_name.strip()
            if not surname or surname in exclude_surnames:
                continue
            records_by_surname.setdefault(surname, []).append(record)

        by_surname: dict[str, dict[str, list[int]]] = {}
        self.last_strays_dropped = {}
        for surname, surname_records in records_by_surname.items():
            cluster = dominant_roster_cluster(surname_records)
            if len(cluster) != len(surname_records):
                self.last_strays_dropped[surname] = len(surname_records) - len(cluster)
            for record in cluster:
                by_surname.setdefault(surname, {}).setdefault(record.species_name, []).append(record.current_hp)

        # When a surname's roster presence vanishes entirely between polls -- for ANY reason, not just the
        # confirmed-win path -- purge every per-slot key for it. Stranded keys caused two bugs: a battle that ended
        # without every slot reaching a confirmed 0 never adds the surname to `_awaiting_clear` and never fires its
        # keys, so they stayed baselined forever and `has_unresolved_battle()` read "still fighting" permanently,
        # blocking `give_items()` for the session; and a rematch reusing the same species hit a stale
        # `key in self._fired` and credited an instant kill. `_surname_queue_position` and `_defeat_count` are left
        # alone -- those are session counters, not per-battle state.
        tracked_surnames = {surname for surname, _species in self._baselined} | self._awaiting_clear
        for vanished_surname in tracked_surnames - set(by_surname.keys()):
            self._baselined = {k for k in self._baselined if k[0] != vanished_surname}
            self._min_hp_seen = {k: v for k, v in self._min_hp_seen.items() if k[0] != vanished_surname}
            self._pending_zero = {k for k in self._pending_zero if k[0] != vanished_surname}
            self._fired = {k for k in self._fired if k[0] != vanished_surname}
            # Hygiene only -- a purely stale key is separately excluded by has_unresolved_battle() -- so this
            # dict does not grow forever across a long session.
            self._polls_without_progress = {
                k: v for k, v in self._polls_without_progress.items() if k[0] != vanished_surname
            }
            # `_max_hp_seen` is per-BATTLE-INSTANCE evidence, not a session counter: "highest HP ever seen is
            # MaxHP" holds only within one fight. Carried across battles it self-corrects for an ascending series but
            # not for a REMATCH OF AN EARLIER encounter -- Miror B. at a colosseum exactly, whose level-50 figures
            # would be scored against the level-30 team actually on the field.
            self._max_hp_seen = {
                k: v for k, v in self._max_hp_seen.items() if k[0] != vanished_surname
            }
        # A surname parked in _awaiting_clear whose records have fully disappeared this poll is ready to
        # re-arm for a future rematch (see class docstring).
        self._awaiting_clear &= set(by_surname.keys())

        completed: list[str] = []
        for surname, species_groups in by_surname.items():
            if surname in self._awaiting_clear:
                continue  # already counted this battle instance; waiting for the roster to clear
            slot_keys = [(surname, species_name) for species_name in species_groups]
            # The highest HP ever seen for a slot IS its MaxHP: a Pokemon starts a fight at full HP, and a stale
            # roster copy stays pinned at MaxHP for the whole battle (which is why `min()` does the kill check).
            # So the max across copies is free MaxHP with no new RAM field to find -- a better identity axis than
            # level, which has never been located.
            for species_name, hp_values in species_groups.items():
                key = (surname, species_name)
                self._max_hp_seen[key] = max(self._max_hp_seen.get(key, 0), max(hp_values))
            all_confirmed_zero = True
            any_fresh_baseline = False
            for key in slot_keys:
                min_hp = min(by_surname[surname][key[1]])
                if key not in self._baselined:
                    # First-ever sighting of this slot: baseline only, never a same-poll confirmation, and never
                    # fire off a bare baseline-0 -- a stale leftover reading 0 the first time must not look like a
                    # fresh kill. Gates the whole surname off firing this poll regardless of the other slots.
                    self._baselined.add(key)
                    self._min_hp_seen[key] = min_hp
                    self._polls_without_progress[key] = 0  # ADDENDUM 100
                    if min_hp != 0:
                        all_confirmed_zero = False
                    any_fresh_baseline = True
                    continue
                if min_hp < self._min_hp_seen[key]:
                    # A genuine, live, poll-over-poll DROP -- never a same-poll fire, even if it lands on 0.
                    self._min_hp_seen[key] = min_hp
                    self._polls_without_progress[key] = 0  # ADDENDUM 100 -- real movement, reset staleness
                    if min_hp == 0:
                        self._pending_zero.add(key)
                    all_confirmed_zero = False
                    continue
                if key in self._fired:
                    # Confirmed on an earlier poll and still reads unchanged -- counts toward confirmed-zero.
                    continue
                if min_hp == 0 and key in self._pending_zero:
                    # Confirmed on a SECOND poll still reading 0 -- counts toward confirmed-zero.
                    self._pending_zero.discard(key)
                    self._fired.add(key)
                    self._polls_without_progress[key] = 0  # ADDENDUM 100 -- real, if final, confirmation
                    continue
                # Baselined, not fired, not a drop, not a pending-zero confirmation: this key sat unchanged this
                # poll. Only meaningful while the key is still unresolved -- see has_unresolved_battle()'s
                # staleness exclusion.
                self._polls_without_progress[key] = self._polls_without_progress.get(key, 0) + 1
                all_confirmed_zero = False
            if any_fresh_baseline or not all_confirmed_zero or not slot_keys:
                continue

            # Every slot this surname currently has in the roster is a confirmed (not just baselined-0) kill.
            self._awaiting_clear.add(surname)
            # Appended for EVERY confirmed win, rematch or not: the "Defeat X (Any)" checks and goal detection
            # both ask "was this trainer beaten", which a rematch answers just as well. Only counting is
            # team-gated.
            self.last_confirmed_surnames.append(surname)

            # The Nth check needs an Nth TEAM, not an Nth win. A queue entry per win is defensible for a trainer met
            # once per story beat and wrong for one you can re-fight on demand: beating Miror B.'s first team three
            # times at a colosseum checked off #1, #2 and #3 without the player seeing the later encounters.
            #
            # Identity first, dispatch second. The fingerprinter answers "which of this trainer's teams was that",
            # across the WHOLE queue including teams already beaten -- a question with a stable answer, unlike "which
            # unclaimed slot should this win take". Dispatch is then pure counting, so `Defeat - Miror B. #3` means
            # "the third distinct team you beat" and the fingerprint only has to tell SAME from DIFFERENT, which
            # makes an ambiguous read cost a mislabelled check rather than a stranded one.
            observed = {name.upper() for name in species_groups}
            # No level field has been located in the roster record, so observed_levels stays None -- max HP is
            # observable today and carries the same information.
            observed_max_hp = {
                name.upper(): self._max_hp_seen.get((surname, name), 0)
                for name in species_groups
            }
            queue = queue_by_upper.get(surname.upper()) or []
            identity = self._team_identity(
                surname, queue, observed, team_fingerprints, observed_max_hp
            )
            beaten = self._beaten_team_ids.setdefault(surname.upper(), [])
            if identity in beaten:
                # A team already beaten. Nothing is checked off and the running total does not move, so a
                # rematch cannot farm the cumulative bucket either.
                self.rematches_ignored += 1
                continue
            beaten.append(identity)

            self._defeat_count += 1
            if count_location_max is None or self._defeat_count <= count_location_max:
                completed.append(count_location_name(self._defeat_count))
            index = len(beaten) - 1
            if index < len(queue):
                dispatched_name = queue[index]
                if dispatched_name is not None:  # ADDENDUM 102 -- a decoy-battle sentinel dispatches nothing
                    completed.append(dispatched_name)
                self._claimed_queue_indices.setdefault(surname, set()).add(index)
                self._surname_queue_position[surname] = (
                    max(self._surname_queue_position.get(surname, 0), index + 1)
                )
        # A key we did not even SEE this poll made no progress this poll. The counter above only rises for keys in
        # this poll's dominant cluster -- but a key can stop being looked at without its surname disappearing:
        # `dominant_roster_cluster` keeps the largest contiguous run and drops the rest, MEM1 accumulates stale
        # rosters for the whole boot, and XD reuses surnames, so an old battle's cluster and a new one's compete under
        # one key and the winner flips as the new roster is written. The old cluster's species is then baselined, not
        # fired, its surname still present so the vanish-purge does not touch it, and its counter FROZEN below the
        # threshold -- so `has_unresolved_battle()` returns True until the client restarts.
        #
        # Count the poll, do not purge the key: a species can drop out of the cluster for a poll or two mid-battle
        # and come back, and purging loses the min-HP baseline a real kill is measured against.
        observed_this_poll = {
            (seen_surname, species_name)
            for seen_surname, species_groups in by_surname.items()
            for species_name in species_groups
        }
        for key in self._baselined:
            if key in observed_this_poll:
                continue
            self._polls_without_progress[key] = self._polls_without_progress.get(key, 0) + 1
        return completed

    # What makes one of a trainer's teams different from another of them.
    def _team_identity(
        self,
        surname: str,
        queue: "list[str | None]",
        observed_species: "set[str]",
        team_fingerprints: "dict[str, Any] | None",
        observed_max_hp: "dict[str, int] | None" = None,
    ) -> str:
        """A stable string naming the team just beaten, for comparison against the ones already beaten.

        Two sources, in order of what they are worth. The occurrence the fingerprinter resolves it to, as
        `occ:{label}`, scored across the FULL queue rather than the unclaimed part, because recognising a rematch means
        being allowed to land on a team already beaten; a label rather than an index, so it survives a round trip to
        disk beside a queue that may have changed. Otherwise the team actually observed, as `obs:{species@maxhp ...}`,
        which cannot say which encounter this was but answers the only question dispatch asks, from direct evidence --
        so a seed generated before fingerprints shipped still gets rematch protection.

        The observed signature is the fallback because it is noisier than it looks: the roster shows what is on the
        field, so a six-slot trainer whose bench never appeared signs differently from the same trainer when it did,
        which splits one team into two identities and hands out an extra check.

        MaxHP is rounded into a coarse band first: the raw figure varies with IVs/EVs, which this project has never
        extracted, so two sightings of one team can differ by a few points."""
        if queue and team_fingerprints:
            label = self._resolve_occurrence(
                queue, observed_species, team_fingerprints, observed_max_hp
            )
            if label is not None:
                self.fingerprint_matches += 1
                return f"occ:{label}"
        parts = []
        for name in sorted(observed_species):
            hp = (observed_max_hp or {}).get(name, 0)
            parts.append(f"{name}@{hp // self.HP_IDENTITY_BAND if hp > 0 else 0}")
        return "obs:" + ",".join(parts)

    #: MaxHP is divided by this before it enters a fallback identity. Wide enough to swallow the unextracted
    #: IV/EV spread, narrow enough that two encounters differing by whole level bands never share a bucket.
    HP_IDENTITY_BAND: int = 8

    def _resolve_occurrence(
        self,
        queue: "list[str | None]",
        observed_species: "set[str]",
        team_fingerprints: "dict[str, Any]",
        observed_max_hp: "dict[str, int] | None" = None,
    ) -> "str | None":
        """Which of this surname's labels the observed team belongs to, or None when the evidence does not single
        one out. Scored over every label, not just the unclaimed ones."""
        best_label: "str | None" = None
        best_score = 0
        tied = False
        for label in queue:
            entry = team_fingerprints.get(label) if label else None
            if not entry:
                continue
            score = self._fingerprint_score(entry, observed_species, None, observed_max_hp)
            if score > best_score:
                best_label, best_score, tied = label, score, False
            elif score == best_score and best_score > 0 and label != best_label:
                tied = True
        if best_label is None or best_score <= 0 or tied:
            return None
        return best_label

    # ADDENDUM 362: the beaten-team ledger, so a client restart cannot reopen the rematch it closes. Shaped
    # like `PurificationCountTracker.to_json` and persisted beside it in the same per-seed state file.
    def to_json(self) -> dict:
        return {"beaten_teams": {k: list(v) for k, v in self._beaten_team_ids.items() if v}}

    def load_json(self, data: "dict | None") -> None:
        """Tolerant on purpose: a hand-edited or older state file must degrade to "nothing beaten yet" rather
        than take the client down, exactly as the area-memory loader does."""
        if not isinstance(data, dict):
            return
        beaten = data.get("beaten_teams")
        if not isinstance(beaten, dict):
            return
        for surname, identities in beaten.items():
            if not isinstance(surname, str) or not isinstance(identities, list):
                continue
            clean = [i for i in identities if isinstance(i, str)]
            if clean:
                self._beaten_team_ids[surname.upper()] = clean

    def beaten_team_counts(self) -> "dict[str, int]":
        """{SURNAME: how many distinct teams of theirs have been beaten}. For `!teams`."""
        return {k: len(v) for k, v in self._beaten_team_ids.items() if v}

    # --- The axes a team is recognised by. ---
    # Additive across independent axes, all optional: a fingerprint carrying only species still works, and a seed with
    # no fingerprints falls back to the observed signature.
    #
    #   * Species overlap, weight 2 per hit. The primary signal.
    #   * Level overlap, weight 2 per hit, against EITHER the vanilla or the enhanced-difficulty levels, since both
    #     ship. Dormant: no level field has been found in the roster record; `observed_levels` is the hook.
    #   * Max HP band, weight 2 per hit. What does the level's work today.
    #   * Party size, weight 1, a LOWER BOUND: Enhanced Difficulty and Shadow Expansion only ADD members, so a
    #     candidate whose base size exceeds what was on the field is contradicted and subtracts.
    #
    # Overlap rather than equality throughout, because the roster shows what is on the FIELD (a subset for a six-slot
    # trainer mid-battle), Shadow slots are not fingerprinted, difficulty padding is chosen too late to fingerprint,
    # and a nickname resolves to no species. A partial match still identifies; a tie or no evidence identifies nothing.

    SPECIES_MATCH_WEIGHT: int = 2
    LEVEL_MATCH_WEIGHT: int = 2
    # Weighted like a species hit: a species present AND whose MaxHP lands in the predicted band is twice the
    # evidence of the species alone.
    HP_MATCH_WEIGHT: int = 2
    PARTY_SIZE_WEIGHT: int = 1

    @classmethod
    def _fingerprint_score(
        cls,
        entry: "Any",
        observed_species: "set[str]",
        observed_levels: "set[int] | None",
        observed_max_hp: "dict[str, int] | None" = None,
    ) -> int:
        """How well one candidate's fingerprint explains what was on the field; axes and weights above. Accepts
        a bare list of species names as well as the dict shape, so a seed generated in between still matches."""
        if isinstance(entry, (list, tuple, set)):
            entry = {"species": list(entry)}
        if not isinstance(entry, dict):
            return 0

        score = 0
        expected_species = {str(name).upper() for name in entry.get("species") or ()}
        species_hits = len(observed_species & expected_species) if observed_species else 0
        score += cls.SPECIES_MATCH_WEIGHT * species_hits

        level_hits = 0
        if observed_levels:
            # Either level set is a legitimate hit -- the seed ships both so the client never has to know
            # whether Enhanced Difficulty was on.
            expected_levels = set(entry.get("levels") or ()) | set(entry.get("levels_enhanced") or ())
            level_hits = len(observed_levels & expected_levels)
            score += cls.LEVEL_MATCH_WEIGHT * level_hits

        hp_hits = 0
        if observed_max_hp:
            # Either difficulty's bands count, same reasoning as the levels. A species with no band -- a Shadow
            # slot, a padding member, or one above dex 251 where the index space is unresolved -- contributes
            # nothing rather than a guess.
            for name, hp in observed_max_hp.items():
                if hp <= 0:
                    continue
                for candidate in (entry.get("hp_bands") or {}, entry.get("hp_bands_enhanced") or {}):
                    band = candidate.get(name)
                    if band and len(band) == 2 and band[0] <= hp <= band[1]:
                        hp_hits += 1
                        break
            score += cls.HP_MATCH_WEIGHT * hp_hits

        if expected_species and observed_species:
            # Compared as DISTINCT species, not slot count: `observed_species` is a set, so a trainer with two
            # Zubat contributes one name to each side. `base_party_size` is the real slot count, for display only.
            if len(expected_species) > len(observed_species):
                # More distinct ordinary species than were ever on the field. Difficulty and Shadow Expansion
                # only ADD, so this candidate is contradicted rather than merely unsupported -- worth recording
                # even with no other evidence, because it rules a candidate OUT.
                score -= cls.PARTY_SIZE_WEIGHT
            elif len(expected_species) == len(observed_species) and (species_hits or level_hits or hp_hits):
                # Only ever a tiebreak. On its own a matching team size is not evidence of the right trainer and
                # must never produce a positive score from nothing.
                score += cls.PARTY_SIZE_WEIGHT
        return score

    def has_unresolved_battle(self) -> bool:
        """True if, as of the last `poll()`, some (surname, species) slot is baselined but not yet confirmed dead for
        a surname not already counted this encounter -- i.e. a real trainer fight looks to be in progress.

        `BattleStateTracker` uses it as a second, independent signal. Unlike the anchor it reuses state this tracker
        already maintains, so it stays True for a real battle's whole duration, menu waits included, with no extra
        reads. Ordinary trainer battles cannot be fled, so a surname's slots realistically stop being unresolved only
        by being confirmed dead. False before this tracker has ever polled.

        A stale slot is excluded by "no observed HP movement for `STALE_NO_PROGRESS_POLLS` consecutive polls". Stale
        roster records are never cleared from memory and keep matching the signature scan, so the vanish purge never
        fires for them: a WIN leaves one frozen at 0 with no observed drop, a LOSS leaves one frozen at whatever
        nonzero HP it last had, and excluding only the 0-HP shape left the loss shape sticking this True for the rest
        of the boot -- which showed up as items always taking the full delivery ceiling to arrive."""
        for key in self._baselined:
            surname = key[0]
            if key in self._fired or surname in self._awaiting_clear:
                continue
            if self._polls_without_progress.get(key, 0) >= self.STALE_NO_PROGRESS_POLLS:
                # No HP movement in a long time -- a stale leftover (frozen at 0 after a win, or at any other
                # value after a loss), not something being actively fought.
                continue
            return True
        return False

    def describe_blocking(self) -> "list[str]":
        """Why `has_unresolved_battle()` is answering what it is answering, key by key.

        `!battle` could tell a player "free -- items can deliver" while this signal held every delivery for ten
        minutes: the command printed the UI flag and the debounce and never the corroborating input that overrides
        both."""
        blocking: "list[str]" = []
        stale = 0
        for key in sorted(self._baselined):
            surname, species = key
            if key in self._fired or surname in self._awaiting_clear:
                continue
            idle = self._polls_without_progress.get(key, 0)
            if idle >= self.STALE_NO_PROGRESS_POLLS:
                stale += 1
                continue
            blocking.append(f"    {surname} / {species}: idle {idle}/{self.STALE_NO_PROGRESS_POLLS} poll(s), "
                            f"min HP seen {self._min_hp_seen.get(key, '?')}")
        lines = [f"  unresolved battle: {'YES -- deliveries are held' if blocking else 'no'} "
                 f"({len(self._baselined)} roster key(s) tracked, {len(blocking)} blocking, {stale} aged out)"]
        lines.extend(blocking[:8])
        if len(blocking) > 8:
            lines.append(f"    ... and {len(blocking) - 8} more")
        return lines


# --- Battle-state detection. ---
# Gates Client.py's give_items() so a received item is never written into the Bag mid-battle; it sits untouched in
# the existing given_item_indices retry queue instead. Trust is asymmetric: a NONZERO read means "definitely in
# battle, right now" and is trusted immediately, but a bare zero-read is not -- so this debounces the OPPOSITE
# direction to the other trackers, waiting for a confirmed run of zeros before trusting "safe now".

BATTLE_STRUCT_ANCHOR_ADDRESS = 0x80874F54  # RETIRED 2026-09-14 (ADDENDUM 202) -- read 0 DURING a real
                                            # battle on the player's own live game. See below. Kept only so
                                            # `!battle` can show it next to the replacement.

# --- The battle gate, measured across eleven states. ---
# BATTLE_STRUCT_ANCHOR_ADDRESS is retired: it read 0x00000000 in all four live dumps taken, two from inside real
# battles, so every gate built on it was open for the whole of every fight. The replacement was found by
# intersecting four full 24 MB dumps (two in battle, two just after) -- a raw before/after diff is useless, since
# leaving a battle rewrites 35% of RAM -- and then testing each survivor in NON-battle states, the step never done
# for the old anchor: 0x80814AC0 and 0x80874E50 both read "in battle" in the Bag menu.
#     state                              value   gate
#     ---------------------------------  -----   ----------
#     battle just started                    1   closed
#     mid-battle, move-select menu           1   closed
#     battle end screen                      1   closed
#     post-battle, control not yet back      1   closed
#     control regained                       0   OPENS
#     a few seconds later                    0   open
#     overworld, standing                    0   open
#     overworld, walking                     0   open
#     Bag menu                               1   closed
#     Party screen                           1   closed
#     cutscene / dialogue                    0   open   <- KNOWN GAP, see below
#
# The drop point is the whole point: this flag goes to 0 at the same moment the game finishes writing the Bag.
# Measured across one battle's end, prize money (BLOCK_BASE+0x8A4) went 5315 -> 5435 and an item left the Bag, both
# between "end screen" and "control regained". So the gate means "the game has finished touching the Bag", which
# matters because `route_and_give_item` writes into that same Bag -- an item delivered at the end screen is racing
# the game's own write. Not per-frame scratch: the surrounding 256-byte window was byte-identical between standing
# and walking, and across the other sampled pairs.
#
# KNOWN GAP: it reads 0 during cutscenes and NPC dialogue -- a battle-and-full-screen-menu flag, not a "player has
# free control" flag. Whether delivering mid-cutscene is harmful is unknown. 0x80814A64 is plausible as a stable
# address (0x52 bytes from ROOM_ID_MIRRORS[0], in the region documented as keeping its address across boots and save
# files), but is not yet confirmed across a reboot.
BATTLE_UI_FLAG_ADDRESS = 0x80814A64

# Observation only. A mode enum, not a flag: 0 normal, 1 immediately after a battle, 2 cutscene/dialogue. Five
# samples, and what resets 1 -> 0 is unknown (a menu, a room change, or time). Recorded because a genuine "a
# battle just ended" edge is what was originally asked for and this may be it. Nothing depends on it; measure
# what clears it before gating on it.
BATTLE_MODE_ENUM_ADDRESS = 0x80874E50


def read_battle_ui_flag() -> int:
    """1 while a battle or a full-screen menu owns the game, 0 when it does not. See the section comment above for
    the states this was measured in and the one known gap (cutscenes read 0)."""
    return struct.unpack(">I", read_bytes(BATTLE_UI_FLAG_ADDRESS, 4))[0]


def read_battle_mode_enum() -> int:
    """Diagnostic only -- see BATTLE_MODE_ENUM_ADDRESS. Nothing gates on this."""
    return struct.unpack(">I", read_bytes(BATTLE_MODE_ENUM_ADDRESS, 4))[0]


def read_battle_struct_anchor() -> int:
    """Raw pointer value at BATTLE_STRUCT_ANCHOR_ADDRESS. Retired -- use BattleStateTracker.poll() for a
    trustworthy "safe to deliver items now" signal."""
    return struct.unpack(">I", read_bytes(BATTLE_STRUCT_ANCHOR_ADDRESS, 4))[0]


def read_step_counter(block_base: "int | None") -> "int | None":
    """The save's running step total, or None when it cannot be read. Never raises."""
    if block_base is None:
        return None
    try:
        return struct.unpack(">I", read_bytes(block_base + STEP_COUNTER_OFFSET, 4))[0]
    except Exception:
        return None


@dataclass
class StepCounterGate:
    """"Did the player just take a step?" -- the question item delivery waits on.

    The inverse of detecting a battle, and better: a detector's failure mode is claiming a battle that has ended, once
    for the full ten-minute backstop. The step counter only moves while the player is walking in the field, which is
    exactly when a Bag write is safe.

    Evidence for `STEP_COUNTER_OFFSET`, block-relative, from this project's MEM1 dumps: 0 on a new save before the
    player has control and 9 after the first moves; unchanged across every before/after battle pair in the corpus
    (1982/1982, 2084/2084, 2471/2471, 3008/3008, 7511/7511, 792/792, 977/977); unchanged across menus (six map-select
    dumps read 14733, seven shop-menu dumps 8021); rising in small steps between rooms (9368 -> 9429 -> 9439 -> 9443
    -> 9445 -> 9455 -> 9501); a plain running total per save through at least 14,765 steps. One offset qualified.

    True only when the counter rose by a plausible walking amount since a RECENT previous poll: a rise over
    `MAX_STEPS_PER_POLL` is a save load, a baseline older than `MAX_BASELINE_AGE_SECONDS` says nothing about now, and a
    DECREASE is a different save. None when unreadable, so the caller falls back rather than blocking forever."""

    MAX_STEPS_PER_POLL: int = 100
    MAX_BASELINE_AGE_SECONDS: float = 3.0

    last_value: "int | None" = None
    last_block: "int | None" = None
    last_time: "float | None" = None
    advanced_polls: int = 0
    readable: bool = False

    def poll(self, block_base: "int | None", now: "float | None" = None) -> "bool | None":
        if now is None:
            now = time.monotonic()
        value = read_step_counter(block_base)
        if value is None:
            self.readable = False
            self.last_value = None
            return None
        self.readable = True
        stale = (self.last_time is None or now - self.last_time > self.MAX_BASELINE_AGE_SECONDS)
        rebaseline = block_base != self.last_block or self.last_value is None or stale
        previous = self.last_value
        self.last_value, self.last_block, self.last_time = value, block_base, now
        if rebaseline:
            return False
        delta = value - previous
        if 0 < delta <= self.MAX_STEPS_PER_POLL:
            self.advanced_polls += 1
            return True
        return False

    def describe(self) -> str:
        if not self.readable:
            return "Step counter: not readable right now -- delivery falls back to the battle gate."
        return (f"Step counter: {self.last_value} total; items start delivering on a poll where it rises "
                f"({self.advanced_polls} such polls so far).")


@dataclass
class BattleStateTracker:
    """Debounces BATTLE_UI_FLAG_ADDRESS into a single "safe to deliver received items right now" bool.

    A nonzero read is trusted immediately: the flag is 1 whenever a battle or a full-screen menu owns the game,
    including the post-battle teardown, which is where the game writes the Bag this client also writes to.

    "Not in battle" needs CONFIRM_POLLS consecutive zero-reads, because nothing here trusts a bare snapshot. 3
    rather than the dead anchor's 8: the measured flag showed no drift across repeated samples in one state. A
    transient zero has only been ruled out at sampled moments, so if one is ever seen mid-battle raise this number
    rather than inventing a second signal.

    Starts at `_consecutive_zero = 0`, so a fresh connection earns its own streak -- withholding for a few seconds
    is harmless, since `give_items`' retry queue delivers the moment this returns True.

    `corroborating_in_battle` is veto-only and now believed redundant, kept because it can only add caution. The
    load-bearing guarantee is `give_items`' hard per-item timeout: this class of gate has wedged itself shut four
    separate times in real runs, and item delivery must never be blocked indefinitely."""

    _consecutive_zero: int = 0
    CONFIRM_POLLS: ClassVar[int] = 3

    def poll(self, corroborating_in_battle: bool = False) -> bool:
        """True when it is currently safe for give_items() to proceed.

        `corroborating_in_battle` is treated exactly like a nonzero flag read: blocks immediately and resets the
        streak. It can only add caution. False (the default, e.g. with `shuffle_trainer_defeats` off) leaves the
        plain flag debounce."""
        if corroborating_in_battle:
            self._consecutive_zero = 0
            return False
        # The measured flag, not the dead anchor. 1 covers the whole post-battle teardown, which is where the
        # game writes the Bag this client also writes to.
        flag = read_battle_ui_flag()
        if flag != 0:
            self._consecutive_zero = 0
            return False
        self._consecutive_zero += 1
        return self._consecutive_zero >= self.CONFIRM_POLLS


# --- Manual smoke test: run this file directly to sanity-check hooking, base resolution and pocket contents
# against a real running game, independent of any AP server. Test tooling, not the client. ---

def _describe_pocket(name: str, slots: list[BagSlot]) -> None:
    owned = [s for s in slots if not s.empty]
    print(f"  {name}: {len(owned)}/{len(slots)} slots used")
    for s in owned:
        print(f"    [{s.index}] item_id={s.item_id} qty={s.quantity} @ {hex(s.address)}")


def main() -> None:
    import sys

    if len(sys.argv) > 1:
        landmark = sys.argv[1]
    else:
        # No hardcoded default -- see TRAINER_NAME_LANDMARK. A real client gets this from its AP slot name.
        landmark = input("In-game trainer name (must match exactly, case included): ").strip()

    print("Hooking to Dolphin...")
    if not hook():
        print("Failed to hook -- is Dolphin running with the game loaded? See pokemon-xd-live-bridge-notes.md "
              "for known hooking pitfalls (Store Python / AppContainer sandboxing, stuck hook state, etc.)")
        return
    print(f"Hooked. Resolving player-state block base for trainer name {landmark!r} "
          "(one-time full-memory scan, may take a few seconds)...")
    base = resolve_block_base(landmark)
    if base is None:
        print(f"No occurrence of {landmark!r} validated as a real player-state block -- not in-game yet, the "
              "in-game trainer name doesn't actually match, or XD's name-entry screen altered it. See "
              "resolve_block_base's docstring.")
        return
    print(f"Resolved block base: {hex(base)}")
    print(f"Money: {read_money(base)}")
    _describe_pocket("Items", read_pocket(base + ITEMS_POCKET_OFFSET, ITEMS_POCKET_MAX_SLOTS))
    _describe_pocket("Poke Balls", read_pocket(base + POKEBALL_POCKET_OFFSET, POKEBALL_POCKET_MAX_SLOTS))
    _describe_pocket("Key Items", read_pocket(base + KEY_ITEMS_OFFSET, KEY_ITEMS_MAX_SLOTS))

    party_dex_numbers = read_party_species(PARTY_BASE)
    print(f"Party ({len(party_dex_numbers)} species, confirmed-safe live source): {party_dex_numbers}")
    print(
        "PC box slots NOT scanned here -- box-slot reading is provisional/best-effort only "
        "(see read_box_slot_species's docstring); call it explicitly with a known-displayed slot index "
        "if you want to sanity-check it against what's actually on screen right now."
    )


if __name__ == "__main__":
    main()


# --- A battle hold that CANNOT wedge. ---
# Four separate incidents of a battle gate sticking True and blocking delivery for the rest of a run ended in every
# gate being ripped out, so the problem is not "find a battle signal" but "find one incapable of staying true".
# BATTLE_STRUCT_ANCHOR_ADDRESS is a LEVEL signal -- a value supposed to return to 0, and the whole failure history
# is it not doing so. Roster HP is a MOTION signal: the hold is armed by HP values CHANGING between polls, so it
# decays the instant the game stops updating them, and a stuck pointer, a stale record or a scripted battle that
# never tears down cannot hold it true.
#
# Two belts on top: `quiet_seconds` releases the hold that long after the last observed change rather than on an
# end-of-battle event that might never arrive, and `max_hold_seconds` caps one continuous hold absolutely. Worst
# case is a bounded delay, never a block, and a held poll simply does not attempt delivery.

BATTLE_HOLD_QUIET_SECONDS = 2.5
BATTLE_HOLD_MAX_SECONDS = 30.0


@dataclass
class BattleActivityHold:
    """Motion-based "a battle is actively running right now" signal. Feed it each poll's roster records (the
    same scan `TrainerBattleDefeatTracker` already consumes -- no extra memory read) and, optionally, the
    battle-struct anchor value. Ask `should_hold()` whether to defer item delivery this poll."""

    quiet_seconds: float = BATTLE_HOLD_QUIET_SECONDS
    max_hold_seconds: float = BATTLE_HOLD_MAX_SECONDS

    _last_hp: dict[tuple[int, str], int] = field(default_factory=dict)
    _last_change_at: float | None = None
    _hold_started_at: float | None = None
    _ceiling_tripped: bool = False
    last_reason: str = "no battle activity observed"

    def observe(
        self,
        records: "list[BattleRosterRecord] | None",
        anchor_value: int = 0,
        now: float | None = None,
    ) -> bool:
        """Record this poll's evidence; returns the same bool as `should_hold()`. Keyed by (address, species) so a
        record overwritten in place by a different Pokemon still registers as motion."""
        now = time.time() if now is None else now
        changed = False
        seen: dict[tuple[int, str], int] = {}
        for record in records or ():
            if record.species_dex is None:
                continue
            key = (record.address, record.species_name)
            seen[key] = record.current_hp
            if key in self._last_hp and self._last_hp[key] != record.current_hp:
                changed = True
        # A record appearing or disappearing is motion too -- that is a roster being built up or torn down.
        if not changed and self._last_hp and set(seen) != set(self._last_hp):
            changed = True
        self._last_hp = seen

        if changed or anchor_value:
            self._last_change_at = now
            if self._hold_started_at is None:
                self._hold_started_at = now
                self._ceiling_tripped = False
        return self.should_hold(now)

    def should_hold(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        if self._last_change_at is None:
            self.last_reason = "no battle activity observed"
            return False
        quiet_for = now - self._last_change_at
        if quiet_for > self.quiet_seconds:
            # Fully released -- re-arm so a later battle gets a fresh ceiling.
            self._hold_started_at = None
            self._ceiling_tripped = False
            self.last_reason = f"no battle activity for {quiet_for:.1f}s"
            return False
        if self._hold_started_at is not None and now - self._hold_started_at > self.max_hold_seconds:
            if not self._ceiling_tripped:
                self._ceiling_tripped = True
            self.last_reason = (f"battle activity still ongoing after {now - self._hold_started_at:.0f}s -- "
                                f"delivering anyway (hold ceiling reached)")
            return False
        self.last_reason = f"battle activity {quiet_for:.1f}s ago"
        return True

    @property
    def ceiling_tripped(self) -> bool:
        """True once one continuous hold has run past `max_hold_seconds`. Worth logging once: it means something
        kept the roster churning far longer than a battle should."""
        return self._ceiling_tripped


# --- The current-area id -- RETRACTED. DO NOT TRUST THIS VALUE. ---
# 0x80447EF0 looked like the current area across nine MEM1 dumps at six areas. A post-reboot test disproved it:
# standing at the HQ Lab EXTERIOR the address read 6 (Gateon Port), 0x80447F10 held 1 (HQ interior, null pointer),
# and a 24 MB scan found no record holding the correct id 11 with a live pointer. The region is a cache of RECENTLY
# LOADED areas; it tracked position in the original session only because the player walked through areas in order.
# Kept because the machinery is sound and the labels are real observations worth having if the true field is found.
#
# Observed ids, each reproduced across independent visits:
#     1  Pokemon HQ Lab -- INTERIOR (three samples)   2  Cipher Lab           6  Gateon Port (two visits)
#     7  Kaminko's house (two visits)                11  Pokemon HQ Lab -- EXTERIOR
#
# Interior and exterior of one building have DIFFERENT ids -- XD treats them as separate areas, which is why hunting
# for a "Purify Chamber enabled" FLAG came up empty: the chamber is a property of which lab map is loaded. Two
# live-observed caveats, both handled below: the field reads 0 in some states (treat 0 as unknown), and cross-boot
# stability was never established, so `read_area_id()` validates rather than trusting.

# The address is RESOLVED rather than assumed, from two candidates in order: `block_base -
# AREA_ID_BLOCK_BASE_DELTA`, which tracks automatically if the game-state region relocates as one piece, then the
# absolute `AREA_ID_ADDRESS`. Both are validated the same way and a failed validation means unknown, never a guess.
# Which is correct is unestablished and needs one observation from a second boot; `!area` reports which it used. A
# pure signature scan was rejected: the shape (small id + MEM1 pointer + an identical copy 0xD0 later) matches
# 679-1517 places in a real 24 MB dump.

AREA_ID_ADDRESS = 0x80447EF0
AREA_ID_MIRROR_OFFSET = 0xD0
AREA_ID_MIRROR_ADDRESS = AREA_ID_ADDRESS + AREA_ID_MIRROR_OFFSET
AREA_ID_BLOCK_BASE_DELTA = 0x31490   # BLOCK_BASE 0x80479380 - 0x80447EF0, this boot
AREA_ID_MAX_PLAUSIBLE = 0x400

KNOWN_AREA_IDS: "dict[int, str]" = {
    1: "Pokemon HQ Lab (interior)",
    2: "Cipher Lab",
    6: "Gateon Port",
    7: "Kaminko's house",
    11: "Pokemon HQ Lab (exterior)",
}


def area_name(area_id: "int | None") -> str:
    if area_id is None:
        return "unknown"
    return KNOWN_AREA_IDS.get(area_id, f"area {area_id} (unmapped)")


def area_id_candidates(block_base: "int | None") -> "list[tuple[int, str]]":
    """`(address, how_it_was_derived)` in preference order. The relative anchor first -- if the region moves
    as one piece it is the one that survives a reboot."""
    out: list[tuple[int, str]] = []
    if block_base:
        out.append((block_base - AREA_ID_BLOCK_BASE_DELTA, "relative to the save block"))
    out.append((AREA_ID_ADDRESS, "fixed address"))
    return out


def read_area_id_at(address: int) -> "int | None":
    """Read and validate one candidate address. None means "this is not a trustworthy area id": the mirrored
    copies disagree, the value is implausibly large, or it is zero (a real, observed state during map
    transitions, menus and cutscenes -- see the section comment)."""
    if not (MEM1_START < address < MEM1_START + MEM1_SIZE - AREA_ID_MIRROR_OFFSET - 4):
        return None
    try:
        primary = struct.unpack(">I", read_bytes(address, 4))[0]
        mirror = struct.unpack(">I", read_bytes(address + AREA_ID_MIRROR_OFFSET, 4))[0]
    except Exception:
        return None
    if primary != mirror:
        return None
    if primary == 0 or primary > AREA_ID_MAX_PLAUSIBLE:
        return None
    return primary


def read_area_id(block_base: "int | None" = None) -> "int | None":
    """Best-effort current area id, trying each candidate anchor in order. Kept for callers that do not want
    to track which anchor worked; `AreaTracker` uses the resolving form below instead."""
    for address, _how in area_id_candidates(block_base):
        value = read_area_id_at(address)
        if value is not None:
            return value
    return None


@dataclass
class AreaTracker:
    """Holds the last trustworthy area id and reports transitions. Cheap: two 4-byte reads per poll."""

    current: "int | None" = None
    previous: "int | None" = None
    changes: int = 0
    address: "int | None" = None      # resolved once, then reused
    anchor: str = "not resolved yet"
    _unknown_polls: int = 0

    def poll(self, block_base: "int | None" = None) -> "tuple[int, int] | None":
        """Returns `(from_id, to_id)` on a confirmed area change, else None. An unreadable/zero id never
        counts as a change -- it is simply ignored and the last known area is kept.

        The address is resolved on the first poll that yields a real id and then reused. Resolution
        deliberately REQUIRES a non-zero id: when the field reads zero, every candidate validates trivially
        (both copies are zero), so a zero reading can never be allowed to pick the anchor."""
        observed = None
        if self.address is not None:
            observed = read_area_id_at(self.address)
            if observed is None:
                self._unknown_polls += 1
                if self._unknown_polls > 60:
                    # A minute of nothing: the anchor may have gone stale (a reset, a different boot).
                    self.address, self.anchor = None, "not resolved yet"
                    self._unknown_polls = 0
                return None
        else:
            for address, how in area_id_candidates(block_base):
                value = read_area_id_at(address)
                if value is not None:
                    self.address, self.anchor, observed = address, how, value
                    break
            if observed is None:
                self._unknown_polls += 1
                return None
        self._unknown_polls = 0
        if observed == self.current:
            return None
        self.previous, self.current = self.current, observed
        self.changes += 1
        if self.previous is None:
            return None  # first sighting is not a transition
        return (self.previous, observed)

    UNRELIABLE_NOTE = ("  NOTE: this value is KNOWN UNRELIABLE (ADDENDUM 140) -- it read 'Gateon Port' while "
                       "the player stood at the HQ Lab exterior. It appears to be a cache of recently loaded "
                       "areas, not current position. Research only; nothing in the client acts on it.")

    def describe(self) -> str:
        if self.current is None:
            return ("Area: unknown (the id reads 0 or could not be validated). Anchor: " + self.anchor + ".\n"
                    + self.UNRELIABLE_NOTE)
        line = f"Area: {area_name(self.current)} [id {self.current}]"
        line += f"\n  read from {self.address:#010x} ({self.anchor})"
        if self.previous is not None:
            line += f"; previously {area_name(self.previous)} [id {self.previous}]"
        return line + f"; {self.changes} value change(s) seen this session.\n" + self.UNRELIABLE_NOTE


# --- The global story-progress byte, read live. ---
# `+0x00` of the travel-control record (BLOCK_BASE + 0x10720). Polled, every change logged with its time, and
# `!story` reports the current value plus the whole 20-byte record. Only `+0x00` is tracked as the story byte:
# `+0x04`..`+0x07` drift on their own with no player action.
#
# `+0x01`'s top three bits are NOT a drifting neighbour -- they are the bottom three bits of the story value. GS
# variable 964 is twelve bits at bitpos 917 of flag group 24, i.e. `(u16_be(record + 0x00) >> 5) & 0xFFF`, so
# `+0x00` is bits 3..10 of it, and a checkpoint where `+0x01` went 0x00 -> 0xC0 -> 0x00 is the low bits going
# 0 -> 6 -> 0. `+0x01`'s low five bits are the tail of GS variable 802, and `poke_story_byte` preserves them.

STORY_RECORD_OFFSET = 0x10720   # == travel_locations.TRAVEL_RECORD_OFFSET_FROM_BLOCK_BASE; duplicated rather
                                # than imported to keep ram_client free of an apworld-module dependency.
STORY_RECORD_SIZE = 20
STORY_BYTE_OFFSET = 0x00
STORY_BYTE_MAX_PLAUSIBLE = 0xFE  # 0xFF has only ever been seen as a deliberate test write (checkpoint 12)

# Checkpoints from pokemon-xd-story-flags.md worth recognising on sight. Values are NOT comparable across save
# files -- a hint for the player, never a decision input. Two kinds of entry: the original nine are observed states
# ("the byte read this when I was roughly here"), while the later ones are deliberate TRANSITIONS ("0x17 -> 0x19 =
# Agate unlock"), a much stronger claim and the only kind that could become a real unlock gate.
#
# One conflict is left standing: 0x25 was recorded in an earlier playthrough as "first purification", while the
# newer compilation puts that at 0x21 -> 0x23 and makes 0x25 -> 0x26 the Cipher Lab unlock. The watched transition
# is more likely right, but overwriting an earlier observation with a later one is how the area-id retraction
# happened, so both are kept and both are labelled.
STORY_BYTE_LANDMARKS: "dict[int, str]" = {
    # 0x0F reads two ways and both are kept, but the Snag Machine is the load-bearing one: story_bytes' HQ Lab
    # 0x17 rule and Kaminko's 0x53 rule both key on the lab having genuinely reached it.
    0x0F: "Snag Machine obtained (player, 2026-09-18) / Gateon Port unlock dialogue complete (earlier note)",
    0x10: "Krane Memos 1 and 2 obtained (transition)",
    0x11: "Gateon Port cutscene fully complete",
    0x16: "Machine Part obtained (transition; the Machine Part key item is also required)",
    0x17: "Krane Memos 3, 4 and 5 obtained (transition)",
    0x19: "Agate Village unlocked (transition from 0x17)",
    0x20: "around Agate Village / pre-Eagun",
    0x21: "Eagun defeated",
    0x23: "first Shadow Pokemon purified (transition from 0x21)",
    0x24: "Mt. Battle unlocked (transition from 0x23)",
    0x25: "first purification / released from Eagun's hold (EARLIER observation -- see 0x23)",
    0x26: "Cipher Lab unlocked (transition from 0x25)",
    0x28: "first Cipher Lab visit, pre-six-battle",
    0x2B: "Lovrina defeated",
    0x2D: "Purify Chamber unlocked",
    0x2F: "Pokemon deposited into the Purify Chamber",
}


# --- Krane Memos. ---
# The memos are this world's only real progression items -- every region past Phenac City is gated on holding N of
# them -- but the game hands all five over during the ordinary early story, which made that gating decorative. So
# when the story byte crosses each threshold, the game's own copies are cleared out of the Key Items pocket and the
# matching locations are sent. Mirrors locations.py's KRANE_MEMO_* constants for the same standalone-loadability
# reason as the other mirrored constants here; test_addendum_153 asserts the two copies against each other.
KRANE_MEMO_COUNT = 5
KRANE_MEMO_STORY_THRESHOLDS: "dict[int, int]" = {1: 0x10, 2: 0x10, 3: 0x17, 4: 0x17, 5: 0x17}

# --- A threshold is credited from the AREA that hands the thing over, not the global byte. ---
# `check_krane_memos` used to read the raw live byte, so hovering Agate on the map screen (entry floor 0x19) cleared
# BOTH memo thresholds, 0x10 and 0x17, in one tick. `StoryProgressWitness` alone would not have fixed it, because
# travelling somewhere COMMITS that destination's floor -- after a real trip to Agate the byte genuinely IS 0x19 and
# the witness rises to it honestly, clearing every threshold below wherever the player stands.
#
# Krane hands the memos over in his lab, so the LAB's high-water mark is the witness that means something, and it
# only rises while the player is standing in the lab with that byte -- which is the event itself. The area marks are
# safe to read only because two other rules launder them: one refuses any byte recorded while a hover write is
# outstanding, the other refuses a committed hover write against the region the player landed in.
KRANE_MEMO_HANDOVER_AREA = "Pokemon HQ Lab"
KRANE_MEMO_GAME_ITEM_IDS: "dict[int, int]" = {n: 522 + n for n in range(1, KRANE_MEMO_COUNT + 1)}


def krane_memo_location_name(memo_number: int) -> str:
    return f"Story - Krane Memo {memo_number}"


# --- Key items are RECONCILED every poll rather than delivered once. ---
# `give_items()` is an event handler: it writes an arriving item, confirms over several polls, and never thinks about
# it again. Right for a Potion; for an item that gates the map it has two structural gaps. It only ever ADDS, so
# nothing removes a key item the player was never given -- and with key-item shuffle on the game still hands out the
# Machine Part at the Gateon parts shop and other key items from NPCs, which ISO patching cannot dummy out. And a
# confirmed write is permanent in the bookkeeping, not in the save, so an item that later leaves the Bag is never put
# back. A reconciler has neither gap because it holds no history: every poll it asks whether the Bag agrees with what
# Archipelago says this player owns, and fixes whichever way it disagrees.
#
# One behaviour worth knowing: a key item the player USES comes back. The ID Card is consumed on use (confirmed live)
# and a reconciler writes it again within a poll, which for a gating item is the safer direction but does mean these
# items stop behaving like consumables. Never guesses: an unresolvable pocket, an unreadable quantity or a failed
# write leaves the id alone for this tick.


@dataclass
class KeyItemReconciler:
    """Makes the Bag's key items match what Archipelago says the player owns. See the section comment above.

    Counters are cumulative and per id, so `!keyitems` can show an id being fought over -- a write and a clear
    both climbing on one id means the should-have set disagrees with itself, a bug in the caller."""

    writes: "dict[int, int]" = field(default_factory=dict)
    clears: "dict[int, int]" = field(default_factory=dict)
    failures: int = 0
    polls: int = 0
    # Clears that were issued and did NOT stick -- the item was still readable afterwards. Counted apart from
    # `failures` (an exception) because a write that lands nowhere raises nothing.
    clears_that_did_not_stick: "dict[int, int]" = field(default_factory=dict)
    # Where each managed id was last SEEN, as {item_id: (pocket_base, quantity)} -- answers "is the Machine Part
    # where we think it is" without another round of guessing.
    last_seen_in: "dict[int, tuple[int, int]]" = field(default_factory=dict)

    def poll(self, block_base: int, should_have: "frozenset[int] | set[int]",
             managed: "frozenset[int] | set[int]") -> "tuple[tuple[int, ...], tuple[int, ...]]":
        """Returns (ids written this tick, ids cleared this tick) -- both usually empty, which is the point: once
        the Bag agrees with Archipelago, a poll only reads.

        The SEARCH is wide and the WRITE is narrow. Every window in `key_item_search_windows` is read and a clear
        is issued against each one that actually holds the id, so an item the game filed somewhere other than the
        routed pocket is still found and removed. Writes go to the routed pocket only."""
        self.polls += 1
        written: "list[int]" = []
        cleared: "list[int]" = []
        for item_id in sorted(managed):
            pocket = resolve_item_pocket(block_base, item_id)
            if pocket is None:
                continue   # no known pocket for this id -- nothing this client can honestly do
            pocket_base, max_slots = pocket
            windows = key_item_search_windows(block_base, item_id)
            try:
                held: "list[tuple[int, int, int]]" = []      # (base, slots, quantity) for windows holding it
                quantity = 0
                for window_base, window_slots in windows:
                    found = find_item_quantity(window_base, window_slots, item_id)
                    if found > 0:
                        held.append((window_base, window_slots, found))
                        quantity += found
            except Exception:
                self.failures += 1
                continue
            self.last_seen_in[item_id] = (held[0][0], quantity) if held else (0, 0)
            try:
                if item_id in should_have:
                    if quantity <= 0:
                        give_item(pocket_base, item_id, 1, max_slots)
                        self.writes[item_id] = self.writes.get(item_id, 0) + 1
                        written.append(item_id)
                elif held:
                    # Verified, and across every window that held it. `clear_item` alone reports success for a
                    # write it merely issued, which is how a clear count could climb once a second beside an item
                    # that never left the Bag.
                    stuck = False
                    for window_base, window_slots, _found in held:
                        result = clear_item_verified(window_base, window_slots, item_id)
                        if result is True:
                            stuck = True
                        elif result is False:
                            self.clears_that_did_not_stick[item_id] = (
                                self.clears_that_did_not_stick.get(item_id, 0) + 1
                            )
                    if stuck:
                        self.clears[item_id] = self.clears.get(item_id, 0) + 1
                        cleared.append(item_id)
            except Exception:
                self.failures += 1
                continue
        return tuple(written), tuple(cleared)

    def describe(self, should_have: "frozenset[int] | set[int]" = frozenset(),
                 managed: "frozenset[int] | set[int]" = frozenset(),
                 block_base: int = 0) -> "list[str]":
        from .game_data import key_items

        if not managed:
            return ["Key-item reconciliation is off for this seed (it needs Key Item Shuffle)."]
        lines = [f"Key-item reconciliation: {self.polls} poll(s), "
                 f"{sum(self.writes.values())} write(s), {sum(self.clears.values())} clear(s)"
                 + (f", {self.failures} read/write failure(s)" if self.failures else "") + "."]
        for item_id in sorted(managed):
            key_item = key_items.KEY_ITEM_BY_GAME_ID.get(item_id)
            name = key_item.name if key_item is not None else f"item {item_id}"
            owned = "OWNED" if item_id in should_have else "not received"
            # WHERE it was last seen, not just how many times we acted on it: "we kept it on purpose", "we looked
            # in the wrong place" and "we cleared it and the write did not land" used to print the same line.
            seen = self.last_seen_in.get(item_id)
            if seen is None:
                where = "not looked at yet"
            elif seen[1] <= 0:
                where = "not in the Bag"
            else:
                where = f"in the {pocket_label(block_base, seen[0])} pocket x{seen[1]}"
            lines.append(f"  {name} (id {item_id}): {owned}; {where}; "
                         f"{self.writes.get(item_id, 0)} written, {self.clears.get(item_id, 0)} cleared")
            stuck = self.clears_that_did_not_stick.get(item_id, 0)
            if stuck:
                lines.append(f"      WARNING: {stuck} clear(s) were issued and the item was still there "
                             f"afterwards -- the write is not landing.")
        return lines


@dataclass
class KraneMemoTracker:
    """Awards a memo's location once the story byte says the game has handed it over, and clears the game's own copy
    out of the Bag so only Archipelago-delivered memos count toward this world's region gating.

    Threshold is `>=`, not `==`, so a player who connects mid-playthrough or blows past 0x10 between two polls still
    gets everything earned -- these are the progression-gating locations, so stranding one is worse here than anywhere
    else. Sending and clearing are independent: the location is reported the moment the threshold is crossed and the
    Bag clear is retried every poll, because the story byte can tick over a frame before the item write lands and a
    check that waited on a successful clear could be lost to a transient failure.

    Clearing is idempotent and bounded: `clear_item` returns False both for "already cleared" and "not there yet",
    which RAM cannot distinguish, so retries stop after `CLEAR_ATTEMPTS` polls. Gated by the caller on the
    block-stability check, like every other Bag reader/writer."""

    awarded: set = None          # type: ignore[assignment]  # memo numbers whose location has been sent
    cleared: set = None          # type: ignore[assignment]  # memo numbers confirmed gone from the Bag
    _clear_attempts: dict = None  # type: ignore[assignment]
    cleared_count: int = 0

    CLEAR_ATTEMPTS: int = 30

    def __post_init__(self) -> None:
        if self.awarded is None:
            self.awarded = set()
        if self.cleared is None:
            self.cleared = set()
        if self._clear_attempts is None:
            self._clear_attempts = {}

    def poll(self, block_base: int, story_byte: "int | None") -> "list[str]":
        """Returns the memo location names newly earned this poll. Never raises."""
        newly_awarded: list[str] = []
        if story_byte is None:
            return newly_awarded

        for memo_number, threshold in sorted(KRANE_MEMO_STORY_THRESHOLDS.items()):
            if story_byte < threshold:
                continue
            if memo_number not in self.awarded:
                self.awarded.add(memo_number)
                newly_awarded.append(krane_memo_location_name(memo_number))
            self._try_clear(block_base, memo_number)
        return newly_awarded

    def award_now(self, location_names: "tuple[str, ...]") -> "list[str]":
        """Mark these memo locations awarded out of band and return the ones not already sent.

        The HQ Lab bump skips the tier the memo handover sits behind, so the checks have to go out at the moment of
        the skip rather than when the threshold is eventually witnessed. Marking them here stops `poll` sending
        them again; it deliberately does NOT touch the Bag clear, which still waits for the ordinary threshold --
        clearing an item the player has not been given yet would just burn retries."""
        by_name = {krane_memo_location_name(n): n for n in KRANE_MEMO_STORY_THRESHOLDS}
        newly: "list[str]" = []
        for name in location_names:
            number = by_name.get(name)
            if number is None:
                continue          # not a memo location -- a future bump may award other things
            if number in self.awarded:
                continue
            self.awarded.add(number)
            newly.append(name)
        return newly

    def _try_clear(self, block_base: int, memo_number: int) -> None:
        if memo_number in self.cleared:
            return
        attempts = self._clear_attempts.get(memo_number, 0)
        if attempts >= self.CLEAR_ATTEMPTS:
            return
        self._clear_attempts[memo_number] = attempts + 1
        try:
            removed = clear_item(
                block_base + KEY_ITEMS_OFFSET,
                KEY_ITEMS_MAX_SLOTS,
                KRANE_MEMO_GAME_ITEM_IDS[memo_number],
            )
        except Exception:
            return
        if removed:
            self.cleared.add(memo_number)
            self.cleared_count += 1

    def describe(self) -> str:
        if not self.awarded:
            return (
                "Krane Memos: none awarded yet. The client sends these when your story byte reaches "
                f"0x{KRANE_MEMO_STORY_THRESHOLDS[1]:02X} (memos 1-2) and "
                f"0x{KRANE_MEMO_STORY_THRESHOLDS[3]:02X} (memos 3-5)."
            )
        awarded = ", ".join(str(n) for n in sorted(self.awarded))
        pending = sorted(set(self.awarded) - self.cleared)
        lines = [f"Krane Memos: checks sent for {awarded}. Removed from your Bag: {self.cleared_count}."]
        if pending:
            lines.append(
                "Still trying to remove from the Bag: "
                + ", ".join(
                    f"{n} ({self._clear_attempts.get(n, 0)}/{self.CLEAR_ATTEMPTS} polls)" for n in pending
                )
                + " -- a memo you never physically received will simply time out; the check still stands."
            )
        return " ".join(lines)


# --- The manual story-byte write log. ---
# The story byte advances two ways: the GAME advances it by playing, and the CLIENT overwrites it. Only the second is
# logged here, and exactly four places do it -- `AreaStoryByteMemory.poll`'s map-screen pre-load write,
# `StoryByteOverride._apply` and `._restore`, and `LiveStoryByteBumper.poll`. `grep` for
# `STORY_RECORD_OFFSET + STORY_BYTE_OFFSET` is the fence: a write site that does not call `record()` is a bug, and a
# test asserts the count.
#
# The log lives at the write site rather than being rebuilt from the client's chat notes, which are formatted for a
# human, dropped on restart, and absent for some writes -- recording inside the `try` that performs the write means
# an entry exists if and only if bytes went into the game. A diagnostic, not state: nothing reads it back, so every
# method swallows rather than raises. Bounded to the most recent `MAX_ENTRIES`, while `total` counts every write ever
# recorded so a trimmed log says how many it dropped.


@dataclass(frozen=True)
class StoryByteWrite:
    """One story-byte overwrite performed by the client."""

    seq: int
    when: float                 # time.time() at the moment of the write
    source: str                 # which mechanism wrote it
    context: str                # the area or room the write was about
    was: "int | None"           # the value that was there, None when it could not be read
    now: int                    # the value written
    why: str

    def describe(self) -> str:
        stamp = time.strftime("%H:%M:%S", time.localtime(self.when))
        before = "??" if self.was is None else f"{self.was:02X}"
        return (f"  #{self.seq} {stamp}  0x{before} -> 0x{self.now:02X}  "
                f"[{self.source}] {self.context} -- {self.why}")


@dataclass
class StoryByteWriteLog:
    """The running list of every story-byte overwrite this client has performed. See the section comment."""

    MAX_ENTRIES: ClassVar[int] = 500

    entries: "list[StoryByteWrite]" = field(default_factory=list)
    total: int = 0               # every write ever recorded, including ones trimmed out of `entries`
    dropped: int = 0             # how many were trimmed
    dirty: bool = False

    def record(self, source: str, context: str, was: "int | None", now: int,
               why: str) -> "StoryByteWrite | None":
        """Append one entry. Never raises -- a logging failure must not disturb a write that already happened."""
        try:
            self.total += 1
            entry = StoryByteWrite(seq=self.total, when=time.time(), source=source, context=context,
                                   was=was, now=int(now) & 0xFF, why=why)
            self.entries.append(entry)
            while len(self.entries) > self.MAX_ENTRIES:
                self.entries.pop(0)
                self.dropped += 1
            self.dirty = True
            return entry
        except Exception:
            return None

    def describe(self, limit: "int | None" = None) -> "list[str]":
        if not self.entries:
            if self.total:
                return [f"Manual story-byte overwrites: {self.total} recorded, but none are still in the "
                        f"list (all {self.dropped} were trimmed)."]
            return ["Manual story-byte overwrites: none yet. The client has not written the story byte this "
                    "run -- the game's own progress is not counted here, only our overwrites."]
        shown = self.entries if limit is None else self.entries[-limit:]
        head = f"Manual story-byte overwrites: {self.total} total"
        if self.dropped:
            head += f" ({self.dropped} older entries trimmed)"
        if len(shown) != len(self.entries):
            head += f", showing the last {len(shown)}"
        lines = [head + "."]
        lines.extend(entry.describe() for entry in shown)
        by_source: "dict[str, int]" = {}
        for entry in self.entries:
            by_source[entry.source] = by_source.get(entry.source, 0) + 1
        lines.append("  by source: " + ", ".join(f"{name} {count}x"
                                                 for name, count in sorted(by_source.items())))
        return lines

    def to_json(self) -> dict:
        return {
            "total": self.total,
            "dropped": self.dropped,
            "entries": [{"seq": e.seq, "when": e.when, "source": e.source, "context": e.context,
                         "was": e.was, "now": e.now, "why": e.why} for e in self.entries],
        }

    def load_json(self, data: dict) -> None:
        """Tolerant: a corrupt or hand-edited file degrades to an empty log rather than taking the client down.
        Nothing depends on this file being readable."""
        try:
            entries: "list[StoryByteWrite]" = []
            for row in (data.get("entries") or []):
                try:
                    was = row.get("was")
                    entries.append(StoryByteWrite(
                        seq=int(row["seq"]), when=float(row["when"]), source=str(row["source"]),
                        context=str(row["context"]), was=None if was is None else int(was),
                        now=int(row["now"]) & 0xFF, why=str(row.get("why", "")),
                    ))
                except Exception:
                    continue  # one malformed row must not cost the whole log
            self.entries = entries[-self.MAX_ENTRIES:]
            self.total = max(int(data.get("total") or 0), len(entries))
            self.dropped = max(int(data.get("dropped") or 0), 0)
            self.dirty = False
        except Exception:
            self.entries = []
            self.total = 0
            self.dropped = 0
            self.dirty = False


# --- Live in-area story-byte bumps. ---
# The rule and its reasoning are data, in game_data/story_bytes.LIVE_STORY_BYTE_BUMPS. This class is only the
# mechanism: read the room, read the byte, write once, log it -- the fourth story-byte write site. It cannot loop,
# because the window is half-open (`when <= live < becomes`), so the moment the write lands the bump no longer
# applies; `_last_written` is belt-and-braces for a write that somehow does not take.


@dataclass
class LiveStoryByteBumper:
    """Raises the live story byte while the player stands inside a region that declares a bump.

    Never writes on a guess: an unknown room, an unresolvable region and an unreadable byte each decline. Never
    lowers anything -- the table's own fence guarantees `becomes > when_byte_is`."""

    write_log: "StoryByteWriteLog | None" = None

    applications: int = 0
    declined_write_failed: int = 0
    last_region: "str | None" = None
    _last_written: "tuple[str, int] | None" = None   # (region, value) of our most recent successful write
    # The ONE ownership channel (`Client._claim_story_write`). This writer used to have Client.py reach in and set
    # the area memory's `last_written_target` by hand after the call, which worked only while the call had one
    # site. It now has two -- the second is the vanilla-travel branch, where there is no area memory poll to
    # piggyback on -- so it declares ownership the way every other writer does.
    last_written_value: "int | None" = None
    #: Location names the bump that just fired declares it skipped past. Set on every successful write (to () when
    #: the bump awards nothing), so a caller reading it after a None poll cannot resend the previous bump's list.
    last_awarded_locations: "tuple[str, ...]" = ()

    def poll(self, block_base: int, current_region: "str | None", story_byte: "int | None",
             travel_shuffle: bool, scooter_shuffle: bool) -> "tuple[int, str] | None":
        """One tick. Returns `(new_byte, note)` when it writes, else None.

        The new byte is returned rather than left for the caller to re-read: the caller already holds the value it
        read this tick, and handing back the written one keeps everything downstream -- the area memory's
        high-water mark above all -- from recording the value we just replaced.

        `travel_shuffle` and `scooter_shuffle` are the seed's own options and are REQUIRED: a bump's gate decides
        whether it exists for this seed at all, and a default here would let a caller silently turn a bump on in a
        mode the player excluded."""
        from .game_data import story_bytes

        bump = story_bytes.live_bump_for(current_region, story_byte, travel_shuffle, scooter_shuffle)
        self.last_region = current_region
        if bump is None:
            return None
        if self._last_written == (bump.region, bump.becomes) and story_byte == bump.when_byte_is:
            # We already wrote this and the game put the old value straight back. Something else owns this byte;
            # fighting it every tick would be worse than declining and saying so.
            self.declined_write_failed += 1
            return None
        try:
            poke_story_byte(block_base, bump.becomes & 0xFF)
        except Exception:
            return None
        self.applications += 1
        self._last_written = (bump.region, bump.becomes)
        self.last_written_value = bump.becomes   # ADDENDUM 293 -- claimed by Client._claim_story_write
        self.last_awarded_locations = tuple(bump.awards_locations)   # ADDENDUM 304
        if self.write_log is not None:
            self.write_log.record("live bump", bump.region, story_byte, bump.becomes, bump.what)
        return (bump.becomes,
                f"Story byte bumped on the spot: {bump.region} 0x{story_byte:02X} -> 0x{bump.becomes:02X} "
                f"({bump.what}).")

    def describe(self) -> "list[str]":
        from .game_data import story_bytes

        lines = [f"Live in-area story-byte bumps: {self.applications} applied."]
        for bump in story_bytes.LIVE_STORY_BYTE_BUMPS:
            # The gate is printed because a bump can be entirely inert for a seed, and "declared but never fires"
            # and "fired and nothing happened" look identical without it.
            gate = bump.gate
            if gate.with_travel_shuffle and gate.with_vanilla_travel:
                when = ("every seed" if not gate.vanilla_needs_scooter_shuffle
                        else "location shuffle always, vanilla travel only with the Scooter shuffled")
            elif gate.with_travel_shuffle:
                when = "location shuffle only"
            elif gate.with_vanilla_travel:
                when = "vanilla travel only"
            else:
                when = "never -- this bump's gate allows no seed"
            lines.append(f"  {bump.region}: 0x{bump.when_byte_is:02X}-0x{bump.becomes - 1:02X} "
                         f"-> 0x{bump.becomes:02X} [{when}] -- {bump.what}")
        if self.declined_write_failed:
            lines.append(f"  declined (the value came back after we wrote it): {self.declined_write_failed}")
        return lines


# --- Story-byte override: lift the byte on entering Gateon with enough Robo Kyogre Parts, restore on leaving. ---
# Built as a general save-and-restore mechanism with one wiring rather than a Gateon special case, because the
# eventual shape is per-area. The "unless" clause is the general rule: on leaving, restore the remembered value ONLY
# if the live byte has not moved past it, because a restore that clobbered genuine progress is far worse than one
# that declines. Two things about writing this byte: `read_story_byte` REJECTS 0xFF, so this class tracks its own
# override state rather than reading back what it wrote; and it is SAVE DATA, so saving while overridden bakes the
# value in -- hence off by default and restoring as early as it can.
#
# STORY_OVERRIDE_VALUE was corrected twice and the history is the lesson. 0x6E came from the ladder's "Robo Kyogre
# unlocked" transition and did NOT let the player ride: the ladder records what the byte READS AFTER an event, not
# what the game CHECKS to allow one. A live bisection found 0x77 rides -- but 0x77 covers story values 952..959 and
# the game only ever holds multiples of ten, so it is a WINDOW above the last real rung rather than a rung, which is
# why it bisected so cleanly. 0x76 IS the rung: 0x76 * 8 = 944, and 950 is the multiple of ten inside it. The
# bisection bounds the gate both ways -- 0x6E (880) did not ride, 0x77 did -- so it opens in (880, 950], and 950 is
# the only value in that range the game can be on. It must also stay below victory (0x78 -> 960).
STORY_OVERRIDE_VALUE = 0x76

# The story byte at or past which this seed is won, whatever route got the player there. The trainer-defeat path
# can miss -- a roster read landing mid-update, a battle ending unusually -- and a missed win is the one failure a
# player cannot work around. The byte advances on its own as the credits run, so it is the backstop.
VICTORY_STORY_BYTE = 0x78

# The override must never be able to send the goal: an override at or above victory would complete the seed for
# any player holding eight Parts the instant they hovered Gateon -- irreversible, from a write this client made on
# their behalf. Asserted at import rather than in a test, because the failure is silent and instant and the two
# numbers are far apart.
assert STORY_OVERRIDE_VALUE < VICTORY_STORY_BYTE, (
    f"STORY_OVERRIDE_VALUE (0x{STORY_OVERRIDE_VALUE:02X}) must stay below VICTORY_STORY_BYTE "
    f"(0x{VICTORY_STORY_BYTE:02X}) -- the Robo Kyogre override would otherwise send this seed's goal"
)

# --- The Gateon gate needs a CEILING, not just a lift. ---
# Without the Parts this client wrote nothing, so the gate was really "the game will not offer the Robo Kyogre
# because your own story byte has not reached it" -- which stops being true the moment ordinary play reaches it. So
# the byte inside Gateon is clamped to 0x6E, the highest value that still cannot ride.
#
# 0x6C would be wrong even though it is lower: 0x6C -> 0x6E is "Robo Kyogre unlocked, Gateon shop restocked, Master
# Ball chest open", so holding at 0x6C also un-restocks the shop and closes the Master Ball chest, both of which
# carry real AP locations. That is blocking checks to enforce a gate. And the ladder misleads the other way -- that
# transition is annotated `opens_regions=("Citadark Isle",)`, but the live bisection confirmed 0x6E cannot ride, so
# the ceiling comes from the measurement and not the table beside it.
#
# THIS IS THE ONLY THING THIS CLIENT DOES THAT CAN LOSE PROGRESS: a clamp writes a LOWER number into save data, so a
# crash or a save-and-quit inside Gateon leaves the player's story behind. Three answers: the same save/restore the
# override uses (the map hover restores too, so the byte is only low inside Gateon rooms); a persisted record written
# the moment the clamp lands, so a reconnect finding the byte still at our clamp value puts it back; and a hard fence
# at victory, since VICTORY_STORY_BYTE is the backstop for a missed final fight and clamping it away would be
# permanent once they save.
GATEON_STORY_CEILING = 0x6E

# Asserted rather than tested for the same reason: the failure is silent and the numbers are far apart.
assert GATEON_STORY_CEILING < STORY_OVERRIDE_VALUE, (
    f"GATEON_STORY_CEILING (0x{GATEON_STORY_CEILING:02X}) must stay below STORY_OVERRIDE_VALUE "
    f"(0x{STORY_OVERRIDE_VALUE:02X}) -- a ceiling at or above the ride threshold gates nothing"
)
# The ceiling is the ONLY value this client writes without the Parts, and the point of the Parts is that the ride
# threshold is reached by holding them rather than by playing.
assert GATEON_STORY_CEILING != STORY_OVERRIDE_VALUE, "the ceiling must never be the unlock value"
assert GATEON_STORY_CEILING < VICTORY_STORY_BYTE, (
    f"GATEON_STORY_CEILING (0x{GATEON_STORY_CEILING:02X}) must stay below VICTORY_STORY_BYTE "
    f"(0x{VICTORY_STORY_BYTE:02X})"
)

# --- Gateon's room set is DERIVED from the region table, plus room 147. ---
# Two independently-maintained descriptions of the same fact drifted. Typed as {147, 153, 156} from an early
# compilation, while `chest_regions.ROOM_TO_REGION` calls {146, 153, 156, 158, 160} Gateon Port -- and neither
# contained the other, so 146 (Krabby Klub basement), 158 (Tower 1F) and 160 (Tower 3F) did nothing, silently, with
# every Part in hand. 147 (the building by the entrance) is kept rather than dropped: the region table came from a
# compilation of rooms holding chests and story bytes and 147 holds neither, so its absence there is not evidence.
def _gateon_room_ids() -> "frozenset[int]":
    from .game_data import chest_regions

    from_region_table = {
        room for room, region in chest_regions.ROOM_TO_REGION.items() if region == "Gateon Port"
    }
    return frozenset(from_region_table | {147})


GATEON_ROOM_IDS: "frozenset[int]" = _gateon_room_ids()


# --- Citadark Isle enters at 0x71. ---
# The Parts override lifts the byte in Gateon and saves what was there -- in travel mode Gateon's own remembered
# area byte, an early value. The Robo Kyogre ride leaves Gateon, and `poll` read "not in a Gateon room, override
# active" as the ordinary walk-out and RESTORED that saved byte as the island loaded, so Citadark loaded at 0x15 and
# its trainers did not start their fights. Citadark has no map icon, so nothing else ever wrote a floor for it.
#
# Two writes, both raise-only: ARRIVAL writes max(0x71, the byte it saved) instead of restoring and lets go, and the
# FLOOR raises a known Citadark room below 0x71 up to it (a reload on the island, a session that started there).
#
# The region table knows Citadark's CHEST rooms only and the Robo Kyogre dock may not be one, so arrival is also
# recognised by shape: the first real room after a Gateon room, reached WITHOUT passing the map screen (every
# walk-out of Gateon goes through the map; the ride is the one exit that does not), outside Gateon's own room-id
# neighbourhood, and not a room the region table files anywhere else.
CITADARK_ENTRY_FLOOR = 0x71
CITADARK_REGION = "Citadark Isle"
_GATEON_ROOM_NEIGHBOURHOOD = range(140, 166)


def _citadark_room_ids() -> "frozenset[int]":
    from .game_data import chest_regions

    return frozenset(room for room, region in chest_regions.ROOM_TO_REGION.items() if region == CITADARK_REGION)


CITADARK_ROOM_IDS: "frozenset[int]" = _citadark_room_ids()


def looks_like_citadark_arrival(room_id: int) -> bool:
    """A room reached straight from Gateon without the map screen -- see the section comment above."""
    from .game_data import chest_regions

    if room_id in CITADARK_ROOM_IDS:
        return True
    if room_id == MAP_SCREEN_ROOM_ID or room_id in GATEON_ROOM_IDS or room_id in _GATEON_ROOM_NEIGHBOURHOOD:
        return False
    return chest_regions.region_for_room(room_id) is None


assert GATEON_STORY_CEILING < CITADARK_ENTRY_FLOOR < STORY_OVERRIDE_VALUE < VICTORY_STORY_BYTE
assert not (CITADARK_ROOM_IDS & GATEON_ROOM_IDS)


# --- The Snagem hideout LOADS at 0x63 and FIGHTS at 0x62. ---
# A hold, not a floor. Every other story-byte writer here raises and leaves the value raised; this one LOWERS, so it
# uses the same save-and-restore shape as the Gateon ceiling -- remember what was there, write 0x62 for the duration
# of the fight, put the player's own value back the moment the fight ends or they leave. Nothing is left lowered.
#
# The trigger is a FIGHT, not a room: standing in the hideout keeps 0x63 so the rooms still build from the byte they
# need. Exemptions come from `story_bytes.SNAGEM_BATTLE_EXEMPT_SURNAMES`, derived from the deck's own story order and
# matched by upper-case surname off the live roster. An unreadable roster DECLINES, which leaves the player's own
# byte -- for a writer that lowers, the safe direction, since the failure is only "a grunt did not start his fight".
SNAGEM_REGION = "Snagem Hideout"


def _snagem_room_ids() -> "frozenset[int]":
    from .game_data import chest_regions

    return frozenset(room for room, region in chest_regions.ROOM_TO_REGION.items() if region == SNAGEM_REGION)


SNAGEM_ROOM_IDS: "frozenset[int]" = _snagem_room_ids()


# --- The Snagem 2F encounter: what gates it, and the one byte we patch. ---
# Decompiled out of `S2_building_2F_2`'s bytecode: the encounter never reads the per-area story byte this project
# writes. It reads a global story variable and a flag, neither of which this project can locate, so we patch the
# consumer:
#
#   `hero_main` (a POLLING LOOP -- its last instruction jumps back to its own top):
#       if NOT(story >= 790):                          exit        <- the gate, a global story variable
#       call snatchdan_battle_check
#       CALL 0x19(player, 17.0, 130.0, 14.0, 99.0)                 a position test
#       if result == 1:                                exit
#       set_flag(2280, 1) ; set_flag(2279, 0)
#       instr 356:  call gonza_battle      -- branches on flag(1293):
#                       flag set   -> instr 663:  call yachino_battle (WAKIN), then the face-off scene
#                       flag clear -> instr 440:  Gonzap alone, Wakin skipped
#       instr 358:  call snatch_put        -- the fade, and the Snag Machine
#
# 790 is the ladder's "Snagem Hideout opens (after Secc mail)". The position test needs nothing from us: the
# stairs spawn the player inside the zone, which is why the fight normally fires on entering the room.
#
# So the patch is ONE byte:
#
#   +0x0797   0x67 -> 0x42   instr 321's JUMPIF target, redirected from the exit onto the next instruction, so
#                            the story gate's bail-out does nothing.
#
# Two earlier patches were RETRACTED. They forced instr 439's JUMPIF into an unconditional JUMP and replaced instr
# 355's line marker with a SCRIPTCALL, to explain a hard freeze on the fade after Gonzap. Six MEM1 dumps settled it:
# the first frozen dump has instr 355 at `10 00 00 ea` and instr 439 at `0b 00 02 97`, both STOCK, and all four
# frozen dumps share one script-VM state (pc at instr 1055, one frame returning to instr 357). The difference was
# SAVE DATA, at story record `+0x37..+0x84`:
#
#     both runs that completed:   00 00 08 00 00 00 00 00 | ff x14 | 00 x56
#     all four freezes:           ff x78
#
# Six for six, whatever the script bytes were. This project filled that range with 0xFF during its own bit-bisection
# and never restored it, and it persisted in the player's savestate. `SnagemRecordRepair` puts it back, only when it
# is all-0xFF; with the record repaired, `gonza_battle`'s flag-1293 branch calls `yachino_battle` by itself.
#
# STAGING. `preprocess` runs on map load and picks between the only two arrangements in the script, with a single
# JUMPIF at instr 158:
#
#   a   Wakin  (actor 136) at x=1.86  z=85.30  facing 45.8
#       Gonzap (actor 135) at x=14.52 z=79.75  facing 85.4        <- instrs 159..198
#   b   Gonzap (actor 135) at x=5.52  z=103.75; Wakin not moved   <- instrs 200..219
#
# Forcing `a` retargets the JUMPIF to instr 159 so it falls through -- it still pops its condition, so no stack
# imbalance. Forcing `b` turns instr 159's line marker into `JUMP -> 200`, replacing a debug-only instruction with no
# stack effect. Never both: the selector writes one and holds the other at stock.
#
# Live rather than an ISO patch, because the script is re-read from disc on every map entry so a patch has to be
# re-applied anyway, and `hero_main` is a loop so a patch written while the player is in the room takes effect next
# tick. Staging is the exception -- `preprocess` runs only on map load. The story-gate byte is emitted by the LZSS
# compressor as a literal at disc 0x2F68FA60, if that half is ever wanted statically.

SNAGEM_2F_SCRIPT_SIZE = 0x2E90          # the TCOD decompressed-size field that identifies S2_building_2F_2

_CODE0 = 0x290                          # file offset of script instruction 0 (CODE section + 0x20)


def _instr(index: int) -> int:
    """File offset of a script instruction, so the offsets below read as the bytecode we decompiled."""
    return _CODE0 + index * 4


# (offset into the decompressed script, expected byte, patched byte)
SNAGEM_2F_SCRIPT_PATCHES: "tuple[tuple[int, int, int], ...]" = (
    (_instr(321) + 3, 0x67, 0x42),      # +0x0797  story gate: instr 321 JUMPIF target -> the next instruction
)

# Optional staging override, off by default; POKEMON_XD_SNAGEM_STAGE=a|b forces one without a rebuild. With the story
# variable written correctly the game reaches the scene through its own `preprocess`, so this is only for inspecting
# an arrangement on demand.
SNAGEM_2F_STAGE: "str | None" = None

SNAGEM_2F_STAGE_PATCHES: "dict[str, tuple[tuple[int, int, int], ...]]" = {
    # force arrangement a: instr 158's JUMPIF target 200 -> 159, i.e. fall through
    "a": ((_instr(158) + 3, 0xC8, 0x9F),),
    # force arrangement b: instr 159's line marker -> JUMP -> 200
    "b": ((_instr(159) + 0, 0x10, 0x0C), (_instr(159) + 3, 0x7A, 0xC8)),
}


def snagem_2f_stage() -> "str | None":
    """The staging to force, honouring the environment override. Anything unrecognised means "leave alone"."""
    choice = os.environ.get("POKEMON_XD_SNAGEM_STAGE", "").strip().lower() or SNAGEM_2F_STAGE
    return choice if choice in SNAGEM_2F_STAGE_PATCHES else None


def snagem_2f_patches() -> "tuple[tuple[int, int, int], ...]":
    """Every (offset, stock, patched) triple this client will write for the staging currently selected.

    Both staging sites are always included: the unselected one is listed with `patched == stock`, so switching
    stages actively restores the other site rather than leaving two overlapping edits behind."""
    chosen = snagem_2f_stage()
    out = list(SNAGEM_2F_SCRIPT_PATCHES)
    for stage, patches in sorted(SNAGEM_2F_STAGE_PATCHES.items()):
        for offset, stock, patched in patches:
            out.append((offset, stock, patched if stage == chosen else stock))
    return tuple(out)


# ANCHORS -- what must hold before this project writes a byte into a map script.
#
# Measured, not assumed: the resident copy is NOT byte-identical to the disc copy. Across two dumps taken in the room
# on different boots, 156 of 11920 bytes differ, and every one is in 0x0030..0x00C7 (the FTBL name-pointer table,
# which the loader relocates), one byte at 0x021B in HEAD, or 0x2DA1..0x2DAB in GVAR. The entire CODE section
# (0x0270..0x2D80) is identical, which is why patch offsets into it are stable.
#
# Four independent layers, because the cost of a false match is writing into unrelated memory: the container header
# and size field; every one of the nine section tags at its fixed offset; the three SCRIPTCALLs that define the
# encounter's shape, which are never patched so they can be anchored whole and between them pin the function table's
# layout; and the instructions on either side of every patch site. Bytes a patch changes are deliberately NOT
# anchored, which is why some anchors are three bytes or two.
SNAGEM_2F_SCRIPT_ANCHORS: "tuple[tuple[int, bytes], ...]" = (
    (0x0000, b"TCOD"), (0x0004, b"\x00\x00\x2e\x90"),
    (0x0010, b"FTBL"), (0x0200, b"HEAD"), (0x0270, b"CODE"),
    (0x2D80, b"GVAR"), (0x2DB0, b"STRG"), (0x2DD0, b"VECT"), (0x2DF0, b"GIRI"), (0x2E60, b"ARRY"),
    (_instr(356), b"\x07\x00\x01\x73"),     # hero_main    -> 371  gonza_battle
    (_instr(358), b"\x07\x00\x05\x9a"),     # hero_main    -> 1434 snatch_put
    (_instr(664), b"\x07\x00\x04\x20"),     # gonza_battle -> 1056 yachino_battle
    (_instr(157), b"\x01\x31\x00\x00"),     # instr 157  ALU -- the preprocess flag-1293 comparison
    (_instr(158), b"\x0b\x00\x00"),         # instr 158  JUMPIF + target high byte (low byte is ours)
    (_instr(159) + 1, b"\x00\x00"),         # instr 159  line marker's middle bytes (ends are ours)
    (_instr(319), b"\x03\x02\x00\x00"),     # instr 319  loadvar -- immediately before the story gate
    (_instr(320), b"\x01\x30\x00\x00"),     # instr 320  ALU
    (_instr(321), b"\x0b\x00\x01"),         # instr 321  JUMPIF + target high byte (low byte is ours)
    (_instr(438), b"\x01\x31\x00\x00"),     # instr 438  ALU -- the gonza_battle flag-1293 comparison
    (_instr(439), b"\x0b\x00\x02\x97"),     # instr 439  JUMPIF -> 663, left alone since ADDENDUM 342
)

SNAGEM_2F_SCRIPT_MAGIC = SNAGEM_2F_SCRIPT_ANCHORS[0][1]


def looks_like_snagem_2f_script(read: "Callable[[int, int], bytes]", blob: int) -> bool:
    """True when every anchor holds at `blob`. `read` is injected so this can be checked against a dump as easily
    as against live memory."""
    try:
        if struct.unpack(">I", read(blob + 4, 4))[0] != SNAGEM_2F_SCRIPT_SIZE:
            return False
        for offset, expected in SNAGEM_2F_SCRIPT_ANCHORS:
            if read(blob + offset, len(expected)) != expected:
                return False
    except Exception:
        return False
    return True


def find_snagem_2f_script(mem: "bytes | None" = None) -> "int | None":
    """Address of the loaded `S2_building_2F_2` script, or None if it is not resident.

    Found by structure, never by a remembered address -- the blob sat at 0x8099E160 across several boots and is
    still not hardcoded, because the cost of being wrong is writing into unrelated memory. Candidates come from
    the TCOD magic plus the size field, then go through every anchor before being accepted."""
    if mem is None:
        try:
            mem = dump_mem1()
        except Exception:
            return None

    def read_from_dump(address: int, length: int) -> bytes:
        start = address - MEM1_START
        if start < 0 or start + length > len(mem):
            raise IndexError(address)
        return mem[start:start + length]

    index = mem.find(SNAGEM_2F_SCRIPT_MAGIC)
    while index != -1:
        candidate = MEM1_START + index
        if looks_like_snagem_2f_script(read_from_dump, candidate):
            return candidate
        index = mem.find(SNAGEM_2F_SCRIPT_MAGIC, index + 1)
    return None


def snagem_2f_patch_state(blob: int) -> "tuple[bool, bool]":
    """`(all patches already applied, the blob still looks like the script we decompiled)`.

    The second half is the safety check: every patch site must currently hold either the disc byte or the byte we
    would write. Anything else means this is not the script we think it is -- a different build, a different map,
    a blob matched by accident -- and we must not write."""
    try:
        if not looks_like_snagem_2f_script(read_bytes, blob):
            return False, False
        applied = True
        for offset, expected, patched in snagem_2f_patches():
            value = read_bytes(blob + offset, 1)[0]
            if value == patched:
                continue
            if value == expected:
                applied = False
            else:
                return False, False
        return applied, True
    except Exception:
        return False, False


def patch_snagem_2f_script(blob: int) -> "int | None":
    """Apply the patches. Returns how many bytes were written, or None if the blob failed validation.

    Zero is normal: the script is already patched and this poll had nothing to do."""
    applied, recognised = snagem_2f_patch_state(blob)
    if not recognised:
        return None
    if applied:
        return 0
    written = 0
    try:
        for offset, expected, patched in snagem_2f_patches():
            if patched != expected and read_bytes(blob + offset, 1)[0] == expected:
                write_bytes(blob + offset, bytes([patched]))
                written += 1
    except Exception:
        return written
    return written


def restore_snagem_2f_script(blob: int) -> "int | None":
    """Put every patch site back to its stock byte. Returns how many bytes were written, or None if the blob
    failed validation.

    This is what lets the player leave the room. The story gate is the only thing stopping `hero_main` -- a LOOP
    -- from re-running the encounter every tick the player stands in the zone. Vanilla stops repeating because
    `snatch_put` sets the story variable to 800 at instr 2104, making the gate false; our patch forces that gate
    true, so the vanilla stop cannot work and the fight restarts forever. Undoing the patch restores vanilla
    behaviour on the loop's next iteration."""
    _applied, recognised = snagem_2f_patch_state(blob)
    if not recognised:
        return None
    written = 0
    try:
        for offset, expected, patched in snagem_2f_patches():
            if patched != expected and read_bytes(blob + offset, 1)[0] == patched:
                write_bytes(blob + offset, bytes([expected]))
                written += 1
    except Exception:
        return written
    return written


# --- The patch has to stop, and the stop has to survive a reload. ---
# STOPPING: `hero_main` is a polling loop whose last instruction jumps back to its own top, so the only thing that
# ends the encounter is its gate going false. Vanilla ends it by advancing the story variable -- instr 2104 of
# `snatch_put` is `CALL 0x83(800, 964)`, a rung past the 790 the gate tests -- but our patch forces that gate true
# for as long as it is applied, so the client performs the stop itself by removing the patch.
#
# PERSISTING: an in-memory bool dies with the client and the script blob is re-read from disc on every map entry, so
# the stop must be re-derivable from SAVE state. `snatch_put` hands the player the Snag Machine and in vanilla there
# is no other way to get it, so "owned" is a sound, reload-proof "already done". A beaten-Gonzap surname from the
# defeat tracker is the second signal, because the Snag Machine flips only at the very end of the scene. The AP check
# for "Defeat - Snagem Head Gonzap" is deliberately not used: it does not exist in cumulative trainer-defeat mode.

SNAGEM_COMPLETION_SURNAMES: "frozenset[str]" = frozenset({"GONZAP"})


def snagem_force_patch() -> bool:
    """POKEMON_XD_SNAGEM_FORCE=1 keeps patching even once the scene is done, so the encounter can be re-tested
    without stripping the Snag Machine back off."""
    return os.environ.get("POKEMON_XD_SNAGEM_FORCE", "").strip().lower() in ("1", "on", "true", "yes")


def snagem_scene_completed(block_base: "int | None") -> bool:
    """True when the save says this scene has already happened. Reload-proof, because it reads the save.

    `read_snag_machine` returns None when its two sites disagree, which is a "do not know", not a "yes" -- and a
    "do not know" must not stop the patch, or a mid-scene read could strand the player."""
    if block_base is None:
        return False
    try:
        return read_snag_machine(block_base) is True
    except Exception:
        return False


# --- Repairing story record +0x37..+0x84. ---
# SAVE DATA, not a script patch, and a repair of damage this project inflicted (see the six-dump comparison above),
# so the trigger is far tighter than anything else here: the range must be EXACTLY 78 bytes of 0xFF.
#
# That condition does real work. 0xFF is this record's natural "unset" fill -- `+0x12..+0x36` is 0xFF in every dump
# this project holds, including ones that played fine -- so an all-0xFF range is not proof of damage. What makes the
# write defensible is that it is scoped to the Snagem Hideout, happens at most once per session, and writes the exact
# bytes observed in the two dumps where the encounter ran to completion.
#
# OFF BY DEFAULT, and the least-proven thing in this module: a wholesale 0x4E-byte write over a window the bisection
# itself damaged, and the freeze it was built to clear had a different cause (`hero_main` tests
# `storyvar(964) == 790` and the floor was written as 0x63, a byte whose window holds no legal story value).
# POKEMON_XD_SNAGEM_REPAIR=1 applies it.
SNAGEM_RECORD_REPAIR = False
SNAGEM_RECORD_FIX_OFFSET = STORY_RECORD_OFFSET + 0x37
SNAGEM_RECORD_FIX_BYTES = bytes.fromhex("0000080000000000") + b"\xff" * 14 + b"\x00" * 56
SNAGEM_RECORD_DAMAGED = b"\xff" * len(SNAGEM_RECORD_FIX_BYTES)

assert len(SNAGEM_RECORD_FIX_BYTES) == 0x4E, "the repaired window is +0x37..+0x84 inclusive"


def snagem_record_repair_enabled() -> bool:
    override = os.environ.get("POKEMON_XD_SNAGEM_REPAIR", "").strip().lower()
    if override in ("0", "off", "false", "no"):
        return False
    if override in ("1", "on", "true", "yes"):
        return True
    return SNAGEM_RECORD_REPAIR


def snagem_record_state(block_base: int) -> "str | None":
    """`"repaired"`, `"damaged"`, or None when the window is neither -- i.e. leave it alone."""
    try:
        window = read_bytes(block_base + SNAGEM_RECORD_FIX_OFFSET, len(SNAGEM_RECORD_FIX_BYTES))
    except Exception:
        return None
    if window == SNAGEM_RECORD_FIX_BYTES:
        return "repaired"
    if window == SNAGEM_RECORD_DAMAGED:
        return "damaged"
    return None


def repair_snagem_record(block_base: int) -> bool:
    """Write the repaired window, but only over the exact damaged pattern. True when a write happened."""
    if not snagem_record_repair_enabled():
        return False
    if snagem_record_state(block_base) != "damaged":
        return False
    try:
        write_bytes(block_base + SNAGEM_RECORD_FIX_OFFSET, SNAGEM_RECORD_FIX_BYTES)
    except Exception:
        return False
    return snagem_record_state(block_base) == "repaired"


@dataclass
class SnagemScriptPatcher:
    """Keeps the Snagem 2F script patched while the player is in the hideout, and repairs the story record window
    once per session.

    Never raises. Re-applies after every map load, since the script is re-read from disc each entry. Cheap: it
    only looks for the script while the player is in a Snagem room, and once it has the address it checks a
    handful of bytes per poll rather than re-scanning MEM1."""

    blob: "int | None" = None
    applications: int = 0
    writes: int = 0
    rejected: int = 0
    last_room: "int | None" = None
    repaired: bool = False
    gonzap_seen: bool = False
    restored: bool = False

    def note_defeats(self, surnames: "set[str] | None") -> None:
        """Latch the live half of the stop. Sticky, because the tracker only reports a surname on the one poll it
        confirms it."""
        if not surnames:
            return
        try:
            if {s.strip().upper() for s in surnames} & SNAGEM_COMPLETION_SURNAMES:
                self.gonzap_seen = True
        except Exception:
            pass

    def finished(self, block_base: "int | None") -> bool:
        """True once the scene is done and the patch must come back out. `gonzap_seen` is this session's signal,
        `snagem_scene_completed` the reload-proof one; either is enough, and the second still answers tomorrow."""
        if snagem_force_patch():
            return False
        return self.gonzap_seen or snagem_scene_completed(block_base)

    def poll(self, block_base: "int | None", room_id: "int | None",
             defeated_surnames: "set[str] | None" = None) -> "str | None":
        """One tick. Returns a note the first time each fresh load is patched or unpatched, else None."""
        try:
            self.note_defeats(defeated_surnames)
            inside = room_id is not None and room_id in SNAGEM_ROOM_IDS
            if not inside:
                self.blob = None
                self.last_room = room_id
                return None
            notes = []
            if block_base and not self.repaired and repair_snagem_record(block_base):
                self.repaired = True
                notes.append("Snagem story record +0x37..+0x84 repaired -- this window was left filled with "
                             "0xFF by an earlier experiment and is what froze the fade after Gonzap.")
            if self.blob is not None:
                _applied, recognised = snagem_2f_patch_state(self.blob)
                if not recognised:
                    self.blob = None          # the map reloaded somewhere else; re-find it
            if self.blob is None:
                self.blob = find_snagem_2f_script()
            if self.blob is None:
                return "\n".join(notes) if notes else None

            # The stop comes before the patch, so a tick that learns the scene is over never re-applies the byte
            # it is about to remove.
            if self.finished(block_base):
                removed = restore_snagem_2f_script(self.blob)
                if removed is None:
                    self.blob = None
                    self.rejected += 1
                elif removed and not self.restored:
                    self.restored = True
                    notes.append("Gonzap is done -- Snagem 2F script restored to stock. The encounter will "
                                 "not re-trigger, and it stays off across reloads.")
                elif removed:
                    self.restored = True
                return "\n".join(notes) if notes else None

            written = patch_snagem_2f_script(self.blob)
            if written is None:
                self.blob = None
                self.rejected += 1
                return "\n".join(notes) if notes else None
            if written:
                self.applications += 1
                self.writes += written
                self.restored = False
                stage = snagem_2f_stage()
                where = f", staging {stage}" if stage else ""
                notes.append(f"Snagem 2F script patched ({written} byte(s){where}) -- the Wakin and Gonzap "
                             f"fight can start. Removed again automatically once Gonzap is beaten.")
            return "\n".join(notes) if notes else None
        except Exception:
            return None

    def describe(self) -> str:
        where = f"0x{self.blob:08X}" if self.blob else "not resident"
        stage = snagem_2f_stage() or "left to the game's own flags"
        if snagem_force_patch():
            state = "forced on (POKEMON_XD_SNAGEM_FORCE)"
        elif self.restored:
            state = "stopped -- Gonzap done, script restored to stock"
        elif self.gonzap_seen:
            state = "stopping -- Gonzap seen beaten this session"
        else:
            state = "armed"
        return (f"Snagem 2F script: {where}; {state}; patched {self.applications} time(s), {self.writes} "
                f"byte(s) written, {self.rejected} rejected read(s); staging {stage}; record repair "
                f"{'done' if self.repaired else 'not needed this session'}.\n")


assert SNAGEM_ROOM_IDS, "no room maps to the Snagem Hideout, so this hold could never fire"


@dataclass
class SnagemBattleStoryHold:
    """Holds the story byte at 0x62 while a non-exempt Snagem Hideout fight is on, and restores after.

    Never raises. Never leaves the byte lowered: `poll` restores on the first tick the fight is over, the
    player has left the hideout, or the roster stops naming a fight we are holding for."""

    write_log: "StoryByteWriteLog | None" = None

    active: bool = False
    saved_byte: "int | None" = None
    applied_value: "int | None" = None
    last_written_value: "int | None" = None       # the ownership channel -- Client._claim_story_write
    applications: int = 0
    restorations: int = 0
    declined_exempt: int = 0
    declined_no_surname: int = 0
    declined_restores: int = 0
    last_surnames: "tuple[str, ...]" = ()

    def poll(self, block_base: int, room_id: "int | None", in_battle: bool,
             surnames: "set[str] | None") -> "str | None":
        """One tick. `surnames` is the upper-case set on the live battle roster, or None when unknown.

        Returns a note when it writes, else None."""
        from .game_data import story_bytes

        try:
            if not story_bytes.SNAGEM_BATTLE_DROP_NEEDED:
                # The hideout's entry floor and its fighting rung are the same value now, so there is nothing to
                # drop -- and dropping anyway would be worse than useless. Snagem 2F's `hero_main` is
                # `if storyvar(964) == 790`, an equality it re-tests every tick, so putting a player who is
                # already past Gonzap back on 790 would re-arm his scene.
                return self._restore(block_base) if self.active else None
            inside = room_id is not None and room_id in SNAGEM_ROOM_IDS
            if not inside or not in_battle:
                return self._restore(block_base) if self.active else None
            if self.active:
                return self._hold(block_base)
            if not surnames:
                # No roster yet -- the battle flag can lead the records by a tick. Decline rather than write
                # blind: without a name we cannot tell Gonzap from a grunt, and guessing wrong is exactly what
                # the exemption exists to prevent.
                self.declined_no_surname += 1
                return None
            self.last_surnames = tuple(sorted(surnames))
            if surnames & story_bytes.SNAGEM_BATTLE_EXEMPT_SURNAMES:
                self.declined_exempt += 1
                return None
            return self._apply(block_base)
        except Exception:
            return None

    def _apply(self, block_base: int) -> "str | None":
        from .game_data import story_bytes

        current = read_story_byte(block_base)
        if current is None:
            return None   # cannot promise a restore we have nothing to restore to
        target = story_bytes.SNAGEM_BATTLE_FLOOR
        if current <= target:
            return None   # already at or below the fighting rung -- nothing to drop
        if current >= VICTORY_STORY_BYTE:
            # A won game is never clamped, the same rule the Gateon ceiling holds: the victory backstop reads
            # this byte, and lowering it would erase a finished run.
            return None
        poke_story_byte(block_base, target & 0xFF)
        self.saved_byte = current
        self.applied_value = target
        self.last_written_value = target
        self.active = True
        self.applications += 1
        if self.write_log is not None:
            self.write_log.record("snagem battle", SNAGEM_REGION, current, target,
                                  f"fighting {', '.join(self.last_surnames) or 'a Snagem trainer'} -- the "
                                  "grunts' scripts want the rung below the hideout's entry floor")
        return (f"Snagem Hideout fight -- story byte held at 0x{target:02X} (was 0x{current:02X}); your real "
                f"value is put back when the fight ends.")

    def _hold(self, block_base: int) -> "str | None":
        """Still fighting. Catch a value that rose underneath us -- a cutscene mid-fight, or another writer."""
        current = read_story_byte(block_base)
        if current is None or self.applied_value is None or current == self.applied_value:
            return None
        if current >= VICTORY_STORY_BYTE:
            return None
        # Whatever moved it is newer than what we saved, so that becomes the value we owe them back.
        self.saved_byte = max(self.saved_byte or 0, current)
        poke_story_byte(block_base, self.applied_value & 0xFF)
        self.last_written_value = self.applied_value
        return None

    def _restore(self, block_base: int) -> "str | None":
        """The fight is over or the player has left. Put their byte back.

        `active` is cleared AFTER the write: the progress witness reads it to decide whether a value is ours, and
        clearing it first would make our own restore look like the player having earned that rung."""
        saved = self.saved_byte
        current = read_story_byte(block_base)
        if saved is None or current is None:
            self.active = False
            self.saved_byte = None
            self.applied_value = None
            return None
        if current > saved:
            # The game advanced past what we saved -- beating the fight does exactly this. Real progress
            # outranks the remembered value; never drag it back.
            self.declined_restores += 1
            self.active = False
            self.saved_byte = None
            self.applied_value = None
            return None
        if current != saved:
            poke_story_byte(block_base, saved & 0xFF)
            self.last_written_value = saved
            self.restorations += 1
            if self.write_log is not None:
                self.write_log.record("snagem restore", SNAGEM_REGION, current, saved,
                                      "Snagem fight over -- the player's own byte put back")
        self.active = False
        self.saved_byte = None
        self.applied_value = None
        return f"Snagem fight over -- story byte restored to 0x{saved:02X}."

    def describe(self) -> "list[str]":
        from .game_data import story_bytes

        lines = [
            f"Snagem battle story-byte hold: 0x{story_bytes.SNAGEM_BASE_FLOOR:02X} in the rooms, "
            f"0x{story_bytes.SNAGEM_BATTLE_FLOOR:02X} during a fight "
            f"[location shuffle only] -- {self.applications} applied, {self.restorations} restored.",
            f"  exempt (keep 0x{story_bytes.SNAGEM_BASE_FLOOR:02X}): "
            f"{', '.join(sorted(story_bytes.SNAGEM_BATTLE_EXEMPT_SURNAMES))}",
        ]
        if self.active:
            lines.append(f"  HOLDING now for {', '.join(self.last_surnames) or 'an unnamed fight'}; "
                         f"owed back 0x{(self.saved_byte or 0):02X}")
        if self.declined_exempt:
            lines.append(f"  {self.declined_exempt} ticks declined -- an exempt trainer was on the field")
        if self.declined_no_surname:
            lines.append(f"  {self.declined_no_surname} ticks declined -- battle flag up, roster not readable "
                         "yet (we never write without a name)")
        if self.declined_restores:
            lines.append(f"  {self.declined_restores} restores declined -- real progress outranked the "
                         "remembered value")
        return lines


# --- SS Libra's two tiers, and the item that separates them. ---
# SS Libra is one map ICON over two REGIONS (story_bytes.AREA_GROUPS): the stranded first visit and the real ship.
# The ladder names the step between them -- `0x57 -> 0x5A, "scooter upgraded in Gateon"` -- so it is a real story
# event with a real byte, and `items.SCOOTER_ITEM_NAME` stands in for it. The low tier is 0x4E rather than 0x50
# because `0x4E -> 0x50` IS the stranded visit's own cutscene, so entering at 0x50 would skip the visit the low tier
# exists to give you.
#
# AREA_MEMORY_SCHEMA_VERSION is bumped whenever a defect could have written marks indistinguishable from good ones;
# anything older is discarded on load. 1: a committed hover write could become another area's mark. 2: the
# foreign-commit guard, which still EXCUSED a write made for the region the player landed in -- the commonest case.
# 3: our own write is never a mark, in any region.
AREA_MEMORY_SCHEMA_VERSION = 3

SS_LIBRA_STRANDED_FLOOR = 0x4E
SS_LIBRA_SCOOTER_FLOOR = 0x5A

assert SS_LIBRA_STRANDED_FLOOR < SS_LIBRA_SCOOTER_FLOOR, "the stranded tier must sit below the real ship"

# The regions behind the SS Libra icon, derived rather than typed -- the same lesson as GATEON_ROOM_IDS.
def _ss_libra_regions() -> "frozenset[str]":
    from .game_data import story_bytes

    return frozenset(story_bytes.AREA_GROUPS.get("SS Libra", ("SS Libra",)))


SS_LIBRA_REGIONS: "frozenset[str]" = _ss_libra_regions()


# The rooms the ship occupies, derived from the region table rather than hand-written.
def _ss_libra_room_ids() -> "frozenset[int]":
    from .game_data import chest_regions

    return frozenset(room for room, region in chest_regions.ROOM_TO_REGION.items()
                     if region in SS_LIBRA_REGIONS)


SS_LIBRA_ROOM_IDS: "frozenset[int]" = _ss_libra_room_ids()

# Flip to True to make the travel-randomization-OFF hold permanent (never restore the player's real byte on
# leaving). Left False deliberately: `0x57 -> 0x5A` is the only way into 0x5A, so in that mode a byte past it was
# earned in story and a permanent clamp deletes progress rather than closing a hole.
SS_LIBRA_HOLD_IS_PERMANENT = False

# --- Holding the story below the upgrade the Scooter item is supposed to grant. ---
# Serving the STRANDED ship whenever the player lacks the Scooter holds on the map route, because the hover is a
# pre-load hook. It does not hold on a story warp into the ship rooms -- outside the map screen there is no pre-load
# hook, so the room is already built by the time we see it and the clamp only bites on re-entry, leaking one
# real-ship visit.
#
# The fix is not to fight the cutscene: `0x57 -> 0x5A` is the game writing its own byte, and arguing every tick is
# worse than declining. So the cutscene plays out and the story is held one tier BELOW it until the item arrives.
# 0x57 is a HOLD, not a rollback -- every transition past the upgrade is already behind the Scooter in logic (0x5B
# the first fight on the ship, 0x5D the Key Lair, 0x5F the Outskirt Stand, 0x62 Snagem) -- so it does not invent a
# restriction, it makes the GAME agree with the graph the seed was generated against.
SCOOTER_HOLD_FLOOR = 0x57

# The band this will pull back from. 0x58/0x59 are the transition's own passthrough values and 0x5A/0x5B the upgrade
# and the first fight -- all reachable ONLY through the cutscene we are undoing. Above 0x5B the player got past the
# ship by some route this did not model, so the hold gives up rather than destroy real progress. That ceiling is the
# whole safety story: a hold that cannot rewind more than four tiers cannot eat a run.
SCOOTER_HOLD_BAND = (0x58, 0x5B)

# When the item lands, write the upgrade byte rather than making the player replay the Gateon cutscene: the hold
# declined an advance, and this is the same advance granted by the thing meant to grant it.
SCOOTER_GRANT_ON_ARRIVAL = True

assert SCOOTER_HOLD_FLOOR < SCOOTER_HOLD_BAND[0] <= SCOOTER_HOLD_BAND[1] < SS_LIBRA_SCOOTER_FLOOR + 2, (
    "the hold floor must sit below the band it pulls back from, and the band must not reach past the ship"
)
assert SCOOTER_HOLD_BAND[1] < VICTORY_STORY_BYTE, "the hold must never be able to touch a won game"


@dataclass
class ScooterStoryHold:
    """Keeps the story byte below the scooter upgrade until the Scooter Upgrade item arrives.

    Runs in BOTH travel modes and anywhere in the game, unlike everything else here that writes this byte, and
    that is the point: the leak it closes is a story warp into the ship, and a gate watching only the ship's own
    rooms would be watching the wrong place, because by then the room is built. Watching the BYTE means the upgrade
    is undone wherever it happens, before it can be used.

    Never raises. Writes nothing unless the seed turned the option on AND the item is genuinely outstanding."""

    enabled: bool = False          # the seed's `shuffle_scooter_upgrade`
    scooter_held: bool = False     # the item has arrived
    holds: int = 0
    grants: int = 0
    declined_out_of_band: int = 0
    granted_once: bool = False
    write_log: "StoryByteWriteLog | None" = None
    # The value this class last put in the byte, so the readers can tell it from progress. Both writers here were
    # invisible to the ownership test: the HOLD (0x57) could be banked by `observe()` as an area's mark, and the
    # GRANT (0x5A) is a RAISE that `StoryProgressWitness` banked as though the game had produced it, clearing eight
    # `Unlock -` thresholds off a byte this client wrote.
    last_written_value: "int | None" = None

    def poll(self, block_base: int, story_byte: "int | None") -> "str | None":
        if not self.enabled or story_byte is None:
            return None
        try:
            if self.scooter_held:
                return self._grant(block_base, story_byte)
            low, high = SCOOTER_HOLD_BAND
            if story_byte < low:
                return None            # still below the upgrade -- nothing to hold
            if story_byte > high:
                # Past the band -- see SCOOTER_HOLD_BAND. Pulling back from here would be a rollback, not a
                # hold, so decline and say so rather than quietly eating the run.
                self.declined_out_of_band += 1
                return None
            poke_story_byte(block_base, SCOOTER_HOLD_FLOOR & 0xFF)
            self.last_written_value = SCOOTER_HOLD_FLOOR   # ADDENDUM 288
            self.holds += 1
            if self.write_log is not None:
                self.write_log.record("scooter hold", "story", story_byte, SCOOTER_HOLD_FLOOR,
                                      "scooter upgrade is an Archipelago item this slot does not hold yet")
            if self.holds == 1:
                return (f"The scooter upgrade is an Archipelago item in this seed, so the story is held at "
                        f"0x{SCOOTER_HOLD_FLOOR:02X} (was 0x{story_byte:02X}) until the Scooter Upgrade "
                        f"arrives. Nothing is lost -- it is written for you the moment the item lands.")
            return None
        except Exception:
            return None

    def _grant(self, block_base: int, story_byte: int) -> "str | None":
        """The item arrived. Put back the advance the hold declined, once."""
        if not SCOOTER_GRANT_ON_ARRIVAL or self.granted_once:
            return None
        if story_byte != SCOOTER_HOLD_FLOOR:
            # Either they never hit the hold, or they have moved on since. Granting on top of a byte we did not
            # park would be inventing progress.
            self.granted_once = True
            return None
        try:
            poke_story_byte(block_base, SS_LIBRA_SCOOTER_FLOOR & 0xFF)
        except Exception:
            return None
        self.last_written_value = SS_LIBRA_SCOOTER_FLOOR   # ADDENDUM 288 -- an unowned RAISE until now
        self.granted_once = True
        self.grants += 1
        if self.write_log is not None:
            self.write_log.record("scooter grant", "story", story_byte, SS_LIBRA_SCOOTER_FLOOR,
                                  "Scooter Upgrade received -- the held advance granted")
        return (f"Scooter Upgrade received -- story byte advanced to 0x{SS_LIBRA_SCOOTER_FLOOR:02X}. "
                f"The SS Libra is yours; no need to replay the Gateon cutscene.")

    def describe(self) -> str:
        if not self.enabled:
            return "Scooter hold: off for this seed (shuffle_scooter_upgrade is not set)."
        state = "item held" if self.scooter_held else f"holding at 0x{SCOOTER_HOLD_FLOOR:02X}"
        line = f"Scooter hold: {state}. {self.holds} hold write(s), {self.grants} grant(s)"
        if self.declined_out_of_band:
            line += (f", declined {self.declined_out_of_band}x because the byte was past "
                     f"0x{SCOOTER_HOLD_BAND[1]:02X} (a rollback, not a hold)")
        return line + "."


@dataclass
class StoryByteOverride:
    """Writes a story-byte value while the player is inside a set of rooms, and puts back what was there when they
    leave. See the override section comment above for the design and its two caveats.

    Never raises, and never writes unless `armed` -- the caller arms it only when this seed's option is on AND the
    required number of MacGuffins has been received."""

    trigger_rooms: "frozenset[int]" = GATEON_ROOM_IDS
    value: int = STORY_OVERRIDE_VALUE
    # ADDENDUM 255: the map destination whose HOVER also applies this. See `poll_hover`.
    trigger_region: str = "Gateon Port"

    # The other half of the gate: without the Parts the byte is held at or below this while the player is in
    # Gateon. `None` disables clamping entirely and restores lift-only behaviour.
    ceiling: "int | None" = GATEON_STORY_CEILING

    armed: bool = False
    active: bool = False               # currently overridden
    saved_byte: "int | None" = None    # what was there before we entered
    # WHICH value we wrote -- the lift or the ceiling. `_restore` has to recognise its own write to tell it from
    # the player's progress, and getting that wrong in the clamp direction would restore OUR number, not theirs.
    applied_value: "int | None" = None
    applications: int = 0
    restorations: int = 0
    declined_restores: int = 0         # times real progress outranked the remembered value
    # The last value this override wrote. `_restore` and `recover` are both RAISES and both run with `active`
    # already False, so the witness had no way to tell either from the game's own progress.
    last_written_value: "int | None" = None
    clamps: int = 0                    # ADDENDUM 272: applications that lowered the byte rather than raising it
    via_map: bool = False              # ADDENDUM 313: the map screen was seen since the last Gateon room
    citadark_arrivals: int = 0         # ADDENDUM 313
    citadark_floor_writes: int = 0     # ADDENDUM 313
    citadark_arrival_room: "int | None" = None   # ADDENDUM 313: the room the ride landed in, for the table
    declined_clamp_won: int = 0        # ADDENDUM 272: refused to clamp a byte at or past victory

    # Optional so every existing construction of this class keeps working; when supplied, both of this class's
    # writes land in the running overwrite list.
    write_log: "StoryByteWriteLog | None" = None

    def poll(self, block_base: int, room_id: "int | None") -> "str | None":
        """Call once per tick with the current room. Returns a one-line note when it acts, else None."""
        if room_id is None:
            return None  # room unknown -- never guess at a transition, and never write on a guess
        # The map screen is not "outside Gateon". `poll_hover` writes while the cursor rests on Gateon, because the
        # room is built from the byte and the write has to land BEFORE the load -- but the map is room 910, not in
        # `trigger_rooms`, so the next tick would restore the byte before the destination loaded and the hover write
        # would undo itself every time. The map screen is a limbo, not a place: wait for a real room.
        if room_id == MAP_SCREEN_ROOM_ID:
            if self.active:
                self.via_map = True   # ADDENDUM 313: a walk-out, not the Robo Kyogre ride
            return None
        inside = room_id in self.trigger_rooms
        try:
            # The ride to Citadark is not a walk-out -- enter at the island's floor instead.
            if not inside and self.active and not self.via_map and looks_like_citadark_arrival(room_id):
                return self._arrive_citadark(block_base, room_id)
            if not inside and not self.active and room_id in CITADARK_ROOM_IDS:
                return self._citadark_floor(block_base)
            if inside:
                self.via_map = False
            if inside and not self.active:
                # Not gated on `armed`: `_apply` decides -- lift with the Parts, clamp without them, nothing when
                # the byte is already below the ceiling -- and returns None when there is nothing to do, so this
                # retries next tick rather than latching. Retrying is the point, because a byte that RISES while
                # the player stands in Gateon has to be caught too, not just one that was already high.
                return self._apply(block_base)
            if inside and self.active:
                return self._hold(block_base)
            if not inside and self.active:
                return self._restore(block_base)
        except Exception:
            return None
        return None

    def _hold(self, block_base: int) -> "str | None":
        """Already holding the byte, still inside. Catch a value that rose underneath us.

        A cutscene or event inside Gateon can advance the byte past what we wrote, walking straight through the
        gate we are standing on. Re-clamping is only safe because `saved_byte` is raised to the new high FIRST, so
        the player's progress is kept for the restore and only the live value is held down."""
        if self.applied_value is None or self.saved_byte is None:
            return None
        live = read_story_byte(block_base)
        if live is None or live <= self.applied_value:
            return None
        if live >= VICTORY_STORY_BYTE:
            # They won while standing in Gateon. Let go entirely rather than clamp the backstop away.
            self.declined_clamp_won += 1
            self.saved_byte = max(self.saved_byte, live)
            self.active = False
            self.applied_value = None
            return (f"Story byte reached 0x{live:02X} inside Gateon Port -- that is a win, so the ceiling is "
                    f"released rather than applied.")
        previous = self.saved_byte
        self.saved_byte = max(self.saved_byte, live)
        if self.armed:
            return None  # the lift is what we wrote; a byte above it is the player's and stays
        poke_story_byte(block_base, self.applied_value & 0xFF)
        self.clamps += 1
        if self.write_log is not None:
            self.write_log.record("kyogre ceiling", "Gateon Port", live, self.applied_value,
                                  "byte advanced inside Gateon -- held back down, real value kept for restore")
        return (f"Story byte advanced to 0x{live:02X} inside Gateon Port -- held back at "
                f"0x{self.applied_value:02X} (was keeping 0x{previous:02X}, now keeping 0x{self.saved_byte:02X}).")

    def poll_hover(self, block_base: int, hovered_region: "str | None") -> "str | None":
        """Apply while the player is HOVERING this override's destination on the map, and restore on the hover too.

        The hover is a PRE-LOAD hook: Gateon is built from the byte as the room loads, so a write on arrival is one
        visit too late. The same goes for letting go -- ignoring the map screen in `poll` once slid the restore to
        after arrival, so the next area was built with our synthetic value still in the byte. While the map is open
        the byte should be whatever the destination UNDER THE CURSOR needs; an unreadable cursor does neither.

        The room trigger in `poll` is kept as well. It costs nothing and covers walking in, a story warp, or a
        missed hover; whichever fires first sets `active` and the other does nothing."""
        if hovered_region is None:
            return None   # cursor unreadable -- never write on a guess
        try:
            if hovered_region == self.trigger_region:
                # `armed` is dropped here for the same reason as in `poll`: the clamp has to land on the hover
                # too, because Gateon is built from the byte as the room loads.
                if not self.active:
                    return self._apply(block_base)
                return self._hold(block_base)
            # Hovering somewhere else while we hold the byte. The destination is about to be built from it, so put
            # the real value back now rather than after it has loaded.
            if self.active:
                return self._restore(block_base)
        except Exception:
            return None
        return None

    def target_for(self, current: int) -> "int | None":
        """What the byte should read inside Gateon, given what it reads now. None means "leave it alone".

        The single decision point, on purpose: a lift and a clamp on the same byte in the same rooms are two
        writers racing over one value, and one function that answers "what should it be" cannot race itself."""
        if self.armed:
            # Holding the Parts. The lift is the whole feature; it is never also clamped.
            return self.value if current != self.value else None
        if self.ceiling is None or current <= self.ceiling:
            return None  # nothing to hold down -- the byte is already below the gate
        if current >= VICTORY_STORY_BYTE:
            # The victory byte is the backstop for a missed final fight, and a clamp would erase it --
            # permanently, if they save here. A won game does not need the Robo Kyogre gated.
            self.declined_clamp_won += 1
            return None
        return self.ceiling

    def _apply(self, block_base: int) -> "str | None":
        current = read_story_byte(block_base)
        if current is None:
            return None  # cannot promise a restore we have nothing to restore to
        target = self.target_for(current)
        if target is None:
            return None
        poke_story_byte(block_base, target & 0xFF)
        self.saved_byte = current
        self.applied_value = target
        self.active = True
        self.applications += 1
        clamped = target < current
        if clamped:
            self.clamps += 1
        if self.write_log is not None:
            self.write_log.record(
                "kyogre ceiling" if clamped else "kyogre unlock", "Gateon Port", current, target,
                "no Robo Kyogre Parts -- held at the Gateon ceiling" if clamped
                else "Robo Kyogre Parts complete -- held while inside Gateon")
        if clamped:
            return (f"Gateon Port -- story byte held at 0x{target:02X} (was 0x{current:02X}); the Robo Kyogre "
                    f"needs its Robo Kyogre Parts (not the Machine Part from the Gateon parts shop -- they "
                    f"are different items). Your real value is put back when you leave.")
        return (f"Robo Kyogre Parts complete -- story byte set to 0x{target:02X} for Gateon Port "
                f"(was 0x{current:02X}, restored when you leave).")

    def _arrive_citadark(self, block_base: int, room_id: int) -> "str | None":
        """Rode the Robo Kyogre out of Gateon: write the island's entry value and let go.

        max(0x71, saved) -- the saved byte is the player's own progress from before Gateon, so a return trip to an
        island they had already advanced keeps that advance, and a won game is left exactly as it was."""
        saved = self.saved_byte
        target = CITADARK_ENTRY_FLOOR if saved is None else max(CITADARK_ENTRY_FLOOR, saved)
        live = read_story_byte(block_base)
        if live is not None and live >= VICTORY_STORY_BYTE:
            target = live
        if live != target:
            poke_story_byte(block_base, target & 0xFF)
            self.last_written_value = target
            if self.write_log is not None:
                self.write_log.record("citadark entry", CITADARK_REGION, live,
                                      target, f"rode the Robo Kyogre from Gateon (room {room_id})")
        # Only after the write, so the witness can tell this from the game's own progress.
        self.active = False
        self.saved_byte = None
        self.applied_value = None
        self.via_map = False
        self.citadark_arrivals += 1
        self.citadark_arrival_room = room_id
        return (f"Arrived at Citadark Isle (room {room_id}) -- story byte set to 0x{target:02X} "
                f"instead of rolling back to the pre-Gateon value.")

    def _citadark_floor(self, block_base: int) -> "str | None":
        """In a known Citadark room below the island's floor: raise it, never lower."""
        live = read_story_byte(block_base)
        if live is None or live >= CITADARK_ENTRY_FLOOR:
            return None
        poke_story_byte(block_base, CITADARK_ENTRY_FLOOR)
        self.last_written_value = CITADARK_ENTRY_FLOOR
        self.citadark_floor_writes += 1
        if self.write_log is not None:
            self.write_log.record("citadark floor", CITADARK_REGION, live, CITADARK_ENTRY_FLOOR,
                                  "on Citadark Isle below its entry value")
        return f"On Citadark Isle with story byte 0x{live:02X} -- raised to 0x{CITADARK_ENTRY_FLOOR:02X}."

    def _restore(self, block_base: int) -> "str | None":
        # `active` drops only once the byte is genuinely back. Cleared before the write instead, it left our own
        # value in memory unprotected -- `active` is one of the four things `StoryProgressWitness` refuses on -- which
        # is survivable while the write succeeds and not when it RAISES and then throws. There is no `try` here, the
        # caller swallows, and on that path `active` is already False, `saved_byte` already None and the lift value
        # still in the save, with `_apply` unable to re-arm because the player has left Gateon. The lift is above
        # every `Unlock -` threshold in the game, so the witness banks it. A failed restore keeps `active` True.
        saved = self.saved_byte
        if saved is None:
            self.active = False
            self.saved_byte = None
            return None
        live = read_story_byte(block_base)
        # Recognise whatever WE wrote -- the lift or the clamp -- rather than leaning on `read_story_byte` rejecting
        # it. That only worked because the written value was 0xFF, above STORY_BYTE_MAX_PLAUSIBLE, so `live` came back
        # None and the "did real progress outrank us?" test was skipped. A plausible written value comes back as
        # itself and outranks anything we would have saved, so that test would have declined every restore -- and
        # after a clamp the live byte is the CEILING, below `saved`, so `live > saved` would pass it through.
        written = self.applied_value if self.applied_value is not None else self.value
        if live == written:
            live = None  # our own write, not someone else's progress
        if live is not None and live > saved:
            self.declined_restores += 1
            # Genuine progress outranks our saved value, so there is nothing to put back and nothing of ours left
            # in the byte -- releasing the flag here is correct.
            self.active = False
            self.saved_byte = None
            return (f"Left Gateon Port -- story byte is 0x{live:02X}, past the 0x{saved:02X} from before, so "
                    f"real progress is kept rather than rolled back.")
        poke_story_byte(block_base, saved)
        # Only now. Everything above this line runs with our own value still in the byte.
        self.active = False
        self.saved_byte = None
        self.applied_value = None
        self.last_written_value = saved
        self.restorations += 1
        if self.write_log is not None:
            self.write_log.record("kyogre restore", "Gateon Port", written, saved,
                                  "left Gateon -- the pre-override value put back")
        return f"Left Gateon Port -- story byte restored to 0x{saved:02X}."

    def recover(self, block_base: int) -> "str | None":
        """Put back a value a PREVIOUS session was holding when it died. Called once on connect with whatever
        `saved_byte` was persisted; returns a note when it writes.

        Save/restore covers leaving Gateon, not the client being killed while inside it. For the lift that never
        mattered -- a byte left high is a byte the player keeps. A clamp left behind is story progress GONE, so
        this is the half that makes the clamp safe to ship.

        Deliberately narrow: it writes only when the live byte is still EXACTLY the clamp value. Anything else
        means the player has moved on, and a restore would be the clobber rather than the repair."""
        if self.saved_byte is None or self.ceiling is None:
            return None
        live = read_story_byte(block_base)
        if live is None or live != self.ceiling or self.saved_byte <= live:
            self.saved_byte = None
            return None
        saved = self.saved_byte
        try:
            poke_story_byte(block_base, saved & 0xFF)
        except Exception:
            return None   # keep the record; a later connect can try again
        self.saved_byte = None
        self.active = False
        self.applied_value = None
        # This fires on the FIRST tick after a reconnect, from whatever room the player is in, and is a RAISE by
        # construction (the guard above requires saved > live). The value is the player's own, so banking it is not
        # dishonest, but it is still a byte this client put there at the one moment the witness has no history.
        self.last_written_value = saved
        self.restorations += 1
        if self.write_log is not None:
            self.write_log.record("kyogre ceiling recovery", "Gateon Port", live, saved,
                                  "a previous session was clamping Gateon and did not get to restore")
        return (f"Recovered: a previous session left the Gateon ceiling in place. Story byte put back to "
                f"0x{saved:02X} (found 0x{live:02X}).")

    def describe(self) -> str:
        rooms = ", ".join(room_name(r) for r in sorted(self.trigger_rooms))
        state = "ACTIVE" if self.active else ("armed, waiting for you to enter" if self.armed else "not armed")
        ceiling = "off" if self.ceiling is None else f"0x{self.ceiling:02X}"
        line = (f"Story-byte override: {state}. Value 0x{self.value:02X}, ceiling {ceiling} (applies without "
                f"the Parts), trigger rooms: {rooms}. "
                f"Applied {self.applications}x ({self.clamps} of them clamps), restored {self.restorations}x")
        if self.declined_restores:
            line += f", declined {self.declined_restores}x because real progress had moved past it"
        if self.declined_clamp_won:
            line += (f", declined {self.declined_clamp_won}x to clamp a byte at or past victory "
                     f"(0x{VICTORY_STORY_BYTE:02X})")
        if self.saved_byte is not None:
            line += f". Holding 0x{self.saved_byte:02X} to put back"
        return line + "."


def story_byte_says_won(block_base: int) -> bool:
    """True when the story byte has reached `VICTORY_STORY_BYTE`. Never raises and never guesses: an unreadable or
    implausible byte is False, so this can only ADD a win detection, never invent one."""
    value = read_story_byte(block_base)
    return value is not None and value >= VICTORY_STORY_BYTE


def read_story_record(block_base: int) -> bytes:
    """The raw 20-byte travel-control record. This is the exact blob the story-flags doc records verbatim."""
    return read_bytes(block_base + STORY_RECORD_OFFSET, STORY_RECORD_SIZE)


# --- The story byte is eight bits of a twelve-bit variable. ---
# Field scripts never read the byte at `STORY_RECORD_OFFSET + STORY_BYTE_OFFSET`. They call builtin 0x85 with the
# argument 964 -- GS variable 964, width 12, storage group 24, bitpos 917 -- which resolves to
#
#     var964 = (u16_be(record + 0x00) >> 5) & 0xFFF = (story_byte << 3) | (record[0x01] >> 5)
#
# so this project's byte is bits 3..10 of it and the low 3 bits were never written. game_data/story_bytes.py carries
# the derivation, the tens rule, and why 0x27 and 0x63 are values the game can never hold. The low five bits of that
# u16 are NOT ours -- bits 904..916 are the tail of GS variable 802 (width 32, bitpos 885), which read 0x00 in all
# 155 clean dumps in the corpus and 0x1F only in the eight checkpoint-12 dumps where this project wrote 0xFF over
# them -- so the write is a read-modify-write and preserves them.

STORY_VALUE_SHIFT = 5             # bits of the u16 below variable 964
STORY_VALUE_NEIGHBOUR_MASK = (1 << STORY_VALUE_SHIFT) - 1   # the tail of GS variable 802, never ours
STORY_VALUE_STEP = 10             # every value the game holds is a multiple of this (163-dump census)


def read_story_value(block_base: int) -> "int | None":
    """GS variable 964 itself -- what every field script compares against. None when it cannot be read.

    Applies no plausibility ceiling, unlike `read_story_byte`, whose "implausible means don't know" contract is
    unchanged."""
    try:
        raw = read_bytes(block_base + STORY_RECORD_OFFSET + STORY_BYTE_OFFSET, 2)
    except Exception:
        return None
    return (struct.unpack(">H", raw)[0] >> STORY_VALUE_SHIFT) & 0xFFF


def poke_story_byte(block_base: int, story_byte: int) -> bool:
    """Set the story variable to what `story_byte` stands for. THE ONLY WRITE PATH FOR THE STORY BYTE.

    Every rule here that moves the player's story position goes through this -- the area floor, the live bumps, the
    Parts lift, the Gateon ceiling, the scooter hold, the Citadark entry, the debug command. Writing one byte and
    leaving the variable's low three bits at whatever the save held put the game on a rung no script tests for.

    A byte with no story value behind it (`story_value_for_byte` returns None) is written as the bare byte rather
    than rounded to a neighbour: rounding would silently move the player to a rung the caller did not ask for.
    `story_bytes` asserts no shipped floor is such a byte, so in practice only the debug command reaches it."""
    from .game_data import story_bytes

    address = block_base + STORY_RECORD_OFFSET + STORY_BYTE_OFFSET
    value = story_bytes.story_value_for_byte(story_byte & 0xFF)
    if value is None:
        write_bytes(address, bytes([story_byte & 0xFF]))
        return False
    try:
        keep = struct.unpack(">H", read_bytes(address, 2))[0] & STORY_VALUE_NEIGHBOUR_MASK
    except Exception:
        keep = 0
    write_bytes(address, struct.pack(">H", ((value & 0xFFF) << STORY_VALUE_SHIFT) | keep))
    return True


def read_story_byte(block_base: int) -> "int | None":
    """The global story-progress byte, or None if it cannot be trusted. Mirrors `read_area_id`'s contract: an
    implausible value means "don't know" rather than a number the caller might act on."""
    try:
        value = read_story_record(block_base)[STORY_BYTE_OFFSET]
    except Exception:
        return None
    if value > STORY_BYTE_MAX_PLAUSIBLE:
        return None
    return value


def write_story_byte(block_base: int, value: int,
                     write_log: "StoryByteWriteLog | None" = None,
                     why: str = "!storybyte") -> "tuple[bool, int | None]":
    """Set the story byte outright. Returns `(written, previous value)`.

    The debug command's write, and the only one here a player asks for directly. Deliberately the plainest: no
    plausibility opinion beyond the byte range, no save/restore, no memory of having done it -- a debug command
    that second-guesses the number typed into it is not a debug command. The caller is responsible for claiming the
    write (Client.py's `_claim_story_write`) so the progress witness does not bank it as the game's own progress,
    since "a value we wrote is not a value we observed" is a property of every writer here."""
    if not 0 <= value <= 0xFF:
        return False, None
    previous = read_story_byte(block_base)
    try:
        poke_story_byte(block_base, value)
    except Exception:
        return False, previous
    if write_log is not None:
        write_log.record("manual", "story", previous, value, why)
    return True, previous


# --- The Snag Machine is two bytes, and neither of them is the story byte. ---
# Both earlier hypotheses were ruled out: the Key Items pocket reads empty while the machine is demonstrably in use,
# and the global story ladder was never findable in MEM1 at all.
#
# Found from three MEM1 dumps taken with the player standing at the pickup -- two of the identical pre-pickup state
# as a noise mask, one immediately after. Across all of MEM1 the pre->post delta was ~3.0M bytes with ~2.1M of noise
# between the two identical dumps; restricted to the resolved player-state block (0x11000 bytes) the noise was ZERO
# and the delta was exactly two bytes:
#
#     block +0x00919                       0x00 -> 0x02
#     block +0x10732  (story record +0x12)  0x10 -> 0x18   (bit 0x08 set)
#
# The story byte read 0x0A in all three, which kills "just set the story byte" for this transition -- 0x0F is where
# the story byte ARRIVES later, not what grants the machine. Checked against the dump archive in a DIFFERENT save
# file on a DIFFERENT boot (BLOCK_BASE 0x80478F00 vs 0x804795C0), seventeen days earlier:
#
#     dump                              story byte   +0x919   record +0x12
#     mem1_pre_pda                         0x02        0x00       0x00      (not yet owned)
#     mem1_post_kraneconvo_pre_snag        0x0A        0x00       0x14      (immediately before pickup)
#     mem1_post_snag                       0x0A        0x02       0x1C      (immediately after)
#     snagmachine_pre_a / _pre_b           0x0A        0x00       0x10      (this session, before)
#     snagmachine_post                     0x0A        0x02       0x18      (this session, after)
#     gio_after_lovrina                    0x2B        0x02       0x19      (mid-game, still owned)
#
# Six dumps, three save files, three boots: `+0x919` is 0x00 in every not-owned state and 0x02 in every owned one,
# and record `+0x12` bit 0x08 follows it exactly. The other bits of `+0x12` differ per save file, which is why this
# writes the BIT and never the byte.
#
# Written as well as read: live-tested through the bridge -- both sites cleared, read back cleared, left cleared
# through ~45 seconds of play, then restored and read back restored -- so the game does not re-derive either and
# these are real persistent state.
#
# NOT PROVEN: nobody has walked into a Shadow battle with these bytes cleared and confirmed the Snag option is gone.
# "The flag the game sets when it grants the machine" and "the flag the game reads when it offers to snag" are two
# claims and only the first is measured. Until an in-battle test happens this is the primitive, not the item.

SNAG_MACHINE_FLAG_OFFSET = 0x919          # block-relative u8; only 0x00 and 0x02 have ever been observed
SNAG_MACHINE_FLAG_BIT = 0x02
SNAG_MACHINE_RECORD_BYTE_OFFSET = 0x12    # within the 20-byte story/travel record at STORY_RECORD_OFFSET
SNAG_MACHINE_RECORD_BIT = 0x08


def read_snag_machine(block_base: int) -> "bool | None":
    """True/False if the Snag Machine flag can be read, None if it cannot -- the same "don't know" contract as
    `read_story_byte`, so a failed read is never mistaken for "the player doesn't have it".

    BOTH sites must agree. They have in all six dumps this was derived from, and a disagreement would mean one of
    them is not the flag after all, so a split read returns None rather than picking a favourite."""
    try:
        flag = read_bytes(block_base + SNAG_MACHINE_FLAG_OFFSET, 1)[0]
        record = read_bytes(block_base + STORY_RECORD_OFFSET + SNAG_MACHINE_RECORD_BYTE_OFFSET, 1)[0]
    except Exception:
        return None
    owned_flag = bool(flag & SNAG_MACHINE_FLAG_BIT)
    owned_record = bool(record & SNAG_MACHINE_RECORD_BIT)
    if owned_flag != owned_record:
        return None
    return owned_flag


def write_snag_machine(block_base: int, owned: bool) -> bool:
    """Give (`owned=True`) or take away (`owned=False`) the Snag Machine. True if both writes landed.

    READ-MODIFY-WRITE at both sites, never a blind byte write. Record `+0x12` carries other bits whose values
    differ between save files (0x14/0x1C in one, 0x10/0x18 in another, 0x19 mid-game), and that record is the SAME
    twenty bytes the travel-unlock bits live in -- a blind write would silently relock or unlock map destinations.
    `+0x919` has only ever read 0x00 or 0x02, so masking it is belt-and-braces, but it costs one read and means a
    future discovery that the byte packs a second flag cannot turn this into a corruption bug."""
    try:
        flag = read_bytes(block_base + SNAG_MACHINE_FLAG_OFFSET, 1)[0]
        record_address = block_base + STORY_RECORD_OFFSET + SNAG_MACHINE_RECORD_BYTE_OFFSET
        record = read_bytes(record_address, 1)[0]
        if owned:
            flag |= SNAG_MACHINE_FLAG_BIT
            record |= SNAG_MACHINE_RECORD_BIT
        else:
            flag &= ~SNAG_MACHINE_FLAG_BIT & 0xFF
            record &= ~SNAG_MACHINE_RECORD_BIT & 0xFF
        write_bytes(block_base + SNAG_MACHINE_FLAG_OFFSET, bytes([flag]))
        write_bytes(record_address, bytes([record]))
    except Exception:
        return False
    return True


# --- Per-chest "is this chest open", from the game's own flag bits. ---
# See game_data/chest_flags.py for how the mapping was found and for the four-dump consistency check: each chest
# carries a flag id in its treasure-table entry, and that id indexes a global bitfield of u32BE words in the
# player-state block. Two chests opened live pinned the model; a brute-force search over bit layouts left one family.
#
# READ-ONLY BY DESIGN. The region demonstrably carries non-chest flags too (set bits in the same words decode to no
# chest at all), so a stray write could clear story progress with no way to tell.

CHEST_FLAG_WORD_COUNT = 64   # generous window covering every chest's word; see chest_flag_span()


def chest_flag_span() -> "tuple[int, int]":
    """(first_offset, length) from BLOCK_BASE covering every flagged chest's byte, so a caller can pull the whole
    bitfield in ONE read instead of 113 of them."""
    from .game_data import chest_flags

    offsets = [chest_flags.chest_byte_offset_and_mask(c)[0] for c in chest_flags.flagged_chest_ids()]
    first = min(offsets) & ~0x3
    last = (max(offsets) | 0x3) + 1
    return first, last - first


def read_chest_flag_block(block_base: int) -> "bytes | None":
    """The whole chest-flag region in one read, or None if it cannot be read."""
    first, length = chest_flag_span()
    try:
        return read_bytes(block_base + first, length)
    except Exception:
        return None


def chest_is_open_in_block(block: bytes, chest_id: int) -> "bool | None":
    """Decode one chest out of `read_chest_flag_block`'s result. None means "no answer" -- the chest has no flag
    at all (the room-175 debug pair) or the block is too short. Never a guessed False: a false "closed" is
    indistinguishable from a real one, and a false "open" would send a check that never happened."""
    from .game_data import chest_flags

    # A chest outside the one measured flag cluster gets NO ANSWER, not a guessed one. The model reaches the
    # other four clusters by arithmetic alone and the original dumps contradict it -- every byte it assigns them is
    # zero on a save that had demonstrably opened some. None is the only answer a caller can notice.
    if not chest_flags.chest_flag_is_validated(chest_id):
        return None
    located = chest_flags.chest_byte_offset_and_mask(chest_id)
    if located is None:
        return None
    offset, mask = located
    first, _ = chest_flag_span()
    index = offset - first
    if not (0 <= index < len(block)):
        return None
    return bool(block[index] & mask)


def undetectable_chest_ids() -> "tuple[int, ...]":
    """Chests whose open/closed state this client cannot read -- the unvalidated clusters plus the two chests the
    game records nothing for. Exposed so the connect banner and `!chests` can say so out loud."""
    from .game_data import chest_flags

    return tuple(sorted(
        set(chest_flags.unvalidated_chest_ids()) | set(chest_flags.UNFLAGGED_CHEST_IDS)
    ))


def undetectable_chest_locations() -> "tuple[str, ...]":
    """The AP location names behind `undetectable_chest_ids`, only for the ones that are real locations in this
    build (an excluded room or a key-item chest has no name and is not a lost check)."""
    return tuple(sorted({
        name for chest_id in undetectable_chest_ids()
        if (name := CHEST_ID_TO_LOCATION.get(chest_id))
    }))


def open_chest_ids(block: bytes) -> "tuple[int, ...]":
    """Every chest the block says is open. Chests with no flag, and chests we will not answer for, are absent."""
    from .game_data import chest_flags

    return tuple(
        chest_id for chest_id in chest_flags.flagged_chest_ids()
        if chest_is_open_in_block(block, chest_id)
    )


# --- The berry IS the chest. ---
# Six earlier attempts tried to recover a chest's identity from the chest-flag bitfield. That array is global, carries
# story flags on chest positions (a fresh save walking around the HQ Lab sets the bit the model read as chest 62,
# Citadark Isle), and its cluster offsets are non-monotonic -- measured at 696, 696, 464, 483, 483, 483, with gaps of
# 232 and 19 slots. Every model was fitted in one cluster and extrapolated across five, and it is wrong in places:
# chests 87 and 88 were opened live and the bits assigned to them (BLOCK_BASE+0x107AF, masks 0x08/0x10) are still
# zero, with two Cipher Lab chests credited instead.
#
# So this reads no flag bit. Each chest contains its own berry, assigned so no two chests in one room share one
# (game_data/chest_berries.py asserts that at import):
#
#     a reserved chest berry appeared  ->  a chest was opened
#     which berry + which room         ->  exactly which chest
#
# Both halves are exact -- nothing else can bump a reserved berry's quantity, `read_room_id` is validated four ways
# and returns None rather than guessing, and you cannot open a chest without standing in its room. `chest_for()`
# returns None rather than a best guess, and a None is CARRIED rather than dropped.
#
# THE BERRY IS CLEARED AFTER CREDITING, because a berry is shared by ~16 chests across rooms, so an uncleared stack
# makes every later pickup a delta against a growing number -- and the player can use, sell or toss one, which would
# look like a negative pickup. A berry seen while the room is unreadable is left in the Bag and resolved by the next
# poll with a readable room, so nothing is lost. Needs `randomize_chests` on; a key-item chest keeping its vanilla
# contents gives no berry and is not a location, so it correctly credits nothing.


# --- The validated chest-flag band, derived once. ---
# Every chest whose flag has actually been MEASURED (96 of 115) has its bit inside one contiguous run of bytes, so
# the whole set can be watched with a single read. Derived from the table rather than written down, because a
# hand-typed span is exactly the thing that stops matching the table it was copied from.
_FLAG_SPAN_CACHE: "tuple[int, int] | None" = None
_FLAG_BITS_CACHE: "tuple[tuple[int, int, int], ...] | None" = None


def _validated_flag_bits() -> "tuple[tuple[int, int, int], ...]":
    """[(chest_id, byte offset from BLOCK_BASE, mask)] for every chest with a MEASURED flag."""
    global _FLAG_BITS_CACHE
    if _FLAG_BITS_CACHE is None:
        from .game_data import chest_flags
        out = []
        for chest_id in sorted(chest_flags.CHEST_FLAG_IDS):
            if not chest_flags.chest_flag_is_validated(chest_id):
                continue   # a confident wrong answer is worse than no answer
            pair = chest_flags.chest_byte_offset_and_mask(chest_id)
            if pair is None:
                continue
            out.append((chest_id, pair[0], pair[1]))
        _FLAG_BITS_CACHE = tuple(out)
    return _FLAG_BITS_CACHE


def _validated_flag_span() -> "tuple[int, int] | None":
    """(start offset, length) covering every validated chest flag, or None if there are none."""
    global _FLAG_SPAN_CACHE
    if _FLAG_SPAN_CACHE is None:
        bits = _validated_flag_bits()
        if not bits:
            return None
        offsets = [offset for _, offset, _ in bits]
        _FLAG_SPAN_CACHE = (min(offsets), max(offsets) - min(offsets) + 1)
    return _FLAG_SPAN_CACHE


@dataclass
class ChestBerryTracker:
    """Credits exactly the chest whose berry appeared. See the section comment above.

    Holds no model of the flag array, no learned positions and no per-chest state beyond what it has credited --
    which is what makes it correct rather than merely better-tuned."""

    # berry id -> last confirmed Bag quantity. Zero after a credit, because we clear.
    last_seen: "dict[int, int]" = field(default_factory=dict)
    # A pending pickup carries the room it happened in. Recording only THAT a berry appeared and resolving against
    # whatever room was readable later reintroduced the exact failure this design removes: open a chest while the room
    # is briefly unreadable, walk to a DIFFERENT room holding a chest with that berry, and that room's chest is
    # credited while the one actually opened never is. Both shapes are "credit the wrong chest", the one outcome that
    # cannot be taken back, so a pickup that cannot be placed is ABANDONED rather than left to drift -- a missed check
    # can be re-sent with `!checked`, a wrong one has already released another player's item.
    pending: "list[dict]" = field(default_factory=list)

    # A chest opened before the client's first poll cannot be backfilled automatically. The first sighting of a berry
    # is a BASELINE, not a pickup -- correct, because a quantity already there says nothing about when it got there --
    # but open a chest before connecting (the Pokemon HQ Lab's three chests are exactly there) and that check can
    # never fire. Seven berries cover 115 chests, 17 each, and identity is (room, berry), so a berry in the Bag at
    # connect carries no room and crediting one would be a 1-in-17 guess at a check that cannot be taken back. So the
    # tracker says what it saw, names the candidates, and points at `!checked`.
    #
    baseline_carried: "dict[int, int]" = field(default_factory=dict)
    # Set by the client once it has told the player, so the notice survives a reconnect without being repeated.
    backfill_announced: bool = False
    # Carried berries whose chest was the only unchecked candidate, so it was credited rather than announced.
    # Counted because "we silently did something clever" is the shape this project distrusts.
    backfilled_unambiguously: int = 0

    credited_by_room: "dict[int, int]" = field(default_factory=dict)
    credits: int = 0
    unplaceable_polls: int = 0            # a berry appeared with no readable room
    berries_in_a_room_with_no_such_chest: int = 0   # the one genuinely wrong-looking case, counted not hidden
    abandoned_pickups: int = 0            # held too long with no readable room -- dropped rather than guessed
    clear_failures: int = 0

    # How many polls a pickup may wait for a readable room before it is abandoned. Deliberately SHORT: the player
    # is standing in the room when they open a chest, and `read_room_id` returns None only around transitions, so a
    # room still unreadable seconds later most likely means the player has moved.
    _MAX_PENDING_POLLS: ClassVar[int] = 4

    _pending_quantity: "dict[int, int]" = field(default_factory=dict)
    _pending_streak: "dict[int, int]" = field(default_factory=dict)
    # The block-stability gate is the real defence against the save-menu stale read, so this streak is a second
    # line rather than the first.
    _CONFIRM_STREAK: ClassVar[int] = 2
    # The floor `set_poll_interval` may never resolve below. The streak derives from
    # `CONFIRM_WINDOW_SECONDS["chest_berry"]`, which is now SHORTER than the outer poll interval, so the derivation
    # alone would give 1 -- "believe the first reading". Two agreeing reads is the standing guarantee here and it
    # does not move when the clock does.
    _MIN_CONFIRM_STREAK: ClassVar[int] = 2

    # Both windows are CLOCKS, because the fast sub-poll calls this several times per outer tick -- but they need
    # opposite treatment. `_CONFIRM_SECONDS` is the debounce, where cutting short risks a PHANTOM check, so it is a
    # floor: a rise must survive both `_CONFIRM_STREAK` agreeing reads and this many real seconds.
    # `_MAX_PENDING_SECONDS` is the deadline on a pickup waiting for a readable room, and runs the other way --
    # cutting it short DROPS A CHECK THE PLAYER ALREADY EARNED, and at a 0.1s sub-tick a bare `_MAX_PENDING_POLLS` of
    # 4 would abandon a real pickup after four tenths of a second. So abandonment requires the poll count AND the real
    # duration to be exhausted; in practice the clock binds.
    _CONFIRM_SECONDS: ClassVar[float] = CONFIRM_WINDOW_SECONDS["chest_berry"]
    _MAX_PENDING_SECONDS: ClassVar[float] = CONFIRM_WINDOW_SECONDS["chest_pending"]

    # THE CHEST'S SECOND WITNESS, so a real pickup no longer waits out the debounce. The poll rate is not what is
    # slow -- chests already run on the 0.1s sub-loop and `_CONFIRM_SECONDS` is deliberately rate-proof -- so replace
    # the window with better evidence rather than less of it. The game's own per-chest "already opened" bit is
    # located for 96 of the 115 chests, and every validated flag lives in one 132-byte band, so watching all of them
    # costs ONE read per poll.
    #
    # The pair is unfakeable by what the window guards against: the save-menu glitch serves a STALE SNAPSHOT, which is
    # internally consistent -- old berry count AND old flags together -- and a flag going CLEAR -> SET is the one
    # thing a rewind cannot produce. It also runs behind the block-stability gate, so the 1 -> 0 -> 1 flap a rewrite
    # could produce is never observed here.
    #
    # Narrow by construction, which is what makes it safe to be fast: an unreadable flag band, a chest with no
    # measured flag, a first poll with nothing to diff against, or a flag flipping outside the window all fall through
    # to the untouched streak and clock.
    #
    # 6.0 seconds because the two halves DO NOT ARRIVE TOGETHER -- the flag flips when the chest is opened, the berry
    # lands after the animation and the "obtained" message. At 1.0s the transition was seen, counted and thrown away
    # before the berry arrived. Widening is not loosening: `_corroborating_chest` still requires the flipped chest to
    # be the one this room and this berry independently name. 6.0 is reasoning about an animation length, not a
    # measurement, so `flag_transitions_expired` counts transitions that still time out unused.
    _FLAG_CORROBORATION_SECONDS: ClassVar[float] = 6.0

    _flag_bytes: "bytes | None" = None            # last poll's snapshot of the validated flag band
    _recently_opened: "dict[int, float]" = field(default_factory=dict)   # {chest_id: when its bit flipped}
    flag_corroborated: int = 0                    # pickups credited on the pair rather than the clock
    flag_reads_failed: int = 0
    flag_transitions_seen: int = 0
    # Transitions pruned without ever corroborating a pickup: the instrument that says whether
    # `_FLAG_CORROBORATION_SECONDS` is wide enough.
    flag_transitions_expired: int = 0
    # Times the flag's chest and the player's own room named different chests for one berry -- the instrument that
    # turns "two chests share a label" into "chest N's measured flag is wrong", which one play session can
    # confirm.
    flag_disagreed_with_room: int = 0
    flag_room_disagreements: "list[str]" = field(default_factory=list)

    # A chest opened on the way out of a room used to be silently dropped, because the room was read at CREDIT time
    # rather than at pickup time: a pickup waits out `_CONFIRM_SECONDS`, and the room captured at the end of that
    # wait is wherever the player is by then, so `chest_for(that room, berry)` named no chest and the pickup was
    # counted and RETURNED. Measured before changing anything: flagged chest 1 credited if you stay or leave after
    # 0.1s, LOST if you leave immediately; unflagged chest 31 credited only if you stay.
    #
    # Three changes, first being the one that matters:
    # 1. THE FLAG NAMES THE CHEST BY ITSELF -- a per-chest "already opened" bit needs no room to disambiguate it, so
    #    a corroborated pickup never consults the room. That covers 96 chests outright.
    # 2. The room is captured when the RISE is first seen, within a tenth of a second of the berry landing.
    # 3. Recently-visited rooms are candidates, newest first, when the pickup's own room names no chest -- only rooms
    #    inside `_ROOM_HISTORY_SECONDS` that hold a chest with exactly this berry.
    #
    # ORDERING, NOT A CLOCK, bounds those candidates: on a real clock a few polls is milliseconds, so any time window
    # wide enough to be useful also admits a room entered AFTER the pickup. A room sighting carries a SEQUENCE
    # NUMBER, and only rooms seen at or before the berry rise are candidates.
    #
    # Nothing is dropped silently now: a pickup that still cannot be placed is held for `_UNPLACEABLE_HOLD_SECONDS`
    # and then reported by name through `unplaceable_notices`.
    _ROOM_HISTORY_SECONDS: ClassVar[float] = 20.0
    _UNPLACEABLE_HOLD_SECONDS: ClassVar[float] = 20.0

    _room_history: "list[tuple[int, float, int]]" = field(default_factory=list)   # (seq, when, room)
    _room_seq: int = 0
    _pending_room: "dict[int, int | None]" = field(default_factory=dict)
    _pending_seq: "dict[int, int]" = field(default_factory=dict)
    placed_by_history: int = 0        # pickups saved by a room the player had already left
    placed_by_flag: int = 0           # pickups credited on the flag's own identity, room never consulted
    unplaceable_notices: "list[str]" = field(default_factory=list)
    # Injectable so the tests can drive it -- see `ShopPurchaseTracker.clock` for the full reasoning.
    clock: "Callable[[], float]" = time.monotonic
    _pending_since: "dict[int, float]" = field(default_factory=dict)

    def poll(self, block_base: int, room_id: "int | None",
             already_checked: "frozenset[str]") -> "list[str]":
        """One tick. Returns the location names to send -- usually none."""
        from .game_data import chest_berries

        return self._poll(block_base, room_id, already_checked, chest_berries)

    def _remember_room(self, room_id: "int | None") -> None:
        """Keep the rooms the player was actually in, so a pickup that outlived its room can still be placed
        against somewhere they really were rather than against a guess."""
        if room_id is None:
            return
        now = self.clock()
        if not self._room_history or self._room_history[-1][2] != room_id:
            self._room_seq += 1
            self._room_history.append((self._room_seq, now, room_id))
        cutoff = now - self._ROOM_HISTORY_SECONDS
        while self._room_history and self._room_history[0][1] < cutoff:
            self._room_history.pop(0)

    def _candidate_rooms(self, entry: dict) -> "tuple[int, ...]":
        """The pickup's own room first, then every room seen around it, newest first. Deduplicated, and bounded by
        `_ROOM_HISTORY_SECONDS` -- never "any room ever entered"."""
        out: "list[int]" = []
        own = entry.get("room")
        if own is not None:
            out.append(own)
        limit = entry.get("rise_seq")
        for seq, _when, room in reversed(self._room_history):
            if limit is not None and seq > limit:
                continue          # entered AFTER the berry appeared -- the chest cannot have been there
            if room not in out:
                out.append(room)
        return tuple(out)

    def _watch_chest_flags(self, block_base: int) -> None:
        """One read of the validated flag band; record every bit that went CLEAR -> SET.

        Populates `_recently_opened` with the moment each chest's bit flipped, so a berry rise arriving a poll or
        two later can still be corroborated. Never raises and never credits anything by itself -- a failed read
        drops the snapshot so the next poll re-baselines rather than diffing across a gap, which declines
        corroboration rather than inventing it."""
        from .game_data import chest_flags

        span = _validated_flag_span()
        if span is None:
            return
        start, length = span
        try:
            current = read_bytes(block_base + start, length)
        except Exception:
            self.flag_reads_failed += 1
            self._flag_bytes = None          # re-baseline next poll; no corroboration in the meantime
            return
        if current is None or len(current) != length:
            self.flag_reads_failed += 1
            self._flag_bytes = None
            return

        previous, self._flag_bytes = self._flag_bytes, current
        now = self.clock()
        # Prune first, so a stale entry can never corroborate a much later pickup.
        for chest_id, when in list(self._recently_opened.items()):
            if now - when > self._FLAG_CORROBORATION_SECONDS:
                del self._recently_opened[chest_id]
                self.flag_transitions_expired += 1
        if previous is None:
            return                            # first sighting is a baseline, never a transition

        for chest_id, offset, mask in _validated_flag_bits():
            index = offset - start
            if not 0 <= index < length:
                continue
            was_set = bool(previous[index] & mask)
            is_set = bool(current[index] & mask)
            if is_set and not was_set:
                self._recently_opened[chest_id] = now
                self.flag_transitions_seen += 1

    def _corroborating_chest(self, room_id: "int | None", berry_id: int, chest_berries) -> "int | None":
        """The chest whose own bit just flipped AND which this room+berry independently names, or None.

        Both halves are required on purpose. "Some chest somewhere was opened" would credit a berry to a pickup in
        another room; "this room has a chest for this berry" is what the slow path already concludes. The pair
        corroborates the EVENT and the IDENTITY at once."""
        if not self._recently_opened:
            return None
        # The flag IS the identity: a per-chest "already opened" bit that just went CLEAR -> SET, whose own berry
        # is the berry that just rose, names one chest and needs no room to do it. That is what makes leaving the
        # room irrelevant for every chest with a measured flag.
        matches: "list[tuple[float, int]]" = []
        for chest_id, when in self._recently_opened.items():
            try:
                pair = chest_berries.berry_for_chest(chest_id)
            except Exception:
                continue
            if pair and pair[0] == berry_id:
                matches.append((when, chest_id))
        if not matches:
            return None
        try:
            named = chest_berries.chest_for(room_id, berry_id)
        except Exception:
            named = None
        if len(matches) > 1:
            # Two chests in different rooms can hold the same berry. If the room still agrees with one of them,
            # take that one; otherwise take the most recent flip, nearest in time to the rise we are explaining.
            if named is not None and any(c == named for _w, c in matches):
                return named
        winner = max(matches)[1]
        # THE ROOM OVERRULES THE FLAG when the two name different places. Returning the flag's chest without
        # consulting the room is right when the bit is measured correctly and catastrophic when it is not: a bit
        # attributed to the wrong chest silently renames every pickup that flips it, whatever room the player is in --
        # which is how one label came to appear on two physical chests (a Key Lair chest and a Snagem one), since
        # neither the name tables nor the room path can produce that.
        #
        # The bits for that pair do look mis-assigned -- Snagem's seven chests sit at 0x107B6 bits 0x08..0x80
        # (101-105) and 0x107B5 bits 0x1/0x2 (106/107), a separate otherwise-empty byte, while 0x107B6 has exactly
        # three free bits left, and the three Cipher Key Lair 1F chests that would be affected (43, 44, 56) have no
        # measured flag at all -- but that is a hypothesis about the ISO, not what this guard rests on. The guard is
        # weaker and safer: if the room the player is in independently names a DIFFERENT chest for this berry, the room
        # wins. It cannot lose a check, cannot credit a chest the player was never near, and makes the disagreement
        # visible instead of silent.
        if named is not None and winner != named:
            self.flag_disagreed_with_room += 1
            self.flag_room_disagreements.append(
                f"chest flag named chest {winner} but room {room_id} holds chest {named} for this berry -- "
                f"crediting the room. If this repeats, chest {winner}'s measured open-flag is wrong."
            )
            return named
        return winner

    def _poll(self, block_base, room_id, already_checked, chest_berries) -> "list[str]":
        # One flag read before any berry is considered, so every berry this tick sees the same snapshot and a
        # single pickup cannot be corroborated twice off two different reads.
        self._watch_chest_flags(block_base)
        # Record where the player is before anything is credited, so a pickup placed later has the rooms they were
        # really in to choose from.
        self._remember_room(room_id)
        names: "list[str]" = []
        for berry_id in chest_berries.CHEST_BERRY_IDS:
            # The READ window, base and count together. Pairing the berry sub-window's base (array slot 82) with
            # the whole array's slot COUNT both missed the slots the game fills and ran off the end of the array.
            window = resolve_item_read_window(block_base, berry_id)
            if window is None:
                continue
            read_base, read_slots = window
            try:
                quantity = find_item_quantity(read_base, read_slots, berry_id)
            except Exception:
                continue   # a failed read is not evidence of anything -- try again next poll

            baseline = self.last_seen.get(berry_id)
            if baseline is None:
                # First sighting. Whatever is there predates this client's view, so it is a baseline rather
                # than a pickup.
                self.last_seen[berry_id] = quantity
                # A NON-ZERO baseline means a chest was opened before this client was watching and its check
                # will never fire on its own -- recorded, not guessed at.
                if quantity > 0:
                    self.baseline_carried[berry_id] = quantity
                continue
            if quantity <= baseline:
                # Gone down or unchanged. A decrease is the player using or tossing one, or our own clear
                # landing; neither is a pickup, and neither may manufacture one.
                if quantity < baseline:
                    self.last_seen[berry_id] = quantity
                self._pending_quantity.pop(berry_id, None)
                self._pending_streak.pop(berry_id, None)
                self._pending_since.pop(berry_id, None)
                self._pending_room.pop(berry_id, None)
                self._pending_seq.pop(berry_id, None)
                continue

            # A rise. Debounce it before believing it.
            if self._pending_quantity.get(berry_id) == quantity:
                self._pending_streak[berry_id] = self._pending_streak.get(berry_id, 0) + 1
            else:
                self._pending_quantity[berry_id] = quantity
                self._pending_streak[berry_id] = 1
                self._pending_since[berry_id] = self.clock()
                # The room AT THE RISE, not at the credit: at the 0.1s sub-poll that is within a tenth of a second
                # of the berry landing, where the old capture point was up to two seconds later and the player
                # could be two rooms away. The sequence number fences the candidate list.
                self._pending_room[berry_id] = room_id
                self._pending_seq[berry_id] = self._room_seq
            # The pair short-circuits the clock, checked BEFORE the streak and the seconds, because both of those
            # exist only to compensate for having a single witness.
            witness = self._corroborating_chest(room_id, berry_id, chest_berries)
            corroborated = witness is not None
            if corroborated:
                self.flag_corroborated += 1
                # Spend the transition. One flip credits one pickup, and an entry that has done its job must not
                # later count as having expired unused -- that counter has to mean only one thing.
                self._recently_opened.pop(witness, None)
            if not corroborated and self._pending_streak[berry_id] < self._CONFIRM_STREAK:
                continue
            # The duration half of the same debounce: a floor, so it can only delay a credit by a poll or two.
            since = self._pending_since.get(berry_id)
            if not corroborated:
                if since is None:
                    self._pending_since[berry_id] = self.clock()
                    continue
                if (self.clock() - since) < self._CONFIRM_SECONDS:
                    continue

            self._pending_quantity.pop(berry_id, None)
            self._pending_streak.pop(berry_id, None)
            self._pending_since.pop(berry_id, None)
            # The room recorded when the rise was FIRST seen, falling back to the current one only if there was
            # none: capturing it here, at credit time, gets the room the player has walked to rather than the one
            # they opened the chest in. `chest` is the flag's own answer when there is one.
            first_room = self._pending_room.pop(berry_id, None)
            self.pending.append({"berry": berry_id,
                                 "room": first_room if first_room is not None else room_id,
                                 "chest": witness,
                                 "rise_seq": self._pending_seq.pop(berry_id, self._room_seq),
                                 "waited": 0, "since": self.clock()})
            self.last_seen[berry_id] = quantity

        # ADDENDUM 226: resolve each pending pickup against the room IT was picked up in.
        still_pending: "list[dict]" = []
        for entry in self.pending:
            berry_id = entry["berry"]
            where = entry["room"]

            if where is None and entry.get("chest") is None:
                # The room was unreadable at the moment of the pickup. The first readable room after it is the best
                # evidence available, since the player is standing where they opened the chest. When that never
                # arrives this falls through to the candidate-room resolution below rather than abandoning the
                # pickup, and anything surviving even that is reported by name rather than discarded quietly.
                if room_id is not None and not entry.get("expired"):
                    where = entry["room"] = room_id
                else:
                    entry["waited"] += 1
                    self.unplaceable_polls += 1
                    waited_long_enough = (self.clock() - entry.get("since", self.clock())
                                          ) >= self._MAX_PENDING_SECONDS
                    if not (entry["waited"] > self._MAX_PENDING_POLLS and waited_long_enough):
                        still_pending.append(entry)
                        continue
                    # Out of patience waiting for a live room read. The history may still hold a room from BEFORE
                    # the rise, which is legitimate; what must never happen is adopting whatever room the player
                    # wanders into next, so the entry is marked and the live-room shortcut closed to it for good.
                    if not entry.get("expired"):
                        self.abandoned_pickups += 1
                    entry["expired"] = True

            # In order of how much the evidence is worth.
            # 1. The flag named the chest outright. No room is consulted, so no amount of walking can lose it.
            chest = entry.get("chest")
            if chest is not None:
                self.placed_by_flag += 1
            else:
                # 2. The rooms the player was actually in around the pickup, nearest first.
                chest = None
                for index, candidate in enumerate(self._candidate_rooms(entry)):
                    try:
                        found = chest_berries.chest_for(candidate, berry_id)
                    except Exception:
                        found = None
                    if found is not None:
                        chest = found
                        if index:
                            self.placed_by_history += 1
                        break
            if chest is None:
                # 3. Nothing places it yet. HELD, not dropped: counting this in a field nobody read is exactly how
                # a chest opened on the way out of a room went missing without a word. Bounded by
                # `_UNPLACEABLE_HOLD_SECONDS`, after which the player is TOLD, by berry name.
                waited = self.clock() - entry.get("since", self.clock())
                if waited < self._UNPLACEABLE_HOLD_SECONDS:
                    still_pending.append(entry)
                    continue
                self.berries_in_a_room_with_no_such_chest += 1
                berry_name = chest_berries.CHEST_BERRY_ID_TO_NAME.get(berry_id, str(berry_id))
                self.unplaceable_notices.append(
                    f"Pokemon XD: a {berry_name} reached the Bag but no chest in any room you were in around "
                    f"then holds it, so no chest check could be sent. If you just opened a chest, use "
                    f"`!checked` to see what is still missing.")
                continue

            name = CHEST_ID_TO_LOCATION.get(chest)
            self._clear(block_base, berry_id)
            if name is None or name in already_checked:
                continue   # a real chest that is not an AP location, or one already sent
            names.append(name)
            self.credits += 1
            self.credited_by_room[where] = self.credited_by_room.get(where, 0) + 1

        self.pending = still_pending
        return names

    def _clear(self, block_base: int, berry_id: int) -> None:
        """Return the berry's slot to zero so the next pickup of it is unambiguous. A failed clear is counted,
        never raised: the credit has already happened, and the baseline is reset either way so the tracker cannot
        double-count from a stale high-water mark."""
        try:
            # Same window as the read, and for a sharper reason -- `clear_item` WRITES. The old pairing had it
            # clearing up to 328 bytes past the end of the array.
            window = resolve_item_read_window(block_base, berry_id)
            if window is not None:
                clear_item(window[0], window[1], berry_id)
        except Exception:
            self.clear_failures += 1
        self.last_seen[berry_id] = 0

    def backfill_candidates(self, already_checked: "frozenset[str]" = frozenset()) -> "list[str]":
        """Location names that MIGHT be the chest(s) opened before this client started.

        One entry per chest sharing a carried berry, unchecked ones only, sorted for a stable notice. Deliberately
        not narrowed: the only thing that would narrow it is the room, which a baseline sighting does not have."""
        from .game_data import chest_berries

        names: "list[str]" = []
        for berry_id in sorted(self.baseline_carried):
            for chest, (assigned, _quantity) in sorted(chest_berries.CHEST_BERRY_ASSIGNMENT.items()):
                if assigned != berry_id:
                    continue
                name = CHEST_ID_TO_LOCATION.get(chest)
                if name and name not in already_checked and name not in names:
                    names.append(name)
        return names

    def unambiguous_backfill(self, already_checked: "frozenset[str]" = frozenset()) -> "list[str]":
        """Carried berries whose chest is DEDUCIBLE, credited rather than announced.

        A berry already in the Bag at the first poll becomes the BASELINE, because a quantity already there says
        nothing about when it got there -- so a chest opened before the client connected, during a reconnect, or in the
        minutes before the save block resolves (exactly where the Pokemon HQ Lab's three chests are) can never fire.

        Crediting one looks like a 1-in-17 guess: seven berries cover 115 chests and a carried berry has no room. But
        the candidate set is those seventeen MINUS every one already checked, and the server tells us which those are.
        When that leaves exactly ONE, the berry can only have come from that chest -- a deduction, not a coin flip.

        So this credits only the singletons; two or more candidates and `backfill_candidates` /`backfill_notice` handle
        the ambiguous case. `_clear` zeroes a berry's slot the moment its chest is credited, so a chest berry sitting in
        the Bag is already evidence that its chest was opened and not yet sent."""
        from .game_data import chest_berries

        out: "list[str]" = []
        for berry_id in sorted(self.baseline_carried):
            candidates = [
                name for chest, (assigned, _q) in sorted(chest_berries.CHEST_BERRY_ASSIGNMENT.items())
                if assigned == berry_id
                for name in (CHEST_ID_TO_LOCATION.get(chest),)
                if name and name not in already_checked
            ]
            if len(candidates) == 1:
                out.append(candidates[0])
                self.backfilled_unambiguously += 1
        return out

    def backfill_notice(self, already_checked: "frozenset[str]" = frozenset()) -> "list[str]":
        """The lines the client prints once, or an empty list when there is nothing to say."""
        from .game_data import chest_berries

        if not self.baseline_carried:
            return []
        carried = ", ".join(
            f"{chest_berries.CHEST_BERRY_ID_TO_NAME.get(b, b)} x{q}"
            for b, q in sorted(self.baseline_carried.items())
        )
        candidates = self.backfill_candidates(already_checked)
        lines = [
            f"{len(self.baseline_carried)} chest berry/berries were ALREADY in the Bag when this client "
            f"started watching ({carried}).",
            "That means at least one chest was opened before the client was running. Those checks cannot "
            "fire on their own -- a berry in the Bag carries no room, and the room is what names the chest.",
        ]
        if candidates:
            shown = ", ".join(candidates[:12])
            more = f" (+{len(candidates) - 12} more, see !chests)" if len(candidates) > 12 else ""
            lines.append(f"Candidates -- NOT a diagnosis, one of these per berry: {shown}{more}")
        lines.append("If you opened one of these, send it by hand with `!checked <name>`.")
        return lines

    def describe(self) -> "list[str]":
        from .game_data import chest_berries

        lines = [f"Chest berries: {self.credits} chest(s) credited."]
        if self.baseline_carried:
            carried = ", ".join(f"{chest_berries.CHEST_BERRY_ID_TO_NAME.get(b, b)} x{q}"
                                for b, q in sorted(self.baseline_carried.items()))
            lines.append(f"  berries already held at first poll (ADDENDUM 246): {carried} "
                         f"-- {len(self.backfill_candidates())} candidate chest(s), use `!checked`")
        rooms = ", ".join(f"{room_name(r)}={n}" for r, n in sorted(self.credited_by_room.items()))
        lines.append(f"  by room: {rooms or 'none yet'}")
        if self.pending:
            held = ", ".join(chest_berries.CHEST_BERRY_ID_TO_NAME.get(e["berry"], str(e["berry"]))
                             for e in self.pending)
            lines.append(f"  pending (waiting for a readable room): {held}")
        if self.abandoned_pickups:
            lines.append(f"  pickups that ran out of patience waiting for a live room read: "
                         f"{self.abandoned_pickups} (ADDENDUM 345: these now fall through to the room "
                         f"history rather than being dropped)")
        # The two rescues, so it is visible which one is doing the work.
        if self.placed_by_flag or self.placed_by_history:
            lines.append(f"  placed by the chest's own flag (room never consulted): {self.placed_by_flag}; "
                         f"placed from a room already left: {self.placed_by_history}")
        # Say which path credited: "instant" and "two seconds" both happen now, and a player who sees the slow
        # one deserves to know why.
        span = _validated_flag_span()
        if span is not None:
            covered = len(_validated_flag_bits())
            lines.append(f"  Chest-flag corroboration (ADDENDA 289/344): {self.flag_corroborated} "
                         f"pickup(s) credited instantly on the open-flag pair, {self.flag_transitions_seen} "
                         f"flag flip(s) seen. {covered} chests carry a measured flag; the rest wait out the "
                         f"{self._CONFIRM_SECONDS:.1f}s window.")
            # A non-zero count here means the flag was seen and thrown away before its berry arrived, i.e. the
            # corroboration window is still too short.
            lines.append(f"    flag flips that expired unused within "
                         f"{self._FLAG_CORROBORATION_SECONDS:.1f}s: {self.flag_transitions_expired}"
                         + (" -- widen _FLAG_CORROBORATION_SECONDS if this keeps climbing"
                            if self.flag_transitions_expired else " (the window is wide enough)"))
            if self.flag_reads_failed:
                lines.append(f"    flag band unreadable on {self.flag_reads_failed} poll(s) -- those fell "
                             f"back to the window, which is the safe direction")
        if self.unplaceable_polls:
            lines.append(f"  polls where a pickup could not be placed yet: {self.unplaceable_polls}")
        if self.berries_in_a_room_with_no_such_chest:
            lines.append(f"  berries that no room you were in could explain: "
                         f"{self.berries_in_a_room_with_no_such_chest} -- held for "
                         f"{self._UNPLACEABLE_HOLD_SECONDS:.0f}s, then reported rather than dropped "
                         f"(ADDENDUM 345); this is the never-credit-the-wrong-chest rule, now audible")
        if self.clear_failures:
            lines.append(f"  berry clears that failed: {self.clear_failures}")
        lines.append("  reserved chest berries: "
                     + ", ".join(f"{chest_berries.CHEST_BERRY_ID_TO_NAME.get(b, b)}({b})"
                                 for b in chest_berries.CHEST_BERRY_IDS))
        return lines


# --- RETIRED: ChestPickupTracker, ChestBandTracker, and the flag-array identity model. ---
# All of them existed to work out WHICH chest an opened berry was by watching the chest-flag bitfield. That model was
# fitted in one cluster and extrapolated across five, and it was wrong four separate times; the best version still
# had to report a `guessed_credits` count. Each chest now holds its OWN berry, so the berry plus the room names the
# chest exactly, and `ChestBerryTracker` is the whole detector. Deleted rather than left in place because dead
# identity code is how the wrong model keeps coming back. `chest_flags.py` and `ChestFlagTracker` are KEPT -- the
# flag array is still real save state and still worth reading for diagnostics, just not a source of identity.


def chest_locations_in_room(room_id: int, already_checked: "frozenset[str]" = frozenset()) -> "list[str]":
    """AP chest location names in `room_id` that have not been checked yet, lowest chest id first. Built from the
    same chest table `!chests` prints -- the ROOM data was never what was wrong here, only the flags."""
    from .game_data import chest_table

    names: "list[str]" = []
    for chest in sorted(chest_table.chests_in_room(room_id), key=lambda c: c["chest"]):
        name = CHEST_ID_TO_LOCATION.get(chest["chest"])
        if name and name not in already_checked and name not in names:
            names.append(name)
    return names


@dataclass
class ChestFlagTracker:
    """Watches the chest-flag bitfield and reports newly-opened chests BY ID. One read per poll.

    The first sighting is a baseline, not a batch of events: without that, connecting to a save with 40 chests
    already opened would fire 40 reports at once. Bits only ever go on in this array, but a bit going off (a state
    load) is tolerated by forgetting it, so reopening later reports again rather than being swallowed."""

    seen: "set[int]" = field(default_factory=set)
    established: bool = False

    def poll(self, block_base: int) -> "tuple[int, ...]":
        block = read_chest_flag_block(block_base)
        if block is None:
            return ()
        current = set(open_chest_ids(block))
        if not self.established:
            self.seen = current
            self.established = True
            return ()
        newly = tuple(sorted(current - self.seen))
        self.seen = current
        return newly


# --- Per-area story-byte memory: the pre-load hook. ---
# With travel randomization on, an item can drop the player into an area the story has long since passed, or not
# reached at all, and the game reads ONE global story byte to decide what is in that room -- which NPCs, which
# cutscene, whether the place is even navigable. The map screen is the right hook because writing after the room
# loads is too late; reading the HIGHLIGHTED destination off the map cursor lands the write before the player presses
# A. The cursor's `location_id` is the stable key, since its index moves between sessions.
#
# The rule: a first visit gets the area's FLOOR (game_data/story_bytes.REGION_STORY_WINDOW), a later visit gets the
# HIGHEST BYTE ACHIEVED there, and standing in an area raises that area's remembered mark to the live byte.
#
# NO RESTORE ON EXIT, deliberately: save-on-entry/restore-on-exit needs the client to witness both edges, and a crash
# between them leaves the save holding another area's byte with nothing able to notice, while writing on every ENTRY
# is idempotent and self-correcting. Never writes on a guess -- an unknown destination, an area with no story window
# and an unreadable byte each decline, as does a value that already matches.
#
# `highest_by_region` is persisted because the mark is the only thing that cannot be recovered by looking at the game:
# the save holds one global byte, not a per-area history, so a client that forgot would send the player back to an
# area's FLOOR and undo their progress there.


@dataclass
class AreaStoryByteMemory:
    """Per-area story-byte memory. See the section comment above for the design and why there is no restore."""

    highest_by_region: "dict[str, int]" = field(default_factory=dict)
    visited: "set[str]" = field(default_factory=set)

    writes: int = 0
    declined_unknown_destination: int = 0
    declined_no_window: int = 0
    last_written_region: "str | None" = None
    dirty: bool = False               # something changed that the persisted file does not have yet

    # BACKING OUT OF THE MAP PUTS THE BYTE BACK. The hover write is a pre-load hook, so "no restore" holds for
    # travelling and not for backing out, where the player returns to the room they were already standing in carrying
    # some other area's floor. And it does not stay a wrong live byte: `observe()` then records that foreign value as
    # the CURRENT area's high-water mark, so the lab's remembered byte becomes Agate's floor -- permanently, in a file
    # built to outlive the client, and re-applied on every future entry. Hence the restore happens BEFORE any
    # recording.
    #
    # Two things make it safe. `saved_byte` is the value from before the FIRST write of a map visit, so a player who
    # hovers six destinations gets back the one they started with. And `_write_outstanding` HARD-LOCKS `observe()` for
    # every region while a hover write is in the air, so no ordering lets a foreign byte reach the memory.
    saved_byte: "int | None" = None          # the byte from before this map visit's first write
    last_written_target: "int | None" = None # the value the most recent hover write put there
    _write_outstanding: bool = False         # a hover write is live; observe() must record nothing
    restores: int = 0
    declined_restores: int = 0               # real progress outranked the saved value -- never rolled back
    # Hover writes refused because the live byte could not be read. Counted rather than silent, because "nothing
    # happened" and "we chose not to" look identical from the outside.
    declined_unreadable_byte: int = 0
    # Does this slot hold the Scooter Upgrade? Set by the client from `items_received` every tick. Without it every
    # SS Libra tier is capped at the stranded floor -- including a high-water mark recorded before the item existed,
    # which is why the cap is applied to the RESULT rather than only to the floor lookup.
    scooter_held: bool = False
    capped_ss_libra: int = 0
    # Observes refused because the live byte was a hover write made for a DIFFERENT destination than the one the
    # player landed in.
    declined_foreign_commit: int = 0
    # This file was written by a client old enough to have poisoned its own marks, so they were dropped on load.
    # Surfaced in `describe()` so a player sees why an area re-entered at its floor.
    discarded_stale_schema: bool = False
    # The last (region, byte) actually recorded, used to spot a byte carried in from elsewhere. Deliberately NOT
    # persisted -- it describes one session's movement, not the player's progress.
    _last_observed_region: "str | None" = None
    _last_observed_byte: "int | None" = None
    declined_inherited_byte: int = 0
    # Hovers over an area whose floor writes are paused (story_bytes.FLOOR_WRITES_PAUSE_ABOVE, `target_for`). Its
    # own counter rather than `declined_no_window`, because the two mean opposite things: no-window is "we have
    # nothing to say about this place", this is "we have something and are deliberately not saying it".
    declined_floor_paused: int = 0
    # The poisoned-byte guard's counters. Separate from every "declined" above because they are the only ones that
    # describe a WRITE rather than a refusal to record.
    poison_clamps: int = 0
    declined_poison_no_mark: int = 0
    declined_poison_busy: int = 0
    last_poison_clamp: "tuple[str, int, int] | None" = None   # (region, found, restored)
    declined_above_ceiling: int = 0

    # Optional for the same reason StoryByteOverride's is.
    write_log: "StoryByteWriteLog | None" = None

    def observe(self, region: "str | None", story_byte: "int | None") -> bool:
        """Raise `region`'s high-water mark to `story_byte`. Returns True when the memory changed.

        Called with wherever the player actually IS, which is how the mark gets raised: the byte advances while they
        play, and the area they were standing in is the area that earned it.

        Records NOTHING while a hover write is outstanding. The live byte then belongs to a map destination rather
        than to anywhere the player has been, and writing it into the memory is the permanent, persisted corruption
        this guard exists to prevent. Declining is free -- the byte is restored or committed within a poll or two
        and the mark is taken then, from a value that means something."""
        if region is None or story_byte is None:
            return False
        if self._write_outstanding:
            return False
        # A byte written FOR one destination is never another one's mark, and a COMMIT is not a promise that the
        # player went where the cursor was resting. The sequence needs no race: the cursor rests on Agate so the hover
        # writes Agate's 0x19; the player confirms a different icon; `left_map_screen` correctly calls it a trip,
        # commits the byte and releases the lock; and the next `observe()` records 0x19 against the region they LANDED
        # in. Land in the Pokemon HQ Lab and its mark becomes 0x19, past 0x17, the top of its whole ladder --
        # permanently, and re-applied on every future entry.
        #
        # The lab has no static floor, so `target_for` is driven purely by rules topping out at 0x17 and by this
        # mark, and a poisoned mark simply wins. That was also a CYCLE: a later area's mark satisfies an
        # `AreaFloorRule` for an earlier one, hovering the lab then WRITES that value, and banking it feeds the memo
        # witness, the next rule along, and `target_for` again.
        #
        # The cost is exactly one value. While the live byte still equals our write the mark does not move; the moment
        # the GAME advances it, the value differs and is recorded normally.
        if self.last_written_target is not None and story_byte == self.last_written_target:
            self.declined_foreign_commit += 1
            return False
        # The byte on the ARRIVAL tick belongs to where you came FROM. Every other guard here asks "did WE write
        # this byte"; none asks whether the byte is even about THIS AREA. On the tick the player arrives somewhere,
        # the story byte is still whatever the previous area left in it.
        #
        # The hover write usually prevents that, and cannot when the destination has nothing to be entered at: an
        # always-open area on a FIRST visit has no static window, no satisfied rule and no mark, so `target_for`
        # returns None, we write nothing, and the byte walks in with the player. Measured: play Agate to 0x19,
        # travel to Gateon, and Gateon is a 0x19 area from then on -- which satisfies Kaminko's 0x53 rule, and so
        # on up the chain, with no bug in the rules at all.
        #
        # The test is INHERITANCE, not provenance: a byte that has not moved since the last observation in a
        # DIFFERENT area was carried in, not earned here. The moment the game changes it while the player stands
        # here, it is theirs and it is recorded.
        if (self._last_observed_region is not None
                and region != self._last_observed_region
                and story_byte == self._last_observed_byte):
            self.declined_inherited_byte += 1
            return False
        # A byte above this area's ceiling is not this area's mark, whatever wrote it. Belt and braces beside
        # `clamp_poisoned_byte`: the clamp runs first and normally means this never sees one, but a poll where the
        # clamp declines (no mark yet, another writer busy) would otherwise let the foreign value into the
        # persisted file, which is the damage that outlives the session.
        from .game_data import story_bytes as _story_bytes

        _ceiling = _story_bytes.AREA_GUARD_CEILINGS.get(region)
        if _ceiling is not None and story_byte > _ceiling:
            self.declined_above_ceiling += 1
            return False
        self._last_observed_region = region
        self._last_observed_byte = story_byte
        changed = region not in self.visited
        self.visited.add(region)
        if story_byte > self.highest_by_region.get(region, -1):
            self.highest_by_region[region] = story_byte
            changed = True
        if changed:
            self.dirty = True
        return changed

    def target_for(self, region: "str | None") -> "int | None":
        """The byte this area should be entered at, or None when there is no honest answer.

        First visit means the floor. A later visit means the highest this area has ever reached, which is never
        below its floor: an area's floor is what the story had to have reached for the area to exist at all, so
        entering below it would build a room the game has no state for."""
        from .game_data import story_bytes

        if region is None:
            return None
        # FIRST, above every candidate, because the candidates are the problem for a paused area. Kaminko's mark is
        # a floor and its first-visit byte is 0x03, so once the player has been there the answer is always "whatever
        # byte you happened to be carrying the last time you walked in" -- a number about them, not about the manor.
        # Returning None means `poll` writes nothing at all, which for an always-open area with no gated content is
        # the honest answer.
        #
        # The pause lifts on a RULE, not on a byte: `floor_writes_are_paused` asks `dynamic_region_floor`, so the
        # moment `AreaFloorRule("Kaminko's House", 0x53, ...)` is satisfied this stops returning early and the area
        # behaves as before. Asking the rule table rather than hardcoding a second byte keeps the two from drifting.
        if story_bytes.floor_writes_are_paused(region, self.highest_by_region):
            self.declined_floor_paused += 1
            return None
        # Two sources of floor, not one. The static window says where an area's FIRST visit sits; the rule table
        # says where its SECOND one does, conditional on what other areas have reached. Gateon Port and Kaminko's
        # House have no window at all -- both always-open -- so for the mid-game loop the rule is the only floor.
        #
        # `area_entry_floor`, NOT `region_floor`: `region` here is a MAP DESTINATION's region, and a destination is
        # several tiers. The SS Libra icon named the scooter-upgraded ship (0x5A) rather than the stranded first
        # visit (0x4E), so the first hover skipped the stranded visit entirely and the rule meant to raise it to
        # 0x5A could never bind.
        candidates = [
            value for value in (
                story_bytes.area_entry_floor(region),
                story_bytes.dynamic_region_floor(region, self.highest_by_region),
                # The Scooter Upgrade IS SS Libra's second floor. It has to be a candidate here rather than merely
                # an un-capping, because nothing else can ever name 0x5A -- `area_entry_floor` is the ICON's first
                # tier (0x4E) by design.
                self._scooter_floor(region),
            )
            if value is not None
        ]
        # AN AREA'S OWN MARK IS A FLOOR, not a tie-breaker. The high-water lookup used to sit below an early
        # return, so an area with no static window and no satisfied rule produced no candidates, returned None, and
        # the hover wrote nothing -- so the room was built from whatever byte the player was carrying.
        #
        # The HQ Lab is the worst case: `area_entry_floor` is None for it and all three of its rules need marks it
        # does not have early on (Kaminko 0x07, its own 0x0D, or Gateon 0x16). So for the whole early game the lab
        # had NO floor, and walking in from Agate carried Agate's 0x19 in. That is the other half of "later areas
        # writing to the areas before them": here the earlier area has nothing of its own to be restored to, so the
        # later area's byte simply stays.
        #
        # The mark is a candidate rather than a max() applied afterwards, which is what makes it work when it is the
        # only thing we know. `max()` still picks the highest, so a rule that outranks the mark still wins and a rule
        # can still never drag an area backwards.
        mark = self.highest_by_region.get(region)
        if mark is not None:
            candidates.append(mark)
        if not candidates:
            return None  # never been there and no rule satisfied -- nothing to say, so say nothing
        return self._cap_ss_libra(region, max(candidates))

    def _scooter_floor(self, region: str) -> "int | None":
        """0x5A for the real-ship region once the Scooter is held, else nothing.

        SS Libra (stranded) is excluded on purpose: that region IS the low tier, where the stranded first visit
        happens, so raising it would mean the Scooter deletes the visit it is supposed to come after."""
        if not self.scooter_held or region != "SS Libra":
            return None
        return SS_LIBRA_SCOOTER_FLOOR

    def _cap_ss_libra(self, region: str, value: int) -> int:
        """Without the Scooter Upgrade, no SS Libra tier goes above the stranded floor.

        Applied to the RESULT, not to the floor lookup: the high-water branch can hand back 0x5A from a mark
        recorded in an earlier session, and a gate that only filtered the static floor would be walked straight past
        by the memory's own file. This is the CAP half only -- the raise lives in `_scooter_floor`, and they are
        separate because the cap has to outrank a persisted mark while the raise must not touch the stranded
        region."""
        if self.scooter_held or region not in SS_LIBRA_REGIONS:
            return value
        if value <= SS_LIBRA_STRANDED_FLOOR:
            return value
        self.capped_ss_libra += 1
        return SS_LIBRA_STRANDED_FLOOR

    # --- Put a foreign byte back where the area left it. ---
    # The restore target is the area's OWN MARK, because a mark only records a value the GAME put in the byte while
    # the player stood in that area -- the one number on hand that is both this area's and real. No mark means no
    # answer, and this declines rather than inventing the floor, which is what the next hover would give them anyway.
    #
    # What it will not touch, each for its own reason:
    #   * A byte that is merely high. `story_bytes.poisoned_byte` also requires the value to be a floor this client
    #     writes for somewhere else -- see that function for why the ceiling alone is not safe to write on.
    #   * A map visit in progress (`_write_outstanding`). The hover write is SUPPOSED to be another area's floor;
    #     `left_map_screen` owns undoing it.
    #   * Anything at or above `VICTORY_STORY_BYTE`: a clamp that erases a won game is permanent once they save.
    #   * A caller that says another writer holds the byte (`busy`). Two writers on one value is the bug class this
    #     project keeps finding; this one yields rather than joins in.
    def clamp_poisoned_byte(self, block_base: int, current_region: "str | None",
                            story_byte: "int | None", busy: bool = False) -> "str | None":
        """One tick, before anything records or writes. Returns a note when it puts a byte back, else None."""
        from .game_data import story_bytes as _story_bytes

        if not _story_bytes.poisoned_byte(current_region, story_byte):
            return None
        if story_byte >= VICTORY_STORY_BYTE:
            return None
        if busy or self._write_outstanding:
            self.declined_poison_busy += 1
            return None
        restore = self.highest_by_region.get(current_region)
        if restore is None or restore >= story_byte:
            # No mark to go back to, or one that is not actually lower. Either way there is nothing better than
            # leaving it alone and saying so through the counter.
            self.declined_poison_no_mark += 1
            return None
        try:
            poke_story_byte(block_base, restore & 0xFF)
        except Exception:
            return None
        self.poison_clamps += 1
        self.last_poison_clamp = (current_region, story_byte, restore)
        self.last_written_target = restore   # ADDENDUM 288/293 -- claimed, so observe() does not bank it back
        if self.write_log is not None:
            self.write_log.record("poison clamp", current_region, story_byte, restore,
                                  "a floor belonging to another area was left in this one")
        return (f"Story byte: {current_region} cannot hold 0x{story_byte:02X} (its ceiling is "
                f"0x{_story_bytes.AREA_GUARD_CEILINGS[current_region]:02X}) -- put back to 0x{restore:02X}, "
                "the highest this area has really reached.")

    def poll(self, block_base: int, hovered_region: "str | None",
             current_region: "str | None", story_byte: "int | None") -> "str | None":
        """One tick. `hovered_region` is the map destination under the cursor (None when not on the map),
        `current_region` is where the player is standing. Returns a one-line note when it writes."""
        self.observe(current_region, story_byte)
        if hovered_region is None:
            return None
        target = self.target_for(hovered_region)
        if target is None:
            self.declined_no_window += 1
            return None
        if story_byte is not None and story_byte == target:
            return None  # already right -- an idle map screen must not write every tick
        # An UNREADABLE byte declines rather than writing blind. It used to fall straight through to the write, and
        # then to `saved_byte`, which is only captured `if story_byte is not None` -- so nothing was recorded to
        # restore to. `left_map_screen` then reads a missing `saved_byte` as "no map visit in progress", releases
        # `_write_outstanding` and restores nothing, leaving the hovered destination's floor in the save for
        # `observe()` to bank into the persisted file and re-apply on every future entry. Worse in the two-hover
        # case: hover A on a tick whose read fails, hover B on a tick that succeeds, and `saved_byte` captures OUR
        # OWN write from A, so backing out "restores" A's floor while printing a confident, correct-looking note.
        #
        # Declining costs nothing -- the map screen polls ~20 times a second, so the next tick tries again long
        # before the cursor settles.
        if story_byte is None:
            self.declined_unreadable_byte += 1
            return None
        try:
            poke_story_byte(block_base, target & 0xFF)
        except Exception:
            return None
        # Capture the pre-write value ONCE per map visit. Hovering a second destination overwrites the first
        # write, not this: a player who backs out wants the byte they had before opening the map.
        if self.saved_byte is None and story_byte is not None:
            self.saved_byte = story_byte
        self._write_outstanding = True
        self.last_written_target = target
        self.writes += 1
        self.last_written_region = hovered_region
        first = hovered_region not in self.visited
        if self.write_log is not None:
            self.write_log.record(
                "area memory", hovered_region, story_byte, target,
                "first visit floor" if first else "highest reached in this area")
        return (f"Area story byte: {hovered_region} -> 0x{target:02X} "
                f"({'first visit' if first else 'highest reached here'}; was "
                f"{'unknown' if story_byte is None else f'0x{story_byte:02X}'})")

    def left_map_screen(self, block_base: int, backed_out: bool) -> "str | None":
        """Called once the player is off the map screen. `backed_out` is True when they returned to the room they
        came from rather than travelling anywhere.

        MUST run before `poll()` on the same tick -- see `saved_byte`. The `_write_outstanding` lock makes that
        ordering safe rather than merely required, but the ordering is what keeps the memory recording real values
        instead of skipping a tick.

        Returns a one-line note when it restores, else None. Never raises."""
        if self.saved_byte is None:
            # Only safe because a write is now impossible without capturing `saved_byte`. If a write DID happen,
            # releasing the lock here is what lets a foreign byte reach `observe()` and the persisted file.
            if self._write_outstanding and self.last_written_target is not None:
                # A write we cannot undo. Hold the lock rather than banking whatever it left behind.
                self.declined_restores += 1
                return None
            self._write_outstanding = False
            return None
        saved = self.saved_byte
        self.saved_byte = None

        if not backed_out:
            # They travelled. The written value is the whole point of having written it -- it is what the
            # destination's room is about to be built from. Commit it and release the lock.
            self._write_outstanding = False
            return None

        live = read_story_byte(block_base)
        if live is not None and live > saved and live != self.last_written_target:
            # Real progress outranked the saved value. Cannot happen on a map screen, which is a menu, but a
            # restore that clobbers genuine progress is far worse than one that declines.
            self.declined_restores += 1
            self._write_outstanding = False
            return None
        try:
            poke_story_byte(block_base, saved & 0xFF)
        except Exception:
            # The lock stays ON deliberately. A failed restore means the live byte is still some destination's
            # floor, and recording THAT is the corruption -- better to record nothing until a later poll fixes it.
            return None
        self._write_outstanding = False
        self.restores += 1
        if self.write_log is not None:
            self.write_log.record("map back-out", self.last_written_region or "map screen",
                                  self.last_written_target, saved,
                                  "backed out of the map without travelling -- pre-map byte put back")
        return (f"Backed out of the map -- story byte restored to 0x{saved:02X} "
                f"(the hover had set it to 0x{self.last_written_target:02X} for "
                f"{self.last_written_region}).")

    def describe(self) -> "list[str]":
        lines = [f"Area story-byte memory: {len(self.visited)} area(s) seen, {self.writes} write(s), "
                 f"{self.restores} back-out restore(s)."]
        if self.discarded_stale_schema:
            lines.append("  Marks from an older client were discarded on load (ADDENDUM 276) -- areas will "
                         "re-enter at their floors until you visit them again. This is the repair for the "
                         "0x19 softlock, not a fault.")
        if self.declined_inherited_byte:
            lines.append(f"  Declined {self.declined_inherited_byte} byte(s) carried in from another area "
                         f"(ADDENDUM 279) -- a mark only rises from a byte that MOVED while you were here.")
        if self.declined_foreign_commit:
            # Visible on purpose: this counter going up means the bug is being caught, and a player who reported
            # it should be able to watch it happen rather than take it on faith.
            lines.append(f"  Declined {self.declined_foreign_commit} committed hover write(s) that belonged "
                         f"to a destination other than the one you landed in (ADDENDUM 275).")
        from .game_data import story_bytes

        satisfied = story_bytes.satisfied_area_floor_rules(self.highest_by_region)
        for region in sorted(self.visited):
            floor = story_bytes.area_entry_floor(region)   # ADDENDUM 247 -- same source target_for uses
            dynamic = story_bytes.dynamic_region_floor(region, self.highest_by_region)
            if dynamic is not None and (floor is None or dynamic > floor):
                floor = dynamic
            high = self.highest_by_region.get(region)
            # Parenthesised deliberately: as one bare ternary the floor suffix binds to the else branch only, so a
            # region WITH a remembered value silently lost its floor from the readout.
            head = f"  {region}: highest 0x{high:02X}" if high is not None else f"  {region}: highest unknown"
            tail = f", floor 0x{floor:02X}" if floor is not None else ", no window"
            lines.append(head + tail)
        if satisfied:
            lines.append("  second-visit floors in effect (ADDENDUM 184):")
            for rule in satisfied:
                lines.append(f"    {rule.target} >= 0x{rule.floor:02X} -- {rule.what}")
        if self.declined_floor_paused:
            # Named per area rather than as a bare count, so "we are deliberately not writing Kaminko's floor"
            # reads off `!areas` as the feature it is rather than as something broken.
            paused = ", ".join(f"{area} (>= 0x{byte:02X})"
                               for area, byte in sorted(story_bytes.FLOOR_WRITES_PAUSE_ABOVE.items()))
            lines.append(f"  declined (floor writes paused until a rule applies -- {paused}): "
                         f"{self.declined_floor_paused}")
        if self.declined_no_window:
            lines.append(f"  declined (no story window for the destination): {self.declined_no_window}")
        if self.saved_byte is not None:
            lines.append(f"  holding 0x{self.saved_byte:02X} to put back if you back out of the map")
        if self._write_outstanding:
            lines.append("  a hover write is outstanding -- no area mark is being recorded until it settles")
        if self.declined_restores:
            lines.append(f"  restores declined because real progress outranked the saved value: "
                         f"{self.declined_restores}")
        return lines

    def to_json(self) -> dict:
        return {"schema": AREA_MEMORY_SCHEMA_VERSION,
                "highest_by_region": dict(self.highest_by_region), "visited": sorted(self.visited)}

    def load_json(self, data: dict) -> None:
        """Tolerant on purpose: a corrupt or hand-edited file must degrade to "no memory yet" rather than taking the
        client down, because this file is the only thing standing between the player and an area reset to its
        floor."""
        try:
            # Marks written by a client that could poison them are DISCARDED, because there is no way to tell them
            # apart: a poisoned mark is a plain integer that looks exactly like a real one. A player carrying an old
            # file otherwise keeps getting the bad byte written on every hover of that icon -- 0x19 into the HQ Lab
            # and Kaminko's, past the end of both their ladders, which is the softlock.
            #
            # Safe in a way a cleverer repair would not be: the marks are a CONVENIENCE. Everything they hold is
            # re-derived from floors and rules the moment the player walks back into an area, and an area with no
            # mark enters at its floor -- the conservative value. Losing them costs a little accuracy for one
            # session; keeping a poisoned one costs the run.
            if int(data.get("schema") or 0) < AREA_MEMORY_SCHEMA_VERSION:
                self.highest_by_region = {}
                self.visited = set()
                self.discarded_stale_schema = True
                self.dirty = True
                return
            highest = data.get("highest_by_region") or {}
            self.highest_by_region = {
                str(k): int(v) for k, v in highest.items() if isinstance(v, (int, float))
            }
            self.visited = {str(name) for name in (data.get("visited") or [])}
            # Anything with a remembered value has necessarily been visited, even if the lists disagree.
            self.visited |= set(self.highest_by_region)
        except Exception:
            self.highest_by_region = {}
            self.visited = set()
        self.dirty = False


@dataclass
class StoryByteTracker:
    """Watches the story byte and reports advances. One 20-byte read per poll."""

    current: "int | None" = None
    previous: "int | None" = None
    record: bytes = b""
    advances: int = 0
    # An implausible byte is "unreadable", not "unchanged". `poll` bails before updating anything, so `describe()`
    # used to report `self.current` -- the last value it happened to trust, minutes earlier -- with nothing to say it
    # was stale, which made a successful hand-written 0xFF look like a write that had not taken. Refusing to ADVANCE
    # on an implausible value is right; presenting a stale number as current is the part that misled.
    last_implausible: "int | None" = None

    @property
    def story_value(self) -> "int | None":
        """GS variable 964 -- the number field scripts compare against. Derived from the record this tracker has
        already read, so it costs no extra memory access."""
        if len(self.record) < 2:
            return None
        return (struct.unpack(">H", self.record[:2])[0] >> STORY_VALUE_SHIFT) & 0xFFF

    def poll(self, block_base: int) -> "tuple[int, int] | None":
        """Returns `(from_value, to_value)` on a change, else None. The first sighting is not a change."""
        try:
            record = read_story_record(block_base)
        except Exception:
            return None
        value = record[STORY_BYTE_OFFSET]
        if value > STORY_BYTE_MAX_PLAUSIBLE:
            # Remembered so `describe()` can say the byte is unreadable instead of handing back whatever it last
            # trusted. Still not an advance, and `current` is deliberately left alone -- the last trusted value is
            # worth keeping, it just must not be presented as the live one.
            self.last_implausible = value
            return None
        self.last_implausible = None
        self.record = record
        if value == self.current:
            return None
        self.previous, self.current = self.current, value
        if self.previous is None:
            return None
        self.advances += 1
        return (self.previous, value)

    def describe(self) -> str:
        if self.last_implausible is not None:
            # Said first and plainly, because everything below it is history rather than state.
            line = (f"Story byte: reads 0x{self.last_implausible:02X}, which is above the plausible ceiling "
                    f"(0x{STORY_BYTE_MAX_PLAUSIBLE:02X}) -- treated as UNREADABLE, so nothing in this client "
                    f"is acting on it.")
            if self.current is not None:
                line += (f"\n  Last value this client trusted: 0x{self.current:02X} -- that is history, not "
                         f"what is in memory now.")
            line += ("\n  A byte this high is not a value the game reaches on its own; something wrote it "
                     "(see STORY_OVERRIDE_VALUE's own note on why 0xFF was abandoned).")
            return line
        if self.current is None:
            return "Story byte: not read yet (needs the save block to be resolved first)."
        landmark = STORY_BYTE_LANDMARKS.get(self.current)
        line = f"Story byte: 0x{self.current:02X} ({self.current})"
        # The byte is `value >> 3` of GS variable 964, which is what field scripts read -- and they test it by
        # EQUALITY as often as by threshold. 304..311 all print as 0x26, so a byte-only readout cannot tell a working
        # state from a broken one. The live value is said first and in full.
        value = self.story_value
        if value is not None:
            line += f"  --  story variable 964 = {value}"
            if value % STORY_VALUE_STEP:
                line += (f"  <-- NOT a multiple of {STORY_VALUE_STEP}. The game only ever holds multiples of "
                         f"{STORY_VALUE_STEP}, so this is a rung no script tests for; something wrote the "
                         f"byte without its low three bits.")
        if landmark:
            line += f"\n  last matching logged checkpoint: {landmark}"
        if self.previous is not None:
            line += f"\n  was 0x{self.previous:02X} ({self.advances} change(s) seen this session)"
        if self.record:
            line += f"\n  full travel-control record: {self.record.hex()}"
            line += ("\n  (+0x00 and the top three bits of +0x01 are the story variable; the rest of +0x01 "
                     "belongs to the variable before it, and +0x04..+0x07 drift on their own)")
        return line


# --- The CURRENT ROOM ID, and the replacement for the retracted "area id" above. ---
# A u16 holding the id of the room the player is standing in, replicated at four addresses that have held identical
# values in every sample. Better than the retracted candidate because it distinguishes ROOMS rather than areas and
# because it is verifiable against data shipped in the ISO.
#
# Four independent things line up, three of which the previous candidate failed:
#
#   1. Survives a reboot. BLOCK_BASE moved 0x80479380 -> 0x804792A0 between boots; this read the same at the same
#      real location on both sides.
#   2. Correct immediately after a save load, which is precisely where the old cache-style value failed.
#   3. Room-level, not area-level: Gateon Port outdoors reads 153, a building inside Gateon reads 147.
#   4. Agrees with the ISO. The values match the `room_id` field of `common_rel`'s treasure table, parsed by
#      `xd_rel_format.read_chest_entry` -- data with no connection to any memory dump. At all three sampled
#      locations where the ISO proves a chest exists, this field reads that chest's room:
#          Cipher Lab  -> 8   (chests 17,18,19,21,22 -- chest 18 is item 506, the ID Card)
#          HQ exterior -> 143 (chest 1)
#          Gateon Port -> 153 (chest 4, three Poke Balls)
#      13 of the 17 surviving candidates scored 0/3 or 1/3 on that test; only this family scored 3/3.
#
# Because the ids ARE the ISO's room ids, any room containing a chest can be named from the ISO. Rooms without
# chests still need naming once.

ROOM_ID_ADDRESS = 0x80446F32
ROOM_ID_MIRRORS = (0x80814AB6, 0x8083352E, 0x8083357E)
ROOM_ID_MAX_PLAUSIBLE = 0x400

# Every id below 200 was observed in play with `!room`. The six that predate the player's own compilation were
# validated four ways and are unchanged except where the newer data is more specific (140 was "Pokemon HQ Lab
# (interior)" and is really the downstairs-right room -- the lab has four distinct interior rooms, 138-141).
# Chest numbers in a name are the player's own labelling against `game_data/chest_table.py`'s indices.
KNOWN_ROOM_IDS: "dict[int, str]" = {
    1: "Cipher Lab (left door) -- chests 16, 17",
    7: "Cipher Lab (inside right door)",
    8: "Cipher Lab -- chests 17-22",
    10: "Cipher Lab (downstairs) -- chests 24-27",
    11: "outside the Cipher Lab (first visit)",
    20: "Mt. Battle (outside) -- chest 29",
    21: "Mt. Battle (inside) -- shop",
    125: "Agate Relic Path -- chest 15",
    126: "Agate Cave -- chests 12, 13",
    132: "Agate Village (first village) -- chests 10, 11, 14",
    138: "Pokemon HQ Lab (interior, downstairs left)",
    139: "Pokemon HQ Lab (interior, upstairs left) -- chest 3, the player's room",
    140: "Pokemon HQ Lab (interior, downstairs right)",
    141: "Pokemon HQ Lab (interior, upstairs right)",
    143: "Pokemon HQ Lab (exterior) -- chest 1",
    146: "Krabby Klub basement -- chest 5",
    147: "Gateon Port (building by the entrance)",
    153: "Gateon Port",
    156: "Gateon Port shop",
    158: "Gateon Tower 1F -- chests 6, 7",
    160: "Gateon Tower 3F -- chest 8",
    # ADDENDUM 394: measured live by the player. 164 is the EXTERIOR and was in shops.py as the shop for
    # months, which renamed the shelf on the way past and un-renamed it on the way in.
    163: "Outskirt Stand (inside) -- shop",
    169: "Kaminko's house (inside, first visit)",
    173: "Kaminko's house (outside, first visit)",
    910: "map screen",
}


def room_name(room_id: "int | None") -> str:
    """A human name for a room id, best available.

    `KNOWN_ROOM_IDS` wins when it has an entry -- it is hand-recorded and most specific, and several of its names
    carry detail no other table has. Otherwise the name is DERIVED from `shops.SHOPS` and
    `chest_regions.ROOM_TO_REGION`, which between them already describe rooms this table does not: eight of the ten
    shop rooms had no entry here, so `!room` in the Phenac City shop said "room 103 (unnamed)" while both other
    tables knew exactly what it was. Typing the eight names in would have fixed the instance and left the class."""
    if room_id is None:
        return "unknown"
    known = KNOWN_ROOM_IDS.get(room_id)
    if known is not None:
        return known
    try:
        from .game_data import shops

        shop = shops.SHOPS_BY_ROOM.get(room_id)
        if shop is not None:
            return f"{shop.name} (room {room_id})"
    except Exception:
        pass
    try:
        from .game_data import chest_regions

        region = chest_regions.ROOM_TO_REGION.get(room_id)
        if region is not None:
            return f"{region} (room {room_id}, unnamed)"
    except Exception:
        pass
    return f"room {room_id} (unnamed)"


def read_room_id() -> "int | None":
    """The id of the room the player is currently in, or None when it cannot be trusted.
    Requires a MAJORITY of the four replicated copies to agree, so one copy being mid-update -- or the address
    being wrong on some future build -- yields "unknown" rather than a confident wrong answer."""
    values: list[int] = []
    for address in (ROOM_ID_ADDRESS, *ROOM_ID_MIRRORS):
        try:
            raw = read_bytes(address, 2)
        except Exception:
            continue
        values.append((raw[0] << 8) | raw[1])
    if not values:
        return None
    best = max(set(values), key=values.count)
    if values.count(best) * 2 <= len(values):
        return None  # no majority -- the copies disagree, so we do not know
    if best == 0 or best > ROOM_ID_MAX_PLAUSIBLE:
        return None
    return best


@dataclass
class RoomTracker:
    """Last trustworthy room id plus transition reporting. Four 2-byte reads per poll."""

    current: "int | None" = None
    previous: "int | None" = None
    changes: int = 0
    # "Could not read it" and "it did not change" are not the same answer. Keeping the stale value IS correct here,
    # unlike the story byte: `current` is documented as the last trustworthy room id, and half the poll loop uses it
    # as the fallback when a fresh `read_room_id()` comes back None, so dropping it on an unreadable poll would turn
    # a one-tick hiccup into a lost chest check. What was missing is that nothing could TELL -- `!room` printed the
    # cached room with the same confidence whether it was read this second or two minutes ago.
    unknown_polls: int = 0            # unreadable reads this session, in total
    consecutive_unknown: int = 0      # ...and in a row right now, which is the one that means something

    def poll(self) -> "tuple[int, int] | None":
        observed = read_room_id()
        if observed is None:
            # Counted, not silently folded into "unchanged". `current` is deliberately kept -- see above.
            self.unknown_polls += 1
            self.consecutive_unknown += 1
            return None
        self.consecutive_unknown = 0
        if observed == self.current:
            return None
        self.previous, self.current = self.current, observed
        self.changes += 1
        if self.previous is None:
            return None  # first sighting is not a transition
        return (self.previous, observed)

    def describe(self) -> str:
        if self.current is None:
            return "Room: unknown (no majority among the four copies, or the value is out of range)."
        line = f"Room: {room_name(self.current)} [id {self.current}]"
        # Say so when the cached value is the only thing on offer. Led with, because everything after it describes
        # a room the client may not currently be able to see.
        if self.consecutive_unknown:
            line += (f"  -- STALE: the last {self.consecutive_unknown} read(s) came back unreadable, so this "
                     f"is the last room this client could trust, not necessarily where you are now")
        if self.previous is not None:
            line += f"; came from {room_name(self.previous)} [id {self.previous}]"
        line += f"; {self.changes} room change(s) this session."
        if self.unknown_polls:
            line += f" {self.unknown_polls} unreadable poll(s) so far."
        return line


# --- The MAP SCREEN's highlighted destination: a PRE-LOAD hook. ---
# The story-byte override can only act once `read_room_id()` reports the NEW room, which is after that room has
# loaded and its scripts have already read the byte. While the player is on the map screen (room 910) the game holds
# the currently highlighted destination in a cursor object, so the destination is knowable before they press A. That
# turns "rewind after arriving and hope we beat the room script" into "the byte is already right when the room
# loads".
#
# Found from six full MEM1 dumps taken on the map screen across two identical laps of the same three destinations
# (Phenac City, the Rock Poke Spot, the Cipher Lab, then all three again). One lap is useless: the camera pans to
# whatever is hovered, so ~59k bytes differ between any two hovers and nearly all of it is geometry and a
# re-rendered name label. Requiring each destination to reproduce its OWN value on both laps while all three differ
# from each other left one self-describing object:
#
#     tag+0x00   0x18531013   constant tag -- only 2 hits in all of MEM1, and the decoy is trivially rejected
#     tag+0x08   u32          cursor INDEX             Phenac 1     Rock Spot 9     Cipher Lab 6
#     tag+0x10   f32          destination map x        Phenac 44.0  Rock Spot 70.0  Cipher Lab 21.0
#     tag+0x18   f32          destination map y        Phenac 16.0  Rock Spot -9.0  Cipher Lab -19.0
#     tag+0x1C   f32          x again (the settled target the cursor panned to)
#     tag+0x24   f32          y again
#     tag+0x34   ptr          -> the highlighted-destination RECORD (address constant; contents rewritten)
#     record+0x00 / +0x04  u32  LOCATION ID, stored twice   Phenac 3   Rock Spot 15   Cipher Lab 8
#
# Believed rather than guessed because every field reproduced to the bit on both laps; because the x/y pair is what
# a table-driven selection object would carry and no amount of animation noise produces a coherent coordinate pair
# that repeats per destination; and because a SECOND object carries the same index behind its own signature
# (`00 00 00 3A 40 49 0F DB` -- 0x3A followed by pi, index at that address - 4), cross-checking the first without
# sharing an address with it. That second object is a BONUS: it was present on the boot this was found on and
# absent on the next, so `second_index` is optional everywhere and its absence is never a failure.
#
# Confirmed across a reboot: 0x810ED690 no longer held the tag (it had become audio data) and the object had moved
# to 0x810EF4D0, its record with it (0x810EE8A0 -> 0x810F06E0). The tag scan still found exactly 2 hits, the decoy
# still failed both fences (index 2155918116, record pointer 0x00000100), and Phenac City still read index 1,
# location id 3, x 44.0, y 16.0 -- bit-identical. So the VALUES are boot-stable table data and only the ADDRESS
# moves, which is the split this module is built around: resolve by tag, cache the address, re-validate the tag on
# every cached read and fall back to a signature scan rather than believing a stale one. No fixed address for this
# object is exported.
#
# TWO ID SPACES, AND NEITHER IS PICKED HERE. The cursor index (1/9/6) may be a position in the list of currently
# UNLOCKED destinations, which would shift as more unlock and be worthless as a key; the location id (3/15/8) has
# the sparse look of a fixed table id. Cipher Lab's location id is 8, which is also its room id, so the location id
# may simply BE the room id -- but one coincidence is not evidence. `!map` prints both plus the coordinates, so the
# table can be compiled from real data by hovering each destination once.

MAP_SCREEN_ROOM_ID = 910  # KNOWN_ROOM_IDS[910] == "map screen"

MAP_CURSOR_TAG = bytes.fromhex("18531013")
MAP_CURSOR_INDEX_OFFSET = 0x08
MAP_CURSOR_X_OFFSET = 0x10
MAP_CURSOR_Y_OFFSET = 0x18
MAP_CURSOR_X_SETTLED_OFFSET = 0x1C
MAP_CURSOR_Y_SETTLED_OFFSET = 0x24
MAP_CURSOR_RECORD_POINTER_OFFSET = 0x34
MAP_CURSOR_STRUCT_SIZE = 0x38  # enough to cover every offset above

MAP_RECORD_LOCATION_ID_OFFSET = 0x00
MAP_RECORD_LOCATION_ID_MIRROR_OFFSET = 0x04
MAP_RECORD_READ_SIZE = 0x08

# The second object carrying the same index, behind its own signature. Index sits immediately BEFORE it.
MAP_CURSOR_SECOND_SIGNATURE = bytes.fromhex("0000003a40490fdb")
MAP_CURSOR_SECOND_INDEX_BACK_OFFSET = 0x04

# Plausibility fences. The one decoy tag hit carried index 2155920132 and a record pointer of 0x00000100, so it
# fails both -- these are deliberately loose enough not to depend on that being the only decoy.
MAP_CURSOR_INDEX_MAX_PLAUSIBLE = 0x100
MAP_LOCATION_ID_MAX_PLAUSIBLE = 0x1000
MAP_CURSOR_COORD_MAX_PLAUSIBLE = 100000.0


@dataclass(frozen=True)
class MapCursorReading:
    """One decoded sighting of the map screen's highlighted-destination cursor. Every field is raw game data --
    this class asserts nothing about what the numbers MEAN (see the two id spaces above)."""

    tag_address: int
    index: int
    x: float
    y: float
    x_settled: float
    y_settled: float
    record_address: int
    location_id: int
    location_id_mirror: int
    second_index: "int | None" = None

    @property
    def settled(self) -> bool:
        """True when the cursor's live position equals the target it was panning toward -- the camera has finished
        moving and this reading is of a destination the player is actually resting on."""
        return self.x == self.x_settled and self.y == self.y_settled

    @property
    def consistent(self) -> bool:
        """True when every redundant copy agrees: the record's duplicated location id, and the second object's copy
        of the index when it was found. False means the numbers were read mid-update."""
        if self.location_id != self.location_id_mirror:
            return False
        return self.second_index is None or self.second_index == self.index


def _plausible_coord(value: float) -> bool:
    return value == value and abs(value) <= MAP_CURSOR_COORD_MAX_PLAUSIBLE  # value == value rejects NaN


def _decode_map_cursor(
    data: bytes, buffer_base: int, tag_offset: int, second_index: "int | None" = None,
) -> "MapCursorReading | None":
    """Decode one tag hit out of `data` (a buffer whose first byte is address `buffer_base`), or None if it fails
    any plausibility fence. Never raises."""
    try:
        index = struct.unpack_from(">I", data, tag_offset + MAP_CURSOR_INDEX_OFFSET)[0]
        x = struct.unpack_from(">f", data, tag_offset + MAP_CURSOR_X_OFFSET)[0]
        y = struct.unpack_from(">f", data, tag_offset + MAP_CURSOR_Y_OFFSET)[0]
        x_settled = struct.unpack_from(">f", data, tag_offset + MAP_CURSOR_X_SETTLED_OFFSET)[0]
        y_settled = struct.unpack_from(">f", data, tag_offset + MAP_CURSOR_Y_SETTLED_OFFSET)[0]
        record = struct.unpack_from(">I", data, tag_offset + MAP_CURSOR_RECORD_POINTER_OFFSET)[0]
    except Exception:
        return None
    if index > MAP_CURSOR_INDEX_MAX_PLAUSIBLE:
        return None
    if not (MEM1_START <= record < MEM1_START + MEM1_SIZE):
        return None
    if not all(_plausible_coord(v) for v in (x, y, x_settled, y_settled)):
        return None
    record_offset = record - buffer_base
    try:
        if 0 <= record_offset <= len(data) - MAP_RECORD_READ_SIZE:
            record_bytes = data[record_offset:record_offset + MAP_RECORD_READ_SIZE]
        else:  # the record fell outside this buffer -- read it directly rather than giving up
            record_bytes = read_bytes(record, MAP_RECORD_READ_SIZE)
        location_id = struct.unpack_from(">I", record_bytes, MAP_RECORD_LOCATION_ID_OFFSET)[0]
        location_id_mirror = struct.unpack_from(">I", record_bytes, MAP_RECORD_LOCATION_ID_MIRROR_OFFSET)[0]
    except Exception:
        return None
    if location_id > MAP_LOCATION_ID_MAX_PLAUSIBLE:
        return None
    return MapCursorReading(
        tag_address=buffer_base + tag_offset, index=index, x=x, y=y, x_settled=x_settled, y_settled=y_settled,
        record_address=record, location_id=location_id, location_id_mirror=location_id_mirror,
        second_index=second_index,
    )


def scan_map_cursor() -> "list[MapCursorReading]":
    """One full-MEM1 read plus a tag scan, returning every hit that survives the plausibility fences. Same cost
    profile as `scan_battle_roster` (one un-chunked 24 MiB read) -- fine on demand, which is all this is used for;
    `MapCursorTracker.resolve()` caches the result so the scan happens once per map visit rather than per poll.
    Never raises: an unreadable MEM1 yields an empty list."""
    try:
        data = read_bytes(MEM1_START, MEM1_SIZE)
    except Exception:
        return []
    second_index: "int | None" = None
    second_hit = data.find(MAP_CURSOR_SECOND_SIGNATURE)
    if second_hit >= MAP_CURSOR_SECOND_INDEX_BACK_OFFSET:
        try:
            candidate = struct.unpack_from(">I", data, second_hit - MAP_CURSOR_SECOND_INDEX_BACK_OFFSET)[0]
            if candidate <= MAP_CURSOR_INDEX_MAX_PLAUSIBLE:
                second_index = candidate
        except Exception:
            second_index = None
    readings: list[MapCursorReading] = []
    hit = data.find(MAP_CURSOR_TAG)
    while hit != -1:
        reading = _decode_map_cursor(data, MEM1_START, hit, second_index)
        if reading is not None:
            readings.append(reading)
        hit = data.find(MAP_CURSOR_TAG, hit + 1)
    return readings


def map_destination_region(reading: "MapCursorReading | None") -> "str | None":
    """The regions.py region a live cursor reading points at, or None when it cannot be resolved.

    Keyed on `location_id`, NEVER on `cursor_index`. A second `!map` sweep disagreed with the first in exactly one
    column -- Phenac City read cursor 1 then cursor 3, the Rock Poke Spot 9 then 13 -- while both kept their
    location id. The cursor index is a position in the list of currently-unlocked destinations, so it shifts as more
    unlock, and that sweep even contains an internal collision (SS Libra and Realgam Tower both at 10).

    None is a real answer, not a failure: an unmeasured id means the caller declines to write rather than guessing."""
    from .game_data import map_destinations

    if reading is None or not reading.consistent or not reading.settled:
        return None
    return map_destinations.region_for_location_id(reading.location_id)


def read_map_cursor_at(tag_address: int) -> "MapCursorReading | None":
    """Cheap re-read of a cursor object whose address is already known -- two small reads, no MEM1 scan. The tag is
    re-checked first, so a cached address that no longer points at the object (a new boot, a freed allocation)
    yields None instead of nonsense."""
    try:
        data = read_bytes(tag_address, MAP_CURSOR_STRUCT_SIZE)
    except Exception:
        return None
    if not data.startswith(MAP_CURSOR_TAG):
        return None
    return _decode_map_cursor(data, tag_address, 0, None)


@dataclass
class MapCursorTracker:
    """Resolves and caches the map-screen cursor object. Read-only: nothing here writes to memory.

    The poll loop calls `resolve()` only while the player is on the map screen, which keeps the full-MEM1 fallback
    scan to about one per map open rather than one per tick. `!map` is the other caller."""

    cached_tag_address: "int | None" = None
    last: "MapCursorReading | None" = None
    scans: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    ambiguous_scans: int = 0

    def resolve(self) -> "MapCursorReading | None":
        """Cheap cached read first; a full MEM1 tag scan only when that fails. None when no plausible cursor object
        exists, which is the ordinary answer anywhere other than the map screen."""
        if self.cached_tag_address is not None:
            reading = read_map_cursor_at(self.cached_tag_address)
            if reading is not None:
                self.cache_hits += 1
                self.last = reading
                return reading
            self.cache_misses += 1
            self.cached_tag_address = None
        self.scans += 1
        readings = scan_map_cursor()
        if not readings:
            return None
        if len(readings) > 1:
            self.ambiguous_scans += 1
        # Ties break toward the LOWEST address, the same determinism rule `cluster_battle_roster` uses.
        reading = min(readings, key=lambda r: r.tag_address)
        self.cached_tag_address = reading.tag_address
        self.last = reading
        return reading

    def describe(self, room_id: "int | None" = None) -> "list[str]":
        """The `!map` readout, as a list of log lines."""
        lines: list[str] = []
        on_map = room_id == MAP_SCREEN_ROOM_ID
        if room_id is None:
            lines.append("Room is unknown right now, so I cannot confirm the map screen is open.")
        elif not on_map:
            lines.append(f"You are not on the map screen -- room reads {room_name(room_id)} [id {room_id}]. "
                         f"Any numbers below are left over from the last time it was open and mean nothing.")
        reading = self.resolve()
        if reading is None:
            lines.append("No map-screen cursor found in memory."
                         + ("" if on_map else " That is the expected answer away from the map screen."))
            return lines
        lines.append(f"Map cursor @0x{reading.tag_address:08X} (record @0x{reading.record_address:08X})")
        lines.append(f"  cursor index : {reading.index}")
        lines.append(f"  location id  : {reading.location_id}")
        lines.append(f"  map position : x={reading.x:g}, y={reading.y:g}"
                     + ("" if reading.settled else f"  (STILL PANNING toward x={reading.x_settled:g}, "
                                                   f"y={reading.y_settled:g} -- let it settle and re-run)"))
        if not reading.consistent:
            lines.append("  WARNING: the redundant copies disagree "
                         f"(location id {reading.location_id} vs {reading.location_id_mirror}"
                         + (f", index {reading.index} vs {reading.second_index}"
                            if reading.second_index is not None else "")
                         + ") -- read mid-update, so re-run before recording this one.")
        elif reading.second_index is not None:
            lines.append(f"  cross-check  : the second object agrees, index {reading.second_index}")
        if reading.settled and reading.consistent:
            known = KNOWN_ROOM_IDS.get(reading.location_id)
            hint = (f"  -- note: room id {reading.location_id} is {known!r}, so the location id may BE the "
                    f"room id" if known else "")
            lines.append(f"  RECORD THIS  : <destination name> = index {reading.index}, "
                         f"location id {reading.location_id}{hint}")
        if self.scans or self.cache_misses:
            lines.append(f"  ({self.scans} MEM1 scan(s), {self.cache_hits} cached read(s), "
                         f"{self.cache_misses} stale-cache re-scan(s)"
                         + (f", {self.ambiguous_scans} scan(s) found more than one candidate"
                            if self.ambiguous_scans else "") + ")")
        return lines


# --- The live party, and the only white-out this game has. ---
# Read out of main.dol (GXXE01) rather than measured: every offset below is the displacement in a one- or
# two-instruction accessor, so nothing here is inferred and nothing can drift.
#
#     heroBiosGetPokemonPtr(hero, i)  0x8014E0E4   hero + 0x30 + i * 0xC4   (and returns 0 for i >= 6)
#     Pokemon::getPokemonDataId()     0x8014B87C   lhz r3, 0x00(r3)
#     Pokemon::getItemDataId()        0x8014B6FC   lhz r3, 0x02(r3)
#     Pokemon::getHp()                0x8014B70C   lhz r3, 0x04(r3)
#     Pokemon::getFriendLevel()       0x8014B6F4   lhz r3, 0x06(r3)
#     Pokemon::getLevel()             0x8014B704   lbz r3, 0x11(r3)
#     Pokemon::getCondition()         0x8014B38C   lbz r3, 0x16(r3)
#     Pokemon::getConditionCount()    0x8014B37C   lbz r3, 0x17(r3)
#     Pokemon::getConditionTurn()     0x8014B36C   lbz r3, 0x18(r3)
#     Pokemon::getConditionTurnNow()  0x8014B35C   lbz r3, 0x19(r3)
#     Pokemon::setExp()               0x8014B5E4   stw r4, 0x20(r3)
#     Pokemon::getMaxHp()             0x8014B864   lhz r3, 0x90(r3)
#     Pokemon::getDarkpokemonDataID() 0x8014B394   lhz r3, 0xBA(r3)
#
# A DIFFERENT STRUCTURE FROM `PARTY_BASE`. The 48-byte records at 0x804280E8 are a display cache; these `Pokemon`
# objects are what the game's own code reads and writes through `heroGetStatus(0, 3, i)`. When the two disagree --
# and they were observed disagreeing about current HP -- these are the ones that are true.
#
# It also explains the recap record's base. `PARTY_RECAP_OFFSET` is 0x3E, which is 0x4E past where record 0 actually
# starts, so every offset measured against it carries that error: `PARTY_RECAP_MAXHP_OFFSET` is 0x42, and
# 0x42 + 0x4E = 0x90, which is `getMaxHp`'s own displacement. That is why max HP always read correctly from there
# and `PARTY_RECAP_SPECIES_OFFSET` (0x32, i.e. class +0x80) never did -- it is not the species field at all. Those
# constants are LEFT ALONE: they are load-bearing for the purification tracker and they work.
#
# THE WHITE-OUT. `fightEncountCheckZenmetu` (0x801F0D9C) is the whole of it, and `fightMain` is its only caller, so
# a white-out is reachable ONLY by losing a battle:
#
#     if hero->battleResumeFloorID == 0:               return   (nowhere to send them)
#     if encounter->zenmetuFlag:                       return   (already handled)
#     if fightFloorIsGcHeroWin(fightGetFightResultId()): return (they won)
#     GSflagOff(803)
#     fightEncountAnnihilationRecovery()   -- heals the party, then heroDecPokedoru(maxPartyLevel * 16)
#     peopleAllBlockMoveScript()
#     floorSetFloorChangeInfo / floorPopAndChange(hero->battleResumeFloorID)   -- the warp
#
# There is no overworld path. The overworld poison tick (`cbPoison`, 0x8014EBF8) fires every 4th step, takes 1 HP
# from anything whose condition is 3 or 4, and explicitly refuses to take the last conscious party member below
# 1 HP -- so poison cannot wipe a party, deliberately, and never calls the white-out. That is why Death Link writes
# HP and then waits for the game rather than trying to stage a white-out itself.

HERO_OFFSET_FROM_BLOCK = -0x40       # the Hero object, relative to the save block base this file resolves
PARTY_OFFSET_FROM_HERO = 0x30        # heroBiosGetPokemonPtr's own constant
POKEMON_STRIDE = 0xC4                # ditto
POKEMON_SLOTS = 6                    # heroBiosGetPokemonPtr returns 0 for i >= 6

POKEMON_DATA_ID_OFFSET = 0x00        # u16BE, the MASTER internal species index (not the compacted one the
                                     # PARTY_BASE display record carries -- see PARTY_SPECIES_OFFSET)
POKEMON_HELD_ITEM_OFFSET = 0x02      # u16BE
POKEMON_HP_OFFSET = 0x04             # u16BE, CURRENT hp
POKEMON_FRIEND_OFFSET = 0x06         # u16BE
POKEMON_LEVEL_OFFSET = 0x11          # u8
POKEMON_CONDITION_OFFSET = 0x16      # u8
POKEMON_CONDITION_COUNT_OFFSET = 0x17
POKEMON_CONDITION_TURN_OFFSET = 0x18
POKEMON_CONDITION_TURN_NOW_OFFSET = 0x19
POKEMON_EXP_OFFSET = 0x20            # u32BE
POKEMON_MAXHP_OFFSET = 0x90          # u16BE
POKEMON_SHADOW_ID_OFFSET = 0xBA      # u16BE

# The two values `cbPoison` acts on, and the only two this project can name with certainty. Everything else is left
# unnamed rather than guessed.
POISON_CONDITIONS = frozenset({3, 4})


def party_slot_address(block_base: int, index: int) -> int:
    """Live `Pokemon` object for party slot `index` -- heroBiosGetPokemonPtr's own arithmetic."""
    return (block_base + HERO_OFFSET_FROM_BLOCK + PARTY_OFFSET_FROM_HERO
            + index * POKEMON_STRIDE)


@dataclass
class LivePartyMember:
    """One live `Pokemon` object -- the structure the GAME reads, not the PARTY_BASE display record.

    Named `LivePartyMember` because `PartyMember` is the 48-byte display record's dataclass above; a second
    `PartyMember` silently rebound the name for the whole module and broke the purification tracker, which
    constructs the first one by keyword. `raw` is kept so a later finding can re-read a field without another
    poll."""

    index: int
    address: int
    raw: bytes

    def _u16(self, offset: int) -> int:
        return struct.unpack_from(">H", self.raw, offset)[0]

    @property
    def data_id(self) -> int:
        return self._u16(POKEMON_DATA_ID_OFFSET)

    @property
    def hp(self) -> int:
        return self._u16(POKEMON_HP_OFFSET)

    @property
    def max_hp(self) -> int:
        return self._u16(POKEMON_MAXHP_OFFSET)

    @property
    def level(self) -> int:
        return self.raw[POKEMON_LEVEL_OFFSET]

    @property
    def experience(self) -> int:
        """ADDENDUM 393: `setExp`'s own field. Read because a Gen III level is DERIVED from experience, so
        "level 0 but sane exp" and "level 0 and exp 0" are different bugs -- the first is a display reading
        the wrong thing, the second is a Pokemon that was built wrong."""
        return struct.unpack_from(">I", self.raw, POKEMON_EXP_OFFSET)[0]

    @property
    def condition(self) -> int:
        return self.raw[POKEMON_CONDITION_OFFSET]

    @property
    def poisoned(self) -> bool:
        return self.condition in POISON_CONDITIONS

    @property
    def occupied(self) -> bool:
        """A slot with a real Pokemon in it. Deliberately strict: Death Link writes off this, and writing a slot
        that only looks occupied would be writing into whatever else lives at that address."""
        return (self.data_id != 0
                and 1 <= self.level <= 100
                and 0 < self.max_hp <= 999
                and self.hp <= self.max_hp)

    @property
    def national_dex(self) -> "int | None":
        """The real National Dex number, from the NUMERIC field.

        `+0x00` is `getPokemonDataId`, the game's MASTER internal index, which is what
        `xd_species_index.national_dex_for` already takes. The 48-byte display record's species field is the
        COMPACTED index (master minus 25 from 277 up), which is why that one has to go through
        `national_dex_for_live_species` first; this one does not, and the two agree for every value in range.

        Nothing here reads a name. `read_party_recap_species` resolves the save-side party BY NAME TEXT and so
        returns None for any nicknamed Pokemon -- a real hole in the catch scan."""
        from .tools.xd_species_index import national_dex_for

        if not self.data_id:
            return None
        try:
            return national_dex_for(self.data_id)
        except Exception:
            return None


def read_party(block_base: int) -> "list[LivePartyMember]":
    """Every occupied party slot, live. Returns [] rather than raising -- a poll loop calls this.

    One read when it can, six when it must: the six records are contiguous, so the whole party is 0x498 bytes at one
    address. A failure falls back to reading each slot on its own, so a single bad slot cannot empty the party --
    "the party is empty" is a meaningful answer to two different callers."""
    out: "list[LivePartyMember]" = []
    base = party_slot_address(block_base, 0)
    block: "bytes | None"
    try:
        block = read_bytes(base, POKEMON_STRIDE * POKEMON_SLOTS)
    except Exception:
        block = None
    for index in range(POKEMON_SLOTS):
        address = party_slot_address(block_base, index)
        if block is not None:
            raw = block[index * POKEMON_STRIDE:(index + 1) * POKEMON_STRIDE]
        else:
            try:
                raw = read_bytes(address, POKEMON_STRIDE)
            except Exception:
                continue
        member = LivePartyMember(index=index, address=address, raw=raw)
        if member.occupied:
            out.append(member)
    return out


def describe_live_party(block_base: int) -> "list[str]":
    """One line per party slot, read RAW: species, level, experience, HP, and whether `occupied` accepts it.

    ADDENDUM 393. Players report wild Poke Spot Pokemon showing as LEVEL 0, and ADDENDUM 268 proved every byte
    of the Poke Spot data correct, so the leading explanation is the player's own: the Pokemon has a real level
    and the in-battle struct is not showing it.

    THIS IS THE PARTY, NOT THE OPPONENT, and cannot answer that directly -- a wild Pokemon lives in the
    battle-roster struct, where the only mapped fields are the names and current HP. What it answers is the
    question one step later: what the thing looks like ONCE CAUGHT.

    THIS DELIBERATELY DOES NOT GO THROUGH `read_party`. `LivePartyMember.occupied` requires `1 <= level <= 100`,
    so a level-0 Pokemon is invisible to every live-party reader in this project -- which is very likely why
    nobody has ever managed to inspect one. The instrument that would see the bug was refusing to.

    Catch the level-0 Pokemon, run `!party`, and one line decides it:

      * level sane, experience sane  -> the battle HUD was lying. Cosmetic, and nothing this project writes.
      * level 0, experience sane     -> the level field is derived wrongly from experience.
      * level 0, experience 0        -> it really was built at level 0, upstream of the HUD.

    Read-only, and returns lines rather than logging, so the caller decides how loud it is."""
    from .species import NATIONAL_DEX

    lines = ["Live party (raw records the GAME reads -- every slot, including ones `occupied` rejects):"]
    shown = 0
    for index in range(POKEMON_SLOTS):
        address = party_slot_address(block_base, index)
        try:
            raw = read_bytes(address, POKEMON_STRIDE)
        except Exception as error:
            lines.append(f"  slot {index + 1}: unreadable ({error})")
            continue
        member = LivePartyMember(index=index, address=address, raw=raw)
        if not member.data_id:
            continue      # never filled; not interesting
        shown += 1
        dex = member.national_dex
        name = NATIONAL_DEX.get(dex) if dex else None
        flags = []
        if member.level == 0:
            flags.append("LEVEL 0")
        if not member.occupied:
            flags.append("rejected by `occupied`, so every other reader skips it")
        note = ("   <-- " + "; ".join(flags)) if flags else ""
        lines.append(
            f"  slot {index + 1}: {name or f'species {member.data_id}'} "
            f"Lv {member.level}, exp {member.experience}, HP {member.hp}/{member.max_hp}{note}"
        )
    if not shown:
        lines.append("  no slot holds a species right now.")
    return lines


def get_live_party_species_snapshot(block_base: int) -> "set[int]":
    """National Dex numbers in the live party, from the save-resident `Pokemon` records.

    Two things this has over `get_owned_species_snapshot(block_base, PARTY_BASE)`: it needs no menu to have been
    opened, because these records are save data and valid from the moment the block resolves, where PARTY_BASE is a
    menu row that reads all-zero until the party screen has drawn it; and it resolves species from the numeric field
    rather than the name, so a nicknamed Pokemon counts."""
    owned: "set[int]" = set()
    for member in read_party(block_base):
        dex_number = member.national_dex
        if dex_number is not None:
            owned.add(dex_number)
    return owned


def party_is_wiped(block_base: int) -> "bool | None":
    """True when every occupied slot is at 0 HP. None when the party cannot be read or is empty.

    None rather than False, because "no readable party" is what a load, a box operation and the first ticks after a
    reboot all look like -- and a Death Link sender that read that as "your party is dead" would fire a death at
    everyone every time the player opened the PC."""
    members = read_party(block_base)
    if not members:
        return None
    return all(member.hp == 0 for member in members)


def wipe_party(block_base: int) -> int:
    """Set every occupied party slot to 0 HP. Returns how many slots were written.

    HP only. `Pokemon::setHp` (0x8014B598) writes the u16 at +0x04 and clamps it to max HP and nothing else, so
    writing the field directly is the same thing the game does. Status is deliberately left alone: a faint clears it
    in `cbPoison` and the battle system does its own housekeeping, and writing a condition value this project cannot
    yet name is how you find out it meant something else."""
    written = 0
    for member in read_party(block_base):
        if member.hp == 0:
            continue
        try:
            write_bytes(member.address + POKEMON_HP_OFFSET, b"\x00\x00")
        except Exception:
            continue
        written += 1
    return written


@dataclass
class DeathLinkBridge:
    """Sends a death when the player's party is wiped, and wipes the party when a death arrives.

    The loop is the whole design problem: an incoming death wipes the party, the wipe is a white-out, and a white-out
    is what this sends on, so without a fence every received death would be re-broadcast forever. `_ours` is that
    fence -- a wipe this client caused is remembered until the party is conscious again (the white-out's own
    `fightEncountAnnihilationRecovery` healing them), and a wipe while it is set sends nothing.

    Edge-triggered, not level-triggered: a party sits at zero HP for as long as the losing battle's end sequence
    takes, which is seconds of polls, and `_was_wiped` makes that one death rather than twenty."""

    enabled: bool = False

    _was_wiped: bool = False
    _was_annihilated: bool = False
    _ours: bool = False
    receipts: int = 0            # deaths taken from the pool
    sends: int = 0               # deaths sent to it
    suppressed: int = 0          # wipes not sent, because they were ours
    #: ADDENDUM 390: which signal fired each send, so `!deathlink` can say whether the HP edge is working.
    sends_by_hp: int = 0
    sends_by_flag: int = 0
    flag_readable: bool = False
    last_cause: str = ""

    def receive(self, block_base: "int | None", cause: str = "") -> "str | None":
        """A death arrived. Wipe the party and remember that the resulting white-out is ours."""
        if not self.enabled or block_base is None:
            return None
        try:
            written = wipe_party(block_base)
        except Exception:
            return None
        self.receipts += 1
        self.last_cause = cause
        # `_ours` is set and `_was_wiped` deliberately is NOT: letting `poll` do the edge detection is what makes
        # the fence below the thing that actually fires. Latching `_was_wiped` here suppressed the send by never
        # reaching the fence, which was correct behaviour but left `_ours` dead code and `suppressed` always zero,
        # so the one counter that says the loop guard works could never say it.
        if not written:
            # ADDENDUM 390: `_ours` used to be set BEFORE this check, so a death arriving while the party was
            # already down -- or unreadable -- latched the loop fence with no wipe to justify it, and the fence
            # only comes down when the party next reads conscious. Any genuine white-out in between was
            # suppressed. Nothing was wiped, so there is nothing of ours to fence.
            return None
        self._ours = True
        return (f"your party fainted{f' -- {cause}' if cause else ''}. "
                f"{written} Pokemon set to 0 HP; the white-out lands when the game next resolves a battle.")

    def poll(self, block_base: "int | None") -> "tuple[bool, str | None]":
        """One tick. Returns `(should_send_death, note)`.

        TWO INDEPENDENT SIGNALS (ADDENDUM 390), because the original one was never measured.

        The HP edge is the party going fully unconscious, which is what ADDENDUM 351 shipped on the reasoning
        that "a party sits at zero HP for the whole of a losing battle's end sequence". That was never
        captured, and a white-out heals the party in the same sequence that ends the battle, so the window may
        not exist to be seen -- which is what "we weren't SENDING deathlinks at all" looks like from outside.

        The annihilation flag is the game's own: `fightEncountCheckZenmetu` refuses to run a second time while
        `encounter->zenmetuFlag` is set, so it is a latch and cannot be missed between polls.

        Either one fires a death, and both are edge-triggered and both go through the same loop fence. Keeping
        the HP edge costs one party read it was doing anyway, and if the flag turns out to be wrong on some
        build the feature degrades to what it was rather than to nothing."""
        if not self.enabled or block_base is None:
            return (False, None)
        try:
            wiped = party_is_wiped(block_base)
        except Exception:
            wiped = None
        annihilated = read_annihilation_flag()
        self.flag_readable = annihilated is not None

        # The fence comes down when BOTH signals say the white-out is over -- the party healed and the flag
        # cleared. Releasing on either alone would re-arm while the other was still describing the same death.
        if wiped is False and annihilated is not True:
            self._was_wiped = False
            self._was_annihilated = False
            self._ours = False
            return (False, None)
        if annihilated is not True:
            self._was_annihilated = False

        fresh_hp = wiped is True and not self._was_wiped
        fresh_flag = annihilated is True and not self._was_annihilated
        if wiped is True:
            self._was_wiped = True
        if annihilated is True:
            self._was_annihilated = True
        if not (fresh_hp or fresh_flag):
            return (False, None)        # already accounted for this one
        if self._ours:
            self.suppressed += 1
            return (False, None)
        self.sends += 1
        if fresh_flag:
            self.sends_by_flag += 1
        else:
            self.sends_by_hp += 1
        how = "the game's annihilation flag" if fresh_flag else "your party at 0 HP"
        return (True, f"you whited out ({how}) -- sending a death to everyone linked.")

    def describe(self) -> str:
        """ADDENDUM 390: reachable now. This existed and nothing called it, so `sends` sat at zero with no way
        for a player to see that -- which is why this arrived as "we weren't sending at all" rather than a
        number. The per-signal split is here so the next report says WHICH trigger is doing the work."""
        if not self.enabled:
            return "Death Link: off for this seed."
        return (f"Death Link: on. Sent {self.sends} ({self.sends_by_flag} from the game's annihilation flag, "
                f"{self.sends_by_hp} from the party at 0 HP), received {self.receipts}, "
                f"{self.suppressed} wipe(s) not re-sent because they were ours. "
                f"Party currently {'wiped' if self._was_wiped else 'conscious'}; "
                f"annihilation flag {'readable' if self.flag_readable else 'NOT readable on this build'}"
                + (", currently set" if self._was_annihilated else "") + ".")


# --- The undertaker (Miror B.) engine, and forcing an appearance. ---
# From decompiling `underTakerCallBackFunc` (0x80295C0C) and watching the cycle run live:
#
#   * STEP-DRIVEN. `esabaHeroCallBackInit` registers the callback through `heroMoveAddStepCallback`, the same
#     mechanism `cbPoison` uses, and the step delta is its third argument.
#   * flag 1449 accumulates that delta. On reaching `cfg+0x00` (100) the game rolls `HSD_Rand() % cfg+0x06` (32):
#     under `cfg+0x02` (16) the signal rises, under `+0x02 + cfg+0x04` (24) it falls. The threshold is SUBTRACTED,
#     so the remainder carries.
#   * a hit taking the signal to `cfg+0x08 - 1` (9) attempts the spawn, and `_appearMirabo__Fv` makes a WEIGHTED pick
#     over the seven records at cfg+0x34 -- the u16 at each +0 is a weight (3/3/1/1/1/1/0), so a colosseum is 60% and
#     Gateon Port can never be chosen.
#
# So forcing it changes the RULE, not the counter: threshold 1 so every step rolls, hit weight equal to the modulus so
# every roll hits, and every weight but the target zeroed. All three are u16s in a config struct loaded from disc --
# RAM, not save data -- and all are put back the moment he appears.
#
# THE ACCUMULATOR IS NEVER WRITTEN. 1449 is bits 9-24 of word 49, 1450 (signal) is bits 25-28 of THAT SAME WORD, and
# 1451 straddles into word 50, so writing the accumulator is a read-modify-write of the whole word and reverts any
# signal change the game made in between -- the exact value the force is waiting on. An earlier attempt did that at
# 10Hz and froze the game.
def read_u32(address: int) -> int:
    """`struct.unpack(">I", read_bytes(a, 4))[0]` appears dozens of times in this file; the undertaker code below
    walks pointer chains and would have added a dozen more."""
    return struct.unpack(">I", read_bytes(address, 4))[0]


def read_u16(address: int) -> int:
    return struct.unpack(">H", read_bytes(address, 2))[0]


MIROR_SDA_BASE = 0x804EFE20
MIROR_DATA_PTR = MIROR_SDA_BASE - 30244        # 0x804E87FC `undertakerdata`
GS_DESCRIPTOR_PTR = MIROR_SDA_BASE - 29708     # -> the 6-byte-per-flag descriptor table
GS_GROUP_TABLE_PTR = MIROR_SDA_BASE - 29940    # -> 8-byte entries {size, storage}


# ADDENDUM 390 -- the game's own annihilation flag, read straight out of the white-out code.
#
# Player: "Wouldn't this fail if we have no money? Can we base it off of the actual whiteout code that runs
# that we found before?" Correct on both counts. `heroDecPokedoru` clamps, so a broke player produces no money
# fingerprint at all, and the real function has a better signal in it.
#
# `fightEncountCheckZenmetu` (0x801F0D9C) guards itself on three things, and the second is the one we want:
#
#     encounter = fightGetEncountData(...)            # 0x801F19CC
#     if encounter->zenmetuFlag: return               # 0x801F16B8, and this is a LATCH
#
# Both accessors are short enough to read whole:
#
#     0x801F19CC  lwz r4, -29856(r13)    # -> a u32 count
#                 lwz r0, 0(r4)
#                 cmplw r3, r0           # bounds check
#                 mulli r0, r3, 60       # 60-byte records
#                 lwz r3, -29852(r13)    # -> the records base
#                 add r3, r3, r0
#     0x801F16B8  lbz r3, 4(r3)          # zenmetuFlag, u8 at +0x04
#
# With this file's own measured SDA base (MIROR_SDA_BASE, 0x804EFE20) those two displacements resolve to the
# pointers below. THE FLAG PERSISTS -- `fightEncountCheckZenmetu` returning early on it is what proves that --
# so this is a durable "you were annihilated" answer rather than the transient all-zero-HP window Death Link
# used to depend on, which was reasoned about in ADDENDUM 351 and never measured.
#
# READ ONLY. Nothing here writes; a wrong address costs a None, not a corrupted battle.
ENCOUNTER_COUNT_PTR = MIROR_SDA_BASE - 29856        # 0x804E8980 -> a u32 holding the record count
ENCOUNTER_RECORDS_PTR = MIROR_SDA_BASE - 29852      # 0x804E8984 -> the first 60-byte record
ENCOUNTER_RECORD_STRIDE = 60
ENCOUNTER_ZENMETU_FLAG_OFFSET = 0x04
#: A count outside this is a pointer that has not been initialised, and the read is refused.
ENCOUNTER_PLAUSIBLE_COUNT = 64


def read_annihilation_flag() -> "bool | None":
    """True when the game is holding an annihilation (white-out) on any encounter record.

    None -- never False -- when the tables cannot be trusted: before they initialise, both pointers are zero,
    and "I cannot see the battle state" must not mean "you are fine" any more than it may mean "you died".
    Every caller treats None as "no answer this poll"."""
    try:
        count = read_u32(read_u32(ENCOUNTER_COUNT_PTR))
        records = read_u32(ENCOUNTER_RECORDS_PTR)
    except Exception:
        return None
    if not records or records < MEM1_START:
        return None
    if not 0 < count <= ENCOUNTER_PLAUSIBLE_COUNT:
        return None
    try:
        for index in range(count):
            address = (records + index * ENCOUNTER_RECORD_STRIDE
                       + ENCOUNTER_ZENMETU_FLAG_OFFSET)
            if read_bytes(address, 1)[0]:
                return True
    except Exception:
        return None
    return False

# Config-struct offsets, all confirmed live.
MIROR_THRESHOLD_OFF, MIROR_HIT_OFF, MIROR_MODULUS_OFF = 0x00, 0x02, 0x06
MIROR_SIGNAL_MAX_OFF = 0x08
MIROR_FLAG_OFFS = {"start": 0x0C, "accumulator": 0x10, "signal": 0x14,
                   "place": 0x18, "timer": 0x1C, "suppress": 0x20}
MIROR_PLACE_TABLE_OFF, MIROR_PLACE_STRIDE, MIROR_PLACE_COUNT = 0x34, 8, 7

# The names `!mirorforce` accepts. Gateon Port is deliberately absent: its weight is 0, so the game itself can never
# pick it, and offering it would be offering something that cannot work.
MIROR_PLACE_IDS: "dict[str, tuple[int, str]]" = {
    "pyrite": (119, "Pyrite Colosseum"),
    "realgam": (58, "Realgam Colosseum"),
    "rock": (90, "Rock Poke Spot"),
    "oasis": (91, "Oasis Poke Spot"),
    "cave": (92, "Cave Poke Spot"),
}
MIROR_FORCE_TIMEOUT = 45.0      # seconds of not appearing before we give up and put everything back


def _gs_descriptor(flag_id: int) -> "tuple[int, int, int] | None":
    """(width, bitpos, storage) for a GS flag, or None if anything about the chain looks wrong.

    THE SELECTOR IS A BYTE OFFSET, NOT AN INDEX. `(byte0 >> 3) & 0x18` yields 0, 8, 16 or 24 and the group table's
    entries are 8 bytes each, so those ARE the offsets of entries 0..3. Multiplying by 8 again finds an empty entry
    and a NULL storage pointer, which then reads flags out of low memory and returns plausible-looking nonsense."""
    try:
        table = read_u32(GS_DESCRIPTOR_PTR)
        raw = read_bytes(table + flag_id * 6, 6)
        width = raw[0] & 0x3F
        bitpos = struct.unpack(">H", raw[2:4])[0]
        entry = read_u32(GS_GROUP_TABLE_PTR) + ((raw[0] >> 3) & 0x18)
        size, storage = read_u32(entry), read_u32(entry + 4)
        if not width or not (0x80000000 <= storage < 0x81800000):
            return None
        # The guard that would have caught the above immediately: a flag has to fit in its group.
        if bitpos + width > size * 8:
            return None
        return width, bitpos, storage
    except Exception:
        return None


def gs_flag_get(flag_id: int) -> "int | None":
    """Read a bit-packed GS flag. None on any failure -- never raises into the poll loop."""
    desc = _gs_descriptor(flag_id)
    if desc is None:
        return None
    width, bitpos, storage = desc
    try:
        word, off = bitpos >> 5, bitpos & 0x1F
        both = (read_u32(storage + word * 4 + 4) << 32) | read_u32(storage + word * 4)
        return (both >> off) & ((1 << width) - 1)
    except Exception:
        return None


def gs_flag_set(flag_id: int, value: int) -> bool:
    """Write a bit-packed GS flag, touching ONLY the words the field occupies.

    A field is a bit-range inside a word, so writing the following word back "unchanged" writes a stale copy of every
    other flag in it -- which is how an earlier force froze the game."""
    desc = _gs_descriptor(flag_id)
    if desc is None:
        return False
    width, bitpos, storage = desc
    mask = (1 << width) - 1
    if not 0 <= value <= mask:
        return False
    try:
        word, off = bitpos >> 5, bitpos & 0x1F
        low = (read_u32(storage + word * 4) & ~((mask << off) & 0xFFFFFFFF)) | ((value << off) & 0xFFFFFFFF)
        write_bytes(storage + word * 4, struct.pack(">I", low))
        if off + width > 32:
            spill = width - (32 - off)
            high = (read_u32(storage + word * 4 + 4) & ~((1 << spill) - 1)) | (value >> (32 - off))
            write_bytes(storage + word * 4 + 4, struct.pack(">I", high))
        return gs_flag_get(flag_id) == value
    except Exception:
        return False


def miror_config_base() -> "int | None":
    try:
        cfg = read_u32(MIROR_DATA_PTR)
        return cfg if 0x80000000 <= cfg < 0x81800000 else None
    except Exception:
        return None


def miror_state() -> "dict | None":
    """Everything `!mirorforce` and `!miror` need, or None when the engine is not resolvable."""
    cfg = miror_config_base()
    if cfg is None:
        return None
    try:
        ids = {name: read_u32(cfg + off) for name, off in MIROR_FLAG_OFFS.items()}
        consts = {off: read_u16(cfg + off) for off in
                  (MIROR_THRESHOLD_OFF, MIROR_HIT_OFF, MIROR_MODULUS_OFF, MIROR_SIGNAL_MAX_OFF)}
        values = {name: gs_flag_get(fid) for name, fid in ids.items()}
        if any(v is None for v in values.values()):
            return None
        places = []
        for i in range(MIROR_PLACE_COUNT):
            rec = cfg + MIROR_PLACE_TABLE_OFF + i * MIROR_PLACE_STRIDE
            places.append((rec, read_u16(rec), read_u16(rec + 2)))
        return {"cfg": cfg, "ids": ids, "consts": consts, "values": values, "places": places}
    except Exception:
        return None


@dataclass
class MirorForce:
    """Arms a forced Miror B. appearance, then waits for the game to make it happen.

    It never fabricates the appearance. `_appearMirabo__Fv` is what sets the place, plays message 16004 and opens the
    event where the player is standing; writing flag 1452 by hand only stages the NPC on the next map load, which is
    not what the radar going off looks like.

    Every write is reversible and none is in a loop: two (or six, with a target) u16s in the config struct, plus one
    narrow flag write to put the signal a notch below the spawn level."""

    active: bool = False
    cfg: int = 0
    target: str = ""
    target_id: int = 0
    saved: "dict[int, int]" = field(default_factory=dict)
    armed_at: float = 0.0
    last_error: "str | None" = None

    # Gate 3 is `darkpokemonCheckUnderTaker`, and it is NOT "un-snagged Shadows remain": it counts Shadows whose
    # 3-bit status field is exactly 2, which `_darkPokemonSetUnderTaker` sets when one ESCAPES a battle. 1 is fought,
    # 2 is queued for the undertaker, 3 is snagged, 4 is purified, and `isSnach` is status >= 3. So Miror B. is a
    # recovery path with a SUPPLY, not a timer: he shows up while something is queued and stops when you snag it. The
    # one step-based value, `setEscapeTime(getFootStep())`, is read only to ORDER his team. There is no cooldown.
    def arm(self, place_key: str) -> "tuple[bool, str]":
        state = miror_state()
        if state is None:
            return False, ("The undertaker engine is not readable right now -- no save loaded, or the game "
                           "is not past the title screen.")
        ids, values, consts = state["ids"], state["values"], state["consts"]
        if values["place"]:
            return False, f"He is already out at place id {values['place']}. Nothing to force."
        if not values["start"]:
            return False, (f"Flag {ids['start']} (the first-Miror-B.-fight flag) is clear, so the step "
                           f"callback returns on its first instruction. Beat him once and this will work.")
        self.restore()          # never stack two arms
        place_id, place_name = MIROR_PLACE_IDS[place_key]
        self.target, self.target_id = place_name, place_id
        self.cfg = state["cfg"]
        try:
            if values["suppress"] and not gs_flag_set(ids["suppress"], 0):
                return False, "Could not clear the suppress flag."
            cfg = state["cfg"]
            # Every step rolls, and every roll is a hit. Both are RAM, both are restored.
            self._stash(cfg + MIROR_THRESHOLD_OFF, 1)
            self._stash(cfg + MIROR_HIT_OFF, consts[MIROR_MODULUS_OFF])
            # The pick is weighted; zero every weight but the target's and it can only land there.
            for rec, weight, pid in state["places"]:
                if pid != place_id and weight:
                    self._stash(rec, 0)
            # ...and put the signal one notch below the spawn level, so that guaranteed hit lands on it.
            if not gs_flag_set(ids["signal"], consts[MIROR_SIGNAL_MAX_OFF] - 2):
                self.restore()
                return False, "Could not set the signal flag."
        except Exception as exc:                       # pragma: no cover - live-Dolphin failure path
            self.restore()
            self.last_error = str(exc)
            return False, f"Failed to arm: {exc}"
        self.active, self.armed_at = True, time.time()
        return True, (f"Armed for {place_name}. TAKE ONE STEP -- the next roll is a guaranteed hit. "
                      f"Everything is put back the moment he appears.")

    def _stash(self, address: int, value: int) -> None:
        if address not in self.saved:
            self.saved[address] = read_u16(address)
        write_bytes(address, struct.pack(">H", value & 0xFFFF))

    def poll(self) -> "str | None":
        """One tick. Returns a line to log when the force resolves, otherwise None. Never raises."""
        if not self.active:
            return None
        try:
            state = miror_state()
            if state is None:
                return None                            # unreadable this tick; ask again next one
            place = state["values"]["place"]
            if place:
                self.restore()
                where = self.target if place == self.target_id else f"place id {place}"
                return (f"Miror B. has appeared at {where}. The engine is back to normal; he stays "
                        f"1000 step units, and the timer freezes once you reach him.")
            if time.time() - self.armed_at > MIROR_FORCE_TIMEOUT:
                # WHICH gate refused is readable, so say it rather than listing possibilities. With the roll
                # guaranteed, the signal is the witness: at the spawn level it means the spawn ITSELF was refused
                # and bounced back; below it means the callback never rolled at all.
                values, consts = state["values"], state["consts"]
                spawn_at = consts[MIROR_SIGNAL_MAX_OFF] - 1
                self.restore()
                if values["suppress"]:
                    return ("!mirorforce gave up: the suppress flag is set, which is gate 2 -- the game "
                            "sets it while you are AT an encounter, and it stops the callback dead. "
                            "Everything has been put back.")
                if not values["start"]:
                    return ("!mirorforce gave up: the first-fight flag went clear, so the callback returns "
                            "on its first instruction. Everything has been put back.")
                if values["signal"] >= spawn_at:
                    return (f"!mirorforce gave up: the signal reached {values['signal']} of {spawn_at} and "
                            f"the SPAWN was refused, not the roll. Either the story window, or nothing was "
                            f"eligible -- a Poke Spot only counts while nothing is there, and a colosseum "
                            f"needs its map flag AND you must not be standing in it. Everything has been "
                            f"put back.")
                if values["signal"] <= consts[MIROR_SIGNAL_MAX_OFF] - 2:
                    return (f"!mirorforce gave up: the signal never moved off {values['signal']}, so the "
                            f"callback never rolled. Gates 1 and 2 are open, so it is the third: NO SHADOW "
                            f"IS QUEUED FOR HIM. A Shadow joins his queue only by ESCAPING a battle "
                            f"(status 2); snagging it removes it (status 3). There is no cooldown to wait "
                            f"out -- let one get away and he comes back. (If you were standing still, walk "
                            f"and try again: the engine is step-driven.) Everything has been put back.")
                return "!mirorforce gave up. Everything has been put back."
        except Exception:                              # pragma: no cover - live-Dolphin failure path
            self.restore()
            return "!mirorforce aborted on a read failure. Everything has been put back."
        return None

    def restore(self) -> None:
        """Put the config struct back. Safe to call twice, and safe to call when nothing is armed."""
        threshold = None
        for address, value in list(self.saved.items()):
            try:
                write_bytes(address, struct.pack(">H", value & 0xFFFF))
                if self.cfg and address == self.cfg + MIROR_THRESHOLD_OFF:
                    threshold = value
            except Exception:
                pass                                   # a failed restore is RAM-only and dies with the boot
        self.saved.clear()
        self.active = False
        # THE THRESHOLD IS RE-READ BETWEEN THE COMPARE AND THE SUBTRACT -- 0x80295C90 tests it, 0x80295DA4 loads it
        # again to subtract. Restoring it to 100 while a callback sits between those two makes the game subtract 100
        # from an accumulator that only had to beat 1, and the field is UNSIGNED 16-BIT, so it underflows to ~65449
        # and then rolls on every step for the next 650. Measured live: accumulator 65449 after a force. One narrow
        # write closes it, at a cost of at most one roll's worth of walking.
        if threshold is None:
            return
        try:
            ids = {name: read_u32(self.cfg + off) for name, off in MIROR_FLAG_OFFS.items()}
            accumulator = gs_flag_get(ids["accumulator"])
            if accumulator is not None and accumulator >= threshold:
                gs_flag_set(ids["accumulator"], 0)
        except Exception:
            pass

    def describe(self) -> str:
        if not self.active:
            return "!mirorforce: not armed."
        return (f"!mirorforce: armed for {self.target}, {time.time() - self.armed_at:.0f}s ago, "
                f"{len(self.saved)} config value(s) held.")
