# Chest/Overworld-Item Verification Report

Sources actually fetched for this pass (real WebFetch/WebSearch calls, Sept 2026):
- Bulbapedia `Walkthrough:Pokémon_XD/Part_1` (raw wikitext + rendered) — for Outskirt Stand/Gateon Port cross-check
- Bulbapedia `Walkthrough:Pokémon_XD/Part_2` (raw wikitext + rendered) — Cipher Lab
- Bulbapedia `Walkthrough:Pokémon_XD/Part_4` (raw wikitext + rendered) — Phenac City
- Bulbapedia `Walkthrough:Pokémon_XD/Part_5` (raw wikitext + rendered) — Kaminko's House, S.S. Libra
- Bulbapedia `Walkthrough:Pokémon_XD/Part_6` (raw wikitext + rendered, 2 passes) — Cipher Key Lair
- Bulbapedia `Walkthrough:Pokémon_XD/Part_7` (raw wikitext) — Citadark Isle
- `https://www.ludo.guide/guide/pokemon-xd-gale-of-darkness/kaminko-s-house` — independent cross-check for Kaminko's House
- WebSearch for "Sun Stone" + Chobin/Kaminko's House (no independent source found)

**Scope note:** the user's checklist only asked me to verify Parts 2, 4, 5, 6, 7. Pyrite Town (filed under "Part 3") was **not** re-verified this pass — it's out of scope for this report.

**Important structural correction to the real walkthrough index** (differs from what the location.py code comments assume): the real Bulbapedia part breakdown is:
- Part 1 = Pokémon HQ Lab intro, Agate Village, Gateon Port, Mt. Battle
- Part 2 = **Cipher Lab only** (not Outskirt Stand/Gateon Port/The Under)
- Part 3 = Poké Spots/Miror B., ONBS HQ, Exol (Pyrite/Under area)
- Part 4 = Phenac City, Snattle
- Part 5 = Kaminko's House, S.S. Libra, plus some Phenac Battle-CD content
- Part 6 = Cipher Key Lair, Gorigan
- Part 7 = Citadark Isle, Ardos, Eldes, Greevil
- Part 8 = Aftergame

The locations.py comment for the "Outskirt Stand" bucket already says "Bulbapedia walkthrough **Parts 1-2**" (not just Part 2), which turns out to be the right call — the Gateon Port/HQ Lab items are genuinely from Part 1, and Cipher Peon Digor's item is genuinely from Part 2 (Cipher Lab). No code change needed there, just noting it for the record.

---

## Verdict summary

| Verdict | Count |
|---|---|
| CONFIRMED | 23 |
| NEEDS CORRECTION | 5 |
| NOT FOUND | 2 |
| **Total checked** | **30** |

(Pyrite Town's 6 entries were not in scope for this pass.)

---

## Phenac City (Part 4)

| Location name | Verdict | Notes |
|---|---|---|
| Phenac City - Behind the House | **CONFIRMED** | Real text: "hiding behind the house in the lower right of the city is a box containing **3 Ultra Balls**." |
| Phenac City - Shop Ledge | **CONFIRMED** | Real text: "upstairs on a ledge next to the Shop is another box with **2 Hyper Potions**." |
| Phenac City - Pre-Gym Building | **NEEDS CORRECTION** | The real pickup here is not a box/chest — it's a **Music Disc** given by an NPC ("the man") inside a building near the Pre-Gym, which you then carry to the Mayor's House as a short fetch quest. Recommend renaming to `Phenac City - Pre-Gym Building (Music Disc)` and updating the description to say "given by an NPC," not "found in a box." |

Extra real items found in Part 4 not currently in the list (Battle CD trainer rewards, not boxes, so lower priority): Battle CD 19 (Resix), Battle CD 16 (Blusix), Battle CD 28 (Greesix), Battle CD 08 (Purpsix), Battle CD 32 (Browsix), Battle CD 27 (Yellosix).

---

## Realgam Tower / Kaminko's House / S.S. Libra (Part 5)

| Location name | Verdict | Notes |
|---|---|---|
| Kaminko's House - Chobin's Sun Stone | **NOT FOUND** | No Sun Stone anywhere in Kaminko's House per either Bulbapedia Part 5 or the independent ludo.guide walkthrough. Recommend **removing** this location — it does not appear to be a real pickup. |
| Kaminko's House - Secret Base Diary | **NEEDS CORRECTION** | Real item: "two diary pages belonging to **Jovi**," in an item box on the catwalks, found after solving the crane puzzle (independently corroborated by ludo.guide as "Jovi's Diary"). There is no "secret base" wording in either source. Recommend renaming to `Kaminko's House - Catwalk Diary Pages` and describing it as Jovi's diary pages. |
| Kaminko's House - R&D Lab Basement | **CONFIRMED** | Real item: **Rare Candy**, left corner of the R&D Lab basement (ludo.guide separately attributes it to a character "Makan"). |
| S.S. Libra - Hull Item | **NEEDS CORRECTION** (minor) | Real item: an **Iron**, "the first item box you see" upon boarding. "Hull" specifically isn't attested wording, but this is plausibly the entry-area box; recommend keeping the location but adding the item name to the description for clarity. |
| S.S. Libra - Box Puzzle Top | **CONFIRMED** | Real item: **Fire Stone**, top box of the block-pushing puzzle. |
| S.S. Libra - Box Puzzle Bottom | **CONFIRMED** | Real item: **2 PP Up**, bottom box of the same puzzle. |
| S.S. Libra - Second Puzzle Box | **NEEDS CORRECTION** | Real item: **Max Ether**, in the box of the puzzle that comes after the Top/Bottom one. The pickup is real, but "Second" is an approximate ordinal (there are effectively 4 box-puzzle rooms in sequence: Top/Bottom pair, then this single Max Ether box, then a final pair). Recommend renaming to `S.S. Libra - Third Puzzle Box (Max Ether)` or similar to reduce ambiguity. |
| S.S. Libra - Final Puzzle Box | **NEEDS CORRECTION** | The final puzzle room actually has **two** item boxes: a **Yellow Flute** and a **TM35 (Flamethrower)**. This single location currently represents only one pickup. Recommend splitting into two locations (e.g. `S.S. Libra - Final Puzzle Box (Yellow Flute)` and `S.S. Libra - Final Puzzle Box (TM Flamethrower)`), or renaming this one to cover just one of the two and adding the other as a new location. |
| S.S. Libra - Bonsly's Item | **CONFIRMED** | Real item: **Leftovers**, left behind by Bonsly in the final room. |
| S.S. Libra - Bottom Right Box | **CONFIRMED** | Real item: **Luxury Ball**, bottom right corner of Bonsly's room. |

Extra real items found in Part 5 not currently in the list: Battle CD 05 (Kaminko's House catwalks), Battle CD 18 (S.S. Libra, on the floor after descending stairs), Battle CD 15 (held by Dash's Castform, Phenac City), Battle CD 10 (bookcase, bottom-right house, Phenac City), Battle CD 12 (Mayor's office bookcase, Phenac City), Battle CD 35 (Pre-Gym desert training area).

---

## Cipher Key Lair (Part 6)

| Location name | Verdict | Notes |
|---|---|---|
| Cipher Key Lair - 1F Center Room | **CONFIRMED** | Real item: **3 Hyper Potions**. |
| Cipher Key Lair - 1F Upper Left | **CONFIRMED** | Real item: **2 Revives**. |
| Cipher Key Lair - Jelstin's Chamber | **CONFIRMED** (broadly) | After defeating Jelstin, a newly-accessible section has boxes with **3 Ultra Balls** and **1 Rare Candy**. This single location name may be under-representing what's really 2 separate boxes — consider splitting if precision matters for the fill algorithm. |
| Cipher Key Lair - B1F South Room | **CONFIRMED** | Real item: **TM24 (Thunderbolt)**, south of the room after defeating a Peon. One extraction pass named this peon "Kollo," which doesn't match any Cipher Key Lair trainer in the verified Shadow Pokémon list (Zook/Humah/Gorog/Lok/Targ/Snidle/Angic/Smarton/Gorigan) — likely a misread name; worth a manual spot-check of the live page if the trainer name matters. |
| Cipher Key Lair - 2F Center Room | **CONFIRMED** | Real item: **1 PP Up**, center room with the staircase to 3F, after defeating Gorog. |
| Cipher Key Lair - 2F Bottom Left | **CONFIRMED** | Real item: **1 Full Restore**. Caveat: the exact floor number (1F vs 2F) for this box flickered between two separate extraction passes of the same page — the box itself (and its "bottom left" position, near the Jelstin fight area) is real, but double-check the live page directly if the floor number is load-bearing for region/logic assignment. |
| Cipher Key Lair - 2F Upper Left | **CONFIRMED** | Real item: **1 Elixir**. Same floor-number caveat as above. |
| Cipher Key Lair - 3F Moon Door | **CONFIRMED** | Real item: **1 Max Revive**, behind the moon door after solving the puzzles. |
| Cipher Key Lair - 3F Hallway | **CONFIRMED** | Real item: **3 Full Heals**, down the hall to the right. |
| Cipher Key Lair - 4F Hallway | **CONFIRMED** | Real item: **2 Hyper Potions**, right hall from the stairs. |
| Cipher Key Lair - 4F Kleto's Room | **CONFIRMED** | Real item: **1 HP Up**, left hall, north of the Kleto fight. |

Extra real item found in Part 6 not currently in the list: **5F/Roof — TM26 (Earthquake)**, north of the control panel. This is a whole extra floor not represented in the current list at all — worth adding as a new location.

---

## Citadark Isle (Part 7)

| Location name | Verdict | Notes |
|---|---|---|
| Citadark Isle - After Furgy | **CONFIRMED** | Real item: **1 Max Elixir**, box on 1F right after Furgy's room. |
| Citadark Isle - Bridge Ultra Balls | **CONFIRMED** | Real item: **5 Ultra Balls**, box on B1F on the left side of the bridge. |

Extra real items found in Part 7 not currently in the list (Citadark Isle is a large, heavily-itemized dungeon — only 2 of its many boxes are currently represented):
- 1F, right door room: 3 Hyper Potions
- B1F, after Grason: 2 Full Restores
- 2F-1: 2 Revives (first block), 2 White Herbs (far right block)
- 3F-1: 2 Hyper Potions (near Nalix), PP Up (after Hunter), Elixir (past Kulig and Jargo)
- 3F-2: 2 Full Restores (by entrance)
- 4F: 2 Max Potions (hidden room via right platform), 3 Rare Candy (spiral path), 1 PP Max (below spiral path)
- 5F: 3 Timer Balls
- 6F: 3 Max Ethers, 1 Max Revive, 4 Full Heals, 2 Revives
- Dome 1F: 1 Max Revive (top right corner)

---

## Outskirt Stand / Gateon Port / The Under (Parts 1-2)

| Location name | Verdict | Notes |
|---|---|---|
| Outskirt Stand - HQ Lab Potions | **CONFIRMED** (sourced from Part 1) | Real item: **3 Potions**, found in the player's room on the second floor of Pokémon HQ Lab. Note this room is physically part of the HQ Lab, not "Outskirt Stand" itself — the code's bucketing under "Outskirt Stand" is a deliberate grouping choice (per the existing code comment), not a factual location error. |
| Gateon Port - Krabby Club Basement Item | **CONFIRMED** (sourced from Part 1) | Real item: a **Super Potion**, in the Krabby Club basement. |
| Gateon Port - Post-Battle Revive | **NOT FOUND** | No Revive appears anywhere in the Part 1 or Part 2 Gateon Port content. There IS a real Revive in the game, but it's awarded in **Cipher Lab** (Part 2) after battling Cipher Peon Nexir — not at Gateon Port, and not tied to any Gateon Port trainer battle (Cyle/Kilen). Recommend **removing** this location as currently named/located, or repurposing it as a Cipher Lab entry for the Nexir-battle Revive (distinct from the Digor Ether item below). |
| The Under - Cipher Peon Digor's Item | **CONFIRMED** | Real item: **1 Ether**, in a box unlocked by (optionally) defeating Cipher Peon Digor, who also unlocks a healing machine on the same visit. Note: this room is technically inside **Cipher Lab** (Part 2 content), which is accessed via The Under — if area-gating logic cares about the exact building name, "Cipher Lab" may be more precise than "The Under." |

Extra real items found in Parts 1-2 not currently in the list:
- Cipher Lab: a **Revive**, obtained just after battling Cipher Peon Nexir ("get the Revive and go upstairs") — this is likely what the mislabeled "Gateon Port - Post-Battle Revive" entry was actually trying to describe.
- Cipher Lab: an **Ether**, from Cipher Peon Meda (south hall, right of the two-elevator room) — a distinct pickup from Digor's Ether, not currently represented at all.
- Agate Village entrance chest (Poké Ball) and Agate Village hidden-cave chests (Poké Ball + Super Potion) — already covered elsewhere in locations.py under the Agate Village bucket, not part of this checklist.
