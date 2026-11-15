# cosema/input_output/

Alles, was Daten von "außen" liest oder schreibt — die Postgres/TimescaleDB-Datenbank
des OEDS-Servers (seit 2026-08 statt InfluxDB).
Gegenstück: `cosema/generation/` usw. enthalten die Rechenlogik, die auf diesen
Daten arbeitet.

## db_client.py

`DBClient` — Klasse für den Zugriff auf die Zeitreihen. Eigene Ergebnisse liegen
im Schema `cosema` (eine Tabelle pro früherem InfluxDB-Measurement, als Hypertable).
ENTSO-E-Rohdaten (Erzeugung nach Typ, Verbrauch, Grenzflüsse) werden nur gelesen,
aus den Schemas des OEDS-Crawlers: `entsoe_raw` ab 2026-07-21, davor die
Jahres-Schemas `2020_raw` … `2026_raw` (Auswahl pro Zeitfenster in `_entsoe_sources`).
Bis 2026-11 hieß die Datei `influxdb.py`.

- `write_df` — allgemeine Schreibfunktion für ein DataFrame in ein Measurement
- `query_per_type_gen` — liest Erzeugung nach Typ für ein Land
- `query_per_unit_gen` — liest Pro-Einheit-Erzeugung (einzelne Kraftwerke)
- `check_per_unit_data` — prüft, bis wann Pro-Einheit-Daten verfügbar sind
- `query_vre` — liest VRE-Erzeugung/Kapazitätsfaktoren
- `query_demand_data` — liest Verbrauch für ein Land
- `query_reg_gen_data` — liest regionale (Bundesland-)Erzeugung
- `query_reg_demand_data` — liest regionalen Verbrauch
- `query_intensities` — liest bereits berechnete Intensitätswerte
- `query_cross_border_flows` — liest Grenzflüsse
- `write_vre_data` — schreibt VRE-Erzeugung/Kapazitätsfaktoren
- `write_reg_intensities` — schreibt finale Intensitätswerte
- `write_reg_demand_data` / `write_reg_generation_data` — schreiben regionale Erzeugung/Verbrauch
- `delete_series` / `delete_interval` — Aufräumfunktionen (fragen vor dem Löschen nach Bestätigung)

Freistehende Funktionen (Wrapper um `DBClient`, mit Fehlerbehandlung/Fallback
auf Null-Daten):
- `query_demand_data` — Verbrauch für mehrere Länder auf einmal, mit Fallback
- `query_DE_demand_data` — Verbrauch nur für Deutschland (aktuell ungenutzt)
- `query_reg_demand_data` — regionaler Verbrauch für alle Bundesländer
- `query_per_type_data` — Erzeugung nach Typ für mehrere Länder
- `query_reg_per_type_data` — regionale Erzeugung nach Typ für alle Bundesländer
- `collect_vre` — VRE-Erzeugung/Kapazitätsfaktoren für Solar/Wind on-/offshore, alle Bundesländer
- `collect_intensities` — bereits berechnete Verbrauchs- und Erzeugungs-Intensitäten, alle Bundesländer

## local_files.py

- `load_demand_reg_factors` — lädt die Verbrauchs-Regionalisierungsfaktoren
  aus `cosema_inputs.demand_reg_factors` (früher jährliche CSVs unter
  `inputs/demand_reg_data/`) für einen gegebenen Zeitindex.

## db_engine.py

- `get_engine` — SQLAlchemy-Engine aus `DB_HOST/PORT/NAME/USER/PASSWORD`
  (bzw. `.env`), für die Referenzdaten außerhalb von `DBClient`
- `INPUTS_SCHEMA` — Schema der Referenzdaten, Standard `cosema_inputs`

## oeds_zones.py

- `zones_for_country` — Gebotszonen in den OEDS-Tabellen zu einem Land
  (z.B. `DE` → `DE_LU`)

## gap_filling.py

- `default_rules` / `germany_rules` — Regelsätze, wie Datenlücken in einer
  Zeitreihe gefüllt werden sollen (z.B. interpolieren, mit 0 auffüllen)
- `cross_border_rules_unilateral` / `cross_border_rules_bilateral` — Regeln
  speziell für Grenzfluss-Daten
- `find_gaps` — findet Lücken in einem DataFrame (mehrere Spalten)
- `find_gaps_series` — findet Lücken in einer einzelnen Zeitreihe
- `fill_gaps_series` — füllt gefundene Lücken gemäß Regelsatz
- `evaluate_gap_filling` — Auswertung/Statistik, wie viel Lücken gefüllt wurden
