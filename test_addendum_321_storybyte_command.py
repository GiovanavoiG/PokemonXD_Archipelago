"""ADDENDUM 321 -- `!storybyte`, the manual story-byte write.

Player: "can you add a debug command to edit story byte? for example '!storybyte 27' would set it to 0x27"."""
import unittest
from unittest import mock

from .. import Client, ram_client as rc

BLOCK = 0x80479000


class _Live:
    def __init__(self, value: int) -> None:
        self.value = value
        self.writes: "list[tuple[int, int]]" = []
        self._write, self._read = rc.write_bytes, rc.read_story_byte
        rc.write_bytes = self._fake_write
        rc.read_story_byte = lambda block_base: self.value

    def _fake_write(self, address, data):
        self.writes.append((address, data[0]))
        self.value = data[0]

    def restore(self):
        rc.write_bytes, rc.read_story_byte = self._write, self._read


class TestTheWriter(unittest.TestCase):
    def setUp(self):
        self.live = _Live(0x15)

    def tearDown(self):
        self.live.restore()

    def test_it_writes_the_value_and_reports_the_old_one(self):
        written, previous = rc.write_story_byte(BLOCK, 0x27)
        self.assertTrue(written)
        self.assertEqual(0x15, previous)
        self.assertEqual(0x27, self.live.value)

    def test_it_writes_to_the_story_byte_address(self):
        rc.write_story_byte(BLOCK, 0x27)
        self.assertEqual([(BLOCK + rc.STORY_RECORD_OFFSET + rc.STORY_BYTE_OFFSET, 0x27)], self.live.writes)

    def test_a_value_outside_a_byte_is_refused(self):
        for value in (-1, 256, 1000):
            self.assertEqual((False, None), rc.write_story_byte(BLOCK, value))
        self.assertEqual([], self.live.writes)

    def test_it_is_logged_like_every_other_write_site(self):
        log = rc.StoryByteWriteLog()
        rc.write_story_byte(BLOCK, 0x71, write_log=log, why="!storybyte (manual)")
        self.assertIn("manual", [entry.source for entry in log.entries])

    def test_it_holds_no_opinion_about_the_number(self):
        """A debug command that refuses an odd value is not a debug command. 0xFF is writable."""
        self.assertEqual((True, 0x15), rc.write_story_byte(BLOCK, 0xFF))


class _Ctx:
    """Only what the command touches."""
    def __init__(self):
        self.block_base = BLOCK
        self.story_write_log = rc.StoryByteWriteLog()
        self.story_write_log_path = None
        self.area_story_memory = rc.AreaStoryByteMemory()


class TestTheCommand(unittest.TestCase):
    def setUp(self):
        self.live = _Live(0x15)
        self.ctx = _Ctx()
        self.processor = Client.PokemonXDCommandProcessor.__new__(Client.PokemonXDCommandProcessor)
        self.processor.ctx = self.ctx
        self.logged: "list[str]" = []
        patcher = mock.patch.object(Client.logger, "info", side_effect=self.logged.append)
        patcher.start()
        self.addCleanup(patcher.stop)
        saver = mock.patch.object(Client, "_save_story_write_log")
        saver.start()
        self.addCleanup(saver.stop)
        isinst = mock.patch.object(Client, "PokemonXDContext", _Ctx)
        isinst.start()
        self.addCleanup(isinst.stop)

    def tearDown(self):
        self.live.restore()

    def test_the_players_own_example(self):
        self.processor._cmd_storybyte("27")
        self.assertEqual(0x27, self.live.value)
        self.assertIn("0x15 -> 0x27", "\n".join(self.logged))

    def test_hex_with_or_without_the_prefix(self):
        self.processor._cmd_storybyte("0x6e")
        self.assertEqual(0x6E, self.live.value)

    def test_decimal_on_request(self):
        self.processor._cmd_storybyte("d110")
        self.assertEqual(110, self.live.value)

    def test_no_argument_just_reads(self):
        self.processor._cmd_storybyte()
        self.assertEqual(0x15, self.live.value)
        self.assertEqual([], self.live.writes)
        self.assertIn("0x15", self.logged[0])

    def test_nonsense_is_refused_without_writing(self):
        self.processor._cmd_storybyte("banana")
        self.assertEqual([], self.live.writes)
        self.assertIn("not a number", "\n".join(self.logged))

    def test_out_of_range_is_refused_without_writing(self):
        self.processor._cmd_storybyte("1ff")
        self.assertEqual([], self.live.writes)

    def test_the_write_is_claimed_so_no_check_is_credited(self):
        """ADDENDUM 268/288: a byte you typed is not a place you went."""
        self.processor._cmd_storybyte("77")
        self.assertEqual(0x77, self.ctx.area_story_memory.last_written_target)

    def test_it_says_the_clients_rules_may_write_over_it(self):
        self.processor._cmd_storybyte("27")
        self.assertIn("may write over this", "\n".join(self.logged))


class TestItIsDiscoverable(unittest.TestCase):
    def test_the_command_exists_with_a_docstring(self):
        command = Client.PokemonXDCommandProcessor._cmd_storybyte
        self.assertTrue(command.__doc__)
        self.assertIn("!storybyte 27", command.__doc__)
