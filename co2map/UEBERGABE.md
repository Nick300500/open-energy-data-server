# Übergabe: CO2-Map-Integration in den Open-Energy-Data-Server

Diese Datei ist der Einstiegspunkt für die Arbeit **in diesem Repo** (Fork von
`INATECH-CIG/open-energy-data-server`, Branch `co2map-integration`). Der vorherige Teil der Arbeit (DBClient-Umbau
auf Postgres/TimescaleDB, Grafana-Dashboards) lief im separaten Repo `CO2_Intensity` — dessen Planungs-Historie ist
hier nicht 1:1 mitkopiert, nur das Ergebnis (Code im `co2map/`-Unterordner).

## Kontext in Kürze

Die CO2-Intensitäts-Karte (`cosema`, hier unter `co2map/`) soll in den bestehenden Open-Energy-Data-Server (OEDS)
integriert werden — echte Integration in dessen Stack (Postgres/TimescaleDB, Prefect, Metabase), kein
unveränderter Parallelbetrieb des alten eigenen Stacks (InfluxDB/eigene Scheduler/eigenes Grafana).

**Wichtigste Architektur-Entscheidung**: die CO2-Map wird **kein** Prefect-Flow/Crawler — sie läuft als
**dauerhafter Service** in einem **eigenen Container**, analog zum `streamlit-app`-Service, der schon produktiv im
OEDS-Repo existiert (eigener Branch `streamlit-app`, Vorbild für unseren eigenen Dockerfile-/`compose.yml`-Aufbau).

## Was schon erledigt ist (im `CO2_Intensity`-Repo, Branch `dbclient-timescaledb`)

- `DBClient` (Datenzugriffsschicht) komplett von InfluxDB/InfluxQL auf SQLAlchemy/TimescaleDB/SQL portiert,
  gleiche Methodennamen/-signaturen, lokal verifiziert (13/13 + 11/11 Checks).
- Alle 3 Grafana-Dashboards als SQL-Version umgeschrieben (`docker_configs/dashboard-definitions/*_timescaledb.json`),
  lokal gegen echtes Grafana verifiziert (24/24 Panel-Queries), dabei mehrere vorbestehende Bugs im InfluxDB-
  Original gefixt.
- Beides liegt im `co2map/`-Unterordner dieses Repos (kopiert von `dbclient-timescaledb`).

## Server-Zugang (Kurzfassung — Details/Zugangsdaten in der Mail vom Kollegen, nicht hier)

- SSH: `nick@132.230.100.67`, nur im Instituts-VPN erreichbar.
- Staging-Bereich: `/srv/staging/open-energy-data-server` (gemeinsam genutzt, Eigentümer `root`/`staging` —
  **keine Branches wechseln oder Dateien dort eigenmächtig ändern**).
- DB von außen erreichbar: Host `132.230.100.67`, Port `7432`, DB/User `opendata`.
- **Bekanntes, gemeldetes Problem (Stand zuletzt)**: Verbindung zur DB funktioniert (Login klappt), aber jede
  Abfrage schlägt server-seitig fehl (`FATAL: could not open file "global/pg_filenode.map": Permission denied`)
  — sieht nach einem Dateisystem-Berechtigungsproblem auf dem Server aus, an den Kollegen gemeldet, **Antwort
  stand zuletzt noch aus**. Vor weiteren DB-Zugriffsversuchen prüfen, ob das inzwischen behoben ist.
- Keine Docker-Gruppen-Mitgliedschaft für `nick` auf dem Server (`docker ps` → `permission denied`, kein Sudo) —
  ebenfalls beim Kollegen angefragt, Status prüfen.

## Aktueller Plan — nächste Schritte (Reihenfolge, Stand der Übergabe)

1. ~~GitHub-Branch von `main` anlegen, lokal auschecken~~ ✅ erledigt (dieser Fork/Branch)
2. Echtes Schema von `entsoe_raw`/`entsoe` verifizieren (pgAdmin oder SQL, nicht Metabase-Anzeigenamen) —
   **blockiert durch das oben genannte Server-Problem**
3. Lokal testweise `query_per_type_gen`/`query_demand_data`/`query_cross_border_flows` im `DBClient`
   (`co2map/cosema/input_output/influxdb.py`) auf Lesezugriff gegen die echten Server-Tabellen umstellen,
   Formate/Kompatibilität prüfen
4. Unklaren Punkt aus dem ursprünglichen Meeting-Mitschrieb konkretisieren ("prüfen, ob nach Verbindungsaufbau
   alles korrekt mitläuft")
5. Fehlende Daten (v.a. MaStR-Kraftwerksdatenbank, ~13 GB) beschaffen und auf den Staging-Bereich hochladen —
   Kollege will diese langfristig in der DB (eigenes Postgres-Schema, keine Hypertable, Vorschlag: über
   `pandas.read_sql`/`to_sql` ähnlich `DBClient.write_df`), noch nicht abgestimmt
6. `.env`-Datei anlegen (Muster: `os.getenv(...)` + `python-dotenv`, wie vom Kollegen vorgeschlagen)
7. Docker-Image bauen — Vorlage: `streamlit-app`-Branch (`Dockerfile`: `python:3.11-slim`, `apt-get` Build-Deps,
   `pip install -r requirements.txt`, `COPY . /app`; `compose.yml`-Service-Block: `build: context: ./co2map`,
   `depends_on: open-data-17`, kein eigenes Netzwerk nötig) — für uns zusätzlich: Gurobi-Installation +
   Lizenz (Linux/floating, nicht die alte Windows-WSL-Form)
8. Docker-Gruppen-Mitgliedschaft-Antwort abwarten, um Schritt 7 auf dem Server zu testen
9. *(Niedrige Priorität)* kleiner separater Prefect-Flow fürs periodische Hochladen von Daten (MaStR/Wetter) —
   kein Widerspruch zu "CO2-Map nutzt kein Prefect", eigenständige Nebenaufgabe
10. Grafana-Dashboards einspeisen (`data/provisioning/grafana/dashboards/` — auf `develop` aktuell nicht aktiv,
    vorher klären ob/wie aktiviert)
11. End-to-End-Test, Vergleich mit dem bisherigen InfluxDB-Stand

## Offene Fragen an den Server-Kollegen (Stand der Übergabe)

- Server-DB-Fehler (siehe oben) — gerade gemeldet, Antwort ausstehend
- Docker-Gruppen-Mitgliedschaft für `nick` — angefragt, Antwort ausstehend
- `DB_HOST`-Wert für Verbindungen *innerhalb* des Docker-Netzwerks bestätigen (vermutlich `open-data-17`, der
  Service-Name — **nicht** derselbe Wert wie der externe `DB_PORT=7432`)
- `develop` vs. `main`: Staging-Checkout steht auf `develop`, nicht `main` wie ursprünglich gesagt — Absicht?
- Deploy-Prozess für einen Dauerhaft-Service (vermutlich `git pull` + `docker compose restart`, wie beim
  `streamlit-app`-Vorbild, aber nicht 100 % bestätigt)
- Ist Grafana auf `develop` bewusst deaktiviert oder nur noch nicht gemerged?
- Server-Datenhaltung generell (was bleibt dauerhaft in der DB, was wird pro Lauf neu gezogen) — mit Mirko und
  Niklas zu klären
- Gap-Filling-Methodik auf dem Server (Ansprechpartner vermutlich Tiernan) — alte Recherche dazu basierte auf
  dem inzwischen als veraltet bestätigten `entsoe`-Branch, muss neu verifiziert werden
- Aktuelles Crawler-Repo (Name/Ort) — niedrige Priorität, nur relevant für den optionalen Sync-Flow (Punkt 9)

## Wichtige Prinzipien aus der bisherigen Arbeit

- **Nicht eigenmächtig im gemeinsamen Staging-Bereich auf dem Server herumändern** (Branch wechseln, Dateien
  löschen) — andere nutzen denselben Checkout.
- **Keine Secrets/Passwörter in Dateien, die committed werden** — `.env` bleibt lokal/serverseitig, nicht im Git.
- Bei Unsicherheit über Server-Infrastruktur (Docker-Netzwerke, Ports, Deploy-Prozesse) zuerst versuchen, die
  Antwort aus bereits vorhandenem Code auf dem Server abzuleiten (wie beim `streamlit-app`-Fund), bevor man den
  Kollegen fragt — spart Rückfragen-Runden.
