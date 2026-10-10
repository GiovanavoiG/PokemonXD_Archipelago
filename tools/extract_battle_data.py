"""ADDENDUM 461 -- writes `data/battle_data.json`, the battle-relevant columns of XD's species and move tables.

Read out of a real `common_rel` (the 704,448-byte `bridge/dumps/a263_commonrel.bin`), at the offsets the rest of
the project already measured: the species stats table at 0x29DA8 (ADDENDUM 285, `species_stats`), 0x124 bytes per
entry, and the move table at 0xA2710 (ADDENDUM 291), 0x38 bytes per entry. Field offsets are GoD-Tool's, each
pinned to the game's own accessor (`pokemonDataBiosGetZokuseiDataId` = +0x30, `...GetTokuseiDataId` = +0x32,
`wazaDataBios*`), and spot-checked against Generation III: Gastly Ghost/Poison + Levitate, Shedinja Wonder Guard,
Chinchou Volt Absorb, Lapras Water Absorb, Tackle 35 power 95 accuracy, Explosion 250, Counter priority -5.

    species  {internal index: [type1, type2, ability1, ability2, hp, atk, def, spatk, spdef, speed, weight_hg]}
    moves    {move id: [type, power, accuracy, effect, effect_chance, priority, contact, sound, pp]}

Types use XD's own numbering (Normal 0 ... Steel 8, ??? 9, Fire 10 ... Dark 17); abilities and effects use
Generation III's (pokeemerald's ABILITY_* and EFFECT_*), which XD shares.

    python3 -m pokemon_xd.tools.extract_battle_data <common_rel dump> <out.json>
"""
from __future__ import annotations

import json
import struct
import sys

SPECIES_BASE = 0x29DA8
SPECIES_SIZE = 0x124
SPECIES_COUNT = 415
MOVES_BASE = 0xA2710
MOVE_SIZE = 0x38
MOVE_COUNT = 355          # 0..354; the Shadow moves past 355 never reach a starter or an ordinary trainer


def extract(data: bytes) -> dict:
    species = {}
    for index in range(1, SPECIES_COUNT):
        entry = data[SPECIES_BASE + index * SPECIES_SIZE:SPECIES_BASE + (index + 1) * SPECIES_SIZE]
        stats = [entry[0x8F + 2 * k] for k in range(6)]
        if not any(stats):
            continue
        weight = struct.unpack(">H", entry[0x0A:0x0C])[0]
        species[str(index)] = [entry[0x30], entry[0x31], entry[0x32], entry[0x33], *stats, weight]
    moves = {}
    for index in range(1, MOVE_COUNT):
        e = data[MOVES_BASE + index * MOVE_SIZE:MOVES_BASE + (index + 1) * MOVE_SIZE]
        moves[str(index)] = [e[0x02], e[0x19], e[0x04], e[0x1D], e[0x05], struct.unpack("b", e[0:1])[0],
                             e[0x06], e[0x10], e[0x01]]
    return {"species": species, "moves": moves}


def main(argv: "list[str]") -> int:
    with open(argv[1], "rb") as handle:
        out = extract(handle.read())
    assert out["moves"]["33"][:3] == [0, 35, 95], "not the move table: Tackle is Normal, 35 power, 95 accuracy"
    assert out["species"]["92"][:4] == [7, 3, 26, 0], "not the species table: Gastly is Ghost/Poison, Levitate"
    with open(argv[2], "w") as handle:
        json.dump(out, handle, separators=(",", ":"), sort_keys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
