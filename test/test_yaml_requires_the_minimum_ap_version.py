"""The YAML template asks for the Archipelago version the apworld declares as its minimum, never a newer one: a newer
number makes that Archipelago refuse the YAML before the world is even loaded."""
from __future__ import annotations

import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestTheYamlVersion(unittest.TestCase):
    def test_both_templates_match_the_manifest(self):
        minimum = json.loads((ROOT / "archipelago.json").read_text(encoding="utf-8"))["minimum_ap_version"]
        for path in (ROOT / "data" / "reference_template.yaml", ROOT / "docs" / "Pokemon XD Gale of Darkness.yaml"):
            found = re.search(r"^requires:\n  version: (\S+)", path.read_text(encoding="utf-8-sig"), re.MULTILINE)
            self.assertIsNotNone(found, path.name)
            self.assertEqual(minimum, found.group(1), path.name)


if __name__ == "__main__":
    unittest.main()
