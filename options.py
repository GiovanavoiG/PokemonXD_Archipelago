"""
Player options for the Pokemon XD: Gale of Darkness apworld.

Every docstring below is the tooltip the player reads in the YAML template and on the website, and
`data/reference_template.yaml` is compared against them byte-for-byte -- edit one and that test tells you.
"""

from dataclasses import dataclass

from Options import Choice, DeathLink, DefaultOnToggle, PerGameCommonOptions, Range, Toggle


class RandomizeShadowSpecies(DefaultOnToggle):
    """
    Shuffles all of the shadow pokemon in the game into different pokemon - can be any in the game.
    Use !shadowdex to check what they were shuffled into/check locations.
    """

    display_name = "Randomize Shadow Species"



class RandomizeChests(DefaultOnToggle):
    """
    Randomize every chest in the game to hold an AP item instead of its regular contents.
    """

    display_name = "Randomize Chests"


class ShuffleTrainerDefeats(DefaultOnToggle):
    """
    Shuffle trainer defeats as checks into the multiworld. Check below setting for options.
    """

    display_name = "Shuffle Trainer Defeats"


class TrainerDefeatMode(Choice):
    """
    Cumulative or Unique Trainer Defeats.

    **Cumulative** : defeating any trainer advances one
    shared counter, so the checks are "Defeat 1 Trainers" ... "Defeat X Trainers" (X set by Trainer Defeat
    Check Count below), plus 66 "Defeat - {trainer}" locations for story trainers.
    CUMULATIVE WITH LOCATION SHUFFLE IS PRONE TO SOFTLOCK DUE TO HOW REMATCHES WORK.
    IF YOU LOCATION SHUFFLE + CUMULATIVE, KEEP THE NUMBER OF DEFEATS LOW IN THE SETTING IN THE YAML.

    **Unique**: one check per named trainer in the game. Recommended.
    """

    display_name = "Cumulative or Unique Trainer Defeats"
    option_cumulative = 0
    option_unique = 1
    default = 1


class ProgressionLocations(Choice):
    """
    Which checks are allowed to hold a progression or useful item.

    **World checks** (1): chests, trainer defeats (cumulative and unique) and shop purchases

    **Everything** (2, default): also opens up purifications and species catches (recommended). See more options below.
    """

    display_name = "Checks That Can Hold Progression"
    # `option_overworld_only = 0` is gone. It restricted progression to the 81 "Overworld Items" locations, of
    # which 65 had no client detector at all -- hand-compiled field-item names duplicating the per-chest
    # locations (game_data/overworld_item_census.py). Retiring the 52 provable duplicates left 29, too few to
    # hold the progression pool, and __init__.py's capacity check rejected it outright. Ids are NOT renumbered
    # -- world_checks stays 1, everything stays 2 -- so existing yamls keep working; one still naming
    # `overworld_only` now fails with AP's unknown-value error, which is correct.
    option_world_checks = 1
    option_everything = 2
    default = 2


class PurificationProgressionCap(Range):
    """
    How many of the "Purify N Shadow Pokemon" checks are allowed to hold a progression or useful item.

    IF YOU DO NOT PLAN TO CATCH EVERY SHADOW POKEMON, KEEP THIS RELATIVELY LOW OR YOU WILL LOCK YOURSELF.
    You can use /mirorforce {pyrite, realgam, oasis, rock, cave} to spawn Miror B in these locations, once you have the radar and one of the locations.
    There are 83 + your shadow expansion setting (below) purifications available.
    A higher number means you may have to purify more pokemon to progress.
    Default is 30.
    """

    display_name = "Purification Checks That Can Hold Progression"
    range_start = 0
    range_end = 127
    default = 30


class TrainerDefeatCheckCount(Range):
    """
    Only meaningful when Shuffle Trainer Defeats is on with setting Cumulative. Defaults off.

    If you choose 114, you will need to battle nearly every trainer the moment they are accessible.
    """

    display_name = "Trainer Defeat Check Count"
    range_start = 1
    # Capped at 114 rather than all 232: thresholds 114-205 land in the Mt. Battle bucket of rules.py's weight
    # table, which would park progression behind an optional 92-battle grind the generator cannot know is
    # optional. 114 is exactly where that bucket starts.
    range_end = 114
    default = 100


class ShuffleTrainerMovesets(DefaultOnToggle):
    """
    If enabled, every ordinary (non-Shadow) trainer Pokemon's 4 moves are reassigned at random, restricted to
    moves that species could plausibly know by its level (drawn from its real level-up learnset, filtered to
    entries at or below its level -- so a low-level Pokemon never ends up with a high-level move). This
    applies AFTER trainer-team species reassignment, so a trainer whose Pokemon was swapped to a different
    species gets a moveset appropriate for the NEW species, not its original one.

    Shadow Pokemon's first 4 moves will be whatever they took the place of - may change in future, but gives a couple 
    illegal moves for fun.
    """

    display_name = "Shuffle Trainer Movesets"


class ShadowPokemonExpansion(Range):
    """
    Adds this many BRAND-NEW Shadow Pokemon to the game, on top of the 83 vanilla ones -- real trainers each
    gain one or more extra team members that are Shadow Pokemon (Shadow-only moves included), the same
    as any vanilla Shadow encounter.

    Trainers with at least one empty slot have a chance of receiving a shadow pokemon.

    The real disc format has room for exactly 44 new Shadow Pokemon and no more (128 total Shadow Pokemon slots
    in the game's data, 83 already used by the vanilla roster, 1 reserved) -- this is a hard ceiling, not a
    tuning choice, so 44 is both the default maximum and the highest this can be set to. 0 (the default) turns
    this off entirely and leaves every trainer's team exactly as vanilla/however other options left it.

    Each new Shadow Pokemon's level matches its trainer's own team (their average level, rounded),
    and its moves are drawn from that species' real level-up learnset at that level,
    same as Shuffle Trainer Movesets already does for ordinary Pokemon.

    Highly recommended to turn on! Miror B rematching also works to catch these if you defeat them.
    """

    display_name = "Shadow Pokemon Expansion"
    range_start = 0
    range_end = 44  # the real, disc-format-level ceiling -- see randomizer/shadow_expansion.py's module docstring
    default = 44


class EnhancedDifficulty(Choice):
    """
    How many EXTRA (ordinary, non-Shadow) Pokemon get added to real trainers' teams.

    Off: nobody's team is padded.
    Up to one additional pokemon: at most one extra member per trainer.
    Up to two additional pokemon: at most two.
    Fill enemy team: every remaining slot, up to a full team of six.

    Early trainers are balanced to be beatable.

    "Up to" is literal in both directions -- a trainer with fewer free slots than your setting only gets what
    it has room for, and nobody ever loses an existing member or ends up with more than six.

    Level scaling is a separate option below -- this one only adds Pokemon.

    This is completely separate from, and works independently of, Shadow Pokemon Expansion above -- Enhanced
    Difficulty only ever adds ORDINARY Pokemon (never a Shadow Pokemon, never touching Shadow Pokemon
    Expansion's own 44-slot capacity), so the two can be turned on together, or either one alone, with no
    interaction between them.
    """

    display_name = "Enhanced Difficulty"
    option_off = 0
    option_up_to_one_additional_pokemon = 1
    option_up_to_two_additional_pokemon = 2
    option_fill_enemy_team = 3
    default = 0


class EnhancedDifficultyLevelScaling(Toggle):
    """
    If enabled, every real trainer's existing team member has its level multiplied by 1.33x and rounded down.

    Independent of the team padding above: you can scale levels without adding a single Pokemon, pad teams
    without touching levels, or do both. With this off, any Pokemon added by the setting above joins at its
    trainer's own average level instead of a boosted one.
    """

    display_name = "Enhanced Difficulty Level Scaling"


class DisableMoveAnimations(Toggle):
    """
    Turns off every move's battle animation. Attacks resolve instantly, with the message and the damage but no
    animation, which makes a long playthrough substantially shorter.

    Definitely removes a lot of the soul, but shortens time SIGNIFICANTLY.
    """

    display_name = "Disable Move Animations"


class ExperienceRate(Range):
    """
    EXP gain rate, in percentage. Reduces the need for grinding.

    Up to 700% this is exact, because it changes the divisor in the game's own experience formula. Above that
    the species tables make up the difference and a little is lost to rounding: 1000% lands at about 991%.
    """

    display_name = "Experience Rate (%)"
    range_start = 100
    range_end = 1000
    default = 100


class MaxCatchRate(Toggle):
    """
    Makes catches guaranteed. Might have some exceptions (?) but I haven't found any - let me know if you find pokemon this doesn't work on.
    """

    display_name = "Max Catch Rate"


class PathLevelScaling(Toggle):
    """
    For use with Location Shuffle. Scales trainers to match the level curve of the original game,
    regardless of the order you unlock locations. Intended early areas are scaled to lower levels,
    and intended later areas are scaled higher.

    Stacks with Enhanced Difficulty Level Scaling: this sets the base level, and that multiplies it.
    Recommended.
    """

    display_name = "Scale Trainer Levels By Intended Path"


class ExcludeMtBattleTrainers(DefaultOnToggle):
    """
    Excludes Mt Battle from enhanced difficulty -- no extra team members and no level multiplier.
    Also excludes Mt Battle trainers from checks.

    Path Level Scaling is a separate option and still applies to Mt Battle when this is on.
    Recommended "true" to exclude, unless you're doing a Mt Battle goal.
    """

    display_name = "Exclude Mt. Battle Trainers"


class KeyItemShuffle(DefaultOnToggle):
    """
    Shuffles key items into the pool. Will remove them from your inventory if you're not supposed to have them,
    and will add them to your inventory upon receiving them in Archipelago.

    The nine items that actually gate something: Machine Part, Data ROM, ID Card, Music Disc, Mayor's Note, Elevator Key,
    System Lever, and the Robo Kyogre Parts. Two are excluded from the shuffle even when this is on:

      * **Elevator Key** -- taking it out of its vanilla chest (79, Phenac Colosseum)
        can leave you locked in the room.
      * **Gonzap's Key** -- the container it opens is not in the game's treasure table at all, so it gates no AP
        location and is left vanilla rather than shuffled into a pool where it would do nothing.
    """

    display_name = "Key Item Shuffle"


class ShadowCatchProgression(Toggle):
    """
    Whether "Catch - {species}" checks may hold a progression or useful item. OFF by default.

    PLEASE only turn on if you plan on trying to catch every shadow pokemon as they come up.
    Currently, with location shuffle on, this can lock you unless you have access to Miror B and Pyrite town/poke spots
    In vanilla, this setting SHOULD work so long as you're careful to catch every shadow pokemon.
    You can use /mirorforce {pyrite, realgam, oasis, rock, cave} to spawn Miror B in these locations, once you have the radar and one of the locations.
    """

    display_name = "Shadow Pokemon Catch Checks Can Hold Progression"


class CitadarkProgressionChance(Range):
    """
    The percentage of Citadark Isle checks left eligible to hold progression or useful items. The rest are
    marked EXCLUDED -- filler only -- and WHICH ones are chosen varies per seed rather than being a fixed list.

    The higher the number, the more items can be locked behind Citadark.
    Recommended at 0 (Citadark is all filler) or 10 (SOME progressive items can be gated in Citadark, unlikely)
    """

    display_name = "Citadark Progression Chance"
    range_start = 0
    range_end = 100
    default = 10


class RandomizeTravelLocations(Toggle):
    """
    If enabled, 11 of this game's travel destinations become receivable AP items
    ("Travel Unlock - {name}"): Snagem Hideout, Outskirt Stand, Poke Spots, Pyrite Town, Phenac City,
    Realgam Tower, Cipher Key Lair, Cipher Lab, Mt. Battle, SS Libra and Orre Colosseum.

    WARNING - THIS IS EXTREMELY EXPERIMENTAL. EXPECT SOFTLOCKS.
    This is my ideal setting to run this game with. HOWEVER, it's hard to test completely, and very complicated.
    Please only use this in groups that are okay with experimental games/issues.
    """

    display_name = 'Randomize Travel Locations/Location Shuffle'


class RandomizeShops(DefaultOnToggle):
    """
    Replaces every item in shops (except Scents and Poke Snacks) with AP Items.
    Each shop has its own unique checks - AP Items are priced by category, filler costing 100, useful 500, and progressive 1500.
    Recommended ON/true.
    """

    display_name = "Randomize Shops"


class RoboKyogrePartsUnlockCitadark(DefaultOnToggle):
    """
    Gate Citadark Isle behind collecting Robo Kyogre Parts.

    Adds maguffin item to the pool - upon acquiring your set amount, Gateon Port will gain the Robo Kyogre.
    This will allow you to ride to Citadark and complete the final dungeon/game, regardless of story progress.

    On by default.
    """

    display_name = "Robo Kyogre Parts Unlock Citadark Isle"


class RoboKyogrePartsRequired(Range):
    """
    How many Robo Kyogre Parts are needed to reach Citadark Isle.

    Only meaningful when "Robo Kyogre Parts Unlock Citadark Isle" is on. Must be no greater than
    "Robo Kyogre Parts Available" below -- generation fails if it is, rather than producing a seed that
    cannot be finished.
    """

    display_name = "Robo Kyogre Parts Required"
    range_start = 1
    range_end = 20
    default = 8


class RoboKyogrePartsAvailable(Range):
    """
    How many Robo Kyogre Parts exist in the multiworld.

    More copies = easier time clearing the game. Less = harder.
    """

    display_name = "Robo Kyogre Parts Available"
    range_start = 1
    range_end = 40
    default = 12


class Goal(Choice):
    """
    Defeat Greevil: Goal is complete upon defeating Greevil (the second time) on Citadark Isle.
    Win Mt Battle: Defeat the final trainer on Mt Battle. Recommended with Enhanced Difficulty ON and Exclude Mt Battle OFF.
    """

    display_name = "Goal"
    option_defeat_greevil = 0
    option_win_mt_battle = 1
    default = 0



class ShuffleScooterUpgrade(Toggle):
    """
    Puts the SS Libra's scooter upgrade into the multiworld as an item ("Scooter Upgrade"). OFF by default.

    SS Libra is really two places behind one map icon: the STRANDED first visit, and the REAL ship you board
    after Makan upgrades your scooter in Gateon. With this on, that upgrade stops being something the story
    hands you and becomes something the multiworld sends.

    Three things happen while you do not hold it:

      * the SS Libra icon takes you to the stranded ship, whatever your story progress says;
      * the Gateon cutscene that would grant the upgrade is allowed to play, and then the story is held just
        below it, so the game cannot give you what the item is for;
      * logic knows all of this, so nothing you need is ever placed past the ship without the item.

    HOW MUCH THIS GATES DEPENDS ON THE OTHER OPTION. With Randomize Travel Locations ON, it gates the SS Libra
    and nothing else -- the Outskirt Stand, Snagem Hideout, both Key Lair tiers and Citadark Isle are all
    reachable without it. With travel randomization OFF you walk the story,
    the ship is a chokepoint on the way to the Cipher Key Lair, and all of those ARE behind this item --
    so a seed that places it late holds you at the scooter errand for a long time.

    The in-game half works the same either way: the icon takes you to the stranded ship and the story is held
    below the upgrade until the item arrives, whichever mode you are in.
    """
    display_name = "Shuffle Scooter Upgrade"



# Filler categories: one Range each so every category shows up on its own in the options page, with 0 meaning
# "not allowed". The categories are items.FILLER_CATEGORIES and the defaults match
# items.FILLER_CATEGORY_DEFAULT_WEIGHTS -- a test holds the two together.


class FillerWeightPokeBalls(Range):
    """
    Filler weight for Poke Balls: Every ball, singles and the 10 Poke Balls / 5 Great Balls / 3 Ultra Balls bundles.
    Weights are relative shares of the filler pool (all ten add up to 100 by default). 0 = never appears.
    """

    display_name = "Filler Weight: Poke Balls"
    range_start = 0
    range_end = 100
    # 43, not 45: two points went to the `currency` category. A test holds this against
    # items.FILLER_CATEGORY_DEFAULT_WEIGHTS so the pair cannot drift.
    default = 43


class FillerWeightMedicine(Range):
    """
    Filler weight for Medicine: Potions, revives, PP restorers, drinks, herbs and Rare Candy -- everything that heals except the single-status cures.
    Weights are relative shares of the filler pool (all ten add up to 100 by default). 0 = never appears.
    """

    display_name = "Filler Weight: Medicine"
    range_start = 0
    range_end = 100
    default = 28


class FillerWeightStatusHeals(Range):
    """
    Filler weight for Status Heals: Antidote, Burn Heal, Ice Heal, Awakening, Parlyz Heal and Heal Powder.
    Weights are relative shares of the filler pool (all ten add up to 100 by default). 0 = never appears.
    """

    display_name = "Filler Weight: Status Heals"
    range_start = 0
    range_end = 100
    default = 2


class FillerWeightBerries(Range):
    """
    Filler weight for Berries: Held/usable berries.
    Weights are relative shares of the filler pool (all ten add up to 100 by default). 0 = never appears.
    """

    display_name = "Filler Weight: Berries"
    range_start = 0
    range_end = 100
    default = 4


class FillerWeightBattleItems(Range):
    """
    Filler weight for Battle Items: X items, Guard Spec., Dire Hit, Poke Doll and Fluffy Tail.
    Weights are relative shares of the filler pool (all ten add up to 100 by default). 0 = never appears.
    """

    display_name = "Filler Weight: Battle Items"
    range_start = 0
    range_end = 100
    default = 2


class FillerWeightTreasure(Range):
    """
    Filler weight for Treasure: Sellables -- Nugget, Pearls, Stardust, Star Piece, Mushrooms.
    Weights are relative shares of the filler pool (all ten add up to 100 by default). 0 = never appears.
    """

    display_name = "Filler Weight: Treasure"
    range_start = 0
    range_end = 100
    default = 2


class FillerWeightFlutes(Range):
    """
    Filler weight for Flutes: Blue, Yellow and Red Flute.
    Weights are relative shares of the filler pool (all ten add up to 100 by default). 0 = never appears.
    """

    display_name = "Filler Weight: Flutes"
    range_start = 0
    range_end = 100
    default = 1


class FillerWeightTMs(Range):
    """
    Filler weight for TMs: TM01-TM50.
    Weights are relative shares of the filler pool (all ten add up to 100 by default). 0 = never appears.
    """

    display_name = "Filler Weight: TMs"
    range_start = 0
    range_end = 100
    default = 12


class FillerWeightCurrency(Range):
    """
    Filler weight for Currency: 5000 Poke Coupons.
    Weights are relative shares of the filler pool (all ten add up to 100 by default). 0 = never appears.
    Poke Coupons are Mt. Battle's currency -- this is not a Bag item; the client adds it to your save
    directly, to both the spendable balance and the lifetime total the prize tiers read.
    """

    display_name = 'Filler Weight: Poke Coupons'
    range_start = 0
    range_end = 100
    default = 2


class FillerWeightEvolutionStones(Range):
    """
    Filler weight for Evolution Stones: Sun, Moon, Fire, Thunder, Water and Leaf Stone.
    Weights are relative shares of the filler pool (all ten add up to 100 by default). 0 = never appears.
    """

    display_name = "Filler Weight: Evolution Stones"
    range_start = 0
    range_end = 100
    default = 4


class PokemonXDDeathLink(DeathLink):
    """
    When another linked player dies, your whole party faints. When you white out, they die.

    HOW IT LANDS, and why it is not instant in the overworld. Pokemon XD has exactly one white-out: it lives
    in `fightEncountCheckZenmetu`, which only the battle loop calls (ADDENDUM 351). There is no code path
    that whites you out while you are walking around -- the overworld poison tick even refuses to take your
    last conscious Pokemon below 1 HP on purpose. So an incoming death sets every party member to 0 HP, and
    the game resolves it the way it resolves any wipe: in a battle, immediately, with the real heal, the real
    money penalty and the real warp; out of one, the moment you next enter a battle, which you then lose.

    Your own white-outs send a death. One caused by an incoming death does not send one back.
    """

    display_name = "Death Link"


class AgateVillagePitStop(Toggle):
    """
    Agate Village's shop sells real supplies instead of AP Items: Poke Balls, Great Balls, Ultra Balls,
    Potions, Super Potions, Hyper Potions and Full Heals from the start, plus Revives after its first restock
    and Max Potions after its second. Its Scents stay where they are.

    Agate's shop checks are removed from the seed. Only does anything with Randomize Shops on -- with it off,
    every shop already sells its normal items.
    """

    display_name = "Agate Village Pit Stop"


@dataclass
class PokemonXDOptions(PerGameCommonOptions):
    # ORDER MATTERS: Options.generate_yaml_templates emits the template in exactly this order, and that
    # template is the player's own curated YAML. Reordering these lines reorders their file.
    randomize_shadow_species: RandomizeShadowSpecies
    randomize_chests: RandomizeChests
    shuffle_trainer_defeats: ShuffleTrainerDefeats
    trainer_defeat_mode: TrainerDefeatMode
    trainer_defeat_check_count: TrainerDefeatCheckCount
    progression_locations: ProgressionLocations
    purification_progression_cap: PurificationProgressionCap
    shadow_pokemon_expansion: ShadowPokemonExpansion
    robo_kyogre_parts_unlock_citadark: RoboKyogrePartsUnlockCitadark
    robo_kyogre_parts_required: RoboKyogrePartsRequired
    robo_kyogre_parts_available: RoboKyogrePartsAvailable
    shuffle_trainer_movesets: ShuffleTrainerMovesets
    enhanced_difficulty: EnhancedDifficulty
    enhanced_difficulty_level_scaling: EnhancedDifficultyLevelScaling
    path_level_scaling: PathLevelScaling
    experience_rate: ExperienceRate
    disable_move_animations: DisableMoveAnimations
    max_catch_rate: MaxCatchRate
    exclude_mt_battle_trainers: ExcludeMtBattleTrainers
    randomize_travel_locations: RandomizeTravelLocations
    key_item_shuffle: KeyItemShuffle
    shuffle_scooter_upgrade: ShuffleScooterUpgrade
    shadow_catch_progression: ShadowCatchProgression
    citadark_progression_chance: CitadarkProgressionChance
    randomize_shops: RandomizeShops
    agate_village_pit_stop: AgateVillagePitStop
    goal: Goal
    death_link: PokemonXDDeathLink
    filler_weight_poke_balls: FillerWeightPokeBalls
    filler_weight_medicine: FillerWeightMedicine
    filler_weight_status_heals: FillerWeightStatusHeals
    filler_weight_berries: FillerWeightBerries
    filler_weight_battle_items: FillerWeightBattleItems
    filler_weight_treasure: FillerWeightTreasure
    filler_weight_flutes: FillerWeightFlutes
    filler_weight_tms: FillerWeightTMs
    filler_weight_evolution_stones: FillerWeightEvolutionStones
    filler_weight_currency: FillerWeightCurrency
