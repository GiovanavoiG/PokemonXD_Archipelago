"""Shared chest-location samples for tests written against the retired "Open N Chests" ladder.

ADDENDUM 174 replaced 90 cumulative-count locations with 89 per-chest ones, which broke every test that said
`chest_location_name(1)` to mean "an early chest" or `chest_location_name(CHEST_LOCATION_COUNT)` to mean "the
deepest chest". Those two ideas still exist -- they are just expressed by REGION now instead of by position in
a ladder. Resolved from the live tables rather than hardcoded, so a future re-bucketing of a room moves the
sample instead of silently testing the wrong thing.
"""
from __future__ import annotations

from .. import locations


def _first_chest_in(region_name: str) -> str:
    """The first chest in a region that CAN hold progression.

    ADDENDUM 386 skips the shiny chests. Every caller here means "a representative chest", and a location
    that fill refuses to require is not representative -- the Cipher Key Lair's first chest happens to be
    chest 42, a shiny one, so without this skip the "a chest can hold progression" test starts failing on a
    sample that was never the point."""
    for name, region in locations.CHEST_LOCATION_TO_REGION.items():
        if region == region_name and name not in locations.FILLER_ONLY_CHEST_LOCATIONS:
            return name
    raise AssertionError(f"no progression-eligible chest location in region {region_name!r} -- "
                         "chest_regions.py changed, or the whole region went filler-only?")


# A chest behind the whole key-item chain AND the Robo Kyogre parts. The ladder's top threshold meant this.
DEEPEST_CHEST = _first_chest_in("Citadark Isle")

# A chest in one of the four always-open starting regions. The ladder's "Open 1 Chests" meant this.
EARLIEST_CHEST = _first_chest_in("Pokemon HQ Lab")

# A LATE chest that is not on Citadark Isle. ADDENDUM 174 weights Citadark checks away from progression with a
# per-location roll, so DEEPEST_CHEST is usually EXCLUDED and is the wrong sample for "a chest can hold
# progression". Cipher Key Lair is the last region before Citadark, so this keeps the "deep" part without
# colliding with the roll.
DEEP_NON_CITADARK_CHEST = _first_chest_in("Cipher Key Lair")


def _samples_in_graph_order() -> "tuple[str, ...]":
    """One chest per chest-holding region, in the region graph's own order.

    This replaces the ladder sampling the sphere tests used to do. Sampling positions along a count told you
    about the model; sampling one chest per region, in graph order, tells you about the map -- and it is the
    right shape for the monotonicity property those tests actually care about (a later region's chest must
    never open before an earlier region's)."""
    from .. import regions

    first_by_region: "dict[str, str]" = {}
    for name, region in locations.CHEST_LOCATION_TO_REGION.items():
        first_by_region.setdefault(region, name)
    return tuple(
        first_by_region[region] for region in regions.REGION_NAMES if region in first_by_region
    )


CHEST_SAMPLES_IN_GRAPH_ORDER = _samples_in_graph_order()
