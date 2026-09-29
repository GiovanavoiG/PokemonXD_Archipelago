"""ADDENDUM 288 (2026-09-19) -- the credit was judged against the room the player had LEFT.

Player: "Outskirt stand still sent checks for unlocking every location. Double check our floor/write system
everywhere."

WHY OUTSKIRT STAND MAKES THIS DIAGNOSABLE RATHER THAN MYSTERIOUS. Its own entry floor is 0x5F, and
`_story_byte_was_earned_here` credits only thresholds STRICTLY above the region's floor (ADDENDUM 270). Of the
eleven live `Unlock -` thresholds exactly one -- Snagem Hideout, 0x62 -- is above 0x5F. So a CLEAN reading in
Outskirt Stand can credit at most one check, and eleven firing is arithmetic proof that the region the guard
was asked about was not Outskirt Stand. There are only three regions whose floor is below the lowest threshold
(0x24): the always-open three. The player was not standing in them. `ctx.room_tracker.current` was.

THE MECHANISM, and both halves of it are documented, correct, and were never read together:
  * `read_room_id` answers None rather than guessing when its four replicated copies disagree (ADDENDUM 142),
    which is exactly what happens across a room transition;
  * `RoomTracker` deliberately KEEPS its last trustworthy value on an unreadable poll (ADDENDUM 257: dropping
    it "would turn a one-tick hiccup into a lost chest check").
So for the whole of every transition the cached room is the room being LEFT -- while a travel has already
committed the DESTINATION's floor into the story byte. Leave an always-open area for anywhere at all and the
guard is asked "could a byte of 0x62 have been earned in the HQ Lab?" and truthfully answers yes.

Every other consumer of the cached room is doing arithmetic a stale value merely DELAYS. This one SENDS A
CHECK, which cannot be taken back. `consecutive_unknown` has existed since ADDENDUM 257 with no reader; it has
one now.

THE REST OF THIS FILE is the write-ownership half of the same sweep. `AreaStoryByteMemory.last_written_target`
is the one channel both readers test against, and only two of this client's writers reached it. Three others
could raise the byte and be banked as though the game had done it.
"""
from __future__ import annotations

import pathlib
import re
import sys
import types
import unittest

if "dolphin_memory_engine" not in sys.modules:
    _stub = types.ModuleType("dolphin_memory_engine")
    _stub.hook = lambda: None
    _stub.un_hook = lambda: None
    _stub.is_hooked = lambda: False
    _stub.read_bytes = lambda address, length: b""
    _stub.write_bytes = lambda address, data: None
    sys.modules["dolphin_memory_engine"] = _stub

from .. import ram_client as rc
from .. import travel_locations
from ..game_data import chest_regions, story_bytes

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _client() -> str:
    return (ROOT / "Client.py").read_text(encoding="utf-8")


class TestTheArithmeticThatIdentifiesTheBug(unittest.TestCase):
    """No mocking -- just the tables, proving a clean Outskirt Stand reading cannot do what was reported."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.thresholds = {n: t for n in travel_locations.TRAVEL_LOCATION_NAMES
                          if (t := travel_locations.vanilla_unlock_story_byte(n)) is not None}

    def test_outskirt_stands_floor_is_its_own_threshold(self) -> None:
        self.assertEqual(0x5F, story_bytes.area_entry_floor("Outskirt Stand"))
        self.assertEqual(0x5F, self.thresholds["Outskirt Stand"])

    def test_a_clean_reading_in_outskirt_stand_can_credit_exactly_one_check(self) -> None:
        floor = story_bytes.area_entry_floor("Outskirt Stand")
        eligible = [n for n, t in self.thresholds.items() if floor < t]
        self.assertEqual(["Snagem Hideout"], eligible,
                         "if this ever grows, the report's arithmetic no longer identifies a stale room")

    def test_only_four_regions_can_credit_everything(self) -> None:
        """The regions the guard WAS being asked about. Naming them is what turns the report into a diagnosis
        -- and the fourth is a small surprise worth pinning: Agate Village's floor is 0x19, below Mt. Battle's
        0x24, so it is as permissive as the always-open three despite not being one of them."""
        lowest = min(self.thresholds.values())
        permissive = sorted(r for r in set(chest_regions.ROOM_TO_REGION.values())
                            if (f := story_bytes.area_entry_floor(r)) is not None and f < lowest)
        self.assertEqual(
            ["Agate Village", "Gateon Port", "Kaminko's House (Robo Groudon)", "Pokemon HQ Lab"], permissive)
        self.assertLess(story_bytes.area_entry_floor("Agate Village"), lowest)

    def test_every_region_has_a_floor_so_the_guard_is_never_vacuous(self) -> None:
        """`floor is None` short-circuits the guard to True. ADDENDUM 279 gave the always-open three real
        floors; this asserts no region anywhere is still floorless."""
        for region in sorted(set(chest_regions.ROOM_TO_REGION.values())):
            self.assertIsNotNone(story_bytes.area_entry_floor(region), region)


class TestTheRoomTrackerReallyGoesStale(unittest.TestCase):
    def test_an_unreadable_poll_keeps_the_old_room_and_counts_it(self) -> None:
        tracker = rc.RoomTracker()
        tracker.current = 138
        from unittest import mock
        with mock.patch.object(rc, "read_room_id", lambda: None):
            for expected in (1, 2, 3):
                tracker.poll()
                self.assertEqual(138, tracker.current, "the cached room is kept, by design")
                self.assertEqual(expected, tracker.consecutive_unknown)

    def test_a_clean_read_clears_the_counter(self) -> None:
        tracker = rc.RoomTracker()
        tracker.current = 138
        tracker.consecutive_unknown = 7
        from unittest import mock
        with mock.patch.object(rc, "read_room_id", lambda: 164):
            tracker.poll()
        self.assertEqual(0, tracker.consecutive_unknown)
        self.assertEqual(164, tracker.current)

    def test_the_lag_is_unbounded(self) -> None:
        """Nothing caps it, which is why "how many ticks" was never the right question to ask."""
        tracker = rc.RoomTracker()
        tracker.current = 138
        from unittest import mock
        with mock.patch.object(rc, "read_room_id", lambda: None):
            for _ in range(500):
                tracker.poll()
        self.assertEqual(500, tracker.consecutive_unknown)
        self.assertEqual(138, tracker.current)


class TestTheCreditRefusesAStaleRoom(unittest.TestCase):
    """Structural -- `Client.py` is not importable here.

    RETARGETED 2026-09-25 (ADDENDUM 355). The hazard this class was written for was: the `Unlock -` credit
    read the player's LIVE room, `read_room_id` had come back unreadable, and the last-known room was being
    reused as if it were current. ADDENDUM 288's fix was to consult `consecutive_unknown` and refuse.

    THE CREDIT NO LONGER READS THE LIVE ROOM AT ALL. `_unlock_is_earned` asks the persisted area memory
    whether the GAME moved the byte to this destination's threshold while the player was in this destination.
    A stale room cannot produce a wrong answer to that question, because the question is not about the room
    the player is in now. So the hazard is closed by construction rather than by a counter -- which is the
    stronger form, and these tests now pin THAT rather than the counter.

    The counter itself is not dead: `AreaStoryByteMemory.describe` still reports it, which is what the player
    reads when a mark looks wrong. Pinned below so it cannot be quietly dropped."""

    @classmethod
    def setUpClass(cls) -> None:
        source = _client()
        cls.body = cls._slice(source, "def _unlock_is_earned") + cls._slice(source, "def _unlock_mark_for")
        cls.source = source
        cls.ram = (ROOT / "ram_client.py").read_text(encoding="utf-8")

    @staticmethod
    def _slice(source: str, header: str) -> str:
        """`re`, not `source.index("\ndef ")` -- what follows these two is `async def`, and bounding on the
        plain form swallows `enforce_travel_locks` whole."""
        start = source.index(header)
        following = re.search(r"^(?:async )?def ", source[start + len(header):], re.M)
        assert following is not None, header
        return source[start:start + len(header) + following.start()]

    def test_the_credit_does_not_consult_the_live_room(self) -> None:
        """The whole class of stale-room bugs, stated as a fact about the gate rather than as a guard in it."""
        for fragment in ("read_room_id", "MAP_SCREEN_ROOM_ID", "consecutive_unknown", "region_for_room"):
            self.assertNotIn(fragment, self.body, fragment)

    def test_it_reads_the_persisted_mark_instead(self) -> None:
        self.assertIn("ctx.area_story_memory.highest_by_region", self.body)

    def test_an_absent_mark_refuses_rather_than_crediting(self) -> None:
        """ADDENDUM 226/267/288's rule, unchanged in substance: never "credit anyway"."""
        self.assertIn("mark is not None and mark >= threshold", self.body)

    def test_the_counter_still_has_a_reader(self) -> None:
        """It existed from ADDENDUM 257 with none, and that was the shape of THAT bug. It has one now -- the
        stale banner in `describe` -- and losing it again would make an unreadable run silent."""
        self.assertGreaterEqual(self.ram.count("consecutive_unknown"), 2)
        self.assertIn("STALE:", self.ram)


class TestEveryStoryByteWriterRegistersOwnership(unittest.TestCase):
    """The sweep the player asked for: "double check our floor/write system everywhere"."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.ram = (ROOT / "ram_client.py").read_text(encoding="utf-8")
        cls.client = _client()

    def test_the_write_site_census_is_still_nine(self) -> None:
        """ADDENDUM 212's fence. If this changes, every claim below has to be re-derived."""
        # 11 since ADDENDUM 313 -- the Citadark arrival and floor, both of which set `last_written_value`
        # (pinned in test_addendum_313_citadark_entry).
        # 12 since ADDENDUM 321 (`write_story_byte`, the manual debug write; Client.py claims it).
        # 15 since ADDENDUM 332 -- SnagemBattleStoryHold's `_apply`, `_hold` and `_restore`. All three set
        # `last_written_value`, and the client claims them (asserted below). This is the first writer in the
        # client that LOWERS the byte, which is why it saves and restores rather than setting a floor.
        # ADDENDUM 350: the sites are unchanged, but each now calls `poke_story_byte` -- which writes all
        # twelve bits of GS variable 964 -- instead of stamping the byte's eight over the top of the low
        # three. The count is the same fence; the raw-write count being zero is a new one.
        # 16 since ADDENDUM 365: `AreaStoryByteMemory.clamp_poisoned_byte`, which puts a byte back when the
        # area it is standing in cannot hold it. The SECOND writer in this client that lowers the byte (after
        # ADDENDUM 332's hold), and unlike that one it does not save-and-restore: the value it writes is the
        # area's own mark, which is by construction a value the game itself put there. It calls `record()`
        # and sets `last_written_target`, which is this writer's own ownership channel because it IS the area
        # memory -- see the `test_it_claims_the_write_so_the_mark_is_not_banked_back` test in
        # test_addendum_365.
        self.assertEqual(16, self.ram.count("poke_story_byte(block_base, "))
        self.assertEqual(0, self.ram.count("write_bytes(block_base + STORY_RECORD_OFFSET + STORY_BYTE_OFFSET"))

    def test_the_scooter_hold_and_grant_both_record_what_they_wrote(self) -> None:
        start = self.ram.index("class ScooterStoryHold")
        body = self.ram[start:self.ram.index("\n@dataclass", start + 1)]
        self.assertIn("last_written_value: ", body, "the field must exist")
        self.assertIn("self.last_written_value = SCOOTER_HOLD_FLOOR", body, "the hold")
        self.assertIn("self.last_written_value = SS_LIBRA_SCOOTER_FLOOR", body, "the grant -- an unowned RAISE")

    def test_the_override_records_its_restore_and_its_recover(self) -> None:
        start = self.ram.index("class StoryByteOverride")
        body = self.ram[start:self.ram.index("\n@dataclass", start + 1)]
        self.assertIn("last_written_value: ", body)
        self.assertGreaterEqual(body.count("self.last_written_value = saved"), 2,
                                "_restore and recover are both raises and both run with active already False")

    def test_every_restore_clears_active_only_after_the_write(self) -> None:
        """THE SHARP ONE. `active` used to drop twenty-seven lines before the write, so a raising write
        stranded 0x77 -- above every `Unlock -` threshold -- with the fence already down.

        WIDENED BY ADDENDUM 332 from "the first `_restore` in the file" to EVERY one of them. That addendum
        added a second save-and-restore writer (`SnagemBattleStoryHold`), and a test anchored on
        `self.ram.index(...)` silently stops watching the class it was written for the moment another class
        with the same method name is defined above it. Checking all of them is both the honest fence and a
        stronger one."""
        found = 0
        cursor = 0
        while True:
            try:
                start = self.ram.index("    def _restore(self, block_base: int)", cursor)
            except ValueError:
                break
            cursor = start + 1
            body = self.ram[start:self.ram.index("\n    def ", start + 1)]
            if "poke_story_byte(block_base, " not in body:
                continue
            found += 1
            write_at = body.index("poke_story_byte(block_base, ")
            self.assertIn("self.active = False", body[write_at:],
                          "the flag must drop after the byte is genuinely back")
            before = body[:write_at]
            for line in before.splitlines():
                if line.strip().startswith("self.active = False"):
                    # Only allowed on paths that write nothing of ours at all.
                    context = before[:before.index(line)]
                    tail = context.rstrip()
                    self.assertTrue(
                        tail.endswith("if saved is None:")
                        or tail.endswith("if saved is None or current is None:")
                        or "declined_restores" in context.splitlines()[-1]
                        or "declined_restores" in tail,
                        "active may only be cleared early on a path that leaves nothing of ours in the byte",
                    )
        self.assertGreaterEqual(found, 2, "both save-and-restore writers must be covered")

    def test_every_writer_is_claimed_by_the_client(self) -> None:
        # ADDENDUM 332 adds `ctx.snagem_battle_hold` -- the first writer that LOWERS the byte, so an unclaimed
        # write here would not merely over-credit, it would let the witness treat a value we dropped as the
        # player's own and bank 0x62 as the hideout's mark for good.
        for writer in ("ctx.scooter_hold", "ctx.story_byte_override", "ctx.ss_libra_gate",
                       "ctx.snagem_battle_hold"):
            self.assertIn(f"_claim_story_write(ctx, {writer})", self.client, writer)

    def test_the_claim_goes_into_the_one_shared_channel(self) -> None:
        start = self.client.index("def _claim_story_write")
        body = self.client[start:self.client.index("\nasync def ", start)]
        self.assertIn("ctx.area_story_memory.last_written_target = value", body)
        self.assertIn("writer.last_written_value = None", body, "a claim must be consumed, not re-applied")
        self.assertIn("except Exception", body, "an ownership record must never break the poll loop")

    def test_both_overrides_fence_the_witness(self) -> None:
        start = self.client.index("def _any_override_holding")
        body = self.client[start:self.client.index("\ndef ", start + 1)]
        for name in ("story_byte_override", "ss_libra_gate"):
            self.assertIn(name, body, name)


class TestTheLabPassThrough(unittest.TestCase):
    """Player, ADDENDUM 288: "instead of hq lab going from 0x0D to 0x0F, make it go to 0x0E".
    Player, ADDENDUM 304: "Make the HQ Lab live bump from 0x0D to 0x0F again."

    REVERTED, and this class kept rather than deleted: the pairing it asserts (bump and floor move together)
    is the durable fact, and it is the thing that would silently break if only one of them were edited."""

    def test_the_bump_targets_0x0F(self) -> None:
        lab = [b for b in story_bytes.LIVE_STORY_BYTE_BUMPS if b.region == "Pokemon HQ Lab"]
        self.assertEqual(1, len(lab))
        self.assertEqual((0x0D, 0x0F), (lab[0].when_byte_is, lab[0].becomes))

    def test_the_paired_floor_rule_moved_with_it(self) -> None:
        """They are two halves of one instruction. A floor of 0x0F would push a returning player straight
        back past the value this change exists to stop at."""
        lab = [b for b in story_bytes.LIVE_STORY_BYTE_BUMPS if b.region == "Pokemon HQ Lab"][0]
        self.assertEqual(lab.becomes,
                         story_bytes.dynamic_region_floor("Pokemon HQ Lab", {"Pokemon HQ Lab": 0x0D}))

    def test_0x0E_is_on_the_allowlist_now(self) -> None:
        self.assertTrue(story_bytes.floor_is_accounted_for(0x0E))

    def test_the_bump_now_satisfies_the_always_open_gate(self) -> None:
        """RECORDED BECAUSE IT IS A REAL CONSEQUENCE, not because it is a bug, and it flipped back with
        ADDENDUM 304. ADDENDUM 280 opens Agate and Gateon when the lab reaches 0x0F, and `_always_open_gate`
        has two paths: the area MARK (which by ADDENDUM 277 never records our own writes) and the LIVE byte
        read while standing in the lab (which does). So with the bump back at 0x0F the gate latches off our
        own write the moment it fires, and those two destinations open at the lab's 0x0D rather than when the
        game reaches the Snag Machine tier by itself.

        That is the behaviour ADDENDUM 288 had removed and ADDENDUM 304 restores. Asserted so it is a stated
        consequence of the player's instruction rather than something discovered in play."""
        self.assertEqual(0x0F, travel_locations.ALWAYS_OPEN_GATE_BYTE)
        lab = [b for b in story_bytes.LIVE_STORY_BYTE_BUMPS if b.region == "Pokemon HQ Lab"][0]
        self.assertGreaterEqual(lab.becomes, travel_locations.ALWAYS_OPEN_GATE_BYTE)


if __name__ == "__main__":
    unittest.main()
