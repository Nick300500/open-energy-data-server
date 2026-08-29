# OEDS-Integration — Historie & Recherche-Verlauf

Chronologischer Verlauf, wie wir zum aktuellen Stand gekommen sind — inklusive verworfener Pläne und inzwischen
überholter Recherche-Ergebnisse. **Für den aktuellen Plan siehe [`oeds_integration_plan.md`](oeds_integration_plan.md)
— diese Datei hier ist reines Archiv, nicht mehr aktiv gepflegt außer bei neuen historischen Meilensteinen.**

## 2026-08-04: Ursprünglicher Plan — Lift-and-Shift (verworfen)

Erster Ansatz: die bestehende lokale Pipeline (InfluxDB, eigene APScheduler, Grafana) unverändert zusätzlich auf
den Zielserver bringen, ohne inhaltliche Integration in den dortigen Stack. Geplante Phasen 0–7: Server-Zugang,
Code-Transfer, Secrets/Config, Docker-Services (eigener InfluxDB-Container), Python-Umgebung/Gurobi, statische
Input-Dateien, Scheduler-Betrieb (nohup/systemd), Verifikation.

**Verworfen am 2026-08-12**: zu hoher Aufwand für reinen Parallelbetrieb ohne echten Mehrwert, stattdessen
Entscheidung für echte Integration in den bestehenden Open-Energy-Data-Server-Stack (OEDS,
`github.com/INATECH-CIG/open-energy-data-server`) — Postgres/TimescaleDB statt InfluxDB, dessen Prefect/Grafana
statt eigener Instanzen. Vergleich Lift-and-Shift (17–32 h) vs. echte Integration (55–90 h, damals geschätzt).

Zwei Detailpunkte aus dieser Phase blieben relevant und sind in den aktuellen Plan übernommen: die
Gurobi/Lizenzfrage (README erwähnte eine an Windows/WSL gebundene Lizenz) und die Liste der großen,
nicht-tabellarischen Input-Dateien.

## 2026-08-12: Erste Recherche zum OEDS-Repo

- Server-Kollege bestätigt: OEDS hat bereits einen eigenen ENTSO-E-Crawler, der Erzeugung nach Land+Typ, Verbrauch
  nach Land und Cross-Border-Flows liefert — für diese drei Datenarten bräuchten wir vermutlich keine eigene
  Ingestion mehr, nur lesenden Zugriff auf `entsoe_raw`/`entsoe`.
- Kraftwerksblock-Feindaten (per-unit) gibt es dort noch nicht.
- Metabase-Tabellenabgleich (Screenshots von Nick): 3 von 6 benötigten ENTSO-E-Inputs abgedeckt (Erzeugung,
  Verbrauch, Cross-Border-Flows — Cross-Border in 3 Varianten, davon ist "Physical Flows" die fachlich richtige).
  Wichtiger Fallstrick: Metabase "verschönert" Spalten-/Tabellennamen nur für die Anzeige, echte Namen vor
  Nutzung über pgAdmin/SQL verifizieren.
- `entsoe`-Branch des OEDS-Repos gefunden (`oeds/base_crawler.py`, `oeds/crawler/entsoe_crawler.py`) — zu diesem
  Zeitpunkt als Strukturvorlage für einen eigenen Crawler eingeschätzt (`BaseCrawler`/`ContinuousCrawler`-Muster,
  eigenes Postgres-Schema pro Crawler, Hypertable-Erstellung über die Basisklasse). **Diese Einschätzung wurde am
  2026-08-17 korrigiert, siehe unten** — der Branch ist inzwischen veraltet.
- Separater `entsoe/`-Analyseordner auf diesem Branch enthält Flow-Tracing/Pooling-Funktionen, fachlich nah an
  unserem SIGI-Balancing — Ursprung/Verwandtschaft zu unserer eigenen Logik nie abschließend geklärt (offene
  Frage ans Meeting, siehe unten).

## 2026-08-13/14: DBClient-Umbau (eigener Task)

Eigene, dedizierte Session mit Auftrag `TASK_dbclient_rewrite.md` (Auftragstext siehe unten). Ergebnis:

- `cosema/input_output/influxdb.py` (Klasse `DBClient` + Modul-Wrapper) komplett von InfluxDB/InfluxQL auf
  SQLAlchemy/TimescaleDB/SQL portiert, gleiche Methodennamen/-signaturen.
- **Scope-Entscheidung**: kompletter 1:1-Port aller Methoden auf eigene Tabellen, auch für die drei Methoden, die
  später lesend an OEDS andocken könnten (`query_per_type_gen`, `query_demand_data`, `query_cross_border_flows`)
  — kein Serverzugriff zu dem Zeitpunkt, Gap-Filling-Methodik von OEDS noch nicht verifiziert.
- Design: Tabellen werden dynamisch pro `measurement` angelegt (Tags → Spalten), damit `write_df()` weiterhin so
  funktioniert wie direkt aus `cosema/ingestion/entsoe.py` aufgerufen. `query_per_unit_gen` gibt jetzt ein `dict`
  statt InfluxDB-`ResultSet` zurück.
- Lokal gegen Docker-TimescaleDB verifiziert: 13/13 Checks auf `DBClient`-Ebene, 11/11 auf Wrapper-Ebene.
- `tests/golden_master`: lief zunächst nicht (`pypsa.linopt`-Fehler) — stellte sich als falsche Python-Umgebung
  heraus (System-Python statt Conda-Env `cosema`), kein echter Bug. Mit korrektem Interpreter: 1 passed.
- `pyproject.toml`: `influxdb`-Abhängigkeit gegen `sqlalchemy`/`psycopg2-binary` getauscht.
- Ergebnis liegt auf eigenem Branch **`dbclient-timescaledb`** (Commit `0165922`), `modularisierung-merged`
  unverändert gelassen (Produktivbetrieb läuft weiter mit InfluxDB). Zwei parallele Worktrees eingerichtet
  (`CO2_Intensity` und `CO2_Intensity-modularisierung-merged`), damit beide Stände gleichzeitig einsehbar sind.
- Merge-Entscheidung: bewusst vertagt, passiert erst ganz am Ende (nach der OEDS-Anbindung), nicht vorher.

**Direkt danach (noch 2026-08-14)**: alle 3 Grafana-Dashboards (`Inputs.json`, `outputs.json`, `validation.json`)
ebenfalls auf SQL/TimescaleDB umgeschrieben (`*_timescaledb.json`), neue Postgres-Datasource ergänzt, lokal gegen
echtes Grafana + Docker-TimescaleDB verifiziert (24/24 Panel-Queries laufen). Dabei mehrere vorbestehende Bugs im
InfluxDB-Original gefunden und gefixt: falsche Tabellen (`Capacities`/nicht existierende `$Scenario`-Variable für
"Solar"), falscher Tag-Wert (`technology = 'Oil'`/`'Onshore'` statt `'Fossil Oil'`/`'Wind Onshore'`), ein
Tippfehler (`mode = 'api_version'` statt `$mode`-Variable), ein systematisches `/4` bei mehreren Technologien
(vierteilte stündliche Werte fälschlich), Storage-Vorzeichen-Inkonsistenz zwischen den Dashboards, falsche Tabelle
in mehreren regionalen Panels (`per_type_gen` statt `reg_generation`). Bewusst **nicht migriert**, klar als TODO
markiert: das "Generation per unit"-Panel (fragte nie die richtige Tabelle ab) und alle "(balanced)"-Panels in
`validation.json` (Zieltabellen wurden nie von irgendeinem Code beschrieben — fehlende Funktion, kein
Übersetzungsbug). Committed als eigener Commit `949c4c0` auf `dbclient-timescaledb`.

Auch an diesem Tag: Dateigrößen der großen statischen Inputs ermittelt (MaStR-DB ~13 GB dominiert, Rest ~400 MB)
und Secrets-Struktur von OEDS konkret recherchiert (`.env_template`, `oeds/base_crawler.py::load_config()`) —
letzteres beruhte auf dem `entsoe`-Branch und ist seit 2026-08-17 mit Vorsicht zu genießen (siehe unten).

## 2026-08-17: Kollegen-Mail — DBClient-Ansatz bestätigt, Crawler-Vorlage revidiert

- **DBClient/SQL-Ansatz bestätigt**: Kollege beschreibt unabhängig genau den Ansatz, den wir schon umgesetzt
  hatten — keine inhaltliche Änderung nötig.
- **Wichtige Korrektur**: Crawler-Skripte liegen mittlerweile **absichtlich nicht mehr im
  `open-energy-data-server`-Repo selbst**, sondern in einem **eigenen, separaten Repository**, das Prefect täglich
  zieht und einmal ausführt. Der `entsoe`-Branch (unsere bisherige Strukturvorlage, `oeds/base_crawler.py`/
  `oeds/crawler/entsoe_crawler.py`) ist **veraltet** — nicht mehr als Vorlage zu benutzen. Von `main` abzweigen
  (wie ursprünglich gesagt), nicht von `entsoe`.
- Damit auch fraglich geworden: die am 2026-08-14 recherchierte `config.yml`/`CrawlerConfig`-Struktur
  (`db_uri`, `entsoe_api_key` etc.) — das war spezifisch fürs alte Crawler-Muster, gilt für unseren Fall evtl.
  nicht mehr (siehe nächster Punkt, 2026-08-19).

## 2026-08-19: Meeting mit dem Server-Kollegen — größter Architektur-Pivot

**Zentrale Erkenntnis**: die CO2-Map wird **kein** Prefect-Crawler/-Flow — sie läuft als **dauerhafter Service** in
einem **eigenen Container** (`compose.yml`-Eintrag), analog zu Grafana/der Datenbank im bestehenden Stack. Prefect
ist ausschließlich für wiederkehrende, in sich abgeschlossene Einzelaufgaben gedacht (wie den ENTSO-E-Crawler:
einmal täglich anstoßen, fertig) — nicht für einen Dauerbetrieb.

Das macht den bis dahin recherchierten Prefect-Umbau (`prefect.yaml`, `@flow`-Konvertierung unserer Scheduler,
`config.yml`/`CrawlerConfig`) für unseren Hauptteil **hinfällig**. Stattdessen: eigenes **Dockerfile** + Eintrag in
(vermutlich) OEDS's `compose.yml`. Weitere Klärungen aus diesem Austausch:

- **Gurobi**: kein Problem mehr mit einem geteilten Server-Worker — kommt isoliert ins eigene Dockerfile. Nur noch
  offen: richtige Lizenzform besorgen (Linux/floating statt der alten Windows-WSL-Lizenz).
- **Grafana**: keine Rückfrage nötig — wir wissen aus der 2026-08-12-Recherche schon, dass OEDS ein gemeinsames
  Grafana betreibt (Dashboard-JSON-Provisionierung), unsere fertigen `*_timescaledb.json`-Dashboards docken dort
  an, kein eigener Container nötig.
- **Große Dateien**: Kollege schlägt vor, regelmäßig aktualisierte Daten könnten in die normale DB + ein
  Prefect-automatisiertes Sync-Skript. Nachfrage unsererseits: das passt gut auf die echte Zeitreihe
  (Wetter-Cutouts), fraglich für MaStR (ein Register, keine Zeitreihe) — Kollege wollte MaStR aber ausdrücklich
  auch in die DB haben. Als Alternativvorschlag entwickelt: MaStR (liegt lokal als SQLite `.db` vor) ließe sich
  als eigenes, normales Postgres-Schema migrieren (keine Hypertable, da nicht zeitindiziert) — z.B. über
  `pandas.read_sql`/`to_sql`, analog zu dem, was `DBClient.write_df` schon kann.
- Klassifizierung der großen Dateien nach Zeitreihen-Eigenschaft erarbeitet: MaStR/Shapefiles/Netzwerk-Dateien =
  statisch (keine Zeitreihe), Wetter-Cutouts = echte Zeitreihe, Kapazitäts-Parquets/Demand-Faktoren = grobe
  periodische Schnappschüsse (monatlich/jährlich).
- TimescaleDB-Erweiterung auf dem Server: unklar, ob/wie stark genutzt — laut Kollege "nicht dramatisch", falls
  nicht vorhanden. Unser `DBClient` legt eigene Tabellen als Hypertables an, setzt das also implizit voraus.

## 2026-08-28/29: Erster echter Deploy, Gurobi-Lizenz, End-to-End-Verifikation

Der `co2map`-Service läuft seit 2026-08-28 produktiv im Staging-`compose.yml` des Servers (eigener Container,
`./co2map:/app` als Live-Mount statt Rebuild bei jeder Änderung — Frage 3 oben damit beantwortet: `git pull` +
`docker compose up -d --build co2map` reicht). Alle drei Scheduler (`initial_calculations`,
`updated_calculations`, `forecast_calculations`) laufen stabil, keine Crash-Loops mehr. Iterative Fixes dazu (u.a.
lokale-Datei-Reste, Capacity-Lookback, Logging-Sichtbarkeit, Spalten-Inkonsistenz `demand_reg_factors`) sind im
Git-Log dokumentiert, nicht hier dupliziert.

**Gurobi-Lizenz**: die alte Windows/WSL-gebundene Lizenz (siehe Eintrag 2026-08-04) ist am 2025-11-24 abgelaufen.
Für den Server-Container **Gurobi WLS (Web License Service)** beantragt statt einer normalen Named-User-
Akademiklizenz — Named-User verlangt eine Aktivierung im Uni-Netzwerk, was ein externer Server nicht erfüllt; WLS
funktioniert von überall, genau für Cloud-/Container-Deployments gedacht. Eingebaut wie die anderen Secrets
(`ENTSOE_API_KEY`, `CDSAPI_KEY`): `gurobi.lic`-Datei liegt **außerhalb des Repos** unter
`data/co2map-secrets/gurobi.lic` auf dem Server (nicht committed), read-only in den Container gemountet
(`/app/gurobi.lic`), `GRB_LICENSE_FILE` zeigt darauf. Stolperfalle beim ersten Einrichten: Docker legt beim
allerersten Hochfahren automatisch ein leeres Verzeichnis am Bind-Mount-Ziel an, falls die Quelldatei zu dem
Zeitpunkt noch nicht existiert — sowohl host- als auch containerseitig (`/app/gurobi.lic` lag da schon als leerer
Ordner in der `./co2map`-Repo-Kopie). Nach Anlegen der echten Datei musste dieser Ordner manuell entfernt und der
Container mit `docker compose rm -f co2map` (nicht nur `restart`) neu angelegt werden, damit der Mount als Datei
statt Verzeichnis erkannt wird.

**Verifikation der Fachlogik** (Anlass: der Community-ENTSO-E-Crawler von OEDS stand seit 2026-07-27 für alle
Zonen/Datenarten still, wodurch die Live-Läufe nur Nullwerte sahen und `calc_intensities.py` mit einem
`IndexError` abstürzte — auf ausdrücklichen Wunsch **nicht** defensiv gepatcht, sondern stattdessen echt
verifiziert). Eigens dafür `scripts/test_pipeline_real_data.py` gebaut: Pipeline für ein bestätigtes
Echtdaten-Fenster (2026-07-21–22) ohne eigene Downloads laufen lassen. Ergebnis am 2026-08-29 (nach Einbau der
WLS-Lizenz): komplette Pipeline läuft durch — Regionalisierung, SIGI-Balancing, PyPSA/Gurobi-Netzwerkoptimierung
(optimale Lösung), Flow-Tracing, Intensitätsberechnung, Schreiben in `cosema.co2_intensity`. Nur erwartete
Datenlücken-Warnings (fehlende VRE-/Länderdaten im Testfenster), kein Fehler. Bestätigt: die Kernlogik war die
ganze Zeit korrekt, der `IndexError` war ausschließlich ein Symptom der Nulldaten während des Crawler-Ausfalls,
kein eigener Bug — der Ausfall wurde separat beim Server-Kollegen gemeldet.

## Referenzierte Auftragstexte (archiviert)

### `TASK_dbclient_rewrite.md` (ursprünglicher Auftrag, Task jetzt abgeschlossen)

Auftrag für eine dedizierte Session (2026-08-13): `cosema/input_output/influxdb.py` (Klasse `DBClient` + Modul-
Hilfsfunktionen) durch eine äquivalente TimescaleDB/Postgres-Implementierung ersetzen, gleiche Methodennamen/
-signaturen, damit die restliche Pipeline (13 aufrufende Dateien) unverändert bleibt. Explizit nicht Teil des
Tasks: Prefect-Umbau, Secrets/Config-Umstellung, Gurobi/Worker-Thema, Grafana-Dashboards, `entsoe/`-Ordner-
Entscheidung. Lokales Testsetup: `docker run ... timescale/timescaledb-ha:pg17-oss`. Ergebnis siehe Eintrag
2026-08-13/14 oben — Task vollständig erledigt.

### `server_umzug_plan.md` (ursprünglicher Lift-and-Shift-Plan, verworfen)

Siehe Eintrag 2026-08-04 oben — vollständiger Phasenplan (0–7) für unveränderten Parallelbetrieb auf dem Server,
verworfen zugunsten der echten OEDS-Integration.

## Quellen der Recherche (GitHub, öffentlich)

**`main`-Branch** (Stand 2026-08-12): `README.md`, `compose.yml`, `docs/source/getting_started.md`,
`docs/source/minimal_walkthrough/*`, `pyproject.toml`, `requirements.txt`, `.env_template`, `.gitlab-ci.yml`.

**`entsoe`-Branch** (Stand 2026-08-12, **seit 2026-08-17 als veraltet bestätigt, nicht mehr als Strukturvorlage
verwenden**): `oeds/base_crawler.py`, `oeds/crawler/entsoe_crawler.py`, `Dockerfile.prefect-worker`,
`entsoe/main.py`, `entsoe/config.py`, `entsoe/postgres_utils.py`,
`entsoe/inputs/generation_data/gen_types_and_emission_factors.csv`, Funktionssignaturen aus `entsoe/data_analysis.py`.

**Metabase**: Screenshots von Nick (Datenbank `opendata`, Schemas `entsoe_raw` und `entsoe`), Stand 2026-08-12.
