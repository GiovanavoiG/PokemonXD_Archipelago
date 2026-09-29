"""ADDENDA 318/319 -- purifications are read from the party AND the PC, and Shadow species are never wild.

Player: "Some purifications aren't sending checks - also, the purification chamber doesn't send any checks when
a pokemon is purified. Can we add a purification check to our pc/party scan, still maintaining our species
clause, so that we're better at catching them?" ... "if we know a shadow pokemon exists in the seed, then
finding it as a normal pokemon anywhere will count as a purification." ... "Please make it so that shadow
pokemon and wild spot pokemon can never overlap for this reason."

THE OFFSETS HERE ARE MEASURED, against this project's own dumps: the Teddiursa purification bracket
(dump_pre/post_purify_teddiursa_20260903.bin) and the PC deposit (dump_post_teddiursa_pc_20260902.bin). Party
slot 2 read species 216 / shadow id 1 / flag 0 before and species 216 / shadow id 1 / flag 64 after; the
deposited Shadow read species 216 / shadow id 1 / flag 0 in box slot 0, which is what proves a box slot is the
same record shape as a party one. The fixtures below reproduce those three records byte for byte."""
import random
import struct
import unittest
from unittest import mock

from . import PokemonXDTestBase
from .. import ram_client as rc
from ..game_data.pokespot_data import assign_pokespot_species

TEDDIURSA_INTERNAL = 216
TEDDIURSA_DEX = 216
EEVEE_INTERNAL = 133


def _record(species: int, level: int = 11, shadow_id: int = 0, purified: int = 0) -> bytes:
    data = bytearray(0xC4)
    struct.pack_into(">H", data, rc.RECORD_SPECIES_OFFSET, species)
    data[rc.RECORD_LEVEL_OFFSET] = level
    struct.pack_into(">H", data, rc.RECORD_SHADOW_ID_OFFSET, shadow_id)
    struct.pack_into(">H", data, rc.RECORD_PURIFIED_FLAG_OFFSET, purified)
    # ADDENDUM 328: a real record agrees with itself across these too.
    struct.pack_into(">H", data, rc.RECORD_CURRENT_HP_OFFSET, 20)
    struct.pack_into(">H", data, rc.RECORD_MAX_HP_OFFSET, 34)
    struct.pack_into(">I", data, rc.RECORD_TRAINER_ID_OFFSET, 0xF9AFB2B3)
    struct.pack_into(">I", data, rc.RECORD_PID_OFFSET, 0x41882587)
    return bytes(data)


class TestTheRecordFields(unittest.TestCase):
    def test_the_anchor_relationship_is_the_one_the_old_constants_use(self) -> None:
        self.assertEqual(rc.PARTY_RECAP_PURIFIED_FLAG_OFFSET,
                         rc.RECORD_PURIFIED_FLAG_OFFSET - rc.RECORD_TEXT_ANCHOR_OFFSET)

    def test_a_purified_shadow(self) -> None:
        record = rc.ShadowRecord("party", 2, TEDDIURSA_DEX, shadow_id=1, purified_flag=rc.PURIFIED_FLAG_VALUE)
        self.assertTrue(record.was_snagged_as_shadow)
        self.assertTrue(record.is_purified)

    def test_an_unpurified_shadow_in_the_pc(self) -> None:
        """The deposited Teddiursa. Shadow id 1, flag 0 -- must NEVER count."""
        record = rc.ShadowRecord("box", 0, TEDDIURSA_DEX, shadow_id=1, purified_flag=0)
        self.assertTrue(record.was_snagged_as_shadow)
        self.assertFalse(record.is_purified)

    def test_the_shadow_id_survives_purification_so_it_is_not_the_state(self) -> None:
        """Measured: the id stayed 1 across the purification. Testing it for purity would count nothing."""
        record = rc.ShadowRecord("party", 2, TEDDIURSA_DEX, shadow_id=1, purified_flag=rc.PURIFIED_FLAG_VALUE)
        self.assertNotEqual(0, record.shadow_id)

    def test_an_unrecognised_flag_value_is_not_purified(self) -> None:
        """ADDENDUM 232's rule, restated for the new reader: only the measured value counts."""
        for value in (1, 2, 32, 63, 65, 128):
            record = rc.ShadowRecord("party", 0, TEDDIURSA_DEX, shadow_id=1, purified_flag=value)
            self.assertFalse(record.is_purified, value)


class TestTheScan(unittest.TestCase):
    def _scan(self, party: "dict[int, bytes]", boxes: "dict[int, bytes]"):
        block = 0x80479000

        def fake_read(address: int, length: int) -> bytes:
            for slot, blob in party.items():
                if address == rc.party_record_address(block, slot):
                    return blob
            for slot, blob in boxes.items():
                if address == rc.box_record_address(block, slot):
                    return blob
            return bytes(0xC4)

        with mock.patch.object(rc, "read_bytes", side_effect=fake_read):
            return rc.scan_shadow_records(block, box_slots=sorted(boxes))

    def test_the_party_and_the_pc_are_both_read(self) -> None:
        records = self._scan(
            {0: _record(EEVEE_INTERNAL)},
            {0: _record(TEDDIURSA_INTERNAL, shadow_id=1, purified=rc.PURIFIED_FLAG_VALUE)},
        )
        self.assertEqual({"party", "box"}, {r.source for r in records})
        purified = [r for r in records if r.is_purified]
        self.assertEqual(1, len(purified))
        self.assertEqual("box", purified[0].source)

    def test_empty_slots_are_skipped(self) -> None:
        self.assertEqual([], self._scan({}, {}))


class TestTheLedgerAndTheRules(unittest.TestCase):
    """RETARGETED (ADDENDUM 320): records now carry a level and a PID, and a count needs the second look
    guard 4 asks for. Both are deliberate -- see TestTheShadowIdLedgerAndItsGuards below -- so these call
    through a helper that scans twice rather than asserting the old single-scan behaviour."""

    def setUp(self) -> None:
        self.tracker = rc.PurificationCountTracker()

    @staticmethod
    def _rec(source, slot, dex, shadow_id, flag, pid=0x11111111):
        # ADDENDUM 328: records carry HP now, and a record that does not look like a Pokemon is refused
        # before either rule -- so the fixtures describe a real one.
        return rc.ShadowRecord(source, slot, dex, shadow_id, flag, 20, 0xF9AFB2B3, pid, 40, 60)

    def _settle(self, records, **kwargs):
        out = []
        for _ in range(rc.PURIFICATION_SCAN_CONFIRM_SCANS):
            out += self.tracker.observe_records(records, **kwargs)
        return out

    def test_rule_one_the_purified_flag(self) -> None:
        crossed = self._settle([self._rec("box", 3, TEDDIURSA_DEX, 1, rc.PURIFIED_FLAG_VALUE)])
        self.assertEqual([rc.purification_location_name(1)], crossed)
        self.assertEqual(1, self.tracker.total_purified)

    def test_rule_two_a_shadow_species_owned_as_an_ordinary_pokemon(self) -> None:
        """The player's own rule, and the one that catches a purification from before the client connected."""
        crossed = self._settle([self._rec("box", 3, TEDDIURSA_DEX, 0, 0),
                                self._rec("party", 0, 133, 0, 0)],
                               seed_shadow_dex={TEDDIURSA_DEX},
                               trusted_owned_dex={TEDDIURSA_DEX})
        self.assertEqual([rc.purification_location_name(1)], crossed)

    def test_an_unpurified_shadow_counts_nothing_under_either_rule(self) -> None:
        self.assertEqual([], self._settle([self._rec("box", 3, TEDDIURSA_DEX, 1, 0)],
                                          seed_shadow_dex={TEDDIURSA_DEX},
                                          trusted_owned_dex={TEDDIURSA_DEX}))
        self.assertEqual(0, self.tracker.total_purified)

    def test_a_species_that_is_not_a_shadow_this_seed_counts_nothing(self) -> None:
        self.assertEqual([], self._settle([self._rec("party", 0, 133, 0, 0)],
                                          seed_shadow_dex={TEDDIURSA_DEX},
                                          trusted_owned_dex={133, TEDDIURSA_DEX}))

    def test_the_species_clause_still_holds_across_both_rules(self) -> None:
        record = self._rec("party", 0, TEDDIURSA_DEX, 1, rc.PURIFIED_FLAG_VALUE)
        self.assertEqual(1, len(self._settle([record])))
        for _ in range(5):
            self.assertEqual([], self.tracker.observe_records([record]))
        self.assertEqual([], self._settle([self._rec("box", 9, TEDDIURSA_DEX, 0, 0),
                                           self._rec("party", 0, 133, 0, 0)],
                                          seed_shadow_dex={TEDDIURSA_DEX},
                                          trusted_owned_dex={TEDDIURSA_DEX}))
        self.assertEqual(1, self.tracker.total_purified)
        self.assertEqual(5 + 2, self.tracker.duplicate_species_rejected)

    def test_the_flip_watchers_ledger_is_shared(self) -> None:
        """A species the scan counted must not be counted again when the party flag flips, and vice versa."""
        self._settle([self._rec("box", 0, TEDDIURSA_DEX, 1, rc.PURIFIED_FLAG_VALUE)])
        self.assertIn(TEDDIURSA_DEX, self.tracker.purified_species)

    def test_the_ladder_caps_where_it_always_did(self) -> None:
        for dex in range(1, rc.PURIFICATION_LOCATION_COUNT + 5):
            self._settle([self._rec("party", 0, dex, dex, rc.PURIFIED_FLAG_VALUE, pid=dex)])
        self.assertEqual(rc.PURIFICATION_LOCATION_COUNT, self.tracker.total_purified)

    def test_it_is_reported(self) -> None:
        self._settle([self._rec("box", 0, TEDDIURSA_DEX, 1, rc.PURIFIED_FLAG_VALUE)])
        self.assertTrue(any("party/PC scan" in line for line in self.tracker.describe()))

    def test_the_ledger_survives_a_reconnect(self) -> None:
        self._settle([self._rec("box", 0, TEDDIURSA_DEX, 1, rc.PURIFIED_FLAG_VALUE)])
        fresh = rc.PurificationCountTracker()
        fresh.load_json(self.tracker.to_json())
        for _ in range(rc.PURIFICATION_SCAN_CONFIRM_SCANS):
            self.assertEqual([], fresh.observe_records(
                [self._rec("box", 0, TEDDIURSA_DEX, 1, rc.PURIFIED_FLAG_VALUE)]))


class TestPokeSpotsNeverOverlapShadows(unittest.TestCase):
    def test_no_overlap_across_many_seeds(self) -> None:
        shadow = set(range(1, 130))
        for seed in range(50):
            entries = assign_pokespot_species(shadow, random.Random(seed))
            self.assertEqual(11, len(entries))
            picked = {e["new_dex"] for e in entries}
            self.assertEqual(set(), picked & shadow, seed)
            self.assertEqual(11, len(picked), "the 11 slots must still be distinct species")

    def test_it_raises_rather_than_overlapping(self) -> None:
        """The old ladder relaxed into the obtainable set when candidates ran short. Now that would cost a
        wrong purification check, so it is a generation error instead."""
        everything = set(range(1, 387))
        with self.assertRaises(ValueError):
            assign_pokespot_species(everything, random.Random(1))


class TestTheShadowIdLedgerAndItsGuards(unittest.TestCase):
    """ADDENDUM 320. The Shadow id is the identity that survives evolution; five guards stand behind it.

    Measured (mem1_pre_eeveestone.bin / mem1_post_evolve.bin): evolving moved species 133 -> 135 while the PID
    held at CFFBB772 and the shadow id held at 0. Evolution moves the species and nothing else."""

    TOTODILE, CROCONAW = 158, 159
    PID = 0x41882587
    TRAINER = 0xF9AFB2B3

    def setUp(self) -> None:
        self.tracker = rc.PurificationCountTracker()

    def _record(self, dex, shadow_id=1, purified=rc.PURIFIED_FLAG_VALUE, pid=None, trainer=None, level=20,
                source="box", slot=0, max_hp=60, cur_hp=40):
        return rc.ShadowRecord(source, slot, dex, shadow_id, purified, level,
                               self.TRAINER if trainer is None else trainer,
                               self.PID if pid is None else pid, cur_hp, max_hp)

    def _settle(self, records, **kwargs):
        """Two scans -- guard 4 asks for a second look."""
        out = []
        for _ in range(rc.PURIFICATION_SCAN_CONFIRM_SCANS):
            out += self.tracker.observe_records(records, **kwargs)
        return out

    def test_an_evolved_purified_shadow_still_counts_once(self) -> None:
        crossed = self._settle([self._record(self.TOTODILE)])
        self.assertEqual([rc.purification_location_name(1)], crossed)
        # Same individual, evolved: new species, same shadow id and PID.
        self.assertEqual([], self._settle([self._record(self.CROCONAW)]))
        self.assertEqual(1, self.tracker.total_purified)
        self.assertIn(1, self.tracker.purified_shadow_ids)

    def test_a_species_that_will_not_resolve_is_refused_now(self) -> None:
        """RETARGETED (ADDENDUM 328). This used to assert the opposite -- with the shadow id as the key, a
        record whose species field did not convert could still be counted -- and that was the right call
        while the only records reaching here were real ones.

        The player's report settled it the other way: three purification checks before catching anything, off
        box slots of leftover bytes. A species field that does not convert is far more often a bad read than
        a rare Pokemon, and there are 360 box slots to be wrong about. So the species has to resolve, along
        with four other fields that a real record agrees with itself on. Under-counting a genuinely unreadable
        Pokemon is recoverable -- it is read again every second; a wrong check is not."""
        self.assertEqual([], self._settle([self._record(None)]))
        self.assertIn("record does not look like a real Pokemon", self.tracker.guard_rejections)

    def test_guard_1_implausible_level(self) -> None:
        """RETARGETED (ADDENDUM 328): an out-of-range level is now caught by the broader "is this a Pokemon
        at all" gate, which asks the same question of five fields at once."""
        self.assertEqual([], self._settle([self._record(self.TOTODILE, level=0)]))
        self.assertEqual([], self._settle([self._record(self.TOTODILE, level=200)]))
        self.assertIn("record does not look like a real Pokemon", self.tracker.guard_rejections)

    def test_guard_1_shadow_id_out_of_range(self) -> None:
        self.assertEqual([], self._settle([self._record(self.TOTODILE, shadow_id=0x4141)]))
        self.assertIn("shadow id out of range", self.tracker.guard_rejections)

    def test_guard_1_only_the_measured_flag_value(self) -> None:
        self.assertEqual([], self._settle([self._record(self.TOTODILE, purified=63)]))

    def test_guard_2_the_pid_cross_check(self) -> None:
        self._settle([self._record(self.TOTODILE)])
        self.assertEqual(self.PID, self.tracker.shadow_pids[1])
        # A different Pokemon claiming the same shadow id is a misread.
        self.assertEqual([], self._settle([self._record(300, shadow_id=1, pid=0xDEADBEEF)]))
        self.assertIn("PID disagrees with this Shadow id", self.tracker.guard_rejections)

    def test_guard_3_trainer_id_mismatch(self) -> None:
        records = [self._record(self.TOTODILE, shadow_id=1, slot=0),
                   self._record(300, shadow_id=2, slot=1, pid=0x11111111),
                   self._record(301, shadow_id=3, slot=2, pid=0x22222222, trainer=0x12345678)]
        self._settle(records)
        self.assertEqual(2, self.tracker.total_purified, "the two real ones counted")
        self.assertIn("trainer id mismatch", self.tracker.guard_rejections)

    def test_guard_3_is_off_when_it_cannot_be_established(self) -> None:
        """One record alone cannot vote on what the save's trainer id is, so the guard must not block it."""
        self.assertIsNone(rc.dominant_trainer_id([self._record(self.TOTODILE)]))
        self.assertEqual([rc.purification_location_name(1)], self._settle([self._record(self.TOTODILE)]))

    def test_guard_4_needs_a_second_look_but_never_drops_one(self) -> None:
        record = [self._record(self.TOTODILE)]
        self.assertEqual([], self.tracker.observe_records(record), "not on the first sighting")
        self.assertEqual([rc.purification_location_name(1)], self.tracker.observe_records(record))

    def test_guard_4_a_one_scan_flicker_never_accumulates(self) -> None:
        for _ in range(10):
            self.tracker.observe_records([self._record(self.TOTODILE)])
            self.tracker.observe_records([])   # gone again -- a misread, not a Pokemon
        # The first pair counts it (two consecutive scans is exactly the confirmation); after that the
        # alternating pattern must not keep adding.
        self.assertLessEqual(self.tracker.total_purified, 1)

    def test_guard_5_never_more_than_the_seed_has_shadows(self) -> None:
        for dex in range(1, 8):
            self._settle([self._record(dex, shadow_id=dex, pid=dex)], shadow_count_cap=3)
        self.assertEqual(3, self.tracker.total_purified)

    def test_the_ledgers_agree_after_an_older_state_file(self) -> None:
        """A species counted by the ADDENDUM 318 ledger must not be counted again under its shadow id."""
        self.tracker.load_json({"total_purified": 1, "purified_species": [self.TOTODILE]})
        self.assertEqual([], self._settle([self._record(self.TOTODILE)]))
        self.assertEqual(1, self.tracker.total_purified)
        self.assertIn(1, self.tracker.purified_shadow_ids, "the id is adopted so the two ledgers agree")

    def test_the_shadow_ledger_persists(self) -> None:
        self._settle([self._record(self.TOTODILE)])
        fresh = rc.PurificationCountTracker()
        fresh.load_json(self.tracker.to_json())
        self.assertEqual({1}, fresh.purified_shadow_ids)
        for _ in range(rc.PURIFICATION_SCAN_CONFIRM_SCANS):
            self.assertEqual([], fresh.observe_records([self._record(self.CROCONAW)]))

    def test_it_is_all_reported(self) -> None:
        self._settle([self._record(self.TOTODILE)])
        self._settle([self._record(self.TOTODILE, level=0)])
        text = "\n".join(self.tracker.describe())
        self.assertIn("Shadow ids counted", text)
        self.assertIn("scan guards rejected", text)


class TestRuleTwoDoesNotFireOnAGiftedSpecies(unittest.TestCase):
    """ADDENDUM 325 -- player: "My second purification sent two checks ... I only purified three pokemon, but
    the third one also sent the fourth check."

    Rule 2 reads "you own a Shadow species as an ordinary Pokemon" as proof of a purification. That holds only
    while such a species cannot be had another way. Two ways it can: this seed's Poke Spot species (forbidden
    at generation since ADDENDUM 319, but a seed made before it still has them) and the guaranteed Eevee plus
    its five evolutions, which every player is given."""

    EEVEE, VAPOREON, PHANPY = 133, 134, 231
    TRAINER = 0xF9AFB2B3

    def setUp(self) -> None:
        self.tracker = rc.PurificationCountTracker()

    def _ordinary(self, dex, slot=0):
        return rc.ShadowRecord("party", slot, dex, 0, 0, 20, self.TRAINER, 0xABCDEF01, 30, 45)

    def _settle(self, records, **kwargs):
        out = []
        for _ in range(rc.PURIFICATION_SCAN_CONFIRM_SCANS):
            out += self.tracker.observe_records(records, **kwargs)
        return out

    def test_the_gift_eevee_is_not_a_purification(self) -> None:
        crossed = self._settle([self._ordinary(self.EEVEE)], seed_shadow_dex={self.EEVEE},
                               obtainable_elsewhere_dex={self.EEVEE, self.VAPOREON},
                               trusted_owned_dex={self.EEVEE, self.VAPOREON, self.PHANPY, 300})
        self.assertEqual([], crossed)
        self.assertIn("a Shadow species this seed also gives out another way", self.tracker.guard_rejections)

    def test_nor_what_it_evolves_into(self) -> None:
        self.assertEqual([], self._settle([self._ordinary(self.VAPOREON)], seed_shadow_dex={self.VAPOREON},
                                          obtainable_elsewhere_dex={self.EEVEE, self.VAPOREON},
                                          trusted_owned_dex={self.VAPOREON}))

    def test_nor_a_poke_spot_species_in_an_older_seed(self) -> None:
        self.assertEqual([], self._settle([self._ordinary(self.PHANPY)], seed_shadow_dex={self.PHANPY},
                                          obtainable_elsewhere_dex={self.PHANPY},
                                          trusted_owned_dex={self.PHANPY}))

    def test_rule_two_still_works_for_a_shadow_only_species(self) -> None:
        crossed = self._settle([self._ordinary(300)], seed_shadow_dex={300},
                               obtainable_elsewhere_dex={self.EEVEE}, trusted_owned_dex={300})
        self.assertEqual([rc.purification_location_name(1)], crossed)

    def test_rule_one_is_untouched_by_the_exclusion(self) -> None:
        """A record that SAYS it was purified is a fact, not an inference -- the exclusion must not gag it."""
        record = rc.ShadowRecord("box", 2, self.EEVEE, 7, rc.PURIFIED_FLAG_VALUE, 20, self.TRAINER,
                                 0x1234, 30, 45)
        self.assertEqual([rc.purification_location_name(1)],
                         self._settle([record], seed_shadow_dex={self.EEVEE},
                                      obtainable_elsewhere_dex={self.EEVEE}))

    def test_each_count_says_where_it_came_from(self) -> None:
        self._settle([self._ordinary(300)], seed_shadow_dex={300}, trusted_owned_dex={300})
        self.assertTrue(self.tracker.last_counts)
        self.assertIn("species 300", self.tracker.last_counts[0])

    def test_the_audit_resets_between_scans(self) -> None:
        self._settle([self._ordinary(300)], seed_shadow_dex={300}, trusted_owned_dex={300})
        self.tracker.observe_records([], seed_shadow_dex={300})
        self.assertEqual([], self.tracker.last_counts)


class TestGenerationKeepsTheGiftLineOutOfTheShadowPool(PokemonXDTestBase):
    options = {"shadow_pokemon_expansion": 44, "randomize_shadow_species": True}

    def test_no_generated_shadow_is_the_gift_eevee_or_an_eeveelution(self) -> None:
        from ..tools.xd_species_index import national_dex_for
        from ..species import EEVEELUTION_DEX_NUMBERS

        world = self.multiworld.worlds[self.player]
        generated = {national_dex_for(mon["species"])
                     for plan in (world._shadow_expansion_plans or []) for mon in plan["new_pokemon"]}
        self.assertTrue(generated)
        self.assertEqual(set(), generated & ({133} | set(EEVEELUTION_DEX_NUMBERS)))


class TestJunkBoxSlotsAreNotPurifications(unittest.TestCase):
    """ADDENDUM 328 -- player report, relayed: "User reported getting 3 purify checks before even catching a
    pokemon", with `!purifications` showing all three counted by rule 2 for species 22, 25 and 71, and the
    level guard having rejected 76 records in the same session.

    The scan walks 360 box slots. On a fresh save almost none of them hold a record, and a slot of leftover
    bytes only has to land on a plausible level and a species number to look like a Pokemon."""

    TRAINER = 0xF9AFB2B3

    def setUp(self) -> None:
        self.tracker = rc.PurificationCountTracker()
        self.party = rc.ShadowRecord("party", 0, 133, 0, 0, 11, self.TRAINER, 0x11112222, 20, 34)

    def _settle(self, records, **kwargs):
        out = []
        for _ in range(rc.PURIFICATION_SCAN_CONFIRM_SCANS):
            out += self.tracker.observe_records(records, **kwargs)
        return out

    def _junk(self, dex, **fields):
        base = dict(shadow_id=0, purified_flag=0, level=37, trainer_id=0, pid=0, cur_hp=0, max_hp=0)
        base.update(fields)
        return rc.ShadowRecord("box", 44, dex, base["shadow_id"], base["purified_flag"], base["level"],
                               base["trainer_id"], base["pid"], base["cur_hp"], base["max_hp"])

    def test_the_three_species_from_the_report(self) -> None:
        junk = [self._junk(dex) for dex in (22, 25, 71)]
        crossed = self._settle([self.party] + junk, seed_shadow_dex={22, 25, 71},
                               trusted_owned_dex={22, 25, 71})
        self.assertEqual([], crossed)
        self.assertEqual(0, self.tracker.total_purified)

    def test_each_missing_field_alone_is_enough_to_refuse_it(self) -> None:
        for field in ("trainer_id", "pid", "max_hp"):
            tracker = rc.PurificationCountTracker()
            record = self._junk(300, trainer_id=self.TRAINER, pid=0x1234, cur_hp=10, max_hp=40)
            record = record._replace(**{field: 0}) if hasattr(record, "_replace") else record
            broken = rc.ShadowRecord("box", 44, 300, 0, 0, 37,
                                     0 if field == "trainer_id" else self.TRAINER,
                                     0 if field == "pid" else 0x1234,
                                     10, 0 if field == "max_hp" else 40)
            for _ in range(rc.PURIFICATION_SCAN_CONFIRM_SCANS):
                tracker.observe_records([self.party, broken], seed_shadow_dex={300},
                                        trusted_owned_dex={300})
            self.assertEqual(0, tracker.total_purified, field)

    def test_current_hp_above_max_is_not_a_pokemon(self) -> None:
        record = rc.ShadowRecord("box", 44, 300, 0, 0, 37, self.TRAINER, 0x1234, 900, 40)
        self._settle([self.party, record], seed_shadow_dex={300}, trusted_owned_dex={300})
        self.assertEqual(0, self.tracker.total_purified)

    def test_rule_two_needs_the_catch_scan_to_have_seen_the_species(self) -> None:
        real = rc.ShadowRecord("box", 3, 300, 0, 0, 25, self.TRAINER, 0x9999, 30, 50)
        self.assertEqual([], self._settle([self.party, real], seed_shadow_dex={300}, trusted_owned_dex=set()))
        self.assertIn("rule 2 without the catch scan having seen the player own that species",
                      self.tracker.guard_rejections)
        self.assertEqual([rc.purification_location_name(1)],
                         self._settle([self.party, real], seed_shadow_dex={300}, trusted_owned_dex={300}))

    def test_rule_two_needs_a_party_record_to_anchor_the_trainer_id(self) -> None:
        real = rc.ShadowRecord("box", 3, 300, 0, 0, 25, self.TRAINER, 0x9999, 30, 50)
        self.assertEqual([], self._settle([real], seed_shadow_dex={300}, trusted_owned_dex={300}))

    def test_the_trainer_id_comes_from_the_party_not_from_a_vote(self) -> None:
        """360 junk slots must not be able to outvote the one Pokemon the player actually has."""
        junk = [rc.ShadowRecord("box", i, 300, 0, 0, 30, 0xDEADBEEF, 0x1, 10, 20) for i in range(20)]
        self.assertEqual(self.TRAINER, rc.dominant_trainer_id([self.party] + junk))

    def test_a_real_purified_record_still_counts_among_the_junk(self) -> None:
        real = rc.ShadowRecord("box", 7, 300, 12, rc.PURIFIED_FLAG_VALUE, 30, self.TRAINER, 0xABCD, 44, 70)
        crossed = self._settle([self.party, real] + [self._junk(d) for d in (22, 25, 71)],
                               seed_shadow_dex={22, 25, 71, 300}, trusted_owned_dex={300})
        self.assertEqual([rc.purification_location_name(1)], crossed)
