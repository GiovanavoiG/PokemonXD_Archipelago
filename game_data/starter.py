"""ADDENDUM 443 -- Randomize Starter.

Three options: off, random_no_legendary and true_random. The randomized starter always has at least one attacking
move.

WHERE THE EEVEE COMES FROM. `_menuTopNewGame` calls the new-game routine at 0x801CE9A4, which (on the retail ROM
version) builds a `HeroPokemonGetParam` on its stack and hands it to `Hero::pokemonGet`:

    0x801CECF0  li r3,133    species (Eevee)        -> sth +0x1E
    0x801CECF8  li r8,10     level                  -> stb +0x1D   (kept: a level-10 starter like vanilla)
    0x801CECFC  li r7,215    friendship             -> sth +0x22   (kept: high, as the game gives Eevee)
    0x801CED00  li r6,33     move 1 (Tackle)        -> sth +0x24
    0x801CED04  li r5,39     move 2 (Tail Whip)     -> sth +0x26
    0x801CED08  li r4,44     move 3 (Bite)          -> sth +0x28
    0x801CED0C  li r0,28     move 4 (Sand-Attack)   -> sth +0x2A

so the starter is five immediates: the species (XD's INTERNAL index) and four moves. Every word is checked against
its vanilla value before it is written, like every other main.dol patch here. Only a NEW game reads them.

The moves are the same chooser trainer Pokemon use (`team_shuffle.choose_moveset` at level 10: level-up moves,
damaging first, plus one legal tutor/egg move), then `ensure_attacking` guarantees a damaging move: the species'
own earliest damaging level-up move, else a damaging tutor/egg/TM move it can learn, else Tackle. ADDENDUM 461
tightened "damaging" to "reliable" (`is_reliable_attack`), so Explosion/Selfdestruct alone no longer qualify.
"""
from __future__ import annotations

import random
import struct

OFF, NO_LEGENDARY, TRUE_RANDOM = 0, 1, 2
VANILLA_STARTER_DEX = 133
STARTER_LEVEL = 10
TACKLE = 33

SPECIES_ADDRESS = 0x801CECF0
#: (address, register, vanilla immediate) for the four moves, in slot order.
MOVE_SLOTS: "tuple[tuple[int, int, int], ...]" = (
    (0x801CED00, 6, 33),
    (0x801CED04, 5, 39),
    (0x801CED08, 4, 44),
    (0x801CED0C, 0, 28),
)
VANILLA_MOVES = tuple(move for _a, _r, move in MOVE_SLOTS)


def _li(rd: int, value: int) -> int:
    if not 0 <= value < 0x8000:
        raise ValueError(f"li immediate {value} out of range")
    return (14 << 26) | (rd << 21) | value


def candidate_dex(mode: int) -> "list[int]":
    """National Dex 1-386 for true_random; without the legendaries for random_no_legendary."""
    from .real_trainer_data import LEGENDARY_NATIONAL_DEX

    out = list(range(1, 387))
    if mode == NO_LEGENDARY:
        out = [dex for dex in out if dex not in LEGENDARY_NATIONAL_DEX]
    return out


def choose_starter_dex(rng: random.Random, mode: int) -> int:
    return VANILLA_STARTER_DEX if mode == OFF else rng.choice(candidate_dex(mode))


def evolution_line(dex: int) -> "frozenset[int]":
    """The starter and everything it can become (level, trade, item, friendship and branch evolutions)."""
    from .evolution_data import NATIONAL_DEX_LEVEL_EVOLUTIONS, TRAINER_EVOLUTIONS

    line, frontier = {dex}, [dex]
    while frontier:
        current = frontier.pop()
        targets = [to for to, _lvl in TRAINER_EVOLUTIONS.get(current, [])]
        if current in NATIONAL_DEX_LEVEL_EVOLUTIONS:
            targets.append(NATIONAL_DEX_LEVEL_EVOLUTIONS[current][0])
        for target in targets:
            if target not in line:
                line.add(target)
                frontier.append(target)
    return frozenset(line)


def is_damaging(move: int) -> bool:
    from ..randomizer.team_shuffle import STATUS_MOVE_IDS, move_power

    return bool(move) and move not in STATUS_MOVE_IDS and move_power().get(move, 0) > 0


def is_reliable_attack(move: int) -> bool:
    """ADDENDUM 461: damaging, and not one of `battle_sim.UNRELIABLE_EFFECTS` -- Explosion, Selfdestruct, the
    OHKO moves, Counter, Mirror Coat, Bide and the rest that cannot be counted on to take HP when chosen. Falls back
    to plain `is_damaging` less Explosion/Selfdestruct if this build has no battle data."""
    from . import battle_sim

    if not is_damaging(move):
        return False
    if battle_sim.available():
        return battle_sim.is_reliable_attack(move)
    return move not in (120, 153)


def ensure_attacking(moves: "list[int]", internal_species: int, learnset: "list[tuple[int, int]]") -> "list[int]":
    """At least one RELIABLE attack (ADDENDUM 461; ADDENDUM 443 required only a damaging one): the starter can never have
    only Explosion/Selfdestruct as its attacks. Adds into an empty slot, else replaces the
    last status move, else the last move; never more than four. The pick is the species' own: a level-up move it
    knows by the starter's level first, then any level-up move, then a tutor/egg/TM move, and Tackle only when the
    species has nothing at all."""
    from ..randomizer.team_shuffle import EXCLUDED_MOVE_IDS, species_move_compat

    moves = [m for m in moves if m][:4]
    if any(is_reliable_attack(m) for m in moves):
        return moves
    # Never Pound (`team_shuffle.EXCLUDED_MOVE_IDS`, the real-hardware freeze). Before ADDENDUM 461 this pick
    # could land on it: Drowzee's and Gulpin's earliest damaging level-up move IS Pound.
    ordered = [(lvl, move) for lvl, move in sorted(learnset) if move not in EXCLUDED_MOVE_IDS]
    pick = next((move for lvl, move in ordered if lvl <= STARTER_LEVEL and is_reliable_attack(move)
                 and move not in moves), None)
    if pick is None:
        pick = next((move for _lvl, move in ordered if is_reliable_attack(move) and move not in moves), None)
    if pick is None:
        compat = species_move_compat().get(internal_species) or {}
        pool = sorted(m for m in compat.get("tutor", []) + compat.get("egg", []) + compat.get("tm", [])
                      if is_reliable_attack(m) and m not in moves and m not in EXCLUDED_MOVE_IDS)
        pick = pool[0] if pool else TACKLE
    if len(moves) < 4:
        moves.append(pick)
    else:
        status = [i for i, m in enumerate(moves) if not is_damaging(m)]
        moves[status[-1] if status else -1] = pick
    return moves


def starter_moves(rng: random.Random, internal_species: int,
                  level_up_moves: "dict[int, list[tuple[int, int]]] | None") -> "list[int]":
    from ..randomizer.team_shuffle import choose_moveset

    learnset = (level_up_moves or {}).get(internal_species, [])
    chosen = choose_moveset(internal_species, STARTER_LEVEL, learnset, rng) if learnset else []
    return ensure_attacking(list(chosen), internal_species, learnset)


def plan(rng: random.Random, mode: int) -> "dict | None":
    """{"dex", "internal", "moves", "line"} for a randomized starter, or None when the option is off."""
    if mode == OFF:
        return None
    from ..tools.xd_species_index import internal_index_for_national_dex
    from .real_moveset_data import load_level_up_moves

    dex = choose_starter_dex(rng, mode)
    internal = internal_index_for_national_dex(dex)
    if internal is None:
        raise ValueError(f"starter dex {dex} has no internal species index")
    moves = starter_moves(rng, internal, load_level_up_moves())
    return {"dex": dex, "internal": internal, "moves": moves, "line": sorted(evolution_line(dex))}


def dol_patch_words(internal_species: int, moves: "list[int]") -> "tuple[tuple[int, int, int], ...]":
    """(address, vanilla word, new word) -- the species and the four move immediates."""
    padded = (list(moves) + [0, 0, 0, 0])[:4]
    words = [(SPECIES_ADDRESS, _li(3, VANILLA_STARTER_DEX), _li(3, int(internal_species)))]
    for (address, register, vanilla), move in zip(MOVE_SLOTS, padded):
        words.append((address, _li(register, vanilla), _li(register, int(move))))
    return tuple(words)


assert dol_patch_words(VANILLA_STARTER_DEX, list(VANILLA_MOVES)) == tuple(
    (address, vanilla, vanilla) for address, vanilla, _new in dol_patch_words(VANILLA_STARTER_DEX, list(VANILLA_MOVES))
)
assert struct.pack(">I", _li(3, 133)) == bytes.fromhex("38600085")
