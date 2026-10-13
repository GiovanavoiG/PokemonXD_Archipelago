from BaseClasses import Tutorial
from worlds.AutoWorld import WebWorld

from .options import OPTION_GROUPS


class PokemonXDWebWorld(WebWorld):
    game = "Pokemon XD Gale of Darkness"

    theme = "ice"

    bug_report_page = "https://github.com/GiovanavoiG/PokemonXD_Archipelago/issues"

    setup_en = Tutorial(
        "Setup Guide",
        "A guide to setting up Pokemon XD: Gale of Darkness for Archipelago.",
        "English",
        "setup_en.md",
        "setup/en",
        ["GiovanavoiG"],
    )

    tutorials = [setup_en]

    # ADDENDUM 447: the template and options page in sections -- see options.OPTION_GROUPS.
    option_groups = OPTION_GROUPS
