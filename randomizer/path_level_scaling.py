"""Trainer levels that follow the INTENDED path through the game, not the order a seed unlocks areas in --
the received order is not knowable at patch time, since the ISO is patched before anyone plays.
`story_bytes.region_floor(region)` is the story byte at which the unmodified game first lets you into a
region, so sorting the trainer-bearing regions by it IS the intended path. Thirteen tiers:

    0x19 Agate Village   0x24 Mt. Battle   0x27 Cipher Lab   0x30 Pyrite Town   0x35 Poke Spots
    0x3C Pyrite Town (ONBS)   0x3E Phenac City   0x46 Phenac City (Post-Sixes)   0x5A SS Libra
    0x5F Outskirt Stand   0x62 Snagem Hideout   0x64 Cipher Key Lair (+ exterior, merged)   0x6E Citadark Isle

The three always-open regions are off the ramp (`PATH_EXCLUDED_REGIONS`). The curve is ENDPOINTS, 8 at the
first tier and 50 at the last spread evenly, so adding or retiring a tier re-spaces the ramp instead of
needing a new table. 50 is roughly the vanilla late-game level, so a travel-shuffled player handed Citadark
Isle in their first hour gets steep rather than impossible; enhanced difficulty is the way back up, and the
two compose as the option text promises -- path scaling sets the base, ED's 1.33x multiplies it. Mt. Battle
is one region at one tier but a hundred trainers, so it takes the path only as its STARTING point and keeps
its own 1-to-100 ramp. The 37 `PLACEMENTS` rows with `region=None` keep their vanilla levels.
"""
from __future__ import annotations

import math


# The player's endpoints. Endpoints and not a table of levels, so the ramp re-spaces when a tier moves.
FIRST_TIER_LEVEL = 8
LAST_TIER_LEVEL = 50

# Levels are a u8 in the real files and the game's cap is 100. The clamp turns a bad endpoint into a low
# level rather than a corrupt record.
MIN_LEVEL = 1
MAX_LEVEL = 100


def path_tiers(regions: "set[str]") -> "list[int | None]":
    """The intended-path ordering of `regions`, as distinct entry floors, earliest first.

    `None` is the always-open tier -- one tier for all of them, sorting ahead of every real floor, since "the
    game lets you in immediately" is a position on the path and not missing data. No real seed reaches it now
    that all three are excluded; it stays because this is a total function over any region set. ADDENDUM 279's
    first-visit floors (0x01, 0x03, 0x0F) are not used here: splitting the opening tier into three would
    re-level every trainer in a path-scaled seed."""
    # An excluded region contributes no tier, so excluding a WINDOWED region some day cannot leave an empty
    # tier behind and re-space the ramp for everyone else.
    floors = {_path_floor(region) for region in regions if region not in PATH_EXCLUDED_REGIONS}
    real = sorted(f for f in floors if f is not None)
    return ([None] if None in floors else []) + real


# ADDENDUM 329: the ramp asks each REGION where it sits (`story_bytes.region_floor`), not `area_entry_floor`,
# which answers a map-ICON question and hands every region of an `AREA_GROUPS` place the place's FIRST tier.
# One icon instruction ("make Cipher Key Lab's floor 0x64") silently re-ordered the level ramp: the 0x5D tier
# disappeared, the ramp went 15 tiers to 12, and the Key Lair exterior jumped above Outskirt Stand and Snagem.
# The region floors the ramp reads instead:
#     Pyrite Town (ONBS)         0x30 -> 0x3C   its own tier, above Pyrite Town
#     Phenac City (Post-Sixes)   0x3E -> 0x46   its own tier, above Phenac City
#     SS Libra                   0x4E -> 0x5A   the ship, not the stranded arrival (which has no trainers)
#     Cipher Key Lair (exterior) 0x64 -> 0x5D   below Outskirt Stand (0x5F) and Snagem (0x62)
#     Cipher Key Lair            0x64           unchanged
# ADDENDA 366/367: an always-open region is open from the first hour and fought in across the whole story, so
# it cannot say WHEN a fight in it happens. All three come off the ramp rather than being flattened to
# FIRST_TIER_LEVEL -- Laken #3, vanilla 50, was being fielded at 8.
PATH_EXCLUDED_REGIONS: "frozenset[str]" = frozenset({
    # Open from the first hour and fought in across the whole story, so the region dates no fight in it.
    "Kaminko's House",    # Chobin x7, vanilla 5-38, all flattened to 8 (ADDENDUM 366)
    "Gateon Port",        # Laken x3, Ardos, Berk, Cyle, Bost, Kilen, Zook -- vanilla 6-50
    "Pokemon HQ Lab",     # Aferd x4, Naps -- vanilla 5-28
})


# ADDENDUM 368: the Key Lair doorway and its inside are ONE place, merged onto the interior's floor here
# because they were being levelled fourteen rungs apart -- one seed put the interior at tier 3/15 (level 14)
# and the exterior at tier 15/15 (level 50), and Zook #2 (147) and Biden #2 (148) stand at that doorway,
# where a travel unlock lands. 299's "same floor, same tier" safeguard could not catch it: after 329 no two
# trainer-bearing regions shared a floor at all. The merge lives in `_path_floor`, the one place answering
# "where is this region on the path", so merged regions are ONE group and cannot be ordered apart. The target
# is the INTERIOR (0x64) and the direction matters: 0x64 is when you get inside, keeping the Lair above
# Outskirt Stand (0x5F) and Snagem Hideout (0x62), where merging the other way drags seventeen interior
# trainers below Snagem. Scoped to the Key Lair on the player's wording -- the two Phenac, two Pyrite and two
# SS Libra regions split the same way and are NOT merged, being later STORY MOMENTS in the same place.
PATH_FLOOR_MERGES: "dict[str, str]" = {
    # The doorway and the inside of one building. Zook (147/148) stands in the exterior.
    "Cipher Key Lair (exterior)": "Cipher Key Lair",
    # No trainer is placed in `(deep)` today, so this row binds on nothing. Kept because its floor (0x6A) is
    # its own, so the day the census moves a fight there the split comes straight back.
    "Cipher Key Lair (deep)": "Cipher Key Lair",
}


def _path_floor(region: str) -> "int | None":
    """The region's OWN story-window floor, except that the always-open regions collapse to one `None` tier.
    `region_floor`, not `area_entry_floor` -- different questions, and different answers since ADDENDUM 324's
    icon override on the Cipher Key Lair. One helper, so `path_tiers` and `tier_index` cannot disagree."""
    from ..game_data import story_bytes

    if region in story_bytes.ALWAYS_OPEN_REGIONS:
        return None
    # A region that is the same PLACE as another borrows its floor, so the two are one tier. Done here and
    # not in `sphere_tier_order`, so the merge is invisible to every caller.
    return story_bytes.region_floor(PATH_FLOOR_MERGES.get(region, region))


def tier_index(region: "str | None", tiers: "list[int | None]",
               known: "set[str] | None" = None) -> "int | None":
    """Where `region` sits on the path, or None when it has no known position. `known` is the set of regions
    the tier list was built from, and passing it separates "always-open" from "never heard of this region" --
    `_path_floor` returns None for both, and without it an unrecognised name found the always-open tier by
    `list.index(None)` and came back as tier 0."""
    if region is None:
        return None
    if region in PATH_EXCLUDED_REGIONS:
        return None   # ADDENDUM 366 -- see PATH_EXCLUDED_REGIONS
    if known is not None and region not in known:
        return None
    floor = _path_floor(region)
    try:
        return tiers.index(floor)
    except ValueError:
        return None


def level_for_tier(index: int, tier_count: int,
                   first: int = FIRST_TIER_LEVEL, last: int = LAST_TIER_LEVEL) -> int:
    """The level a trainer at tier `index` of `tier_count` should field. Rounded rather than floored, so the
    ramp is symmetric about its endpoints instead of biased low; a single tier answers `first` rather than
    dividing by zero."""
    if tier_count <= 1:
        return _clamp(first)
    span = (last - first) / (tier_count - 1)
    # `_round_half_up`, not `round()`, which rounds halves to EVEN -- neither symmetric nor biased low. One
    # rounding rule for the module: a five-tier ramp over 8-50 puts tier 1 on exactly 18.5.
    return _clamp(_round_half_up(first + index * span))


def _clamp(level: "int | float") -> int:
    return max(MIN_LEVEL, min(MAX_LEVEL, int(level)))


def _round_half_up(value: float) -> int:
    """Round halves upward, always, rather than to even. `round()` rounds halves to EVEN, so a two-member
    team offset by exactly +/-0.5 flattens: vanilla 9/10 at a tier of 20 gives 19.5 and 20.5, and `round()`
    answers 20 and 20. Most two-member teams here are odd-span."""
    return int(math.floor(value + 0.5))


# ADDENDUM 369: where a trainer STANDS and which region's level band he belongs in are two questions. Biden
# #2 (trainer 148) really is at `Cipher Key Lair (exterior)`, between Zook #2 (147) and the first interior
# fight Grezle #1 (149) in deck order, and that row is what the access rules, `region_for_room` and ADDENDUM
# 327's anchor derivation read. Only his LEVEL is wrong, so the override is scoped to the ramp.
RAMP_REGION_OVERRIDES: "dict[int, str]" = {
    148: "Snagem Hideout",   # Defeat - Biden #2 -- player ruling, 2026-09-26
}


def region_by_trainer_index() -> "dict[int, str]":
    """{trainer_index: region} for every placement that HAS a region, from `trainer_placements.PLACEMENTS`,
    except `RAMP_REGION_OVERRIDES`, which answers the narrower "which region's LEVEL BAND does this fight
    belong in" -- a trainer can stand in one place and belong to another's difficulty."""
    from ..game_data import trainer_placements

    out = {index: placement.region
           for index, placement in trainer_placements.PLACEMENTS.items()
           if placement.region is not None}
    for index, region in RAMP_REGION_OVERRIDES.items():
        if index in out:
            out[index] = region
    return out


# ADDENDUM 299: the ramp follows THIS SEED's order, not the game's. The intended path is a constant, so SS
# Libra was tier 8 and Pyrite tier 5 in every seed ever generated -- but the ISO is patched after GENERATION,
# and generation includes fill, so the sphere each travel unlock becomes obtainable in is knowable. Measured
# on a real filled travel-shuffle seed: Snagem Hideout (fixed tier 10) opened in sphere 1 while Cipher Lab
# (fixed tier 3) did not open until sphere 7, i.e. a level-46 Snagem in the first hour. The TIERS are
# reordered, not the regions: groups, 8..50 spacing and count all survive. Regions sharing a story-byte floor
# are one PLACE and are never levelled apart; a group's sphere is its earliest member's; and ties break on
# the intended path, so a vanilla-travel seed reproduces the old ramp.
def sphere_tier_order(sphere_by_region: "dict[str, int]",
                      regions: "set[str] | None" = None) -> "dict[str, int]":
    """`{region: tier index}` with this seed's own sphere order replacing the intended path's.
    `sphere_by_region` is `{region: the sphere it first becomes reachable in}`; a region missing from it is
    treated as opening last, the safe direction. Pass the result on as `tier_by_region`."""
    known = set(region_by_trainer_index().values()) if regions is None else set(regions)
    tiers = path_tiers(known)
    groups: "dict[int, list[str]]" = {}
    for region in sorted(known):
        index = tier_index(region, tiers, known)
        if index is not None:
            groups.setdefault(index, []).append(region)
    late = max(sphere_by_region.values(), default=0) + 1

    def sort_key(original_index: int) -> "tuple[int, int]":
        earliest = min((sphere_by_region.get(region, late) for region in groups[original_index]),
                       default=late)
        return (earliest, original_index)

    out: "dict[str, int]" = {}
    for new_index, original_index in enumerate(sorted(groups, key=sort_key)):
        for region in groups[original_index]:
            out[region] = new_index
    return out


def level_by_trainer_index(first: int = FIRST_TIER_LEVEL,
                           last: int = LAST_TIER_LEVEL,
                           tier_by_region: "dict[str, int] | None" = None) -> "dict[int, int]":
    """{trainer_index: the level their area calls for}, for EVERY trainer with a known region. Deliberately
    not derived from the team census, unlike `build_path_level_plan`: nine trainers carry a Shadow and no
    ordinary member at all (`real_trainer_data.real_shadow_census`), so they never appear in it and showed up
    as stray levels (11, 17, 46, 57) among the ramp's clean fives in a generated seed."""
    regions = region_by_trainer_index()
    tiers = path_tiers(set(regions.values()))
    out: "dict[int, int]" = {}
    for trainer_index, region in regions.items():
        # `tier_by_region` is this seed's ordering when one was computed, None the intended path -- the same
        # fallback `build_path_level_plan` takes, so the two cannot disagree.
        index = (tier_by_region.get(region) if tier_by_region is not None
                 else tier_index(region, tiers, set(regions.values())))
        if index is not None:
            out[trainer_index] = level_for_tier(index, len(tiers), first, last)
    return out


# ADDENDUM 281: the tutorial fight keeps its vanilla level. Chobin #1 is `trainer_index` 15, one Sunkern,
# level 5 in the real deck data (`data/deckdata_story_trainers.json`), and the ramp was doubling him.
# Kaminko's House has since come off the ramp, which would leave him the same 5, but the player asked for a
# literal. `build_path_level_plan` reads the pin BEFORE its no-tier skip, so an exclusion cannot retire it.
PINNED_TRAINER_LEVELS: "dict[int, int]" = {
    15: 5,   # Defeat - Chobin #1, the tutorial fight at Kaminko's House
}


# ADDENDUM 366's fences. An empty exclusion set reads as a guarantee (ADDENDUM 298); these keep it from
# drifting back into one.
def _check_path_exclusions() -> None:
    from ..game_data import story_bytes, trainer_placements, trainer_roster

    assert PATH_EXCLUDED_REGIONS, (
        "PATH_EXCLUDED_REGIONS is empty -- ADDENDUM 298 deleted this mechanism for exactly that reason. "
        "Delete it again rather than shipping a filter that can never bind"
    )
    placed = {trainer_placements.region_for(index) for index in trainer_roster.TRAINERS_BY_INDEX}
    for region in PATH_EXCLUDED_REGIONS:
        assert region in story_bytes.ALL_KNOWN_REGIONS, f"{region} is not a region"
        assert region in placed, (
            f"{region} has no trainers placed in it, so excluding it from the ramp changes nothing -- an "
            "entry that cannot bind is the thing this fence exists to refuse"
        )
    # The exclusions are the always-open regions, and the reason is a property of that set -- asserted so a
    # future entry has to bring its own reason rather than the set becoming a junk drawer.
    assert PATH_EXCLUDED_REGIONS == story_bytes.ALWAYS_OPEN_REGIONS, (
        "PATH_EXCLUDED_REGIONS has drifted from the always-open set. That is allowed, but not silently: "
        "every entry today is excluded BECAUSE it is always-open, and a different kind of entry needs its "
        f"own reasoning written down. excluded={sorted(PATH_EXCLUDED_REGIONS)}, "
        f"always-open={sorted(story_bytes.ALWAYS_OPEN_REGIONS)}"
    )
    # `build_path_level_plan`'s pinned-past-the-skip branch is only reachable while a pinned trainer sits in
    # an excluded region, so that is asserted rather than trusted.
    pinned_regions = {trainer_placements.region_for(index) for index in PINNED_TRAINER_LEVELS}
    assert pinned_regions & PATH_EXCLUDED_REGIONS, (
        "no pinned trainer is in an excluded region -- `build_path_level_plan`'s pinned-past-the-skip branch "
        "can no longer be reached, so either the pin or that branch is now dead"
    )


_check_path_exclusions()


def _check_path_floor_merges() -> None:
    """ADDENDUM 368's table, refused at import if it is decorative. It has to move a real trainer and its
    target has to be a region this module knows -- a condition nobody can trigger reads as a guarantee."""
    from ..game_data import story_bytes, trainer_placements

    assert PATH_FLOOR_MERGES, "ADDENDUM 368's merge table is empty -- delete it rather than shipping a no-op"

    for source, target in PATH_FLOOR_MERGES.items():
        assert source != target, f"{source!r} is merged onto itself"
        assert target not in PATH_FLOOR_MERGES, (
            f"{source!r} -> {target!r} -> {PATH_FLOOR_MERGES[target]!r}: merges do not chain, so a two-hop "
            f"entry would silently only take the first hop"
        )
        assert story_bytes.region_floor(source) is not None, f"{source!r} has no story-window floor"
        assert story_bytes.region_floor(target) is not None, f"{target!r} has no story-window floor"
        assert story_bytes.region_floor(source) != story_bytes.region_floor(target), (
            f"{source!r} and {target!r} already share floor "
            f"{story_bytes.region_floor(target):#x} -- the merge does nothing"
        )

    # The table as a whole must change some real trainer's tier, or there is nothing to guarantee.
    assert trainer_placements.REGIONS_WITH_TRAINERS & set(PATH_FLOOR_MERGES), (
        "no merged region holds a placed trainer -- ADDENDUM 368's table cannot affect any level, so either "
        "the census moved or the table should go"
    )


_check_path_floor_merges()


def _check_ramp_region_overrides() -> None:
    """ADDENDUM 369's table, refused at import if a row is decorative or names something that does not exist."""
    from ..game_data import trainer_placements

    assert RAMP_REGION_OVERRIDES, (
        "ADDENDUM 369's table is empty -- delete it rather than shipping a no-op (ADDENDA 247/298)"
    )
    for index, region in RAMP_REGION_OVERRIDES.items():
        placement = trainer_placements.PLACEMENTS.get(index)
        assert placement is not None, f"ramp region override names trainer {index}, who is not in the roster"
        assert placement.region is not None, (
            f"ramp region override names trainer {index}, whom the workbook left region-less -- a region-less "
            "row is filler-only by design and giving it a level band here would bypass that decision"
        )
        assert placement.region != region, (
            f"ramp region override for trainer {index} names {region!r}, which is already where the placements "
            "put him -- an override that changes nothing reads as a correction and is not one"
        )
        assert region in trainer_placements.REGIONS_WITH_TRAINERS, (
            f"ramp region override sends trainer {index} to {region!r}, which holds no trainers -- so it has "
            "no level band to join"
        )

    # ADDENDUM 368's merge only bites while the exterior is still in the ramp's region set, so an override
    # that empties a merged region is refused here rather than discovered.
    left = set(region_by_trainer_index().values())
    for source in PATH_FLOOR_MERGES:
        if source in trainer_placements.REGIONS_WITH_TRAINERS:
            assert source in left, (
                f"the ramp region overrides emptied {source!r}, so ADDENDUM 368's merge of it can no longer "
                "affect any level -- either the override or the merge is now wrong"
            )


_check_ramp_region_overrides()


# ADDENDUM 297 took Citadark Isle off the ramp and the player reversed it the same day; the mechanism was
# removed rather than left empty. `pokemon-xd-addendum-297-*.md` has the design if an area comes off again.


# ADDENDUM 295: a tier is where the team SITS, not what every member IS -- writing the tier's level to every
# member turned a vanilla 23/25/28 into 25/25/25. Each member keeps its distance from its team's own vanilla
# average instead: 23/25/28 against a mean of 25.33 is -2.33/-0.33/+2.67, which at a tier of 40 is 38/40/43.
# The returned average is MEASURED, not assumed to be the tier -- rounding each offset independently and
# clamping at the ends can move the real mean off it, and `shadow_level_assignment` re-matches Shadows to it.
def _spread_over_team(level: int, member_levels: "dict[int, int]") -> "dict[int, int]":
    """`{dpkm_index: new level}` for one team placed at `level`, keeping each member's distance from its own
    team's vanilla average. A one-member team is unchanged by construction."""
    if not member_levels:
        return {}
    mean = sum(member_levels.values()) / len(member_levels)
    return {dpkm_index: _clamp(_round_half_up(level + (vanilla - mean)))
            for dpkm_index, vanilla in member_levels.items()}


def build_path_level_plan(
    team_census: "list[dict]",
    regions_by_trainer: "dict[int, str] | None" = None,
    first: int = FIRST_TIER_LEVEL,
    last: int = LAST_TIER_LEVEL,
    tier_by_region: "dict[str, int] | None" = None,
) -> "tuple[dict[int, int], dict[int, float]]":
    """Returns `({dpkm_index: level}, {trainer_index: the new team average})`. The second half is not a
    diagnostic: `enhanced_difficulty.shadow_level_assignment` matches every vanilla Shadow to its trainer's
    TEAM AVERAGE, so if the ordinary members have just moved, the average it was handed is the old one. A
    trainer with no known region is absent entirely, which is what keeps its vanilla levels."""
    regions = region_by_trainer_index() if regions_by_trainer is None else regions_by_trainer
    tiers = path_tiers(set(regions.values()))
    levels: "dict[int, int]" = {}
    averages: "dict[int, float]" = {}
    for row in team_census:
        region = regions.get(row["trainer_index"])
        # This seed's own tier when one was computed, the intended path otherwise. One lookup, so a caller
        # cannot half-apply the new ordering.
        index = (tier_by_region.get(region) if tier_by_region is not None
                 else tier_index(region, tiers, set(regions.values())))
        pinned = PINNED_TRAINER_LEVELS.get(row["trainer_index"])
        # The pin is read BEFORE the no-tier skip and the skip lets a pinned trainer past: Kaminko's House
        # being excluded puts Chobin #1 on the no-tier path, and a lookup after this `continue` would make
        # ADDENDUM 281's pin unreachable.
        if index is None and pinned is None:
            continue
        # A pin outranks the tier, applied here rather than by dropping the trainer from the census, so the
        # new team average below is the pinned level too. A pin is flat by design.
        if pinned is not None:
            assigned = {dpkm_index: _clamp(pinned) for dpkm_index in row["member_levels"]}
        else:
            assigned = _spread_over_team(
                level_for_tier(index, len(tiers), first, last), row["member_levels"],
            )
        if not assigned:
            continue
        levels.update(assigned)
        averages[row["trainer_index"]] = sum(assigned.values()) / len(assigned)
    return levels, averages


# ADDENDUM 388: Mt. Battle's ramp gets its OWN ceiling, and it is DERIVED from the mountain rather than
# typed. The story ramp ends at 50 because Citadark Isle does; Mt. Battle's hundredth trainer is a level-70
# fight in the unmodified game, so sharing the story's 50 made path scaling hand the player a mountain whose
# top fifth is EASIER than vanilla -- measured mean 48.5 -> 34.8 across all 100 trainers. It also put every
# padded member (levelled from vanilla, up to 70) above the entire ramp, which is where the 24-level team
# spreads came from.
#
# Never below the story ramp's top: whatever the census says, the mountain is not allowed to end lower than
# Citadark, because it is the later content.
def mt_battle_ramp_top(team_census: "list[dict]", floor: int = LAST_TIER_LEVEL) -> int:
    """The highest level the unmodified mountain fields, which is where its own ramp ends."""
    top = max((level for row in team_census for level in row["member_levels"].values()), default=floor)
    return _clamp(max(int(floor), int(top)))


def build_mt_battle_path_level_plan(
    team_census: "list[dict]",
    first: int = FIRST_TIER_LEVEL,
    last: "int | None" = None,
) -> "tuple[dict[int, int], dict[int, float]]":
    """Mt. Battle's own 1-to-100 ramp, anchored at its place on the path: first trainer at the Mt. Battle
    tier's level, hundredth at the mountain's own ceiling. The anchor goes through the same `path_tiers`/
    `tier_index` pair the story ramp uses, so Mt. Battle moving on the path moves its floor here too.

    ADDENDUM 388: `last` defaults to `mt_battle_ramp_top(team_census)` -- 70 on the real census -- rather
    than to the story ramp's 50. An explicit `last` still wins, for tests and for callers that mean it."""
    if not team_census:
        return {}, {}
    if last is None:
        last = mt_battle_ramp_top(team_census)
    regions = region_by_trainer_index()
    tiers = path_tiers(set(regions.values()))
    anchor_index = tier_index("Mt. Battle", tiers, set(regions.values()))
    anchor = level_for_tier(anchor_index, len(tiers), first, last) if anchor_index is not None else first

    indices = sorted({row["trainer_index"] for row in team_census})
    lowest, highest = indices[0], indices[-1]
    span = max(1, highest - lowest)

    levels: "dict[int, int]" = {}
    averages: "dict[int, float]" = {}
    for row in team_census:
        position = (row["trainer_index"] - lowest) / span
        level = _clamp(round(anchor + position * (last - anchor)))
        # The same spread as the story ramp. Mt. Battle already varies between trainers, but a hundred teams
        # of identical numbers is exactly the flatness this is meant to undo.
        assigned = _spread_over_team(level, row["member_levels"])
        if not assigned:
            continue
        levels.update(assigned)
        averages[row["trainer_index"]] = sum(assigned.values()) / len(assigned)
    return levels, averages


def describe(regions_by_trainer: "dict[int, str] | None" = None,
             tier_by_region: "dict[str, int] | None" = None) -> "list[str]":
    """The ramp, as lines, for the seed note. Pass this seed's `tier_by_region` and the note describes the
    ramp the seed ACTUALLY got -- it is the only record a player has of why a trainer was the level they
    were."""
    from ..game_data import story_bytes

    regions = region_by_trainer_index() if regions_by_trainer is None else regions_by_trainer
    tiers = path_tiers(set(regions.values()))
    by_tier: "dict[int, list[str]]" = {}
    for region in sorted(set(regions.values())):
        index = (tier_by_region.get(region) if tier_by_region is not None
                 else tier_index(region, tiers, set(regions.values())))
        if index is not None:
            by_tier.setdefault(index, []).append(region)
    lines = []
    for index in sorted(by_tier):
        if tier_by_region is None:
            floor = tiers[index]
            where = "always-open" if floor is None else f"0x{floor:02X}"
        else:
            where = "this seed's order"
        lines.append(f"  tier {index + 1}/{len(tiers)} ({where}): level "
                     f"{level_for_tier(index, len(tiers))} -- {', '.join(by_tier[index])}")
    # This list goes into the seed notes, so a reader seeing "level 40" beside a team of 38/40/43 finds the
    # explanation in the same place as the number.
    lines.append("  each member keeps its own distance from its team's vanilla average, so a team the game "
                 "fielded as 23/25/28 arrives at a level-39 tier as 37/39/42 rather than 39/39/39.")
    return lines


# ADDENDUM 269: ONE answer to "what level will this member actually be fought at". Species are evolved in
# `generate_early` against `enhanced_difficulty.ordinary_level_assignment` while levels are written in
# `generate_output` with the path plan over ED's, so once path scaling existed a member fought at 65 had been
# evolved for its vanilla level. Both phases call this function; neither composes the two sources itself.


def final_ordinary_levels(
    team_census: "list[dict]",
    path_scaling: bool,
    ed_scaling: bool,
    first: int = FIRST_TIER_LEVEL,
    last: int = LAST_TIER_LEVEL,
    tier_by_region: "dict[str, int] | None" = None,
) -> "dict[int, int]":
    """`{dpkm_index: the level this member will actually be fought at}`, for every member either option moves.
    The composition is the one the option text promises and `generate_output` performs: path scaling sets the
    base level, ED's multiplier scales it. A member neither option touches is ABSENT rather than present at
    its vanilla level -- absence is how every caller says "leave this one alone"."""
    from .enhanced_difficulty import ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER, ordinary_level_assignment

    levels = dict(ordinary_level_assignment(team_census, scale_levels=ed_scaling))
    if not path_scaling:
        return levels
    path_levels, _averages = build_path_level_plan(
        team_census, first=first, last=last, tier_by_region=tier_by_region,
    )
    if ed_scaling:
        path_levels = {
            index: _clamp(int(level * ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER))
            for index, level in path_levels.items()
        }
    levels.update(path_levels)
    return levels
