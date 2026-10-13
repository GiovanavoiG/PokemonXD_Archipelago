"""ADDENDUM 489 -- where each trainer-defeat check is fought, in its hint.

Player: "Can you make it so the trainer checks/defeat hints show their location, like the catch hints?"

Same channel as `catch_sources`: `World.extend_hint_information`, the text AP shows beside the location in hints and
the spoiler.

  * `Defeat - X` / `Defeat - X #N`: the location's own region -- the one its logic uses, so the hint and the rule
    never disagree.
  * `Defeat X (Any)`: it fires on whichever of that trainer's fights the player wins, so every area those fights are
    in, the logic's (anchor) region first. Fights the player only watches (Zook and Ardos at Gateon, Biden at the Key
    Lair -- `missable_indices.NON_PLAYER_FIGHT_INDICES`) and post-game rows with no region are left out.
  * The cumulative `Defeat N Trainers` checks are counts, not places: no text.
"""
from __future__ import annotations

from typing import Any

# Buckets the rules treat as always open; a check parked in one has no place to name.
_NO_PLACE_REGIONS = frozenset({"Trainer Defeat Count", "Unique Trainer Defeats", "Menu"})


def _fight_regions_by_surname() -> "dict[str, list[str]]":
    """SURNAME -> the regions of the fights the player can fight, in roster order, deduplicated."""
    from .game_data import trainer_placements, trainer_roster
    from .game_data.missable_indices import NON_PLAYER_FIGHT_INDICES

    out: "dict[str, list[str]]" = {}
    for trainer in sorted(trainer_roster.TRAINERS, key=lambda t: t["index"]):
        index = trainer["index"]
        if index in NON_PLAYER_FIGHT_INDICES:
            continue
        region = trainer_placements.region_for(index)
        bucket = out.setdefault(str(trainer["name"]).upper(), [])
        if region and region not in bucket:
            bucket.append(region)
    return out


def defeat_hint_texts(world: Any) -> "dict[str, str]":
    """Location name -> where it is fought, for every trainer-defeat check this seed created."""
    from .game_data import repeatable_trainers as rt

    prefix, suffix = rt.LOCATION_NAME_PREFIX, rt.LOCATION_NAME_SUFFIX
    regions_by_surname = _fight_regions_by_surname()
    out: "dict[str, str]" = {}
    for location in world.multiworld.get_locations(world.player):
        name = location.name
        if location.address is None or not name.startswith(prefix):
            continue
        is_any = name.endswith(suffix)
        if not is_any and not name.startswith("Defeat - "):
            continue                                   # "Defeat N Trainers": a count, not a place
        own = location.parent_region.name if location.parent_region is not None else None
        places = [own] if own and own not in _NO_PLACE_REGIONS else []
        if is_any:
            surname = name[len(prefix):-len(suffix)].upper()
            places += [r for r in regions_by_surname.get(surname, ()) if r not in places]
        if places:
            out[name] = " or ".join(places)
    return out
