"""
Patch container for Pokemon XD: Gale of Darkness.

ARCHITECTURE DECISION (2026-09-02): follows the same shape as worlds/tww (The Wind Waker) -- also a GameCube
game on Archipelago. TWW's container (`TWWContainer`) is a plain `APPlayerContainer`, NOT an
`APProcedurePatch`/bsdiff-against-a-base-ROM setup: it just zips up a small placement payload (item/location
assignments, options, a few game-specific mappings) alongside the standard `archipelago.json` manifest, and
the *real* ISO-level patching happens entirely in TWW's own separate client tool, run locally by the player
against their own legally-owned ISO.

Pokemon XD follows the same pattern here, for the same reasons that made it the right call for TWW and that
match what this session's own research turned up:
  - AP does not want (and generally can't legally ship) a full copy of, or a full binary diff against, a
    ~1.4GB copyrighted GameCube ISO baked into a patch file.
  - The actual GameCube-side write-back (locating the DTNR/DPKM/DDPK blocks inside the real ISO, handling
    FSYS extraction/compression, rebuilding the disc image) is genuinely unresolved from this session's
    research -- rotobash/pokemon-ngc-rando's own `ISO.cs.Encode()` is an unimplemented stub in what was
    fetched. Committing to a specific byte-diffing scheme against a base ISO this session has never seen
    would be guessing, and a wrong guess here risks producing a patch that corrupts the player's disc image.
  - This is exactly the situation `APPlayerContainer` (not `APProcedurePatch`) exists for: a small, inspectable
    "here's the seed" file, with the actual patching delegated to a companion tool built and tested against
    real game data. See `apply_patch.py` at the repo root for that companion tool and its own honesty notes
    about what it can and can't yet do.

The container carries one JSON payload (`seed.json`, plain text, not obfuscated -- unlike TWW's base64+yaml
choice, plain JSON keeps this inspectable by hand while the ISO-write-back path is still being validated):
  - `item_id_to_game_item_id`: for every location this player's multiworld filled, the real Bag item id
    (`items.py`'s `game_item_id`) that check should grant, or `null` for items with no real Bag id yet
    (Ein File S, the trap) -- the client is expected to special-case those.
  - `trainer_team_assignments`: output of `randomizer.team_shuffle`, keyed by a trainer identifier string the
    apply step is expected to resolve against real ISO trainer data (see its own docstring for the gap here).
  - `player`, `player_name`, `seed_name`: for the client/apply step to confirm it's operating on the right
    seed.
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
