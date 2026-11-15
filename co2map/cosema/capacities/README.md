# cosema/capacities/

Lädt und bereitet installierte Kraftwerkskapazitäten aus dem
Marktstammdatenregister (MaStR) auf. Läuft separat, ca. monatlich — nicht Teil
des stündlichen/täglichen Scheduler-Laufs.

**Datenfluss:** MaStR und Bundesland-Umrisse kommen aus `cosema_inputs`
(`*_extended`, `shapefile_states`) → `calculate_total_capacities_for_cosema`
schreibt Parquet-Dateien pro Monat → Upload mit `transfer_capacities.py`
(Ordner "Transfer data to database", außerhalb dieses Repos) nach
`cosema_inputs.capacities_conventional` / `capacities_vre` → gelesen von
`generation/regional_split.py` bzw. `generation/vre.py`.

**Aufruf** für einen Monatsbereich: `python -m scripts.calc_capacities --start 2020-01 --end 2026-11 --out-dir <Ordner>`
(siehe `scripts/calc_capacities.py`).

## mastr.py

- `load_config` — lädt eine Konfigurationsdatei
- `_clean_names` — bereinigt Namensfelder (Sonderzeichen etc.)
- `_get_postcodes` — lädt Postleitzahl-Referenzdaten für die Standortzuordnung
- `_clean_default_data` — bereinigt Rohdaten: Einheitenumrechnung, fehlende
  Standorte auffüllen, Stilllegungsdaten
- `_clean_specific_data` — technologie-spezifische Bereinigung (z.B.
  Solar-Ausrichtung, Windnabenhöhe-Defaults)
- `_get_region_identifier` — ordnet Koordinaten eines Kraftwerks einem
  Bundesland zu
- `_add_region_information` — hängt die Bundesland-Zuordnung an die
  Kraftwerksliste an
- `get_pp_MaStr` — zieht die MaStR-Rohdaten aus `cosema_inputs` und wendet
  obige Bereinigungsschritte an
- `calculate_total_capacities_for_cosema` — Haupteinstieg: lädt das MaStR
  einmal und berechnet dann pro Monat die Kapazitäten der Anlagen, die in dem
  Monat in Betrieb sind. Schreibt nach `{out_dir}/{Jahr_Monat}/`
  (Standard `inputs/capacities`):
  - `conv_capacities_{Jahr_Monat}.parquet` — konventionell, eine Zeile pro
    Bundesland, eine Spalte pro Technologie
  - `{technologie}_capacities_{Bundesland}_{Jahr_Monat}.parquet` — Solar,
    Wind on-/offshore, eine Zeile pro 0,25°-Wetterzelle mit summierter
    Kapazität (seit 2026-11; vorher eine Zeile pro Anlage, gleiche Erzeugung)

  Die `conv_capacities`-Datei wird pro Monat zuletzt geschrieben und markiert
  ihn als fertig: Ein abgebrochener Lauf macht beim ersten unfertigen Monat
  weiter, `overwrite=True` rechnet alles neu.
