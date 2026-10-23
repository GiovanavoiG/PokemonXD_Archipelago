"""The AP patch's memory block: its layout, the feature flags, the battle table, and the checks built on them."""
import struct
import unittest
from unittest import mock

from .. import ap_patch as ap
from .. import ram_client as rc
from ..game_data import trainer_roster
from ..game_data.battle_index import BATTLE_OPPONENTS, MT_BATTLE_DECK, STORY_DECK


def _battle_for(deck: int, index: int) -> int:
    return next(b for b, opponent in sorted(BATTLE_OPPONENTS.items()) if opponent == (deck, index))


def _block(flags=0, death_link=0, beaten=(), purified=(), caught=()) -> bytes:
    raw = bytearray(ap.CHECKS_READ_SIZE)
    struct.pack_into(">H", raw, ap.FLAGS_OFFSET, flags)
    raw[ap.DEATH_LINK_OFFSET] = death_link
    struct.pack_into(">H", raw, ap.BEAT_TRAINER_COUNTER_OFFSET, len(beaten))
    for i, battle in enumerate(beaten):
        struct.pack_into(">H", raw, ap.BEAT_TRAINER_INDICES_OFFSET + 2 * i, battle)
    struct.pack_into(">H", raw, ap.CHECK_PURIFY_COUNTER_OFFSET, len(purified))
    for i, shadow in enumerate(purified):
        struct.pack_into(">H", raw, ap.CHECK_PURIFIED_OFFSET + 2 * i, shadow)
    struct.pack_into(">H", raw, ap.CATCH_COUNTER_OFFSET, len(caught))
    for i, (level, species, shadow) in enumerate(caught):
        at = ap.CATCHES_OFFSET + i * ap.CATCH_ENTRY_SIZE
        raw[at] = level
        struct.pack_into(">HH", raw, at + 2, species, shadow)
    return bytes(raw)


class TestTheLayoutIsTheCStruct(unittest.TestCase):
    """`struct AP` under the GameCube EABI: u16 aligned to 2, so every field packs with no padding until the
    6-byte `CaughtPokemon` (u8 + pad + u16 + u16)."""

    def test_the_offsets(self):
        self.assertEqual(0x81700000, ap.AP_BLOCK_ADDRESS)
        self.assertEqual(0x004, ap.BEAT_TRAINER_COUNTER_OFFSET)
        self.assertEqual(0x006, ap.BEAT_TRAINER_INDICES_OFFSET)
        self.assertEqual(ap.BEAT_TRAINER_INDICES_OFFSET + 2 * 450, ap.CHECK_PURIFY_COUNTER_OFFSET)
        self.assertEqual(ap.CHECK_PURIFY_COUNTER_OFFSET + 2, ap.CHECK_PURIFIED_OFFSET)
        self.assertEqual(ap.CHECK_PURIFIED_OFFSET + 2 * 0x80, ap.CATCH_COUNTER_OFFSET)
        self.assertEqual(ap.CATCH_COUNTER_OFFSET + 2, ap.CATCHES_OFFSET)
        self.assertEqual(6, ap.CATCH_ENTRY_SIZE)
        self.assertEqual(0x78E, ap.CHECKS_READ_SIZE)

    def test_the_flag_bits_are_the_patchs_defines(self):
        # AP_ENABLE_ITEMCHECKS 0, _POKEMONCHECKS 1, _PURIFYCHECKS 2, _DEATHLINK 3
        self.assertEqual(0b0001, ap.feature_flags(item_checks=True, pokemon_checks=False,
                                                  purify_checks=False, death_link=False))
        self.assertEqual(0b0010, ap.feature_flags(item_checks=False, pokemon_checks=True,
                                                  purify_checks=False, death_link=False))
        self.assertEqual(0b0100, ap.feature_flags(item_checks=False, pokemon_checks=False,
                                                  purify_checks=True, death_link=False))
        self.assertEqual(0b1001, ap.feature_flags(item_checks=True, pokemon_checks=False,
                                                  purify_checks=False, death_link=True))


class TestParse(unittest.TestCase):
    def test_every_field(self):
        block = ap.parse(_block(flags=0x9, death_link=1, beaten=(216, 300), purified=(5,),
                                caught=((12, 1, 0), (30, 25, 7))))
        self.assertEqual(0x9, block.flags)
        self.assertEqual(1, block.death_link)
        self.assertEqual((216, 300), block.beaten_battles)
        self.assertEqual((5,), block.purified)
        self.assertEqual((ap.CaughtPokemon(12, 1, 0), ap.CaughtPokemon(30, 25, 7)), block.caught)

    def test_an_empty_block_is_a_block(self):
        self.assertEqual((), ap.parse(bytes(ap.CHECKS_READ_SIZE)).beaten_battles)

    def test_a_counter_past_its_array_is_not_the_patch(self):
        raw = bytearray(_block())
        struct.pack_into(">H", raw, ap.CATCH_COUNTER_OFFSET, 0x81)
        self.assertIsNone(ap.parse(bytes(raw)))
        raw = bytearray(_block())
        struct.pack_into(">H", raw, ap.BEAT_TRAINER_COUNTER_OFFSET, 451)
        self.assertIsNone(ap.parse(bytes(raw)))

    def test_a_short_read_is_not_the_patch(self):
        self.assertIsNone(ap.parse(b"\x00" * 16))

    def test_species_are_live_indices(self):
        # Treecko is live index 252 (master 277): the gap past Celebi is what the conversion is for.
        block = ap.parse(_block(caught=((5, 1, 0), (5, 252, 0), (5, 0, 0))))
        self.assertEqual({1, 252}, ap.caught_dex(block))


class TestTheBattleTable(unittest.TestCase):
    def test_it_covers_every_story_and_mt_battle_trainer_with_a_fight(self):
        story = {index for deck, index in BATTLE_OPPONENTS.values() if deck == STORY_DECK}
        mt = {index for deck, index in BATTLE_OPPONENTS.values() if deck == MT_BATTLE_DECK}
        self.assertEqual(set(range(1, 101)), mt)
        self.assertLessEqual(story, set(trainer_roster.TRAINERS_BY_INDEX))
        self.assertEqual(226, sum(1 for deck, _ in BATTLE_OPPONENTS.values() if deck == STORY_DECK))

    def test_landmarks(self):
        self.assertEqual((MT_BATTLE_DECK, 100), BATTLE_OPPONENTS[215])
        self.assertEqual("ZOOK", trainer_roster.TRAINERS_BY_INDEX[BATTLE_OPPONENTS[349][1]]["name"])


class TestResolve(unittest.TestCase):
    def test_a_story_fight(self):
        opponent = ap.resolve_battle(_battle_for(STORY_DECK, 2))
        self.assertEqual("MIROR B.", opponent.surname)
        self.assertEqual(2, opponent.story_index)
        self.assertFalse(opponent.mt_battle_only)

    def test_identical_teams_are_one_identity(self):
        # Chobin #4 (125) and #5 (127) field byte-identical teams.
        self.assertEqual(ap.resolve_battle(_battle_for(STORY_DECK, 125)).identity,
                         ap.resolve_battle(_battle_for(STORY_DECK, 127)).identity)

    def test_mt_battle_area_1_is_the_story_trainers(self):
        miru = ap.resolve_battle(_battle_for(MT_BATTLE_DECK, 1))
        self.assertEqual("MIRU", miru.surname)
        self.assertFalse(miru.mt_battle_only)

    def test_mt_battle_only(self):
        battlus = ap.resolve_battle(_battle_for(MT_BATTLE_DECK, 100))
        self.assertEqual("BATTLUS", battlus.surname)
        self.assertTrue(battlus.mt_battle_only)

    def test_no_check_behind_it(self):
        self.assertIsNone(ap.resolve_battle(1))      # the tutorial
        self.assertIsNone(ap.resolve_battle(9999))


def _count(n: int) -> str:
    return f"Defeat {n} Trainers"


class TestTheDefeatTracker(unittest.TestCase):
    QUEUE = {"MIROR B.": ["Defeat - Miror B. #1", "Defeat - Miror B. #2"]}

    def test_the_nth_distinct_team_takes_the_nth_label(self):
        tracker = ap.PatchDefeatTracker()
        first, second = _battle_for(STORY_DECK, 2), _battle_for(STORY_DECK, 72)
        self.assertEqual([_count(1), "Defeat - Miror B. #1"], tracker.poll([first], self.QUEUE, _count))
        self.assertEqual([_count(2), "Defeat - Miror B. #2"], tracker.poll([first, second], self.QUEUE, _count))

    def test_a_rematch_checks_off_nothing(self):
        tracker = ap.PatchDefeatTracker()
        battle = _battle_for(STORY_DECK, 2)
        tracker.poll([battle], self.QUEUE, _count)
        self.assertEqual([], tracker.poll([battle, battle], self.QUEUE, _count))
        self.assertEqual(1, tracker.rematches_ignored)
        self.assertEqual(2, tracker.wins_by_surname["MIROR B."])

    def test_a_shorter_log_is_replayed_without_double_counting(self):
        """A new boot starts the log over; the beaten teams survive and dedup the replay."""
        tracker = ap.PatchDefeatTracker()
        battle = _battle_for(STORY_DECK, 2)
        tracker.poll([battle, _battle_for(STORY_DECK, 72)], self.QUEUE, _count)
        self.assertEqual([], tracker.poll([battle], self.QUEUE, _count))
        self.assertEqual(1, tracker.replays)
        self.assertEqual(2, tracker.defeat_count)
        self.assertEqual({"MIROR B."}, tracker.last_confirmed_surnames)

    def test_the_count_is_capped(self):
        tracker = ap.PatchDefeatTracker()
        sent = tracker.poll([_battle_for(STORY_DECK, 2)], self.QUEUE, _count, count_location_max=0)
        self.assertEqual(["Defeat - Miror B. #1"], sent)

    def test_mt_battle_wins_are_kept_out_when_excluded(self):
        tracker = ap.PatchDefeatTracker()
        sent = tracker.poll([_battle_for(MT_BATTLE_DECK, 50)], {}, _count, exclude_mt_battle=True)
        self.assertEqual([], sent)
        sent = tracker.poll([_battle_for(MT_BATTLE_DECK, 50)], {}, _count, exclude_mt_battle=False)
        self.assertEqual([], sent, "the same log entry is not read twice")

    def test_it_survives_a_client_restart(self):
        tracker = ap.PatchDefeatTracker()
        battle = _battle_for(STORY_DECK, 2)
        tracker.poll([battle], self.QUEUE, _count)
        restored = ap.PatchDefeatTracker()
        restored.load_json(tracker.to_json())
        self.assertEqual([], restored.poll([battle], self.QUEUE, _count))
        self.assertEqual(1, restored.defeat_count)


class TestDeathLinkThroughThePatch(unittest.TestCase):
    def test_the_white_out_it_causes_is_not_sent_back(self):
        bridge = rc.DeathLinkBridge(enabled=True)
        self.assertIsNotNone(bridge.receive_via_patch("someone"))
        bridge.patch_pending = True
        with mock.patch.object(rc, "party_is_wiped", return_value=False):
            # Many conscious polls while the patch still holds the death: the fence must not come down.
            for _ in range(10):
                self.assertEqual((False, None), bridge.poll(0x80479680, whiteouts=0))
            bridge.patch_pending = False
            self.assertEqual((False, None), bridge.poll(0x80479680, whiteouts=1))
        self.assertEqual(1, bridge.suppressed)
        self.assertEqual(0, bridge.sends)

    def test_off_means_nothing_is_queued(self):
        self.assertIsNone(rc.DeathLinkBridge(enabled=False).receive_via_patch())


if __name__ == "__main__":
    unittest.main()
