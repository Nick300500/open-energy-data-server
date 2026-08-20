"""
Canonical model of the German Bundesländer (states) used throughout cosema.

Single source of truth for state abbreviations, replacing the ad-hoc
`config["states"].values()` re-derivation duplicated across
generation/regional_split.py, generation/vre.py, input_output/influxdb.py,
calc_forecast.py, forecast_scripts.py, and the hardcoded `["MV", "NI", "SH"]`
offshore-states literal duplicated in generation/vre.py (x2) and
input_output/influxdb.py (x1). See modularization_docs/modularisierung_zielstruktur.md
(Schritt 4) / modularization_docs/modularisierung_status.md.

The abbreviations and their order mirror config.yaml's `states:` mapping
(kept there for the full German display names, not used in code logic).
"""

from enum import Enum


class State(str, Enum):
    BB = "BB"  # Brandenburg
    BW = "BW"  # Baden-Württemberg
    BY = "BY"  # Bayern
    HE = "HE"  # Hessen
    MV = "MV"  # Mecklenburg-Vorpommern
    NI = "NI"  # Niedersachsen
    NW = "NW"  # Nordrhein-Westfalen
    RP = "RP"  # Rheinland-Pfalz
    SH = "SH"  # Schleswig-Holstein
    SL = "SL"  # Saarland
    SN = "SN"  # Sachsen
    ST = "ST"  # Sachsen-Anhalt
    TH = "TH"  # Thüringen


# Plain list of abbreviation strings, same order as config.yaml's `states:` --
# drop-in replacement for the old `config["states"].values()` pattern.
BUSES = [s.value for s in State]

# States with offshore wind capacity.
OFFSHORE_STATES = [State.MV.value, State.NI.value, State.SH.value]
