"""ADDENDUM 429 (2026-10-06) -- Trade Evolutions By Level.

An option evolves trade evolutions by level-up instead, with the same logic as the trainer team evolutions.

"The same logic" is `evolution_data.TRAINER_EVOLUTIONS` (ADDENDUM 425): the level a trainer's Pokemon is fielded
evolved, and a seeded coin between two branches. The patch rewrites the evolution entries in common_rel's species
table (0x124-byte rows, five 6-byte entries at +0xA6: method u8, pad u8, condition u16, target u16) so the
player's own Pokemon follow the same thresholds:

  * plain trade (method 5) and trade holding an item (method 6) become LEVEL (method 4) at the trainer level:
    Kadabra, Machoke, Graveler, Haunter at 37; Onix, Scyther, Porygon at 30; Seadra at 40; Poliwhirl ->
    Politoed at 36 (its Water Stone -> Poliwrath entry is untouched, so a stone still gives Poliwrath).
  * a TWO-WAY branch uses the game's own Wurmple rule instead of a coin: method 11 is "level reached and the
    personality value's high half mod 10 is below 5", method 12 the other half (`getEvoPokemonLevelUp`'s cases
    11/12 call `getUniqueRandom`, which is exactly `(PID >> 16) % 10`; nothing in them is species-specific).
    Clamperl -> Huntail / Gorebyss at 30, and Slowpoke -> Slowbro / Slowking at 37 -- so half of all Slowpoke
    become Slowking where vanilla made every one a Slowbro, which is what a trainer's Slowpoke already does.

The level-up check walks all five entries and the LAST match wins, so each branch pair is made exclusive rather
than left to order. Every entry is checked against its vanilla bytes before it is written. Import-free, so the
standalone patcher can load it by path; the test holds every level to TRAINER_EVOLUTIONS.
"""
from __future__ import annotations

EVOLUTION_ENTRY_OFFSET = 0xA6
EVOLUTION_ENTRY_SIZE = 6
LEVEL = 4
TRADE = 5
TRADE_ITEM = 6
STONE = 7
PERSONALITY_LOW = 11      # Silcoon's rule: (PID >> 16) % 10 < 5
PERSONALITY_HIGH = 12     # Cascoon's rule: >= 5
BEAUTY = 15               # Feebas: Beauty at least the condition, which nothing in XD can raise

#: (internal species, entry slot, vanilla (method, condition, target), new (method, condition, target)).
#: Vanilla values read off XD's own species table; each new condition is that species' TRAINER_EVOLUTIONS level.
EVOLUTION_EDITS: "tuple[tuple[int, int, tuple[int, int, int], tuple[int, int, int]], ...]" = (
    (64, 0, (TRADE, 0, 65), (LEVEL, 37, 65)),                         # Kadabra -> Alakazam
    (67, 0, (TRADE, 0, 68), (LEVEL, 37, 68)),                         # Machoke -> Machamp
    (75, 0, (TRADE, 0, 76), (LEVEL, 37, 76)),                         # Graveler -> Golem
    (93, 0, (TRADE, 0, 94), (LEVEL, 37, 94)),                         # Haunter -> Gengar
    (95, 0, (TRADE_ITEM, 199, 208), (LEVEL, 30, 208)),                # Onix -> Steelix (Metal Coat)
    (123, 0, (TRADE_ITEM, 199, 212), (LEVEL, 30, 212)),               # Scyther -> Scizor (Metal Coat)
    (117, 0, (TRADE_ITEM, 201, 230), (LEVEL, 40, 230)),               # Seadra -> Kingdra (Dragon Scale)
    (137, 0, (TRADE_ITEM, 218, 233), (LEVEL, 30, 233)),               # Porygon -> Porygon2 (Up-Grade)
    (61, 1, (TRADE_ITEM, 187, 186), (LEVEL, 36, 186)),                # Poliwhirl -> Politoed (King's Rock)
    (79, 0, (LEVEL, 37, 80), (PERSONALITY_LOW, 37, 80)),              # Slowpoke -> Slowbro, half
    (79, 1, (TRADE_ITEM, 187, 199), (PERSONALITY_HIGH, 37, 199)),     # Slowpoke -> Slowking, the other half
    (373, 0, (TRADE_ITEM, 192, 374), (PERSONALITY_LOW, 30, 374)),     # Clamperl -> Huntail
    (373, 1, (TRADE_ITEM, 193, 375), (PERSONALITY_HIGH, 30, 375)),    # Clamperl -> Gorebyss
    (328, 0, (BEAUTY, 170, 329), (LEVEL, 30, 329)),                   # Feebas -> Milotic (Beauty 170)
)

#: Species that gain a SECOND level-up evolution ahead of them once these are level-ups -- the Candy Box
#: (ADDENDUM 427) stops them at 99 so the last one still triggers. Poliwag, Abra, Machop, Geodude, Gastly, Horsea.
NEW_TWO_STAGE_LEVEL_EVOLVERS: "tuple[int, ...]" = (60, 63, 66, 74, 92, 116)


FRIENDSHIP = 1

# ADDENDUM 451. Friendship evolutions are just by level. Always on, no option. XD has seven
# friendship (method 1) entries -- Espeon and Umbreon are the Sun/Moon Shard key items (method 16) here, not
# friendship -- and each becomes LEVEL at its TRAINER_EVOLUTIONS threshold: the babies at 15, Golbat at 35, Chansey
# at 40. Azurill -> Marill at 15 then Marill -> Azumarill at 18, as a trainer's would.
FRIENDSHIP_EVOLUTION_EDITS: "tuple[tuple[int, int, tuple[int, int, int], tuple[int, int, int]], ...]" = (
    (42, 0, (FRIENDSHIP, 0, 169), (LEVEL, 35, 169)),                  # Golbat -> Crobat
    (113, 0, (FRIENDSHIP, 0, 242), (LEVEL, 40, 242)),                 # Chansey -> Blissey
    (172, 0, (FRIENDSHIP, 0, 25), (LEVEL, 15, 25)),                   # Pichu -> Pikachu
    (173, 0, (FRIENDSHIP, 0, 35), (LEVEL, 15, 35)),                   # Cleffa -> Clefairy
    (174, 0, (FRIENDSHIP, 0, 39), (LEVEL, 15, 39)),                   # Igglybuff -> Jigglypuff
    (175, 0, (FRIENDSHIP, 0, 176), (LEVEL, 15, 176)),                 # Togepi -> Togetic
    (350, 0, (FRIENDSHIP, 0, 183), (LEVEL, 15, 183)),                 # Azurill -> Marill
)


def evolution_edits(trade_by_level: bool = True,
                    friendship_by_level: bool = False) -> "tuple[tuple[int, int, tuple[int, int, int], tuple[int, int, int]], ...]":
    """The species-table edits to write: trade evolutions (the option), friendship evolutions (always, ADDENDUM 451)."""
    return (EVOLUTION_EDITS if trade_by_level else ()) + (FRIENDSHIP_EVOLUTION_EDITS if friendship_by_level else ())
