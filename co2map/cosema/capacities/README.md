# cosema/capacities/

Lädt und bereitet installierte Kraftwerkskapazitäten aus dem
Marktstammdatenregister (MaStr) auf. Läuft separat, ca. monatlich — nicht Teil
des stündlichen/täglichen Scheduler-Laufs.

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
- `get_pp_MaStr` — zieht die MaStr-Rohdaten und wendet obige
  Bereinigungsschritte an
- `calculate_total_capacities_for_cosema` — Haupteinstieg: berechnet
  Gesamtkapazitäten (konventionell + VRE) pro Monat und schreibt sie als
  Parquet-Dateien nach `inputs/capacities/{Jahr_Monat}/`
