"""ADDENDUM 165 (2026-09-13), revised 2026-10-30: the Launcher component and what a `.appxd` does.

  * opening a `.appxd` starts the CLIENT with that seed -- the client patches the ISO and boots it in Dolphin
    itself (Client.patch_and_boot), so the standalone patch dialogs (`prompt_and_patch`) are not used;
  * there is no description below "Pokemon XD Client" in the Archipelago Launcher.

The original split (patch, then stop) existed because the patched ISO still had to be loaded in Dolphin by
hand, so a client started straight after patching had nothing to hook. Now that the client boots Dolphin on the
patched copy, that reason is gone."""
from __future__ import annotations

import unittest

import importlib

# The world package itself, whatever it is mounted as -- `from .. import __init__` resolves to the
# dunder method-wrapper, not the module, and the suite is run both as `pokemon_xd.test` (-t apworld_v2)
# and as `apworld_v2.pokemon_xd.test`, so the parent is resolved relatively rather than by name.
world_module = importlib.import_module("..", __package__)


class _Spy:
    """Records calls instead of making them. `raises` lets a test make the call fail the way the real one
    would (a cancelled dialog, or a missing dolphin_memory_engine)."""

    def __init__(self, result=None, raises: "BaseException | None" = None) -> None:
        self.calls: list[tuple] = []
        self.result = result
        self.raises = raises

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.raises is not None:
            raise self.raises
        return self.result

    @property
    def called(self) -> bool:
        return bool(self.calls)


class _Patched:
    """Swaps out both halves of `launch_client_or_patch` plus `Utils.messagebox`, so nothing here touches a
    real dialog, a real ISO, or a real client."""

    def __init__(self, *, patch_result="C:/fake (AP).iso", client_raises=None) -> None:
        self.prompt_and_patch = _Spy(result=patch_result)
        self.launch_client = _Spy(raises=client_raises)
        self.messagebox = _Spy()

    def __enter__(self) -> "_Patched":
        import Utils

        from .. import launcher_patch

        self._orig = (launcher_patch.prompt_and_patch, world_module.launch_client, Utils.messagebox)
        launcher_patch.prompt_and_patch = self.prompt_and_patch
        world_module.launch_client = self.launch_client
        Utils.messagebox = self.messagebox
        return self

    def __exit__(self, *exc) -> None:
        import Utils

        from .. import launcher_patch

        launcher_patch.prompt_and_patch, world_module.launch_client, Utils.messagebox = self._orig


class TestASeedLaunchesTheClient(unittest.TestCase):
    def test_opening_a_seed_starts_the_client_with_it(self) -> None:
        with _Patched() as spies:
            world_module.launch_client_or_patch("C:/seeds/AP_12345_P1.appxd")
        self.assertEqual(spies.launch_client.calls, [(("C:/seeds/AP_12345_P1.appxd",), {})])

    def test_opening_a_seed_skips_the_standalone_patch_dialogs(self) -> None:
        with _Patched() as spies:
            world_module.launch_client_or_patch("C:/seeds/AP_12345_P1.appxd")
        self.assertFalse(spies.prompt_and_patch.called, "the client does the patching now")

    def test_a_missing_dolphin_memory_engine_is_reported_for_a_seed_too(self) -> None:
        with _Patched(client_raises=ImportError("No module named 'dolphin_memory_engine'")) as spies:
            world_module.launch_client_or_patch("C:/seeds/AP_12345_P1.appxd")
        self.assertTrue(spies.messagebox.called)


class TestTheClientStillConnects(unittest.TestCase):
    def test_no_arguments_connects_without_patching(self) -> None:
        with _Patched() as spies:
            world_module.launch_client_or_patch()
        self.assertEqual(spies.launch_client.calls, [((), {})], "the plain button must never start a patch")

    def test_a_non_seed_argument_is_treated_as_a_plain_launch(self) -> None:
        with _Patched() as spies:
            world_module.launch_client_or_patch("--some-launcher-arg")
        self.assertEqual(spies.launch_client.calls, [((), {})])

    def test_a_missing_dolphin_memory_engine_is_reported_not_silent(self) -> None:
        with _Patched(client_raises=ImportError("No module named 'dolphin_memory_engine'")) as spies:
            world_module.launch_client_or_patch()
        self.assertTrue(spies.messagebox.called)
        self.assertIn("dolphin_memory_engine", spies.messagebox.calls[0][0][1])


class TestTheLauncherComponent(unittest.TestCase):
    def _component(self):
        from worlds.LauncherComponents import components

        matches = [c for c in components if c.display_name == "Pokemon XD Client"]
        self.assertEqual(len(matches), 1, "there must be exactly one Pokemon XD Launcher component")
        return matches[0]

    def test_it_has_no_description_line(self) -> None:
        """No subtitle. Component's own signature defaults `description` to "", which the Launcher renders
        as no subtitle at all."""
        self.assertEqual(self._component().description, "")

    def test_it_still_handles_appxd_seed_files(self) -> None:
        component = self._component()
        self.assertTrue(component.handles_file("AP_12345_P1_Player.appxd"))
        self.assertFalse(component.handles_file("AP_12345_P1_Player.zip"))

    def test_it_is_still_the_single_entry_point(self) -> None:
        self.assertIs(self._component().func, world_module.launch_client_or_patch)


if __name__ == "__main__":
    unittest.main()
