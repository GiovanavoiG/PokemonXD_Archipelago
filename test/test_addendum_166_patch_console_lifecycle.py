"""ADDENDUM 166 (2026-09-13): the patch console is released when the patch ends.

Player request: "Make the patch console not connect to the server - let it end with 'Patch Complete. Press
Enter to close.'"

The console never connected to anything. `_ensure_visible_console()` repoints THIS process's streams -- and
this process is the Archipelago Launcher -- so the redirection outlived the patch and the window titled
"Pokemon XD Patch - Progress" went on to catch the client's own server output whenever the player started the
client later in the same Launcher session. These tests pin the release: the exact closing message, that the
saved streams come back, that only the handles this module opened get closed, and that tidying up can never
turn a successful patch into a failure."""
from __future__ import annotations

import io
import unittest

from .. import launcher_patch as lp

SUCCESS_MESSAGE = "\nPatch Complete. Press Enter to close."
FAILURE_MESSAGE = "\nPatch FAILED. Press Enter to close."


class _Stream(io.StringIO):
    """A stand-in that records whether it was closed, so 'did the release close the right handle' is
    answerable."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name_tag = name
        self.closed_flag = False
        self.captured = ""

    def close(self) -> None:
        # Snapshot before closing: the release step legitimately closes the console handles, and a test still
        # needs to read back what was printed to them.
        if not self.closed_flag:
            self.captured = self.getvalue()
        self.closed_flag = True
        super().close()


class _ConsoleFixture:
    """Simulates the state `_ensure_visible_console()` leaves behind on Windows, without any of the ctypes.
    `input()` is stubbed because a test run has no console to answer the prompt."""

    def __init__(self, *, allocated: bool = True, original_stdout=None, input_raises=None) -> None:
        self.allocated = allocated
        self.original_stdout = original_stdout if original_stdout is not None else _Stream("original stdout")
        self.original_stderr = _Stream("original stderr")
        self.original_stdin = _Stream("original stdin")
        self.console_stdout = _Stream("CONOUT$ stdout")
        self.console_stderr = _Stream("CONOUT$ stderr")
        self.console_stdin = _Stream("CONIN$")
        self.input_raises = input_raises
        self.input_calls = 0

    def __enter__(self) -> "_ConsoleFixture":
        import sys

        self._sys = sys
        self._saved = (sys.stdout, sys.stderr, sys.stdin)
        self._saved_state = dict(lp._console_state)
        self._saved_input = lp.__builtins__["input"] if isinstance(lp.__builtins__, dict) else None

        lp._console_state.clear()
        if self.allocated:
            lp._console_state.update({
                "allocated": True,
                "stdout": self.original_stdout,
                "stderr": self.original_stderr,
                "stdin": self.original_stdin,
            })
            sys.stdout, sys.stderr, sys.stdin = (
                self.console_stdout, self.console_stderr, self.console_stdin)

        def _fake_input(*args, **kwargs):
            self.input_calls += 1
            if self.input_raises is not None:
                raise self.input_raises
            return ""

        import builtins
        self._real_input = builtins.input
        builtins.input = _fake_input
        return self

    def __exit__(self, *exc) -> None:
        import builtins
        builtins.input = self._real_input
        self._sys.stdout, self._sys.stderr, self._sys.stdin = self._saved
        lp._console_state.clear()
        lp._console_state.update(self._saved_state)

    @property
    def console_output(self) -> str:
        stream = self.console_stdout
        return stream.captured if stream.closed_flag else stream.getvalue()


class TestReleasingTheConsole(unittest.TestCase):
    def test_it_prints_the_exact_message_the_player_asked_for(self) -> None:
        with _ConsoleFixture() as fixture:
            lp._release_console(SUCCESS_MESSAGE)
            printed = fixture.console_output
        self.assertIn("Patch Complete. Press Enter to close.", printed)

    def test_it_waits_for_enter_before_closing(self) -> None:
        with _ConsoleFixture() as fixture:
            lp._release_console(SUCCESS_MESSAGE)
        self.assertEqual(fixture.input_calls, 1)

    def test_it_puts_the_real_streams_back(self) -> None:
        """The whole point: the Launcher's own streams must be exactly what they were before patching, so a
        client started later in the same session is not writing into the patch window."""
        import sys

        with _ConsoleFixture() as fixture:
            lp._release_console(SUCCESS_MESSAGE)
            self.assertIs(sys.stdout, fixture.original_stdout)
            self.assertIs(sys.stderr, fixture.original_stderr)
            self.assertIs(sys.stdin, fixture.original_stdin)

    def test_it_closes_only_the_handles_this_module_opened(self) -> None:
        with _ConsoleFixture() as fixture:
            lp._release_console(SUCCESS_MESSAGE)
        self.assertTrue(fixture.console_stdout.closed_flag)
        self.assertTrue(fixture.console_stderr.closed_flag)
        self.assertTrue(fixture.console_stdin.closed_flag)
        self.assertFalse(fixture.original_stdout.closed_flag, "the pre-existing stream must survive")
        self.assertFalse(fixture.original_stderr.closed_flag)
        self.assertFalse(fixture.original_stdin.closed_flag)

    def test_a_none_stdout_is_restored_as_none(self) -> None:
        """A frozen, GUI-launched Launcher can legitimately have had no stdout at all. Restoring None is
        correct -- `print()` against a None sys.stdout is a documented no-op, not an error."""
        import sys

        with _ConsoleFixture(original_stdout=None):
            lp._console_state["stdout"] = None
            lp._release_console(SUCCESS_MESSAGE)
            self.assertIsNone(sys.stdout)
            print("this must not raise")

    def test_it_clears_its_state_so_a_second_call_is_a_no_op(self) -> None:
        with _ConsoleFixture() as fixture:
            lp._release_console(SUCCESS_MESSAGE)
            self.assertEqual(lp._console_state, {})
            lp._release_console(SUCCESS_MESSAGE)
        self.assertEqual(fixture.input_calls, 1, "the second call must not prompt again")

    def test_it_does_nothing_when_no_console_was_allocated(self) -> None:
        """A dev terminal the process already had is somebody else's -- never prompted at, never freed."""
        import sys

        with _ConsoleFixture(allocated=False) as fixture:
            before = (sys.stdout, sys.stderr, sys.stdin)
            lp._release_console(SUCCESS_MESSAGE)
            self.assertEqual((sys.stdout, sys.stderr, sys.stdin), before)
        self.assertEqual(fixture.input_calls, 0)

    def test_an_unanswerable_prompt_does_not_hang_or_raise(self) -> None:
        """If CONIN$ could not be opened, `input()` raises. Falling through to tidy up beats hanging a window
        the player cannot answer."""
        import sys

        with _ConsoleFixture(input_raises=EOFError()) as fixture:
            lp._release_console(SUCCESS_MESSAGE)
            self.assertIs(sys.stdout, fixture.original_stdout)
        self.assertEqual(lp._console_state, {})


class _FakePatcher:
    def __init__(self, raises: "BaseException | None" = None) -> None:
        self.raises = raises
        self.calls = 0

    def apply_patch(self, source, output, seed, overwrite=False):
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return {"output": str(output), "trainer_slots_patched": 7}


class _SpyRelease:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def __call__(self, message: str) -> None:
        self.messages.append(message)

    def __enter__(self) -> "_SpyRelease":
        self._orig = lp._release_console
        lp._release_console = self
        return self

    def __exit__(self, *exc) -> None:
        lp._release_console = self._orig


class TestBothPathsReleaseTheConsole(unittest.TestCase):
    def test_success_ends_with_patch_complete(self) -> None:
        patcher = _FakePatcher()
        with _SpyRelease() as spy:
            result = lp._apply_with_visible_progress(patcher, "in.iso", "out.iso", "seed.appxd", True)
        self.assertEqual(result["trainer_slots_patched"], 7)
        self.assertEqual(spy.messages, [SUCCESS_MESSAGE])

    def test_failure_also_releases_and_still_re_raises(self) -> None:
        """`prompt_and_patch` reports the failure in a message box. Releasing the console must not swallow
        the exception that gets it there."""
        patcher = _FakePatcher(raises=RuntimeError("disc image is not a GameCube ISO"))
        with _SpyRelease() as spy:
            with self.assertRaises(RuntimeError):
                lp._apply_with_visible_progress(patcher, "in.iso", "out.iso", "seed.appxd", True)
        self.assertEqual(spy.messages, [FAILURE_MESSAGE])

    def test_the_console_is_released_exactly_once_per_patch(self) -> None:
        patcher = _FakePatcher()
        with _SpyRelease() as spy:
            lp._apply_with_visible_progress(patcher, "in.iso", "out.iso", "seed.appxd", True)
        self.assertEqual(len(spy.messages), 1)

    def test_the_patch_itself_still_runs(self) -> None:
        patcher = _FakePatcher()
        with _SpyRelease():
            lp._apply_with_visible_progress(patcher, "in.iso", "out.iso", "seed.appxd", True)
        self.assertEqual(patcher.calls, 1)


class TestConsoleOwnership(unittest.TestCase):
    def test_has_console_is_false_off_windows(self) -> None:
        """The ctypes path is Windows-only; everywhere else this must answer False rather than explode."""
        import sys

        if sys.platform == "win32":
            self.skipTest("this asserts the non-Windows answer")
        self.assertFalse(lp._has_console())

    def test_the_module_exposes_the_release_step(self) -> None:
        """Guards against the release being inlined back into the caller, where it would be easy to lose on
        one of the two exit paths."""
        self.assertTrue(callable(lp._release_console))


if __name__ == "__main__":
    unittest.main()
