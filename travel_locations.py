"""
Travel-destination unlock data for the "Randomize Travel Locations" YAML option
(options.RandomizeTravelLocations, items "Travel Unlock - {name}", ADDENDUM 104, 2026-09-09).

With the option on, every destination in `TRAVEL_LOCATION_BITS` becomes its own progression item instead of being
vanilla-accessible. Receiving one live-writes that destination's FULL-icon bit(s) into the travel-control record,
making it selectable on the in-game map -- a live RAM write via Client.py, never an ISO patch, and always an OR
into the target byte, since several destinations share one.

WHERE THE BITS COME FROM -- this project's own live Dolphin-bridge investigation, not a guess. ADDENDUM 83/84
found the 20-byte record and `+0x08` as a per-destination unlock bitmask (Kaminko Mansion, Gateon Port, Snagem
Hideout, Outskirt Stand); ADDENDUM 85 found `+0x09` (Cave Poke Spot, Pyrite Town, Agate Village) and that
"access" and "map icon shown" are sometimes separate bits for one location -- a low "partial" bit beneath a
higher "full icon" bit; ADDENDUM 90 added `+0x0A` (Phenac City) and Outskirt Stand's 3-bit combo; ADDENDUM 91
fixed `travel_record_base = BLOCK_BASE + 0x10720` (identical across two independent reboots) and bit-mapped
`+0x0D`/`+0x0E`/`+0x0F`/`+0x11` (Oasis Poke Spot, Realgam Tower, Cipher Key Lair, Rockground Poke Spot, Kaminko's
House, Cipher Lab, Mt. Battle, SS Libra, Orre Colosseum). That addendum's "Master reveal everything reference
table" is the authoritative source for every entry below.

ALWAYS OPEN BY DESIGN, never items (ADDENDUM 106): Kaminko Mansion and the HQ Lab have no gating bit at all
(ADDENDUM 84; the lab was never a separate destination), while Agate Village (`+0x09` `0x20`) and Gateon Port
(`+0x08` `0x08`) do and are written proactively. "The Under" is not a reachable area in XD (player correction,
2026-09-09) and never had a bit; Citadark Isle goes through the story byte, not this bitmask.

Adjacency is confirmed for Outskirt Stand and SS Libra only (ADDENDUM 105). For the other twelve no source solid
enough to encode exists -- Bulbapedia's Orre article says outright that "it is not known if there are any
connecting routes" -- so they stay item-gated; `pokemon-xd-addendum-106-...md` has the per-location travel-menu
testing list that would close the gap.

SAVE SAFETY, unresolved: this record has never been confirmed to persist across a Dolphin reboot. ADDENDUM 91
established that its ADDRESS relocates by a fixed offset from BLOCK_BASE but never tested whether its CONTENTS
survive, so treat every bit as possibly resetting to baseline on every reboot -- which is why persisting what was
received and re-flipping it on reconnect is required rather than nice to have.
"""

from __future__ import annotations

from dataclasses import dataclass

# `ram_client` needs `dolphin_memory_engine`, which only ever exists on the CLIENT side, and this module is
# imported by items.py at world-generation time. So it is imported lazily inside the functions that touch live
# memory. Do NOT hoist it: generation would fail with ModuleNotFoundError on any machine that only generates.

# ADDENDUM 91: always this fixed offset from the already-resolved player-state block base
# (ram_client.resolve_block_base), confirmed identical across two independent reboots, so any caller holding a
# valid block_base can derive it without a separate resolution step.
TRAVEL_RECORD_OFFSET_FROM_BLOCK_BASE = 0x10720

# Kept here rather than hardcoded in Client.py so the two cannot drift on the exact prefix text.
TRAVEL_UNLOCK_ITEM_PREFIX = "Travel Unlock - "


@dataclass(frozen=True)
class TravelBit:
    byte_offset: int  # offset from travel_record_base (e.g. 0x08 for the first bitmask byte)
    full_bits: int  # bit(s), OR'd together, that grant this destination's FULL ("?" icon shown) access
    # Set only where the partial bit was measured in play rather than derived. Outskirt Stand is the single
    # case, and it also shows the derivation is slightly too eager: `full >> 1` would give it 0x01|0x10, but
    # ADDENDUM 90's confirmed access combo is 0x02|0x10|0x20 -- no 0x01. That 0x01 has never been observed set,
    # so clearing it would be harmless, but harmless is not measured.
    measured_partial_bits: "int | None" = None

    @property
    def partial_bits(self) -> int:
        """The lower "partial/access-only" bit(s) ADDENDUM 85 found beneath the full-icon bit(s). Clearing only the
        full-icon bit leaves a destination selectable or half-drawn but without a proper icon (ADDENDUM 172).

        DERIVED, and checkable. Every byte here is 2-bit PAIRS, one per destination: full-icon bit at the odd
        position, partial beneath it at the even one. Byte 0x08 proves it, since three destinations share it --
        0x01/0x02 and 0x10/0x20 are Outskirt Stand's two pairs, 0x04/0x08 Gateon Port's, 0x40/0x80 Snagem's. And
        Outskirt Stand's partial was confirmed in play (ADDENDUM 90: access is 0x02|0x10|0x20, the full-icon
        state drops 0x10), where 0x10 is exactly `0x20 >> 1`. So `full >> 1` reproduces the measured case and
        never leaves a destination's own pair. Setting stayed full-bits-only until ADDENDUM 380 -- see
        `_or_write_bit`."""
        if self.measured_partial_bits is not None:
            return self.measured_partial_bits
        return (self.full_bits >> 1) & 0xFF

    @property
    def all_bits(self) -> int:
        """Everything this destination owns -- what a clear has to take away."""
        return self.full_bits | self.partial_bits


# Every travel destination with an independently-confirmed, live-writable bit that is not one of the always-open
# locations. Declaration order is NOT story/travel order, and `items._table` numbers by index into it, so
# reordering renumbers item ids. "Gateon Port" was moved out to `ALWAYS_OPEN_TRAVEL_BITS` (ADDENDUM 106).
TRAVEL_LOCATION_BITS: dict[str, TravelBit] = {
    "Snagem Hideout": TravelBit(0x08, 0x80),
    # The one destination whose partial bit was measured rather than derived (ADDENDUM 90): its full access is
    # the 3-bit combo 0x02|0x10|0x20, and the full-icon state drops 0x10. So 0x10 IS the partial bit.
    "Outskirt Stand": TravelBit(0x08, 0x02 | 0x20, measured_partial_bits=0x10),
    "Cave Poke Spot": TravelBit(0x09, 0x02),
    "Pyrite Town": TravelBit(0x09, 0x08),
    "Phenac City": TravelBit(0x0A, 0x80),
    "Oasis Poke Spot": TravelBit(0x0D, 0x02),
    "Realgam Tower": TravelBit(0x0E, 0x02),
    # ADDENDUM 378, player: "Make every 'Key Lab' reference 'Key Lair'." This key is the one edit that does it: the
    # item, the `Unlock -` location and regions.py's `Travel Gateway -` region all derive from
    # `TRAVEL_LOCATION_NAMES`, which comes from this table. Its POSITION is unchanged, which keeps the ids.
    "Cipher Key Lair": TravelBit(0x0E, 0x08),
    "Rockground Poke Spot": TravelBit(0x0E, 0x80),
    # "Kaminko's House" (`TravelBit(0x0F, 0x02)`) removed 2026-09-25, ADDENDUM 356. Its item gated nothing:
    # Kaminko's is always-open, so it sat in TRAVEL_CLEAR_EXEMPT (never re-locked) and out of
    # `gateway_only_regions` (chain edge never suppressed). Frozen id 249 is retired, not reused, like 239
    # (Gateon Port, ADDENDUM 106) and the three per-spot ids ADDENDUM 177 merged.
    "Cipher Lab": TravelBit(0x0F, 0x08),
    "Mt. Battle": TravelBit(0x0F, 0x20),
    "SS Libra": TravelBit(0x0F, 0x80),
    "Orre Colosseum": TravelBit(0x11, 0x04),
}

# ADDENDUM 177: the three Poke Spots are ONE unlock. Two layers kept apart -- `TRAVEL_LOCATION_BITS` stays the
# PHYSICAL truth, one bit per spot in its own byte, because the game needs all three written or the icons
# disagree; this layer is what the multiworld sees. Collapsing the bit table would have meant inventing a
# multi-byte TravelBit and losing the per-spot measurements ADDENDA 85/91 confirmed.
TRAVEL_UNLOCK_MEMBERS: dict[str, tuple[str, ...]] = {
    "Poke Spots": ("Cave Poke Spot", "Oasis Poke Spot", "Rockground Poke Spot"),
}

_GROUPED_DESTINATIONS: "frozenset[str]" = frozenset(
    member for members in TRAVEL_UNLOCK_MEMBERS.values() for member in members
)

# The unlock names the multiworld deals in: every ungrouped destination plus one per group, in the bit table's
# order, each group taking its first member's position (so the Poke Spots unlock sits where "Cave Poke Spot"
# was and this list stays recognisable against the record layout).
def _unlock_names() -> list[str]:
    names: list[str] = []
    for destination in TRAVEL_LOCATION_BITS:
        if destination not in _GROUPED_DESTINATIONS:
            names.append(destination)
            continue
        group = next(g for g, members in TRAVEL_UNLOCK_MEMBERS.items() if destination in members)
        if group not in names:
            names.append(group)
    return names


TRAVEL_LOCATION_NAMES: list[str] = _unlock_names()


def travel_unlock_members(unlock_name: str) -> "tuple[str, ...]":
    """The physical destinations one unlock name covers; a plain destination covers itself, so callers need not
    know whether they hold a group."""
    return TRAVEL_UNLOCK_MEMBERS.get(unlock_name, (unlock_name,))

# ADDENDUM 106: confirmed bits for locations that are always open by design and never items, written
# proactively so the real map matches what AP logic treats as free rather than showing an unselectable icon.
# Kaminko Mansion and the HQ Lab have no entry because neither has a bit at all -- see the module docstring.
ALWAYS_OPEN_TRAVEL_BITS: dict[str, TravelBit] = {
    "Gateon Port": TravelBit(0x08, 0x08),
    "Agate Village": TravelBit(0x09, 0x20),
}

# Which existing regions.py region a travel item unlocks reachability to (see create_and_connect_regions). Since
# ADDENDUM 171/168 gave the graph 21 real regions, 13 of 14 are exact 1:1 matches rather than the old
# seven-region approximations; the one merge is the player's own, all three Poke Spots on one region.
#
# ADDENDUM 185 unmerged Orre Colosseum from Realgam Tower, which had made its item a SECOND key to a region that
# already had one. It now points at a region of its own that holds nothing and leads nowhere, so the item and
# its check still work in game and the logic no longer cares -- it is a postgame area.
ORRE_COLOSSEUM_REGION = "Orre Colosseum"

TRAVEL_LOCATION_TARGET_REGION: dict[str, str] = {
    "Snagem Hideout": "Snagem Hideout",
    "Outskirt Stand": "Outskirt Stand",
    "Poke Spots": "Poke Spots",
    "Pyrite Town": "Pyrite Town",
    "Phenac City": "Phenac City",
    "Realgam Tower": "Realgam Tower",
    "Cipher Key Lair": "Cipher Key Lair",   # ADDENDUM 378 -- an identity row now, like every other one here
    # "Kaminko's House" removed 2026-09-25 (ADDENDUM 356) alongside its bit-table entry. regions.py iterates
    # THIS table to build gateways, so leaving it would have built `Travel Gateway - Kaminko's House` behind an
    # item that no longer exists -- harmless in itself, but a dead entrance a later audit mistakes for a gate.
    "Cipher Lab": "Cipher Lab",
    "Mt. Battle": "Mt. Battle",
    "SS Libra": "SS Libra",
    "Orre Colosseum": ORRE_COLOSSEUM_REGION,
}

# ADDENDUM 171: the vanilla unlock moment becomes a CHECK. The player's own example -- "Mt Battle is vanilla
# unlocked at story byte 0x23 > 0x24" -- applies to every destination after Kaminko/Agate/Gateon/HQ Lab. The GAME
# still unlocks destinations as the story advances, and ADDENDUM 104 only ever added bits, so progressing
# normally gave every destination free. Now an
# unreceived destination's bit is held clear every tick, and the byte that would have unlocked it in the
# unmodified game sends its own AP location instead: the item grants the access, the story grants the check.
# Thresholds come from game_data/story_bytes.py rather than being typed again.
TRAVEL_UNLOCK_LOCATION_PREFIX = "Unlock - "


def travel_unlock_location_name(destination: str) -> str:
    """The AP location that fires when the story reaches `destination`'s vanilla unlock point."""
    return f"{TRAVEL_UNLOCK_LOCATION_PREFIX}{destination}"


# ADDENDUM 185: where a destination's CHECK fires is a different question from what its ITEM opens, and Orre
# Colosseum is the one place the answers differ. Its item opens a region that gates nothing, but the check still
# has to be gettable -- and it is physically part of the Realgam complex, so Realgam's unlock byte is when the
# game would make it selectable. Any destination absent here answers with its target region.
TRAVEL_UNLOCK_STORY_REGION: dict[str, str] = {
    "Orre Colosseum": "Realgam Tower",
}


def vanilla_unlock_story_byte(destination: str) -> "int | None":
    """The story byte at which the unmodified game would unlock `destination`, or None when there is no story data
    for it -- which reads as "never fire the check from the story byte"."""
    from .game_data import story_bytes

    region = TRAVEL_UNLOCK_STORY_REGION.get(destination) or TRAVEL_LOCATION_TARGET_REGION.get(destination)
    if region is None:
        return None
    # ADDENDUM 279's first-visit floors answer "what byte should this room be BUILT from", not "at what byte does
    # the game unlock this icon" -- you never unlock Gateon, the lab or Kaminko's. Unscoped, this handed Kaminko a
    # threshold of 0x03 and so an `Unlock - Kaminko's House` location that has never existed.
    if region in story_bytes.ALWAYS_OPEN_REGIONS:
        return None
    # `area_unlock_floor`, not `area_entry_floor` (ADDENDA 247/324): the SS Libra icon appears in vanilla at 0x4E,
    # when the stranded ship becomes reachable, not at the 0x5A scooter upgrade, so `Unlock - SS Libra` was
    # credited twelve bytes late. Same for the Key Lair, whose icon is the exterior at 0x5D, not 0x64.
    return story_bytes.area_unlock_floor(region)


# ADDENDUM 355/356: an `Unlock - D` check is earned in the area BEFORE D, not in D itself.
#
# Nine fired at once on walking into Gateon Port, all credited from the story byte -- which cannot answer this in
# the only mode these locations exist in, because the client FORGES the byte there: arriving anywhere writes that
# area's entry floor so the rooms build (ADDENDUM 177). Travel straight to Snagem, get written in at 0x62, beat
# Gonzap, and the game advances the byte from a value we invented -- real progress, which `StoryProgressWitness`
# cannot and should not refuse -- so "the byte is past 0x30" stops meaning "you have been to Pyrite". ADDENDUM
# 355's fix, the mark in D ITSELF, then made every `Unlock - D` require
# `Travel Unlock - D` first: deferred self-credit, the shape ADDENDUM 270 forbids.
#
# The PREDECESSOR answers both -- it is where the byte really moves ("you finish the Cipher Lab and PYRITE's icon
# appears") and it is never D. Unforgeable, since `AreaStoryByteMemory.visited` is only written from `observe()`,
# which refuses our own writes. Derived as the group whose unlock floor is the largest value strictly below D's
# threshold, over the same `area_unlock_floor` that produces it, and resolving to:
#     Cipher Lab, Mt. Battle   <- Agate Village        Phenac City      <- Poke Spots
#     Pyrite Town              <- Cipher Lab           Realgam Tower    <- Phenac City
#     Poke Spots               <- Pyrite Town          Orre Colosseum   <- Phenac City
#     SS Libra                 <- Realgam Tower        Cipher Key Lair  <- SS Libra
#     Outskirt Stand, Snagem Hideout                   <- Cipher Key Lair
#
# Orre Colosseum needs the substitution it already has: no room in `chest_regions.ROOM_TO_REGION` maps to its
# region, so an arrival test against it could never be satisfied. `TRAVEL_UNLOCK_STORY_REGION` answers this for
# the threshold already, for the same physical reason, so the witness uses the same table.
_UNLOCK_PREDECESSORS: "dict[str, tuple[str, ...]]" = {}


def _build_unlock_predecessors() -> "dict[str, tuple[str, ...]]":
    from .game_data import story_bytes

    # The GROUP is the unit: Pyrite's ONBS half and Phenac's Mayor's House are the same place to the player.
    floors: "dict[int, list[str]]" = {}
    for group in story_bytes.AREA_GROUPS:
        floor = story_bytes.area_unlock_floor(group)
        if floor is not None:
            floors.setdefault(floor, []).append(group)

    built: "dict[str, tuple[str, ...]]" = {}
    for destination in TRAVEL_LOCATION_NAMES:
        threshold = vanilla_unlock_story_byte(destination)
        if threshold is None:
            continue
        below = [value for value in floors if value < threshold]
        if not below:
            continue
        groups = floors[max(below)]
        # A tie is a real ambiguity, not a detail to average over: two groups sharing one floor means the ladder
        # does not say which of them the byte moved in. Nothing ties today; if one ever does, answer it.
        assert len(groups) == 1, f"{destination}: ambiguous predecessor {groups} at floor {max(below):#04x}"
        built[destination] = tuple(story_bytes.AREA_GROUPS[groups[0]])
    return built


def unlock_predecessor_region(destination: str) -> str:
    """The ENTRY TIER of the area one rung below `destination` on the story ladder, or "" when there is none.

    The group's first member, since `AREA_GROUPS` lists every group entry-first -- the tier a player arrives in,
    and what `Unlock - {destination}` is filed under in locations.py, so AP's logic gates the check the same way
    the client credits it. The sibling tiers are not lost: `travel_item_by_sibling_region()` already requires
    their travel item, so filing on the entry tier is the loosest of the group's rules."""
    members = _UNLOCK_PREDECESSORS.get(destination)
    return members[0] if members else ""


def unlock_witness_regions(destination: str) -> "tuple[str, ...]":
    """Every region whose story mark can earn `Unlock - {destination}`: the PREDECESSOR area's whole group,
    never `destination` itself (ADDENDUM 356).

    Empty when this project cannot name a predecessor, which reads as "never credit" the same way a missing
    threshold does."""
    return _UNLOCK_PREDECESSORS.get(destination, ())


_UNLOCK_PREDECESSORS.update(_build_unlock_predecessors())

# Every destination with a threshold must have a predecessor -- one without would be a check no mark could ever
# earn -- and no destination may be its own witness, which is ADDENDUM 270's finding as an assertion.
for _destination in TRAVEL_LOCATION_NAMES:
    if vanilla_unlock_story_byte(_destination) is None:
        continue
    _witnesses = unlock_witness_regions(_destination)
    assert _witnesses, f"{_destination}: has a threshold but no predecessor area to earn it in"
    _own = TRAVEL_UNLOCK_STORY_REGION.get(_destination) or TRAVEL_LOCATION_TARGET_REGION.get(_destination)
    assert _own not in _witnesses, f"{_destination}: would credit itself -- see ADDENDUM 270"
del _destination, _witnesses, _own


def clear_travel_location_bit(record_base: int, location_name: str) -> bool:
    """AND-NOT the opposite of `_or_write_bit`: holds `location_name`'s bit(s) CLEAR. Returns True only on a real
    change, so the caller can log a transition rather than every tick.

    Touches only this location's own bits -- several destinations share a byte, so a blunt overwrite would
    re-lock a sibling the player has received."""
    from . import ram_client  # lazy -- see the module docstring

    # ADDENDUM 177: one unlock name can cover several physical destinations (the Poke Spots). Every member's
    # bits are cleared, and "changed" means ANY of them moved.
    changed = False
    for destination in travel_unlock_members(location_name):
        bit = TRAVEL_LOCATION_BITS[destination]
        address = record_base + bit.byte_offset
        current = ram_client.read_bytes(address, 1)[0]
        # ADDENDUM 172: the PARTIAL bit goes too, or the destination is left in ADDENDUM 85's in-between state
        # rather than actually locked. See TravelBit.partial_bits.
        updated = current & ~bit.all_bits & 0xFF
        if updated != current:
            ram_client.write_bytes(address, bytes([updated]))
            changed = True
    return changed


assert set(TRAVEL_LOCATION_TARGET_REGION) == set(TRAVEL_LOCATION_NAMES), (
    "travel_locations.py: TRAVEL_LOCATION_TARGET_REGION must cover exactly the same names as "
    "TRAVEL_LOCATION_BITS -- every randomizable travel destination needs a target region to wire into "
    "regions.py's graph when randomize_travel_locations is on."
)


# ADDENDUM 105: two destinations have a live-confirmed adjacency constraint on top of their own item. ADDENDUM 85
# found Outskirt Stand's travel menu offers only {Cave Poke Spot, Pyrite Town, Snagem Hideout}; ADDENDUM 91 found
# that boarding SS Libra without the scooter drops the player at Phenac City, making Phenac the ship's departure
# point. An `AdjacencyRequirement` is an EXTRA clause ANDed onto a gateway rule, itself an OR: hold a
# `sibling_items` entry, or `can_reach()` one of `regions` (ordinary region names, never gateway nodes, so no
# cycle). Everything else stays item-only, since an unconfirmed adjacency would be a guess.
#
# KNOWN LIMITATION: "Outskirt Stand" and "Phenac City" are the two chain links regions.py must leave open from
# turn one, or the first Krane Memo has nowhere valid to go, and both are this table's region targets -- so that
# OR-branch is trivially True. What it does fix is each gateway's own ENTRANCE rule (TestTravelLocationAdjacency
# exercises it directly); Outskirt Stand's sibling_items branch is not trivial and has real effect today.
@dataclass(frozen=True)
class AdjacencyRequirement:
    sibling_items: tuple[str, ...] = ()  # OR'd: state.has() on these OTHER travel-unlock item names
    regions: tuple[str, ...] = ()  # OR'd: state.can_reach() on these existing regions.py region names


TRAVEL_LOCATION_ADJACENCY: dict[str, AdjacencyRequirement] = {
    "Outskirt Stand": AdjacencyRequirement(
        # ADDENDUM 177: "Cave Poke Spot" folded into the "Poke Spots" unlock, so the group's item is the sibling.
        sibling_items=("Poke Spots", "Snagem Hideout"),
        regions=("Pyrite Town",),
    ),
    # ADDENDUM 324 moved SS Libra's entry to TRAVEL_LOCATION_REQUIRED_REGIONS below. It was
    # `AdjacencyRequirement(regions=("Phenac City",))`, which had no teeth for the reason stated above.
}


# ADDENDUM 176: HARD region prerequisites, their own table rather than a flag on `AdjacencyRequirement`, because
# an adjacency is an OR a sibling item can satisfy and this is "that region must be reachable, full stop". The
# base chain already enforced them with travel randomization off (REGION_EDGES runs SS Libra -> Cipher Key Lair
# (exterior) -> Outskirt Stand -> Snagem Hideout -> Cipher Key Lair); the hole was the gateway straight off Menu,
# whose only requirement is its own item. Keys are TRAVEL LOCATION names, not always region names, and the
# assertions below check both halves so a typo cannot sit here doing nothing.
#
# Two entries are gone, neither replaced, for the same unconfirmed-adjacency reason as above. ADDENDUM 293
# withdrew Snagem's SS Libra prerequisite: since ADDENDUM 273 the `SS Libra` region means "the multiworld has sent
# the Scooter", so naming it put Snagem and the whole Key Lair branch behind one item. ADDENDUM 332 then decoupled
# the Key Lair from Snagem -- that gate existed because the game's own route runs through the hideout, and here
# the hover writes `AREA_ENTRY_FLOOR_OVERRIDES["Cipher Key Lair"]`, which IS "Gonzap beaten, the Lair open".
# (`Defeat - Zook #2` still names Snagem in `PLACEMENTS[147].required_regions` -- a fact about that FIGHT.)
#
# SS LIBRA'S ENTRY remains, as a hard AND rather than ADDENDUM 105's toothless adjacency (ADDENDUM 324). "After
# Phenac" is the CLEARED town, "Phenac City (Post-Sixes)": plain "Phenac City" is open from turn one and the
# Mayor's House tier stops half way through. That is what the vanilla chain says too, so travel shuffle stops
# being looser than the unmodified game, and the Disc and Note land on every path to the ship. With travel
# randomization off none of this applies -- `ScooterStoryHold` keeps the ship before Snagem there.
TRAVEL_LOCATION_REQUIRED_REGIONS: dict[str, tuple[str, ...]] = {
    "SS Libra": ("Phenac City (Post-Sixes)",),
}


def required_regions_for(travel_location_name: str) -> "tuple[str, ...]":
    return TRAVEL_LOCATION_REQUIRED_REGIONS.get(travel_location_name, ())


# ADDENDUM 190: the story chain is NOT a second way in. The gateways were an extra entrance alongside it while
# the client only ADDED map bits; ADDENDUM 171 made `enforce_travel_locks` hold every unreceived bit clear every
# tick, and nobody changed the graph, which went on offering the vanilla chain to places the client was re-locking.
# MEASURED before the fix: holding every progression item EXCEPT the twelve travel unlocks, all 675 locations were
# still reachable.
#
# Single source of truth for both halves -- `enforce_travel_locks` skips these when clearing bits and
# `gateway_only_regions()` subtracts them. EMPTY since ADDENDUM 356 retired Kaminko's House, its only member, and
# kept so a future always-open destination has somewhere to go. Never a tombstone: a retired name left here would
# silently exempt it if anyone re-added its bit.
TRAVEL_CLEAR_EXEMPT: "frozenset[str]" = frozenset()


def gateway_only_regions() -> "frozenset[str]":
    """Regions whose ONLY entrance is their travel gateway when randomize_travel_locations is on.

    Every destination whose map bit the client holds clear -- reaching it any other way is a promise the game
    cannot keep. Derived from the exempt set rather than listed again, so the graph cannot disagree with what the
    client re-locks. One region per destination, the one the gateway CONNECTS TO; the others behind the same map
    icon go through `travel_item_by_sibling_region()`, for the reason that function gives."""
    return frozenset(
        region for name, region in TRAVEL_LOCATION_TARGET_REGION.items()
        if name not in TRAVEL_CLEAR_EXEMPT
    )


def travel_item_by_sibling_region() -> "dict[str, str]":
    """`{region: the travel item that must also be held to reach it}`, for every region behind a destination's map
    icon that is not the region its gateway connects to.

    ADDENDUM 270: one icon is often several regions (`story_bytes.AREA_GROUPS`), and `gateway_only_regions()`
    covers only the gateway's own target. A SIBLING tier entered from elsewhere kept its chain edge, so the graph
    believed you could reach it without the destination's item while the client held that bit clear every tick.
    MEASURED with `Travel Unlock - Pyrite Town` withheld: nine progression-eligible locations in
    `Pyrite Town (ONBS)` still reachable, three chests and six trainer defeats, so a key item on any of them
    generates cleanly and cannot be finished. `Kaminko's House (Robo Groudon)` behind SS Libra is the same shape,
    two chests.

    NOT just "add them to gateway_only" -- tried, and wrong: that suppresses the chain edge while the gateway
    connects to its own target, so the siblings strand with no entrance at all (ONBS, the Kaminko crane room and
    two shops went unreachable under `all_state`). Their edge must SURVIVE and gain the item."""
    from .game_data import story_bytes

    gateways = gateway_only_regions()
    out: "dict[str, str]" = {}
    for name, region in TRAVEL_LOCATION_TARGET_REGION.items():
        if name in TRAVEL_CLEAR_EXEMPT:
            continue
        for members in story_bytes.AREA_GROUPS.values():
            if region not in members:
                continue
            for sibling in members:
                # The gateway's own target is already handled, and a region that is some OTHER destination's
                # gateway target has its own item and must not be given a second one.
                if sibling == region or sibling in gateways:
                    continue
                out[sibling] = travel_unlock_item_name(name)
    return out


assert set(TRAVEL_LOCATION_REQUIRED_REGIONS) <= set(TRAVEL_LOCATION_TARGET_REGION), (
    "a hard-prerequisite key is not a real travel location name -- it would silently gate nothing"
)
def _prerequisite_region_is_real(region: str) -> bool:
    """A prerequisite may name a destination's own region OR a deeper tier of that destination's area.

    ADDENDUM 324 widened this from "must be some destination's target region": "Phenac City (Post-Sixes)" is not
    a map icon, it is the tier that means the town has been done. The invariant kept is that the name is a REAL
    region of a real destination's area, so a typo still fails -- hence the test against `AREA_GROUPS`."""
    from .game_data import story_bytes

    targets = set(TRAVEL_LOCATION_TARGET_REGION.values())
    if region in targets:
        return True
    for area, members in story_bytes.AREA_GROUPS.items():
        if region in members and (area in targets or set(members) & targets):
            return True
    return False


assert all(
    _prerequisite_region_is_real(region)
    for regions_needed in TRAVEL_LOCATION_REQUIRED_REGIONS.values()
    for region in regions_needed
), "a hard prerequisite names a region no travel destination's area contains"


def travel_unlock_item_name(location_name: str) -> str:
    return f"{TRAVEL_UNLOCK_ITEM_PREFIX}{location_name}"


def travel_location_name_from_item(item_name: str) -> str | None:
    """Inverse of `travel_unlock_item_name` -- None if `item_name` isn't a travel-unlock item at all."""
    if not item_name.startswith(TRAVEL_UNLOCK_ITEM_PREFIX):
        return None
    name = item_name[len(TRAVEL_UNLOCK_ITEM_PREFIX):]
    return name if name in TRAVEL_LOCATION_NAMES else None


def _or_write_bit(record_base: int, bit: TravelBit) -> None:
    """Shared OR-not-overwrite write, for both item-triggered unlocks and the always-open proactive write.
    Several locations share a byte, so it must never clobber a sibling's bit(s)."""
    from . import ram_client  # lazy -- see the module docstring

    address = record_base + bit.byte_offset
    current = ram_client.read_bytes(address, 1)[0]
    # ADDENDUM 380: a grant CLEARS the partial bit as well as setting the full one. Every clear path here takes
    # `all_bits` (ADDENDUM 172), while this, the only SET path, took `full_bits` alone -- so a clear produced 00
    # and a grant produced full|partial whenever the partial was already set. And the game sets the partial bit
    # itself the moment the story reveals an area, so the icon was drawn from a pattern meaning neither "hidden"
    # nor "available".
    #
    # One write, not two: set-then-clear would leave a poll-width window where both bits are set, which is the
    # exact state being fixed. The mask is computed first and written once.
    updated = (current | bit.full_bits) & ~bit.partial_bits & 0xFF
    if updated != current:
        ram_client.write_bytes(address, bytes([updated]))


def write_travel_location_bit(record_base: int, location_name: str) -> None:
    """Puts `location_name` into the FULL ("?" icon shown) state at an already-resolved record base -- full bit(s)
    set, partial bit(s) cleared (ADDENDUM 380, see `_or_write_bit`).

    Idempotent and meant to be re-called: it writes only on a real change, so `sync_travel_locations` can run it
    every poll, which is what keeps the icon right after the story sets the partial bit for an area the player
    already holds. The Poke Spots item writes all three spots' bits (ADDENDUM 177), since the game keeps a bit
    per spot and writing one would leave the other two icons dark."""
    for destination in travel_unlock_members(location_name):
        _or_write_bit(record_base, TRAVEL_LOCATION_BITS[destination])


def read_travel_location_unlocked(record_base: int, location_name: str) -> bool:
    """True if every one of `location_name`'s full-icon bits is currently set at the given record base."""
    from . import ram_client  # lazy -- see the module docstring

    # ADDENDUM 177: a grouped unlock counts as unlocked only when EVERY member is -- a half-written group is the
    # in-between state this function exists to distinguish.
    for destination in travel_unlock_members(location_name):
        bit = TRAVEL_LOCATION_BITS[destination]
        current = ram_client.read_bytes(record_base + bit.byte_offset, 1)[0]
        if (current & bit.full_bits) != bit.full_bits:
            return False
    return True


def write_always_open_bits(record_base: int) -> None:
    """ADDENDUM 106: writes every `ALWAYS_OPEN_TRAVEL_BITS` bit so the real map matches what AP logic treats as
    free from turn one, instead of showing an unselectable icon on a fresh save.

    Called EVERY POLL while the ADDENDUM 280 gate is open, not once per boot, which ADDENDUM 380 relies on: a
    granted destination has to be re-asserted for as long as the game can still set its partial bit."""
    for bit in ALWAYS_OPEN_TRAVEL_BITS.values():
        _or_write_bit(record_base, bit)


# ADDENDUM 280: the always-open pair is not open at byte zero. ADDENDUM 106 made Agate Village and Gateon Port
# free from turn one, which is right about the ITEM POOL and wrong about WHEN the map should offer them -- the
# client writes those bits on the first poll after `block_base` resolves, before the lab's opening beats have
# run, and travelling out of them early is what strands the run.
#
# A TIMING GATE, NOT A LOGIC GATE, which is what keeps generation untouched: reaching 0x0F in the lab needs no
# item from anybody, so both stay exactly as reachable as they were in sphere zero and regions.py does not change.
ALWAYS_OPEN_GATE_AREA = "Pokemon HQ Lab"
ALWAYS_OPEN_GATE_BYTE = 0x0F


def clear_always_open_bits(record_base: int) -> bool:
    """Hold every `ALWAYS_OPEN_TRAVEL_BITS` entry's bit(s) CLEAR. Returns True when something actually changed.

    Has to exist rather than the client simply declining to write: the GAME sets these bits itself, since they
    are genuinely always-open in vanilla, so not writing them leaves them set. Clears `all_bits`
    (full | partial), matching `clear_travel_location_bit`, because a partial bit left standing is ADDENDUM 85's
    "selectable but no proper icon" state."""
    from . import ram_client  # lazy -- see the module docstring

    changed = False
    for bit in ALWAYS_OPEN_TRAVEL_BITS.values():
        address = record_base + bit.byte_offset
        current = ram_client.read_bytes(address, 1)[0]
        wanted = current & ~bit.all_bits & 0xFF
        if wanted != current:
            ram_client.write_bytes(address, bytes([wanted]))
            changed = True
    return changed


def read_always_open_bits_set(record_base: int) -> bool:
    """True if every `ALWAYS_OPEN_TRAVEL_BITS` entry's bit(s) are currently set at the given record base."""
    from . import ram_client  # lazy -- see the module docstring

    for bit in ALWAYS_OPEN_TRAVEL_BITS.values():
        current = ram_client.read_bytes(record_base + bit.byte_offset, 1)[0]
        if (current & bit.full_bits) != bit.full_bits:
            return False
    return True
