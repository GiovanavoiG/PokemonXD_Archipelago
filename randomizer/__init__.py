"""Pure-Python randomization algorithms for Pokemon XD: Gale of Darkness.

Everything in this package operates on plain dataclasses (PokemonInstance / Trainer / TrainerPool, etc.) and
is deliberately decoupled from any GameCube-specific byte format or ISO I/O -- that layer lives in
`pokemon_xd.game_data`. This split exists so the shuffling logic itself can be unit-tested with synthetic
data (no ISO required), independent of whether the byte-level read/write against a real disc image has been
validated yet.
"""
