# OEDS-Integration — Aktueller Plan (Stand 2026-08-20)

Für die Entstehungsgeschichte, verworfene Ansätze und überholte Recherche-Ergebnisse siehe
[`oeds_integration_historie.md`](oeds_integration_historie.md). Für die technischen Rohdaten aus dem ersten
Server-Login (compose.yml-Analyse, streamlit-app-Vorlage etc.) siehe
[`server_zugang_recherche.md`](server_zugang_recherche.md) — diese Datei hier enthält nur den aktuellen,
verdichteten Plan.

## Nächste konkrete Schritte

**Grundsatzentscheidung (2026-08-20, mit Nick abgestimmt)**: Priorität liegt jetzt darauf, zuerst die **echten
Daten** zu verifizieren, bevor Zeit in den Container-Bau fließt. Konkret: prüfen, ob die schon auf dem Server
vorhandenen ENTSO-E-Rohdaten (`entsoe_raw`/`entsoe`-Schema) zu dem passen, was unsere Pipeline erwartet — dafür
unser lokales Repo testweise umstellen, sodass es diese Server-Daten liest statt der eigenen, manuell gezogenen
ENTSO-E-Daten. Das war ohnehin als "Schritt 4b" vorgemerkt, wird jetzt vorgezogen.

**Strukturelle Erkenntnis**: der `streamlit-app`-Service im OEDS-Repo liegt als **Unterordner direkt im
`open-energy-data-server`-Repo** (`build: context: ./streamlit-app`), nicht in einem komplett separaten Repo.
Das erklärt vermutlich, was der Kollege von Anfang an mit "von `main` abzweigen" meinte: einen eigenen Branch im
`open-energy-data-server`-Repo anlegen und die CO2-Map als Unterordner dort reinbringen — analog zum
`streamlit-app`-Muster.

**1. GitHub-Branch von `main` anlegen (im Fork), lokal auschecken**
Vorbereitung dafür, dass die CO2-Map später als Unterordner ins `open-energy-data-server`-Repo kann. Passiert im
eigenen GitHub-Fork, nicht direkt im gemeinsam genutzten Staging-Checkout auf dem Server.

**2. Echtes Schema von `entsoe_raw`/`entsoe` verifizieren**
Über pgAdmin oder direkte SQL-Abfrage (nicht die Metabase-Anzeigenamen 1:1 übernehmen, die "verschönert"
Metabase nur für die Darstellung).

**3. Lokal testweise auf Lesezugriff umstellen**
`query_per_type_gen`/`query_demand_data`/`query_cross_border_flows` in unserem `DBClient` probeweise gegen die
echten Server-Tabellen laufen lassen (statt der eigenen Tabellen) — prüfen, ob Formate/Spalten kompatibel sind,
und ob die Gap-Filling-Methodik von OEDS zu unseren Annahmen passt (siehe Frage 8 unten).

**4. Prüfen, ob nach Verbindungsaufbau alles korrekt mitläuft**
Unklarer Punkt aus dem ursprünglichen Meeting-Mitschrieb — beim nächsten Austausch konkretisieren, was genau
gemeint war.

**5. Fehlende Daten beschaffen und auf den Staging-Bereich hochladen**
Vor allem die MaStR-Kraftwerksdatenbank (~13 GB). Kollege will diese langfristig **in der Datenbank** haben,
nicht als Datei — Richtung ist klar, unser Umsetzungsvorschlag (eigenes Postgres-Schema, keine Hypertable, via
`pandas.read_sql`/`to_sql` ähnlich `DBClient.write_df`) noch nicht abgestimmt (Frage 5 unten). Technischer
Uploadweg jetzt klar: eigener SSH-Zugang zum Staging-Bereich vorhanden.

**6. `.env`-Datei anlegen**
Format ist abgestimmt, nicht ins Git pushen. Können wir jetzt selbst im Staging-Bereich anlegen.

**7. *(parallel möglich)* Docker-Image für die CO2-Map bauen**
Konkrete Vorlage vorhanden: der `streamlit-app`-Service (Details in `server_zugang_recherche.md`) — Base-Image
`python:3.11-slim`, Build aus einem Unterordner im eigenen Repo, kein eigenes Netzwerk nötig (`depends_on`
reicht). Daran orientieren, für unseren eigenen Container anpassen (inkl. Gurobi-Installation).

**8. Docker-Gruppen-Mitgliedschaft beim Kollegen anfragen**
Blockiert nur das *Testen* von Schritt 7 auf dem Server (`docker ps` etc. schlägt aktuell mit `permission
denied` fehl, kein Sudo vorhanden) — kein Blocker für Schritte 1–6. Kurze Nachricht:
`sudo usermod -aG docker nick`, keine vollen Sudo-Rechte nötig.

**9. *(Niedrige Priorität, für später)* Kleiner Prefect-Flow fürs Daten-Hochladen**
Ein Skript in einem eigenen (Git-)Repo, als Prefect-Flow, das Daten (z.B. MaStR/Wetter) periodisch in die
Server-DB schreibt/aktualisiert — analog zum bestehenden ENTSO-E-Crawler-Muster (`config.example.yml`-Format
dafür schon verifiziert). Kein Widerspruch zu "CO2-Map nutzt kein Prefect" — eigenständige Nebenaufgabe.
Erstmal zurückgestellt.

**10. Grafana-Dashboards einspeisen**
Technisch fertig — unsere drei `*_timescaledb.json`-Dashboards sind lokal verifiziert, Ziel-Ordnerstruktur jetzt
bekannt (`data/provisioning/grafana/dashboards/`). Nur: Grafana ist auf dem aktuellen `develop`-Branch (noch)
nicht aktiv — vorher klären, ob/wie es aktiviert wird (Frage 4b unten).

**11. End-to-End-Test**
Sobald Container, Secrets und Daten stehen: Pipeline für ein bekanntes Zeitfenster laufen lassen, mit dem
bisherigen InfluxDB-Stand vergleichen.

## Offene Fragen — an den Server-Kollegen

1. ✅ **Server-Zugangsdaten** — erledigt, SSH-Zugang funktioniert, Staging-Bereich erkundet (siehe
   `server_zugang_recherche.md`).
2. ✅ **Dockerfile-Details** — größtenteils beantwortet durch den `streamlit-app`-Branch als Vorbild (Base-Image,
   Netzwerk-Muster). Nur noch zu bestätigen: `DB_HOST`-Wert (steht nicht in der `.env`, vermutlich `open-data-17`).
3. **Deploy-Prozess für den Dauerhaft-Service**: das `streamlit-app`-Vorbild mountet den Code zusätzlich als
   Volume (nicht nur beim Image-Build kopiert) — deutet auf `git pull` + `docker compose restart` statt vollem
   Rebuild bei jeder Änderung. Beim Kollegen bestätigen, ob das die übliche Praxis ist.
4. **Secrets-Format**: `.env` ist abgestimmt. Übertragungsweg ist kein offenes Problem mehr (eigener
   SSH-Zugriff auf den Staging-Bereich vorhanden) — Frage entfällt.
   **4b. (Neu)** Ist Grafana auf `develop` bewusst deaktiviert, oder nur noch nicht gemerged? (Auf dem
   `streamlit-app`-Branch existieren die Provisioning-Dateien.)
5. **Große Dateien — Umsetzungsdetails**: Richtung ist klar (auch MaStR soll in die DB), unser Schema-Vorschlag
   (Schritt 5 oben) noch nicht abgestimmt.
6. ✅ **Port-Konflikte/Netzwerk** — beantwortet: alle Ports laufen über `.env`-Variablen, kein hartkodierter
   Konflikt zu erwarten, wir ergänzen einfach eine eigene Variable nach demselben Muster.
7. **Server-Datenhaltung generell**: welche Daten bleiben dauerhaft in der DB, welche werden pro Lauf neu
   gezogen, welche verworfen — passen die ENTSO-E-Inputs überhaupt drauf, sind Kraftwerksblock-Daten (per-unit)
   dort schon vorgesehen? (mit Mirko und Niklas klären)
8. **Gap-Filling auf dem Server**: wie wird das aktuell gemacht (Tiernan?) — unsere bisherige Recherche dazu
   basierte auf dem inzwischen als veraltet bestätigten `entsoe`-Branch, muss neu verifiziert werden. (mit Mirko
   und Niklas klären)
9. **Aktuelles Crawler-Repo** (Name/Ort) als Strukturvorlage — niedrige Priorität, nur relevant für den
   optionalen Sync-Flow (Schritt 6 oben).
10. **(Neu) `develop` vs. `main`**: Staging-Checkout steht auf `develop`, nicht `main` wie ursprünglich gesagt —
    Absicht oder sollen wir zu `main` wechseln?
11. **(Neu) Docker-Gruppen-Mitgliedschaft** für `nick` fehlt — siehe Schritt 1 oben.

## Hintergrund (Nebensächlich — nur zur Einordnung)

**Architektur**: CO2-Map wird eigener, dauerhaft laufender Service (eigener Container, kein Prefect-Flow) —
Details siehe Historie. DB: Postgres/TimescaleDB statt InfluxDB. Gurobi läuft isoliert im eigenen Container.
Branch: `main` grundsätzlich bestätigt (aber siehe Frage 10 — Staging steht aktuell auf `develop`).

**Umsetzungsstand unsererseits**:
- ✅ `DBClient` komplett auf SQLAlchemy/TimescaleDB portiert, lokal verifiziert (Branch `dbclient-timescaledb`,
  Commit `0165922`); `modularisierung-merged` läuft unverändert mit InfluxDB weiter.
- ✅ Alle 3 Grafana-Dashboards als SQL-Version umgeschrieben und lokal verifiziert (Commit `949c4c0`).
- ✅ Größen/Formate der großen Inputs ermittelt (Tabelle unten).
- ✅ Server-Zugang hergestellt, Staging-Bereich erkundet, Dockerfile-Vorlage gefunden.
- ⏳ Noch nicht begonnen: eigenes Dockerfile, `compose.yml`-Eintrag, MaStR-Migration, lesender OEDS-Zugriff für
  die 3 Ingestion-Methoden (separater späterer Task), Merge von `dbclient-timescaledb` (bewusst ganz am Ende).

**Große Dateien** (~13,4 GB gesamt, dominiert von MaStR):

| Was | Pfad | Größe | Format | Zeitreihe? |
|---|---|---|---|---|
| MaStR-Kraftwerksdatenbank | `~/.open-MaStR` (außerhalb des Repos) | ~13 GB | SQLite (`.db`) | Nein — Register/Stammdaten |
| Shapefiles | `inputs/shapefiles/` | 118 MB | ESRI Shapefile + GeoJSON | Nein — statisch |
| Netz-Topologie | `inputs/networks/` | 66 MB | NetCDF (`.nc`) | Nein — statisch |
| Wetter-Cutouts | `inputs/cutouts/` | 90 MB | NetCDF (`.nc`) | **Ja** — stündlich pro Gitterzelle |
| Kapazitäts-Parquets | `inputs/capacities/` | 45 MB | Parquet | Grobe monatliche Schnappschüsse |
| Demand-Regionalisierungsfaktoren | `inputs/demand_reg_data/` | 22 MB | CSV | Grobe jährliche Schnappschüsse |
| Technologie-Zuordnungstabellen | `inputs/generation_data/` | 49 KB | CSV | Nein — statisch |

**Intern, keine Kollegen-Frage**:
- Eigener Branch-Stand: `modularisierung-merged` jetzt deployen, oder erst nach Merge in `main`? Wie einfach
  lässt sich das im Nachhinein ändern?
- Gurobi-Lizenzform: richtige (Linux/floating statt der alten Windows-WSL-Lizenz) besorgen, sobald Dockerfile
  ansteht.
- TimescaleDB-Erweiterung auf dem Server: unklar, ob/wie stark tatsächlich genutzt — laut Kollege "nicht
  dramatisch", falls nicht. Niedrige Priorität, nicht blockierend.
