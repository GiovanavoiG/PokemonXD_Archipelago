"""Playtest pass, 2026-09-15 -- ADDENDA 215, 216 and 217.

215: "Add a toggle to the client for printing out every time the story byte changes."
216: "Make sure that at 0x16, the machine part is cleared from inventory unless we've received it in
      archipelago, or ideally Include it as part of our key item polling/clearing."
217: "Let's remove our guardrail on pokemon movesets - previously, we only gave them 3 moves, and removed
      their level 1 moves - let's go ahead and give them a fourth move if they can learn it and give their
      level 1 moves back, since FST guard prevents those freezes."
"""
import random
import unittest
from pathlib import Path

from .. import ram_client
from ..randomizer import team_shuffle, shadow_expansion


class TestStoryWatchToggle(unittest.TestCase):
    """Source-checked: Client.py pulls in Archipelago's CommonClient, which this environment cannot import."""

    @classmethod
    def setUpClass(cls):
        cls.source = (Path(ram_client.__file__).resolve().parent / "Client.py").read_text(encoding="utf-8")

    def test_the_command_exists(self):
        self.assertIn("def _cmd_storywatch(self, state: str = \"\") -> None:", self.source)

    def test_it_has_its_own_flag_rather_than_reusing_verbose(self):
        """If it piggy-backed on verbose_logging the player would have to take the room/travel/key-item
        firehose to watch one byte, which is the opposite of what was asked for."""
        self.assertIn("self.story_byte_watch: bool = False", self.source)

    def test_it_is_off_by_default(self):
        self.assertIn("self.story_byte_watch: bool = False", self.source)
        self.assertNotIn("self.story_byte_watch: bool = True", self.source)

    def test_when_on_it_logs_rather_than_notes(self):
        """`_note` is silenced unless verbose is on. A watch that could be silenced by an unrelated toggle
        would not be a watch."""
        self.assertIn("if ctx.story_byte_watch:", self.source)
        self.assertIn("logger.info(line)", self.source)

    def test_a_decrease_is_not_reported_as_an_advance(self):
        """The tracker reports any change, and this client itself writes LOWER values (the area-memory floor,
        the parts-override restore), so the old unconditional wording was wrong on the way down."""
        self.assertIn('direction = "advanced" if now > was else "moved back"', self.source)


class TestKeyItemPocketRouting(unittest.TestCase):
    """ADDENDUM 216. The Machine Part was already in the polling set; the routing was the bug."""

    BLOCK = 0x80479000

    def key_items_pocket(self):
        return self.BLOCK + ram_client.KEY_ITEMS_OFFSET

    def test_the_machine_part_routes_to_the_key_items_pocket(self):
        resolved = ram_client.resolve_item_pocket(self.BLOCK, 503)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved[0], self.key_items_pocket(),
                         "id 503 used to fall through to the Items pocket, where the game never puts it")

    def test_every_gating_key_item_routes_there(self):
        from ..game_data import key_items

        for item_id in sorted(key_items.POLLED_GAME_ITEM_IDS):
            resolved = ram_client.resolve_item_pocket(self.BLOCK, item_id)
            self.assertIsNotNone(resolved, f"id {item_id} has no pocket at all")
            self.assertEqual(resolved[0], self.key_items_pocket(),
                             f"id {item_id} ({key_items.KEY_ITEM_BY_GAME_ID[item_id].name}) routes elsewhere")

    def test_the_krane_memos_and_voice_cases_still_route_there(self):
        """The original 523-533 rule must not have been replaced, only widened."""
        for item_id in list(range(523, 534)):
            self.assertEqual(ram_client.resolve_item_pocket(self.BLOCK, item_id)[0], self.key_items_pocket())

    def test_nothing_outside_the_key_item_range_moved(self):
        """The widened range is 500-533. Everything on either side must land where it always did."""
        self.assertEqual(ram_client.resolve_item_pocket(self.BLOCK, 1)[0],
                         self.BLOCK + ram_client.POKEBALL_POCKET_OFFSET, "Poke Ball")
        self.assertEqual(ram_client.resolve_item_pocket(self.BLOCK, 300)[0],
                         self.BLOCK + ram_client.POKEBALL_POCKET_OFFSET
                         + ram_client.TM_HM_POCKET_RELATIVE_START * 4, "a TM")
        self.assertEqual(ram_client.resolve_item_pocket(self.BLOCK, 140)[0],
                         self.BLOCK + ram_client.POKEBALL_POCKET_OFFSET
                         + ram_client.BERRIES_POCKET_RELATIVE_START * 4, "a berry")
        for items_pocket_id in (13, 68, 225, 499, 534):
            self.assertEqual(ram_client.resolve_item_pocket(self.BLOCK, items_pocket_id)[0],
                             self.BLOCK + ram_client.ITEMS_POCKET_OFFSET, f"id {items_pocket_id}")

    def test_a_none_id_still_declines(self):
        self.assertIsNone(ram_client.resolve_item_pocket(self.BLOCK, None))

    def test_the_machine_part_is_in_the_polled_set(self):
        """The half that was already right. Pinned so a future edit cannot quietly drop it and leave the
        routing fix looking like it covers something it no longer does."""
        from ..game_data import key_items

        self.assertIn(503, key_items.POLLED_GAME_ITEM_IDS)
        self.assertEqual(key_items.KEY_ITEM_BY_GAME_ID[503].name, "Machine Part")


class TestFourMovesAndLevelOneMoves(unittest.TestCase):
    GROWL, TACKLE, EMBER, LEER, FIRE_PUNCH, FLAME_WHEEL = 45, 33, 52, 43, 7, 172

    def learnset(self):
        return [(1, self.GROWL), (5, self.TACKLE), (10, self.EMBER),
                (15, self.LEER), (20, self.FIRE_PUNCH), (25, self.FLAME_WHEEL)]

    def test_the_default_is_four(self):
        self.assertEqual(team_shuffle.MOVESET_SHUFFLE_DEFAULT_MOVE_COUNT, 4)

    def test_shadow_expansion_tracks_it(self):
        self.assertEqual(shadow_expansion.SHADOW_EXPANSION_MOVE_COUNT, 4)

    def test_four_slots_are_actually_filled(self):
        chosen = team_shuffle.choose_moveset(species_id=1, level=40, learnset=self.learnset(),
                                             rng=random.Random(3))
        self.assertEqual(len(chosen), 4)
        self.assertEqual(len(set(chosen)), 4, "moves must still be distinct")

    def test_the_level_one_move_is_selectable_again(self):
        """The direct statement of the change: at a level where Growl is the only remaining candidate, it has
        to be picked. Under ADDENDUM 75 it could never be."""
        chosen = team_shuffle.choose_moveset(species_id=1, level=12, learnset=self.learnset(),
                                             rng=random.Random(1), move_count=3)
        self.assertIn(self.GROWL, chosen)

    def test_pound_is_still_excluded(self):
        """ADDENDUM 72/73 is a SEPARATE real-hardware freeze and was not part of this instruction. Removing
        the first-entry exclusion must not have taken it along."""
        self.assertIn(1, team_shuffle.EXCLUDED_MOVE_IDS)
        learnset = [(1, 1), (5, self.TACKLE), (10, self.EMBER)]
        chosen = team_shuffle.choose_moveset(species_id=1, level=40, learnset=learnset, rng=random.Random(0))
        self.assertNotIn(1, chosen)

    def test_a_species_whose_only_move_is_its_first_is_no_longer_left_empty(self):
        """The concrete cost of the old exclusion: a slot low enough to have learned exactly one move got
        nothing at all, because that one move was the excluded one."""
        chosen = team_shuffle.choose_moveset(species_id=1, level=3, learnset=[(1, self.TACKLE)],
                                             rng=random.Random(0))
        self.assertEqual(chosen, [self.TACKLE])

    def test_assign_movesets_pads_to_four(self):
        """The ISO write layer takes 4 slots either way; the padding is what keeps the returned shape honest."""
        from ..randomizer.team_shuffle import PokemonInstance, Trainer, TrainerPool

        mon = PokemonInstance(index=0, species_id=1, level=40)
        pool = TrainerPool(name="test", trainers=[Trainer(name="t", team=[mon])])
        out = team_shuffle.assign_movesets([pool], {1: self.learnset()}, random.Random(0))
        self.assertEqual(len(out[0]), 4)


class TestTheBudgetReasoningIsRecorded(unittest.TestCase):
    """ADDENDUM 35's cap black-screened the game when it was wrong. Raising it is only defensible with the
    measurement written down, so this asserts the record exists rather than trusting a bare constant."""

    @classmethod
    def setUpClass(cls):
        cls.source = Path(team_shuffle.__file__).read_text(encoding="utf-8")

    def test_the_original_failure_is_still_documented(self):
        self.assertIn("16615", self.source, "the real budget figure must stay findable")
        self.assertIn("black screen", self.source.lower())

    def test_the_new_measurement_is_recorded_with_its_numbers(self):
        self.assertIn("16124-16203", self.source,
                      "the re-measured range must be written down, not just asserted to fit")

    def test_the_safety_net_is_named(self):
        self.assertIn("patch_entry_decompressed", self.source)


if __name__ == "__main__":
    unittest.main()
