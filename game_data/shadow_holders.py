"""Who holds each Shadow, resolved once, before anything reads a level -- the level census, the logic gates
and the expansion planner used to work it out separately and disagree. Each record carries the trainer row,
the occurrence of that name, the ordinary levels on that team, their average, and the placement region.

The rule is the EARLIEST occurrence that carries the Shadow: seven of the 83 vanilla Shadows are carried by
more than one occurrence of one trainer, and a Shadow is snagged the first time it is offered, which is what
`shadow_regions.gate_for_label` also takes. Generated Shadows need no special case, since each trainer row is
one occurrence. Nothing here is seed-dependent, so generate_early, generate_output and a test cannot disagree.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import load_json_data_file, trainer_placements, trainer_roster


@dataclass(frozen=True)
class ShadowHolder:
    """One fight, and everything about it a level or a gate needs."""

    trainer_index: int
    surname: str
    occurrence: int              # 1-based, among trainers sharing this surname
    total_with_name: int
    team_levels: "tuple[int, ...]"   # the ORDINARY (DPKM) members' levels; a Shadow has none of its own here
    region: "str | None"         # trainer_placements' region, None for the filler-only rows

    @property
    def team_avg_level(self) -> "float | None":
        """None when there is no ordinary member to average -- nine Shadows are held by all-Shadow trainers
        (Hordel's, Greevil's six). Callers keep the Shadow's own level there rather than invent one."""
        if not self.team_levels:
            return None
        return sum(self.team_levels) / len(self.team_levels)

    def describe(self) -> str:
        name = f"{self.surname.title()}"
        if self.total_with_name > 1:
            name += f" #{self.occurrence}"
        average = "no ordinary team" if self.team_avg_level is None else f"team avg {self.team_avg_level:.1f}"
        return f"{name} (trainer {self.trainer_index}, {self.region or 'no region'}, {average})"


def _story_trainers() -> "list[dict]":
    return load_json_data_file("deckdata_story_trainers.json") or []


def _ordinary_levels(trainer: dict) -> "tuple[int, ...]":
    return tuple(slot["level"] for slot in trainer.get("team", [])
                 if slot.get("kind") == "DPKM" and slot.get("level") is not None)


def holder_for_trainer_index(index: int) -> "ShadowHolder | None":
    """The holder record for one trainer row. This is the whole answer for a GENERATED Shadow, whose host is
    already a specific occurrence."""
    trainer = trainer_roster.TRAINERS_BY_INDEX.get(index)
    if trainer is None:
        return None
    return ShadowHolder(
        trainer_index=index,
        surname=trainer["name"],
        occurrence=trainer["occurrence"],
        total_with_name=trainer["total_with_name"],
        team_levels=_ordinary_levels(trainer),
        region=trainer_placements.region_for(index),
    )


def vanilla_shadow_holders() -> "dict[int, ShadowHolder]":
    """ddpk_index -> the EARLIEST fight that carries it. Empty when the roster data is missing from this
    build, which every caller already treats as "no census" (see real_trainer_data's loaders)."""
    earliest: "dict[int, int]" = {}
    for trainer in _story_trainers():
        for slot in trainer.get("team", []):
            if slot.get("kind") != "DDPK" or slot.get("ddpk_index") is None:
                continue
            ddpk = slot["ddpk_index"]
            index = trainer["index"]
            earliest[ddpk] = index if ddpk not in earliest else min(earliest[ddpk], index)
    out: "dict[int, ShadowHolder]" = {}
    for ddpk, index in earliest.items():
        holder = holder_for_trainer_index(index)
        if holder is not None:
            out[ddpk] = holder
    return out


def shadows_held_more_than_once() -> "dict[int, tuple[int, ...]]":
    """ddpk_index -> every trainer row carrying it, ascending. The population the earliest-wins rule is about;
    exposed so a test can assert against the DATA rather than against a remembered count."""
    holders: "dict[int, list[int]]" = {}
    for trainer in _story_trainers():
        for slot in trainer.get("team", []):
            if slot.get("kind") == "DDPK" and slot.get("ddpk_index") is not None:
                holders.setdefault(slot["ddpk_index"], []).append(trainer["index"])
    return {ddpk: tuple(sorted(rows)) for ddpk, rows in holders.items() if len(rows) > 1}


def describe_resolution(effective_levels: "dict[int, int] | None" = None) -> "list[str]":
    """One line per Shadow whose holder was ambiguous, for the seed notes and `!shadowdex`-style output.

    A ShadowHolder only knows the VANILLA team average, so on a re-levelled team these lines used to describe
    a level nobody was writing. Pass `{ddpk_index: the level actually assigned}` as `effective_levels` and the
    line states that instead, which is what makes a wrong level checkable from the patch."""
    holders = vanilla_shadow_holders()
    lines: "list[str]" = []
    for ddpk, rows in sorted(shadows_held_more_than_once().items()):
        holder = holders.get(ddpk)
        if holder is None:
            continue
        others = ", ".join(str(i) for i in rows if i != holder.trainer_index)
        line = f"Shadow {ddpk}: matched to {holder.describe()}"
        if effective_levels is not None and ddpk in effective_levels:
            line += f", written at level {effective_levels[ddpk]}"
        lines.append(f"{line}; also carried by trainer(s) {others}")
    return lines
