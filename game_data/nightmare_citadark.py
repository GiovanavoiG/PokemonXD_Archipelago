"""ADDENDUM 423 -- Nightmare Citadark: every Citadark Isle trainer fields an Orre Colosseum team at level 100.

The option `Nightmare_Citadark` replaces every Citadark trainer's team with one of these teams at level 100, and
copies each source trainer's AI. With it enabled, Citadark trainers field no Shadow Pokemon at all; every team has
six members. Greevil's first team (Shadow Lugia alone) is not replaced, and the Citadark Shadows it displaces are
moved onto the rest of the trainers -- only ever onto non-missable ones.

GREEVIL #1 (row 199) fields Shadow Lugia and nothing else, and keeps it: 33 trainers take a team, not 34. The
other 35 Citadark Shadows are RELOCATED, not deleted (`plan_relocations`): each keeps its own DDPK entry and the
DPKM record behind it -- so the species shuffle, catch flags and purification data all still apply -- and is
hung on a free slot of a non-missable trainer elsewhere, at that trainer's level, the way Shadow Pokemon
Expansion places its generated ones. No DDPK capacity is spent, so the expansion keeps its full 44.

WHERE THE TEAMS ARE. XD's own disc carries the Orre Colosseum in `deck_archive.fsys` -> `DeckData_Colosseum.bin`.
Trainers 41-68 of that deck are the 28 six-member challengers the Bulbapedia XD section lists (Greel, Herlam,
Lestor, Lovrina, ...): deck level 60 (the game scales them to the player), with full sets -- item, four moves,
IVs, EVs, nature/gender/ability byte, AI role -- and each trainer's own `aiIndex` into that deck's DTAI table.
Trainers 1-40 are the low tiers (level 20/40, three to five members) and are not used.

For these, generation names the source trainer and its six species, so the patcher can refuse a disc whose deck
disagrees; the sets and the AI row are copied from that deck at patch time.

THE COLOSSEUM TEAMS. The pool is XD + Colosseum, and every trainer gets a unique team -- 33 Citadark trainers
against XD's 28. Pokemon Colosseum's own Orre
Colosseum, Lv. 100 Battle Mode, adds sixteen: eight Single rounds and eight Double rounds, every member already
level 100. They were read off a Colosseum (USA, GC6E) disc's `common.rel` -- Trainer table (0x34/row, rows 559-574)
and TrainerPokemonData (0x50/row) -- and every field was explicit (no random ability, gender, nature or move). Each
team's sets are below, with how its AI plays (`COLOSSEUM_ORRE_LV100_AI_STYLES`).

Both games number species, items and moves the same way, and their Pokemon AI-role tables are the same table: 79
rows each, every row's name id and second word identical, weights on a different scale (Colosseum 0x80 at
neutral, XD 0x32). Measured on Colosseum's `common.rel` and XD's live table at `*(r13-0x74D4)` (count at
`*(r13-0x74D8)`, read by `fightTrainerPokemonPartDataBiosGetPtr`). So a member's AI role carries over as its number.

A Colosseum team's AI is given as named settings (`AiStyle`) and built into an XD DTAI row (`dtai_row`).

THE AI. Story trainers' DTAI rows are nearly empty -- no stat-stage targets, no switch/item/KO rates -- while the
Colosseum rows set all of them. The patch copies the source trainer's 0x20-byte DTAI row into the Citadark
trainer's own row (each Story trainer owns row == its index, so it is an in-place overwrite), its combo fields
(DTNR +0x2C..+0x37), and each member's whole DPKM record, AI role and combo flags included.
"""
from __future__ import annotations

import random
import struct
from typing import NamedTuple

from . import load_json_data_file
from .catch_rate_exclusions import citadark_trainer_indices
from .shadow_holders import vanilla_shadow_holders

NIGHTMARE_LEVEL = 100
TEAM_SIZE = 6

#: The deck file the pool lives in, and its trainer rows that form the pool.
SOURCE_DECK = "DeckData_Colosseum.bin"

#: {source trainer index in DeckData_Colosseum.bin: the six internal species indices it fields, in slot order}.
#: Identifiers only (see the module docstring); the patcher checks them against the disc before copying.
XD_ORRE_COLOSSEUM_TEAMS: "dict[int, tuple[int, ...]]" = {
    41: (47, 307, 80, 124, 229, 394),
    42: (308, 199, 345, 108, 352, 235),
    43: (234, 176, 178, 352, 26, 12),
    44: (213, 329, 202, 242, 200, 154),
    45: (248, 28, 195, 319, 345, 51),
    46: (87, 99, 51, 34, 127, 131),
    47: (303, 132, 97, 359, 141, 78),
    48: (101, 94, 89, 347, 401, 402),
    49: (331, 71, 106, 76, 380, 31),
    50: (34, 22, 126, 124, 186, 391),
    51: (212, 59, 125, 343, 195, 57),
    52: (397, 210, 59, 128, 237, 130),
    53: (196, 197, 135, 134, 136, 133),
    54: (366, 94, 65, 400, 329, 319),
    55: (169, 85, 305, 68, 53, 214),
    56: (212, 122, 149, 105, 115, 302),
    57: (135, 302, 110, 208, 229, 106),
    58: (157, 154, 160, 243, 199, 169),
    59: (285, 394, 279, 305, 282, 45),
    60: (9, 366, 227, 397, 6, 3),
    61: (362, 397, 149, 334, 142, 145),
    62: (300, 103, 189, 244, 36, 282),
    63: (297, 375, 139, 230, 338, 211),
    64: (279, 6, 94, 142, 128, 121),
    65: (6, 36, 303, 176, 143, 214),
    66: (145, 146, 144, 243, 244, 245),
    67: (105, 130, 338, 85, 121, 131),
    68: (408, 407, 94, 400, 143, 128),
}

assert all(len(team) == TEAM_SIZE for team in XD_ORRE_COLOSSEUM_TEAMS.values())


class _Set(NamedTuple):
    """One member, as Colosseum's TrainerPokemonData has it (level is always 100 there)."""
    species: int            # internal index, shared by both games
    item: int
    happiness: int
    ai_role: int            # row in the shared Pokemon AI-role table
    ivs: "tuple[int, ...]"  # HP/Atk/Def/SpA/SpD/Spe
    evs: "tuple[int, ...]"
    moves: "tuple[int, ...]"
    nature: int
    gender: int             # 0 male, 1 female, 2 genderless -- the encoding XD's DPKM +0x1E uses too
    ability: int            # slot 0 or 1

    def as_dict(self) -> dict:
        return {"species": self.species, "item": self.item, "happiness": self.happiness, "ai_role": self.ai_role,
                "ivs": list(self.ivs), "evs": list(self.evs), "moves": list(self.moves), "nature": self.nature,
                "gender": self.gender, "ability": self.ability}


#: {Colosseum Trainer row: its six sets}. Rows 559-566 are the Single rounds 1-8, 567-574 the Double rounds.
COLOSSEUM_ORRE_LV100_TEAMS: "dict[int, tuple[_Set, ...]]" = {
    559: (  # Lv. 100 Battle Mode Single, round 1
        _Set(241, 170, 0, 16, (29, 30, 29, 13, 28, 30), (6, 252, 0, 0, 0, 252), (34, 89, 203, 179), 13, 1, 0),
        _Set(302, 168, 0, 16, (31, 31, 27, 15, 30, 30), (6, 252, 0, 0, 252, 0), (14, 332, 237, 203), 3, 1, 0),
        _Set(389, 200, 0, 17, (31, 27, 29, 14, 29, 28), (6, 0, 252, 0, 252, 0), (105, 188, 109, 133), 8, 1, 0),
        _Set(336, 134, 0, 70, (31, 25, 30, 11, 30, 27), (6, 0, 252, 0, 252, 0), (187, 156, 89, 280), 23, 0, 0),
        _Set(196, 171, 0, 16, (30, 18, 27, 30, 26, 31), (6, 0, 0, 252, 0, 252), (94, 44, 347, 203), 10, 0, 0),
        _Set(245, 169, 0, 16, (31, 15, 30, 27, 29, 25), (6, 0, 252, 252, 0, 0), (58, 57, 156, 347), 20, 2, 0),
    ),
    560: (  # Lv. 100 Battle Mode Single, round 2
        _Set(248, 200, 0, 16, (30, 29, 29, 18, 29, 31), (6, 252, 0, 0, 0, 252), (157, 89, 332, 349), 13, 0, 0),
        _Set(345, 179, 0, 1, (29, 30, 27, 30, 27, 26), (0, 252, 0, 252, 0, 6), (290, 202, 298, 185), 17, 1, 0),
        _Set(207, 221, 0, 1, (30, 30, 27, 19, 28, 27), (6, 252, 0, 0, 252, 0), (332, 89, 12, 290), 3, 0, 1),
        _Set(82, 183, 0, 2, (29, 23, 28, 31, 29, 22), (6, 0, 0, 252, 252, 0), (115, 85, 86, 237), 15, 2, 1),
        _Set(334, 198, 0, 1, (30, 29, 27, 28, 27, 31), (6, 252, 0, 0, 0, 252), (89, 237, 126, 225), 13, 1, 0),
        _Set(403, 180, 0, 78, (31, 30, 29, 25, 30, 25), (6, 252, 0, 0, 252, 0), (153, 276, 246, 89), 3, 2, 0),
    ),
    561: (  # Lv. 100 Battle Mode Single, round 3
        _Set(85, 186, 255, 1, (29, 30, 28, 12, 28, 31), (6, 252, 0, 0, 0, 252), (216, 65, 63, 98), 13, 0, 1),
        _Set(329, 196, 0, 1, (31, 13, 29, 29, 30, 26), (6, 0, 252, 252, 0, 0), (109, 58, 57, 105), 5, 1, 0),
        _Set(400, 200, 0, 1, (28, 30, 28, 17, 29, 27), (6, 252, 0, 0, 252, 0), (309, 247, 89, 280), 3, 2, 0),
        _Set(409, 179, 0, 16, (29, 20, 28, 30, 28, 31), (6, 0, 0, 252, 0, 252), (347, 94, 352, 85), 10, 2, 0),
        _Set(243, 221, 0, 2, (28, 11, 27, 31, 27, 31), (6, 0, 0, 252, 0, 252), (85, 115, 242, 46), 10, 2, 0),
        _Set(169, 198, 0, 1, (29, 31, 28, 15, 29, 30), (6, 252, 0, 0, 0, 252), (109, 188, 247, 332), 13, 1, 0),
    ),
    562: (  # Lv. 100 Battle Mode Single, round 4
        _Set(285, 134, 255, 16, (29, 30, 30, 15, 30, 25), (6, 252, 0, 0, 252, 0), (174, 89, 216, 156), 2, 1, 0),
        _Set(282, 170, 0, 16, (30, 31, 28, 28, 28, 29), (6, 252, 0, 0, 0, 252), (89, 126, 203, 179), 3, 0, 0),
        _Set(279, 198, 0, 1, (27, 22, 30, 31, 27, 31), (6, 0, 0, 252, 0, 252), (348, 337, 242, 237), 10, 1, 0),
        _Set(397, 200, 255, 1, (29, 31, 29, 12, 30, 30), (6, 252, 0, 0, 0, 252), (216, 332, 89, 280), 13, 0, 0),
        _Set(394, 179, 0, 16, (30, 19, 28, 31, 30, 27), (6, 0, 0, 252, 0, 252), (85, 94, 347, 194), 15, 1, 0),
        _Set(338, 221, 0, 1, (27, 18, 30, 30, 27, 31), (6, 0, 0, 252, 0, 252), (86, 242, 85, 237), 10, 1, 0),
    ),
    563: (  # Lv. 100 Battle Mode Single, round 5
        _Set(302, 179, 0, 68, (29, 31, 27, 13, 29, 30), (0, 252, 6, 0, 252, 0), (14, 182, 226, 318), 23, 1, 0),
        _Set(217, 219, 255, 1, (30, 31, 30, 19, 30, 27), (0, 252, 0, 0, 0, 252), (216, 89, 280, 237), 3, 0, 0),
        _Set(121, 221, 0, 1, (29, 0, 27, 30, 28, 31), (6, 0, 0, 252, 0, 252), (57, 58, 85, 94), 10, 2, 1),
        _Set(68, 200, 0, 1, (30, 31, 27, 11, 30, 28), (0, 252, 0, 0, 0, 252), (157, 238, 89, 63), 3, 0, 0),
        _Set(130, 198, 255, 16, (31, 31, 27, 18, 30, 30), (6, 252, 0, 0, 0, 252), (349, 216, 89, 237), 3, 0, 0),
        _Set(202, 183, 0, 16, (31, 11, 30, 8, 30, 26), (252, 0, 129, 0, 129, 0), (68, 243, 219, 194), 23, 1, 0),
    ),
    564: (  # Lv. 100 Battle Mode Single, round 6
        _Set(404, 134, 0, 1, (28, 13, 27, 30, 29, 31), (6, 0, 0, 252, 0, 252), (57, 58, 87, 156), 10, 2, 0),
        _Set(297, 200, 0, 2, (29, 17, 31, 29, 30, 27), (0, 0, 158, 252, 0, 100), (58, 56, 202, 73), 15, 1, 0),
        _Set(230, 187, 0, 1, (28, 14, 29, 31, 30, 28), (6, 0, 252, 252, 0, 0), (58, 56, 225, 240), 15, 0, 0),
        _Set(101, 217, 0, 78, (29, 28, 27, 30, 28, 30), (6, 0, 0, 252, 0, 252), (87, 153, 240, 113), 19, 2, 1),
        _Set(375, 221, 0, 1, (27, 18, 30, 31, 31, 26), (6, 0, 0, 252, 0, 252), (58, 56, 94, 237), 15, 0, 0),
        _Set(402, 179, 0, 78, (27, 26, 31, 31, 31, 18), (0, 6, 252, 252, 0, 0), (58, 153, 87, 237), 15, 2, 0),
    ),
    565: (  # Lv. 100 Battle Mode Single, round 7
        _Set(405, 183, 255, 1, (30, 31, 26, 25, 29, 30), (6, 252, 0, 0, 0, 252), (89, 246, 216, 315), 13, 2, 0),
        _Set(300, 221, 0, 78, (28, 30, 27, 28, 29, 27), (0, 252, 102, 0, 0, 156), (153, 76, 247, 280), 2, 0, 0),
        _Set(45, 187, 0, 1, (27, 22, 27, 30, 31, 26), (6, 0, 0, 252, 0, 252), (76, 237, 79, 241), 15, 1, 0),
        _Set(229, 198, 0, 1, (30, 18, 26, 31, 27, 31), (6, 0, 0, 252, 0, 252), (76, 315, 242, 237), 10, 0, 1),
        _Set(244, 179, 0, 1, (30, 22, 26, 31, 27, 31), (6, 0, 0, 252, 0, 252), (76, 126, 115, 237), 10, 2, 0),
        _Set(401, 200, 0, 78, (30, 31, 27, 18, 30, 26), (6, 252, 0, 0, 252, 0), (276, 153, 246, 89), 23, 2, 0),
    ),
    566: (  # Lv. 100 Battle Mode Single, round 8
        _Set(404, 134, 0, 1, (30, 1, 30, 31, 29, 31), (6, 0, 0, 252, 0, 252), (57, 58, 87, 156), 10, 2, 0),
        _Set(366, 186, 0, 1, (30, 31, 30, 1, 31, 31), (6, 252, 0, 0, 0, 252), (63, 89, 247, 0), 13, 0, 0),
        _Set(407, 179, 0, 1, (30, 1, 30, 31, 30, 31), (6, 0, 0, 252, 0, 252), (347, 58, 337, 94), 10, 1, 0),
        _Set(408, 191, 0, 1, (30, 1, 31, 31, 29, 31), (6, 0, 0, 252, 0, 252), (57, 87, 337, 94), 10, 0, 0),
        _Set(214, 170, 0, 16, (31, 31, 30, 1, 30, 31), (6, 252, 0, 0, 0, 252), (224, 89, 203, 179), 3, 0, 0),
        _Set(406, 200, 0, 16, (30, 31, 30, 1, 31, 31), (0, 252, 0, 0, 158, 100), (332, 245, 89, 349), 3, 2, 0),
    ),
    567: (  # Lv. 100 Battle Mode Double, round 1
        _Set(227, 179, 0, 3, (28, 28, 28, 28, 28, 28), (0, 6, 252, 0, 252, 0), (191, 92, 65, 46), 3, 1, 0),
        _Set(285, 198, 0, 1, (28, 28, 28, 28, 28, 28), (0, 252, 0, 6, 252, 0), (89, 330, 58, 46), 1, 0, 0),
        _Set(322, 141, 0, 3, (28, 28, 28, 28, 28, 28), (0, 6, 252, 0, 252, 0), (109, 92, 247, 105), 3, 0, 0),
        _Set(213, 134, 0, 3, (28, 28, 28, 28, 28, 28), (6, 0, 252, 0, 252, 0), (92, 213, 219, 156), 5, 1, 0),
        _Set(402, 196, 0, 3, (28, 28, 28, 28, 28, 28), (0, 0, 252, 252, 6, 0), (196, 58, 85, 182), 15, 2, 0),
        _Set(197, 200, 0, 3, (28, 28, 28, 28, 28, 28), (252, 0, 252, 0, 6, 0), (109, 92, 185, 236), 5, 0, 0),
    ),
    568: (  # Lv. 100 Battle Mode Double, round 2
        _Set(245, 134, 0, 16, (28, 28, 28, 28, 28, 28), (0, 0, 252, 252, 0, 6), (58, 56, 347, 156), 20, 2, 0),
        _Set(112, 183, 0, 69, (28, 28, 28, 28, 28, 28), (0, 252, 252, 0, 0, 6), (224, 89, 350, 182), 3, 0, 0),
        _Set(305, 186, 255, 1, (28, 28, 28, 28, 28, 28), (6, 252, 0, 0, 0, 252), (216, 332, 63, 98), 13, 1, 0),
        _Set(408, 191, 0, 1, (28, 28, 28, 28, 28, 28), (6, 0, 0, 252, 0, 252), (94, 85, 337, 58), 10, 0, 0),
        _Set(400, 198, 0, 1, (28, 28, 28, 28, 28, 28), (0, 252, 0, 0, 252, 6), (309, 89, 247, 182), 3, 2, 0),
        _Set(343, 200, 0, 14, (28, 28, 28, 28, 28, 28), (0, 0, 0, 252, 252, 6), (58, 127, 329, 182), 15, 1, 0),
    ),
    569: (  # Lv. 100 Battle Mode Double, round 3
        _Set(241, 179, 255, 1, (29, 29, 29, 29, 29, 29), (0, 0, 129, 0, 129, 252), (244, 89, 247, 216), 13, 1, 0),
        _Set(289, 134, 255, 70, (29, 29, 29, 29, 29, 29), (0, 0, 131, 0, 131, 248), (187, 247, 216, 156), 13, 0, 0),
        _Set(407, 221, 0, 1, (29, 29, 29, 29, 29, 29), (6, 0, 0, 0, 252, 252), (270, 115, 113, 94), 20, 1, 0),
        _Set(169, 198, 0, 1, (29, 29, 29, 29, 29, 29), (6, 252, 0, 0, 0, 252), (247, 332, 188, 109), 13, 0, 0),
        _Set(303, 141, 0, 1, (29, 29, 29, 29, 29, 29), (0, 252, 0, 0, 0, 252), (14, 318, 247, 182), 3, 2, 0),
        _Set(409, 183, 0, 1, (29, 29, 29, 29, 29, 29), (0, 0, 252, 252, 0, 6), (94, 87, 352, 182), 15, 2, 0),
    ),
    570: (  # Lv. 100 Battle Mode Double, round 4
        _Set(362, 134, 0, 69, (29, 29, 29, 29, 29, 29), (6, 0, 252, 0, 252, 0), (286, 182, 58, 89), 5, 1, 0),
        _Set(334, 179, 0, 2, (29, 29, 29, 29, 29, 29), (0, 252, 0, 252, 0, 6), (126, 89, 242, 337), 0, 0, 0),
        _Set(406, 198, 0, 2, (29, 29, 29, 29, 29, 29), (6, 0, 0, 252, 0, 252), (85, 58, 182, 337), 10, 2, 0),
        _Set(397, 221, 0, 2, (29, 29, 29, 29, 29, 29), (6, 252, 0, 0, 0, 252), (89, 332, 38, 280), 13, 1, 0),
        _Set(82, 183, 0, 2, (27, 27, 27, 30, 27, 30), (6, 0, 252, 252, 0, 0), (85, 86, 115, 237), 15, 2, 1),
        _Set(359, 187, 0, 2, (29, 29, 29, 29, 29, 29), (0, 252, 0, 252, 0, 6), (53, 143, 89, 337), 6, 1, 0),
    ),
    571: (  # Lv. 100 Battle Mode Double, round 5
        _Set(336, 200, 255, 65, (30, 30, 30, 20, 30, 30), (6, 0, 252, 0, 252, 0), (270, 280, 252, 182), 23, 1, 0),
        _Set(230, 187, 255, 67, (30, 20, 30, 30, 30, 30), (0, 0, 6, 252, 252, 0), (240, 56, 58, 225), 20, 0, 0),
        _Set(243, 179, 255, 64, (30, 11, 27, 30, 31, 30), (0, 0, 6, 252, 0, 252), (87, 242, 237, 182), 10, 2, 0),
        _Set(279, 196, 255, 64, (30, 20, 30, 30, 30, 30), (0, 0, 0, 252, 6, 252), (337, 348, 242, 197), 10, 0, 0),
        _Set(121, 198, 255, 64, (30, 20, 30, 30, 30, 30), (0, 0, 6, 252, 0, 252), (87, 58, 182, 56), 10, 2, 1),
        _Set(130, 141, 255, 66, (30, 30, 30, 10, 30, 31), (0, 252, 14, 0, 0, 244), (89, 216, 349, 237), 3, 0, 0),
    ),
    572: (  # Lv. 100 Battle Mode Double, round 6
        _Set(302, 141, 0, 18, (28, 27, 27, 26, 29, 29), (6, 252, 0, 0, 0, 252), (14, 332, 226, 182), 13, 1, 0),
        _Set(176, 221, 0, 3, (29, 25, 24, 25, 29, 28), (6, 0, 252, 0, 252, 0), (266, 113, 115, 227), 20, 0, 1),
        _Set(160, 198, 0, 2, (27, 29, 25, 27, 26, 29), (6, 252, 0, 0, 0, 252), (280, 163, 242, 56), 1, 0, 0),
        _Set(214, 170, 0, 2, (28, 28, 26, 9, 27, 29), (6, 252, 0, 0, 0, 252), (224, 89, 203, 179), 13, 0, 0),
        _Set(217, 134, 255, 2, (27, 29, 28, 10, 25, 28), (6, 252, 0, 0, 0, 252), (216, 332, 280, 156), 3, 1, 0),
        _Set(212, 196, 0, 1, (29, 28, 25, 5, 28, 29), (6, 252, 0, 0, 0, 252), (14, 226, 332, 318), 3, 0, 0),
    ),
    573: (  # Lv. 100 Battle Mode Double, round 7
        _Set(401, 217, 0, 60, (29, 29, 29, 29, 29, 29), (0, 252, 0, 0, 252, 6), (153, 241, 246, 182), 23, 2, 0),
        _Set(300, 141, 0, 61, (29, 29, 29, 29, 29, 29), (0, 252, 0, 158, 0, 100), (153, 252, 76, 247), 2, 0, 0),
        _Set(76, 183, 0, 1, (29, 29, 29, 29, 29, 29), (0, 252, 0, 0, 252, 6), (153, 182, 350, 89), 3, 0, 0),
        _Set(101, 186, 0, 2, (29, 29, 29, 29, 29, 29), (6, 252, 0, 0, 0, 252), (153, 85, 0, 0), 3, 2, 0),
        _Set(229, 180, 0, 1, (29, 29, 29, 29, 29, 29), (6, 0, 0, 252, 0, 252), (315, 76, 242, 182), 10, 1, 1),
        _Set(65, 221, 0, 1, (29, 29, 29, 29, 29, 29), (6, 0, 0, 252, 0, 252), (94, 7, 182, 8), 10, 1, 1),
    ),
    574: (  # Lv. 100 Battle Mode Double, round 8
        _Set(407, 200, 0, 16, (30, 1, 30, 31, 29, 31), (6, 0, 0, 252, 0, 252), (347, 58, 296, 337), 10, 1, 0),
        _Set(408, 191, 0, 1, (31, 2, 30, 31, 29, 31), (6, 0, 0, 252, 0, 252), (94, 337, 87, 76), 10, 0, 0),
        _Set(404, 179, 0, 1, (31, 3, 30, 31, 29, 31), (6, 0, 0, 252, 0, 252), (323, 58, 87, 182), 10, 2, 0),
        _Set(397, 198, 0, 1, (31, 4, 29, 31, 30, 31), (6, 0, 0, 252, 0, 252), (126, 337, 56, 242), 10, 1, 0),
        _Set(405, 221, 0, 1, (30, 31, 29, 5, 30, 31), (6, 252, 0, 0, 0, 252), (89, 246, 315, 182), 13, 2, 0),
        _Set(366, 186, 0, 1, (31, 31, 29, 6, 30, 31), (6, 252, 0, 0, 0, 252), (63, 89, 247, 0), 13, 0, 0),
    ),
}

assert all(len(team) == TEAM_SIZE for team in COLOSSEUM_ORRE_LV100_TEAMS.values())

# How each Colosseum team's AI plays, set out as XD's AI reads it. A DTAI row is 0x20 bytes:
#
#   0x00, 0x01   trait bits (`_TRAIT_BITS`)        0x0E  switch %              0x14, 0x15  type ids to weigh
#   0x04-0x0A    per-stat stage limits (0x66)      0x0F  item %                0x16, 0x17  their weights
#   0x0C, 0x0D   stage-total max / min             0x10  accuracy floor %      0x18, 0x1A  move kinds to weigh (u16)
#   0x11         both-actives-on-one-target (0)    0x12  low-HP %              0x1C, 0x1D  their weights
#   0x1E         random +-N on move scores         0x13  last-PP %
#
# Weights are percentages where 50 is neutral; type 9 and move kind 0 mean "none". The stage limits are read only by
# combos, and these teams have none, so they stay neutral; 0x11 stays 0.
_TRAIT_BITS: "dict[str, tuple[int, int]]" = {
    "random_lead": (0x00, 7), "lead_into_weakness": (0x00, 6), "send_in_listed_order": (0x00, 5),
    "ace_last": (0x00, 4), "key_member": (0x00, 3), "type_matchups": (0x00, 2), "abilities": (0x00, 1),
    "damage_estimates": (0x00, 0), "random_target": (0x01, 7), "random_move": (0x01, 6),
    "opening_move_bias": (0x01, 5), "follow_roles": (0x01, 4), "check_accuracy": (0x01, 3), "weigh_risk": (0x01, 2),
    "status_aware": (0x01, 1),
}
NO_TYPE = 9
NO_MOVE_KIND = 0
NEUTRAL = 50
_NEUTRAL_STAGE_LIMIT = 0x66


class AiStyle(NamedTuple):
    traits: "frozenset[str]"
    stage_max: int = 43
    stage_min: int = 38
    switch_pct: int = 100
    item_pct: int = 0
    accuracy_pct: int = 80
    low_hp_pct: int = 50
    last_pp_pct: int = 10
    spread: int = 2
    type_bias: "tuple[tuple[int, int], tuple[int, int]]" = ((NO_TYPE, NEUTRAL), (NO_TYPE, NEUTRAL))
    move_kind_bias: "tuple[tuple[int, int], tuple[int, int]]" = ((NO_MOVE_KIND, NEUTRAL), (NO_MOVE_KIND, NEUTRAL))


def dtai_row(style: AiStyle) -> bytes:
    """The 0x20-byte XD DTAI row that plays `style`."""
    row = bytearray(0x20)
    for trait in style.traits:
        at, bit = _TRAIT_BITS[trait]
        row[at] |= 1 << bit
    row[0x04:0x0B] = bytes((_NEUTRAL_STAGE_LIMIT,)) * 7
    row[0x0C], row[0x0D] = style.stage_max, style.stage_min
    row[0x0E], row[0x0F], row[0x10] = style.switch_pct, style.item_pct, style.accuracy_pct
    row[0x12], row[0x13], row[0x1E] = style.low_hp_pct, style.last_pp_pct, style.spread
    for i, ((type_id, type_weight), (kind, kind_weight)) in enumerate(zip(style.type_bias, style.move_kind_bias)):
        row[0x14 + i], row[0x16 + i] = type_id, type_weight
        struct.pack_into(">H", row, 0x18 + 2 * i, kind)
        row[0x1C + i] = kind_weight
    return bytes(row)


_PLAYS_WELL = frozenset({"key_member", "type_matchups", "abilities", "damage_estimates", "opening_move_bias",
                         "follow_roles", "check_accuracy", "status_aware"})
_SINGLES = AiStyle(_PLAYS_WELL | {"ace_last", "random_target"})
_DOUBLES = AiStyle(_PLAYS_WELL | {"lead_into_weakness"}, spread=8)

#: {Colosseum Trainer row: how its AI plays}.
COLOSSEUM_ORRE_LV100_AI_STYLES: "dict[int, AiStyle]" = {
    559: _SINGLES, 560: _SINGLES, 561: _SINGLES, 562: _SINGLES,
    563: _SINGLES._replace(stage_max=46, spread=0),
    564: _SINGLES, 565: _SINGLES, 566: _SINGLES,
    567: _DOUBLES._replace(stage_max=44),
    568: _DOUBLES._replace(spread=3),
    569: _DOUBLES, 570: _DOUBLES,
    571: _DOUBLES._replace(spread=3, accuracy_pct=91, low_hp_pct=20, type_bias=((4, 100), (NO_TYPE, NEUTRAL))),
    572: _DOUBLES._replace(stage_max=45, stage_min=39, spread=3),
    573: _DOUBLES._replace(traits=_DOUBLES.traits | {"weigh_risk"}, spread=2, accuracy_pct=100,
                          type_bias=((13, 0), (13, 0)), move_kind_bias=((6, 100), (7, 100))),
    574: AiStyle(_PLAYS_WELL | {"ace_last"}),
}

assert set(COLOSSEUM_ORRE_LV100_AI_STYLES) == set(COLOSSEUM_ORRE_LV100_TEAMS)


#: Every team in the pool, by key: "xd:<DeckData_Colosseum.bin trainer>" and "colo:<Colosseum Trainer row>".
TEAM_KEYS: "tuple[str, ...]" = tuple(
    [f"xd:{index}" for index in sorted(XD_ORRE_COLOSSEUM_TEAMS)]
    + [f"colo:{index}" for index in sorted(COLOSSEUM_ORRE_LV100_TEAMS)]
)


def team_species(key: str) -> "tuple[int, ...]":
    game, _, index = key.partition(":")
    if game == "xd":
        return XD_ORRE_COLOSSEUM_TEAMS[int(index)]
    return tuple(member.species for member in COLOSSEUM_ORRE_LV100_TEAMS[int(index)])


def seed_entry(key: str) -> dict:
    """What the patcher needs for one team. An XD team names its source row, which the patcher copies whole;
    a Colosseum team carries its sets and its AI as an XD DTAI row."""
    game, _, index = key.partition(":")
    if game == "xd":
        return {"key": key, "deck": SOURCE_DECK, "trainer": int(index), "species": list(team_species(key))}
    return {"key": key, "sets": [member.as_dict() for member in COLOSSEUM_ORRE_LV100_TEAMS[int(index)]],
            "ai_row": dtai_row(COLOSSEUM_ORRE_LV100_AI_STYLES[int(index)]).hex()}


#: Greevil's first fight: Shadow Lugia alone. ADDENDUM 424 leaves it exactly as the game has it.
GREEVIL_LUGIA_TRAINER = 199


#: Greevil's final story battle -- his second row, the six Shadows right after the Lugia fight. The goal fires on it.
GREEVIL_FINAL_TRAINER = 200
#: His post-game rematch (an ordinary team of six at 50), the row the game lets you re-fight.
GREEVIL_REMATCH_TRAINER = 201
#: Nightmare Greevil's rows: the final battle and the rematch. The final battle's Shadows are relocated like any other
#: removed Shadow (`shadow_removal_trainers`).
NIGHTMARE_GREEVIL_TRAINERS = frozenset({GREEVIL_FINAL_TRAINER, GREEVIL_REMATCH_TRAINER})


def nightmare_trainer_indices() -> "frozenset[int]":
    """The Citadark Isle trainer rows that take a team: 168..201 except Greevil's Lugia fight -- 33."""
    return citadark_trainer_indices() - {GREEVIL_LUGIA_TRAINER}


#: ADDENDUM 431: Greevil's two Shadow fights -- Shadow Lugia alone (199) and his six Shadows (200).
GREEVIL_SHADOW_TRAINERS = frozenset({GREEVIL_LUGIA_TRAINER, 200})


def shadow_removal_trainers(nightmare_citadark: bool, remove_citadark: bool, remove_greevil: bool,
                            nightmare_greevil: bool = False, admins_only: bool = False) -> "frozenset[int]":
    """ADDENDUM 431: the trainers whose Shadows leave them this seed. Nightmare Citadark takes every Citadark
    trainer but Lugia's fight; Nightmare Greevil his final battle's; Remove Citadark Shadows every one but Greevil's;
    Remove Greevil Shadows his two; Citadark Admins Only every Citadark trainer that is not an admin."""
    out: "set[int]" = set()
    if admins_only:
        from .citadark_admins import REMOVED_TRAINER_INDICES
        out |= REMOVED_TRAINER_INDICES
    if nightmare_citadark:
        out |= nightmare_trainer_indices()
    if nightmare_greevil:
        out |= {GREEVIL_FINAL_TRAINER}
    if remove_citadark:
        out |= citadark_trainer_indices() - GREEVIL_SHADOW_TRAINERS - {GREEVIL_REMATCH_TRAINER}
    if remove_greevil:
        out |= GREEVIL_SHADOW_TRAINERS
    return frozenset(out)


def removed_shadow_ddpks(trainers: "frozenset[int] | None" = None) -> "dict[int, int]":
    """{ddpk_index: holder trainer index} for every vanilla Shadow whose EARLIEST holder is in `trainers`
    (default: the Nightmare Citadark set) -- by holder, not by `shadow_regions`' label join, which files nine of
    them under earlier regions. These leave their trainer and are relocated (`plan_relocations`)."""
    citadark = nightmare_trainer_indices() if trainers is None else frozenset(trainers)
    return {ddpk: holder.trainer_index for ddpk, holder in vanilla_shadow_holders().items()
            if holder.trainer_index in citadark}


def removed_shadow_records(trainers: "frozenset[int] | None" = None) -> "list[dict]":
    """The `deckdata_dark_pokemon.json` rows (ddpk_index, dpkm_index, species, shadow_level) of the removed
    Shadows, ascending by DDPK index. Empty when the data file is missing from this build."""
    removed = removed_shadow_ddpks(trainers)
    rows = load_json_data_file("deckdata_dark_pokemon.json") or []
    return sorted((row for row in rows if row.get("ddpk_index") in removed), key=lambda row: row["ddpk_index"])


def removed_shadow_dpkm_indices(trainers: "frozenset[int] | None" = None) -> "frozenset[int]":
    return frozenset(int(row["dpkm_index"]) for row in removed_shadow_records(trainers))


def vacated_slots(trainers: "frozenset[int]", replaced: "frozenset[int]") -> "list[dict]":
    """ADDENDUM 431: every Shadow slot on `trainers` that a Nightmare team does NOT replace -- it keeps an
    ordinary copy of its Pokemon while the Shadow itself moves. [{trainer_index, slot, ddpk_index}]."""
    from .trainer_roster import TRAINERS

    out = []
    for trainer in TRAINERS:
        if trainer["index"] not in trainers or trainer["index"] in replaced:
            continue
        for member in trainer["team"]:
            if member.get("kind") == "DDPK":
                out.append({"trainer_index": trainer["index"], "slot": int(member["slot"]),
                            "ddpk_index": int(member["ddpk_index"])})
    return sorted(out, key=lambda v: (v["trainer_index"], v["slot"]))


def removed_shadow_national_dex(trainers: "frozenset[int] | None" = None) -> "frozenset[int]":
    """The removed Shadows' VANILLA species as National Dex numbers -- the key `shadow_pokemon_list.json` and
    the client's static Shadow table use. Vanilla Shadow species are one-to-one with encounters."""
    from ..tools.xd_species_index import national_dex_for

    out = set()
    for row in removed_shadow_records(trainers):
        dex = national_dex_for(int(row["species"]))
        if dex is not None:
            out.add(dex)
    return frozenset(out)


def plan_relocations(rng: random.Random, free_slot_census: "list[dict]", excluded_trainer_indices: "frozenset[int]",
                     level_multiplier: float = 1.0, trainers: "frozenset[int] | None" = None) -> "list[dict]":
    """Where each displaced Shadow goes: `[{"trainer_index": host, "shadows": [{"ddpk_index", "dpkm_index",
    "species", "level"}, ...]}]`, ascending by host.

    Hosts are `free_slot_census` rows (`real_trainer_free_slot_census()`: trainer_index, free_slots, avg_level)
    outside `excluded_trainer_indices` -- the caller passes the expansion's own fence (missable and re-fightable
    trainers, Mt. Battle when excluded) plus all of Citadark -- and outside `PERMANENTLY_EXCLUDED_TRAINER_INDICES`.
    Filled round-robin over a shuffled order, one Shadow per host per pass, so they spread as widely as they can.
    A Shadow joins at its host's average team level times `level_multiplier`, the expansion's rule. Raises rather
    than dropping a Shadow when hosts run out."""
    from .real_trainer_data import PERMANENTLY_EXCLUDED_TRAINER_INDICES

    records = list(removed_shadow_records(trainers))
    if not records:
        return []
    hosts = [row for row in free_slot_census
             if row["trainer_index"] not in excluded_trainer_indices
             and row["trainer_index"] not in PERMANENTLY_EXCLUDED_TRAINER_INDICES
             and int(row["free_slots"]) > 0]
    if sum(int(row["free_slots"]) for row in hosts) < len(records):
        raise ValueError(f"only {sum(int(r['free_slots']) for r in hosts)} free slots on eligible trainers for "
                         f"{len(records)} relocated Shadows")
    hosts = sorted(hosts, key=lambda row: row["trainer_index"])
    rng.shuffle(hosts)
    rng.shuffle(records)
    remaining = {row["trainer_index"]: int(row["free_slots"]) for row in hosts}
    average = {row["trainer_index"]: float(row["avg_level"]) for row in hosts}
    placed: "dict[int, list[dict]]" = {}
    cursor = 0
    while cursor < len(records):
        for row in hosts:
            if cursor >= len(records):
                break
            host = row["trainer_index"]
            if remaining[host] <= 0:
                continue
            remaining[host] -= 1
            record = records[cursor]
            cursor += 1
            placed.setdefault(host, []).append({
                "ddpk_index": int(record["ddpk_index"]), "dpkm_index": int(record["dpkm_index"]),
                "species": int(record["species"]),
                "level": max(1, min(100, round(average[host] * level_multiplier))),
            })
    return [{"trainer_index": host, "shadows": sorted(shadows, key=lambda s: s["ddpk_index"])}
            for host, shadows in sorted(placed.items())]


def assign_teams(rng: random.Random, trainer_indices=None) -> "dict[int, str]":
    """{citadark trainer index: team key}, every team different: every trainer has a unique team. 44 teams for 33
    trainers, so eleven sit out each seed."""
    trainers = sorted(nightmare_trainer_indices() if trainer_indices is None else trainer_indices)
    if len(trainers) > len(TEAM_KEYS):
        raise ValueError(f"{len(trainers)} trainers but only {len(TEAM_KEYS)} Nightmare teams")
    return dict(zip(trainers, rng.sample(list(TEAM_KEYS), len(trainers))))
