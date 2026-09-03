# Pokemon XD: Gale of Darkness

## Where is the options page?

The player options page for this game contains the options you need to configure and export a config file.

## What does randomization do to this game?

**This is a minimum-viable, still-experimental implementation and is not yet playable end to end.** Generation
(deciding what item goes where, and the logic that governs it) works fully, and produces a real `.appxd` patch
file -- see the setup guide for exactly what's still missing before a generated seed can be played.

Four kinds of check are shuffled:

- **Overworld items** -- chests, NPC gifts, and found items in the field (48 locations, sourced from a
  published walkthrough -- not yet the complete list).
- **Shadow Pokemon captures** -- defeating/snagging one of Cipher's corrupted Pokemon from a Peon or Admin (9
  locations, a representative sample).
- **Catching a species** -- one check per National Dex entry (1-386) the first time that species is seen owned,
  live-detected off the game's own memory.
- **Purifying a Shadow Pokemon** -- 32 cumulative checks, "Purify 1 Shadow Pokemon" through "Purify 32 Shadow
  Pokemon", live-detected the same way.

Every check grants an ordinary shuffled item from the multiworld -- the specific Pokemon species you catch or
Shadow Pokemon you purify remains a vanilla, client-side concern, the same way other Pokemon Archipelago worlds
don't ship wild-species choice as a multiworld item either.

## What is the goal of Pokemon XD?

Reach Citadark Isle and defeat Cipher's boss, having gathered the key items (Krane Memos and the Ein File S)
needed to get there.

## What does another world's item look like in this game?

Not yet defined -- no client exists yet to render a "foreign item" placeholder in-game.

## Known issues

- No AP server/CommonClient network loop exists yet -- species-catch and purification detection are
  live-verified against real game memory, but nothing yet sends a `LocationChecks` packet or applies an
  incoming item.
- Overworld-item and Shadow-capture checks additionally need an ISO-level item-table patch (designed, not yet
  implemented) before they're detectable at all -- see the setup guide.
- The overworld-item and Shadow-capture location rosters are not the complete game (48 and 9 respectively).
- See the project's feasibility notes for what's needed before this can be played for real.
