"""Opening a `.appxd` starts the client, which asks host.yaml for Dolphin and the vanilla ISO, patches a copy named
after the seed file, and boots Dolphin on it (Client.patch_and_boot). Nothing here touches a real ISO, dialog or
Dolphin: the patch, the prompt and the boot are all swapped out."""
from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from .. import Client, launcher_patch
from .. import PokemonXDSettings


class _FakeCtx:
    def __init__(self) -> None:
        self.fst_isos: list[str] = []

    def apply_fst_iso(self, path: str, remember: bool = True) -> bool:
        self.fst_isos.append(path)
        return True


class _Swap:
    """Set attributes for the duration of a `with`, then put the originals back."""

    def __init__(self, *triples) -> None:
        self.triples = triples

    def __enter__(self) -> "_Swap":
        self.originals = [(obj, name, getattr(obj, name)) for obj, name, _value in self.triples]
        for obj, name, value in self.triples:
            setattr(obj, name, value)
        return self

    def __exit__(self, *exc) -> None:
        for obj, name, value in self.originals:
            setattr(obj, name, value)


class TestManifestAndNaming(unittest.TestCase):
    def test_the_manifest_gives_server_and_slot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            seed = Path(tmp, "AP_1_P1_Ash.appxd")
            with zipfile.ZipFile(seed, "w") as zf:
                zf.writestr("archipelago.json", json.dumps({"server": "archipelago.gg:1234", "player_name": "Ash"}))
            manifest = Client.read_patch_manifest(str(seed))
        self.assertEqual(manifest["server"], "archipelago.gg:1234")
        self.assertEqual(manifest["player_name"], "Ash")

    def test_an_unreadable_manifest_is_just_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            seed = Path(tmp, "broken.appxd")
            seed.write_bytes(b"not a zip")
            self.assertEqual(Client.read_patch_manifest(str(seed)), {})

    def test_the_patched_copy_is_named_after_the_seed_in_the_source_format(self) -> None:
        self.assertEqual(Client.patched_iso_path("C:/s/AP_1_P1_Ash.appxd", "D:/XD.ciso"), Path("C:/s/AP_1_P1_Ash.ciso"))
        self.assertEqual(Client.patched_iso_path("C:/s/AP_1_P1_Ash.appxd", "D:/XD.ISO"), Path("C:/s/AP_1_P1_Ash.iso"))
        self.assertEqual(Client.patched_iso_path("C:/s/AP_1_P1_Ash.appxd", "D:/XD.bin"), Path("C:/s/AP_1_P1_Ash.iso"))


class TestLogLines(unittest.TestCase):
    def test_only_complete_non_blank_lines_are_forwarded(self) -> None:
        forwarded = []

        class _Loop:
            def call_soon_threadsafe(self, func, *args):
                forwarded.append(args[0])

        stream = Client._LogLines(_Loop())
        stream.write("one\n\ntw")
        stream.write("o\nthree")
        self.assertEqual(forwarded, ["one", "two"])


class TestResolveLaunchPaths(unittest.TestCase):
    def _run(self, group: PokemonXDSettings, answers):
        saved = []
        prompts = []

        class _Settings:
            pokemon_xd_options = group

            def save(self):
                saved.append(True)

        def prompt(requests):
            prompts.append([title for title, _types in requests])
            return answers

        import settings
        with _Swap((settings, "get_settings", lambda: _Settings()),
                   (launcher_patch, "prompt_open_files", prompt)):
            return Client.resolve_launch_paths(), prompts, saved

    def test_only_missing_paths_are_asked_for_and_saved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dolphin = Path(tmp, "Dolphin.exe")
            iso = Path(tmp, "XD.iso")
            dolphin.write_bytes(b"")
            iso.write_bytes(b"")
            group = PokemonXDSettings()
            group.dolphin_path = PokemonXDSettings.DolphinPath(str(dolphin))
            group.rom_file = PokemonXDSettings.RomFile(str(Path(tmp, "missing.iso")))

            result, prompts, saved = self._run(group, [str(iso)])

        self.assertEqual(prompts, [[f"Select {PokemonXDSettings.RomFile.description}"]])
        self.assertEqual(saved, [True])
        self.assertEqual(Path(result[0]), dolphin)
        self.assertEqual(Path(result[1]), iso)

    def test_nothing_is_asked_when_both_paths_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("Dolphin.exe", "XD.iso"):
                Path(tmp, name).write_bytes(b"")
            group = PokemonXDSettings()
            group.dolphin_path = PokemonXDSettings.DolphinPath(str(Path(tmp, "Dolphin.exe")))
            group.rom_file = PokemonXDSettings.RomFile(str(Path(tmp, "XD.iso")))

            result, prompts, saved = self._run(group, None)

        self.assertEqual(prompts, [])
        self.assertEqual(saved, [])
        self.assertIsNotNone(result)

    def test_a_cancel_returns_none(self) -> None:
        group = PokemonXDSettings()
        group.dolphin_path = PokemonXDSettings.DolphinPath("Z:/nowhere/Dolphin.exe")
        group.rom_file = PokemonXDSettings.RomFile("Z:/nowhere/XD.iso")
        result, prompts, saved = self._run(group, None)
        self.assertIsNone(result)
        self.assertEqual(len(prompts[0]), 2, "both missing paths are asked for in one chain")
        self.assertEqual(saved, [])


class TestPatchAndBoot(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.seed = Path(self.tmp.name, "AP_1_P1_Ash.appxd")
        self.seed.write_bytes(b"seed")
        self.source = Path(self.tmp.name, "XD.iso")
        self.source.write_bytes(b"vanilla")
        self.patches: list[Path] = []
        self.boots: list[tuple[str, str]] = []

    def _fake_apply(self, _loop, source_iso, output, patch_file):
        self.patches.append(Path(output))
        Path(output).write_bytes(b"patched")
        return {"output": str(output), "trainer_slots_patched": 3}

    def _failing_apply(self, _loop, source_iso, output, patch_file):
        Path(output).write_bytes(b"half")
        raise ValueError("This ISO cannot be patched")

    def _run(self, apply):
        ctx = _FakeCtx()
        with _Swap((Client, "_apply_patch", apply),
                   (Client, "boot_dolphin", lambda dolphin, iso: self.boots.append((dolphin, iso)))):
            asyncio.run(Client.patch_and_boot(ctx, str(self.seed), "C:/Dolphin/Dolphin.exe", str(self.source)))
        return ctx

    def test_patches_then_boots_the_copy_and_arms_the_fst_guard(self) -> None:
        ctx = self._run(self._fake_apply)
        output = Path(self.tmp.name, "AP_1_P1_Ash.iso")
        self.assertEqual(output.read_bytes(), b"patched")
        self.assertNotEqual(self.patches[0], output, "patching goes to a temp name first")
        self.assertFalse(self.patches[0].exists())
        self.assertEqual(self.boots, [("C:/Dolphin/Dolphin.exe", str(output))])
        self.assertEqual(ctx.fst_isos, [str(output)])
        self.assertEqual(self.source.read_bytes(), b"vanilla")

    def test_a_second_open_reuses_the_patched_copy(self) -> None:
        self._run(self._fake_apply)
        self._run(self._fake_apply)
        self.assertEqual(len(self.patches), 1)
        self.assertEqual(len(self.boots), 2)

    def test_a_failed_patch_leaves_nothing_behind_and_boots_nothing(self) -> None:
        ctx = self._run(self._failing_apply)
        self.assertEqual(sorted(p.name for p in Path(self.tmp.name).iterdir()), ["AP_1_P1_Ash.appxd", "XD.iso"])
        self.assertEqual(self.boots, [])
        self.assertEqual(ctx.fst_isos, [])


if __name__ == "__main__":
    unittest.main()
