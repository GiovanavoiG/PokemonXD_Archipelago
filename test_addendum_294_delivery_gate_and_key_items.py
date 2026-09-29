"""
ADDENDUM 294 (2026-09-20) -- the gate that never opened, and the pocket we never looked in.

Player, in one message: *"Can we double check our system that scans key items? User reported machine part not
being removed. Also, double check our item delivery - user reported later in the run that some items were
taking the full 10 minute timeout - this is fine, but it seemed more consistent than we wanted. Also, new bump
- with location shuffle, make it so that if Phenac reaches 0x3F, it gets bumped to 0x41."*

Three reports. The first two turned out to be the same kind of mistake in two different subsystems: a
question asked of one place when the answer could be in another.

## 1. The ten-minute ceiling, and the counter that could not count

`ITEM_DELIVERY_MAX_BATTLE_WAIT_SECONDS` is not a give-up-and-accept timeout. It is a ceiling on the
BEFORE-THE-FIRST-WRITE battle hold, so "this item took the full ten minutes" means exactly one thing:
`BattleStateTracker.poll` answered False on every poll for six hundred unbroken seconds. With
`shuffle_trainer_defeats` on, that signal is `TrainerBattleDefeatTracker.has_unresolved_battle()`, which
overrides both the battle-UI flag and the three-poll debounce.

ADDENDUM 100 built the escape hatch for exactly this: a roster key stops blocking once it has gone
`STALE_NO_PROGRESS_POLLS` polls with no observed HP movement. **But the counter was only ever incremented
inside the per-surname loop, and that loop walks `slot_keys` -- this poll's DOMINANT CLUSTER for that
surname.** A key we are no longer looking at could not accumulate idle polls.

And a key stops being looked at without its surname disappearing. `dominant_roster_cluster` keeps a surname's
largest contiguous run of records and drops the rest; MEM1 accumulates stale rosters for the whole boot (this
project's own notes record twelve LOVRINA records in three places in one real dump). XD reuses surnames, so
an old battle's cluster and a new one's compete under the same key, and as a fresh roster is written record
by record the winner flips. The species from the losing cluster is then baselined, unfired, its surname still
present so the vanish-purge cannot touch it, and its idle counter **frozen below the threshold forever**.

`ram_client.py` predicted the symptom in ADDENDUM 80's own words, years of addenda ago:

> "Before ADDENDUM 80 added ITEM_DELIVERY_MAX_BATTLE_WAIT_SECONDS as a hard ceiling, this shape looked like
> 'items never arrive'; with that ceiling now in place, it instead looks like 'items always take the full
> ceiling to arrive'."

That is the report, word for word, and it grows more consistent through a run because the stale records the
cluster has to choose between accumulate.

**The fix counts the poll rather than forgetting the key.** A key absent from this poll's clusters is, if
anything, more obviously stale than one present and unchanged. Purging it instead would lose the min-HP
baseline a real kill is measured against -- a missed check, the direction this project never trades toward --
and counting is reversible: if the key comes back and its HP moves, the existing branches reset it to zero
and it blocks again, correctly.

## 2. The Machine Part, and the rule this project has now learned three times

A write window must be narrow, because a wrong write corrupts a save. A READ window must be as wide as the
item could plausibly be, because the game's own item-add code is not this client. ADDENDUM 222 learned it for
a delivery baseline; ADDENDUM 231 learned it again for the chest berry scan. `KeyItemReconciler` was still
reading through `resolve_item_pocket` -- the WRITE window.

ADDENDUM 216 widened key-item routing to the Key Items pocket and proves less than it sounds like: it
establishes that every id in 501-533 has a key-item NAME, not which pocket the game physically files each one
in. This module's own header says that pocket "has NOT been write-tested", and the only gating key item ever
observed there live is the ID Card. If XD files the Machine Part in the Items pocket, the reconciler reads
zero forever, concludes the player does not have it, and clears nothing -- while every other managed id
behaves, because they really are where we look. That is the reported symptom exactly.

Rather than guess the pocket a second time, look in both. Item ids are one global namespace, so id 503 in the
Items pocket IS the Machine Part; there is nothing else it could be, and the search makes no new writes at
all. Writes are unchanged and still go to the routed pocket alone.

Two things came out of the same report and are fixed with it: `clear_item` reported success for a write it
had merely ISSUED, so a clear count could climb once a second beside an item that never left the Bag; and
`!keyitems` counted what we did without ever saying WHERE the item was, which is the one fact that separates
"kept on purpose" from "looked in the wrong place" from "the write is not landing".

## 3. Phenac's lockdown

`0x3E -> 0x3F` is Phenac's first visit, which forces the player out to Realgam; `0x3F -> 0x41` is Realgam's
visit, which unlocks the town. At 0x3F the whole town is inert. In a vanilla run that is a two-minute errand.
With travel locations shuffled, Realgam is its own destination behind its own unlock item, so a player can
sit at 0x3F with a town full of visible, dead checks for as long as the multiworld takes. Location shuffle
only, which is the player's own scope and the honest one.
"""
from __future__ import annotations

import struct
import unittest
from pathlib import Path

from .. import ram_client as rc
from ..game_data import story_bytes

BLOCK_BASE = 0x80479000
CLIENT_SOURCE = (Path(rc.__file__).resolve().parent / "Client.py").read_text(encoding="utf-8")


def _record(address: int, surname: str, species: str, hp: int) -> "rc.BattleRosterRecord":
    return rc.BattleRosterRecord(address, surname, species, hp)


# ================================================================================================
# 1. The battle gate
# ================================================================================================
class TestTheGateCanNowLetGo(unittest.TestCase):
    """The permanent stick, reproduced and then fixed, against the real tracker."""

    def _tracker(self) -> "rc.TrainerBattleDefeatTracker":
        return rc.TrainerBattleDefeatTracker()

    def _poll(self, tracker, records) -> None:
        tracker.poll(records=records, surname_to_location_queue={}, count_location_name=lambda n: f"D{n}")

    def test_a_key_that_drops_out_of_the_cluster_still_ages_out(self) -> None:
        """THE BUG. Baseline a key while its cluster dominates, then let a LARGER cluster for the same
        surname win. Before this addendum the first key's idle counter froze and `has_unresolved_battle()`
        answered True for the rest of the client session -- every later delivery then waited the full ten
        minutes before it was even written."""
        tracker = self._tracker()
        # Poll 1: one cluster, one species, alive. This baselines ("DOSK", "SENTRET") and blocks.
        self._poll(tracker, [_record(0x1000, "DOSK", "SENTRET", 40)])
        self.assertTrue(tracker.has_unresolved_battle())

        # Poll 2 onward: a SECOND, larger cluster for the same surname wins `dominant_roster_cluster`, so
        # SENTRET is no longer among the records this poll looks at -- while DOSK is still present, so the
        # vanish-purge never fires and the key stays in `_baselined`.
        newer = [_record(0x90000 + i * 0x100, "DOSK", name, 50)
                 for i, name in enumerate(("ZIGZAGOON", "TAILLOW", "WHISMUR"))]
        for _ in range(rc.TrainerBattleDefeatTracker.STALE_NO_PROGRESS_POLLS + 2):
            self._poll(tracker, newer)

        self.assertIn(("DOSK", "SENTRET"), tracker._baselined,
                      "the key is still tracked -- this addendum counts the poll, it does not forget the key")
        self.assertGreaterEqual(tracker._polls_without_progress[("DOSK", "SENTRET")],
                                rc.TrainerBattleDefeatTracker.STALE_NO_PROGRESS_POLLS,
                                "an unseen key must accumulate idle polls, or it blocks deliveries forever")

    def test_a_real_fight_still_blocks(self) -> None:
        """The fix must not open the gate during an actual battle. A key whose HP keeps moving resets its
        counter every time, so it never ages out however long the fight runs."""
        tracker = self._tracker()
        hp = 60
        for _ in range(rc.TrainerBattleDefeatTracker.STALE_NO_PROGRESS_POLLS * 3):
            self._poll(tracker, [_record(0x1000, "DOSK", "SENTRET", hp)])
            hp -= 1
            self.assertTrue(tracker.has_unresolved_battle())

    def test_an_unseen_key_that_comes_back_and_moves_blocks_again(self) -> None:
        """Counting is reversible by construction, which is why it is safe where purging would not be."""
        tracker = self._tracker()
        self._poll(tracker, [_record(0x1000, "DOSK", "SENTRET", 40)])
        others = [_record(0x90000 + i * 0x100, "DOSK", name, 50)
                  for i, name in enumerate(("ZIGZAGOON", "TAILLOW", "WHISMUR"))]
        for _ in range(rc.TrainerBattleDefeatTracker.STALE_NO_PROGRESS_POLLS + 2):
            self._poll(tracker, others)
        self.assertFalse(tracker.has_unresolved_battle())
        # SENTRET is back, and its HP has dropped -- a live fight again.
        self._poll(tracker, [_record(0x1000, "DOSK", "SENTRET", 30)])
        self.assertEqual(tracker._polls_without_progress[("DOSK", "SENTRET")], 0)
        self.assertTrue(tracker.has_unresolved_battle())

    def test_the_readout_says_which_record_is_holding_it(self) -> None:
        """`!battle` could report "free -- items can deliver" while THIS signal held every delivery, because
        the command printed the UI flag and the debounce and never the input that overrides both."""
        tracker = self._tracker()
        self._poll(tracker, [_record(0x1000, "DOSK", "SENTRET", 40)])
        text = "\n".join(tracker.describe_blocking())
        self.assertIn("YES", text)
        self.assertIn("DOSK", text)
        self.assertIn("SENTRET", text)
        self.assertIn("idle 0/", text)

    def test_the_battle_command_prints_it(self) -> None:
        start = CLIENT_SOURCE.index("def _cmd_battle(")
        end = CLIENT_SOURCE.index("def _cmd_room(")
        self.assertIn("describe_blocking()", CLIENT_SOURCE[start:end])


# ================================================================================================
# 2. Delivery visibility
# ================================================================================================
class TestTheDeliveryPathSaysWhatItIsDoing(unittest.TestCase):
    """Source-checked: `Client.py` cannot be imported in this sandbox (see test_addendum_181's note)."""

    def test_the_ceiling_is_logged_unconditionally(self) -> None:
        """The ceiling firing is itself a bug report, and it was completely silent -- not `_note`-gated,
        absent. A ten-minute wait, a permanently stuck item and normal operation all looked identical."""
        self.assertIn("waited the full ", CLIENT_SOURCE)
        start = CLIENT_SOURCE.index("waited the full ")
        window = CLIENT_SOURCE[start - 400:start]
        self.assertIn("logger.warning(", window)
        self.assertNotIn("_note_warn(", window.split("if not safe_to_start_new_items:")[-1])

    def test_a_full_write_window_is_reported_and_the_item_is_not_dropped(self) -> None:
        """`give_item` returns False when every slot in the write window is taken -- it touched no memory.
        Both call sites discarded that, so a full pocket produced a baseline, no write, a peak that could
        never rise, and an infinite silent retry. The Items pocket is thirty slots and a bag only fills."""
        self.assertIn("def _warn_write_window_full(", CLIENT_SOURCE)
        self.assertIn("if not ram_client.give_item(pocket_base, game_item_id, quantity, max_slots):",
                      CLIENT_SOURCE)
        self.assertIn("elif not ram_client.give_item(pocket_base, game_item_id, quantity, max_slots):",
                      CLIENT_SOURCE)
        helper = CLIENT_SOURCE[CLIENT_SOURCE.index("def _warn_write_window_full("):]
        helper = helper[:helper.index("\ndef ", 1)]
        self.assertIn("logger.warning(", helper)
        self.assertNotIn("delivered = True", helper,
                         "ADDENDUM 44: an item is never dropped -- it lands when a slot frees up")

    def test_no_give_item_call_in_the_delivery_path_ignores_its_answer(self) -> None:
        """The property, not the two lines. A third call site added later must not re-open this."""
        start = CLIENT_SOURCE.index("async def give_items(")
        rest = CLIENT_SOURCE[start:]
        # The next TOP-LEVEL definition, at column zero. Searching for the next `async def ` at any
        # indentation walked straight past the end of this function and into `!getitem`, which has its own
        # contract ("write it and trust it") and its own reporting -- so the test failed on a line it was
        # never about. Caught by the test itself on the first run, which is the argument for writing it as a
        # property rather than as two `assertIn`s.
        offsets = [rest.index(marker, 1) for marker in ("\ndef ", "\nasync def ") if marker in rest[1:]]
        body = rest[:min(offsets)] if offsets else rest
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("ram_client.give_item("):
                self.fail(f"this give_item call discards its return value: {stripped}")


# ================================================================================================
# 3. The key-item reconciler, against a real packed pocket
# ================================================================================================
class _Bag:
    """Two real, packed, byte-level pockets -- the Items pocket and the Key Items pocket.

    The reconciler had NO byte-level test before this addendum: its only test replaced
    `find_item_quantity`/`give_item`/`clear_item` wholesale with a dict, so `read_pocket`, `write_slot`, the
    offsets, the slot counts and the `>HH` layout were never exercised by it at all. That is why a
    wrong-pocket bug could live in it."""

    def __init__(self, items: "dict[int, int]" = None, key_items: "dict[int, int]" = None) -> None:
        self.pockets = {
            BLOCK_BASE + rc.ITEMS_POCKET_OFFSET: self._pack(items or {}, rc.ITEMS_POCKET_MAX_SLOTS),
            BLOCK_BASE + rc.KEY_ITEMS_OFFSET: self._pack(key_items or {}, rc.KEY_ITEMS_MAX_SLOTS),
        }

    @staticmethod
    def _pack(contents: "dict[int, int]", slots: int) -> "list[list[int]]":
        packed = [[item_id, qty] for item_id, qty in contents.items()]
        while len(packed) < slots:
            packed.append([0, 0])
        return packed

    def _locate(self, address: int) -> "tuple[int, int]":
        for base, slots in self.pockets.items():
            if base <= address < base + len(slots) * 4:
                return base, (address - base) // 4
        raise AssertionError(f"read/write outside any modelled pocket: 0x{address:08X}")

    def read(self, address: int, length: int) -> bytes:
        base, index = self._locate(address)
        slots = self.pockets[base]
        raw = b"".join(struct.pack(">HH", i, q) for i, q in slots)
        start = address - base
        assert start + length <= len(raw), "read ran past the end of the pocket"
        return raw[start:start + length]

    def write(self, address: int, payload: bytes) -> None:
        base, index = self._locate(address)
        self.pockets[base][index] = list(struct.unpack(">HH", payload))

    def ids_in(self, offset: int) -> "set[int]":
        return {i for i, q in self.pockets[BLOCK_BASE + offset] if i}


class _Patched:
    def __init__(self, bag: "_Bag") -> None:
        self.bag = bag

    def __enter__(self) -> "_Bag":
        self._read, self._write = rc.read_bytes, rc.write_bytes
        rc.read_bytes, rc.write_bytes = self.bag.read, self.bag.write
        return self.bag

    def __exit__(self, *exc) -> None:
        rc.read_bytes, rc.write_bytes = self._read, self._write


MACHINE_PART = 503
MANAGED = frozenset({MACHINE_PART})


class TestTheReconcilerFindsItWhereverItIs(unittest.TestCase):
    def test_it_clears_the_machine_part_from_the_key_items_pocket(self) -> None:
        """The case that always worked, pinned at byte level for the first time."""
        bag = _Bag(key_items={MACHINE_PART: 1})
        with _Patched(bag):
            reconciler = rc.KeyItemReconciler()
            written, cleared = reconciler.poll(BLOCK_BASE, frozenset(), MANAGED)
        self.assertEqual(cleared, (MACHINE_PART,))
        self.assertEqual(bag.ids_in(rc.KEY_ITEMS_OFFSET), set())

    def test_it_clears_the_machine_part_from_the_ITEMS_pocket(self) -> None:
        """THE REPORT. If XD files this one in the Items pocket, the old reconciler read the Key Items pocket,
        found nothing, concluded the player did not have it, and cleared nothing -- forever, and only for the
        ids the game files somewhere other than where ADDENDUM 216 assumed."""
        bag = _Bag(items={MACHINE_PART: 1})
        with _Patched(bag):
            reconciler = rc.KeyItemReconciler()
            written, cleared = reconciler.poll(BLOCK_BASE, frozenset(), MANAGED)
        self.assertEqual(cleared, (MACHINE_PART,))
        self.assertEqual(bag.ids_in(rc.ITEMS_POCKET_OFFSET), set())

    def test_it_clears_both_copies_when_the_id_is_in_two_pockets(self) -> None:
        bag = _Bag(items={MACHINE_PART: 1}, key_items={MACHINE_PART: 1})
        with _Patched(bag):
            rc.KeyItemReconciler().poll(BLOCK_BASE, frozenset(), MANAGED)
        self.assertEqual(bag.ids_in(rc.ITEMS_POCKET_OFFSET), set())
        self.assertEqual(bag.ids_in(rc.KEY_ITEMS_OFFSET), set())

    def test_an_owned_item_is_kept_wherever_it_sits(self) -> None:
        """The other half, and the one that is NOT a bug: the Machine Part is forced into sphere zero, so a
        player very often owns it early -- and then keeping it is the correct behaviour, not a failure."""
        for pocket in ("items", "key_items"):
            bag = _Bag(**{pocket: {MACHINE_PART: 1}})
            with _Patched(bag):
                reconciler = rc.KeyItemReconciler()
                written, cleared = reconciler.poll(BLOCK_BASE, MANAGED, MANAGED)
            self.assertEqual(cleared, (), f"owned, in the {pocket} pocket -- must not be cleared")
            self.assertEqual(written, (), "already present, so nothing to write")

    def test_an_owned_item_that_is_missing_is_written_to_the_ROUTED_pocket(self) -> None:
        """Writes stay narrow. Searching widely is free because it makes no writes; writing widely is the
        corruption the narrow window exists to prevent."""
        bag = _Bag()
        with _Patched(bag):
            written, cleared = rc.KeyItemReconciler().poll(BLOCK_BASE, MANAGED, MANAGED)
        self.assertEqual(written, (MACHINE_PART,))
        self.assertEqual(bag.ids_in(rc.KEY_ITEMS_OFFSET), {MACHINE_PART})
        self.assertEqual(bag.ids_in(rc.ITEMS_POCKET_OFFSET), set())

    def test_the_readout_says_which_pocket_it_was_found_in(self) -> None:
        """The one fact that separates "kept on purpose" from "we looked in the wrong place"."""
        bag = _Bag(items={MACHINE_PART: 1})
        with _Patched(bag):
            reconciler = rc.KeyItemReconciler()
            reconciler.poll(BLOCK_BASE, MANAGED, MANAGED)
            text = "\n".join(reconciler.describe(MANAGED, MANAGED, block_base=BLOCK_BASE))
        self.assertIn("Machine Part", text)
        self.assertIn("in the Items pocket", text)
        self.assertIn("OWNED", text)

    def test_a_clear_that_does_not_stick_is_not_counted_as_a_clear(self) -> None:
        """`clear_item` reported success for a write it had merely ISSUED. A clear count climbing once a
        second beside an item still in the Bag reads as "the feature ran" when the truth is "the feature ran
        and achieved nothing" -- which is exactly the question the player was trying to answer."""
        bag = _Bag(key_items={MACHINE_PART: 1})
        with _Patched(bag):
            bag.write = lambda address, payload: None      # every write silently does nothing
            reconciler = rc.KeyItemReconciler()
            rc.write_bytes = bag.write
            written, cleared = reconciler.poll(BLOCK_BASE, frozenset(), MANAGED)
        self.assertEqual(cleared, ())
        self.assertEqual(reconciler.clears.get(MACHINE_PART, 0), 0)
        self.assertEqual(reconciler.clears_that_did_not_stick.get(MACHINE_PART), 1)

    def test_the_windows_are_the_two_pockets_and_the_routed_one_comes_first(self) -> None:
        windows = rc.key_item_search_windows(BLOCK_BASE, MACHINE_PART)
        self.assertEqual(windows[0], rc.resolve_item_pocket(BLOCK_BASE, MACHINE_PART))
        self.assertIn((BLOCK_BASE + rc.ITEMS_POCKET_OFFSET, rc.ITEMS_POCKET_MAX_SLOTS), windows)
        self.assertIn((BLOCK_BASE + rc.KEY_ITEMS_OFFSET, rc.KEY_ITEMS_MAX_SLOTS), windows)
        self.assertEqual(len(windows), len(set(windows)), "a duplicated window would clear twice")


class TestClearItemVerified(unittest.TestCase):
    def test_absent_is_not_a_failure(self) -> None:
        bag = _Bag()
        with _Patched(bag):
            self.assertIsNone(rc.clear_item_verified(
                BLOCK_BASE + rc.KEY_ITEMS_OFFSET, rc.KEY_ITEMS_MAX_SLOTS, MACHINE_PART))

    def test_present_and_removed_is_true(self) -> None:
        bag = _Bag(key_items={MACHINE_PART: 1})
        with _Patched(bag):
            self.assertIs(rc.clear_item_verified(
                BLOCK_BASE + rc.KEY_ITEMS_OFFSET, rc.KEY_ITEMS_MAX_SLOTS, MACHINE_PART), True)

    def test_present_and_still_there_is_false(self) -> None:
        bag = _Bag(key_items={MACHINE_PART: 1})
        with _Patched(bag):
            rc.write_bytes = lambda address, payload: None
            self.assertIs(rc.clear_item_verified(
                BLOCK_BASE + rc.KEY_ITEMS_OFFSET, rc.KEY_ITEMS_MAX_SLOTS, MACHINE_PART), False)


# ================================================================================================
# 4. Phenac's bump
# ================================================================================================
class TestThePhenacBump(unittest.TestCase):
    def _bump(self) -> "story_bytes.LiveStoryByteBump":
        found = [b for b in story_bytes.LIVE_STORY_BYTE_BUMPS if b.region == "Phenac City"]
        self.assertEqual(len(found), 1)
        return found[0]

    def test_it_goes_from_the_arrival_byte_to_the_unlocked_one(self) -> None:
        """RETARGETED BY ADDENDUM 331, from (0x3F, 0x41) to (0x3E, 0x41).

        Player: "The phenac bump - 0x3F > 0x41 - is not going off in play." It could not: Phenac's icon
        enters the town at its window FLOOR, 0x3E, so 0x3E is the byte on every arrival. 0x3F is reached only
        by the game's own first-visit-complete beat, which ENDS by forcing the player out toward Realgam --
        so there is barely a moment where anyone is standing in a Phenac room at 0x3F. The window described a
        state the player passes through somewhere else."""
        self.assertEqual((self._bump().when_byte_is, self._bump().becomes), (0x3E, 0x41))

    def test_those_bytes_are_the_ones_the_ladder_names(self) -> None:
        lands_on = {t.after: t.what for t in story_bytes.TRANSITIONS}
        self.assertIn("forced to Realgam Tower", lands_on[0x3F])
        self.assertIn("Phenac City fully unlocked", lands_on[0x41])

    def test_location_shuffle_only(self) -> None:
        self.assertIs(self._bump().gate, story_bytes.TRAVEL_SHUFFLE_ONLY)
        self.assertIsNotNone(story_bytes.live_bump_for("Phenac City", 0x3F, True, False))
        for scooter in (False, True):
            self.assertIsNone(story_bytes.live_bump_for("Phenac City", 0x3F, False, scooter),
                              "with travel vanilla the forced Realgam trip IS the next thing the game does")

    def test_the_whole_locked_band_is_caught_and_the_target_is_not(self) -> None:
        bump = self._bump()
        self.assertTrue(bump.applies("Phenac City", 0x3E),
                        "ADDENDUM 331: 0x3E is what the icon writes on landing -- this is the case the "
                        "player reported never firing")
        self.assertTrue(bump.applies("Phenac City", 0x3F), "the first visit having completed still lifts")
        self.assertTrue(bump.applies("Phenac City", 0x40), "a poll that landed a tick late still finishes")
        self.assertFalse(bump.applies("Phenac City", 0x41), "already there")
        self.assertFalse(bump.applies("Phenac City", 0x42), "never lowers")

    def test_the_bump_and_the_icon_agree_on_where_phenac_is_entered(self) -> None:
        """ADDENDUM 331 is two halves of one answer -- "raise the floor and its current byte". If they named
        different bytes the icon and the bump would fight over the town every time the map opened."""
        self.assertEqual(story_bytes.area_entry_floor("Phenac City"), self._bump().becomes)

    def test_it_does_not_fire_in_the_deeper_tiers(self) -> None:
        for region in ("Phenac City (Mayor's House)", "Phenac City (Post-Sixes)"):
            self.assertFalse(self._bump().applies(region, 0x3F))

    def test_the_rooms_a_locked_down_phenac_player_stands_in_resolve_to_it(self) -> None:
        """A bump that names a region no room maps to never fires. Phenac's own rooms are the plain-town
        tier, which is where a player at 0x3F is."""
        from ..game_data import chest_regions

        self.assertEqual(chest_regions.region_for_room(94), "Phenac City")
        self.assertEqual(chest_regions.region_for_room(98), "Phenac City")


if __name__ == "__main__":
    unittest.main()
