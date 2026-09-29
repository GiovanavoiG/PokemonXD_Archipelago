"""ADDENDUM 244 (2026-09-16) -- audit of the three things the player asked to re-check.

Player: "Let's double check that our rematchable fights aren't infinitely spawning shadow pokemon. Let's also
double check our pc scanning, and our purification checks."

All three hold. What follows pins the parts that were NOT already covered by ADDENDUM 236's own tests, plus
two findings that were new to this pass.
"""
import glob
import os
import unittest

from .. import ram_client as rc
from ..game_data import census_repeat_column, missable_trainers, trainer_roster

DUMP_DIR = "/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/"

_REPEAT = census_repeat_column.CENSUS_REPEAT_AND_MISSABLE
_FINAL = {i for i, (repeat, _m) in _REPEAT.items() if repeat == "final"}
_EARLIER = {i for i, (repeat, _m) in _REPEAT.items() if repeat and repeat.startswith("earlier")}
_MISSABLE = {i for i, (_r, missable) in _REPEAT.items() if missable}


class TestTheRefightFenceCoversTheWholeShape(unittest.TestCase):
    """ADDENDUM 236 asserts that the `final` rows are inside the exclusion set. This widens that to the whole
    shape of the workbook's repeat column, because `final` alone is not the whole hazard."""

    def setUp(self) -> None:
        self.excluded = missable_trainers.shadow_expansion_excluded_trainer_indices()

    def test_final_earlier_and_missable_are_all_excluded(self) -> None:
        """A `final` row is re-fightable, so a Shadow there is farmable. An `earlier` row is one occurrence of
        a repeated fight, so a Shadow there is walk-past-able once the story moves on. A missable row is
        losable outright. All three are catch locations that cannot be trusted, and all three are in."""
        self.assertEqual(_FINAL - self.excluded, set(), "a re-fightable trainer can take a generated Shadow")
        self.assertEqual(_EARLIER - self.excluded, set(), "an earlier occurrence can take a generated Shadow")
        self.assertEqual(_MISSABLE - self.excluded, set(), "a missable trainer can take a generated Shadow")

    def test_the_set_is_big_enough_to_be_doing_something(self) -> None:
        """A fence that shrank to nothing would pass every test above. 150 of the 232 story trainers."""
        self.assertEqual(len(self.excluded), 150)   # ADDENDUM 341 lifted 337's +Wakin/+Gonzap
        self.assertEqual(len(_FINAL), 35)

    def test_the_five_the_player_reported_and_the_two_brothers(self) -> None:
        """The rows ADDENDUM 236 named from the real plan that triggered the report."""
        for index in (167, 215, 223, 226, 232):
            self.assertIn(index, self.excluded, index)
        for index in (34, 35):
            self.assertIn(index, self.excluded, index)


class TestVanillaShadowsOnRefightableTrainers(unittest.TestCase):
    """A FINDING OF THIS PASS, recorded rather than fixed.

    ADDENDUM 236 stopped the expansion putting GENERATED Shadows on re-fightable trainers. It did not -- and
    could not -- do anything about the VANILLA ones: seven trainers the workbook marks `final` hold a DDPK
    (Shadow) slot in the shipped game, including MIROR B., whose rematches are a designed vanilla mechanic.
    Seven more sit on missable rows, RESIX among them -- the trainer the player's original report named.

    THIS IS NOT AN AP HAZARD, and the reason is worth pinning rather than reasoning out again next time: a
    catch check is keyed by SPECIES, not by trainer or by encounter. Re-fighting a trainer and re-snagging the
    same Shadow yields a species that has already been reported, and `_send_checks` -> `ctx.check_locations`
    is idempotent against an already-checked id. So a rematch can hand the player another Pokemon -- which is
    vanilla behaviour -- but it can never send another check."""

    def _shadow_holders(self):
        return {t["index"]: t["name"] for t in trainer_roster.TRAINERS
                if any(slot.get("kind") == "DDPK" for slot in t["team"])}

    def test_vanilla_shadows_do_sit_on_refightable_and_missable_trainers(self) -> None:
        holders = self._shadow_holders()
        self.assertEqual(len(holders), 72)
        on_final = sorted(set(holders) & _FINAL)
        on_missable = sorted(set(holders) & _MISSABLE)
        self.assertEqual([holders[i] for i in on_final],
                         ["ZOOK", "SMARTON", "LOVRINA", "SNATTLE", "ARDOS", "GORIGAN", "MIROR B."])
        self.assertIn("RESIX", [holders[i] for i in on_missable])

    def test_a_catch_location_is_named_after_a_species_not_a_trainer(self) -> None:
        """The property that makes the above harmless. If catch locations were ever keyed per encounter, the
        seven trainers above would become seven farmable checks and this test is where that shows up."""
        from .. import locations, species
        for dex in (1, 133, 250):
            name = species.location_name_for_species(dex)
            self.assertIn(name, locations.LOCATION_TABLE)
            self.assertTrue(name.startswith("Catch - "), name)
            self.assertNotIn("Defeat", name)


class TestThePcBoxOverScanIsClean(unittest.TestCase):
    """`PC_BOX_SCAN_COUNT` is 12 while the box addressing is only CONFIRMED through box 8, and the four extra
    boxes are scanned on the argument that "a nonexistent/out-of-range box's slots almost certainly won't
    decode to an exact real species name by coincidence".

    That argument was never tested, and it is the one that matters: if those addresses landed on some other
    structure holding Pokemon, the box half would fire catch checks for Pokemon the player may not own -- and
    a false catch is unrecoverable within a seed. Measured here against real 24 MB MEM1 dumps."""

    def _dump(self, name):
        path = os.path.join(DUMP_DIR, name)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as handle:
            return handle.read()

    def _scan(self, memory, block_base):
        rows = []
        for slot in range(rc.PC_BOX_SCAN_COUNT * rc.PC_BOX_SLOTS_PER_BOX):
            box, local = divmod(slot, rc.PC_BOX_SLOTS_PER_BOX)
            anchor = (block_base + rc.BOX_SLOT_TEXT_ANCHOR_OFFSET
                      + box * (rc.PC_BOX_SLOTS_PER_BOX * rc.BOX_SLOT_STRIDE + rc.BOX_PADDING_PER_BOX)
                      + local * rc.BOX_SLOT_STRIDE)
            offset = anchor - rc.MEM1_START
            if offset < 0 or offset + rc.PARTY_NAME_MAX_BYTES > len(memory):
                continue
            text = memory[offset:offset + rc.PARTY_NAME_MAX_BYTES].decode(
                "utf-16-be", errors="ignore").split("\x00")[0].strip()
            if text and rc.species_dex_from_name(text) is not None:
                rows.append((box + 1, text))
        return rows

    def test_boxes_nine_to_twelve_decode_no_species_in_any_real_dump(self) -> None:
        """Three dumps, three different sessions. Boxes 1-8 decode the player's real Pokemon; 9-12 decode
        nothing at all -- so the over-scan reads dead space, not another Pokemon-bearing structure."""
        cases = {"agate_shopmenu_20260915.bin": 0x80479200,
                 "reboot_shopmenu_20260915.bin": 0x80479200,
                 "gateon_indoors.bin": 0x804792A0}
        checked = 0
        for name, block_base in cases.items():
            memory = self._dump(name)
            if memory is None:
                continue
            checked += 1
            rows = self._scan(memory, block_base)
            self.assertTrue([r for r in rows if r[0] <= 8], f"{name}: boxes 1-8 decoded nothing -- the block "
                                                            "base is probably wrong, so this proves nothing")
            self.assertEqual([r for r in rows if r[0] > 8], [], name)
        if not checked:
            self.skipTest("no MEM1 dumps available")


class TestTheNicknameGapInTheSaveBlockScan(unittest.TestCase):
    """A SECOND FINDING OF THIS PASS, recorded rather than fixed.

    Both save-block halves resolve a Pokemon by NAME TEXT -- `read_box_slot_species_by_name` and
    `read_party_recap_species` -- because each record's own numeric species field is documented in this module
    as unreliable for a recently-deposited slot. A nickname resolves to no species, and both correctly return
    None for it.

    The consequence: a NICKNAMED Pokemon that lives only in the PC is invisible to the save-block scan. The
    live-party path is not affected (it reads `national_dex`, a number), so in ordinary play the Pokemon was
    seen while it was in the party and its check already fired. The gap is narrow and real: nickname a
    Pokemon, box it, and reconnect -- the priming scan cannot see it, and its catch check waits until it next
    enters the party.

    Not fixed here because the fix is a numeric fallback on a field this project has documented as unreliable,
    and a WRONG species would be an unrecoverable false catch. Pinned so the behaviour is a known one."""

    def test_a_nicknamed_slot_resolves_to_no_species(self) -> None:
        self.assertIsNone(rc.species_dex_from_name("SPARKY"))
        self.assertIsNotNone(rc.species_dex_from_name("PIKACHU"))

    def test_the_live_party_path_is_numeric_and_survives_a_rename(self) -> None:
        """Why the gap does not bite in ordinary play: PARTY_BASE members carry a dex NUMBER."""
        import inspect
        source = inspect.getsource(rc.get_owned_species_snapshot)
        self.assertIn("national_dex", source)


class TestThePurificationGateIsActuallyWired(unittest.TestCase):
    """ADDENDUM 236's in-battle gate is only worth anything if the caller ever sets the flag. A gate whose
    argument is always False is a comment."""

    def test_the_client_feeds_it_a_real_battle_signal(self) -> None:
        import pathlib
        source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        self.assertIn("in_battle = ctx.trainer_defeat_tracker.has_unresolved_battle()", source)
        self.assertIn("ctx.block_base, ram_client.PARTY_BASE, in_battle=in_battle", source)

    def test_the_three_diagnostic_counters_are_printed(self) -> None:
        """ADDENDUM 236b caught the write-up claiming these were printed when they were not. Each one is a
        CLAIM about live behaviour, and a counter nobody can read falsifies nothing."""
        import inspect
        source = inspect.getsource(rc.PurificationCountTracker.describe)
        for counter in ("mismatched_recap_pairings", "party_changes_seen", "battle_polls_skipped"):
            self.assertIn(counter, source)

    def test_only_the_measured_flag_value_fires(self) -> None:
        self.assertEqual(rc.PURIFIED_FLAG_VALUE, 64)

    def test_the_battle_gate_has_a_ceiling(self) -> None:
        """`has_unresolved_battle()` has a documented history of sticking True. A suppression that never ends
        is the same class of failure as blocking delivery."""
        self.assertGreater(rc.NamedPurificationTracker.MAX_CONSECUTIVE_BATTLE_SKIPS, 0)
        self.assertLessEqual(rc.NamedPurificationTracker.MAX_CONSECUTIVE_BATTLE_SKIPS, 2000)


if __name__ == "__main__":
    unittest.main()
