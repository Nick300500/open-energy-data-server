# OEDS-Integration — Offene Punkte (Stand 2026-10-19)

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

**Konkreter Effekt im Live-Betrieb (Server-Check 2026-10-19)**: `cosema.co2_intensity` (`only_per_type`) für den
18.10. hat alle Stunden 01:00–23:00, aber **00:00 fehlt**. Erklärung (aus dem Code abgeleitet, noch nicht für
mehrere Tage bestätigt): Der stündliche Lauf rechnet `[timestep − 24h, timestep]`
(`schedulers/initial_calculations.py`), die Stunde 00:00 des Vortags liegt also nur im Fenster des Laufs mit
Ende 00:00 — und der läuft, bevor der Crawler den Vortag liefert (offenbar ca. 01–02 Uhr UTC).
**Bestätigt (2026-10-23)**: 00:00 fehlt an jedem Tag 15.–22.10., am 17.10. sogar 00:00–03:00 (Crawler dort
später); im Log jeweils `Skipping intensity calculation for <Tag> 00:00 - <Folgetag> 00:00`. Wird **nicht**
nachgetragen — der Tageslauf schreibt `mode='with_per_unit'`, nicht `only_per_type` (15.10. hat auch nach 8 Tagen
nur 23h). **Vorschlag**: `TIME_DELTA` auf ~27h (oder mehr, für spätere Crawler-Läufe wie am 17.10.) vergrößern,
sodass der erste Lauf nach dem Crawler-Import den ganzen Vortag mitrechnet (Mehrfachschreiben ist dank
transaktionalem `write_df` unkritisch).

**Crawler-Zeitpunkt (2026-10-25)**: `entsoe_raw."Zonal_Generation_Raw".download_timestamp` (DE_LU) zeigt für
jeden Tag genau einen Wert, meist Folgetag ~15:10 UTC, für den jüngsten Tag aber ~01:05 UTC. Da die Live-
Intensitäten schon ab 01:00 vorliegen, kann der 15-Uhr-Lauf nicht der einzige sein — wahrscheinlichste
Erklärung (abgeleitet, nicht in Prefect bestätigt): **zwei Läufe täglich (~01:05 und ~15:10 UTC)**, beide holen
den Vortag, der zweite überschreibt den Download-Zeitstempel. Der für 00:00 zuständige stündliche Lauf startet
um 01:15 (Lauf um HH:15 rechnet bis HH−1:00) — also nur ~10 min nach dem Crawler. Am 17.10. lieferte der
Crawler offenbar erst ~04–05 Uhr, da hätten auch 27h nicht gereicht. **Robustere Alternative**: Fensterstart
fest auf 00:00 des Vortags statt fixer Stundenzahl. (Flow-Tabelle hat eigene Spalte `Download Time`.)

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

**Entscheidung (2026-10-19)**: Die `co2map_reg_facts`-Faktoren **ersetzen** die bisherigen (per Kalenderabgleich
fortgeschriebene 2018er-Reihe, `scripts/prepare_demand_data.py`) — kein Umschalten zwischen beiden, also keine
Codeänderung in der Map nötig. Sie liegen für mehrere Jahre vor und haben am Ende dieselbe Struktur wie die
aktuelle Tabelle `cosema_inputs.demand_reg_factors`; ausgetauscht wird nur der Inhalt über die Upload-Skripte.

## 3. Wetterdaten-API (Open-Meteo-Archiv, nicht Copernicus/CDS): Beinahe-Absturz durch Ratenlimit

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
- ~~**Cross-Border-Flows** nie einzeln geprüft~~ — **geprüft 2026-10-25**: `entsoe_raw."Cross_Border_Physical_
  Flows_Bidding_Zones_Raw"` für `DE_LU`, 20.–24.10.: alle 11 Nachbarzonen in beide Richtungen (22 Paare),
  stündlich lückenlos (109/109 Werte), Stand jeweils Vortag 23:00 (wie Erzeugung/Last). Maxima 200–4.100 MW,
  größte Werte an den großen Interkonnektoren (NL, DK_1, FR, PL, AT), keine negativen/Dauer-Null-Werte.
  Plausibel.
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

## 7. Scheduler: Zeitzähler läuft bei verpassten Läufen ggf. hinterher

Beobachtet 2026-10-19: Der Container-Prozess hing ca. 03:45–04:46 UTC (vermutlich im Zusammenhang mit dem
automatischen Kernel-Update/Reboot des Servers um 06:03 UTC). Folge: `updated_calculations` wurde mit 1:01:34
Verspätung **übersprungen** (`misfire_grace_time=60min`, kein Cutout `*_10_04_10_11_historical.nc`), ebenso
zwei stündliche Läufe. Wegen der überlappenden 7-Tage-Fenster geht dabei kein Tag verloren.

Strukturelles Risiko dahinter: `timestep` in `initial_calculations.py` ist ein eigener Zähler, der nur bei
tatsächlich ausgeführten Läufen um `interval` weitergezählt wird (`timestep += interval`), nicht aus der
Uhrzeit abgeleitet. Verpasste Läufe würden das Fenster also dauerhaft hinter die echte Zeit zurückfallen
lassen, bis zum nächsten Container-Neustart (der den Zähler neu initialisiert — am 19.10. hat der Reboot das
kaschiert). Noch nicht verifiziert, wie `start_scheduler` misfires behandelt; ggf. gleiches Muster in
`updated_calculations.py`/`forecast_calculations.py` prüfen. **Vorschlag**: Fensterende pro Lauf aus der
aktuellen Uhrzeit ableiten (auf volle Stunde gerundet) statt hochzuzählen. Ursache des einstündigen Hängers
selbst ggf. über `journalctl` für den Zeitraum klären.

## 8. Per-Unit-Download aus der Map auslagern

`download_per_unit_data` (`cosema/ingestion/entsoe.py`, nur im täglichen Lauf) ist der letzte Rohdaten-Download,
den die Map noch selbst macht — Erzeugung nach Typ, Verbrauch und Grenzflüsse kommen seit 28.08. live aus
`entsoe_raw`. Kraftwerksblock-Daten gab es dort laut `historie.md` (12.08.) noch nicht.

Gründe für das Auslagern: passt zur Architektur (die Map liest nur, Rohdaten kommen vom Server), ein eigener
Crawler kann verpasste Tage nachholen (der Scheduler-Zähler rückt nur vorwärts, siehe Punkt 7), Download- und
Rechenfehler blockieren sich nicht mehr gegenseitig, die Map braucht keinen eigenen `ENTSOE_API_KEY` mehr, und
die Daten stehen auch anderen zur Verfügung. Zwei der Probleme der letzten Wochen kamen aus diesem Pfad
(doppelte Zeitstempel aus `entsoe-py`, `per_unit_gen` ~9 Tage Rückstand Ende September).

Nicht dringend, läuft aktuell. **Optionen**: (a) OEDS-Betreuer fragen, ob ihr ENTSO-E-Crawler zusätzlich
"Generation per Production Unit" abrufen kann (sauberste Lösung, Crawler gehören nicht uns), oder (b) in den
geplanten eigenen Prefect-Flow für Referenzdaten (Punkt 2) mit aufnehmen. Auf Map-Seite danach nur noch
`query_per_unit_gen` auf die neue Tabelle umstellen und `download_per_unit` im täglichen Lauf abschalten —
gleiches Muster wie die Umstellung am 28.08.

**Vorab klären**: wie lange der Download aktuell dauert (in `logs/updated_calculations.log` die Spanne zwischen
APScheduler "Running job" um 05:45 und "Per unit data downloaded and written to database"), und ob
`per_unit_gen` den Rückstand von Ende September inzwischen aufgeholt hat.

## 9. Merge in `main`/`develop`

Der komplette Stand läuft bisher nur auf dem gemeinsam genutzten Staging-Server, auf dem Branch
`co2map-integration` — nie offiziell gemerged. War von Anfang an bewusst als allerletzter Schritt vorgesehen,
nachdem alles andere stabil läuft.
