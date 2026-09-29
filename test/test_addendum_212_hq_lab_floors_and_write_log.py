"""ADDENDUM 212 (2026-09-14) -- the three early-game HQ Lab floors, and the manual story-byte write log.

Player instruction, verbatim:
    "For location shuffle, If Kaminko reaches 0x07, and HQ Lab is below it, IMMEDIATELY set HQ lab to 0x07. If
     HQ Lab reaches 0x0D, IMMEDIATELY change it to 0x0F. If Gateon reaches 0x16, set HQ lab to 0x17.
     Please add a command that will print a log of all of our MANUAL story byte overwrites throughout a run -
     just keep a running list."

Two features, one addendum, because the second exists to make the first auditable: the whole point of a write
log is that a player who ends up at a byte they did not expect can see which rule put them there.
"""
import unittest

from ..game_data import story_bytes
from .. import ram_client


#: The lab's pass-through target, DERIVED from the bump table rather than written here. ADDENDUM 288 moved
#: it from 0x0F to 0x0E, and this file failed in six places because it had the number typed out six times.
_PASS_THROUGH = next(b.becomes for b in story_bytes.LIVE_STORY_BYTE_BUMPS if b.region == "Pokemon HQ Lab")


class TestTheThreeHQLabFloors(unittest.TestCase):
    """Each rule is tested at its boundary from BOTH sides -- one below and one at the threshold -- because a
    rule that fires one value early is exactly as wrong as one that never fires, and an `>=` typed as `>` is
    the single easiest mistake to make in this table."""

    def floor(self, marks: "dict[str, int]") -> "int | None":
        return story_bytes.dynamic_region_floor("Pokemon HQ Lab", marks)

    def test_no_rule_fires_on_a_cold_memory(self):
        self.assertIsNone(self.floor({}), "an untouched run must impose no floor on the lab at all")

    def test_kaminko_0x07_raises_the_lab_to_0x07(self):
        self.assertIsNone(self.floor({"Kaminko's House": 0x06}), "0x06 is below the threshold")
        self.assertEqual(self.floor({"Kaminko's House": 0x07}), 0x07)
        self.assertEqual(self.floor({"Kaminko's House": 0x09}), 0x07,
                         "the rule is >= -- overshooting the threshold must not stop it firing")

    def test_the_lab_skips_its_own_0x0D_pass_through(self):
        self.assertEqual(self.floor({"Pokemon HQ Lab": 0x0C}), None)
        # ADDENDUM 288: the pass-through target is 0x0E now (player, 2026-09-19). Read from the bump table
        # so the floor rule and the live bump cannot drift -- they are two halves of one instruction.
        self.assertEqual(self.floor({"Pokemon HQ Lab": 0x0D}), _PASS_THROUGH)

    def test_the_self_referential_rule_is_idempotent(self):
        """The 0x0D -> 0x0F rule names its own target, so it must be checked for a feedback loop: applying it
        and feeding the result back in has to converge, not climb."""
        marks = {"Pokemon HQ Lab": 0x0D}   # ADDENDUM 288: settles on _PASS_THROUGH, not 0x0F
        for _ in range(5):
            value = self.floor(marks)
            self.assertEqual(value, _PASS_THROUGH)
            marks["Pokemon HQ Lab"] = max(marks["Pokemon HQ Lab"], value)
        self.assertEqual(marks["Pokemon HQ Lab"], _PASS_THROUGH)

    def test_gateon_0x16_raises_the_lab_to_0x17(self):
        """TIGHTENED 2026-09-15 (ADDENDUM 227): the lab must ALSO have reached its own 0x0F first.

        ADDENDUM 277 did not change this VALUE. 0x0F is the Snag Machine tier (player, 2026-09-18), which is
        exactly the right thing to ask for. What changed is what can SATISFY it: the live bump (ADDENDUM 213,
        0x0D -> 0x0F) is a CLIENT write, and a client write is no longer eligible to become the lab's mark. So
        "the lab reached 0x0F" now means the game put it there, and this rule stopped being satisfiable by
        merely walking into the lab."""
        # ADDENDUM 288: the pass-through rule now answers _PASS_THROUGH (0x0E), which is BELOW the 0x0F mark
        # this case supplies -- so the floor here is the mark itself, not a rule. Same conclusion, one layer
        # down: 0x17 stays shut until Gateon has the Machine Part.
        self.assertEqual(self.floor({"Gateon Port": 0x15, "Pokemon HQ Lab": 0x0F}), _PASS_THROUGH,
                         "0x15 is the value BEFORE the Machine Part, so 0x17 stays shut and the lab's own "
                         "pass-through rule is the highest one satisfied")
        self.assertEqual(self.floor({"Gateon Port": 0x16, "Pokemon HQ Lab": 0x0F}), 0x17)

    def test_the_lab_must_have_earned_its_own_0x0f_first(self):
        """The half ADDENDUM 227 added. Gateon alone said nothing about where the LAB had got to."""
        self.assertIsNone(self.floor({"Gateon Port": 0x16}), "lab never seen -- no floor to raise")
        self.assertEqual(self.floor({"Gateon Port": 0x16, "Pokemon HQ Lab": 0x07}), None,
                         "lab only at 0x07 -- 0x17 is two rungs away, not one")
        # ADDENDUM 288: 0x0E is now the pass-through TARGET rather than a value inside the window, but the
        # point is unchanged -- the lab has not reached its own 0x0F, so the 0x17 rule is not open yet and
        # the pass-through rule is still the highest satisfied one.
        self.assertEqual(self.floor({"Gateon Port": 0x16, "Pokemon HQ Lab": 0x0E}), _PASS_THROUGH,
                         "the lab must earn its own 0x0F before the 0x17 rule opens")

    def test_the_ladder_self_sequences(self):
        """The three lab rules form a chain: 0x07 -> 0x0F -> 0x17, each rung earned before the next opens."""
        marks = {"Kaminko's House": 0x07, "Gateon Port": 0x16}
        self.assertEqual(self.floor(marks), 0x07)
        marks["Pokemon HQ Lab"] = 0x0D
        self.assertEqual(self.floor(marks), _PASS_THROUGH)
        marks["Pokemon HQ Lab"] = 0x0F
        self.assertEqual(self.floor(marks), 0x17)

    def test_the_highest_satisfied_rule_wins(self):
        """All three can be satisfied at once late in the early game. `dynamic_region_floor` takes the max, so
        an earlier rule can never drag the lab back down."""
        # UPDATED (ADDENDUM 227): at lab 0x0D the 0x17 rule is NOT yet satisfied -- the lab has to reach 0x0F
        # first -- so the highest satisfied rule here is the 0x0D -> 0x0F one.
        marks = {"Kaminko's House": 0x07, "Pokemon HQ Lab": 0x0D, "Gateon Port": 0x16}
        self.assertEqual(self.floor(marks), _PASS_THROUGH)
        marks["Pokemon HQ Lab"] = 0x0F          # the Snag Machine rung
        self.assertEqual(self.floor(marks), 0x17, "once the lab is at 0x0F, 0x17 becomes the highest")


class TestARuleOnlyEverRaises(unittest.TestCase):
    """The player's "and HQ Lab is below it" clause is not implemented as a condition -- it falls out of
    `target_for` taking a max. That is only true if this holds, so it is asserted rather than assumed."""

    def test_a_lab_already_past_the_floor_keeps_its_own_value(self):
        memory = ram_client.AreaStoryByteMemory()
        memory.observe("Kaminko's House", 0x07)
        memory.observe("Pokemon HQ Lab", 0x30)
        self.assertEqual(memory.target_for("Pokemon HQ Lab"), 0x30,
                         "a rule must never send an area backwards")

    def test_a_first_visit_takes_the_rule_floor(self):
        memory = ram_client.AreaStoryByteMemory()
        memory.observe("Gateon Port", 0x16)
        memory.observe("Kaminko's House", 0x07)
        self.assertNotIn("Pokemon HQ Lab", memory.visited)
        self.assertEqual(memory.target_for("Pokemon HQ Lab"), 0x07,
                         "a lab never visited cannot have earned 0x0F, so 0x17 is not open to it yet")


class TestTheRulesNameRealThings(unittest.TestCase):
    """ADDENDUM 184's fence, re-applied to the new rows: a rule whose `requires` names something that is not an
    AREA_GROUPS key silently never fires, which is the failure mode ADDENDUM 210 was caught by."""

    def test_every_required_area_is_a_declared_group(self):
        for rule in story_bytes.AREA_FLOOR_RULES:
            for area, _ in rule.requires:
                self.assertIn(area, story_bytes.AREA_GROUPS,
                              f"rule targeting {rule.target!r} requires undeclared area {area!r}")

    def test_the_lab_is_a_declared_group_and_a_real_region(self):
        self.assertIn("Pokemon HQ Lab", story_bytes.AREA_GROUPS)
        self.assertIn("Pokemon HQ Lab", story_bytes.ALL_KNOWN_REGIONS)

    def test_the_lab_has_no_static_window_so_the_rules_are_its_only_floor(self):
        """If the lab ever gains a window this test fails, which is the point: the three rules were written on
        the assumption that nothing else supplies a floor here."""
        self.assertIn("Pokemon HQ Lab", story_bytes.ALWAYS_OPEN_REGIONS)
        # ADDENDUM 279: the lab has a first-visit byte (0x00). The rules are no longer its ONLY floor, but
        # they are still what raises it past that, which is what the rest of this class checks.
        self.assertEqual(0x00, story_bytes.region_floor("Pokemon HQ Lab"))


class TestTheWriteLogRecords(unittest.TestCase):
    def test_an_empty_log_says_so_without_pretending(self):
        log = ram_client.StoryByteWriteLog()
        text = "\n".join(log.describe())
        self.assertIn("none yet", text)

    def test_entries_are_numbered_and_ordered(self):
        log = ram_client.StoryByteWriteLog()
        log.record("area memory", "Pokemon HQ Lab", 0x30, 0x17, "first visit floor")
        log.record("parts override", "Gateon Port", 0x17, 0x6E, "parts complete")
        self.assertEqual([e.seq for e in log.entries], [1, 2])
        self.assertEqual(log.total, 2)
        text = "\n".join(log.describe())
        self.assertIn("0x30 -> 0x17", text)
        self.assertIn("0x17 -> 0x6E", text)

    def test_an_unreadable_previous_value_prints_as_unknown_not_as_zero(self):
        log = ram_client.StoryByteWriteLog()
        log.record("area memory", "Agate Village", None, 0x19, "first visit floor")
        self.assertIn("0x?? -> 0x19", "\n".join(log.describe()))

    def test_the_list_is_bounded_but_the_total_is_not(self):
        log = ram_client.StoryByteWriteLog()
        for index in range(ram_client.StoryByteWriteLog.MAX_ENTRIES + 25):
            log.record("area memory", "Phenac City", 0x3E, 0x41, "highest reached in this area")
        self.assertEqual(len(log.entries), ram_client.StoryByteWriteLog.MAX_ENTRIES)
        self.assertEqual(log.total, ram_client.StoryByteWriteLog.MAX_ENTRIES + 25)
        self.assertEqual(log.dropped, 25)
        self.assertIn("trimmed", "\n".join(log.describe()))

    def test_limit_shows_only_the_tail(self):
        log = ram_client.StoryByteWriteLog()
        for _ in range(10):
            log.record("area memory", "Pyrite Town", 0x30, 0x3C, "highest reached in this area")
        lines = log.describe(limit=3)
        self.assertEqual(sum(1 for line in lines if line.strip().startswith("#")), 3)

    def test_it_round_trips_through_json(self):
        log = ram_client.StoryByteWriteLog()
        log.record("area memory", "Pokemon HQ Lab", None, 0x0F, "highest reached in this area")
        log.record("parts restore", "Gateon Port", 0x6E, 0x20, "left Gateon")
        restored = ram_client.StoryByteWriteLog()
        restored.load_json(log.to_json())
        self.assertEqual(restored.total, 2)
        self.assertEqual([e.now for e in restored.entries], [0x0F, 0x20])
        self.assertIsNone(restored.entries[0].was)

    def test_a_corrupt_file_degrades_to_an_empty_log_rather_than_raising(self):
        """Same contract as AreaStoryByteMemory.load_json. Nothing reads this log back to make a decision, so
        an unreadable one must never be able to take the client down."""
        for junk in ({}, {"entries": "not a list"}, {"entries": [{"seq": "x"}]}, {"total": None}):
            restored = ram_client.StoryByteWriteLog()
            restored.load_json(junk)
            self.assertEqual(restored.entries, [])

    def test_one_bad_row_does_not_cost_the_whole_log(self):
        good = {"seq": 1, "when": 0.0, "source": "area memory", "context": "Agate Village",
                "was": 0x19, "now": 0x1A, "why": "x"}
        restored = ram_client.StoryByteWriteLog()
        restored.load_json({"total": 2, "entries": [good, {"seq": "nonsense"}]})
        self.assertEqual(len(restored.entries), 1)

    def test_recording_never_raises(self):
        log = ram_client.StoryByteWriteLog()
        self.assertIsNotNone(log.record("area memory", "x", None, 0x10, "y"))


class TestEveryWriteSiteIsLogged(unittest.TestCase):
    """The fence named in ram_client's ADDENDUM 212 section comment. There are exactly three places in this
    project that overwrite the story byte; a fourth that forgets to call `record()` would make `!storylog`
    quietly incomplete, which is worse than not having it."""

    def test_there_are_still_exactly_three_story_byte_write_sites(self):
        import inspect

        source = inspect.getsource(ram_client)
        # ADDENDUM 350 turned the raw `write_bytes(block_base + STORY_RECORD_OFFSET + STORY_BYTE_OFFSET, ...)`
        # of every site into a call to `poke_story_byte`, which sets all twelve bits of GS variable 964
        # instead of the byte's eight. The fence is unchanged in intent and strictly stronger in reach: the
        # census now also demands that NOTHING but `poke_story_byte` touches that address, so a new site
        # cannot write a bare byte even by accident.
        sites = source.count("poke_story_byte(block_base, ")
        raw = source.count("write_bytes(block_base + STORY_RECORD_OFFSET + STORY_BYTE_OFFSET")
        self.assertEqual(raw, 0,
                         "the story byte is eight bits of a twelve-bit variable (ADDENDUM 350) -- a raw "
                         "one-byte write leaves the game on a rung no script tests for; call "
                         "poke_story_byte() instead")
        # 3 at ADDENDUM 212; 4 since ADDENDUM 213 added the live in-area bump; 5 since ADDENDUM 229 added the
        # map back-out restore; 7 since ADDENDUM 272 added the Gateon ceiling's re-clamp (`_hold`, for a byte
        # that rises while the player stands in Gateon) and its crash recovery (`recover`). Raised
        # deliberately each time, as the message below demands, rather than the fence being waived -- this
        # test catching both of ADDENDUM 272's writers is the fence working, and both call `record()`.
        # 9 since ADDENDUM 274 added ScooterStoryHold's two: the hold itself and the grant that pays it back
        # when the item lands. Both call `record()`; both are guarded by `shuffle_scooter_upgrade`.
        # 11 since ADDENDUM 313: StoryByteOverride's Citadark arrival and Citadark floor. Both call `record()`
        # and set `last_written_value`; both only run with robo_kyogre_parts_unlock_citadark on.
        # 12 since ADDENDUM 321: `write_story_byte`, the `!storybyte` debug command's write. It calls
        # `record()` like every other site and its caller claims the write, so the witness cannot bank it.
        # 15 since ADDENDUM 332: SnagemBattleStoryHold's three -- `_apply` (the drop to 0x62 for a Snagem
        # fight), `_hold` (a byte that rose mid-fight, re-dropped) and `_restore` (the player's own value put
        # back). The FIRST writer in this client that lowers the byte, which is why it is a save-and-restore
        # hold rather than a floor; all three call `record()` and set `last_written_value`.
        # 16 since ADDENDUM 365: `AreaStoryByteMemory.clamp_poisoned_byte`, which puts a byte back when the
        # area it is standing in cannot hold it. The SECOND writer in this client that lowers the byte (after
        # ADDENDUM 332's hold), and unlike that one it does not save-and-restore: the value it writes is the
        # area's own mark, which is by construction a value the game itself put there. It calls `record()`
        # and sets `last_written_target`, which is this writer's own ownership channel because it IS the area
        # memory -- see the `test_it_claims_the_write_so_the_mark_is_not_banked_back` test in
        # test_addendum_365.
        self.assertEqual(sites, 16,
                         "a story-byte write site was added or removed -- if added, it must also call "
                         "write_log.record(), and this count must be updated deliberately")

    def test_both_writers_accept_a_log_and_default_to_none(self):
        self.assertIsNone(ram_client.AreaStoryByteMemory().write_log)
        self.assertIsNone(ram_client.StoryByteOverride().write_log)
        log = ram_client.StoryByteWriteLog()
        self.assertIs(ram_client.AreaStoryByteMemory(write_log=log).write_log, log)
        self.assertIs(ram_client.StoryByteOverride(write_log=log).write_log, log)

    def test_the_area_memory_logs_the_write_it_performs(self):
        """Driven through `poll` with `write_bytes` stubbed, so this asserts the record happens at the real
        write site rather than that a helper exists."""
        log = ram_client.StoryByteWriteLog()
        memory = ram_client.AreaStoryByteMemory(write_log=log)
        # A floor has to exist before there is anything to write: the lab is always-open and has no static
        # window, so the ADDENDUM 212 Gateon rule is what gives it one.
        memory.observe("Gateon Port", 0x16)
        memory.observe("Pokemon HQ Lab", 0x0F)   # ADDENDUM 227/277: the 0x17 rule needs the Snag Machine rung
        written: "list[tuple[int, bytes]]" = []
        original = ram_client.write_bytes
        ram_client.write_bytes = lambda address, data: written.append((address, data))
        try:
            note = memory.poll(0x80479000, "Pokemon HQ Lab", None, 0x30)
        finally:
            ram_client.write_bytes = original
        self.assertIsNotNone(note)
        self.assertEqual(len(written), 1)
        self.assertEqual(log.total, 1, "the write happened but was not logged")
        entry = log.entries[0]
        self.assertEqual(entry.source, "area memory")
        self.assertEqual(entry.context, "Pokemon HQ Lab")
        self.assertEqual(entry.was, 0x30)
        self.assertEqual(entry.now, 0x17, "the Gateon rule's floor is what should have been written")
        self.assertEqual(entry.now, written[0][1][0], "the logged value must be the byte that went in")

    def test_a_declined_write_logs_nothing(self):
        """An idle map screen, where the byte already matches, must not fill the log with no-ops."""
        log = ram_client.StoryByteWriteLog()
        memory = ram_client.AreaStoryByteMemory(write_log=log)
        memory.observe("Agate Village", 0x19)
        self.assertIsNone(memory.poll(0x80479000, "Agate Village", None, 0x19))
        self.assertEqual(log.total, 0)

    def test_an_unknown_destination_logs_nothing(self):
        log = ram_client.StoryByteWriteLog()
        memory = ram_client.AreaStoryByteMemory(write_log=log)
        self.assertIsNone(memory.poll(0x80479000, None, "Pyrite Town", 0x30))
        self.assertEqual(log.total, 0)


class TestTheCommandExists(unittest.TestCase):
    """Checked against the SOURCE rather than by import, the same way every other Client.py test in this suite
    is: Client.py pulls in Archipelago's CommonClient, which needs a real websockets install."""

    @classmethod
    def setUpClass(cls):
        from pathlib import Path

        cls.source = (Path(ram_client.__file__).resolve().parent / "Client.py").read_text(encoding="utf-8")

    def test_storylog_is_registered_and_takes_an_optional_count(self):
        self.assertIn("def _cmd_storylog(self, *args: str) -> None:", self.source,
                      "!storylog must exist and accept an optional entry count")

    def test_the_log_is_shared_by_both_writers(self):
        """One log, handed to both mechanisms. Two separate logs would print two lists the player has to
        interleave by hand, which is not what "a running list" means."""
        self.assertIn("self.story_write_log = ram_client.StoryByteWriteLog()", self.source)
        self.assertIn("ram_client.AreaStoryByteMemory(write_log=self.story_write_log)", self.source)
        self.assertIn("ram_client.StoryByteOverride(write_log=self.story_write_log)", self.source)

    def test_the_log_is_persisted_so_it_survives_a_client_restart(self):
        """"Throughout a run" is the requirement, and a run outlives a client session."""
        for fragment in ("_story_write_log_path", "_load_story_write_log", "_save_story_write_log",
                         "story_byte_writes_"):
            self.assertIn(fragment, self.source, f"missing persistence piece: {fragment}")

    def test_both_polls_persist_the_log_after_running(self):
        # ADDENDUM 273: 3 now -- the area-memory poll, the parts-override poll, and the SS Libra gate that
        # runs on the travel-randomization-OFF path. Raised deliberately, like ADDENDUM 212's write-site
        # census: a persister added without this count moving would mean a writer whose log never reaches disk.
        # ADDENDUM 293 added the fifth: the vanilla-travel bump (`_bump_in_vanilla_travel`), which is a
        # story-byte write like any other and has to reach the same log.
        # ADDENDUM 321 added the sixth: the `!storybyte` debug command, which writes the byte on the player's
        # own instruction and so has to land in the same log as every automatic writer.
        # ADDENDUM 332 added the seventh: the Snagem battle hold, whose drop and restore are story-byte writes
        # like any other -- and the only ones that go DOWNWARD, so a log that never reached disk would lose
        # the one record showing the value was put back.
        # ADDENDUM 365 added the eighth: the poisoned-byte clamp persists the log right after it writes, for
        # the same reason every other site does -- a write nobody can see afterwards is a write nobody can
        # question.
        self.assertEqual(self.source.count("_save_story_write_log(ctx)"), 8,
                         "the area-memory poll and the parts-override poll must each persist the log")


if __name__ == "__main__":
    unittest.main()
