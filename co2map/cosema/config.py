"""
Central place to load config.yaml once.

Replaces the `with open("config.yaml") as f: config = yaml.safe_load(f)`
pattern duplicated at module level across ~10 files (see
modularization_docs/modularisierung_zielstruktur.md). Existing files keep their own copy
for now (not retrofitted, to keep this a low-risk pure addition) -- new
modules created during the modularization sweep (ingestion/, capacities/,
balance.py, ...) import `config` from here instead.
"""

import yaml

with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)
