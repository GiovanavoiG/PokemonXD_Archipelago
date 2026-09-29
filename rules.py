"""
Access rules for individual locations. Region-level gating lives in regions.py's entrance rules; a location
gets a rule here only when its parent region's reachability is not the whole requirement.

The cumulative "Defeat N Trainers" and "Purify N Shadow Pokemon" ladders have no per-check location, so each
threshold is gated behind the earliest region whose cumulative census weight can supply the Nth one, through
`state.can_reach()` on the real region graph. No sphere number is hardcoded anywhere.

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
    """The TRAINER cumulative-count rules. Silently skips a threshold this seed did not create -- they are
    EXCLUDED either way, so a missing one is never a generation-safety concern."""
    # With ExcludeMtBattleTrainers on a Mt. Battle win no longer advances the counter, so fall back to the
    # Mt. Battle-free table. A no-op against today's census, but the options are independent.
    excluding_mt_battle = bool(getattr(world.options, "exclude_mt_battle_trainers", False))
    trainer_weights = (_UNIQUE_TRAINER_WEIGHT_BY_REGION if excluding_mt_battle
                       else _TRAINER_WEIGHT_BY_REGION)
    trainer_thresholds = _cumulative_region_thresholds(trainer_weights)
    for count in range(1, locations.TRAINER_DEFEAT_COUNT_LOCATION_COUNT + 1):
        try:
            location = world.multiworld.get_location(
                locations.trainer_defeat_count_location_name(count), world.player
            )
        except KeyError:
            continue
        region_name = _region_for_sphere_count(trainer_thresholds, count)
        set_rule(location, lambda state, r=region_name: state.can_reach(r, player=world.player))


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

_SNAG_FLOOR_REGIONS: "tuple[str, ...]" = ("Pyrite Town", "Poke Spots")
_MIROR_RADAR_CHEST_ID = 77          # its vanilla home, and why "Poke Spots" is in the floor above
_EEVEELUTION_REGION = "Gateon Port"  # player: "Eeveelution is accessible so long as gateon is, which is always"


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


def _set_catch_rules(world) -> None:
    """The "Catch - {species}" rules. Silently skips a location this seed did not create."""
    from BaseClasses import LocationProgressType

    from . import items

    player = world.player
    gates, unplaceable = _catch_gates_for_species(world)

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
        if dex == _GUARANTEED_EEVEE_DEX:
            continue
        location_name = species.location_name_for_species(dex)
        location = location_or_none(location_name)
        if location is None:
            continue

        if dex in unplaceable:
            # No honest gate exists. Filler-only is the only safe answer -- see this section's last paragraph.
            location.progress_type = LocationProgressType.EXCLUDED
            continue

        # Each source becomes a closed-over tuple of plain requirements, so the rule does no lookups at
        # evaluation time; item names are dropped when this seed's pool does not hold them.
        compiled: "list[tuple[tuple[str, ...], tuple[str, ...], bool]]" = []
        for gate in gates[dex]:
            if gate == "pokespot":
                compiled.append((("Poke Spots",), (), False))
                continue
            regions_needed = [gate.region, *gate.required_regions]
            items_needed = [items.requirement_to_pool_item(name) for name in gate.required_items]
            items_needed = [name for name in dict.fromkeys(items_needed)
                            if _requirement_is_in_the_pool(world, name)]
            compiled.append((tuple(dict.fromkeys(regions_needed)), tuple(items_needed), True))

        def rule(state, compiled=tuple(compiled), player=player):
            for regions_needed, items_needed, needs_snag_floor in compiled:
                if needs_snag_floor and not all(
                    state.can_reach(name, player=player) for name in _SNAG_FLOOR_REGIONS
                ):
                    continue
                if not all(state.can_reach(name, player=player) for name in regions_needed):
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
# on turn one. Rules first; `options.ProgressionLocations` then only opens categories that have one.

# Purification weights, a census: `data/shadow_pokemon_list.json` names the trainer holding each of the 83
# vanilla shadows and the trainer census says where that trainer is. 83 shadows, 32 thresholds -- threshold N
# is gated on the region where the Nth shadow becomes obtainable, so the weights are the region counts of the
# first 32 in graph order and sum to exactly 32 by construction. Deliberately static when
# `shadow_pokemon_expansion` adds more: the expansion hangs new shadows on existing trainers and so can only
# make a threshold reachable EARLIER, and over-strict logic merely delays a sphere.
def _purification_weights_from_census() -> "dict[str, int]":
    from .game_data import shadow_regions

    return shadow_regions.purification_weights(locations.PURIFICATION_LOCATION_COUNT)


_PURIFICATION_WEIGHT_BY_REGION: dict[str, int] = _purification_weights_from_census()

# The same census as _TRAINER_WEIGHT_BY_REGION, under its own name because `_set_sphere_rules` still selects
# between them on ExcludeMtBattleTrainers.
_UNIQUE_TRAINER_WEIGHT_BY_REGION: dict[str, int] = _trainer_weights_from_census()

assert sum(_PURIFICATION_WEIGHT_BY_REGION.values()) == locations.PURIFICATION_LOCATION_COUNT
assert sum(_UNIQUE_TRAINER_WEIGHT_BY_REGION.values()) == locations.TRAINER_DEFEAT_COUNT_LOCATION_COUNT

# _SHOP_OCCURRENCE_REGIONS is retired (ADDENDUM 176): shop locations are named after shops and filed in their
# room's own region, so the region IS the rule. Nothing models money any more.

def _has_snag_machine(state, world) -> bool:
    """Snagging needs the Snag Machine, which comes out of the Pokemon HQ Lab, which the player says the
    Machine Part is what progresses. With key_item_shuffle off the Part sits in its vanilla home and is never
    created, so there is nothing to ask for and this is trivially true (ADDENDUM 168)."""
    from . import items  # lazy, like the other item-aware rules in this module

    part = items.requirement_to_pool_item("Machine Part")
    if part not in items.GATING_KEY_ITEM_NAMES:
        return True
    if not bool(getattr(world.options, "key_item_shuffle", 1)):
        return True
    return state.has(part, world.player)


def _set_remaining_sphere_rules(world) -> None:
    """The purification ladder. Same silent-skip convention as `_set_sphere_rules`, and attached whatever
    `ProgressionLocations` says -- an honest reachability model is not something to turn off."""
    purification_thresholds = _cumulative_region_thresholds(_PURIFICATION_WEIGHT_BY_REGION)
    for count in range(1, locations.PURIFICATION_LOCATION_COUNT + 1):
        try:
            location = world.multiworld.get_location(
                locations.purification_location_name(count), world.player
            )
        except KeyError:
            continue
        region_name = _region_for_sphere_count(purification_thresholds, count)
        # ANDed with the Machine Part: reaching the region is where a shadow can be PURIFIED, holding the
        # Part is what makes there be a shadow to purify. Without it the ladder read as sphere zero in travel
        # mode and fill put the Part on a `Purify N` check.
        set_rule(location, lambda state, r=region_name: (
            state.can_reach(r, player=world.player) and _has_snag_machine(state, world)
        ))

    # The per-trainer locations used to be gated by a model, because the roster carried no region data. It
    # does now, so they live in their real regions and get real gates (`_set_trainer_census_rules`).


# ADDENDUM 174: the chest item gates. Region membership covers most chests; the rest are the player's own
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
            return  # randomize_chests off this seed -- same convention as _set_sphere_rules
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


# ADDENDUM 175: the per-trainer gates, from the player's own census -- area AND items, ANDed. The region half
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
    # Illustrative example only -- not necessarily true of the real game.
    try:
        location = world.multiworld.get_location("Realgam Tower - Colosseum Clear Reward", world.player)
    except KeyError:
        pass  # location wasn't created this seed -- fine, nothing else in this function depends on it
    else:
        set_rule(location, lambda state: state.has("Master Ball", world.player))

    _set_sphere_rules(world)
    _set_chest_rules(world)
    _set_trainer_census_rules(world)
    _set_remaining_sphere_rules(world)
    _set_catch_rules(world)
    _set_shop_tier_rules(world)
    _set_repeatable_trainer_rules(world)
    _set_named_defeat_item_gates(world)
    _assert_no_ungated_progression_in_an_always_open_bucket(world)


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
