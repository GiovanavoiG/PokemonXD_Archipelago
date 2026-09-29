# Pokemon XD: Gale of Darkness

## Where is the options page?

The player options page for this game contains the options you need to configure and export a config file.

## What does randomization do to this game?

AP client talks to a Dolphin process over its
memory -- see the setup guide for what it can and can't do automatically. Several kinds of check are shuffled:

- **Overworld items** -- chests, NPC gifts, and found items in the field.
- **Shadow Pokemon defeats** -- defeating one of the game's 83 real Shadow Pokemon in battle (the full roster,
  not a sample), live-detected off the battle's own HP data the moment it hits 0.
- **Trainer defeats** -- defeating a unique trainer.
- **Catching a species** -- one check per National Dex entry (1-386) the first time that species is seen owned,
  live-detected off the game's own memory.
- **Purifying a Shadow Pokemon** -- Cumulative checks, "Purify 1 Shadow Pokemon" through "Purify X Shadow
  Pokemon", live-detected the same way.
- **Opening a chest** -- unique per chest location.

Every check grants an ordinary shuffled item from the multiworld.

## What is the goal of Pokemon XD?

Reach Citadark Isle and defeat Cipher's boss, having gathered the key items needed to get there.

## What does another world's item look like in this game?

Not yet defined -- the client doesn't currently render a distinct "foreign item" indicator in-game.

## Known issues

- Location shuffle is experimental. Issues and softlocks are definitely possible. Please report all bugs if you can.
