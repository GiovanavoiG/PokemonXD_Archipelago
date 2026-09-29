"""ADDENDUM 346 (2026-09-25) -- the Launcher button carries the project's own icon.

Player supplied the artwork and asked for it on the "Pokemon XD Client" button in the Archipelago Launcher.

WHY THIS IS NOT A FILE PATH, which is the only interesting thing about the change. `kvui`'s
`ImageLoaderPkgutil` splits an `ap:` URI into a module and a path and loads it with `pkgutil.get_data`, which
goes through the PACKAGE'S OWN LOADER rather than the filesystem. ADDENDUM 271 is why that matters: this world
has to work both as a folder under `worlds/` and as a zipped `.apworld`, and a plain path only works for the
first. The package is also imported under a DIFFERENT NAME in those two cases -- `worlds.pokemon_xd` from a
folder, `pokemon_xd` from a zip -- which is why the registration uses `__name__` and not a literal.

So the tests below are mostly about the loading mechanism, not about the picture.
"""
from __future__ import annotations

import io
import pkgutil
import sys
import types
import unittest
import zipfile
from pathlib import Path

if "dolphin_memory_engine" not in sys.modules:
    _stub = types.ModuleType("dolphin_memory_engine")
    _stub.hook = lambda: None
    _stub.un_hook = lambda: None
    _stub.is_hooked = lambda: False
    _stub.read_bytes = lambda address, length: b""
    _stub.write_bytes = lambda address, data: None
    sys.modules["dolphin_memory_engine"] = _stub

from worlds.LauncherComponents import components, icon_paths

WORLD = Path(__file__).resolve().parents[1]
ICON = WORLD / "assets" / "launcher_icon.png"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _component():
    return next((c for c in components if c.display_name == "Pokemon XD Client"), None)


class TestTheComponentAsksForIt(unittest.TestCase):
    def test_the_client_component_is_registered(self):
        self.assertIsNotNone(_component(), "the Launcher component itself went missing")

    def test_it_names_an_icon_that_is_not_the_default(self):
        component = _component()
        self.assertEqual("Pokemon XD", component.icon)
        self.assertNotEqual("icon", component.icon, "'icon' is Component's default -- the generic AP logo")

    def test_the_icon_key_resolves_in_icon_paths(self):
        """`Launcher.build_card` does `icon_paths[component.icon]` with no fallback, so a missing key is a
        KeyError at startup rather than a missing picture."""
        self.assertIn(_component().icon, icon_paths)


class TestTheUriIsLoadableTheWayKvuiLoadsIt(unittest.TestCase):
    def _uri(self) -> str:
        return icon_paths[_component().icon]

    def test_it_is_an_ap_uri_not_a_filesystem_path(self):
        uri = self._uri()
        self.assertTrue(uri.startswith("ap:"), uri)
        self.assertNotIn("\\", uri, "a Windows path here would not survive being zipped")

    def test_the_module_half_is_this_package_under_whatever_name_it_was_imported(self):
        """`__name__`, not a literal. From a folder that is `worlds.pokemon_xd`; from an `.apworld` it is
        `pokemon_xd`, and a literal would be wrong in one of the two."""
        module, _path = self._uri()[3:].split("/", 1)
        self.assertEqual(__name__.rsplit(".", 2)[0], module)

    def test_pkgutil_returns_the_bytes(self):
        """Exactly what `ImageLoaderPkgutil.load` does."""
        module, path = self._uri()[3:].split("/", 1)
        data = pkgutil.get_data(module, path)
        self.assertTrue(data, "pkgutil found nothing -- the asset is not shipping with the package")
        self.assertEqual(PNG_MAGIC, data[:8], "not a PNG")

    def test_it_decodes_to_a_square_rgba_image(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not available")
        module, path = self._uri()[3:].split("/", 1)
        image = Image.open(io.BytesIO(pkgutil.get_data(module, path)))
        self.assertEqual("RGBA", image.mode, "the Launcher card needs a transparent background")
        self.assertEqual(image.width, image.height, "a non-square icon is stretched by the card")
        self.assertGreaterEqual(image.width, 32)
        self.assertLessEqual(image.width, 512, "every other shipped world icon is 512 or smaller")

    def test_it_is_authored_at_the_size_the_launcher_draws_it(self):
        """ADDENDUM 354. `data/launcher.kv` gives the card's `ApAsyncImage` a hard `size: (48, 48)` -- raw
        pixels, not dp like the card's own `height: "75dp"` -- and Kivy minifies with GL_LINEAR and no
        mipmaps. Four texels per output pixel, however far apart they are. A 256px asset shrunk to 48 is
        four samples out of every twenty-eight, which is the aliasing that reads as 'crunchy'.

        So the asset is drawn at 48 and the GPU has nothing left to do. That is also what the other worlds
        in this tree that ship a component icon do -- messenger and jakanddaxter are both exactly 48x48,
        tww is 32x32 -- and ours at 256 was the largest of the lot.

        Pinned as a RANGE, not a number: anything up to 96 stays a clean integer reduction that GL_LINEAR
        resolves correctly. 256 does not, which is the mistake this test exists to stop being made twice."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not available")
        module, path = self._uri()[3:].split("/", 1)
        width = Image.open(io.BytesIO(pkgutil.get_data(module, path))).width
        self.assertIn(width, (48, 96),
                      f"{width}px is not a clean 1:1 or 2:1 for the Launcher's 48x48 image widget")

    def test_it_fills_the_square_it_is_given(self):
        """The widget is square and Kivy preserves aspect ratio, so any letterboxing is space the icon
        simply does not use. ADDENDUM 354 dropped the 6px margin for the same reason."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not available")
        module, path = self._uri()[3:].split("/", 1)
        alpha = Image.open(io.BytesIO(pkgutil.get_data(module, path))).getchannel("A")
        bbox = alpha.getbbox()
        self.assertEqual((0, 0, alpha.width, alpha.height), bbox,
                         "the artwork should reach every edge of the canvas -- a margin here is wasted "
                         "space in a box that is only 48 pixels across")

    def test_the_corners_are_transparent(self):
        """A trimmed-and-centred icon should never paint its own background."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not available")
        module, path = self._uri()[3:].split("/", 1)
        alpha = Image.open(io.BytesIO(pkgutil.get_data(module, path))).getchannel("A")
        size = alpha.size[0]
        for corner in ((0, 0), (size - 1, 0), (0, size - 1), (size - 1, size - 1)):
            self.assertEqual(0, alpha.getpixel(corner), f"corner {corner} is not transparent")

    def test_something_is_actually_drawn(self):
        """A fully transparent PNG would pass every check above and show nothing."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not available")
        module, path = self._uri()[3:].split("/", 1)
        alpha = Image.open(io.BytesIO(pkgutil.get_data(module, path))).getchannel("A")
        opaque = sum(1 for value in alpha.get_flattened_data() if value > 0) \
            if hasattr(alpha, "get_flattened_data") else sum(1 for value in alpha.getdata() if value > 0)
        self.assertGreater(opaque, alpha.size[0] * alpha.size[1] // 10, "the icon is mostly empty")


class TestItShipsWithTheApworld(unittest.TestCase):
    def test_the_asset_is_inside_the_world_package(self):
        """ADDENDUM 271: anything outside this directory does not make it into the `.apworld`."""
        self.assertTrue(ICON.is_file(), f"{ICON} is missing")
        self.assertTrue(ICON.resolve().is_relative_to(WORLD.resolve()))

    def test_a_zip_of_this_world_contains_it(self):
        """Built here rather than trusting the release step, because 'it works from the folder' is exactly
        the bug this addendum's `ap:` URI exists to avoid."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "pokemon_xd.apworld"
            with zipfile.ZipFile(archive, "w") as zf:
                for path in WORLD.rglob("*"):
                    if path.is_file() and "__pycache__" not in path.parts:
                        zf.write(path, Path("pokemon_xd") / path.relative_to(WORLD))
            names = zipfile.ZipFile(archive).namelist()
        self.assertIn("pokemon_xd/assets/launcher_icon.png", names)

    def test_the_icon_is_not_enormous(self):
        self.assertLess(ICON.stat().st_size, 512 * 1024, "a Launcher icon should not be a big download")


if __name__ == "__main__":
    unittest.main()
