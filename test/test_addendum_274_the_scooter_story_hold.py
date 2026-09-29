"""ADDENDUM 274 (2026-09-18): holding the story below the upgrade the item is meant to grant.

Player: *"what happens if the player gets the scooter upgrade through story? can we prevent that?"* then
*"Build with your suggestion of holding at 0x57, but make it an option -- 'shuffle scooter upgrade'. Make the
option apply to both location shuffle and normal."*

ADDENDUM 273 served the STRANDED ship whenever the player lacked the Scooter. That holds on the MAP route,
because the hover is a pre-load hook. It does not hold on a story warp into the ship rooms: there is no
pre-load hook outside the map screen (ADDENDA 177, 255), so the room is already built by the time the client
sees it, and the clamp only bites on re-entry. Measured: one real-ship visit leaks.

## Why the fix is a hold and not a fight

`0x57 -> 0x5A` is the game writing its own byte during a cutscene. ADDENDUM 213 already learned what arguing
with that costs -- `declined_write_failed` exists because "something else owns this byte; fighting it every
tick would be worse than declining". So the cutscene plays out, and the story is then held one tier below it.

## Why 0x57 is a hold and not a rollback

Every transition past the upgrade is already behind the Scooter in logic: 0x5B is the first fight on the ship,
0x5D opens the Key Lair, 0x5F the Outskirt Stand, 0x62 Snagem -- the six regions ADDENDUM 273 put downstream
of the SS Libra edge. Holding at 0x57 does not invent a restriction, it makes the GAME agree with the graph
the seed was generated against.

And `SCOOTER_HOLD_BAND` is the safety story. The hold will only pull back from 0x58..0x5B -- the transition's
own passthrough values plus the upgrade and the first fight, all of them reachable only through the cutscene
being undone. Above that the player got past the ship by a route this addendum did not model, and pulling them
back would be destroying progress rather than declining an advance, so it declines instead. **A hold that
cannot rewind more than four tiers cannot eat a run.**

Nothing is lost either way: `SCOOTER_GRANT_ON_ARRIVAL` writes the upgrade byte the moment the item lands,
rather than making the player replay the Gateon cutscene.
"""
from __future__ import annotations

import sys
import types
import unittest

if "dolphin_memory_engine" not in sys.modules:
    _stub = types.ModuleType("dolphin_memory_engine")
    _stub.hook = _stub.un_hook = lambda: None
    _stub.is_hooked = lambda: False
    _stub.read_bytes = lambda address, length: b""
    _stub.write_bytes = lambda address, data: None
    sys.modules["dolphin_memory_engine"] = _stub

from unittest import mock

from . import PokemonXDTestBase
from .. import items, ram_client as rc

BASE = 0x80479120


class _Byte:
    def __init__(self, value): self.value = value
    def write(self, address, payload): self.value = payload[0]
    def patch(self): return mock.patch.object(rc, "write_bytes", self.write)


class TestTheNumbers(unittest.TestCase):
    def test_the_hold_floor_is_one_tier_below_the_upgrade(self) -> None:
        from ..game_data import story_bytes as sb

        upgrade = [t for t in sb.TRANSITIONS if t.after == rc.SS_LIBRA_SCOOTER_FLOOR]
        self.assertEqual(1, len(upgrade))
        self.assertEqual(rc.SCOOTER_HOLD_FLOOR, upgrade[0].before,
                         "the hold must park on the tier the upgrade transition starts from")

    def test_the_band_cannot_reach_a_won_game(self) -> None:
        self.assertLess(rc.SCOOTER_HOLD_BAND[1], rc.VICTORY_STORY_BYTE)

    def test_the_band_is_small_enough_that_a_rewind_cannot_eat_a_run(self) -> None:
        low, high = rc.SCOOTER_HOLD_BAND
        self.assertLessEqual(high - rc.SCOOTER_HOLD_FLOOR, 4)
        self.assertGreater(low, rc.SCOOTER_HOLD_FLOOR)


class TestTheHold(unittest.TestCase):
    def _hold(self, **kw):
        return rc.ScooterStoryHold(enabled=True, **kw)

    def test_it_pulls_the_upgrade_back(self) -> None:
        byte = _Byte(rc.SS_LIBRA_SCOOTER_FLOOR)
        hold = self._hold()
        with byte.patch():
            note = hold.poll(BASE, byte.value)
        self.assertEqual(rc.SCOOTER_HOLD_FLOOR, byte.value)
        self.assertEqual(1, hold.holds)
        self.assertIn("Scooter Upgrade", note)

    def test_it_catches_the_first_fight_too(self) -> None:
        """0x5B is only reachable from 0x5A, so a player who slipped one tier further is still inside the
        cutscene's own consequences."""
        byte = _Byte(0x5B)
        hold = self._hold()
        with byte.patch():
            hold.poll(BASE, byte.value)
        self.assertEqual(rc.SCOOTER_HOLD_FLOOR, byte.value)

    def test_it_leaves_a_byte_below_the_upgrade_alone(self) -> None:
        for value in (0x16, 0x4E, 0x50, rc.SCOOTER_HOLD_FLOOR):
            byte = _Byte(value)
            with byte.patch():
                self.assertIsNone(self._hold().poll(BASE, value))
            self.assertEqual(value, byte.value)

    def test_it_declines_past_the_band_rather_than_rewinding(self) -> None:
        """The safety story, asserted. 0x5D+ means the player got past the ship some way this did not model,
        and pulling them back from there is a rollback, not a hold."""
        for value in (0x5D, 0x62, 0x6E, rc.VICTORY_STORY_BYTE):
            byte = _Byte(value)
            hold = self._hold()
            with byte.patch():
                self.assertIsNone(hold.poll(BASE, value))
            self.assertEqual(value, byte.value, f"0x{value:02X} must not be pulled back")
            self.assertEqual(1, hold.declined_out_of_band)

    def test_it_writes_nothing_when_the_option_is_off(self) -> None:
        byte = _Byte(rc.SS_LIBRA_SCOOTER_FLOOR)
        with byte.patch():
            self.assertIsNone(rc.ScooterStoryHold(enabled=False).poll(BASE, byte.value))
        self.assertEqual(rc.SS_LIBRA_SCOOTER_FLOOR, byte.value)

    def test_an_unreadable_byte_writes_nothing(self) -> None:
        with mock.patch.object(rc, "write_bytes", lambda a, p: self.fail("wrote on an unreadable byte")):
            self.assertIsNone(self._hold().poll(BASE, None))

    def test_it_only_narrates_once(self) -> None:
        """The hold re-fires every poll while the cutscene keeps re-granting; the player needs telling once."""
        byte = _Byte(rc.SS_LIBRA_SCOOTER_FLOOR)
        hold = self._hold()
        with byte.patch():
            self.assertIsNotNone(hold.poll(BASE, rc.SS_LIBRA_SCOOTER_FLOOR))
            self.assertIsNone(hold.poll(BASE, rc.SS_LIBRA_SCOOTER_FLOOR))


class TestTheGrant(unittest.TestCase):
    def test_the_item_pays_the_held_advance_back(self) -> None:
        byte = _Byte(rc.SS_LIBRA_SCOOTER_FLOOR)
        hold = rc.ScooterStoryHold(enabled=True)
        with byte.patch():
            hold.poll(BASE, byte.value)                 # held at 0x57
            self.assertEqual(rc.SCOOTER_HOLD_FLOOR, byte.value)
            hold.scooter_held = True
            note = hold.poll(BASE, byte.value)
        self.assertEqual(rc.SS_LIBRA_SCOOTER_FLOOR, byte.value)
        self.assertEqual(1, hold.grants)
        self.assertIn("no need to replay", note)

    def test_it_grants_once_and_never_again(self) -> None:
        byte = _Byte(rc.SCOOTER_HOLD_FLOOR)
        hold = rc.ScooterStoryHold(enabled=True, scooter_held=True)
        with byte.patch():
            hold.poll(BASE, byte.value)
            byte.value = 0x62                            # the player has played on
            hold.poll(BASE, byte.value)
        self.assertEqual(0x62, byte.value, "a second grant would drag them back to the ship")
        self.assertEqual(1, hold.grants)

    def test_it_does_not_invent_progress_on_a_byte_it_never_parked(self) -> None:
        """Arriving with the item while the story sits somewhere else entirely -- granting on top of that
        would be writing an advance the player never reached."""
        byte = _Byte(0x20)
        hold = rc.ScooterStoryHold(enabled=True, scooter_held=True)
        with byte.patch():
            self.assertIsNone(hold.poll(BASE, byte.value))
        self.assertEqual(0x20, byte.value)


class TestTheOptionGatesEverything(PokemonXDTestBase):
    options = {"shuffle_scooter_upgrade": False}

    def test_the_item_does_not_exist_by_default(self) -> None:
        self.assertNotIn(items.SCOOTER_ITEM_NAME, {i.name for i in self.multiworld.itempool})

    def test_and_ss_libra_is_therefore_ungated(self) -> None:
        self.collect_key_item_chain()
        self.assertTrue(self.multiworld.state.can_reach("SS Libra", player=self.player))


class TestTheOptionOnInTravelShuffle(PokemonXDTestBase):
    """*"Make the option apply to both location shuffle and normal."*"""

    options = {"shuffle_scooter_upgrade": True, "randomize_travel_locations": True}

    def test_the_item_exists_here_too(self) -> None:
        self.assertIn(items.SCOOTER_ITEM_NAME, {i.name for i in self.multiworld.itempool})
