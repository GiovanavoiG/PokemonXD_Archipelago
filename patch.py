"""
Patch container for Pokemon XD: Gale of Darkness.

A plain `APPlayerContainer`, not an `APProcedurePatch`/bsdiff-against-a-base-ROM setup, following worlds/tww:
AP cannot ship a copy of, or a binary diff against, a ~1.4GB copyrighted GameCube ISO. So this zips a small
inspectable seed payload and `tools/iso_patcher.py` does the real ISO work locally against the player's own
disc.

`seed.json` is plain JSON rather than TWW's base64+yaml, so it stays readable by hand:
  - `location_to_game_item_id`: per filled location, the real Bag item id (`items.py`'s `game_item_id`) the
    check grants, or `null` for items with no Bag id yet (Ein File S, the trap), which the client special-cases.
  - `trainer_team_assignments`: `randomizer.team_shuffle`'s output, trainer name -> team, for inspection only.
  - `trainer_species_by_dpkm_index`: the byte-exact `{dpkm_index: new_species}` map iso_patcher applies to
    `DeckData_Story.bin`. Only this map has a real join key back to ISO bytes -- see
    `game_data/real_trainer_data.py`.
  - `player`, `player_name`, `seed_name`: so the apply step can confirm it has the right seed.
"""

from __future__ import annotations

import json
from typing import Any

from worlds.Files import APPlayerContainer


class PokemonXDContainer(APPlayerContainer):
    """Zip container carrying this seed's placement data. Not an APProcedurePatch -- see module docstring for
    why the real ISO patching is deliberately NOT done inline here."""

    game: str = "Pokemon XD Gale of Darkness"
    patch_file_ending: str = ".appxd"

    def __init__(self, *args: Any, seed_data: dict[str, Any] | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.seed_data = seed_data or {}

    def write_contents(self, opened_zipfile) -> None:  # noqa: ANN001 - zipfile.ZipFile, matches base signature
        super().write_contents(opened_zipfile)
        opened_zipfile.writestr("seed.json", json.dumps(self.seed_data, indent=2, sort_keys=True))
