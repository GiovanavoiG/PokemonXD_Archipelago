"""Wonder trades: one shared pool per team in the server's data storage, which Pokemon Emerald and Pokemon Crystal
use too, so a Pokemon sent from any of them can arrive in any other.

This module is the pure half: the pool's wire format, and the conversion between it and XD's 0xC4 Pokemon record.
It reads no memory and sends nothing; `wonder_trade_client.py` does both.

The pool key is `pokemon_wonder_trades_{team}`. Its value is a dict: `_lock` (0, or the ms time a client took it)
and any number of `"<n>": [sender, payload]` entries, the payload a JSON string. Sender is the AP slot number.

Payload fields (all games): version "1", language, nickname, personality, species (National Dex), experience
(total), ability (0/1), ivs and evs ([HP, Atk, Def, Spe, SpA, SpD]), conditions ([Cool, Beauty, Cute, Smart, Tough,
Sheen]), pokerus (strain << 4 | days), location_met, level_met, game (1 S, 2 R, 3 E, 4 FR, 5 LG, 15 Colosseum/XD),
ball, moves (4 x [id, pp, pp ups]), trainer {name, id (SID << 16 | TID), female}, and item (a modern held-item id,
left out when there is none).

Crystal's client writes Generation III held-item ids instead of modern ones; its payloads are recognised by the
shape its sender gives them (see `looks_like_crystal`) and their item read that way.

XD record offsets are big-endian throughout. The species field is the game's master internal index."""
from __future__ import annotations

import json
import struct
from typing import Any, Callable, Optional

from . import wonder_trade_tables as tables

POOL_KEY_TEMPLATE = "pokemon_wonder_trades_{team}"
LOCK_KEY = "_lock"
LOCK_TTL_MS = 5000
BASE_COOLDOWN_MS = 5000
MAX_COOLDOWN_MS = 60000
REPLY_TIMEOUT_S = 5.0
PAYLOAD_VERSION = "1"

MAX_DEX = 386
MAX_MOVE = 354                 # Psycho Boost; XD's Shadow moves (355 up) exist nowhere else
MAX_LEVEL = 100
MAX_U32 = 0xFFFFFFFF
METLOC_IN_GAME_TRADE = 254     # Generation III's "obtained in a trade" met location
GAME_COLOSSEUM_XD = 15

# Held items this apworld gives another meaning: the shop and chest berries stand for checks (148-175, Enigma among
# them), Yellow Shard is the Candy Box and Green Shard the Ability Patch. Never sent, and dropped from what arrives.
RESERVED_ITEMS: "frozenset[int]" = frozenset({50, 51}) | frozenset(range(148, 176))

LANGUAGES = ("Japanese", "English", "French", "Italian", "German", "Spanish")
GC_LANGUAGE_TO_NAME = {1: "Japanese", 2: "English", 3: "German", 4: "French", 5: "Italian", 6: "Spanish"}
NAME_TO_GC_LANGUAGE = {v: k for k, v in GC_LANGUAGE_TO_NAME.items()}
GC_VERSION_TO_GAME = {1: 4, 2: 5, 8: 1, 9: 2, 10: 3, 11: GAME_COLOSSEUM_XD}
GAME_TO_GC_VERSION = {v: k for k, v in GC_VERSION_TO_GAME.items()}
GC_VERSION_UNKNOWN_ORIGIN = 10        # Emerald: what XD shows for a Pokemon from a game it does not know

# Record layout (0xC4).
RECORD_SIZE = 0xC4
OFF_SPECIES = 0x00
OFF_ITEM = 0x02
OFF_HP = 0x04
OFF_FRIENDSHIP = 0x06
OFF_MET_LOCATION = 0x08
OFF_MET_LEVEL = 0x0E
OFF_BALL = 0x0F
OFF_OT_GENDER = 0x10
OFF_LEVEL = 0x11
OFF_SHEEN = 0x12
OFF_POKERUS_STRAIN = 0x13
OFF_MARKINGS = 0x14
OFF_POKERUS_DAYS = 0x15
OFF_STATUS = 0x16              # 0x16-0x1A, battle status
OFF_FLAGS = 0x1D
OFF_EXP = 0x20
OFF_TRAINER_ID = 0x24          # u32: SID << 16 | TID
OFF_PID = 0x28
OFF_VERSION = 0x34
OFF_LANGUAGE = 0x37
OFF_OT_NAME = 0x38
OFF_NICKNAME_DISPLAY = 0x4E
OFF_NICKNAME = 0x64
NAME_BYTES = 22                # 10 characters and a terminator, UTF-16
NAME_CHARS = 10
OFF_RIBBONS = 0x7C
OFF_MOVES = 0x80
OFF_STATS = 0x90               # max HP, Atk, Def, SpA, SpD, Spe
OFF_EVS = 0x9C                 # u16 each, HP, Atk, Def, SpA, SpD, Spe
OFF_IVS = 0xA8                 # u8 each, same order
OFF_CONTEST = 0xAE             # Cool, Beauty, Cute, Smart, Tough
OFF_RIBBON_COUNTS = 0xB3       # 0xB3-0xB7
OFF_SHADOW_ID = 0xBA

FLAG_EGG = 0x80
FLAG_ABILITY = 0x40
FLAG_INVALID = 0x20

# XD keeps HP, Atk, Def, SpA, SpD, Spe; the pool HP, Atk, Def, Spe, SpA, SpD.
_POOL_FROM_XD = (0, 1, 2, 5, 3, 4)
_XD_FROM_POOL = (0, 1, 2, 4, 5, 3)

_DEX_TO_INTERNAL = {row[0]: index for index, row in tables.SPECIES.items()}


class TradeError(ValueError):
    """A Pokemon that cannot be sent, or a payload that cannot be taken."""


def pool_key(team: int) -> str:
    return POOL_KEY_TEMPLATE.format(team=int(team or 0))


# ---------------------------------------------------------------------------------------------------------------
# Experience. The pool carries total experience on the species' vanilla curve; a seed's Experience Rate can move a
# species to a faster one, so the client converts in both directions and keeps the progress into the level.

def exp_total(curve: int, level: int) -> int:
    from .species_stats import exp_total_at_level
    return exp_total_at_level(curve, max(1, min(MAX_LEVEL, level)))


def level_for_exp(curve: int, experience: int) -> int:
    from .species_stats import level_at_exp
    return level_at_exp(curve, max(0, experience))


def convert_exp(experience: int, from_curve: int, to_curve: int, level: "int | None" = None) -> "tuple[int, int]":
    """(experience on `to_curve`, level): the same level, and the same fraction of the way to the next one."""
    if level is None:
        level = level_for_exp(from_curve, experience)
    level = max(1, min(MAX_LEVEL, int(level)))
    if level >= MAX_LEVEL:
        return exp_total(to_curve, MAX_LEVEL), MAX_LEVEL
    lo, hi = exp_total(from_curve, level), exp_total(from_curve, level + 1)
    fraction = 0.0 if hi <= lo else min(max((experience - lo) / (hi - lo), 0.0), 0.999)
    to_lo, to_hi = exp_total(to_curve, level), exp_total(to_curve, level + 1)
    return to_lo + int(fraction * (to_hi - to_lo)), level


# ---------------------------------------------------------------------------------------------------------------
# Stats (the Generation III formulas).

def nature_multipliers(pid: int) -> "tuple[int, int, int, int, int]":
    """Atk, Def, Spe, SpA, SpD multipliers in percent for PID % 25."""
    nature = pid % 25
    up, down = nature // 5, nature % 5
    out = [100] * 5
    if up != down:
        out[up] = 110
        out[down] = 90
    return tuple(out)  # type: ignore[return-value]


def compute_stats(dex: int, base: "tuple[int, ...]", ivs_xd: "list[int]", evs_xd: "list[int]", level: int,
                  pid: int) -> "list[int]":
    """Max HP, Atk, Def, SpA, SpD, Spe, in XD's order. `base`, `ivs_xd`, `evs_xd` are in XD's order too."""
    hp = 1 if dex == 292 else (2 * base[0] + ivs_xd[0] + evs_xd[0] // 4) * level // 100 + level + 10
    mult = nature_multipliers(pid)           # Atk, Def, Spe, SpA, SpD
    by_xd = {1: mult[0], 2: mult[1], 3: mult[3], 4: mult[4], 5: mult[2]}
    out = [hp]
    for k in range(1, 6):
        raw = (2 * base[k] + ivs_xd[k] + evs_xd[k] // 4) * level // 100 + 5
        out.append(raw * by_xd[k] // 100)
    return out


# ---------------------------------------------------------------------------------------------------------------
# Names.

def decode_name(raw: bytes) -> str:
    chars = []
    for i in range(0, len(raw) - 1, 2):
        code = struct.unpack_from(">H", raw, i)[0]
        if code == 0:
            break
        chars.append(chr(code))
    return "".join(chars)


def _renderable(ch: str) -> bool:
    code = ord(ch)
    return (0x20 <= code < 0x7F) or (0xA0 <= code <= 0xFF) or ch in "♂♀…"


def encode_name(text: str) -> bytes:
    """UTF-16BE, at most 10 characters, terminated and padded to 22 bytes. Anything XD cannot draw becomes '?'."""
    clean = "".join(ch if _renderable(ch) else "?" for ch in str(text))[:NAME_CHARS]
    return clean.encode("utf-16-be").ljust(NAME_BYTES, b"\x00")


def species_name(dex: int) -> str:
    from ..tools import xd_species_index
    index = _DEX_TO_INTERNAL.get(int(dex))
    return (xd_species_index.name_for(index) if index is not None else None) or "POKEMON"


# ---------------------------------------------------------------------------------------------------------------
# Sending: an XD record to a payload.

def is_shadow(record: bytes) -> bool:
    return struct.unpack_from(">H", record, OFF_SHADOW_ID)[0] != 0


def record_to_payload(record: bytes, seed_curve: "int | None" = None) -> "dict[str, Any]":
    """The pool payload for one XD record. Raises TradeError for anything that cannot go: an empty slot, an egg, a
    species no other game has, or a Pokemon left with no move another game knows. Shadow status is the caller's to
    judge (the record alone cannot tell a purified Shadow from one that is not)."""
    if len(record) < RECORD_SIZE:
        raise TradeError("that slot did not read")
    internal = struct.unpack_from(">H", record, OFF_SPECIES)[0]
    if internal == 0:
        raise TradeError("that slot is empty")
    row = tables.SPECIES.get(internal)
    if row is None:
        raise TradeError("that species only exists in XD")
    dex, vanilla_curve = row[0], row[1]
    flags = record[OFF_FLAGS]
    if flags & FLAG_EGG:
        raise TradeError("eggs can't be traded")
    if flags & FLAG_INVALID:
        raise TradeError("that record is marked invalid")

    moves = []
    for i in range(4):
        move, pp, ups = struct.unpack_from(">HBB", record, OFF_MOVES + 4 * i)
        if 1 <= move <= MAX_MOVE:
            moves.append([move, min(pp, 0xFF), min(ups, 3)])
    if not moves:
        raise TradeError("it knows no move outside XD (Shadow moves can't be traded)")
    while len(moves) < 4:
        moves.append([0, 0, 0])

    level = max(1, min(MAX_LEVEL, record[OFF_LEVEL]))
    experience = struct.unpack_from(">I", record, OFF_EXP)[0]
    curve = vanilla_curve if seed_curve is None else seed_curve
    experience, _level = convert_exp(experience, curve, vanilla_curve, level)

    ivs_xd = [min(record[OFF_IVS + k], 31) for k in range(6)]
    evs_xd = [min(struct.unpack_from(">H", record, OFF_EVS + 2 * k)[0], 0xFF) for k in range(6)]
    days = record[OFF_POKERUS_DAYS]
    pokerus = ((record[OFF_POKERUS_STRAIN] & 0xF) << 4) | (0 if days == 0xFF else days & 0xF)

    nickname = decode_name(record[OFF_NICKNAME:OFF_NICKNAME + NAME_BYTES]).strip() or species_name(dex)
    ot_name = decode_name(record[OFF_OT_NAME:OFF_OT_NAME + NAME_BYTES]).strip() or "XD"
    ball = record[OFF_BALL]
    payload: "dict[str, Any]" = {
        "version": PAYLOAD_VERSION,
        "language": GC_LANGUAGE_TO_NAME.get(record[OFF_LANGUAGE], "English"),
        "nickname": nickname[:NAME_CHARS],
        "personality": struct.unpack_from(">I", record, OFF_PID)[0],
        "species": dex,
        "experience": experience,
        "ability": 1 if flags & FLAG_ABILITY else 0,
        "ivs": [ivs_xd[k] for k in _POOL_FROM_XD],
        "evs": [evs_xd[k] for k in _POOL_FROM_XD],
        "conditions": [min(record[OFF_CONTEST + k], 0xFF) for k in range(5)] + [record[OFF_SHEEN]],
        "pokerus": pokerus,
        "location_met": METLOC_IN_GAME_TRADE,
        "level_met": max(1, min(MAX_LEVEL, record[OFF_MET_LEVEL] or level)),
        "game": GC_VERSION_TO_GAME.get(record[OFF_VERSION], GAME_COLOSSEUM_XD),
        "ball": ball if 1 <= ball <= 12 else 4,
        "moves": moves,
        "trainer": {
            "name": ot_name[:NAME_CHARS],
            "id": struct.unpack_from(">I", record, OFF_TRAINER_ID)[0],
            "female": record[OFF_OT_GENDER] == 1,
        },
    }
    item = struct.unpack_from(">H", record, OFF_ITEM)[0]
    if item and item not in RESERVED_ITEMS and item in tables.GEN3_TO_MODERN_ITEM:
        payload["item"] = tables.GEN3_TO_MODERN_ITEM[item]
    check_payload_shape(payload)
    return payload


def dump_payload(payload: "dict[str, Any]") -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def check_payload_shape(payload: "dict[str, Any]") -> None:
    """Everything the other games' readers index or pack without checking. Raises TradeError on the first problem:
    a malformed entry in the pool stops other games' clients from reading it at all."""
    def u(value, hi, what):
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= hi:
            raise TradeError(f"{what} out of range: {value!r}")

    for key in ("version", "language", "nickname", "personality", "species", "experience", "ivs", "evs", "moves",
                "trainer"):
        if key not in payload:
            raise TradeError(f"missing {key}")
    if payload["version"] != PAYLOAD_VERSION or payload["language"] not in LANGUAGES:
        raise TradeError("bad version or language")
    if not isinstance(payload["nickname"], str) or not payload["nickname"]:
        raise TradeError("empty nickname")
    u(payload["personality"], MAX_U32, "personality")
    if not isinstance(payload["species"], int) or not 1 <= payload["species"] <= MAX_DEX:
        raise TradeError("species")
    u(payload["experience"], MAX_U32, "experience")
    u(payload.get("ability", 0), 1, "ability")
    for key, hi in (("ivs", 31), ("evs", 0xFF), ("conditions", 0xFF)):
        values = payload.get(key, [0] * 6)
        if not isinstance(values, list) or len(values) != 6:
            raise TradeError(key)
        for v in values:
            u(v, hi, key)
    u(payload.get("pokerus", 0), 0xFF, "pokerus")
    u(payload.get("location_met", 0), 0xFF, "location_met")
    u(payload.get("level_met", 1), MAX_LEVEL, "level_met")
    u(payload.get("game", 0), 15, "game")
    u(payload.get("ball", 4), 12, "ball")
    moves = payload["moves"]
    if not isinstance(moves, list) or len(moves) != 4:
        raise TradeError("moves")
    for move in moves:
        if not isinstance(move, list) or len(move) != 3:
            raise TradeError("moves")
        u(move[0], MAX_MOVE, "move")
        u(move[1], 0xFF, "pp")
        u(move[2], 3, "pp ups")
    trainer = payload["trainer"]
    if not isinstance(trainer, dict) or not isinstance(trainer.get("name"), str) or not trainer.get("name"):
        raise TradeError("trainer")
    u(trainer.get("id"), MAX_U32, "trainer id")
    if "item" in payload:
        u(payload["item"], 0xFFFF, "item")


# ---------------------------------------------------------------------------------------------------------------
# Receiving: a pool entry to an XD record.

def _int(value, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return default


def looks_like_crystal(payload: "dict[str, Any]") -> bool:
    """Crystal's sender builds the personality from its trainer id, DVs and species, and fixes game 0, location 254
    and ball 4. Nothing else produces all of those at once."""
    try:
        species = _int(payload.get("species"))
        personality = _int(payload.get("personality"))
        trainer_id = _int((payload.get("trainer") or {}).get("id"))
        return (1 <= species <= 251 and _int(payload.get("game"), -1) == 0
                and _int(payload.get("location_met"), -1) == METLOC_IN_GAME_TRADE
                and _int(payload.get("ball"), -1) == 4 and 0 <= trainer_id <= 0xFFFF
                and (personality & 0xFF) == species and (personality >> 24) == (trainer_id >> 8) & 0xFF)
    except Exception:
        return False


def received_item(payload: "dict[str, Any]") -> int:
    """The Generation III (XD) held-item id for what arrived, 0 for none or one this seed must not hand out."""
    raw = _int(payload.get("item"), 0)
    if raw <= 0:
        return 0
    item = raw if looks_like_crystal(payload) else tables.MODERN_TO_GEN3_ITEM.get(raw, 0)
    if item not in tables.GEN3_TO_MODERN_ITEM or item in RESERVED_ITEMS:
        return 0
    return item


def parse_entry(entry: Any) -> "tuple[Any, dict[str, Any]] | None":
    """(sender, payload) for a pool entry XD can take, else None. Never raises."""
    try:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2 or not isinstance(entry[1], str):
            return None
        payload = json.loads(entry[1])
        if not isinstance(payload, dict):
            return None
        species = payload.get("species")
        if not isinstance(species, int) or isinstance(species, bool) or not 1 <= species <= MAX_DEX:
            return None
        if species not in _DEX_TO_INTERNAL:
            return None
        if not any(isinstance(m, (list, tuple)) and m and isinstance(m[0], int) and 1 <= m[0] <= MAX_MOVE
                   for m in (payload.get("moves") or [])):
            return None
        payload_to_record(payload, template=None, seed_curve=None, max_pp=None)   # it converts
        return entry[0], payload
    except Exception:
        return None


def payload_to_record(payload: "dict[str, Any]", template: "bytes | None", seed_curve: "int | None",
                      max_pp: "Optional[Callable[[int, int], Optional[int]]]") -> bytes:
    """The XD record for a payload. `template` is one of the player's own records, for the bytes nobody has named;
    `seed_curve` the species' growth group in this seed (None: vanilla); `max_pp(move, pp ups)` the full PP from the
    live move table (None: keep the PP that arrived, capped at 64). Raises TradeError."""
    dex = _int(payload.get("species"))
    internal = _DEX_TO_INTERNAL.get(dex)
    if internal is None:
        raise TradeError("species")
    row = tables.SPECIES[internal]
    vanilla_curve, base_friendship, base_stats, abilities = row[1], row[2], row[3], row[4]

    moves = []
    for entry in payload.get("moves") or []:
        if not isinstance(entry, (list, tuple)) or not entry:
            continue
        move = _int(entry[0])
        if not 1 <= move <= MAX_MOVE:
            continue
        ups = max(0, min(3, _int(entry[2]) if len(entry) > 2 else 0))
        pp = max(0, _int(entry[1]) if len(entry) > 1 else 0)
        full = max_pp(move, ups) if max_pp else None
        pp = min(pp, full) if full is not None else min(pp, 64)
        moves.append((move, pp, ups))
        if len(moves) == 4:
            break
    if not moves:
        raise TradeError("no move XD knows")

    experience = max(0, min(MAX_U32, _int(payload.get("experience"))))
    level = level_for_exp(vanilla_curve, experience)
    experience, level = convert_exp(experience, vanilla_curve,
                                    vanilla_curve if seed_curve is None else seed_curve, level)

    def six(key, hi):
        values = payload.get(key) or []
        values = [max(0, min(hi, _int(v))) for v in list(values)[:6]]
        return values + [0] * (6 - len(values))

    ivs_pool, evs_pool = six("ivs", 31), six("evs", 0xFF)
    ivs_xd = [ivs_pool[k] for k in _XD_FROM_POOL]
    evs_xd = [evs_pool[k] for k in _XD_FROM_POOL]
    conditions = six("conditions", 0xFF)
    pid = _int(payload.get("personality")) & MAX_U32
    trainer = payload.get("trainer") if isinstance(payload.get("trainer"), dict) else {}
    stats = compute_stats(dex, base_stats, ivs_xd, evs_xd, level, pid)

    out = bytearray(template[:RECORD_SIZE]) if template and len(template) >= RECORD_SIZE else bytearray(RECORD_SIZE)
    struct.pack_into(">H", out, OFF_SPECIES, internal)
    struct.pack_into(">H", out, OFF_ITEM, received_item(payload))
    struct.pack_into(">H", out, OFF_HP, stats[0])
    struct.pack_into(">H", out, OFF_FRIENDSHIP, base_friendship)
    struct.pack_into(">H", out, OFF_MET_LOCATION, 0)
    met_level = _int(payload.get("level_met"), level)
    out[OFF_MET_LEVEL] = max(1, min(MAX_LEVEL, met_level or level))
    ball = _int(payload.get("ball"), 4)
    out[OFF_BALL] = ball if 1 <= ball <= 12 else 4
    out[OFF_OT_GENDER] = 1 if trainer.get("female") else 0
    out[OFF_LEVEL] = level
    out[OFF_SHEEN] = conditions[5]
    pokerus = max(0, min(0xFF, _int(payload.get("pokerus"))))
    out[OFF_POKERUS_STRAIN] = (pokerus >> 4) & 0xF
    out[OFF_MARKINGS] = 0
    out[OFF_POKERUS_DAYS] = (pokerus & 0xF) if pokerus else 0xFF
    out[OFF_STATUS:OFF_STATUS + 5] = b"\x00" * 5
    ability = 1 if _int(payload.get("ability")) == 1 and abilities[1] else 0
    out[OFF_FLAGS] = (out[OFF_FLAGS] & 0x1F & ~FLAG_INVALID) | (FLAG_ABILITY if ability else 0)
    struct.pack_into(">I", out, OFF_EXP, experience)
    struct.pack_into(">I", out, OFF_TRAINER_ID, _int(trainer.get("id")) & MAX_U32)
    struct.pack_into(">I", out, OFF_PID, pid)
    out[OFF_VERSION] = GAME_TO_GC_VERSION.get(_int(payload.get("game"), 0), GC_VERSION_UNKNOWN_ORIGIN)
    language = payload.get("language")
    out[OFF_LANGUAGE] = NAME_TO_GC_LANGUAGE.get(language if isinstance(language, str) else "", 2)
    out[OFF_OT_NAME:OFF_OT_NAME + NAME_BYTES] = encode_name(trainer.get("name") or "AP")
    nickname = payload.get("nickname") if isinstance(payload.get("nickname"), str) else ""
    name = encode_name(nickname.strip() or species_name(dex))
    out[OFF_NICKNAME_DISPLAY:OFF_NICKNAME_DISPLAY + NAME_BYTES] = name
    out[OFF_NICKNAME:OFF_NICKNAME + NAME_BYTES] = name
    struct.pack_into(">H", out, OFF_RIBBONS, 0)
    for i in range(4):
        move, pp, ups = moves[i] if i < len(moves) else (0, 0, 0)
        struct.pack_into(">HBB", out, OFF_MOVES + 4 * i, move, pp, ups)
    for k in range(6):
        struct.pack_into(">H", out, OFF_STATS + 2 * k, stats[k])
        struct.pack_into(">H", out, OFF_EVS + 2 * k, evs_xd[k])
        out[OFF_IVS + k] = ivs_xd[k]
    for k in range(5):
        out[OFF_CONTEST + k] = conditions[k]
    out[OFF_RIBBON_COUNTS:OFF_RIBBON_COUNTS + 5] = b"\x00" * 5
    struct.pack_into(">H", out, OFF_SHADOW_ID - 2, 0)
    struct.pack_into(">H", out, OFF_SHADOW_ID, 0)
    return bytes(out)


def describe_payload(payload: "dict[str, Any]") -> str:
    """'NICKNAME (Species, Lv N) from OT' for the log."""
    dex = _int(payload.get("species"))
    row = tables.SPECIES.get(_DEX_TO_INTERNAL.get(dex, -1))
    level = level_for_exp(row[1], _int(payload.get("experience"))) if row else "?"
    kind = species_name(dex).title()
    nickname = str(payload.get("nickname") or kind)
    trainer = payload.get("trainer") if isinstance(payload.get("trainer"), dict) else {}
    head = kind if nickname.upper() == kind.upper() else f"{nickname} ({kind})"
    return f"{head}, Lv {level}, from {trainer.get('name') or 'someone'}"


# ---------------------------------------------------------------------------------------------------------------
# The pool.

def candidate_keys(value: Any, own_slot: int, own_blob: "str | None") -> "list[str]":
    """Pool keys XD could take: not its own sender, not its own deposit, and a payload that converts."""
    if not isinstance(value, dict):
        return []
    out = []
    for key, entry in value.items():
        if key == LOCK_KEY:
            continue
        if isinstance(entry, (list, tuple)) and len(entry) >= 2:
            if entry[0] == own_slot or (own_blob is not None and entry[1] == own_blob):
                continue
        if parse_entry(entry) is not None:
            out.append(key)
    return out


def free_key(value: Any) -> str:
    """The lowest unused integer key."""
    taken = set(value) if isinstance(value, dict) else set()
    n = 0
    while str(n) in taken:
        n += 1
    return str(n)


def lock_was_free(lock: int, reply: "dict[str, Any]") -> bool:
    """A lock attempt took the key only if the value it replaced was unlocked or expired, and it is still ours."""
    value = reply.get("value") if isinstance(reply.get("value"), dict) else {}
    original = reply.get("original_value") if isinstance(reply.get("original_value"), dict) else {}
    return value.get(LOCK_KEY) == lock and lock - _int(original.get(LOCK_KEY), 0) >= LOCK_TTL_MS
