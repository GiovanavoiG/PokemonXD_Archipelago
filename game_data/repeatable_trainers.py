"""One progression-eligible "(Any)" check per re-fightable trainer.

Every individual occurrence of a re-fightable trainer is either missable or post-game (its `final` row carries
region `None`), so none can hold progression and all 24 named `Defeat -` locations for these trainers stay
excluded. An "(Any)" check is earned by the first of that trainer's fights the player wins, so it cannot be
missed while any occurrence remains; 31 of the 35 have an in-game, non-missable occurrence to anchor to.

The anchor is derived -- the earliest occurrence that is both non-missable and regioned, which excludes the
post-game block by construction -- and its requirements come with it. Too early is the dangerous direction:
it lets Fill treat the check as available in a sphere the player cannot reach it in. Biden, Equin, Eroll and
Willie have no such occurrence and are always filler, as is Greevil, whose last Citadark fight is the goal.
"""
from __future__ import annotations

from .census_repeat_column import CENSUS_REPEAT_AND_MISSABLE as _WORKBOOK
from .missable_indices import WORKBOOK_MISSABLE_OVERRULED

# ADDENDUM 436: the workbook's columns, with the "not missable" overrides applied (Biden #1).
CENSUS_REPEAT_AND_MISSABLE = {
    index: (repeat, missable and index not in WORKBOOK_MISSABLE_OVERRULED)
    for index, (repeat, missable) in _WORKBOOK.items()
}
from .trainer_placements import PLACEMENTS
from .trainer_roster import TRAINERS_BY_INDEX

LOCATION_NAME_PREFIX = "Defeat "
LOCATION_NAME_SUFFIX = " (Any)"

# Surnames that get a location like everyone else but are never progression-eligible; the string beside each
# is why. Biden, Equin, Eroll and Willie are derivable -- the fence below would refuse to import without them.
# The rest are judgement calls.
ALWAYS_FILLER_SURNAMES: "dict[str, str]" = {
    # Aferd, Laken and Hebon left this list: the client patches their scripts so each always battles when talked to,
    # so their (Any) can never be missed. Note that all 35 anchors sit in
    # `missable_trainers.FILLER_ONLY_TRAINER_INDICES` by construction, so membership there proves nothing.
    # Both anchors are census-safe, so the fence would not have caught these.
    "ARDOS": "always filler (ADDENDUM 308)",
    "ZOOK": "always filler (ADDENDUM 308)",
    # ADDENDUM 457: Miror B. leaves if you lose to him, so every Miror B. check is filler.
    "MIROR B.": "always filler (ADDENDUM 457) -- he leaves if you lose to him",
    # BIDEN left this list in ADDENDUM 436: his Snagem Hideout fight is not missable, and it is his one check.
    "EQUIN": "only non-missable occurrence is post-game",
    "EROLL": "only non-missable occurrence is post-game",
    "WILLIE": "always filler (ADDENDUM 460): unmissable, but not made progression-eligible",
    "GREEVIL": "every occurrence is Citadark Isle and the last one is the goal fight",
}


# surname -> the occurrence its (Any) check anchors to, for fights whose reachable occurrence the census
# cannot express. Empty since `trainer_placements.PLACEMENT_REGION_OVERRIDES` un-swapped Biden's two rows and
# the derivation picked the Snagem Hideout fight by itself; the mechanism stays for a fight that needs it.
#
# ADDENDUM 436: Ardos's derived anchor was his Gateon fight, which the player only watches. His check comes from
# Citadark Isle (`missable_indices.SINGLE_CHECK_FIGHTS`).
ANCHOR_OVERRIDES: "dict[str, int]" = {"ARDOS": 193}

# A trainer whose (Any) can be won in more than one place, either of which is enough. The location parks in the
# always-open bucket and its rule asks for any one of these regions. Miror B. is met at the Poke Spots or at the
# Outskirt Stand.
ANY_OF_REGIONS: "dict[str, tuple[str, ...]]" = {"MIROR B.": ("Poke Spots", "Outskirt Stand")}
ANY_OF_BUCKET_REGION = "Unique Trainer Defeats"


def display_surname(raw: str) -> str:
    """The census stores surnames upper-case. `MIROR B.` -> `Miror B.`, `BLUSIX` -> `Blusix`."""
    return raw.title()


def location_name(raw_surname: str) -> str:
    return f"{LOCATION_NAME_PREFIX}{display_surname(raw_surname)}{LOCATION_NAME_SUFFIX}"


def _build():
    placements = dict(PLACEMENTS)
    occurrences: "dict[str, list[int]]" = {}
    for index in sorted(CENSUS_REPEAT_AND_MISSABLE):
        entry = TRAINERS_BY_INDEX.get(index)
        if entry:
            occurrences.setdefault(entry["name"], []).append(index)

    rows = []
    for surname, indices in sorted(occurrences.items()):
        if not any(CENSUS_REPEAT_AND_MISSABLE[i][0] == "final" for i in indices):
            continue   # fought once, or never re-fightable -- nothing to add
        regioned = [i for i in indices if placements.get(i) and placements[i].region]
        safe = [i for i in regioned if not CENSUS_REPEAT_AND_MISSABLE[i][1]]
        anchor_pool = safe or regioned
        if not anchor_pool:
            # No in-game occurrence at all. Nothing in the census hits this today; if one ever does it must be
            # decided explicitly rather than given a guessed region -- a wrong region is an unwinnable seed.
            continue
        anchor = ANCHOR_OVERRIDES.get(surname, anchor_pool[0])
        placement = placements[anchor]
        rows.append({
            "surname": surname,
            "location": location_name(surname),
            "anchor_index": anchor,
            "region": ANY_OF_BUCKET_REGION if surname in ANY_OF_REGIONS else placement.region,
            "any_of_regions": ANY_OF_REGIONS.get(surname, ()),
            "required_items": tuple(placement.required_items),
            "required_regions": tuple(placement.required_regions),
            "occurrences": tuple(indices),
            "always_filler": surname in ALWAYS_FILLER_SURNAMES,
            "anchor_is_missable": CENSUS_REPEAT_AND_MISSABLE[anchor][1],
        })
    return tuple(rows)


REPEATABLE_TRAINERS: "tuple[dict, ...]" = _build()

LOCATION_NAMES: "tuple[str, ...]" = tuple(row["location"] for row in REPEATABLE_TRAINERS)

# location name -> the UPPER-CASE surname the live battle roster reports. The client matches on this.
LOCATION_TO_SURNAME: "dict[str, str]" = {row["location"]: row["surname"] for row in REPEATABLE_TRAINERS}
SURNAME_TO_LOCATION: "dict[str, str]" = {row["surname"]: row["location"] for row in REPEATABLE_TRAINERS}

# region -> [location names], for locations.py's LOCATIONS_BY_REGION.
LOCATIONS_BY_REGION: "dict[str, list[str]]" = {}
for _row in REPEATABLE_TRAINERS:
    LOCATIONS_BY_REGION.setdefault(_row["region"], []).append(_row["location"])

ALWAYS_FILLER_LOCATIONS: "frozenset[str]" = frozenset(
    row["location"] for row in REPEATABLE_TRAINERS if row["always_filler"]
)


# Assertions rather than tests: a malformed table here produces a wrong region graph, and that surfaces as an
# unwinnable seed rather than an error.
assert len(LOCATION_NAMES) == len(set(LOCATION_NAMES)), "two re-fightable trainers produced the same name"
assert len(REPEATABLE_TRAINERS) == 35, (
    f"the census has {len(REPEATABLE_TRAINERS)} re-fightable trainers, not the 35 this was built against -- "
    "re-read the workbook before changing this number"
)
# ADDENDUM 410: a lone `#1` is removed only because `(Any)` covers the same win -- so the (Any) must exist.
from .trainer_roster import ANY_DUPLICATE_DEFEAT_LOCATIONS as _ANY_DUPES, TRAINERS as _ALL, trainer_label as _lab  # noqa: E402

assert all(_t["name"].upper() in SURNAME_TO_LOCATION for _t in _ALL if _lab(_t) in _ANY_DUPES), (
    "ADDENDUM 410 removed a #1 whose surname has no (Any) location -- that fight would be no check at all"
)
# Every always-filler surname must actually BE re-fightable, or the entry is attached to nothing.
assert set(ALWAYS_FILLER_SURNAMES) <= {row["surname"] for row in REPEATABLE_TRAINERS}, (
    "ALWAYS_FILLER_SURNAMES names a trainer that is not in the re-fightable set"
)
# A missable or post-game anchor cannot hold progression, so one appearing outside the entries above fails
# the import rather than shipping a seed that can strand an item on a fight already walked past.
for _row in REPEATABLE_TRAINERS:
    if _row["anchor_is_missable"]:
        assert _row["always_filler"], (
            f"{_row['location']}'s anchor (occurrence {_row['anchor_index']}) is MISSABLE and it is not marked "
            "always-filler -- it needs an explicit entry, not a default"
        )


# An override has to name a real, regioned occurrence of its own surname.
for _surname, _index in ANCHOR_OVERRIDES.items():
    _entry = TRAINERS_BY_INDEX.get(_index)
    assert _entry is not None and _entry["name"] == _surname, (
        f"anchor override {_surname} -> {_index} does not name an occurrence of that trainer"
    )
    assert PLACEMENTS.get(_index) and PLACEMENTS[_index].region, (
        f"anchor override {_surname} -> {_index} names an occurrence with no region -- it would gate nothing"
    )
# `globals().pop`, not `del`: the table is empty, so the loop above never binds these names and a bare `del`
# would raise NameError at import.
for _name in ("_surname", "_index", "_entry"):
    globals().pop(_name, None)
del _name
