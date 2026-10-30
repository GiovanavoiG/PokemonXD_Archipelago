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

THE DEFINITIONS are `data/move_data.json`'s rows: `NameId`, plus `Vanilla*` and `Gen9*` copies of each field above.
A row is written only when all six of its fields still hold the `Vanilla*` values -- whichever option is on -- so a
build whose table is not vanilla's is refused whole rather than half-converted.

FAIRY. Charm, Sweet Kiss and Moonlight are Fairy in Generation IX, a type XD does not have; their `Gen9Type` is
their vanilla type. A definition naming a type past Dark keeps the vanilla type and is reported.

THE CATEGORY BYTE ALONE DOES NOTHING for an ordinary move. `waza_GetZokuseiKindData` (main.dol 0x8013E7F0) reads
+0x13 only when `wazaCheckDarkWaza` says the move is a Shadow move, and asks the move's TYPE for every other one
(`zokusei::zokuseiBiosGetWazaKind`). So the split also replaces that call, `bl wazaCheckDarkWaza` at 0x8013E820, with
`li r3,1`, along with the same check at the other call sites that pick a category (`SHADOW_CHECK_WORDS`): every move
then takes the +0x13 path (`dol_patch_words`). The Shadow moves already carry 1 or 2 there, so
they are unchanged.

Import-free so the standalone patcher can load it by path.
"""
from __future__ import annotations

import struct

MOVE_ENTRY_SIZE = 0x38
PRIORITY_OFFSET = 0x00
PP_OFFSET = 0x01
TYPE_OFFSET = 0x02
ACCURACY_OFFSET = 0x04
CATEGORY_OFFSET = 0x13
POWER_OFFSET = 0x18
NAME_ID_OFFSET = 0x20

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
    Returns {"moves_written": n, "types_kept": [names]}.

    Raises ValueError, before writing anything, if a row's name id has no definition or a row's bytes do not hold
    its `Vanilla*` values."""
    written_fields = (CATEGORY_FIELDS if split else ()) + (GEN9_FIELDS if gen9_moves else ())
    by_name_id = {int(d["NameId"]): d for d in definitions if d.get("NameId")}
    end = moves_base + move_count * MOVE_ENTRY_SIZE
    if moves_base < 0 or end > len(rel_bytes):
        raise ValueError(f"the move table ({move_count} rows at {moves_base:#x}) runs past common_rel's end")

    plan: "list[tuple[int, str, int]]" = []   # (absolute offset, format, value)
    moves_written = 0
    types_kept: "list[str]" = []
    for index in range(move_count):
        row = moves_base + index * MOVE_ENTRY_SIZE
        (name_id,) = struct.unpack_from(">I", rel_bytes, row + NAME_ID_OFFSET)
        if name_id == 0:
            continue          # the unused slots (0 and 355)
        definition = by_name_id.get(name_id)
        if definition is None:
            raise ValueError(f"move {index}'s name id {name_id} is not in move_data.json")
        for suffix, offset, fmt in FIELDS:
            (current,) = struct.unpack_from(fmt, rel_bytes, row + offset)
            vanilla = int(definition[f"Vanilla{suffix}"])
            if current != vanilla:
                raise ValueError(f"move {index} ({definition.get('Name')}) has {suffix} {current}, not the "
                                 f"vanilla {vanilla}")
        changed = False
        for suffix, offset, fmt in written_fields:
            new = int(definition[f"Gen9{suffix}"])
            if suffix == "Type" and new > MAX_XD_TYPE:
                types_kept.append(str(definition.get("Name")))
                continue
            if new != int(definition[f"Vanilla{suffix}"]):
                plan.append((row + offset, fmt, new))
                changed = True
        moves_written += changed

    for offset, fmt, value in plan:
        struct.pack_into(fmt, rel_bytes, offset, value)
    return {"moves_written": moves_written, "types_kept": types_kept}
