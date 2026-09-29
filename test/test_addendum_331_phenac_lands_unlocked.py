"""ADDENDUM 331 (2026-09-23): Phenac lands unlocked, and stays unlocked.

Player: "The phenac bump - 0x3F > 0x41 - is not going off in play. We need to raise the floor and its current
byte the moment we land in the phenac room id, so that the return trip doesn't kick us out again."

TWO DEFECTS, one per half of that sentence.

**The current byte.** `LiveStoryByteBump("Phenac City", 0x3F, 0x41)` fires only while the live byte is in
[0x3F, 0x41). Phenac's icon enters the town at its window FLOOR -- 0x3E -- so that is the byte on every
arrival, one rung BELOW the window. 0x3F is reached only by the game's own first-visit-complete beat, which
ends by forcing the player out toward Realgam. The bump described a state a player is hardly ever standing in
Phenac for.

**The floor.** Even when it did fire, nothing made 0x41 stick: a client write is deliberately never banked as
the area's mark (ADDENDUM 277), and the only rule that raised Phenac's floor to 0x41 was
`AreaFloorRule("Phenac City", 0x41, (("Phenac City", 0x3F), ("Realgam Tower", 0x41)))` -- which needs a
Realgam mark. With travel locations shuffled Realgam is its own destination behind its own unlock item, so
that mark may never exist, the rule never binds, and `target_for` falls back to 0x3E. Every return hover
rebuilt the LOCKED town.
"""
import unittest

from . import PokemonXDTestBase
from .. import ram_client as rc
from ..game_data import chest_regions, story_bytes


class TestTheCurrentByte(unittest.TestCase):
    def _bump(self):
        found = [b for b in story_bytes.LIVE_STORY_BYTE_BUMPS if b.region == "Phenac City"]
        self.assertEqual(1, len(found))
        return found[0]

    def test_it_fires_at_the_byte_the_icon_actually_writes(self) -> None:
        """The reported failure, stated as the thing that was false."""
        arrival = story_bytes.region_floor("Phenac City")
        self.assertEqual(0x3E, arrival)
        self.assertTrue(self._bump().applies("Phenac City", arrival))

    def test_it_covers_every_locked_value_and_stops_at_the_unlocked_one(self) -> None:
        bump = self._bump()
        for byte in (0x3E, 0x3F, 0x40):
            self.assertTrue(bump.applies("Phenac City", byte), hex(byte))
        for byte in (0x3D, 0x41, 0x42, 0x50):
            self.assertFalse(bump.applies("Phenac City", byte), hex(byte))

    def test_it_never_lowers(self) -> None:
        bump = self._bump()
        self.assertGreater(bump.becomes, bump.when_byte_is)

    def test_every_plain_phenac_room_resolves_to_the_region_the_bump_names(self) -> None:
        """A bump that names a region no room maps to never fires -- and "the phenac room id" is the player's
        own trigger, so the mapping is the mechanism rather than a detail."""
        rooms = [room for room, region in chest_regions.ROOM_TO_REGION.items()
                 if region == "Phenac City"]
        self.assertTrue(rooms)
        for room in rooms:
            self.assertEqual("Phenac City", chest_regions.region_for_room(room), room)

    def test_location_shuffle_only_is_unchanged(self) -> None:
        """The widened window must not leak into vanilla travel, where the forced Realgam trip IS the next
        thing the game does and skipping it would be editing a story beat."""
        self.assertIs(story_bytes.TRAVEL_SHUFFLE_ONLY, self._bump().gate)
        for byte in (0x3E, 0x3F, 0x40):
            self.assertIsNotNone(story_bytes.live_bump_for("Phenac City", byte, True, False), hex(byte))
            for scooter in (False, True):
                self.assertIsNone(story_bytes.live_bump_for("Phenac City", byte, False, scooter), hex(byte))


class TestTheFloor(unittest.TestCase):
    def test_the_icon_enters_the_unlocked_town(self) -> None:
        self.assertEqual(0x41, story_bytes.area_entry_floor("Phenac City"))

    def test_no_mark_anywhere_is_needed_for_it(self) -> None:
        """The whole point: a location-shuffle player may never have been to Realgam."""
        self.assertIsNone(story_bytes.dynamic_region_floor("Phenac City", {}))
        self.assertIsNone(story_bytes.dynamic_region_floor("Phenac City", {"Phenac City": 0x3F}))
        self.assertIsNone(story_bytes.dynamic_region_floor("Phenac City",
                                                           {"Realgam Tower": 0x41, "Phenac City": 0x3F}))

    def test_the_return_trip_does_not_kick_the_player_out(self) -> None:
        """The player's sentence, as a sequence. Land at 0x3E, get lifted to 0x41, leave, come back -- and
        the hover must not name the locked town again. Asserted with NO Realgam mark, which is the case that
        was broken."""
        memory = rc.AreaStoryByteMemory()
        self.assertEqual(0x41, memory.target_for("Phenac City"))      # first landing
        memory.observe("Phenac City", 0x3F)                            # the game's own first-visit beat
        memory.observe("Pyrite Town", 0x30)                            # went somewhere else
        self.assertEqual(0x41, memory.target_for("Phenac City"))      # return trip

    def test_a_player_past_the_town_keeps_their_own_progress(self) -> None:
        """Raise-only. A mark above the floor still wins -- the override is a floor, not a value."""
        memory = rc.AreaStoryByteMemory()
        memory.observe("Phenac City", 0x4C)
        self.assertEqual(0x4C, memory.target_for("Phenac City"))

    def test_the_unlock_check_still_credits_at_the_games_own_byte(self) -> None:
        """`area_unlock_floor` deliberately does not read the override. Crediting `Unlock - Phenac City` at
        0x41 would fire it three rungs late -- ADDENDUM 324's reason for splitting the two functions."""
        self.assertEqual(0x3E, story_bytes.area_unlock_floor("Phenac City"))
        self.assertEqual(0x3E, story_bytes.region_floor("Phenac City"))

    def test_the_deleted_rule_left_nothing_that_can_never_bind(self) -> None:
        """ADDENDUM 247's fence would refuse a rule whose floor is not above its area's entry floor, so the
        old Phenac rule had to GO rather than sit beside the override."""
        for rule in story_bytes.AREA_FLOOR_RULES:
            self.assertNotEqual("Phenac City", rule.target)


class TestTheTwoHalvesAgree(PokemonXDTestBase):
    def test_the_icon_and_the_bump_name_the_same_byte(self) -> None:
        """If they disagreed, the icon and the bump would fight over the town every time the map opened --
        the "two writers, one byte" shape (ADDENDUM 255)."""
        bump = [b for b in story_bytes.LIVE_STORY_BYTE_BUMPS if b.region == "Phenac City"][0]
        self.assertEqual(story_bytes.area_entry_floor("Phenac City"), bump.becomes)

    def test_0x41_grants_no_region_the_player_has_not_earned(self) -> None:
        """0x3F -> 0x41 names `Realgam Tower` in `opens_regions`, which looks like a leak. It is not: with
        travel shuffle on the client holds every not-yet-received destination's map bit clear, so Realgam is
        gateway-only and the story unlock is taken back as fast as the game grants it."""
        from ..travel_locations import gateway_only_regions

        self.assertIn("Realgam Tower", gateway_only_regions())
