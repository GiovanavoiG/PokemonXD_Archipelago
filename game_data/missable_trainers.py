"""Trainers whose defeat check can be PERMANENTLY missed, and the fence that keeps items off them.

A progression item on a fight you can walk past forever is an unwinnable seed every time it happens, so these
locations stay `LocationProgressType.EXCLUDED` at EVERY `ProgressionLocations` setting, `everything` included.
That exception is the player's own qualifier on the option, asked for in the same breath as the option itself.

The list is the player's field data and is explicitly incomplete; treat it as a growing set. Adding an index
here is all that is needed, since locations.py reads this module directly.
"""
from __future__ import annotations

# Index 8 (Aferd 1) is also in `real_trainer_data.PERMANENTLY_EXCLUDED_TRAINER_INDICES`, but for another
# reason: that set governs what the ISO patcher does TO a trainer, this one what AP may place ON the check.
# Index 51 (Digor) has total_with_name 1, so there is no later encounter to fall back on.
MISSABLE_TRAINER_INDICES: "frozenset[int]" = frozenset({
    # From the player's compiled list, resolved against trainer_roster.py's 232 trainers. "Name 1" means
    # occurrence 1 only, so Dosk 2/3 stay eligible; Biden is listed twice, hence both its occurrences.
    # One correction, confirmed 2026-09-13: the six "Sixes" are RESIX, BLUSIX, BROWSIX, YELLOSIX, PURPSIX,
    # GREESIX (occurrence-1 indices 33-38). The list said "redsix" (no such trainer), GREESIX twice, no BROWSIX.
    8,    # Aferd 1
    51,   # Digor
    21,   # Cida 1
    23,   # Hebon 1
    22,   # Dosk 1
    9,    # Zook 1
    33, 34, 35, 36, 37, 38,   # Resix 1, Blusix 1, Browsix 1, Yellosix 1, Purpsix 1, Greesix 1
    16,   # Laken 1
    13,   # Bost
    53,   # Morbit
    54,   # Meda
    55,   # Elrok
    56,   # Coffy
    58,   # Nopia
    68,   # Doby 1
    67,   # Labet 1
    66,   # Raling 1
    64,   # Finol 1
    74,   # Mocor
    76,   # Elox
    77,   # Rixor
    79,   # Dilly
    85,   # Edlos
    94,   # Kapen
    92,   # Fenton
    91,   # Pellim
    93,   # Forgs
    95,   # Ezoor
    96,   # Ertlig
    105,  # Eroll 1
    106,  # Equin 1
    143,  # Biden 1
    148,  # Biden 2
    135,  # Willie 1
    142,  # Hobble
    141,  # Golit
    138,  # Jinok
    137,  # Gaply
    136,  # Fudlo
    151,  # Ibsol
    154,  # Jelstin
    161,  # Fudler
})


def missable_trainer_location_names() -> "set[str]":
    """Defeat-location names that must never hold progression or a useful item.

    Resolved through `trainer_roster.trainer_label`, never hardcoded, so a roster regeneration that renumbers
    an occurrence suffix cannot leave a stale string matching nothing. RETIRED labels are dropped: they are not
    locations in any seed, so asserting a progress type for one would fail on a KeyError instead of on the
    thing under test. The index stays fenced either way.
    """
    from . import trainer_roster

    names: set[str] = set()
    for index in MISSABLE_TRAINER_INDICES:
        trainer = trainer_roster.TRAINERS_BY_INDEX.get(index)
        if trainer is not None:
            names.add(trainer_roster.trainer_label(trainer))
    return names - trainer_roster.RETIRED_UNIQUE_DEFEAT_LOCATIONS

# The fence reversed twice. ADDENDUM 171 unapplied it wholesale on the player's "story trainers are NOT
# missable"; ADDENDUM 185 put it back after a seed placed the Music Disc on a Six. The list itself was never
# deleted -- it is the player's own field data and costly to reproduce -- which is why re-applying it was a
# one-line change.
MANDATORY_REPEATED_TRAINERS: "frozenset[str]" = frozenset()   # retained for compatibility; unused since 171


# Empty because there is nothing to fence: `MT_BATTLE_ONLY_SURNAMES` has zero name overlap with the 232-trainer
# story roster, so all 232 defeat locations are story trainers. Careful with
# `mtbattle_trainer_data.MT_BATTLE_ALL_TRAINER_INDICES` -- it is `frozenset(range(1, 101))` in the Mt. Battle
# DECK's index space, and intersecting it with story indices fences story trainers 1-100 by number (the tell
# was "Defeat - Bardo", story index 32, coming back EXCLUDED). Mt. Battle is gated by
# `exclude_mt_battle_trainers` instead, and its 92 rungs feed the cumulative "Defeat N Trainers" ladder.
NON_STORY_TRAINER_INDICES: "frozenset[int]" = frozenset()

# Retired; kept empty so an importer gets a harmless answer rather than an AttributeError.
NON_FINAL_REPEAT_INDICES: "frozenset[int]" = frozenset()

# The fence is per TRAINER, not per occurrence. The workbook marks occurrences ("Aferd 1", "Browsix 1"), which
# covered only 47 of the 232 rows and left the 54 later fights of those same 46 trainers wide open -- that is
# where the keys kept landing (Aferd #2 with the Machine Part, Zook #2 with the System Lever, Laken #3 with the
# Mayor's Note). A trainer you can walk past is one you can walk past every time, so every occurrence of a named
# trainer is fenced, resolved by NAME rather than index.
def _every_occurrence_of(indices: "frozenset[int]") -> "frozenset[int]":
    from . import trainer_roster

    names = {
        trainer_roster.TRAINERS_BY_INDEX[index]["name"].upper()
        for index in indices
        if index in trainer_roster.TRAINERS_BY_INDEX
    }
    return frozenset(
        index for index, trainer in trainer_roster.TRAINERS_BY_INDEX.items()
        if trainer["name"].upper() in names
    )


# The fence is the union of four different ways of being un-redoable, with the workbook's own counts:
#   1. `Missable?` marked                            -- the player's field notes (47 rows)
#   2. `Repeat?` = "earlier (N of M)"                -- structurally not the last fight (88 rows; only 20 of
#      them also marked Missable, so reading one column and not the other left 68 one-shot fights eligible)
#   3. every other occurrence of any name in 1 or 2  -- the workbook marks occurrences, not trainers
#   4. `trainer_placements.region is None`           -- a row with no region is a check nobody has located (37)
#
# 142 of 232 fenced, 90 left eligible. A filler-only check costs the fill some options; a progression item
# behind a fight that cannot be redone costs the run.
def _one_shot_fights_from_the_workbook() -> "frozenset[int]":
    from . import census_repeat_column

    return frozenset(
        index for index in census_repeat_column.CENSUS_REPEAT_AND_MISSABLE
        if census_repeat_column.is_a_one_shot_fight(index)
    )


def _rows_with_no_region() -> "frozenset[int]":
    from . import trainer_placements

    return frozenset(
        index for index, placement in trainer_placements.PLACEMENTS.items()
        if placement.region is None
    )


# With `goal: defeat_greevil`, `Defeat - Greevil #3` and the win condition are the same moment, so an item
# there arrives at or after the run is already over -- winnable with a key item still in the box. ADDENDUM 192's
# fence happens to cover all three Greevil rows already, but only by accident of the data, so the rule is stated
# in its own right with its own test. Only the fight that IS the goal belongs here: Citadark Isle's other checks
# are reachable strictly before the boss and are legitimate progression hosts.
def _the_final_boss_fight() -> "frozenset[int]":
    from . import trainer_roster

    out = set()
    for index, trainer in trainer_roster.TRAINERS_BY_INDEX.items():
        if trainer["name"].upper() != "GREEVIL":
            continue
        if trainer["occurrence"] == trainer["total_with_name"]:
            out.add(index)
    return frozenset(out)


POST_GOAL_TRAINER_INDICES: "frozenset[int]" = _the_final_boss_fight()

ONE_SHOT_TRAINER_INDICES: "frozenset[int]" = _one_shot_fights_from_the_workbook()

# Empty. Wakin (144) and Gonzap (145) were fenced while the client could not make their fights start; nothing
# in the workbook marks them -- both are `final` occurrences and both regioned. The blocker was not the Snag
# Machine: decompiling `S2_building_2F_2` showed the encounter never reads the per-area story byte at all.
# `hero_main` gates it on `story >= 790` and `gonza_battle` gates Wakin on `flag(1293)`, neither reachable from
# here, and removing the Snag Machine changed nothing. `ram_client.SnagemScriptPatcher` now patches two bytes of
# the loaded script, which starts both fights in the right order (Wakin, then Gonzap); confirmed in play.
#
# The set is kept, empty, because `FILLER_ONLY_TRAINER_INDICES` and `_check_workbook_totals` still read it and a
# re-fence is one literal away. A client limitation is deliberately NOT folded into MISSABLE_TRAINER_INDICES --
# that list is the player's measurement of what can be walked past, and mixing the two corrupts the evidence.
_WAKIN, _GONZAP = 144, 145

SNAG_MACHINE_BLOCKED_TRAINER_INDICES: "frozenset[int]" = frozenset()

FILLER_ONLY_TRAINER_INDICES: "frozenset[int]" = (
    _every_occurrence_of(MISSABLE_TRAINER_INDICES | ONE_SHOT_TRAINER_INDICES)
    | ONE_SHOT_TRAINER_INDICES
    | _rows_with_no_region()
    | POST_GOAL_TRAINER_INDICES          # ADDENDUM 193 -- stated separately, never inferred
    | SNAG_MACHINE_BLOCKED_TRAINER_INDICES   # ADDENDUM 337, emptied by 341 -- kept so a re-fence is one edit
)


# Assertions rather than tests: a miscount here silently un-fences checks and surfaces as an unwinnable seed.
def _check_workbook_totals() -> None:
    from . import census_repeat_column as c

    assert len(c.CENSUS_REPEAT_AND_MISSABLE) == c.WORKBOOK_ROW_COUNT == 232, "row count drifted from the sheet"
    marked = sum(1 for _i, (_r, m) in c.CENSUS_REPEAT_AND_MISSABLE.items() if m)
    earlier = sum(1 for _i, (r, _m) in c.CENSUS_REPEAT_AND_MISSABLE.items()
                  if r is not None and r.startswith("earlier"))
    final = sum(1 for _i, (r, _m) in c.CENSUS_REPEAT_AND_MISSABLE.items() if r == "final")
    assert marked == c.WORKBOOK_MISSABLE_COUNT == 47, f"Missable? count is {marked}, workbook says 47"
    assert earlier == c.WORKBOOK_EARLIER_COUNT == 88, f"earlier count is {earlier}, workbook says 88"
    assert final == c.WORKBOOK_FINAL_COUNT == 35, f"final count is {final}, workbook says 35"
    # If this stops holding, the Repeat? column has been misread again.
    assert c.is_a_one_shot_fight(124), "Defeat - Chobin #3 must read as a one-shot fight"
    assert POST_GOAL_TRAINER_INDICES, "the final Greevil fight must be identifiable -- it IS the goal"
    # Conditional rather than deleted: if the Snag Machine set is ever re-populated it must still name the two
    # fights the reasoning was about.
    from . import story_bytes, trainer_placements, trainer_roster

    if SNAG_MACHINE_BLOCKED_TRAINER_INDICES:
        _named = {trainer_roster.TRAINERS_BY_INDEX[i]["name"].upper()
                  for i in SNAG_MACHINE_BLOCKED_TRAINER_INDICES}
        assert _named == story_bytes.SNAGEM_BATTLE_EXEMPT_SURNAMES, (
            f"the Snag Machine ruling names {_named}, but ADDENDUM 332 exempts "
            f"{set(story_bytes.SNAGEM_BATTLE_EXEMPT_SURNAMES)} -- they are the same two fights or the "
            "reasoning no longer holds"
        )
        assert all(trainer_placements.region_for(i) == "Snagem Hideout"
                   for i in SNAG_MACHINE_BLOCKED_TRAINER_INDICES), (
            "the Snag Machine ruling names a fight that is not in the Snagem Hideout"
        )
    else:
        # The two fights it used to name must now be genuinely un-fenced, or the lift achieved nothing.
        assert _WAKIN not in FILLER_ONLY_TRAINER_INDICES and _GONZAP not in FILLER_ONLY_TRAINER_INDICES, (
            "ADDENDUM 341 lifted the Snag Machine ruling, but Wakin/Gonzap are still filler-only -- something "
            "else is fencing them and the lift is a no-op"
        )


_check_workbook_totals()


def filler_only_trainer_indices() -> "frozenset[int]":
    """The fenced set as INDICES. locations.py needs these as well as the names, to resolve the named-66
    locations by surname."""
    return FILLER_ONLY_TRAINER_INDICES



def filler_only_trainer_location_names() -> "set[str]":
    """The fenced set, resolved through `trainer_roster.trainer_label` and used exactly as returned.

    Never rebuild the name by hand. `trainer_label` already returns the full location name, and prefixing it
    again with "Defeat - " silently un-fenced 39 checks once before. RETIRED labels are dropped: they are not
    locations in any seed, so the index stays fenced but the name would only produce a KeyError.
    """
    from . import trainer_roster

    names: set[str] = set()
    for index in FILLER_ONLY_TRAINER_INDICES:
        trainer = trainer_roster.TRAINERS_BY_INDEX.get(index)
        if trainer is not None:
            names.add(trainer_roster.trainer_label(trainer))
    names -= trainer_roster.RETIRED_UNIQUE_DEFEAT_LOCATIONS
    return names


# Generated Shadow Pokemon may not go on a re-fightable or missable trainer. Measured on a real 60-Shadow plan
# built from the real census: of the 44 trainers it targeted, five (167, 215, 223, 226, 232) are marked `final`
# in the Repeat? column -- the occurrence the game LETS YOU RE-FIGHT -- so their Shadow is offered again on every
# rematch, and nothing in the game's save bookkeeping covers a Shadow this project invented. That is the
# reported infinite catch. The same pass also targeted 34 and 35, both `earlier (1 of 6)` and Missable, where
# the catch check can instead be walked past and lost.
#
# Both are already what `FILLER_ONLY_TRAINER_INDICES` means (150 indices, all 35 `final` rows inside it), so
# this is an existing fence applied to the one generator that never read it. There is room: of the 215 trainers
# with free team slots, 80 survive the exclusion holding 182 slots between them, against a ceiling of 44.
def shadow_expansion_excluded_trainer_indices() -> "frozenset[int]":
    """Trainers that must never receive a generated Shadow Pokemon: a Shadow is a catch location, so its
    trainer must be fightable exactly once and never again."""
    return FILLER_ONLY_TRAINER_INDICES

