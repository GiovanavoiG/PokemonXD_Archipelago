# Pokemon XD: Gale of Darkness -- Setup Guide

## Installing

1. **Double-click `pokemon_xd.apworld`**, right click -> Open With -> find your archipelago launcher exe, or use the Launcher's "Install APWorld" button and pick it.
   Archipelago copies the file where it actually looks and gives it the name it needs. Then **restart the Launcher**.

   Do not drag the file into a folder yourself unless you have read the next paragraph, because two things
   about a dropped-in file have to be exactly right and neither one reports what went wrong. If the world does
   not load you get no "Pokemon XD Client" button in the Launcher and no Pokemon XD entry from "Generate
   Template Options".

   <details>
   <summary><b>If you install it by hand anyway -- the two things that have to be right</b></summary>

   **The filename must be exactly `pokemon_xd.apworld`.**

   | Your install | Where to put it |
   |---|---|
   | Portable, or running from source | `<Archipelago folder>/custom_worlds/` |
   | Installed (Windows `Program Files`, frozen macOS) | `%USERPROFILE%\Archipelago\worlds\` (Windows) or `~/Archipelago/worlds/` |

   If you are not sure which you have, install by double-clicking and let Archipelago decide.
   </details>

2. If you are running Archipelago from source rather than a release, follow
   [Running From Source](/docs/running%20from%20source.md) first.
3. You'll need [Dolphin](https://dolphin-emu.org/) and your own legally-owned Pokemon XD: Gale of Darkness (USA,
   game code `GXXE`) ISO.

## Generating a seed

1. Use the Launcher's "Generate Template Options" to produce a default YAML for Pokemon XD Gale of Darkness, or
   use `docs/Pokemon XD Gale of Darkness.yaml` in this package as a starting point.
2. Set your `name` in the YAML to the trainer name you'll use in-game (SEVEN CHARACTERS MAX) -- **this must match exactly** (see
   below for why).
3. Put the YAML in your `Players` folder and hit Generate in the Archipelago launcher.
4. This produces a `.appxd` file in the output folder. That's your seed file for this game.
   Right click it -> open with -> find your Archipelago Launcher exe. This should allow you to just double click them in the future.

## Playing

1. Boot Dolphin and load your own Pokemon XD ISO - DO NOT OPEN THE POKEMON XD ARCHIPELAGO CLIENT YET.
2. Start a new save file or continue one.
3. In-game, set your trainer name to exactly match the `name` you generated your YAML with (seven characters max).
4. **Finish the intro fight and save the game before connecting the client.** This gives you a clean fallback to reload from if anything
   goes wrong during your first connection/sync, and it is worth saving again periodically as you play.
5. Open your party menu at least once.
6. Launch the client and connect to your room - enter your slot name.
7. Play.
