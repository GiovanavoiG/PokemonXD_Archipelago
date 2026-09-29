"""ADDENDUM 253 (2026-09-17) -- a Bag slot is a u16, and the retry loop was overflowing it.

Player, with a screenshot from a live run:

    Failed to deliver Chesto Berry (index 2xx) -- will keep retrying silently every poll.
    ...
    write_slot(slot.address, item_id, slot.quantity + quantity)
    struct.error: 'H' format requires 0 <= number <= 65535

`give_item` packed `slot.quantity + quantity` straight into a `>HH` with nothing bounding the sum.

THE PACK ERROR IS THE SYMPTOM. Nothing in a real playthrough puts sixty thousand berries in a Bag; the confirm
loop does. `give_items`' "reverted, or never took" branch called `give_item` again on EVERY poll for as long as
an item stayed unconfirmed, and each call added to the slot. At one poll a second, 65535 is about eighteen
hours -- and the screenshot's item index was in the 200s.

So both ends are fixed, and the second is the one that matters: the arithmetic saturates instead of raising,
and a slot that physically cannot grow stops being retried.
"""
import struct
import unittest

from .. import ram_client as rc


class _FakeMemory:
    """One pocket of 4-byte slots, backed by a dict, standing in for Dolphin."""

    def __init__(self, base=0x80479000, slots=20):
        self.base = base
        self.data = bytearray(slots * 4)
        self.writes = 0

    def read(self, address, length):
        off = address - self.base
        return bytes(self.data[off:off + length])

    def write(self, address, payload):
        off = address - self.base
        self.data[off:off + len(payload)] = payload
        self.writes += 1

    def put(self, index, item_id, quantity):
        struct.pack_into(">HH", self.data, index * 4, item_id, quantity)


class _MemoryPatch(unittest.TestCase):
    def setUp(self):
        self.mem = _FakeMemory()
        self._read, self._write = rc.read_bytes, rc.write_bytes
        rc.read_bytes = self.mem.read
        rc.write_bytes = self.mem.write

    def tearDown(self):
        rc.read_bytes, rc.write_bytes = self._read, self._write


class TestTheCrashIsGone(_MemoryPatch):
    def test_the_exact_reported_arithmetic_no_longer_raises(self) -> None:
        """65535 + 1. This is the line from the traceback."""
        self.mem.put(0, 42, 65535)
        rc.give_item(self.mem.base, 42, 1, 20)   # used to raise struct.error
        self.assertEqual(65535, rc.find_item_quantity(self.mem.base, 20, 42))

    def test_an_add_that_would_overflow_saturates(self) -> None:
        self.mem.put(0, 42, 65530)
        rc.give_item(self.mem.base, 42, 50, 20)
        self.assertEqual(rc.BAG_SLOT_QUANTITY_MAX, rc.find_item_quantity(self.mem.base, 20, 42))

    def test_an_ordinary_add_is_untouched(self) -> None:
        self.mem.put(0, 42, 3)
        rc.give_item(self.mem.base, 42, 2, 20)
        self.assertEqual(5, rc.find_item_quantity(self.mem.base, 20, 42))

    def test_write_slot_clamps_rather_than_raising(self) -> None:
        rc.write_slot(self.mem.base, 42, 999_999)
        self.assertEqual(rc.BAG_SLOT_QUANTITY_MAX, rc.find_item_quantity(self.mem.base, 20, 42))
        rc.write_slot(self.mem.base, 42, -5)
        self.assertEqual(0, struct.unpack_from(">HH", self.mem.data, 0)[1])

    def test_a_fresh_slot_still_takes_the_quantity_given(self) -> None:
        rc.give_item(self.mem.base, 77, 4, 20)
        self.assertEqual(4, rc.find_item_quantity(self.mem.base, 20, 77))

    def test_clear_item_still_empties_a_saturated_slot(self) -> None:
        self.mem.put(0, 42, rc.BAG_SLOT_QUANTITY_MAX)
        self.assertTrue(rc.clear_item(self.mem.base, 20, 42))
        self.assertEqual(0, rc.find_item_quantity(self.mem.base, 20, 42))


class TestTheSaturationProbe(_MemoryPatch):
    def test_it_is_false_for_an_ordinary_slot(self) -> None:
        self.mem.put(0, 42, 12)
        self.assertFalse(rc.bag_slot_is_saturated(self.mem.base, 20, 42))

    def test_it_is_false_for_an_absent_item(self) -> None:
        self.assertFalse(rc.bag_slot_is_saturated(self.mem.base, 20, 42))

    def test_it_is_true_at_the_maximum(self) -> None:
        self.mem.put(0, 42, rc.BAG_SLOT_QUANTITY_MAX)
        self.assertTrue(rc.bag_slot_is_saturated(self.mem.base, 20, 42))

    def test_the_maximum_is_the_field_width_not_a_guess_about_the_game(self) -> None:
        """XD's own per-item ceiling is not known to this project and is deliberately not invented. 0xFFFF is
        what the four-byte slot can physically hold; if the game clamps lower on its own, the probe simply
        never fires."""
        self.assertEqual(0xFFFF, rc.BAG_SLOT_QUANTITY_MAX)


class TestTheRootCause(_MemoryPatch):
    """WHY a slot reached 65535, reproduced. This is the half worth keeping: the pack error was a seatbelt
    failing, and this is the crash it was failing to prevent."""

    CHESTO = 134   # any real berry id, 133-175 -- the shared Poke Ball / TM / Berries array

    def setUp(self):
        super().setUp()
        self.block = 0x80479000
        self.array = self.block + rc.POKEBALL_POCKET_OFFSET
        self.mem.base = self.array
        self.mem.data = bytearray(rc.POKEBALL_POCKET_ARRAY_SLOT_COUNT * 4)

    def test_the_write_window_and_the_read_window_are_different_slots(self) -> None:
        """Both are right on their own. Together they are the bug."""
        write_base, _ = rc.resolve_item_pocket(self.block, self.CHESTO)
        read_base, read_slots = rc.resolve_item_read_window(self.block, self.CHESTO)
        self.assertEqual(82, (write_base - self.array) // 4, "writes go into the slot-82 berry sub-window")
        self.assertEqual(0, (read_base - self.array) // 4, "reads cover the whole array (ADDENDUM 222/231)")
        self.assertEqual(rc.POKEBALL_POCKET_ARRAY_SLOT_COUNT, read_slots)

    def test_one_id_really_does_end_up_in_two_slots(self) -> None:
        """The game's own add code fills from slot 0; this client writes at 82."""
        self.mem.put(3, self.CHESTO, 5)          # the player already owns five
        write_base, write_slots = rc.resolve_item_pocket(self.block, self.CHESTO)
        rc.give_item(write_base, self.CHESTO, 1, write_slots)
        holding = [i for i in range(rc.POKEBALL_POCKET_ARRAY_SLOT_COUNT)
                   if struct.unpack_from(">HH", self.mem.data, i * 4)[0] == self.CHESTO]
        self.assertEqual([3, 82], holding)

    def test_the_confirm_now_sees_the_write_wherever_it_landed(self) -> None:
        """Before ADDENDUM 253 `find_item_quantity` returned the FIRST match -- 5, forever, however much slot
        82 grew. The confirm compares `current >= baseline + quantity`, so it never confirmed, `give_items`
        re-wrote every poll, and slot 82 climbed by one a second."""
        self.mem.put(3, self.CHESTO, 5)
        write_base, write_slots = rc.resolve_item_pocket(self.block, self.CHESTO)
        read_base, read_slots = rc.resolve_item_read_window(self.block, self.CHESTO)

        baseline = rc.find_item_quantity(read_base, read_slots, self.CHESTO)
        self.assertEqual(5, baseline)
        rc.give_item(write_base, self.CHESTO, 1, write_slots)
        self.assertGreaterEqual(rc.find_item_quantity(read_base, read_slots, self.CHESTO), baseline + 1)

    def test_the_old_first_match_reading_would_have_looped_forever(self) -> None:
        """Stated as the counterfactual it is, so the reason for summing survives the change."""
        self.mem.put(3, self.CHESTO, 5)
        write_base, write_slots = rc.resolve_item_pocket(self.block, self.CHESTO)
        read_base, read_slots = rc.resolve_item_read_window(self.block, self.CHESTO)

        def first_match_only():
            for slot in rc.read_pocket(read_base, read_slots):
                if slot.item_id == self.CHESTO:
                    return slot.quantity
            return 0

        for _ in range(10):
            rc.give_item(write_base, self.CHESTO, 1, write_slots)
        self.assertEqual(5, first_match_only(), "the old reading never moved")
        self.assertEqual(15, rc.find_item_quantity(read_base, read_slots, self.CHESTO))

    def test_clear_item_removes_every_slot_holding_the_id(self) -> None:
        """The other half of summing. A clear that left a second slot behind would read as a fresh pickup on
        the next poll and credit a check nobody earned -- the one outcome that cannot be taken back."""
        self.mem.put(3, self.CHESTO, 5)
        self.mem.put(82, self.CHESTO, 2)
        self.assertTrue(rc.clear_item(self.array, rc.POKEBALL_POCKET_ARRAY_SLOT_COUNT, self.CHESTO))
        self.assertEqual(0, rc.find_item_quantity(self.array, rc.POKEBALL_POCKET_ARRAY_SLOT_COUNT, self.CHESTO))

    def test_saturation_asks_about_a_SLOT_not_the_total(self) -> None:
        """`give_item` writes into one slot, so the question is whether that slot can grow. Two slots summing
        past the ceiling are still growable."""
        self.mem.put(3, self.CHESTO, 40000)
        self.mem.put(82, self.CHESTO, 40000)
        self.assertFalse(rc.bag_slot_is_saturated(self.array, rc.POKEBALL_POCKET_ARRAY_SLOT_COUNT, self.CHESTO))
        self.mem.put(82, self.CHESTO, rc.BAG_SLOT_QUANTITY_MAX)
        self.assertTrue(rc.bag_slot_is_saturated(self.array, rc.POKEBALL_POCKET_ARRAY_SLOT_COUNT, self.CHESTO))


class TestTheRetryLoopStops(unittest.TestCase):
    """Client.py cannot be imported in this sandbox (CommonClient -> MultiServer -> websockets.extensions) --
    the documented limitation test_addendum_109 and test_addendum_181 both work around -- so the branch is
    checked over the AST."""

    @classmethod
    def setUpClass(cls) -> None:
        import ast
        import pathlib

        cls.source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text("utf-8")
        cls.tree = ast.parse(cls.source)

    def test_the_unconfirmed_branch_asks_whether_a_retry_could_change_anything(self) -> None:
        self.assertIn("bag_slot_is_saturated(read_base, read_slots, game_item_id)", self.source)

    def test_the_saturated_path_marks_the_item_delivered(self) -> None:
        """ADDENDUM 44: an item is never left blocked. Giving up silently would be the other way to get this
        wrong -- the branch both stops retrying AND finishes the item."""
        import ast

        func = next(n for n in ast.walk(self.tree)
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == "give_items")
        saturated = [n for n in ast.walk(func)
                     if isinstance(n, ast.If) and "bag_slot_is_saturated" in ast.dump(n.test)]
        self.assertEqual(1, len(saturated), "exactly one saturation branch")
        body = ast.dump(ast.Module(body=saturated[0].body, type_ignores=[]))
        self.assertIn("delivered", body)
        self.assertIn("logger", body, "the player is told -- a saturated slot is the only evidence left")

    def test_the_retry_only_happens_in_the_other_arm(self) -> None:
        """The whole point: `give_item` must no longer be reachable on a poll where the slot cannot grow."""
        import ast

        func = next(n for n in ast.walk(self.tree)
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == "give_items")
        saturated = next(n for n in ast.walk(func)
                         if isinstance(n, ast.If) and "bag_slot_is_saturated" in ast.dump(n.test))
        self.assertTrue(saturated.orelse, "the retry belongs in the else arm")
        self.assertIn("give_item", ast.dump(ast.Module(body=saturated.orelse, type_ignores=[])))
        self.assertNotIn("give_item", ast.dump(ast.Module(body=saturated.body, type_ignores=[])))


if __name__ == "__main__":
    unittest.main()
