"""ADDENDUM 461 -- a one-on-one Generation III battle model, for the first Chobin fight.

Two jobs. `min_hit_fraction` is the arithmetic the player asked for: the smallest share of a Pokemon's HP one of the
starter's attacks is guaranteed to take -- lowest damage roll, no critical hit, the starter's worst IVs and nature,
the target's best IVs, every ability the target could have (and, through Trace, every ability the starter could
have), type and ability immunities included. `simulate` then plays the whole fight out, turn by turn, so "can we
win" is a measured rate and not an argument.

Data is `data/battle_data.json` (`tools/extract_battle_data.py`), read from XD's own species and move tables.
Mechanics follow pokeemerald, which XD's battle engine shares: the damage formula and its rounding order, the
physical/special split by TYPE, stat stages, the accuracy table, sleep 2-5, confusion 2-5, Toxic's counter. What is
modelled is what can decide a level-10 versus level-5 fight; a status move this does not model is a wasted turn for
whoever used it. That errs toward the FOE being weaker only for moves whose effect is a pure stat change on itself
that the model also ignores, and those are listed in `_IGNORED_STATUS_EFFECTS` so the gap is written down.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------------------------------- data

NORMAL, FIGHTING, FLYING, POISON, GROUND, ROCK, BUG, GHOST, STEEL, MYSTERY = range(10)
FIRE, WATER, GRASS, ELECTRIC, PSYCHIC, ICE, DRAGON, DARK = range(10, 18)
TYPE_NAMES = ("Normal", "Fighting", "Flying", "Poison", "Ground", "Rock", "Bug", "Ghost", "Steel", "???",
              "Fire", "Water", "Grass", "Electric", "Psychic", "Ice", "Dragon", "Dark")

#: Generation III: the type, not the move, decides physical or special.
PHYSICAL_TYPES = frozenset({NORMAL, FIGHTING, FLYING, POISON, GROUND, ROCK, BUG, GHOST, STEEL, MYSTERY})

_CHART: "dict[int, dict[int, float]]" = {
    NORMAL: {ROCK: .5, STEEL: .5, GHOST: 0},
    FIGHTING: {NORMAL: 2, ICE: 2, ROCK: 2, DARK: 2, STEEL: 2, POISON: .5, FLYING: .5, PSYCHIC: .5, BUG: .5,
               GHOST: 0},
    FLYING: {GRASS: 2, FIGHTING: 2, BUG: 2, ELECTRIC: .5, ROCK: .5, STEEL: .5},
    POISON: {GRASS: 2, POISON: .5, GROUND: .5, ROCK: .5, GHOST: .5, STEEL: 0},
    GROUND: {FIRE: 2, ELECTRIC: 2, POISON: 2, ROCK: 2, STEEL: 2, GRASS: .5, BUG: .5, FLYING: 0},
    ROCK: {FIRE: 2, ICE: 2, FLYING: 2, BUG: 2, FIGHTING: .5, GROUND: .5, STEEL: .5},
    BUG: {GRASS: 2, PSYCHIC: 2, DARK: 2, FIRE: .5, FIGHTING: .5, POISON: .5, FLYING: .5, GHOST: .5, STEEL: .5},
    GHOST: {PSYCHIC: 2, GHOST: 2, DARK: .5, STEEL: .5, NORMAL: 0},
    STEEL: {ICE: 2, ROCK: 2, FIRE: .5, WATER: .5, ELECTRIC: .5, STEEL: .5},
    FIRE: {GRASS: 2, ICE: 2, BUG: 2, STEEL: 2, FIRE: .5, WATER: .5, ROCK: .5, DRAGON: .5},
    WATER: {FIRE: 2, GROUND: 2, ROCK: 2, WATER: .5, GRASS: .5, DRAGON: .5},
    GRASS: {WATER: 2, GROUND: 2, ROCK: 2, FIRE: .5, GRASS: .5, POISON: .5, FLYING: .5, BUG: .5, DRAGON: .5,
            STEEL: .5},
    ELECTRIC: {WATER: 2, FLYING: 2, ELECTRIC: .5, GRASS: .5, DRAGON: .5, GROUND: 0},
    PSYCHIC: {FIGHTING: 2, POISON: 2, PSYCHIC: .5, STEEL: .5, DARK: 0},
    ICE: {GRASS: 2, GROUND: 2, FLYING: 2, DRAGON: 2, FIRE: .5, WATER: .5, ICE: .5, STEEL: .5},
    DRAGON: {DRAGON: 2, STEEL: .5},
    DARK: {PSYCHIC: 2, GHOST: 2, FIGHTING: .5, DARK: .5, STEEL: .5},
}


def effectiveness(move_type: int, defender_types: "tuple[int, ...]") -> float:
    out = 1.0
    for t in dict.fromkeys(defender_types):   # a mono-type is stored twice; count it once
        out *= _CHART.get(move_type, {}).get(t, 1.0)
    return out


# Generation III ability ids (pokeemerald ABILITY_*), the subset the model reads.
DRIZZLE, SPEED_BOOST, BATTLE_ARMOR, STURDY, DAMP, LIMBER, SAND_VEIL, STATIC = 2, 3, 4, 5, 6, 7, 8, 9
VOLT_ABSORB, WATER_ABSORB, OBLIVIOUS, CLOUD_NINE, COMPOUNDEYES, INSOMNIA, COLOR_CHANGE, IMMUNITY = range(10, 18)
FLASH_FIRE, SHIELD_DUST, OWN_TEMPO = 18, 19, 20
INTIMIDATE, ROUGH_SKIN, WONDER_GUARD, LEVITATE, EFFECT_SPORE, SYNCHRONIZE, CLEAR_BODY = 22, 24, 25, 26, 27, 28, 29
SERENE_GRACE, SWIFT_SWIM, CHLOROPHYLL, TRACE, HUGE_POWER, POISON_POINT, INNER_FOCUS = 32, 33, 34, 36, 37, 38, 39
MAGMA_ARMOR, WATER_VEIL, SOUNDPROOF, SAND_STREAM, PRESSURE, THICK_FAT, EARLY_BIRD = 40, 41, 43, 45, 46, 47, 48
FLAME_BODY, KEEN_EYE, HYPER_CUTTER, TRUANT, HUSTLE, CUTE_CHARM = 49, 51, 52, 54, 55, 56
SHED_SKIN, GUTS, MARVEL_SCALE, LIQUID_OOZE, OVERGROW, BLAZE, TORRENT, SWARM, ROCK_HEAD, DROUGHT = range(61, 71)
VITAL_SPIRIT, WHITE_SMOKE, PURE_POWER, SHELL_ARMOR, AIR_LOCK = 72, 73, 74, 75, 77

ABILITY_NAMES = {LEVITATE: "Levitate", SOUNDPROOF: "Soundproof", FLASH_FIRE: "Flash Fire",
                 VOLT_ABSORB: "Volt Absorb", WATER_ABSORB: "Water Absorb", WONDER_GUARD: "Wonder Guard",
                 TRACE: "Trace", THICK_FAT: "Thick Fat", INTIMIDATE: "Intimidate", STURDY: "Sturdy"}

# Generation III move effects (pokeemerald EFFECT_*). XD stores the same ids at move +0x1D (`move_status`).
E_HIT, E_SLEEP, E_POISON_HIT, E_ABSORB, E_BURN_HIT, E_FREEZE_HIT, E_PARALYZE_HIT, E_EXPLOSION = range(8)
E_DREAM_EATER, E_MIRROR_MOVE = 8, 9
E_ALWAYS_HIT, E_HAZE, E_BIDE, E_RAMPAGE, E_MULTI_HIT, E_FLINCH_HIT, E_RESTORE_HP, E_TOXIC = 17, 25, 26, 27, 29, 31, 32, 33
E_LIGHT_SCREEN, E_TRI_ATTACK, E_REST, E_OHKO, E_RAZOR_WIND, E_SUPER_FANG, E_DRAGON_RAGE = 35, 36, 37, 38, 39, 40, 41
E_TRAP, E_HIGH_CRIT, E_DOUBLE_HIT, E_RECOIL_IF_MISS, E_RECOIL, E_CONFUSE = 42, 43, 44, 45, 48, 49
E_TRANSFORM, E_REFLECT, E_POISON, E_PARALYZE = 57, 65, 66, 67
E_SKY_ATTACK, E_CONFUSE_HIT, E_TWINEEDLE, E_SUBSTITUTE, E_RECHARGE = 75, 76, 77, 79, 80
E_LEECH_SEED, E_DISABLE, E_LEVEL_DAMAGE, E_PSYWAVE, E_COUNTER = 84, 86, 87, 88, 89
E_PAIN_SPLIT, E_SNORE, E_DESTINY_BOND, E_FLAIL, E_FALSE_SWIPE, E_TRIPLE_KICK = 91, 92, 98, 99, 101, 104
E_CURSE, E_PROTECT, E_PERISH_SONG, E_SANDSTORM, E_ENDURE, E_ROLLOUT, E_SWAGGER, E_FURY_CUTTER = (
    109, 111, 114, 115, 116, 117, 118, 119)
E_ATTRACT, E_RETURN, E_PRESENT, E_FRUSTRATION, E_MAGNITUDE = 120, 121, 122, 123, 126
E_SONICBOOM, E_MORNING_SUN, E_SYNTHESIS, E_MOONLIGHT, E_HIDDEN_POWER, E_RAIN_DANCE, E_SUNNY_DAY = (
    130, 132, 133, 134, 135, 136, 137)
E_DEFENSE_UP_HIT, E_ATTACK_UP_HIT, E_ALL_STATS_UP_HIT, E_BELLY_DRUM, E_MIRROR_COAT, E_SKULL_BASH = (
    138, 139, 140, 142, 144, 145)
E_FUTURE_SIGHT, E_SOLARBEAM, E_THUNDER, E_BEAT_UP, E_SEMI_INVULNERABLE, E_SOFTBOILED, E_FAKE_OUT = (
    148, 151, 152, 154, 155, 157, 158)
E_SPIT_UP, E_HAIL, E_FLATTER, E_WILL_O_WISP, E_MEMENTO, E_FACADE, E_FOCUS_PUNCH = 161, 164, 166, 167, 168, 169, 170
E_SMELLINGSALT, E_SUPERPOWER, E_REVENGE, E_YAWN, E_ENDEAVOR, E_ERUPTION = 171, 182, 185, 187, 189, 190
E_LOW_KICK, E_DOUBLE_EDGE, E_TEETER_DANCE, E_BLAZE_KICK, E_POISON_FANG, E_WEATHER_BALL = 196, 198, 199, 200, 202, 203
E_OVERHEAT, E_TICKLE, E_COSMIC_POWER, E_BULK_UP, E_POISON_TAIL, E_CALM_MIND, E_DRAGON_DANCE = (
    204, 205, 206, 208, 209, 211, 212)
E_SECRET_POWER, E_THAW_HIT, E_FLINCH_MINIMIZE_HIT = 197, 125, 150

#: effect -> ((stat, stages), ...) applied to the USER (status moves) -- stats are "atk def spa spd spe acc eva".
_SELF_STAGES: "dict[int, tuple[tuple[str, int], ...]]" = {
    10: (("atk", 1),), 11: (("def", 1),), 12: (("spe", 1),), 13: (("spa", 1),), 14: (("spd", 1),),
    15: (("acc", 1),), 16: (("eva", 1),), 50: (("atk", 2),), 51: (("def", 2),), 52: (("spe", 2),),
    53: (("spa", 2),), 54: (("spd", 2),), 55: (("acc", 2),), 56: (("eva", 2),), 108: (("eva", 1),),
    156: (("def", 1),), E_COSMIC_POWER: (("def", 1), ("spd", 1)), E_BULK_UP: (("atk", 1), ("def", 1)),
    E_CALM_MIND: (("spa", 1), ("spd", 1)), E_DRAGON_DANCE: (("atk", 1), ("spe", 1)),
}
#: effect -> ((stat, stages), ...) applied to the TARGET (status moves).
_TARGET_STAGES: "dict[int, tuple[tuple[str, int], ...]]" = {
    18: (("atk", -1),), 19: (("def", -1),), 20: (("spe", -1),), 21: (("spa", -1),), 22: (("spd", -1),),
    23: (("acc", -1),), 24: (("eva", -1),), 58: (("atk", -2),), 59: (("def", -2),), 60: (("spe", -2),),
    61: (("spa", -2),), 62: (("spd", -2),), 63: (("acc", -2),), 64: (("eva", -2),),
    E_TICKLE: (("atk", -1), ("def", -1)),
}
#: effect -> (stat, stages) a damaging move may inflict on the target at its effect chance.
_HIT_TARGET_STAGES = {68: ("atk", -1), 69: ("def", -1), 70: ("spe", -1), 71: ("spa", -1), 72: ("spd", -1),
                      73: ("acc", -1), 74: ("eva", -1)}
#: effect -> ((stat, stages), ...) a damaging move applies to its user (always, or at its chance where noted).
_HIT_SELF_STAGES = {E_SUPERPOWER: (("atk", -1), ("def", -1)), E_OVERHEAT: (("spa", -2),)}
_HIT_SELF_CHANCE_STAGES = {E_DEFENSE_UP_HIT: (("def", 1),), E_ATTACK_UP_HIT: (("atk", 1),),
                           E_ALL_STATS_UP_HIT: (("atk", 1), ("def", 1), ("spa", 1), ("spd", 1), ("spe", 1))}
#: Status moves deliberately left as no-ops, so the gap is written down: none of them can lose the fight.
_IGNORED_STATUS_EFFECTS = frozenset({
    9, 28, 30, 34, 46, 47, 82, 83, 85, 90, 93, 94, 95, 97, 100, 102, 106, 107, 112, 113, 124, 127, 129, 143, 153,
    165, 172, 173, 174, 175, 176, 177, 178, 179, 180, 181, 183, 184, 191, 192, 193, 194, 195, 201, 210, 213,
})

_STAGE_NUM = {-6: (2, 8), -5: (2, 7), -4: (2, 6), -3: (2, 5), -2: (2, 4), -1: (2, 3), 0: (2, 2),
              1: (3, 2), 2: (4, 2), 3: (5, 2), 4: (6, 2), 5: (7, 2), 6: (8, 2)}
_ACC_STAGE = {-6: (33, 100), -5: (36, 100), -4: (43, 100), -3: (50, 100), -2: (60, 100), -1: (75, 100),
              0: (1, 1), 1: (133, 100), 2: (166, 100), 3: (2, 1), 4: (233, 100), 5: (133, 50), 6: (3, 1)}

_DATA: "dict | None" = None


def _data() -> dict:
    global _DATA
    if _DATA is None:
        from . import load_json_data_file

        raw = load_json_data_file("battle_data.json") or {}
        _DATA = {
            "species": {int(k): tuple(v) for k, v in (raw.get("species") or {}).items()},
            "moves": {int(k): tuple(v) for k, v in (raw.get("moves") or {}).items()},
        }
    return _DATA


def available() -> bool:
    return bool(_data()["species"]) and bool(_data()["moves"])


def species_row(internal: int) -> "tuple | None":
    return _data()["species"].get(int(internal))


def move_row(move: int) -> "tuple | None":
    return _data()["moves"].get(int(move))


def species_types(internal: int) -> "tuple[int, int]":
    row = species_row(internal)
    return (row[0], row[1]) if row else (NORMAL, NORMAL)


def species_abilities(internal: int) -> "tuple[int, ...]":
    row = species_row(internal)
    if not row:
        return (0,)
    return tuple(a for a in dict.fromkeys((row[2], row[3])) if a) or (0,)


# ---------------------------------------------------------------------------------------------------- stats

def stat_values(internal: int, level: int, ivs: "tuple[int, ...]", nature: "tuple[str | None, str | None]" = (None, None),
                evs: "tuple[int, ...]" = (0,) * 6) -> "dict[str, int]":
    """Generation III stats. `nature` is (boosted stat, hindered stat), names as in `_STATS`."""
    row = species_row(internal)
    base = row[4:10]
    out = {}
    for i, name in enumerate(("hp", "atk", "def", "spa", "spd", "spe")):
        core = (2 * base[i] + ivs[i] + evs[i] // 4) * level // 100
        if name == "hp":
            out[name] = 1 if base[i] == 1 else core + level + 10
        else:
            value = core + 5
            if nature[0] == name and nature[1] != name:
                value = value * 110 // 100
            elif nature[1] == name and nature[0] != name:
                value = value * 90 // 100
            out[name] = value
    return out


_STATS = ("atk", "def", "spa", "spd", "spe")


def random_nature(rng: random.Random) -> "tuple[str | None, str | None]":
    return (rng.choice(_STATS), rng.choice(_STATS))


# ---------------------------------------------------------------------------------------------------- moves

#: Attacks that cannot be counted on to take a share of the foe's HP on the turn they are chosen: they knock the
#: user out, only work in a state the foe controls, fail outright against a level-5 target's luck, return damage
#: rather than deal it, or cannot finish a Pokemon. The player: "ensure our starter CANT ONLY HAVE
#: explosion/selfdestruct as its attacks" -- this is that rule, widened to everything of the same kind.
UNRELIABLE_EFFECTS: "frozenset[int]" = frozenset({
    E_EXPLOSION, E_OHKO, E_COUNTER, E_MIRROR_COAT, E_BIDE, E_DREAM_EATER, E_SNORE, E_SPIT_UP, E_FOCUS_PUNCH,
    E_FAKE_OUT, E_ENDEAVOR, E_PRESENT, E_FALSE_SWIPE, E_FUTURE_SIGHT, E_SUPER_FANG, E_BEAT_UP,
})


def is_damaging(move: int) -> bool:
    row = move_row(move)
    return bool(row) and row[1] > 0


def is_reliable_attack(move: int) -> bool:
    row = move_row(move)
    return bool(row) and row[1] > 0 and row[3] not in UNRELIABLE_EFFECTS


def _fixed_damage(effect: int, user_level: int, target_hp: int, roll_min: bool, rng: "random.Random | None") -> "int | None":
    if effect == E_SONICBOOM:
        return 20
    if effect == E_DRAGON_RAGE:
        return 40
    if effect == E_LEVEL_DAMAGE:
        return user_level
    if effect == E_PSYWAVE:
        r = 0 if roll_min else rng.randint(0, 10)
        return max(1, user_level * (r * 10 + 50) // 100)
    if effect == E_SUPER_FANG:
        return max(1, target_hp // 2)
    return None


def hidden_power(ivs: "tuple[int, ...]") -> "tuple[int, int]":
    """(type, power) from IVs in HP/Atk/Def/Spe/SpA/SpD order, Generation III."""
    hp, atk, de, spa, spd, spe = ivs
    bits = [hp, atk, de, spe, spa, spd]
    t = sum(((v & 1) << i) for i, v in enumerate(bits)) * 15 // 63
    p = sum((((v >> 1) & 1) << i) for i, v in enumerate(bits)) * 40 // 63 + 30
    hp_types = (FIGHTING, FLYING, POISON, GROUND, ROCK, BUG, GHOST, STEEL, FIRE, WATER, GRASS, ELECTRIC, PSYCHIC,
                ICE, DRAGON, DARK)
    return hp_types[t], p


HIDDEN_POWER_TYPES = (FIGHTING, FLYING, POISON, GROUND, ROCK, BUG, GHOST, STEEL, FIRE, WATER, GRASS, ELECTRIC,
                      PSYCHIC, ICE, DRAGON, DARK)


def _low_kick_power(weight_hg: int) -> int:
    for limit, power in ((100, 20), (250, 40), (500, 60), (1000, 80), (2000, 100)):
        if weight_hg < limit:
            return power
    return 120


def _variable_power(effect: int, base: int, user_hp: int, user_max: int, target_weight: int,
                    friendship: int, roll_min: bool, rng: "random.Random | None") -> int:
    if effect == E_RETURN:
        return max(1, friendship * 10 // 25)
    if effect == E_FRUSTRATION:
        return max(1, (255 - friendship) * 10 // 25)
    if effect == E_FLAIL:
        n = 48 * user_hp // user_max
        for limit, power in ((2, 200), (5, 150), (10, 100), (17, 80), (33, 40)):
            if n < limit:
                return power
        return 20
    if effect == E_ERUPTION:
        return max(1, base * user_hp // user_max)
    if effect == E_LOW_KICK:
        return _low_kick_power(target_weight)
    if effect == E_MAGNITUDE:
        if roll_min:
            return 10
        r = rng.randint(0, 99)
        for limit, power in ((5, 10), (15, 30), (35, 50), (65, 70), (85, 90), (95, 110)):
            if r < limit:
                return power
        return 150
    if effect == E_WEATHER_BALL:
        return 50
    if effect == E_TRIPLE_KICK:
        return 10
    return base


# ---------------------------------------------------------------------------------------------------- the check

@dataclass(frozen=True)
class Side:
    """Everything the static check needs about one Pokemon."""
    internal: int
    level: int
    moves: "tuple[int, ...]" = ()


STARTER_FRIENDSHIP = 215          # `starter.py`: the li r7,215 the new-game routine stores, kept as vanilla


def min_hit_fraction(attacker: Side, defender: Side, move: int, *, defender_ability: int,
                     attacker_ability: int = 0, hp_type: "int | None" = None) -> float:
    """The lowest share of `defender`'s max HP one use of `move` is sure to take, with `defender_ability`.

    Worst case for the attacker everywhere: IVs 0 and a nature that lowers the attacking stat, the defender's IVs
    31, the lowest damage roll, no critical hit, Intimidate applied. 0.0 means the move cannot hurt it at all."""
    row = move_row(move)
    if not row or row[1] <= 0:
        return 0.0
    mtype, power, _acc, effect, _chance, _prio, _contact, sound = row[:8]
    if effect == E_HIDDEN_POWER:
        mtype, power = (hp_type if hp_type is not None else NORMAL), 30
    if effect in (E_WEATHER_BALL,):
        mtype = NORMAL
    a_types = species_types(attacker.internal)
    d_types = species_types(defender.internal)
    d_stats = stat_values(defender.internal, defender.level, (31,) * 6)
    d_hp = d_stats["hp"]
    # Ability immunities first -- they decide whether the move lands at all.
    if defender_ability == SOUNDPROOF and sound:
        return 0.0
    if defender_ability == LEVITATE and mtype == GROUND:
        return 0.0
    if defender_ability == FLASH_FIRE and mtype == FIRE:
        return 0.0
    if defender_ability == VOLT_ABSORB and mtype == ELECTRIC:
        return 0.0
    if defender_ability == WATER_ABSORB and mtype == WATER:
        return 0.0
    if defender_ability == STURDY and effect == E_OHKO:
        return 0.0
    if defender_ability == DAMP and effect == E_EXPLOSION:
        return 0.0
    eff = effectiveness(mtype, d_types)
    if effect == E_BEAT_UP or effect == E_FUTURE_SIGHT:
        eff = 1.0                       # typeless in Generation III
    if eff == 0:
        return 0.0
    if defender_ability == WONDER_GUARD and eff <= 1 and effect not in (E_BEAT_UP, E_FUTURE_SIGHT):
        return 0.0
    if effect == E_OHKO:
        return 0.0 if defender.level > attacker.level else 1.0
    fixed = _fixed_damage(effect, attacker.level, d_hp, True, None)
    if fixed is not None:
        return min(1.0, fixed / d_hp)
    physical = mtype in PHYSICAL_TYPES
    nature = ("spe", "atk" if physical else "spa")
    a_stats = stat_values(attacker.internal, attacker.level, (0,) * 6, nature)
    attack = a_stats["atk" if physical else "spa"]
    defense = d_stats["def" if physical else "spd"]
    if physical and attacker_ability in (HUGE_POWER, PURE_POWER):
        attack *= 2
    if physical and defender_ability == INTIMIDATE:
        attack = attack * 2 // 3
    if defender_ability == THICK_FAT and mtype in (FIRE, ICE):
        attack //= 2
    if effect == E_EXPLOSION:
        defense = max(1, defense // 2)
    power = _variable_power(effect, power, 1, 1, species_row(defender.internal)[10], STARTER_FRIENDSHIP, True, None)
    hits = 2 if effect in (E_MULTI_HIT, E_DOUBLE_HIT, E_TWINEEDLE) else 1
    dmg = (2 * attacker.level // 5 + 2) * power * attack // defense // 50 + 2
    if mtype in a_types:
        dmg = dmg * 15 // 10
    for t in dict.fromkeys(d_types):
        m = _CHART.get(mtype, {}).get(t, 1.0)
        dmg = int(dmg * m)
    dmg = max(1, dmg * 85 // 100)
    return min(1.0, hits * dmg / d_hp)


def guaranteed_fraction(starter: Side, foe: Side) -> "tuple[float, int | None]":
    """(the best guaranteed share of `foe`'s HP any one of the starter's reliable attacks takes, that move).

    Every ability the foe could field is tried and the worst kept, and a foe with Trace is also tried with each
    of the starter's own abilities, since Trace copies what it sees. Hidden Power's type comes from IVs the game
    rolls at new-game time, so it is tried as every type it can be and the worst kept."""
    foe_abilities = set(species_abilities(foe.internal))
    starter_abilities = species_abilities(starter.internal)
    if TRACE in foe_abilities:
        foe_abilities |= set(starter_abilities)
    best, best_move = 0.0, None
    for move in starter.moves:
        if not is_reliable_attack(move):
            continue
        row = move_row(move)
        hp_types = HIDDEN_POWER_TYPES if row[3] == E_HIDDEN_POWER else (None,)
        worst = min(
            min_hit_fraction(starter, foe, move, defender_ability=ability, attacker_ability=own, hp_type=hp)
            for ability in foe_abilities for own in starter_abilities for hp in hp_types
        )
        if worst > best:
            best, best_move = worst, move
    return best, best_move


# ---------------------------------------------------------------------------------------------------- the sim

@dataclass
class Mon:
    internal: int
    level: int
    moves: "list[list[int]]"              # [[move id, pp], ...]
    ability: int
    stats: "dict[str, int]"
    ivs: "tuple[int, ...]"
    friendship: int = 0
    gender: int = 0                       # 0/1; Cute Charm and Attract compare it
    hp: int = 0
    types: "tuple[int, int]" = (NORMAL, NORMAL)
    status: "str | None" = None
    sleep: int = 0
    toxic: int = 0
    stages: "dict[str, int]" = field(default_factory=lambda: dict.fromkeys(("atk", "def", "spa", "spd", "spe", "acc", "eva"), 0))
    confused: int = 0
    seeded: bool = False
    protect_chain: int = 0
    protected: bool = False
    enduring: bool = False
    charging: "int | None" = None
    invulnerable: bool = False
    recharge: bool = False
    rampage: int = 0
    rampage_move: int = 0
    disabled: int = 0
    disabled_turns: int = 0
    loafing: bool = False
    substitute: int = 0
    trap: int = 0
    attracted: bool = False
    last_move: int = 0
    last_damage_taken: int = 0
    last_damage_physical: bool = True
    rollout: int = 0
    fury: int = 0
    flash_fire: bool = False
    yawn: int = 0
    screen_reflect: int = 0
    screen_light: int = 0
    destiny_bond: bool = False
    perish: int = 0
    cursed: bool = False
    focus: bool = False
    hit_this_turn: bool = False
    future: "tuple[int, int] | None" = None
    bide: int = 0
    bide_damage: int = 0
    flinched: bool = False

    def __post_init__(self) -> None:
        self.hp = self.hp or self.stats["hp"]
        self.types = species_types(self.internal)

    @property
    def fainted(self) -> bool:
        return self.hp <= 0


def make_mon(internal: int, level: int, moves: "list[int]", rng: random.Random, *, ivs: "tuple[int, ...] | None" = None,
             nature: "tuple[str | None, str | None] | None" = None, ability: "int | None" = None,
             friendship: int = 0) -> Mon:
    ivs = tuple(rng.randint(0, 31) for _ in range(6)) if ivs is None else tuple(ivs)
    nature = random_nature(rng) if nature is None else nature
    abilities = species_abilities(internal)
    ability = rng.choice(abilities) if ability is None else ability
    stats = stat_values(internal, level, ivs, nature)
    move_list = [[m, move_row(m)[8]] for m in moves if m and move_row(m)]
    return Mon(internal=internal, level=level, moves=move_list, ability=ability, stats=stats, ivs=ivs,
               friendship=friendship, gender=rng.randint(0, 1))


class Battle:
    def __init__(self, player: Mon, foe: Mon, rng: random.Random, foe_greedy: float = 0.5) -> None:
        self.p, self.f, self.rng = player, foe, rng
        self.weather: "str | None" = None
        self.weather_turns = 0
        self.foe_greedy = foe_greedy
        self.turns = 0
        self._switch_in(self.p, self.f)
        self._switch_in(self.f, self.p)
        for mon in (self.p, self.f):
            if mon.ability in (DRIZZLE, DROUGHT, SAND_STREAM):
                self.weather = {DRIZZLE: "rain", DROUGHT: "sun", SAND_STREAM: "sand"}[mon.ability]
                self.weather_turns = 10 ** 6

    # -- entry
    def _switch_in(self, mon: Mon, other: Mon) -> None:
        if mon.ability == TRACE and other.ability not in (0, TRACE):
            mon.ability = other.ability
        if mon.ability == INTIMIDATE and other.ability not in (CLEAR_BODY, WHITE_SMOKE, HYPER_CUTTER):
            self._stage(other, "atk", -1, source_is_foe=True)

    # -- helpers
    def _weather_active(self) -> "str | None":
        if any(m.ability in (CLOUD_NINE, AIR_LOCK) for m in (self.p, self.f)):
            return None
        return self.weather

    def _stage(self, mon: Mon, stat: str, n: int, source_is_foe: bool = False) -> None:
        if n < 0 and source_is_foe:
            if mon.ability in (CLEAR_BODY, WHITE_SMOKE):
                return
            if mon.ability == HYPER_CUTTER and stat == "atk":
                return
            if mon.ability == KEEN_EYE and stat == "acc":
                return
        mon.stages[stat] = max(-6, min(6, mon.stages[stat] + n))

    def _eff_stat(self, mon: Mon, stat: str, crit: bool = False, attacking: bool = True) -> int:
        stage = mon.stages[stat]
        if crit:
            stage = max(stage, 0) if attacking else min(stage, 0)
        num, den = _STAGE_NUM[stage]
        value = mon.stats[stat] * num // den
        if stat == "spe":
            if mon.status == "par":
                value //= 4
            w = self._weather_active()
            if (mon.ability == SWIFT_SWIM and w == "rain") or (mon.ability == CHLOROPHYLL and w == "sun"):
                value *= 2
        return max(1, value)

    def _can_status(self, mon: Mon, status: str) -> bool:
        if mon.status is not None or mon.fainted:
            return False
        if mon.substitute > 0:
            return False
        immune = {"slp": (INSOMNIA, VITAL_SPIRIT), "par": (LIMBER,), "psn": (IMMUNITY,), "tox": (IMMUNITY,),
                  "brn": (WATER_VEIL,), "frz": (MAGMA_ARMOR,)}[status]
        if mon.ability in immune:
            return False
        if status in ("psn", "tox") and (POISON in mon.types or STEEL in mon.types):
            return False
        if status == "brn" and FIRE in mon.types:
            return False
        if status == "frz" and (ICE in mon.types or self._weather_active() == "sun"):
            return False
        return True

    def _give_status(self, mon: Mon, status: str, source: "Mon | None" = None) -> bool:
        if not self._can_status(mon, status):
            return False
        mon.status = status
        if status == "slp":
            mon.sleep = self.rng.randint(2, 5)
            if mon.ability == EARLY_BIRD:
                mon.sleep = max(1, mon.sleep // 2)
        if status == "tox":
            mon.toxic = 1
        if source is not None and mon.ability == SYNCHRONIZE and status in ("psn", "tox", "par", "brn"):
            self._give_status(source, "psn" if status == "tox" else status)
        return True

    def _confuse(self, mon: Mon) -> None:
        if mon.confused or mon.ability == OWN_TEMPO or mon.substitute > 0:
            return
        mon.confused = self.rng.randint(2, 5)

    def _damage(self, mon: Mon, amount: int) -> int:
        amount = max(0, min(mon.hp, amount))
        if mon.enduring and amount >= mon.hp:
            amount = mon.hp - 1
        mon.hp -= amount
        return amount

    def _heal(self, mon: Mon, amount: int) -> None:
        mon.hp = min(mon.stats["hp"], mon.hp + max(0, amount))

    # -- the move's numbers
    def _type_and_power(self, user: Mon, target: Mon, move: int) -> "tuple[int, int]":
        mtype, power, _acc, effect = move_row(move)[:4]
        if effect == E_HIDDEN_POWER:
            return hidden_power(user.ivs)
        if effect == E_WEATHER_BALL:
            w = self._weather_active()
            if w:
                return {"rain": WATER, "sun": FIRE, "sand": ROCK, "hail": ICE}[w], 100
            return NORMAL, 50
        power = _variable_power(effect, power, user.hp, user.stats["hp"], species_row(target.internal)[10],
                                user.friendship, False, self.rng)
        if effect == E_ROLLOUT:
            power = power * (2 ** min(user.rollout, 4))
        if effect == E_FURY_CUTTER:
            power = power * (2 ** min(user.fury, 4))
        if effect == E_FACADE and user.status in ("psn", "tox", "par", "brn"):
            power *= 2
        if effect == E_SMELLINGSALT and target.status == "par":
            power *= 2
        if effect == E_REVENGE and user.hit_this_turn:
            power *= 2
        return mtype, power

    def _blocked_by_ability(self, target: Mon, move: int, mtype: int, eff: float) -> bool:
        row = move_row(move)
        effect = row[3]
        if target.ability == SOUNDPROOF and row[7]:
            return True
        if target.ability == LEVITATE and mtype == GROUND:
            return True
        if target.ability == FLASH_FIRE and mtype == FIRE:
            target.flash_fire = True
            return True
        if target.ability == VOLT_ABSORB and mtype == ELECTRIC:
            self._heal(target, target.stats["hp"] // 4)
            return True
        if target.ability == WATER_ABSORB and mtype == WATER:
            self._heal(target, target.stats["hp"] // 4)
            return True
        if target.ability == WONDER_GUARD and eff <= 1 and effect not in (E_BEAT_UP, E_FUTURE_SIGHT):
            return True
        return False

    def calc_damage(self, user: Mon, target: Mon, move: int, *, crit: bool, roll: int) -> "tuple[int, float]":
        """(damage, effectiveness) -- pokeemerald's CalculateBaseDamage + ApplyRandomDmgMultiplier order."""
        mtype, power = self._type_and_power(user, target, move)
        effect = move_row(move)[3]
        eff = 1.0 if effect in (E_BEAT_UP, E_FUTURE_SIGHT) else effectiveness(mtype, target.types)
        physical = mtype in PHYSICAL_TYPES
        attack = self._eff_stat(user, "atk" if physical else "spa", crit, attacking=True)
        defense = self._eff_stat(target, "def" if physical else "spd", crit, attacking=False)
        if physical and user.ability in (HUGE_POWER, PURE_POWER):
            attack *= 2
        if physical and user.ability == HUSTLE:
            attack = attack * 15 // 10
        if physical and user.ability == GUTS and user.status:
            attack = attack * 15 // 10
        if physical and target.ability == MARVEL_SCALE and target.status:
            defense = defense * 15 // 10
        if target.ability == THICK_FAT and mtype in (FIRE, ICE):
            attack //= 2
        if effect == E_EXPLOSION:
            defense = max(1, defense // 2)
        if user.hp * 3 <= user.stats["hp"] and (
                (user.ability == OVERGROW and mtype == GRASS) or (user.ability == BLAZE and mtype == FIRE)
                or (user.ability == TORRENT and mtype == WATER) or (user.ability == SWARM and mtype == BUG)):
            power = power * 15 // 10
        dmg = (2 * user.level // 5 + 2) * power * attack // defense // 50
        if physical and user.status == "brn" and user.ability != GUTS:
            dmg //= 2
        if not crit and ((physical and target.screen_reflect) or (not physical and target.screen_light)):
            dmg //= 2
        w = self._weather_active()
        if w == "rain":
            dmg = dmg * 15 // 10 if mtype == WATER else (dmg // 2 if mtype == FIRE else dmg)
        elif w == "sun":
            dmg = dmg * 15 // 10 if mtype == FIRE else (dmg // 2 if mtype == WATER else dmg)
        if effect == E_SOLARBEAM and w in ("rain", "sand", "hail"):
            dmg //= 2
        if user.flash_fire and mtype == FIRE:
            dmg = dmg * 15 // 10
        dmg += 2
        if crit:
            dmg *= 2
        if mtype in user.types:
            dmg = dmg * 15 // 10
        for t in dict.fromkeys(target.types):
            dmg = int(dmg * _CHART.get(mtype, {}).get(t, 1.0))
        dmg = dmg * roll // 100
        return (max(1, dmg) if eff > 0 else 0), eff

    # -- choosing
    def expected_damage(self, user: Mon, target: Mon, move: int) -> float:
        row = move_row(move)
        mtype, power, acc, effect = row[:4]
        if power <= 0:
            return 0.0
        if effect in (E_EXPLOSION, E_COUNTER, E_MIRROR_COAT, E_BIDE, E_FOCUS_PUNCH, E_ENDEAVOR, E_PRESENT,
                      E_SPIT_UP, E_FUTURE_SIGHT):
            return 0.0
        if effect == E_DREAM_EATER and target.status != "slp":
            return 0.0
        if effect == E_SNORE and user.status != "slp":
            return 0.0
        if effect == E_FAKE_OUT and self.turns > 1:
            return 0.0
        if effect == E_OHKO:
            if target.level > user.level or target.ability == STURDY:
                return 0.0
            return (30 + user.level - target.level) / 100 * target.hp
        t, _p = self._type_and_power(user, target, move)
        eff = 1.0 if effect in (E_BEAT_UP, E_FUTURE_SIGHT) else effectiveness(t, target.types)
        if eff == 0:
            return 0.0
        row_sound = row[7]
        if (target.ability == SOUNDPROOF and row_sound) or (target.ability == LEVITATE and t == GROUND) or \
                (target.ability == FLASH_FIRE and t == FIRE) or (target.ability == VOLT_ABSORB and t == ELECTRIC) or \
                (target.ability == WATER_ABSORB and t == WATER) or (target.ability == WONDER_GUARD and eff <= 1):
            return 0.0
        fixed = _fixed_damage(effect, user.level, target.hp, True, None)
        if fixed is not None:
            dmg = fixed if effect != E_PSYWAVE else user.level
        else:
            dmg, _ = self.calc_damage(user, target, move, crit=False, roll=92)
            if effect in (E_MULTI_HIT,):
                dmg *= 3
            elif effect in (E_DOUBLE_HIT, E_TWINEEDLE):
                dmg *= 2
        if effect in (E_RAZOR_WIND, E_SKY_ATTACK, E_SKULL_BASH, E_SOLARBEAM, E_SEMI_INVULNERABLE, E_RECHARGE) \
                and not (effect == E_SOLARBEAM and self._weather_active() == "sun"):
            dmg /= 2
        if effect == E_FALSE_SWIPE:
            dmg = min(dmg, max(0, target.hp - 1))
        hit = 1.0 if acc == 0 else min(1.0, acc / 100)
        return min(dmg, target.hp) * hit

    def _usable(self, mon: Mon) -> "list[int]":
        out = []
        for move, pp in mon.moves:
            if pp <= 0 or move == mon.disabled:
                continue
            out.append(move)
        return out

    def choose(self, mon: Mon, target: Mon, is_player: bool) -> int:
        usable = self._usable(mon)
        if not usable:
            return 165                               # Struggle
        if is_player:
            scored = [(self.expected_damage(mon, target, m), m) for m in usable]
            best = max(scored)
            if best[0] > 0:
                return best[1]
            # Nothing damaging lands: a status move beats Explosion, and Explosion only as a last resort.
            safe = [m for m in usable if move_row(m)[3] != E_EXPLOSION]
            return self.rng.choice(safe or usable)
        if self.rng.random() < self.foe_greedy:
            scored = [(self.expected_damage(mon, target, m), m) for m in usable]
            best = max(scored)
            if best[0] > 0:
                return best[1]
        return self.rng.choice(usable)

    # -- one turn
    @staticmethod
    def _priority(move: int) -> int:
        row = move_row(move) if move > 0 else None
        return row[5] if row and move != 165 else 0

    def _order(self, pm: int, fm: int) -> "list[tuple[Mon, Mon, int, bool]]":
        pp, fp = self._priority(pm), self._priority(fm)
        ps, fs = self._eff_stat(self.p, "spe"), self._eff_stat(self.f, "spe")
        player_first = (pp, ps) > (fp, fs) or ((pp, ps) == (fp, fs) and self.rng.random() < 0.5)
        a = (self.p, self.f, pm, True)
        b = (self.f, self.p, fm, False)
        return [a, b] if player_first else [b, a]

    def turn(self) -> None:
        self.turns += 1
        for mon in (self.p, self.f):
            mon.protected = False
            mon.enduring = False
            mon.hit_this_turn = False
            mon.flinched = False
        pm = self._locked_move(self.p) or self.choose(self.p, self.f, True)
        fm = self._locked_move(self.f) or self.choose(self.f, self.p, False)
        order = self._order(pm, fm)
        for idx, (user, target, move, _is_player) in enumerate(order):
            if user.fainted or target.fainted:
                break
            self.act(user, target, move, moved_first=(idx == 0))
            if self.p.fainted or self.f.fainted:
                break
        if not (self.p.fainted or self.f.fainted):
            self.end_of_turn()

    def _locked_move(self, mon: Mon) -> int:
        if mon.recharge:
            return -1
        if mon.charging:
            return mon.charging
        if mon.rampage > 0:
            return mon.rampage_move
        if mon.bide > 0:
            return 117
        if mon.rollout > 0 and mon.last_move and move_row(mon.last_move)[3] == E_ROLLOUT:
            return mon.last_move
        return 0

    def act(self, user: Mon, target: Mon, move: int, moved_first: bool) -> None:
        rng = self.rng
        if move == -1:
            user.recharge = False
            return
        if user.ability == TRUANT:
            if user.loafing:
                user.loafing = False
                return
            user.loafing = True
        if user.status == "slp":
            user.sleep -= 1
            if user.sleep > 0:
                if move > 0 and move_row(move) and move_row(move)[3] == E_SNORE:
                    pass
                else:
                    user.charging = None
                    return
            else:
                user.status = None
        if user.status == "frz":
            if rng.random() < 0.2 or (move > 0 and move_row(move) and move_row(move)[3] == E_THAW_HIT):
                user.status = None
            else:
                return
        if user.flinched:
            user.flinched = False
            return
        if user.confused:
            user.confused -= 1
            if user.confused > 0 and rng.random() < 0.5:
                atk, de = self._eff_stat(user, "atk"), self._eff_stat(user, "def")
                self._damage(user, (2 * user.level // 5 + 2) * 40 * atk // de // 50 + 2)
                user.charging = None
                user.rampage = 0
                return
        if user.status == "par" and rng.random() < 0.25:
            user.charging = None
            user.rampage = 0
            return
        if user.attracted and rng.random() < 0.5:
            return
        if move == 165:
            self._use_struggle(user, target)
            return
        # PP
        for slot in user.moves:
            if slot[0] == move and not user.charging and not user.rampage and not user.bide and \
                    not (user.rollout and move_row(move)[3] == E_ROLLOUT):
                slot[1] -= 2 if target.ability == PRESSURE else 1
                break
        user.last_move = move
        user.destiny_bond = False
        self._execute(user, target, move, moved_first)

    def _use_struggle(self, user: Mon, target: Mon) -> None:
        atk, de = self._eff_stat(user, "atk"), self._eff_stat(target, "def")
        dmg = ((2 * user.level // 5 + 2) * 50 * atk // de // 50 + 2) * self.rng.randint(85, 100) // 100
        dealt = self._damage(target, max(1, dmg))
        self._damage(user, max(1, dealt // 4))

    def _accuracy_hits(self, user: Mon, target: Mon, move: int) -> bool:
        row = move_row(move)
        acc, effect = row[2], row[3]
        if target.invulnerable:
            return False
        if acc == 0 or effect == E_ALWAYS_HIT or effect == 78:
            return True
        if effect == E_THUNDER and self._weather_active() == "rain":
            return True
        stage = max(-6, min(6, user.stages["acc"] - target.stages["eva"]))
        num, den = _ACC_STAGE[stage]
        chance = acc * num // den
        if user.ability == COMPOUNDEYES:
            chance = chance * 130 // 100
        if user.ability == HUSTLE and row[0] in PHYSICAL_TYPES and row[1] > 0:
            chance = chance * 80 // 100
        w = self._weather_active()
        if target.ability == SAND_VEIL and w == "sand":
            chance = chance * 80 // 100
        if effect == E_THUNDER and w == "sun":
            chance = 50
        return self.rng.randint(1, 100) <= chance

    def _execute(self, user: Mon, target: Mon, move: int, moved_first: bool) -> None:
        rng = self.rng
        row = move_row(move)
        mtype, power, acc, effect, chance, _prio, contact, sound = row[:8]
        # two-turn moves
        if effect in (E_RAZOR_WIND, E_SKY_ATTACK, E_SKULL_BASH, E_SOLARBEAM, E_SEMI_INVULNERABLE) and user.charging != move:
            if not (effect == E_SOLARBEAM and self._weather_active() == "sun"):
                user.charging = move
                if effect == E_SKULL_BASH:
                    self._stage(user, "def", 1)
                if effect == E_SEMI_INVULNERABLE:
                    user.invulnerable = True
                return
        if user.charging == move:
            user.charging = None
            user.invulnerable = False
        if effect == E_BIDE:
            if user.bide == 0:
                user.bide, user.bide_damage = 2, 0
                return
            user.bide -= 1
            if user.bide > 0:
                return
            dmg = user.bide_damage * 2
            if dmg and effectiveness(NORMAL, target.types) > 0:
                self._damage(target, dmg)
            return
        if power <= 0:
            self._status_move(user, target, move)
            return
        # Protect blocks damaging moves aimed at the target
        if target.protected:
            return
        if effect == E_FAKE_OUT and self.turns > 1:
            return
        if effect == E_DREAM_EATER and target.status != "slp":
            return
        if effect == E_SNORE and user.status != "slp":
            return
        if effect == E_SPIT_UP:
            return
        if effect == E_FOCUS_PUNCH and user.hit_this_turn:
            return
        if effect == E_FUTURE_SIGHT:
            if user.future is None:
                dmg, _ = self.calc_damage(user, target, move, crit=False, roll=rng.randint(85, 100))
                target.future = (3, dmg)
            return
        if effect == E_EXPLOSION:
            if target.ability == DAMP or user.ability == DAMP:
                return
            self._damage(user, user.hp)
        if effect == E_COUNTER or effect == E_MIRROR_COAT:
            want_physical = effect == E_COUNTER
            if user.last_damage_taken and user.hit_this_turn and user.last_damage_physical == want_physical:
                eff = effectiveness(mtype, target.types)
                if eff > 0 and not (target.ability == WONDER_GUARD):
                    self._damage(target, user.last_damage_taken * 2)
            return
        if effect == E_OHKO:
            if target.level > user.level or target.ability == STURDY:
                return
            if effectiveness(mtype, target.types) == 0:
                return
            if rng.randint(1, 100) <= 30 + user.level - target.level and not target.invulnerable:
                self._damage(target, target.hp)
            return
        if not self._accuracy_hits(user, target, move):
            if effect == E_RECOIL_IF_MISS:
                atk_dmg, _ = self.calc_damage(user, target, move, crit=False, roll=100)
                self._damage(user, max(1, min(atk_dmg, target.stats["hp"]) // 2))
            if effect == E_ROLLOUT:
                user.rollout = 0
            if effect == E_FURY_CUTTER:
                user.fury = 0
            return
        t, _p = self._type_and_power(user, target, move)
        eff = 1.0 if effect in (E_BEAT_UP, E_FUTURE_SIGHT) else effectiveness(t, target.types)
        if eff == 0 or self._blocked_by_ability(target, move, t, eff):
            if effect == E_RECOIL_IF_MISS:
                atk_dmg, _ = self.calc_damage(user, target, move, crit=False, roll=100)
                self._damage(user, max(1, atk_dmg // 2))
            return
        hits = 1
        if effect == E_MULTI_HIT:
            hits = rng.choice((2, 2, 2, 3, 3, 3, 4, 5))
        elif effect in (E_DOUBLE_HIT, E_TWINEEDLE):
            hits = 2
        elif effect == E_TRIPLE_KICK:
            hits = 3
        total = 0
        for h in range(hits):
            if target.fainted:
                break
            fixed = _fixed_damage(effect, user.level, target.hp, False, rng)
            if fixed is not None:
                dmg = fixed
            else:
                crit_stage = (1 if effect in (E_HIGH_CRIT, E_SKY_ATTACK, E_BLAZE_KICK, E_POISON_TAIL) else 0) + (2 if user.focus else 0)
                crit_chance = (16, 8, 4, 3, 2)[min(crit_stage, 4)]
                crit = target.ability not in (BATTLE_ARMOR, SHELL_ARMOR) and rng.randint(1, crit_chance) == 1
                if effect == E_TRIPLE_KICK:
                    dmg, _ = self.calc_damage(user, target, move, crit=crit, roll=rng.randint(85, 100))
                    dmg *= (h + 1)
                else:
                    dmg, _ = self.calc_damage(user, target, move, crit=crit, roll=rng.randint(85, 100))
            if effect == E_FALSE_SWIPE:
                dmg = min(dmg, target.hp - 1)
            if target.substitute > 0:
                target.substitute -= dmg
                if target.substitute < 0:
                    target.substitute = 0
                continue
            dealt = self._damage(target, dmg)
            total += dealt
            target.hit_this_turn = True
            target.last_damage_taken = dealt
            target.last_damage_physical = t in PHYSICAL_TYPES
            if target.bide:
                target.bide_damage += dealt
            if contact:
                self._contact_ability(user, target)
            if user.fainted:
                break
        if effect == E_ROLLOUT:
            user.rollout = (user.rollout + 1) % 5
        if effect == E_FURY_CUTTER:
            user.fury += 1
        if target.fainted and target.destiny_bond:
            self._damage(user, user.hp)
        if effect == E_ABSORB or effect == E_DREAM_EATER:
            if target.ability == LIQUID_OOZE:
                self._damage(user, max(1, total // 2))
            else:
                self._heal(user, max(1, total // 2))
        if effect == E_RECOIL and user.ability != ROCK_HEAD:
            self._damage(user, max(1, total // 4))
        if effect == E_DOUBLE_EDGE and user.ability != ROCK_HEAD:
            self._damage(user, max(1, total // 3))
        if effect == E_RECHARGE and not target.fainted:
            user.recharge = True
        if effect == E_RAMPAGE:
            if user.rampage == 0:
                user.rampage, user.rampage_move = rng.randint(2, 3), move
            user.rampage -= 1
            if user.rampage == 0:
                self._confuse(user)
        if effect in _HIT_SELF_STAGES:
            for stat, n in _HIT_SELF_STAGES[effect]:
                self._stage(user, stat, n)
        if target.fainted or total == 0:
            return
        self._secondary(user, target, effect, chance, moved_first)

    def _secondary(self, user: Mon, target: Mon, effect: int, chance: int, moved_first: bool) -> None:
        rng = self.rng
        if target.ability == SHIELD_DUST and effect not in _HIT_SELF_CHANCE_STAGES:
            return
        if effect == E_FAKE_OUT:
            chance = 100               # the table stores 0; the flinch is the move
        if user.ability == SERENE_GRACE:
            chance = min(100, chance * 2)
        roll = rng.randint(1, 100) <= chance
        if not roll:
            return
        if effect in (E_POISON_HIT, E_TWINEEDLE, E_POISON_TAIL):
            self._give_status(target, "psn", user)
        elif effect == E_POISON_FANG:
            self._give_status(target, "tox", user)
        elif effect in (E_BURN_HIT, E_BLAZE_KICK):
            self._give_status(target, "brn", user)
        elif effect == E_FREEZE_HIT:
            self._give_status(target, "frz", user)
        elif effect in (E_PARALYZE_HIT, E_THUNDER):
            self._give_status(target, "par", user)
        elif effect == E_TRI_ATTACK:
            self._give_status(target, rng.choice(("par", "brn", "frz")), user)
        elif effect in (E_FLINCH_HIT, E_FLINCH_MINIMIZE_HIT, E_SKY_ATTACK, 146, E_FAKE_OUT):
            if moved_first and target.ability != INNER_FOCUS:
                target.flinched = True
        elif effect == E_CONFUSE_HIT:
            self._confuse(target)
        elif effect in _HIT_TARGET_STAGES:
            stat, n = _HIT_TARGET_STAGES[effect]
            self._stage(target, stat, n, source_is_foe=True)
        elif effect in _HIT_SELF_CHANCE_STAGES:
            for stat, n in _HIT_SELF_CHANCE_STAGES[effect]:
                self._stage(user, stat, n)
        elif effect == E_TRAP:
            target.trap = rng.randint(2, 5)

    def _contact_ability(self, user: Mon, target: Mon) -> None:
        rng = self.rng
        a = target.ability
        if a == ROUGH_SKIN:
            self._damage(user, max(1, user.stats["hp"] // 16))
        elif a == STATIC and rng.random() < 0.3:
            self._give_status(user, "par", target)
        elif a == POISON_POINT and rng.random() < 0.3:
            self._give_status(user, "psn", target)
        elif a == FLAME_BODY and rng.random() < 0.3:
            self._give_status(user, "brn", target)
        elif a == EFFECT_SPORE and rng.random() < 0.1:
            self._give_status(user, rng.choice(("psn", "par", "slp")), target)
        elif a == CUTE_CHARM and rng.random() < 0.3 and user.gender != target.gender and user.ability != OBLIVIOUS:
            user.attracted = True
        elif a == COLOR_CHANGE:
            pass

    def _status_move(self, user: Mon, target: Mon, move: int) -> None:
        rng = self.rng
        row = move_row(move)
        mtype, _power, acc, effect = row[:4]
        targets_foe = effect in (E_SLEEP, E_TOXIC, E_POISON, E_PARALYZE, E_CONFUSE, E_SWAGGER, E_FLATTER,
                                 E_WILL_O_WISP, E_LEECH_SEED, E_ATTRACT, E_DISABLE, E_YAWN, E_TEETER_DANCE,
                                 E_TRANSFORM) or effect in _TARGET_STAGES or effect == E_MEMENTO
        if targets_foe:
            if target.protected or target.invulnerable:
                return
            if target.ability == SOUNDPROOF and row[7]:
                return
            if acc and not self._accuracy_hits(user, target, move):
                return
        if effect == E_SLEEP:
            self._give_status(target, "slp", user)
        elif effect == E_TOXIC:
            self._give_status(target, "tox", user)
        elif effect == E_POISON:
            self._give_status(target, "psn", user)
        elif effect == E_PARALYZE:
            if not (mtype == ELECTRIC and effectiveness(ELECTRIC, target.types) == 0):
                self._give_status(target, "par", user)
        elif effect == E_WILL_O_WISP:
            self._give_status(target, "brn", user)
        elif effect in (E_CONFUSE, E_TEETER_DANCE):
            self._confuse(target)
        elif effect == E_SWAGGER:
            self._stage(target, "atk", 2)
            self._confuse(target)
        elif effect == E_FLATTER:
            self._stage(target, "spa", 1)
            self._confuse(target)
        elif effect in _TARGET_STAGES:
            if target.substitute > 0:
                return
            for stat, n in _TARGET_STAGES[effect]:
                self._stage(target, stat, n, source_is_foe=True)
        elif effect in _SELF_STAGES:
            for stat, n in _SELF_STAGES[effect]:
                self._stage(user, stat, n)
        elif effect == E_CURSE:
            if GHOST in user.types:
                self._damage(user, user.stats["hp"] // 2)
                target.cursed = True
            else:
                self._stage(user, "atk", 1)
                self._stage(user, "def", 1)
                self._stage(user, "spe", -1)
        elif effect == E_BELLY_DRUM:
            if user.hp > user.stats["hp"] // 2:
                self._damage(user, user.stats["hp"] // 2)
                user.stages["atk"] = 6
        elif effect in (E_RESTORE_HP, E_SOFTBOILED):
            self._heal(user, user.stats["hp"] // 2)
        elif effect in (E_MORNING_SUN, E_SYNTHESIS, E_MOONLIGHT):
            w = self._weather_active()
            frac = 2 / 3 if w == "sun" else (1 / 4 if w else 1 / 2)
            self._heal(user, int(user.stats["hp"] * frac))
        elif effect == E_REST:
            if user.hp < user.stats["hp"] and user.ability not in (INSOMNIA, VITAL_SPIRIT):
                user.hp, user.status, user.sleep = user.stats["hp"], "slp", 3
        elif effect == E_PROTECT or effect == E_ENDURE:
            ok = rng.random() < 1 / (2 ** user.protect_chain)
            if ok:
                user.protect_chain += 1
                if effect == E_PROTECT:
                    user.protected = True
                else:
                    user.enduring = True
            else:
                user.protect_chain = 0
            return
        elif effect == E_LEECH_SEED:
            if GRASS not in target.types and target.substitute == 0:
                target.seeded = True
        elif effect == E_SUBSTITUTE:
            cost = user.stats["hp"] // 4
            if user.substitute == 0 and user.hp > cost:
                self._damage(user, cost)
                user.substitute = cost
        elif effect == E_REFLECT:
            user.screen_reflect = 5
        elif effect == E_LIGHT_SCREEN:
            user.screen_light = 5
        elif effect == E_HAZE:
            for mon in (user, target):
                for k in mon.stages:
                    mon.stages[k] = 0
        elif effect == E_DISABLE:
            if target.last_move and not target.disabled:
                target.disabled, target.disabled_turns = target.last_move, rng.randint(2, 5)
        elif effect == E_ATTRACT:
            if user.gender != target.gender and target.ability != OBLIVIOUS:
                target.attracted = True
        elif effect == E_YAWN:
            if target.status is None and not target.yawn:
                target.yawn = 2
        elif effect == E_PAIN_SPLIT:
            avg = (user.hp + target.hp) // 2
            user.hp, target.hp = min(user.stats["hp"], avg), min(target.stats["hp"], avg)
        elif effect == E_DESTINY_BOND:
            user.destiny_bond = True
        elif effect == E_PERISH_SONG:
            for mon in (user, target):
                if not mon.perish and not (mon.ability == SOUNDPROOF):
                    mon.perish = 4
        elif effect == E_MEMENTO:
            self._damage(user, user.hp)
            self._stage(target, "atk", -2, source_is_foe=True)
            self._stage(target, "spa", -2, source_is_foe=True)
        elif effect == E_SANDSTORM:
            self.weather, self.weather_turns = "sand", 5
        elif effect == E_HAIL:
            self.weather, self.weather_turns = "hail", 5
        elif effect == E_RAIN_DANCE:
            self.weather, self.weather_turns = "rain", 5
        elif effect == E_SUNNY_DAY:
            self.weather, self.weather_turns = "sun", 5
        elif effect == E_TRANSFORM:
            user.types = target.types
            user.stats = dict(target.stats, hp=user.stats["hp"])
            user.moves = [[m, 5] for m, _ in target.moves]
            user.ability = target.ability
            user.stages = dict(target.stages)
        elif effect == 47:
            user.focus = True
        if effect not in (E_PROTECT, E_ENDURE):
            user.protect_chain = 0

    def end_of_turn(self) -> None:
        rng = self.rng
        w = self._weather_active()
        for mon, other in ((self.p, self.f), (self.f, self.p)):
            if mon.fainted:
                continue
            if w == "sand" and not ({ROCK, GROUND, STEEL} & set(mon.types)) and mon.ability != SAND_VEIL:
                self._damage(mon, max(1, mon.stats["hp"] // 16))
            if w == "hail" and ICE not in mon.types:
                self._damage(mon, max(1, mon.stats["hp"] // 16))
            if mon.fainted:
                continue
            if mon.status == "psn":
                self._damage(mon, max(1, mon.stats["hp"] // 8))
            elif mon.status == "tox":
                self._damage(mon, max(1, mon.stats["hp"] * mon.toxic // 16))
                mon.toxic += 1
            elif mon.status == "brn":
                self._damage(mon, max(1, mon.stats["hp"] // 8))
            if mon.seeded and not mon.fainted and not other.fainted:
                drained = self._damage(mon, max(1, mon.stats["hp"] // 8))
                self._heal(other, drained)
            if mon.cursed:
                self._damage(mon, max(1, mon.stats["hp"] // 4))
            if mon.trap:
                mon.trap -= 1
                self._damage(mon, max(1, mon.stats["hp"] // 16))
            if mon.future:
                turns, dmg = mon.future
                if turns <= 1:
                    self._damage(mon, dmg)
                    mon.future = None
                else:
                    mon.future = (turns - 1, dmg)
            if mon.yawn:
                mon.yawn -= 1
                if mon.yawn == 0:
                    self._give_status(mon, "slp")
            if mon.perish:
                mon.perish -= 1
                if mon.perish == 0:
                    self._damage(mon, mon.hp)
            if mon.status and mon.ability == SHED_SKIN and rng.random() < 0.3:
                mon.status = None
            if mon.ability == SPEED_BOOST:
                self._stage(mon, "spe", 1)
            if mon.disabled:
                mon.disabled_turns -= 1
                if mon.disabled_turns <= 0:
                    mon.disabled = 0
            for screen in ("screen_reflect", "screen_light"):
                if getattr(mon, screen):
                    setattr(mon, screen, getattr(mon, screen) - 1)
        if self.weather_turns:
            self.weather_turns -= 1
            if self.weather_turns == 0:
                self.weather = None

    def run(self, max_turns: int = 200) -> str:
        """'win', 'loss', or 'draw' (both down, or the turn limit) -- a draw is not a win."""
        while self.turns < max_turns:
            self.turn()
            if self.p.fainted and self.f.fainted:
                return "draw"
            if self.f.fainted:
                return "win"
            if self.p.fainted:
                return "loss"
        return "draw"


def simulate(starter_internal: int, starter_level: int, starter_moves: "list[int]", foe_internal: int,
             foe_level: int, foe_moves: "list[int]", rng: random.Random, *, battles: int = 200,
             foe_ivs: "tuple[int, ...]" = (0,) * 6, foe_nature=(None, None), foe_ability: "int | None" = None,
             foe_greedy: float = 0.5) -> "dict[str, float]":
    """Plays `battles` fights; the starter's IVs, nature, ability and gender are rolled per fight, since the game
    rolls them at new-game time. The foe is fixed, as the deck data fixes it (IVs 0, Hardy, ability slot 0)."""
    results = {"win": 0, "loss": 0, "draw": 0}
    turns = 0
    for _ in range(battles):
        player = make_mon(starter_internal, starter_level, starter_moves, rng, friendship=STARTER_FRIENDSHIP)
        foe = make_mon(foe_internal, foe_level, foe_moves, rng, ivs=foe_ivs, nature=foe_nature,
                       ability=species_abilities(foe_internal)[0] if foe_ability is None else foe_ability)
        battle = Battle(player, foe, rng, foe_greedy=foe_greedy)
        results[battle.run()] += 1
        turns += battle.turns
    return {"win_rate": results["win"] / battles, "losses": results["loss"], "draws": results["draw"],
            "mean_turns": turns / battles}
