# Pokemon XD: Gale of Darkness -- Setup Guide

## What's real and playable vs. what still needs manual work (read this first)

This apworld generates a real multiworld (569 locations: 67 Overworld Items, 83 Shadow Pokemon captures, 386
"Catch - {species}" checks, 32 cumulative "Purify N Shadow Pokemon" checks) and now includes a real, connectable
AP client (`Client.py`) built on top of this project's live-RAM findings. Here's exactly what that gets you and
what it doesn't:

**Fully automatic, no ISO patch, tested against real Dolphin memory addresses this project already confirmed:**
- Species catches (386) and Shadow Pokemon captures (83) -- both fire off the same live party-species signal.
  Snagging or defeating a Shadow Pokemon lands it in your party like any other catch, so no ISO patch is needed
  to detect it.
- Shadow Pokemon purifications (32 cumulative thresholds).
- Receiving items from other players -- delivered live, straight into the correct real Bag pocket (Balls, TMs/
  HMs, Berries, Key Items, or the general Items pocket), the moment the server sends them.

**Manual by design, still fully multiplayer-integrated (no ISO patch needed for these either):**
- Overworld Items (67 chests/boxes/NPC gifts) have no known live-RAM signal in this project -- picking one up
  in-game doesn't touch any address we've confirmed. Use `!checked <part of the name>` right after picking one
  up; it fuzzy-matches against this seed's real location list (`!remaining` shows what's left).
- Declaring the game complete (defeating the Cipher Boss at Citadark Isle) has no known live-RAM signal either
  -- use `!goal` after you actually beat him.

**NOT push-button yet -- the one real remaining gap: Trainer Team Randomization applying to your ISO.**
Generation *does* produce real, seeded trainer-team data (`seed.json`'s `trainer_team_assignments`, built from
a real 68-trainer/286-Pokemon census sourced from GameFAQs/Serebii walkthroughs -- see
`data/trainer_pools_SOURCES.md`). But turning that into bytes written into your actual ISO requires a
still-manual pipeline (`apply_patch.py`, see below) because live RAM writes to a trainer's team revert after one
turn -- durably changing a trainer's species has to happen as an offline edit to the ISO's own DPKM/DDPK trainer
tables, and this project has deliberately NOT implemented GameCube FST/FSYS parsing from scratch (see
`patch.py` and `game_data/iso_format.py`'s own docstrings for why: guessing at byte offsets against a real ISO
without a way to verify the result risks corrupting your disc image, and the reference randomizer
[rotobash/pokemon-ngc-rando](https://github.com/rotobash/pokemon-ngc-rando) this logic was ported from has an
unimplemented stub at exactly that step). If you don't want to deal with this yet, just leave trainer teams
un-patched -- everything else in this guide (chests, catches, shadow captures, purifications, item receiving)
works completely independently of whether you've applied the trainer-team patch.

## Installing

1. Follow [Running From Source](/docs/running%20from%20source.md) to set up Archipelago from source, or use a
   built release that has this apworld installed (drop `pokemon_xd_apworld.apworld` into your `custom_worlds`
   folder).
2. Install the one client-only dependency this world needs (never required for generation): `pip install
   dolphin_memory_engine`.
3. You'll need [Dolphin](https://dolphin-emu.org/) and your own legally-owned Pokemon XD: Gale of Darkness (USA,
   game code `GXXE`) ISO/GCM.

## Generating a seed

1. Use the Launcher's "Generate Template Options" to produce a default YAML for Pokemon XD Gale of Darkness, or
   use `docs/Pokemon XD Gale of Darkness.yaml` in this package as a starting point.
2. Set your `name` in the YAML to the trainer name you'll use in-game -- **this must match exactly** (see
   Connecting below for why).
3. Put the YAML in your `Players` folder and run `Generate.py` (or generate a multiworld normally alongside
   other players' YAMLs -- this world plays fine alongside any other AP game).
4. This produces a `.appxd` file in the output folder. That's your seed file for this game -- open it with the
   Launcher's "Pokemon XD Client" the same way you would any other AP patch file, or run
   `PokemonXDClient.py`/the Launcher component directly.

## Playing

1. Boot Dolphin and load your own Pokemon XD ISO.
2. Start (or continue) a save file, and **open the in-game Party/Status screen at least once** after booting --
   the party data this client reads is lazily initialized and stays blank in memory until you do this once per
   boot.
3. In-game, set your trainer name to exactly match the `name` you generated your YAML with.
4. Launch the client (via the Launcher's "Pokemon XD Client" component, or `python3 -m
   worlds.pokemon_xd.Client --name "YourTrainerName"` from source) and connect to your room the normal AP way.
   This client does not patch or read anything from a slot-name-embedded-in-ROM the way some other GameCube
   clients do -- it authenticates the normal AP way (`--name`, an `archipelago://` URL, or the interactive
   prompt) and then uses that same name to locate your save data in Dolphin's memory, which is why it has to
   match your in-game trainer name.
5. Play normally. Catches, Shadow captures, and purifications report themselves. For chests/boxes/NPC gifts,
   use `!checked <part of the name>` right after picking one up (try `!remaining` if you're not sure what's
   still outstanding, or the fuzzy match is ambiguous). Use `!goal` once you've beaten the Cipher Boss.
6. `!dolphin` shows the current Dolphin connection status at any time.

## For developers: applying the trainer-team patch (optional, manual, advanced)

If you want trainer teams randomized too, `apply_patch.py` (at the repo root, deliberately shipped *outside*
this apworld package) can write this seed's chosen species/level/held-item into an already-extracted DPKM/DDPK
table. It does not read a raw ISO itself -- you need a separate tool that already understands Pokemon XD's file
system to pull those tables out first (rotobash/pokemon-ngc-rando or PekanMmd/Pokemon-XD-Code ["GoD Tool"] are
the two known candidates; neither's extraction step was independently verified by this project). See
`apply_patch.py`'s own module docstring for the full usage, the `layout.json` format it expects, and exactly
what it does and doesn't do.

## For developers: generating a test seed without a real ISO/Dolphin

You can generate and inspect seeds (including the trainer-team assignment logic) without any of the above --
`Generate.py` and this world's test suite (`worlds/pokemon_xd/test/`) don't need Dolphin or a real ISO at all,
only for actually playing a generated seed live.
