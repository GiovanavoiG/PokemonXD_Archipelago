"""Trainers whose defeat check can be PERMANENTLY missed, and the fence that keeps items off them.

A progression item on a fight you can walk past forever is an unwinnable seed every time it happens, so these
locations stay `LocationProgressType.EXCLUDED` at EVERY `ProgressionLocations` setting, `everything` included.
That exception is part of the option's definition.

The list is field data and is explicitly incomplete; treat it as a growing set. Adding an index
here is all that is needed, since locations.py reads this module directly.
"""
from __future__ import annotations

# ADDENDUM 401: the literal lives in `missable_indices.py` now (see its docstring) and is re-exported here
# under the same name, so nothing that reads it had to change.
from .missable_indices import MISSABLE_TRAINER_INDICES  # noqa: E402,F401



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
    # ADDENDUM 401: the removed missable fights are not locations in any seed either.
    return (names - trainer_roster.RETIRED_UNIQUE_DEFEAT_LOCATIONS
            - trainer_roster.REMOVED_DEFEAT_LOCATIONS)

# The fence reversed twice. ADDENDUM 171 unapplied it wholesale on the premise that story trainers are NOT
# missable; ADDENDUM 185 put it back after a seed placed the Music Disc on a Six. The list itself was never
# deleted -- it is field data and costly to reproduce -- which is why re-applying it was a
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
#   1. `Missable?` marked                            -- the field notes (47 rows)
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
# that list is a measurement of what can be walked past, and mixing the two corrupts the evidence.
_WAKIN, _GONZAP = 144, 145

SNAG_MACHINE_BLOCKED_TRAINER_INDICES: "frozenset[int]" = frozenset()

# Every fight that cannot be redone, or cannot be dated, or is the goal: the fence as ADDENDA 188-341 built it.
# Still what Shadow Expansion and the named-location fence read -- a generated Shadow must go on a fight the
# player meets exactly once, and a named location cannot say which occurrence it fired on.
UNREDOABLE_TRAINER_INDICES: "frozenset[int]" = (
    _every_occurrence_of(MISSABLE_TRAINER_INDICES | ONE_SHOT_TRAINER_INDICES)
    | ONE_SHOT_TRAINER_INDICES
    | _rows_with_no_region()
    | POST_GOAL_TRAINER_INDICES          # ADDENDUM 193 -- stated separately, never inferred
    | SNAG_MACHINE_BLOCKED_TRAINER_INDICES   # ADDENDUM 337, emptied by 341 -- kept so a re-fence is one edit
)


# ADDENDUM 407 -- mandatory rematches may hold progression and useful items, after ADDENDUM 406 restored them (Naps #2
# is also gated there, and a mandatory fight).
#
# A rematch can hold an item only if its REGION says WHEN it is fought, because logic reads the region and nothing
# else. That is what the fence was protecting all along: ADDENDUM 188 found key items parked on Aferd #2, Zook #2,
# Laken #3 and Browsix #4. So this is an allowlist of the rematches whose region dates them, not a rule over all:
#
#   ON (1)  Naps #2 (60)          Cipher Lab, beside Lovrina (61) in deck order, behind the ID Card like her.
#
#   FILLER: Cida #2 (29), Sixes #2 (39-44).
#
#   HELD BACK -- the region does not date the fight, so logic would call it reachable too early:
#           Aferd #2-#4, Laken #2/#3   always-open regions (HQ Lab, Gateon Port): open from the first hour.
#           Zook #2 (147)              the Key Lair enters at 0x64 (ADDENDUM 439), before his fight -- unconfirmed in play.
#           Hebon #2                   Laken and Hebon are excluded from progression.
#           Sixes #3/#4 (112-123)      filed under Cipher Lab, but sit far later in deck order -- the lab's
#                                      rebattles; Browsix #4 is one of 188's stuck keys.
#           Dosk #2 (82)               filed under Agate Village, but sits among the ONBS fights in deck order.
#           Finol/Raling/Labet/Doby #2 (107-111)  filed under Pyrite Town, but sit after ONBS in deck order.
# Each held-back fight is one region correction (or a confirmed story byte) away from this list.
MANDATORY_REMATCH_INDICES: "frozenset[int]" = frozenset({60})


def _check_mandatory_rematches() -> None:
    from . import story_bytes, trainer_placements, trainer_roster

    for index in MANDATORY_REMATCH_INDICES:
        trainer = trainer_roster.TRAINERS_BY_INDEX[index]
        label = trainer_roster.trainer_label(trainer)
        assert trainer["occurrence"] >= 2, f"{label} is not a rematch"
        assert index not in MISSABLE_TRAINER_INDICES, f"{label} is on the missable list"
        assert index not in POST_GOAL_TRAINER_INDICES, f"{label} is the goal fight"
        assert label not in trainer_roster.REMOVED_DEFEAT_LOCATIONS, f"{label} is not a location"
        region = trainer_placements.region_for(index)
        assert region is not None and region not in story_bytes.ALWAYS_OPEN_REGIONS, (
            f"{label} has no region that dates it ({region})"
        )
        assert trainer["name"].upper() not in {"LAKEN", "HEBON"}, "ADDENDUM 362 excludes Laken and Hebon"


_check_mandatory_rematches()

FILLER_ONLY_TRAINER_INDICES: "frozenset[int]" = UNREDOABLE_TRAINER_INDICES - MANDATORY_REMATCH_INDICES


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
            f"the Snag Machine fence names {_named}, but ADDENDUM 332 exempts "
            f"{set(story_bytes.SNAGEM_BATTLE_EXEMPT_SURNAMES)} -- they are the same two fights or the "
            "reasoning no longer holds"
        )
        assert all(trainer_placements.region_for(i) == "Snagem Hideout"
                   for i in SNAG_MACHINE_BLOCKED_TRAINER_INDICES), (
            "the Snag Machine fence names a fight that is not in the Snagem Hideout"
        )
    else:
        # The two fights it used to name must now be genuinely un-fenced, or the lift achieved nothing.
        assert _WAKIN not in FILLER_ONLY_TRAINER_INDICES and _GONZAP not in FILLER_ONLY_TRAINER_INDICES, (
            "ADDENDUM 341 lifted the Snag Machine fence, but Wakin/Gonzap are still filler-only -- something "
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
    names -= trainer_roster.REMOVED_DEFEAT_LOCATIONS   # ADDENDA 401/409
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
# ADDENDUM 459: a Shadow Snubbul on one of the Agate trainers (24-27) respawned after being caught -- those trainers
# can be rematched with the exact same team. Gorps, Jols, Ladi and Cron are each one row in the deck (no `#2` row to mark them re-fightable), yet the game lets you fight that same
# row again -- so a generated or relocated Shadow on them is offered on every rematch.
SAME_TEAM_REMATCH_TRAINER_INDICES: "frozenset[int]" = frozenset({
    24,   # Gorps, Agate Village
    25,   # Jols, Agate Village
    26,   # Ladi, Agate Village
    27,   # Cron, Agate Village
})


# ADDENDUM 460: the trainers marked unmissable may host a Shadow only if they will NOT spawn it again on a rematch.
# Checked against the deck: Cida #1, Dosk #1, Raling #1, Labet #1, Doby #1 and Willie #1 each have later rows of their
# own with different teams and levels, so their rematches are those rows and a Shadow on #1 is offered once; the Snagem
# fights and Willie are fine. Bost is ONE row with no later one -- the same shape as Agate's
# Gorps/Jols/Ladi/Cron, which the game re-fights as-is (ADDENDUM 459).
#
# ADDENDUM 461: everyone here except the Snagem trainers and Willie is removed as a Shadow candidate. So of the
# 460 unmissable rows only the five Snagem Hideout fights, Biden #1 (also Snagem) and Willie #1 may host a Shadow. The
# six below keep everything else 460 gave them -- unmissable, progression-eligible -- and lose only Shadow hosting.
SHADOW_HOST_REFUSED: "frozenset[int]" = frozenset({
    13,    # Bost, Gateon Port
    21,    # Cida #1, Agate Village
    22,    # Dosk #1, Agate Village
    66,    # Raling #1, Pyrite Town
    67,    # Labet #1, Pyrite Town
    68,    # Doby #1, Pyrite Town
})
#: Kept as a name: ADDENDUM 460's one-member set (Bost), now a subset of the set above.
SHADOW_HOST_UNCONFIRMED: "frozenset[int]" = frozenset({13})
assert SHADOW_HOST_UNCONFIRMED <= SHADOW_HOST_REFUSED


# ADDENDUM 466: the Shadow rematch constraints are relaxed. ADDENDUM 465 stopped the engine
# rebuilding a snagged or purified Shadow when its trainer is fought again (`game_data/shadow_engine.py`), which was the
# whole reason a rematch could not host one. So three fences come down for Shadow hosting only -- every one stays
# defined, so a revert is one line in `shadow_expansion_excluded_trainer_indices`:
#   * `SAME_TEAM_REMATCH_TRAINER_INDICES` (ADDENDUM 459, Agate's Gorps/Jols/Ladi/Cron) -- no longer subtracted;
#   * `SHADOW_HOST_REFUSED` (ADDENDUM 461) -- no longer added; those rows are reopened;
#   * the re-fightable `final` rows below, fenced only because every occurrence of their name is (ADDENDUM 236's
#     "offered again on every rematch"). Each is regioned, not missable, not Citadark, not the goal and snaggable.
#     Laken #3 (202) is the one other row of that shape, and stays out: Laken and Hebon are excluded from progression.
# Missable, unplaced (no region), post-goal and no-snag fights are untouched -- those are about losing or never
# reaching the catch, not about rematches.
REFIGHTABLE_FINAL_SHADOW_HOSTS: "frozenset[int]" = frozenset({
    60,    # Naps #2, Cipher Lab
    147,   # Zook #2, Cipher Key Lair (exterior)
    164,   # Smarton #2, Cipher Key Lair
    167,   # Chobin #7, Kaminko's House
})
#: Set to False to put all three ADDENDUM 466 fences back exactly as ADDENDUM 461 left them.
SHADOW_REMATCH_FENCES_RELAXED = True


def missable_shadow_host_indices() -> "frozenset[int]":
    """The missable trainers that may host a Shadow with Missable Trainer Shadows on: every one-shot fight the client
    sends for you at its area's cap (`missable_autosend.AUTO_SEND_ONE_SHOT_INDICES`). A Shadow left on one when the
    area closes is handed to Miror B. by the client. Never a fight a Shadow cannot be snagged from, one past the goal,
    one on Citadark Isle, or one with no region to gate it on."""
    from . import trainer_placements
    from .catch_rate_exclusions import citadark_trainer_indices
    from .missable_autosend import AUTO_SEND_ONE_SHOT_INDICES
    from .shadow_regions import NO_SNAG_TRAINER_INDICES

    citadark = citadark_trainer_indices()
    out = set()
    for index in AUTO_SEND_ONE_SHOT_INDICES:
        placement = trainer_placements.PLACEMENTS.get(index)
        if placement is None or not placement.region:
            continue
        if index in NO_SNAG_TRAINER_INDICES or index in POST_GOAL_TRAINER_INDICES or index in citadark:
            continue
        out.add(index)
    return frozenset(out)


def shadow_expansion_excluded_trainer_indices(allow_missable_hosts: bool = False) -> "frozenset[int]":
    """Trainers that must never receive a generated Shadow Pokemon: a Shadow is a catch location, so its
    trainer must be fightable exactly once and never again. The full un-redoable set, NOT the ADDENDUM 407
    progression fence -- a mandatory rematch may hold an item, but a Shadow on it is still offered twice.

    ADDENDUM 432: plus every fight a Shadow cannot be snagged from at all (`shadow_regions.NO_SNAG_TRAINER_INDICES`
    -- Zook #1, Ardos #1, Biden #2), so a moved or generated Shadow can never be hung where it is uncatchable."""
    from .shadow_regions import NO_SNAG_TRAINER_INDICES

    # ADDENDUM 459: plus the rows the game re-fights as-is (`SAME_TEAM_REMATCH_TRAINER_INDICES`).
    # ADDENDUM 460: minus the rows marked unmissable -- one-time rows (a rematch is a different deck row), so a
    # Shadow on one is offered once and never infinitely respawned.
    from .missable_indices import CONFIRMED_UNMISSABLE

    allowed = missable_shadow_host_indices() if allow_missable_hosts else frozenset()
    if not SHADOW_REMATCH_FENCES_RELAXED:   # ADDENDUM 461's fence, kept verbatim for a revert
        return ((frozenset(UNREDOABLE_TRAINER_INDICES) - CONFIRMED_UNMISSABLE - allowed)
                | NO_SNAG_TRAINER_INDICES | SAME_TEAM_REMATCH_TRAINER_INDICES | SHADOW_HOST_REFUSED)
    # ADDENDUM 466: rematches may host a Shadow -- a snagged one is no longer rebuilt (ADDENDUM 465).
    # ADDENDUM 487: and the first fights whose second fight always carries the mirror (`shadow_mirrors`).
    from .shadow_mirrors import mirrored_host_rows

    return ((frozenset(UNREDOABLE_TRAINER_INDICES) - CONFIRMED_UNMISSABLE - REFIGHTABLE_FINAL_SHADOW_HOSTS
             - mirrored_host_rows() - allowed)
            | NO_SNAG_TRAINER_INDICES)


def _check_refightable_final_hosts() -> None:
    from . import census_repeat_column, trainer_placements
    from .catch_rate_exclusions import citadark_trainer_indices
    from .missable_indices import MISSABLE_TRAINER_INDICES as _listed
    from .shadow_regions import NO_SNAG_TRAINER_INDICES as _no_snag

    for index in REFIGHTABLE_FINAL_SHADOW_HOSTS:
        repeat, missable = census_repeat_column.CENSUS_REPEAT_AND_MISSABLE[index]
        placement = trainer_placements.PLACEMENTS.get(index)
        assert repeat == "final" and not missable and index not in _listed, f"{index} is not a safe final row"
        assert placement is not None and placement.region, f"{index} has no region"
        assert index not in POST_GOAL_TRAINER_INDICES and index not in _no_snag, index
        assert index not in citadark_trainer_indices(), index


_check_refightable_final_hosts()

