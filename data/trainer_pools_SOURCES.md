# trainer_census.json sourcing (2026-09-03)

Every `(species, level, is_shadow)` tuple in `trainer_census.json`'s `trainer_pools` was read directly from a
real fetched page below -- none were guessed or reconstructed from memory. `build_census.py` (this session's
scratchpad, not shipped) converts species names to National Dex numbers via `species.py`'s own table and
writes the final JSON; a handful of source-text typos (e.g. "Girafraig", "Graveller", "Zatu", "Medicharm",
"Electrabuzz", "Bannette", "Duduo") were corrected to their real species names via an explicit alias table in
that script -- documented there, not silently guessed.

## URLs actually fetched, and what each contributed

- `https://gamefaqs.gamespot.com/gamecube/925945-pokemon-xd-gale-of-darkness/faqs/40528` (Raph136's walkthrough
  FAQ -- note the game id is **925945**, not 929781; an earlier session guessed the wrong id and got an
  unrelated game's page). Contributed: Eagun's intro battle, Lovrina's 1st battle, Miror B.'s 1st battle, Exol,
  Snattle's 1st battle, Gonzap. The fetch tool's HTML->text conversion truncates this page consistently around
  the Gorigan fight -- later bosses (anything past that point) were not recoverable from this URL despite
  several retry attempts with different prompts and a `?page=2` query param (GameFAQs' own pagination didn't
  come through the fetch tool either way -- same content both times).
- `https://www.serebii.net/xd/walkthrough/04.shtml` -- 20 Phenac-area Cipher Peons (Exinn through Egrog),
  Snattle's 1st battle (cross-check, consistent with GameFAQs), Chobin + Robo Groudon, Cipher Peon Smarton's
  1st (Deserted Cruiser) team.
- `https://www.serebii.net/xd/walkthrough/05.shtml` -- Miror B.'s Outskirt Stand rematch (cross-check,
  consistent with GameFAQs), Rider Willie, Gorigan's Shadow Pokemon Factory team (6 mons -- more complete than
  GameFAQs' 5-mon excerpt, which cut off before Hypno), Thug Zook, Cipher Peon Smarton's 2nd (Factory Control
  Room) team.
- `https://www.serebii.net/xd/walkthrough/06.shtml` -- the entire Citadark Isle roster: Navigator Abson through
  Cipher Admin Eldes (~30 named trainers), Shadow Lugia, and Cipher Boss Greevil's main-story team.
- `https://www.serebii.net/xd/walkthrough/07.shtml` -- fetched twice (once pre-compaction, once fresh this
  segment to independently re-verify) -- Eagun's real post-game team, Miror B.'s final encounter, Cipher Boss
  Greevil's post-game rematch team. Both fetches returned the same data.
- `https://bulbapedia.bulbagarden.net/wiki/Dakim`, `.../wiki/Nascour` -- fetched to check whether these
  Pokemon Colosseum characters also appear as battles in XD. **Both confirmed Colosseum-only** -- Dakim's page
  only documents Mt. Battle/Realgam Tower/Deep Colosseum fights (all Colosseum locations), and Nascour's page
  explicitly states no XD content. `Venus_(Trainer)` and `Ein_(game)` both 404'd outright. Combined with XD's
  own known plot (Miror B. and Gorigan carry over from Colosseum; Lovrina, Snattle, Ardos and Eldes are XD's
  new admins) -- **Dakim, Venus, Ein, and Nascour do NOT appear in this trainer census because they are not
  battles that exist in Pokemon XD**, not because research failed to find them. An earlier pre-compaction
  research pass had assumed these might be real XD bosses; that assumption is corrected here.
- WebSearch for `"Duking" Pokemon XD Gale of Darkness battle team` returned only forum threads literally titled
  "where is Duking?" / "wheres duking??" -- strong evidence Duking is not a battle the player fights in XD
  either (he's a recurring Pokemon Colosseum NPC; if he cameos in XD it isn't as a trainer battle). Omitted for
  the same reason as Dakim/Venus/Ein/Nascour.
- `https://pokemonlp.fandom.com/wiki/Appendix:Pok%C3%A9mon_XD:_Gale_of_Darkness_Walkthrough/Realgam_Colosseum`
  -- 402 error, inaccessible.
- `https://bulbapedia.bulbagarden.net/wiki/Realgam_Colosseum` and
  `https://bulbapedia.bulbagarden.net/wiki/Walkthrough:Pok%C3%A9mon_XD/Part_5` -- both fetched looking for the
  Realgam Tower Colosseum tournament's own trainer rosters (Rounds 1-4). Neither page's fetched content
  included the actual per-round trainer teams (Bulbapedia's page confirmed the rounds exist and named their TM
  rewards, but not the opposing trainers/Pokemon).

## Coverage / honest gaps

**Covered, real, sourced**: 68 trainers across 21 pools / 286 individual Pokemon instances -- effectively the
whole named Cipher Peon roster from Phenac City through Citadark Isle, every Cipher Admin who actually appears
in XD (Lovrina x2, Snattle x2, Gorigan x2, Ardos, Eldes), Miror B.'s three encounters, Gonzap, Exol, the final
boss Greevil (both his main-story and post-game rematch teams), Shadow Lugia, and Eagun's two battles.

**Still missing / not found**:
- The Realgam Tower Colosseum tournament's own opponent trainers (Rounds 1-4) -- these exist in-game (TM
  rewards for each round were found) but their rosters weren't recoverable from any source fetched this
  session. Likely lower-stakes/randomized filler trainers rather than named story bosses, but not confirmed.
- A handful of early-mid-game Cipher Peons/trainers this session didn't specifically search for beyond the
  Phenac-area sweep (e.g. any named trainers at Pyrite Town, The Under, or Agate Village outside of Chobin) --
  not ruled out, just not covered by the sources fetched this pass.
- For Cipher Admin Ardos (Citadark Isle) and Cipher Admin Eldes (Citadark Isle), Serebii's page labeled their
  teams "Shadow Pokemon: 3" and "Shadow Pokemon: 4" respectively without saying which specific team slots are
  the Shadow Pokemon -- rather than guess, every mon on both of their teams is recorded with `is_shadow: false`
  in `trainer_census.json`. This underclaims two Shadow Pokemon locations' worth of "is_shadow" flags but never
  overclaims one; it only affects `team_shuffle.py`'s shadow-dedup logic (a design not currently wired to any
  live ISO patch anyway -- see `patch.py`), not anything player-facing in this build.
