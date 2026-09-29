"""ADDENDUM 393 (2026-09-29) -- a level-0 Pokemon is invisible to every live-party reader, and `!party` can now see one.

Player, on ADDENDUM 392: "Did you find the actual cause?" -- no -- then:
"I think it's likely that the pokemon has a level, but its in-battle struct isnt showing it."

Then, correctly: "That's party though, right? Not opponent wild pokemon" / "or is that our code for checking
things".

BOTH CORRECTIONS ARE RIGHT, so what this addendum is has to be said plainly. It does NOT explain the in-battle
display. A wild opponent is not in the party: it lives in the battle-roster struct this file locates by
signature scan, and the only fields this project has ever mapped there are the trainer's surname, the species
name twice, and current HP at -0x2c. There is no level field in it, read or written, so the number on the HUD
is the game reading its own struct and is not something this client touches.

What this addendum fixes is a SEPARATE, real bug on the near side of the same report: once such a Pokemon is
CAUGHT, every live-party reader here goes blind to it.

The player's hypothesis still makes a prediction worth testing, and it costs nothing: if the level is real and
only the HUD is wrong, the Pokemon FIGHTS at its real level -- HP bar, damage, and the experience it yields are
all level-appropriate, and it arrives in the party at the right level.

WHAT CHECKING IT TURNED UP. Nothing could check the party side either. `!party` reported species and nothing else, so
`describe_live_party` was added to print level, experience and HP from the live records -- and on the first
probe it showed only ONE of three planted slots.

`LivePartyMember.occupied` requires `1 <= level <= 100`. So a level-0 Pokemon is rejected by the one predicate
every live-party reader in this project goes through:

    read_party -> occupied          the only place `occupied` is called
    party_is_wiped -> read_party    Death Link's detector
    wipe_party -> read_party        Death Link's writer
    get_live_party_species_snapshot -> read_party    the catch tracker's first witness

The instrument that would have seen this bug was refusing to see it, which is a fair explanation for why three
rounds of investigation found nothing. `describe_live_party` therefore reads the six slots RAW and reports which
ones `occupied` rejects, rather than asking it.

WHAT IS NOT CHANGED, and why. `occupied` keeps its bound. Its docstring gives the reason -- "Death Link writes
off this, and writing a slot that only looks occupied would be writing into whatever else lives at that
address" -- and loosening a predicate that guards a WRITE is a separate decision from making a diagnostic able
to read. The catch tracker is also not left blind by it: `check_catches` unions
`get_owned_species_snapshot(PARTY_BASE)` as a second witness, and the display cache has no level bound.

The three shapes this distinguishes, once the Pokemon is in the party:

    level sane, exp sane   ->  the battle HUD was lying. Cosmetic, and nothing this project writes.
    level 0,    exp sane   ->  the level field is derived wrongly from experience.
    level 0,    exp 0      ->  it really was built at level 0, upstream of the HUD.
"""
from __future__ import annotations

import pathlib
import struct
import unittest

from .. import ram_client as rc

BLOCK = 0x80500000


class _FakeParty:
    """Six raw `Pokemon` records, planted slot by slot."""

    def __init__(self) -> None:
        self.raw = bytearray(rc.POKEMON_STRIDE * rc.POKEMON_SLOTS)

    def put(self, slot: int, species: int, level: int, exp: int, hp: int, max_hp: int) -> None:
        base = slot * rc.POKEMON_STRIDE
        struct.pack_into(">H", self.raw, base + rc.POKEMON_DATA_ID_OFFSET, species)
        self.raw[base + rc.POKEMON_LEVEL_OFFSET] = level
        struct.pack_into(">I", self.raw, base + rc.POKEMON_EXP_OFFSET, exp)
        struct.pack_into(">H", self.raw, base + rc.POKEMON_HP_OFFSET, hp)
        struct.pack_into(">H", self.raw, base + rc.POKEMON_MAXHP_OFFSET, max_hp)

    def read(self, address: int, length: int) -> bytes:
        offset = address - rc.party_slot_address(BLOCK, 0)
        if offset < 0:
            return b"\x00" * length
        return bytes(self.raw[offset:offset + length]).ljust(length, b"\x00")


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        self.party = _FakeParty()
        self.saved = rc.read_bytes
        rc.read_bytes = self.party.read

    def tearDown(self) -> None:
        rc.read_bytes = self.saved


class TestTheFieldIsReadable(_Case):
    def test_experience_comes_off_the_live_record(self) -> None:
        self.party.put(0, 27, 14, 2744, 40, 40)
        member = rc.read_party(BLOCK)[0]
        self.assertEqual(2744, member.experience)
        self.assertEqual(14, member.level)

    def test_it_is_the_field_setExp_writes(self) -> None:
        self.assertEqual(0x20, rc.POKEMON_EXP_OFFSET)

    def test_a_full_u32_round_trips(self) -> None:
        self.party.put(0, 27, 100, 1_640_000, 300, 300)
        self.assertEqual(1_640_000, rc.read_party(BLOCK)[0].experience)


class TestALevelZeroPokemonIsInvisibleToEveryReader(_Case):
    """The finding. Each of these is a real consequence, not a restatement of one."""

    def setUp(self) -> None:
        super().setUp()
        self.party.put(0, 385, 0, 1000, 22, 22)   # a level-0 Pokemon, otherwise entirely plausible

    def test_occupied_rejects_it(self) -> None:
        member = rc.LivePartyMember(index=0, address=rc.party_slot_address(BLOCK, 0),
                                    raw=self.party.read(rc.party_slot_address(BLOCK, 0), rc.POKEMON_STRIDE))
        self.assertTrue(member.data_id)
        self.assertEqual(0, member.level)
        self.assertFalse(member.occupied, "the bound that hides it is `1 <= level`")

    def test_read_party_does_not_return_it(self) -> None:
        self.assertEqual([], rc.read_party(BLOCK))

    def test_death_link_cannot_see_it(self) -> None:
        """`party_is_wiped` returns None for an "empty" party, so Death Link neither detects nor wipes it."""
        self.assertIsNone(rc.party_is_wiped(BLOCK))
        self.assertEqual(0, rc.wipe_party(BLOCK))

    def test_the_catch_snapshot_misses_it(self) -> None:
        """Not fatal -- `check_catches` unions the PARTY_BASE display cache, which has no level bound -- but
        this witness alone would lose the check."""
        self.assertEqual(set(), rc.get_live_party_species_snapshot(BLOCK))

    def test_one_level_higher_and_everything_sees_it(self) -> None:
        """ADDENDA 247/298: prove the bound is what does it, not something else about the record."""
        self.party.put(0, 385, 1, 1000, 22, 22)
        self.assertEqual(1, len(rc.read_party(BLOCK)))
        self.assertIs(False, rc.party_is_wiped(BLOCK))


class TestTheDiagnosticSeesItAnyway(_Case):
    def setUp(self) -> None:
        super().setUp()
        self.party.put(0, 27, 14, 2744, 40, 40)      # healthy
        self.party.put(1, 385, 0, 1000, 22, 22)      # level 0, experience sane
        self.party.put(2, 41, 0, 0, 1, 1)            # level 0, experience 0

    def _text(self) -> str:
        return "\n".join(rc.describe_live_party(BLOCK))

    def test_every_planted_slot_appears(self) -> None:
        text = self._text()
        for name in ("Sandshrew", "Castform", "Zubat"):
            self.assertIn(name, text, name)

    def test_it_does_not_route_through_read_party(self) -> None:
        """The bug in the instrument. If it asked `read_party`, two of the three slots would vanish."""
        self.assertEqual(1, len(rc.read_party(BLOCK)), "read_party still only sees the healthy one")
        self.assertEqual(3, self._text().count("slot "))

    def test_it_prints_level_and_experience(self) -> None:
        text = self._text()
        self.assertIn("Lv 14, exp 2744", text)
        self.assertIn("Lv 0, exp 1000", text)
        self.assertIn("Lv 0, exp 0", text)

    def test_it_flags_the_level_zero_slots(self) -> None:
        self.assertEqual(2, self._text().count("LEVEL 0"))

    def test_it_says_the_other_readers_skip_them(self) -> None:
        self.assertEqual(2, self._text().count("rejected by `occupied`"))

    def test_an_empty_party_says_so_rather_than_looking_broken(self) -> None:
        self.party.raw[:] = bytearray(len(self.party.raw))
        self.assertIn("no slot holds a species", self._text())

    def test_a_healthy_party_carries_no_warning(self) -> None:
        self.party.raw[:] = bytearray(len(self.party.raw))
        self.party.put(0, 27, 14, 2744, 40, 40)
        text = self._text()
        self.assertNotIn("LEVEL 0", text)
        self.assertNotIn("rejected", text)


class TestOccupiedIsDeliberatelyUnchanged(unittest.TestCase):
    def test_the_bound_is_still_there(self) -> None:
        """Loosening a predicate that guards a WRITE is a separate decision from letting a diagnostic read."""
        source = (pathlib.Path(__file__).resolve().parent.parent / "ram_client.py").read_text(encoding="utf-8")
        self.assertIn("and 1 <= self.level <= 100", source)

    def test_the_command_reports_it(self) -> None:
        source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        start = source.index("def _cmd_party(")
        body = source[start:start + 900]
        self.assertIn("describe_live_party", body)
        self.assertIn("describe_party_sources", body, "both sources still print")


if __name__ == "__main__":
    unittest.main()
