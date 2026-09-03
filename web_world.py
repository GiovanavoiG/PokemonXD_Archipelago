from BaseClasses import Tutorial
from worlds.AutoWorld import WebWorld


class PokemonXDWebWorld(WebWorld):
    game = "Pokemon XD Gale of Darkness"

    theme = "ice"

    bug_report_page = "https://github.com/ArchipelagoMW/Archipelago/issues"

    setup_en = Tutorial(
        "Setup Guide",
        "A guide to setting up Pokemon XD: Gale of Darkness for Archipelago.",
        "English",
        "setup_en.md",
        "setup/en",
        "Gioig",
    )

    tutorials = [setup_en]
