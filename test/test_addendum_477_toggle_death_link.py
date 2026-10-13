"""ADDENDUM 477 (2026-10-13) -- /toggledeathlink. Player: "can we make a /toggledeathlink command that turns on/off
the deathlink feature"."""
from __future__ import annotations

import pathlib
import unittest
from types import SimpleNamespace
from unittest import mock

CLIENT = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")


class TestTheCommand(unittest.TestCase):
    def _processor(self):
        from .. import Client, ram_client

        bridge = ram_client.DeathLinkBridge(enabled=False)
        bridge._ours = True
        ctx = SimpleNamespace(death_link_bridge=bridge, death_link_override=None, slot=1, saved=0)
        ctx.update_death_link = mock.AsyncMock()
        ctx._save_local_state = lambda: setattr(ctx, "saved", ctx.saved + 1)
        processor = SimpleNamespace(ctx=ctx)
        return Client, ctx, processor

    def _run(self, *args):
        Client, ctx, processor = self._processor()
        with mock.patch.object(Client, "isinstance", create=True, side_effect=lambda o, t: True), \
                mock.patch.object(Client.Utils, "async_start"):
            for arg_list in args:
                Client.PokemonXDCommandProcessor._cmd_toggledeathlink(processor, *arg_list)
        return ctx

    def test_flip_and_explicit(self) -> None:
        ctx = self._run(())
        self.assertTrue(ctx.death_link_bridge.enabled)
        self.assertTrue(ctx.death_link_override)
        self.assertFalse(ctx.death_link_bridge._ours, "a stale fence is cleared on a switch")
        ctx = self._run(("off",))
        self.assertFalse(ctx.death_link_bridge.enabled)
        ctx = self._run(("on",), ("on",))
        self.assertTrue(ctx.death_link_bridge.enabled)
        self.assertEqual(2, ctx.saved)

    def test_bad_argument_changes_nothing(self) -> None:
        ctx = self._run(("maybe",))
        self.assertFalse(ctx.death_link_bridge.enabled)
        self.assertIsNone(ctx.death_link_override)


class TestPersistenceAndPrecedence(unittest.TestCase):
    def test_saved_and_loaded(self) -> None:
        self.assertIn('"death_link_override": getattr(self, "death_link_override", None)', CLIENT)
        self.assertIn('slot_state.get("death_link_override")', CLIENT)

    def test_it_outranks_the_seed_after_the_state_loads(self) -> None:
        body = CLIENT.split('self.death_link_from_seed = bool(slot_data.get("death_link", False))', 1)[1]
        self.assertLess(body.index("self._load_local_state()"),
                        body.index("if self.death_link_override is not None"))

    def test_a_disabled_bridge_neither_sends_nor_receives(self) -> None:
        from .. import ram_client
        off = ram_client.DeathLinkBridge(enabled=False)
        self.assertIsNone(off.receive(0x80400000, "x"))
        self.assertEqual((False, None), off.poll(0x80400000, True, whiteouts=1))


if __name__ == "__main__":
    unittest.main()
