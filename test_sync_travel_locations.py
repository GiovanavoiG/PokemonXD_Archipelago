"""Regression coverage for the "Randomize Travel Locations" live-RAM bit-flip logic (ADDENDUM 104).

WHY THIS DOES NOT IMPORT `Client.py` DIRECTLY: confirmed this session that `Client.py` cannot be imported at
all in this sandbox, independent of anything ADDENDUM 104 changed -- `Client.py` -> `CommonClient` ->
`MultiServer` -> `websockets.extensions` (`ModuleNotFoundError: No module named 'websockets.extensions';
'websockets' is not a package`). This matches this project's own already-documented lesson (see ADDENDUM 103's
verification notes): never import `Client.py` directly in this sandbox; verify its logic some other way. This
file instead:
  1. Fully exercises `travel_locations.py`'s actual live-memory-touching functions
     (`write_travel_location_bit`/`read_travel_location_unlocked`) against a fake in-process memory backend --
     the same functions `Client.py`'s `sync_travel_locations` calls, so this covers the one part of the
     mechanism with real correctness risk (OR-not-overwrite byte sharing, exact bit math per the ADDENDUM 91
     master table).
  2. A structural sanity check on `Client.py`'s own source text confirming `sync_travel_locations` exists, is
     wired into the poll loop, and touches the specific pieces of state (`received_travel_locations`,
     `_travel_bits_applied_for_block_base`) the reconnect/retry design (ADDENDUM 104) depends on -- catching a
     gross wiring mistake (forgotten call, renamed attribute) even though it can't exercise the async logic
     end-to-end in this sandbox. A real end-to-end confirmation of the reconnect/retry behavior still needs a
     live Dolphin session, same disclosed limitation as every other live-RAM mechanism in this project."""
from __future__ import annotations

import os
import sys
import types
import unittest
import unittest.mock

if "dolphin_memory_engine" not in sys.modules:
    _stub = types.ModuleType("dolphin_memory_engine")
    _stub.hook = lambda: None
    _stub.un_hook = lambda: None
    _stub.is_hooked = lambda: False
    _stub.read_bytes = lambda address, length: b""
    _stub.write_bytes = lambda address, data: None
    sys.modules["dolphin_memory_engine"] = _stub

from .. import ram_client, travel_locations


class _FakeMemory:
    """A tiny in-process stand-in for live Dolphin memory: a dict of address -> single byte, defaulting to
    0x00 for any address never explicitly written."""

    def __init__(self) -> None:
        self.data: dict[int, int] = {}

    def read_bytes(self, address: int, length: int) -> bytes:
        return bytes(self.data.get(address + i, 0) for i in range(length))

    def write_bytes(self, address: int, data: bytes) -> None:
        for i, b in enumerate(data):
            self.data[address + i] = b


class TestTravelLocationBitData(unittest.TestCase):
    def test_target_region_covers_exactly_the_unlock_names(self) -> None:
        """ADDENDUM 177: the two tables are no longer the same set. TRAVEL_LOCATION_BITS is the PHYSICAL layer
        (one entry per destination, each with its own bit) and TRAVEL_LOCATION_NAMES is what the multiworld
        deals in (the Poke Spots collapse into one). The target-region map belongs to the second, because it is
        what the gateway loop iterates."""
        self.assertEqual(set(travel_locations.TRAVEL_LOCATION_NAMES),
                         set(travel_locations.TRAVEL_LOCATION_TARGET_REGION))
        # Every grouped member still has its own bit, and no group name pretends to have one.
        for group, members in travel_locations.TRAVEL_UNLOCK_MEMBERS.items():
            self.assertNotIn(group, travel_locations.TRAVEL_LOCATION_BITS)
            for member in members:
                self.assertIn(member, travel_locations.TRAVEL_LOCATION_BITS)

    def test_item_name_round_trips(self) -> None:
        for name in travel_locations.TRAVEL_LOCATION_NAMES:
            item_name = travel_locations.travel_unlock_item_name(name)
            self.assertEqual(travel_locations.travel_location_name_from_item(item_name), name)

    def test_non_travel_item_name_returns_none(self) -> None:
        self.assertIsNone(travel_locations.travel_location_name_from_item("Krane Memo 1"))
        self.assertIsNone(travel_locations.travel_location_name_from_item("Travel Unlock - Not A Real Place"))

    def test_the_under_has_no_bit_entry(self) -> None:
        # Player correction, 2026-09-09: "The Under" is not a real, reachable area in this game.
        for name in travel_locations.TRAVEL_LOCATION_NAMES:
            self.assertNotIn("under", name.lower())

    def test_always_open_locations_are_never_randomizable(self) -> None:
        # ADDENDUM 106 (2026-09-10, player request: "the only locations I want open by default are Kaminko,
        # Gateon, Agate and Pokemon HQ Lab") -- none of the four should ever be a "Travel Unlock - " item.
        # "Kaminko" here is Kaminko Mansion (Chobin's intro battle), NOT the late-game "Kaminko's House" travel
        # destination -- those are two distinct real locations (see travel_locations.py's own docstring).
        for name in ("Kaminko Mansion", "Gateon Port", "Agate Village"):
            self.assertNotIn(name, travel_locations.TRAVEL_LOCATION_NAMES)
        # UPDATED 2026-09-25 (ADDENDUM 356). "Kaminko's House" (late-game, distinct from Kaminko Mansion) used
        # to remain a real item-gated destination. It is retired: being always open, its item gated nothing --
        # its region kept an unconditional chain edge, so holding the item changed no location's reachability.
        # So the rule this test states now covers all four names the player gave rather than three of them.
        self.assertNotIn("Kaminko's House", travel_locations.TRAVEL_LOCATION_NAMES)

    def test_always_open_travel_bits_covers_exactly_gateon_port_and_agate_village(self) -> None:
        # Kaminko Mansion has no bit at all (ADDENDUM 84 -- nothing to write); Pokemon HQ Lab was never a
        # separate travel destination with its own bit.
        self.assertEqual(set(travel_locations.ALWAYS_OPEN_TRAVEL_BITS), {"Gateon Port", "Agate Village"})
        self.assertTrue(set(travel_locations.ALWAYS_OPEN_TRAVEL_BITS).isdisjoint(travel_locations.TRAVEL_LOCATION_BITS))


class TestWriteTravelLocationBit(unittest.TestCase):
    def setUp(self) -> None:
        self.mem = _FakeMemory()
        # Patched against the actual `ram_client` module object this test imported (relative import, same
        # package-resolution path travel_locations.py's own lazy `from . import ram_client` uses) rather than
        # a hardcoded string module path -- avoids a module-identity mismatch between how this test's runner
        # imports the package (e.g. "pokemon_xd.ram_client" under `python -m unittest discover -t apworld_v2`
        # vs. "apworld_v2.pokemon_xd.ram_client" under a plain `import apworld_v2...`) and how travel_locations.
        # py resolves its own lazy import at call time.
        self._patch = unittest.mock.patch.multiple(
            ram_client,
            read_bytes=self.mem.read_bytes,
            write_bytes=self.mem.write_bytes,
        )
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.record_base = 0x80489AE0  # arbitrary -- matches a real observed record base, but any value works

    def test_write_sets_exactly_the_documented_bits(self) -> None:
        travel_locations.write_travel_location_bit(self.record_base, "Mt. Battle")
        byte = self.mem.data[self.record_base + 0x0F]
        self.assertEqual(byte, 0x20)

    def test_write_is_an_or_not_an_overwrite(self) -> None:
        # Snagem Hideout (+0x08, 0x80) and Outskirt Stand (+0x08, 0x02|0x20) share the same byte as Gateon Port
        # (+0x08, 0x08, now in ALWAYS_OPEN_TRAVEL_BITS as of ADDENDUM 106, not TRAVEL_LOCATION_BITS) -- writing
        # both item-gated ones, in any order, must leave both of them set without needing Gateon Port's own
        # write (that's covered separately by TestAlwaysOpenTravelBits below).
        travel_locations.write_travel_location_bit(self.record_base, "Snagem Hideout")
        travel_locations.write_travel_location_bit(self.record_base, "Outskirt Stand")
        byte = self.mem.data[self.record_base + 0x08]
        self.assertEqual(byte, 0x80 | 0x02 | 0x20)
        for name in ("Snagem Hideout", "Outskirt Stand"):
            self.assertTrue(travel_locations.read_travel_location_unlocked(self.record_base, name))

    def test_gateon_port_is_no_longer_an_item_gated_location(self) -> None:
        # ADDENDUM 106 (player request, 2026-09-10): Gateon Port moved to ALWAYS_OPEN_TRAVEL_BITS and is no
        # longer a randomizable "Travel Unlock - " item.
        self.assertNotIn("Gateon Port", travel_locations.TRAVEL_LOCATION_BITS)
        with self.assertRaises(KeyError):
            travel_locations.write_travel_location_bit(self.record_base, "Gateon Port")

    def test_write_never_touches_an_unrelated_byte(self) -> None:
        travel_locations.write_travel_location_bit(self.record_base, "Pyrite Town")  # +0x09
        self.assertNotIn(self.record_base + 0x08, self.mem.data)
        self.assertNotIn(self.record_base + 0x0A, self.mem.data)

    def test_read_travel_location_unlocked_is_false_before_any_write(self) -> None:
        self.assertFalse(travel_locations.read_travel_location_unlocked(self.record_base, "Orre Colosseum"))

    def test_outskirt_stands_old_partial_access_combo_alone_does_not_read_as_full_icon_unlocked(self) -> None:
        # Outskirt Stand's full-icon state needs 0x02|0x20 (dropping the partial-only 0x10 bit, ADDENDUM 90) --
        # the ORIGINAL 3-bit access-only combo (0x02|0x10|0x20, ADDENDUM 84) is missing nothing from the
        # full-icon pair in THIS particular case (0x02 and 0x20 are both already in it), so this specific
        # example isn't a useful negative test -- what genuinely isn't "full-icon unlocked" is a byte missing
        # either full-icon bit, e.g. 0x10 alone (the partial bit by itself, no access at all).
        self.mem.write_bytes(self.record_base + 0x08, bytes([0x10]))
        self.assertFalse(travel_locations.read_travel_location_unlocked(self.record_base, "Outskirt Stand"))


class TestAlwaysOpenTravelBits(unittest.TestCase):
    """ADDENDUM 106 (2026-09-10) -- Gateon Port and Agate Village's bits are now written UNCONDITIONALLY (no
    item involved at all), so the real in-game map matches what AP logic has always treated as free for these
    two (plus Kaminko Mansion and Pokemon HQ Lab, neither of which has a bit to write -- see
    TestTravelLocationBitData.test_always_open_travel_bits_covers_exactly_gateon_port_and_agate_village)."""

    def setUp(self) -> None:
        self.mem = _FakeMemory()
        self._patch = unittest.mock.patch.multiple(
            ram_client,
            read_bytes=self.mem.read_bytes,
            write_bytes=self.mem.write_bytes,
        )
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.record_base = 0x80489AE0

    def test_write_always_open_bits_sets_gateon_port_and_agate_village(self) -> None:
        self.assertFalse(travel_locations.read_always_open_bits_set(self.record_base))
        travel_locations.write_always_open_bits(self.record_base)
        self.assertTrue(travel_locations.read_always_open_bits_set(self.record_base))
        # Gateon Port (+0x08, 0x08) and Agate Village (+0x09, 0x20) -- different bytes, both set.
        self.assertEqual(self.mem.data[self.record_base + 0x08], 0x08)
        self.assertEqual(self.mem.data[self.record_base + 0x09], 0x20)

    def test_write_always_open_bits_is_an_or_not_an_overwrite(self) -> None:
        # Gateon Port shares +0x08 with Snagem Hideout/Outskirt Stand -- writing the always-open bits after an
        # item-gated one (or vice versa) must not clobber either.
        travel_locations.write_travel_location_bit(self.record_base, "Snagem Hideout")
        travel_locations.write_always_open_bits(self.record_base)
        byte = self.mem.data[self.record_base + 0x08]
        self.assertEqual(byte, 0x80 | 0x08)
        self.assertTrue(travel_locations.read_travel_location_unlocked(self.record_base, "Snagem Hideout"))
        self.assertTrue(travel_locations.read_always_open_bits_set(self.record_base))

    def test_write_always_open_bits_is_idempotent(self) -> None:
        travel_locations.write_always_open_bits(self.record_base)
        travel_locations.write_always_open_bits(self.record_base)
        self.assertEqual(self.mem.data[self.record_base + 0x08], 0x08)
        self.assertEqual(self.mem.data[self.record_base + 0x09], 0x20)


class TestClientPyWiring(unittest.TestCase):
    """Text-level sanity check -- see this module's own docstring for why an import-based test isn't possible
    in this sandbox."""

    def setUp(self) -> None:
        client_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Client.py")
        with open(client_path, encoding="utf-8") as f:
            self.source = f.read()

    def test_sync_travel_locations_is_defined(self) -> None:
        self.assertIn("async def sync_travel_locations(ctx: PokemonXDContext)", self.source)

    def test_sync_travel_locations_is_called_from_the_poll_loop(self) -> None:
        self.assertIn("await sync_travel_locations(ctx)", self.source)

    def test_received_travel_locations_is_persisted(self) -> None:
        self.assertIn("received_travel_locations", self.source)
        self.assertIn('"received_travel_locations"', self.source)

    def test_block_base_change_detection_field_exists(self) -> None:
        self.assertIn("_travel_bits_applied_for_block_base", self.source)

    def test_write_always_open_bits_is_called_from_sync_travel_locations(self) -> None:
        # ADDENDUM 106 (2026-09-10) -- Gateon Port/Agate Village must be written unconditionally, every boot.
        self.assertIn("travel_locations.write_always_open_bits(record_base)", self.source)
