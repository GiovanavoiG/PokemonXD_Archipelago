"""Which missable trainer checks the client sends on its own, and at what story byte.

ADDENDUM 402. Missable checks are treated as unreliable: once an area hits its story cap, every missable trainer
defeat in that area is received.

WHAT IS IN HERE. Every missable trainer check that still exists after ADDENDUM 401 removed the numbered fights of
the missable trainers that fight more than once:

  * the 26 ONE-SHOT missables (`Defeat - Digor`, `Defeat - Bost`, ...) -- a single fight, no number, nothing to
    fall back on. Released at the cap of the area their fight is placed in.
  * `Defeat X (Any)` for a surname EVERY one of whose fights is on the missable list. Today that is Biden alone:
    both of his fights are missable, so his (Any) can be missed outright. Released at the LATEST cap among his
    fights' areas -- an (Any) is only lost once the last chance at it has closed.

The other 19 (Any) checks of missable trainers are NOT here. Each of those surnames has a fight that is not on
the missable list, so the (Any) cannot be missed, and the (Any) is left as it is.

WHAT "THE CAP" IS. `story_bytes.REGION_STORY_WINDOW[area].ceiling` -- the same ceiling the area memory and the
poison guard use, overrides included, so a change to an area's cap moves its auto-send with it. One source.

ADDENDUM 405 -- AT THE CAP, AND ONLY IN THAT AREA. The checks are sent AT the story cap for each area, and only
when THAT AREA's floor reaches it. With travel randomization on every area keeps its own
story byte (`ram_client.AreaStoryByteMemory`), so a fight is gone only when ITS area moves past it -- Pyrite's
progress says nothing about the Cipher Lab. The client therefore compares each check against its own area's
progress (`AUTO_SEND_AREA_CAPS`, `story_bytes.area_progress`). With travel randomization off there is one byte
for every area and the comparison below is the right one.

THE BYTE IT IS COMPARED AGAINST (travel randomization off) is NOT the live story byte, which the client itself writes (a hover on the map
screen writes the destination's floor; the Robo Kyogre Parts override lifts Gateon to 0x6E). The client compares
against `StoryProgressWitness.high_water`, the highest byte the GAME put there. See `ram_client.MissableAutoSender`.

WHICH WAY IT FAILS. Early is harmless: these checks are all EXCLUDED, so an early send hands over one filler item
the player would have earned anyway. Late, or never, is the bug this exists to remove. Every judgement call below
leans early for that reason.
"""
from __future__ import annotations

# An area with no story window has no cap to read. One missable sits in one today: Bost, in Gateon Port, which is
# always open and so has no window at all. "The story cap for an area" does not define a cap for it, so this
# table does, and every entry here is a judgement call.
#
#   Bost -> 0x19, "Agate Village unlocked / first visit". That is the byte that ends the opening Gateon stretch,
#   and it is the EARLY choice on purpose: if Bost is actually fought on a later Gateon visit, he is auto-sent
#   before he appears -- one filler item early, harmless. Picking a later byte risks the opposite.
CAP_OVERRIDES: "dict[str, int]" = {
    "Defeat - Bost": 0x19,
}

# ADDENDUM 436. Missable Phenac trainers send upon defeating Snattle (ONLY Cipher members). Every
# missable fight in Phenac City's area (the town, the Mayor's House and Post-Sixes) whose trainer is a Cipher Peon is
# released at 0x48, "Snattle defeated" (0x47 -> 0x48) -- the six one-shots (Pellim, Fenton, Forgs, Kapen, Ezoor,
# Ertlig) and the Sixes' #2, which ADDENDUM 409 had released at 0x46. Judged like every other cap: the global byte
# with location shuffle off, Phenac's own progress with it on.
SNATTLE_DEFEATED = 0x48
CIPHER_PEON_CLASS = 17
PHENAC_AREA_REGIONS: "frozenset[str]" = frozenset({
    "Phenac City", "Phenac City (Mayor's House)", "Phenac City (Post-Sixes)",
})


def _build() -> "tuple[dict[str, int], dict[str, tuple[tuple[str, int], ...]]]":
    from . import missable_indices, repeatable_trainers, story_bytes, trainer_placements, trainer_roster

    windows = story_bytes.REGION_STORY_WINDOW
    schedule: "dict[str, int]" = {}
    by_area: "dict[str, tuple[tuple[str, int], ...]]" = {}
    unresolved: "list[str]" = []

    def region_for(index: int) -> "str | None":
        placement = trainer_placements.PLACEMENTS.get(index)
        return placement.region if placement is not None else None

    def cap_for(label: str, index: int) -> "int | None":
        if label in CAP_OVERRIDES:
            return CAP_OVERRIDES[label]
        region = region_for(index)
        trainer = trainer_roster.TRAINERS_BY_INDEX.get(index) or {}
        if region in PHENAC_AREA_REGIONS and trainer.get("trainer_class") == CIPHER_PEON_CLASS:
            return SNATTLE_DEFEATED            # ADDENDUM 436
        if index in missable_indices.PHENAC_INVASION_INDICES:
            return SNATTLE_DEFEATED            # ADDENDUM 440: "send them when Phenac is done"
        window = windows.get(region) if region is not None else None
        return window.ceiling if window is not None else None

    # The one-shots: their own label, their own area.
    for index in sorted(missable_indices.MISSABLE_TRAINER_INDICES):
        trainer = trainer_roster.TRAINERS_BY_INDEX.get(index)
        if trainer is None:
            continue
        label = trainer_roster.trainer_label(trainer)
        if label in trainer_roster.REMOVED_DEFEAT_LOCATIONS:
            continue                       # ADDENDUM 401 removed it; there is nothing left to send
        if label in trainer_roster.LINKED_MISSABLE_DEFEAT_LOCATIONS:
            continue                       # ADDENDUM 411: its mandatory partner sends it (none since ADDENDUM 436)
        if label in trainer_roster.RETIRED_UNIQUE_DEFEAT_LOCATIONS:
            continue
        cap = cap_for(label, index)
        if cap is None or region_for(index) is None:
            unresolved.append(label)
            continue
        schedule[label] = cap
        by_area[label] = ((region_for(index), cap),)

    # The fully-missable surnames' (Any): the latest cap among all of that surname's fights.
    for surname, rows in trainer_roster.TRAINERS_BY_NAME.items():
        indices = [row["index"] for row in rows]
        if len(indices) < 2 or not all(i in missable_indices.MISSABLE_TRAINER_INDICES
                                       and i not in missable_indices.WORKBOOK_MISSABLE_OVERRULED for i in indices):
            continue                       # ADDENDUM 436: Biden's Snagem fight cannot be missed
        any_name = repeatable_trainers.SURNAME_TO_LOCATION.get(surname.upper())
        if any_name is None:
            continue                       # no (Any) location for this surname, so nothing to send
        caps = [cap_for(trainer_roster.trainer_label(trainer_roster.TRAINERS_BY_INDEX[i]), i) for i in indices]
        if any(cap is None for cap in caps) or any(region_for(i) is None for i in indices):
            unresolved.append(any_name)
            continue
        schedule[any_name] = max(caps)
        # Per area, every fight waits on ITS OWN area: the (Any) is lost only once each of its chances has closed,
        # and each chance closes when the area it is in reaches that fight's cap.
        by_area[any_name] = tuple(sorted({(region_for(i), cap) for i, cap in zip(indices, caps)}))

    # Loud, not silent: a missable with no cap is exactly a check that can be lost forever.
    assert not unresolved, (
        f"missable check(s) with no story cap to release them at: {sorted(unresolved)} -- give each an area "
        "with a story window, or an entry in CAP_OVERRIDES"
    )
    for name, cap in schedule.items():
        assert story_bytes.byte_is_reachable(cap), (
            f"{name}'s release byte 0x{cap:02X} is one the game never rests on (ADDENDUM 350) -- it would never "
            "be reached, which is the failure this module exists to prevent"
        )
    assert set(by_area) == set(schedule), "every scheduled check needs its area requirement too"
    return schedule, by_area


AUTO_SEND_AT_STORY_BYTE, AUTO_SEND_AREA_CAPS = _build()

# ADDENDUM 438: checks a client-written entry floor can step over. The Key Lair is entered at 0x66 (820), one story
# step past `0x64 -> 0x65` "Zook defeated at the Key Lair after Snagem", and since ADDENDUM 436 that fight is Zook's
# only check. Released at 0x67 -- the first byte the GAME writes after an arrival at 0x66 ("Snagem puts the grunts to
# sleep"), so a byte this client wrote never counts -- judged on the Key Lair's own progress with location shuffle on,
# the global byte with it off (where the walk-in fights him first anyway). A filler check, so early costs nothing.
# ADDENDUM 439 put the floor back at 0x64, BELOW his rung, so the arrival no longer steps over the fight. Kept as a
# backstop: 0x67 is only reachable through `0x64 -> 0x65` (his fight) then `0x65 -> 0x67`, so it can never fire
# before he is beaten -- it only covers a win the defeat tracker failed to read.
FLOOR_SKIPPED_CHECKS: "dict[str, tuple[str, int]]" = {
    "Defeat Zook (Any)": ("Cipher Key Lair", 0x67),
}


def _add_floor_skipped() -> None:
    from . import story_bytes

    for name, (region, cap) in FLOOR_SKIPPED_CHECKS.items():
        assert story_bytes.byte_is_reachable(cap), f"{name}: 0x{cap:02X} is never rested on"
        assert cap > story_bytes.AREA_ENTRY_FLOOR_OVERRIDES.get(story_bytes.area_of(region), -1), (
            f"{name}: released at or below the floor this client writes -- it would go on the arrival itself"
        )
        AUTO_SEND_AT_STORY_BYTE[name] = cap
        AUTO_SEND_AREA_CAPS[name] = ((region, cap),)


_add_floor_skipped()
"""AUTO_SEND_AT_STORY_BYTE: {location name -> the story byte at which the client sends it, travel randomization
OFF}. With travel randomization off every area reads the one global byte, so an area's floor IS that byte.

AUTO_SEND_AREA_CAPS (ADDENDUM 405): {location name -> ((region, cap), ...)}, travel randomization ON. Sent once
EVERY listed area has itself reached its cap -- `story_bytes.area_progress`, the per-area memory -- and never on
another area's progress. One pair for a one-shot; one per fight for Biden's (Any)."""
