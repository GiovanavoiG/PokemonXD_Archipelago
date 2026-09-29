"""The species stats table in `common_rel`, and the two bytes that decide experience.

Experience belongs to the SPECIES, not to a trainer's Pokemon: the DPKM record is 0x20 bytes and all of
them are named, censused against all 823 records in a real DeckData_Story.bin.

The table was found in a real `common_rel` RAM dump by requiring 22 species to agree on this project's own
base-HP offset (+0x8F); every offset in the 0x124-byte entry was then brute-forced against 50 known Gen III
base-experience yields and exactly one matched all 50. Both offsets, and the single-byte width, agree with
rotobash/pokemon-ngc-rando's `XDPokemon.cs` (see NOTICE.md).

    +0x00  u8   experience group (the `ExpRate` enum below)
    +0x01  u8   catch rate                 verified: Bulbasaur 45, Pikachu 190, Chansey 30, Mewtwo 3
    +0x02  u8   gender ratio               verified: Bulbasaur 31, Pikachu 127, Chansey 254, Mewtwo 255
    +0x05  u8   base experience yield      verified: 50/50 species
    +0x07  u8   base happiness             70 in 327 of 415 entries
    +0x08  u16  height, decimetres         verified: Bulbasaur 7, Snorlax 21, Mewtwo 20
    +0x0A  u16  weight, hectograms         verified: Bulbasaur 69, Snorlax 4600, Mewtwo 1220
    +0x0E  u16  National Dex number
    +0x8F  base HP, then Atk/Def/SpAtk/SpDef/Speed two bytes apart
    +0xC4  the level-up learnset

Two levers, not one, because base exp is a byte: vanilla runs 20..255 (mean 135.6), so a plain multiplier
saturates -- x1.5 delivers 1.44x (114/386 species clamp), x2 1.71x (219), x3 2.04x (297), x5 2.25x (380).
The second lever is the experience GROUP at +0x00, safe because a trainer's Pokemon never gains experience
(its level is a fixed byte in the deck data), so it only moves the player's own levelling. Combined ceiling
is about 2.6x, measured mean 2.63x at rate 500; `plan_experience_rate` reports what it actually achieved.
Nothing here slows anything down, and at rate 100 the plan is empty so the common_rel pass is skipped."""

from __future__ import annotations

SPECIES_STATS_ENTRY_SIZE = 0x124
EXP_RATE_OFFSET = 0x00
CATCH_RATE_OFFSET = 0x01
GENDER_RATIO_OFFSET = 0x02
BASE_EXP_OFFSET = 0x05
BASE_HAPPINESS_OFFSET = 0x07
HEIGHT_OFFSET = 0x08
WEIGHT_OFFSET = 0x0A
NATIONAL_DEX_OFFSET = 0x0E
BASE_HP_OFFSET = 0x8F

#: Both fields are single bytes; that ceiling is the whole reason the curve lever exists.
BASE_EXP_MAX = 0xFF
BASE_EXP_MIN = 1

# Order taken from pokemon-ngc-rando's `ExpRate`, then confirmed against the real table: Bulbasaur 3,
# Pikachu 0, Chansey 4, Magikarp 5, Mewtwo 5, Eevee 0. The names are the ones players use.
EXP_RATE_MEDIUM_FAST = 0
EXP_RATE_ERRATIC = 1
EXP_RATE_FLUCTUATING = 2
EXP_RATE_MEDIUM_SLOW = 3
EXP_RATE_FAST = 4
EXP_RATE_SLOW = 5

#: Total experience to reach level 100 per group -- the ratio the planner compares curves by.
EXP_RATE_TOTAL_TO_100: "dict[int, int]" = {
    EXP_RATE_MEDIUM_FAST: 1_000_000,
    EXP_RATE_ERRATIC: 600_000,
    EXP_RATE_FLUCTUATING: 1_640_000,
    EXP_RATE_MEDIUM_SLOW: 1_059_860,
    EXP_RATE_FAST: 800_000,
    EXP_RATE_SLOW: 1_250_000,
}

EXP_RATE_NAMES: "dict[int, str]" = {
    EXP_RATE_MEDIUM_FAST: "Medium Fast",
    EXP_RATE_ERRATIC: "Erratic",
    EXP_RATE_FLUCTUATING: "Fluctuating",
    EXP_RATE_MEDIUM_SLOW: "Medium Slow",
    EXP_RATE_FAST: "Fast",
    EXP_RATE_SLOW: "Slow",
}

assert set(EXP_RATE_NAMES) == set(EXP_RATE_TOTAL_TO_100), "every group needs a name and a total"

#: Percent, because Archipelago's `Range` is integer-only and the player asked for decimals: 250 is 2.50x
#: and 1% steps make 1.75x and 3.33x both expressible. Every use below divides by this, never by 100 inline.
RATE_SCALE = 100
RATE_MIN = 100

# ADDENDUM 384: the divisor in the game's own experience formula, and the reason this range is no longer 500.
#
# The formula is `base_exp * level / 7`, and the 7 is an immediate in one instruction:
#
#     0x80212C80  mullw r3,r3,r0     base_exp * level
#     0x80212C84  li    r0,7         <- this
#     0x80212C8C  divw  r0,r3,r0     / 7
#
# Found by solving main.dol's load base from two functions this project had already documented
# (`setExp` and `getLevel`, agreeing on 0x800030A0 out of 49 candidate pairings, then all nine
# documented accessors decoding correctly), then taking the only two `li rX,7` instructions in the DOL that
# feed a division. The other is a modulo on an unrelated halfword. Confirmed against a measured award:
# an Eevee at level 11 gained exactly 154, and 98 * 11 / 7 is 154 on the nose.
#
# WHY IT CHANGES THE CEILING. Base exp is a byte, so the table levers together top out near 2.6x however
# much is asked -- measured 2.63x at the old maximum of 500, with 358 of 386 species clamped at 255. The
# divisor is not a byte in a table, it is an operand: 7 -> 3 is 2.33x on every species at once, exactly,
# with no clamping and no distortion of which Pokemon are worth fighting.
#
# THE DIVISOR IS SPENT FIRST, for that reason. It is uniform and exact where the table is lossy, so a rate
# the divisor can satisfy alone leaves every species' bytes as shipped -- 233% now costs nothing at all,
# where before it clamped 227 species.
EXP_DIVISOR_VANILLA = 7
EXP_DIVISOR_MIN = 1                 # `divw` by 0 is undefined on PowerPC; 1 is "no division at all"

#: Capped where the option still DELIVERS what it says. The divisor alone is exact to 700 (0 species
#: clamped); the tables then carry the rest, and measured against the real table the gap stays under 1%
#: through 1000 (9.91x for 10x, 36 clamped) and opens up past it -- 3% by 1200. The old ceiling was 500
#: asked for 2.63x delivered, which is the thing this range exists to stop doing.
RATE_MAX = 1000


def divisor_speedup(divisor: int) -> float:
    """How much faster experience arrives with `divisor` in place of the vanilla 7."""
    divisor = max(EXP_DIVISOR_MIN, min(EXP_DIVISOR_VANILLA, int(divisor)))
    return EXP_DIVISOR_VANILLA / divisor


def choose_exp_divisor(rate_percent: int) -> int:
    """The divisor to write for `rate_percent`: the biggest speedup that does not overshoot on its own.

    Overshooting would mean handing back experience with the table levers, which they cannot do -- they only
    ever raise. So the divisor takes whole steps up to the request and the tables cover the remainder."""
    wanted = max(RATE_MIN, min(RATE_MAX, int(rate_percent))) / RATE_SCALE
    chosen = EXP_DIVISOR_VANILLA
    for candidate in range(EXP_DIVISOR_VANILLA - 1, EXP_DIVISOR_MIN - 1, -1):
        if EXP_DIVISOR_VANILLA / candidate <= wanted + 1e-9:
            chosen = candidate
    return chosen
# ADDENDUM 349 -- evolving used to lose levels. Measured against the real table in `a263_commonrel.bin`, at
# 250% Eevee (Medium Fast -> Erratic) dropped up to 4 levels on evolving and at 400% (Fast -> Erratic) up to
# 7, with up to 111 of 122 evolution pairs on two different curves, worst case -9. Erratic is not actually
# faster: it is `n^3*(100-n)/50` below level 50, more than Medium Fast's `n^3` at every level under 50.
# So a replacement must need no more experience at EVERY level 2..100 (computed below, not typed in), which
# leaves three uniform-ratio transitions, and the curve is chosen once per SOURCE curve so no evolution
# crosses a boundary vanilla did not -- fifteen of the game's own 122 pairs already do. Worth 1.25x, for
# Medium Fast and Slow species only.


def exp_total_at_level(curve: int, level: int) -> int:
    """Total experience required to BE `level` on `curve`. The real Gen III formulas, integer division
    throughout as in the games, so the domination test below is derived from the curves themselves."""
    n = int(level)
    if n <= 1:
        return 0
    if curve == EXP_RATE_MEDIUM_FAST:
        return n ** 3
    if curve == EXP_RATE_FAST:
        return 4 * n ** 3 // 5
    if curve == EXP_RATE_SLOW:
        return 5 * n ** 3 // 4
    if curve == EXP_RATE_MEDIUM_SLOW:
        return (6 * n ** 3) // 5 - 15 * n * n + 100 * n - 140
    if curve == EXP_RATE_ERRATIC:
        if n < 50:
            return n ** 3 * (100 - n) // 50
        if n < 68:
            return n ** 3 * (150 - n) // 100
        if n < 98:
            return n ** 3 * ((1911 - 10 * n) // 3) // 500
        return n ** 3 * (160 - n) // 100
    if curve == EXP_RATE_FLUCTUATING:
        if n < 15:
            return n ** 3 * ((n + 1) // 3 + 24) // 50
        if n < 36:
            return n ** 3 * (n + 14) // 50
        return n ** 3 * (n // 2 + 32) // 50
    return n ** 3


def level_at_exp(curve: int, experience: int) -> int:
    """The level `experience` buys on `curve` -- what the game derives after a species change."""
    level = 1
    for n in range(2, 101):
        if exp_total_at_level(curve, n) <= experience:
            level = n
        else:
            break
    return level


def _dominates(replacement: int, current: int) -> bool:
    """True when `replacement` never needs more experience than `current` at any level -- the safety
    property: if it holds, nothing can lose a level by moving between them."""
    if replacement == current:
        return False
    cheaper_somewhere = False
    for n in range(2, 101):
        have, want = exp_total_at_level(current, n), exp_total_at_level(replacement, n)
        if want > have:
            return False
        if want < have:
            cheaper_somewhere = True
    return cheaper_somewhere


#: {current curve: (replacements faster at EVERY level, fastest first)}. Derived, never typed.
SAFE_CURVE_REPLACEMENTS: "dict[int, tuple[int, ...]]" = {
    current: tuple(sorted(
        (c for c in EXP_RATE_TOTAL_TO_100 if _dominates(c, current)),
        key=lambda c: exp_total_at_level(c, 100)))
    for current in EXP_RATE_TOTAL_TO_100
}


def curve_speedup(current: int, replacement: int) -> float:
    """How much faster `replacement` levels a Pokemon than `current`; 1.0 means no change.

    Level 100 is exact rather than a summary because every transition `SAFE_CURVE_REPLACEMENTS` allows is a
    uniform ratio at every level (Medium Fast to Fast 4/5, Slow to Medium Fast 4/5, Slow to Fast 16/25)."""
    have = EXP_RATE_TOTAL_TO_100.get(current)
    want = EXP_RATE_TOTAL_TO_100.get(replacement)
    if not have or not want:
        return 1.0
    return have / want


def best_curve_within(current: int, budget: float) -> int:
    """The fastest SAFE group no more than `budget` times faster than `current`, or `current` if none
    qualifies. Candidates come from `SAFE_CURVE_REPLACEMENTS`, so Erratic can no longer be picked."""
    best, best_ratio = current, 1.0
    for candidate in SAFE_CURVE_REPLACEMENTS.get(current, ()):
        ratio = curve_speedup(current, candidate)
        if ratio < 1.0 or ratio > budget:
            continue
        if ratio > best_ratio:
            best, best_ratio = candidate, ratio
    return best


def plan_experience_rate(
    species: "dict[int, tuple[int, int]]",
    rate_percent: int,
    use_curve: bool = True,
    from_divisor: float = 1.0,
) -> "dict[str, object]":
    """Build the write plan. `species` is {internal_index: (base_exp, exp_rate)} read from the real table.

    Returns {"rate_percent", "base_exp", "exp_rate", "achieved_mean", "achieved_min", "achieved_max",
    "clamped"}; the two dicts hold only entries that CHANGE, str-keyed to survive the JSON round-trip
    through the `.appxd` seed file. Base exp is spent first and the curve asked only for the shortfall, so a
    rate the byte can satisfy alone leaves every levelling curve as shipped; at rate 100 both are empty."""
    rate = max(RATE_MIN, min(RATE_MAX, int(rate_percent)))
    out_base: "dict[str, int]" = {}
    out_rate: "dict[str, int]" = {}
    achieved: "list[float]" = []
    clamped = 0
    if rate == RATE_SCALE:
        return {"rate_percent": rate, "base_exp": {}, "exp_rate": {},
                "achieved_mean": 1.0, "achieved_min": 1.0, "achieved_max": 1.0, "clamped": 0}

    # ADDENDUM 384: whatever the divisor already delivered is not asked of the bytes again.
    wanted = (rate / RATE_SCALE) / max(1.0, float(from_divisor))
    if wanted <= 1.0:
        return {"rate_percent": rate, "base_exp": {}, "exp_rate": {},
                "achieved_mean": 1.0, "achieved_min": 1.0, "achieved_max": 1.0, "clamped": 0}

    # ADDENDUM 349: the curve is decided once per source curve, before any species is looked at. Deciding it
    # per species from that species' own clamped shortfall is what split Eevee from Vaporeon and lost levels
    # on evolution. The budget is the request itself, not a per-species shortfall; overshoot is taken back on
    # the base-exp side below, where it can be done per species without splitting anything.
    curve_for: "dict[int, int]" = {}
    if use_curve:
        for _index, pair in species.items():
            source = int(pair[1])
            if source not in curve_for:
                curve_for[source] = best_curve_within(source, wanted)

    for index, pair in species.items():
        base_exp, exp_rate = int(pair[0]), int(pair[1])
        if base_exp <= 0:
            continue                      # an entry with no yield is not a species this touches
        replacement = curve_for.get(exp_rate, exp_rate)
        from_curve = curve_speedup(exp_rate, replacement) if replacement != exp_rate else 1.0
        if replacement != exp_rate:
            out_rate[str(index)] = replacement
        # Ask the byte only for the shortfall the curve did not already deliver, so nothing overshoots.
        want_from_base = wanted / from_curve
        raised = min(BASE_EXP_MAX, max(BASE_EXP_MIN, round(base_exp * want_from_base)))
        if raised != base_exp:
            out_base[str(index)] = raised
        if raised == BASE_EXP_MAX and base_exp * want_from_base > BASE_EXP_MAX:
            clamped += 1
        achieved.append((raised / base_exp) * from_curve)

    if not achieved:
        achieved = [1.0]
    return {
        "rate_percent": rate,
        "base_exp": out_base,
        "exp_rate": out_rate,
        "achieved_mean": sum(achieved) / len(achieved),
        "achieved_min": min(achieved),
        "achieved_max": max(achieved),
        "clamped": clamped,
    }


def describe_plan(plan: "dict[str, object]") -> str:
    """One line for the seed log: what was asked and what was actually delivered."""
    rate = int(plan.get("rate_percent", RATE_SCALE))
    if rate == RATE_SCALE:
        return "Experience rate: vanilla (nothing written)."
    mean = float(plan.get("achieved_mean", 1.0))
    lo = float(plan.get("achieved_min", 1.0))
    hi = float(plan.get("achieved_max", 1.0))
    base_n = len(plan.get("base_exp") or {})
    rate_n = len(plan.get("exp_rate") or {})
    clamped = int(plan.get("clamped", 0))
    return (f"Experience rate: asked {rate / RATE_SCALE:.2f}x, delivering {mean:.2f}x on average "
            f"(range {lo:.2f}x-{hi:.2f}x) -- {base_n} base-exp value(s) raised ({clamped} clamped at the "
            f"byte's 255 ceiling) and {rate_n} levelling curve(s) made faster.")


# ADDENDUM 300 -- max catch rate, which lives in two places: ordinary species at +0x01 of the 0x124-byte
# stats entry (verified: Bulbasaur 45, Pikachu 190, Chansey 30, Mewtwo 3), and Shadows not there at all --
# each DDPK record has its own `catch_rate_override` at +0x01, which is what a Snag Ball is checked against,
# so writing only the stats table leaves every snag at vanilla difficulty. The other half is
# `iso_patcher.apply_shadow_catch_rate`, over all three DarkPokemon copies (ADDENDUM 287).
#
# 255 is the byte's maximum, not "100%": a = ((3*HPmax - 2*HPcur) * rate * ball) / (3*HPmax) * status,
# guaranteed only at a >= 255, so rate is multiplied by a health term worth 1/3 at full HP -- at 255 with a
# plain Poke Ball on an untouched target a = 85. Full-health odds, rate 190 -> 255: Poke 28.0 -> 33.7%,
# Great 41.0 -> 50.3%, Ultra 50.3 -> 78.5%; certain at or below 50% HP (Great) and 75% (Ultra). The tutorial
# Teddiursa is a guaranteed catch yet its DDPK override reads 120 off a real `DeckData_DarkPokemon.bin`, and
# eleven vanilla Shadows read 255 without being certainties -- that catch is scripted, not rated, and no
# data byte reaches it. Clamp upward only: with the option off nothing is written.
CATCH_RATE_MAX = 0xFF


def plan_catch_rate(catch_rates: "dict[int, int]", target: int = CATCH_RATE_MAX) -> "dict[str, object]":
    """Build the write plan. `catch_rates` is {internal_index: catch_rate} read from the real table.

    Returns {"target", "catch_rate", "already_max", "raised", "lowest_seen"}; `catch_rate` holds only the
    entries that change, str-keyed as above. A rate of 0 is skipped rather than raised -- that is what the
    table's unused/sentinel rows read, and every real species reads 3 or higher."""
    target = max(1, min(CATCH_RATE_MAX, int(target)))
    out: "dict[str, int]" = {}
    already = 0
    lowest = CATCH_RATE_MAX
    for index, rate in catch_rates.items():
        rate = int(rate)
        if rate <= 0:
            continue                      # sentinel/unused row -- see the docstring
        lowest = min(lowest, rate)
        if rate >= target:
            already += 1
            continue
        out[str(index)] = target
    return {
        "target": target,
        "catch_rate": out,
        "already_max": already,
        "raised": len(out),
        "lowest_seen": lowest,
    }


def describe_catch_rate_plan(plan: "dict[str, object]") -> str:
    """One line for the patch log: what was raised and from how low."""
    raised = int(plan.get("raised", 0) or 0)
    already = int(plan.get("already_max", 0) or 0)
    target = int(plan.get("target", CATCH_RATE_MAX) or CATCH_RATE_MAX)
    lowest = int(plan.get("lowest_seen", target) or target)
    if not raised:
        return f"Catch rate: every species already reads {target}; nothing to raise."
    return (
        f"Catch rate: raised {raised} species to {target} ({already} already there; the lowest vanilla rate "
        f"among them was {lowest})."
    )
