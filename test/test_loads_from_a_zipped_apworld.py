"""ADDENDUM 195. The world must load, and its data files must be readable, from a zipped .apworld.

Player: "That apworld is no longer generating a yaml."

WHAT HAPPENS. `game_data/shadow_regions._load()` read `data/shadow_pokemon_list.json` with `open()` on a path
built from `__file__`. From a loose checkout that works. From an installed `.apworld` it cannot: a zipimported
module's `__file__` points INSIDE the zip, and `open()` cannot read that. Its `except Exception: return []`
then turned the failure into an empty shadow list -- and that is not a quiet degradation, because rules.py
asserts at import time that the purification weights sum to `PURIFICATION_LOCATION_COUNT`:

    empty list -> weights {} -> sum 0 != 32 -> AssertionError at import
                             -> the world never registers
                             -> the Launcher has no options to build a YAML template from

So the symptom was "no yaml", three layers away from the cause.

THIS IS THE THIRD TIME. `game_data.load_json_data_file`'s own docstring records the first two, both found live
by the player rather than by any test, and both fixed by routing a caller through that helper. Two callers had
never been routed through it. The reason this keeps recurring is that every test in this suite imports the
world as a DIRECTORY, where the broken path works perfectly -- so no test could see it.

This one builds a real zip and imports it in a subprocess, which is the only arrangement that reproduces the
failure. It is slower than the rest of the suite and worth it.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile

_PACKAGE_ROOT = pathlib.Path(__file__).resolve().parent.parent          # .../pokemon_xd
_WORLD_PARENT = _PACKAGE_ROOT.parent                                    # .../apworld_v2

_PATCHER_PROBE = r'''
# ADDENDUM 260. The Launcher's ISO patch, reached exactly the way the Launcher reaches it, from inside a zip.
#
# ADDENDUM 250's rule, which this probe needs for the same reason the other one does: `unittest` must be in
# sys.modules BEFORE `worlds` is first imported, because that is the condition Archipelago's AP_TEST_WORLDS
# filter checks. Without it the LOOSE copy of pokemon_xd autoloads from the Archipelago root (which this probe
# needs on the path, because `pokemon_xd/__init__.py` imports BaseClasses) and the zip's copy then fails to
# register as a duplicate -- a harness failure that looks nothing like the bug under test.
import unittest  # noqa: F401 -- imported for its presence in sys.modules, not for its API
import sys

sys.path.insert(0, sys.argv[1])
from pokemon_xd import launcher_patch

patcher = launcher_patch._import_iso_patcher()
print("module", patcher.__name__)
print("package", patcher.__package__ or "<none>")
print("infile", "1" if ".apworld" in str(patcher.__file__) else "0")
# The two reaches into game_data that were dead when the patcher was imported rootless. Touched, not merely
# imported -- a module object that exists but holds nothing would still pass an import check.
print("shadowmoves", len(patcher._shadow_move_slots.ALL_SHADOW_MOVE_IDS))
print("martgroups", len(patcher._game_data_module("shop_stock").MART_GROUPS))
# The sibling tools modules, which were reached by a sys.path insert of a directory that does not exist
# inside a zip.
print("siblings", "1" if all(m.__package__ for m in
                             (patcher.rel_format, patcher.deck_format, patcher.species_index)) else "0")
print("applypatch", "1" if callable(patcher.apply_patch) else "0")
'''

_PROBE = r'''
import sys
# ADDENDUM 250: `unittest` must be in sys.modules BEFORE `worlds` is first imported, because that is the
# condition Archipelago's own AP_TEST_WORLDS filter checks (worlds/__init__.py). With the Archipelago root on
# the path -- which this probe needs, for BaseClasses -- the world directory would otherwise autoload the
# LOOSE copy of pokemon_xd and the zip's copy would then fail to register as a duplicate. The filter is AP's
# supported way to say "index these worlds and no others", so the loose copy is simply never indexed and the
# zip's copy is the only one that registers, which is what this test is actually about.
import unittest  # noqa: F401 -- imported for its presence in sys.modules, not for its API
sys.path.insert(0, sys.argv[1])
from pokemon_xd.game_data import shadow_regions
from pokemon_xd import locations, rules
print("shadows", len(shadow_regions.shadow_regions_in_graph_order()))
print("weightsum", sum(rules._PURIFICATION_WEIGHT_BY_REGION.values()))
print("expected", locations.PURIFICATION_LOCATION_COUNT)
print("species", len(rules._SPECIES_TO_REGION))
'''


def _build_zip(destination: str) -> str:
    path = os.path.join(destination, "pokemon_xd.apworld")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for root, dirs, filenames in os.walk(_PACKAGE_ROOT):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for filename in filenames:
                if filename.endswith(".pyc"):
                    continue
                full = os.path.join(root, filename)
                archive.write(full, os.path.relpath(full, _WORLD_PARENT))
    return path


def _probe_env() -> "dict[str, str]":
    """The subprocess environment both probes below need.

    EXTRACTED 2026-09-17 (ADDENDUM 260) from the first probe's own setup, unchanged in behaviour -- see the
    long comment inside `test_the_data_files_are_readable_from_inside_the_zip` for why each piece is here.
    In short: strip the loose checkout so the zip is the only copy that can answer, put the Archipelago root
    back (located from `BaseClasses`, not assumed, so it is right in either layout), and index nothing from
    `worlds/` so the loose copy cannot autoload and make the zip's copy a duplicate registration."""
    env = dict(os.environ)
    kept = [p for p in (env.get("PYTHONPATH", "") or "").split(os.pathsep)
            if p and os.path.realpath(p) != os.path.realpath(str(_WORLD_PARENT))]
    import BaseClasses

    archipelago_root = os.path.dirname(os.path.abspath(BaseClasses.__file__))
    if os.path.realpath(archipelago_root) != os.path.realpath(str(_WORLD_PARENT)):
        kept.append(archipelago_root)
    env["PYTHONPATH"] = os.pathsep.join(kept)
    env["AP_TEST_WORLDS"] = "generic"
    return env


class TestLoadsFromAZippedApworld(unittest.TestCase):
    def test_the_data_files_are_readable_from_inside_the_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = _build_zip(tmp)
            script = os.path.join(tmp, "probe.py")
            with open(script, "w", encoding="utf-8") as handle:
                handle.write(_PROBE)
            env = dict(os.environ)
            # The probe must NOT be able to fall back to the loose checkout.
            kept = [p for p in (env.get("PYTHONPATH", "") or "").split(os.pathsep)
                    if p and os.path.realpath(p) != os.path.realpath(str(_WORLD_PARENT))]
            # ========================================================================================
            # ADDENDUM 250 (2026-09-16): the probe needs the Archipelago root, and inherited it by luck
            # ========================================================================================
            # `pokemon_xd/__init__.py` opens with `from BaseClasses import LocationProgressType`, so the
            # subprocess cannot import the world at all without the Archipelago root on its path. This test
            # was written while the world lived in a loose checkout whose PARENT happened to be a directory
            # the ambient PYTHONPATH also pointed at, so the root came along for free. Under the ordinary
            # `worlds/pokemon_xd` layout the parent is `<root>/worlds`, and stripping it -- which this test
            # must do, since that is the whole point -- took the root with it. The probe then failed with
            # `ModuleNotFoundError: No module named 'BaseClasses'` and the assertion below reported it as
            # "importing the world from a zip failed", which looked exactly like the regression this test
            # exists to catch. A test that cannot tell its own harness breaking from the bug it watches for
            # is worse than no test.
            #
            # Located from BaseClasses itself rather than assumed, so it is right in either layout. It does
            # NOT re-expose the loose checkout: the root makes `worlds.pokemon_xd` importable, never a bare
            # top-level `pokemon_xd`, which is the name the probe asks for.
            import BaseClasses

            archipelago_root = os.path.dirname(os.path.abspath(BaseClasses.__file__))
            if os.path.realpath(archipelago_root) != os.path.realpath(str(_WORLD_PARENT)):
                kept.append(archipelago_root)
            env["PYTHONPATH"] = os.pathsep.join(kept)
            # Index nothing from the worlds/ directory except the suite's own fixtures -- see the probe's own
            # comment. Without this the loose pokemon_xd autoloads and the zip's copy cannot register.
            env["AP_TEST_WORLDS"] = "generic"
            result = subprocess.run([sys.executable, script, archive],
                                    capture_output=True, text=True, env=env, timeout=180)
            self.assertEqual(0, result.returncode,
                             f"importing the world from a zip failed:\n{result.stderr[-3000:]}")
            values = dict(line.split(" ", 1) for line in result.stdout.strip().splitlines() if " " in line)
            self.assertGreater(int(values["shadows"]), 0,
                               "the shadow list read as empty from inside the zip -- a data file is being "
                               "opened with open() on a __file__-relative path again")
            self.assertEqual(values["expected"], values["weightsum"],
                             "the purification weights do not sum to the ladder length inside the zip, which "
                             "is the assertion that stops the world registering at all")
            self.assertGreater(int(values["species"]), 0,
                               "the trainer census read as empty from inside the zip")

    def test_no_module_reads_the_data_folder_with_a_bare_open(self) -> None:
        """The source-level half, so the failure is caught at review time rather than at import time.

        `data/` must be reached through `game_data.load_json_data_file`, which resolves resources the way
        importlib does and therefore works from a directory and from a zip alike.
        """
        offenders: "list[str]" = []
        for root, dirs, filenames in os.walk(_PACKAGE_ROOT):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "test", "tools", "data")]
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                full = os.path.join(root, filename)
                with open(full, encoding="utf-8") as handle:
                    for number, line in enumerate(handle, start=1):
                        stripped = line.strip()
                        if stripped.startswith("#") or "open(" not in stripped:
                            continue
                        if "_PATH" in stripped and "with open(" in stripped:
                            offenders.append(f"{os.path.relpath(full, _WORLD_PARENT)}:{number}: {stripped}")
        self.assertEqual([], offenders,
                         "read data files through game_data.load_json_data_file -- a __file__-relative "
                         "open() cannot see inside an installed .apworld")


# ==============================================================================================================
# ADDENDUM 260 (2026-09-17): the Launcher's ISO patch, from inside the zip
# ==============================================================================================================
# Player, with a screenshot of the Launcher's own error dialog:
#
#     Could not load the ISO patcher tool:
#     [Errno 2] No such file or directory:
#     'D:\Archipelago\custom_worlds\pokemon_xd.apworld\pokemon_xd\game_data\shadow_move_slots.py'
#
# and: "The patch shouldn't ever depend this heavily on files -- it should be able to run through the
# archipelago launcher standalone."
#
# SAME BUG AS ADDENDUM 195, ONE DIRECTORY OVER. The file is there; the path is inside a zip, and the loader
# reaching for it was a plain OS file read. What made this one survive ADDENDUM 195's sweep is visible three
# methods above: `test_no_module_reads_the_data_folder_with_a_bare_open` walks the package with
# `dirs[:] = [d for d in dirs if d not in ("__pycache__", "test", "tools", "data")]` -- **tools/ is excluded**,
# and tools/ is where the patcher lives. The sweep that was meant to stop this recurring could not see the one
# place it recurred.
#
# The cause was not in the patcher at all. `launcher_patch._import_iso_patcher()` loaded it ROOTLESS
# (`sys.path.insert(tools_dir); import iso_patcher`), so `__package__` was empty, every relative import inside
# the patcher raised, and its `except ImportError` fallbacks went looking for those modules as files. The class
# is worth naming: **a fallback that cannot tell "there is no package" from "the package is here and something
# in it is broken" will answer the second question with the first one's remedy**, and the error you get names
# the remedy rather than the fault. Both tests below are therefore about REACHABILITY -- can the patch run at
# all from a zip -- not about what the patch produces, which the ADDENDUM 128 end-to-end tests already cover.
class TestTheIsoPatcherLoadsFromAZippedApworld(unittest.TestCase):

    def test_the_launcher_can_load_and_use_the_patcher_from_inside_the_zip(self) -> None:
        """The live failure, reproduced end to end in a subprocess and then proved fixed.

        Everything this probe touches was dead before the fix: `_shadow_move_slots` fell through to the
        by-path loader that produced the player's error, `shop_stock.MART_GROUPS` had no fallback at all and
        would have raised "attempted relative import with no known parent package" the moment the shop pass
        ran, and the three sibling `tools` modules were reached via a `sys.path` insert of a directory that
        does not exist inside an archive."""
        with tempfile.TemporaryDirectory() as tmp:
            archive = _build_zip(tmp)
            script = os.path.join(tmp, "patcher_probe.py")
            with open(script, "w", encoding="utf-8") as handle:
                handle.write(_PATCHER_PROBE)
            env = _probe_env()
            result = subprocess.run([sys.executable, script, archive],
                                    capture_output=True, text=True, env=env, timeout=180)
            self.assertEqual(0, result.returncode,
                             "the Launcher's patch entry point could not load the ISO patcher from an "
                             f"installed .apworld:\n{result.stderr[-3000:]}")
            values = dict(line.split(" ", 1) for line in result.stdout.strip().splitlines() if " " in line)
            self.assertEqual("1", values["infile"],
                             "the probe loaded a patcher from somewhere other than the zip, so it proves "
                             "nothing -- check that the loose checkout is really off the path")
            self.assertNotEqual("<none>", values["package"],
                                "the patcher was imported rootless again. Every relative import inside it is "
                                "dead in that state, and its fallbacks are file reads a zip cannot serve.")
            self.assertGreater(int(values["shadowmoves"]), 0,
                               "game_data/shadow_move_slots.py was not reachable from inside the zip -- this "
                               "is the exact module the player's error named")
            self.assertGreater(int(values["martgroups"]), 0,
                               "game_data/shop_stock.py was not reachable from inside the zip, so the shop "
                               "pass would raise partway through a patch")
            self.assertEqual("1", values["siblings"],
                             "a tools/ sibling was imported flat rather than through the package, which means "
                             "a sys.path insert of a directory that does not exist inside an archive")
            self.assertEqual("1", values["applypatch"])

    def test_every_tools_module_the_world_imports_is_zip_safe(self) -> None:
        """The source-level half, and the one that closes the gap in the older sweep above: that sweep walks
        the package with `dirs[:] = [d for d in dirs if d not in (..., "tools", ...)]`, so **tools/ is the one
        directory it never looks in** -- and tools/ is where this bug lived.

        The rule is not "never load a module by path". Standalone `python tools/iso_patcher.py` is a
        documented promise of this project and genuinely needs that branch. The rule is that the by-path
        branch must sit behind an explicit `__package__` check, so it can only run where `__file__` is
        guaranteed to name a real file on disk. A bare `try: <relative import> / except ImportError: <load by
        path>` does not satisfy it: an installed world always HAS a package, so an ImportError there is a real
        bug, and answering it with a file read reports the bug as a missing file. That is exactly the error
        the player saw.

        WHICH MODULES ARE HELD TO IT is derived, not listed. `tools/` also holds loose dev scripts
        (`verify_ddpk83.py`, `make_ability_test.py`, ...) that are only ever run as `python tools/foo.py` and
        have no package to prefer; naming the exempt ones would be a list that rots. Instead this collects the
        tools modules the world actually imports, transitively, and checks those -- so a new tools module is
        covered the day something in the world starts importing it, and never before."""
        tools_dir = pathlib.Path(_PACKAGE_ROOT, "tools")
        available = {path.stem for path in tools_dir.glob("*.py")} - {"__init__"}
        pattern = re.compile(
            r"(?:from\s+\.{0,2}tools\s+import\s+([\w,\s]+))"
            r"|(?:from\s+\.{0,2}tools\.(\w+)\s+import)"
            r"|(?:\bimport\s+(%s)\b)" % "|".join(sorted(available))
        )

        def referenced(source: str) -> "set[str]":
            found: "set[str]" = set()
            for group_list, dotted, flat in pattern.findall(source):
                for name in group_list.split(","):
                    name = name.strip().split(" as ")[0].strip()
                    if name in available:
                        found.add(name)
                for name in (dotted, flat):
                    if name in available:
                        found.add(name)
            return found

        # Seed: everything outside tools/ that reaches into it.
        reachable: "set[str]" = set()
        for root, dirs, filenames in os.walk(_PACKAGE_ROOT):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "tools", "test")]
            for filename in filenames:
                if filename.endswith(".py"):
                    reachable |= referenced(pathlib.Path(root, filename).read_text(encoding="utf-8"))
        self.assertIn("iso_patcher", reachable,
                      "nothing in the world imports tools/iso_patcher.py any more -- has the Launcher patch "
                      "moved? This test is checking a set it no longer belongs to.")

        # Close over what those import in turn.
        pending = list(reachable)
        while pending:
            source = pathlib.Path(tools_dir, pending.pop() + ".py").read_text(encoding="utf-8")
            for name in referenced(source) - reachable:
                reachable.add(name)
                pending.append(name)

        offenders: "list[str]" = []
        for name in sorted(reachable):
            source = pathlib.Path(tools_dir, name + ".py").read_text(encoding="utf-8")
            for marker in ("spec_from_file_location", "sys.path.insert"):
                if marker in source and "if __package__:" not in source:
                    offenders.append(f"tools/{name}.py: uses {marker} with no `if __package__:` gate")
        # `launcher_patch.py` is the entry point the player's error actually came from, so it is held to the
        # same rule even though it does not live under tools/.
        launcher = pathlib.Path(_PACKAGE_ROOT, "launcher_patch.py").read_text(encoding="utf-8")
        if "sys.path.insert" in launcher and "if __package__:" not in launcher:
            offenders.append("launcher_patch.py: uses sys.path.insert with no `if __package__:` gate")
        self.assertEqual([], offenders,
                         "gate every by-path module load behind `if __package__:` -- inside an installed "
                         ".apworld the package is always there and the file never is")

    def test_the_package_branch_comes_before_the_by_path_fallback(self) -> None:
        """Ordering, not just presence, and checked against the PARSED module rather than its text -- every
        one of these files explains the fallback in prose above the code, so a string search finds the
        explanation and reports it as the thing it warns about.

        Why ordering matters on its own: a flat import tried first can be satisfied by a stale `sys.path`
        entry left behind by some other component, binding a SECOND copy of the same module under a different
        name. Nothing reports that. It shows up later as state that is not shared between two objects that
        were supposed to be one."""
        import ast

        for name in ("tools/iso_patcher.py", "tools/xd_rel_format.py", "launcher_patch.py"):
            source = pathlib.Path(_PACKAGE_ROOT, name).read_text(encoding="utf-8")
            tree = ast.parse(source)
            gates = [node.lineno for node in ast.walk(tree)
                     if isinstance(node, ast.If) and isinstance(node.test, ast.Name)
                     and node.test.id == "__package__"]
            fallbacks = [node.lineno for node in ast.walk(tree)
                         if isinstance(node, ast.Call)
                         and ast.unparse(node.func).endswith(("sys.path.insert", "spec_from_file_location"))]
            if not fallbacks:
                continue
            self.assertTrue(gates, f"{name}: has a by-path fallback and no `if __package__:` gate at all")
            self.assertLess(min(gates), min(fallbacks),
                            f"{name}: the `if __package__:` branch must come before the first by-path "
                            "fallback, or a stale sys.path entry can win")
