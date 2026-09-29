"""ADDENDUM 330 (2026-09-23): the two Biden rows had their regions the wrong way round.

Player: "With path scaling, Biden in Snagem was level 40 but the rest of snagem was 15/16 - is this due to
his fight in the Key Lair? did it scale him to key lair levels?"

ADDENDUM 329 fixed the mechanism (the Cipher Key Lair ICON's floor was reaching the level ramp). This is the
residue: the fight the player met in the Snagem Hideout is `Defeat - Biden #1`, trainer 143, and the census
placed it at `Cipher Key Lair (exterior)`. The deck's own story order -- the property `trainer_roster`'s
docstring states and this project has relied on since ADDENDUM 143 -- puts 143 between Hobble (142) and Wakin
(144), both Snagem Hideout, in the same trainer class and the same level band; and puts Biden #2 (148) beside
Zook #2 (147), immediately before the Cipher Key Lair interior begins at 149.

These tests assert the correction AND the measurement it rests on, so the day the workbook is re-exported the
disagreement shows up here rather than as a level a player has to notice in a playthrough.
"""
from . import PokemonXDTestBase
from ..game_data import trainer_placements as tp
from ..game_data import trainer_roster as trr
from ..randomizer import path_level_scaling as pls


class TestTheTwoBidenRows(PokemonXDTestBase):

    def test_the_hideout_fight_is_in_the_hideout(self) -> None:
        self.assertEqual("Snagem Hideout", tp.region_for(143))
        self.assertEqual("Cipher Key Lair (exterior)", tp.region_for(148))

    def test_both_rows_are_the_same_person(self) -> None:
        """If they were not, swapping them would be inventing a fight rather than correcting one."""
        entries = {entry["index"]: entry for entry in trr.TRAINERS}
        self.assertEqual("BIDEN", entries[143]["name"])
        self.assertEqual("BIDEN", entries[148]["name"])
        self.assertEqual(entries[143]["trainer_class"], entries[148]["trainer_class"])

    def test_the_deck_puts_143_inside_the_snagem_block(self) -> None:
        """The measurement the correction rests on, asserted rather than described."""
        for neighbour in (142, 144, 145):
            self.assertEqual("Snagem Hideout", tp.region_for(neighbour), neighbour)
        entries = {entry["index"]: entry for entry in trr.TRAINERS}
        self.assertEqual(entries[142]["trainer_class"], entries[143]["trainer_class"])
        self.assertEqual(entries[144]["trainer_class"], entries[143]["trainer_class"])

    def test_148_sits_with_zook_on_the_post_snagem_return(self) -> None:
        self.assertEqual("Cipher Key Lair (exterior)", tp.region_for(147))
        self.assertEqual(("Snagem Hideout",), tp.PLACEMENTS[147].required_regions,
                         "Zook #2's own workbook note is what says this pair is the return visit")
        self.assertEqual("Cipher Key Lair", tp.region_for(149),
                         "149 is where the interior begins -- 147/148 are the last two rows outside it")

    def test_the_reported_fight_is_levelled_with_its_neighbours(self) -> None:
        """The player's actual complaint, on the intended path: Biden must not tower over the Snagem block."""
        levels = pls.level_by_trainer_index()
        snagem = [levels[index] for index, place in tp.PLACEMENTS.items()
                  if place.region == "Snagem Hideout" and index in levels]
        self.assertEqual(levels[143], min(snagem))
        self.assertEqual(levels[143], max(snagem),
                         "one region is one tier -- Biden #1 is now simply a Snagem Hideout trainer")

    def test_the_overrides_are_kept_honest(self) -> None:
        """Every override must name a real, regioned row and must actually change it. A correction that
        changes nothing reads as a correction and is not one (ADDENDUM 247's dead-rule rule)."""
        self.assertTrue(tp.PLACEMENT_REGION_OVERRIDES)
        for index, region in tp.PLACEMENT_REGION_OVERRIDES.items():
            self.assertIn(index, tp.PLACEMENTS)
            self.assertEqual(region, tp.region_for(index))
            self.assertIn(region, tp.REGIONS_WITH_TRAINERS)

    def test_the_region_counts_still_add_up(self) -> None:
        """A swap moves rows between two regions and must not create or lose one."""
        counts = tp.trainer_count_by_region()
        self.assertEqual(len(tp.PLACED_INDICES), sum(counts.values()))
        self.assertEqual(232, len(tp.PLACED_INDICES) + len(tp.FILLER_ONLY_INDICES))
