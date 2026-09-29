"""GameCube-specific binary format helpers for Pokemon XD: Gale of Darkness.

Nothing in this package touches a raw ISO file or FSYS archive directly -- see iso_format.py's module
docstring for exactly why, and what's still needed before this can run end-to-end against a real disc image.
"""

from __future__ import annotations

import json
from typing import Any


def load_json_data_file(relative_path: str) -> Any | None:
    """Load a JSON file from this world's own `data/` folder, or None if this build does not carry it --
    callers treat a missing data file as an expected state, not an error.

    Use `importlib.resources`, never `os.path` + `open()` on `__file__`: the latter works only from a loose
    directory (a dev checkout, or a folder in custom_worlds/) and reports "file not found" once the world is
    installed as a zipped .apworld, whose `__file__` points inside the archive. Resolve against `pokemon_xd`
    via `__package__`'s parent: an install registers the world as `worlds.<name>`, so `__package__` here is
    "worlds.pokemon_xd.game_data" and `.split(".")[0]` would yield "worlds". `game_data` is always
    pokemon_xd's direct child, so stripping the trailing `.game_data` is right in both layouts.
    """
    from importlib.resources import files

    pokemon_xd_package = (__package__ or "pokemon_xd.game_data").rsplit(".", 1)[0]
    try:
        resource = files(pokemon_xd_package).joinpath("data", relative_path)
        if not resource.is_file():
            return None
        with resource.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (ModuleNotFoundError, FileNotFoundError, NotADirectoryError):
        return None
