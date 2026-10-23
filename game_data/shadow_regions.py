"""Where each vanilla Shadow Pokemon actually is, by the region of the trainer holding it (ADDENDUM 177).

Replaces `rules._PURIFICATION_WEIGHT_BY_REGION`, the last estimate-shaped weight table in the project: it
guessed how many of the 32 "Purify N Shadow Pokemon" thresholds each region supplied against a seven-region
skeleton, and still carried a `"_retired Relic Forest": 0` tombstone.

Two joins against data already here: `data/shadow_pokemon_list.json` (83 shadows) names the TRAINER holding
each one as a display label ("Spy Naps"), and `trainer_roster.TRAINERS` plus `trainer_placements` turn that
surname into a region from the census (ADDENDUM 175). The surname is matched by LONGEST SUFFIX
rather than by splitting on spaces, because "Miror B." is a two-word surname with a period in it. A trainer
fought more than once gets the EARLIEST of their regions in graph order -- a shadow is obtainable from the
first fight that offers it, and taking the latest would make the ladder harder than the game.

Four shadows resolve by `area` text instead, listed below rather than silently defaulted: three of their
trainers are not in the 232-story roster and one is (Hordel, whose census row is filler-only).
Hordel's shadow area reads "Outskirt Stand", which his census row does not claim -- the census answers where
his DEFEAT check is and this file where his shadow is obtainable -- but it is the hint if that row is
revisited.
"""
from __future__ import annotations

import functools

import json
import os
from typing import NamedTuple

from . import trainer_placements, trainer_roster

_SHADOW_LIST_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data",
                                 "shadow_pokemon_list.json")

# Shadows whose holding trainer cannot be resolved through the roster/census join, with the region their own
# `area` field states. Kept as an explicit table so an unresolvable shadow is a decision rather than a default.
_AREA_FALLBACK: "dict[str, str]" = {
    "Cipher Peon Labor": "Pyrite Town (ONBS)",    # area: "ONBS Station"
    "Hordel": "Outskirt Stand",                   # area: "Outskirt Stand" -- see the module docstring
    "Cipher Peon Gefta": "Citadark Isle",         # area: "Citadark Isle"
    "Cipher Peon Stron": "Citadark Isle",         # area: "Citadark Isle"
}


def _load() -> "list[dict]":
    """ADDENDUM 195: read through the package's own zip-safe loader, not `open()`. A path built from
    `__file__` works from a loose checkout but not from an installed `.apworld`, where `__file__` points
    inside the zip, and the old `except Exception: return []` turned that into an empty shadow list. rules.py
    asserts at import time that the purification weights sum to `PURIFICATION_LOCATION_COUNT`, so empty ->
    sum 0 -> AssertionError -> the world never registers and the Launcher cannot build a YAML template."""
    from . import load_json_data_file

    return load_json_data_file("shadow_pokemon_list.json") or []


# ADDENDUM 363: these three cache a constant regrouping that was rebuilt hundreds of times per seed. A world
# generation spent a measured 20% of its time here -- `shadow_regions_in_graph_order` calls `gate_for_label`
# 166 times per seed, and each call rebuilt the 232-trainer roster index and linear-scanned its 144
# surnames, from module-level constants that cannot change within a process. Safe because it adds no sharing
# that did not already exist: the returned dicts are the same `trainer_roster.TRAINERS` dicts every caller
# gets, and `TrainerGate` is a NamedTuple. `load_json_data_file` is deliberately NOT cached though it is
# next on the profile -- its callers build fresh structures and some edit them, so caching there would share
# mutable per-seed data between generations.
@functools.lru_cache(maxsize=1)
def _roster_by_surname() -> "dict[str, list[dict]]":
    out: "dict[str, list[dict]]" = {}
    for trainer in trainer_roster.TRAINERS:
        out.setdefault(trainer["name"].upper(), []).append(trainer)
    return out


@functools.lru_cache(maxsize=None)
def _surname_of_cached(label: str) -> "str | None":
    """`_surname_of` with the roster taken from `_roster_by_surname()`, so it is a function of the label
    alone and can be cached. Separate from `_surname_of`, which tests call with a hand-built roster."""
    return _surname_of(label, _roster_by_surname())


def _surname_of(label: str, roster: "dict[str, list[dict]]") -> "str | None":
    """Longest roster surname that `label` ends with. Suffix matching rather than word splitting, so a
    multi-word surname with punctuation ("Miror B.") survives."""
    upper = label.upper()
    best: "str | None" = None
    for surname in roster:
        if upper.endswith(surname) and (best is None or len(surname) > len(best)):
            best = surname
    return best


@functools.lru_cache(maxsize=1)
def _region_order_cached() -> "tuple[str, ...]":
    """A tuple: an lru_cache handing the same mutable list to every caller is a hazard, the same tuple is
    not. `_region_order` stays for callers that want a list of their own."""
    from .. import regions

    return tuple(regions.REGION_NAMES)


def _region_order() -> "list[str]":
    return list(_region_order_cached())


# ADDENDUM 183: the same join, exposed per SHADOW SLOT instead of per purification threshold. A catch
# location needs the trainer's whole gate -- region plus the extra items and regions the census recorded for
# that fight (trainer_placements.TrainerPlacement) -- so the label-to-trainer join moved out of
# `shadow_regions_in_graph_order` into `gate_for_label`, which both consumers now call. It keys on a LABEL
# because that is all a shadow slot knows: its AP location name ("Shadow Defeat - Spy Naps (Teddiursa)")
# carries the label between "Shadow Defeat - " and " (", the same string `data/shadow_pokemon_list.json`
# puts in its `trainer` field. The species in the parentheses is the VANILLA one and is deliberately unused
# -- with randomize_shadow_species on, the species changed and the label did not.


class TrainerGate(NamedTuple):
    """A trainer's full access requirement: be able to get to `region`, hold `required_items`, and also be able
    to reach every name in `required_regions`. All three are ANDed -- `trainer_placements`' own convention."""
    region: str
    required_items: "tuple[str, ...]"
    required_regions: "tuple[str, ...]"
    source: str  # how the region was resolved, for diagnostics and tests


def trainer_label_from_location(location_name: str) -> str:
    """"Shadow Defeat - Spy Naps (Teddiursa)" -> "Spy Naps". Anything unrecognised comes back unchanged, which
    then simply fails to match a roster surname and resolves to None -- an unknown holder, not a crash."""
    text = location_name
    prefix = "Shadow Defeat - "
    if text.startswith(prefix):
        text = text[len(prefix):]
    return text.rsplit(" (", 1)[0].strip()


def gate_for_label(label: str) -> "TrainerGate | None":
    """The full gate for whoever holds a shadow, or None when this project has no region for them. None is a
    real answer callers must honour: 37 of the 232 census rows are `region=None` because they are marked
    filler-only, and inventing a region would put a fake requirement on a check. ADDENDUM 182 found the
    opposite failure -- ungated AND progression-eligible -- so None must mean filler-only."""
    roster = _roster_by_surname()
    order = _region_order_cached()
    surname = _surname_of_cached(label)
    if surname is not None:
        rows = [
            (trainer_placements.region_for(t["index"]), t["index"])
            for t in roster[surname]
        ]
        rows = [(region, index) for region, index in rows if region in order]
        if rows:
            # Fought more than once: take the EARLIEST region and that encounter's own placement row. The
            # shadow is obtainable from the first fight; a later one would claim a requirement that is not
            # in the game.
            region, index = min(rows, key=lambda row: order.index(row[0]))
            placement = trainer_placements.placement_for(index)
            return TrainerGate(
                region,
                tuple(placement.required_items) if placement else (),
                tuple(placement.required_regions) if placement else (),
                f"census row #{index} ({surname})",
            )
    fallback = _AREA_FALLBACK.get(label)
    if fallback is not None and fallback in order:
        # No census row at all, so there are no extra item/region requirements -- the `area` string is
        # the whole of what is known about these four.
        return TrainerGate(fallback, (), (), "area fallback")
    return None


def gate_for_trainer_index(index: int) -> "TrainerGate | None":
    """The same gate for an ORDINARY trainer, addressed by roster index. This is the path a GENERATED shadow
    takes: `shadow_pokemon_expansion` hangs new Shadow Pokemon on real trainers by index, never by label."""
    region = trainer_placements.region_for(index)
    if region is None:
        return None
    placement = trainer_placements.placement_for(index)
    return TrainerGate(
        region,
        tuple(placement.required_items) if placement else (),
        tuple(placement.required_regions) if placement else (),
        f"expansion host #{index}",
    )


# ADDENDUM 432: a Shadow is snagged from the FIGHT that carries it, so it is gated by that trainer ROW -- never by
# the trainer's NAME. `gate_for_label` resolved a label to a surname and took that surname's EARLIEST region, so
# every Shadow of a trainer who appears more than once was gated at their first appearance whether or not that
# fight carried it: Lovrina's Citadark pair at the Cipher Lab, Ardos's three at Gateon Port, Snattle's and
# Gorigan's Citadark pairs at Phenac and the Key Lair, Smarton's Arbok at the SS Libra, Miror B.'s post-game
# Dragonite at the Poke Spots. The fix covers every character who appears more than once.
#
# The rows a Shadow cannot be snagged from at all, even though they carry or could carry one. Ardos shows up in
# Gateon, but his team cannot be caught at all until Citadark, and the same holds for Zook and Biden.
# ADDENDUM 433 corrected Biden's row: his KEY LAIR fight is uncatchable; his Snagem fight is fine.
NO_SNAG_TRAINER_INDICES: "frozenset[int]" = frozenset({
    9,     # Zook #1, Gateon Port -- his Zangoose is snagged at the Cipher Key Lair (row 147)
    10,    # Ardos #1, Gateon Port
    148,   # Biden #2, Cipher Key Lair (exterior) -- his Snagem Hideout fight (row 143) is snaggable
})

# The three Shadows whose every carrying row has no census region (those rows are filler-only), with
# the region the Shadow is really obtainable in. A decision per Shadow, not a default.
DDPK_REGION_FALLBACK: "dict[int, tuple[str, str]]" = {
    29: ("Poke Spots", "Miror B.'s Voltorb, at the Cave Poke Spot"),
    80: ("Citadark Isle", "Miror B.'s Dragonite, a post-game rematch at Gateon -- nothing earlier than the end game"),
    81: ("Outskirt Stand", "Hordel's Togepi, at the Outskirt Stand"),
}

# ADDENDUM 473: Shadows only obtainable AFTER the goal.
# Miror B.'s Dragonite (DDPK 80) is his post-game Gateon rematch. Its Citadark fallback above stays -- it is still
# where the island's ladder files it -- but rules.py adds the goal itself ("Victory") to every way of getting it:
# its catch location and every `Purify N` that needs it are reachable only after the goal, and are filler-only.
#
# ADDENDUM 479: and every Shadow Greevil carries. Post-game/post-Greevil Shadows get no checks, since a check on one
# could softlock; their trainers stay randomized.
# Shadow Lugia (his first fight, DDPK 73) and the six of his second (DDPK 74-79, the goal fight itself) can only be
# PURIFIED once Greevil is beaten. These Shadows now have no checks at all: no `Catch - X` for a species only they
# carry, and no `Purify N` counted for them -- this seed's purification ladder is one rung per Shadow that can be
# had before the goal. Their trainers are untouched. A Shadow MOVED off Greevil (Remove Greevil Shadows, which
# hands his seven to unmissable trainers elsewhere) is not at its Greevil row any more and keeps its checks.
POST_GOAL_DRAGONITE_DDPK = 80
GREEVIL_SHADOW_ROWS: "frozenset[int]" = frozenset({199, 200, 201})


def _greevil_only_ddpks() -> "frozenset[int]":
    rows_by_ddpk = shadow_carriers()
    return frozenset(ddpk for ddpk, rows in rows_by_ddpk.items() if rows and set(rows) <= GREEVIL_SHADOW_ROWS)


#: The event item Greevil's defeat awards (regions.py), required on top of a post-Greevil Shadow's gate. Not
#: "Victory": with the Mt. Battle goal that is the Mt. Battle win.
POST_GOAL_EVENT_ITEM = "Greevil Defeated"


@functools.lru_cache(maxsize=1)
def shadow_carriers() -> "dict[int, tuple[int, ...]]":
    """ddpk_index -> every Story-deck trainer row carrying it, ascending. The Sixes' Phenac rows are not carriers: the
    patch makes their Shadow slot an ordinary Pokemon (`shadow_mirrors.SIXES_PHENAC_SHADOW_SLOTS`), so those Shadows
    are only ever snagged at the Cipher Lab."""
    from . import load_json_data_file
    from .shadow_mirrors import SIXES_PHENAC_SHADOW_SLOTS

    not_carried = set(SIXES_PHENAC_SHADOW_SLOTS)
    out: "dict[int, list[int]]" = {}
    for trainer in load_json_data_file("deckdata_story_trainers.json") or []:
        for slot in trainer.get("team", []):
            if slot.get("kind") == "DDPK" and slot.get("ddpk_index") is not None:
                if (int(trainer["index"]), int(slot["ddpk_index"])) in not_carried:
                    continue
                out.setdefault(int(slot["ddpk_index"]), []).append(int(trainer["index"]))
    return {ddpk: tuple(sorted(set(rows))) for ddpk, rows in out.items()}


# Lugia (73) and Greevil's six (74-79), read off the census; the literal is only for a build missing the data file.
POST_GOAL_SHADOW_DDPKS: "frozenset[int]" = frozenset({POST_GOAL_DRAGONITE_DDPK}) | (
    _greevil_only_ddpks() or frozenset(range(73, 80)))


@functools.lru_cache(maxsize=1)
def ddpk_for_dpkm() -> "dict[int, int]":
    """dpkm_index -> ddpk_index, for the 83 vanilla Shadows."""
    from . import load_json_data_file

    return {int(e["dpkm_index"]): int(e["ddpk_index"]) for e in load_json_data_file("deckdata_dark_pokemon.json") or []}


@functools.lru_cache(maxsize=None)
def gates_for_ddpk(ddpk: int) -> "tuple[TrainerGate, ...]":
    """Every way to snag vanilla Shadow `ddpk`: one gate per carrying row a Shadow can be snagged from, ANY of
    which will do. Empty only for a DDPK this project does not know."""
    gates = []
    for index in shadow_carriers().get(int(ddpk), ()):
        if index in NO_SNAG_TRAINER_INDICES:
            continue
        gate = gate_for_trainer_index(index)
        if gate is not None and gate.region in _region_order_cached():
            gates.append(gate._replace(source=f"carrier #{index}"))
    if not gates and int(ddpk) in DDPK_REGION_FALLBACK:
        region, why = DDPK_REGION_FALLBACK[int(ddpk)]
        gates.append(TrainerGate(region, (), (), f"fallback: {why}"))
    if int(ddpk) in POST_GOAL_SHADOW_DDPKS:
        # ADDENDUM 473: only after the goal -- every way to it also needs the goal's own event item.
        gates = [g._replace(required_items=tuple(g.required_items) + (POST_GOAL_EVENT_ITEM,),
                            source=f"{g.source}, after the goal") for g in gates]
    return tuple(gates)


def shadow_regions_in_graph_order(exclude_dex: "frozenset[int]" = frozenset(),
                                  include_post_goal: bool = True) -> "list[tuple[str, str]]":
    """[(region, species_name), ...] for every vanilla shadow, sorted by how early its EARLIEST snag region is in
    the graph. ADDENDUM 432: by carrying trainer row, not by name -- see `gates_for_ddpk`. ADDENDUM 479:
    `include_post_goal=False` leaves out the Shadows that have no checks (`POST_GOAL_SHADOW_DDPKS`)."""
    from . import load_json_data_file
    from ..tools.xd_species_index import INTERNAL_INDEX_TO_NATIONAL_DEX

    order = _region_order()
    rows: "list[tuple[int, str, str]]" = []
    for entry in load_json_data_file("deckdata_dark_pokemon.json") or []:
        dex, name = INTERNAL_INDEX_TO_NATIONAL_DEX.get(int(entry["species"]), (None, "?"))
        if dex in exclude_dex:
            continue   # ADDENDUM 423: a Shadow this seed removed (Nightmare Citadark)
        if not include_post_goal and is_post_goal_ddpk(int(entry["ddpk_index"])):
            continue   # ADDENDUM 479
        gates = gates_for_ddpk(int(entry["ddpk_index"]))
        if not gates:
            continue
        region = min((g.region for g in gates), key=order.index)
        rows.append((order.index(region), region, str(name).title()))
    rows.sort(key=lambda row: row[0])
    return [(region, species) for _position, region, species in rows]


def is_post_goal_ddpk(ddpk: int) -> bool:
    """ADDENDUM 479: a Shadow that, at its own trainer, can only be purified after the goal -- no checks."""
    return int(ddpk) in POST_GOAL_SHADOW_DDPKS


# ADDENDUM 184: where you CATCH a shadow and where you can PURIFY it are different questions, and this
# ladder answers the second. Without a floor, thresholds 1-7 file under Pokemon HQ Lab and Gateon Port,
# where their shadows are snagged -- both always open, so they read as sphere zero and can hold the Machine
# Part, which is the key to Agate Village, the only place that purifies. The
# floor is Agate Village itself; the Purify Chamber's own unlock is deliberately not modelled on top.
PURIFICATION_FLOOR_REGION = "Agate Village"


def purification_weights(threshold_count: int, exclude_dex: "frozenset[int]" = frozenset(),
                         include_post_goal: bool = True) -> "dict[str, int]":
    """How many of the first `threshold_count` purification thresholds each region supplies. Truncated at
    `threshold_count` on purpose: 83 vanilla shadows, but the ladder is only as long as
    `locations.PURIFICATION_LOCATION_COUNT` (32). Threshold N is gated where the Nth shadow becomes
    PURIFIABLE -- the later of its snag region and Agate Village -- so the counts sum to exactly
    `threshold_count`, which rules.py asserts."""
    order = _region_order()
    floor_at = order.index(PURIFICATION_FLOOR_REGION) if PURIFICATION_FLOOR_REGION in order else 0
    counts: "dict[str, int]" = {}
    for region, _species in shadow_regions_in_graph_order(exclude_dex, include_post_goal)[:threshold_count]:
        if order.index(region) < floor_at:
            region = PURIFICATION_FLOOR_REGION
        counts[region] = counts.get(region, 0) + 1
    return counts


def total_shadow_count() -> int:
    return len(shadow_regions_in_graph_order())
