# cosema/generation/

Produktionsseitige Erzeugungsberechnung: Wettersimulation (VRE), Verteilung auf
Bundesländer, Datenabgleich zwischen verschiedenen Erzeugungs-Meldequellen.
`intensity.py` (finale Intensitätsberechnung als einfache Formel statt
PyPSA/netallocation) ist geplant, aber noch nicht umgesetzt.

## vre.py

Variable erneuerbare Energien (Solar, Wind on-/offshore) über atlite
(wetterbasierte Simulation):

- `get_borders_federal` — lädt Bundesland-Umrisse als Shapefile
- `create_cutout` — baut/lädt den atlite-Wetterausschnitt ("Cutout") für einen
  Zeitraum und ein Gebiet
- `select_cutout` — schneidet einen bestehenden Cutout auf ein kleineres Gebiet zu
- `renewable_generation` — rechnet Wetter × installierte Kapazität in eine
  stündliche Erzeugungs-Zeitreihe um (nutzt atlite `cutout.pv`/`cutout.wind`)
- `run_vre_calculations` — Haupteinstieg: baut den Cutout, lädt Kapazitäten,
  berechnet Erzeugung + Kapazitätsfaktoren je Technologie/Bundesland und
  schreibt sie in die Datenbank

## regional_split.py

Verteilung bundesweiter Erzeugung/Verbrauch auf Bundesländer, mittels
Kapazitätsfaktoren (konventionell + VRE) und Verbrauchs-Regionalisierungsfaktoren:

- `preprocess_gen_per_unit` — verarbeitet Pro-Einheit-Rohdaten: ordnet jedes
  Kraftwerk per EIC einem Bundesland zu, summiert genutzte Kapazität je
  Bundesland/Technologie
- `calc_reg_gen_by_type` — verteilt bundesweite Erzeugung je Typ auf
  Bundesländer, mittels Kapazitätsfaktoren
- `reg_demand_data_dynamic` — verteilt bundesweiten Verbrauch auf Bundesländer,
  mittels der Faktoren aus `input_output/local_files.py`
- `get_per_type_data` / `get_vre_data` / `get_demand_data` — Abfrage-Wrapper mit
  Fallback auf Null-Daten bei Fehlern (rufen `input_output/influxdb.py` auf)
- `calculate_regionalized_gen_and_demand` — Haupteinstieg: orchestriert alle
  obigen Schritte, kombiniert mit Pro-Einheit-Daten (falls `mode="with_per_unit"`)
  und schreibt das Ergebnis in die Datenbank

## leftover.py

Datenabgleich zwischen bundesweit gemeldeter Erzeugung nach Typ und der Summe
der Einzelkraftwerks- (Pro-Einheit-) Meldungen — auf Länderebene, **keine**
Verteilung auf Bundesländer (dafür ist `regional_split.py` zuständig):

- `prepare_gen_per_unit` — bringt rohe Pro-Einheit-Daten in ein einheitliches
  DataFrame-Format
- `calc_leftover_gen_per_type` — berechnet die Differenz ("Restmenge") zwischen
  Pro-Typ-Meldung und der Summe der Pro-Einheit-Meldungen je Technologie

## intensity.py — noch nicht vorhanden

Geplant: einfache Formel (Erzeugung × Emissionsfaktor) statt der aufwendigen
PyPSA/netallocation-Optimierung aus `calc_intensities.py`, um die
produktionsseitige Intensität zu berechnen. Hängt an einer noch nicht
verifizierten Hypothese, siehe `modularization_docs/modularisierung_zielstruktur.md`.
