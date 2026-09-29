"""
ADDENDUM 293 (2026-09-20) -- the SS Libra stops being a rung, and Kaminko's stops being written.

Player, in one message:

    "With scooter upgrade shuffled in, decouple SS Libra from Snagem. To do this, when SS Libra hits 0x5B,
    immediately skip it to 0x5D. Make this happen no matter what on location shuffle, but only with scooter
    shuffle in vanilla. Ensure Snagem's base floor is 0x62. This also means that Snagem is no longer gated
    behind SS libra, which means Key Lair is also not gated behind SS Libra. Ensure the logic chains are
    modified due to this. Also, after Kaminko reaches 0x03, stop writing its floor until it hits one of our
    gates that modifies it - then we can start writing its floor again."

Five changes, and they are not five features. Four of them are one feature seen from four angles.

## Why the ship had become a chokepoint

ADDENDUM 273 made the Scooter Upgrade an Archipelago item and the `SS Libra` region its gate. That was the
whole point, and it was right. What nobody measured at the time is what ELSE was standing behind that region:

  * `travel_locations.TRAVEL_LOCATION_REQUIRED_REGIONS` said Snagem's gateway is sourced at `SS Libra`
    (ADDENDUM 176, the player's own earlier instruction "Gate Snagem logically behind full SS Libra access"),
    and the Key Lair's at `Snagem Hideout`. So the Key Lair inherited the ship through Snagem.
  * `regions.REGION_EDGES` ran `SS Libra -> Cipher Key Lair (exterior)`, and the exterior is a SIBLING tier
    (ADDENDUM 270) whose chain edge survives by design -- so it stayed behind the ship even with travel
    shuffle on, where almost everything else is gateway-only.

MEASURED, travel shuffle on, every progression item held EXCEPT the Scooter Upgrade: **33 regions reachable,
and six blocked by that one item** -- SS Libra, Cipher Key Lair (exterior), Snagem Hideout, Cipher Key Lair,
Cipher Key Lair (deep), Citadark Isle. One placement decided the back half of the game. After this addendum:
**40 regions, and the only one still blocked is the ship itself**, which is what the Scooter is supposed to
gate and all it is supposed to gate.

## The four angles

1. **In game, with travel shuffle:** nothing to do. The player receives `Travel Unlock - Snagem Hideout`, the
   icon appears, `AreaStoryByteMemory` writes the hideout's own first-visit byte and they walk in. This is
   why the loosened graph is a promise the client can keep, and it is why `SNAGEM_BASE_FLOOR` is now fenced
   rather than merely derived -- the whole argument rests on that byte being 0x62.
2. **In game, in a vanilla-travel seed:** the live bump, `SS Libra` 0x5B -> 0x5D. The ship stops being a rung
   on the story ladder the moment the player stands on it.
3. **In logic, with travel shuffle:** the Snagem prerequisite is withdrawn and the Key Lair exterior is
   re-sourced from `Kaminko's House (Robo Groudon)`, the ship's own predecessor.
4. **In logic, in a vanilla-travel seed:** NOTHING CHANGES, and that is the safety argument rather than an
   omission. There the map only offers what the story unlocked, and `ScooterStoryHold` holds the byte below
   the upgrade until the item arrives -- so Snagem really is behind the Scooter, and loosening the graph
   would let the fill put the Scooter itself in Snagem and produce a seed that cannot be finished.

## The fifth change is unrelated, and is its own thing

Kaminko's House is always-open, so its first-visit byte is 0x03 (ADDENDUM 279) and its mark is a floor
(ADDENDUM 278). Between those two, the manor's target after its first visit is "the highest byte ever
recorded there" -- which is whatever the player was carrying when they last wandered past, written into their
save as though it meant something. There are exactly two bytes the manor has ever been shown to care about:
0x03 and the 0x53 Verich tier that `AREA_FLOOR_RULES` already states. So between them, no floor at all.

That is a deliberate hole in ADDENDUM 278 and the test below says so. 278 exists because an area with no
floor is entered carrying somewhere else's byte; that can now happen at Kaminko's, on purpose, because the
manor's mid-game has no content at stake and where it does (0x53) a rule covers it.
"""
from __future__ import annotations

import struct
import unittest
from pathlib import Path

from BaseClasses import CollectionState

from . import PokemonXDTestBase
from .. import items as _items, ram_client, regions, travel_locations as tl
from ..game_data import story_bytes


# ================================================================================================
# 1. The skip itself
# ================================================================================================
class TestTheSSLibraSkip(unittest.TestCase):
    def _bump(self) -> "story_bytes.LiveStoryByteBump":
        found = [b for b in story_bytes.LIVE_STORY_BYTE_BUMPS if b.region == "SS Libra"]
        self.assertEqual(len(found), 1, "exactly one SS Libra bump, or the lookup order starts to matter")
        return found[0]

    def test_it_goes_from_the_first_fight_to_the_snag_machine_byte(self) -> None:
        bump = self._bump()
        self.assertEqual((bump.when_byte_is, bump.becomes), (0x5B, 0x5D))

    def test_those_two_bytes_are_the_ones_the_ladder_names(self) -> None:
        """Not typed twice. 0x5B is what "first fight on the SS Libra" lands on and 0x5D is what "Snag Machine
        stolen" lands on -- and it is 0x5D, not 0x5C, that opens the Key Lair exterior. If a future correction
        to the player's own compilation moves either, this fails rather than the bump quietly aiming at a byte
        that no longer means what the comment says."""
        lands_on = {t.after: t.what for t in story_bytes.TRANSITIONS}
        self.assertIn("first fight on the SS Libra", lands_on[0x5B])
        self.assertIn("Snag Machine stolen", lands_on[0x5D])
        opens = {region for t in story_bytes.TRANSITIONS if t.after == 0x5D for region in t.opens_regions}
        self.assertIn("Cipher Key Lair (exterior)", opens)

    def test_the_window_is_a_real_range_and_it_can_only_go_up(self) -> None:
        """0x5C fires too, and that is the RANGE doing the job ADDENDUM 213 built it for -- not a leak.

        The in-game poll runs about once a second, so an exact `== 0x5B` test can miss the value outright if
        the game advances between ticks. 0x5C is a `passthrough` of the same transition: the ladder records
        it as a value stepped through with no content, so a player sitting on it is already mid-skip and
        finishing the skip is the whole point. This is the property ADDENDUM 288 knowingly gave up when it
        shrank the lab's window to one value; the ship keeps it."""
        bump = self._bump()
        self.assertTrue(bump.applies("SS Libra", 0x5B))
        self.assertTrue(bump.applies("SS Libra", 0x5C), "catch-up after a missed tick")
        passthrough = {v for t in story_bytes.TRANSITIONS if t.before == 0x5B for v in t.passthrough}
        self.assertIn(0x5C, passthrough, "0x5C is only safe to bump from because it holds nothing")
        self.assertFalse(bump.applies("SS Libra", 0x5A), "below the trigger")
        self.assertFalse(bump.applies("SS Libra", 0x5D), "already there -- the half-open window retires it")
        self.assertFalse(bump.applies("SS Libra", 0x60), "long past it")
        self.assertFalse(bump.applies("SS Libra (stranded)", 0x5B), "the stranded tier is not the ship")
        self.assertFalse(bump.applies("Gateon Port", 0x5B))

    def test_the_gate_is_exactly_the_players_sentence(self) -> None:
        """"no matter what on location shuffle, but only with scooter shuffle in vanilla" -- all four
        combinations, because a gate is the kind of thing that is easy to get right in three of them."""
        for scooter in (False, True):
            self.assertIsNotNone(story_bytes.live_bump_for("SS Libra", 0x5B, True, scooter),
                                 "location shuffle: fires whatever the Scooter option says")
        self.assertIsNotNone(story_bytes.live_bump_for("SS Libra", 0x5B, False, True),
                             "vanilla travel WITH the Scooter shuffled: fires")
        self.assertIsNone(story_bytes.live_bump_for("SS Libra", 0x5B, False, False),
                          "vanilla travel without it: the story walks this rung itself, so there is nothing "
                          "here to fix and we must not touch the byte")

    def test_a_return_visit_enters_at_the_skipped_value(self) -> None:
        """The paired floor rule -- the other half, same as the lab's 0x0D pair (ADDENDA 212/213)."""
        self.assertEqual(story_bytes.dynamic_region_floor("SS Libra", {"SS Libra": 0x5B}), 0x5D)
        self.assertEqual(story_bytes.dynamic_region_floor("SS Libra", {"SS Libra": 0x5D}), 0x5D,
                         "idempotent: once the mark is there the rule still holds and still says 0x5D")
        self.assertIsNone(story_bytes.dynamic_region_floor("SS Libra", {"SS Libra": 0x5A}),
                          "below the trigger the rule must not bind")


class TestTheSkipWritesInBothModes(unittest.TestCase):
    def setUp(self) -> None:
        self.written: "list[tuple[int, bytes]]" = []
        self._original = ram_client.write_bytes
        ram_client.write_bytes = lambda address, data: self.written.append((address, data))

    def tearDown(self) -> None:
        ram_client.write_bytes = self._original

    def test_it_writes_0x5d_on_the_ship(self) -> None:
        bumper = ram_client.LiveStoryByteBumper()
        result = bumper.poll(0x80479000, "SS Libra", 0x5B, True, False)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 0x5D)
        # ADDENDUM 350: all twelve bits of GS variable 964. 0x5D stands for 750.
        self.assertEqual(self.written[0][1], struct.pack(">H", 750 << 5))
        self.assertEqual(self.written[0][1][0], 0x5D)
        self.assertEqual(self.written[0][0],
                         0x80479000 + ram_client.STORY_RECORD_OFFSET + ram_client.STORY_BYTE_OFFSET)

    def test_a_vanilla_seed_without_the_scooter_option_writes_nothing(self) -> None:
        bumper = ram_client.LiveStoryByteBumper()
        self.assertIsNone(bumper.poll(0x80479000, "SS Libra", 0x5B, False, False))
        self.assertEqual(self.written, [])

    def test_it_claims_the_write_so_nothing_credits_the_player_for_it(self) -> None:
        """ADDENDUM 293 gave the bumper `last_written_value` so it reports through the ONE ownership channel
        (`Client._claim_story_write`). Without it, the second call site -- vanilla travel, where there is no
        area-memory poll for the caller to piggyback on -- would raise the byte with nothing recording that
        WE raised it, and `StoryProgressWitness` would credit the player for a rung we put them on."""
        bumper = ram_client.LiveStoryByteBumper()
        self.assertIsNone(bumper.last_written_value)
        bumper.poll(0x80479000, "SS Libra", 0x5B, True, False)
        self.assertEqual(bumper.last_written_value, 0x5D)


class TestTheClientRunsItInVanillaTravel(unittest.TestCase):
    """Source-checked, like every other Client.py wiring test in this suite."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (Path(ram_client.__file__).resolve().parent / "Client.py").read_text(encoding="utf-8")

    def test_the_vanilla_branch_calls_the_bumper(self) -> None:
        """The bug this closes is one of PLACEMENT, not of logic: the single call to the bumper sat below
        `check_area_story_memory`'s `if not ctx.randomize_travel_locations: return`, so no bump had ever
        fired in a vanilla-travel seed and nothing said that was a decision."""
        self.assertIn("def _bump_in_vanilla_travel(", self.source)
        start = self.source.index("def _bump_in_vanilla_travel(")
        end = self.source.index("async def check_area_story_memory(")
        body = self.source[start:end]
        self.assertIn("ctx.live_story_bumper.poll(", body)
        self.assertIn("travel_shuffle=False", body)
        self.assertIn("_claim_story_write(ctx, ctx.live_story_bumper)", body)

    def test_it_is_called_from_the_early_return_branch(self) -> None:
        start = self.source.index("async def check_area_story_memory(")
        end = self.source.index("async def check_story_byte_override(")
        body = self.source[start:end]
        called_at = body.index("_bump_in_vanilla_travel(ctx)")
        returned_at = body.index("    if not ctx.randomize_travel_locations:")
        self.assertGreater(called_at, returned_at)
        self.assertLess(called_at, body.index("ctx.live_story_bumper.poll("),
                        "the vanilla call must sit in the branch that returns, not after it")

    def test_the_hold_runs_first(self) -> None:
        """`_hold_ss_libra_without_the_scooter` can write the byte itself, and the bump has to decide from the
        value actually in the save. Reading it after the hold has had its turn is the only ordering under
        which "the ship reached 0x5B" means the ship really did."""
        start = self.source.index("async def check_area_story_memory(")
        end = self.source.index("async def check_story_byte_override(")
        body = self.source[start:end]
        self.assertLess(body.index("_hold_ss_libra_without_the_scooter(ctx)"),
                        body.index("_bump_in_vanilla_travel(ctx)"))


# ================================================================================================
# 2. Snagem's base floor -- the value the loosened graph rests on
# ================================================================================================
class TestSnagemsBaseFloor(unittest.TestCase):
    def test_it_is_0x62_from_the_ladder_itself(self) -> None:
        """RETARGETED TWICE. ADDENDUM 324 moved this to 0x63 on the player's report; ADDENDUM 350 moved it
        back, because 0x63 is a byte the game can never hold -- its window 792..799 contains no multiple of
        ten, and the story variable only ever holds multiples of ten. The property this class is really
        about is unchanged either way: the constant, the window and the entry floor must all be the same
        number, because the rerouted Key Lair chain rests on a hovered player being written in at it."""
        self.assertEqual(story_bytes.SNAGEM_BASE_FLOOR, 0x62)
        self.assertEqual(story_bytes.REGION_STORY_WINDOW["Snagem Hideout"].floor, 0x62)
        self.assertEqual(story_bytes.area_entry_floor("Snagem Hideout"), 0x62)
        self.assertEqual(story_bytes.story_value_for_byte(0x62), 790,
                         "790 is what Snagem 2F's hero_main tests for, as an equality")
        self.assertIsNone(story_bytes.story_value_for_byte(0x63),
                          "0x63 is unreachable -- that is why it must never be a floor again")

    def test_that_byte_is_the_one_the_player_recorded(self) -> None:
        opens = [t for t in story_bytes.TRANSITIONS if "Snagem Hideout" in t.opens_regions]
        self.assertEqual(len(opens), 1)
        self.assertEqual(opens[0].after, story_bytes.SNAGEM_BASE_FLOOR)
        self.assertIn("Snagem Hideout reachable", opens[0].what)


# ================================================================================================
# 3. The logic chains
# ================================================================================================
class TestNothingTheplayerNamedIsBehindTheShip(PokemonXDTestBase):
    options = {
        "randomize_travel_locations": True,
        "key_item_shuffle": True,
        "randomize_chests": True,
        "randomize_shops": True,
        "shuffle_scooter_upgrade": True,
    }

    def _everything_but_the_scooter(self) -> CollectionState:
        state = CollectionState(self.multiworld)
        for item in self.multiworld.itempool:
            if item.advancement and item.name != _items.SCOOTER_ITEM_NAME:
                state.collect(item, True)
        state.sweep_for_advancements()
        return state

    def test_the_scooter_gates_the_ship_and_only_the_ship(self) -> None:
        """The measurement in this file's docstring, as an assertion. Before: six regions behind one item.
        After: one, and it is the one the item is for."""
        state = self._everything_but_the_scooter()
        blocked = [region for region in (
            "SS Libra", "Cipher Key Lair (exterior)", "Outskirt Stand", "Snagem Hideout",
            "Cipher Key Lair", "Cipher Key Lair (deep)", "Citadark Isle",
        ) if not state.can_reach(region, player=self.player)]
        self.assertEqual(["SS Libra"], blocked)

    def test_the_ship_is_still_really_gated(self) -> None:
        """The loosening must not have leaked into the thing it was loosening around. ADDENDUM 273's gate is
        the point of the Scooter existing, and a decoupling that also ungated the ship would be a different
        change wearing this one's name."""
        state = self._everything_but_the_scooter()
        self.assertFalse(state.can_reach("SS Libra", player=self.player))

    def test_the_exterior_is_sourced_at_the_ships_predecessor(self) -> None:
        self.assertEqual(regions.TRAVEL_SHUFFLE_REROUTED_EDGES["Cipher Key Lair (exterior)"],
                         "Kaminko's House (Robo Groudon)")
        self.assertIn(("SS Libra", "Cipher Key Lair (exterior)", ()), regions.REGION_EDGES,
                      "REGION_EDGES describes the GAME's route and keeps saying so -- the reroute is applied "
                      "when the graph is built, and only with travel shuffle on")

    def test_snagem_has_no_hard_prerequisite_left(self) -> None:
        """UPDATED BY ADDENDUM 332. The second line used to assert that the Key Lair was still behind Snagem
        -- this addendum's own reasoning was that the Lair stopped being behind the SHIP as a consequence of
        Snagem doing so, rather than by a second edit. The player has since made that second edit
        ("Decouple Key Lair from snagem"), so what survives here is this addendum's own claim: Snagem itself
        is behind nothing."""
        self.assertNotIn("Snagem Hideout", tl.TRAVEL_LOCATION_REQUIRED_REGIONS)
        self.assertNotIn("Cipher Key Lair", tl.TRAVEL_LOCATION_REQUIRED_REGIONS)


class TestVanillaTravelIsUntouched(PokemonXDTestBase):
    """The safety half. With travel randomization off the ladder is the only route, and it cannot pass 0x5A
    without the scooter upgrade -- `ScooterStoryHold` holds it there deliberately. So Snagem really IS behind
    the Scooter here, and the graph has to keep saying so or the fill can place the Scooter in Snagem."""

    options = {
        "randomize_travel_locations": False,
        "key_item_shuffle": True,
        "shuffle_scooter_upgrade": True,
    }

    def test_snagem_and_the_key_lair_stay_behind_the_scooter(self) -> None:
        state = CollectionState(self.multiworld)
        for item in self.multiworld.itempool:
            if item.advancement and item.name != _items.SCOOTER_ITEM_NAME:
                state.collect(item, True)
        state.sweep_for_advancements()
        for region in ("SS Libra", "Cipher Key Lair (exterior)", "Snagem Hideout", "Citadark Isle"):
            self.assertFalse(state.can_reach(region, player=self.player),
                             f"{region} must stay behind the Scooter with travel randomization off")


# ================================================================================================
# 4. Kaminko's paused floor
# ================================================================================================
class TestKaminkosFloorPause(unittest.TestCase):
    def test_the_table_says_0x03_which_is_the_manors_own_first_visit(self) -> None:
        self.assertEqual(story_bytes.FLOOR_WRITES_PAUSE_ABOVE["Kaminko's House"], 0x03)
        self.assertEqual(story_bytes.ALWAYS_OPEN_FIRST_VISIT["Kaminko's House"], 0x03,
                         "the pause byte IS the first-visit byte -- if they ever differ, say why")

    def test_before_the_first_visit_nothing_is_paused(self) -> None:
        self.assertFalse(story_bytes.floor_writes_are_paused("Kaminko's House", {}))
        self.assertFalse(story_bytes.floor_writes_are_paused("Kaminko's House", {"Kaminko's House": 0x02}))

    def test_after_it_the_floor_is_withheld(self) -> None:
        for mark in (0x03, 0x10, 0x19, 0x40, 0x52):
            self.assertTrue(
                story_bytes.floor_writes_are_paused("Kaminko's House", {"Kaminko's House": mark}),
                f"0x{mark:02X} is a byte the player was carrying, not a floor the manor asked for",
            )

    def test_a_satisfied_rule_resumes_it(self) -> None:
        """"then we can start writing its floor again" -- and it resumes on the RULE, not on a second byte
        typed in here, so the two tables cannot drift."""
        marks = {"Kaminko's House": 0x10, "Gateon Port": 0x52, "Pokemon HQ Lab": 0x0F}
        self.assertFalse(story_bytes.floor_writes_are_paused("Kaminko's House", marks))
        self.assertEqual(story_bytes.dynamic_region_floor("Kaminko's House", marks), 0x53)   # ADDENDUM 350: back to 0x53. 0x54 is a byte the game can never hold (672..679 contains no multiple of ten); what it bought was a write that always cleared 670 while the byte-only write made 0x53 land anywhere in 664..671. The twelve-bit write puts 0x53 exactly on 670.

    def test_the_robo_groudon_tier_counts_as_the_manor(self) -> None:
        """Keyed on the AREA GROUP, so "Kaminko reaches 0x03" means what the player means by it."""
        self.assertIn("Kaminko's House (Robo Groudon)", story_bytes.AREA_GROUPS["Kaminko's House"])
        self.assertTrue(story_bytes.floor_writes_are_paused(
            "Kaminko's House (Robo Groudon)", {"Kaminko's House": 0x30}))

    def test_no_other_area_is_paused(self) -> None:
        self.assertEqual(set(story_bytes.FLOOR_WRITES_PAUSE_ABOVE), {"Kaminko's House"})
        for region in ("Pokemon HQ Lab", "Gateon Port", "Agate Village", "Pyrite Town"):
            self.assertFalse(story_bytes.floor_writes_are_paused(region, {region: 0x50}))


class TestTheMemoryHonoursThePause(unittest.TestCase):
    def test_it_declines_rather_than_writing_the_mark(self) -> None:
        memory = ram_client.AreaStoryByteMemory()
        memory.highest_by_region["Kaminko's House"] = 0x19
        self.assertIsNone(memory.target_for("Kaminko's House"),
                          "0x19 is Agate's floor carried in on the player's feet, not the manor's")
        self.assertEqual(memory.declined_floor_paused, 1)

    def test_the_first_visit_still_gets_its_floor(self) -> None:
        memory = ram_client.AreaStoryByteMemory()
        self.assertEqual(memory.target_for("Kaminko's House"), 0x03)
        self.assertEqual(memory.declined_floor_paused, 0)

    def test_the_rule_tier_writes_again(self) -> None:
        memory = ram_client.AreaStoryByteMemory()
        memory.highest_by_region.update({"Kaminko's House": 0x19, "Gateon Port": 0x52,
                                         "Pokemon HQ Lab": 0x0F})
        self.assertEqual(memory.target_for("Kaminko's House"), 0x53)   # ADDENDUM 350: back to 0x53. 0x54 is a byte the game can never hold (672..679 contains no multiple of ten); what it bought was a write that always cleared 670 while the byte-only write made 0x53 land anywhere in 664..671. The twelve-bit write puts 0x53 exactly on 670.
        self.assertEqual(memory.declined_floor_paused, 0)

    def test_a_late_mark_outranks_the_rule_once_writing_resumes(self) -> None:
        """Resuming means resuming ENTIRELY, mark included -- not "resume, but only ever write 0x53"."""
        memory = ram_client.AreaStoryByteMemory()
        memory.highest_by_region.update({"Kaminko's House": 0x56, "Gateon Port": 0x52,
                                         "Pokemon HQ Lab": 0x0F})
        self.assertEqual(memory.target_for("Kaminko's House"), 0x56)

    def test_a_paused_hover_writes_nothing_at_all(self) -> None:
        written: "list[tuple[int, bytes]]" = []
        original = ram_client.write_bytes
        ram_client.write_bytes = lambda address, data: written.append((address, data))
        try:
            memory = ram_client.AreaStoryByteMemory()
            memory.highest_by_region["Kaminko's House"] = 0x40
            self.assertIsNone(memory.poll(0x80479000, "Kaminko's House", None, 0x40))
            self.assertEqual(written, [])
            self.assertEqual(memory.writes, 0)
        finally:
            ram_client.write_bytes = original

    def test_areas_says_it_is_deliberate(self) -> None:
        """A feature that looks exactly like a bug from the outside has to name itself in the readout."""
        memory = ram_client.AreaStoryByteMemory()
        memory.highest_by_region["Kaminko's House"] = 0x40
        memory.target_for("Kaminko's House")
        text = "\n".join(memory.describe())
        self.assertIn("floor writes paused", text)
        self.assertIn("Kaminko's House", text)

    def test_a_byte_carried_in_never_becomes_the_manors_mark(self) -> None:
        """The obvious worry about writing nothing, and the reason it is not one.

        With no floor written, the player walks into the manor carrying whatever byte they had. ADDENDUM
        279's inheritance guard already refuses to bank that -- a byte that has not moved since the last
        observation in a DIFFERENT area was carried in, not earned here -- so the pause cannot poison the
        mark, and the rules that read that mark (the HQ Lab's 0x07, Gateon's 0x57) are untouched."""
        memory = ram_client.AreaStoryByteMemory()
        memory.observe("Agate Village", 0x19)          # played Agate up to its tier
        memory.observe("Kaminko's House", 0x19)        # travelled, arrived still carrying it
        self.assertNotIn("Kaminko's House", memory.highest_by_region)
        self.assertEqual(memory.declined_inherited_byte, 1)
        memory.observe("Kaminko's House", 0x1A)        # the game moved it while they stood there
        self.assertEqual(memory.highest_by_region["Kaminko's House"], 0x1A)

    def test_the_gap_the_mark_based_arming_leaves_is_the_documented_one(self) -> None:
        """Disclosed rather than discovered later. "Reaches 0x03" is read as the MARK reaching it, and a mark
        only appears when the game moved the byte while the player was inside. So a player who walks in and
        leaves without the story advancing has no mark, the pause does not arm, and 0x03 is written as
        before. Recorded as a decision, not left to be found as a surprise -- see the table's own comment for
        why the alternative (arming on our own write) is worse."""
        memory = ram_client.AreaStoryByteMemory()
        self.assertFalse(story_bytes.floor_writes_are_paused("Kaminko's House", {}))
        self.assertEqual(memory.target_for("Kaminko's House"), 0x03)

    def test_the_pause_does_not_stop_the_memory_recording(self) -> None:
        """Only the WRITE is paused. Marks still have to rise, or the 0x53 rule could never be satisfied and
        the pause would never lift -- a hold that prevents its own release."""
        memory = ram_client.AreaStoryByteMemory()
        memory.observe("Kaminko's House", 0x03)
        memory.observe("Kaminko's House", 0x30)
        self.assertEqual(memory.highest_by_region["Kaminko's House"], 0x30)


if __name__ == "__main__":
    unittest.main()
