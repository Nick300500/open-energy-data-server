# Server-Zugang & Staging-Recherche (Stand 2026-08-20)

Konkrete technische Erkenntnisse aus dem ersten echten Login auf dem OEDS-Server. Ergänzt/beantwortet mehrere
Fragen aus [`oeds_integration_plan.md`](oeds_integration_plan.md) — dort bei Gelegenheit als "beantwortet"
nachpflegen. **Keine Secrets/Passwörter in dieser Datei** — die stehen in der Kollegen-Mail bzw. der `.env` auf
dem Server selbst, nicht hier.

## Zugang

- **SSH**: `ssh nick@132.230.100.67` — nur im Instituts-VPN erreichbar.
- Passwort nach erstem Login geändert (Pflicht, war im Klartext in der Übergabe-Mail).
- **Keine Sudo-Rechte** (`nick is not in the sudoers file`), **kein Zugriff auf den Docker-Socket**
  (`permission denied` bei `docker ps`) — Nutzer `nick` ist nicht in der `docker`-Gruppe.
  → **Offener Punkt für den Kollegen**: `sudo usermod -aG docker nick` (reicht, keine vollen Sudo-Rechte nötig).

## Server-Umgebung

- Docker 29.1.3, Docker Compose 2.40.3 — beide aktuell, vorhanden.
- Python 3.12.3 (system-weit).
- Speicherplatz: 194 GB gesamt, 87 GB frei (53 % belegt) — reicht für unsere ~13,4 GB Inputs.

## Staging-Verzeichnis

`~/staging` → symlink auf `/srv/staging` (Eigentümer `root`, Gruppe `staging`, gemeinsam genutzt — **nicht
eigenmächtig Branches wechseln oder Dateien verändern**, andere könnten denselben Checkout nutzen).

Darin: `/srv/staging/open-energy-data-server` — ein vollständiger Git-Checkout des OEDS-Repos.

**Aktuell ausgecheckter Branch: `develop`** — nicht `main`, wie ursprünglich vom Kollegen gesagt.
→ **Offener Punkt**: klären, ob das Absicht ist (z.B. `develop` = aktueller Arbeitsstand, `main` nur Releases)
oder ob wir für unsere eigene Arbeit zu `main` wechseln sollten.

Verfügbare Remote-Branches: `main`, `develop`, `entsoe`, `entsoe-merge`, `metabase`, `prefect`, `streamlit-app`,
`test`, `test-prefect`.

## `compose.yml` (auf `develop`) — Architektur-Überblick

| Service | Zweck | Netzwerk-Erreichbarkeit |
|---|---|---|
| `open-data-17` | TimescaleDB (Postgres 17), Haupt-Datenbank, User/DB `opendata` | Service-Name `open-data-17:5432` intern; extern über `${DB_PORT}` |
| `pgadmin` | Web-UI für Postgres | `${PGADMIN_PORT}` |
| `open-postgrest` | REST-API auto-generiert aus dem Schema, nur lesend (`readonly`-Rolle) | `${POSTGREST_PORT}` |
| `postgres` (14) | eigene, separate DB nur für Prefects Metadaten | intern |
| `redis` | Prefect-Messaging | intern |
| `prefect-server` / `prefect-services` | Prefect-API/-UI | `${PREFECT_PORT}` |
| `prefect-worker` | führt Crawler-Flows aus (Pool `local-pool`), bekommt `ENTSOE_API_KEY` + DB-Zugangsdaten als Env-Vars | — |
| `metabase` + `postgres-metabase` | DB-Browsing-Tool, eigene Backend-DB, öffentlich über Traefik (`proxy`-Netzwerk, Let's-Encrypt) | `${METABASE_PORT}` + `proxy`-Netzwerk |

**Zwei Netzwerke**: implizites `default` (alle Services erreichen sich intern per Service-Name) + externes,
geteiltes `proxy`-Netzwerk (nur für Services, die öffentlich per HTTPS über Traefik erreichbar sein sollen, siehe
Metabase-Labels).

**Alle Ports sind `.env`-Variablen** (`DB_PORT`, `PGADMIN_PORT`, `POSTGREST_PORT`, `PREFECT_PORT`,
`METABASE_PORT`) — kein hartkodierter Port, den wir versehentlich doppelt belegen könnten.

**Kein Grafana-Service auf `develop`** — widerspricht unserer bisherigen Annahme (siehe unten, `streamlit-app`-
Branch).

## `config.example.yml` — Crawler-Config-Muster, weiterhin aktuell

```yaml
db_uri: "postgresql://opendata:opendata@localhost:6432/opendata?options=--search_path={DBNAME}"
entsoe_api_key: "YOUR_ENTSOE_API_KEY"
gie_api_key: "YOUR_GIE_API_KEY"
ipnt_client_id: "YOUR_IPNT_CLIENT_ID"
ipnt_client_secret: "YOUR_IPNT_CLIENT_SECRET"
jao_api_key: "YOUR_JAO_API_KEY"
```

Bestätigt: das `CrawlerConfig`-Muster aus der alten `entsoe`-Branch-Recherche ist strukturell weiterhin aktuell
(nur der *Ort* der Crawler-Repos hat sich geändert, nicht das Config-Format) — relevant nur, falls wir uns später
für den optionalen kleinen Daten-Sync-Flow entscheiden (siehe `oeds_integration_plan.md`).

## `streamlit-app`-Branch — Vorlage für einen dauerhaften Service

Genau das gesuchte Beispiel: eine App (Streamlit-Dashboard, INATECH-Kollege Tiernan Buckley), die wie die
CO2-Map als **dauerhafter Service** läuft, kein Crawler. Enthält `data/provisioning/grafana/dashboards/*.json`
(u.a. `entsoe.json`, `smard.json`, `weather.json`) — Grafana existiert also grundsätzlich im Baukasten, ist auf
`develop` aber offenbar (noch) nicht aktiviert.

**`streamlit-app/Dockerfile`**:
```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc g++ libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY . /app

EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
```

**Zugehöriger `compose.yml`-Service-Block**:
```yaml
streamlit-app:
    build:
      context: ./streamlit-app
      dockerfile: Dockerfile
    container_name: oeds-streamlit
    restart: unless-stopped
    depends_on:
      - open-data-17
    volumes:
      - ./streamlit-app:/app
    environment:
      DB_HOST: ${DB_HOST}
      DB_PORT: ${DB_PORT}
      POSTGRES_DB: ${DB_NAME}
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      TOPOLOGY_CONFIG_PATH: /app/config/topology.yaml
      LOG_LEVEL: INFO
    ports:
      - "${STREAMLIT_PORT:-8501}:8501"
```

**Wichtige Learnings daraus**:
- **Kein eigenes Netzwerk nötig** — `depends_on: open-data-17` reicht, Docker Compose steckt beide automatisch
  ins selbe Standard-Netzwerk, Erreichbarkeit über den Service-Namen als Hostname.
- **Build aus Unterordner im selben Repo** (`build: context: ./streamlit-app`) — kein separates Image-Repository
  nötig, passt zu unserem Fall (`CO2_Intensity`-Repo bekommt einen eigenen Unterordner mit Dockerfile).
- **Code zusätzlich als Volume gemountet** (`./streamlit-app:/app`), nicht nur beim Image-Build reinkopiert —
  deutet auf einen Deploy-Prozess über `git pull` + `docker compose restart` statt vollem Rebuild bei jeder
  Code-Änderung (beantwortet Frage 3 aus `oeds_integration_plan.md` vermutlich, aber nicht 100% sicher —
  im Zweifel den Kollegen fragen, ob das die übliche Praxis ist).
- **Port-Fallback-Syntax**: `"${STREAMLIT_PORT:-8501}:8501"` — Variable mit Default-Wert, falls in `.env` nicht
  gesetzt.
- **`DB_HOST` fehlt aktuell in der echten `.env`** (`grep DB_HOST .env` → kein Treffer) — vermutlich einfach
  `open-data-17` (der Service-Name). Für unseren eigenen Service-Block müssten wir diese Variable selbst
  ergänzen (oder den Wert direkt hart eintragen, ohne Variable). **Achtung, Stolperstein**: das ist ein anderer
  Wert als der `DB_PORT` aus der externen `.env` (der ist für Verbindungen von außerhalb des Docker-Netzwerks,
  z.B. vom eigenen Laptop — von innerhalb des Netzwerks braucht man den internen Port 5432 am Service-Namen).

## Offene Punkte aus dieser Recherche

1. Docker-Gruppen-Mitgliedschaft für `nick` fehlt (Kollege muss das setzen)
2. `develop` vs. `main` als Ausgangspunkt klären
3. `DB_HOST`-Wert bestätigen (vermutlich `open-data-17`)
4. Ob Grafana auf `develop` bewusst deaktiviert ist oder nur noch nicht gemerged wurde
5. Ob unser Deploy-Prozess (Schritt 3 in `oeds_integration_plan.md`) wirklich `git pull` + `restart` ist, wie
   beim `streamlit-app`-Vorbild, oder ob ein Rebuild erwartet wird
