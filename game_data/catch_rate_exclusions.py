"""ADDENDUM 416 -- the fights whose Shadows keep their vanilla catch rate under Max Catch Rate.

Options exclude two places from catch-rate maxing: Citadark Isle and Greevil.

A Shadow's catch rate is ONE byte on its DDPK record (`catch_rate_override`, +0x01), shared by every fight that
carries that record. So the rate cannot differ by place; it follows the record. These are TRAINER indices -- the
expansion's Shadows only get their DDPK slots at patch time, so `tools/iso_patcher.py` resolves the records off
the patched DeckData_Story.bin, and keeps a record vanilla only when its EARLIEST holder is one of these (a Shadow
is snagged the first time it is offered -- the rule `shadow_holders` uses).
"""
from __future__ import annotations

from . import trainer_placements, trainer_roster

CITADARK_REGION = "Citadark Isle"


def citadark_trainer_indices() -> "frozenset[int]":
    return frozenset(index for index, placement in trainer_placements.PLACEMENTS.items()
                     if placement.region == CITADARK_REGION)


def greevil_trainer_indices() -> "frozenset[int]":
    return frozenset(t["index"] for t in trainer_roster.TRAINERS if t["name"].upper() == "GREEVIL")


def catch_rate_excluded_trainer_indices(citadark: bool, greevil: bool) -> "frozenset[int]":
    out: "set[int]" = set()
    if citadark:
        out |= citadark_trainer_indices()
    if greevil:
        out |= greevil_trainer_indices()
    return frozenset(out)


def excluded_ddpk_indices(trainer_teams: "dict[int, list[int]]", excluded: "frozenset[int] | set[int]") -> "set[int]":
    """{ddpk_index} whose EARLIEST holder is excluded. `trainer_teams` is {trainer_index: [ddpk_index, ...]} for
    every trainer, read off the deck being patched."""
    earliest: "dict[int, int]" = {}
    for trainer_index, ddpks in trainer_teams.items():
        for ddpk in ddpks:
            if ddpk not in earliest or trainer_index < earliest[ddpk]:
                earliest[ddpk] = trainer_index
    return {ddpk for ddpk, holder in earliest.items() if holder in excluded}
