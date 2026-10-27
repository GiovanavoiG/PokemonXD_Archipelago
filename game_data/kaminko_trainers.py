"""Missable trainers, and a Miror B., standing outside Kaminko's House.

MIROR B. (every seed). One more NPC, beside the arrival point, with Miror B.'s own model (copied into the room's
archive from the Outskirt Stand's). Talked to while his queue holds a Shadow, he asks and then starts battle 423 --
the battle every Poke Spot starts, whose type (16) has the engine build his team from the Shadows that fled. So it
is the same fight anywhere: a Shadow snagged here is snagged everywhere and leaves his queue, and one beaten without
a snag stays in it. The client sets one global while the player is here, 1 when the queue holds a Shadow, 0 when it
does not; at 0 he says so and does not fight. Logic counts on him: a Shadow knocked out is never lost, because his
copy is at Kaminko's House from the start.

THE TRAINERS (Kaminko Missable Trainers).

Twelve extra NPCs are added to the manor's exterior (map S3_out), lined up along the drive from Chobin's battle
spot towards the entrance. Each is a slot, not a fixed trainer: the client fills the slots from the missable
trainers the player has missed -- their area's story is past them -- and not yet beaten, by writing each slot's battle
and opening line into the floor script's globals once the floor has loaded. A slot with no trainer is never shown. A
slot whose battle is won clears its battle global and hides itself, and the next visit fills it with someone else.

Three files in S3_out.fsys change, each rebuilt rather than patched in place, because each grows, and one is added
(Miror B.'s model):
  * the floor module (REL): the NPC table is copied to the end of its data section with twelve records added, its
    count bumped, and the three relocations that point at it repointed;
  * the floor script (TCOD): twelve talk functions (one per slot) plus Miror B.'s and the per-frame show function,
    50 integer globals (battle, line and model per slot, an epoch the client uses to tell a fresh load from a won
    battle, Miror B.'s flag and each slot's shown state) and the added character references;
  * the floor's message file: three lines per trainer -- who they are and where they're from with a yes/no
    question, their battle line (their own, copied from their room, where they have one), and a line for "no".

Nothing here writes the story value. Logic is unchanged: these are extra places to fight trainers whose checks
already exist.
"""
from __future__ import annotations

import math
import struct

# ----------------------------------------------------------------------------------------------------------------
# The trainers. (trainer index, battle id, (room, message id) of the line they open with, or None.)
# Missable trainers, minus the three who always battle now (Aferd, Laken, Hebon), Finol and Eroll (their first
# fights can't be walked past) and the two whose "fights" are between NPCs (Zook #1 vs Ardos, Biden #2 vs Zook).
KAMINKO_TRAINERS: "tuple[tuple[int, int, tuple[str, int] | None], ...]" = (
    (39, 320, ("M1_out", 36159)),            # Resix #2 (their Phenac team)
    (40, 321, ("M1_out", 36164)),            # Blusix #2
    (41, 322, ("M1_houseA_1F", 36180)),      # Browsix #2
    (42, 323, ("M1_houseA_1F", 36174)),      # Yellosix #2
    (43, 324, ("M1_out", 36185)),            # Purpsix #2
    (44, 325, ("M1_out", 36190)),            # Greesix #2
    (51, 258, ("D1_labo_B1", 30068)),        # Digor
    (53, 260, ("D1_labo_B3", 30092)),        # Morbit
    (54, 261, ("D1_labo_B3", 30091)),        # Meda
    (55, 262, ("D1_labo_B3", 30096)),        # Elrok
    (56, 263, ("D1_labo_B3", 30099)),        # Coffy
    (58, 265, ("D1_labo_B1", 30067)),        # Nopia
    (74, 280, None),                         # Mocor
    (76, 282, ("M2_building_2F", 37170)),    # Elox
    (77, 283, ("M2_building_2F", 37176)),    # Rixor
    (79, 285, None),                         # Dilly
    (85, 287, None),                         # Edlos
    (91, 293, ("M1_out", 36053)),            # Pellim
    (92, 294, ("M1_out", 36057)),            # Fenton
    (93, 295, ("M1_out", 36062)),            # Forgs
    (94, 296, ("M1_out", 36066)),            # Kapen
    (95, 297, ("M1_out", 36070)),            # Ezoor
    (96, 298, ("M1_out", 36077)),            # Ertlig
    (106, 308, ("M1_water_colo_field", 36239)),
    (129, 331, None),                        # Quelor
    (130, 332, None),                        # Teslor
    (131, 333, None),                        # Nopel
    (132, 334, None),                        # Kalus
    (133, 335, None),                        # Justy
    (151, 353, ("D5_factory_1F", 34034)),    # Ibsol
    (152, 354, ("D5_factory_B1", 34037)),    # Kollo
    (154, 356, ("D5_factory_1F", 34035)),    # Jelstin
    (159, 361, ("D5_factory_4F", 34045)),    # Hospel
    (161, 363, ("D5_factory_top", 34050)),   # Fudler
)

#: Each trainer's own overworld model, as its room's character record has it: the character model table's people_archive
#: resource id for that record's model index. A slot takes it on as it appears (`Character` function 0x46, the one
#: the game's own scripts use to swap a character's model), so every trainer looks as they did where they stood.
_AGENT_M, _AGENT_F, _RESEARCHER = 0x19180400, 0x18C90400, 0x169A0400          # models 13, 11, 129
_SIX = 0x16A70400                                                                # model 139
TRAINER_MODELS: "dict[int, int]" = {
    **{six: _SIX for six in range(39, 45)},
    51: _AGENT_M, 53: _RESEARCHER, 54: _AGENT_F, 55: _RESEARCHER, 56: _RESEARCHER, 58: _AGENT_F,
    74: _AGENT_M, 76: _AGENT_M, 77: _AGENT_M, 79: _AGENT_F, 85: _AGENT_M,
    91: 0x1A700400, 92: 0x1A720400, 93: 0x172A0400, 94: 0x17220400, 95: 0x1A700400, 96: 0x1A720400,
    106: 0x172F0400,
    129: 0x172F0400, 130: 0x177F0400, 131: 0x19460400, 132: 0x19200400, 133: _SIX,
    151: _AGENT_F, 152: _AGENT_F, 154: _AGENT_F, 159: _RESEARCHER, 161: 0x191A0400,
}
CHARACTER_SET_MODEL = 0x09230046                 # Character function 0x46 (object, people_archive resource id)
PEOPLE_ARCHIVE = "people_archive.fsys"           # where function 0x46 reads them from (file group 0x9A)

#: Who each trainer is and where they're from, as the slots introduce them.
TRAINER_INTRODUCTIONS: "dict[int, tuple[str, str]]" = {
    **{t: (n, "PHENAC CITY") for t, n in ((39, "RESIX"), (40, "BLUSIX"), (41, "BROWSIX"), (42, "YELLOSIX"),
                                          (43, "PURPSIX"), (44, "GREESIX"))},
    **{t: (n, "the CIPHER LAB") for t, n in ((51, "DIGOR"), (53, "MORBIT"), (54, "MEDA"), (55, "ELROK"),
                                             (56, "COFFY"), (58, "NOPIA"))},
    **{t: (n, "PYRITE's ONBS building") for t, n in ((74, "MOCOR"), (76, "ELOX"), (77, "RIXOR"),
                                                         (79, "DILLY"), (85, "EDLOS"))},
    **{t: (n, "PHENAC CITY") for t, n in ((91, "PELLIM"), (92, "FENTON"), (93, "FORGS"), (94, "KAPEN"),
                                          (95, "EZOOR"), (96, "ERTLIG"), (129, "QUELOR"),
                                          (130, "TESLOR"), (131, "NOPEL"), (132, "KALUS"), (133, "JUSTY"))},
    106: ("EQUIN", "the PHENAC STADIUM"),
    **{t: (n, "the CIPHER KEY LAIR") for t, n in ((151, "IBSOL"), (152, "KOLLO"), (154, "JELSTIN"),
                                                     (159, "HOSPEL"), (161, "FUDLER"))},
}

#: Trainer i of KAMINKO_TRAINERS has three lines: its battle line at MESSAGE_BASE + i, its introduction and question
#: at that + QUESTION_OFFSET, and its answer to "no" at that + DECLINE_OFFSET. The client only writes the first id; the
#: slot's script adds the offsets.
MESSAGE_BASE = 49000
QUESTION_OFFSET = 100
DECLINE_OFFSET = 200

_SPEAKER = b"\xff\xff\x59"          # stands for the talking character's name; every slot is Chobin's record, so it
_NEW_BOX = b"\xff\xff\x03"          # is spelled out instead
_NEW_LINE = b"\xff\xff\x00"
_END = b"\xff\xff\x02\x00\x00"
_END_QUESTION = b"\x00\x00"          # a yes/no question ends without the wait-for-button code


def _text(value: str) -> bytes:
    return value.encode("utf-16-be")


def _spoken(name: str, *lines: str) -> bytes:
    return _text(name + ": ") + _NEW_LINE.join(_text(line) for line in lines)


def question_line(name: str, home: str) -> bytes:
    return _spoken(name, "Hey, you there!", f"I'm {name}, from {home}!", "How about a battle?") + _END_QUESTION


def decline_line(name: str) -> bytes:
    return _spoken(name, "Suit yourself.", "Come find me when you're ready!") + _END


def battle_line(name: str, own: "bytes | None") -> bytes:
    """The trainer's own line with their name spelled out, or a plain one."""
    if own:
        return own.replace(_SPEAKER, _text(name))
    return _spoken(name, "All right! Let's battle!") + _END


assert set(TRAINER_INTRODUCTIONS) == {t for t, _b, _m in KAMINKO_TRAINERS}

# ----------------------------------------------------------------------------------------------------------------
# The floor. Chobin stands at (-10, -0.4, -237.9) and the map arrival point is (-10, -0.25, 5). The fountain is a
# circle centred on (-9.5, -150.3), its wall about 45 units out (from the room's collision mesh). The slots stand on a
# ring 66 units from its centre, about 20 clear of the wall, six either side; nothing stands within 20 degrees of the
# walk up the middle (x = -10), where Robo Groudon appears late in the story, or in front of the manor door.
SLOT_COUNT = 12
FOUNTAIN_CENTRE = (-9.5, -150.3)
FOUNTAIN_WALL_RADIUS = 45.0
SLOT_RING_RADIUS = 66.0
_SLOT_RING_DEGREES = (65, 115, 40, 140, 15, 165, 350, 190, 325, 215, 300, 240)   # nearest the arrival point first
_SLOT_ANGLES = (37, 214, 128, 301, 76, 259, 162, 18, 233, 95, 341, 187)


def _ring_point(degrees: int) -> "tuple[float, float]":
    a = math.radians(degrees)
    # Quarter units: exact in the record's 32-bit floats.
    return (round((FOUNTAIN_CENTRE[0] + SLOT_RING_RADIUS * math.cos(a)) * 4) / 4,
            round((FOUNTAIN_CENTRE[1] + SLOT_RING_RADIUS * math.sin(a)) * 4) / 4)


SLOT_POSITIONS: "tuple[tuple[float, float, float, int], ...]" = (
    (18.5, -0.4, -90.5, 37), (-37.5, -0.4, -90.5, 214), (41.0, -0.4, -108.0, 128), (-60.0, -0.4, -108.0, 301),
    (54.25, -0.4, -133.25, 76), (-73.25, -0.4, -133.25, 259), (55.5, -0.4, -161.75, 162),
    (-74.5, -0.4, -161.75, 18), (44.5, -0.4, -188.25, 233), (-63.5, -0.4, -188.25, 95),
    (23.5, -0.4, -207.5, 341), (-42.5, -0.4, -207.5, 187),
)
assert all(_ring_point(d) == (x, z) for d, (x, _y, z, _a) in zip(_SLOT_RING_DEGREES, SLOT_POSITIONS))


def reposition_slots(rel: bytes, with_trainers: bool = True) -> bytes:
    """An already-patched floor module with Miror B. moved to MIROR_POSITION and (with the trainers) its twelve slots
    to SLOT_POSITIONS, each found by its talk function word, so re-patching an ISO built by an older version still
    puts them where they belong now."""
    out = bytearray(rel)
    places = [(VANILLA_FUNCTION_COUNT + k, position) for k, position in enumerate(SLOT_POSITIONS)] if with_trainers else []
    places.append((MIROR_FUNCTION_INDEX, MIROR_POSITION))
    for k, (function, (x, y, z, angle)) in enumerate(places):
        word = struct.pack(">I", 0x01000000 + function)
        at = [i for i in range(0, len(out) - 4, 4) if out[i:i + 4] == word and i >= 0x14
              and out[i - 0x14] in (SLOT_HIDDEN_FLAGS, SLOT_CHARACTER_FLAGS)]
        if len(at) != 1:
            raise ValueError(f"slot {k}'s record is not unique in this floor module")
        record = at[0] - 0x14
        struct.pack_into(">h", out, record + 0x04, angle)
        struct.pack_into(">3f", out, record + 0x18, x, y, z)
    return bytes(out)


FLOOR_ROOM = "S3_out"
#: Its room id (read off the room-id word in three dumps taken standing there).
FLOOR_ROOM_ID = 173
#: The manor's own NPC whose record the slots copy (model, name, behaviour): Chobin, the floor's first character.
TEMPLATE_CHARACTER = 0
#: The script names every slot function starts with -- the client finds the floor script in RAM by it.
SLOT_FUNCTION_PREFIX = b"ap_kaminko_slot_"
CHARACTER_GROUP = 0x80A                    # GIRI group of this floor's own characters
VANILLA_CHARACTER_COUNT = 4
VANILLA_FUNCTION_COUNT = 20
VANILLA_GVAR_COUNT = 7

# Globals the slots read, after the floor's own seven.
GVAR_BATTLE_BASE = VANILLA_GVAR_COUNT                 # slot k's battle id
GVAR_MESSAGE_BASE = VANILLA_GVAR_COUNT + SLOT_COUNT    # slot k's opening line
GVAR_EPOCH = VANILLA_GVAR_COUNT + 2 * SLOT_COUNT       # non-zero once the client has filled this load's slots
GVAR_MIROR = GVAR_EPOCH + 1                            # 1 while Miror B.'s queue holds a Shadow
GVAR_SHOWN_BASE = GVAR_MIROR + 1                       # slot k is showing (the script's own record of it)
GVAR_MODEL_BASE = GVAR_SHOWN_BASE + SLOT_COUNT         # slot k's model (people_archive resource id), 0 = Chobin's
GVAR_ADDED = 4 * SLOT_COUNT + 2
GVAR_TYPE_INT = 1

# The slots start hidden. The floor's main loop (`hero_main`) runs every frame; its loop top is a line-number marker
# (a no-op), which becomes a call to SHOW_FUNCTION_NAME: each slot is shown while it holds a battle and hidden when it
# does not, so an empty slot -- no missed trainer to put there -- is never seen.
SHOW_FUNCTION_NAME = b"ap_kaminko_show"
SHOW_FUNCTION_INDEX = VANILLA_FUNCTION_COUNT + SLOT_COUNT + 1
HERO_MAIN_LOOP_TOP = 1457                # w1457: `line 541`, the target of the loop's closing `jump 1457` (w1472)
HERO_MAIN_LOOP_TOP_VANILLA = 0x1000021D
HERO_MAIN_LOOP_JUMP = 1472
SLOT_OBJECT_BASE = 0x80 + 8              # object id of slot 0: the script's GIRI table holds eight before the slots
SLOT_HIDDEN_FLAGS = 0x78                 # as Chobin's own record: placed, but not shown until the script shows it

# Miror B. The script always carries the twelve slot functions (the client finds the script by their names) and his,
# after them; the floor only gets the slot characters when Kaminko Missable Trainers is on.
MIROR_FUNCTION_NAME = b"ap_kaminko_miror"
MIROR_FUNCTION_INDEX = VANILLA_FUNCTION_COUNT + SLOT_COUNT
MIROR_BATTLE = 423                       # the Poke Spots' battle: type 16, team built from his queue
MIROR_MODEL = 105                        # his overworld model's index in the character model table
MIROR_NAME_ID = 100                      # his name, as the Outskirt Stand's record has it
MIROR_MODEL_SOURCE = ("S1_out", "mirrabo_0000")   # the room archive his model is copied from, and its entry
MIROR_POSITION = (-21.0, -0.4, -30.0, 90)  # 35 in from the arrival point (-10, -0.25, 5), short of the slot ring
MIROR_MESSAGE_QUESTION = 49300
MIROR_MESSAGE_BATTLE = 49301
MIROR_MESSAGE_DECLINE = 49302
MIROR_MESSAGE_EMPTY = 49303

assert len({t for t, _b, _m in KAMINKO_TRAINERS}) == len(KAMINKO_TRAINERS)
assert set(TRAINER_MODELS) == {t for t, _b, _m in KAMINKO_TRAINERS}
assert len(SLOT_POSITIONS) == SLOT_COUNT


def _be32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def _pad16(blob: bytes) -> bytes:
    return blob + b"\x00" * (-len(blob) % 16)


# ----------------------------------------------------------------------------------------------------------------
# The floor module (REL, file format 28).
CHARACTER_RECORD_SIZE = 0x24
#: Visible, placed when the floor loads, solid, turns its head, talkable through walls -- what town NPCs use. Chobin's
#: own record leaves "visible" clear because his script shows him.
SLOT_CHARACTER_FLAGS = 0xF8


def _rel_sections(rel: bytes) -> "list[tuple[int, int]]":
    count, info = _be32(rel, 0x0C), _be32(rel, 0x10)
    return [struct.unpack_from(">II", rel, info + 8 * i) for i in range(count)]


def _rel_self_relocations(rel: bytes) -> "tuple[int, list[tuple[int, int, int, int, int]]]":
    """(self module id, [(file offset of the entry, current section, offset in section, type, target section,
    addend)])."""
    module = _be32(rel, 0x00)
    imp_off, imp_size = _be32(rel, 0x28), _be32(rel, 0x2C)
    out = []
    for i in range(imp_size // 8):
        who, start = struct.unpack_from(">II", rel, imp_off + 8 * i)
        if who != module:
            continue
        pos, section, at = start, None, 0
        while True:
            off, kind, target, addend = struct.unpack_from(">HBBI", rel, pos)
            if kind == 203:
                break
            at += off
            if kind == 202:
                section, at = target, 0
            else:
                out.append((pos, section, at, kind, target, addend))
            pos += 8
    return module, out


def added_characters(with_trainers: bool) -> "list[tuple[float, float, float, int, int, int | None, int | None]]":
    """(x, y, z, angle, talk function index, model or None, name id or None) for every character this patch adds:
    the trainer slots when they are on, then Miror B."""
    out = []
    if with_trainers:
        out += [(x, y, z, a, VANILLA_FUNCTION_COUNT + k, None, None) for k, (x, y, z, a) in enumerate(SLOT_POSITIONS)]
    x, y, z, a = MIROR_POSITION
    out.append((x, y, z, a, MIROR_FUNCTION_INDEX, MIROR_MODEL, MIROR_NAME_ID))
    return out


def build_floor_rel(rel: bytes, with_trainers: bool = True) -> bytes:
    """The S3_out floor module with the added characters. Refuses anything that is not the vanilla shape."""
    sections = _rel_sections(rel)
    data_off, data_size = sections[3]
    _module, relocs = _rel_self_relocations(rel)
    table_refs = [r for r in relocs if r[4] == 3 and r[5] == 0]
    count_refs = [r for r in relocs if r[1] == 1 and r[4] == 3 and r[3] == 6]
    if len(table_refs) != 3 or not count_refs:
        raise ValueError("S3_out's floor module does not have the expected NPC-table relocations")
    count_at = data_off + count_refs[1][5]
    if _be32(rel, count_at) != VANILLA_CHARACTER_COUNT:
        raise ValueError(f"S3_out has {_be32(rel, count_at)} characters, not {VANILLA_CHARACTER_COUNT}")
    if data_off + data_size != _be32(rel, 0x28):
        raise ValueError("S3_out's data section is not directly followed by its import table")
    template = rel[data_off + TEMPLATE_CHARACTER * CHARACTER_RECORD_SIZE:][:CHARACTER_RECORD_SIZE]
    table = bytearray(rel[data_off:data_off + VANILLA_CHARACTER_COUNT * CHARACTER_RECORD_SIZE])
    added = added_characters(with_trainers)
    for x, y, z, angle, function, model, name in added:
        record = bytearray(template)
        record[0] = SLOT_HIDDEN_FLAGS if function < MIROR_FUNCTION_INDEX else SLOT_CHARACTER_FLAGS
        struct.pack_into(">h", record, 0x04, angle)
        if model is not None:
            struct.pack_into(">H", record, 0x06, model)
        if name is not None:
            struct.pack_into(">H", record, 0x08, name)
        struct.pack_into(">I", record, 0x10, 0)                                           # no move script
        struct.pack_into(">I", record, 0x14, 0x01000000 + function)                       # its talk function
        struct.pack_into(">3f", record, 0x18, x, y, z)
        table += record
    new_table_at = data_size + (-data_size % 4)
    grow = new_table_at - data_size + len(table)
    out = bytearray(rel[:data_off + data_size]) + b"\x00" * (new_table_at - data_size) + table + rel[data_off + data_size:]
    info = _be32(rel, 0x10)
    struct.pack_into(">II", out, info + 8 * 3, data_off, data_size + grow)
    for field in (0x24, 0x28, 0x48):                        # relocation, import and fix-size offsets move
        struct.pack_into(">I", out, field, _be32(rel, field) + grow)
    imp_off, imp_size = _be32(out, 0x28), _be32(out, 0x2C)
    for i in range(imp_size // 8):
        struct.pack_into(">I", out, imp_off + 8 * i + 4, _be32(out, imp_off + 8 * i + 4) + grow)
    for pos, _section, _at, _kind, _target, _addend in table_refs:
        struct.pack_into(">I", out, pos + grow + 4, new_table_at)
    struct.pack_into(">I", out, count_at, VANILLA_CHARACTER_COUNT + len(added))
    return bytes(out)


# ----------------------------------------------------------------------------------------------------------------
# The floor script (TCOD).
SECTION_TAGS = (b"FTBL", b"HEAD", b"CODE", b"GVAR", b"STRG", b"VECT", b"GIRI", b"ARRY")


def split_script(tcod: bytes) -> "dict[bytes, bytes]":
    if tcod[:4] != b"TCOD":
        raise ValueError("not a script")
    out, offset = {}, 0x10
    for tag in SECTION_TAGS:
        if tcod[offset:offset + 4] != tag:
            raise ValueError(f"expected {tag!r} at 0x{offset:X}")
        size = _be32(tcod, offset + 4)
        out[tag] = tcod[offset:offset + size]
        offset += size
    return out


def slot_function_words(slot: int, start: int) -> "list[int]":
    """Slot `slot`'s talk function, placed at CODE word `start`. Mirrors the floors' own trainer functions and
    Hebon's ask-first one: nothing if the slot is empty, else face each other and ask; on "yes" battle with this
    slot's line, then clear the slot's battle global and hide; on "no" say so and stay."""
    battle, message = GVAR_BATTLE_BASE + slot, GVAR_MESSAGE_BASE + slot
    body = [
        0x03000000 | battle, 0x02010000, 0, OP_NOT_EQUAL, "end",        # unless battle != 0 -> end
        0x1103002B, 0x092B0012, 0x06010000,                              # lock the player
        0x02020000, 0x00000000, 0x03030080, 0x11010001, 0x09230031, 0x06030000,   # turn to the player
        0x02020000, 0x3F800000, 0x03010001, 0x03030080, 0x09230031, 0x06030000,   # player turns to them
        0x03000000 | message, 0x02010000, QUESTION_OFFSET, 0x01230000,  # introduction + yes/no
        0x02010000, 8, 0x11010001, 0x09230049, 0x06030000,
        0x03020000, 0x02010000, 0, 0x01300000, "decline",                # answer != yes -> decline
        0x03000000 | battle, 0x03000000 | message, 0x02010000, 6, 0x11010001, 0x09230049, 0x06040000,  # line + battle
        0x02010000, 0, 0x04000000 | battle,                              # won: the slot is empty now
        0x02010000, 0, 0x11010001, 0x09230010, 0x06020000,               # hide
        "unlock",
        "@decline",
        0x03000000 | message, 0x02010000, DECLINE_OFFSET, 0x01230000,   # "no": say so
        0x02010000, 1, 0x11010001, 0x09230049, 0x06030000,
        "@unlock",
        0x1103002B, 0x092B0013, 0x06010000,                              # unlock the player
        "@end",
        0x0E000000, 0x08000000,                                          # release 0, return
    ]
    labels, words, at = {}, [], start
    for word in body:
        if isinstance(word, str) and word.startswith("@"):
            labels[word[1:]] = at
        else:
            words.append(word)
            at += 1
    jumps = {"end": JUMP_IF_FALSE, "decline": JUMP_IF_FALSE, "unlock": 0x0C000000}
    return [jumps[w] | labels[w] if isinstance(w, str) else w for w in words]


# The game's own scripts branch only with jump-if-false (0x0B) -- not one jump-if-true (0x0A) in any of them -- so
# every test here is written that way: "skip unless x != c" rather than "skip if x == c".
JUMP_IF_FALSE = 0x0B000000
OP_EQUAL = 0x01300000
OP_NOT_EQUAL = 0x01350000

_FACE_EACH_OTHER = [
    0x02020000, 0x00000000, 0x03030080, 0x11010001, 0x09230031, 0x06030000,   # turn to the player
    0x02020000, 0x3F800000, 0x03010001, 0x03030080, 0x09230031, 0x06030000,   # player turns to them
]
_LOCK = [0x1103002B, 0x092B0012, 0x06010000]
_UNLOCK = [0x1103002B, 0x092B0013, 0x06010000]


def _talk(kind: int, message: int) -> "list[int]":
    return [0x02010000, message, 0x02010000, kind, 0x11010001, 0x09230049, 0x06030000]


def miror_function_words(start: int) -> "list[int]":
    """Miror B.'s talk function, placed at CODE word `start`: with nothing queued he says so; otherwise he asks, and
    on "yes" starts battle 423 with his line. He stays where he is either way."""
    body = [
        0x03000000 | GVAR_MIROR, 0x02010000, 0, OP_NOT_EQUAL, (JUMP_IF_FALSE, "empty"),   # nothing queued -> say so
        *_LOCK, *_FACE_EACH_OTHER,
        *_talk(8, MIROR_MESSAGE_QUESTION),                                          # yes/no
        0x03020000, 0x02010000, 0, 0x01300000, (0x0B000000, "decline"),
        0x02010000, MIROR_BATTLE, 0x02010000, MIROR_MESSAGE_BATTLE, 0x02010000, 6,  # line + battle 423
        0x11010001, 0x09230049, 0x06040000,
        (0x0C000000, "unlock"),
        "@empty",
        *_LOCK, *_FACE_EACH_OTHER,
        *_talk(1, MIROR_MESSAGE_EMPTY),
        (0x0C000000, "unlock"),
        "@decline",
        *_talk(1, MIROR_MESSAGE_DECLINE),
        "@unlock",
        *_UNLOCK,
        0x0E000000, 0x08000000,                                                     # release 0, return
    ]
    labels, words, at = {}, [], start
    for word in body:
        if isinstance(word, str):
            labels[word[1:]] = at
        else:
            words.append(word)
            at += 1
    return [w[0] | labels[w[1]] if isinstance(w, tuple) else w for w in words]


def show_function_words(start: int, with_models: bool = True) -> "list[int]":
    """Each frame, from the floor's main loop: show slot k when its battle global is set and it is not showing, hide
    it when the global is clear and it is. Two words of state per slot keep it from touching a model every frame.
    Just before it shows, a slot whose model global is set takes that model on."""
    body: list = []
    for k in range(SLOT_COUNT):
        battle, shown, obj = GVAR_BATTLE_BASE + k, GVAR_SHOWN_BASE + k, 0x03030000 | (SLOT_OBJECT_BASE + k)
        model = GVAR_MODEL_BASE + k
        set_model = [
            0x03000000 | model, 0x02010000, 0, OP_NOT_EQUAL, (JUMP_IF_FALSE, f"show{k}"),
            0x03000000 | model, obj, CHARACTER_SET_MODEL, 0x06020000,
            f"@show{k}",
        ] if with_models else []
        body += [
            0x03000000 | battle, 0x02010000, 0, 0x01300000, (0x0B000000, f"on{k}"),
            0x03000000 | shown, 0x02010000, 0, OP_NOT_EQUAL, (JUMP_IF_FALSE, f"next{k}"),   # already hidden
            0x02010000, 0, obj, 0x09230010, 0x06020000,                   # hide
            0x02010000, 0, 0x04000000 | shown,
            (0x0C000000, f"next{k}"),
            f"@on{k}",
            0x03000000 | shown, 0x02010000, 1, OP_NOT_EQUAL, (JUMP_IF_FALSE, f"next{k}"),   # already showing
            *set_model,
            0x02010000, 1, obj, 0x09230010, 0x06020000,                   # show
            0x02010000, 1, 0x04000000 | shown,
            f"@next{k}",
        ]
    body += [0x0E000000, 0x08000000]
    labels, words, at = {}, [], start
    for word in body:
        if isinstance(word, str):
            labels[word[1:]] = at
        else:
            words.append(word)
            at += 1
    return [w[0] | labels[w[1]] if isinstance(w, tuple) else w for w in words]


def build_floor_script(tcod: bytes, with_trainers: bool = True, with_models: bool = True) -> bytes:
    parts = split_script(tcod)
    ftbl, head, code, gvar, giri = (parts[t] for t in (b"FTBL", b"HEAD", b"CODE", b"GVAR", b"GIRI"))
    count = _be32(ftbl, 0x10)
    if count != VANILLA_FUNCTION_COUNT or _be32(gvar, 0x10) != VANILLA_GVAR_COUNT or _be32(giri, 0x10) != 8:
        raise ValueError("S3_out's script is not the vanilla shape")
    added = SLOT_COUNT + 2
    # CODE: append after the used words (the header's +0x14), keeping the trailing padding convention.
    used = _be32(code, 0x14)
    words = [_be32(code, 0x20 + 4 * i) for i in range(used)]
    starts = []
    for slot in range(SLOT_COUNT):
        starts.append(len(words))
        words.extend(slot_function_words(slot, len(words)))
    starts.append(len(words))
    words.extend(miror_function_words(len(words)))
    starts.append(len(words))
    words.extend(show_function_words(len(words), with_models))
    if with_trainers:
        if words[HERO_MAIN_LOOP_TOP] != HERO_MAIN_LOOP_TOP_VANILLA or \
                words[HERO_MAIN_LOOP_JUMP] != (0x0C000000 | HERO_MAIN_LOOP_TOP):
            raise ValueError("S3_out's main loop is not the vanilla shape")
        words[HERO_MAIN_LOOP_TOP] = 0x07000000 | starts[-1]          # call ap_kaminko_show, every frame
    code_body = b"".join(struct.pack(">I", w) for w in words) + b"\x00" * 8
    new_code = bytearray(code[:0x20]) + code_body
    new_code = bytearray(_pad16(bytes(new_code)))
    struct.pack_into(">I", new_code, 4, len(new_code))
    struct.pack_into(">I", new_code, 0x10, count + added)
    struct.pack_into(">I", new_code, 0x14, len(words))
    # FTBL: entries then names; every old name offset moves by the new entries' size.
    names_start = _be32(ftbl, 0x14)
    old_entries = [struct.unpack_from(">II", ftbl, 0x20 + 8 * i) for i in range(count)]
    names = bytearray(ftbl[names_start:]).rstrip(b"\x00") + b"\x00"
    shift = 8 * added
    entries = [(co, no + shift) for co, no in old_entries]
    new_names_start = names_start + shift
    for slot, start in enumerate(starts):
        entries.append((start, new_names_start + len(names)))
        names += (SLOT_FUNCTION_PREFIX + f"{slot:02d}".encode() if slot < SLOT_COUNT
                  else (MIROR_FUNCTION_NAME, SHOW_FUNCTION_NAME)[slot - SLOT_COUNT]) + b"\x00"
    new_ftbl = bytearray(ftbl[:0x20]) + b"".join(struct.pack(">II", *e) for e in entries) + names
    new_ftbl = bytearray(_pad16(bytes(new_ftbl)))
    struct.pack_into(">I", new_ftbl, 4, len(new_ftbl))
    struct.pack_into(">I", new_ftbl, 0x10, count + added)
    struct.pack_into(">I", new_ftbl, 0x14, new_names_start)
    # HEAD: one code offset per function.
    head_words = [_be32(head, 0x20 + 4 * i) for i in range(count)] + starts
    new_head = bytearray(head[:0x20]) + b"".join(struct.pack(">I", w) for w in head_words)
    new_head = bytearray(_pad16(bytes(new_head)))
    struct.pack_into(">I", new_head, 4, len(new_head))
    struct.pack_into(">I", new_head, 0x10, count + added)
    # GVAR: integers, zero.
    gv_count = _be32(gvar, 0x10)
    # On disc an entry is (u32 kind, u32 value), kind 1 an integer like the floor's own first three; the loader
    # rewrites the kind into its runtime form in place and the value stays at +4, where the client writes.
    gv = gvar[0x20:0x20 + 8 * gv_count] + b"".join(struct.pack(">II", GVAR_TYPE_INT, 0)
                                                   for _ in range(GVAR_ADDED))
    new_gvar = bytearray(_pad16(bytes(gvar[:0x20]) + gv))
    struct.pack_into(">I", new_gvar, 4, len(new_gvar))
    struct.pack_into(">I", new_gvar, 0x10, gv_count + GVAR_ADDED)
    # GIRI: the added characters, so each has an object id like the floor's own four.
    characters = len(added_characters(with_trainers))
    gi_count = _be32(giri, 0x10)
    gi = giri[0x20:0x20 + 8 * gi_count] + b"".join(
        struct.pack(">II", CHARACTER_GROUP, VANILLA_CHARACTER_COUNT + k) for k in range(characters))
    new_giri = bytearray(_pad16(bytes(giri[:0x20]) + gi))
    struct.pack_into(">I", new_giri, 4, len(new_giri))
    struct.pack_into(">I", new_giri, 0x10, gi_count + characters)
    rebuilt = {b"FTBL": bytes(new_ftbl), b"HEAD": bytes(new_head), b"CODE": bytes(new_code),
               b"GVAR": bytes(new_gvar), b"GIRI": bytes(new_giri)}
    body = b"".join(rebuilt.get(tag, parts[tag]) for tag in SECTION_TAGS)
    header = bytearray(tcod[:0x10])
    struct.pack_into(">I", header, 4, 0x10 + len(body))
    return bytes(header) + body


def section_offsets(tcod_head: bytes) -> "dict[bytes, int]":
    """Offsets of each section in a script, read from its own headers (works on the resident copy too)."""
    out, offset = {}, 0x10
    for tag in SECTION_TAGS:
        out[tag] = offset
        offset += _be32(tcod_head, offset + 4)
    return out


# ----------------------------------------------------------------------------------------------------------------
# The floor's message file.
def message_entries(msg: bytes) -> "dict[int, bytes]":
    count = struct.unpack_from(">H", msg, 4)[0]
    pairs = [struct.unpack_from(">II", msg, 0x10 + 8 * i) for i in range(count)]
    offsets = sorted({o for _sid, o in pairs}) + [len(msg)]
    following = {o: offsets[i + 1] for i, o in enumerate(offsets[:-1])}
    return {sid: msg[o:following[o]] for sid, o in pairs}


def build_messages(msg: bytes, added: "dict[int, bytes]") -> bytes:
    count = struct.unpack_from(">H", msg, 4)[0]
    pairs = [struct.unpack_from(">II", msg, 0x10 + 8 * i) for i in range(count)]
    if any(sid in added for sid, _o in pairs):
        raise ValueError("a new message id is already in use")
    shift = 8 * len(added)
    strings_start = 0x10 + 8 * count
    if min(o for _sid, o in pairs) != strings_start:
        raise ValueError("this message file's strings do not start right after its pairs")
    tail = msg[strings_start:]
    end = len(msg) + shift
    new_pairs = [(sid, o + shift) for sid, o in pairs]
    blobs = b""
    for sid, text in sorted(added.items()):
        new_pairs.append((sid, end + len(blobs)))
        blobs += text
    header = bytearray(msg[:0x10])
    struct.pack_into(">H", header, 4, count + len(added))
    return bytes(header) + b"".join(struct.pack(">II", *p) for p in new_pairs) + tail + blobs


def miror_lines() -> "dict[int, bytes]":
    name = "MIROR B."
    return {
        MIROR_MESSAGE_QUESTION: _spoken(name, "Oh-ho! Come to take back the Shadows", "that got away from you?",
                                        "Then dance with me!") + _END_QUESTION,
        MIROR_MESSAGE_BATTLE: _spoken(name, "Let's get this party started!") + _END,
        MIROR_MESSAGE_DECLINE: _spoken(name, "No? Your loss, baby!") + _END,
        MIROR_MESSAGE_EMPTY: _spoken(name, "I've got nothing of yours right now.",
                                     "Let one get away and come see me!") + _END,
    }


def floor_lines(source_messages: "dict[str, dict[int, bytes]]", with_trainers: bool) -> "dict[int, bytes]":
    """Every line the patch adds to the floor's message file."""
    out = miror_lines()
    if with_trainers:
        out.update(trainer_lines(source_messages))
    return out


def trainer_lines(source_messages: "dict[str, dict[int, bytes]]") -> "dict[int, bytes]":
    """{new message id: text}: every trainer's battle line, introduction and answer to "no"."""
    out = {}
    for i, (trainer, _battle, source) in enumerate(KAMINKO_TRAINERS):
        name, home = TRAINER_INTRODUCTIONS[trainer]
        own = None
        if source is not None:
            room, message = source
            own = source_messages.get(room, {}).get(message)
        out[MESSAGE_BASE + i] = battle_line(name, own)
        out[MESSAGE_BASE + QUESTION_OFFSET + i] = question_line(name, home)
        out[MESSAGE_BASE + DECLINE_OFFSET + i] = decline_line(name)
    return out
