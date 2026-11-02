# gap_review — Lückenanalyse der Map-Inputs

Prüft die Zeitreihen-Inputs der CO2-Map (ENTSO-E-Crawler-Daten in `entsoe_raw` und `cosema.per_unit_gen`) auf
Lücken. Läuft **lokal** gegen die Production-DB über einen SSH-Tunnel; Rohdaten und Ergebnisse bleiben lokal
(`data/`, `out/`, beide git-ignored).

**Lücke** = Zeitpunkt im Raster der Reihe (15/30/60 min, je Reihe ermittelt) ohne Zeile, mit NULL oder mit `''`.
Eine gemeldete **0 ist keine Lücke**, sie wird nur als Info gezählt.

## Ausführen

1. VPN an, Tunnel offen lassen (eigenes Terminal):
   ```bash
   ssh -N -L 16432:localhost:<db_port> <user>@<server>
   ```
   `<db_port>` ist der Port der Production-DB auf dem Server-Host.
2. Einmalig `.env.example` nach `.env` kopieren und die Zugangsdaten eintragen
   (auf dem Server: `docker exec oeds-co2map env | grep -E "^DB_"`).
3. Starten:
   ```bash
   python gap_review.py              # letzte 90 Tage laden + auswerten
   python gap_review.py --days 30    # anderer Zeitraum
   python gap_review.py --skip-fetch # nur neu auswerten, ohne DB
   ```

**Crawler-Ausfälle** werden standardmäßig herausgerechnet: Ein Tag gilt pro Quelle als Ausfalltag, wenn
mindestens 80 % der Reihen mindestens die Hälfte des Tages fehlt. Solche Tage zählen in `gaps.csv`,
`coverage.csv` und `daily_missing.csv` weder als Soll noch als Lücke (`excluded_outage` in `coverage.csv`), sodass
nur die Lücken einzelner Zonen/Grenzen übrig bleiben. `outages.csv` listet weiterhin alle Tage.
- `--outage-share 0.4` — Schwelle senken, um auch Teilausfälle herauszurechnen (z.B. Flows am 28.08./19.09.2026)
- `--keep-outages` — nichts herausrechnen, Gesamtbild inkl. Ausfälle

## Ergebnisse (`out/`)

| Datei | Eine Zeile pro … | Inhalt |
|---|---|---|
| `gaps.csv` | zusammenhängende Lücke | Quelle, Reihe, Beginn, Ende, Dauer [h], Art (`no_row`/`null_value`/`empty`/`invalid`/`mixed`), Lage (`inside`/`start`/`end`) |
| `coverage.csv` | Zeitreihe | Auflösung, erster/letzter Wert, Soll/Ist, Fehlquote, Lücken, längste Lücke, Zählung je Art, Nullen, längste Null-Strecke (nur Last/Gesamterzeugung), Duplikate, Werte neben dem Raster (`off_grid`) bzw. leere Füllzeilen dort (`off_grid_empty`), Anteil abweichender Auflösung |
| `daily_missing.csv` | Reihe × Tag (nur Tage mit Lücken) | Fehlquote des Tages |
| `outages.csv` | Quelle × Tag | Anteil der Reihen, denen ≥ 50 % des Tages fehlen; `outage` ab Schwelle (Standard 80 %) → Crawler-Ausfall, wird herausgerechnet |
| `missing_series.csv` | erwartete Reihe ohne Daten | Zonen/Grenzen aus `config.yaml`, die im Zeitraum gar nicht vorkommen |

Quellen: `generation` (Zone), `generation_type` (Zone × Erzeugungsart, nur Arten, die die Zone überhaupt meldet),
`demand`, `flows` (From → To), `per_unit` (Block | Technologie | TSO).

## Hinweise

- `start`-Lücken: Reihe beginnt später als der Zeitraum. `end`-Lücken: Reihe endet vor dem jüngsten Wert der
  ganzen Quelle (z.B. Zone vom letzten Crawler-Lauf nicht geliefert).
- `missing_series.csv` meldet auch `LU`, obwohl Luxemburg zur Gebotszone `DE_LU` gehört — kein echter Fehlbestand.
  AL und IE fehlen in `entsoe_raw` bekanntermaßen ganz (siehe `cosema/input_output/oeds_zones.py`).
- `per_unit` hängt durch den täglichen Lauf ~8 Tage zurück; Anfang und Ende der Quelle sind deren eigener ältester
  bzw. jüngster Wert (die Tabelle gibt es erst seit 22.08.2026). Blöcke mit Stundenwerten stehen dort auf einem
  15-min-Index mit leeren Zwischenzeilen — die zählen als `off_grid_empty`, nicht als Lücke.
- Der Crawler schreibt für Erzeugungsarten, die eine Zone gar nicht hat, **0 statt NULL** (z.B. `DE_LU|Marine`).
  Solche Reihen tauchen daher in `generation_type` auf; ihre Lücken sind identisch mit denen der Zone.
