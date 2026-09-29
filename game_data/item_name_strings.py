"""Live, in-RAM renaming of the dummy berries.

`common_rel.rel` is resident in RAM contiguously at a fixed base, so any common_rel byte is at
`COMMON_REL_RAM_BASE + its offset in the decompressed REL`. Measured two ways that agree, against the real
vanilla files plus `bridge/dumps/dump_full_bagopen.bin`: 48-byte chunks from rel+0x4E474, rel+0x50274 and
rel+0x56274 each occur once in MEM1 with an implied base of 0x80B18DC0, and a UTF-16BE search for
"RAZZ BERRY" lands at 0x80B6B60C = 0x80B18DC0 + 0x5284C, string id 5115's entry start.

Item names live in pointer 116's CommonRelStringTable (5001 MASTER BALL, 5013 POTION, 5115-5141 the berries,
5261 JOY SCENT), stored uppercase. Descriptions do not: a name id is +0x10 into the Items entry, a
description id is +0x14 and resolves through `pocket_menu.fsys`'s `pocket_menu.msg`.

The table is packed -- UTF-16BE text, 2-byte terminator, next entry immediately after -- so a rename is
written in place and space-padded to the original's exact character count, as
`xd_rel_format.apply_item_name_rename` does at patch time. The shortest shop berry is RAZZ/BLUK at 10
characters, the ceiling for anything that must fit every shop berry.
"""
from __future__ import annotations

# Not trusted blindly: `ram_client.ItemNameRenamer.verify()` reads the bytes at each address and refuses to
# write unless they have the exact shape of a string-table entry.
COMMON_REL_RAM_BASE = 0x80B18DC0

# {game_item_id: (offset in the decompressed common_rel.rel, the vanilla name there)}, read from the real
# `common.fsys` -> `common_rel`. Each terminator sits immediately after the name, so a name's character count
# is its whole budget.
ITEM_NAME_ENTRIES: "dict[int, tuple[int, str]]" = {
    # --- shop berries (items.USELESS_BERRY_IDS) ---
    148: (0x05284C, "RAZZ BERRY"),
    149: (0x052862, "BLUK BERRY"),
    150: (0x052878, "NANAB BERRY"),
    151: (0x052890, "WEPEAR BERRY"),
    152: (0x0528AA, "PINAP BERRY"),
    153: (0x0528C2, "POMEG BERRY"),
    154: (0x0528DA, "KELPSY BERRY"),
    155: (0x0528F4, "QUALOT BERRY"),
    156: (0x05290E, "HONDEW BERRY"),
    157: (0x052928, "GREPA BERRY"),
    158: (0x052940, "TAMATO BERRY"),
    159: (0x05295A, "CORNN BERRY"),
    160: (0x052972, "MAGOST BERRY"),
    162: (0x0529A6, "NOMEL BERRY"),
    163: (0x0529BE, "SPELON BERRY"),
    164: (0x0529D8, "PAMTRE BERRY"),
    165: (0x0529F2, "WATMEL BERRY"),
    166: (0x052A0C, "DURIN BERRY"),
    167: (0x052A24, "BELUE BERRY"),
    168: (0x052A3C, "LIECHI BERRY"),
    # --- chest berries (items.CHEST_BERRY_IDS) -- not renamed yet, measured here anyway ---
    161: (0x05298C, "RABUTA BERRY"),
    169: (0x052A56, "GANLON BERRY"),
    170: (0x052A70, "SALAC BERRY"),
    171: (0x052A88, "PETAYA BERRY"),
    172: (0x052AA2, "APICOT BERRY"),
    173: (0x052ABC, "LANSAT BERRY"),
    174: (0x052AD6, "STARF BERRY"),
}

STRING_TERMINATOR = b"\x00\x00"


def ram_address(game_item_id: int) -> "int | None":
    """Where this item's name string lives in MEM1, or None for an item this module has no offset for."""
    entry = ITEM_NAME_ENTRIES.get(game_item_id)
    return None if entry is None else COMMON_REL_RAM_BASE + entry[0]


def budget_chars(game_item_id: int) -> "int | None":
    """How many characters a replacement name may use for this item. The vanilla name's own length."""
    entry = ITEM_NAME_ENTRIES.get(game_item_id)
    return None if entry is None else len(entry[1])


# The smallest budget across the SHOP berries -- the ceiling for any text that must work on all of them.
SHOP_BERRY_NAME_BUDGET = 10


def encode_name(text: str, budget: int) -> "bytes | None":
    """The exact bytes to write over this entry, or None if `text` does not fit. Space-padded to `budget`
    characters and re-terminated, so the entry keeps its byte length and the packed entries after it are not
    disturbed."""
    if len(text) > budget:
        return None
    return (text + " " * (budget - len(text))).encode("utf-16-be") + STRING_TERMINATOR


def numbered_name(index: int) -> str:
    """"AP ITEM 01" .. "AP ITEM 20". Exactly 10 characters at every index in that range -- the shortest shop
    berry's whole budget -- so one format fits all twenty."""
    return f"AP ITEM {index:02d}"


def is_plausible_entry_bytes(raw: bytes, budget: int) -> bool:
    """True when `raw` has the shape of this table's entries: `budget` UTF-16BE units of printable ASCII, then
    the 2-byte terminator. Content-agnostic on purpose -- checking for the vanilla text would fail on every
    reconnect after a rename, and the point is only to confirm the table is where this module thinks."""
    if len(raw) != budget * 2 + 2:
        return False
    if raw[-2:] != STRING_TERMINATOR:
        return False
    for i in range(0, budget * 2, 2):
        if raw[i] != 0x00 or not (0x20 <= raw[i + 1] <= 0x7E):
            return False
    return True


# Price lives in `common_rel`'s global Items table: per-item-id struct, 0x28 stride, price a u16BE at +0x06.
# The table's offset is resolved at runtime from the REL's pointer table (index 70) rather than stored here --
# a resolved value is right on any build. Measured once over the bridge to prove the resolution works:
# 0x80B38CA4, i.e. COMMON_REL_RAM_BASE + 0x01FEE4. The same read confirmed +0x06 is price in Pokedollars
# (Master Ball 0, Poke Ball 200, Great Ball 600, Ultra Ball 1200, Potion 300, Super Potion 700, TM01 3000,
# Poke Snack 300, Joy Scent 600), that every shop berry costs 20, and that item 175 (Enigma Berry) has
# NameID 0.
ITEMS_TABLE_POINTER_INDEX = 70
ITEM_ENTRY_SIZE = 0x28
ITEM_PRICE_OFFSET = 0x06      # u16BE
ITEM_NAME_ID_OFFSET = 0x10    # u32BE, masked to 20 bits
ITEM_NAME_ID_MASK = 0xFFFFF

# REL header fields, relative to COMMON_REL_RAM_BASE. In the LOADED REL these hold absolute RAM addresses
# (OSLink rewrites them at link time), not the on-disk file-relative offsets, so `xd_rel_format.RelFile`
# cannot be reused against a RAM copy; pointer-table entries stay relative to the data-section address. Live:
# data section 0x80B1AA70 + 0xA6408 ends at 0x80BC0E78, where the import table (+0x28) begins.
REL_DATA_SECTION_ADDRESS_OFFSET = 0x6C   # common_rel uses 0x6C; other RELs use 0x64
REL_POINTER_TABLE_ADDRESS_OFFSET = 0x24
REL_FIRST_POINTER_OFFSET = 0x08
REL_POINTER_STRIDE = 0x10
REL_POINTER_VALUE_OFFSET = 0x04

# NameIDs in the Items table were read live for all 27 berry ids and are consecutive without exception, so
# the relationship is stored instead of 27 typed numbers that gate a write into common_rel.
FIRST_SHOP_BERRY_ID = 148
FIRST_SHOP_BERRY_NAME_ID = 5115


def expected_name_id(game_item_id: int) -> "int | None":
    """The NameID the Items table must hold for a shop berry, or None for an id this cannot vouch for. This
    is the safety gate for price writing: 26 consecutive unrelated structs will not all carry the predicted
    NameID, so any disagreement means write nothing."""
    if not FIRST_SHOP_BERRY_ID <= game_item_id <= 174:
        return None
    return FIRST_SHOP_BERRY_NAME_ID + (game_item_id - FIRST_SHOP_BERRY_ID)


# What each class of AP item costs. Filler does not keep the vanilla 20 -- every patchable slot in every shop
# is a dummy berry, so there is nothing vanilla-priced to blend in with. A trap follows `_FILLER_PRICE` rather
# than repeating the number, because a conspicuously-priced trap is a tell.
_FILLER_PRICE = 100
PRICE_BY_CLASSIFICATION: "dict[str, int]" = {
    "progression": 1500,
    "useful": 500,
    "trap": _FILLER_PRICE,
    "filler": _FILLER_PRICE,
}
# What the game charges for these berries, measured live: every shop berry reads 20. Kept as the restore
# value for a berry that is not currently any shop's line -- see `ItemPriceWriter.desired_prices`.
VANILLA_SHOP_BERRY_PRICE = 20
MAX_ITEM_PRICE = 0xFFFF   # the field is a u16
