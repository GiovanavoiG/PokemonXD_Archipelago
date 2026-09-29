r"""
Pokemon XD: Gale of Darkness -- GameCube REL pointer-table reader.

Written from scratch against the REL container format. Header offsets, pointer-table geometry and the XD
table indices below agree with `rotobash/pokemon-ngc-rando` (GPLv2) -- see NOTICE.md; the `.cs` filenames
named below are that project's. Everything here was then verified against a real `common_rel.rel`.

ALL OFFSETS BELOW ARE RELATIVE TO THE DECOMPRESSED REL'S OWN BYTES, never `common.fsys`'s or the ISO's.
"""

from __future__ import annotations

import struct

COMMON_REL_DATA_START_OFFSET_LOCATION = 0x6C  # used when the REL's own filename contains "common_rel"
REL_DATA_START_OFFSET_LOCATION = 0x64  # used for every other REL file
REL_POINTERS_START_OFFSET_LOCATION = 0x24
REL_POINTERS_HEADER_POINTER_1_OFFSET = 0x28
REL_POINTERS_FIRST_POINTER_OFFSET = 0x8
REL_SIZE_OF_POINTER = 0x10
REL_POINTER_DATA_POINTER_1_OFFSET = 0x4

# Sentinel range: a pointer-table "value" landing in here marks the end of the table, not a real pointer.
_SENTINEL_LOW = 0xCA01
_SENTINEL_HIGH = 0xCAFF


class RelFile:
    """Parses a decompressed REL's pointer table; exposes the GetPointer/GetValueAtPointer reads."""

    def __init__(self, rel_bytes: bytes, is_common: bool, label: str = "REL"):
        self.data = rel_bytes
        self.label = label  # only for the error messages below; never affects parsing
        start_off = COMMON_REL_DATA_START_OFFSET_LOCATION if is_common else REL_DATA_START_OFFSET_LOCATION
        self.data_start = self._u32(start_off)
        # ADDENDUM 128: 0x64/0x6C are section-info-table entries ({u32 offset, u32 size}, table at 0x4C), so
        # the u32 after the data-start offset is that section's SIZE -- the upper bound for every table in it.
        self.data_section_end = self.data_start + self._u32(start_off + 4)
        self.pointer_start = self._u32(REL_POINTERS_START_OFFSET_LOCATION)
        self.first_pointer = self.pointer_start + REL_POINTERS_FIRST_POINTER_OFFSET

        pointer_header = self._u32(REL_POINTERS_HEADER_POINTER_1_OFFSET)
        pointer_end = self._u32(pointer_header + 0xC)

        count = 0
        offset = self.first_pointer
        while offset < pointer_end:
            val = self._u32(offset)
            if _SENTINEL_LOW <= val <= _SENTINEL_HIGH:
                break
            count += 1
            offset += REL_SIZE_OF_POINTER
        self.number_of_pointers = count

    def _u32(self, offset: int) -> int:
        # ADDENDUM 115: a bare struct.error gave no hint which REL or offset caused it.
        if offset < 0 or offset + 4 > len(self.data):
            raise ValueError(
                f"{self.label}: pointer-table walk computed offset {offset}, which is out of bounds for this "
                f"REL's own decompressed size ({len(self.data)} bytes) -- this container's data very likely "
                "is NOT real REL pointer-table data (either the wrong FSYS entry was selected, or this file "
                "doesn't follow the expected REL.cs layout). This needs a live inspection of the container's "
                "real entries to identify the correct one, not another blind guess."
            )
        return struct.unpack_from(">I", self.data, offset)[0]

    def get_pointer_offset(self, index: int) -> int:
        """Offset of entry `index`'s own stored offset field -- what RETARGETING the pointer would write."""
        return self.first_pointer + index * REL_SIZE_OF_POINTER + REL_POINTER_DATA_POINTER_1_OFFSET

    def get_pointer(self, index: int) -> int:
        """Resolves entry `index` to an absolute offset in `self.data` (stored offset + data_start)."""
        offset = self.get_pointer_offset(index)
        return self._u32(offset) + self.data_start

    def get_value_at_pointer(self, index: int) -> int:
        """The u32BE stored AT the address entry `index` resolves to -- scalars, not array bases."""
        offset = self.get_pointer(index)
        return self._u32(offset)


# Chest ("treasure box") table, XD pointer-table indices from Constants.cs. Entry layout from
# OverworldItem.cs, 28 bytes: Model(u8,+0x0), Quantity(u8,+0x1), Angle(u8,+0x2), RoomID(u16BE,+0x4),
# Flag(u16BE,+0x6), ItemID(u16BE,+0xE), X/Y/Z(f32BE, +0x10/+0x14/+0x18).

XD_TREASURE_BOX_DATA_POINTER = 66
XD_NUMBER_TREASURE_BOXES_POINTER = 67
TREASURE_BOX_ENTRY_SIZE = 0x1C
TREASURE_BOX_ITEM_ID_OFFSET = 0x0E
TREASURE_BOX_ROOM_ID_OFFSET = 0x04
TREASURE_BOX_MODEL_OFFSET = 0x00
TREASURE_BOX_QUANTITY_OFFSET = 0x01


def chest_table_base(rel: RelFile) -> int:
    """Absolute offset (within `rel.data`) of treasure-box entry 0."""
    return rel.get_pointer(XD_TREASURE_BOX_DATA_POINTER)


def chest_raw_count(rel: RelFile) -> int:
    """Raw entry count per the REL's own table (116, confirmed against the real ISO 2026-09-07). Entry 0 is
    an all-zero sentinel; `real_chest_indices()` is the count without it.

    SENTINEL CONFIRMED 2026-09-14 (ADDENDUM 207) against the player's own `common_rel`: entry 0 is 28 zero
    bytes and entries 1..115 match `game_data/chest_table.py` byte-for-byte. 116 raw is 115 real chests."""
    return rel.get_value_at_pointer(XD_NUMBER_TREASURE_BOXES_POINTER)


def real_chest_indices(rel: RelFile) -> list[int]:
    """Every raw entry except index 0 -- see `chest_raw_count`."""
    return list(range(1, chest_raw_count(rel)))


def chest_item_id_offset(rel: RelFile, index: int) -> int:
    """Absolute offset (within `rel.data`) of chest entry `index`'s 2-byte (u16BE) ItemID field."""
    return chest_table_base(rel) + index * TREASURE_BOX_ENTRY_SIZE + TREASURE_BOX_ITEM_ID_OFFSET


def chest_quantity_offset(rel: RelFile, index: int) -> int:
    """Offset of chest `index`'s 1-byte Quantity field, patched with ItemID so one chest is one check."""
    return chest_table_base(rel) + index * TREASURE_BOX_ENTRY_SIZE + TREASURE_BOX_QUANTITY_OFFSET


def read_chest_entry(rel: RelFile, index: int) -> dict:
    """Full decode of one chest entry, for census use. Patching only needs `chest_item_id_offset`."""
    base = chest_table_base(rel) + index * TREASURE_BOX_ENTRY_SIZE
    data = rel.data
    model = data[base + TREASURE_BOX_MODEL_OFFSET]
    quantity = data[base + TREASURE_BOX_QUANTITY_OFFSET]
    room_id = struct.unpack_from(">H", data, base + TREASURE_BOX_ROOM_ID_OFFSET)[0]
    item_id = struct.unpack_from(">H", data, base + TREASURE_BOX_ITEM_ID_OFFSET)[0]
    x, y, z = struct.unpack_from(">fff", data, base + 0x10)
    return {
        "index": index, "model": model, "quantity": quantity, "room_id": room_id, "item_id": item_id,
        "x": x, "y": y, "z": z,
    }


# ADDENDUM 134: 24 of the 115 real chests vanilla-hold a 5xx-band item, and overwriting one deletes it from
# the seed -- most still have game_item_id=None and are `useful`, so they are neither pooled nor deliverable.
# At or above this floor a chest keeps its item and is not an AP location. Anchors: Krane Memo 1-5 = 523-527,
# Voice Case 1-5 = 528-532, Disc Case = 533, ID Card = 506 (chest 18, room 8). The floor sits below the lowest
# observed key item (501) on purpose.
KEY_ITEM_ID_FLOOR = 500


def apply_chest_dummy_item(rel_bytes: bytearray, rel: RelFile, dummy_item_id: int,
                           also_convert: "frozenset[int] | None" = None,
                           per_chest: "dict[int, tuple[int, int]] | None" = None) -> int:
    """Overwrites every real chest's ItemID and Quantity in `rel_bytes` (a bytearray copy of `rel.data`).

    `per_chest` gives a chest its own `(item_id, quantity)` (ADDENDUM 218), else `(dummy_item_id, 1)`.
    `also_convert` (ADDENDUM 177) names chests to convert despite sitting at or above KEY_ITEM_ID_FLOOR;
    it is passed in because the SAME list drives the location table, and both failure modes are silent --
    dummied without becoming a check deletes the key item, a check without dummying hands over both. Quantity
    is written at all because `ram_client.ChestCountTracker` reads a running Bag quantity."""
    count = 0
    also_convert = frozenset(also_convert or ())
    per_chest = per_chest or {}
    for index in real_chest_indices(rel):
        item_off = chest_item_id_offset(rel, index)
        vanilla_item_id = struct.unpack_from(">H", rel_bytes, item_off)[0]
        if vanilla_item_id >= KEY_ITEM_ID_FLOOR and index not in also_convert:
            continue  # ADDENDUM 134 -- see KEY_ITEM_ID_FLOOR, and `also_convert` for the ADDENDUM 177 exception
        # ADDENDUM 218: the per-chest berry, falling back to the shared dummy for pre-218 callers.
        item_id, quantity = per_chest.get(index, (dummy_item_id, 1))
        struct.pack_into(">H", rel_bytes, item_off, item_id)
        qty_off = chest_quantity_offset(rel, index)
        struct.pack_into(">B", rel_bytes, qty_off, quantity & 0xFF)
        count += 1
    return count


def chest_indices_holding_key_items(rel: RelFile) -> "list[tuple[int, int]]":
    """`(chest_index, vanilla_item_id)` for every real chest `apply_chest_dummy_item` refuses to overwrite."""
    out = []
    for index in real_chest_indices(rel):
        item_id = struct.unpack_from(">H", rel.data, chest_item_id_offset(rel, index))[0]
        if item_id >= KEY_ITEM_ID_FLOOR:
            out.append((index, item_id))
    return out


def randomizable_chest_count(rel: RelFile) -> int:
    """How many chests randomization converts; `locations.CHEST_LOCATION_COUNT` must equal this."""
    return len(real_chest_indices(rel)) - len(chest_indices_holding_key_items(rel))


# Shop/mart item table (ADDENDUM 110), in `pocket_menu.fsys`'s own REL with its OWN pointer numbering. The
# indices are Constants.cs's, not invented. Originally a disclosed hypothesis; since confirmed against a live
# RAM dump -- 166 of 166 pool slots agree, see shop_stock.py -- and ADDENDUM 128 corrected the entry offset
# below off that measurement. Layout: MartStartIndexes (index 0) is an array of 4-byte entries
# whose FirstItemIndex is a u16BE offset, in u16 units, into one shared pool (MartItems, index 4); a mart's
# list runs to a 0 sentinel. NumberOfMarts (1) and NumberOfMartItems (5) are scalars, read dynamically. The
# other 2 bytes of each entry are never touched -- meaning unconfirmed.

MART_START_INDEXES_POINTER = 0
NUMBER_OF_MARTS_POINTER = 1
MART_ITEMS_POINTER = 4
NUMBER_OF_MART_ITEMS_POINTER = 5
MART_START_INDEXES_ENTRY_SIZE = 4
# FIXED (ADDENDUM 128): FirstItemIndex is the SECOND u16 of each 4-byte entry, at +2; ADDENDUM 110 read +0
# (Pokemarts.cs indexes the same way). The wrong halfword sent sentinel
# walks through the REL's own relocation table -- the census's junk values 32846=0x804E,
# 50638/50639=0xC5CE/0xC5CF, 1035=0x040B, 1547=0x060B are DOL-address halves and {type, section} words --
# which got berry ids written over them and made OSLink flood "unknown relocation type".
MART_START_INDEXES_FIRST_ITEM_OFFSET = 0x2
MART_ITEM_ENTRY_SIZE = 2  # one u16BE item-id per shared-pool slot
MART_ITEM_SENTINEL = 0  # terminates one mart's slice of the shared item pool
MART_WALK_CAP = 4096  # defensive per-mart walk cap (slots); a real mart is < 30


def mart_start_indexes_base(rel: RelFile) -> int:
    """Absolute offset (within `rel.data`) of MartStartIndexes entry 0."""
    return rel.get_pointer(MART_START_INDEXES_POINTER)


def number_of_marts(rel: RelFile) -> int:
    """Real mart/shop count per this REL's own table. Not yet cross-checked against a real ISO census."""
    return rel.get_value_at_pointer(NUMBER_OF_MARTS_POINTER)


def mart_items_base(rel: RelFile) -> int:
    """Absolute offset (within `rel.data`) of the shared MartItems pool's entry 0."""
    return rel.get_pointer(MART_ITEMS_POINTER)


def number_of_mart_items(rel: RelFile) -> int:
    """Scalar total item-slot count. Deliberately NOT used to bound the per-mart walk: whether it counts each
    mart's terminating sentinel is unconfirmed, so it could stop a slot early or run a slot long."""
    return rel.get_value_at_pointer(NUMBER_OF_MART_ITEMS_POINTER)


def mart_first_item_index(rel: RelFile, mart_index: int) -> int:
    """MartStartIndexes entry `mart_index`'s FirstItemIndex -- a u16BE offset in u16 units, NOT bytes."""
    off = (
        mart_start_indexes_base(rel)
        + mart_index * MART_START_INDEXES_ENTRY_SIZE
        + MART_START_INDEXES_FIRST_ITEM_OFFSET
    )
    return struct.unpack_from(">H", rel.data, off)[0]


def mart_item_slot_offset(rel: RelFile, pool_index: int) -> int:
    """Absolute offset (within `rel.data`) of the shared MartItems pool's `pool_index`'th u16BE entry."""
    return mart_items_base(rel) + pool_index * MART_ITEM_ENTRY_SIZE


def mart_pool_end_offset(rel) -> int:
    """ADDENDUM 128: structural upper bound (absolute, exclusive) of the shared MartItems pool -- the nearest
    other pointer target after its base, its section's end, or the file's end. Inputs are all optional."""
    base = mart_items_base(rel)
    end = len(rel.data)
    section_end = getattr(rel, "data_section_end", None)
    if isinstance(section_end, int) and base < section_end < end:
        end = section_end
    pointer_count = getattr(rel, "number_of_pointers", None)
    if isinstance(pointer_count, int):
        for index in range(pointer_count):
            try:
                target = rel.get_pointer(index)
            except Exception:  # pragma: no cover -- a malformed pointer can't narrow the bound, that's all
                continue
            if base < target < end:
                end = target
    declared = getattr(rel, "declared_pool_end_offset", None)
    if isinstance(declared, int) and base < declared < end:
        end = declared
    return end


def mart_pool_end_index(rel) -> int:
    """ADDENDUM 128: `mart_pool_end_offset` expressed as an exclusive pool index (u16 slots from the base)."""
    return (mart_pool_end_offset(rel) - mart_items_base(rel)) // MART_ITEM_ENTRY_SIZE


def mart_slot_limit(rel, mart_index: int) -> int:
    """ADDENDUM 128: exclusive upper pool index for mart `mart_index` -- the smallest OTHER mart's
    FirstItemIndex after its start, capped by `mart_pool_end_index` and by `NumberOfMartItems +
    NumberOfMarts` (a scalar whose sentinel-inclusiveness is unconfirmed, read generously). A walk that hits
    this limit without a sentinel stops, so it can never wander into another table."""
    start = mart_first_item_index(rel, mart_index)
    limit = mart_pool_end_index(rel)
    mart_count = number_of_marts(rel)
    try:
        declared_limit = number_of_mart_items(rel) + mart_count
    except Exception:  # pragma: no cover -- defensive; a REL without that scalar just isn't capped by it
        declared_limit = None
    if declared_limit is not None and 0 < declared_limit < limit:
        limit = declared_limit
    for other in range(mart_count):
        other_start = mart_first_item_index(rel, other)
        if start < other_start < limit:
            limit = other_start
    return min(limit, start + MART_WALK_CAP)


def mart_item_slots(rel: RelFile, mart_index: int) -> list[int]:
    """Pool indices belonging to mart `mart_index`, walked from its FirstItemIndex to the 0 sentinel but never
    past `mart_slot_limit()` -- a missing sentinel used to march over the shop REL's relocation table."""
    start = mart_first_item_index(rel, mart_index)
    data = rel.data
    base = mart_items_base(rel)
    indices: list[int] = []
    pool_index = start
    limit = mart_slot_limit(rel, mart_index)
    while pool_index < limit:
        off = base + pool_index * MART_ITEM_ENTRY_SIZE
        if off + 2 > len(data):
            break
        item_id = struct.unpack_from(">H", data, off)[0]
        if item_id == MART_ITEM_SENTINEL:
            break
        indices.append(pool_index)
        pool_index += 1
    return indices


def read_all_mart_slots(rel: RelFile) -> list[dict]:
    """Full decode of every mart's slots for census use: {"mart_index", "pool_index", "item_id"} each."""
    out: list[dict] = []
    for mart_index in range(number_of_marts(rel)):
        for pool_index in mart_item_slots(rel, mart_index):
            item_id = struct.unpack_from(">H", rel.data, mart_item_slot_offset(rel, pool_index))[0]
            out.append({"mart_index": mart_index, "pool_index": pool_index, "item_id": item_id})
    return out


def apply_mart_randomization(
    rel_bytes: bytearray,
    rel: RelFile,
    dummy_item_ids: "list[int]",
    excluded_item_ids: "set[int] | frozenset[int]" = frozenset(),
    mart_groups: "list[tuple[str, tuple[int, ...]]] | None" = None,
) -> int:
    """Overwrites every real mart item slot in `rel_bytes` with one of `dummy_item_ids`, EXCEPT slots whose
    ORIGINAL id is in `excluded_item_ids` -- excluded by content, not position, because Agate's Scents and
    every Poke Snack must stay and there is no confirmed per-mart layout to target by position.

    SAFETY BOUNDS (ADDENDUM 127/128): a slot is written only if its original id is a real vanilla item id
    (`1 <= id < ITEM_REMAP_THRESHOLD_ID`) and lies inside its mart's structural slice of the pool; the caller
    confines the whole write set to `[mart_items_base, mart_pool_end_offset)` before anything reaches disc.

    `mart_groups` (ADDENDUM 238c) assigns berries PER SHOP LINE: (group key, marts in story order), tiers
    oldest first. The first sighting of an item id takes the next unused berry and later tiers reuse it, so
    a line keeps its berry all game and "check N" is the Nth line that shop ever offers. Berries need only be
    distinct within a shop, since a check is (room, berry); more lines than berries raises, as does a slot
    claimed by two DIFFERENT groups. Unnamed marts become their own group. Without `mart_groups` the LEGACY
    global rotation runs, whose defect is structural -- a shop's tiers are different pool slices, so a restock
    moved every line onto a fresh berry instead of only the changed ones."""
    count = 0
    n = len(dummy_item_ids)
    mart_count = number_of_marts(rel)

    def patchable(mart_index: "int") -> "list[tuple[int, int]]":
        """[(pool_index, original_item_id)] for the slots in this mart that may be overwritten."""
        out = []
        for pool_index in mart_item_slots(rel, mart_index):
            off = mart_item_slot_offset(rel, pool_index)
            original_item_id = struct.unpack_from(">H", rel.data, off)[0]
            if original_item_id in excluded_item_ids:
                continue
            if not 1 <= original_item_id < ITEM_REMAP_THRESHOLD_ID:
                continue
            out.append((pool_index, original_item_id))
        return out

    if mart_groups is None:
        rotation = 0
        for mart_index in range(mart_count):
            for pool_index, _original in patchable(mart_index):
                struct.pack_into(">H", rel_bytes, mart_item_slot_offset(rel, pool_index),
                                 dummy_item_ids[rotation % n])
                rotation += 1
                count += 1
        return count

    groups: "list[tuple[str, tuple[int, ...]]]" = list(mart_groups)
    named = {m for _key, marts in groups for m in marts}
    for mart_index in range(mart_count):
        if mart_index not in named:
            groups.append((f"mart {mart_index}", (mart_index,)))

    slot_owner: "dict[int, str]" = {}
    for key, marts in groups:
        assigned: "dict[int, int]" = {}
        for mart_index in marts:
            if not 0 <= mart_index < mart_count:
                # A group may name a mart this REL lacks (test fixtures, a trimmed REL): nothing to patch.
                continue
            for pool_index, original_item_id in patchable(mart_index):
                previous = slot_owner.setdefault(pool_index, key)
                if previous != key:
                    raise ValueError(
                        f"pool slot {pool_index} is claimed by both {previous!r} and {key!r} -- one shelf "
                        "line cannot belong to two shops' check numbering"
                    )
                berry = assigned.get(original_item_id)
                if berry is None:
                    berry = len(assigned)
                    if berry >= n:
                        raise ValueError(
                            f"group {key!r} has more than {n} distinct shelf lines, so two of its lines would "
                            "share a berry and collapse into one check"
                        )
                    assigned[original_item_id] = berry
                struct.pack_into(">H", rel_bytes, mart_item_slot_offset(rel, pool_index),
                                 dummy_item_ids[berry])
                count += 1
    return count


def apply_mart_fixed_stock(
    rel_bytes: bytearray,
    rel: RelFile,
    marts: "tuple[int, ...] | list[int]",
    stock: "tuple[int, ...] | list[int]",
    excluded_item_ids: "set[int] | frozenset[int]" = frozenset(),
) -> int:
    """ADDENDUM 311 (Agate Village Pit Stop): write real item ids into `marts`, overriding what
    `apply_mart_randomization` left. Patchable slots take `stock` in order; same in-place, same-width writes."""
    mart_count = number_of_marts(rel)
    count = 0
    for mart_index in marts:
        if not 0 <= mart_index < mart_count:
            continue
        line = 0
        for pool_index in mart_item_slots(rel, mart_index):
            off = mart_item_slot_offset(rel, pool_index)
            original_item_id = struct.unpack_from(">H", rel.data, off)[0]
            if original_item_id in excluded_item_ids:
                continue
            if not 1 <= original_item_id < ITEM_REMAP_THRESHOLD_ID:
                continue
            if line >= len(stock):
                raise ValueError(f"mart {mart_index} has more patchable lines than the {len(stock)}-item stock")
            struct.pack_into(">H", rel_bytes, off, int(stock[line]))
            line += 1
            count += 1
    return count


def byte_diff_offsets(original: bytes, patched: bytes) -> list[int]:
    """ADDENDUM 128: every offset at which `patched` differs from `original` (same length required)."""
    if len(original) != len(patched):
        raise ValueError(f"length mismatch: {len(original)} vs {len(patched)}")
    return [i for i, (a, b) in enumerate(zip(original, patched)) if a != b]


# REL structural validation (ADDENDUM 128). OSModuleHeader, the parts OSLink consumes: 0x00 id, 0x0C
# numSections, 0x10 sectionInfoOffset ({u32 offset|execFlag, u32 size}), 0x1C version, 0x20 bssSize, 0x24
# relOffset, 0x28 impOffset, 0x2C impSize ({u32 moduleId, u32 relocationsOffset}). A relocation list is 8-byte
# {u16 offset, u8 type, u8 section, u32 addend} entries ending in R_DOLPHIN_END (203); a type outside the set
# OSLink handles fails the link. Walking every list refuses such a REL before it is written and doubles as a
# decoder sanity check.

REL_RELOCATION_TYPES_OSLINK_HANDLES = frozenset({0, 1, 2, 3, 4, 5, 6, 10, 11, 201, 202, 203, 204})
R_DOLPHIN_SECTION = 202
R_DOLPHIN_END = 203
REL_HEADER_MIN_SIZE = 0x4C


def validate_rel_structure(data: bytes, label: str = "REL") -> dict:
    """Parses `data` as a GameCube REL and walks every import's relocation list to its R_DOLPHIN_END, raising
    `ValueError` on the first structural problem. Returns a summary dict for diagnostics. Read-only."""
    n = len(data)
    if n < REL_HEADER_MIN_SIZE:
        raise ValueError(f"{label}: only {n} bytes, shorter than a REL header ({REL_HEADER_MIN_SIZE})")

    def u32(off: int) -> int:
        if off < 0 or off + 4 > n:
            raise ValueError(f"{label}: header field read at {off:#x} is outside the file ({n} bytes)")
        return struct.unpack_from(">I", data, off)[0]

    header = {
        "id": u32(0x00),
        "num_sections": u32(0x0C),
        "section_info_offset": u32(0x10),
        "name_offset": u32(0x14),
        "name_size": u32(0x18),
        "version": u32(0x1C),
        "bss_size": u32(0x20),
        "rel_offset": u32(0x24),
        "imp_offset": u32(0x28),
        "imp_size": u32(0x2C),
    }
    num_sections = header["num_sections"]
    if num_sections == 0 or num_sections > 64:
        raise ValueError(f"{label}: implausible numSections={num_sections}")
    sio = header["section_info_offset"]
    if sio + num_sections * 8 > n:
        raise ValueError(f"{label}: section info table ({sio:#x}, {num_sections} entries) runs past the file")
    sections = []
    for s in range(num_sections):
        raw_off = u32(sio + s * 8)
        size = u32(sio + s * 8 + 4)
        off = raw_off & ~1
        if off and off + size > n:
            raise ValueError(f"{label}: section {s} ({off:#x} + {size:#x}) runs past the file ({n} bytes)")
        sections.append({"offset": off, "size": size, "exec": bool(raw_off & 1)})
    imp_off, imp_size = header["imp_offset"], header["imp_size"]
    if imp_size % 8 or imp_off + imp_size > n or imp_size == 0:
        raise ValueError(f"{label}: import table ({imp_off:#x}, size {imp_size}) is malformed or out of bounds")
    if header["rel_offset"] >= n:
        raise ValueError(f"{label}: relOffset {header['rel_offset']:#x} is outside the file")
    imports = []
    for k in range(imp_size // 8):
        module_id = u32(imp_off + k * 8)
        rel_off = u32(imp_off + k * 8 + 4)
        if rel_off >= n or rel_off % 4:
            raise ValueError(f"{label}: import {k} (module {module_id}) relocation offset {rel_off:#x} is invalid")
        p = rel_off
        count = 0
        while True:
            if p + 8 > n:
                raise ValueError(
                    f"{label}: import {k} (module {module_id}) relocation list from {rel_off:#x} runs past the "
                    f"end of the file ({n} bytes) without an R_DOLPHIN_END marker"
                )
            _delta, rel_type, section = struct.unpack_from(">HBB", data, p)
            if rel_type == R_DOLPHIN_END:
                break
            if rel_type not in REL_RELOCATION_TYPES_OSLINK_HANDLES:
                raise ValueError(
                    f"{label}: import {k} (module {module_id}) relocation entry #{count} at {p:#x} has type "
                    f"{rel_type}, which OSLink does not handle (it would log 'unknown relocation type "
                    f"{rel_type}' and fail the link)"
                )
            if rel_type == R_DOLPHIN_SECTION and section >= num_sections:
                raise ValueError(
                    f"{label}: import {k} relocation entry #{count} at {p:#x} selects section {section}, but the "
                    f"header only declares {num_sections}"
                )
            p += 8
            count += 1
        imports.append({"module": module_id, "rel_offset": rel_off, "entries": count, "end_offset": p + 8})
    return {"size": n, "header": header, "sections": sections, "imports": imports}


# Shop/mart location -- read-only candidate scan (ADDENDUM 119). The pocket_menu REL tables above were never
# live-confirmed and hold only Bag-menu UI texture data in this build (ADDENDUM 116/117); the real data is
# likely in the 7 per-town "shop" containers ADDENDUM 118 enumerated. With no oracle for what a shop should
# sell, this pattern-matches instead of writing: real mart data is a flat list of u16BE item ids ended by
# 0x0000.
def scan_bytes_for_item_id_runs(
    data: bytes, valid_item_ids: "set[int]", min_run_length: int = 3
) -> "list[dict]":
    """Read-only scan for candidate mart/shop item-id lists: consecutive u16BE values all in
    `valid_item_ids`, at least `min_run_length` of them, immediately followed by an exact 0x0000 terminator.
    Requiring both is what keeps coincidental runs out. NEVER WRITES ANYTHING."""
    out: "list[dict]" = []
    n = len(data)
    run_start: "int | None" = None
    run_ids: "list[int]" = []
    i = 0
    while i + 1 < n:
        value = struct.unpack_from(">H", data, i)[0]
        if value in valid_item_ids:
            if run_start is None:
                run_start = i
            run_ids.append(value)
        elif value == 0 and run_ids:
            if len(run_ids) >= min_run_length:
                out.append({"offset": run_start, "item_ids": list(run_ids), "terminator_offset": i})
            run_start = None
            run_ids = []
        else:
            # Neither a valid item id nor a sentinel: abandon the run WITHOUT recording it.
            run_start = None
            run_ids = []
        i += 2
    return out


# Pokemon base-stats table (ADDENDUM 20) -- Constants.cs's XDPokemonStats/XDNumberOfPokemon indices, plus the
# per-species level-up-moveset sub-table from Pokemon.cs (FirstLevelUpMoveOffset=0xC4,
# NumberOfLevelUpMoves=0x13, SizeOfLevelUpData=0x4). Indexed by this game's INTERNAL species index, the same
# one DPKM/DTNR records use. Confirmed 2026-09-07 against known Gen III learnsets -- species 1 (BULBASAUR)
# decodes to (1,Tackle=33), (4,Growl=45), (7,LeechSeed=73), (10,VineWhip=22), (15,PoisonPowder=77),
# (15,SleepPowder=79), (20,RazorLeaf=75), (25,SweetScent=230) -- and the count reads 415, matching
# xd_species_index.py's 0-414 range. One real vanilla gap: species 413 (BONSLY) has an EMPTY level-up list,
# which that randomizer patches manually, so an empty moveset is expected rather than an error.

XD_POKEMON_STATS_POINTER = 88
XD_NUMBER_OF_POKEMON_POINTER = 89
POKEMON_STATS_ENTRY_SIZE = 0x124
FIRST_LEVEL_UP_MOVE_OFFSET = 0xC4
NUMBER_OF_LEVEL_UP_MOVES = 0x13
SIZE_OF_LEVEL_UP_DATA = 0x4
LEVEL_UP_MOVE_LEVEL_OFFSET = 0x0
LEVEL_UP_MOVE_INDEX_OFFSET = 0x2
NUMBER_OF_POKEMON_MOVES = 4  # max moves in an active battle moveset


def pokemon_stats_base(rel: RelFile) -> int:
    """Absolute offset (within `rel.data`) of species-stats entry 0 (internal species index 0)."""
    return rel.get_pointer(XD_POKEMON_STATS_POINTER)


def pokemon_stats_count(rel: RelFile) -> int:
    """Real entry count per the REL's own table (415, confirmed against the real ISO 2026-09-07)."""
    return rel.get_value_at_pointer(XD_NUMBER_OF_POKEMON_POINTER)


# ADDENDUM 285: a wrong base here writes into arbitrary common_rel bytes, so the table is PROVEN first.
SPECIES_BASE_EXP_OFFSET = 0x05
#: ADDENDUM 300. Verified alongside the two experience offsets when the table was located: Bulbasaur 45,
#: Pikachu 190, Chansey 30, Mewtwo 3 -- four species agreeing at once on a single byte.
SPECIES_CATCH_RATE_OFFSET = 0x01
SPECIES_EXP_RATE_OFFSET = 0x00
SPECIES_BASE_HP_OFFSET = 0x8F


# ADDENDUM 291: the move table, and the field that turns battle animations off. rotobash's move pass zeroes
# every move's animation id, and its `Move` class resolves that id to `common_rel` pointer 124, a 0x38-byte
# stride and a u16 at +0x1E for XD. Those four facts are what this uses.
#
# Verified first against the player's own `common_rel`: exactly one 0x38-stride candidate reproduces eighteen
# known Gen III (PP, base power) pairs at +0x01/+0x19, at 0xA2710, and type (+0x02) and accuracy (+0x04) then
# decoded correctly too. The animation id IS the move index (359 distinct values over 359 entries), so slot 0
# is the "no animation" entry and writing 0 is unambiguous -- and that is why indices 0 and 355 are skipped:
# theirs is already 0. A second field at +0x32 usually agrees but the first four Shadow moves (356-359) do
# not, and it is left alone as unmeasured.
XD_MOVES_POINTER = 124
XD_NUMBER_OF_MOVES_POINTER = 125
MOVE_ENTRY_SIZE = 0x38
MOVE_PP_OFFSET = 0x01
MOVE_TYPE_OFFSET = 0x02
MOVE_ACCURACY_OFFSET = 0x04
MOVE_BASE_POWER_OFFSET = 0x19
MOVE_ANIMATION_OFFSET = 0x1E          # u16BE -- the one this writes
MOVE_SECOND_ANIMATION_OFFSET = 0x32   # u16BE -- measured, deliberately untouched (see above)

#: {move index: (PP, base power)}, standard Generation III data. Used ONLY as evidence that a candidate
#: table really is the move table, never as data the patch writes.
MOVE_TABLE_FINGERPRINT: "dict[int, tuple[int, int]]" = {
    1: (35, 40), 2: (25, 50), 3: (10, 15), 4: (15, 18), 5: (20, 80), 6: (20, 40),
    7: (15, 75), 8: (15, 75), 9: (15, 75), 10: (35, 40), 11: (30, 55), 13: (10, 80),
    15: (30, 50), 16: (35, 40), 17: (35, 60), 19: (15, 70), 20: (20, 15), 63: (5, 150),
}

#: Entries rotobash skips, and the measurement says why: their animation id is already 0.
MOVES_WITHOUT_ANIMATIONS: "frozenset[int]" = frozenset({0, 355})

# ADDENDUM 381: the two fields that decide which status a move inflicts, and the fence that keeps us off them.
#
# Measured 2026-09-28 against `bridge/dumps/a263_commonrel.bin`, chasing two player reports (Poison Fang
# slept its target, Icy Wind froze both of its). Neither offset was known before, and both matter more than
# the animation field above, because between them they ARE the move's status behaviour:
#
#   +0x05  secondary-effect chance, a percentage. 24 of 24 known Gen III chances matched exactly
#          (Ice Beam 10, Body Slam 30, Icy Wind 100, Shadow Ball 20, Octazooka 50, ...).
#   +0x1D  effect id, in Generation III's own EFFECT_* numbering. Found by grouping moves whose effect
#          CLASS is known and asking which byte separates the groups: twelve classes, each internally
#          unanimous and all twelve distinct -- sleep 1, poison 2, burn 4, freeze 5, paralyze 6, flinch 31,
#          toxic 33, paralyze(primary) 67, speed down 70, sp.def down 72, accuracy down 73, confuse 76.
#
# WHY THE FENCE. `MOVE_ANIMATION_OFFSET` is +0x1E, one byte past the effect id, and it is written as a u16,
# so the write covers +0x1E and +0x1F. It does not touch +0x1D -- confirmed across 163 MEM1 dumps, three of
# them from a build with the animation option on: those three differ from vanilla at +0x1E/+0x1F in exactly
# 358 entries (all but `MOVES_WITHOUT_ANIMATIONS`) and at no other byte of any entry. But "correct today, one
# byte from a status field" is a standing invitation, so the invariant is now enforced rather than assumed.
MOVE_SECONDARY_CHANCE_OFFSET = 0x05   # u8, percent
MOVE_EFFECT_OFFSET = 0x1D             # u8, Gen III EFFECT_* -- NOTHING here may ever write this

def verify_move_status_fields(rel: RelFile, census: "dict[int, tuple[int, int]]",
                              minimum_agreement: int = 300) -> bool:
    """True when this ISO's move table agrees with `census` on both status fields for every move it names.

    Stricter than `verify_moves_table`, which only proves the table's LOCATION: a base that satisfies PP and
    base power could still be a build whose effect numbering is not the measured one, and writing a byte away
    from those values on such a build is exactly what this refuses. `census` is
    `game_data.move_status.MOVE_STATUS`, passed in rather than imported so this module keeps owning only the
    byte layout (the same split as `verify_species_stats_table`)."""
    try:
        base = moves_table_base(rel)
        count = moves_table_count(rel)
    except Exception:
        return False
    data = rel.data
    checked = 0
    for index, (chance, effect) in census.items():
        if index >= count:
            continue
        off = base + index * MOVE_ENTRY_SIZE
        if off + MOVE_ENTRY_SIZE > len(data):
            return False
        if data[off + MOVE_SECONDARY_CHANCE_OFFSET] != chance:
            return False
        if data[off + MOVE_EFFECT_OFFSET] != effect:
            return False
        checked += 1
    return checked >= minimum_agreement


def move_status_fields(rel_bytes: bytes, base: int, count: int) -> bytes:
    """The two status bytes of every move entry, in index order -- the thing no write may change.

    Two bytes per move, so 720 bytes on a real table. Snapshot it before mutating `common_rel` and hand both
    halves to `assert_move_status_fields_unchanged`."""
    out = bytearray(2 * count)
    for index in range(count):
        off = base + index * MOVE_ENTRY_SIZE
        out[2 * index] = rel_bytes[off + MOVE_SECONDARY_CHANCE_OFFSET]
        out[2 * index + 1] = rel_bytes[off + MOVE_EFFECT_OFFSET]
    return bytes(out)


def assert_move_status_fields_unchanged(before: bytes, after: bytes) -> None:
    """Raise if any move's effect id or secondary-effect chance moved. Cheap enough to be unconditional: it
    is a 720-byte comparison in a pass whose LZSS re-encode takes tens of seconds."""
    if before == after:
        return
    drifted = []
    for index in range(min(len(before), len(after)) // 2):
        b, a = before[2 * index:2 * index + 2], after[2 * index:2 * index + 2]
        if b != a:
            drifted.append(f"move {index}: chance {b[0]}->{a[0]}, effect {b[1]}->{a[1]}")
    raise RuntimeError(
        "a common_rel write changed move STATUS data, which nothing in this project is allowed to touch -- "
        "refusing to ship the patch. "
        f"+0x{MOVE_SECONDARY_CHANCE_OFFSET:02X} is the secondary-effect chance and "
        f"+0x{MOVE_EFFECT_OFFSET:02X} the effect id; the animation write at "
        f"+0x{MOVE_ANIMATION_OFFSET:02X} sits one byte past the second of them. "
        + "; ".join(drifted[:10]) + (f"; and {len(drifted) - 10} more" if len(drifted) > 10 else "")
    )


def moves_table_base(rel: RelFile) -> int:
    return rel.get_pointer(XD_MOVES_POINTER)


def moves_table_count(rel: RelFile) -> int:
    return rel.get_value_at_pointer(XD_NUMBER_OF_MOVES_POINTER)


def verify_moves_table(rel: RelFile, minimum_agreement: int = 12) -> bool:
    """True when this ISO's move table is where the pointer says: many moves must agree at once on BOTH PP and
    base power. One coincidental match proves nothing, and a wrong base writes zeros into arbitrary bytes."""
    try:
        base = moves_table_base(rel)
        count = moves_table_count(rel)
    except Exception:
        return False
    data = rel.data
    checked = 0
    for index, (pp, power) in MOVE_TABLE_FINGERPRINT.items():
        if index >= count:
            continue
        off = base + index * MOVE_ENTRY_SIZE
        if off + MOVE_ENTRY_SIZE > len(data):
            return False
        if data[off + MOVE_PP_OFFSET] != pp or data[off + MOVE_BASE_POWER_OFFSET] != power:
            return False
        checked += 1
    return checked >= minimum_agreement


def apply_disable_move_animations(rel_bytes: bytearray, rel: RelFile) -> "dict[str, int]":
    """Zero every move's animation id. Bound-checked against the table's declared extent before writing."""
    base = moves_table_base(rel)
    count = moves_table_count(rel)
    end = base + count * MOVE_ENTRY_SIZE
    if end > len(rel_bytes):
        raise ValueError(
            f"this ISO's move table declares {count} entries ending at 0x{end:X}, past common_rel's "
            f"0x{len(rel_bytes):X} bytes -- refusing to write rather than running off the end"
        )
    cleared = 0
    already = 0
    for index in range(count):
        if index in MOVES_WITHOUT_ANIMATIONS:
            already += 1
            continue
        off = base + index * MOVE_ENTRY_SIZE + MOVE_ANIMATION_OFFSET
        if struct.unpack_from(">H", rel_bytes, off)[0] == 0:
            already += 1
            continue
        struct.pack_into(">H", rel_bytes, off, 0)
        cleared += 1
    return {"animations_cleared": cleared, "already_silent": already, "moves": count}


def read_species_experience(rel: RelFile) -> "dict[int, tuple[int, int]]":
    """{internal species index: (base_exp, exp_rate)} straight off this ISO's own stats table."""
    base = pokemon_stats_base(rel)
    count = pokemon_stats_count(rel)
    data = rel.data
    out: "dict[int, tuple[int, int]]" = {}
    for index in range(count):
        off = base + index * POKEMON_STATS_ENTRY_SIZE
        out[index] = (data[off + SPECIES_BASE_EXP_OFFSET], data[off + SPECIES_EXP_RATE_OFFSET])
    return out


# ADDENDUM 303, CORRECTED BY 304 -- the per-item behaviour table, found while asking whether catch rate can be
# literally 100%. Ruled out first: species stats and the DDPK override both cap at 255, the one guaranteed
# catch (the tutorial Teddiursa, ddpk index 1) has nothing unique in its record but level and deck pointer,
# and all 12 balls are BYTE-IDENTICAL in the Items table outside price, name id, description id and their own
# id, with no bonus array anywhere in common_rel.
#
# The table is indexed by item id, 8-byte stride: a u16 at +0x00, the constant 0x0104 at +0x02, that item's
# "use" handler pointer at +0x04, and all twelve balls share one handler. Across the full 400-row table the
# +0x00 value takes 14 distinct values -- 0x0028 (214 rows), 0x0004 (88), 0x0024 (84) and a tail -- and the
# Master Ball's 0x8C00 is the only one with BIT 15 SET, every other below 0x0500. ADDENDUM 304 also rebuilt
# the locator, which had matched handlers against the Items table's +0x20: that is 0x00000000 ON DISC and
# filled in by the REL loader, so it worked on a RAM dump and returned None for every real ISO.
#
# NOTHING IS WIRED TO A YAML OPTION -- one item having bit 15 set is worth an experiment, not a meaning. The
# handlers are not patchable here either: 0x800A4B7C sits below common_rel's RAM base (0x80B18DC0, ADDENDUM
# 263), so the ball's use routine is in the main DOL.
ITEM_BEHAVIOR_ENTRY_SIZE = 8
ITEM_BEHAVIOR_VALUE_OFFSET = 0x00
ITEM_BEHAVIOR_CONSTANT_OFFSET = 0x02
ITEM_BEHAVIOR_HANDLER_OFFSET = 0x04

#: Every row in the table carries this at +0x02. Part of what identifies a row as a row.
ITEM_BEHAVIOR_ROW_CONSTANT = 0x0104

#: The Master Ball's own value, and the bit that no other item in the table sets. Measured, never a meaning.
MASTER_BALL_BEHAVIOR_VALUE = 0x8C00
MASTER_BALL_BEHAVIOR_BIT = 0x8000

#: Item ids of the twelve balls, in id order. Used only to address the probe, never to derive anything.
BALL_ITEM_IDS: "tuple[int, ...]" = tuple(range(1, 13))

_PLAUSIBLE_POINTER_LOW = 0x80000000
_PLAUSIBLE_POINTER_HIGH = 0x81800000


def _behavior_row_is_plausible(data, off: int) -> bool:
    if off < 0 or off + ITEM_BEHAVIOR_ENTRY_SIZE > len(data):
        return False
    if struct.unpack_from(">H", data, off + ITEM_BEHAVIOR_CONSTANT_OFFSET)[0] != ITEM_BEHAVIOR_ROW_CONSTANT:
        return False
    handler = struct.unpack_from(">I", data, off + ITEM_BEHAVIOR_HANDLER_OFFSET)[0]
    return handler == 0 or _PLAUSIBLE_POINTER_LOW <= handler < _PLAUSIBLE_POINTER_HIGH


def find_item_behavior_table(rel: RelFile, minimum_rows: int = 300) -> "int | None":
    """Locate the per-item behaviour table, or None when this ISO does not reproduce it. BUILT ONLY FROM
    FIELDS THAT ARE THE SAME ON DISC AND IN RAM. Three conditions must hold at once: a contiguous run of at
    least `minimum_rows` plausible rows (the real table is 404; the next longest run in a real common_rel is
    15); exactly ONE row in it with bit 15 set, the Master Ball, which fixes the item-id alignment; and the
    twelve rows from there sharing one handler while their neighbours do not."""
    data = rel.data
    best_start = None
    best_len = 0
    off = 0
    while off + ITEM_BEHAVIOR_ENTRY_SIZE <= len(data):
        if not _behavior_row_is_plausible(data, off):
            off += 4
            continue
        start = off
        rows = 0
        while _behavior_row_is_plausible(data, off):
            off += ITEM_BEHAVIOR_ENTRY_SIZE
            rows += 1
        if rows > best_len:
            best_start, best_len = start, rows
    if best_start is None or best_len < minimum_rows:
        return None

    flagged = [
        index for index in range(best_len)
        if struct.unpack_from(">H", data, best_start + index * ITEM_BEHAVIOR_ENTRY_SIZE)[0]
        & MASTER_BALL_BEHAVIOR_BIT
    ]
    if len(flagged) != 1:
        return None
    base = best_start + (flagged[0] - 1) * ITEM_BEHAVIOR_ENTRY_SIZE
    if base < 0:
        return None

    handlers = []
    for item_id in list(BALL_ITEM_IDS) + [0, BALL_ITEM_IDS[-1] + 1]:
        off = base + item_id * ITEM_BEHAVIOR_ENTRY_SIZE + ITEM_BEHAVIOR_HANDLER_OFFSET
        if off + 4 > len(data):
            return None
        handlers.append(struct.unpack_from(">I", data, off)[0])
    ball_handlers, neighbours = handlers[:len(BALL_ITEM_IDS)], handlers[len(BALL_ITEM_IDS):]
    if len(set(ball_handlers)) != 1:
        return None
    if any(neighbour == ball_handlers[0] for neighbour in neighbours):
        return None
    return base


def read_item_behavior_values(rel: RelFile, base: int, item_ids: "list[int]") -> "dict[int, int]":
    """{item id: the u16 at +0x00 of its behaviour row}. Read-only; the probe's before/after evidence."""
    return {
        item_id: struct.unpack_from(
            ">H", rel.data, base + item_id * ITEM_BEHAVIOR_ENTRY_SIZE + ITEM_BEHAVIOR_VALUE_OFFSET)[0]
        for item_id in item_ids
    }


def apply_item_behavior_value(rel_bytes: bytearray, rel: RelFile, base: int,
                              item_ids: "list[int]", value: "int | None" = None,
                              set_bit: int = MASTER_BALL_BEHAVIOR_BIT) -> "dict[str, int]":
    """DIAGNOSTIC ONLY. `value` writes outright; None ORs `set_bit`, leaving the low bits alone."""
    written = 0
    for item_id in item_ids:
        off = base + int(item_id) * ITEM_BEHAVIOR_ENTRY_SIZE + ITEM_BEHAVIOR_VALUE_OFFSET
        if off < 0 or off + 2 > len(rel_bytes):
            raise ValueError(
                f"item {item_id}'s behaviour row at 0x{off:X} is outside this common_rel's "
                f"0x{len(rel_bytes):X} bytes -- refusing to write off the end"
            )
        if value is None:
            new_value = struct.unpack_from(">H", rel_bytes, off)[0] | int(set_bit)
        else:
            new_value = int(value)
        if not 0 <= new_value <= 0xFFFF:
            raise ValueError(f"behaviour value {new_value!r} does not fit the u16 it is written into")
        struct.pack_into(">H", rel_bytes, off, new_value)
        written += 1
    return {"behaviour_values_written": written}


def read_species_catch_rates(rel: RelFile) -> "dict[int, int]":
    """{internal species index: catch rate} off this ISO's own stats table."""
    base = pokemon_stats_base(rel)
    count = pokemon_stats_count(rel)
    data = rel.data
    return {index: data[base + index * POKEMON_STATS_ENTRY_SIZE + SPECIES_CATCH_RATE_OFFSET]
            for index in range(count)}


def apply_catch_rate(rel_bytes: bytearray, rel: RelFile, plan: dict) -> "dict[str, int]":
    """Writes `plan_catch_rate`'s bytes; bound-checked, or a 255 lands in whatever follows the table."""
    base = pokemon_stats_base(rel)
    count = pokemon_stats_count(rel)
    written = 0
    for key, value in (plan.get("catch_rate") or {}).items():
        index = int(key)
        value = int(value)
        if not 0 <= index < count:
            raise ValueError(
                f"species index {index} is outside this ISO's stats table, which declares {count} entries -- "
                f"writing it would put a catch rate into whatever follows the table"
            )
        if not 0 <= value <= 0xFF:
            raise ValueError(f"catch rate {value!r} for species {key!r} does not fit the byte the game reads")
        rel_bytes[base + index * POKEMON_STATS_ENTRY_SIZE + SPECIES_CATCH_RATE_OFFSET] = value
        written += 1
    return {"catch_rate_written": written}


def verify_species_stats_table(rel: RelFile, expected_base_hp: "dict[int, int]",
                               national_dex_for: "dict[int, int]", minimum_agreement: int = 20) -> bool:
    """True when this ISO's stats table is where the pointer says: the base-HP byte is checked against this
    project's census and at least `minimum_agreement` species must agree EXACTLY -- the same shape as
    `ItemPriceWriter.verify()`, and the method that located the table. A failing table is never written to."""
    try:
        base = pokemon_stats_base(rel)
        count = pokemon_stats_count(rel)
    except Exception:
        return False
    data = rel.data
    checked = 0
    for index in range(count):
        dex = national_dex_for.get(index)
        if not dex:
            continue
        want = expected_base_hp.get(dex)
        if not want:
            continue
        off = base + index * POKEMON_STATS_ENTRY_SIZE + SPECIES_BASE_HP_OFFSET
        if off >= len(data):
            return False
        if data[off] != want:
            return False
        checked += 1
    return checked >= minimum_agreement


def apply_experience_rate(rel_bytes: bytearray, rel: RelFile, plan: dict) -> "dict[str, int]":
    """Writes `species_stats.plan_experience_rate`'s base-exp and experience-group bytes. Both maps are keyed
    by str(index), which is what survives the JSON round-trip through the `.appxd` seed. Bound-checked
    against the table's declared extent; a value outside 0..255 raises rather than being masked."""
    base = pokemon_stats_base(rel)
    count = pokemon_stats_count(rel)
    written_exp = 0
    written_rate = 0

    def _entry(index: int) -> int:
        if not 0 <= index < count:
            raise ValueError(
                f"species index {index} is outside this ISO's stats table, which declares {count} entries -- "
                f"writing it would put an experience value into whatever follows the table"
            )
        return base + index * POKEMON_STATS_ENTRY_SIZE

    for key, value in (plan.get("base_exp") or {}).items():
        value = int(value)
        if not 0 <= value <= 0xFF:
            raise ValueError(f"base exp {value!r} for species {key!r} does not fit the byte the game reads")
        rel_bytes[_entry(int(key)) + SPECIES_BASE_EXP_OFFSET] = value
        written_exp += 1

    for key, value in (plan.get("exp_rate") or {}).items():
        value = int(value)
        if not 0 <= value <= 5:
            raise ValueError(f"experience group {value!r} for species {key!r} is not one of the game's six")
        rel_bytes[_entry(int(key)) + SPECIES_EXP_RATE_OFFSET] = value
        written_rate += 1

    return {"base_exp_written": written_exp, "exp_rate_written": written_rate}


def read_level_up_moves(rel: RelFile, species_index: int) -> list[tuple[int, int]]:
    """This species' vanilla level-up moveset as (level, move_id), skipping unused slots (level == 0; every
    species has 0x13 fixed slots). Empty means no moves are recorded -- a real vanilla gap, not a failure."""
    base = pokemon_stats_base(rel) + species_index * POKEMON_STATS_ENTRY_SIZE + FIRST_LEVEL_UP_MOVE_OFFSET
    data = rel.data
    out: list[tuple[int, int]] = []
    for i in range(NUMBER_OF_LEVEL_UP_MOVES):
        off = base + i * SIZE_OF_LEVEL_UP_DATA
        level = data[off + LEVEL_UP_MOVE_LEVEL_OFFSET]
        if level == 0:
            continue
        move = struct.unpack_from(">H", data, off + LEVEL_UP_MOVE_INDEX_OFFSET)[0]
        out.append((level, move))
    return out


# Poke Spot wild-encounter tables (ADDENDUM 43). Pointer indices cited from Constants.cs, entry layout from
# PokeSpotPokemon.cs, 12 bytes: MinLevel(u8,+0x0),
# MaxLevel(u8,+0x1), Species(u16BE,+0x2 -- this game's INTERNAL index, NOT National Dex above 252),
# EncounterPercentage(u32BE,+0x4), StepsPerSnack(u32BE,+0x8). Confirmed 2026-09-06 against the real ISO,
# cross-validated with Serebii and a GameFAQs FAQ. Reassignment only ever touches Species.

POKESPOT_POOL_POINTERS: dict[str, tuple[int, int]] = {
    # pool name -> (data pointer-table index, entry-count pointer-table index)
    "rock": (12, 13),
    "oasis": (15, 16),
    "cave": (18, 19),
    "all": (21, 22),
}
POKESPOT_ENTRY_SIZE = 0xC
POKESPOT_MIN_LEVEL_OFFSET = 0x0
POKESPOT_MAX_LEVEL_OFFSET = 0x1
POKESPOT_SPECIES_OFFSET = 0x2
POKESPOT_ENCOUNTER_PERCENTAGE_OFFSET = 0x4
POKESPOT_STEPS_PER_SNACK_OFFSET = 0x8


def pokespot_pool_base(rel: RelFile, pool: str) -> int:
    """Offset of `pool`'s entry 0. `pool` is "rock", "oasis", "cave" or "all" (KeyError otherwise)."""
    data_index, _entries_index = POKESPOT_POOL_POINTERS[pool]
    return rel.get_pointer(data_index)


def pokespot_pool_count(rel: RelFile, pool: str) -> int:
    """Real entry count for `pool` per the REL's own table (3 for rock/oasis/cave, 2 for all -- confirmed
    2026-09-06 against the real ISO, see game_data/pokespot_data.py's VANILLA_POKESPOT_SLOTS)."""
    _data_index, entries_index = POKESPOT_POOL_POINTERS[pool]
    return rel.get_value_at_pointer(entries_index)


def pokespot_species_offset(rel: RelFile, pool: str, slot_index: int) -> int:
    """Offset of `pool` entry `slot_index`'s u16BE Species field -- the only field reassignment writes."""
    return pokespot_pool_base(rel, pool) + slot_index * POKESPOT_ENTRY_SIZE + POKESPOT_SPECIES_OFFSET


def read_pokespot_entry(rel: RelFile, pool: str, slot_index: int) -> dict:
    """Full decode of one Poke Spot entry, for census use; patching only needs `pokespot_species_offset`."""
    base = pokespot_pool_base(rel, pool) + slot_index * POKESPOT_ENTRY_SIZE
    data = rel.data
    min_level = data[base + POKESPOT_MIN_LEVEL_OFFSET]
    max_level = data[base + POKESPOT_MAX_LEVEL_OFFSET]
    species_index = struct.unpack_from(">H", data, base + POKESPOT_SPECIES_OFFSET)[0]
    encounter_percentage = struct.unpack_from(">I", data, base + POKESPOT_ENCOUNTER_PERCENTAGE_OFFSET)[0]
    steps_per_snack = struct.unpack_from(">I", data, base + POKESPOT_STEPS_PER_SNACK_OFFSET)[0]
    return {
        "pool": pool, "slot_index": slot_index, "min_level": min_level, "max_level": max_level,
        "species_index": species_index, "encounter_percentage": encounter_percentage,
        "steps_per_snack": steps_per_snack,
    }


# ADDENDUM 392 -- the Poke Spot LEVEL fields, fenced.
#
# Player: "Another report of wild pokemon being level 0 at the wild spots."
#
# ADDENDUM 268 chased a level-0 Castform through four hypotheses and killed all four: every vanilla slot reads
# min >= 10 in the live `common_rel`, the assignment only ever names the eleven real slots, Castform has no
# alternate-form index, and all 386 dex numbers round-trip through the species index cleanly. It closed asking
# for the seed, and the report has come back instead.
#
# What 268 could NOT rule out is the one thing nothing checks: the Poke Spot write shares a single
# decompress/mutate/re-encode pass over `common_rel` with the chest writer, the item renamer, the experience
# tables and the animation zeroing (ADDENDUM 43 folded them together deliberately, because that file's LZSS
# re-encode budget is finite). The move-status fields got a before/after fence in ADDENDUM 381 for exactly this
# reason. The Poke Spot levels never did.
#
# Two guards, both of which ADDENDUM 381 already proved out on the move table:
#
#   1. VERIFY BEFORE WRITING. The eleven vanilla level ranges are a strong fingerprint -- nine of eleven slots
#      are 10-20/10-21/10-23 and the two "all" slots are 10-10 -- so if `pokespot_pool_base` ever resolves
#      somewhere else on some build, this refuses instead of writing a species over a MinLevel byte. That
#      failure mode would produce a level-0 encounter precisely: a species index below 256 written two bytes
#      early puts its high byte, zero, into MinLevel.
#   2. ASSERT AFTER. Snapshot every level byte before the pass and prove them unchanged after, so a stray write
#      from any writer in the shared pass is caught before the ISO is handed over.
#
# The ranges come from this project's own decode of the real `common_rel`, cross-checked against Serebii and a
# GameFAQs Poke Spot FAQ when ADDENDUM 43 shipped.
POKESPOT_VANILLA_LEVEL_RANGES: "dict[str, tuple[tuple[int, int], ...]]" = {
    "rock": ((10, 23), (10, 20), (10, 20)),
    "oasis": ((10, 20), (10, 20), (10, 20)),
    "cave": ((10, 21), (10, 21), (10, 21)),
    "all": ((10, 10), (10, 10)),
}
#: No wild encounter in this game is below this. A slot reading under it is the bug being hunted, not data.
POKESPOT_MIN_PLAUSIBLE_LEVEL = 2


def pokespot_level_fields(rel_bytes: bytes, rel: RelFile) -> bytes:
    """The two level bytes of every slot in every pool, in a fixed order, as one snapshot to compare."""
    out = bytearray()
    for pool in sorted(POKESPOT_POOL_POINTERS):
        base = pokespot_pool_base(rel, pool)
        for index in range(pokespot_pool_count(rel, pool)):
            entry = base + index * POKESPOT_ENTRY_SIZE
            out.append(rel_bytes[entry + POKESPOT_MIN_LEVEL_OFFSET])
            out.append(rel_bytes[entry + POKESPOT_MAX_LEVEL_OFFSET])
    return bytes(out)


def pokespot_level_report(rel_bytes: bytes, rel: RelFile) -> "list[dict]":
    """Every slot's decoded level range, for a diagnostic that has to say WHICH slot is wrong."""
    rows = []
    for pool in sorted(POKESPOT_POOL_POINTERS):
        base = pokespot_pool_base(rel, pool)
        for index in range(pokespot_pool_count(rel, pool)):
            entry = base + index * POKESPOT_ENTRY_SIZE
            expected = POKESPOT_VANILLA_LEVEL_RANGES.get(pool, ())
            rows.append({
                "pool": pool,
                "slot_index": index,
                "min_level": rel_bytes[entry + POKESPOT_MIN_LEVEL_OFFSET],
                "max_level": rel_bytes[entry + POKESPOT_MAX_LEVEL_OFFSET],
                "expected": expected[index] if index < len(expected) else None,
            })
    return rows


def verify_pokespot_table(rel: RelFile) -> bool:
    """Does this ISO's Poke Spot table reproduce the eleven known vanilla level ranges?

    The same argument `verify_moves_table` makes: the pointer walk says WHERE, and this says the thing found
    there really is the table. A pool whose count disagrees fails too -- writing slot 2 of a pool this build
    says has one entry is the out-of-bounds case ADDENDUM 268 added a bound for."""
    try:
        for pool, expected in POKESPOT_VANILLA_LEVEL_RANGES.items():
            if pokespot_pool_count(rel, pool) != len(expected):
                return False
            base = pokespot_pool_base(rel, pool)
            for index, (want_min, want_max) in enumerate(expected):
                entry = base + index * POKESPOT_ENTRY_SIZE
                if rel.data[entry + POKESPOT_MIN_LEVEL_OFFSET] != want_min:
                    return False
                if rel.data[entry + POKESPOT_MAX_LEVEL_OFFSET] != want_max:
                    return False
    except Exception:
        return False
    return True


def assert_pokespot_levels_unchanged(before: bytes, after: bytes) -> None:
    """Raises if any Poke Spot level byte moved. ADDENDUM 381's fence, applied to the other table in the pass."""
    if before == after:
        return
    moved = [i for i in range(min(len(before), len(after))) if before[i] != after[i]]
    raise AssertionError(
        f"the Poke Spot level fields changed during the common_rel pass ({len(moved)} byte(s), first at index "
        f"{moved[0] if moved else 'unknown'}) -- something in this pass wrote over a wild encounter's level, "
        "which is the level-0 wild Pokemon players have reported. The ISO was NOT written."
    )


def apply_pokespot_species(rel_bytes: bytearray, rel: RelFile, assignment: dict[str, int]) -> int:
    """Overwrites each keyed slot's Species field in `rel_bytes`. Keys are "{pool}:{slot_index}" strings,
    matching seed_data['pokespot_species_by_slot'] -- strings because that survives the JSON round-trip.
    iso_patcher folds this into the SAME re-encode cycle as `apply_chest_dummy_item`, because common_rel's
    re-encoded size budget is finite."""
    count = 0
    for key, new_species in assignment.items():
        pool, slot_index_str = key.split(":", 1)
        slot_index = int(slot_index_str)
        # ADDENDUM 268: `pokespot_species_offset` is pure arithmetic (base + index * 0xC + 2) with nothing
        # checking the index against `pokespot_pool_count`, so a bad key would write a species into whatever
        # follows the table -- zero padding reads back as a Pokemon with min/max level 0.
        available = pokespot_pool_count(rel, pool)
        if not 0 <= slot_index < available:
            raise ValueError(
                f"pokespot slot {key!r} is outside the {pool!r} pool, which this ISO says has {available} "
                f"entries -- writing it would put a species into whatever follows the table"
            )
        if not 0 < int(new_species) <= 0xFFFF:
            raise ValueError(f"pokespot slot {key!r} was assigned species index {new_species!r}, which is "
                             "not a species this game can encode")
        off = pokespot_species_offset(rel, pool, slot_index)
        struct.pack_into(">H", rel_bytes, off, int(new_species))
        count += 1
    return count


def load_common_rel(common_fsys_bytes: bytes, lzss_decode) -> RelFile:
    """Locates the `common_rel` entry in a raw `common.fsys` and decompresses it with the `lzss_decode`
    passed in (passed, not imported, to avoid that module's import-path quirks). The entry is named bare
    "common_rel", no ".rel" suffix -- confirmed 2026-09-07 against a live dump (27 entries, 704448 bytes)."""
    # Local import, to avoid a top-of-file dependency on iso_patcher's sibling-import dance. Package first
    # (ADDENDUM 260): trying the flat import first meant anything that had put tools/ on sys.path could get a
    # SECOND copy of the patcher imported under another name and winning.
    if __package__:
        from . import iso_patcher  # type: ignore
    else:  # pragma: no cover - standalone execution from within tools/
        import iso_patcher  # type: ignore
    entries = iso_patcher.parse_fsys(common_fsys_bytes)
    entry = entries["common_rel"]
    entry_raw = common_fsys_bytes[entry["data_off"]: entry["data_off"] + 0x10 + entry["comp_size"]]
    decompressed = lzss_decode(entry_raw)
    return RelFile(decompressed, is_common=True)


# CommonRelStringTable + Items table (ADDENDUM 113/114: the AP Item in-game rename), both in `common_rel.rel`
# and indexed in its own pointer space.
#
# CommonRelStringTable (pointer 116, base = `rel.get_pointer(116) + 0x68`) is the same shared table species
# names resolve through; per ADDENDUM 113's reading of StringTable.cs/Items.cs/Move.cs/Abilities.cs, item,
# move and ability names all resolve through this one.
# Layout: a 0x10-byte header (count u16BE at +0x04), `entry_count` 8-byte records (4-byte id masked & 0xFFFFF,
# 4-byte offset), then UTF-16BE data terminated by 0x0000, with 0xFFFF reserved as an escape unit. ADDENDUM
# 125: a record's stored offset is relative to the TABLE'S OWN HEADER START, not the data region, which is why
# every lookup used to land 15,464 bytes too far; the smallest stored offset is exactly `0x10 + entry_count *
# 8` and points at "MASTER BALL" only when measured from the header. Corrected, 1729/1931 entries decode as
# clean text, species names sit at NameIDs 1001+ and item names at 5001+. Lookup goes through that explicit
# id->offset index, never by walking strings, which is what makes an EQUAL-BYTE-LENGTH overwrite safe: nothing
# else's location depends on the edited string's length.
#
# Items table (pointer 70; ValidItems=68, TotalNumberOfItems=69, Items=70, XDNumberOfItems=71): a per-item-id
# struct table, 0x28 stride, price at +0x06, CanBeHeld at +0x01, NameID at +0x10. Items.cs's XD branch shifts
# ids strictly between the live `XDNumberOfItems` scalar and 0x251 (593) down by 150; that scalar is read
# dynamically, but whether XD's on-disk table really applies the remap is unconfirmed. Every rename target
# (the useless berries, ids 148-174, 26 since Enigma Berry/175 was dropped in ADDENDUM 117) is well below any
# plausible threshold anyway.

COMMON_REL_STRING_TABLE_POINTER = 116
STRING_TABLE_BLOB_OFFSET = 0x68
STRING_TABLE_ENTRY_COUNT_OFFSET = 0x04
STRING_TABLE_HEADER_SIZE = 0x10
STRING_TABLE_ENTRY_SIZE = 8
STRING_TABLE_ID_MASK = 0xFFFFF
STRING_TABLE_TERMINATOR = 0x0000
STRING_ESCAPE_UNIT = 0xFFFF

ITEMS_TABLE_POINTER = 70
XD_NUMBER_OF_ITEMS_POINTER = 71
ITEM_ENTRY_SIZE = 0x28
ITEM_NAME_ID_OFFSET = 0x10
ITEM_REMAP_THRESHOLD_ID = 0x251  # 593
ITEM_REMAP_SHIFT = 150


def string_table_base(rel: RelFile) -> int:
    """Absolute offset (within `rel.data`) of the CommonRelStringTable's own header."""
    return rel.get_pointer(COMMON_REL_STRING_TABLE_POINTER) + STRING_TABLE_BLOB_OFFSET


def string_table_entry_count(rel: RelFile) -> int:
    """Entry count field -- a u16BE at the table header's `+0x04` (per `StringTable.cs`)."""
    base = string_table_base(rel)
    return struct.unpack_from(">H", rel.data, base + STRING_TABLE_ENTRY_COUNT_OFFSET)[0]


def string_table_data_region_base(rel: RelFile) -> int:
    """Absolute offset of the string-data region, after the header and record array. INFORMATIONAL ONLY: a
    record's stored offset is relative to `string_table_base`, not to this, so no lookup uses it."""
    return string_table_base(rel) + STRING_TABLE_HEADER_SIZE + string_table_entry_count(rel) * STRING_TABLE_ENTRY_SIZE


def string_table_id_offsets(rel: RelFile) -> dict[int, int]:
    """Every (masked id -> absolute offset of that string's first UTF-16BE unit) pair, walking the record
    array once. Offsets are relative to the table's own header start (ADDENDUM 125) -- the one-line base
    change that turned the AP Item rename from 0/27 to 27/27."""
    base = string_table_base(rel)
    count = string_table_entry_count(rel)
    data = rel.data
    out: dict[int, int] = {}
    for i in range(count):
        rec_off = base + STRING_TABLE_HEADER_SIZE + i * STRING_TABLE_ENTRY_SIZE
        raw_id = struct.unpack_from(">I", data, rec_off)[0]
        string_off = struct.unpack_from(">I", data, rec_off + 4)[0]
        out[raw_id & STRING_TABLE_ID_MASK] = base + string_off
    return out


def _decode_utf16be_run(data: bytes, off: int) -> tuple[bytes, int, bool]:
    """Reads UTF-16BE units from `off` to a 0x0000 terminator or an 0xFFFF escape. Returns `(raw_bytes,
    total_length_including_terminator_or_escape, hit_escape)`; `hit_escape` also covers a truncated buffer."""
    raw = bytearray()
    i = off
    n = len(data)
    while i + 2 <= n:
        value = struct.unpack_from(">H", data, i)[0]
        if value == STRING_ESCAPE_UNIT:
            return bytes(raw), (i - off) + 2, True
        if value == STRING_TABLE_TERMINATOR:
            return bytes(raw), (i - off) + 2, False
        raw += data[i:i + 2]
        i += 2
    return bytes(raw), (i - off), True


def read_string_table_entry_bytes(rel: RelFile, abs_offset: int) -> bytes:
    """One entry's raw UTF-16BE bytes from `abs_offset`, no terminator. Stops early on an 0xFFFF escape."""
    raw, _total_len, _hit_escape = _decode_utf16be_run(rel.data, abs_offset)
    return raw


# ADDENDUM 123: a live dump of pointer 116's table (1931 entries) matched none of 27 known item names but
# plenty of move and species fragments -- so the table decodes correctly and items may live in a separate
# per-category table.
def find_candidate_item_string_tables(
    rel: RelFile, known_item_names: "set[str]", substring_hints: "set[str]" = frozenset()
) -> "list[dict]":
    """Read-only diagnostic: try EVERY pointer index as a candidate string table, parsed exactly like pointer
    116, reporting EXACT matches against `known_item_names` and SUBSTRING matches against `substring_hints`.
    Candidates that fail to parse are skipped silently, since most indices are not string tables."""
    out: "list[dict]" = []
    normalized_targets = {n.strip().casefold() for n in known_item_names}
    normalized_hints = {h.strip().casefold() for h in substring_hints if h.strip()}
    data = rel.data
    n = len(data)
    for pointer_index in range(rel.number_of_pointers):
        try:
            base = rel.get_pointer(pointer_index) + STRING_TABLE_BLOB_OFFSET
            if base < 0 or base + STRING_TABLE_HEADER_SIZE > n:
                continue
            count = struct.unpack_from(">H", data, base + STRING_TABLE_ENTRY_COUNT_OFFSET)[0]
            if count <= 0 or count > 20000:
                continue
            matches: "list[dict]" = []
            for i in range(count):
                rec_off = base + STRING_TABLE_HEADER_SIZE + i * STRING_TABLE_ENTRY_SIZE
                if rec_off + STRING_TABLE_ENTRY_SIZE > n:
                    break
                raw_id = struct.unpack_from(">I", data, rec_off)[0]
                string_off = struct.unpack_from(">I", data, rec_off + 4)[0]
                abs_off = base + string_off  # ADDENDUM 125: offsets are relative to the table header start
                if abs_off < 0 or abs_off >= n:
                    continue
                raw, _total_len, hit_escape = _decode_utf16be_run(data, abs_off)
                if hit_escape:
                    continue
                text = raw.decode("utf-16-be", errors="replace")
                normalized = text.strip().casefold()
                name_id = raw_id & STRING_TABLE_ID_MASK
                if normalized in normalized_targets:
                    matches.append({"name_id": name_id, "text": text, "kind": "exact"})
                elif normalized_hints and any(hint in normalized for hint in normalized_hints):
                    matches.append({"name_id": name_id, "text": text, "kind": "substring"})
                else:
                    continue
                if len(matches) >= 50:
                    break
            if matches:
                # `unique_name_ids` flags a degenerate parse: far fewer unique ids than matches.
                out.append({
                    "pointer_index": pointer_index,
                    "entry_count": count,
                    "matches": matches,
                    "unique_name_ids": len({m["name_id"] for m in matches}),
                })
        except Exception:
            continue
    return out


def item_table_base(rel: RelFile) -> int:
    """Absolute offset (within `rel.data`) of Items-table entry index 0."""
    return rel.get_pointer(ITEMS_TABLE_POINTER)


def xd_number_of_items(rel: RelFile) -> int:
    """Live `XDNumberOfItems` scalar, read dynamically -- the remap threshold `item_table_index` uses."""
    return rel.get_value_at_pointer(XD_NUMBER_OF_ITEMS_POINTER)


def item_table_index(rel: RelFile, item_id: int) -> int:
    """Resolves a game item id to its Items-table array index, applying Items.cs's XD-branch remap (ids
    strictly between `XDNumberOfItems` and 0x251 shift down by 150). Unconfirmed against a live ISO."""
    threshold = xd_number_of_items(rel)
    if threshold < item_id < ITEM_REMAP_THRESHOLD_ID:
        return item_id - ITEM_REMAP_SHIFT
    return item_id


def item_name_id(rel: RelFile, item_id: int) -> int:
    """Item `item_id`'s NameID -- u32BE at +0x10 of its entry, masked & 0xFFFFF like the string table."""
    index = item_table_index(rel, item_id)
    off = item_table_base(rel) + index * ITEM_ENTRY_SIZE + ITEM_NAME_ID_OFFSET
    raw = struct.unpack_from(">I", rel.data, off)[0]
    return raw & STRING_TABLE_ID_MASK


# ADDENDUM 124: pointer 116 does resolve at least one real item name ("Krane Memo 4"), so the mechanism is not
# broken across the board. This checks the original struct resolution on items other than the berry rename
# targets.
def check_item_struct_resolution_sample(rel: RelFile, sample_item_names: "dict[int, str]") -> "list[dict]":
    """DIAGNOSTIC ONLY. Runs the original resolution per {item_id: expected_name} and reports matches."""
    id_offsets = string_table_id_offsets(rel)
    out: "list[dict]" = []
    for item_id, expected_name in sample_item_names.items():
        try:
            name_id = item_name_id(rel, item_id)
        except Exception as exc:
            out.append({"item_id": item_id, "expected": expected_name, "found": None, "match": False,
                        "reason": f"could not resolve NameID: {exc}"})
            continue
        abs_off = id_offsets.get(name_id)
        if abs_off is None:
            out.append({"item_id": item_id, "expected": expected_name, "found": None, "match": False,
                        "reason": f"NameID {name_id} not found in string table"})
            continue
        raw, _total_len, hit_escape = _decode_utf16be_run(rel.data, abs_off)
        if hit_escape:
            out.append({"item_id": item_id, "expected": expected_name, "found": None, "match": False,
                        "reason": "hit an 0xFFFF escape/unterminated run"})
            continue
        text = raw.decode("utf-16-be", errors="replace")
        out.append({
            "item_id": item_id,
            "expected": expected_name,
            "found": text,
            "match": text.strip().casefold() == expected_name.strip().casefold(),
        })
    return out


# ADDENDUM 121: knowing where item_id's NameID lives was never necessary -- only where the STRING is, since
# that is all this function writes -- and `string_table_id_offsets()` already maps every string. So the
# fallback searches that map for the entry whose decoded text equals the expected name; it activates only for
# an item_id in `expected_names`, since otherwise there is no ground truth. (ADDENDUM 119 first tried
# perturbing the NameID offset and entry index, ~20 combinations per item, and came back 0/27 -- which ruled
# out a small per-field error.)


def apply_item_name_rename(
    rel_bytes: bytearray,
    rel: RelFile,
    item_ids: "list[int]",
    replacement_text: str = "AP Item",
    expected_names: "dict[int, str] | None" = None,
) -> dict:
    """Overwrites each item's display-name STRING in the shared CommonRelStringTable with `replacement_text`,
    right-padded with spaces to the original string's exact encoded byte length (UTF-16BE, terminator
    included). EQUAL-LENGTH-ONLY: lookup is by an untouched id->offset index, so nothing else moves as long
    as the length does not change. The item id itself is never touched.

    `expected_names` is the defensive check against the unconfirmed Items-table remap: the current decoded
    string must match, case- and trailing-whitespace-insensitively, or that item is skipped. It is the only
    thing between a resolved-but-wrong NameID and a corrupted unrelated string.

    For an item with an entry, the original struct path is tried first (it is literally the string the item's
    NameID points at), then ADDENDUM 121's text search, used only on an exact, UNIQUE match. Every per-item
    problem is a skip, never an exception. This function never grows a string."""
    renamed: list[int] = []
    skipped: list[dict] = []
    resolved_via: dict[int, dict] = {}
    expected_names = expected_names or {}
    id_offsets = string_table_id_offsets(rel)
    data = rel.data

    for item_id in item_ids:
        expected = expected_names.get(item_id)

        if expected is None:
            # The original default path: no ground truth to calibrate a search against, so it stays as it was.
            try:
                name_id = item_name_id(rel, item_id)
            except Exception as exc:  # pragma: no cover -- defensive; no known way to trigger against real data
                skipped.append({"item_id": item_id, "reason": f"could not resolve NameID: {exc}"})
                continue

            abs_off = id_offsets.get(name_id)
            if abs_off is None:
                skipped.append({"item_id": item_id, "reason": f"NameID {name_id} not found in string table index"})
                continue

            raw_bytes, total_len, hit_escape = _decode_utf16be_run(data, abs_off)
            if hit_escape:
                skipped.append({
                    "item_id": item_id,
                    "reason": "original string contains an 0xFFFF escape unit or is unterminated -- not renamed",
                })
                continue
        else:
            expected_norm = expected.strip().casefold()
            abs_off = None
            total_len = None

            # 1. PRIMARY (ADDENDUM 125): the original struct path, verified against the expected name.
            struct_note = ""
            try:
                struct_name_id = item_name_id(rel, item_id)
                struct_abs_off = id_offsets.get(struct_name_id)
                if struct_abs_off is None:
                    struct_note = f"struct path resolved NameID {struct_name_id}, not in the string table index"
                else:
                    s_raw, s_total_len, s_hit_escape = _decode_utf16be_run(data, struct_abs_off)
                    if s_hit_escape:
                        struct_note = f"struct path resolved NameID {struct_name_id}, an escape/unterminated string"
                    else:
                        s_text = s_raw.decode("utf-16-be", errors="replace")
                        if s_text.strip().casefold() == expected_norm:
                            abs_off, total_len = struct_abs_off, s_total_len
                            resolved_via[item_id] = {"via": "struct", "name_id": struct_name_id}
                        else:
                            struct_note = f"struct path resolved NameID {struct_name_id} = {s_text!r}"
            except Exception as exc:
                struct_note = f"struct path could not resolve a NameID ({exc})"

            # 2. FALLBACK (ADDENDUM 121): exact, unique text search across the whole table.
            if abs_off is None:
                matches: "list[tuple[int, int, int]]" = []  # (name_id, abs_off, total_len)
                for name_id, cand_abs_off in id_offsets.items():
                    cand_raw, cand_total_len, cand_hit_escape = _decode_utf16be_run(data, cand_abs_off)
                    if cand_hit_escape:
                        continue
                    cand_text = cand_raw.decode("utf-16-be", errors="replace")
                    if cand_text.strip().casefold() == expected_norm:
                        matches.append((name_id, cand_abs_off, cand_total_len))

                if not matches:
                    skipped.append({
                        "item_id": item_id,
                        "reason": (
                            f"expected {expected!r}: {struct_note}; text search found it nowhere in this REL's "
                            f"own string table ({len(id_offsets)} entries) -- skipped for safety"
                        ),
                    })
                    continue
                if len(matches) > 1:
                    skipped.append({
                        "item_id": item_id,
                        "reason": (
                            f"expected {expected!r}: {struct_note}; text search matched {len(matches)} "
                            f"different string-table entries (NameIDs {[m[0] for m in matches]}) -- ambiguous "
                            f"which one is this item's own name, skipped for safety"
                        ),
                    })
                    continue

                name_id, abs_off, total_len = matches[0]
                resolved_via[item_id] = {"via": "text-search", "name_id": name_id}
            # Whichever path set abs_off/total_len already confirmed an exact match against the expected name.

        available_text_bytes = total_len - 2  # total_len includes the 2-byte terminator
        base_bytes = replacement_text.encode("utf-16-be")
        if len(base_bytes) > available_text_bytes:
            skipped.append({
                "item_id": item_id,
                "reason": f"{replacement_text!r} ({len(base_bytes)} bytes) does not fit in original string's "
                          f"{available_text_bytes}-byte budget",
            })
            continue

        pad_units = (available_text_bytes - len(base_bytes)) // 2
        new_bytes = (replacement_text + (" " * pad_units)).encode("utf-16-be") + b"\x00\x00"
        if len(new_bytes) != total_len:
            # Defensive -- unreachable given the padding math, but never write a mismatched-length edit.
            skipped.append({"item_id": item_id, "reason": "internal padding length mismatch -- not renamed"})
            continue

        rel_bytes[abs_off:abs_off + total_len] = new_bytes
        renamed.append(item_id)

    return {"renamed": renamed, "skipped": skipped, "resolved_via": resolved_via}
