# Pokemon XD: Gale of Darkness — Archipelago apworld

An Archipelago world for the GameCube game *Pokemon XD: Gale of Darkness* (USA, `GXXE`).

---

## What's in a seed

| | |
|---|---|
| Locations | About 600 with default options, up to about 700 |
| Items | 225 (134 of them filler) |
| YAML options | 74 |

**Check categories**

- **Overworld items** — 94 chests plus some NPC gifts and field pickups.
- **Trainer defeats** — one check per trainer, plus a "Defeat X (Any)" for trainers you can fight more than once
  (only the five forced second fights keep their own numbered check), or a cumulative "Defeat N Trainers",
  depending on the mode you pick. With Exclude Mt. Battle Trainers off, each Mt. Battle trainer is a check too.
- **Shadow Pokemon catches** — vanilla roster, plus up to 44 more if you turn on Shadow
  Pokemon Expansion.
- **Purifications** — "Purify 1 Shadow Pokemon" through "Purify X".
- **Species catches** — one per entry, 1–386.
- **Shop purchases** — every shop slot becomes its own check when Randomize Shops is on.
- **Travel unlocks** — 11 fast-travel destinations become items when Location Shuffle is on.

**Goal:** reach Citadark Isle and beat Cipher's boss — or win Mt. Battle, if you set that goal instead.

---

## Getting started

# Pokemon XD: Gale of Darkness -- Setup Guide

## Installing

1. **Double-click `pokemon_xd.apworld`**, right click -> Open With -> find your archipelago launcher exe, or use the Launcher's "Install APWorld" button and pick it.
   Archipelago copies the file where it actually looks and gives it the name it needs. Then **restart the Launcher**.
   
2. You'll need Dolphin and your own legally-owned Pokemon XD: Gale of Darkness (USA,
   game code `GXXE`) ISO.

## Generating a YAML

1. Use the Launcher's "Generate Template Options" to produce a default YAML for Pokemon XD Gale of Darkness, or
   use `docs/Pokemon XD Gale of Darkness.yaml` in this package as a starting point.
2. If hosting, put the YAML in your `Players` folder. Use "Generate" in the Archipelago launcher to create the zip file. Host the same as any other multiworld.

## Patching

1. On your Archipelago world page, your slot should have a patch to download (the .appxd file). Download it.
2. Right click it -> open with -> find your Archipelago Launcher exe. This should allow you to just double click them in the future.
3. Select your **UNPATCHED** ISO/CISO file.
4. Write a name for your new ISO/CISO. Make sure not to delete the file extension (.iso or .ciso)
5. Allow the patch to finish - it usually takes a minute or two, depending on settings. A console shows progress.

## Playing

1. Boot Dolphin and load your own Pokemon XD ISO - DO NOT OPEN THE POKEMON XD ARCHIPELAGO CLIENT YET.
2. Start a new save file or continue one.
3. **Finish the intro fight and save the game before connecting the client.** You can backup save files in the Dolphin folders if needed.
4. Open your party menu at least once.
5. Launch the client and connect to your room - enter your slot name.
6. Play. **Please save after acquiring the Snag Machine. Save often for your own sake.**
---

## Things worth knowing before you play

- **Location Shuffle is experimental.** It is my preferred way to play this game and the most likely
  to break. Only run it with a group that is happy to hit bugs and report them until I can test further.
- **Cumulative trainer defeats + Location Shuffle can softlock.** If you use both, keep the defeat count low.
- **Catch checks holding progression** is off by default, and should stay off unless you intend to catch
  every Shadow Pokemon as it comes up.
- **Save often.** The client writes to live memory. saves are handy.
- **Some areas require other story segments.** Namely, ONBS raid will be triggered upon finishing Pyrite's
  initial storyline (up to being sent away to the pokespots) and fighting Miror B at the Cave Poke spot.
- **Save states work, but may cause issues if used immediately after a reboot. Feel free to report bugs.**
- **Escape Rope.** It's always in your Key Items and takes you straight to the world map. Using it in the middle of
  a story sequence (a cutscene area, the SS Libra, Citadark Isle) can leave the story somewhere it doesn't expect. Save first.

---

## Client commands

Most are diagnostics prefixed `DEBUG:` in their help text. The ones you are most likely to want:

| | |
|---|---|
| `/mirorforce <place>` | Put Miror B. at pyrite, realgam, rock, oasis or cave on your next step |
| `/keyitems` | Which key items you currently hold |
| `/parts` | Robo Kyogre Part progress |
| `/remaining` | Overworld Item locations you have not checked yet |
| `/goal` | Force the goal, if you beat it and the check did not send |
| `/catches` | Where each species can be caught this seed |
| `/animations on\|off` | Turn move animations on or off, whatever the YAML says |
| `/toggledeathlink on\|off` | Turn Death Link on or off for this slot |
| `/pokespots` | Each Poke Spot's snacks, waiting Pokemon and Miror B.'s location |
| `/missableshadows` | Shadows on missable trainers this seed, and which went to Miror B. |

`/help` lists the rest.

---

## Reporting a bug

Say what you were doing, which options you had on, and paste the client log around the moment it went wrong.
If the story looks wrong, `/story` and `/storylog` together are usually enough to help me.

---

## Credits and license

Game data is extracted from your own disc at patch time. See `pokemon_xd/NOTICE.md` for third-party notices.
