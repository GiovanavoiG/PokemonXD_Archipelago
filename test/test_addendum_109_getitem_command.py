"""Regression coverage for ADDENDUM 109 (2026-09-10, player request, verbatim: "make it so the !getitem command
bypasses our holds and delivers the item to back immediately, without a second check").

WHY THIS DOES NOT IMPORT `Client.py` DIRECTLY: same documented sandbox limitation as test_sync_travel_
locations.py's own module docstring -- `Client.py` -> `CommonClient` -> `MultiServer` -> `websockets.extensions`
fails to import in this sandbox, independent of anything this addendum changed. This is a text-level structural
sanity check confirming the new `!getitem` command exists, is wired to its implementation, and that the
implementation genuinely skips give_items()'s two safety holds (no reference to the battle-state tracker or the
confirm-streak constant inside its own body) -- it can't exercise the async delivery logic end-to-end in this
sandbox, same disclosed limitation as every other live-RAM mechanism in this project."""
from __future__ import annotations

import os
import re
import unittest


class TestGetItemCommandWiring(unittest.TestCase):
    def setUp(self) -> None:
        client_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Client.py")
        with open(client_path, encoding="utf-8") as f:
            self.source = f.read()

    def test_cmd_getitem_is_defined_on_the_command_processor(self) -> None:
        self.assertIn("def _cmd_getitem(self, *name_words: str) -> None:", self.source)

    def test_cmd_getitem_calls_force_deliver_pending_items(self) -> None:
        self.assertIn("force_deliver_pending_items(self.ctx,", self.source)

    def test_force_deliver_pending_items_is_defined(self) -> None:
        self.assertIn(
            "def force_deliver_pending_items(ctx: PokemonXDContext, name_filter: str = \"\") -> None:", self.source
        )

    def _force_deliver_body(self) -> str:
        # Isolate just force_deliver_pending_items's own CODE (its docstring stripped out, since the docstring
        # deliberately explains battle_state_tracker/confirm-streak BY NAME as the things it's skipping -- that
        # prose would otherwise defeat the "never mentions X" checks below) -- up to the next top-level `def `/
        # `class ` at column 0, so those checks can't accidentally match text belonging to a neighboring
        # function like give_items() either.
        start = self.source.index("def force_deliver_pending_items(ctx: PokemonXDContext")
        rest = self.source[start:]
        match = re.search(r"\n(?:def |class |async def )", rest[1:])
        full = rest[: match.start() + 1] if match else rest
        # Strip the triple-quoted docstring immediately following the `def` line.
        return re.sub(r'"""(?:[^"]|"(?!""))*"""', "", full, count=1, flags=re.DOTALL)

    def test_force_deliver_pending_items_never_checks_the_battle_state_tracker(self) -> None:
        # The whole point of this addendum: unlike give_items(), this function must NOT wait on
        # ctx.battle_state_tracker before writing -- that's one of the two "holds" the player asked to bypass.
        body = self._force_deliver_body()
        self.assertNotIn("battle_state_tracker", body)

    def test_force_deliver_pending_items_never_uses_the_confirm_streak_bookkeeping(self) -> None:
        # The other "hold": no multi-poll re-verification. It's fine (expected, even) for this function to POP
        # stale confirm-streak/baseline entries left over from a give_items() attempt -- but it must never
        # itself set or read them as part of deciding whether an item counts as delivered.
        body = self._force_deliver_body()
        self.assertNotIn("_delivery_confirm_streak[idx] =", body)
        self.assertNotIn("_delivery_confirm_streak.get(idx", body)
        self.assertNotIn("_delivery_pending_baseline[idx] =", body)
        self.assertIn("_delivery_confirm_streak.pop(idx, None)", body)  # cleanup of stale state IS expected
        self.assertIn("_delivery_pending_baseline.pop(idx, None)", body)

    def test_force_deliver_pending_items_marks_delivered_after_a_single_write_attempt(self) -> None:
        # No re-read/verify call (ram_client.give_item_verified / find_item_quantity) anywhere in this
        # function's body -- exactly one ram_client.give_item() write, then immediately marked given.
        body = self._force_deliver_body()
        self.assertIn("ram_client.give_item(", body)
        self.assertNotIn("give_item_verified", body)
        self.assertNotIn("find_item_quantity", body)
        self.assertIn("ctx.given_item_indices.add(idx)", body)

    def test_getitem_command_is_documented_with_a_usage_example(self) -> None:
        """RETARGETED 2026-09-26: the player rewrote `!getitem`'s help text in their own words, and the
        worked example went with it -- the help now reads "Notable items not in pool: 99 Master Balls, 99
        Rare Candies", which says what the command is FOR but not how to type it.

        The command still takes `*name_words` and still fuzzy-matches, so a usage line is still true; whether
        the help carries one is the player's call. What this test pins now is the thing that made the example
        worth having: the command really does take free-form words rather than an id."""
        import ast

        tree = ast.parse(self.source)
        node = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "_cmd_getitem")
        self.assertIsNotNone(node.args.vararg, "!getitem takes free-form name words, not an index")
        self.assertEqual(node.args.vararg.arg, "name_words")
        self.assertTrue(ast.get_docstring(node), "it must still have help text of some kind")


if __name__ == "__main__":
    unittest.main()
