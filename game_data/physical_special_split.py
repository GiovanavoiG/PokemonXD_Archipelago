"""Physical/Special Split and Update Moves to Gen 9 -- two options over the same move-table rows.

Physical/Special Split writes each move's Generation IX category. Update Moves to Gen 9 writes its Generation IX
priority, PP, accuracy, type and power. Either can be on without the other.

THE TABLE is common_rel's move table (inside `common.fsys`): pointer index 124, 0x38 bytes per move
(`xd_rel_format.MOVE_ENTRY_SIZE`). The fields, by their `waza::wazaDataBios*` accessors in main.dol:

    +0x00  s8   priority        (`wazaDB_GetPri`)
    +0x01  u8   PP
    +0x02  u8   type            (`zz_move_get_type`)
    +0x04  u8   accuracy, 0 = never misses
    +0x13  u8   category, 0 = the type decides, 1 = physical, 2 = special (`waza_GetZokuseiKindData`)
    +0x18  s16  base power      (`wazaDataBiosGetIryoku`; `xd_rel_format.MOVE_BASE_POWER_OFFSET` is its low byte)
    +0x20  u32  name id         (`zz_move_data_get_name_id`) -- the key into the definitions

THE DEFINITIONS are `data/move_data.json`'s rows: `Name` and `NameId`, plus a `Vanilla*` and `Gen9*` pair for each
field above that Generation IX changes -- a field the row leaves out keeps its vanilla value. A row is written only
when every field it lists still holds its `Vanilla*` value -- whichever option is on -- so a build whose table is not
vanilla's is refused whole rather than half-converted.

FAIRY. Charm, Sweet Kiss and Moonlight are Fairy in Generation IX, a type XD does not have; their definitions
leave their type out. A definition naming a type past Dark keeps the vanilla type and is reported.

THE CATEGORY BYTE ALONE DOES NOTHING for an ordinary move. `waza_GetZokuseiKindData` (main.dol 0x8013E7F0) reads
+0x13 only when `wazaCheckDarkWaza` says the move is a Shadow move, and asks the move's TYPE for every other one
(`zokusei::zokuseiBiosGetWazaKind`). So the split also replaces that call, `bl wazaCheckDarkWaza` at 0x8013E820, with
`li r3,1`, along with the same check at the other call sites that pick a category (`SHADOW_CHECK_WORDS`): every move
then takes the +0x13 path (`dol_patch_words`). The Shadow moves already carry 1 or 2 there, so
they are unchanged.

THE DESCRIPTIONS. Each move whose category the split changes, and each Shadow move with a base power (the ones that
already carry 1 or 2 at +0x13 and that the definitions give no category), gets that category in capitals as a first
line of its description: POUND's "Pounds the target with{br}forelegs or tail." becomes "PHYSICAL{br}Pounds the target with{br}
forelegs or tail.", where {br} is the 3-byte line break `FF FF 00`. A description id is the row's +0x2C, a string in
main.dol's own message table (`MESSAGE_TABLE`, "US", 859 strings, the first `GSmsgOpen` at boot, 0x8005C4E8). That
table has no slack, and the 216 prefixes need 3,950 more bytes. The game resolves a string as table + the pair's
offset in 32-bit arithmetic with no bounds check (`zz_get_pointer_to_string_with_id`, 0x80107300), so a string can
live anywhere: `description_patch_words` repacks the run of strings the move descriptions occupy, prefixes added,
and what no longer fits goes into `DESCRIPTION_OVERFLOW`: 1,839 debug-only strings (floor names such as
"S2_building_1F_2", ids 60370-62317 among them) in the third table main.dol opens, reclaimed. Their pairs keep pointing
there.

Import-free so the standalone patcher can load it by path.
"""
from __future__ import annotations

import hashlib
import struct

MOVE_ENTRY_SIZE = 0x38
PRIORITY_OFFSET = 0x00
PP_OFFSET = 0x01
TYPE_OFFSET = 0x02
ACCURACY_OFFSET = 0x04
CATEGORY_OFFSET = 0x13
POWER_OFFSET = 0x18
NAME_ID_OFFSET = 0x20
DESCRIPTION_ID_OFFSET = 0x2C

#: The first line a changed move's description gets, by its new category.
CATEGORY_NAMES = {1: "PHYSICAL", 2: "SPECIAL"}
LINE_BREAK = b"\xff\xff\x00"

#: main.dol's message table (file offset 0x374FC0 on GXXE01) and the SHA-1 of its vanilla bytes.
MESSAGE_TABLE = 0x80377FC0
MESSAGE_TABLE_SIZE = 0x178BC
MESSAGE_TABLE_SHA1 = "f754613c36ee65961be4a531b460a7e687c7fec8"
MESSAGE_COUNT_OFFSET = 0x04
MESSAGE_PAIRS_OFFSET = 0x10
MESSAGE_PAIR_SIZE = 8
MESSAGE_ID_MASK = 0xFFFFF
#: Debug-only strings ("Auto Demonstration" up to, not including, "D6_dome_2F (Dome 2F)"): where the descriptions
#: that outgrow the table go.
DESCRIPTION_OVERFLOW = 0x80399274
DESCRIPTION_OVERFLOW_SIZE = 0xBF74
DESCRIPTION_OVERFLOW_SHA1 = "a7b4c416243fbdeee25e8b6593bb955dd05d2bcc"

#: main.dol: each `bl wazaCheckDarkWaza` (0x8013D03C) that picks a move's category -> `li r3,1`.
#: {address: vanilla `bl` word}; the first is the one inside `waza_GetZokuseiKindData` (file offset 0x13B780).
SHADOW_CHECK_WORDS = {
    0x8013E820: 0x4BFFE81D,
    0x802157E4: 0x4BF27859,
    0x802177D4: 0x4BF25869,
    0x80229608: 0x4BF13A35,
    0x8022A074: 0x4BF12FC9,
}
PATCHED_SHADOW_CHECK_WORD = 0x38600001

AI_MOVE_CHECK_ADDRESSES = [
    { "address": 0x802e2d60, "vanilla": 0x4be34d65, "patched": 0x4be5ba91 },
    { "address": 0x802e2e7c, "vanilla": 0x4be34c49, "patched": 0x4be5b975 }
]


#: XD's last type index (17, Dark). A Generation IX type past it (Fairy, 18) is not written.
MAX_XD_TYPE = 17

#: (definition suffix, offset, struct format). Physical/Special Split writes these.
CATEGORY_FIELDS: "tuple[tuple[str, int, str], ...]" = (
    ("Category", CATEGORY_OFFSET, ">B"),
)
#: Update Moves to Gen 9 writes these.
GEN9_FIELDS: "tuple[tuple[str, int, str], ...]" = (
    ("Priority", PRIORITY_OFFSET, ">b"),
    ("Pp", PP_OFFSET, ">B"),
    ("Accuracy", ACCURACY_OFFSET, ">B"),
    ("Type", TYPE_OFFSET, ">B"),
    ("Power", POWER_OFFSET, ">h"),
)
#: Every field; all of them are checked against `Vanilla*` before anything is written.
FIELDS = GEN9_FIELDS + CATEGORY_FIELDS


def dol_patch_words() -> "tuple[tuple[int, int, int], ...]":
    """(address, vanilla word, new word) -- the split's main.dol half."""
    patched_words = tuple((address, vanilla, PATCHED_SHADOW_CHECK_WORD) for address, vanilla in SHADOW_CHECK_WORDS.items())
    patched_words += tuple((ai["address"], ai["vanilla"], ai["patched"]) for ai in AI_MOVE_CHECK_ADDRESSES)
    
    return patched_words


def apply_move_updates(rel_bytes: bytearray, moves_base: int, move_count: int, definitions: "list[dict]",
                       split: bool, gen9_moves: bool) -> "dict[str, object]":
    """Write the Generation IX values of the enabled options into the move table in `rel_bytes` (common_rel,
    decompressed), in place: the category when `split`, the other five fields when `gen9_moves`. `moves_base` is
    the table's offset in `rel_bytes`, `move_count` its row count, and `definitions` `move_data.json`'s rows.
    Returns {"moves_written": n, "types_kept": [names], "descriptions": {description id: new category}}, the last
    for `description_patch_words`.

    Raises ValueError, before writing anything, if a row's name id has no definition or a row's bytes do not hold
    the `Vanilla*` values its definition lists."""
    written_fields = (CATEGORY_FIELDS if split else ()) + (GEN9_FIELDS if gen9_moves else ())
    by_name_id = {int(d["NameId"]): d for d in definitions if d.get("NameId")}
    end = moves_base + move_count * MOVE_ENTRY_SIZE
    if moves_base < 0 or end > len(rel_bytes):
        raise ValueError(f"the move table ({move_count} rows at {moves_base:#x}) runs past common_rel's end")

    plan: "list[tuple[int, str, int]]" = []   # (absolute offset, format, value)
    moves_written = 0
    types_kept: "list[str]" = []
    descriptions: "dict[int, int]" = {}
    for index in range(move_count):
        row = moves_base + index * MOVE_ENTRY_SIZE
        (name_id,) = struct.unpack_from(">I", rel_bytes, row + NAME_ID_OFFSET)
        if name_id == 0:
            continue          # the unused slots (0 and 355)
        definition = by_name_id.get(name_id)
        if definition is None:
            raise ValueError(f"move {index}'s name id {name_id} is not in move_data.json")
        for suffix, offset, fmt in FIELDS:
            if f"Vanilla{suffix}" not in definition:
                continue      # Generation IX leaves this field alone
            (current,) = struct.unpack_from(fmt, rel_bytes, row + offset)
            vanilla = int(definition[f"Vanilla{suffix}"])
            if current != vanilla:
                raise ValueError(f"move {index} ({definition.get('Name')}) has {suffix} {current}, not the "
                                 f"vanilla {vanilla}")
        def describe(category: int) -> None:
            (description_id,) = struct.unpack_from(">I", rel_bytes, row + DESCRIPTION_ID_OFFSET)
            if description_id and descriptions.get(description_id, category) != category:
                raise ValueError(f"move {index} ({definition.get('Name')}) shares description "
                                 f"{description_id} with a move of another category")
            if description_id:
                descriptions[description_id] = category

        if split and "Gen9Category" not in definition:
            # A Shadow move: its category is already 1 or 2. Only those with a base power are labelled, as the
            # ordinary status moves (category 0) are not.
            (power,) = struct.unpack_from(">h", rel_bytes, row + POWER_OFFSET)
            if rel_bytes[row + CATEGORY_OFFSET] in CATEGORY_NAMES and power > 0:
                describe(rel_bytes[row + CATEGORY_OFFSET])
        changed = False
        for suffix, offset, fmt in written_fields:
            if f"Gen9{suffix}" not in definition:
                continue
            new = int(definition[f"Gen9{suffix}"])
            if suffix == "Type" and new > MAX_XD_TYPE:
                types_kept.append(str(definition.get("Name")))
                continue
            if new != int(definition[f"Vanilla{suffix}"]):
                plan.append((row + offset, fmt, new))
                changed = True
                if suffix == "Category":
                    describe(new)
        moves_written += changed

    for offset, fmt, value in plan:
        struct.pack_into(fmt, rel_bytes, offset, value)
    return {"moves_written": moves_written, "types_kept": types_kept, "descriptions": descriptions}


def description_patch_words(table: bytes, overflow: bytes, descriptions: "dict[int, int]"
                            ) -> "tuple[tuple[int, int, int], ...]":
    """(address, vanilla word, new word) that give each description id in `descriptions` its category's first
    line. `table` is main.dol's `MESSAGE_TABLE_SIZE` bytes at `MESSAGE_TABLE` and `overflow` its
    `DESCRIPTION_OVERFLOW_SIZE` bytes at `DESCRIPTION_OVERFLOW`, both read from the ISO being patched.

    Every string from the first description's to the end of the last one's is rewritten in order -- the strings
    between them too, unchanged -- each placed in that run if it still fits there, else in the overflow, and its pair
    repointed. An entry's bytes run to the next entry's offset, so whatever follows a terminator travels with it.

    Raises ValueError, before anything is planned, unless both spans are vanilla's, every id is in the table on
    an offset of its own, and everything fits."""
    if hashlib.sha1(table).hexdigest() != MESSAGE_TABLE_SHA1:
        raise ValueError("main.dol's message table is not the vanilla GXXE01 table")
    if hashlib.sha1(overflow).hexdigest() != DESCRIPTION_OVERFLOW_SHA1:
        raise ValueError(f"main.dol's strings at 0x{DESCRIPTION_OVERFLOW:08X} are not the vanilla debug strings")
    if not descriptions:
        return ()
    (count,) = struct.unpack_from(">H", table, MESSAGE_COUNT_OFFSET)
    pairs = [struct.unpack_from(">II", table, MESSAGE_PAIRS_OFFSET + i * MESSAGE_PAIR_SIZE) for i in range(count)]
    offset_of = {raw_id & MESSAGE_ID_MASK: offset for raw_id, offset in pairs}
    ids_at: "dict[int, list[int]]" = {}
    for raw_id, offset in pairs:
        ids_at.setdefault(offset, []).append(raw_id & MESSAGE_ID_MASK)
    for description_id in descriptions:
        if description_id not in offset_of:
            raise ValueError(f"description {description_id} is not in main.dol's message table")
        if len(ids_at[offset_of[description_id]]) > 1:
            raise ValueError(f"description {description_id} shares its text with another string")

    offsets = sorted(ids_at)
    end_of = {offset: following for offset, following in zip(offsets, offsets[1:] + [len(table)])}
    run_start = min(offset_of[d] for d in descriptions)
    run_end = max(end_of[offset_of[d]] for d in descriptions)

    new_table, new_overflow = bytearray(table), bytearray(overflow)
    new_table[run_start:run_end] = bytes(run_end - run_start)
    table_at, overflow_at = run_start, 0
    new_offset: "dict[int, int]" = {}
    for offset in (o for o in offsets if run_start <= o < run_end):
        text = table[offset:end_of[offset]]
        category = descriptions.get(ids_at[offset][0])
        if category is not None:
            text = CATEGORY_NAMES[category].encode("utf-16-be") + LINE_BREAK + text
        if table_at + len(text) <= run_end:
            new_table[table_at:table_at + len(text)] = text
            new_offset[offset] = table_at
            table_at += len(text)
        elif overflow_at + len(text) <= len(overflow):
            new_overflow[overflow_at:overflow_at + len(text)] = text
            new_offset[offset] = (DESCRIPTION_OVERFLOW + overflow_at - MESSAGE_TABLE) & 0xFFFFFFFF
            overflow_at += len(text)
        else:
            raise ValueError(f"the move descriptions need more than the {len(overflow):#x}-byte overflow")
    for index, (raw_id, offset) in enumerate(pairs):
        if offset in new_offset:
            struct.pack_into(">I", new_table, MESSAGE_PAIRS_OFFSET + index * MESSAGE_PAIR_SIZE + 4, new_offset[offset])

    words = []
    for address, old, new in ((MESSAGE_TABLE, table, new_table), (DESCRIPTION_OVERFLOW, overflow, new_overflow)):
        for i in range(0, len(old) - len(old) % 4, 4):
            if old[i:i + 4] != new[i:i + 4]:
                words.append((address + i, struct.unpack_from(">I", old, i)[0], struct.unpack_from(">I", new, i)[0]))
    return tuple(words)
