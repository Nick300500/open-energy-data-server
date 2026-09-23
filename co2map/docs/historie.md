# OEDS-Integration — Historie & Recherche-Verlauf

Chronologischer Verlauf, wie wir zum aktuellen Stand gekommen sind — inklusive verworfener Pläne und inzwischen
überholter Recherche-Ergebnisse. **Für den aktuellen Stand siehe [`README.md`](README.md), für verbleibende
offene Punkte [`plan.md`](plan.md) — diese Datei hier ist reines Archiv, nicht mehr aktiv gepflegt außer bei
neuen historischen Meilensteinen.**

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

- Bestätigt: OEDS hat bereits einen eigenen ENTSO-E-Crawler, der Erzeugung nach Land+Typ, Verbrauch nach Land und
  Cross-Border-Flows liefert — für diese drei Datenarten bräuchten wir vermutlich keine eigene Ingestion mehr, nur
  lesenden Zugriff auf `entsoe_raw`/`entsoe`.
- Kraftwerksblock-Feindaten (per-unit) gibt es dort noch nicht.
- Metabase-Tabellenabgleich (per Screenshot geprüft): 3 von 6 benötigten ENTSO-E-Inputs abgedeckt (Erzeugung,
  Verbrauch, Cross-Border-Flows — Cross-Border in 3 Varianten, davon ist "Physical Flows" die fachlich richtige).
  Wichtiger Fallstrick: Metabase "verschönert" Spalten-/Tabellennamen nur für die Anzeige, echte Namen vor
  Nutzung über pgAdmin/SQL verifizieren.
- `entsoe`-Branch des OEDS-Repos gefunden (`oeds/base_crawler.py`, `oeds/crawler/entsoe_crawler.py`) — zu diesem
  Zeitpunkt als Strukturvorlage für einen eigenen Crawler eingeschätzt (`BaseCrawler`/`ContinuousCrawler`-Muster,
  eigenes Postgres-Schema pro Crawler, Hypertable-Erstellung über die Basisklasse). **Diese Einschätzung wurde am
  2026-08-17 korrigiert, siehe unten** — der Branch ist inzwischen veraltet.
- Separater `entsoe/`-Analyseordner auf diesem Branch enthält Flow-Tracing/Pooling-Funktionen, fachlich nah an
  unserem SIGI-Balancing — Ursprung/Verwandtschaft zu unserer eigenen Logik nie abschließend geklärt.

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

## 2026-08-17: DBClient-Ansatz bestätigt, Crawler-Vorlage revidiert

- **DBClient/SQL-Ansatz bestätigt**: unabhängig genau der Ansatz, den wir schon umgesetzt hatten — keine
  inhaltliche Änderung nötig.
- **Wichtige Korrektur**: Crawler-Skripte liegen mittlerweile **absichtlich nicht mehr im
  `open-energy-data-server`-Repo selbst**, sondern in einem **eigenen, separaten Repository**, das Prefect täglich
  zieht und einmal ausführt. Der `entsoe`-Branch (unsere bisherige Strukturvorlage, `oeds/base_crawler.py`/
  `oeds/crawler/entsoe_crawler.py`) ist **veraltet** — nicht mehr als Vorlage zu benutzen. Von `main` abzweigen
  (wie ursprünglich gesagt), nicht von `entsoe`.
- Damit auch fraglich geworden: die am 2026-08-14 recherchierte `config.yml`/`CrawlerConfig`-Struktur
  (`db_uri`, `entsoe_api_key` etc.) — das war spezifisch fürs alte Crawler-Muster, gilt für unseren Fall evtl.
  nicht mehr (siehe nächster Punkt, 2026-08-19).

## 2026-08-19: Größter Architektur-Pivot

**Zentrale Erkenntnis**: die CO2-Map wird **kein** Prefect-Crawler/-Flow — sie läuft als **dauerhafter Service** in
einem **eigenen Container** (`compose.yml`-Eintrag), analog zu Grafana/der Datenbank im bestehenden Stack. Prefect
ist ausschließlich für wiederkehrende, in sich abgeschlossene Einzelaufgaben gedacht (wie den ENTSO-E-Crawler:
einmal täglich anstoßen, fertig) — nicht für einen Dauerbetrieb.

Das macht den bis dahin recherchierten Prefect-Umbau (`prefect.yaml`, `@flow`-Konvertierung unserer Scheduler,
`config.yml`/`CrawlerConfig`) für unseren Hauptteil **hinfällig**. Stattdessen: eigenes **Dockerfile** + Eintrag in
(vermutlich) OEDS's `compose.yml`. Weitere Klärungen aus diesem Zeitraum:

- **Gurobi**: kein Problem mehr mit einem geteilten Server-Worker — kommt isoliert ins eigene Dockerfile. Nur noch
  offen: richtige Lizenzform besorgen (Linux/floating statt der alten Windows-WSL-Lizenz).
- **Grafana**: keine Rückfrage nötig — wir wissen aus der 2026-08-12-Recherche schon, dass OEDS ein gemeinsames
  Grafana betreibt (Dashboard-JSON-Provisionierung), unsere fertigen `*_timescaledb.json`-Dashboards docken dort
  an, kein eigener Container nötig. **Revidiert am 2026-09-03, siehe unten** — im tatsächlich laufenden
  `compose.yml` gab es zu dem Zeitpunkt noch gar keinen aktiven Grafana-Service.
- **Große Dateien**: Vorschlag, regelmäßig aktualisierte Daten könnten in die normale DB + ein
  Prefect-automatisiertes Sync-Skript. Das passt gut auf die echte Zeitreihe (Wetter-Cutouts), fraglich für MaStR
  (ein Register, keine Zeitreihe) — MaStR sollte aber ausdrücklich auch in die DB. Als Alternativvorschlag
  entwickelt: MaStR (liegt lokal als SQLite `.db` vor) ließe sich als eigenes, normales Postgres-Schema migrieren
  (keine Hypertable, da nicht zeitindiziert) — z.B. über `pandas.read_sql`/`to_sql`, analog zu dem, was
  `DBClient.write_df` schon kann.
- Klassifizierung der großen Dateien nach Zeitreihen-Eigenschaft erarbeitet: MaStR/Shapefiles/Netzwerk-Dateien =
  statisch (keine Zeitreihe), Wetter-Cutouts = echte Zeitreihe, Kapazitäts-Parquets/Demand-Faktoren = grobe
  periodische Schnappschüsse (monatlich/jährlich).
- TimescaleDB-Erweiterung auf dem Server: unklar, ob/wie stark genutzt, vermutlich nicht kritisch, falls nicht
  vorhanden. Unser `DBClient` legt eigene Tabellen als Hypertables an, setzt das also implizit voraus.

## 2026-08-28/29: Erster echter Deploy, Gurobi-Lizenz, End-to-End-Verifikation

Der `co2map`-Service läuft seit 2026-08-28 produktiv im Staging-`compose.yml` des Servers (eigener Container,
`./co2map:/app` als Live-Mount statt Rebuild bei jeder Änderung — `git pull` + `docker compose up -d --build
co2map` reicht). Alle drei Scheduler (`initial_calculations`, `updated_calculations`, `forecast_calculations`)
laufen stabil, keine Crash-Loops mehr. Iterative Fixes dazu (u.a. lokale-Datei-Reste, Capacity-Lookback,
Logging-Sichtbarkeit, Spalten-Inkonsistenz `demand_reg_factors`) sind im Git-Log dokumentiert, nicht hier
dupliziert.

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

**Verifikation der Fachlogik** (Anlass: der ENTSO-E-Crawler von OEDS stand seit 2026-07-27 für alle
Zonen/Datenarten still, wodurch die Live-Läufe nur Nullwerte sahen und `calc_intensities.py` mit einem
`IndexError` abstürzte — auf ausdrücklichen Wunsch **nicht** defensiv gepatcht, sondern stattdessen echt
verifiziert). Eigens dafür `scripts/test_pipeline_real_data.py` gebaut: Pipeline für ein bestätigtes
Echtdaten-Fenster (2026-07-21–22) ohne eigene Downloads laufen lassen. Ergebnis am 2026-08-29 (nach Einbau der
WLS-Lizenz): komplette Pipeline läuft durch — Regionalisierung, SIGI-Balancing, PyPSA/Gurobi-Netzwerkoptimierung
(optimale Lösung), Flow-Tracing, Intensitätsberechnung, Schreiben in `cosema.co2_intensity`. Nur erwartete
Datenlücken-Warnings (fehlende VRE-/Länderdaten im Testfenster), kein Fehler. Bestätigt: die Kernlogik war die
ganze Zeit korrekt, der `IndexError` war ausschließlich ein Symptom der Nulldaten während des Crawler-Ausfalls,
kein eigener Bug — der Ausfall wurde separat gemeldet.

## 2026-09-02 bis 2026-09-07: Robustheitsfix, gemeinsames Grafana, Umstellung auf Production-DB

**Robustheitsfix für Nulldaten-Fenster** (2026-09-02): der am 2026-08-29 bewusst ungepatchte `IndexError` in
`calc_intensities.py::collect_and_prepare_data` (siehe Eintrag oben) tritt seit dem Crawler-Ausfall stündlich in
den Live-Läufen auf. Statt eines defensiven Patches, der explizit abgelehnt worden war, jetzt eine saubere, klar
erkennbare Lösung: neue `NoDataAvailableError`, geworfen wenn ein Zeitfenster *komplett* ohne echte Daten ist
(alle Zeilen null) — abgefangen in `calculate_intensities` mit einer eindeutigen `WARNING`-Zeile ("... not a code
error, likely an upstream data gap") statt Absturz. Teilweise Lücken bleiben unverändert (weiterhin nullgefüllt
und normal verarbeitet), nur der vollständig-leere Fall wird jetzt sauber übersprungen.

**Gemeinsames Grafana als eigener Container** (2026-09-03/04): Review-Feedback zum `co2map`-Block in
`compose.yml` (fehlender Port + Frage nach der Visualisierung, zu viele Kommentare, Service-Reihenfolge zwischen
den beiden Metabase-Containern) plus Entscheidung zur Grafana-Frage: eigener Container, nicht im `co2map`-
Container gebündelt. Dabei fiel auf: `co2map` hat **kein eigenes Web-Frontend** (kein Flask/Streamlit/o.ä. im
portierten Code) — die Visualisierung war immer als Grafana-Dashboards gedacht, nicht als eigene
"Karten"-Weboberfläche; ob eine solche separat erwartet wird, ist noch unklar.

Umgesetzt: neuer `grafana`-Service (`grafana/grafana-oss`, eigener Port über `GRAFANA_PORT`), `datasource.yml`
korrigiert (zeigte noch auf die nicht mehr existierende `open-data-16`, Passwort war hart auf `readonly` codiert
statt über Grafanas `$__env{}`-Provisioning-Syntax aus `READONLY_PW`), Platzhalter in `dashboardproviders/
opendata.yml` ausgefüllt, unsere drei `*_timescaledb.json`-Dashboards in den gemeinsamen Provisioning-Ordner
kopiert. Zwei Stolperfallen dabei, gleiches Muster wie schon bei `gurobi.lic`: Docker legte `./data/grafana` beim
allerersten Start automatisch als `root`-Verzeichnis an (Grafana-Image läuft intern als UID 472, kein
Schreibzugriff, kein `sudo` verfügbar) — gelöst wie bei `pgadmin` schon vorgemacht, mit `user: root` im Service.
Danach lief Grafana zwar, war aber von außen nicht erreichbar (`curl` lokal auf dem Server lieferte sauber `302`,
von außen Timeout) — Port `4002` war schlicht noch nicht in der Server-Firewall freigegeben, Freigabe angefragt.
Direkt danach noch ein Strukturfehler beim manuellen Nachziehen der Service-Reihenfolge gefunden und korrigiert
(`co2map`-Block landete versehentlich hinter dem `networks:`-Top-Level-Key statt unter `services:` —
`docker compose config` hätte das beim nächsten Deploy hart abgelehnt).

**Umstellung auf die Production-DB** (2026-09-04, laufend): Entscheidung, `co2map` an die Production-DB
anzubinden — Hintergrund: der ENTSO-E-Crawler läuft in Production unverändert weiter (nur Staging steht seit
2026-07-27 still), ansonsten sind Schema/Daten identisch. `co2map` läuft technisch weiterhin im Staging-
Compose-Projekt, erreicht die Production-DB daher nicht über einen internen Servicenamen, sondern über die externe
Serveradresse + Production's extern gemapptem Port (`132.230.100.67:6432`, analog zum bisherigen Zugriffsmuster
für Staging über `:7432`). Umgesetzt über neue, `co2map`-eigene `CO2MAP_DB_*`-Variablen in `compose.yml`
(bewusst **nicht** die bestehenden `DB_HOST`/`DB_PORT`/etc. wiederverwendet, da die weiterhin von `open-data-17`
selbst, `prefect-worker` und `open-postgrest` für die Staging-DB gebraucht werden).

**Aktueller Blocker (Stand 2026-09-07, Server gerade nicht erreichbar)**: `entsoe_raw`/`cosema_inputs` hängen im
Code an derselben DB-Verbindung (`cosema/input_output/db_engine.py`) — die Umstellung auf Production zieht also
auch `cosema_inputs` (MaStR, Shapefiles, Capacities, Demand-Faktoren, Gen-Type-Mapping) mit, das aber nur einmalig
in die **Staging**-DB migriert wurde, nie nach Production. Container crasht seither mit `UndefinedTable:
cosema_inputs.gen_types_and_emission_factors`. Direkter Check gegen die Production-DB bestätigt: Schema
`cosema_inputs` existiert dort noch gar nicht (0 Tabellen). Erster Versuch, die "Transfer data to database"-
Skripte gegen Production erneut laufen zu lassen, ist fehlgeschlagen, weil die lokal editierte `.env` beim
Skriptlauf noch nicht gespeichert war (`python-dotenv` las also weiterhin die alten Staging-Werte) — die Skripte
liefen dadurch effektiv nochmal gegen Staging (harmlos, dort lag alles schon, nur am falschen Ziel). Noch offen:
`.env` diesmal wirklich gespeichert nochmal gegen Production laufen lassen, sobald der Server wieder erreichbar
ist.

## 2026-09-13 bis 2026-09-22: Production-DB-Verbindung, Grafana über Traefik, Doppelte-Zeilen-Fix

**Production-DB erreichbar gemacht** (2026-09-21): Der Container konnte die öffentliche IP des eigenen Hosts von
innen nicht erreichen (`Network is unreachable` auf Port 6432) — klassisches Docker-Verhalten, ein Container
erreicht die externe Adresse seines eigenen Hosts oft nicht direkt. Gelöst über `extra_hosts:
host.docker.internal:host-gateway` im `co2map`-Service plus `CO2MAP_DB_HOST=host.docker.internal` in der `.env`.
Danach fehlte noch das komplette `cosema_inputs`-Schema in Production (nur einmalig nach Staging migriert) — die
"Transfer data to database"-Skripte erneut gegen Production laufen lassen, diesmal mit tatsächlich gespeicherter
`.env`, hat alle 16 Tabellen angelegt.

**Grafana über Traefik statt direktem Port** (2026-09-13/14): Auf Nachfrage zur Visualisierung (kein eigenes
Web-Frontend im portierten Code, nur Grafana-Dashboards geplant) und zur Reverse-Proxy-Frage kam die Rückmeldung,
Grafana wie Metabase über Traefik zu routen, aber ohne eigene Domain (nur `<ip>:<port>`). Traefiks eigene Config
(`/srv/traefik/`, nicht Teil dieses Repos) zeigt: Let's Encrypt stellt grundsätzlich keine Zertifikate für nackte
IPs aus, und der `web`-Entrypoint (Port 80) leitet zwingend auf HTTPS um — das Metabase-Muster (Host-Domain +
`websecure` + Zertifikat) funktioniert also nur mit Domain. Stattdessen: eigener, dedizierter `grafana`-Entrypoint
(reines HTTP, kein Zertifikat) analog zum bestehenden `ping`-Entrypoint. Das spart keinen Firewall-Eintrag (der
neue Port muss trotzdem freigegeben werden), zentralisiert aber das Routing in Traefik. Umgesetzt in
`compose.yml` (Labels + `networks: default, proxy` statt `ports:`); die beiden nötigen Ergänzungen in Traefiks
eigener Config (neuer Entrypoint, neuer Port) liegen außerhalb des Repo-Zugriffs.

**Nach der Umstellung: stündlicher Live-Lauf findet keine Daten** — Testlauf für ein Fenster ohne ENTSO-E-Daten
(18.09.) ergab durchgehend 0 g/kWh. Systematische Prüfung der `entsoe_raw`-Tabellen ergab zwei getrennte Befunde,
beide gemeldet: (1) an mehreren Tagen (30.08.–01.09., 05.–07.09., 15.–18.09.) fand für **alle** Zonen gleichzeitig
kein Crawler-Lauf statt (erkennbar an der `download_timestamp`-Spalte) — der Crawler holt verpasste Tage nicht von
selbst nach; (2) die aktuellsten Daten hinken der Gegenwart 1–2 Tage hinterher (Verbrauch stand am 21.09. erst bei
19.09. 21:45 UTC), was ausschließlich den stündlichen Live-Lauf betrifft (24h-Fenster bis "jetzt") — der tägliche
Lauf (Fenster endet 7 Tage in der Vergangenheit) ist davon nicht betroffen.

**Gefundener und behobener Bug: Doppelte Zeilen durch fehlendes Überschreiben** (2026-09-21/22): Beim
Nachrechnen eines lückenlosen Tages (10.09.) fielen unplausible Summen auf (z.B. Solar in Baden-Württemberg
~23.000 statt ~2.200 MW). Ursache: `DBClient.write_df` hängt bei jedem Schreiben nur an (`if_exists="append"`).
Da die Scheduler-Fenster sich stark überlappen (stündlicher Lauf rechnet z.B. jede Stunde bis zu 24-mal neu),
sammelten sich pro Zeitstempel bis zu 26 Zeilen an, und die Leser summierten/mittelten unbemerkt über alle. Bei
InfluxDB (vor der Portierung) überschrieb ein neuer Punkt mit gleichem Zeitstempel und gleichen Tags automatisch
den alten — dieses Verhalten fehlte in der Postgres-Version komplett. Betroffen waren alle sechs `cosema`-Tabellen
in unterschiedlichem Ausmaß (53–89 % überzählige Zeilen).

Fix: `write_df` löscht jetzt vor dem Einfügen die vorhandenen Zeilen mit gleichem Zeitstempel, gleichen Tags und
mindestens einer befüllten Spalte, in derselben Transaktion. Lokal gegen eine echte TimescaleDB verifiziert
(wiederholtes/überlappendes Schreiben, andere Tags unberührt, Leser-Summe korrekt, `vre_gen`s getrennte
Erzeugungs-/Regionalfaktor-Schreibvorgänge bleiben nebeneinander bestehen). Danach in Production: die drei
Ergebnistabellen (`co2_intensity`, `reg_generation`, `reg_demand`) geleert (bewusste Entscheidung für einen
sauberen Neustart statt Rekonstruktion der alten, teils widersprüchlichen Werte), `vre_gen`/`per_unit_gen`
verlustfrei entdoppelt (dortige Duplikate waren identisch), `vre_forecast` unverändert gelassen. Ein Neustart des
`co2map`-Containers war zusätzlich nötig, da die drei Scheduler als langlebige Python-Prozesse laufen und
geänderten Code erst nach einem Neustart sehen, nicht nach einem reinen `git pull`. Im Live-Betrieb danach mit
zwei aufeinanderfolgenden Läufen für dasselbe Zeitfenster verifiziert: genau eine Zeile pro Stunde statt Duplikate.

**Offen**: der stündliche Live-Lauf schreibt weiterhin Nullzeilen in `reg_generation`/`reg_demand` für die letzten
1–2 Stunden, für die der Crawler noch keine Daten hat (der `NoDataAvailableError`-Schutz greift erst eine Stufe
später, bei der Intensitätsberechnung). Lösung hängt an der Antwort zur Crawler-Verzögerung — entweder das
Live-Fenster bei uns versetzen, oder den Regionalisierungs-Schritt bei fehlenden Daten ebenfalls überspringen.

## 2026-09-23: Absturz im täglichen Per-Unit-Lauf behoben, Beinahe-Absturz bei der Wetter-API entdeckt

**Ursache des `InvalidIndexError`-Absturzes gefunden und behoben**: der tägliche Lauf (`updated_calculations`,
Modus `with_per_unit`) crashte in `regional_split.py::preprocess_gen_per_unit` beim Zusammenführen der
Kraftwerksblock-Zeitreihen (`pd.concat(..., axis=1)`), weil einzelne Blöcke doppelte Zeitstempel hatten. Ursache
in der externen `entsoe-py`-Bibliothek (`^0.7.0`): der `day_limited`-Decorator zerlegt mehrtägige Anfragen in
Tagesblöcke und schneidet jeden mit `df.truncate(before=_start, after=_end)` zu — `truncate` ist an **beiden**
Enden einschließlich, und benachbarte Tagesblöcke teilen sich ihre Grenze, wodurch der Grenz-Zeitstempel doppelt
zurückkommt. Empirisch bestätigt: 49.174 doppelte (Block, Zeit)-Kombinationen in `cosema.per_unit_gen`, nie mit
widersprüchlichen echten Werten (nur identische Werte oder beidseitig `NULL` — Kraftwerksblöcke mit
Berichtslücken reiten strukturell auf demselben Bug mit).

Fix an zwei Stellen: direkt nach dem Download in `cosema/ingestion/entsoe.py::download_per_unit_data` (verhindert,
dass Duplikate je gespeichert werden) und defensiv in `regional_split.py::preprocess_gen_per_unit` (schützt vor
Altbestand und jeder anderen künftigen Quelle nicht-eindeutiger Zeitstempel). Die 81.214 überzähligen Alt-Zeilen
in `cosema.per_unit_gen` wurden bereinigt, mit Sicherheitsprüfung pro Schlüssel (jede Gruppe mit echtem Wert
behält nach der Bereinigung genau einen echten Wert) statt eines pauschalen Vorher/Nachher-Zeilenvergleichs — ein
erster Versuch mit der falschen Prüfung hätte harmlose Duplikat-Entfernung fälschlich als Datenverlust gewertet
und wurde automatisch zurückgerollt, bevor irgendwas geändert war.

**Separat entdeckt, beim Einordnen der Logs**: im selben Tageslauf (vor dem Absturz, beim Wetter-Cutout für
`run_vre_historical`) gab es mehrfache `Minutely API request limit exceeded`/Timeout-Meldungen von der
Copernicus/Open-Meteo-Wetter-API (`Vendor/atlite/datasets/meteo_hist.py::urlopen_with_retry`,
`@retry(tries=5, delay=5, backoff=2)`, also maximal 5 Versuche). Die Wartezeiten in den Logs (5s → 10s → 20s)
zeigen: es hat erst der **4. von 5** möglichen Versuchen geklappt — ein weiterer Fehlschlag hätte auch diesen
Schritt zum Absturz gebracht, mit denselben Folgen wie der Per-Unit-Bug (kompletter Tageslauf-Abbruch). Kein
eigener Code-Fehler, sondern eine externe Ratenlimit-Situation, aber ein echter Beinahe-Fall, kein reines
Log-Rauschen. **Noch nicht behoben** — mögliche Ansätze: mehr Versuche/höhere Basiswartezeit, oder ein
eigenständiger, nicht-fataler Fehlerpfad für einen einzelnen fehlgeschlagenen Cutout-Download statt Absturz des
ganzen Laufs.

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

**Metabase**: Screenshots (Datenbank `opendata`, Schemas `entsoe_raw` und `entsoe`), Stand 2026-08-12.
