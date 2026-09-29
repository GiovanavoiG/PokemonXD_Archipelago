"""ADDENDUM 353 (2026-09-25): the party menu step is gone.

Player: "Does this new party structure mean we no longer need them to open the party menu in the setup step?"
Then: "Go ahead on the party menu work."

WHAT THE STEP WAS. `PARTY_BASE` (0x804280E8) is a 48-byte menu ROW -- name, species, level, HP -- and the
game does not populate a slot until the Party/Status screen has drawn it. So every boot, until the player
opened that screen once, the catch scan's party half read all-zero. `_looks_ingame()` existed to notice that,
and `docs/setup_en.md` asked the player to do it.

WHY IT CAN GO. ADDENDUM 351 found the structure the game itself uses: `heroBiosGetPokemonPtr(hero, i)` is
`hero + 0x30 + i*0xC4`, and the Hero object is 0x40 below the save block base, so party slot i is
`BLOCK_BASE - 0x10 + i*0xC4`. Those are SAVE DATA. They are valid from the moment the block resolves, no
menu required, and they carry a numeric species field.

AND IT FIXES A SECOND THING ON THE WAY. The save-side party reader this project already had,
`read_party_recap_species`, resolves species from the NAME TEXT and returns None for any nickname -- so a
nicknamed catch was invisible to it, documented as the expected non-error case. `+0x00` is the master
internal index, which `xd_species_index.national_dex_for` already takes, so the numeric path needs no new
mapping at all.
"""
import pathlib
import struct
import unittest

from .. import ram_client as rc
from ..tools import xd_species_index as xsi


BLOCK = 0x80479680
CLIENT_SOURCE = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
SETUP_DOC = (pathlib.Path(__file__).resolve().parent.parent / "docs" / "setup_en.md").read_text(
    encoding="utf-8")


class TestTheMasterIndexNeedsNoNewMapping(unittest.TestCase):
    """The claim the whole species half rests on: the live record's +0x00 is the MASTER index, and the
    display record's species field is that same value compacted (minus 25 from 277 up). So
    `national_dex_for(master)` and `national_dex_for_live_species(compacted)` are the same function composed
    with the compaction, and there is nothing new to write."""

    def test_the_two_paths_agree_for_every_value_in_range(self):
        for live in range(1, 700):
            master = live if live < xsi.LIVE_INDEX_GAP_START else live + xsi.LIVE_INDEX_GAP_SIZE
            self.assertEqual(xsi.national_dex_for_live_species(live), xsi.national_dex_for(master), live)

    def test_the_case_that_proved_it(self):
        """Metagross, read live in both structures at once: 375 in the display record, 400 in the live one,
        and 376 is the real National Dex number."""
        self.assertEqual(376, xsi.national_dex_for(400))
        self.assertEqual(376, xsi.national_dex_for_live_species(375))
        self.assertEqual(25, xsi.LIVE_INDEX_GAP_SIZE)


def _pokemon(data_id=133, level=50, hp=100, max_hp=100):
    raw = bytearray(rc.POKEMON_STRIDE)
    struct.pack_into(">H", raw, rc.POKEMON_DATA_ID_OFFSET, data_id)
    struct.pack_into(">H", raw, rc.POKEMON_HP_OFFSET, hp)
    struct.pack_into(">H", raw, rc.POKEMON_MAXHP_OFFSET, max_hp)
    raw[rc.POKEMON_LEVEL_OFFSET] = level
    return bytes(raw)


class _FakeParty:
    def __init__(self, members, fail_bulk=False):
        self.cells = bytearray(rc.POKEMON_STRIDE * rc.POKEMON_SLOTS)
        for index, raw in enumerate(members):
            self.cells[index * rc.POKEMON_STRIDE:(index + 1) * rc.POKEMON_STRIDE] = raw
        self.fail_bulk = fail_bulk
        self.reads = 0

    def install(self, test):
        test.addCleanup(setattr, rc, "read_bytes", rc.read_bytes)
        rc.read_bytes = self._read

    def _read(self, address, length):
        self.reads += 1
        if self.fail_bulk and length > rc.POKEMON_STRIDE:
            raise RuntimeError("bulk read refused")
        start = address - rc.party_slot_address(BLOCK, 0)
        if start < 0 or start + length > len(self.cells):
            raise ValueError("outside the party this fake models")
        return bytes(self.cells[start:start + length])


class TestTheSpeciesSnapshot(unittest.TestCase):
    def test_it_resolves_the_national_dex_from_the_numeric_field(self):
        party = _FakeParty([_pokemon(133), _pokemon(197, max_hp=44, hp=44), _pokemon(400)])
        party.install(self)
        self.assertEqual({133, 197, 376}, rc.get_live_party_species_snapshot(BLOCK))

    def test_a_nickname_cannot_hide_a_catch(self):
        """The hole in the name-based save-side reader, stated as a property. Nothing in this path reads a
        name, so there is nothing a nickname can change -- the record here has no name bytes at all."""
        party = _FakeParty([_pokemon(133)])
        party.install(self)
        self.assertEqual({133}, rc.get_live_party_species_snapshot(BLOCK))

    def test_an_empty_party_is_an_empty_set_not_an_error(self):
        party = _FakeParty([])
        party.install(self)
        self.assertEqual(set(), rc.get_live_party_species_snapshot(BLOCK))

    def test_the_whole_party_is_one_read(self):
        party = _FakeParty([_pokemon(133), _pokemon(197, max_hp=44, hp=44)])
        party.install(self)
        rc.read_party(BLOCK)
        self.assertEqual(1, party.reads, "six contiguous records are one round trip, not six")

    def test_a_refused_bulk_read_falls_back_to_one_slot_at_a_time(self):
        """"The party is empty" is a meaningful answer to two different callers, so a single bad read must
        never be able to produce it."""
        party = _FakeParty([_pokemon(133), _pokemon(197, max_hp=44, hp=44)], fail_bulk=True)
        party.install(self)
        self.assertEqual({133, 197}, rc.get_live_party_species_snapshot(BLOCK))
        self.assertEqual(1 + rc.POKEMON_SLOTS, party.reads)


class TestTheGateIsGoneFromTheMainLoop(unittest.TestCase):
    def test_neither_scan_is_gated_on_the_party_menu(self):
        start = CLIENT_SOURCE.index("if block_is_stable:")
        end = CLIENT_SOURCE.index("elif not ctx._block_churn_logged:", start)
        block = CLIENT_SOURCE[start:end]
        self.assertIn("await check_species_catches(ctx)", block)
        self.assertIn("await check_purifications(ctx)", block)
        self.assertNotIn("_looks_ingame", block)

    def test_the_one_surviving_gate_is_around_the_correlation_that_needs_it(self):
        """`PurificationTracker.poll` correlates the recap array against PARTY_BASE, and that has never been
        confirmed safe against an all-zero PARTY_BASE. That call keeps the gate; nothing else does."""
        start = CLIENT_SOURCE.index("async def check_purifications")
        end = CLIENT_SOURCE.index("\nasync def ", start + 1)
        body = CLIENT_SOURCE[start:end]
        self.assertIn("if _looks_ingame():", body)
        gate = body.index("if _looks_ingame():")
        self.assertLess(gate, body.index("ctx.purification_tracker.poll("))

    def test_the_state_scan_is_not_behind_that_gate(self):
        """ADDENDUM 318's scan is what covers the Purify Chamber and a purification from before the client
        connected. With the menu unopened it is the ONLY half that runs, so it must not be gated too."""
        start = CLIENT_SOURCE.index("async def check_purifications")
        end = CLIENT_SOURCE.index("\nasync def ", start + 1)
        body = CLIENT_SOURCE[start:end]
        self.assertLess(body.index("ctx.purification_tracker.poll("), body.index("scan_shadow_records"))
        self.assertEqual(1, body.count("if _looks_ingame():"),
                         "exactly one gate in this function, and it is the one above the correlation")

    def test_the_catch_scan_reads_the_live_records_first(self):
        start = CLIENT_SOURCE.index("async def check_species_catches")
        end = CLIENT_SOURCE.index("\nasync def ", start + 1)
        body = CLIENT_SOURCE[start:end]
        self.assertIn("get_live_party_species_snapshot", body)
        self.assertLess(body.index("get_live_party_species_snapshot"),
                        body.index("get_owned_species_snapshot"),
                        "PARTY_BASE is the second witness now, not the first")

    def test_the_hint_that_asked_for_an_action_is_gone(self):
        """A one-shot instruction telling the player to do something that no longer does anything is worse
        than silence."""
        self.assertNotIn("this boot only needs it opened one time", CLIENT_SOURCE)
        self.assertNotIn("_not_ingame_hint_logged = True", CLIENT_SOURCE,
                         "the hint is gone, so nothing should still be latching it as printed")

    def test_the_setup_doc_no_longer_asks_for_it(self):
        self.assertNotIn("Party/Status screen", SETUP_DOC)
        self.assertNotIn("lazily initialized", SETUP_DOC)

    def test_the_playing_steps_are_still_numbered_contiguously(self):
        """Removing a step from a numbered list is exactly the edit that leaves 1,2,3,5,6 behind."""
        import re
        section = SETUP_DOC[SETUP_DOC.index("## Playing"):]
        section = section[:section.index("\n## ", 1)] if "\n## " in section[1:] else section
        numbers = [int(m.group(1)) for m in re.finditer(r"^(\d+)\. ", section, re.M)]
        self.assertEqual(list(range(1, len(numbers) + 1)), numbers)
