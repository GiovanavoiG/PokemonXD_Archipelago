"""
Mt. Battle (`DeckData_Hundred.bin`) trainer census for Enhanced Difficulty (2026-09-09, ADDENDUM 93).

Separate from `real_trainer_data.py` because the data is separate: Mt. Battle's trainers live in their own
`deck_archive.fsys` entry with its OWN `trainer_index` (DTNR position) and `dpkm_index` numbering, starting
back at 1 and 0, so `DeckData_Hundred.bin` trainer_index 3 and `DeckData_Story.bin` trainer_index 3 are
unrelated trainers on unrelated bytes. Never merge an index from this module with one from
`real_trainer_data.py`, and never pass this census into a call that also receives Story data or Story's own
`PERMANENTLY_EXCLUDED_TRAINER_INDICES` -- ADDENDUM 92 nearly shipped `MT_BATTLE_TRAINER_INDICES` populated
with Hundred indices, which would have silently excluded Story trainers 1-100 instead.

`data/mtbattle_trainer_census.json` was read off the real vanilla disc (`iso_bridge.py`'s `iso_read`, not the
AP-patched copy) through `iso_patcher.parse_fsys()` and `xd_deck_format.DeckFile.all_trainers()`, the same
extraction used for `data/deckdata_story_trainers.json`, and live-verified against 3 real Dolphin-bridge
battles (Mt. Battle #1-3, matched by exact species pair plus battle order equal to ascending DTNR index
order). A team member's `species` is this game's INTERNAL index, not National Dex;
`species_national_dex`/`species_name` ride along for convenience but only `species` is written back.

Structural facts from ADDENDUM 92, relied on below: exactly 100 non-empty trainers, DTNR indices 1-100 with
no gaps; levels run 9 (index 1) to 70 (index 100); every team slot is an ordinary DPKM Pokemon, zero DDPK
slots anywhere. That is why there is no Shadow-slot exclusion below, and why Shadow Pokemon Expansion is
never pointed at this table -- there is no precedent here for what a Shadow team member looks like.
"""

from __future__ import annotations

from . import load_json_data_file

# Every real Mt. Battle DTNR trainer_index, in DeckData_Hundred.bin's OWN namespace (ADDENDUM 92: sequential
# 1-100, no gaps, no empty slots). Passed by __init__.py's generate_output() as `excluded_trainer_indices`
# to `build_enhanced_difficulty_plan()` when `ExcludeMtBattleTrainers` is on, so every Mt. Battle trainer is
# skipped for new-member padding; existing members still get the flat level boost, because that argument
# only ever gates padding.
MT_BATTLE_ALL_TRAINER_INDICES: frozenset[int] = frozenset(range(1, 101))

# Unconditional and permanent, independent of any YAML option: generate_output() only ever calls
# `build_shadow_expansion_plans()` against `real_trainer_data.real_trainer_free_slot_census()`, never
# against `mtbattle_team_census()` below. Nothing imports this for a runtime check -- it is a greppable
# statement of the decision, so a future change that wires Mt. Battle into Shadow expansion has something
# concrete to find and reconsider.
MT_BATTLE_PERMANENTLY_EXCLUDED_FROM_SHADOW_EXPANSION: bool = True

# ADDENDUM 94. Mt. Battle trainer_index 1's live-confirmed surname (ADDENDUM 92's bridge battle #1: MIRU,
# Wurmple + Wingull). Battle order is confirmed equal to ascending DTNR index order with no separate lookup
# table, and Mt. Battle Enhanced Difficulty edits only team composition and levels, never a class or name,
# so this stays their identity whatever the YAML says. Client.py arms a defeat count on it: MIRU plus 99
# more ordinary-trainer defeats is the 100th fight, the facility's 100 being sequential and back-to-back.
# No live "inside Mt. Battle" signal exists, so it assumes nothing else is battled in between and that MIRU
# is fought fresh this client session; `!goal` is the manual fallback.
MT_BATTLE_FIRST_TRAINER_SURNAME: str = "MIRU"
MT_BATTLE_TOTAL_TRAINER_COUNT: int = 100

# ADDENDUM 95, corrected by ADDENDUM 145. Serebii named trainer_index 100 "Mt. Battle Master Somek", and
# index 100's team here is Dusclops/Latios/Latias/Salamence/Metagross/Slaking, an exact six-species match to
# that listing -- so the TRAINER was identified correctly and the NAME was not. Decoding all 100 `name_id`s
# through `common_rel`'s string table gives 96-100 as SIVIL / FLOSTIN / TETIL / LIBAL / BATTLUS, with SOMEK
# nowhere among the 100; the same pass reproduces MIRU / CRIDEL / BARDO, which ADDENDUM 92 live-confirmed.
# Both spellings are kept: BATTLUS is what the player's ISO says, SOMEK costs nothing, and goal detection is
# a one-way latch. Client.py compares case-insensitively, because this capitalisation was never
# live-confirmed the way MIRU was.
MT_BATTLE_FINAL_TRAINER_SURNAMES: tuple[str, ...] = ("BATTLUS", "SOMEK")

# Kept for callers that predate the tuple. Now the ISO-backed spelling.
MT_BATTLE_FINAL_TRAINER_SURNAME: str = MT_BATTLE_FINAL_TRAINER_SURNAMES[0]


# MT. BATTLE TRAINER NAMES (ADDENDUM 161). The client identifies a trainer only by the surname the battle
# roster reports, so letting ExcludeMtBattleTrainers control defeat checks needs names, not `name_id`s.
# Decoded from the player's own ISO through `common_rel`'s string table, the same pass that produced
# `trainer_roster.py`'s 232 story names. All 100 are distinct.
#
# MIRU, CRIDEL and BARDO are Mt. Battle 1/2/3 AND story indices 30/31/32 with the same `name_id`s (ADDENDUM
# 145) -- Mt. Battle Area 1 is story content, so they are the same three characters. They are deliberately
# not in `MT_BATTLE_ONLY_SURNAMES`: excluding them would stop the story encounter counting too.
MT_BATTLE_TRAINER_NAMES: dict[int, str] = {
    1: 'MIRU',
    2: 'CRIDEL',
    3: 'BARDO',
    4: 'ROBELL',
    5: 'KABIN',
    6: 'EZELLA',
    7: 'HORBIT',
    8: 'ELOFF',
    9: 'DIBSIN',
    10: 'VANDER',
    11: 'DABIL',
    12: 'CIDLOR',
    13: 'GRATIN',
    14: 'HARDIG',
    15: 'GOLING',
    16: 'JEOL',
    17: 'ECHART',
    18: 'DELF',
    19: 'DOLAM',
    20: 'ELDOF',
    21: 'GRESTLY',
    22: 'FOLOP',
    23: 'KWANE',
    24: 'NAPOL',
    25: 'KOIYT',
    26: 'ATILL',
    27: 'METSON',
    28: 'JESPON',
    29: 'MOPAR',
    30: 'TARIA',
    31: 'ATLES',
    32: 'NIVEN',
    33: 'FOPAW',
    34: 'PETIL',
    35: 'NEVAH',
    36: 'SELOR',
    37: 'PIXEN',
    38: 'EDIN',
    39: 'ROZE',
    40: 'BOYDEN',
    41: 'HOMBOL',
    42: 'JILER',
    43: 'CARLON',
    44: 'KUXOR',
    45: 'LESK',
    46: 'MOBID',
    47: 'BLIST',
    48: 'KNOOK',
    49: 'BURDON',
    50: 'CALUS',
    51: 'DOOST',
    52: 'JIMER',
    53: 'CREX',
    54: 'FEEPLY',
    55: 'JACEN',
    56: 'DIBEL',
    57: 'KEVY',
    58: 'GABSEN',
    59: 'DEGIN',
    60: 'HAMPY',
    61: 'MELIN',
    62: 'GIBSON',
    63: 'IDLON',
    64: 'HOBOL',
    65: 'KELLER',
    66: 'EBILO',
    67: 'TULON',
    68: 'OKOR',
    69: 'EBZOR',
    70: 'NOCON',
    71: 'ORDES',
    72: 'OVUN',
    73: 'ADESON',
    74: 'ROBIT',
    75: 'NOXON',
    76: 'RELEO',
    77: 'CARK',
    78: 'MINOT',
    79: 'LASK',
    80: 'NADAY',
    81: 'HOLS',
    82: 'ALBAH',
    83: 'GINNER',
    84: 'COPIN',
    85: 'KOREN',
    86: 'LAKS',
    87: 'KIPPEN',
    88: 'NASOM',
    89: 'NIMBLIS',
    90: 'RAGEN',
    91: 'NEWIN',
    92: 'ROBEN',
    93: 'RILLIAN',
    94: 'SOLOG',
    95: 'SAKEN',
    96: 'SIVIL',
    97: 'FLOSTIN',
    98: 'TETIL',
    99: 'LIBAL',
    100: 'BATTLUS'
}

# The surnames that belong to Mt. Battle and nothing else -- 97 of the 100. The client adds these to
# `TrainerBattleDefeatTracker.poll`'s `exclude_surnames` when ExcludeMtBattleTrainers is on, so a Mt. Battle
# win stops advancing the cumulative "Defeat N Trainers" counter. Same mechanism that already keeps the
# player's own party out of the count (ADDENDUM 135).
MT_BATTLE_ONLY_SURNAMES: frozenset[str] = frozenset({
    'ADESON', 'ALBAH', 'ATILL', 'ATLES', 'BATTLUS', 'BLIST', 'BOYDEN', 'BURDON', 'CALUS', 'CARK',
    'CARLON', 'CIDLOR', 'COPIN', 'CREX', 'DABIL', 'DEGIN', 'DELF', 'DIBEL', 'DIBSIN', 'DOLAM', 'DOOST',
    'EBILO', 'EBZOR', 'ECHART', 'EDIN', 'ELDOF', 'ELOFF', 'EZELLA', 'FEEPLY', 'FLOSTIN', 'FOLOP', 'FOPAW',
    'GABSEN', 'GIBSON', 'GINNER', 'GOLING', 'GRATIN', 'GRESTLY', 'HAMPY', 'HARDIG', 'HOBOL', 'HOLS',
    'HOMBOL', 'HORBIT', 'IDLON', 'JACEN', 'JEOL', 'JESPON', 'JILER', 'JIMER', 'KABIN', 'KELLER', 'KEVY',
    'KIPPEN', 'KNOOK', 'KOIYT', 'KOREN', 'KUXOR', 'KWANE', 'LAKS', 'LASK', 'LESK', 'LIBAL', 'MELIN',
    'METSON', 'MINOT', 'MOBID', 'MOPAR', 'NADAY', 'NAPOL', 'NASOM', 'NEVAH', 'NEWIN', 'NIMBLIS', 'NIVEN',
    'NOCON', 'NOXON', 'OKOR', 'ORDES', 'OVUN', 'PETIL', 'PIXEN', 'RAGEN', 'RELEO', 'RILLIAN', 'ROBELL',
    'ROBEN', 'ROBIT', 'ROZE', 'SAKEN', 'SELOR', 'SIVIL', 'SOLOG', 'TARIA', 'TETIL', 'TULON', 'VANDER'
})

# The three shared with the story roster, named explicitly so the reason they are absent above is greppable.
MT_BATTLE_SURNAMES_SHARED_WITH_STORY: frozenset[str] = frozenset({'BARDO', 'CRIDEL', 'MIRU'})


def mtbattle_team_census() -> list[dict] | None:
    """Same shape and contract as `real_trainer_data.real_trainer_team_census()`, sourced from
    `data/mtbattle_trainer_census.json` (`DeckData_Hundred.bin`) -- see the module docstring for why the two
    are never interchangeable. All 100 trainers should qualify: ADDENDUM 92 found every one has at least one
    ordinary DPKM member and none are Shadow-only. None if the census file is not in this build."""
    raw_trainers = load_json_data_file("mtbattle_trainer_census.json")
    if raw_trainers is None:
        return None

    census: list[dict] = []
    for t in raw_trainers:
        member_levels = {
            slot["dpkm_index"]: slot["level"]
            for slot in t.get("team", [])
            if slot.get("kind") == "DPKM" and slot.get("level") is not None
        }
        if not member_levels:
            continue  # defensive only -- ADDENDUM 92 found no all-Shadow/empty Mt. Battle trainer
        census.append({
            "trainer_index": t["index"],
            "free_slots": 6 - t["party_size"],
            "avg_level": sum(member_levels.values()) / len(member_levels),
            "member_levels": member_levels,
        })
    return census
