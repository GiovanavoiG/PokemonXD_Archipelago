"""ADDENDUM 351 (2026-09-25): Death Link, and the only white-out this game has.

Player: "I want it for deathlink to force out a whiteout." Then, having been shown that a white-out is only
reachable by losing a battle: "Implement option 1. Make deathlink an option in the yaml. Send it whenever we
whiteout, but don't start a loop."

WHY IT CANNOT BE INSTANT, restated here because it is the constraint the whole design sits on.
`fightEncountCheckZenmetu` (main.dol 0x801F0D9C) is the entire white-out -- heal, money penalty, warp -- and
`fightMain` is its only caller. There is no overworld path to it. The overworld poison tick refuses to take
the last conscious party member below 1 HP on purpose, so poison cannot even wipe a party, let alone white
one out. So an incoming death writes 0 HP to the party and the GAME decides when that becomes a white-out.
"""
import struct
import unittest

from .. import ram_client as rc
from ..game_data import story_bytes as sb   # noqa: F401  (imported for the module-import fence below)


BLOCK = 0x80479680


class TestTheOffsetsAreTheDecompiledOnes(unittest.TestCase):
    """Every number here is a displacement in a one- or two-instruction accessor in main.dol (GXXE01).
    Pinned individually so a "tidy-up" cannot quietly move one."""

    def test_the_pokemon_class_layout(self):
        self.assertEqual(0x00, rc.POKEMON_DATA_ID_OFFSET)          # getPokemonDataId  lhz r3,0x00(r3)
        self.assertEqual(0x02, rc.POKEMON_HELD_ITEM_OFFSET)        # getItemDataId     lhz r3,0x02(r3)
        self.assertEqual(0x04, rc.POKEMON_HP_OFFSET)               # getHp             lhz r3,0x04(r3)
        self.assertEqual(0x06, rc.POKEMON_FRIEND_OFFSET)           # getFriendLevel    lhz r3,0x06(r3)
        self.assertEqual(0x11, rc.POKEMON_LEVEL_OFFSET)            # getLevel          lbz r3,0x11(r3)
        self.assertEqual(0x16, rc.POKEMON_CONDITION_OFFSET)        # getCondition      lbz r3,0x16(r3)
        self.assertEqual(0x17, rc.POKEMON_CONDITION_COUNT_OFFSET)
        self.assertEqual(0x18, rc.POKEMON_CONDITION_TURN_OFFSET)
        self.assertEqual(0x19, rc.POKEMON_CONDITION_TURN_NOW_OFFSET)
        self.assertEqual(0x20, rc.POKEMON_EXP_OFFSET)              # setExp            stw r4,0x20(r3)
        self.assertEqual(0x90, rc.POKEMON_MAXHP_OFFSET)            # getMaxHp          lhz r3,0x90(r3)
        self.assertEqual(0xBA, rc.POKEMON_SHADOW_ID_OFFSET)

    def test_the_party_address_is_heroBiosGetPokemonPtrs_own_arithmetic(self):
        """`hero + 0x30 + i * 0xC4`, with the Hero object 0x40 below the save block base."""
        self.assertEqual(0xC4, rc.POKEMON_STRIDE)
        self.assertEqual(6, rc.POKEMON_SLOTS)
        for index in range(6):
            self.assertEqual(BLOCK - 0x10 + index * 0xC4, rc.party_slot_address(BLOCK, index))

    def test_it_reconciles_with_the_recap_records_measured_offset(self):
        """The recap record's base (PARTY_RECAP_OFFSET, 0x3E) is 0x4E past where record 0 really starts, and
        PARTY_RECAP_MAXHP_OFFSET carries that error: 0x42 + 0x4E == 0x90, which is getMaxHp's displacement.
        That is the arithmetic that says the two describe the same structure, and it is why max HP always
        read correctly from the recap while its species field never did."""
        self.assertEqual(rc.POKEMON_MAXHP_OFFSET,
                         rc.PARTY_RECAP_MAXHP_OFFSET + (rc.PARTY_RECAP_OFFSET + 0x10))

    def test_poison_is_the_two_values_cbPoison_acts_on(self):
        """cbPoison (0x8014EBF8) compares the condition against 3 and 4 and against nothing else. Which is
        which is deliberately NOT claimed here -- see the constant's own comment."""
        self.assertEqual({3, 4}, set(rc.POISON_CONDITIONS))


class TestTheNameCollisionStaysFixed(unittest.TestCase):
    """The live object is `LivePartyMember`. `PartyMember` was already the 48-byte display record's
    dataclass, and appending a second class by that name rebound it for the whole module and broke the
    purification tracker. Its tests caught it; this one keeps it caught."""

    def test_party_member_is_still_the_display_record(self):
        import dataclasses
        fields = {f.name for f in dataclasses.fields(rc.PartyMember)}
        self.assertIn("party_index", fields)
        self.assertIn("current_hp", fields)

    def test_the_live_object_has_its_own_name(self):
        import dataclasses
        fields = {f.name for f in dataclasses.fields(rc.LivePartyMember)}
        self.assertEqual({"index", "address", "raw"}, fields)


def _pokemon(data_id=133, level=50, hp=100, max_hp=100, condition=0):
    raw = bytearray(rc.POKEMON_STRIDE)
    struct.pack_into(">H", raw, rc.POKEMON_DATA_ID_OFFSET, data_id)
    struct.pack_into(">H", raw, rc.POKEMON_HP_OFFSET, hp)
    struct.pack_into(">H", raw, rc.POKEMON_MAXHP_OFFSET, max_hp)
    raw[rc.POKEMON_LEVEL_OFFSET] = level
    raw[rc.POKEMON_CONDITION_OFFSET] = condition
    return bytes(raw)


class _FakeParty:
    """Six party slots' worth of memory, addressed exactly as the client addresses them."""

    def __init__(self, members):
        self.cells = bytearray(rc.POKEMON_STRIDE * rc.POKEMON_SLOTS)
        for index, raw in enumerate(members):
            start = index * rc.POKEMON_STRIDE
            self.cells[start:start + rc.POKEMON_STRIDE] = raw
        self.writes = []

    def install(self, test):
        test.addCleanup(setattr, rc, "read_bytes", rc.read_bytes)
        test.addCleanup(setattr, rc, "write_bytes", rc.write_bytes)
        rc.read_bytes = self._read
        rc.write_bytes = self._write

    def _index(self, address):
        return address - rc.party_slot_address(BLOCK, 0)

    def _read(self, address, length):
        start = self._index(address)
        if start < 0 or start + length > len(self.cells):
            raise ValueError("outside the party this fake models")
        return bytes(self.cells[start:start + length])

    def _write(self, address, data):
        start = self._index(address)
        self.cells[start:start + len(data)] = data
        self.writes.append((address, bytes(data)))

    def hp(self, index):
        start = index * rc.POKEMON_STRIDE + rc.POKEMON_HP_OFFSET
        return struct.unpack_from(">H", self.cells, start)[0]


class TestReadingTheParty(unittest.TestCase):
    def test_it_returns_only_occupied_slots(self):
        party = _FakeParty([_pokemon(), _pokemon(data_id=197, level=11, hp=44, max_hp=44)])
        party.install(self)
        members = rc.read_party(BLOCK)
        self.assertEqual([0, 1], [m.index for m in members])
        self.assertEqual([133, 197], [m.data_id for m in members])
        self.assertEqual([100, 44], [m.hp for m in members])

    def test_an_empty_party_reads_as_none_rather_than_wiped(self):
        """The distinction Death Link's sender rests on: "I cannot see your party" must never mean "your
        party is dead", or opening the PC would fire a death at everyone."""
        party = _FakeParty([])
        party.install(self)
        self.assertEqual([], rc.read_party(BLOCK))
        self.assertIsNone(rc.party_is_wiped(BLOCK))

    def test_a_zeroed_party_reads_as_wiped(self):
        party = _FakeParty([_pokemon(hp=0), _pokemon(data_id=197, hp=0, max_hp=44)])
        party.install(self)
        self.assertTrue(rc.party_is_wiped(BLOCK))

    def test_one_survivor_is_not_a_wipe(self):
        party = _FakeParty([_pokemon(hp=0), _pokemon(data_id=197, hp=1, max_hp=44)])
        party.install(self)
        self.assertFalse(rc.party_is_wiped(BLOCK))

    def test_poisoned_is_reported_off_the_condition_byte(self):
        party = _FakeParty([_pokemon(condition=3), _pokemon(data_id=197, condition=0)])
        party.install(self)
        members = rc.read_party(BLOCK)
        self.assertTrue(members[0].poisoned)
        self.assertFalse(members[1].poisoned)


class TestWiping(unittest.TestCase):
    def test_it_zeroes_every_occupied_slot(self):
        party = _FakeParty([_pokemon(), _pokemon(data_id=197, hp=44, max_hp=44), _pokemon(data_id=375)])
        party.install(self)
        self.assertEqual(3, rc.wipe_party(BLOCK))
        self.assertEqual([0, 0, 0], [party.hp(i) for i in range(3)])

    def test_it_writes_only_the_hp_field(self):
        party = _FakeParty([_pokemon()])
        party.install(self)
        rc.wipe_party(BLOCK)
        self.assertEqual(1, len(party.writes))
        address, data = party.writes[0]
        self.assertEqual(rc.party_slot_address(BLOCK, 0) + rc.POKEMON_HP_OFFSET, address)
        self.assertEqual(b"\x00\x00", data)

    def test_it_leaves_status_alone(self):
        """Deliberate. A faint clears status in the game's own code, and writing a condition value this
        project cannot yet name is how you find out it meant something else."""
        party = _FakeParty([_pokemon(condition=3)])
        party.install(self)
        rc.wipe_party(BLOCK)
        self.assertEqual(3, rc.read_party(BLOCK)[0].condition)

    def test_an_already_dead_slot_is_not_rewritten(self):
        party = _FakeParty([_pokemon(hp=0), _pokemon(data_id=197, hp=44, max_hp=44)])
        party.install(self)
        self.assertEqual(1, rc.wipe_party(BLOCK))


class TestTheBridge(unittest.TestCase):
    def setUp(self):
        self.party = _FakeParty([_pokemon(), _pokemon(data_id=197, hp=44, max_hp=44)])
        self.party.install(self)
        self.bridge = rc.DeathLinkBridge(enabled=True)

    def test_it_does_nothing_at_all_when_the_option_is_off(self):
        off = rc.DeathLinkBridge()
        self.assertIsNone(off.receive(BLOCK, "x"))
        self.assertEqual((False, None), off.poll(BLOCK))
        self.assertEqual([], self.party.writes)

    def test_a_received_death_wipes_the_party(self):
        note = self.bridge.receive(BLOCK, "Bob fell in a hole")
        self.assertIsNotNone(note)
        self.assertIn("Bob fell in a hole", note)
        self.assertEqual([0, 0], [self.party.hp(i) for i in range(2)])
        self.assertEqual(1, self.bridge.receipts)

    def test_our_own_wipe_is_never_re_broadcast(self):
        """The loop, which is the whole design problem. Player: "don't start a loop.\""""
        self.bridge.receive(BLOCK, "Bob")
        for _ in range(5):
            self.assertEqual((False, None), self.bridge.poll(BLOCK))
        self.assertEqual(0, self.bridge.sends)
        self.assertEqual(1, self.bridge.suppressed)

    def test_the_players_own_wipe_sends_exactly_one_death(self):
        for index in range(2):
            start = index * rc.POKEMON_STRIDE + rc.POKEMON_HP_OFFSET
            struct.pack_into(">H", self.party.cells, start, 0)
        should_send, note = self.bridge.poll(BLOCK)
        self.assertTrue(should_send)
        self.assertIn("whited out", note)
        for _ in range(5):
            self.assertEqual((False, None), self.bridge.poll(BLOCK))
        self.assertEqual(1, self.bridge.sends)

    def test_the_fence_comes_down_once_the_white_out_has_healed_them(self):
        """`fightEncountAnnihilationRecovery` heals the party as part of the white-out, so a conscious party
        is the signal that the previous wipe is finished and the next one is a new event."""
        self.bridge.receive(BLOCK, "Bob")
        self.assertEqual((False, None), self.bridge.poll(BLOCK))       # ours, suppressed
        struct.pack_into(">H", self.party.cells, rc.POKEMON_HP_OFFSET, 100)   # healed
        self.assertEqual((False, None), self.bridge.poll(BLOCK))
        for index in range(2):                                          # and now a real, own wipe
            start = index * rc.POKEMON_STRIDE + rc.POKEMON_HP_OFFSET
            struct.pack_into(">H", self.party.cells, start, 0)
        should_send, _ = self.bridge.poll(BLOCK)
        self.assertTrue(should_send)
        self.assertEqual(1, self.bridge.sends)
        self.assertEqual(1, self.bridge.suppressed)

    # ========================================================================================================
    # ADDENDUM 366 (2026-09-26): the gap between the wipe and the white-out
    # ========================================================================================================
    # Player, checking rather than reporting: "if we get sent a deathlink, and auto-white-out in the next
    # battle, we will NOT send a deathlink, correct? Verify."
    #
    # WHY THE EXISTING TESTS DID NOT ANSWER IT. `test_our_own_wipe_is_never_re_broadcast` polls five times
    # straight after the receive, which models a white-out that resolves immediately. The real sequence does
    # not: `wipe_party` sets the party to 0 HP and the note says so out loud -- "the white-out lands when the
    # game next resolves a battle" -- so the player can walk around, open menus, ride the scooter and save,
    # for hundreds of polls, before the battle that actually triggers `fightEncountAnnihilationRecovery`.
    #
    # The fence has to survive all of it. These pin the three ways it could have failed to.
    def test_the_fence_survives_the_whole_walk_to_the_next_battle(self) -> None:
        """A received death, then two hundred polls of walking around at 0 HP, then the battle resolves and
        heals them. Exactly one suppression, no sends, and the fence is down again afterwards."""
        self.bridge.receive(BLOCK, "someone else died")
        for _ in range(200):
            self.assertEqual((False, None), self.bridge.poll(BLOCK))
        self.assertEqual(0, self.bridge.sends)
        self.assertEqual(1, self.bridge.suppressed, "one wipe, counted once -- it is edge-triggered")

        struct.pack_into(">H", self.party.cells, rc.POKEMON_HP_OFFSET, 100)   # the white-out healed them
        self.assertEqual((False, None), self.bridge.poll(BLOCK))
        self.assertFalse(self.bridge._ours, "the fence must come down once they are conscious")
        self.assertEqual(0, self.bridge.sends)

    def test_an_unreadable_party_mid_gap_does_not_drop_the_fence(self) -> None:
        """The dangerous one. Opening the PC, a load and the first ticks after a reboot all read as "no
        party", and if that cleared `_ours` the white-out that follows would be sent as a fresh death --
        which is the loop, just with a delay in the middle.

        `party_is_wiped` answers None rather than False for exactly this reason, and `poll` returns on None
        without touching either flag."""
        self.bridge.receive(BLOCK, "someone else died")
        self.assertEqual((False, None), self.bridge.poll(BLOCK))

        original = rc.read_bytes
        self.addCleanup(setattr, rc, "read_bytes", original)
        rc.read_bytes = lambda address, length: b"\x00" * length    # an empty party: None, not False
        self.assertIsNone(rc.party_is_wiped(BLOCK))
        for _ in range(20):
            self.assertEqual((False, None), self.bridge.poll(BLOCK))
        self.assertTrue(self.bridge._ours, "an unreadable party is not evidence that they are conscious")

        rc.read_bytes = original                                      # party visible again, still wiped
        for _ in range(10):
            self.assertEqual((False, None), self.bridge.poll(BLOCK))
        self.assertEqual(0, self.bridge.sends)

    def test_healing_before_the_battle_re_arms_a_genuine_send(self) -> None:
        """The other side of the same rule, so the fence cannot be read as "never send after a receive". A
        player who revives someone at a Center has ended the wipe we caused; a white-out after that is their
        own and belongs in the pool."""
        self.bridge.receive(BLOCK, "someone else died")
        self.assertEqual((False, None), self.bridge.poll(BLOCK))
        struct.pack_into(">H", self.party.cells, rc.POKEMON_HP_OFFSET, 100)
        self.assertEqual((False, None), self.bridge.poll(BLOCK))

        for index in range(2):
            start = index * rc.POKEMON_STRIDE + rc.POKEMON_HP_OFFSET
            struct.pack_into(">H", self.party.cells, start, 0)
        should_send, _note = self.bridge.poll(BLOCK)
        self.assertTrue(should_send)
        self.assertEqual(1, self.bridge.sends)
        self.assertEqual(1, self.bridge.suppressed)

    def test_two_deaths_arriving_during_one_gap_still_send_nothing(self) -> None:
        """A busy pool. The second receive re-arms `_ours` over an already-set flag, which must not somehow
        leave an unfenced wipe behind it."""
        self.bridge.receive(BLOCK, "first")
        self.assertEqual((False, None), self.bridge.poll(BLOCK))
        self.bridge.receive(BLOCK, "second")
        for _ in range(50):
            self.assertEqual((False, None), self.bridge.poll(BLOCK))
        self.assertEqual(2, self.bridge.receipts)
        self.assertEqual(0, self.bridge.sends)

    def test_an_unreadable_party_sends_nothing(self):
        self.addCleanup(setattr, rc, "read_bytes", rc.read_bytes)

        def _raise(address, length):
            raise RuntimeError("not hooked")

        rc.read_bytes = _raise
        self.assertEqual((False, None), self.bridge.poll(BLOCK))
        self.assertEqual(0, self.bridge.sends)

    def test_no_block_base_sends_nothing_and_writes_nothing(self):
        self.assertEqual((False, None), self.bridge.poll(None))
        self.assertIsNone(self.bridge.receive(None, "x"))
        self.assertEqual([], self.party.writes)

    def test_it_never_raises(self):
        self.addCleanup(setattr, rc, "write_bytes", rc.write_bytes)

        def _raise(address, data):
            raise RuntimeError("write failed")

        rc.write_bytes = _raise
        self.assertIsNone(self.bridge.receive(BLOCK, "x"))


class TestTheOptionAndItsWiring(unittest.TestCase):
    def test_the_option_exists_and_is_off_by_default(self):
        from ..options import PokemonXDDeathLink, PokemonXDOptions
        self.assertIn("death_link", PokemonXDOptions.__annotations__)
        self.assertEqual(0, PokemonXDDeathLink.default)

    def test_it_is_sent_in_slot_data(self):
        import pathlib
        source = (pathlib.Path(__file__).resolve().parent.parent / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('"death_link"', source)

    def test_the_client_arms_the_tag_from_slot_data_and_defaults_off(self):
        import pathlib
        source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        self.assertIn('slot_data.get("death_link", False)', source,
                      "a seed generated before this key existed had no Death Link -- defaulting it ON would "
                      "start wiping a party the player never opted in to")
        self.assertIn("update_death_link", source, "the DeathLink tag must be set on the connection")

    def test_the_received_death_goes_through_commonclients_own_hook_first(self):
        """`super().on_deathlink(data)` is what stamps `last_death_link`, which is what stops our own
        `send_death` bouncing back and being treated as a new death."""
        import pathlib
        source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        index = source.index("def on_deathlink")
        body = source[index:index + 900]
        self.assertIn("super().on_deathlink(data)", body)
        self.assertLess(body.index("super().on_deathlink(data)"), body.index("death_link_bridge.receive"))
