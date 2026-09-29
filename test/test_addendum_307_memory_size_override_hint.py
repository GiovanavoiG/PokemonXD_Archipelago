"""ADDENDUM 307 (2026-09-20) -- the memory-size override, and why it cannot be supported from here.

Player: "User reported not being able to connect the client to dolphin after enabling Enable Emulated Memory
Size Override in Dolphin. Any chance we can make this compatible by default, or an option if necessary?"

THE ANSWER IS NO, AND THE REASON IS STRUCTURAL. `dolphin_memory_engine` does not ask Dolphin where its
emulated RAM is. It walks the process's memory regions and matches one whose SIZE equals the size it expects
(`info.RegionSize == Common::GetMEM1Size()`, rounded to the next power of two). The override changes that
size, nothing matches, `hook()` returns false -- and that happens before any address this project knows about
is ever read. There is no constant here to widen and no argument to pass.

Upstream DME has a knob -- `GetMEM1Size()` reads `SConfig::getMEM1Size()`, a setting in its own Qt config the
user matches to Dolphin by hand. The Python binding is that library without the application, so it carries
the default and exposes nothing. Fixing this means an upstream change: a binding that exposes the size, or
reading Dolphin's own `SystemInfo` the way DME's master branch now does.

NOT SPECIFIC TO THIS WORLD -- The Wind Waker's official Archipelago setup guide instructs players to disable
the same setting. So what ships is the honest thing: the client names the setting, once, at the point it
fails, instead of leaving the player reading "is Dolphin running?" and hunting a problem that is not there.

WHAT THESE TESTS GUARD. That the hint exists and is actionable; that it is not spammed on every retry (the
common case is a client started before the emulator); that a success resets the counter; and -- the part
worth stating -- that nothing about the working path changed.
"""
from __future__ import annotations

import unittest

from .. import Client
from .. import ram_client


class TestTheHintItself(unittest.TestCase):
    def test_it_names_the_exact_setting(self) -> None:
        text = ram_client.DOLPHIN_MEMORY_OVERRIDE_HINT
        self.assertIn("Enable Emulated Memory Size Override", text)

    def test_it_says_where_to_find_it(self) -> None:
        self.assertIn("Advanced", ram_client.DOLPHIN_MEMORY_OVERRIDE_HINT)

    def test_it_says_what_to_do(self) -> None:
        self.assertIn("OFF", ram_client.DOLPHIN_MEMORY_OVERRIDE_HINT)

    def test_it_says_this_is_not_our_bug(self) -> None:
        """A player who thinks this world is broken goes looking in the wrong place."""
        self.assertIn("every Archipelago client", ram_client.DOLPHIN_MEMORY_OVERRIDE_HINT)


class TestItIsOfferedOnceAndLate(unittest.TestCase):
    def test_the_threshold_is_late_enough_to_not_fire_on_a_normal_start(self) -> None:
        """A client started before Dolphin fails a few times as a matter of course. Firing on the first
        failure would train players to ignore it."""
        self.assertGreaterEqual(Client.HOOK_FAILURES_BEFORE_OVERRIDE_HINT, 3)

    def test_and_early_enough_that_someone_is_still_watching(self) -> None:
        seconds = Client.HOOK_FAILURES_BEFORE_OVERRIDE_HINT * Client.POLL_INTERVAL_RETRY
        self.assertLessEqual(seconds, 120)

    def test_the_retry_loop_logs_it_at_most_once(self) -> None:
        source = open(Client.__file__, encoding="utf-8").read()
        self.assertIn("not ctx._override_hint_logged", source, "the guard must exist")
        self.assertIn("ctx._override_hint_logged = True", source, "and must latch")

    def test_a_successful_hook_resets_the_counter(self) -> None:
        """Otherwise a player who reconnects all session eventually gets the hint for no reason."""
        source = open(Client.__file__, encoding="utf-8").read()
        start = source.index("if ram_client.hook():")
        self.assertIn("ctx._hook_failures = 0", source[start:start + 400])


class TestEveryModuleActuallyCompiles(unittest.TestCase):
    """THE FENCE THIS ADDENDUM EXISTS FOR, and it matters more than the hint above.

    ADDENDUM 304 left an `await` inside a non-async function in `Client.py`. That is a SyntaxError -- the
    module cannot be imported at all, so the client would not start. It shipped, and a suite of 2,745 tests
    stayed green, because not one of them imported `Client`: the tests that examine it read it as SOURCE TEXT
    (`open(...).read()`), which a syntax error passes straight through.

    Byte-compiling every module in the package is the cheap, total fence for that whole class. It would have
    caught this the moment it was introduced, and it costs a fraction of a second."""

    def test_every_python_file_in_the_package_compiles(self) -> None:
        import pathlib
        import py_compile
        import tempfile

        root = pathlib.Path(Client.__file__).parent
        files = sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
        self.assertGreater(len(files), 30, "the sweep must actually be finding the package")
        with tempfile.TemporaryDirectory() as out:
            for path in files:
                target = str(pathlib.Path(out) / (path.stem + str(abs(hash(str(path)))) + ".pyc"))
                try:
                    py_compile.compile(str(path), cfile=target, doraise=True)
                except py_compile.PyCompileError as exc:
                    self.fail(f"{path.relative_to(root)} does not compile: {exc}")

    def test_the_client_module_imports(self) -> None:
        """Compiling proves syntax; importing proves the module body runs. Both have shipped broken before."""
        self.assertTrue(hasattr(Client, "dolphin_sync_task"))
        self.assertTrue(hasattr(Client, "_send_bump_awards"), "ADDENDUM 304's helper")

    def test_the_vanilla_travel_bump_is_awaitable(self) -> None:
        """The exact defect: it gained an `await` in ADDENDUM 304 without becoming async."""
        import inspect

        self.assertTrue(inspect.iscoroutinefunction(Client._bump_in_vanilla_travel))

    def test_its_caller_awaits_it(self) -> None:
        source = open(Client.__file__, encoding="utf-8").read()
        self.assertIn("await _bump_in_vanilla_travel(ctx)", source)
        self.assertNotIn("\n        _bump_in_vanilla_travel(ctx)", source)


class TestNothingWorkingChanged(unittest.TestCase):
    """The player's standing instruction: "Do not break anything that we have working"."""

    def test_the_memory_constants_are_untouched(self) -> None:
        self.assertEqual(0x80000000, ram_client.MEM1_START)
        self.assertEqual(0x1800000, ram_client.MEM1_SIZE)

    def test_hook_still_unhooks_first(self) -> None:
        """The ADDENDUM-era fix for repeated hook() calls getting stuck, still in place."""
        import inspect

        body = inspect.getsource(ram_client.hook)
        self.assertIn("un_hook", body)
        self.assertIn("is_hooked", body)

    def test_the_hint_is_only_a_message(self) -> None:
        """It must not gate, branch or suppress anything -- a diagnostic that changes behaviour is a bug."""
        import inspect

        source = inspect.getsource(Client)
        self.assertEqual(1, source.count("DOLPHIN_MEMORY_OVERRIDE_HINT"))

    def test_the_missing_package_message_is_still_separate(self) -> None:
        """Two different failures with two different remedies; merging them would help nobody."""
        self.assertNotEqual(ram_client.DOLPHIN_MISSING_MESSAGE,
                            ram_client.DOLPHIN_MEMORY_OVERRIDE_HINT)
        self.assertIn("pip install", ram_client.DOLPHIN_MISSING_MESSAGE)


if __name__ == "__main__":
    unittest.main()
