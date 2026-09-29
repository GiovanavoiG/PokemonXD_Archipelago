"""
Pokemon XD: Gale of Darkness -- the global story byte, as data (ADDENDUM 167, 2026-09-13).

Every `(before, after)` pair here was observed live with `!story` open in the player's own run (compiled
2026-09-12, corrected across three review rounds 2026-09-13); nothing is inferred from a walkthrough.

The byte lives at `BLOCK_BASE + STORY_RECORD_OFFSET + STORY_BYTE_OFFSET` (ram_client) and is a monotonic
counter, NOT a bitfield: every area's scripts compare the same byte against their own thresholds, so an area
entered past its first-visit window silently skips that content. Hence `StoryByteAreaMemory` (regions.py).

Per region, both derived from `TRANSITIONS` (see `REGION_STORY_WINDOW`): the FLOOR its first visit expects
(below it the area is not open, above it first-visit content is skipped -- the unrecoverable direction), and
the CEILING past which that content is finished and the override retires.

Where the player's notes read "a > b > c", the intermediates hold no reachable content and are recorded as one
transition plus `passthrough`. The ADDENDUM 350 section at the bottom says what they really are.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StoryTransition:
    """One observed advance of the global story byte."""

    before: int
    after: int
    what: str                                   # the player's own description of the event
    requires: "tuple[str, ...]" = ()            # key items their notes say the event needs
    opens_regions: "tuple[str, ...]" = ()       # the regions.py regions this transition makes reachable
    passthrough: "tuple[int, ...]" = ()         # intermediate values stepped through with no content
    note: str = ""


# The full ladder, in the player's own order. `opens_regions` is the only field regions.py reads.
TRANSITIONS: "tuple[StoryTransition, ...]" = (
    StoryTransition(0x10, 0x10, "Krane Memos 1 and 2 are in the bag -- 2 AP checks, then cleared",
                    note="ADDENDUM 153 ships this; threshold is >=, not an advance of its own"),
    StoryTransition(0x15, 0x16, "Machine Part obtained", requires=(),
                    note="from the Gateon Port parts shop (player, 2026-09-13)"),
    StoryTransition(0x17, 0x17, "Krane Memos 3, 4 and 5 are in the bag -- 3 AP checks, then cleared",
                    note="same >= threshold shape as 0x10"),
    StoryTransition(0x17, 0x19, "Agate Village unlocked / first visit", requires=("Machine Part",),
                    opens_regions=("Agate Village",)),
    StoryTransition(0x21, 0x23, "first Shadow Pokemon purified"),
    StoryTransition(0x23, 0x24, "Mt. Battle unlocked / first visit", opens_regions=("Mt. Battle",)),
    # Off the ISO: D1_out stages the arrival on `flag 1692 == 0 AND storyvar(964) == 310`, and `brother_enter`
    # ends with write(964, 320). 310 is 0x26 and 320 is 0x28, so the scene is an EQUALITY on 0x26 -- which
    # ADDENDUM 314's unholdable 0x27 could not meet. Room 11 is the exterior (room_story_compilation.md).
    StoryTransition(0x25, 0x26, "Cipher Lab unlocked / first visit", opens_regions=("Cipher Lab",),
                    note="the vanilla unlock happens AT Mt. Battle (player correction, 2026-09-13); 0x26 is "
                         "story value 310, the value D1_out's hero_main tests for by equality"),
    StoryTransition(0x26, 0x28, "the arrival scene outside the Cipher Lab -- the Sixes turn up",
                    note="READ FROM THE GAME, not played: D1_out's `brother_enter` ends with write(964, 320). "
                         "The player's landmark table independently records 0x28 as 'first Cipher Lab visit, "
                         "pre-six-battle'"),
    StoryTransition(0x2F, 0x30, "Pyrite Town unlocked / first visit", requires=("Data ROM",),
                    opens_regions=("Pyrite Town",)),
    StoryTransition(0x34, 0x35, "Data ROM handed over in Pyrite Town -- Rock Poke Spot unlocked",
                    requires=("Data ROM",), opens_regions=("Poke Spots",)),
    StoryTransition(0x37, 0x38, "Poke Snacks placed at the Rock spot"),
    StoryTransition(0x38, 0x39, "Spot Monitor received -- Oasis Poke Spot unlocked",
                    note="the Spot Monitor is granted here, not shuffled: it is not a real item id"),
    StoryTransition(0x39, 0x3A, "Cave Poke Spot unlocked / first Miror B encounter"),
    StoryTransition(0x3A, 0x3C, "Miror B defeated -- Pyrite visit 2, ONBS and outside chests open",
                    opens_regions=("Pyrite Town (ONBS)",)),
    # ADDENDUM 188: Phenac is named HERE, not on the 0x3F -> 0x41 line -- `_build_windows` keeps the highest floor
    # a region is named at, so naming it twice put the first visit at 0x41, the second visit's value.
    StoryTransition(0x3C, 0x3E, "Phenac City unlocked", opens_regions=("Phenac City",), passthrough=(0x3D,)),
    StoryTransition(0x3E, 0x3F, "Phenac City first visit -- forced to Realgam Tower",
                    note="all Phenac items and trainers stay locked until Realgam is visited"),
    StoryTransition(0x3F, 0x41, "Realgam Tower first visit -- Phenac City fully unlocked",
                    opens_regions=("Realgam Tower",),
                    note="one event opens two places: Realgam is reached AND Phenac stops being locked down"),
    StoryTransition(0x41, 0x42, "Music Disc picked up (chest 80, room 98)",
                    note="chest 80 sits in plain Phenac City, NOT behind the Music Disc gate -- it IS the Disc"),
    StoryTransition(0x42, 0x43, "Music Disc handed over in the Mayor's House downstairs",
                    requires=("Music Disc",)),
    StoryTransition(0x43, 0x44, "Mayor's Note picked up in the Mayor's House upstairs (chest 78)",
                    requires=("Music Disc",), opens_regions=("Phenac City (Mayor's House)",),
                    note="its own region, gated on the Music Disc ALONE: chest 78 holds the Mayor's Note, so a "
                         "region needing both items would gate the Note behind itself"),
    StoryTransition(0x44, 0x46, "battled out of the Mayor's House -- the Sixes split up",
                    requires=("Music Disc", "Mayor's Note"), opens_regions=("Phenac City (Post-Sixes)",),
                    passthrough=(0x45,),
                    note="the Disc-AND-Note tier: the Phenac shops, Justy, Snattle, and Sixes occurrence 2"),
    StoryTransition(0x46, 0x47, "Justy defeated inside the PRE Gym",
                    requires=("Music Disc", "Mayor's Note")),
    StoryTransition(0x47, 0x48, "Snattle defeated", requires=("Music Disc", "Mayor's Note")),
    StoryTransition(0x48, 0x49, "Elevator Key picked up (chest 79, Phenac Colosseum)",
                    requires=("Music Disc", "Mayor's Note"),
                    note="left vanilla and never shuffled -- the player reports it locks you in the room"),
    StoryTransition(0x49, 0x4C, "Phenac City residents rescued",
                    requires=("Music Disc", "Mayor's Note", "Elevator Key"), passthrough=(0x4B,)),
    StoryTransition(0x4C, 0x4E, "Daycare unlocked, EXP Share from the Mayor -- SS Libra reachable",
                    requires=("Music Disc", "Mayor's Note", "Elevator Key"),
                    opens_regions=("SS Libra (stranded)",), passthrough=(0x4D,)),
    StoryTransition(0x4E, 0x50, "SS Libra first visit -- kicked back to Phenac, mail sent to Pyrite Town"),
    StoryTransition(0x50, 0x51, "talked to Nett -- told to see Perr in Gateon"),
    StoryTransition(0x51, 0x52, "talked to Perr -- told to see his grandpa at Kaminko's"),
    StoryTransition(0x52, 0x53, "Verich cutscene in Gateon -- second Kaminko visit, Chobin 2",
                    opens_regions=("Kaminko's House (Robo Groudon)",)),
    StoryTransition(0x53, 0x55, "Robo Groudon defeated", passthrough=(0x54,)),
    StoryTransition(0x55, 0x56, "Kaminko's downstairs opened"),
    StoryTransition(0x56, 0x57, "talked to Makan -- forced back to Gateon"),
    StoryTransition(0x57, 0x5A, "scooter upgraded in Gateon -- the real SS Libra visit",
                    opens_regions=("SS Libra",), passthrough=(0x58,)),
    StoryTransition(0x5A, 0x5B, "first fight on the SS Libra"),
    StoryTransition(0x5B, 0x5D, "Snag Machine stolen -- Cipher Key Lair reachable, mail to Pyrite (visit 3)",
                    opens_regions=("Cipher Key Lair (exterior)",), passthrough=(0x5C,),
                    note="Zook defeats Biden here, which is why Biden 1 and 2 are both missable"),
    StoryTransition(0x5D, 0x5F, "talked to SECC -- Outskirt Stand reachable, Miror B battle",
                    opens_regions=("Outskirt Stand",), passthrough=(0x5E,)),
    StoryTransition(0x5F, 0x60, "Miror B defeated"),
    StoryTransition(0x60, 0x61, "talked to Hordel"),
    # 0x62, not the 0x63 of ADDENDUM 324: Snagem 2F's `hero_main` is `if storyvar(964) == 790`, and 790 is 0x62.
    # 0x63's window 792..799 holds no multiple of ten, so the game can never rest there (ADDENDUM 350).
    StoryTransition(0x61, 0x62, "Snagem Hideout reachable", opens_regions=("Snagem Hideout",)),
    StoryTransition(0x62, 0x64, "Gonzap defeated -- Gonzap's Key and the Snag Machine back",
                    opens_regions=("Cipher Key Lair",), passthrough=(0x63,),
                    note="Gonzap's Key is left vanilla: it opens a container outside the treasure table"),
    StoryTransition(0x64, 0x65, "Zook defeated at the Key Lair after Snagem"),
    StoryTransition(0x65, 0x67, "Snagem puts the grunts to sleep", passthrough=(0x66,)),
    StoryTransition(0x67, 0x69, "entered the Cipher Key Lair", passthrough=(0x68,)),
    StoryTransition(0x69, 0x6A, "System Lever used in the Key Lair", requires=("System Lever",),
                    opens_regions=("Cipher Key Lair (deep)",)),
    StoryTransition(0x6A, 0x6B, "Gorigan defeated"),
    StoryTransition(0x6B, 0x6C, "leaving the Key Lair"),
    StoryTransition(0x6C, 0x6E, "Robo Kyogre unlocked, Gateon shop restocked, Master Ball chest open",
                    opens_regions=("Citadark Isle",), passthrough=(0x6D,)),
)

# Regions that are open from the start, so they have no opening TRANSITION. They do have a floor -- see below.
ALWAYS_OPEN_REGIONS: "frozenset[str]" = frozenset({
    "Pokemon HQ Lab",
    "Kaminko's House",
    "Gateon Port",
})

# ADDENDUM 279/379: the always-open areas have first-visit bytes too, and these are the player's own numbers.
# Without them `region_floor` returned None, the hover wrote nothing, and the player walked in carrying another
# area's byte -- which `observe()` then banked as this area's mark. Own table, not folded into `_build_windows`,
# since these have a measured floor and no measured ceiling. The lab's 0x00 is a value, not an absence: every
# consumer tests `is None`, so a future `if floor:` would restore the bug for the lab alone. Gateon's 0x10 is NOT
# `ram_client.GATEON_STORY_CEILING` (0x6E, the Robo Kyogre gate), which stays put -- 0x6E is Citadark Isle's whole
# window, so raising that clamp would hand the Kyogre unlock to a player with no Parts.
ALWAYS_OPEN_FIRST_VISIT: "dict[str, int]" = {
    "Pokemon HQ Lab": 0x00,
    "Kaminko's House": 0x03,
    "Gateon Port": 0x10,   # ADDENDUM 379 -- was 0x0F
}

assert set(ALWAYS_OPEN_FIRST_VISIT) == ALWAYS_OPEN_REGIONS, (
    "every always-open region needs a first-visit byte, or it inherits whatever the player walks in with"
)


@dataclass(frozen=True)
class StoryWindow:
    """The byte range during which a region's own first-visit content is live."""

    floor: int
    ceiling: int
    opened_by: str = ""

    def contains(self, value: int) -> bool:
        return self.floor <= value <= self.ceiling


# `_build_windows` derives each ceiling as "the next region's opening byte minus one", which is wrong where the
# successor's opening byte is earned INSIDE the region. Named overrides rather than widening the rule globally,
# which would move twelve windows to fix one. A ceiling only decides which bytes this module treats as
# BELONGING to an area (`observe()`'s mark banking, ADDENDUM 365's poison guard); it is not what the client
# writes on arrival, so the paired AREA_FLOOR_RULES entry is what actually puts a revisit there.
REGION_CEILING_OVERRIDES: "dict[str, int]" = {
    # ADDENDUM 377. Derived was 0x19..0x23. But 0x23 ("first Shadow purified") is earned at Agate's own Relic
    # Stone and 0x24 is the errand it hands you, so the village is still Agate's at 0x24 -- and 0x24 is the
    # byte past Eagun, whose cutscene was replaying on a revisit.
    "Agate Village": 0x24,
    # ADDENDUM 379. Derived was 0x3E..0x40, one rung BELOW the 0x41 this client writes on every Phenac arrival
    # (`AREA_ENTRY_FLOOR_OVERRIDES`), so `observe()` could not bank our own arrival state as Phenac's. 0x40 is
    # also not a byte the game rests on at all -- the ladder runs 0x3E -> 0x3F -> 0x41.
    "Phenac City": 0x41,
    # ADDENDUM 391, all four at the player's instruction. Every one of these regions earns its successor's
    # opening byte WHILE THE PLAYER IS STILL STANDING IN IT, which is the exact case the note above says the
    # derived rule ("the next region's opening byte minus one") gets wrong.
    #
    # Derived was 0x3C..0x3D. 0x3E opens Phenac, and it is earned at the ONBS broadcast -- so the player is in
    # Pyrite when it lands. Player: "Pyrite cap should be 0x3E for ONBS visit."
    "Pyrite Town (ONBS)": 0x3E,
    # Derived was 0x46..0x4D. The player asked for 0x4F; ADDENDUM 350's fence refuses it, because no transition
    # lands on 0x4F -- the ladder runs 0x4E then 0x50. 0x4E is the adjacent reachable byte and the one that
    # matches the other three here: it is SS Libra (stranded)'s own opening value, and the Mayor hands over the
    # EXP Share that earns it while the player is standing in Phenac. 0x50 was the other candidate and is one
    # rung further than anything else in this table reaches.
    "Phenac City (Post-Sixes)": 0x4E,
    # Derived was 0x5F..0x61. 0x62 is SNAGEM_BASE_FLOOR -- the Snag Machine is stolen at the Outskirt Stand, so
    # the byte that opens the hideout is earned standing in the bar.
    "Outskirt Stand": 0x62,
    # Derived was 0x62..0x63. 0x64 opens the Cipher Key Lair, and it is earned on beating Gonzap inside the
    # hideout.
    "Snagem Hideout": 0x64,
}


def _build_windows() -> "dict[str, StoryWindow]":
    """FLOOR is the value the opening transition lands on. CEILING is the next region's opening value minus
    one, except where `REGION_CEILING_OVERRIDES` says otherwise. The last region's ceiling is the highest
    value in the table."""
    opening = [(t.after, region, t.what) for t in TRANSITIONS for region in t.opens_regions]
    opening.sort(key=lambda row: row[0])
    floors = sorted({row[0] for row in opening})
    highest = max(t.after for t in TRANSITIONS)
    windows: "dict[str, StoryWindow]" = {}
    for floor, region, what in opening:
        later = [f for f in floors if f > floor]
        ceiling = (later[0] - 1) if later else highest
        override = REGION_CEILING_OVERRIDES.get(region)
        if override is not None:
            ceiling = override
        windows[region] = StoryWindow(floor=floor, ceiling=ceiling, opened_by=what)
    return windows


REGION_STORY_WINDOW: "dict[str, StoryWindow]" = _build_windows()

# Every region named anywhere in this module, for cross-checking against regions.py.
REGIONS_WITH_A_STORY_WINDOW: "frozenset[str]" = frozenset(REGION_STORY_WINDOW)
ALL_KNOWN_REGIONS: "frozenset[str]" = ALWAYS_OPEN_REGIONS | REGIONS_WITH_A_STORY_WINDOW

# Derived from the `0x61 -> 0x62` transition, so this is a FENCE: regions.py routes the Key Lair chain around
# the SS Libra on the strength of a travel-shuffled player being written into the hideout at its own first-visit
# byte, so an edit moving that byte is a silent unwinnable seed. Asserted further down.
SNAGEM_BASE_FLOOR: int = 0x62   # ADDENDUM 350 (0x63 from ADDENDUM 324, retracted -- see the transition)


# ADDENDUM 332 wanted two rungs, 0x63 to load the hideout and 0x62 for the grunts' `== 790` fights -- an
# artefact of byte-only writes leaving the variable's low three bits alone, so "0x63" meant 792..799 and "0x62"
# meant 784..791. With all twelve bits written 0x62 is exactly 790 and does both jobs, so
# `SNAGEM_BATTLE_DROP_NEEDED` is False; the machinery stays in case the two ever genuinely separate again. The
# exempt fights derive from the deck's index order, which IS story order. Location shuffle only.
SNAGEM_BATTLE_FLOOR: int = 0x62


def snagem_battle_exempt_surnames() -> "frozenset[str]":
    """The two fights that keep `SNAGEM_BASE_FLOOR` -- Gonzap and the trainer immediately before him in the
    deck's own story order. Upper-case, because that is how the live battle roster reports NPC names."""
    from .trainer_placements import PLACEMENTS
    from .trainer_roster import TRAINERS

    names = {entry["index"]: str(entry["name"]).upper() for entry in TRAINERS}
    order = sorted(index for index, place in PLACEMENTS.items() if place.region == "Snagem Hideout")
    return frozenset(names[index] for index in order[-2:] if index in names)


SNAGEM_BATTLE_EXEMPT_SURNAMES: "frozenset[str]" = snagem_battle_exempt_surnames()

# Derived rather than hardcoded False: moving either constant brings the whole hold back without re-deriving it.
SNAGEM_BATTLE_DROP_NEEDED: bool = SNAGEM_BATTLE_FLOOR < SNAGEM_BASE_FLOOR

assert SNAGEM_BATTLE_FLOOR <= SNAGEM_BASE_FLOOR, (
    "the battle drop must not be ABOVE the hideout's entry floor -- a 'drop' that raises is not one"
)
assert "GONZAP" in SNAGEM_BATTLE_EXEMPT_SURNAMES, (
    "the last Snagem Hideout placement is no longer Gonzap, so 'Gonzap or the trainer right before him' no "
    "longer means what this derivation computes -- rule on it rather than letting it exempt another fight"
)
assert len(SNAGEM_BATTLE_EXEMPT_SURNAMES) == 2, (
    "exactly two fights are exempt: Gonzap and the one before him"
)


# Second-visit floors (ADDENDUM 184) -- what a static window cannot express. A window belongs to one region,
# which is the wrong model for the mid-game loop: the story bounces the player between Gateon, Kaminko's and the
# SS Libra, each return expects a different byte, and the first two have no window at all. So a floor here is
# conditional on what OTHER areas have reached. Read only with randomize_travel_locations on
# (ram_client.AreaStoryByteMemory), and a rule can only ever RAISE a floor, since `target_for` takes the max.

# A map destination is one PLACE to the player and several regions to the graph. A rule condition names the
# place, and any of its regions having reached the byte counts -- without this, "Phenac has reached 0x4E" would
# never fire, since 0x4E is earned in the Post-Sixes tier rather than the region the icon points at.
AREA_GROUPS: "dict[str, tuple[str, ...]]" = {
    "Gateon Port": ("Gateon Port",),
    "Kaminko's House": ("Kaminko's House", "Kaminko's House (Robo Groudon)"),
    "Phenac City": ("Phenac City", "Phenac City (Mayor's House)", "Phenac City (Post-Sixes)"),
    "SS Libra": ("SS Libra (stranded)", "SS Libra"),
    "Cipher Key Lair": ("Cipher Key Lair (exterior)", "Cipher Key Lair", "Cipher Key Lair (deep)"),
    "Snagem Hideout": ("Snagem Hideout",),
    "Realgam Tower": ("Realgam Tower",),
    # One group for all three spots: map_destinations resolves Rock, Oasis and Cave to the single "Poke Spots"
    # region. Declared rather than left to `highest_in_area`'s unknown-name fallback -- identical today, but
    # ADDENDUM 184's fence requires every rule's `requires` to name a real group.
    "Poke Spots": ("Poke Spots",),
    # One region, declared for the same reason -- a fallthrough would stop working the day the lab grows a tier.

    "Pokemon HQ Lab": ("Pokemon HQ Lab",),
    "Pyrite Town": ("Pyrite Town", "Pyrite Town (ONBS)"),
    "Agate Village": ("Agate Village", "Relic Forest"),
    # ADDENDUM 334: the lab was the one map destination with no group, so no rule could name it as a CONDITION.
    "Cipher Lab": ("Cipher Lab",),
}


# TRANSITIONS begins at 0x10, where the player's `!story` compilation begins, so ADDENDUM 184's fence has nothing
# to check below it and would reject the three HQ Lab rules. Allowlisted rather than invented into TRANSITIONS,
# one value at a time so the fence keeps its teeth -- a typo'd 0x0C still fails.
EARLY_FLOORS_NOT_YET_IN_TRANSITIONS: "frozenset[int]" = frozenset({
    0x07,   # player, 2026-09-14: "If Kaminko reaches 0x07 ... set HQ lab to 0x07"
    0x0D,   # player, same: the lab's own pass-through value
    0x0E,   # player, 2026-09-19: "instead of hq lab going from 0x0D to 0x0F, make it go to 0x0E"
    0x0F,   # player, 2026-09-14: the original pass-through target, still the Snag Machine tier
})

# The lowest value TRANSITIONS covers. Anything below this is outside the recorded ladder entirely.
LOWEST_RECORDED_STORY_BYTE: int = min(t.before for t in TRANSITIONS)


def floor_is_accounted_for(value: int) -> bool:
    """True when `value` is either a byte some transition lands on, or an explicitly listed early value.

    ADDENDUM 184's fence, expressed as data so the test and the table cannot drift apart."""
    reachable = {t.after for t in TRANSITIONS} | {t.before for t in TRANSITIONS}
    reachable |= {v for t in TRANSITIONS for v in t.passthrough}
    return value in reachable or value in EARLY_FLOORS_NOT_YET_IN_TRANSITIONS


@dataclass(frozen=True)
class AreaFloorRule:
    """`target`'s floor becomes `floor` once every (area, byte) in `requires` has been reached.

    `target` is a region name -- whichever region the map destination resolves to (game_data/map_destinations).
    `requires` names AREA_GROUPS keys, not regions, for the reason above.
    """

    target: str
    floor: int
    requires: "tuple[tuple[str, int], ...]"
    what: str


# Rules deliberately gone, each because the ADDENDUM 247 fence below refuses a floor that is not above the
# area's entry floor: Phenac City 0x41 and Cipher Key Lair 0x64/0x67 are `AREA_ENTRY_FLOOR_OVERRIDES` values now
# (ADDENDUM 331, and ADDENDA 324/371 -- player, verbatim: "And make Cipher Key Lab's floor 0x64."), and SS Libra
# 0x5A became the Scooter item (ADDENDUM 273), which no rule here can ask for. A condition nobody can trigger
# reads as a guarantee.
AREA_FLOOR_RULES: "tuple[AreaFloorRule, ...]" = (
    # ADDENDUM 334/350. Keyed on the lab's own mark at 0x28, the byte `brother_enter` writes -- and our writes are
    # never banked as a mark (ADDENDUM 277), so a mark there means the first visit really happened.
    AreaFloorRule("Cipher Lab", 0x28,
                  (("Cipher Lab", 0x28),),
                  "the arrival is behind them -- a return trip is to the lab itself"),
    # 0x30 first visit, 0x35 Data ROM handed over IN Pyrite, 0x3A Cave spot, 0x3C Miror B beaten and visit 2 opens;
    # without this the map rebuilds the opening town. "Poke Spots" because all three spots share one region -- not
    # a weakening, since 0x3B cannot be reached before 0x3A, which IS the Cave spot unlock.
    AreaFloorRule("Pyrite Town", 0x3C,
                  (("Pyrite Town", 0x35), ("Poke Spots", 0x3B)),
                  "Data ROM handed over in Pyrite and Miror B dealt with at the spots -- Pyrite visit 2"),
    # ADDENDUM 377, the other half of the ceiling override -- raising the ceiling makes 0x24 acceptable as Agate's
    # but nothing then WRITES it, so revisits still replayed the Eagun cutscene. Condition is Agate's own mark at
    # 0x23, "first Shadow purified", earned at its Relic Stone. 0x24 is the first byte past Eagun and no higher.
    AreaFloorRule("Agate Village", 0x24,
                  (("Agate Village", 0x23),),
                  "first Shadow purified at Agate's Relic Stone -- a return trip is past Eagun"),
    # ADDENDUM 212's three early-game HQ Lab floors. 0x07, 0x0D, 0x0F, 0x16 and 0x17 are known only from the
    # player's instructions, since the ladder starts at 0x10, so this table is the only place they exist -- extend
    # TRANSITIONS if the early ladder is ever recorded, never reconcile by deleting them.
    AreaFloorRule("Pokemon HQ Lab", 0x07,
                  (("Kaminko's House", 0x07),),
                  "Kaminko's opening visit has happened -- the lab is no longer at its cold-open value"),
    # The one rule whose condition names its own target -- a SKIP, not a dependency: the lab passes through 0x0D
    # and a return trip belongs at 0x0F (ADDENDUM 304; 0x0E briefly, from 288). Moves with the paired live bump's
    # target, always: a floor below it pushes a returning player back through the tier the bump exists to skip.
    AreaFloorRule("Pokemon HQ Lab", 0x0F,
                  (("Pokemon HQ Lab", 0x0D),),
                  "the lab's own 0x0D is a pass-through -- a return visit belongs at 0x0F"),
    # 0x16 is the Machine Part from the Gateon parts shop, 0x17 the Krane Memo 3-5 handover. The lab's own 0x0F
    # condition (ADDENDUM 227) makes this a STEP, 0x07 -> 0x0F -> 0x17, rather than a jump in from outside.
    AreaFloorRule("Pokemon HQ Lab", 0x17,
                  (("Gateon Port", 0x16), ("Pokemon HQ Lab", 0x0F)),
                  # 0x0F IS the Snag Machine tier (ram_client.STORY_BYTE_LANDMARKS). Toothless until ADDENDUM
                  # 277 made the live bump's write ineligible as the lab's mark -- before that the bump handed
                  # the lab 0x0F on arrival, so the rule reduced to "Gateon reached 0x16".
                  "Machine Part obtained in Gateon AND the lab past the Snag Machine (0x0F) -- "
                  "Krane Memo 3-5 tier"),

    # Phenac is finished (0x4C -> 0x4E opened the stranded SS Libra) and the scooter exists, so returning to
    # Gateon is the Nett/Perr errand rather than the opening visit.
    AreaFloorRule("Gateon Port", 0x51,
                  (("Gateon Port", 0x16), ("Phenac City", 0x4E)),
                  "talked to Nett -- Gateon's second visit is the Perr errand, not the parts shop"),
    # 0x52 is "talked to Perr", so the manor's next visit is the Verich tier. 0x53, not the 0x54 of ADDENDUM 338
    # (retracted by 350): 0x54's window 672..679 holds no multiple of ten, so it never named a state. It only
    # changed the failure mode of a byte-only write, where "0x53" meant 664..671 and sometimes fell below 670, the
    # rung the Verich visit opens at; with twelve bits written 0x53 is exactly 670. Not 0x55 either, which is 680,
    # "Robo Groudon defeated", so it would skip the fight.
    AreaFloorRule("Kaminko's House", 0x53,
                  (("Gateon Port", 0x52), ("Pokemon HQ Lab", 0x0F)),
                  # ADDENDUM 277 added the lab rung: Gateon 0x52 alone is a SINGLE witness, and a Gateon mark
                  # is exactly what the pre-277 bug could fabricate. Cheap -- any late-game lab visit records a
                  # byte far above 0x0F, and no floor means no write.
                  "Perr sends the player to Kaminko's -- the manor's mid-game tier"),
    # 0x56 is "talked to Makan -- forced back to Gateon", so Gateon is entered at 0x57 and left at 0x5A once the
    # scooter is upgraded. Only the entry value is a floor; 0x5A arrives on its own and is caught by the area's
    # remembered high-water mark.
    AreaFloorRule("Gateon Port", 0x57,
                  (("Kaminko's House", 0x56),),
                  "Makan forces the player back to Gateon for the scooter upgrade"),
    # ADDENDUM 293, the paired half of the SS Libra live bump: that one is "on the ship as the byte ticks to 0x5B",
    # this one is coming back later. Without it the mark 0x5B is the entry value and the bump fires again on every
    # arrival, so the game rebuilds the deck at 0x5B and we overwrite it a tick later. Still capped without the
    # Scooter, because `_cap_ss_libra` runs on the RESULT.
    AreaFloorRule("SS Libra", 0x5D,
                  (("SS Libra", 0x5B),),
                  "the ship's own 0x5B is a pass-through now -- a return visit belongs at 0x5D"),
)


# Live in-area bumps (ADDENDUM 213) -- the one write the map hook cannot do, since every other story-byte write
# here lands on the map screen before a room loads. Safe because a bump only fires INSIDE its own region, so the
# room the player stands in is the room the value describes, and `when_byte_is <= live < becomes` keeps it
# monotonic. A RANGE and not an equality because the poll runs about once a second and an exact test can miss the
# value. Bumps do not replace the paired AREA_FLOOR_RULES entries -- the bump is "I am here and the byte just
# ticked over", the floor is "I am arriving later". ADDENDUM 293 made the seed gate data, and `live_bump_for`
# REQUIRES the options: a caller that forgets is a wrong write to save data.


@dataclass(frozen=True)
class OptionGate:
    """Which seeds a bump is live in.

    `vanilla_needs_scooter_shuffle` narrows the vanilla-travel case to seeds that also shuffle the Scooter
    Upgrade, and applies ONLY to that case -- "no matter what on location shuffle, but only with scooter
    shuffle in vanilla"."""

    with_travel_shuffle: bool = True
    with_vanilla_travel: bool = False
    vanilla_needs_scooter_shuffle: bool = False

    def allows(self, travel_shuffle: bool, scooter_shuffle: bool) -> bool:
        if travel_shuffle:
            return self.with_travel_shuffle
        if not self.with_vanilla_travel:
            return False
        return scooter_shuffle or not self.vanilla_needs_scooter_shuffle


#: What every bump in this table did before ADDENDUM 293, written down rather than left implicit.
TRAVEL_SHUFFLE_ONLY = OptionGate(with_travel_shuffle=True, with_vanilla_travel=False)

#: The player's ADDENDUM 293 sentence, as data.
ALWAYS_SHUFFLED_SCOOTER_ONLY_IN_VANILLA = OptionGate(
    with_travel_shuffle=True, with_vanilla_travel=True, vanilla_needs_scooter_shuffle=True,
)


@dataclass(frozen=True)
class LiveStoryByteBump:
    """Raise the live story byte while the player is standing inside `region`.

    Fires when `when_byte_is <= live < becomes`, and only in the seeds `gate` allows. See the section comment
    for why the window is a range, and the ADDENDUM 293 comment for why the gate is data."""

    region: str
    when_byte_is: int
    becomes: int
    what: str
    gate: "OptionGate" = TRAVEL_SHUFFLE_ONLY
    #: ADDENDUM 304. Location names to send the moment this bump fires -- a skipped tier's checks never fire by
    # the ordinary route, and the HQ Lab's two Krane Memo locations gate the whole region graph. Plain strings,
    # not a `locations` import, because `ram_client` reads this table and cannot load anything with Archipelago
    # dependencies; `test_addendum_304` pins them against the real `krane_memo_location_name`.
    awards_locations: "tuple[str, ...]" = ()

    def applies(self, region: str, live: int) -> bool:
        return region == self.region and self.when_byte_is <= live < self.becomes


LIVE_STORY_BYTE_BUMPS: "tuple[LiveStoryByteBump, ...]" = (
    # ADDENDUM 304. The memo handover sits at 0x10 (`KRANE_MEMO_STORY_THRESHOLDS`), judged against this area's
    # mark, which is never our own write -- so a skipped player reaches it without the mark witnessing it, and the
    # memos gate every region past Phenac City. `awards_locations` sends them at the instant of the skip.
    LiveStoryByteBump("Pokemon HQ Lab", 0x0D, 0x0F,
                      "the lab's 0x0D is a pass-through -- bumped to 0x0F on the spot (player, ADDENDUM 304)",
                      awards_locations=("Story - Krane Memo 1", "Story - Krane Memo 2"),
                      gate=TRAVEL_SHUFFLE_ONLY),
    # ADDENDUM 293. 0x5B exists only to be climbed on the deck; 0x5D is the Snag Machine theft that
    # `opens_regions=("Cipher Key Lair (exterior)",)` hangs off, and the ladder then runs 0x5F -> 0x62 without
    # touching the ship again. Skipping 0x5B makes the ship a place holding its own checks. Vanilla travel gates
    # it on the Scooter being shuffled -- the only vanilla case where reaching the ship is an AP question.
    LiveStoryByteBump("SS Libra", 0x5B, 0x5D,
                      "the ship's 0x5B goes straight to the Snag-Machine byte -- Snagem and the Key Lair stop "
                      "hanging off the SS Libra (player, ADDENDUM 293)",
                      gate=ALWAYS_SHUFFLED_SCOOTER_ONLY_IN_VANILLA),
    # ADDENDA 294/331. At 0x3F Phenac is in lockdown -- items, trainers and shops shut until Realgam is seen,
    # which with travel shuffled can be a long wait. The window starts at 0x3E, not 0x3F, which is why ADDENDUM
    # 294's version never fired: the icon enters at 0x3E, and 0x3F is only reached by the first-visit beat that
    # ENDS by forcing the player out. Starting at 0x3E skips that scripted visit, the player's own call. 0x41
    # grants no access it should not, since `enforce_travel_locks` holds unreceived map bits clear every tick.
    #
    # ADDENDUM 350 deleted the Cipher Lab's 0x25 -> 0x26 bump: its arrival scene fires on storyvar 310, which IS
    # 0x26, so the icon can now drop the player there directly. The bump had only worked by luck -- a byte-only
    # write made "0x26" mean 304..311, and only a save whose low three bits were 6 landed on 310.
    LiveStoryByteBump("Phenac City", 0x3E, 0x41,
                      "Phenac's lockdown lifts the moment you land -- the town stops waiting on Realgam "
                      "(player, ADDENDA 294/331)",
                      gate=TRAVEL_SHUFFLE_ONLY),
)


def live_bump_for(region: "str | None", live: "int | None",
                  travel_shuffle: bool, scooter_shuffle: bool) -> "LiveStoryByteBump | None":
    """The bump that applies right now, or None. Never guesses: an unknown region or an unreadable byte is
    None, the same contract every other writer in this project holds.

    `travel_shuffle` and `scooter_shuffle` are the seed's own options and are REQUIRED, with no defaults -- a
    bump whose gate rejects the seed does not exist for that seed (ADDENDUM 293)."""
    if region is None or live is None:
        return None
    for bump in LIVE_STORY_BYTE_BUMPS:
        if not bump.gate.allows(travel_shuffle, scooter_shuffle):
            continue
        if bump.applies(region, live):
            return bump
    return None


# ADDENDUM 293: an area whose floor we stop writing once its first visit is behind it. Kaminko's is always-open at
# 0x03 and ADDENDUM 278 made an area's own mark a floor candidate, so the manor's target became "the highest byte
# ever recorded there" -- someone who wandered in at 0x19 got 0x19 on every hover afterwards. It has only ever
# been shown to care about 0x03, the front door, and 0x53, the Verich tier AREA_FLOOR_RULES already states.
#
# Above the pause byte there is no floor until a rule names one, and no floor means no write, so the player walks
# in carrying their own byte. A deliberate hole in ADDENDUM 278, whose lab had content at three rungs where the
# manor's mid-game has none. Keyed on the area GROUP, and armed by the MARK, so a visit where the story never
# advances leaves the pause unarmed.
FLOOR_WRITES_PAUSE_ABOVE: "dict[str, int]" = {
    "Kaminko's House": 0x03,
}


def floor_writes_are_paused(region_name: str, highest_by_region: "dict[str, int]") -> bool:
    """True when `region_name` should be offered NO floor at all right now.

    Two conditions, both required: the area's own mark has reached its pause byte, and no AREA_FLOOR_RULE
    currently names it. A satisfied rule is the "one of our gates that modifies it" the player asked to
    resume on, so a paused area un-pauses the same poll the rule's conditions are met."""
    for area, pause_at in FLOOR_WRITES_PAUSE_ABOVE.items():
        if region_name not in AREA_GROUPS.get(area, (area,)):
            continue
        reached = highest_in_area(area, highest_by_region)
        if reached is None or reached < pause_at:
            return False
        return dynamic_region_floor(region_name, highest_by_region) is None
    return False


def highest_in_area(area: str, highest_by_region: "dict[str, int]") -> "int | None":
    """The highest byte any region of `area` has reached, or None if none of them has been seen."""
    members = AREA_GROUPS.get(area, (area,))
    seen = [highest_by_region[name] for name in members if name in highest_by_region]
    return max(seen) if seen else None


def satisfied_area_floor_rules(highest_by_region: "dict[str, int]") -> "list[AreaFloorRule]":
    """Every rule whose conditions are all met by the marks recorded so far."""
    out: "list[AreaFloorRule]" = []
    for rule in AREA_FLOOR_RULES:
        ok = True
        for area, minimum in rule.requires:
            reached = highest_in_area(area, highest_by_region)
            if reached is None or reached < minimum:
                ok = False
                break
        if ok:
            out.append(rule)
    return out


def dynamic_region_floor(region_name: str, highest_by_region: "dict[str, int]") -> "int | None":
    """The highest floor any satisfied rule imposes on `region_name`, or None when no rule applies.

    None and 0 are different answers, so this returns None rather than a falsy default -- an area with no rule
    and no window has nothing honest to write, which is not the same as "write zero"."""
    floors = [rule.floor for rule in satisfied_area_floor_rules(highest_by_region)
              if rule.target == region_name]
    return max(floors) if floors else None


def transitions_requiring(item_name: str) -> "list[StoryTransition]":
    """Every transition the player's notes say needs `item_name`."""
    return [t for t in TRANSITIONS if item_name in t.requires]


def region_floor(region_name: str) -> "int | None":
    """The byte value `region_name`'s first visit expects, or None for an always-open region.

    This is the REGION's own floor, not the PLACE's. Anything keyed off a map destination -- which is every
    story-byte write -- wants `area_entry_floor` instead."""
    window = REGION_STORY_WINDOW.get(region_name)
    if window is not None:
        return window.floor
    # ADDENDUM 279: an always-open region has no opening transition, but it does have a first visit.
    return ALWAYS_OPEN_FIRST_VISIT.get(region_name)


# ADDENDUM 247: a map destination's floor is its AREA's first tier, not the tier its row happens to name. The SS
# Libra icon's region is "SS Libra" (floor 0x5A, the scooter-upgraded ship) while the stranded first visit is
# `SS Libra (stranded)` at 0x4E, so the first hover wrote 0x5A and skipped it; the Key Lair had the same shape,
# 0x64 against its exterior's 0x5D. `AREA_GROUPS` lists a place's regions in story order, so the entry floor is
# the first tier -- 15 of 17 destinations unchanged. `AREA_ENTRY_FLOOR_OVERRIDES` is the other case, an icon
# entering at a LATER tier; a per-area override rather than reordering AREA_GROUPS, which the chain edges use.
AREA_ENTRY_FLOOR_OVERRIDES: "dict[str, int]" = {
    # ADDENDUM 371, was 0x64 (ADDENDUM 324, player: "And make Cipher Key Lab's floor 0x64." -- their spelling,
    # left verbatim). 0x67 is the `before` of `0x67 -> 0x69`, so arriving there puts the
    # player at the doorway and walking in fires the transition -- three rungs above 0x64, so the Lair can never
    # ask for the Snagem chain. The cost: 0x65 is "Zook beaten at the Lair", so a first visit is staged past that
    # fight and `Defeat - Zook #2` (trainer 147) cannot be relied on. Already fenced into
    # `missable_trainers.FILLER_ONLY_TRAINER_INDICES` (ADDENDUM 188), like Biden #2 (148) beside him, and
    # `test_addendum_371` pins that raising this floor and un-fencing Zook cannot both be true.
    "Cipher Key Lair": 0x67,
    # ADDENDUM 331. The window floor 0x3E is the locked first visit, and the only thing that used to raise the
    # icon above it needed a `Realgam Tower` mark a travel-shuffle player may never earn. The UNLOCK floor stays
    # at 0x3E (`area_unlock_floor` does not read this table), so `Unlock - Phenac City` still credits at the byte
    # the unmodified game reveals the icon at.
    "Phenac City": 0x41,
    # ADDENDUM 350 removed the Cipher Lab's override: with the arrival's real value (storyvar 310 = 0x26) in the
    # ladder, the window floor IS where a first visit belongs, and an override equal to what it overrides is the
    # quiet no-op ADDENDUM 247's fence keeps out.
}


def area_entry_floor(region_name: str) -> "int | None":
    """The byte a MAP DESTINATION resolving to `region_name` should be entered at on a first visit.

    The floor of the first tier of the region's `AREA_GROUPS` place. None when that tier is always-open and has
    no window -- Gateon Port and Kaminko's House, where `AREA_FLOOR_RULES` is the only floor there is."""
    for area, members in AREA_GROUPS.items():
        if region_name in members:
            # ADDENDUM 324: the icon's own value wins over the area's first tier, when one is recorded.
            override = AREA_ENTRY_FLOOR_OVERRIDES.get(area)
            return override if override is not None else region_floor(members[0])
    override = AREA_ENTRY_FLOOR_OVERRIDES.get(region_name)
    return override if override is not None else region_floor(region_name)


def area_unlock_floor(region_name: str) -> "int | None":
    """The byte at which the GAME unlocks this destination's icon -- its area's FIRST tier, always.

    ADDENDUM 324 split this from `area_entry_floor`: that is the byte a room should be BUILT from when the icon
    takes you there, this is the byte at which the icon APPEARS in the unmodified game (the Key Lair's exterior,
    0x5D). Crediting `Unlock - Cipher Key Lair` at the entry floor would fire it twelve bytes late, so
    `AREA_ENTRY_FLOOR_OVERRIDES` is deliberately not consulted here."""
    for members in AREA_GROUPS.values():
        if region_name in members:
            return region_floor(members[0])
    return region_floor(region_name)


def lowest_floor_among(region_names: "set[str]") -> "int | None":
    """The safe value to write when a load is starting and the destination is not yet known -- the lowest floor
    across the regions still to be visited. Writing this is the recoverable direction: too early means content
    has not unlocked yet, where too late means it is skipped for good."""
    floors = [w.floor for name, w in REGION_STORY_WINDOW.items() if name in region_names]
    return min(floors) if floors else None


# Sanity fences. These are assertions rather than tests because a malformed table here would silently produce a
# wrong region graph, and the failure would surface as an unwinnable seed rather than an error.
assert all(t.after >= t.before for t in TRANSITIONS), "story byte transitions must never go backwards"
_opened = [region for t in TRANSITIONS for region in t.opens_regions]
assert len(set(_opened)) == len(_opened), (
    "two transitions claim to open the same region -- the window builder cannot resolve that"
)
assert all(b.becomes > b.when_byte_is for b in LIVE_STORY_BYTE_BUMPS), (
    "a live bump must raise the story byte -- one that lowered it would undo real progress"
)
assert all(b.region in ALL_KNOWN_REGIONS for b in LIVE_STORY_BYTE_BUMPS), (
    "a live bump names a region that does not exist, so it would silently never fire"
)
# ADDENDUM 293. Snagem's floor is what regions.py's rerouted Key Lair edge relies on -- see SNAGEM_BASE_FLOOR.
assert REGION_STORY_WINDOW["Snagem Hideout"].floor == SNAGEM_BASE_FLOOR, (
    f"Snagem Hideout's window floor is 0x{REGION_STORY_WINDOW['Snagem Hideout'].floor:02X}, not "
    f"0x{SNAGEM_BASE_FLOOR:02X} -- regions.py routes the Cipher Key Lair chain around the SS Libra on the "
    f"strength of a travel-shuffled player being written into the hideout at its own first-visit byte"
)
assert all(region in ALL_KNOWN_REGIONS for area in FLOOR_WRITES_PAUSE_ABOVE
           for region in AREA_GROUPS.get(area, (area,))), (
    "ADDENDUM 293: a paused area names a region that does not exist, so the pause would never apply"
)
assert not (ALWAYS_OPEN_REGIONS & REGIONS_WITH_A_STORY_WINDOW), (
    "a region cannot be both always-open and opened by a story transition"
)
# ADDENDUM 247. A rule whose floor is at or below the area's entry floor can never change any outcome, because
# `target_for` takes the max -- a condition the player wrote down, quietly doing nothing.
for _rule in AREA_FLOOR_RULES:
    _entry = area_entry_floor(_rule.target)
    assert _entry is None or _rule.floor > _entry, (
        f"AREA_FLOOR_RULES entry for {_rule.target} has floor 0x{_rule.floor:02X}, which is not above that "
        f"area's entry floor 0x{(_entry or 0):02X} -- the rule can never bind, so the condition it carries "
        f"({_rule.requires}) is silently ignored"
    )


# ADDENDUM 377: a ceiling override must RAISE a real region's derived ceiling and name a byte the ladder lands on.
# An override at or below the derived value is ADDENDUM 247's dead-condition shape; one naming an unreachable byte
# would widen the window over a rung the game never rests on. An empty table is refused for the same reason.
assert REGION_CEILING_OVERRIDES, (
    "REGION_CEILING_OVERRIDES is empty -- delete the table and the branch in `_build_windows` rather than "
    "shipping an override mechanism that overrides nothing"
)
for _region, _ceiling in REGION_CEILING_OVERRIDES.items():
    assert _region in REGION_STORY_WINDOW, (
        f"ceiling override names {_region!r}, which has no story window to widen"
    )
    assert REGION_STORY_WINDOW[_region].ceiling == _ceiling, (
        f"ceiling override for {_region} did not take effect -- _build_windows is not reading the table"
    )
    assert _ceiling > REGION_STORY_WINDOW[_region].floor, (
        f"ceiling override for {_region} is not above its own floor"
    )
    _derived = sorted({t.after for t in TRANSITIONS for _r in t.opens_regions
                       if t.after > REGION_STORY_WINDOW[_region].floor})
    assert _derived and _ceiling > _derived[0] - 1, (
        f"ceiling override for {_region} is 0x{_ceiling:02X}, which is not above the derived ceiling "
        f"0x{_derived[0] - 1:02X} -- an override that widens nothing reads as one that does"
    )
del _region, _ceiling, _derived    # safe: the table is asserted non-empty directly above


# ADDENDUM 324: an override must name a real area and a byte the ladder accounts for -- the same fence every
# other floor in this module passes. A typo here would silently write the wrong rung on every visit.
assert all(area in AREA_GROUPS or area in ALL_KNOWN_REGIONS for area in AREA_ENTRY_FLOOR_OVERRIDES), (
    "an entry-floor override names an area that does not exist"
)
assert all(floor_is_accounted_for(value) for value in AREA_ENTRY_FLOOR_OVERRIDES.values()), (
    "an entry-floor override names a byte no transition lands on"
)


# ADDENDUM 350: the story byte is the top 8 bits of a 12-bit variable, and the variable counts in tens.
#
# Field scripts call builtin 0x85 with argument 964 -- GS variable 964, not a byte. GSflagGet (main.dol GXXE01
# 0x801A0364) and its worker (0x801A03E8) disassemble to:
#
#     word  = bitpos >> 5 ;  off = bitpos & 0x1F
#     lo    = u32(storage + word*4) ;  hi = u32(storage + word*4 + 4)
#     value = ((hi << (32 - off)) | (lo >> off)) & mask(width)
#
# Variable 964 has width 12, storage group 24 and bitpos 917. Group 24's storage is BLOCK_BASE + 0x106B0, and
# STORY_RECORD_OFFSET is 0x10720 -- the story record begins 0x70 bytes into that group, at bit 896. So:
#
#     var964 = (u16_be(record + 0x00) >> 5) & 0xFFF
#            = (story_byte << 3) | (record[0x01] >> 5)
#
# The byte this project writes is bits 3..10 of the variable. The low 3 bits live in the top of record + 0x01 and
# were never written, so every write left the variable at `byte * 8 + whatever was already there`.
#
# THE TENS RULE, measured: across all 163 full MEM1 dumps in the corpus every naturally-saved var964 is a multiple
# of ten (0x02 -> 20, 0x0A -> 80, 0x15 -> 170, 0x25 -> 300, 0x28 -> 320, 0x2B -> 350, 0x41 -> 520); the only
# exceptions are this project's own writes (snagbase.bin at 794, the eight 0xFF checkpoint-12 dumps at 2047).
# Independently, the vanilla Snagem 2F script (S2_building_2F_2.fsys, LZSS-decoded from the ISO) compares var964
# against 790, 800, 810, 840, 870 and 970 across 48 call sites and nothing else. So the byte is
# `floor(step * 10 / 8)`, a lossy view: one whose window [8b, 8b+7] holds no multiple of ten is a value the game
# can NEVER hold, and a script gated on it can never fire. Two chosen floors were exactly that -- 0x63 (Snagem,
# ADDENDUM 324; Snagem 2F's `hero_main` is `== 790`, which is 0x62) and 0x27 (Cipher Lab, ADDENDUM 314; 312..319
# holds none). It also explains the docstring's intermediates: 0x45, 0x54, 0x5E, 0x68 and 0x6D are precisely the
# unreachable bytes in this ladder's range, never story states.
#
# Callers keep using bytes -- what the tables, the tracker and the player's notes are written in -- but a WRITE
# must set the whole variable, via `story_value_for_byte` and ram_client's `poke_story_value`.

STORY_VARIABLE_ID = 964          # what field scripts pass to builtin 0x85
STORY_VARIABLE_WIDTH = 12
STORY_VARIABLE_STEP = 10         # every value the game holds is a multiple of this
STORY_VARIABLE_SHIFT = 3         # byte = value >> 3


def story_value_for_byte(story_byte: int) -> "int | None":
    """The story-variable value a given story byte stands for, or None if the byte is unreachable.

    A byte `b` covers values `8b .. 8b+7`, and since the variable only holds multiples of ten at most one of
    them is real -- for roughly one byte in five, none is. None rather than a nearest fit on purpose: a caller
    that silently rounded would reintroduce the failure this addendum found."""
    low = story_byte * (1 << STORY_VARIABLE_SHIFT)
    candidate = ((low + STORY_VARIABLE_STEP - 1) // STORY_VARIABLE_STEP) * STORY_VARIABLE_STEP
    if candidate > low + (1 << STORY_VARIABLE_SHIFT) - 1:
        return None
    return candidate


def story_byte_for_value(value: int) -> int:
    """The story byte a variable value presents as -- the lossy direction, and always defined."""
    return value >> STORY_VARIABLE_SHIFT


def byte_is_reachable(story_byte: int) -> bool:
    """True when the game can actually hold this byte. See `story_value_for_byte`."""
    return story_value_for_byte(story_byte) is not None


UNREACHABLE_BYTES_IN_LADDER: "tuple[int, ...]" = tuple(sorted({
    value
    for transition in TRANSITIONS
    for value in (transition.before, transition.after, *transition.passthrough)
    if not byte_is_reachable(value)
}))


# Anything this module WRITES must be a byte with a story value behind it. A `passthrough` is exempt on purpose:
# those ARE the unreachable rungs, recorded as what the byte view seemed to step through, and nothing writes them.
for _region, _window in REGION_STORY_WINDOW.items():
    assert byte_is_reachable(_window.floor), (
        f"{_region}'s window floor 0x{_window.floor:02X} is a byte the game can never hold -- the story "
        f"variable only takes multiples of {STORY_VARIABLE_STEP}, and 0x{_window.floor:02X} covers "
        f"{_window.floor * 8}..{_window.floor * 8 + 7}, which contains none. Writing it puts the player on a "
        f"rung no script tests for (ADDENDUM 350)"
    )
for _area, _floor in AREA_ENTRY_FLOOR_OVERRIDES.items():
    assert byte_is_reachable(_floor), (
        f"{_area}'s entry-floor override 0x{_floor:02X} is an unreachable byte (ADDENDUM 350)"
    )
for _rule in AREA_FLOOR_RULES:
    assert byte_is_reachable(_rule.floor), (
        f"the {_rule.target} floor rule writes 0x{_rule.floor:02X}, an unreachable byte (ADDENDUM 350)"
    )

# The reachability half of the ceiling-override fence lives here because `byte_is_reachable` is only defined as
# of this section -- asserting it earlier is a NameError at import.
for _region, _ceiling in REGION_CEILING_OVERRIDES.items():
    assert byte_is_reachable(_ceiling), (
        f"ceiling override for {_region} names 0x{_ceiling:02X}, a byte no transition lands on (ADDENDUM 350)"
    )
del _region, _ceiling
for _bump in LIVE_STORY_BYTE_BUMPS:
    assert byte_is_reachable(_bump.becomes), (
        f"the {_bump.region} live bump writes 0x{_bump.becomes:02X}, an unreachable byte (ADDENDUM 350)"
    )


# ADDENDUM 365: a ceiling per area, so a foreign byte cannot settle in it. The failure was a save standing in the
# Cipher Lab reading 0x3C -- Pyrite's visit-2 floor -- with "was 0x28" beside it and nothing in the ladder going
# 0x28 -> 0x3C. Every number is DERIVED, never typed, or it becomes a second table to disagree with the ladder:
# the lab's comes out as 0x2F, one rung above the 0x2E the player quoted, and loose is the safe direction, since
# a ceiling too high misses some poisoning while one too low clamps real progress. Four things decide whether an
# area qualifies, all computed from existing tables:
#   1. The span is the whole PLACE, never one tier: `region_for_room` returns "Phenac City" for the town all game
#      while the ladder walks it 0x3E..0x4D, so a 0x4C mark is ordinary and a 0x41 ceiling would clamp it.
#   2. Widened by the area's own EXITS: the Cipher Lab hands off at 0x2F -> 0x30 and that write can land while the
#      player is still inside, so the lab's guard is 0x30, not 0x2F.
#   3. An area whose own floor machinery writes above that is DISQUALIFIED, not accommodated -- Pyrite writes 0x3C
#      against a window ending at 0x34, Citadark 0x71 against a 0x6E..0x6E window.
#   4. A place with an always-open member is disqualified: Kaminko's is reachable at any point, and its live name
#      is "Kaminko's House (Robo Groudon)", window 0x53-0x59, so a player walking in at 0x6C would be clamped
#      back twenty rungs.
#
# Five of eighteen fall out today. The fence below asserts the SHAPE, not the list, so a floor-rule change moves
# an area out by itself.
def _guard_span(live_region: str) -> "tuple[str, ...]":
    """The story regions a player standing in `live_region` could actually be in: its whole PLACE.

    Never the individually nameable tiers -- a per-tier window clamps ordinary marks, which the ADDENDA 177/331
    tests caught. Strictly the looser answer, the direction this guard errs in on purpose."""
    for place, members in AREA_GROUPS.items():
        if live_region in members:
            return tuple(members)
    return (live_region,)


def _build_area_guard_ceilings() -> "dict[str, int]":
    from . import chest_regions

    live_names = frozenset(
        name for name in (chest_regions.region_for_room(room) for room in range(1200)) if name
    )
    out: "dict[str, int]" = {}
    for live_region in sorted(live_names):
        span = _guard_span(live_region)
        windows = [REGION_STORY_WINDOW[m] for m in span if m in REGION_STORY_WINDOW]
        if not windows:
            continue                                        # always-open, no claim to make (point 4)
        if any(m in ALWAYS_OPEN_REGIONS for m in span):
            continue                                        # point 4
        low = min(w.floor for w in windows)
        high = max(w.ceiling for w in windows)
        exits = set()
        for transition in TRANSITIONS:                      # point 2
            if low <= transition.before <= high and transition.after > high:
                exits.add(transition.after)
                exits.update(transition.passthrough)
        ceiling = max([high] + sorted(exits))
        ours = [area_entry_floor(m) or 0 for m in span]
        ours += [rule.floor for rule in AREA_FLOOR_RULES if rule.target in span]
        ours += [bump.becomes for bump in LIVE_STORY_BYTE_BUMPS if bump.region in span]
        ours += [SPECIAL_AREA_WRITES[m] for m in span if m in SPECIAL_AREA_WRITES]
        if max(ours) > ceiling:                             # point 3
            continue
        out[live_region] = ceiling
    return out


#: Values written by a writer that lives in ram_client rather than in a table here. Named so `_build_area_
#: guard_ceilings` can disqualify their areas; the numbers are asserted against ram_client's own constants by
#: `test_addendum_365` so this cannot drift into a second source of truth.
SPECIAL_AREA_WRITES: "dict[str, int]" = {
    "Citadark Isle": 0x71,                    # ram_client.CITADARK_ENTRY_FLOOR
    "SS Libra": 0x5A,                         # ram_client.SS_LIBRA_SCOOTER_FLOOR
    "Gateon Port": 0x76,                      # ram_client.STORY_OVERRIDE_VALUE
    "Kaminko's House (Robo Groudon)": 0x57,   # ram_client.SCOOTER_HOLD_FLOOR
}

AREA_GUARD_CEILINGS: "dict[str, int]" = _build_area_guard_ceilings()
"""{live region name -> the highest byte that region can legitimately hold}. See the block above."""


# What makes a byte FOREIGN rather than merely high -- read this first. The mod holds the story byte at "what the
# room the player is standing in should be built from", not "how far they have got", so a high byte in a low area
# is NORMAL in cases the ladder cannot describe: walking between adjacent areas writes nothing, so someone who
# walks out of the Outskirt Stand into Snagem at 0x6C really is in Snagem at 0x6C. So the ceiling is the trigger,
# not the test -- the test is whether the value is one this client's own floor machinery could have written for
# some OTHER area. 0x3C in the Cipher Lab is Pyrite's rule floor and gets caught; 0x6C in Snagem is left alone.
# A poisoned byte that is nobody's floor therefore survives -- never observed, and clamping anything above a
# ceiling can end a run.
def _build_floor_values() -> "frozenset[int]":
    values = set(SPECIAL_AREA_WRITES.values())
    values.update(AREA_ENTRY_FLOOR_OVERRIDES.values())
    values.update(rule.floor for rule in AREA_FLOOR_RULES)
    values.update(bump.becomes for bump in LIVE_STORY_BYTE_BUMPS)
    for region in REGION_STORY_WINDOW:
        floor = area_entry_floor(region)
        if floor is not None:
            values.add(floor)
    return frozenset(values)


OUR_FLOOR_VALUES: "frozenset[int]" = _build_floor_values()
"""Every byte this client's own floor machinery can write. A value above an area's ceiling that is ALSO in
here is a floor left behind for somewhere else -- which is what "poisoned" means."""


def poisoned_byte(live_region: "str | None", story_byte: "int | None") -> bool:
    """True when `story_byte` cannot belong to `live_region` and is a floor this client writes elsewhere.

    Never guesses: an unknown region, an area with no guard ceiling and an unreadable byte are all False, the
    same contract every other decision in this module holds."""
    if live_region is None or story_byte is None:
        return False
    ceiling = AREA_GUARD_CEILINGS.get(live_region)
    if ceiling is None:
        return False
    return story_byte > ceiling and story_byte in OUR_FLOOR_VALUES


# Fences. The SHAPE is asserted, never the list -- an area must fall out of the table on its own when a floor
# rule moves, rather than leaving an entry here that no longer describes it.
assert AREA_GUARD_CEILINGS, "the area guard table came out empty -- the derivation is reading nothing"
for _region, _ceiling in AREA_GUARD_CEILINGS.items():
    assert _region in ALL_KNOWN_REGIONS, f"{_region} is not a region"
    assert _region not in ALWAYS_OPEN_REGIONS, (
        f"{_region} is always-open, so the byte while standing in it says nothing -- it must not carry a "
        "ceiling (ADDENDUM 365, point 4)"
    )
    _span = _guard_span(_region)
    _mine = [area_entry_floor(_m) or 0 for _m in _span]
    _mine += [_r.floor for _r in AREA_FLOOR_RULES if _r.target in _span]
    _mine += [_b.becomes for _b in LIVE_STORY_BYTE_BUMPS if _b.region in _span]
    _mine += [SPECIAL_AREA_WRITES[_m] for _m in _span if _m in SPECIAL_AREA_WRITES]
    assert max(_mine) <= _ceiling, (
        f"{_region}'s own floor machinery writes 0x{max(_mine):02X}, above its guard ceiling "
        f"0x{_ceiling:02X} -- the guard would fight this client's own write (ADDENDUM 365, point 3)"
    )
