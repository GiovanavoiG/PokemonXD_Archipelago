"""
Access rules for individual locations. Region-level gating lives in regions.py's entrance rules; a location
gets a rule here only when its parent region's reachability is not the whole requirement.

The cumulative "Defeat N Trainers" and "Purify N Shadow Pokemon" checks are TALLIES (ADDENDUM 432): threshold N
is in logic once at least N trainers / Shadows can really be reached in this state, each counted behind its own
fight's region, extra regions and items. They used to be ladders -- N gated on the one region holding the Nth
entry of a story-order list -- which Location Shuffle made unsound. No sphere number is hardcoded anywhere.

THE ONE RULE EVERYTHING HERE OBEYS (ADDENDUM 168): an access rule may only name an item that actually ENTERS
THE POOL. `all_state` never holds an uncreated item, so naming one makes the location unreachable forever --
and unlike a region edge, an unreachable LOCATION fails silently. Hence the `in_the_pool` filter in each rule
builder below; the copies are not shared, so an edit for one consumer cannot move another's answer.
"""

import json
import os

from BaseClasses import Location
from worlds.generic.Rules import add_rule, set_rule

from . import regions as regions  # noqa: F401
from . import locations, species, trainer_defeat
from .game_data import trainer_placements, trainer_roster

# Sphere-order chain for the cumulative-count rules below. The SAME region names regions.py builds -- real
# graph nodes, not a parallel structure.
_SPHERE_REGION_ORDER: list[str] = list(regions.REGION_NAMES)  # ADDENDUM 168: the real graph order


def _trainer_weights_from_census() -> "dict[str, int]":
    counts = dict(trainer_placements.trainer_count_by_region())
    unknown = 232 - sum(counts.values())
    if unknown:
        last_region = _SPHERE_REGION_ORDER[-1]
        counts[last_region] = counts.get(last_region, 0) + unknown
    return counts


# _CHEST_WEIGHT_BY_REGION is retired (ADDENDUM 174): chests are per-chest locations filed in the region that
# contains them, so the region IS the rule. "Defeat N Trainers" is still a cumulative count with no
# per-trainer identity, hence the census table below. Mt. Battle weighs 3, not the 92 of the old estimate --
# its 100 trainers live in a separate deck file and are not among the 232 story trainers at all.

# Both cumulative tables are the same census now, so `_set_sphere_rules`' ExcludeMtBattleTrainers branch is a
# no-op -- kept only so that option's independence from TrainerDefeatCheckCount stays explicit.
_TRAINER_WEIGHT_BY_REGION: dict[str, int] = _trainer_weights_from_census()

assert sum(_TRAINER_WEIGHT_BY_REGION.values()) == locations.TRAINER_DEFEAT_COUNT_LOCATION_COUNT, (
    "rules.py's _TRAINER_WEIGHT_BY_REGION must sum to exactly locations.TRAINER_DEFEAT_COUNT_LOCATION_COUNT -- "
    "see this module's own sphere-logic docstring for why."
)


def _cumulative_region_thresholds(weight_by_region: dict[str, int]) -> list[tuple[int, str]]:
    """[(cumulative total through this region, region name), ...] in `_SPHERE_REGION_ORDER` order, for
    `_region_for_sphere_count`."""
    thresholds: list[tuple[int, str]] = []
    running = 0
    for region_name in _SPHERE_REGION_ORDER:
        # A region holding none of this category contributes nothing rather than raising: a real census has
        # gaps -- Outskirt Stand holds no chests at all.
        running += weight_by_region.get(region_name, 0)
        thresholds.append((running, region_name))
    return thresholds


def _region_for_sphere_count(thresholds: list[tuple[int, str]], count: int) -> str:
    """The earliest sphere-order region whose cumulative total is >= `count`, falling back to the LAST region
    (Citadark Isle), which is what keeps Citadark gating the tail if the weights ever drift out of sync with
    the real totals. The module-level asserts exist so that drift is caught first."""
    for cumulative_total, region_name in thresholds:
        if count <= cumulative_total:
            return region_name
    return _SPHERE_REGION_ORDER[-1]


def _set_sphere_rules(world) -> None:
    """The TRAINER cumulative-count rules. Silently skips a threshold this seed did not create.

    ADDENDUM 483 (issue #2): a threshold above what logic can honestly count -- one defeat per trainer the player
    cannot miss (`_trainer_count_groups`) -- is EXCLUDED: it still exists and still sends, but holds nothing anyone
    needs. The docstring used to claim every threshold was excluded; none was."""
    from BaseClasses import LocationProgressType

    # With ExcludeMtBattleTrainers on a Mt. Battle win no longer advances the counter, so fall back to the
    # Mt. Battle-free table. A no-op against today's census, but the options are independent.
    excluding_mt_battle = bool(getattr(world.options, "exclude_mt_battle_trainers", False))
    trainer_weights = (_UNIQUE_TRAINER_WEIGHT_BY_REGION if excluding_mt_battle
                       else _TRAINER_WEIGHT_BY_REGION)
    del trainer_weights  # ADDENDUM 432: the ladder is retired; the tally below counts real fights
    groups = _trainer_count_groups(world)
    countable = sum(many for _ways, many in groups)
    player = world.player
    for count in range(1, locations.TRAINER_DEFEAT_COUNT_LOCATION_COUNT + 1):
        try:
            location = world.multiworld.get_location(
                locations.trainer_defeat_count_location_name(count), world.player
            )
        except KeyError:
            continue
        if count > countable:
            location.progress_type = LocationProgressType.EXCLUDED
        set_rule(location, lambda state, need=count, g=groups: _count_reachable(state, player, g, need))


def _count_reachable(state, player: int, groups, need: int) -> bool:
    """True once the satisfied groups add up to `need`. A group is `(ways, how many)`; a way is
    `(regions, items)` and any one way satisfies the group."""
    total = 0
    for ways, many in groups:
        for regions_needed, items_needed in ways:
            if all(state.can_reach(r, player=player) for r in regions_needed) and all(
                    state.has(name, player) for name in items_needed):
                total += many
                break
        if total >= need:
            return True
    return False


def _trainer_count_groups(world) -> "list[tuple[tuple[tuple[tuple[str, ...], tuple[str, ...]], ...], int]]":
    """ADDENDUM 432: the cumulative "Defeat N Trainers" tally, counted fight by fight, each behind its own region,
    extra regions and items.

    ADDENDUM 483 (issue #2) counts only what the player is sure to be able to fight, and each trainer ONCE:
      * a row with no census region is left out (it used to be counted at Citadark Isle -- an area it is not in);
      * a row on the missable list (`missable_trainers.MISSABLE_TRAINER_INDICES`) is left out -- it may already be
        gone for good when logic counts it;
      * the goal fight (`POST_GOAL_TRAINER_INDICES`) is left out;
      * a trainer's several rows (a rematch, a second team) are ONE defeat, reachable by any of them: a player who
        arrives late can meet only the later team, and the tally then rises by one, not two.
    Logic can only under-count against the client's real tally, never over-count."""
    from . import items
    from .game_data.missable_trainers import MISSABLE_TRAINER_INDICES, POST_GOAL_TRAINER_INDICES

    skip = frozenset(MISSABLE_TRAINER_INDICES) | frozenset(POST_GOAL_TRAINER_INDICES)
    if bool(getattr(world.options, "citadark_admins_only", 0)):
        from .game_data.citadark_admins import REMOVED_TRAINER_INDICES
        skip |= REMOVED_TRAINER_INDICES   # never fought, so never counted
    by_trainer: "dict[str, set[tuple[tuple[str, ...], tuple[str, ...]]]]" = {}
    for index in sorted(trainer_placements.PLACEMENTS):
        placement = trainer_placements.PLACEMENTS[index]
        if placement.region is None or index in skip:
            continue
        regions_needed = tuple(dict.fromkeys([placement.region, *placement.required_regions]))
        names = [items.requirement_to_pool_item(name) for name in placement.required_items]
        way = (regions_needed, tuple(n for n in dict.fromkeys(names) if _requirement_is_in_the_pool(world, n)))
        trainer = trainer_roster.TRAINERS_BY_INDEX.get(index)
        identity = str(trainer["name"]).upper() if trainer and trainer.get("name") else f"#{index}"
        by_trainer.setdefault(identity, set()).add(way)
    counts: "dict[tuple, int]" = {}
    for ways in by_trainer.values():
        key = tuple(sorted(ways))
        counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


# CATCH-POKEMON AREA GATING (ADDENDUM 104). A "Catch - {species}" location requires `can_reach` on a region
# holding a real trainer known to carry that species, so it picks up the travel-unlock gateways for free.
# Disclosed gap: the join of trainer to region and species roster covers only the 66 named trainers, not the
# ~166 with no readable name, so a species carried only by one of those gets NO rule rather than a wrong one.
# `trainer_census.json` was hand-transcribed, so its `species_id` values are ASSUMED to be National Dex
# numbers, not the internal indices that apply to raw DTNR/DPKM/PokeSpot bytes for species >= 252.

# Retired: a __file__-relative path cannot be opened inside an installed .apworld. Kept as a name for the
# diagnostics in tools/.
_TRAINER_CENSUS_PATH = os.path.join(os.path.dirname(__file__), "data", "trainer_census.json")


def _load_species_to_region() -> dict[int, str]:
    """dex -> earliest sphere-order region among any named, region-placed trainer whose team includes that
    species. Empty (not an error) when the census file is missing or malformed -- a missing entry just means
    "no gating rule"."""
    # Through the shared loader, not `open()`: a __file__-relative path cannot read a file bundled inside an
    # installed .apworld.
    from .game_data import load_json_data_file

    census = load_json_data_file("trainer_census.json")
    if not census:
        return {}

    sphere_index = {name: i for i, name in enumerate(_SPHERE_REGION_ORDER)}

    # surname -> earliest region that surname is ever fought in. One fought repeatedly ("Miror B.") appears
    # several times with different regions, and the species counts as available at the earliest.
    surname_to_region: dict[str, str] = {}
    for region, _location_name, surname in trainer_defeat.TRAINER_DEFEAT_ROSTER:
        if region not in sphere_index:
            continue
        current = surname_to_region.get(surname)
        if current is None or sphere_index[region] < sphere_index[current]:
            surname_to_region[surname] = region

    # Longest-first, so a substring match cannot land on a SHORTER surname that is itself a substring of a
    # longer, different one.
    known_surnames = sorted(surname_to_region, key=len, reverse=True)

    species_to_region: dict[int, str] = {}
    for pool in census.get("trainer_pools", []):
        for trainer in pool.get("trainers", []):
            display_name = trainer.get("name") or ""
            surname = next((s for s in known_surnames if s in display_name), None)
            if surname is None:
                continue  # one of the ~166 unnamed-in-this-project trainers -- no region data to attach
            region = surname_to_region[surname]
            for member in trainer.get("team", []):
                dex = member.get("species_id")
                if not isinstance(dex, int):
                    continue
                current = species_to_region.get(dex)
                if current is None or sphere_index[region] < sphere_index[current]:
                    species_to_region[dex] = region
    return species_to_region


_SPECIES_TO_REGION: dict[int, str] = _load_species_to_region()

_GUARANTEED_EEVEE_DEX = 133  # locations.GUARANTEED_SPECIES_LOCATION's species -- always exempt, see above


# ADDENDUM 183: the census join above is not the whole story. `_SPECIES_TO_REGION` is built from ORDINARY
# (DPKM) team slots, but a Shadow Pokemon lives in the DDPK table and never appears there -- while the "Catch"
# locations exist only for the Shadow roster plus the Poke Spot slots plus Eevee. Keyed on one population and
# consumed by another, every shadow-only species fell through ungated and progression-eligible in always-open
# "Pokemon Storage", and five of ten audited seeds were unwinnable.
#
# THE SNAG FLOOR IS TWO REGIONS, NOT AN ITEM. The Miror Radar never enters the pool in any mode, so
# `state.has("Miror Radar")` would make every shadow catch unreachable forever and silently. Its vanilla chest
# 77 sits in "Poke Spots", so the requirement is reaching that region; Pyrite Town is ANDed separately rather
# than left implied, because a Travel Unlock can open Poke Spots straight off the menu. Each source is a
# `shadow_regions.TrainerGate` ANDed on top of that floor, a generated shadow resolving through its HOST
# trainer's roster index. Several sources are an OR, so only the whole disjunction is ANDed with the floor,
# and a species whose every source is a filler-only (`region=None`) row becomes EXCLUDED for want of an
# honest gate.

# The floor is where a Shadow knocked out instead of snagged can be had again: Miror B. brings back the ones that
# got away. It was his Poke Spot appearances (the Miror Radar's chest, after Pyrite). Every seed now has his copy
# outside Kaminko's House (game_data/kaminko_trainers.py), fighting with the same queue, so the floor is the manor --
# open from the start in both travel modes.
_SNAG_FLOOR_REGIONS: "tuple[str, ...]" = ("Kaminko's House",)
_MIROR_RADAR_CHEST_ID = 77          # the Miror Radar's vanilla home, at the Poke Spots
_EEVEELUTION_REGION = "Gateon Port"  # Eeveelution is reachable whenever Gateon is, which is always


def _catch_gates_for_species(world) -> "tuple[dict[int, list], set[int]]":
    """(dex -> [TrainerGate | 'pokespot', ...], dexes whose every source is unplaceable). Reads the per-seed
    caches `__init__.generate_early` records; they exist because the shadow pool is shuffled IN PLACE, so
    re-deriving any of this at set_rules time would describe the vanilla game."""
    from .game_data import shadow_regions

    gates: "dict[int, list]" = {}
    unplaceable: "set[int]" = set()

    def record(dex: int, gate) -> None:
        if gate is None:
            unplaceable.add(dex)
            return
        gates.setdefault(dex, []).append(gate)

    # ADDENDUM 432: by the carrying trainer ROW, never the trainer's name. A label resolves to a surname, and a
    # surname's earliest region was the gate even when that fight did not carry the Shadow.
    by_ddpk = getattr(world, "_shadow_catch_ddpks", None)
    if by_ddpk is not None:
        for dex, ddpks in by_ddpk.items():
            for ddpk in ddpks:
                found = shadow_regions.gates_for_ddpk(ddpk)
                if not found:
                    record(dex, None)
                for gate in found:
                    record(dex, gate)
    else:
        for dex, labels in (getattr(world, "_shadow_catch_labels", None) or {}).items():
            for location_name in labels:
                label = shadow_regions.trainer_label_from_location(location_name)
                record(dex, shadow_regions.gate_for_label(label))

    for dex, hosts in (getattr(world, "_shadow_catch_expansion_hosts", None) or {}).items():
        for index in hosts:
            record(dex, shadow_regions.gate_for_trainer_index(index))

    # Poke Spot species are WILD, not snagged, so they carry no trainer and skip the snag floor. A sentinel
    # rather than a TrainerGate, so the rule builder can tell the two apart.
    for entry in (getattr(world, "_pokespot_species_assignment", None) or []):
        dex = entry.get("new_dex")
        if isinstance(dex, int):
            gates.setdefault(dex, []).append("pokespot")

    # A species with at least one real source is placeable, whatever else also carries it.
    unplaceable -= set(gates)
    return gates, unplaceable


# Wild Pokemon (the catches that are not Shadows) need only the Poke Spots. Empty: no second place is required.
WILD_CATCH_ANY_REGIONS: "tuple[str, ...]" = ()


def _set_catch_rules(world) -> None:
    """The "Catch - {species}" rules. Silently skips a location this seed did not create."""
    from BaseClasses import LocationProgressType

    from . import items

    player = world.player
    gates, unplaceable = _catch_gates_for_species(world)
    # The floor is the Kaminko Miror B. (see above). Start With Miror Radar and Poke Spots drops it altogether.
    snag_floor = () if bool(getattr(world.options, "start_with_poke_spots", 0)) else _SNAG_FLOOR_REGIONS

    def location_or_none(name: str):
        try:
            return world.multiworld.get_location(name, player)
        except KeyError:
            return None

    # Eevee is the STARTER, handed over before anything is gated, so it carries no rule at all -- which also
    # preserves locations.py's guarantee that GUARANTEED_SPECIES_LOCATION is never EXCLUDED. The Eeveelution
    # check fires on evolving it, at always-open Gateon Port: a no-op today, written anyway so the real
    # requirement survives a future graph change. No stone is required -- Espeon and Umbreon evolve on
    # friendship alone.
    eeveelution = location_or_none(locations.EEVEELUTION_LOCATION_NAME)
    if eeveelution is not None:
        set_rule(eeveelution, lambda state: state.can_reach(_EEVEELUTION_REGION, player=player))

    for dex in sorted(set(gates) | unplaceable):
        if dex == int(getattr(world, "starter_dex", _GUARANTEED_EEVEE_DEX)):
            continue   # ADDENDUM 443: the starter, whatever it is this seed
        location_name = species.location_name_for_species(dex)
        location = location_or_none(location_name)
        if location is None:
            continue

        if dex in unplaceable:
            # No honest gate exists. Filler-only is the only safe answer -- see this section's last paragraph.
            location.progress_type = LocationProgressType.EXCLUDED
            continue

        # ADDENDUM 473: a species reachable only after the goal (every source needs the goal's event) is
        # filler-only -- it is still a location, reachable once the goal is, but nothing anyone needs is on it.
        from .game_data.shadow_regions import POST_GOAL_EVENT_ITEM
        if all(gate != "pokespot" and POST_GOAL_EVENT_ITEM in gate.required_items for gate in gates[dex]):
            location.progress_type = LocationProgressType.EXCLUDED

        # Each source becomes a closed-over tuple of plain requirements, so the rule does no lookups at
        # evaluation time; item names are dropped when this seed's pool does not hold them.
        compiled: "list[tuple[tuple[str, ...], tuple[str, ...], bool, tuple[str, ...]]]" = []
        for gate in gates[dex]:
            if gate == "pokespot":
                compiled.append((("Poke Spots",), (), False, WILD_CATCH_ANY_REGIONS))
                continue
            regions_needed = [gate.region, *gate.required_regions]
            items_needed = [items.requirement_to_pool_item(name) for name in gate.required_items]
            items_needed = [name for name in dict.fromkeys(items_needed)
                            if _requirement_is_in_the_pool(world, name)]
            compiled.append((tuple(dict.fromkeys(regions_needed)), tuple(items_needed), True, ()))

        def rule(state, compiled=tuple(compiled), player=player, floor=snag_floor):
            for regions_needed, items_needed, needs_snag_floor, any_regions in compiled:
                if needs_snag_floor and not all(
                    state.can_reach(name, player=player) for name in floor
                ):
                    continue
                if not all(state.can_reach(name, player=player) for name in regions_needed):
                    continue
                if any_regions and not any(state.can_reach(name, player=player) for name in any_regions):
                    continue
                if not all(state.has(name, player) for name in items_needed):
                    continue
                return True
            return False

        set_rule(location, rule)


def _requirement_is_in_the_pool(world, item_name: str) -> bool:
    """ADDENDUM 168's pool rule for a catch gate's extra items. regions.py and `_set_chest_rules` carry their
    own copies for their own consumers, on purpose."""
    from . import items

    if item_name in items.NEVER_SHUFFLED_KEY_ITEM_NAMES:
        return False
    if item_name in items.ITEMS_REMOVED_FROM_POOL:
        return False
    if item_name in items.GATING_KEY_ITEM_NAMES:
        return bool(getattr(world.options, "key_item_shuffle", 1))
    return True


# SPHERE LOGIC FOR THE REMAINING COUNT CATEGORIES (ADDENDUM 150). An EXCLUDED location holds only filler,
# and most of this world's roster was excluded. Un-excluding is safe only where the reachability model is
# honest, and these categories hung straight off Menu -- AP believed "Purify 32 Shadow Pokemon" was reachable
# on turn one. Rules first; the options (ADDENDUM 449: Shadow Catch Progression and the purification cap) then open categories.

# Purification weights, a census: `data/shadow_pokemon_list.json` names the trainer holding each of the 83
# vanilla shadows and the trainer census says where that trainer is. 83 shadows, 32 thresholds -- threshold N
# is gated on the region where the Nth shadow becomes obtainable, so the weights are the region counts of the
# first 32 in graph order and sum to exactly 32 by construction. Deliberately static when
# `shadow_pokemon_expansion` adds more: the expansion hangs new shadows on existing trainers and so can only
# make a threshold reachable EARLIER, and over-strict logic merely delays a sphere.
def _purification_weights_from_census() -> "dict[str, int]":
    from .game_data import shadow_regions

    # ADDENDUM 415: the vanilla ladder only -- 83 thresholds, one per vanilla Shadow. The expansion's thresholds
    # (84..127) are gated per seed in `_set_remaining_sphere_rules`, on where that seed's Shadows really are.
    return shadow_regions.purification_weights(locations.VANILLA_SHADOW_COUNT)


_PURIFICATION_WEIGHT_BY_REGION: dict[str, int] = _purification_weights_from_census()

# The same census as _TRAINER_WEIGHT_BY_REGION, under its own name because `_set_sphere_rules` still selects
# between them on ExcludeMtBattleTrainers.
_UNIQUE_TRAINER_WEIGHT_BY_REGION: dict[str, int] = _trainer_weights_from_census()

assert sum(_PURIFICATION_WEIGHT_BY_REGION.values()) == locations.VANILLA_SHADOW_COUNT
assert sum(_UNIQUE_TRAINER_WEIGHT_BY_REGION.values()) == locations.TRAINER_DEFEAT_COUNT_LOCATION_COUNT

# _SHOP_OCCURRENCE_REGIONS is retired (ADDENDUM 176): shop locations are named after shops and filed in their
# room's own region, so the region IS the rule. Nothing models money any more.

# ADDENDUM 483 (issue #6) removed `_has_snag_machine`. It required the Machine Part on the reasoning that the HQ Lab
# needs it before handing over the Snag Machine, but the Snag Machine comes without the Machine Part, so that logic
# was wrong. The ladder agrees: the lab's 0x0F is the Snag Machine tier, the Machine Part is Gateon's 0x16,
# after it. Snagging -- Shadow catches and the purification ladder -- needs no item. With travel shuffle off the
# Machine Part still gates Agate Village (`regions.REGION_EDGES`), and so the Purify Chamber and everything past it.


def _purification_weights_for(world) -> "dict[str, int]":
    """This world's vanilla ladder. ADDENDUM 423/424: Nightmare Citadark moves Citadark's Shadows (all but Lugia)
    onto hosts elsewhere, so its ladder is the census minus them; their thresholds follow it, gated like the
    expansion's on every region holding a Shadow."""
    removed = frozenset(getattr(world, "_nightmare_removed_dex", None) or ())
    if not removed:
        return _PURIFICATION_WEIGHT_BY_REGION
    from .game_data import shadow_regions

    # ADDENDUM 479: the world's own count already leaves out the post-goal Shadows; so does its ladder.
    return shadow_regions.purification_weights(_vanilla_shadow_count_for(world), removed, include_post_goal=False)


def _vanilla_shadow_count_for(world) -> int:
    return int(getattr(world, "_vanilla_shadow_count", None) or locations.VANILLA_SHADOW_COUNT)


def _purification_tail_regions(world) -> "tuple[str, ...]":
    """Every region that holds a Shadow in this seed: the vanilla census's, plus each expansion host's own region.
    Hosts with no region cannot occur -- `shadow_expansion_excluded_trainer_indices` fences region-less rows."""
    from .game_data import trainer_placements

    regions = set(_purification_weights_for(world))
    # ADDENDUM 424: Nightmare Citadark's relocated Shadows sit on hosts the same way.
    for plan in list(getattr(world, "_shadow_expansion_plans", None) or ()) + list(
            getattr(world, "_nightmare_relocations", None) or ()):
        placement = trainer_placements.PLACEMENTS.get(int(plan["trainer_index"]))
        if placement is not None and placement.region:
            regions.add(placement.region)
    return tuple(sorted(regions))


def _purification_shadow_groups(world) -> "list[tuple[tuple[tuple[tuple[str, ...], tuple[str, ...]], ...], int]]":
    """ADDENDUM 432: every Shadow this seed really holds, as `[(ways to snag it, how many Shadows share exactly
    those ways), ...]`. A way is `(regions to reach, items to hold)`; any one way will do.

    - a vanilla Shadow still at its own trainers: one way per row carrying it (`shadow_regions.gates_for_ddpk`)
    - a Shadow moved by Nightmare Citadark / Remove Citadark or Greevil Shadows: its new host's row
    - a Shadow the expansion added: its host's row

    Grouped so a rule walks ~40 distinct gates rather than 127 Shadows."""
    from . import items
    from .game_data import load_json_data_file, shadow_regions

    def compile_gate(gate) -> "tuple[tuple[str, ...], tuple[str, ...]]":
        regions_needed = tuple(dict.fromkeys([gate.region, *gate.required_regions]))
        names = [items.requirement_to_pool_item(name) for name in gate.required_items]
        names = tuple(name for name in dict.fromkeys(names) if _requirement_is_in_the_pool(world, name))
        return regions_needed, names

    shadows: "list[tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]]" = []
    removed = frozenset(getattr(world, "_nightmare_removed_dpkm", None) or ())
    for entry in load_json_data_file("deckdata_dark_pokemon.json") or []:
        if int(entry["dpkm_index"]) in removed:
            continue
        if shadow_regions.is_post_goal_ddpk(int(entry["ddpk_index"])):
            continue   # ADDENDUM 479: no Purify rung for a Shadow only purifiable after the goal
        gates = shadow_regions.gates_for_ddpk(int(entry["ddpk_index"]))
        if gates:
            shadows.append(tuple(sorted({compile_gate(g) for g in gates})))
    hosted = [int(plan["trainer_index"]) for plan in getattr(world, "_nightmare_relocations", None) or ()
              for _shadow in plan["shadows"]]
    hosted += [int(plan["trainer_index"]) for plan in getattr(world, "_shadow_expansion_plans", None) or ()
               for _mon in plan["new_pokemon"]]
    for index in hosted:
        gate = shadow_regions.gate_for_trainer_index(index)
        if gate is not None:
            shadows.append((compile_gate(gate),))
    counts: "dict[tuple, int]" = {}
    for ways in shadows:
        counts[ways] = counts.get(ways, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def _set_remaining_sphere_rules(world) -> None:
    """The purification checks. ADDENDUM 432: `Purify N` is in logic when Agate Village (the Purify Chamber) is
    reachable and AT LEAST N of this seed's Shadows can be snagged with what is held --
    counted Shadow by Shadow from the fights that really carry them.

    It used to be a ladder: threshold N gated on the ONE region where the Nth Shadow of a fixed story-order list
    sat. That is only honest when the regions open in story order. With Location Shuffle they do not -- reaching
    Phenac said nothing about the Pyrite and Poke Spot Shadows below it on the list -- and the list itself filed
    every multi-appearance trainer's Shadows at their FIRST appearance. If Agate, Gateon and the lab hold only 13
    Shadows, every purification past 13 has to be gated behind other areas, or the seed can softlock."""
    from BaseClasses import LocationProgressType

    from .game_data.shadow_regions import POST_GOAL_EVENT_ITEM

    groups = _purification_shadow_groups(world)
    player = world.player
    floor = shadow_regions_floor()
    # ADDENDUM 473: how many Shadows can be had BEFORE the goal. A threshold past that needs a post-goal Shadow
    # (Miror B.'s Dragonite), so it is filler-only; its rule still lets it count once the goal is reached.
    before_goal = sum(many for ways, many in groups
                      if any(POST_GOAL_EVENT_ITEM not in items_needed for _regions, items_needed in ways))
    for count in range(1, locations.PURIFICATION_LOCATION_COUNT + 1):
        try:
            location = world.multiworld.get_location(locations.purification_location_name(count), player)
        except KeyError:
            continue
        if count > before_goal:
            location.progress_type = LocationProgressType.EXCLUDED

        def rule(state, need=count, groups=tuple(groups)):
            if not state.can_reach(floor, player=player):   # ADDENDUM 483: no Snag Machine item to hold
                return False
            return _count_reachable(state, player, groups, need)

        set_rule(location, rule)


def shadow_regions_floor() -> str:
    from .game_data import shadow_regions

    return shadow_regions.PURIFICATION_FLOOR_REGION


    # The per-trainer locations used to be gated by a model, because the roster carried no region data. It
    # does now, so they live in their real regions and get real gates (`_set_trainer_census_rules`).


# ADDENDUM 174: the chest item gates. Region membership covers most chests; the rest carry their own
# requirements, in chest_regions.CHEST_ITEM_GATES. Chest 2, the HQ Lab Master Ball chest that the Robo Kyogre
# parts open by flipping Gateon's story byte 0x6C -> 0x6E, is in CHEST_REGION_GATES instead. With
# key_item_shuffle off the ID Card is not pooled, and reaching the room already implies holding it.


def _set_chest_rules(world) -> None:
    from . import items
    from .game_data import chest_regions

    shuffle_key_items = bool(getattr(world.options, "key_item_shuffle", 1))

    def in_the_pool(item_name: str) -> bool:
        if item_name in items.NEVER_SHUFFLED_KEY_ITEM_NAMES:
            return False
        if item_name in items.ITEMS_REMOVED_FROM_POOL:
            return False
        if item_name in items.GATING_KEY_ITEM_NAMES:
            return shuffle_key_items
        return True

    # No rule in this file may name the Robo Kyogre Part: the Parts gate Citadark Isle and nothing else.
    # Asserted rather than assumed, because a Parts requirement reappearing elsewhere is the drift this stops.
    assert not any(items.MACGUFFIN_ITEM_NAME in required
                   for required in chest_regions.CHEST_ITEM_GATES.values()), (
        "the Robo Kyogre Part gates Citadark Isle and nothing else -- gate the chest on the region instead"
    )

    def attach(chest_id: int, names: "tuple[str, ...]", regions_needed: "tuple[str, ...]") -> None:
        location_name = locations.CHEST_ID_TO_LOCATION.get(chest_id)
        if location_name is None:
            return  # not an AP location this build (a key-item chest, or an excluded room)
        try:
            location = world.multiworld.get_location(location_name, world.player)
        except KeyError:
            return  # not created this seed -- same convention as _set_sphere_rules
        if not names and not regions_needed:
            return

        def rule(state, n=names, r=regions_needed):
            for item_name in n:
                if not state.has(item_name, world.player):
                    return False
            for region_name in r:
                if not state.can_reach(region_name, player=world.player):
                    return False
            return True

        set_rule(location, rule)

    for chest_id, required in chest_regions.CHEST_ITEM_GATES.items():
        # CHEST_ITEM_GATES says "ID Card" because that is what the chest is behind in the real game;
        # translated here to the item that grants it.
        names = tuple(dict.fromkeys(items.requirement_to_pool_item(name) for name in required))
        names = tuple(name for name in names if in_the_pool(name))
        attach(chest_id, names, ())

    for chest_id, regions_needed in chest_regions.CHEST_REGION_GATES.items():
        attach(chest_id, (), tuple(regions_needed))


# ADDENDUM 175: the per-trainer gates, from the trainer census -- area AND items, ANDed. The region half
# is locations.py's filing; this adds the census's `required_items` (38 trainers) and `required_regions` (one:
# Zook #2 is in Cipher Key Lair (exterior) but must be done with Snagem Hideout, which sits LATER in the graph
# -- index 18 against the exterior's 16 -- so reaching the exterior does not imply it). The Elevator Key is
# filtered out: six census rows name it and it is never pooled.


def _set_trainer_census_rules(world) -> None:
    from . import items
    from .game_data import trainer_placements

    shuffle_key_items = bool(getattr(world.options, "key_item_shuffle", 1))

    def in_the_pool(item_name: str) -> bool:
        if item_name in items.NEVER_SHUFFLED_KEY_ITEM_NAMES:
            return False
        if item_name in items.ITEMS_REMOVED_FROM_POOL:
            return False
        if item_name in items.GATING_KEY_ITEM_NAMES:
            return shuffle_key_items
        return True

    for index, placement in trainer_placements.PLACEMENTS.items():
        if not placement.required_items and not placement.required_regions:
            continue
        trainer = trainer_roster.TRAINERS_BY_INDEX.get(index)
        if trainer is None:
            continue
        # Through trainer_label, never reconstructed: a string-assembled location name has twice silently
        # un-fenced dozens of checks (ADDENDA 144/152).
        name = trainer_roster.trainer_label(trainer)
        try:
            location = world.multiworld.get_location(name, world.player)
        except KeyError:
            continue  # not created this seed (trainer defeats off, or cumulative rather than unique mode)
        # The census records what the GAME requires ("Behind Data Rom and ID Card" is one row), so the two
        # are translated to the single item that delivers them, and deduped.
        required_items = tuple(dict.fromkeys(
            items.requirement_to_pool_item(name) for name in placement.required_items
        ))
        required_items = tuple(i for i in required_items if in_the_pool(i))
        required_regions = placement.required_regions
        if not required_items and not required_regions:
            continue

        def rule(state, it=required_items, rg=required_regions):
            for item_name in it:
                if not state.has(item_name, world.player):
                    return False
            for region_name in rg:
                if not state.can_reach(region_name, player=world.player):
                    return False
            return True

        # add_rule, not set_rule: `_set_remaining_sphere_rules` may already have attached something, and a
        # gate must narrow what is there rather than replace it.
        add_rule(location, rule)


# ADDENDUM 252: the "Defeat X (Any)" rules. The location's REGION already says where its anchor occurrence
# lives; six of the 35 anchors carry more (Lovrina's the Data ROM, Gorigan's the System Lever,
# Snattle/Eroll/Equin the Phenac key items, Zook's the Snagem Hideout region) and those come across with the
# anchor. The pool filter is live here, not hypothetical: Equin's anchor names the never-pooled Elevator Key.
def _set_repeatable_trainer_rules(world) -> None:
    from . import items
    from .game_data import repeatable_trainers

    shuffle_key_items = bool(getattr(world.options, "key_item_shuffle", 1))

    def in_the_pool(item_name: str) -> bool:
        if item_name in items.NEVER_SHUFFLED_KEY_ITEM_NAMES:
            return False
        if item_name in items.ITEMS_REMOVED_FROM_POOL:
            return False
        if item_name in items.GATING_KEY_ITEM_NAMES:
            return shuffle_key_items
        return True

    for row in repeatable_trainers.REPEATABLE_TRAINERS:
        if row["any_of_regions"]:
            try:
                location = world.multiworld.get_location(row["location"], world.player)
            except KeyError:
                continue
            add_rule(location, lambda state, rg=row["any_of_regions"], player=world.player: any(
                state.can_reach(name, "Region", player) for name in rg))
        if not row["required_items"] and not row["required_regions"]:
            continue
        try:
            location = world.multiworld.get_location(row["location"], world.player)
        except KeyError:
            continue   # not created this seed
        required_items = tuple(dict.fromkeys(
            items.requirement_to_pool_item(name) for name in row["required_items"]
        ))
        required_items = tuple(name for name in required_items if in_the_pool(name))
        required_regions = row["required_regions"]
        if not required_items and not required_regions:
            continue

        def rule(state, it=required_items, rg=required_regions):
            for item_name in it:
                if not state.has(item_name, world.player):
                    return False
            for region_name in rg:
                if not state.can_reach(region_name, player=world.player):
                    return False
            return True

        add_rule(location, rule)


# The uncertain Overworld Items are marked EXCLUDED in locations.py at location-creation time, NOT here: AP
# calls create_items before set_rules, so doing it here sized the useful/filler split against a capacity that
# still counted those 14 as DEFAULT and raised `FillError: Not enough filler items for excluded locations`.
# An exclusion that changes the item pool's arithmetic has to happen before the arithmetic runs.
#
# ADDENDUM 238c: a shop's later shelves are not reachable when its room is. Berries are dealt per shop LINE,
# so check N is the Nth line that shop ever offers and a line a restock introduces is not on the opening shelf
# -- Agate's check 9 is its Great Ball line, which does not exist until the ONBS crisis is solved, and
# Pyrite's 11 and 12 are the same. A tier with no recorded gate keeps its room rule.
#
# ADDENDUM 312: item gates on the NAMED (cumulative-mode) defeat locations, which carry a REGION only.
# Smarton's is SS Libra, flown to directly with travel randomization on, so the fight was reachable holding
# neither the Music Disc nor the Mayor's Note. Snattle's region already carries both, and is listed anyway so
# the rule states the requirement rather than relying on where the region sits.
NAMED_DEFEAT_ITEM_GATES: "dict[str, tuple[str, ...]]" = {
    "Defeat - Cipher Peon Smarton": ("Music Disc", "Mayor's Note"),
    "Defeat - Cipher Admin Snattle": ("Music Disc", "Mayor's Note"),
    # ADDENDUM 449. Laken is gated behind the Machine Part; always-open Gateon gave his (Any) no gate at all. It
    # stays filler-only (ADDENDUM 362), so this only moves when it counts as in logic.
    "Defeat Laken (Any)": ("Machine Part",),
}


def _set_named_defeat_item_gates(world) -> None:
    from . import items

    shuffle_key_items = bool(getattr(world.options, "key_item_shuffle", 1))
    for location_name, required in NAMED_DEFEAT_ITEM_GATES.items():
        try:
            location = world.multiworld.get_location(location_name, world.player)
        except KeyError:
            continue
        names = tuple(dict.fromkeys(items.requirement_to_pool_item(n) for n in required))
        names = tuple(n for n in names
                      if n not in items.NEVER_SHUFFLED_KEY_ITEM_NAMES and n not in items.ITEMS_REMOVED_FROM_POOL
                      and (n not in items.GATING_KEY_ITEM_NAMES or shuffle_key_items))
        if names:
            add_rule(location, lambda state, n=names: state.has_all(n, world.player))


def _set_shop_tier_rules(world) -> None:
    from . import items
    from .game_data import shop_stock, shops

    for shop in shops.CONFIRMED_SHOPS:
        for line_numbers, gate in shop_stock.gated_shop_lines(shop.name):
            regions_needed = tuple(dict.fromkeys(gate["regions"]))
            items_needed = [items.requirement_to_pool_item(name) for name in gate["items"]]
            items_needed = tuple(name for name in dict.fromkeys(items_needed)
                                 if _requirement_is_in_the_pool(world, name))
            for number in line_numbers:
                location_name = shops.shop_location_name(shop.name, number)
                try:
                    location = world.multiworld.get_location(location_name, world.player)
                except KeyError:
                    continue  # not created this seed -- shop checks can be switched off
                add_rule(location, lambda state, regions_needed=regions_needed,
                         items_needed=items_needed, player=world.player: (
                    all(state.can_reach(name, player=player) for name in regions_needed)
                    and all(state.has(name, player) for name in items_needed)
                ))


def set_all_rules(world) -> None:
    # ADDENDUM 483 (issue #5): the template's "illustrative" Master Ball rule is gone. Its location was retired long
    # ago, so it never attached, and it was the only reason the Master Ball looked like progression.
    _set_sphere_rules(world)
    _set_chest_rules(world)
    _set_trainer_census_rules(world)
    _set_remaining_sphere_rules(world)
    _set_catch_rules(world)
    _set_shop_tier_rules(world)
    _set_repeatable_trainer_rules(world)
    _set_named_defeat_item_gates(world)
    _set_krane_memo_rules(world)
    _assert_no_ungated_progression_in_an_always_open_bucket(world)


# Memos 3-5 come with the Machine Part's delivery, or with the Cipher Lab cleared (Data ROM and ID Card in hand).
# A requirement that is not in this seed's pool is met where the game hands it out instead.
def _set_krane_memo_rules(world) -> None:
    from . import items

    player = world.player

    def needs(item_name: str):
        pooled = items.requirement_to_pool_item(item_name)
        return pooled if _requirement_is_in_the_pool(world, pooled) else None

    machine_part = needs("Machine Part")
    lab_items = tuple(dict.fromkeys(n for n in (needs("Data ROM"), needs("ID Card")) if n))

    def rule(state) -> bool:
        if machine_part is not None:
            if state.has(machine_part, player):
                return True
        elif state.can_reach("Gateon Port", "Region", player):
            return True
        return state.can_reach("Cipher Lab", "Region", player) and all(state.has(n, player) for n in lab_items)

    for memo in (3, 4, 5):
        try:
            location = world.multiworld.get_location(locations.krane_memo_location_name(memo), player)
        except KeyError:
            continue
        add_rule(location, rule)


# ADDENDUM 183: the guard for the silent shape. A wrong rule is loud -- Fill either cannot place an item or
# reports an unreachable location. NO rule is not: a location in a bucket region hanging straight off Menu,
# left progression-eligible, reads as sphere zero and generates perfectly. The invariant: such a location is
# either filler-only or it carries a rule. Nothing about WHICH rule.
_ALWAYS_OPEN_BUCKET_REGIONS: "frozenset[str]" = frozenset({
    "Pokemon Storage",
    "Shadow Pokemon Purification",
    "Trainer Defeat Count",
    "Unique Trainer Defeats",
})


# The one genuinely ungated AND progression-eligible location: Eevee is the starter, handed over before
# anything is gated. Named here rather than waved through by a `progress_type` check, so a second exception
# has to be a deliberate edit with a reason beside it.
_UNGATED_BY_DESIGN: "frozenset[str]" = frozenset({locations.GUARANTEED_SPECIES_LOCATION})


def _assert_no_ungated_progression_in_an_always_open_bucket(world) -> None:
    from BaseClasses import LocationProgressType

    offenders: "list[str]" = []
    for region_name in _ALWAYS_OPEN_BUCKET_REGIONS:
        try:
            region = world.multiworld.get_region(region_name, world.player)
        except KeyError:
            continue
        for location in region.locations:
            if location.progress_type == LocationProgressType.EXCLUDED:
                continue
            if location.name in _UNGATED_BY_DESIGN:
                continue
            # A location with no rule of its own still carries Location's default, the always-true lambda
            # every Location is constructed with.
            if getattr(location, "access_rule", None) is Location.access_rule:
                offenders.append(location.name)
    if offenders:
        shown = ", ".join(sorted(offenders)[:8])
        more = f" (+{len(offenders) - 8} more)" if len(offenders) > 8 else ""
        raise AssertionError(
            f"Pokemon XD ({world.player_name}): {len(offenders)} location(s) sit in an always-open bucket "
            f"region with no access rule and are still allowed to hold progression, which reads as sphere "
            f"zero and generates silently: {shown}{more}. Give them a rule or mark them EXCLUDED -- see "
            f"rules.py's ADDENDUM 183 section."
        )
