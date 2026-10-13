"""
Player options for the Pokemon XD: Gale of Darkness apworld.

Every docstring below is the tooltip the player reads in the YAML template and on the website, and
`data/reference_template.yaml` is compared against them byte-for-byte -- edit one and that test tells you.
"""

from dataclasses import dataclass

from Options import Choice, DeathLink, DefaultOnToggle, OptionGroup, PerGameCommonOptions, Range, Toggle


class RandomizeShadowSpecies(DefaultOnToggle):
    """
    Shuffles all of the shadow pokemon in the game into different pokemon - can be any in the game.
    Use /shadowdex to check what they were shuffled into/check locations.
    """

    display_name = "Randomize Shadow Species"


class ShadowInheritedMoves(Toggle):
    """
    Shadow Pokemon keep the four normal moves of the Shadow Pokemon they replaced, instead of moves their new
    species can really learn. With Randomize Shadow Species on, that means a few illegal moves for fun -- moves
    the new species could never learn, which it keeps after you snag and purify it.

    Shadow moves are not affected either way, and the extra Shadows from Shadow Pokemon Expansion replace
    nothing, so they always get legal moves. Off gives every Shadow legal moves.
    """

    display_name = "Shadow Pokemon Inherit Replaced Moves"



# ADDENDUM 404: `RandomizeChests` is gone -- every chest is always a check. See locations.py's ADDENDUM 404 note.
# A YAML that still sets `randomize_chests` generates normally: Archipelago warns about the unknown key and
# ignores it.


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
    Check Count below), and nothing else -- a tally.
    CUMULATIVE WITH LOCATION SHUFFLE IS PRONE TO SOFTLOCK DUE TO HOW REMATCHES WORK.
    IF YOU LOCATION SHUFFLE + CUMULATIVE, KEEP THE NUMBER OF DEFEATS LOW IN THE SETTING IN THE YAML.

    **Unique**: one check per named trainer in the game. Recommended.
    """

    display_name = "Cumulative or Unique Trainer Defeats"
    option_cumulative = 0
    option_unique = 1
    default = 1


# ADDENDUM 449: `progression_locations` (Checks That Can Hold Progression) is removed. Its `world_checks` setting was
# exactly Shadow Catch Progression off plus a Purification Progression Cap of 0 -- two options that already say the
# same thing -- so every seed now behaves as its old default, `everything`, and those two decide.


class PurificationChecks(DefaultOnToggle):
    """
    Make purifications checks: "Purify 1 Shadow Pokemon" up to one per Shadow Pokemon in your seed
    (83, plus however many 'Shadow Pokemon Expansion' adds).

    Off: no purification checks at all, and the cap below does nothing.
    """

    display_name = "Purification Checks"


class PurificationProgressionCap(Range):
    """
    How many of the "Purify N Shadow Pokemon" checks are allowed to hold a progression or useful item.
    Only meaningful with "Purification Checks" on.

    IF YOU DO NOT PLAN TO CATCH EVERY SHADOW POKEMON, KEEP THIS RELATIVELY LOW OR YOU WILL LOCK YOURSELF.
    You can use /mirorforce {pyrite, realgam, oasis, rock, cave} to spawn Miror B in these locations, once you have the radar and one of the locations.
    There are 83 + your shadow expansion setting purifications available.
    A higher number means you may have to purify more pokemon to progress.
    Default is 30.
    """

    display_name = "Purification Checks That Can Hold Progression"
    range_start = 0
    range_end = 127
    default = 30


class TrainerDefeatCheckCount(Range):
    """
    Only meaningful when Shuffle Trainer Defeats is on with setting Cumulative. Defaults to 100.

    If you choose 114, you will need to battle nearly every trainer the moment they are accessible.

    Logic counts each trainer once (a rematch is not a second defeat) and never counts a trainer you can miss, so
    the higher counts expect Citadark Isle's trainers. Your real tally counts every win, so in play you usually
    reach a count well before logic expects it. A count higher than logic can ever be sure of is filler-only.
    """

    display_name = "Trainer Defeat Check Count"
    range_start = 1
    # Capped at 114 rather than all 232: thresholds 114-205 land in the Mt. Battle bucket of rules.py's weight
    # table, which would park progression behind an optional 92-battle grind the generator cannot know is
    # optional. 114 is exactly where that bucket starts.
    range_end = 114
    default = 100


class ShadowPokemonExpansion(Range):
    """
    Adds this many BRAND-NEW Shadow Pokemon to the game, on top of the 83 vanilla ones -- real trainers each
    gain one or more extra team members that are Shadow Pokemon (Shadow-only moves included), the same
    as any vanilla Shadow encounter.

    Trainers with at least one empty slot have a chance of receiving a shadow pokemon.

    The real disc format has room for exactly 44 new Shadow Pokemon and no more (128 total Shadow Pokemon slots
    in the game's data, 83 already used by the vanilla roster, 1 reserved) -- this is a hard ceiling, not a
    tuning choice, so 44 is both the default and the highest this can be set to. 0 turns
    this off entirely and leaves every trainer's team exactly as vanilla/however other options left it.

    Each new Shadow Pokemon's level matches its trainer's own team (their average level, rounded),
    and its moves are drawn from that species' real level-up learnset at that level.

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

    "Up to" is literal in both directions - a trainer with fewer free slots than your setting only gets what
    it has room for, and nobody ever loses an existing member or ends up with more than six.

    Level scaling is a separate option below - this one only adds Pokemon.

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


class NoLegendaryShadows(Toggle):
    """
    No Shadow Pokemon is a legendary. With "Randomize Shadow Species" on, Shadows are never randomized into one;
    with it off, the vanilla legendary Shadows (Shadow Lugia and the three birds) become random non-legendary
    Pokemon instead. Shadow Lugia is the one exception when "Shuffle Shadow Lugia" is on.
    """

    display_name = "No Legendary Shadows"


class ShuffleShadowLugia(Toggle):
    """
    Shadow Lugia trades places with a random Shadow Pokemon, so it can turn up anywhere in the game and never at
    Greevil's first battle (Randomize Shadow Species alone leaves Lugia where it is).
    """

    display_name = "Shuffle Shadow Lugia"


class LegendaryTrainerPokemon(Toggle):
    """
    Ordinary trainers (not Shadow Pokemon) can field legendary Pokemon when their teams are randomized, including
    the extra team members Enhanced Difficulty adds. Lugia, Bonsly and Munchlax stay off every team.
    """

    display_name = "Legendary Trainer Pokemon"


class TextSpeed(Choice):
    """
    How fast text is drawn, in and out of battle. Normal is the game's own speed (holding A or B already speeds it
    up); Fast is that sped-up speed all the time; Instant draws each box at once. A box still waits for your
    button press either way.
    """

    display_name = "Text Speed"
    option_normal = 0
    option_fast = 1
    option_instant = 2
    default = 0


class HoldBToAdvance(Toggle):
    """
    Holding B advances each text box as soon as it has finished drawing, so you can hold B through dialogue
    instead of pressing a button for every box. Yes/No questions and menus still need their own press.
    """

    display_name = "Hold B To Advance"


class BattleSpeed(Choice):
    """
    How long battles pause on their messages, HP bars and experience bars. Normal is the game's own pacing;
    Fast halves the waits, Faster quarters them. Move animations are a separate option.
    """

    display_name = "Battle Speed"
    option_normal = 0
    option_fast = 1
    option_faster = 2
    default = 0


class CitadarkStoryWeight(Range):
    """
    With location shuffle off and "Robo Kyogre Parts Unlock Citadark Isle" on, Citadark Isle needs only the
    Parts. This is the chance, in percent, that the seed keeps enough of them in the late story (from the
    stranded SS Libra onward) that you finish most of the story before you can ride there. 0 lets the Parts go
    anywhere.
    """

    display_name = "Citadark Story Weight"
    range_start = 0
    range_end = 100
    default = 85


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


class PurificationRate(Range):
    """
    How fast a Shadow Pokemon's heart gauge goes down, in percentage. Battling, walking, calling it, the Day Care
    and Scents all count for this much more. Reduces the grind before a Shadow can be purified.

    Works by making each of those lower the gauge by more -- the gauges themselves are untouched. At 200% every
    Shadow is ready in about half the steps, battles and Scents. The Purify Chamber is unchanged.
    """

    display_name = "Purification Rate (%)"
    range_start = 100
    range_end = 1000
    default = 100


class CatchRateScaling(Choice):
    """
    Makes catching easier.

    Off: normal catch rates.

    Location Scaled: Shadow Pokemon are much easier to snag early on and the help tapers off as the game goes on --
    late Shadows (Citadark Isle, a legendary at the end) are still noticeably easier than vanilla, never harder. "Later"
    follows the order this seed opens areas in, so it works with Randomize Travel Locations on or off. Wild Poke Spot
    Pokemon get the highest catch rate wherever they are.

    Guaranteed Catches: every catch succeeds.
    """

    display_name = "Catch Rate Scaling"
    option_off = 0
    option_location_scaled = 1
    option_guaranteed_catches = 2
    default = 0


class RandomizeStarter(Choice):
    """
    Replaces the Eevee you start with. Off keeps Eevee; Random No Legendary picks any Pokemon that is not a
    legendary; True Random can pick anything, legendaries included. The new starter is level 10 with moves it
    can really learn, always including at least one attacking move.
    """

    display_name = "Randomize Starter"
    option_off = 0
    option_random_no_legendary = 1
    option_true_random = 2
    default = 0


class CatchRateExcludeCitadark(Toggle):
    """
    With Catch Rate Scaling on, Citadark Isle's Shadow Pokemon keep their normal catch rates.

    With Guaranteed Catches, every other catch in the game stays guaranteed.
    """

    display_name = "Catch Rate Scaling: Not on Citadark Isle"


class CatchRateExcludeGreevil(Toggle):
    """
    With Catch Rate Scaling on, Greevil's Shadow Pokemon keep their normal catch rates.

    With Guaranteed Catches, every other catch in the game stays guaranteed.
    """

    display_name = "Catch Rate Scaling: Not on Greevil"


class NightmareCitadark(Toggle):
    """
    Every Citadark Isle trainer fields a different team of six from the Orre Colosseum's toughest
    challengers in XD and Colosseum, at level 100, with those trainers' own battle AI. Greevil's first
    fight, Shadow Lugia alone, is left as it is.

    The other Shadow Pokemon on Citadark Isle move to trainers elsewhere you cannot miss, at those
    trainers' levels, so every Shadow is still there to snag and purify.
    """

    display_name = "Nightmare Citadark"


class NightmareGreevil(Toggle):
    """
    Only Greevil's final battle takes a Nightmare team: six of the Orre Colosseum's toughest challengers'
    Pokemon from XD or Colosseum, at level 100, with that challenger's own battle AI. His Shadow Lugia fight
    and his Shadow Pokemon fight are left as they are, and nothing else on Citadark Isle changes.

    Does nothing with Nightmare Citadark on, which already includes it.
    """

    display_name = "Nightmare Greevil"


class RemoveCitadarkShadows(Toggle):
    """
    No Citadark Isle trainer except Greevil has a Shadow Pokemon. Each of those Shadow Pokemon moves to a
    trainer elsewhere in the game that you cannot miss, at that trainer's level, so every one is still there
    to snag and purify. The trainers keep an ordinary copy of the Pokemon in its place.

    Greevil's own Shadow Pokemon follow "Remove Greevil Shadows".
    """

    display_name = "Remove Citadark Shadows"


class RemoveGreevilShadows(Toggle):
    """
    Greevil has no Shadow Pokemon: Shadow Lugia and the six Shadow Pokemon of his second battle move to
    trainers elsewhere in the game that you cannot miss, at those trainers' levels. Greevil keeps an ordinary
    copy of each Pokemon in its place.
    """

    display_name = "Remove Greevil Shadows"


class TradeEvolutionsByLevel(DefaultOnToggle):
    """
    Pokemon that evolve by trading evolve by leveling up instead, at the same levels enemy trainers' Pokemon
    use: Kadabra, Machoke, Graveler and Haunter at 37; Onix, Scyther and Porygon at 30; Seadra at 40; Poliwhirl
    into Politoed at 36 (a Water Stone still makes Poliwrath).

    Where a Pokemon could become either of two, its personality decides, the way Wurmple's does: Clamperl
    becomes Huntail or Gorebyss at 30, and Slowpoke becomes Slowbro or Slowking at 37.

    Friendship evolutions are always by level, whether this is on or not: Pichu, Cleffa, Igglybuff, Togepi and
    Azurill at 15, Golbat at 35, Chansey at 40.
    """

    display_name = "Trade Evolutions By Level"


class PathLevelScaling(DefaultOnToggle):
    """
    For use with Location Shuffle. Scales trainers to match the level curve of the original game,
    regardless of the order you unlock locations. Intended early areas are scaled to lower levels,
    and intended later areas are scaled higher. The ramp runs from level 8 to 50, and Citadark Isle always
    comes after it, at 53.

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

    The items that actually gate something: Machine Part, Data ROM & ID Card, Music Disc, Mayor's Note, System Lever,
    and the Robo Kyogre Parts. Two are excluded from the shuffle even when this is on:

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

    Warning: Without Agate Pit Stop enabled, you may run out of/need to wait for Poke Balls. Proceed with caution if Agate Pit Stop is disabled.
    """

    display_name = "Shadow Pokemon Catch Checks Can Hold Progression"


class CitadarkProgressionChance(Range):
    """
    The percentage of Citadark Isle checks left eligible to hold progression or useful items. The rest are
    marked EXCLUDED -- filler only -- and WHICH ones are chosen varies per seed rather than being a fixed list.

    The higher the number, the more items can be locked behind Citadark.
    Recommended at 0 (Citadark is all filler) or 5 (SOME progressive items can be gated in Citadark, unlikely)
    """

    display_name = "Citadark Progression Chance"
    range_start = 0
    range_end = 100
    default = 5


class RandomizeTravelLocations(Toggle):
    """
    If enabled, 10 of this game's travel destinations become receivable AP items
    ("Travel Unlock - {name}"): Snagem Hideout, Outskirt Stand, Poke Spots, Pyrite Town, Phenac City,
    Realgam Tower, Cipher Key Lair, Cipher Lab, Mt. Battle and SS Libra. Orre Colosseum is not one: it opens
    as in the vanilla game and holds no checks.

    This setting is significantly more stable than the first release. It may still have the occasional issue, but should be okay.
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

    Only meaningful when "Robo Kyogre Parts Unlock Citadark Isle" is on. If it is greater than
    "Robo Kyogre Parts Available" below, Available is raised to match, so the seed can always be finished.
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
    Logic follows the goal: with Win Mt Battle, generation makes sure Mt. Battle is reachable.
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
    the ship is a chokepoint on the way to the Cipher Key Lair, and all of those ARE behind this item.

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
    default = 4


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

    Will insta-faint you in battle, or drop your whole party to 0 out of battle.

    Your own white-outs send a death. One caused by an incoming death does not send one back.
    """

    display_name = "Death Link"


class AgateVillagePitStop(Toggle):
    """
    Agate Village's shop sells real supplies instead of AP Items: Poke Balls, Great Balls, Ultra Balls,
    Potions, Super Potions, Hyper Potions and Full Heals from the start, plus Revives after its first restock
    and Max Potions after its second. Its Scents stay where they are.

    Agate's shop checks are removed from the seed. Only does anything with Randomize Shops on - with it off,
    every shop already sells its normal items.
    """

    display_name = "Agate Village Pit Stop"


class ReduceCitadarkGrind(Choice):
    """
    Gateon Port's shop, once it restocks after Gorigan (or all required Kyogre Parts),
    sells a Rare Candy and a Candy Box for 1 each, as many times as you like.

    on: the Candy Box raises a Pokemon straight to level 100 -- or to 99 if it can still evolve, so it evolves on
    the way and one more candy finishes the job.
    equal_to_citadark_entry: the Candy Box raises a Pokemon to the level of the lowest-levelled Pokemon on any
    Citadark Isle trainer in your seed, after Enhanced Difficulty and Path Level Scaling have set the levels.
    A Pokemon already at or above that level goes up one level, like a Rare Candy.

    Shadow Pokemon cannot use either. Works with or without Randomize Shops. With it on, two of Gateon's restock
    checks are removed from the seed.
    """

    display_name = "Reduce Citadark Grind"
    option_off = 0
    option_on = 1
    option_equal_to_citadark_entry = 2
    default = 0


class InfiniteTMs(Toggle):
    """
    TMs are never used up: teaching a move from a TM keeps the TM in your Bag, the way HMs already work.
    """

    display_name = "Infinite TMs"


@dataclass
class PokemonXDOptions(PerGameCommonOptions):
    # ORDER MATTERS: Options.generate_yaml_templates emits the template in exactly this order (group by group,
    # see OPTION_GROUPS below), and that template is the player's own curated YAML. Reordering these lines
    # reorders their file. ADDENDUM 447 grouped related options together; keep each group's lines together and
    # in the same order as OPTION_GROUPS.

    # -- Goal --
    goal: Goal
    robo_kyogre_parts_unlock_citadark: RoboKyogrePartsUnlockCitadark
    robo_kyogre_parts_required: RoboKyogrePartsRequired
    robo_kyogre_parts_available: RoboKyogrePartsAvailable
    citadark_story_weight: CitadarkStoryWeight

    # -- Locations & Progression --
    randomize_travel_locations: RandomizeTravelLocations
    key_item_shuffle: KeyItemShuffle
    shuffle_scooter_upgrade: ShuffleScooterUpgrade
    randomize_shops: RandomizeShops
    agate_village_pit_stop: AgateVillagePitStop
    shadow_catch_progression: ShadowCatchProgression
    citadark_progression_chance: CitadarkProgressionChance

    # -- Trainer Checks --
    shuffle_trainer_defeats: ShuffleTrainerDefeats
    trainer_defeat_mode: TrainerDefeatMode
    trainer_defeat_check_count: TrainerDefeatCheckCount
    exclude_mt_battle_trainers: ExcludeMtBattleTrainers

    # -- Shadow Pokemon --
    purification_checks: PurificationChecks
    purification_progression_cap: PurificationProgressionCap
    shadow_pokemon_expansion: ShadowPokemonExpansion
    randomize_shadow_species: RandomizeShadowSpecies
    shadow_inherited_moves: ShadowInheritedMoves
    no_legendary_shadows: NoLegendaryShadows
    shuffle_shadow_lugia: ShuffleShadowLugia
    remove_citadark_shadows: RemoveCitadarkShadows
    remove_greevil_shadows: RemoveGreevilShadows

    # -- Difficulty --
    enhanced_difficulty: EnhancedDifficulty
    enhanced_difficulty_level_scaling: EnhancedDifficultyLevelScaling
    path_level_scaling: PathLevelScaling
    legendary_trainer_pokemon: LegendaryTrainerPokemon
    nightmare_citadark: NightmareCitadark
    nightmare_greevil: NightmareGreevil

    # -- Your Pokemon --
    randomize_starter: RandomizeStarter
    catch_rate_scaling: CatchRateScaling
    catch_rate_exclude_citadark: CatchRateExcludeCitadark
    catch_rate_exclude_greevil: CatchRateExcludeGreevil
    purification_rate: PurificationRate
    experience_rate: ExperienceRate
    trade_evolutions_by_level: TradeEvolutionsByLevel
    reduce_citadark_grind: ReduceCitadarkGrind
    infinite_tms: InfiniteTMs

    # -- Speed --
    text_speed: TextSpeed
    hold_b_to_advance: HoldBToAdvance
    battle_speed: BattleSpeed
    disable_move_animations: DisableMoveAnimations

    # -- Death Link --
    death_link: PokemonXDDeathLink

    # -- Filler Weights --
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


# ADDENDUM 447: the YAML template and the options page show these as sections, in this order. Same order as the
# dataclass above (a test holds the two together).
OPTION_GROUPS: "list[OptionGroup]" = [
    OptionGroup("Goal", [
        Goal,
        RoboKyogrePartsUnlockCitadark,
        RoboKyogrePartsRequired,
        RoboKyogrePartsAvailable,
        CitadarkStoryWeight,
    ]),
    OptionGroup("Locations & Progression", [
        RandomizeTravelLocations,
        KeyItemShuffle,
        ShuffleScooterUpgrade,
        RandomizeShops,
        AgateVillagePitStop,
        ShadowCatchProgression,
        CitadarkProgressionChance,
    ]),
    OptionGroup("Trainer Checks", [
        ShuffleTrainerDefeats,
        TrainerDefeatMode,
        TrainerDefeatCheckCount,
        ExcludeMtBattleTrainers,
    ]),
    OptionGroup("Shadow Pokemon", [
        PurificationChecks,
        PurificationProgressionCap,
        ShadowPokemonExpansion,
        RandomizeShadowSpecies,
        ShadowInheritedMoves,
        NoLegendaryShadows,
        ShuffleShadowLugia,
        RemoveCitadarkShadows,
        RemoveGreevilShadows,
    ]),
    OptionGroup("Difficulty", [
        EnhancedDifficulty,
        EnhancedDifficultyLevelScaling,
        PathLevelScaling,
        LegendaryTrainerPokemon,
        NightmareCitadark,
        NightmareGreevil,
    ]),
    OptionGroup("Your Pokemon", [
        RandomizeStarter,
        CatchRateScaling,
        CatchRateExcludeCitadark,
        CatchRateExcludeGreevil,
        PurificationRate,
        ExperienceRate,
        TradeEvolutionsByLevel,
        ReduceCitadarkGrind,
        InfiniteTMs,
    ]),
    OptionGroup("Speed", [
        TextSpeed,
        HoldBToAdvance,
        BattleSpeed,
        DisableMoveAnimations,
    ]),
    OptionGroup("Death Link", [
        PokemonXDDeathLink,
    ]),
    OptionGroup("Filler Weights", [
        FillerWeightPokeBalls,
        FillerWeightMedicine,
        FillerWeightStatusHeals,
        FillerWeightBerries,
        FillerWeightBattleItems,
        FillerWeightTreasure,
        FillerWeightFlutes,
        FillerWeightTMs,
        FillerWeightEvolutionStones,
        FillerWeightCurrency,
    ]),
]
