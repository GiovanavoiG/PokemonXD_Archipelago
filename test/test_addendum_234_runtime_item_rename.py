"""ADDENDUM 234. The dummy shop berries are renamed in RAM, live, to name the check they will send.

Player: "Investigate if we can make descriptions or names at runtime, which would allow us to show the exact
check that's going to be sent out." Then: "Do the runtime rename and name them by number."

The addresses these tests lean on were measured, not guessed -- see `game_data/item_name_strings.py` for the
two independent derivations of common_rel's 0x80B18DC0 load base.
"""
from __future__ import annotations

import unittest
from unittest import mock

from ..game_data import item_name_strings as ins
from ..game_data import shops
from .. import ram_client


class TestNameStringTable(unittest.TestCase):
    def test_every_shop_berry_has_an_address_and_a_budget(self) -> None:
        for item_id in ram_client.USELESS_BERRY_IDS:
            self.assertIsNotNone(ins.ram_address(item_id), f"item {item_id} has no name address")
            self.assertGreaterEqual(ins.budget_chars(item_id), ins.SHOP_BERRY_NAME_BUDGET)

    def test_the_documented_budget_is_the_real_floor(self) -> None:
        smallest = min(ins.budget_chars(i) for i in ram_client.USELESS_BERRY_IDS)
        self.assertEqual(ins.SHOP_BERRY_NAME_BUDGET, smallest)

    def test_the_measured_razz_address(self) -> None:
        """The one address checked by hand against the live dump, kept as a regression anchor."""
        self.assertEqual(0x80B6B60C, ins.ram_address(148))

    def test_chest_berries_are_recorded_too(self) -> None:
        for item_id in (161, 169, 170, 171, 172, 173, 174):
            self.assertIsNotNone(ins.ram_address(item_id))

    def test_numbered_names_are_all_exactly_the_budget(self) -> None:
        for i in range(1, 21):
            self.assertEqual(ins.SHOP_BERRY_NAME_BUDGET, len(ins.numbered_name(i)), ins.numbered_name(i))

    def test_encode_pads_and_terminates_without_changing_length(self) -> None:
        payload = ins.encode_name("GATEON #3", 10)
        self.assertEqual(10 * 2 + 2, len(payload))
        self.assertTrue(payload.endswith(b"\x00\x00"))
        self.assertEqual("GATEON #3 ", payload[:-2].decode("utf-16-be"))

    def test_encode_refuses_rather_than_truncating(self) -> None:
        self.assertIsNone(ins.encode_name("OUTSKIRT #8", 10))

    def test_plausibility_check_accepts_real_entries_and_rejects_junk(self) -> None:
        self.assertTrue(ins.is_plausible_entry_bytes(ins.encode_name("AP ITEM 01", 10), 10))
        self.assertFalse(ins.is_plausible_entry_bytes(b"\x00" * 22, 10))          # no printable text
        self.assertFalse(ins.is_plausible_entry_bytes(b"\xde\xad" * 11, 10))      # not UTF-16BE ASCII
        self.assertFalse(ins.is_plausible_entry_bytes(ins.encode_name("AP", 10)[:-2], 10))  # no terminator


class TestShopLabelsFit(unittest.TestCase):
    def test_every_confirmed_shop_has_a_label_that_fits_its_biggest_slot(self) -> None:
        for shop in shops.CONFIRMED_SHOPS:
            worst = shops.live_name_for_slot(shop.room_id, shop.slot_count)
            self.assertIsNotNone(worst, f"{shop.name} has no live name")
            self.assertLessEqual(len(worst), ins.SHOP_BERRY_NAME_BUDGET, f"{shop.name}: {worst!r}")

    def test_labels_are_distinct(self) -> None:
        labels = [s.short_label for s in shops.CONFIRMED_SHOPS]
        self.assertEqual(len(labels), len(set(labels)), "two shops share a label -- the shelf would lie")


class TestRenamePolicy(unittest.TestCase):
    def setUp(self) -> None:
        self.renamer = ram_client.ItemNameRenamer()
        self.renamer.verified = True
        self.berries = ram_client.USELESS_BERRY_IDS

    def test_outside_a_shop_the_berries_are_numbered(self) -> None:
        names = self.renamer.desired_names(None, self.berries)
        self.assertEqual([ins.numbered_name(i + 1) for i in range(len(self.berries))],
                         [names[b] for b in self.berries])

    def test_in_a_shop_every_line_is_labelled_differently(self) -> None:
        """ADDENDUM 235 replaced 234's "every berry shows the next check" with a distinct label per line."""
        # ADDENDUM 238c: a berry index is a shelf LINE now, and Gateon has 15 lines -- so berries 16-20 name
        # no line there and read NO CHECK rather than "GATEON 16".."GATEON 20". Every label that names a real
        # line is still distinct, which is what this test was written to protect.
        names = self.renamer.desired_names(156, self.berries)
        labelled = [t for t in names.values() if t != ram_client.NO_CHECK_NAME]
        self.assertEqual(shops.SHOPS_BY_ROOM[156].slot_count, len(labelled))
        self.assertEqual(len(labelled), len(set(labelled)), "two shelf lines share a label")
        self.assertEqual("GATEON 01", names[self.berries[0]])
        self.assertEqual("GATEON 15", names[self.berries[14]])
        self.assertEqual(ram_client.NO_CHECK_NAME, names[self.berries[-1]])

    def test_a_fully_bought_shop_says_so(self) -> None:
        """ADDENDUM 238c: "exhausted" is no longer a room-level counter reaching its cap -- it is every LINE
        having been bought. See test_addendum_235's own note for why the old rule had to go."""
        self.renamer.purchased_by_room = {156: set(self.berries)}
        self.assertEqual({"NO CHECK"}, set(self.renamer.desired_names(156, self.berries).values()))

    def test_a_non_shop_room_falls_back_to_numbers(self) -> None:
        names = self.renamer.desired_names(999, self.berries)
        self.assertEqual(ins.numbered_name(1), names[self.berries[0]])


class TestRenameWrites(unittest.TestCase):
    def setUp(self) -> None:
        self.renamer = ram_client.ItemNameRenamer()
        self.renamer.verified = True
        self.written: "dict[int, bytes]" = {}
        # ADDENDUM 395: the renamer reads ONE entry back each poll to see whether its own write is still
        # there, so this fake has to be readable as well as writable. A write-only fake reads as zeros, which
        # the canary correctly calls a revert -- and every "a steady poll writes nothing" assertion below
        # would fail for a reason that has nothing to do with what it is testing.
        self._read_patch = mock.patch.object(ram_client, "read_bytes", self._read)
        self._read_patch.start()
        self.addCleanup(self._read_patch.stop)

    def _write(self, address, data):
        self.written[address] = data

    def _read(self, address, length):
        return self.written.get(address, b"\x00" * length)[:length].ljust(length, b"\x00")

    def test_a_room_change_writes_once_and_a_steady_poll_writes_nothing(self) -> None:
        with mock.patch.object(ram_client, "write_bytes", self._write):
            first = self.renamer.poll(156)
            self.assertEqual(len(ram_client.USELESS_BERRY_IDS), first)
            self.assertEqual(0, self.renamer.poll(156), "a second poll in the same room must write nothing")
            # REVERSED 2026-09-17 (ADDENDUM 267). This used to assert that `poll(None)` restored the plain
            # numbered names, i.e. that an unreadable room cleared the shelf. It does the opposite now, and
            # the old assertion was pinning the live bug the player reported ("reopening the shop clears
            # everything and no longer updates"): `read_room_id` answers None around transitions -- opening a
            # shop menu is one -- so a single unreadable poll wiped every label, and if the room stayed
            # unreadable while the menu was open it stayed wiped.
            #
            # ADDENDUM 226 had already settled this for chest pickups: an unreadable room is "ask again next
            # poll", never "the answer is no". Holding costs a poll; restoring on a bad read costs the shelf.
            self.assertEqual(0, self.renamer.poll(None),
                             "an unreadable room must HOLD, not clear the shelf")
            # A room we really can read, that really is not a shop, still clears -- that is a different
            # statement and it has to keep working.
            self.assertEqual(len(ram_client.USELESS_BERRY_IDS), self.renamer.poll(138))

    def test_the_written_bytes_decode_to_the_expected_name(self) -> None:
        with mock.patch.object(ram_client, "write_bytes", self._write):
            self.renamer.poll(156)
        payload = self.written[ins.ram_address(148)]
        self.assertEqual("GATEON 01 ", payload[:-2].decode("utf-16-be"))
        self.assertTrue(payload.endswith(b"\x00\x00"))

    def test_refresh_rewrites_without_a_room_change(self) -> None:
        with mock.patch.object(ram_client, "write_bytes", self._write):
            self.renamer.poll(156)
            self.assertEqual(0, self.renamer.poll(156))
            self.renamer.purchased_by_room = {156: {ram_client.USELESS_BERRY_IDS[0]}}
            self.assertEqual(1, self.renamer.refresh(156), "only the line that was bought should change")
        self.assertEqual("NO CHECK  ", self.written[ins.ram_address(148)][:-2].decode("utf-16-be"))

    def test_a_failed_write_disables_renaming_instead_of_retrying(self) -> None:
        def boom(address, data):
            raise RuntimeError("dolphin went away")
        with mock.patch.object(ram_client, "write_bytes", boom):
            self.renamer.poll(156)
        self.assertFalse(self.renamer.enabled)


class TestRenameVerification(unittest.TestCase):
    def test_verify_passes_on_real_looking_entries(self) -> None:
        def reader(address, length):
            return ins.encode_name("RAZZ BERRY", (length - 2) // 2)
        renamer = ram_client.ItemNameRenamer()
        with mock.patch.object(ram_client, "read_bytes", reader):
            self.assertTrue(renamer.verify(ram_client.USELESS_BERRY_IDS))
        self.assertTrue(renamer.enabled)

    def test_verify_refuses_and_disables_on_junk(self) -> None:
        renamer = ram_client.ItemNameRenamer()
        with mock.patch.object(ram_client, "read_bytes", lambda a, n: b"\x00" * n):
            self.assertFalse(renamer.verify(ram_client.USELESS_BERRY_IDS))
        self.assertFalse(renamer.enabled)
        self.assertTrue(renamer.verify_failures)

    def test_an_unverified_renamer_never_writes(self) -> None:
        renamer = ram_client.ItemNameRenamer()
        calls = []
        with mock.patch.object(ram_client, "write_bytes", lambda a, d: calls.append(a)):
            renamer.poll(156)
            renamer.refresh(156)
        self.assertEqual([], calls, "a renamer that never verified must not write anything")
