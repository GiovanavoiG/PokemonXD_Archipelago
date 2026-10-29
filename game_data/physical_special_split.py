"""Physical/Special Split -- each move takes its Generation IX priority, PP, accuracy, type, category and power.

THE TABLE is common_rel's move table (inside `common.fsys`): pointer index 124, 0x38 bytes per move
(`xd_rel_format.MOVE_ENTRY_SIZE`). The fields this writes, by their `waza::wazaDataBios*` accessors in main.dol:

    +0x00  s8   priority        (`wazaDB_GetPri`)
    +0x01  u8   PP
    +0x02  u8   type            (`zz_move_get_type`)
    +0x04  u8   accuracy, 0 = never misses
    +0x13  u8   category, 0 = the type decides, 1 = physical, 2 = special (`waza_GetZokuseiKindData`)
    +0x18  s16  base power      (`wazaDataBiosGetIryoku`; `xd_rel_format.MOVE_BASE_POWER_OFFSET` is its low byte)
    +0x20  u32  name id         (`zz_move_data_get_name_id`) -- the key into the definitions

THE DEFINITIONS are `data/move_data.json`'s rows: `NameId`, plus `Vanilla*` and `Gen9*` copies of each field above.
A row is written only when every one of its six bytes still holds the `Vanilla*` value, so a build whose table is
not vanilla's is refused whole rather than half-converted.

FAIRY. Charm, Sweet Kiss and Moonlight are Fairy in Generation IX (`Gen9Type` 18), a type XD does not have. They
keep their vanilla type; everything else about them is still written.

THE CATEGORY BYTE ALONE DOES NOTHING for an ordinary move. `waza_GetZokuseiKindData` reads +0x13 only for a Shadow
move and asks the move's TYPE for every other one (`zokusei::zokuseiBiosGetWazaKind`), so the split needs that
main.dol branch changed too. That half is not here.

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

#: XD's last type index (17, Dark). A Generation IX type past it (Fairy, 18) is not written.
MAX_XD_TYPE = 17

#: (definition suffix, offset, struct format) for each field written.
FIELDS: "tuple[tuple[str, int, str], ...]" = (
    ("Priority", PRIORITY_OFFSET, ">b"),
    ("Pp", PP_OFFSET, ">B"),
    ("Accuracy", ACCURACY_OFFSET, ">B"),
    ("Type", TYPE_OFFSET, ">B"),
    ("Category", CATEGORY_OFFSET, ">B"),
    ("Power", POWER_OFFSET, ">h"),
)


def apply_physical_special_split(rel_bytes: bytearray, moves_base: int, move_count: int,
                                 definitions: "list[dict]") -> "dict[str, object]":
    """Write each move's Generation IX values into the move table in `rel_bytes` (common_rel, decompressed), in
    place. `moves_base` is the table's offset in `rel_bytes`, `move_count` its row count, and `definitions`
    `move_data.json`'s rows. Returns {"moves_written": n, "types_kept": [names]}.

    Raises ValueError, before writing anything, if a row's name id has no definition or a row's bytes do not hold
    its `Vanilla*` values."""
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
        changed = False
        for suffix, offset, fmt in FIELDS:
            (current,) = struct.unpack_from(fmt, rel_bytes, row + offset)
            vanilla = int(definition[f"Vanilla{suffix}"])
            if current != vanilla:
                raise ValueError(f"move {index} ({definition.get('Name')}) has {suffix} {current}, not the "
                                 f"vanilla {vanilla}")
            new = int(definition[f"Gen9{suffix}"])
            if suffix == "Type" and new > MAX_XD_TYPE:
                types_kept.append(str(definition.get("Name")))
                continue
            if new != current:
                plan.append((row + offset, fmt, new))
                changed = True
        moves_written += changed

    for offset, fmt, value in plan:
        struct.pack_into(fmt, rel_bytes, offset, value)
    return {"moves_written": moves_written, "types_kept": types_kept}
