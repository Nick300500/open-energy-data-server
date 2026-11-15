# cosema/pipelines/

Gemeinsame Orchestrierungslogik, damit `scripts/manual_runs.py` und die
Scheduler (`schedulers/initial_calculations.py`, `schedulers/updated_calculations.py`)
nicht denselben Ablauf dreimal duplizieren.

## runner.py

- `run_pipeline` — führt eine beliebige Kombination aus Download-/VRE-/
  Regionalisierungs-/Intensitätsschritten aus, ein Flag pro Schritt. Deckt alle
  drei bisherigen Abläufe über reine Flag-Kombinationen ab.

## scheduler_bootstrap.py

- `build_clients` — baut `DBClient` + `EntsoePandasClient` aus den Umgebungsvariablen
  `DB_HOST/PORT/NAME/USER/PASSWORD` und `ENTSOE_API_KEY` (bzw. `.env`); nutzen die
  Scheduler und seit 2026-11 auch `scripts/manual_runs.py`
- `build_db_client` — nur der `DBClient` (ohne ENTSO-E-Key), für die reinen Lese-Skripte
  `scripts/calc_hps_intensities.py` und `scripts/capacity_utilization_report.py`
- `start_scheduler` — registriert eine Funktion als wiederkehrenden
  APScheduler-Job, startet ihn und blockiert, bis das Programm beendet wird

Bewusst **nicht** hier: die Betriebsparameter (`TASK_INTERVAL`, `TIME_DELTA`,
`FIRST_RUN_OFFSET`, `misfire_grace_time`, `max_instances`), die Datums-Default-
Logik und `perform_initial_calculations` selbst — die bleiben einzeln in jeder
`schedulers/*.py`-Datei sichtbar, da `schedulers/` der tatsächliche
Produktivbetrieb ist (siehe `schedulers/restart.sh`).
