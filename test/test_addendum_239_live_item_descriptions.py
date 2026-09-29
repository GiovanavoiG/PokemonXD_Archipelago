"""ADDENDUM 239 (2026-09-15) -- the shop shelf says what it will actually send.

Player: "Wire in those AP item names (what would be sent out) into the description, and label each item with
its check number." ADDENDUM 235 shipped the label; this is the item name, and it needed two things that did
not exist then: the server's answer about what each shop line holds (a LocationScouts on connect) and the
description table's real location in RAM.

THE DUMP-BACKED TESTS BELOW ARE THE POINT. Everything in `game_data/item_descriptions.py` was measured off
three real 24 MB MEM1 dumps taken with a shop menu open, and those dumps are still on disk. So the constants
are not asserted against themselves -- they are re-derived from the dumps on every run where the dumps are
present, and skipped (not silently passed) where they are not.
"""
import os
import struct
import unittest

from .. import ram_client
from ..game_data import item_descriptions as D
from ..game_data import shops
from ..items import USELESS_BERRY_IDS

DUMP_DIR = "/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/"
# {dump file: the table base measured in it}. Three separate loads of the same file at three addresses, which
# is the evidence that the base moves and the per-entry offsets do not.
SHOP_MENU_DUMPS = {
    "dump_gateon_shopmenu_20260915.bin": 0x809CECC0,
    "agate_shopmenu_20260915.bin": 0x8099DC60,
    "reboot_shopmenu_20260915.bin": 0x80D81B60,
}
# Dumps with NO menu open. The table is absent from a shop room with the menu shut, which is why the writer
# has to write while it is open rather than on a room change like the renamer does.
NO_TABLE_DUMPS = ("reboot_phenac.bin", "gateon_indoors.bin", "dump_gateon_shop_20260915.bin")
ITEM_TABLE_RAM = 0x80B38CA4   # located by signature: entry[1].nameid == 5001 and entry[148].nameid == 5115
ITEM_ENTRY_SIZE = 40
ITEM_DESCRIPTION_ID_OFFSET = 0x14


def _dump(name):
    path = os.path.join(DUMP_DIR, name)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as handle:
        return handle.read()



def _merged_contiguous(plan):
    """The plan's bands sorted and merged -- equal to the sorted plan only when they tile without gaps."""
    out = []
    for low, high in sorted(plan):
        if out and out[-1][1] == low:
            out[-1] = (out[-1][0], high)
        else:
            out.append((low, high))
    return out

class TestTheTableInRealDumps(unittest.TestCase):
    def test_the_magic_occurs_exactly_once_in_all_of_mem1(self) -> None:
        """This is what makes locating the table a SEARCH rather than a guess. If the magic appeared twice the
        writer could pick the wrong one and scribble UTF-16 over something else."""
        for name, expected_base in SHOP_MENU_DUMPS.items():
            data = _dump(name)
            if data is None:
                self.skipTest(f"{name} not available")
            hits = []
            start = 0
            while True:
                index = data.find(D.MSG_MAGIC, start)
                if index < 0:
                    break
                hits.append(D.MEM1_START + index - D.MSG_MAGIC_OFFSET)
                start = index + 1
            self.assertEqual(hits, [expected_base], name)

    def test_the_table_is_absent_when_no_menu_is_open(self) -> None:
        checked = 0
        for name in NO_TABLE_DUMPS:
            data = _dump(name)
            if data is None:
                continue
            checked += 1
            self.assertNotIn(D.MSG_MAGIC, data, name)
        if not checked:
            self.skipTest("no menu-closed dumps available")

    def test_the_pair_table_is_self_terminating(self) -> None:
        """The header's +0x10 scalar is 5331, which is NOT the entry count -- 0x18 + 5331*8 would walk the
        parser straight through the string data. The real stopping rule is the smallest offset any pair names,
        and in these dumps the pair table ends exactly there."""
        data = _dump("dump_gateon_shopmenu_20260915.bin")
        if data is None:
            self.skipTest("dump not available")
        base = SHOP_MENU_DUMPS["dump_gateon_shopmenu_20260915.bin"] - D.MEM1_START
        pairs = D.parse_pair_table(data[base:base + 0x20000])
        self.assertEqual(len(pairs), 582)
        lowest = min(offset for _sid, offset in pairs)
        self.assertEqual(D.MSG_PAIR_TABLE_OFFSET + len(pairs) * D.MSG_PAIR_SIZE, lowest)
        self.assertNotEqual(struct.unpack_from(">I", data, base + 0x10)[0], len(pairs))

    def test_every_constant_re_derives_from_every_dump(self) -> None:
        """The whole table of offsets and budgets, rebuilt from each dump independently. Identical in all
        three -- only the base differs."""
        checked = 0
        for name, table_base in SHOP_MENU_DUMPS.items():
            data = _dump(name)
            if data is None:
                continue
            checked += 1
            base = table_base - D.MEM1_START
            pairs = D.parse_pair_table(data[base:base + 0x20000])
            size = max(offset for _sid, offset in pairs) + 0x200
            budgets = D.budgets_from_pairs(pairs, size)
            item_table = ITEM_TABLE_RAM - D.MEM1_START
            for item_id, (offset, budget, description_id) in D.ITEM_DESCRIPTION_ENTRIES.items():
                raw = struct.unpack_from(
                    ">I", data, item_table + item_id * ITEM_ENTRY_SIZE + ITEM_DESCRIPTION_ID_OFFSET)[0]
                self.assertEqual(raw & 0xFFFFF, description_id, f"{name} item {item_id}")
                self.assertEqual(budgets[description_id], (offset, budget), f"{name} item {item_id}")
        if not checked:
            self.skipTest("no shop-menu dumps available")

    def test_the_description_id_is_not_ten_thousand_plus_the_item_id(self) -> None:
        """The shortcut that looks right for a long time and is wrong: 10001 really is Master Ball and 10013
        really is Potion, but 10148 is Soothe Bell, not Razz Berry. The id comes from the item's own +0x14."""
        self.assertEqual(D.ITEM_DESCRIPTION_ENTRIES[148][2], 10115)
        self.assertNotEqual(D.ITEM_DESCRIPTION_ENTRIES[148][2], 10148)

    def test_the_search_helper_finds_the_base_across_a_chunk_boundary(self) -> None:
        """The scan reads in chunks and overlaps them, because the magic could straddle a boundary."""
        data = _dump("dump_gateon_shopmenu_20260915.bin")
        if data is None:
            self.skipTest("dump not available")
        expected = SHOP_MENU_DUMPS["dump_gateon_shopmenu_20260915.bin"]
        index = expected - D.MEM1_START + D.MSG_MAGIC_OFFSET
        chunk_start = index - 0x100
        self.assertEqual(
            D.search_chunk_for_base(data[chunk_start:chunk_start + 0x200], D.MEM1_START + chunk_start),
            expected)
        # A chunk that ends part-way through the magic must NOT report a hit -- which is why the scan overlaps
        # its chunks by the magic's own length rather than reading them back to back.
        for split in range(1, len(D.MSG_MAGIC)):
            cut = data[chunk_start:index + split]
            self.assertIsNone(D.search_chunk_for_base(cut, D.MEM1_START + chunk_start), split)


class TestNothingIsEverWrittenOutsideItsEntry(unittest.TestCase):
    """The rule the first hand-run live test broke -- it "replaced some extra text, such as the cancel
    button", which is what writing past an entry looks like."""

    def test_every_payload_is_exactly_the_budget(self) -> None:
        for item_id, (_offset, budget, _did) in D.ITEM_DESCRIPTION_ENTRIES.items():
            lines = D.describe_ap_item("Some Very Long Item Name Indeed", "Somebody", budget)
            payload = D.encode_lines(lines, budget)
            self.assertIsNotNone(payload, item_id)
            self.assertEqual(len(payload), budget, item_id)

    def test_text_that_cannot_fit_is_refused_rather_than_truncated(self) -> None:
        self.assertIsNone(D.encode_lines(["A" * 200], 88))

    def test_entries_do_not_overlap(self) -> None:
        spans = sorted((offset, offset + budget)
                       for offset, budget, _did in D.ITEM_DESCRIPTION_ENTRIES.values())
        for (_start, end), (next_start, _next_end) in zip(spans, spans[1:]):
            self.assertLessEqual(end, next_start)


class TestTheWrapper(unittest.TestCase):
    def test_short_text_uses_one_line(self) -> None:
        self.assertEqual(D.wrap_description("Progressive Sword", 88), ["Progressive Sword"])

    def test_a_line_break_is_budgeted_as_three_bytes(self) -> None:
        """Two bytes per character is the easy half. A break costs 3, not 2, so a character-only budget
        overruns by one byte per break -- and an overrun is the cancel-button bug."""
        self.assertEqual(D.LINE_BREAK_BYTES, 3)
        for text in ("Bottle of Extremely Fancy Sparkling Water", "A" * 60, "x " * 40):
            lines = D.wrap_description(text, 88)
            payload = D.encode_lines(lines, 88)
            self.assertIsNotNone(payload, text)
            self.assertEqual(len(payload), 88)

    def test_no_line_is_wider_than_the_measured_pane(self) -> None:
        for text in ("Bottle of Extremely Fancy Sparkling Water", "Supercalifragilisticexpialidocious"):
            for line in D.wrap_description(text, 88):
                self.assertLessEqual(len(line), D.DESCRIPTION_LINE_WIDTH, text)

    def test_text_that_does_not_fit_is_marked_rather_than_silently_cut(self) -> None:
        """Showing a truncated name beats showing a different item's name by accident."""
        lines = D.wrap_description("Bottle of Extremely Fancy Sparkling Water From Somewhere", 88)
        self.assertTrue(lines[-1].endswith("..."))

    def test_another_players_item_spends_its_first_line_on_who(self) -> None:
        lines = D.describe_ap_item("Hookshot", "Bobbington", 88)
        self.assertEqual(lines[0], "To Bobbington")
        self.assertIn("Hookshot", lines)

    def test_our_own_item_uses_every_line_for_the_name(self) -> None:
        self.assertEqual(D.describe_ap_item("Data ROM & ID Card", None, 88), ["Data ROM & ID Card"])


class TestWriterPolicy(unittest.TestCase):
    def setUp(self) -> None:
        self.writer = ram_client.ItemDescriptionWriter()
        self.berries = list(USELESS_BERRY_IDS)
        self.gateon = 156

    _DEFAULT = object()

    def _lines(self, scouted=None, purchased=frozenset(), room=_DEFAULT):
        where = self.gateon if room is self._DEFAULT else room
        return self.writer.desired_lines(where, self.berries, scouted or {}, set(purchased))

    def test_outside_a_shop_nothing_is_written(self) -> None:
        self.assertEqual(self._lines(room=None), {})          # room unreadable
        self.assertEqual(self._lines(room=999), {})           # a real room that is not a shop
        self.assertEqual(self._lines(room=61), {})            # the EXCLUDED Battle CD shop room

    def test_a_scouted_line_names_its_real_ap_item(self) -> None:
        scouted = {"Gateon Port Shop AP Item 1": ("Progressive Sword", None)}
        lines = self._lines(scouted)
        self.assertEqual(lines[self.berries[0]], ["Progressive Sword"])

    def test_the_numbering_is_the_same_one_the_label_and_the_tracker_use(self) -> None:
        """ADDENDUM 238c is what makes this honest. Before per-shop-line berries, which check a line sent
        depended on the order the player bought in, and ADDENDUM 235 said naming a line after a specific AP
        slot "would be a claim the tracker does not support"."""
        scouted = {f"Gateon Port Shop AP Item {n}": (f"Item{n}", None) for n in range(1, 16)}
        lines = self._lines(scouted)
        for index, berry in enumerate(self.berries[:15]):
            self.assertEqual(lines[berry], [f"Item{index + 1}"])

    def test_a_berry_past_the_shops_line_count_keeps_its_vanilla_description(self) -> None:
        """Gateon has 15 lines. Berry 16-20 name no line of it, so they are left alone entirely rather than
        given a misleading "no check" -- they are not this shop's to speak for."""
        cap = shops.SHOPS_BY_ROOM[self.gateon].slot_count
        lines = self._lines({f"Gateon Port Shop AP Item {n}": ("X", None) for n in range(1, cap + 1)})
        for berry in self.berries[cap:]:
            self.assertNotIn(berry, lines)

    def test_an_unscouted_line_says_so_rather_than_guessing(self) -> None:
        self.assertEqual(self._lines()[self.berries[0]], D.UNKNOWN_DESCRIPTION_LINES)

    def test_a_bought_line_says_it_will_send_nothing(self) -> None:
        scouted = {"Gateon Port Shop AP Item 1": ("Progressive Sword", None)}
        lines = self._lines(scouted, purchased={self.berries[0]})
        self.assertEqual(lines[self.berries[0]], D.NO_CHECK_DESCRIPTION_LINES)

    def test_every_produced_payload_fits_its_entry(self) -> None:
        scouted = {f"Gateon Port Shop AP Item {n}": ("Bottle of Extremely Fancy Water", "Bobbington")
                   for n in range(1, 16)}
        for item_id, lines in self._lines(scouted).items():
            budget = D.budget_bytes(item_id)
            self.assertEqual(len(D.encode_lines(lines, budget)), budget, item_id)


class TestWriterSafety(unittest.TestCase):
    """Same standing rule ADDENDUM 234 set for the renamer: cosmetics must never cost a check."""

    def test_a_moved_table_drops_the_write_cache(self) -> None:
        """The table is reloaded from disc on every menu open, so every edit at the old base is void. Keeping
        the cache would make the next write a no-op against a table that is vanilla again."""
        writer = ram_client.ItemDescriptionWriter(table_base=0x80900000)
        writer._written[148] = (0x80900000, ("x",))
        calls = []

        def fake_read(address, length):
            calls.append(address)
            return b"\x00" * length   # no magic -- the table has moved or unloaded

        original = ram_client.read_bytes
        ram_client.read_bytes = fake_read
        try:
            writer._last_scan_at = 1e18   # rate-limit the rescan so this test stays pure
            self.assertIsNone(writer.locate(now=1e18))
        finally:
            ram_client.read_bytes = original
        self.assertIsNone(writer.table_base)
        self.assertEqual(writer._written, {})
        self.assertEqual(writer.reloads_detected, 1)

    def test_a_failed_write_disables_the_feature_instead_of_retrying(self) -> None:
        writer = ram_client.ItemDescriptionWriter()

        def boom(address, payload):
            raise RuntimeError("no dolphin")

        original = ram_client.write_bytes
        ram_client.write_bytes = boom
        try:
            written = writer._write(0x80900000, {148: ["Hello"]})
        finally:
            ram_client.write_bytes = original
        self.assertEqual(written, 0)
        self.assertFalse(writer.enabled)
        self.assertEqual(writer.last_error, "no dolphin")
        self.assertEqual(writer.poll(156, {}, set()), 0)

    def test_scans_are_rate_limited(self) -> None:
        """RETARGETED BY ADDENDUM 357: the active interval is 0.25s, not 1.0s. The throttle still exists and
        still governs CHUNK reads -- what changed is its value and, below, what it does not govern."""
        writer = ram_client.ItemDescriptionWriter()
        writer._last_scan_at = 100.0
        self.assertIsNone(writer.locate(now=100.0 + writer._MIN_SECONDS_BETWEEN_SCANS / 2))
        self.assertEqual(writer.scans, 0)

    def test_a_remembered_address_is_probed_without_waiting_for_the_throttle(self) -> None:
        """ADDENDUM 357's fast path. The `.msg` file often reloads to an address it has used before, and a
        few 8-byte reads is not what the throttle is there to govern -- making a reopen wait on it was the
        difference between "instant" and "up to twelve seconds"."""
        writer = ram_client.ItemDescriptionWriter()
        writer._hot_bases = [0x80946140]
        writer._last_scan_at = 100.0   # deep inside the throttle

        def fake_read(address, length):
            if address == 0x80946140:
                return D.MSG_MAGIC.rjust(D.MSG_MAGIC_OFFSET + len(D.MSG_MAGIC), b"\x00")
            return b"\x00" * length

        original = ram_client.read_bytes
        ram_client.read_bytes = fake_read
        try:
            self.assertEqual(0x80946140, writer.locate(now=100.01))
        finally:
            ram_client.read_bytes = original
        self.assertEqual(1, writer.hot_hits)
        self.assertEqual(0, writer.scans, "no chunk scan should have been needed")

    def test_a_lost_table_is_remembered_as_an_address_worth_reprobing(self) -> None:
        writer = ram_client.ItemDescriptionWriter()
        writer.table_base = 0x80999999
        original = ram_client.read_bytes
        ram_client.read_bytes = lambda address, length: b"\x00" * length
        try:
            writer.locate(now=1000.0)
        finally:
            ram_client.read_bytes = original
        self.assertIn(0x80999999, writer._hot_bases)

    def test_the_remembered_list_is_bounded_and_most_recent_first(self) -> None:
        writer = ram_client.ItemDescriptionWriter()
        for base in range(0x80900000, 0x80900000 + (writer._HOT_BASES_KEPT + 4) * 0x100, 0x100):
            writer._remember_base(base)
        self.assertEqual(writer._HOT_BASES_KEPT, len(writer._hot_bases))
        self.assertEqual(sorted(writer._hot_bases, reverse=True), writer._hot_bases)
        writer._remember_base(writer._hot_bases[-1])
        self.assertEqual(writer._HOT_BASES_KEPT, len(writer._hot_bases), "a re-seen address moves, not grows")

    def test_the_scan_is_resumable_and_bounded_per_poll(self) -> None:
        """MEM1 is 24 MB; an exhaustive search is ~390 reads. Doing them in one tick would stall the poll loop
        that is also delivering items. Each poll walks a bounded slice and remembers where it stopped.

        RETARGETED BY ADDENDUM 357. A scan is now the measured bands IN FULL plus a bounded slice of the
        sweep, so the read count per poll is bands + slice rather than slice alone. Both halves of the
        original property survive and are asserted below: bounded, and resumable."""
        writer = ram_client.ItemDescriptionWriter()
        reads = []

        def fake_read(address, length):
            reads.append(address)
            return b"\x00" * length

        step = writer._chunk_step()
        bands = sum(max(1, -(-(high - low) // step)) for low, high in writer._band_plan())
        original = ram_client.read_bytes
        ram_client.read_bytes = fake_read
        try:
            self.assertIsNone(writer.locate(now=1000.0))
            first = len(reads)
            self.assertEqual(first, bands + writer._CHUNKS_PER_POLL, "bounded: bands plus one sweep slice")
            self.assertEqual(writer._scan_cursor, writer._CHUNKS_PER_POLL)
            self.assertIsNone(writer.locate(now=1000.0 + writer._MIN_SECONDS_BETWEEN_SCANS))
            self.assertEqual(len(reads), first * 2)
            # The SWEEP resumed rather than restarting...
            sweep_first = reads[bands:first]
            self.assertNotIn(sweep_first[0], reads[first + bands:])
            # ...while the bands were walked again, which is the whole of ADDENDUM 357's second change.
            self.assertEqual(reads[:bands], reads[first:first + bands])
        finally:
            ram_client.read_bytes = original

    def test_the_bands_are_probed_whatever_the_sweep_cursor_is_doing(self) -> None:
        """ADDENDUM 357's finding, stated directly. `poll` gates on being in a shop ROOM, not on the table
        existing, so with the menu shut the sweep runs continuously and the cursor is at an arbitrary point
        by the time the player opens a menu. If the bands are only reached at cursor zero, the likeliest 28
        chunks are searched last -- which is the six-to-twelve-second wait the player reported twice."""
        writer = ram_client.ItemDescriptionWriter()
        writer._scan_cursor = 200          # mid-sweep, as it would be after standing in a shop a while
        target = D.MEASURED_BAND_LOW_START + 3 * writer._chunk_step()
        payload = D.MSG_MAGIC.rjust(D.MSG_MAGIC_OFFSET + len(D.MSG_MAGIC), b"\x00")

        def fake_read(address, length):
            if address == target:
                return payload + b"\x00" * max(0, length - len(payload))
            return b"\x00" * length

        original = ram_client.read_bytes
        ram_client.read_bytes = fake_read
        try:
            self.assertEqual(target, writer.locate(now=1000.0))
        finally:
            ram_client.read_bytes = original

    def test_a_failed_full_sweep_backs_off_and_a_find_undoes_it(self) -> None:
        """The other half: a player standing in a shop with the menu SHUT used to read 2 MB a second forever
        to keep proving something it had already proved."""
        writer = ram_client.ItemDescriptionWriter()
        original = ram_client.read_bytes
        ram_client.read_bytes = lambda address, length: b"\x00" * length
        try:
            now = 1000.0
            while writer.failed_scans == 0 and now < 1000.0 + 600.0:
                writer.locate(now=now)
                now += writer._scan_interval
            self.assertEqual(1, writer.failed_scans)
            self.assertEqual(writer._IDLE_SECONDS_BETWEEN_SCANS, writer._scan_interval)
        finally:
            ram_client.read_bytes = original
        # Losing a table is "it is about to be somewhere" -- the active rate comes straight back.
        writer.table_base = 0x80999999
        original = ram_client.read_bytes
        ram_client.read_bytes = lambda address, length: b"\x00" * length
        try:
            writer.locate(now=now + 1.0)
        finally:
            ram_client.read_bytes = original
        self.assertEqual(writer._MIN_SECONDS_BETWEEN_SCANS, writer._scan_interval)

    def test_the_search_starts_in_the_bands_the_table_has_been_measured_in(self) -> None:
        """RETARGETED BY ADDENDUM 352. The old single likely window was drawn around four observations; it is
        now eighteen, and they fall in two clusters with nothing between them. The two measured bands go
        first, and between them they are 26 chunks -- small enough that one scan slice covers both."""
        writer = ram_client.ItemDescriptionWriter()
        plan = writer._search_plan()
        self.assertEqual(plan[0], (D.MEASURED_BAND_LOW_START, D.MEASURED_BAND_LOW_END))
        self.assertEqual(plan[1], (D.MEASURED_BAND_HIGH_START, D.MEASURED_BAND_HIGH_END))
        # ADDENDUM 357: and the two halves partition it, so nothing is searched twice within one scan and
        # nothing is missed by being in neither list.
        self.assertEqual(plan, writer._band_plan() + writer._sweep_plan())
        # ...but the bands are an ordering, not a bound: the rest of MEM1 is still covered, contiguously.
        covered = sum(high - low for low, high in plan)
        self.assertEqual(covered, D.MEM1_END - D.MEM1_START)
        self.assertEqual([(D.MEM1_START, D.MEM1_END)], _merged_contiguous(plan),
                         "the plan must tile MEM1 with no gap and no overlap")

    def test_the_two_bands_fit_in_one_scan_slice(self) -> None:
        """The property the whole change rests on. If a later edit widens a band or lowers the per-poll
        budget until they no longer fit, the table stops being found on the first slice and the symptom the
        player reported comes straight back -- silently, because it is only ever slower, never broken."""
        writer = ram_client.ItemDescriptionWriter()
        overlap = D.MSG_MAGIC_OFFSET + len(D.MSG_MAGIC)
        step = writer._CHUNK - overlap
        chunks = sum(-(-(high - low) // step) for low, high in writer._band_plan())
        self.assertLessEqual(chunks, writer._CHUNKS_PER_POLL,
                             f"the measured bands need {chunks} chunks but a slice only walks "
                             f"{writer._CHUNKS_PER_POLL}")

    def test_every_measured_base_falls_inside_a_measured_band(self) -> None:
        """The 18 corpus observations, so a band cannot be narrowed past its own evidence."""
        observed = (0x80946140, 0x80989BA0, 0x8098C0C0, 0x8098E220, 0x8099DC60, 0x809AECA0,
                    0x809CECC0, 0x809FBE60, 0x80A35180, 0x80D3B4C0, 0x80D81B60, 0x80DCB500)
        bands = ((D.MEASURED_BAND_LOW_START, D.MEASURED_BAND_LOW_END),
                 (D.MEASURED_BAND_HIGH_START, D.MEASURED_BAND_HIGH_END))
        for base in observed:
            self.assertTrue(any(low <= base < high for low, high in bands), hex(base))

    def test_losing_the_table_waives_the_scan_throttle_for_one_poll(self) -> None:
        """The menu-reopen case. The table is reloaded from disc at a new address every time a shop menu
        opens, so the tick that notices it is gone is the tick that should search."""
        writer = ram_client.ItemDescriptionWriter()
        writer.table_base = 0x80999999
        writer._last_scan_at = 1000.0

        original = ram_client.read_bytes
        ram_client.read_bytes = lambda address, length: b"\x00" * length   # the table is not there any more
        try:
            writer.locate(now=1000.1)     # well inside _MIN_SECONDS_BETWEEN_SCANS
        finally:
            ram_client.read_bytes = original
        self.assertEqual(1, writer.reloads_detected)
        self.assertNotEqual(1000.0, writer._last_scan_at,
                            "the throttle must have been waived, not merely survived")

    def test_a_read_failure_during_the_search_is_counted_not_fatal(self) -> None:
        """RETARGETED by ADDENDUM 389. This asserted that one failed read switched descriptions off, which was
        the deliberate design and turned out to be the bug the player reported as "all the shops break after
        the first one of a session": the search reads megabytes of MEM1, so a single unlucky read -- a menu
        closing mid-sweep -- took the feature down for good.

        What stays asserted is the half that mattered: it must not SPIN. `locate` still returns None, so the
        poll ends rather than retrying the failed read in a loop."""
        writer = ram_client.ItemDescriptionWriter()

        def boom(address, length):
            raise RuntimeError("no dolphin")

        original = ram_client.read_bytes
        ram_client.read_bytes = boom
        try:
            self.assertIsNone(writer.locate(now=2000.0))
        finally:
            ram_client.read_bytes = original
        self.assertTrue(writer.enabled, "a failed read is bad luck on one address, not a broken feature")
        self.assertGreater(writer.read_failures, 0, "but it must be recorded")

    def test_nothing_load_bearing_reads_the_scouted_map(self) -> None:
        """A scout that never arrives must cost nothing. The map is read in exactly one place."""
        # Read the FILE rather than importing it -- Client.py pulls in the full Archipelago networking
        # stack, which is not importable in a bare test environment, and this assertion is about the source.
        import pathlib
        source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        # NARROWED 2026-09-17 (ADDENDUM 261): the diagnostic command is excluded from the scan.
        #
        # This used to walk the whole file, on the reasoning that the map is read in exactly ONE place. The
        # claim it is really making is narrower and still true: nothing in the ITEM-DELIVERY OR CHECK-SENDING
        # paths reads it, which is what makes a scout that never arrives cost nothing. `!shops` reads it too
        # now, and has to -- ADDENDUM 261's bug was precisely that this map silently stayed empty and no
        # command could say so. A diagnostic the player has to type is not a path anything depends on.
        #
        # Excluded by FUNCTION, not by line text, so the exclusion cannot quietly widen: everything inside a
        # `_cmd_*` method is skipped and everything else is still held to the rule.
        import ast

        command_lines: "set[int]" = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("_cmd_"):
                command_lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
        # Matched as an ATTRIBUTE, not as a bare substring: `shop_scout.scouted_shop_items(` is the pure
        # PARSER's name (ADDENDUM 261) and a substring search reports calling it as reading the map.
        uses = [line.strip() for number, line in enumerate(source.splitlines(), start=1)
                if ("self.scouted_shop_items" in line or "ctx.scouted_shop_items" in line)
                and not line.lstrip().startswith("#")
                and number not in command_lines]
        self.assertTrue(uses)
        reads = [line for line in uses
                 if "self.scouted_shop_items[name] =" not in line
                 and "self.scouted_shop_items.update(" not in line
                 and 'dict[str, tuple[str, str | None]]' not in line
                 and "len(self.scouted_shop_items)" not in line
                 and "if self.scouted_shop_items:" not in line]
        self.assertEqual(reads, ["ctx.scouted_shop_items,"], uses)


class TestEndToEndAgainstARealDump(unittest.TestCase):
    """The test that would have caught the cancel-button bug. A real 24 MB MEM1 dump is used as if it were
    live memory: the writer locates the table in it, writes every shop line, and the result is read back with
    a parser that shares no code with the writer."""

    def test_it_locates_writes_and_never_leaves_its_own_entries(self) -> None:
        raw = _dump("dump_gateon_shopmenu_20260915.bin")
        if raw is None:
            self.skipTest("dump not available")
        memory = bytearray(raw)
        writes: "list[tuple[int, int]]" = []

        def read(address, length):
            return bytes(memory[address - D.MEM1_START:address - D.MEM1_START + length])

        def write(address, payload):
            writes.append((address, len(payload)))
            memory[address - D.MEM1_START:address - D.MEM1_START + len(payload)] = payload

        scouted = {f"Gateon Port Shop AP Item {n}": (name, who) for n, (name, who) in enumerate(
            [("Progressive Sword", None), ("Data ROM & ID Card", None), ("Hookshot", "Bobbington"),
             ("TM10", None), ("Small Key (Palace of Darkness)", "Zelda"), ("Max Revive", None),
             ("Ganlon Berry", "Alice"), ("Bottle of Extremely Fancy Sparkling Water", None),
             ("Ether", None), ("Elevator Key", None), ("Miror Radar", None), ("System Lever", None),
             ("Music Disc", None), ("Master Ball", None), ("Poke Snack", None)], 1)}

        writer = ram_client.ItemDescriptionWriter()
        original_read, original_write = ram_client.read_bytes, ram_client.write_bytes
        ram_client.read_bytes, ram_client.write_bytes = read, write
        try:
            written = 0
            for _ in range(80):     # the scan is resumable, so it takes several polls to reach the table
                written = writer.poll(156, scouted, set())
                if written:
                    break
        finally:
            ram_client.read_bytes, ram_client.write_bytes = original_read, original_write

        self.assertEqual(writer.table_base, SHOP_MENU_DUMPS["dump_gateon_shopmenu_20260915.bin"])
        self.assertEqual(written, shops.SHOPS_BY_ROOM[156].slot_count)

        # THE ASSERTION THAT MATTERS: every write starts exactly at an entry and is exactly that entry long.
        table = read(writer.table_base, 0x20000)
        pairs = D.parse_pair_table(table)
        budgets = D.budgets_from_pairs(pairs, max(offset for _sid, offset in pairs) + 0x200)
        spans = {offset: budget for offset, budget in budgets.values()}
        for address, length in writes:
            offset = address - writer.table_base
            self.assertIn(offset, spans, hex(address))
            self.assertEqual(length, spans[offset], hex(address))

        # And read the result back with an independent decoder.
        self.assertEqual(_decode(memory, writer.table_base, D.entry_offset(148)), ["Progressive Sword"])
        self.assertEqual(_decode(memory, writer.table_base, D.entry_offset(150)),
                         ["To Bobbington", "Hookshot"])
        self.assertEqual(_decode(memory, writer.table_base, D.entry_offset(155)),
                         ["Bottle of Extremely", "Fancy Sparkling", "Water"])

    def test_a_second_poll_writes_nothing_when_nothing_changed(self) -> None:
        """Steady state costs one small re-verify read and zero writes -- the same rule the renamer follows."""
        writer = ram_client.ItemDescriptionWriter(table_base=0x80900000)
        writer._written[148] = (0x80900000, ("Progressive Sword",))
        self.assertEqual(writer._write(0x80900000, {148: ["Progressive Sword"]}), 0)


def _decode(memory: bytearray, table_base: int, offset: int) -> "list[str]":
    """Read one entry back as lines. Deliberately written from the FORMAT, sharing no code with the writer --
    a decoder that reused `encode_lines` would agree with it even when both were wrong."""
    position = table_base - D.MEM1_START + offset
    lines: "list[str]" = []
    current: "list[str]" = []
    while True:
        pair = bytes(memory[position:position + 2])
        if pair == D.STRING_TERMINATOR:
            break
        if pair == D.LINE_BREAK[:2]:
            lines.append("".join(current))
            current = []
            position += D.LINE_BREAK_BYTES
            continue
        current.append(chr(struct.unpack(">H", pair)[0]))
        position += 2
    lines.append("".join(current))
    return [line for line in lines if line]


if __name__ == "__main__":
    unittest.main()
