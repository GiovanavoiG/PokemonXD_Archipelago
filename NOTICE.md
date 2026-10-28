# NOTICE -- third-party references

This apworld is original work. It does not incorporate source code from any other project.

## rotobash/pokemon-ngc-rando (GPLv2)

`rotobash/pokemon-ngc-rando` is a standalone C# randomizer for the GameCube Pokemon games. It is cited
repeatedly in this project's comments and documentation, and those citations are deliberate -- but they are
citations of FACTS, not of code:

* **What is used:** numbers that describe the game's own data, not that project's authorship. Byte offsets,
  struct strides, `common_rel` pointer-table indices, field endianness, LZSS window/match parameters, and
  enumeration orders. A byte offset is a measurement of a 2005 Nintendo disc image; it is the same number
  whoever writes it down, and writing it down does not make it anyone's property.
* **What is not used:** no source file, function, comment, docstring, README text, tooltip, option
  description, or data table from that project appears in this one, in translated or untranslated form. Every
  implementation here was written from scratch; where the two projects solve the same problem, they do not
  share identifiers, control flow, or prose.
* **Independent verification:** the offsets this project actually writes through are not trusted on citation
  alone. They are re-measured against the player's own extracted ISO before any byte is written -- see the
  `verify_*_table` fingerprint checks in `tools/xd_rel_format.py`, which refuse to patch a table that does not
  agree with itself across many independent entries.

If you want to read the original, read it at https://github.com/rotobash/pokemon-ngc-rando. Nothing here is a
substitute for it and nothing here is a copy of it.

## Other references

* `PekanMmd/Pokemon-XD-Code` ("GoD Tool") is named in the setup documentation as an ISO extraction tool a
  player may choose to run. No code from it is used.
* Public community documentation (Serebii, GameFAQs FAQs, Bulbapedia) was used to cross-check vanilla rosters,
  learnsets and evolution data. Facts only; no text reproduced.
* Archipelago itself is a dependency, used through its published world API.
