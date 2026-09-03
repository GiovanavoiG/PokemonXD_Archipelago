"""
Region graph for the Pokemon XD: Gale of Darkness apworld.

STATUS: skeleton. XD's real overworld has more backtracking and parallel access than this (e.g. Pyrite Town
and Realgam Tower are both reachable and revisited repeatedly across the story, not a strict one-way chain).
This models a simplified linear chain -- Menu -> Outskirt Stand -> Phenac City -> Pyrite Town -> Realgam Tower
-> Agate Village -> Cipher Key Lair -> Citadark Isle -- gated by accumulating Krane Memos, which is enough to
demonstrate the region/entrance/access-rule mechanism (see docs/world api.md's create_regions example) without
yet claiming to be a faithful map. Replace with the real connectivity once verified.
"""

from BaseClasses import Region

from .items import PokemonXDItem, ItemClassification
from .locations import PokemonXDLocation, LOCATIONS_BY_REGION, EVENT_LOCATION_NAME, create_regions_and_locations

# Ordered story chain and how many total Krane Memos must be held to advance past each link.
# (index 0 = Menu -> Outskirt Stand, always open)
REGION_CHAIN: list[str] = [
    "Outskirt Stand",
    "Phenac City",
    "Pyrite Town",
    "Realgam Tower",
    "Agate Village",
    "Cipher Key Lair",
    "Citadark Isle",
]

# Krane Memos required (cumulative) to enter each region in the chain, aligned by index.
#
# Outskirt Stand (index 0) always has zero real locations in this skeleton (its only entry, the starting
# Eevee gift, is a landmark rather than a shuffled check -- see locations.py), and depending on options either
# shadow-capture or overworld-item locations may be the only category present in a region. So Phenac City
# (index 1) is also left ungated, to guarantee there's always at least one reachable, unfilled location before
# the first real gate -- otherwise the very first Krane Memo has nowhere logically valid to be placed, a
# textbook "restrictive start" fill failure (see the APWorld Dev FAQ's section on this). Each later threshold
# was chosen so the cumulative location count of already-open regions is always >= the memo count being
# required, even in the worst case where only one of the two shuffle categories is enabled.
MEMOS_REQUIRED: list[int] = [0, 0, 1, 2, 3, 4, 5]


def create_and_connect_regions(world) -> None:
    menu = Region("Menu", world.player, world.multiworld)
    world.multiworld.regions.append(menu)

    regions = create_regions_and_locations(world)

    previous = menu
    for i, region_name in enumerate(REGION_CHAIN):
        region = regions[region_name]
        required = MEMOS_REQUIRED[i]
        if required > 0:
            previous.connect(
                region,
                name=f"{previous.name} -> {region_name}",
                rule=lambda state, n=required: state.count_group_unique("Krane Memos", world.player) >= n,
            )
        else:
            previous.connect(region, name=f"{previous.name} -> {region_name}")
        previous = region

    # Species-catch locations (see locations.py) are checked live by the client whenever it detects a species,
    # not by the player traversing to them in-game, so they don't belong anywhere in the story chain -- connect
    # the "Pokemon Storage" region straight off Menu, always open, same as the chain's own ungated first link.
    menu.connect(regions["Pokemon Storage"], name="Menu -> Pokemon Storage")

    # Same reasoning for the 32 cumulative purification-count locations (2026-09-03, see locations.py) -- the
    # client checks these live off the purification-count tracker, not off any in-game location the player
    # walks to, so this region is also always open straight off Menu.
    menu.connect(regions["Shadow Pokemon Purification"], name="Menu -> Shadow Pokemon Purification")

    # Citadark Isle additionally requires the Ein File S key item (grants final-area access in the real game).
    citadark = regions["Citadark Isle"]

    # The win condition is an event: capture/defeat the Cipher Boss.
    boss_region = citadark
    victory_location = PokemonXDLocation(world.player, EVENT_LOCATION_NAME, None, boss_region)
    victory_location.place_locked_item(
        PokemonXDItem("Victory", ItemClassification.progression, None, world.player)
    )
    victory_location.access_rule = lambda state: state.has("Ein File S", world.player)
    boss_region.locations.append(victory_location)

    world.multiworld.completion_condition[world.player] = lambda state: state.has("Victory", world.player)
