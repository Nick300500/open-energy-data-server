# OEDS-Integration — Offene Punkte (Stand 2026-09-23)

Der ursprüngliche 11-Schritte-Plan (Branch anlegen, Schema verifizieren, Docker-Image bauen, Deploy, ...) ist
**komplett abgearbeitet** — Details dazu in [`historie.md`](historie.md). Diese Datei enthält nur noch, was
wirklich noch offen ist.

## 1. ENTSO-E-Crawler in Production: Lücken und Verzögerung

Gemeldet (2026-09-01), Antwort noch offen. Zwei getrennte Befunde:
- Mehrere komplette Tage ohne jeden Crawler-Lauf (z.B. 05.–07.09., 15.–18.09.) — betrifft alle Zonen gleichzeitig,
  deutet auf ausgefallene Läufe hin, nicht auf einzelne fehlende Zonen.
- Aktuellste Daten hinken 1–2 Tage hinterher — betrifft nur den stündlichen Live-Lauf (24h-Fenster), nicht den
  täglichen (7-Tage-Fenster, endet ohnehin 7 Tage in der Vergangenheit).

**Bei uns zu entscheiden, sobald Antwort da ist**: Live-Fenster versetzen, oder Regionalisierungs-Schritt bei
fehlenden Daten ebenfalls sauber überspringen (aktuell schreibt er noch Nullzeilen, bevor der
Intensitäts-Schritt weiter unten sauber abbricht).

## 2. Periodisches Nachladen der statischen Referenzdaten

MaStR, Kapazitäten und Demand-Regionalisierungsfaktoren liegen bisher nur als **einmaliger Snapshot** in
`cosema_inputs` (hochgeladen über die eigenständigen "Transfer data to database"-Skripte, nicht Teil dieses
Repos). Kapazitäten sind bereits sichtbar veraltet (`Using latest available: 2026_02` bei jedem Lauf).

Geplanter Ansatz: kleiner, eigenständiger Prefect-Flow (analog zum bestehenden ENTSO-E-Crawler-Muster), der
diese Daten periodisch aktualisiert — kein Widerspruch zu "CO2-Map nutzt kein Prefect", eigenständige
Nebenaufgabe. **Wird separat bearbeitet, nicht in dieser Session.** Priorität beim Wiedereinstieg: Kapazitäten
zuerst (kleinste Datei, kein API-Key nötig, größter sichtbarer Effekt).

## 3. Wetterdaten-API (Copernicus/CDS): Beinahe-Absturz durch Ratenlimit

Beim täglichen Lauf am 23.09. hat die Wetter-Cutout-Erstellung (`run_vre_historical`) mehrfach ein Ratenlimit
getroffen und erst im **vorletzten** von 5 erlaubten Versuchen geklappt (`Vendor/atlite/datasets/meteo_hist.py`,
`@retry(tries=5, delay=5, backoff=2)`). Ein Fehlschlag mehr, und der komplette Tageslauf wäre abgestürzt — kein
eigener Code-Fehler, aber ein echtes Robustheitsrisiko. Noch nicht behoben. Optionen: mehr Versuche/höhere
Basiswartezeit, oder ein eigenständiger, nicht-fataler Fehlerpfad für einen einzelnen fehlgeschlagenen
Cutout-Download statt Absturz des ganzen Laufs.

## 4. Forecast-Intensitäten

`schedulers/forecast_calculations.py::perform_forecast()` ruft nur `run_vre_calculations(mode="forecast")` auf —
der Aufruf `forecast_intensities(...)` ist im Code auskommentiert. Der 12h-Lauf berechnet also aktuell **keine**
CO2-Intensitäts-Prognose, nur die Wind-/Solar-Erzeugungsprognose. Unklar (noch nicht untersucht, z.B. via
`git blame`), ob das schon immer so war oder ein übrig gebliebenes TODO ist.

## 5. Grafana

Technisch erreichbar (eigener Traefik-Entrypoint, siehe `historie.md`), aber noch nicht inhaltlich geprüft/
poliert (Dashboards wirklich sinnvoll? Daten korrekt dargestellt?). Separat offen: ob ein eigenes Web-Frontend
für die Karte überhaupt erwartet wird — dafür gibt es aktuell keinen Code in diesem Repo.

## 6. Merge in `main`/`develop`

Der komplette Stand läuft bisher nur auf dem gemeinsam genutzten Staging-Server, auf dem Branch
`co2map-integration` — nie offiziell gemerged. War von Anfang an bewusst als allerletzter Schritt vorgesehen,
nachdem alles andere stabil läuft.
