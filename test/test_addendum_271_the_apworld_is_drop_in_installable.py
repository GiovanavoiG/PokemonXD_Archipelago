"""ADDENDUM 271 (2026-09-18): the apworld has to survive being dragged into a folder.

Player, relaying another player: *"the XD client isn't showing in launcher and yaml isnt generating - they
dropped the apworld into the custom_worlds folder but did not open the file. Can we make it so that everything
works even if the file is dropped in rather than opened?"*

Both symptoms at once -- no Launcher button AND no template -- mean one thing: **the world module never
imported.** Components are registered by the module, and so is the options dataclass the template is built
from, so a world that does not load produces neither and says nothing about it.

## What "opening" does that dropping does not

`LauncherComponents._install_apworld` does two things beyond copying:

    apworld_name = module_name + ".apworld"     # RENAMES the file to match the folder inside the zip
    target = pathlib.Path(worlds.user_folder) / apworld_name   # and picks the folder AP actually scans

Dropping the file in does neither, and both of them can be wrong on their own:

**1. The filename IS the module name.** `worlds/__init__.py` indexes an apworld as
`WorldSource(path, is_zip=True)`, whose `name` is `Path(self.path).stem`, and `load()` calls
`importlib.import_module(f".{self.name}", "worlds")`. So `PokemonXD_Archipelago.apworld` is imported as
`worlds.PokemonXD_Archipelago`, which does not exist inside the zip. Measured, with the real shipped file
renamed: `ModuleNotFoundError: No module named 'worlds.PokemonXD_Archipelago'`, logged and swallowed --
`WorldSource.load` catches everything, on the reasoning that one bad world should not take the Launcher down.
Correct in general; invisible here.

**2. `custom_worlds` is not always the folder.**

    user_folder = user_path("worlds") if user_path() != local_path() else user_path("custom_worlds")

and `user_path()` is `local_path()` only when the program folder is WRITABLE. So a portable/source install
scans `custom_worlds`, and a normal Windows install under `Program Files` (or a frozen macOS app) scans
`~/Archipelago/worlds` instead -- while the `custom_worlds` folder in the program directory, which is the one
a person naturally finds, is never read at all.

## So: can we make a dropped-in file work regardless?

**No, and it is worth writing down why rather than trying.** Both decisions are made by Archipelago before any
byte of this world is imported -- there is no hook, because the failure IS the absence of the import. The one
mechanism that could paper over a wrong filename is shipping alias directories inside the zip, and that breaks
the path that currently works: `_install_apworld` refuses any apworld whose zip does not contain exactly one
directory ("APWorld appears to be invalid or damaged"). Trading a working double-click for a guessed-at
filename is a bad trade.

What IS ours: the file we ship must be drop-in-VALID, and the instructions must not send people into either
trap. `docs/setup_en.md` said *"drop `pokemon_xd_apworld.apworld` into your `custom_worlds` folder"* -- a
filename whose stem is `pokemon_xd_apworld`, which is trap 1 exactly, next to the folder that is trap 2. Our
own guide was the instruction to do the broken thing.

This file guards the artifact. The guide is prose and cannot be asserted; the zip can.
"""
from __future__ import annotations

import json
import pathlib
import unittest
import zipfile

_WORLD_DIR = pathlib.Path(__file__).resolve().parent.parent
_MODULE_NAME = _WORLD_DIR.name


def _built_apworld() -> "pathlib.Path | None":
    """Where the shipped zip is, if it has been built.

    Two candidates because the test harness copies this package into the core's `worlds/` before running, so
    the sibling location only exists in the real source tree. `POKEMON_XD_BUILT_APWORLD` is what the build
    script sets, which is the run that actually matters -- the zip is checked at the moment it is produced
    rather than whenever someone happens to run the suite from the right directory."""
    import os

    override = os.environ.get("POKEMON_XD_BUILT_APWORLD")
    candidates = ([pathlib.Path(override)] if override else []) + [_WORLD_DIR.parent / f"{_MODULE_NAME}.apworld"]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


_BUILT = _built_apworld()


class TestTheManifestIsPresentAndValid(unittest.TestCase):
    """`archipelago.json` is optional on AP 0.6.x -- a missing one is logged and the world still loads -- and
    MANDATORY from 0.7.0, where `worlds/__init__.py` re-raises the `InvalidDataError` instead of logging it.
    It also carries the game name AP uses to notice that two installed copies are the same world; without it
    `apworld.game` is None, the duplicate check is skipped, and the second copy dies with a `RuntimeError`
    about the game already being registered rather than being passed over."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((_WORLD_DIR / "archipelago.json").read_text(encoding="utf-8"))

    def test_it_names_this_world(self) -> None:
        from .. import __init__ as world_module  # noqa: F401  -- import for the registered game name

        self.assertEqual("Pokemon XD Gale of Darkness", self.manifest["game"])

    def test_its_compatible_version_is_readable_by_the_core_that_ships_it(self) -> None:
        """`APContainer.read_contents` refuses a manifest whose `compatible_version` exceeds the running
        core's `container_version`. 7 is what AP's own `APWorldContainer.get_manifest` writes; on an older
        core it degrades to exactly the pre-manifest behaviour (logged, loads anyway), so it can never be
        worse than having no manifest at all."""
        from worlds.Files import container_version

        self.assertLessEqual(self.manifest["compatible_version"], container_version)

    def test_the_declared_minimum_core_version_is_not_above_the_core_we_test_against(self) -> None:
        """A minimum above the running core is a silent refusal to load -- `fail_world`, one log line, no
        Launcher button. Exactly the symptom this addendum is about, so it is worth a fence."""
        from Utils import tuplize_version, version_tuple

        minimum = self.manifest.get("minimum_ap_version")
        if minimum is None:
            self.skipTest("no minimum declared -- nothing to contradict")
        self.assertLessEqual(tuplize_version(minimum), version_tuple)


@unittest.skipUnless(_BUILT is not None, "no built .apworld found -- the build script sets POKEMON_XD_BUILT_APWORLD so this always runs at build time")
class TestTheBuiltApworldIsDropInInstallable(unittest.TestCase):
    """Everything here is about the ZIP as shipped, because that is the thing a player drags."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.zip = zipfile.ZipFile(_BUILT)
        cls.names = cls.zip.namelist()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.zip.close()

    def test_the_filename_matches_the_directory_inside_it(self) -> None:
        """The whole of trap 1. `WorldSource.name` is the file stem and `load()` imports `worlds.<that>`, so
        these two strings must be the same or a dropped-in file cannot import."""
        self.assertEqual(_MODULE_NAME, _BUILT.stem,
                         "a dropped-in apworld is imported under its FILE name; rename the build output "
                         "rather than the directory")

    def test_there_is_exactly_one_top_level_directory(self) -> None:
        """Trap 1's other half, and the reason alias directories are not an option: `_install_apworld` rejects
        anything else outright, so a zip built to tolerate stray filenames could not be double-clicked."""
        tops = {name.split("/")[0] for name in self.names}
        self.assertEqual({_MODULE_NAME}, tops)

    def test_the_installer_would_accept_it(self) -> None:
        """`_install_apworld`'s own two checks, run here instead of found out in a message box: one directory
        whose name is a substring of the file stem, and an `__init__.py` it can open."""
        directories = [f.name for f in zipfile.Path(self.zip).iterdir() if f.is_dir()]
        self.assertEqual(1, len(directories))
        self.assertIn(directories[0], _BUILT.stem)
        self.zip.open(f"{directories[0]}/__init__.py").close()

    def test_the_manifest_ships_inside_the_zip(self) -> None:
        """`APContainer.read_contents` looks for `archipelago.json` at the root and then falls back to any
        entry ENDING with it, so `pokemon_xd/archipelago.json` is found -- and that placement is also where
        the folder-world path (`os.walk` of the world directory) looks, so one file serves both."""
        self.assertIn(f"{_MODULE_NAME}/archipelago.json", self.names)
        manifest = json.loads(self.zip.read(f"{_MODULE_NAME}/archipelago.json"))
        self.assertEqual("Pokemon XD Gale of Darkness", manifest["game"])

    def test_no_compiled_or_cache_files_were_packaged(self) -> None:
        """A stale `.pyc` in the zip is imported in preference to nothing at all and can shadow a source file
        that was edited after it -- the kind of thing that makes a build behave unlike its source tree."""
        junk = [n for n in self.names if n.endswith((".pyc", ".pyo")) or "__pycache__" in n]
        self.assertEqual([], junk)


class TestTheSetupGuideDoesNotTeachTheBrokenInstall(unittest.TestCase):
    """The guide is what the reporting player followed. Prose cannot be asserted, but the one string that was
    actively wrong can be kept from coming back."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = (_WORLD_DIR / "docs" / "setup_en.md").read_text(encoding="utf-8")

    def test_it_no_longer_names_a_filename_that_cannot_import(self) -> None:
        self.assertNotIn("pokemon_xd_apworld.apworld", self.text,
                         "that stem is not the module name, so a dropped-in file under it fails to import")

    def test_it_names_the_real_filename(self) -> None:
        self.assertIn(f"{_MODULE_NAME}.apworld", self.text)

    def test_it_mentions_the_other_folder_too(self) -> None:
        """`custom_worlds` alone is wrong for a non-portable install, which is the common Windows case."""
        self.assertIn("custom_worlds", self.text)
        self.assertIn("Archipelago\\worlds", self.text)
