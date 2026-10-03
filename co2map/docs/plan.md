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

**Ursache eingegrenzt (2026-09-23)**: Der Crawler holt pro Lauf immer exakt den **kompletten Vortag**
(00:00–23:45), nie den laufenden Tag — geprüft über `download_timestamp` vs. das jeweils geschriebene
Zeitfenster in `entsoe_raw`. Die Verzögerung liegt also strukturell im Crawler-Design ("hole gestern,
fertig"), nicht an einer ENTSO-E-Veröffentlichungsverzögerung. Mehrtägige Komplettausfälle (z.B. 16.–19.09.)
waren laut Rückmeldung durch einen Serverausfall bedingt.

**Verifiziert (2026-09-23)**: Für den letzten vollständig gecrawlten Kalendertag (statt "jetzt minus 24h")
läuft die Pipeline lückenlos durch — sowohl der stündliche Modus (`only_per_type`, 24/24h, plausibler
Tagesverlauf 241–658 g/kWh) als auch der tägliche Modus (`with_per_unit`, ebenfalls 24/24h, 231–563 g/kWh) —
letzterer manuell mit `TEST_MODE=with_per_unit` in `test_pipeline_real_data.py` getestet, ohne neue Downloads,
gegen bereits vorhandene `per_unit_gen`/`vre_gen`-Daten. Bestätigt: die Kernlogik ist in beiden Modi korrekt,
es fehlt nur die Ausrichtung des Live-Fensters auf die tatsächliche Crawler-Realität.

## 2. Periodisches Nachladen der statischen Referenzdaten

MaStR, Kapazitäten und Demand-Regionalisierungsfaktoren liegen bisher nur als **einmaliger Snapshot** in
`cosema_inputs` (hochgeladen über die eigenständigen "Transfer data to database"-Skripte, nicht Teil dieses
Repos). Kapazitäten sind bereits sichtbar veraltet (`Using latest available: 2026_02` bei jedem Lauf).

Geplanter Ansatz: kleiner, eigenständiger Prefect-Flow (analog zum bestehenden ENTSO-E-Crawler-Muster), der
diese Daten periodisch aktualisiert — kein Widerspruch zu "CO2-Map nutzt kein Prefect", eigenständige
Nebenaufgabe. **Wird separat bearbeitet, nicht in dieser Session.** Priorität beim Wiedereinstieg: Kapazitäten
zuerst (kleinste Datei, kein API-Key nötig, größter sichtbarer Effekt).

**Neue Demand-Regionalisierungsfaktoren getestet (2026-09-23)**: die Ausgabedateien aus dem separaten
`co2map_reg_facts`-Projekt (2025er und 2026er Jahresdatei) sind funktional kompatibel mit der Map — gegen
`reg_demand_data_dynamic` verifiziert, 2026 sogar mit echtem Produktionsverbrauch. Vor dem Upload noch
vereinheitlichen: die 2026er-Datei ist prozentskaliert (Summe 100) statt Anteil (Summe 1,0), und die
Zeitspalte heißt uneinheitlich `datetime` bzw. `timestamp`.

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

## 6. Weitere Tests, noch nicht angegangen (Stand 2026-09-23)

Bisher wurde vor allem geprüft, dass Läufe *durchlaufen* und grob plausibel aussehen, nicht die Plausibilität
jeder einzelnen Datenquelle im Detail:

- **Wind-/Solar-Werte** (`vre_gen`/`vre_forecast`) nie einzeln auf Plausibilität geprüft (Solar nachts ~0,
  regionale Verteilung passend zu bekannten Wind-/Solarstandorten).
- **Cross-Border-Flows** fließen ins SIGI-Balancing ein, wurden aber nie einzeln auf plausible Werte geprüft
  — nur, dass die Rechnung damit nicht abstürzt.
- **Forecast-Job** (`forecast_calculations.py`, alle 12h): ob `run_vre_calculations(mode="forecast")` selbst
  sinnvolle `vre_forecast`-Werte liefert, nie manuell durchgetestet (unabhängig von Punkt 4 oben).
- **`per_unit`-Aktualität**: `cosema.per_unit_gen` steht aktuell bei 2026-09-14, also schon ~9 Tage hinter
  "heute" (23.09.) — der Tageslauf holt nur ~1 Tag pro erfolgreichem Durchlauf auf. Beobachten, ob das von
  selbst aufholt.
- **Solar/VRE-Warnung aufgeklärt und behoben (2026-10-03)**: `Total regionalized generation for Solar is not
  equal...` kam daher, dass der tägliche Lauf seit 25.09. durchgehend abgestürzt ist (zwei verschiedene,
  aufeinanderfolgende Bugs — Details in `historie.md`). Fix deployed (`query_reg_per_type_data` reindext jetzt
  vollständig). **Noch offen**: die Datenlücke in `reg_generation`/`vre_gen`/`co2_intensity` (`with_per_unit`)
  zwischen ca. 25.09. und dem Deploy ist nicht automatisch nachgeholt worden — ggf. manuell nachrechnen, falls
  die Lücke stört.

## 7. Merge in `main`/`develop`

Der komplette Stand läuft bisher nur auf dem gemeinsam genutzten Staging-Server, auf dem Branch
`co2map-integration` — nie offiziell gemerged. War von Anfang an bewusst als allerletzter Schritt vorgesehen,
nachdem alles andere stabil läuft.
