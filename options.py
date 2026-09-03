"""
Player options for the Pokemon XD: Gale of Darkness apworld.

STATUS: skeleton. Kept intentionally small (two options) to demonstrate the options.py pattern from
docs/world api.md / options api.md; a real release would likely add far more (e.g. matching the breadth of
settings rotobash/pokemon-ngc-rando already exposes for its own standalone shuffling: TM/tutor move shuffling,
mart shuffling, trainer/team shuffling, Shadow Pokemon trait shuffling, Bingo card shuffling, etc.) once it's
decided which of those stay client-side "cosmetic" randomization vs. become real multiworld-tracked checks.
"""

from dataclasses import dataclass

from Options import DefaultOnToggle, PerGameCommonOptions, Toggle


class ShuffleOverworldItems(DefaultOnToggle):
    """
    If enabled, overworld item locations (chests, NPC gifts, found items) are included as checks and can hold
    any item from the multiworld.
    """

    display_name = "Shuffle Overworld Items"


class ShuffleShadowCaptures(DefaultOnToggle):
    """
    If enabled, defeating/snagging a Shadow Pokemon from a Cipher Peon or Admin counts as a check and can award
    any item from the multiworld. This does not affect which Shadow Pokemon species you actually catch there.
    """

    display_name = "Shuffle Shadow Pokemon Captures"


class TrapChance(Toggle):
    """
    If enabled, some filler items in the pool may be replaced with traps (currently just a minor
    Itemfinder-disabling trap) instead of always being helpful/neutral junk.
    """

    display_name = "Include Traps"


@dataclass
class PokemonXDOptions(PerGameCommonOptions):
    shuffle_overworld_items: ShuffleOverworldItems
    shuffle_shadow_captures: ShuffleShadowCaptures
    include_traps: TrapChance
