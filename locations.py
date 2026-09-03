"""
Location definitions for the Pokemon XD: Gale of Darkness apworld.

STATUS (2026-09-03 expansion): four location *categories* are modeled, matching the player's "minimum viable
apworld" request. The first two match categories rotobash/pokemon-ngc-rando already shuffles on the
base-randomizer side (see Randomizer/Shufflers/ItemShuffler.cs and StaticPokemonShuffler.cs in that repo):

- "overworld item" locations: a chest/NPC gift/found item in the field. In AP terms, checking one of these
  reports to the server and receives whatever item the multiworld placed there. **2026-09-03: expanded from a
  9-location sample to 48**, sourced from Bulbapedia's 8-part Pokemon XD walkthrough
  (bulbapedia.bulbagarden.net/wiki/Walkthrough:Pok%C3%A9mon_XD) -- every overworld pickup/chest/box the
  walkthrough explicitly describes a location for, across all 8 parts, minus Battle CDs/Discs (excluded from
  the item pool entirely -- see items.py) and shop purchases. **Still not claimed literally exhaustive** -- the
  walkthrough may omit a few minor pickups, and this hasn't been cross-checked against an ISO extraction or
  pokemon-ngc-rando's own static item-table offsets (see pokemon-xd-feasibility.md's Track B notes) -- but it's
  now a real, sourced list rather than a small illustrative sample, and covers every named chest/box the
  walkthrough calls out. Region assignment (which of the 7 story regions each location lives in) is
  approximate where the walkthrough's real map area doesn't correspond 1:1 to this skeleton's simplified linear
  chain (e.g. Kaminko's House and the S.S. Libra are both bucketed under "Realgam Tower", Gateon Port under
  "Outskirt Stand") -- see regions.py's own disclaimer about the simplified chain.
- "shadow capture" locations: defeating/snagging one of the game's Shadow Pokemon from a Cipher Peon/Admin.
  As in other Pokemon AP worlds, the *location* is the in-game action (the encounter); the AP *item* placed
  there is an ordinary shuffled item, not the Pokemon species itself -- the actual Shadow Pokemon you catch
  there remains a vanilla, client-side concern, same as how existing Pokemon worlds (e.g. pokemon_emerald)
  don't ship wild species choice as a multiworld item either. Still a 9-location sample (the real game has far
  more Shadow Pokemon encounters across a full playthrough than this skeleton names individually) -- expanding
  this to the complete roster is the same "need a verified complete list" gap as the overworld items had before
  this pass, not yet closed.
- "species catch" locations (2026-09-02, see the player's location-design request): one "Catch - {species}"
  location per National Dex entry (1-386, see species.py), checked live by the client when that species is
  newly detected in the party or PC box (see PokemonXDClient.py's `get_owned_species_snapshot`). Deliberately
  placed in an always-reachable-from-Menu region and marked `LocationProgressType.EXCLUDED` (see
  `create_regions_and_locations` below) rather than gated by story progress -- XD has very limited normal
  wild-encounter access, so most of the 386 will never be checked in an ordinary playthrough (only whatever
  the player actually catches/trades in), and EXCLUDED guarantees the fill algorithm never needs any of them
  to be reachable in order to place a progression item there. That's what makes shipping all 386 safe despite
  most being impractical to reach normally, rather than a scope decision that needs to be narrowed down first.
  **One exception**: "Catch - Eevee" (species #133) is deliberately left non-excluded -- see
  `GUARANTEED_SPECIES_LOCATION` below; kept for historical reasons (it closed an exact 19-vs-18 progression/
  location gap before the 2026-09-03 overworld-item expansion) even though the expansion below means it's no
  longer the only thing standing between this world and a FillError -- removing the exception isn't necessary
  and isn't done here to avoid re-touching already-tested logic without a reason.
- "shadow Pokemon purification" locations (2026-09-03, see the player's request): 32 cumulative-count
  locations, "Purify 1 Shadow Pokemon" through "Purify 32 Shadow Pokemon" -- the Nth location checks when the
  player has purified their Nth distinct Shadow Pokemon this session (see PokemonXDClient.py's
  `PurificationCountTracker`). Same treatment as species-catch locations and for the same reason: placed in an
  always-reachable-from-Menu region, all 32 marked EXCLUDED, so the fill algorithm never requires any of them
  to be reachable -- correct regardless of how many Shadow Pokemon a given seed's player actually purifies
  (this skeleton's own Shadow Capture sample is only 9 locations, but the real game allows purifying many more
  than 9 across a full playthrough, so 32 is a real, reachable-in-principle target, not an inflated one).

Client-side detection is confirmed live and working for species-catch and purification locations (see
pokemon-xd-ram-map.md's "SOLVED: purification detection" section and the MAJOR party-struct section).
Overworld-item and shadow-capture location detection is designed (see pokemon-xd-feasibility.md's "item-table
locations... ready now" section: patch each location's vanilla item-table entry to grant one consistent,
watchable placeholder item id, then watch the confirmed Bag `[id][qty]` format for it) but not yet live-tested
against a real ISO patch, since ISO-side item-table write-back (patch.py's known "still open" gap) hasn't been
implemented yet.
"""

from dataclasses import dataclass

from BaseClasses import Location, LocationProgressType, Region

from . import species


class PokemonXDLocation(Location):
    game: str = "Pokemon XD Gale of Darkness"


@dataclass(frozen=True)
class LocationData:
    id_offset: int
    region: str


# Cumulative-purification-count locations -- see the module docstring's fourth bullet. 32 is the player's
# requested cap, not derived from anything in-game (the real game's actual total obtainable Shadow Pokemon
# count across a full playthrough is not confirmed by this project -- see pokemon-xd-ram-map.md).
PURIFICATION_LOCATION_COUNT = 32


def purification_location_name(count: int) -> str:
    """"Purify N Shadow Pokemon" for cumulative count N. No singular/plural special-casing -- "Purify 1 Shadow
    Pokemon" reads fine on its own."""
    return f"Purify {count} Shadow Pokemon"


# name -> count, for the client side (mirrors species.SPECIES_LOCATION_TO_DEX).
PURIFICATION_LOCATION_TO_COUNT: dict[str, int] = {
    purification_location_name(n): n for n in range(1, PURIFICATION_LOCATION_COUNT + 1)
}


# region name -> ordered list of location names in that region
#
# The "# NEW 2026-09-03" blocks below are the Bulbapedia-walkthrough-sourced overworld item expansion -- see
# the module docstring. Appended within each region's existing list (not reordered ahead of the original
# sample entries) so none of the original 9 overworld-item locations' id_offsets shift.
LOCATIONS_BY_REGION: dict[str, list[str]] = {
    "Outskirt Stand": [
        "Outskirt Stand - Eevee Gift",  # story gift, not shuffled as a location reward; kept as a landmark event
        # NEW 2026-09-03 (Bulbapedia walkthrough Parts 1-2; Gateon Port is reached very early via ferry from
        # Outskirt Stand, and Prof. Krane's HQ Lab is physically part of Agate Village but reached at the same
        # very-early story beat, so both are bucketed here rather than under "Agate Village").
        "Outskirt Stand - HQ Lab Potions",
        "Gateon Port - Krabby Club Basement Item",
        # RENAMED/RELOCATED 2026-09-03 per real-source verification (see data/chest_verification_report.md):
        # "Gateon Port - Post-Battle Revive" was NOT FOUND at Gateon Port -- the real Revive this was likely
        # describing is awarded in Cipher Lab just after battling Cipher Peon Nexir. Kept in this bucket
        # (Cipher Lab items are already grouped here, see "The Under" entry below) under its real name.
        "Cipher Lab - Nexir Battle Revive",
        "The Under - Cipher Peon Digor's Item",
        # NEW 2026-09-03, verification pass: a second, distinct Cipher Lab pickup found alongside Digor's.
        "Cipher Lab - Meda's Ether",
        # NEW 2026-09-03: real, sourced Shadow Pokemon roster (see data/shadow_pokemon_list.json and its
        # sourcing notes -- cross-verified against Bulbapedia's List of Shadow Pokemon and Serebii's XD
        # Pokemon table). Replaces this region's old 0-location Shadow Capture placeholder set (there wasn't
        # one here before -- Outskirt Stand only had overworld items).
        "Shadow Capture - Casual Guy Cyle (Ledyba)",
        "Shadow Capture - Bodybuilder Kilen (Poochyena)",
        "Shadow Capture - Cipher Peon Resix (Houndour)",
        "Shadow Capture - Cipher Peon Browsix (Baltoy)",
        "Shadow Capture - Cipher Peon Blusix (Spheal)",
        "Shadow Capture - Cipher Peon Yellosix (Mareep)",
        "Shadow Capture - Cipher Peon Purpsix (Gulpin)",
        "Shadow Capture - Cipher Peon Greesix (Seedot)",
        "Shadow Capture - Cipher Peon Nexir (Spinarak)",
        "Shadow Capture - Cipher Peon Solox (Numel)",
        "Shadow Capture - Cipher R&D Klots (Shroomish)",
        "Shadow Capture - Cipher Peon Cabol (Carvanha)",
        "Shadow Capture - Cipher Admin Lovrina (Delcatty)",
        "Shadow Capture - Hordel (Togepi)",
        "Shadow Capture - Wanderer Miror B. (Dragonite)",
    ],
    "Phenac City": [
        "Phenac City - Stadium Item",
        "Phenac City - Cologne's Item",
        # REPLACED 2026-09-03: real, sourced roster (see above) replaces the single generic placeholder.
        "Shadow Capture - Cipher Peon Exinn (Snorunt)",
        "Shadow Capture - Cipher Peon Gonrag (Pineco)",
        "Shadow Capture - Cipher Peon Eloin (Natu)",
        "Shadow Capture - Cipher Peon Fasin (Roselia)",
        "Shadow Capture - Cipher Peon Fostin (Meowth)",
        "Shadow Capture - Cipher Peon Greck (Swinub)",
        "Shadow Capture - Cipher Peon Ezin (Spearow)",
        "Shadow Capture - Cipher Peon Faltly (Grimer)",
        "Shadow Capture - Cipher Peon Egrog (Seel)",
        "Shadow Capture - Cipher Admin Snattle (Lunatone)",
        # NEW 2026-09-03 (Bulbapedia walkthrough Part 4)
        "Phenac City - Behind the House",
        "Phenac City - Shop Ledge",
        # RENAMED 2026-09-03 per verification: this is an NPC-given Music Disc fetch-quest item, not a box.
        "Phenac City - Pre-Gym Building (Music Disc)",
    ],
    "Pyrite Town": [
        "Pyrite Town - Duel Square Item",
        "The Under - Hidden Item",
        # REPLACED 2026-09-03: real, sourced roster (see the Outskirt Stand block's note above).
        "Shadow Capture - Wanderer Miror B. (Voltorb)",
        "Shadow Capture - Cipher Peon Torkin (Makuhita)",
        "Shadow Capture - Cipher Peon Mesin (Vulpix)",
        "Shadow Capture - Cipher Peon Labor (Duskull)",
        "Shadow Capture - Cipher Peon Feldas (Ralts)",
        "Shadow Capture - Cipher Cmdr. Exol (Mawile)",
        # NEW 2026-09-03 (Bulbapedia walkthrough Part 3)
        "Pyrite Town - Jailhouse Item",
        "Pyrite Town - Grand Hotel Rightmost Room",
        "Pyrite Town - Grand Hotel Center Room",
        "Pyrite Town - Grand Hotel Leftmost Room",
        "Pyrite Town - Colosseum Bridge Box",
        "Pyrite Town - ONBS Third Floor Box",
    ],
    "Realgam Tower": [
        "Realgam Tower - Colosseum Clear Reward",
        # REPLACED 2026-09-03: real, sourced roster (see the Outskirt Stand block's note above).
        "Shadow Capture - Wanderer Miror B. (Nosepass)",
        # NEW 2026-09-03 (Bulbapedia walkthrough Part 5 -- Kaminko's House and the S.S. Libra; bucketed here,
        # see module docstring's region-assignment note)
        # "Kaminko's House - Chobin's Sun Stone" REMOVED 2026-09-03: verification pass found no Sun Stone
        # anywhere in Kaminko's House in either of two independent real sources -- see
        # data/chest_verification_report.md.
        # RENAMED 2026-09-03: real item is "Jovi's diary pages" on the catwalks; no "secret base" wording
        # in any source.
        "Kaminko's House - Catwalk Diary Pages",
        "Kaminko's House - R&D Lab Basement",
        # RENAMED 2026-09-03: real item is an Iron in the entry-area box; "Hull" wasn't attested wording.
        "S.S. Libra - Entry Box (Iron)",
        "S.S. Libra - Box Puzzle Top",
        "S.S. Libra - Box Puzzle Bottom",
        # RENAMED 2026-09-03: real item is a Max Ether; "Second" was an approximate/ambiguous ordinal
        # (there are effectively 4 box-puzzle rooms in sequence).
        "S.S. Libra - Third Puzzle Box (Max Ether)",
        # SPLIT 2026-09-03: the final puzzle room actually holds two separate item boxes, not one.
        "S.S. Libra - Final Puzzle Box (Yellow Flute)",
        "S.S. Libra - Final Puzzle Box (TM Flamethrower)",
        "S.S. Libra - Bonsly's Item",
        "S.S. Libra - Bottom Right Box",
    ],
    "Agate Village": [
        "Agate Village - Eagun's Item",
        "Relic Forest - Hidden Item",
        # REPLACED 2026-09-03: real, sourced roster (see the Outskirt Stand block's note above).
        "Shadow Capture - Spy Naps (Teddiursa)",
        # NEW 2026-09-03 (Bulbapedia walkthrough Part 1)
        "Agate Village - Entry Chest",
        "Agate Village - Eagun's Cave Ball",
        "Agate Village - Eagun's Cave Potion",
    ],
    "Cipher Key Lair": [
        "Cipher Key Lair - Admin Item",
        # REPLACED 2026-09-03: real, sourced roster (see the Outskirt Stand block's note above).
        "Shadow Capture - Thug Zook (Zangoose)",
        "Shadow Capture - Cipher Peon Humah (Paras)",
        "Shadow Capture - Cipher Peon Humah (Growlithe)",
        "Shadow Capture - Cipher Peon Gorog (Shellder)",
        "Shadow Capture - Cipher Peon Lok (Beedrill)",
        "Shadow Capture - Cipher Peon Lok (Pidgeotto)",
        "Shadow Capture - Cipher Peon Targ (Tangela)",
        "Shadow Capture - Cipher Peon Targ (Butterfree)",
        "Shadow Capture - Cipher Peon Snidle (Magneton)",
        "Shadow Capture - Cipher Peon Angic (Venomoth)",
        "Shadow Capture - Cipher Peon Angic (Weepinbell)",
        "Shadow Capture - Cipher Peon Smarton (Arbok)",
        "Shadow Capture - Cipher Admin Gorigan (Primeape)",
        "Shadow Capture - Cipher Admin Gorigan (Hypno)",
        # NEW 2026-09-03 (Bulbapedia walkthrough Part 6, by floor)
        "Cipher Key Lair - 1F Center Room",
        "Cipher Key Lair - 1F Upper Left",
        "Cipher Key Lair - Jelstin's Chamber",
        "Cipher Key Lair - B1F South Room",
        "Cipher Key Lair - 2F Center Room",
        "Cipher Key Lair - 2F Bottom Left",
        "Cipher Key Lair - 2F Upper Left",
        "Cipher Key Lair - 3F Moon Door",
        "Cipher Key Lair - 3F Hallway",
        "Cipher Key Lair - 4F Hallway",
        "Cipher Key Lair - 4F Kleto's Room",
        # NEW 2026-09-03, verification pass: a whole extra floor not previously represented.
        "Cipher Key Lair - 5F Roof",
    ],
    "Citadark Isle": [
        "Citadark Isle - Pre-Boss Item",
        # REPLACED 2026-09-03: real, sourced roster (see the Outskirt Stand block's note above) -- Citadark
        # Isle is the endgame Shadow Pokemon Factory finale, so nearly every trainer here has one, matching
        # the game's own plot (36 of the real game's 83 total shadow encounters happen on this one island).
        "Shadow Capture - Navigator Abson (Golduck)",
        "Shadow Capture - Navigator Abson (Sableye)",
        "Shadow Capture - Chaser Furgy (Raticate)",
        "Shadow Capture - Chaser Furgy (Dodrio)",
        "Shadow Capture - Cipher Admin Lovrina (Farfetch'd)",
        "Shadow Capture - Cipher Admin Lovrina (Altaria)",
        "Shadow Capture - Cipher Peon Litnar (Kangaskhan)",
        "Shadow Capture - Cipher Peon Litnar (Banette)",
        "Shadow Capture - Cipher Peon Grupel (Magmar)",
        "Shadow Capture - Cipher Peon Grupel (Pinsir)",
        "Shadow Capture - Cipher Peon Kolest (Magcargo)",
        "Shadow Capture - Cipher Peon Kolest (Rapidash)",
        "Shadow Capture - Cipher Peon Petro (Hitmonlee)",
        "Shadow Capture - Cipher Peon Karbon (Hitmonchan)",
        "Shadow Capture - Cipher Peon Gefta (Lickitung)",
        "Shadow Capture - Cipher Peon Leden (Scyther)",
        "Shadow Capture - Cipher Peon Leden (Chansey)",
        "Shadow Capture - Cipher Admin Snattle (Solrock)",
        "Shadow Capture - Cipher Admin Snattle (Starmie)",
        "Shadow Capture - Cipher Admin Ardos (Electabuzz)",
        "Shadow Capture - Cipher Admin Ardos (Swellow)",
        "Shadow Capture - Cipher Admin Ardos (Snorlax)",
        "Shadow Capture - Cipher Admin Gorigan (Poliwrath)",
        "Shadow Capture - Cipher Admin Gorigan (Mr. Mime)",
        "Shadow Capture - Cipher Peon Stron (Dugtrio)",
        "Shadow Capture - Cipher Admin Eldes (Manectric)",
        "Shadow Capture - Cipher Admin Eldes (Salamence)",
        "Shadow Capture - Cipher Admin Eldes (Marowak)",
        "Shadow Capture - Cipher Admin Eldes (Lapras)",
        "Shadow Capture - Cipher Boss Greevil (Lugia)",
        "Shadow Capture - Cipher Boss Greevil (Articuno)",
        "Shadow Capture - Cipher Boss Greevil (Zapdos)",
        "Shadow Capture - Cipher Boss Greevil (Moltres)",
        "Shadow Capture - Cipher Boss Greevil (Tauros)",
        "Shadow Capture - Cipher Boss Greevil (Rhydon)",
        "Shadow Capture - Cipher Boss Greevil (Exeggutor)",
        # NEW 2026-09-03 (Bulbapedia walkthrough Part 7)
        "Citadark Isle - After Furgy",
        "Citadark Isle - Bridge Ultra Balls",
        # NEW 2026-09-03, verification pass: Citadark Isle is a large, heavily-itemized final dungeon that was
        # substantially under-represented (only 2 real boxes previously) -- filled out from the same real
        # Part 7 source used for the two above, see data/chest_verification_report.md for the per-item list.
        "Citadark Isle - 1F Right Door Room",
        "Citadark Isle - B1F After Grason",
        "Citadark Isle - 2F First Block",
        "Citadark Isle - 2F Far Right Block",
        "Citadark Isle - 3F Near Nalix",
        "Citadark Isle - 3F After Hunter",
        "Citadark Isle - 3F Past Kulig and Jargo",
        "Citadark Isle - 3F-2 Entrance",
        "Citadark Isle - 4F Hidden Room",
        "Citadark Isle - 4F Spiral Path",
        "Citadark Isle - 4F Below Spiral Path",
        "Citadark Isle - 5F Timer Balls",
        "Citadark Isle - 6F Max Ethers",
        "Citadark Isle - 6F Max Revive",
        "Citadark Isle - 6F Full Heals",
        "Citadark Isle - 6F Revives",
        "Citadark Isle - Dome 1F Corner",
        # The event location that gates the win condition (see rules.py / __init__.py completion_condition).
        "Citadark Isle - Defeat Cipher Boss",
    ],
    # Added after the story regions so neither block shifts any existing location's id_offset. See the module
    # docstring's third/fourth bullets and `create_regions_and_locations` below for why these are
    # always-included and EXCLUDED.
    "Pokemon Storage": [species.location_name_for_species(n) for n in sorted(species.NATIONAL_DEX)],
    "Shadow Pokemon Purification": [purification_location_name(n) for n in range(1, PURIFICATION_LOCATION_COUNT + 1)],
}

_ALL_LOCATIONS: dict[str, LocationData] = {}
_offset = 0
for _region, _names in LOCATIONS_BY_REGION.items():
    for _name in _names:
        _ALL_LOCATIONS[_name] = LocationData(_offset, _region)
        _offset += 1

# The final "defeat the boss" location is an event: it has no numeric id and always holds the locked
# "Victory" event item (see __init__.py). Keep it out of the real id table.
EVENT_LOCATION_NAME = "Citadark Isle - Defeat Cipher Boss"
LOCATION_TABLE: dict[str, LocationData] = {
    name: data for name, data in _ALL_LOCATIONS.items() if name != EVENT_LOCATION_NAME
}

# The one species-catch location NOT marked EXCLUDED -- see the module docstring's "One exception" note.
GUARANTEED_SPECIES_LOCATION = species.location_name_for_species(133)  # "Catch - Eevee"

LOCATION_NAME_GROUPS: dict[str, set[str]] = {
    "Shadow Captures": {name for name in LOCATION_TABLE if name.startswith("Shadow Capture")},
    "Overworld Items": {
        name for name in LOCATION_TABLE
        if not name.startswith("Shadow Capture")
        and not name.startswith("Catch - ")
        and not name.startswith("Purify ")
        and name != "Outskirt Stand - Eevee Gift"
    },
    "Species Catches": {name for name in LOCATION_TABLE if name.startswith("Catch - ")},
    "Shadow Purifications": {name for name in LOCATION_TABLE if name.startswith("Purify ")},
}


def get_location_name_to_id(base_id: int) -> dict[str, int]:
    return {name: base_id + data.id_offset for name, data in LOCATION_TABLE.items()}


def create_regions_and_locations(world) -> dict[str, Region]:
    """Creates one Region per area and populates it with its (non-event) locations, respecting shuffle options."""
    include_overworld = bool(world.options.shuffle_overworld_items)
    include_shadow = bool(world.options.shuffle_shadow_captures)

    regions: dict[str, Region] = {}
    for region_name in LOCATIONS_BY_REGION:
        region = Region(region_name, world.player, world.multiworld)
        for location_name in LOCATIONS_BY_REGION[region_name]:
            if location_name == EVENT_LOCATION_NAME:
                continue  # placed separately, as an event, in regions.py
            if location_name == "Outskirt Stand - Eevee Gift":
                continue  # story landmark only in this skeleton; not a shuffled check
            is_species_catch = location_name.startswith("Catch - ")
            is_purification = location_name.startswith("Purify ")
            is_shadow_capture = location_name.startswith("Shadow Capture")
            # Species-catch and purification-count locations are always included -- not gated by either
            # shuffle toggle -- since they're separate categories from what those two options control. See
            # the module docstring.
            if not is_species_catch and not is_purification:
                if is_shadow_capture and not include_shadow:
                    continue
                if not is_shadow_capture and not include_overworld:
                    continue
            loc_id = world.location_name_to_id[location_name]
            location = PokemonXDLocation(world.player, location_name, loc_id, region)
            if is_purification or (is_species_catch and location_name != GUARANTEED_SPECIES_LOCATION):
                # Never required for logic -- see the module docstring's third/fourth bullets for why this is
                # what makes shipping all 386 species and all 32 purification thresholds safe even though most
                # aren't guaranteed reachable in one XD playthrough. EXCLUDED locations still receive
                # filler/useful items and can still be checked normally; the fill algorithm just never
                # *requires* one to be reachable. Eevee is the one deliberate exception among species
                # locations, and it's species-only -- no purification-count location gets the same exception
                # (see the module docstring's fourth bullet: no single purification threshold is guaranteed
                # the way the Eevee gift is).
                location.progress_type = LocationProgressType.EXCLUDED
            region.locations.append(location)
        regions[region_name] = region
        world.multiworld.regions.append(region)
    return regions
