# CO2-Map-Integration in den Open-Energy-Data-Server — Stand 2026-09-23

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
  Wetter-Cutouts (ERA5 über Copernicus/CDS).
- **`forecast_calculations`** (alle 12h): schreibt nur die Wind-/Solar-**Prognose** (`vre_forecast`) für den
  stündlichen Lauf — berechnet **keine** CO2-Intensitäts-Prognose, der entsprechende Aufruf ist im Code
  auskommentiert (Stand unklar, ob das schon immer so war — noch nicht untersucht).

**Datenquellen**: `entsoe_raw`/`entsoe` (OEDS's eigener ENTSO-E-Crawler, nicht von uns geschrieben) +
`cosema_inputs` (MaStR, Shapefiles, Kapazitäten, Demand-Regionalisierungsfaktoren, Gen-Type-Mapping — einmalig
über die eigenständigen, **nicht in diesem Repo liegenden** "Transfer data to database"-Skripte hochgeladen).
Wetter-Cutouts bleiben bewusst als Dateien (Bind-Mount), nicht in der DB.

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

## Bekannte offene Punkte

Details und Priorisierung siehe [`plan.md`](plan.md). Kurz:

1. ENTSO-E-Crawler-Verzögerung/-Lücken in Production (extern, gemeldet).
2. Periodisches Nachladen der statischen Referenzdaten (MaStR/Kapazitäten/Demand-Faktoren) — bisher nur
   einmaliger Snapshot, wird als eigener Prefect-Flow separat angegangen.
3. Wetterdaten-API (Copernicus/CDS) war beim letzten Lauf nah an einem eigenen Absturz durch Ratenlimits —
   noch nicht abgesichert.
4. Grafana-Dashboards noch nicht final geprüft/poliert; eigenes Web-Frontend für die Karte — unklar, ob überhaupt
   gewollt.
5. Merge des `co2map-integration`-Branches in `main`/`develop` — bewusst der allerletzte Schritt, noch nicht
   angegangen.

## Wichtige Prinzipien aus der bisherigen Arbeit

- **Nicht eigenmächtig im gemeinsamen Staging-Bereich auf dem Server herumändern** (Branch wechseln, Dateien
  löschen) — andere nutzen denselben Checkout.
- **Keine Secrets/Passwörter in Dateien, die committed werden** — `.env` bleibt lokal/serverseitig, nicht im Git.
- **Upload-/Migrations-Tooling für Rohdaten lebt bewusst außerhalb dieses Repos** (eigener Ordner
  "Transfer data to database") — dieses Repo enthält nur die Lese-Seite.
- Vor Codeänderungen an einer echten Fehlerursache: erst gegen echte Daten verifizieren statt defensiv zu
  patchen — mehrfach bewährt (siehe `historie.md`, u.a. der `NoDataAvailableError`- und der Per-Unit-Fix).
