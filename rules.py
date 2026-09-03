"""
Access rules for individual locations (region-level gating lives in regions.py's entrance rules instead, since
that's the shared/common case here -- most of this skeleton's locations only need their parent region to be
reachable, which the World API doc notes is checked implicitly).

STATUS: skeleton. Only one example item-gated location rule is included, to demonstrate the
worlds.generic.Rules.set_rule / add_rule pattern from docs/world api.md. Real per-location logic (e.g. which
Shadow Pokemon captures require specific badges/items to legally challenge) should be filled in once the
location roster itself is finalized.
"""

from worlds.generic.Rules import set_rule


def set_all_rules(world) -> None:
    # Example: the Realgam Tower colosseum clear reward requires a Master Ball to be logically expected
    # (illustrative only -- not necessarily true of the real game).
    location_name = "Realgam Tower - Colosseum Clear Reward"
    try:
        location = world.multiworld.get_location(location_name, world.player)
    except KeyError:
        return  # location wasn't created (e.g. shuffle_overworld_items disabled)

    set_rule(location, lambda state: state.has("Master Ball", world.player))
