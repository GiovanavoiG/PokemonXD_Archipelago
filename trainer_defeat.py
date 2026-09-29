"""
Named ordinary-trainer defeat roster: one "Defeat - {trainer}" location per trainer with a confirmed real
display name and story placement.

Only 66 of the game's 232 ordinary trainers get a named location. `real_trainer_data.py` loads the full
byte-exact roster from data/deckdata_story_trainers.json, but that extraction only recovered each trainer's
trainer_class/name_id/string_ptr -- the text table those point into is not decoded -- so the only source of
readable names is data/trainer_census.json (68 hand-transcribed, see data/trainer_pools_SOURCES.md). Two of
those ("Shadow Lugia" and the Citadark "Final Battles" copy of Cipher Boss Greevil) are all-Shadow-team
placeholders rather than separate trainers, leaving 66. The other 166 are still detected and still counted via
locations.py's TRAINER_DEFEAT_COUNT_LOCATION_COUNT cumulative bucket, which TrainerBattleDefeatTracker awards
for every confirmed defeat whether or not a named location is queued for it.

The detection key is the trainer's `surname`, matching `ram_client.BattleRosterRecord.trainer_name` -- a
UTF-16BE surname of about 11 chars, confirmed live as "LAKEN" for Chaser Laken. The full "Cipher Peon X"
display name is never stored in that RAM structure, so the client can only match the surname. A trainer fought
more than once repeats the same surname text every time and the roster cannot say which occurrence this is, so
`ram_client.TrainerBattleDefeatTracker` dispatches each confirmed win to the next not-yet-completed location in
that surname's queue, in the order listed below -- trainer_census.json's own pool order, which is
story-chronological because it was transcribed off a walkthrough in play order.

Open question, not confirmed live: whether the battle-roster struct exposes an ordinary trainer's entire team
at once (needed for "every opposing record reads 0 HP" to mean "defeated") for a team larger than the two
Pokemon bracketed by the Chaser Laken test (Metagross + Wailmer).
"""

from __future__ import annotations

# (region, location_name, surname) for the 66 named trainers. Generated from data/trainer_census.json -- do
# not hand-edit without regenerating, since location names must stay byte-exact between generation
# (locations.py) and the live client (ram_client.py's surname lookup).
#
# All 22 Phenac entries are filed in "Phenac City (Post-Sixes)", the region whose edge already requires both
# the Music Disc and the Mayor's Note. They used to say plain "Phenac City", which is the tier the Music Disc's
# own chest sits in, so a seed could put the Disc on a Phenac trainer and gate it behind itself. The census
# rows 88-104 all carry ('Music Disc', "Mayor's Note"); seven of the 22 (Jirel, Trita, Kubara, Kuroru, Zanyu,
# Yaida, Rikoza) have no census row at all and are moved with the rest, which is the safe direction -- a check
# gated too late costs placement freedom, one gated too early costs the run.
TRAINER_DEFEAT_ROSTER: list[tuple[str, str, str]] = [
    ("Agate Village", "Defeat - Myth Trainer Eagun", "Eagun"),
    ("Outskirt Stand", "Defeat - Cipher Admin Lovrina", "Lovrina"),
    # The first Miror B. fight is behind the Cave Poke Spot, which comes before the fight even though
    # story_bytes' 0x39 -> 0x3A transition covers both. Not circular: nothing requires a Defeat location. The
    # region is the right grain -- all three spots (Rock, Oasis, Cave) carry region="Poke Spots" in
    # map_destinations and travel randomization creates one "Travel Unlock - Poke Spots" for all three, so no
    # state reaches another spot without the Cave one.
    ("Poke Spots", "Defeat - Wanderer Miror B. (1st)", "Miror B."),
    # Every Pyrite Cipher battle needs the Data ROM / ID Card AND the Poke Spots. The graph is
    # Pyrite Town --(Data ROM)--> Poke Spots --> Pyrite Town (ONBS), so filing this row there means both; plain
    # "Pyrite Town" needs only the item.
    ("Pyrite Town (ONBS)", "Defeat - Cipher Commander Exol", "Exol"),
    # Gonzap is in Snagem Hideout, behind the Elevator Key tier. This row used to open on the Machine Part
    # alone, so a progression item placed here made the seed unwinnable.
    ("Snagem Hideout", "Defeat - Snagem Head Gonzap", "Gonzap"),
    ("Phenac City (Post-Sixes)", "Defeat - Cipher Peon Exinn", "Exinn"),
    ("Phenac City (Post-Sixes)", "Defeat - Cipher Peon Gonrag", "Gonrag"),
    ("Phenac City (Post-Sixes)", "Defeat - Cipher Peon Jirel", "Jirel"),
    ("Phenac City (Post-Sixes)", "Defeat - Cipher Peon Resix", "Resix"),
    ("Phenac City (Post-Sixes)", "Defeat - Cipher Peon Purpsix", "Purpsix"),
    ("Phenac City (Post-Sixes)", "Defeat - Cipher Peon Greesix", "Greesix"),
    ("Phenac City (Post-Sixes)", "Defeat - Cipher Peon Yellosix", "Yellosix"),
    ("Phenac City (Post-Sixes)", "Defeat - Cipher Peon Browsix", "Browsix"),
    ("Phenac City (Post-Sixes)", "Defeat - Cipher Peon Trita", "Trita"),
    ("Phenac City (Post-Sixes)", "Defeat - Cipher Peon Kubara", "Kubara"),
    ("Phenac City (Post-Sixes)", "Defeat - Cipher Peon Kuroru", "Kuroru"),
    ("Phenac City (Post-Sixes)", "Defeat - Cipher Peon Zanyu", "Zanyu"),
    ("Phenac City (Post-Sixes)", "Defeat - Cipher Peon Yaida", "Yaida"),
    ("Phenac City (Post-Sixes)", "Defeat - Cipher Peon Rikoza", "Rikoza"),
    ("Phenac City (Post-Sixes)", "Defeat - Cipher Peon Eloin", "Eloin"),
    ("Phenac City (Post-Sixes)", "Defeat - Cipher Peon Fasin", "Fasin"),
    ("Phenac City (Post-Sixes)", "Defeat - Cipher Peon Fostin", "Fostin"),
    ("Phenac City (Post-Sixes)", "Defeat - Cipher Peon Greck", "Greck"),
    ("Phenac City (Post-Sixes)", "Defeat - Cipher Peon Ezin", "Ezin"),
    ("Phenac City (Post-Sixes)", "Defeat - Cipher Peon Faltly", "Faltly"),
    ("Phenac City (Post-Sixes)", "Defeat - Cipher Peon Egrog", "Egrog"),
    ("Phenac City (Post-Sixes)", "Defeat - Cipher Admin Snattle", "Snattle"),
    ("Agate Village", "Defeat - Researcher Chobin", "Chobin"),
    ("Agate Village", "Defeat - Robo Groudon (Chobin's mecha)", "Chobin"),
    # Smarton's first fight is the post-scooter-upgrade boarding, so plain "SS Libra" -- the later of the two
    # ship regions, reached after the Robo Groudon detour. "SS Libra (stranded)" is the Elevator Key tier. This
    # row used to say "Realgam Tower", a whole key item early (Data ROM vs Mayor's Note).
    ("SS Libra", "Defeat - Cipher Peon Smarton", "Smarton"),
    ("Outskirt Stand", "Defeat - Wanderer Miror B. (rematch)", "Miror B."),
    ("Outskirt Stand", "Defeat - Rider Willie", "Willie"),
    ("Citadark Isle", "Defeat - Cipher Admin Gorigan", "Gorigan"),
    ("Citadark Isle", "Defeat - Thug Zook", "Zook"),
    ("Citadark Isle", "Defeat - Cipher Peon Smarton (Factory Control Room)", "Smarton"),
    ("Citadark Isle", "Defeat - Navigator Abson", "Abson"),
    ("Citadark Isle", "Defeat - Cipher Peon Dimon", "Dimon"),
    ("Citadark Isle", "Defeat - Chaser Furgy", "Furgy"),
    ("Citadark Isle", "Defeat - Sailor Toronba", "Toronba"),
    ("Citadark Isle", "Defeat - Hunter Ransa", "Ransa"),
    ("Citadark Isle", "Defeat - Cipher Admin Lovrina (Citadark)", "Lovrina"),
    ("Citadark Isle", "Defeat - Cipher Peon Berd", "Berd"),
    ("Citadark Isle", "Defeat - Cipher Peon Litnar", "Litnar"),
    ("Citadark Isle", "Defeat - Cipher Peon Grupel", "Grupel"),
    ("Citadark Isle", "Defeat - Cipher Peon Fajo", "Fajo"),
    ("Citadark Isle", "Defeat - Hunter Ogera", "Ogera"),
    ("Citadark Isle", "Defeat - Cipher Peon Kolest", "Kolest"),
    ("Citadark Isle", "Defeat - Cipher Peon Uumo", "Uumo"),
    ("Citadark Isle", "Defeat - Chaser Carol", "Carol"),
    ("Citadark Isle", "Defeat - Rider Fego", "Fego"),
    ("Citadark Isle", "Defeat - Cipher Peon Antol", "Antol"),
    ("Citadark Isle", "Defeat - Cipher Peon Karbon", "Karbon"),
    ("Citadark Isle", "Defeat - Cipher Peon Petro", "Petro"),
    ("Citadark Isle", "Defeat - Cipher Peon Koral", "Koral"),
    ("Citadark Isle", "Defeat - Cipher Peon Akante", "Akante"),
    ("Citadark Isle", "Defeat - Cipher Peon Gefta", "Gefta"),
    ("Citadark Isle", "Defeat - Cipher Peon Leden", "Leden"),
    ("Citadark Isle", "Defeat - Cipher Admin Snattle (Citadark)", "Snattle"),
    ("Citadark Isle", "Defeat - Cipher Peon Metring", "Metring"),
    ("Citadark Isle", "Defeat - Cipher Admin Ardos", "Ardos"),
    ("Citadark Isle", "Defeat - Cipher Peon Stron", "Stron"),
    ("Citadark Isle", "Defeat - Cipher Admin Gorigan (Citadark, final)", "Gorigan"),
    ("Citadark Isle", "Defeat - Cipher Admin Eldes", "Eldes"),
    ("Citadark Isle", "Defeat - Legendary Trainer Eagun", "Eagun"),
    ("Citadark Isle", "Defeat - Wanderer Miror B. (final)", "Miror B."),
    ("Citadark Isle", "Defeat - Cipher Boss Greevil", "Greevil"),
]

# region -> [location names], in TRAINER_DEFEAT_ROSTER order -- what locations.py's LOCATIONS_BY_REGION needs.
TRAINER_DEFEAT_LOCATIONS_BY_REGION: dict[str, list[str]] = {}
for _region, _name, _surname in TRAINER_DEFEAT_ROSTER:
    TRAINER_DEFEAT_LOCATIONS_BY_REGION.setdefault(_region, []).append(_name)

# surname -> ordered queue of location names sharing it (2-3 for a trainer fought more than once). Each
# confirmed win pops the front of the matching queue. Every non-None name appears in exactly one queue; a
# `None` slot (see GREEVIL_DECOY_BATTLE_SENTINEL) is consumed by a kill but never dispatched as a location.
SURNAME_TO_LOCATION_QUEUE: dict[str, list[str | None]] = {}
for _region, _name, _surname in TRAINER_DEFEAT_ROSTER:
    SURNAME_TO_LOCATION_QUEUE.setdefault(_surname, []).append(_name)

TRAINER_DEFEAT_LOCATION_NAMES: list[str] = [name for _region, name, _surname in TRAINER_DEFEAT_ROSTER]

assert len(TRAINER_DEFEAT_LOCATION_NAMES) == len(set(TRAINER_DEFEAT_LOCATION_NAMES)), (
    "TRAINER_DEFEAT_ROSTER has a duplicate location name -- every entry must be byte-unique"
)

# Greevil is fought twice at Citadark Isle -- a one-Pokemon personal battle, then the real final battle -- and
# the roster's surname field names the trainer, not the encounter, so both read "Greevil". The sentinel holds
# queue position 0 so the decoy kill consumes it (the queue does not stall) while
# `TrainerBattleDefeatTracker.poll()` never dispatches a `None`, keeping the goal off the decoy. The real
# location keeps its exact name and frozen id; only which kill it dispatches on moves, 0 -> 1.
GREEVIL_DECOY_BATTLE_SENTINEL: None = None
SURNAME_TO_LOCATION_QUEUE["Greevil"].insert(0, GREEVIL_DECOY_BATTLE_SENTINEL)
GREEVIL_DEFEAT_LOCATION_NAME: str = next(name for name in SURNAME_TO_LOCATION_QUEUE["Greevil"] if name is not None)
