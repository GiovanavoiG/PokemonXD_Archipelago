"""ADDENDUM 332 (2026-09-23): the Key Lair leaves Snagem behind, and the hideout fights one rung lower.

Player, in one message:

> Decouple Key Lair from snagem - we no longer need snagem to access key lair. Also, upon fighting a trainer
> in snagem, please temporarily drop the story byte back to 0x62 unless it's Gonzap or the trainer right
> before him. This lets us properly load snagem, but currently gonzap won't fight the trainer - so we need to
> go back one bit to fix him. The floor can stay at 0x63, but once a fight happens we need 0x62.

Followed by: "that's SPECIFICALLY FOR LOCATION SHUFFLE btw".

Two unrelated changes that share a scope, so they share a file.
"""
import pathlib
import unittest

from . import PokemonXDTestBase
from .. import ram_client as rc
from .. import travel_locations as tl
from ..game_data import story_bytes
from .test_addendum_229_map_backout_restore import BLOCK, _LiveByte

CLIENT_SOURCE = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(
    encoding="utf-8")

SNAGEM = min(rc.SNAGEM_ROOM_IDS)
ELSEWHERE = 132   # Agate -- any room outside the hideout


class TestTheKeyLairIsDecoupled(PokemonXDTestBase):
    options = {"randomize_travel_locations": True, "key_item_shuffle": True}

    def test_the_prerequisite_is_gone(self) -> None:
        self.assertNotIn("Cipher Key Lair", tl.TRAVEL_LOCATION_REQUIRED_REGIONS)

    def test_the_item_alone_opens_it(self) -> None:
        self.collect_by_name(tl.travel_unlock_item_name("Cipher Key Lair"))
        self.assertTrue(self.multiworld.state.can_reach("Cipher Key Lair", player=self.player))

    def test_it_no_longer_needs_snagem_reachable(self) -> None:
        """Stated as the player stated it: Snagem is not on the path any more."""
        from BaseClasses import CollectionState

        state = CollectionState(self.multiworld)
        state.collect(self.get_item_by_name(tl.travel_unlock_item_name("Cipher Key Lair")), True)
        self.assertFalse(state.can_reach_region("Snagem Hideout", self.player),
                         "premise: Snagem really is shut in this state")
        self.assertTrue(state.can_reach_region("Cipher Key Lair", self.player))

    def test_the_arrival_byte_is_what_makes_it_safe(self) -> None:
        """The gate stood in for "Gonzap beaten, the Lair open". The icon writes that state on arrival, so
        nothing is promised that the client cannot deliver.

        ADDENDUM 371 raised the floor from 0x64 to 0x67, which STRENGTHENS this rather than changing it: the
        argument is that the arrival byte is at least "Gonzap beaten, the Lair open", so it is asserted as the
        inequality it always was. 0x64 is the transition that opens the region (`opens_regions` on the
        0x63 -> 0x64 rung), read from the ladder rather than typed, so a change there cannot pass unnoticed."""
        opens_lair = [t.after for t in story_bytes.TRANSITIONS
                      if "Cipher Key Lair" in (t.opens_regions or ())]
        self.assertIn(0x64, opens_lair)
        self.assertGreaterEqual(story_bytes.area_entry_floor("Cipher Key Lair"), 0x64)

    def test_the_ship_gate_is_untouched(self) -> None:
        self.assertEqual(("Phenac City (Post-Sixes)",), tl.TRAVEL_LOCATION_REQUIRED_REGIONS["SS Libra"])


class TestVanillaTravelStillChainsThroughSnagem(PokemonXDTestBase):
    """"That's SPECIFICALLY FOR LOCATION SHUFFLE." With the option off the story chain is the only route and
    the game's own route really does run through the hideout, so nothing above may leak into this mode."""

    options = {"randomize_travel_locations": False, "key_item_shuffle": True}

    def test_the_chain_edge_survives(self) -> None:
        lair = self.multiworld.get_region("Cipher Key Lair", self.player)
        self.assertEqual(["Snagem Hideout"], [e.parent_region.name for e in lair.entrances])


class TestTheExemptFights(unittest.TestCase):
    def test_it_is_gonzap_and_the_trainer_right_before_him(self) -> None:
        self.assertEqual({"GONZAP", "WAKIN"}, set(story_bytes.SNAGEM_BATTLE_EXEMPT_SURNAMES))

    def test_they_are_derived_from_story_order_rather_than_typed(self) -> None:
        """The deck's index order IS story order (`trainer_roster`'s docstring, the property ADDENDUM 330
        leaned on), so "the trainer right before him" is a lookup, not a judgement."""
        from ..game_data.trainer_placements import PLACEMENTS
        from ..game_data.trainer_roster import TRAINERS

        names = {entry["index"]: entry["name"].upper() for entry in TRAINERS}
        order = sorted(i for i, p in PLACEMENTS.items() if p.region == "Snagem Hideout")
        self.assertEqual("GONZAP", names[order[-1]])
        self.assertEqual({names[order[-1]], names[order[-2]]},
                         set(story_bytes.SNAGEM_BATTLE_EXEMPT_SURNAMES))

    def test_the_drop_and_the_floor_are_the_same_rung_now(self) -> None:
        """ADDENDUM 350. The two rungs were never really different -- see that addendum's section in
        game_data/story_bytes.py. Both are 0x62, which stands for story value 790, which is what Snagem 2F's
        `hero_main` tests for. `SNAGEM_BATTLE_DROP_NEEDED` is the derived switch the hold reads, and it being
        False is what stops the hold re-arming Gonzap's scene for a player who is already past him."""
        self.assertEqual(0x62, story_bytes.SNAGEM_BASE_FLOOR)
        self.assertEqual(0x62, story_bytes.SNAGEM_BATTLE_FLOOR)
        self.assertFalse(story_bytes.SNAGEM_BATTLE_DROP_NEEDED)
        self.assertEqual(790, story_bytes.story_value_for_byte(0x62))


class TestTheDropIsRetiredButNotRemoved(unittest.TestCase):
    """ADDENDUM 350: the hold must do nothing by default, and must still work if a floor ever moves again."""

    def setUp(self):
        self.live = _LiveByte(0x64)          # past Gonzap -- the case where a drop would be actively harmful
        self.hold = rc.SnagemBattleStoryHold()

    def tearDown(self):
        self.live.restore_module()

    def test_a_grunt_fight_no_longer_drops_anything(self) -> None:
        self.assertIsNone(self.hold.poll(BLOCK, SNAGEM, True, {"FUDLO"}))
        self.assertEqual(0x64, self.live.value)
        self.assertFalse(self.hold.active)

    def test_it_would_still_drop_if_the_two_rungs_ever_parted(self) -> None:
        original = story_bytes.SNAGEM_BATTLE_DROP_NEEDED
        story_bytes.SNAGEM_BATTLE_DROP_NEEDED = True
        try:
            self.assertIsNotNone(self.hold.poll(BLOCK, SNAGEM, True, {"FUDLO"}))
            self.assertEqual(story_bytes.SNAGEM_BATTLE_FLOOR, self.live.value)
        finally:
            story_bytes.SNAGEM_BATTLE_DROP_NEEDED = original


class _HoldBase(unittest.TestCase):
    """ADDENDUM 350 retired the drop by making `SNAGEM_BATTLE_DROP_NEEDED` False -- the hideout's entry floor
    and its fighting rung became the same value. These tests are about the HOLD'S OWN MACHINERY (exemptions,
    restore-on-exit, the rise-underneath-us case), which is still correct and still wanted if the two rungs
    ever part again, so they force the switch on rather than being deleted. `TestTheDropIsRetiredButNotRemoved`
    above is what pins the default."""

    def setUp(self):
        self._drop_needed = story_bytes.SNAGEM_BATTLE_DROP_NEEDED
        story_bytes.SNAGEM_BATTLE_DROP_NEEDED = True
        # ADDENDUM 350: the hold declines when the byte is already at or below the fighting rung, and the
        # two rungs are the same value now -- so the player's byte has to START above the floor for there to
        # be anything to hold. `self.start` is that value; it is what a restore must put back.
        self.start = story_bytes.SNAGEM_BASE_FLOOR + 1
        self.live = _LiveByte(self.start)
        self.log = rc.StoryByteWriteLog()
        self.hold = rc.SnagemBattleStoryHold(write_log=self.log)

    def tearDown(self):
        story_bytes.SNAGEM_BATTLE_DROP_NEEDED = self._drop_needed
        self.live.restore_module()


class TestTheDrop(_HoldBase):
    def test_a_grunt_fight_drops_to_0x62(self) -> None:
        note = self.hold.poll(BLOCK, SNAGEM, True, {"FUDLO"})
        self.assertEqual(0x62, self.live.value)
        self.assertTrue(self.hold.active)
        self.assertIn("0x62", note)
        self.assertEqual(0x62, self.hold.last_written_value)

    def test_standing_in_the_hideout_without_a_fight_changes_nothing(self) -> None:
        """Standing in the hideout is not a fight; nothing of the player's is touched."""
        self.assertIsNone(self.hold.poll(BLOCK, SNAGEM, False, None))
        self.assertEqual(self.start, self.live.value)

    def test_gonzap_keeps_the_floor(self) -> None:
        self.assertIsNone(self.hold.poll(BLOCK, SNAGEM, True, {"GONZAP"}))
        self.assertEqual(self.start, self.live.value)
        self.assertEqual(1, self.hold.declined_exempt)

    def test_the_trainer_right_before_him_keeps_it_too(self) -> None:
        self.assertIsNone(self.hold.poll(BLOCK, SNAGEM, True, {"WAKIN"}))
        self.assertEqual(self.start, self.live.value)

    def test_a_fight_outside_the_hideout_is_none_of_its_business(self) -> None:
        self.assertIsNone(self.hold.poll(BLOCK, ELSEWHERE, True, {"FUDLO"}))
        self.assertEqual(self.start, self.live.value)

    def test_it_never_writes_without_a_name(self) -> None:
        """The battle flag can lead the roster by a tick, and we cannot tell Gonzap from a grunt with no
        name -- so the tick is declined rather than guessed."""
        self.assertIsNone(self.hold.poll(BLOCK, SNAGEM, True, None))
        self.assertIsNone(self.hold.poll(BLOCK, SNAGEM, True, set()))
        self.assertEqual(self.start, self.live.value)
        self.assertEqual(2, self.hold.declined_no_surname)

    def test_a_won_game_is_never_lowered(self) -> None:
        self.live.value = rc.VICTORY_STORY_BYTE
        self.assertIsNone(self.hold.poll(BLOCK, SNAGEM, True, {"FUDLO"}))
        self.assertEqual(rc.VICTORY_STORY_BYTE, self.live.value)
        self.assertFalse(self.hold.active)


class TestItIsAlwaysPutBack(_HoldBase):
    def test_the_fight_ending_restores_the_players_byte(self) -> None:
        self.hold.poll(BLOCK, SNAGEM, True, {"FUDLO"})
        self.assertEqual(0x62, self.live.value)
        note = self.hold.poll(BLOCK, SNAGEM, False, None)
        self.assertEqual(self.start, self.live.value)
        self.assertFalse(self.hold.active)
        self.assertIn("restored", note)

    def test_walking_out_mid_fight_restores_too(self) -> None:
        self.hold.poll(BLOCK, SNAGEM, True, {"FUDLO"})
        self.hold.poll(BLOCK, ELSEWHERE, True, {"FUDLO"})
        self.assertEqual(self.start, self.live.value)
        self.assertFalse(self.hold.active)

    def test_real_progress_outranks_the_remembered_value(self) -> None:
        """Beating Gonzap advances the byte. A restore must never drag that back."""
        self.hold.poll(BLOCK, SNAGEM, True, {"FUDLO"})
        self.live.value = 0x64
        self.hold.poll(BLOCK, SNAGEM, False, None)
        self.assertEqual(0x64, self.live.value)
        self.assertEqual(1, self.hold.declined_restores)

    def test_a_byte_that_rises_mid_fight_is_owed_back(self) -> None:
        self.hold.poll(BLOCK, SNAGEM, True, {"FUDLO"})
        self.live.value = 0x66                       # a cutscene moved it under us
        self.hold.poll(BLOCK, SNAGEM, True, {"FUDLO"})
        self.assertEqual(0x62, self.live.value, "still held for the fight")
        self.hold.poll(BLOCK, SNAGEM, False, None)
        self.assertEqual(0x66, self.live.value, "and the newer value is what we owe back")

    def test_the_hold_is_never_left_on_after_a_quiet_tick(self) -> None:
        """The property that matters most: no sequence of polls leaves the byte lowered once the fight is
        over. Walked over every ordering this can see."""
        for room in (SNAGEM, ELSEWHERE, None):
            for fighting in (True, False):
                hold = rc.SnagemBattleStoryHold()
                hold.poll(BLOCK, SNAGEM, True, {"FUDLO"})
                hold.poll(BLOCK, room, fighting, {"FUDLO"} if fighting else None)
                hold.poll(BLOCK, ELSEWHERE, False, None)
                self.assertFalse(hold.active, (room, fighting))
                self.assertGreaterEqual(self.live.value, story_bytes.SNAGEM_BATTLE_FLOOR)

    def test_every_write_reaches_the_log(self) -> None:
        self.hold.poll(BLOCK, SNAGEM, True, {"FUDLO"})
        self.hold.poll(BLOCK, SNAGEM, False, None)
        kinds = [entry.source for entry in self.log.entries]
        self.assertIn("snagem battle", kinds)
        self.assertIn("snagem restore", kinds)


class TestItIsWiredForLocationShuffleOnly(unittest.TestCase):
    def test_the_poll_lives_on_the_travel_shuffle_path(self) -> None:
        """The hold is only ever called from the branch that runs with travel shuffle on -- the same branch
        the area memory and the in-area bump live on. A second call site on the vanilla path would be the
        leak the player's "SPECIFICALLY FOR LOCATION SHUFFLE" rules out.

        Read off the file rather than imported: `Client` pulls in the websocket stack, which a data-only test
        has no business needing."""
        self.assertEqual(1, CLIENT_SOURCE.count("ctx.snagem_battle_hold.poll("))
        travel_off = CLIENT_SOURCE[CLIENT_SOURCE.index("def _bump_in_vanilla_travel"):]
        travel_off = travel_off[:travel_off.index("\nasync def ", 1)]
        self.assertNotIn("snagem_battle_hold", travel_off)

    def test_the_client_claims_the_write(self) -> None:
        self.assertIn("_claim_story_write(ctx, ctx.snagem_battle_hold)", CLIENT_SOURCE)

    def test_the_roster_is_only_scanned_where_it_can_matter(self) -> None:
        """The scan is the whole of MEM1. Doing it every tick for a signal that is relevant in three rooms
        would be a real cost -- so the call must sit behind the room test AND the battle flag."""
        start = CLIENT_SOURCE.index("snagem_room = room_id is not None")
        block = CLIENT_SOURCE[start:CLIENT_SOURCE.index("ctx.snagem_battle_hold.poll(", start)]
        self.assertLess(block.index("if snagem_room:"), block.index("scan_battle_roster()"))
        self.assertLess(block.index("if snagem_fighting:"), block.index("scan_battle_roster()"))
