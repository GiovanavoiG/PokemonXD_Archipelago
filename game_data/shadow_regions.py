"""Where each vanilla Shadow Pokemon actually is, by the region of the trainer holding it (ADDENDUM 177).

Replaces `rules._PURIFICATION_WEIGHT_BY_REGION`, the last estimate-shaped weight table in the project: it
guessed how many of the 32 "Purify N Shadow Pokemon" thresholds each region supplied against a seven-region
skeleton, and still carried a `"_retired Relic Forest": 0` tombstone.

Two joins against data already here: `data/shadow_pokemon_list.json` (83 shadows) names the TRAINER holding
each one as a display label ("Spy Naps"), and `trainer_roster.TRAINERS` plus `trainer_placements` turn that
surname into a region from the player's own census (ADDENDUM 175). The surname is matched by LONGEST SUFFIX
rather than by splitting on spaces, because "Miror B." is a two-word surname with a period in it. A trainer
fought more than once gets the EARLIEST of their regions in graph order -- a shadow is obtainable from the
first fight that offers it, and taking the latest would make the ladder harder than the game.

Four shadows resolve by `area` text instead, listed below rather than silently defaulted: three of their
trainers are not in the 232-story roster and one is (Hordel, whose census row the player left filler-only).
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
    real answer callers must honour: 37 of the 232 census rows are `region=None` because the player marked
    them filler-only, and inventing a region would put a fake requirement on a check. ADDENDUM 182 found the
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


def shadow_regions_in_graph_order() -> "list[tuple[str, str]]":
    """[(region, species_name), ...] for every vanilla shadow, sorted by how early its region is in the graph.

    This ordering IS the purification ladder: the Nth threshold becomes obtainable in the region of the Nth
    shadow here."""
    order = _region_order()
    rows: "list[tuple[int, str, str]]" = []
    for shadow in _load():
        # ADDENDUM 183: one join, shared with the catch gates -- see gate_for_label above. The ladder only
        # wants the region half of it.
        gate = gate_for_label(shadow.get("trainer", ""))
        if gate is None or gate.region not in order:
            continue
        rows.append((order.index(gate.region), gate.region, shadow.get("species_name", "?")))
    rows.sort(key=lambda row: row[0])
    return [(region, species) for _position, region, species in rows]


# ADDENDUM 184: where you CATCH a shadow and where you can PURIFY it are different questions, and this
# ladder answers the second. Without a floor, thresholds 1-7 file under Pokemon HQ Lab and Gateon Port,
# where their shadows are snagged -- both always open, so they read as sphere zero and can hold the Machine
# Part, which is the key to Agate Village, the only place that purifies. Per the player's instruction the
# floor is Agate Village itself; the Purify Chamber's own unlock is deliberately not modelled on top.
PURIFICATION_FLOOR_REGION = "Agate Village"


def purification_weights(threshold_count: int) -> "dict[str, int]":
    """How many of the first `threshold_count` purification thresholds each region supplies. Truncated at
    `threshold_count` on purpose: 83 vanilla shadows, but the ladder is only as long as
    `locations.PURIFICATION_LOCATION_COUNT` (32). Threshold N is gated where the Nth shadow becomes
    PURIFIABLE -- the later of its snag region and Agate Village -- so the counts sum to exactly
    `threshold_count`, which rules.py asserts."""
    order = _region_order()
    floor_at = order.index(PURIFICATION_FLOOR_REGION) if PURIFICATION_FLOOR_REGION in order else 0
    counts: "dict[str, int]" = {}
    for region, _species in shadow_regions_in_graph_order()[:threshold_count]:
        if order.index(region) < floor_at:
            region = PURIFICATION_FLOOR_REGION
        counts[region] = counts.get(region, 0) + 1
    return counts


def total_shadow_count() -> int:
    return len(shadow_regions_in_graph_order())
