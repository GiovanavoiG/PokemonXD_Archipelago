# Pokemon XD: Gale of Darkness — Archipelago apworld

An Archipelago world for the GameCube game *Pokemon XD: Gale of Darkness* (USA, `GXXE`).

The client talks to a running Dolphin over its memory and, for the options that need it, patches a **copy**
of your ISO. You supply your own legally-owned disc image; nothing here ships game data.

---

## What's in a seed

| | |
|---|---|
| Locations | 1,191 |
| Items | 225 (134 of them filler) |
| YAML options | 49 |

**Check categories**

- **Overworld items** — 95 chests plus some NPC gifts and field pickups.
- **Trainer defeats** — one check per trainer (231 of the 232-trainer roster), or a cumulative
  "Defeat N Trainers" ladder, depending on the mode you pick.
- **Shadow Pokemon catches** — the full 83-encounter vanilla roster, plus up to 44 more if you turn on Shadow
  Pokemon Expansion.
- **Purifications** — "Purify 1 Shadow Pokemon" through "Purify X".
- **Species catches** — one per National Dex entry, 1–386.
- **Shop purchases** — every shop slot becomes its own check when Randomize Shops is on.
- **Travel unlocks** — 11 fast-travel destinations become items when Location Shuffle is on.

**Goal:** reach Citadark Isle and beat Cipher's boss — or win Mt. Battle, if you set that goal instead.

---

## Getting started

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
3. You'll need Dolphin and your own legally-owned Pokemon XD: Gale of Darkness (USA,
   game code `GXXE`) ISO.

## Generating a seed

1. Use the Launcher's "Generate Template Options" to produce a default YAML for Pokemon XD Gale of Darkness, or
   use `docs/Pokemon XD Gale of Darkness.yaml` in this package as a starting point.
2. Set your `name` in the YAML to the trainer name you'll use in-game (SEVEN CHARACTERS MAX) -- **this must match exactly** (see
   Connecting below for why).
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
---

## Things worth knowing before you play

- **Location Shuffle is experimental.** It is my preferred way to play this game and the most likely
  to break. Only run it with a group that is happy to hit bugs and report them.
- **Cumulative trainer defeats + Location Shuffle can softlock.** If you use both, keep the defeat count low.
- **Catch checks holding progression** is off by default, and should stay off unless you intend to catch
  every Shadow Pokemon as it comes up.
- **Save often.** The client writes to live memory; a save you can fall back to costs nothing.
- **Some areas require other story segments.** Namely, ONBS raid will be triggered upon finishing Pyrite's
  initial storyline (up to being sent away to the pokespots) and fighting Miror B at the Cave Poke spot.

---

## Client commands

Most are diagnostics prefixed `DEBUG:` in their help text. The ones you are most likely to want:

| | |
|---|---|
| `/mirorforce <place>` | Put Miror B. at pyrite, realgam, rock, oasis or cave on your next step |
| `/keyitems` | Which gating key items you currently hold |
| `/parts` | Robo Kyogre Part progress |
| `/remaining` | Overworld Item locations you have not checked yet |
| `/checked <name>` | Mark a chest/check manually |
| `/goal` | Force the goal, if you beat it and the check did not send |

`/help` lists the rest.

---

## Reporting a bug

Say what you were doing, which options you had on, and paste the client log around the moment it went wrong.
If the story looks wrong, `/story` and `/storylog` together are usually enough to find it.

---

## Credits and licence

Game data is extracted from your own disc at patch time. See `pokemon_xd/NOTICE.md` for third-party notices.
