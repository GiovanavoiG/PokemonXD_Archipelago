"""Gen I-III level-up evolution table, used to pick the highest evolution a randomized level allows.

Level-up evolutions only, one deterministic target per species; no entry means "does not evolve" here, which
excludes stone, trade and friendship evolutions and branches with no single target from species+level alone
(Tyrogue, Wurmple's line, Feebas, Eevee) -- `team_shuffle.Species.evolves_into` holds one target.

National Dex numbers throughout, converted by `national_dex_to_internal_level_evolutions()` because this
game's internal indices shift above 251. Standard public game data, not ISO-extracted and not hand-checked:
a threshold that disagrees with the game is a data fix here.
"""

from __future__ import annotations

# {from_dex: (to_dex, min_level)}
NATIONAL_DEX_LEVEL_EVOLUTIONS: dict[int, tuple[int, int]] = {
    # Gen I
    1: (2, 16), 2: (3, 32),
    4: (5, 16), 5: (6, 36),
    7: (8, 16), 8: (9, 36),
    10: (11, 7), 11: (12, 10),
    13: (14, 7), 14: (15, 10),
    16: (17, 18), 17: (18, 36),
    19: (20, 20),
    21: (22, 20),
    23: (24, 22),
    27: (28, 22),
    # Only the Nidoran lines' FIRST stage is level-gated; the second needs a Moon Stone and is
    # correctly absent.
    29: (30, 16),
    32: (33, 16),
    41: (42, 22),
    43: (44, 21),
    46: (47, 24),
    48: (49, 31),
    50: (51, 26),
    52: (53, 28),
    54: (55, 33),
    56: (57, 28),
    60: (61, 25),
    63: (64, 16),
    66: (67, 28),
    69: (70, 21),
    72: (73, 30),
    74: (75, 25),
    77: (78, 40),
    79: (80, 37),
    81: (82, 30),
    84: (85, 31),
    86: (87, 34),
    88: (89, 38),
    92: (93, 25),
    96: (97, 26),
    98: (99, 28),
    100: (101, 30),
    104: (105, 28),
    109: (110, 35),
    111: (112, 42),
    116: (117, 32),
    118: (119, 33),
    129: (130, 20),
    138: (139, 40),
    140: (141, 40),
    147: (148, 30), 148: (149, 55),

    # Gen II
    152: (153, 16), 153: (154, 32),
    155: (156, 14), 156: (157, 36),
    158: (159, 18), 159: (160, 30),
    161: (162, 15),
    163: (164, 20),
    165: (166, 18),
    167: (168, 22),
    170: (171, 27),
    177: (178, 25),
    179: (180, 15), 180: (181, 30),
    183: (184, 18),
    187: (188, 18), 188: (189, 27),
    194: (195, 20),
    204: (205, 31),
    209: (210, 23),
    216: (217, 30),
    218: (219, 38),
    220: (221, 33),
    223: (224, 25),
    228: (229, 24),  # Houndour -> Houndoom, the player's own example
    231: (232, 25),
    238: (124, 30),  # Smoochum -> Jynx
    239: (125, 30),  # Elekid -> Electabuzz
    240: (126, 30),  # Magby -> Magmar
    246: (247, 30), 247: (248, 55),
    360: (202, 15),  # Wynaut -> Wobbuffet

    # Gen III
    252: (253, 16), 253: (254, 36),
    255: (256, 16), 256: (257, 36),
    258: (259, 16), 259: (260, 36),
    261: (262, 18),
    263: (264, 20),
    266: (267, 10),
    268: (269, 10),
    270: (271, 14),
    273: (274, 14),
    276: (277, 22),
    278: (279, 25),
    280: (281, 20), 281: (282, 30),
    283: (284, 22),
    285: (286, 23),
    287: (288, 18), 288: (289, 36),
    290: (291, 20),
    293: (294, 20), 294: (295, 40),
    296: (297, 24),
    304: (305, 32), 305: (306, 42),
    307: (308, 37),
    309: (310, 26),
    316: (317, 26),
    318: (319, 30),
    320: (321, 40),
    322: (323, 33),
    325: (326, 32),
    328: (329, 35), 329: (330, 45),
    331: (332, 32),
    333: (334, 35),
    339: (340, 30),
    341: (342, 30),
    343: (344, 36),
    # Lileep -> Cradily is level 40, like its fossil counterpart Anorith -> Armaldo below.
    345: (346, 40),
    347: (348, 40),
    353: (354, 37),
    355: (356, 37),
    361: (362, 42),
    363: (364, 32), 364: (365, 44),
    371: (372, 30), 372: (373, 50),
    374: (375, 20), 375: (376, 45),
}


def national_dex_to_internal_level_evolutions() -> dict[int, tuple[int, int]]:
    """`NATIONAL_DEX_LEVEL_EVOLUTIONS` in this game's internal species-index space, the one
    `Species.species_id` uses. An entry with no internal-index mapping is skipped rather than raising: a data
    gap trims a feature, it never crashes generation."""
    from ..tools.xd_species_index import NATIONAL_DEX_TO_INTERNAL_INDEX

    result: dict[int, tuple[int, int]] = {}
    for from_dex, (to_dex, level) in NATIONAL_DEX_LEVEL_EVOLUTIONS.items():
        from_internal = NATIONAL_DEX_TO_INTERNAL_INDEX.get(from_dex)
        to_internal = NATIONAL_DEX_TO_INTERNAL_INDEX.get(to_dex)
        if from_internal is not None and to_internal is not None:
            result[from_internal] = (to_internal, level)
    return result


# ADDENDUM 425: the evolutions a trainer's Pokemon could never take. Player: "some pokemon are NOT evolved on trainer
# teams despite being at a suitable level to evolve." The table above holds level-up evolutions only, and it agrees
# with the game's own species data on every one (checked against XD's live table, `pokemonDataBiosGetPtr`, method 4,
# all 135 entries). What it could not express were the 38 species whose next stage takes a stone, a trade, a held
# item, friendship, beauty or a branch -- so a level-60 Kadabra, Pikachu, Golbat, Haunter or Eevee stayed one.
# These are TRAINER thresholds, the level from which a trainer's Pokemon is fielded evolved; nothing here changes
# how the player's own Pokemon evolve. Several targets for one species is a branch, chosen per Pokemon by the
# world's seeded RNG.
TRAINER_EVOLUTIONS: "dict[int, list[tuple[int, int]]]" = {
    # Friendship: the babies early, the two adult ones late.
    172: [(25, 15)], 173: [(35, 15)], 174: [(39, 15)], 175: [(176, 15)], 298: [(183, 15)],
    42: [(169, 35)],            # Golbat -> Crobat
    113: [(242, 40)],           # Chansey -> Blissey
    # Trade.
    64: [(65, 37)], 67: [(68, 37)], 75: [(76, 37)], 93: [(94, 37)],
    # Trade holding an item.
    95: [(208, 30)], 123: [(212, 30)], 117: [(230, 40)], 137: [(233, 30)],
    366: [(367, 30), (368, 30)],                      # Clamperl -> Huntail / Gorebyss
    79: [(199, 37)],                                  # Slowpoke -> Slowking, beside the level-37 Slowbro
    # A stone, on a first stage.
    25: [(26, 30)], 35: [(36, 30)], 37: [(38, 30)], 39: [(40, 30)], 58: [(59, 30)], 90: [(91, 30)],
    102: [(103, 30)], 120: [(121, 30)], 191: [(192, 25)], 300: [(301, 30)],
    133: [(134, 30), (135, 30), (136, 30), (196, 30), (197, 30)],   # Eevee
    # A stone, on a middle stage.
    30: [(31, 36)], 33: [(34, 36)], 70: [(71, 36)], 271: [(272, 36)], 274: [(275, 36)],
    44: [(45, 36), (182, 36)],                        # Gloom -> Vileplume / Bellossom
    61: [(62, 36), (186, 36)],                        # Poliwhirl -> Poliwrath / Politoed
    # Branches decided by something other than the level.
    236: [(106, 20), (107, 20), (237, 20)],           # Tyrogue, by its stats
    265: [(266, 7), (268, 7)],                        # Wurmple, by its personality value
    349: [(350, 30)],                                 # Feebas, by beauty
}


def national_dex_to_internal_trainer_evolutions() -> "dict[int, list[tuple[int, int]]]":
    """Every evolution a trainer's Pokemon may take, in internal indices: {from: [(to, level), ...]}, the level-up
    table's entry first, then `TRAINER_EVOLUTIONS`'. Unmapped entries are skipped, as above."""
    from ..tools.xd_species_index import NATIONAL_DEX_TO_INTERNAL_INDEX

    merged: "dict[int, list[tuple[int, int]]]" = {}
    for from_dex, (to_dex, level) in NATIONAL_DEX_LEVEL_EVOLUTIONS.items():
        merged.setdefault(from_dex, []).append((to_dex, level))
    for from_dex, options in TRAINER_EVOLUTIONS.items():
        merged.setdefault(from_dex, []).extend(options)
    result: "dict[int, list[tuple[int, int]]]" = {}
    for from_dex, options in merged.items():
        from_internal = NATIONAL_DEX_TO_INTERNAL_INDEX.get(from_dex)
        if from_internal is None:
            continue
        mapped = [(NATIONAL_DEX_TO_INTERNAL_INDEX.get(to_dex), level) for to_dex, level in options]
        mapped = [(to, level) for to, level in mapped if to is not None]
        if mapped:
            result[from_internal] = mapped
    return result
