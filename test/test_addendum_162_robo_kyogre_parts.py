"""ADDENDUM 162 (2026-09-12): the Robo Kyogre Part MacGuffin, and the story-byte override it drives.

Player: "Let's add a maguffin item that enables victory. Name them Robo Kyogre Part. Default it to 8 needed,
range of 1-20. Default how many are available to 12, range of 1-40. When the amount is reached, we flip the
story bit to 0xFF upon entering Gateon - which allows the player to go to citadark from Gateon."

REDESIGNED the same day (ADDENDUM 163) on two corrections:

  * "I want robo-kyogre to be included with the defeat greevil victory condition, not its own condition -
    collecting the parts will let us UNLOCK citadark, where the player can then go beat greevil." The Parts
    briefly were their own Goal choice. They are a KEY: they gate the Citadark Isle entrance, alongside the
    Krane Memos it always needed. Goal and the Ein File S boss rule are untouched.
  * "Unlocking citadark is done through flipping that story bit - it's done automatically with that condition."
    So the story-byte write IS the unlock, not a separate experiment, and the second toggle that used to gate it
    is gone. One option now does both halves -- which is the point: logic and the game agree by construction.

And, on what the override is groundwork for: "when we leave an area, our story byte in that area is saved AND
REAPPLIED when we go back there... Do not make this the default yet." Hence the general save-and-restore with
one wiring, and an option that is off by default.

RETARGETED 2026-09-13 (ADDENDUM 168) throughout the two world-building test classes below. Two things this
file asserted are gone:

  * **"alongside the Krane Memos it always needed"** -- the memo ladder is retired. Citadark Isle is now the
    deepest node of regions.REGION_EDGES, reached through the real story key items
    (PokemonXDTestBase.KEY_ITEM_CHAIN), and the Parts are ANDed onto that edge instead of onto a memo count.
    The Parts' own behaviour is unchanged; only what they sit on top of is.
  * **"the Ein File S still gates the boss itself"** -- Ein File S is not an item in the game at all
    (ADDENDUM 167 resolved every real id) and is in items.ITEMS_REMOVED_FROM_POOL, so regions.py's victory
    event no longer carries an access_rule. Reaching Citadark Isle IS the logical win condition now, with the
    real in-game detection living in Client.py. The Parts therefore gate victory directly rather than by
    standing next to a second boss item.

The story-byte override half of the file (everything below TestImpossibleConfigurationIsCaughtEarly) is
untouched -- none of it ever depended on the region model.
"""
from __future__ import annotations

import unittest

from BaseClasses import CollectionState
from Options import OptionError

from . import PokemonXDTestBase
from .. import items, ram_client as rc
from ..options import (
    RoboKyogrePartsAvailable, RoboKyogrePartsRequired, RoboKyogrePartsUnlockCitadark,
)
from ._chest_samples import DEEPEST_CHEST

VICTORY = "Citadark Isle - Defeat Cipher Boss"
PART = items.MACGUFFIN_ITEM_NAME
BLOCK_BASE = 0x80479380


# ADDENDUM 273: derived, not typed. These were the literals 5 and 4 -- "the full chain" and "one edge short"
# -- and adding the Scooter Upgrade to KEY_ITEM_CHAIN silently turned every one of them into a different
# claim. Module level rather than per-class, because more than one class in this file uses them.
FULL_CHAIN = len(PokemonXDTestBase.KEY_ITEM_CHAIN)
ONE_SHORT = FULL_CHAIN - 1


# ADDENDUM 335 (2026-09-24): the probe used to be "Citadark Isle - Pre-Boss Item", one of the fourteen
# uncertain Overworld Items the player has now played and ruled not real. Any Citadark location does this job
# -- what these tests measure is the REGION's gate, never the location -- so it is a real chest now, and one
# constant rather than two classes naming their own.
CITADARK_PROBE = "Citadark Isle Chest 2"


class TestTheOptions(unittest.TestCase):
    def test_the_ranges_and_defaults_are_what_was_asked_for(self) -> None:
        self.assertEqual((RoboKyogrePartsRequired.range_start, RoboKyogrePartsRequired.range_end), (1, 20))
        self.assertEqual(RoboKyogrePartsRequired.default, 8)
        self.assertEqual((RoboKyogrePartsAvailable.range_start, RoboKyogrePartsAvailable.range_end), (1, 40))
        self.assertEqual(RoboKyogrePartsAvailable.default, 12)

    def test_one_option_does_both_halves_and_is_on_by_default(self) -> None:
        """ADDENDUM 163 collapsed two switches into one. It writes to save data, so it is never a default."""
        # FLIPPED 2026-09-14 (ADDENDUM 196): on by default, per the player's own YAML ("On by default.").
        self.assertEqual(RoboKyogrePartsUnlockCitadark.default, 1)

    def test_the_parts_are_not_a_goal(self) -> None:
        """They gate Citadark Isle; beating Greevil there is still the goal."""
        from ..options import Goal

        self.assertFalse(hasattr(Goal, "option_collect_robo_kyogre_parts"))
        self.assertEqual(Goal.default, Goal.option_defeat_greevil)

    def test_the_separate_override_toggle_is_gone(self) -> None:
        """Two overlapping switches for one behaviour is worse than one."""
        from .. import options

        self.assertFalse(hasattr(options, "EnableStoryByteOverride"))


class TestTheItem(unittest.TestCase):
    def test_it_is_progression_with_no_in_game_item(self) -> None:
        """A MacGuffin exists in logic only -- nothing is written into the Bag, same as a Travel Unlock."""
        data = items.ITEM_TABLE[PART]
        self.assertEqual(data.classification.name, "progression")
        self.assertIsNone(data.game_item_id)

    def test_its_id_is_frozen_and_appended_rather_than_inserted(self) -> None:
        """_table hands out offsets by list position, so inserting earlier would renumber every later item --
        the exact failure the STABLE ID FREEZE section exists to prevent."""
        self.assertEqual(items.ITEM_TABLE[PART].id_offset, 254)
        self.assertEqual(items._FROZEN_ITEM_OFFSETS[PART], 254)

    def test_no_other_item_shares_that_offset(self) -> None:
        offsets = [d.id_offset for d in items.ITEM_TABLE.values()]
        self.assertEqual(len(offsets), len(set(offsets)))

    def test_it_is_never_drawn_as_random_filler(self) -> None:
        self.assertNotIn(PART, items._RANDOM_FILLER_POOL)

    def test_it_has_its_own_name_group(self) -> None:
        self.assertEqual(items.ITEM_NAME_GROUPS["Robo Kyogre Parts"], {PART})


class TestPartsGateCitadark(PokemonXDTestBase):
    options = {
        "shuffle_trainer_defeats": True,
        "randomize_chests": True,
        "robo_kyogre_parts_unlock_citadark": True,
        "robo_kyogre_parts_required": 8,
        "robo_kyogre_parts_available": 12,
    }

    CITADARK = CITADARK_PROBE

    # RETARGETED 2026-09-13 (ADDENDUM 168): `memos` was "how many of the five Krane Memos are held", the only
    # thing that used to open the map. It is now "how many links of KEY_ITEM_CHAIN are held" -- see
    # PokemonXDTestBase for the table of what each prefix opens. `chain=5` is the full chain and is what puts
    # the player at Citadark Isle's door; `chain=4` stops at Cipher Key Lair, one edge short, which is the
    # direct equivalent of the old "4 of 5 memos".
    def _state_with(self, chain: int, parts: int) -> CollectionState:
        state = CollectionState(self.multiworld)
        for name in self.KEY_ITEM_CHAIN[:chain]:
            state.collect(self.get_item_by_name(name), prevent_sweep=True)
        for _ in range(parts):
            state.collect(self.get_item_by_name(PART), prevent_sweep=True)
        return state

    def _reach(self, name, chain, parts):
        return self.multiworld.get_location(name, self.player).can_reach(self._state_with(chain, parts))

    def test_exactly_the_requested_number_exist_in_the_pool(self) -> None:
        self.assertEqual([i.name for i in self.multiworld.itempool].count(PART), 12)

    def test_citadark_opens_exactly_at_the_required_count(self) -> None:
        # RETARGETED (ADDENDUM 168): full key-item chain instead of five memos; the Parts arithmetic is what
        # this test is about and is unchanged -- 7 is not enough, 8 is.
        self.assertFalse(self._reach(self.CITADARK, FULL_CHAIN, 7))
        self.assertTrue(self._reach(self.CITADARK, FULL_CHAIN, 8))

    def test_the_parts_are_on_top_of_the_key_item_chain_not_instead_of_it(self) -> None:
        """Every Part in the game must not substitute for the route there.

        RETARGETED 2026-09-13 (ADDENDUM 168), was "...not instead of the memos". Same assertion against the
        real graph: holding every Part that exists, but missing the System Lever that opens Cipher Key Lair
        (deep), must leave Citadark Isle shut.
        """
        self.assertFalse(self._reach(self.CITADARK, ONE_SHORT, 12))
        self.assertTrue(self._reach(self.CITADARK, FULL_CHAIN, 12))

    def test_everything_that_already_needed_citadark_now_needs_the_parts_too(self) -> None:
        """What makes them read as the endgame key rather than a side collection -- the top chest threshold is
        gated on Citadark Isle (see rules.py's sphere logic), so it inherits the Parts requirement for free.
        RETARGETED (ADDENDUM 168) only in how the route to Citadark Isle is opened; the Parts half is the same.
        """
        from .. import locations

        top_chest = DEEPEST_CHEST
        self.assertFalse(self._reach(top_chest, FULL_CHAIN, 7))
        self.assertTrue(self._reach(top_chest, FULL_CHAIN, 8))

    def test_the_parts_are_the_last_thing_victory_waits_on(self) -> None:
        """RETARGETED 2026-09-13 (ADDENDUM 168), was "the boss still needs the Ein File S".

        There is no Ein File S: the item does not exist in the game (ADDENDUM 167 resolved every real id), it is
        in items.ITEMS_REMOVED_FROM_POOL, and regions.py's victory event has no access_rule left at all. So the
        old "both, not either" split collapses into one: with this option on, the Parts ARE what victory waits
        on, because reaching Citadark Isle is the whole logical requirement and the Parts gate that entrance.
        Asserted as an exact boundary (7 no, 8 yes) so the collapse cannot quietly become "victory needs
        nothing".
        """
        self.assertNotIn("Ein File S", [i.name for i in self.multiworld.itempool])
        self.assertIn("Ein File S", items.ITEMS_REMOVED_FROM_POOL)
        self.assertFalse(self._reach(VICTORY, FULL_CHAIN, 7))
        self.assertTrue(self._reach(VICTORY, FULL_CHAIN, 8))


class TestWithTheOptionOff(PokemonXDTestBase):
    # ADDENDUM 196: the Parts option now defaults ON, and this class is the option-OFF twin.
    options = {"shuffle_trainer_defeats": True, "robo_kyogre_parts_unlock_citadark": False}

    def test_no_parts_are_added_when_the_option_is_off(self) -> None:
        """`progression` carries a placement guarantee -- forcing items nothing requires into the pool wastes
        slots for no logic benefit."""
        self.assertNotIn(PART, [i.name for i in self.multiworld.itempool])

    def _chain_state(self, count: int = 5) -> CollectionState:
        # RETARGETED 2026-09-13 (ADDENDUM 168): the five Krane Memos are not items any more; the route to
        # Citadark Isle is KEY_ITEM_CHAIN (see PokemonXDTestBase).
        state = CollectionState(self.multiworld)
        for name in self.KEY_ITEM_CHAIN[:count]:
            state.collect(self.get_item_by_name(name), prevent_sweep=True)
        return state

    def test_citadark_needs_only_the_key_item_chain_and_no_parts(self) -> None:
        """RETARGETED 2026-09-13 (ADDENDUM 168), was "needs only the memos exactly as before". With the option
        off the Parts must add nothing: the ordinary route in has to be sufficient by itself, and one link short
        of it still has to be insufficient (otherwise this would pass with the Citadark edge ungated)."""
        citadark = self.multiworld.get_location(CITADARK_PROBE, self.player)
        self.assertFalse(citadark.can_reach(self._chain_state(ONE_SHORT)))
        self.assertTrue(citadark.can_reach(self._chain_state(FULL_CHAIN)))

    def test_victory_needs_nothing_but_reaching_citadark_isle(self) -> None:
        """RETARGETED 2026-09-13 (ADDENDUM 168), was "victory still needs the Ein File S".

        The Ein File S access_rule is gone with the item (items.ITEMS_REMOVED_FROM_POOL), so with the Parts
        option off the victory event is reachable exactly when Citadark Isle is -- no more, and no less. The
        "no less" half is the one worth keeping: one link short of the chain must still not win the game.
        """
        self.assertNotIn("Ein File S", [i.name for i in self.multiworld.itempool])
        victory = self.multiworld.get_location(VICTORY, self.player)
        self.assertFalse(victory.can_reach(self._chain_state(ONE_SHORT)))
        self.assertTrue(victory.can_reach(self._chain_state(FULL_CHAIN)))


class TestImpossibleConfigurationIsCaughtEarly(unittest.TestCase):
    def test_requiring_more_parts_than_exist_raises_at_generate_early(self) -> None:
        """Citadark Isle could never be reached, so the seed is unwinnable. Loud and early beats an obscure
        fill failure much later."""

        class _Case(PokemonXDTestBase):
            options = {"robo_kyogre_parts_unlock_citadark": True,
                       "robo_kyogre_parts_required": 20, "robo_kyogre_parts_available": 5}

            def runTest(self):
                pass

        with self.assertRaises(OptionError):
            _Case().setUp()


# ============================================================================================================
# The story-byte override
# ============================================================================================================
class _Ram:
    def __init__(self, story_byte: int) -> None:
        self.byte = story_byte
        self.writes: list[tuple[int, bytes]] = []
        self.explode = False

    def read(self, address: int, length: int) -> bytes:
        if self.explode:
            raise RuntimeError("Dolphin went away")
        if address == BLOCK_BASE + rc.STORY_RECORD_OFFSET:
            return bytes([self.byte]) + bytes(length - 1)
        return bytes(length)

    def write(self, address: int, payload: bytes) -> None:
        if self.explode:
            raise RuntimeError("Dolphin went away")
        self.writes.append((address, payload))
        if address == BLOCK_BASE + rc.STORY_RECORD_OFFSET + rc.STORY_BYTE_OFFSET:
            self.byte = payload[0]


class _Patched:
    def __init__(self, ram: _Ram) -> None:
        self.ram = ram

    def __enter__(self):
        self._r, self._w = rc.read_bytes, rc.write_bytes
        rc.read_bytes, rc.write_bytes = self.ram.read, self.ram.write
        return self.ram

    def __exit__(self, *exc):
        rc.read_bytes, rc.write_bytes = self._r, self._w


OUTSIDE = 140  # Pokemon HQ Lab interior -- any non-Gateon room
GATEON = 153


class TestStoryByteOverride(unittest.TestCase):
    def _walk(self, override, ram, rooms):
        notes = []
        with _Patched(ram):
            for room in rooms:
                notes.append(override.poll(BLOCK_BASE, room))
        return notes

    def test_it_writes_nothing_until_armed(self) -> None:
        override, ram = rc.StoryByteOverride(), _Ram(0x2F)
        self._walk(override, ram, [OUTSIDE, GATEON, GATEON, OUTSIDE])
        self.assertEqual(ram.writes, [])
        self.assertEqual(ram.byte, 0x2F)

    def test_entering_gateon_armed_sets_the_override_value(self) -> None:
        override, ram = rc.StoryByteOverride(armed=True), _Ram(0x2F)
        self._walk(override, ram, [OUTSIDE, GATEON])
        self.assertEqual(ram.byte, rc.STORY_OVERRIDE_VALUE)
        self.assertEqual(override.applications, 1)
        self.assertEqual(override.saved_byte, 0x2F)

    def test_leaving_puts_the_original_back(self) -> None:
        override, ram = rc.StoryByteOverride(armed=True), _Ram(0x2F)
        self._walk(override, ram, [OUTSIDE, GATEON, GATEON, OUTSIDE])
        self.assertEqual(ram.byte, 0x2F)
        self.assertEqual(override.restorations, 1)
        self.assertFalse(override.active)

    def test_it_applies_once_per_visit_not_once_per_poll(self) -> None:
        override, ram = rc.StoryByteOverride(armed=True), _Ram(0x2F)
        self._walk(override, ram, [GATEON] * 10)
        self.assertEqual(override.applications, 1)
        self.assertEqual(len(ram.writes), 1)

    def test_a_second_visit_works_again(self) -> None:
        override, ram = rc.StoryByteOverride(armed=True), _Ram(0x2F)
        self._walk(override, ram, [GATEON, OUTSIDE, GATEON, OUTSIDE])
        self.assertEqual((override.applications, override.restorations), (2, 2))
        self.assertEqual(ram.byte, 0x2F)

    def test_every_gateon_room_counts_as_inside(self) -> None:
        """All SIX room ids are one place.

        WIDENED 2026-09-17 (ADDENDUM 254, player: "I have 8 robo kyogre parts - why is gateon not getting its
        story byte written?"). This asserted the literal `{147, 153, 156}` from ADDENDUM 152's compilation,
        which is the three rooms that set was typed from -- so it passed while the Krabby Klub basement (146)
        and both Gateon Tower floors (158, 160) silently did nothing, because it pinned the same mistake the
        code made. A test that restates a literal cannot catch the literal being wrong.

        It now pins the RELATIONSHIP instead: every room the region table calls Gateon Port must count as
        inside. That is the claim worth defending, and it is the one that was false."""
        from ..game_data import chest_regions

        region_table = {room for room, region in chest_regions.ROOM_TO_REGION.items()
                        if region == "Gateon Port"}
        self.assertTrue(region_table <= rc.GATEON_ROOM_IDS,
                        f"not counted as Gateon: {sorted(region_table - rc.GATEON_ROOM_IDS)}")
        self.assertIn(147, rc.GATEON_ROOM_IDS, "the entrance building is Gateon even with no chest in it")
        self.assertEqual(6, len(rc.GATEON_ROOM_IDS))

        override, ram = rc.StoryByteOverride(armed=True), _Ram(0x2F)
        self._walk(override, ram, [OUTSIDE] + sorted(rc.GATEON_ROOM_IDS))
        self.assertEqual(override.applications, 1, "moving between Gateon rooms is not leaving")
        self.assertEqual(override.restorations, 0)

    def test_no_gateon_room_is_missing_from_either_source(self) -> None:
        """The ADDENDUM 243 fence, applied to rooms. Two independently-maintained descriptions of the same
        fact drifted apart and nothing noticed -- which is the `Defeat -` bug class (ADDENDA 185, 211, 241,
        242) in a new table. Derivation is what fixes it; this is what keeps it fixed."""
        from ..game_data import chest_regions

        for room in rc.GATEON_ROOM_IDS:
            region = chest_regions.ROOM_TO_REGION.get(room)
            self.assertIn(region, ("Gateon Port", None),
                          f"room {room} is in the override set but the region table calls it {region}")

    # ==========================================================================================================
    # ADDENDUM 255 (2026-09-17): the hover write, and the map screen that would have undone it
    # ==========================================================================================================
    # Player: "I want it to fire even if random_locations is off. It should write gateon as 0x6E as we hover it
    # so long as we have the kyogre parts."

    MAP = rc.MAP_SCREEN_ROOM_ID

    def test_hovering_gateon_writes_the_byte_before_the_room_loads(self) -> None:
        """The whole reason the hover is the right hook (ADDENDUM 177): once Gateon has loaded it was built
        from whatever the byte was at load time, so a write on arrival is one visit too late."""
        override, ram = rc.StoryByteOverride(armed=True), _Ram(0x2F)
        with _Patched(ram):
            override.poll(BLOCK_BASE, OUTSIDE)
            note = override.poll_hover(BLOCK_BASE, "Gateon Port")
        self.assertIsNotNone(note)
        self.assertEqual(ram.byte, rc.STORY_OVERRIDE_VALUE)
        self.assertEqual(override.saved_byte, 0x2F)

    def test_the_map_screen_does_not_undo_the_hover_write(self) -> None:
        """The trap this had to be built around. Opening the map puts the player in room 910, which is not a
        Gateon room -- so the tick after a hover write, `poll` would have read "not inside and active" and
        restored the byte straight back before the destination ever loaded. The hover would undo itself every
        time and look like it had never fired."""
        override, ram = rc.StoryByteOverride(armed=True), _Ram(0x2F)
        with _Patched(ram):
            override.poll_hover(BLOCK_BASE, "Gateon Port")
            for _ in range(5):
                override.poll(BLOCK_BASE, self.MAP)      # still choosing
        self.assertEqual(ram.byte, rc.STORY_OVERRIDE_VALUE, "the map screen is limbo, not 'outside Gateon'")
        self.assertEqual(override.restorations, 0)
        self.assertTrue(override.active)

    def test_travelling_after_the_hover_keeps_it_and_leaving_restores(self) -> None:
        override, ram = rc.StoryByteOverride(armed=True), _Ram(0x2F)
        with _Patched(ram):
            override.poll_hover(BLOCK_BASE, "Gateon Port")
            override.poll(BLOCK_BASE, self.MAP)
            override.poll(BLOCK_BASE, GATEON)            # arrived
            self.assertEqual(ram.byte, rc.STORY_OVERRIDE_VALUE)
            self.assertEqual(override.applications, 1, "arrival must not re-apply what the hover already did")
            override.poll(BLOCK_BASE, OUTSIDE)           # left
        self.assertEqual(ram.byte, 0x2F)
        self.assertEqual(override.restorations, 1)

    def test_backing_out_of_the_map_restores(self) -> None:
        """ADDENDUM 229's case, handled by the restore that was already here: a player who hovers Gateon and
        then backs out lands in the room they came from, which is not a Gateon room."""
        override, ram = rc.StoryByteOverride(armed=True), _Ram(0x2F)
        with _Patched(ram):
            override.poll(BLOCK_BASE, OUTSIDE)
            override.poll_hover(BLOCK_BASE, "Gateon Port")
            override.poll(BLOCK_BASE, self.MAP)
            override.poll(BLOCK_BASE, OUTSIDE)           # backed out
        self.assertEqual(ram.byte, 0x2F)
        self.assertEqual(override.restorations, 1)
        self.assertFalse(override.active)

    def test_hovering_anywhere_else_writes_nothing_when_not_holding_the_byte(self) -> None:
        override, ram = rc.StoryByteOverride(armed=True), _Ram(0x2F)
        with _Patched(ram):
            for region in ("Phenac City", "Pyrite Town", "Agate Village", None):
                self.assertIsNone(override.poll_hover(BLOCK_BASE, region))
        self.assertEqual(ram.writes, [])
        self.assertEqual(ram.byte, 0x2F)

    def test_hovering_off_gateon_restores_before_the_destination_loads(self) -> None:
        """The half the first cut of ADDENDUM 255 missed, caught by the player: "isn't 'not applying' on the
        map going to break the system since we load in before the write?"

        Applying on the hover was handled; LEAVING was not. Before the hover hook existed, opening the map from
        inside Gateon put the player in room 910, `poll` read that as "not inside", and the restore happened
        there -- on the map, before the destination loaded. Teaching `poll` to ignore the map screen took that
        away, and the restore slid to after the arrival, so the next area would be built while our synthetic
        0x6E was still in the byte. Now the hover drives both directions."""
        override, ram = rc.StoryByteOverride(armed=True), _Ram(0x2F)
        with _Patched(ram):
            override.poll(BLOCK_BASE, GATEON)                     # in Gateon, holding 0x6E
            self.assertEqual(ram.byte, rc.STORY_OVERRIDE_VALUE)
            override.poll(BLOCK_BASE, self.MAP)                   # opened the map
            note = override.poll_hover(BLOCK_BASE, "Phenac City")  # cursor moved off Gateon
        self.assertIsNotNone(note)
        self.assertEqual(ram.byte, 0x2F, "Phenac must not be built from our 0x6E")
        self.assertFalse(override.active)
        self.assertEqual(override.restorations, 1)

    def test_the_cursor_can_go_back_and_forth(self) -> None:
        """A player scrolling across the map passes over several destinations. Each one gets the byte it
        needs, and nothing accumulates."""
        override, ram = rc.StoryByteOverride(armed=True), _Ram(0x2F)
        with _Patched(ram):
            for region in ("Gateon Port", "Phenac City", "Gateon Port", "Pyrite Town", "Gateon Port"):
                override.poll_hover(BLOCK_BASE, region)
                expected = rc.STORY_OVERRIDE_VALUE if region == "Gateon Port" else 0x2F
                self.assertEqual(ram.byte, expected, region)
        self.assertEqual(override.applications, 3)
        self.assertEqual(override.restorations, 2)

    def test_an_unreadable_cursor_changes_nothing_in_either_direction(self) -> None:
        """This project never acts on a guess. A cursor read that failed is not evidence of anything."""
        override, ram = rc.StoryByteOverride(armed=True), _Ram(0x2F)
        with _Patched(ram):
            override.poll_hover(BLOCK_BASE, "Gateon Port")
            writes_before = len(ram.writes)
            self.assertIsNone(override.poll_hover(BLOCK_BASE, None))
        self.assertEqual(len(ram.writes), writes_before)
        self.assertTrue(override.active, "an unreadable cursor must not drop what we are holding")
        self.assertEqual(ram.byte, rc.STORY_OVERRIDE_VALUE)

    def test_hovering_unarmed_writes_nothing(self) -> None:
        override, ram = rc.StoryByteOverride(), _Ram(0x2F)
        with _Patched(ram):
            self.assertIsNone(override.poll_hover(BLOCK_BASE, "Gateon Port"))
        self.assertEqual(ram.writes, [])

    def test_hovering_twice_applies_once(self) -> None:
        override, ram = rc.StoryByteOverride(armed=True), _Ram(0x2F)
        with _Patched(ram):
            for _ in range(6):
                override.poll_hover(BLOCK_BASE, "Gateon Port")
        self.assertEqual(override.applications, 1)
        self.assertEqual(len(ram.writes), 1)

    def test_walking_in_still_works_without_any_hover(self) -> None:
        """The room trigger is kept, not replaced -- it covers walking in, a story warp, or a cursor read that
        simply failed that tick."""
        override, ram = rc.StoryByteOverride(armed=True), _Ram(0x2F)
        self._walk(override, ram, [OUTSIDE, GATEON])
        self.assertEqual(ram.byte, rc.STORY_OVERRIDE_VALUE)
        self.assertEqual(override.applications, 1)

    def test_real_progress_made_inside_gateon_is_never_rolled_back(self) -> None:
        """The player's own "UNLESS something in Pyrite allows us to go to Z story byte" clause, implemented as
        the general rule: restore only if the live byte has not moved past the remembered one."""
        override, ram = rc.StoryByteOverride(armed=True), _Ram(0x2F)
        with _Patched(ram):
            override.poll(BLOCK_BASE, OUTSIDE)
            override.poll(BLOCK_BASE, GATEON)
            ram.byte = 0x31          # the game itself advanced while we were overridden
            override.poll(BLOCK_BASE, OUTSIDE)
        self.assertEqual(ram.byte, 0x31)
        self.assertEqual(override.declined_restores, 1)
        self.assertEqual(override.restorations, 0)

    def test_an_unknown_room_never_triggers_anything(self) -> None:
        """read_room_id returns None when the four copies disagree. Writing on a guess is not acceptable."""
        override, ram = rc.StoryByteOverride(armed=True), _Ram(0x2F)
        self._walk(override, ram, [None, None])
        self.assertEqual(ram.writes, [])

    def test_an_unreadable_story_byte_means_no_override_rather_than_a_blind_write(self) -> None:
        """It cannot promise a restore it has nothing to restore to."""
        override, ram = rc.StoryByteOverride(armed=True), _Ram(0xFF)  # 0xFF reads as implausible
        self._walk(override, ram, [OUTSIDE, GATEON])
        self.assertEqual(ram.writes, [])
        self.assertFalse(override.active)

    def test_a_failing_write_never_raises(self) -> None:
        override, ram = rc.StoryByteOverride(armed=True), _Ram(0x2F)
        ram.explode = True
        self.assertIsNone(override.poll(BLOCK_BASE, GATEON))

    def test_disarming_mid_visit_still_restores_on_the_way_out(self) -> None:
        """Otherwise a disarm would strand 0xFF in the player's save."""
        override, ram = rc.StoryByteOverride(armed=True), _Ram(0x2F)
        with _Patched(ram):
            override.poll(BLOCK_BASE, GATEON)
            override.armed = False
            override.poll(BLOCK_BASE, OUTSIDE)
        self.assertEqual(ram.byte, 0x2F)

    def test_describe_covers_every_state(self) -> None:
        override = rc.StoryByteOverride()
        self.assertIn("not armed", override.describe())
        override.armed = True
        self.assertIn("waiting", override.describe())
        ram = _Ram(0x2F)
        self._walk(override, ram, [GATEON])
        text = override.describe()
        self.assertIn("ACTIVE", text)
        self.assertIn("0x2F", text)


if __name__ == "__main__":
    unittest.main()


class TestItRunsInBothTravelModes(unittest.TestCase):
    """ADDENDUM 255. `check_story_byte_override` used to return early when `randomize_travel_locations` was
    off (ADDENDUM 169's "their bytes shouldn't be edited"), which left a player holding every Part with nothing
    to show for it. Checked over the AST -- Client.py cannot be imported in this sandbox.

    The narrowness is the point: ADDENDUM 169's rule still holds for every OTHER byte, and the area memory
    still obeys it."""

    @classmethod
    def setUpClass(cls) -> None:
        import ast
        import pathlib

        cls.source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text("utf-8")
        cls.tree = ast.parse(cls.source)

    def _func(self, name):
        import ast

        return next(n for n in ast.walk(self.tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)

    def test_the_parts_override_no_longer_returns_on_the_travel_option(self) -> None:
        import ast

        body = ast.dump(self._func("check_story_byte_override"))
        self.assertNotIn("randomize_travel_locations", body,
                         "the Parts override must run in both travel modes")

    def test_the_area_memory_still_does_return_on_it(self) -> None:
        """The exception is for the Parts override alone. If this ever stops being true it is a separate
        decision, not a side effect of this one."""
        import ast

        self.assertIn("randomize_travel_locations", ast.dump(self._func("check_area_story_memory")))

    def test_the_override_is_asked_about_the_hover(self) -> None:
        import ast

        self.assertIn("poll_hover", ast.dump(self._func("check_story_byte_override")))

    def test_the_area_memory_steps_aside_while_the_override_holds_the_byte(self) -> None:
        """Two writers, one byte. Without this the area memory would write Gateon's ordinary floor straight
        over the 0x6E, and would record our own synthetic value as Gateon's high-water mark -- ADDENDUM 229's
        poisoning failure with our write as the foreign byte."""
        import ast

        func = self._func("check_area_story_memory")
        guards = [n for n in ast.walk(func)
                  if isinstance(n, ast.If) and "story_byte_override" in ast.dump(n.test)
                  and any(isinstance(b, ast.Return) for b in n.body)]
        self.assertEqual(1, len(guards))

    def test_the_override_runs_before_the_area_memory_in_the_poll_loop(self) -> None:
        """The guard above reads `.active`, so the ordering is what makes it correct rather than racy."""
        first = self.source.index("await check_story_byte_override(ctx)")
        second = self.source.index("await check_area_story_memory(ctx)")
        self.assertLess(first, second)
