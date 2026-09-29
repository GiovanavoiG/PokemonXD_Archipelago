"""Read DDPK index 83 straight out of a built ISO/CISO's deck_archive.fsys DeckData_DarkPokemon.bin section,
with no bridge or live game. Says whether the "Shadow Overwrite Test" edit actually landed on disk
(story_deck_index 49, shadow_level 8, flee_weight 128, catch_rate_override 190) or not.

Usage:
    py verify_ddpk83.py "Pokemon XD (Shadow Overwrite Test).ciso"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import iso_patcher as ip
from xd_deck_format import lzss_decode

def main():
    if len(sys.argv) != 2:
        print("Usage: py verify_ddpk83.py <path-to-built-iso-or-ciso>")
        sys.exit(1)

    iso_path = Path(sys.argv[1])
    reader = ip.open_reader(iso_path)
    try:
        fst = ip.parse_fst(reader)
        deck_off, deck_len, _ = ip.find_by_basename(fst, "deck_archive.fsys")
        fsys_bytes = reader.read(deck_off, deck_len)
        entries = ip.parse_fsys(fsys_bytes)
        dark_e = entries["DeckData_DarkPokemon.bin"]
        dark_raw = fsys_bytes[dark_e["data_off"]: dark_e["data_off"] + 0x10 + dark_e["comp_size"]]
        dark_dec = lzss_decode(dark_raw)
        ddpk = ip.deck_format.DarkPokemonFile(dark_dec)

        story_e = entries["DeckData_Story.bin"]
        story_raw = fsys_bytes[story_e["data_off"]: story_e["data_off"] + 0x10 + story_e["comp_size"]]
        story_dec = lzss_decode(story_raw)
        deck = ip.deck_format.DeckFile(story_dec)
    finally:
        reader.close()

    entry83 = ddpk.ddpk_full(83)
    print(f"On-disk DDPK index 83 (in {iso_path.name}):")
    print(f"  {entry83}")
    print()
    if entry83["story_deck_index"] == 49 and entry83["flee_weight"] == 128 and entry83["catch_rate_override"] == 190:
        print("MATCHES the overwrite-test's intended edit (story_deck_index=49, flee_weight=128, "
              "catch_rate_override=190) -- the write landed correctly on disk.")
    elif entry83["story_deck_index"] == 20 and entry83["flee_weight"] == 0 and entry83["catch_rate_override"] == 255:
        print("This is the ORIGINAL, UNEDITED vanilla data (story_deck_index=20, Ledyba) -- the write did "
              "NOT land on disk. This file is not the shadow-overwrite-test output, or the edit failed.")
    else:
        print("Neither the expected edit nor the original vanilla values -- unexpected content, worth a "
              "closer look.")

    t26 = deck.trainer(26)
    print()
    print(f"On-disk trainer 26 team: {t26['team']}")


if __name__ == "__main__":
    main()
