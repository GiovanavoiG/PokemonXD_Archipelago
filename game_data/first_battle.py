"""ADDENDUM 461 -- with Randomize Starter on, the first Chobin fight is one the starter can win.

The player: "If we have random starter on, can you make it so that the first Chobin fight has a pokemon that we can
guaranteed hit for at least half its health (or close to it)? Account for immunity abilities (Levitate,
Soundproof, Flash Fire, Volt Absorb, Water Absorb, Soundproof, WONDER GUARD CAN ONLY BE HIT BY SUPEREFFECTIVE) and
type immunities. Also ensure our starter CANT ONLY HAVE explosion/selfdestruct as its attacks. Run battle sims if
you can and ensure we can win."

THE FIGHT. Story trainer 15, Chobin #1 at Kaminko's House: one Pokemon, DPKM record 25, level 5 (pinned by
ADDENDUM 281's `PINNED_TRAINER_LEVELS`, and exempt from Enhanced Difficulty's padding by
`PERMANENTLY_EXCLUDED_TRAINER_INDICES`). The player has only the level-10 starter. The ordinary team shuffle draws
that one Pokemon from the whole species pool, and with a random starter that can be a Ghost against a Normal
starter, a Levitate Pokemon against a Ground one, or a Wobbuffet whose Counter hands a strong hit back doubled.

WHAT THIS DOES. It re-draws that one Pokemon, from the same pool the shuffle uses, under two tests:

  1. The guarantee the player asked for (`battle_sim.guaranteed_fraction`): one of the starter's reliable attacks
     takes at least half the foe's HP on its WORST outcome -- lowest roll, no crit, the starter's worst IVs and
     nature, the foe's best IVs, every ability the foe could have (Trace included), type and ability immunities.
     "Or close to it": when no species reaches 50% the floor steps down (`FRACTION_TIERS`), never to nothing.
  2. A measured win: `GATE_BATTLES` full simulated fights at `MIN_WIN_RATE` or better, against the foe's real
     moveset. A draw (both faint) counts as a loss.

The foe's moves are drawn the way every trainer Pokemon's are (`team_shuffle.choose_moveset`) and then lose the
moves that can beat a level-10 Pokemon without out-fighting it (`DANGEROUS_FOE_EFFECTS`): fixed damage of 20/40,
Counter and Mirror Coat, Bide, Destiny Bond, Perish Song, Explosion, Endeavor, Super Fang. Against a Wonder Guard
starter (Shedinja), also every move that gets past Wonder Guard.

It runs from its own RNG, like the starter, and only when Randomize Starter is on; Eevee's fight is unchanged.
"""
from __future__ import annotations

import random

from . import battle_sim as bs

FIRST_CHOBIN_TRAINER_INDEX = 15
FIRST_CHOBIN_DPKM_INDEX = 25
FOE_LEVEL = 5
STARTER_LEVEL = 10

#: "at least half its health (or close to it)" -- 50% first, then a step at a time; never below the last.
FRACTION_TIERS: "tuple[float, ...]" = (0.5, 0.45, 0.4, 1 / 3, 0.25, 0.0)
GATE_BATTLES = 200
MIN_WIN_RATE = 0.99
#: Species simulated per tier before stepping down; the static test has already thinned the field.
SIM_TRIES_PER_TIER = 10

#: Moves the foe never gets: each can beat a level-10 starter without out-fighting it.
DANGEROUS_FOE_EFFECTS: "frozenset[int]" = frozenset({
    bs.E_EXPLOSION, bs.E_OHKO, bs.E_SUPER_FANG, bs.E_DRAGON_RAGE, bs.E_SONICBOOM, bs.E_COUNTER,
    bs.E_MIRROR_COAT, bs.E_BIDE, bs.E_DESTINY_BOND, bs.E_PERISH_SONG, bs.E_ENDEAVOR,
})

#: Status effects that hurt a Wonder Guard holder anyway: poison, burn, Leech Seed, weather, confusion's self-hit.
_GETS_PAST_WONDER_GUARD: "frozenset[int]" = frozenset({
    bs.E_TOXIC, bs.E_POISON, bs.E_WILL_O_WISP, bs.E_LEECH_SEED, bs.E_SANDSTORM, bs.E_HAIL, bs.E_CONFUSE,
    bs.E_SWAGGER, bs.E_FLATTER, bs.E_TEETER_DANCE, bs.E_CURSE, bs.E_FUTURE_SIGHT, bs.E_BEAT_UP, bs.E_TRANSFORM,
})


def foe_move_is_safe(move: int, starter_internal: int) -> bool:
    row = bs.move_row(move)
    if not row:
        return False
    mtype, power, _acc, effect = row[:4]
    if effect in DANGEROUS_FOE_EFFECTS:
        return False
    if bs.WONDER_GUARD in bs.species_abilities(starter_internal):
        if effect in _GETS_PAST_WONDER_GUARD:
            return False
        if power > 0 and bs.effectiveness(mtype, bs.species_types(starter_internal)) > 1:
            return False
    return True


def foe_moveset(foe_internal: int, starter_internal: int, rng: random.Random,
                learnsets: "dict[int, list[tuple[int, int]]]", level: int = FOE_LEVEL) -> "list[int]":
    """The foe's moves: the ordinary chooser's pick, less the unsafe ones; a safe level-up move if none is left."""
    from ..randomizer.team_shuffle import EXCLUDED_MOVE_IDS, choose_moveset

    learnset = learnsets.get(foe_internal, [])
    chosen = choose_moveset(foe_internal, level, learnset, rng) if learnset else []
    safe = [m for m in chosen if foe_move_is_safe(m, starter_internal)]
    if safe:
        return sorted(set(safe))
    fallback = sorted({m for lvl, m in learnset if lvl <= level and m and m not in EXCLUDED_MOVE_IDS
                       and foe_move_is_safe(m, starter_internal)})
    return fallback[:4]


def candidate_species(species_pool: dict, allow_legendary: bool) -> "list[int]":
    """The pool the team shuffle draws Chobin #1 from -- non-legendary unless Legendary Trainer Pokemon is on --
    less anything the battle data has no row for."""
    return sorted(sid for sid, sp in species_pool.items()
                  if (allow_legendary or not getattr(sp, "is_legendary", False)) and bs.species_row(sid))


def gate(starter_internal: int, starter_moves: "list[int]", foe_internal: int, foe_moves: "list[int]",
         rng: random.Random, level: int = FOE_LEVEL, battles: int = GATE_BATTLES) -> float:
    """The measured win rate: half the fights against a foe that picks its moves half at random, half against one
    that always picks its hardest-hitting move -- XD's trainer AI sits between the two."""
    half = battles // 2
    wins = 0.0
    for greedy in (0.5, 1.0):
        result = bs.simulate(starter_internal, STARTER_LEVEL, starter_moves, foe_internal, level, foe_moves, rng,
                             battles=half, foe_greedy=greedy)
        wins += result["win_rate"] * half
    return wins / (2 * half)


def plan(starter_internal: int, starter_moves: "list[int]", candidates: "list[int]", rng: random.Random,
         learnsets: "dict[int, list[tuple[int, int]]]", level: int = FOE_LEVEL) -> "dict | None":
    """{"species", "moves", "level", "fraction", "decisive_move", "win_rate", "tier"} for Chobin #1, or None when
    the battle data is missing from this build (the shuffle's own pick then stands)."""
    if not bs.available() or not candidates:
        return None
    starter = bs.Side(starter_internal, STARTER_LEVEL, tuple(m for m in starter_moves if m))
    scored = []
    for sid in candidates:
        fraction, decisive = bs.guaranteed_fraction(starter, bs.Side(sid, level))
        scored.append((fraction, sid, decisive))
    best_seen: "dict | None" = None
    for floor in FRACTION_TIERS:
        tier = [row for row in scored if row[0] >= floor]
        if not tier:
            continue
        if floor > 0:
            rng.shuffle(tier)
        else:
            tier.sort(key=lambda row: (-row[0], row[1]))
        for fraction, sid, decisive in tier[:SIM_TRIES_PER_TIER]:
            moves = foe_moveset(sid, starter_internal, rng, learnsets, level)
            if not moves:
                continue
            win_rate = gate(starter_internal, list(starter.moves), sid, moves, random.Random(rng.getrandbits(32)),
                            level)
            entry = {"species": sid, "moves": moves, "level": level, "fraction": round(fraction, 4),
                     "decisive_move": decisive, "win_rate": win_rate, "tier": floor}
            if win_rate >= MIN_WIN_RATE:
                return entry
            if best_seen is None or (entry["win_rate"], entry["fraction"]) > (best_seen["win_rate"], best_seen["fraction"]):
                best_seen = entry
    return best_seen


def describe(entry: dict) -> str:
    from ..tools.xd_species_index import INTERNAL_INDEX_TO_NATIONAL_DEX

    name = (INTERNAL_INDEX_TO_NATIONAL_DEX.get(entry["species"]) or (None, f"species {entry['species']}"))[1]
    return (f"First Chobin (ADDENDUM 461): {name} lv {entry['level']}, moves {entry['moves']}; the "
            f"starter's move {entry['decisive_move']} takes at least {entry['fraction']:.0%} of its HP, and the "
            f"starter won {entry['win_rate']:.0%} of {GATE_BATTLES} simulated fights.")
