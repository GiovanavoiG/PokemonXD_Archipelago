"""Standalone GameCube/ISO binary-format tools for Pokemon XD: Gale of Darkness.

Exists only to make `tools` a real package: `zipimport` needs an actual `__init__.py` to treat a directory
inside a zip as one, so without it a loose checkout worked (PEP 420 namespace package) while an installed
.apworld raised ModuleNotFoundError on `from ..tools.xd_species_index import ...`. Keep it empty beyond this
docstring -- nothing here should have an import-time side effect.
"""
