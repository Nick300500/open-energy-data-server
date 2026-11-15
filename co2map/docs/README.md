# CO2-Map-Integration in den Open-Energy-Data-Server — Stand 2026-11-15

Einstiegspunkt für die Doku zu diesem Repo (Fork von `INATECH-CIG/open-energy-data-server`, Branch
`co2map-integration`). Diese Datei ersetzt die alte `UEBERGABE.md` und beschreibt den **aktuellen** Stand.

- [`plan.md`](plan.md) — was noch offen ist.
- [`historie.md`](historie.md) — chronologisches Archiv, wie es dazu kam (Entscheidungen, verworfene Ansätze,
  gefundene und gefixte Bugs). Nicht mehr aktiv gepflegter Verlauf außer bei neuen Meilensteinen.
- [`server_zugang_recherche.md`](server_zugang_recherche.md) — technische Rohdaten vom ersten Server-Login
  (`compose.yml`-Architektur, `streamlit-app`-Vorlage). Rein archivisch, die meisten offenen Punkte darin sind
  inzwischen geklärt (siehe `historie.md`).

## Architektur in Kürze

Die CO2-Intensitäts-Karte (`cosema`, hier unter `co2map/`) läuft als **eigener, dauerhafter Docker-Service** im
gemeinsamen `compose.yml` des OEDS-Stacks — **kein** Prefect-Flow/Crawler. Drei Scheduler laufen parallel im
selben Container:

- **`initial_calculations`** (stündlich): letzte 24h, liest `entsoe_raw` live, Modus `only_per_type`.
- **`updated_calculations`** (täglich, 05:45 Europe/Berlin): 7-Tage-Fenster mit 7 Tagen Versatz in die
  Vergangenheit, zusätzlich Kraftwerksblock-Daten (`with_per_unit`, braucht `ENTSOE_API_KEY`) und
  Wetter-Cutouts (Open-Meteo-Archiv-API, einzelne Strahlungsgrößen zusätzlich aus ERA5 über Copernicus/CDS;
  die Prognose im 12h-Lauf nutzt die Open-Meteo-Forecast-API).
- **`forecast_calculations`** (alle 12h): schreibt nur die Wind-/Solar-**Prognose** (`vre_forecast`) für den
  stündlichen Lauf — berechnet **keine** CO2-Intensitäts-Prognose, der entsprechende Aufruf ist im Code
  auskommentiert (Stand unklar, ob das schon immer so war — noch nicht untersucht).

**Datenquellen**: `entsoe_raw`/`entsoe` (OEDS's eigener ENTSO-E-Crawler, nicht von uns geschrieben) +
`cosema_inputs` (MaStR, Shapefiles, Kapazitäten, Demand-Regionalisierungsfaktoren, Gen-Type-Mapping und
Emissionsfaktoren — über die eigenständigen, **nicht in diesem Repo liegenden** "Transfer data to database"-Skripte
hochgeladen). Wetter-Cutouts bleiben bewusst als Dateien (Bind-Mount), nicht in der DB.

- **ENTSO-E-Historie**: `entsoe_raw` beginnt erst am 2026-07-21. Davor liegen dieselben Tabellen in den
  Jahres-Schemas `2020_raw` … `2026_raw` (je ein UTC-Jahr). `DBClient` wählt pro Zeitfenster die passenden Schemas
  (seit 2026-11-14), damit sind Läufe ab 2020 möglich. Ein `2019_raw` gibt es nicht.
- **Kapazitäten**: eine Periode pro Monat (`YYYY_MM`) in `capacities_conventional` (pro Bundesland) und
  `capacities_vre` (pro Bundesland × 0,25°-Wetterzelle, seit 2026-11; vorher pro Anlage, ~4,5 Mio. Zeilen pro Monat).
  Fehlt ein Monat, nimmt die Map den neuesten früheren. Hochgeladen ist bisher nur `2026_02`.
- **Zugangsdaten**: alle Skripte und Scheduler lesen `DB_HOST/PORT/NAME/USER/PASSWORD` und `ENTSOE_API_KEY` aus
  Umgebungsvariablen bzw. `.env` (`cosema/pipelines/scheduler_bootstrap.py`). `keys.yaml` wird nicht mehr benutzt.

**Zwei Datenbanken im Spiel**: `co2map` läuft technisch weiter im **Staging**-Compose-Projekt, liest/schreibt
aber inzwischen gegen die **Production**-DB (`CO2MAP_DB_*`-Variablen, siehe `compose.yml`) — weil der
ENTSO-E-Crawler in Staging seit Ende Juli stillsteht, in Production aber weiterläuft. Erreichbar über
`host.docker.internal` (Container kann die öffentliche IP des eigenen Hosts nicht direkt ansprechen).

## Was schon läuft (verifiziert gegen echte Production-Daten)

- Regionalisierung → SIGI-Balancing (Gurobi, WLS-Lizenz) → PyPSA-Netzwerkoptimierung → Flow-Tracing →
  Intensitätsberechnung, Ende-zu-Ende mit plausiblen Werten.
- Keine doppelten Zeilen mehr beim Schreiben (`write_df` überschreibt jetzt statt anzuhängen, InfluxDB-Verhalten
  nachgebildet) — betraf vorher alle sechs `cosema`-Tabellen.
- Gemeinsames Grafana über einen eigenen Traefik-Entrypoint erreichbar (kein eigener Container, keine Domain
  nötig — reines HTTP statt HTTPS/Let's-Encrypt, da Let's Encrypt keine Zertifikate für nackte IPs ausstellt).
- Täglicher Per-Unit-Lauf (ENTSO-E-API direkt, Kraftwerksblock-Ebene) läuft durch, seit ein Bibliotheks-Bug
  (doppelte Zeitstempel an Tagesgrenzen) behoben ist.

## Skripte (`co2map/scripts/`)

Aufruf aus `co2map/`, lokal mit `python -m scripts.<name>` (sonst findet Python `cosema` nicht), im Container geht
auch `python scripts/<name>.py`.

- `manual_runs.py` — manueller Lauf der Pipeline für einen Zeitraum, Monat für Monat (Schritte per Flag).
- `calc_capacities.py` — Kapazitätsdateien für einen Monatsbereich; Upload danach mit `transfer_capacities.py`.
- `calc_hps_intensities.py` — Emissionsfaktor Pumpspeicher für abgeschlossene Jahre, schreibt eine CSV für
  `transfer_generation_data.py`.
- `check_cutouts.py` — prüft Wetter-Cutouts auf Lücken (stille Download-Ausfälle).
- `capacity_utilization_report.py` — Auswertung, wie viel Kapazität/Erzeugung über Blockdaten gemessen vs. verteilt ist.
- `test_pipeline_real_data.py` — manueller Ende-zu-Ende-Test gegen echte Daten.
- Älter, unverändert übernommen: `create_shapefiles.py`, `prepare_demand_data.py`; `sync_from_oeds.py` ist überholt.

## Bekannte offene Punkte

Details und Priorisierung siehe [`plan.md`](plan.md). Kurz:

1. ENTSO-E-Crawler-Verzögerung/-Lücken in Production (extern, gemeldet).
2. Periodisches Nachladen der statischen Referenzdaten (MaStR/Kapazitäten/Demand-Faktoren) — bisher nur
   einmaliger Snapshot, wird als eigener Prefect-Flow separat angegangen.
3. Wetterdaten-API (Open-Meteo-Archiv) war beim letzten Lauf nah an einem eigenen Absturz durch Ratenlimits —
   noch nicht abgesichert.
4. Grafana-Dashboards noch nicht final geprüft/poliert; eigenes Web-Frontend für die Karte — unklar, ob überhaupt
   gewollt.
5. Merge des `co2map-integration`-Branches in `main`/`develop` — bewusst der allerletzte Schritt, noch nicht
   angegangen.
6. Historischer Nachlauf 2020 bis heute: Lesen der Jahres-Schemas und Kapazitäten-Skript stehen, offen sind u.a.
   Kapazitäten für alle Monate, Herkunft der VRE-Faktoren (alte Map oder Wetter-Cutouts) und das Lauf-Skript.

## Wichtige Prinzipien aus der bisherigen Arbeit

- **Nicht eigenmächtig im gemeinsamen Staging-Bereich auf dem Server herumändern** (Branch wechseln, Dateien
  löschen) — andere nutzen denselben Checkout.
- **Keine Secrets/Passwörter in Dateien, die committed werden** — `.env` bleibt lokal/serverseitig, nicht im Git.
- **Upload-/Migrations-Tooling für Rohdaten lebt bewusst außerhalb dieses Repos** (eigener Ordner
  "Transfer data to database") — dieses Repo enthält nur die Lese-Seite.
- Vor Codeänderungen an einer echten Fehlerursache: erst gegen echte Daten verifizieren statt defensiv zu
  patchen — mehrfach bewährt (siehe `historie.md`, u.a. der `NoDataAvailableError`- und der Per-Unit-Fix).
