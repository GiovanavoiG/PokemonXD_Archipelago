"""ADDENDUM 467 -- a Shadow given to a trainer goes on every occurrence of that trainer; one catch clears it from all.

Player: "If you're giving them a shadow pokemon, give it to the #1, #2, etc., the same pokemon. Then, if it's caught
from ANY, remove it from all."

ONE RECORD, MANY SLOTS. A trainer's Shadow slot holds a DDPK index, and the save tracks a Shadow by that index. So
the same DDPK index is written into a free slot of each of the trainer's other occurrences (`mirror_trainer_indices`):
whichever of them the player meets first, it is the same Shadow, met the same way. Once it is snagged (status 3,
ADDENDUM 465) or beaten and fled to Miror B. (status 2, ADDENDUM 468) every ordinary trainer skips it -- "remove it
from all" is the engine's own bookkeeping -- and a fled one is fielded by Miror B. alone, as in the vanilla game.

WHAT GETS A COPY. Every other deck row with the host's name ("CIDA" #1/#2/#3, "NAPS" #1/#2 ...), except:
  * rows that cannot field one sensibly -- the goal fight, Citadark Isle (Nightmare teams and Shadow removal live
    there), the fights the player only watches (`NO_SNAG_TRAINER_INDICES`), and the tutorial/permanently-excluded
    fights (`PERMANENTLY_EXCLUDED_TRAINER_INDICES`: Chobin #1 among them, before the Snag Machine), and Miror B.'s
    Poke Spot rows (#1-#6, `MIROR_B_POKE_SPOT_ROWS`) -- the engine itself brings the Shadows that fled into their
    free slots, so a written copy would compete with it;
  * rows with no free team slot left once every host has taken its own. A copy is never squeezed in: a row that is
    full simply does not get one, and the patcher skips (and counts) a slot that turned out to be taken;
  * rows far below the host's level (`MAX_LEVEL_RATIO`): the host's team averages more than 1.5x theirs. Chobin #7's
    level-38 Shadow does not go on Chobin #2's level-6 team, where it would wall an early, possibly required fight.
    Compared on the vanilla team averages, so path scaling and Enhanced Difficulty (which move both) do not tip it.

The copies change nothing in logic. The catch location stays gated on the host fight (ADDENDUM 432), the one that was
chosen because it cannot be missed; the copies are other places to meet that same Shadow, so they may sit on
missable or post-game rows.

The copy is the same Pokemon -- one DPKM record -- so it has one level: the host team's. On an earlier occurrence it
can be above that team, on a later one below.

REVERT: `SHADOW_MIRRORS_ENABLED = False` plans no copies; the patcher then writes none. `MAX_LEVEL_RATIO = None`
drops only the level fence.
"""
from __future__ import annotations

SHADOW_MIRRORS_ENABLED = True

#: A copy only goes on a row whose vanilla team average is at least host average / this. None: no level fence.
MAX_LEVEL_RATIO: "float | None" = 1.5

#: Miror B. #1-#6: two Pokemon and four open slots that the game fills with the Shadows that fled (status 2).
MIROR_B_POKE_SPOT_ROWS: "frozenset[int]" = frozenset(range(2, 8))

# ADDENDUM 487. Player: "clerr/belish/dosk/dert/raling/labet/doby can be opened with the mirrors. Leave the rest as
# is." Each has a first fight (#1) and a second (#2) in the same town, and a late player may meet only the second.
# So the FIRST hosts the Shadow and the SECOND always carries its mirror -- the catch is in both fights, whichever the
# player meets. {host row: its later rows in the story}. Guaranteed, not best-effort: a host is capped at the slots
# its partners have free (`cap_census_for_mirrored_hosts`), a partner hosts nothing of its own, and `plan_mirrors`
# places every partner copy first, past the level-ratio rule. Each trainer's last row has no region and gains a copy
# only if a slot is left. Player, after: "You can open Cail with the mirrors too." -- Cail has three Pyrite fights,
# so his first carries the Shadow and the second and third both carry the copy.
MIRRORED_SHADOW_HOSTS: "dict[int, tuple[int, ...]]" = {
    19: (80,),        # Clerr #1 -> #2, Agate Village
    20: (81,),        # Belish #1 -> #2, Agate Village
    22: (82,),        # Dosk #1 -> #2, Agate Village
    65: (108,),       # Dert #1 -> #2, Pyrite Town
    66: (109,),       # Raling #1 -> #2, Pyrite Town
    67: (110,),       # Labet #1 -> #2, Pyrite Town
    68: (111,),       # Doby #1 -> #2, Pyrite Town
    62: (90, 126),    # Cail #1 -> #2, #3, Pyrite Town
}


def mirrored_partner_rows() -> "frozenset[int]":
    return frozenset(partner for partners in MIRRORED_SHADOW_HOSTS.values() for partner in partners)


def mirrored_host_rows() -> "frozenset[int]":
    """The rows that may host a Shadow only because its mirror is guaranteed -- none when mirrors are off."""
    return frozenset(MIRRORED_SHADOW_HOSTS) if SHADOW_MIRRORS_ENABLED else frozenset()


def cap_census_for_mirrored_hosts(free_slot_census: "list[dict]") -> "list[dict]":
    """A copy of the census in which each mirrored host has no more free slots than its partner, so every Shadow
    hosted there has a partner slot for its copy. Rows not in `MIRRORED_SHADOW_HOSTS` are passed through unchanged."""
    if not SHADOW_MIRRORS_ENABLED:
        return list(free_slot_census or ())
    free = {int(row["trainer_index"]): int(row["free_slots"]) for row in free_slot_census or ()}
    out = []
    for row in free_slot_census or ():
        partners = MIRRORED_SHADOW_HOSTS.get(int(row["trainer_index"]))
        if partners:
            row = {**row, "free_slots": min([int(row["free_slots"])] + [free.get(p, 0) for p in partners])}
        out.append(row)
    return out


def occurrences_of(trainer_index: int) -> "list[int]":
    """Every story deck row carrying `trainer_index`'s name, itself included, in index order."""
    from .trainer_roster import TRAINERS_BY_INDEX

    host = TRAINERS_BY_INDEX.get(int(trainer_index))
    if host is None:
        return [int(trainer_index)]
    name = host["name"].upper()
    return sorted(i for i, t in TRAINERS_BY_INDEX.items() if t["name"].upper() == name)


def mirror_excluded_trainer_indices(extra: "frozenset[int] | set[int]" = frozenset()) -> "frozenset[int]":
    from .catch_rate_exclusions import citadark_trainer_indices
    from .missable_trainers import POST_GOAL_TRAINER_INDICES
    from .real_trainer_data import PERMANENTLY_EXCLUDED_TRAINER_INDICES
    from .shadow_regions import NO_SNAG_TRAINER_INDICES

    return (frozenset(POST_GOAL_TRAINER_INDICES) | frozenset(citadark_trainer_indices())
            | frozenset(NO_SNAG_TRAINER_INDICES) | frozenset(PERMANENTLY_EXCLUDED_TRAINER_INDICES)
            | MIROR_B_POKE_SPOT_ROWS | frozenset(int(i) for i in extra))


def plan_mirrors(free_slot_census: "list[dict] | None", host_shadows: "list[tuple[int, dict]]",
                 taken: "dict[int, int]", excluded: "frozenset[int] | set[int]" = frozenset()) -> "dict[int, int]":
    """Write `mirror_trainer_indices` into each shadow dict of `host_shadows` -- `[(host trainer index, the plan's
    dict for one Shadow)]`, in the order slots should be handed out -- and return {trainer index: slots the copies
    take}. `taken` is what the hosts themselves already claim ({trainer index: count}); a copy only gets a slot left
    over after that and after earlier copies. Deterministic: no RNG, so Universal Tracker regenerates it exactly."""
    used: "dict[int, int]" = {}
    if not SHADOW_MIRRORS_ENABLED or not free_slot_census:
        for _host, shadow in host_shadows:
            shadow["mirror_trainer_indices"] = []
        return used
    free = {int(row["trainer_index"]): int(row["free_slots"]) for row in free_slot_census}
    level = {int(row["trainer_index"]): float(row["avg_level"]) for row in free_slot_census
             if row.get("avg_level")}
    blocked = mirror_excluded_trainer_indices(excluded)
    for host, shadow in host_shadows:
        mirrors = []
        # ADDENDUM 487: a mirrored host's partner copies come first and are never skipped for level.
        for partner in MIRRORED_SHADOW_HOSTS.get(int(host), ()):
            if partner in blocked:
                continue
            left = free.get(partner, 0) - int(taken.get(partner, 0)) - used.get(partner, 0)
            if left > 0:
                mirrors.append(partner)
                used[partner] = used.get(partner, 0) + 1
            else:
                shadow["mirror_required_missing"] = partner     # cannot happen with a capped census -- tested
        for other in occurrences_of(host):
            if other == int(host) or other in blocked or other in mirrors:
                continue
            if (MAX_LEVEL_RATIO is not None and int(host) in level
                    and level.get(other, 0.0) * MAX_LEVEL_RATIO < level[int(host)]):
                continue
            left = free.get(other, 0) - int(taken.get(other, 0)) - used.get(other, 0)
            if left <= 0:
                continue
            mirrors.append(other)
            used[other] = used.get(other, 0) + 1
        shadow["mirror_trainer_indices"] = mirrors
    return used
