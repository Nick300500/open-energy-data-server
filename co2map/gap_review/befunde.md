# Lückenanalyse Map-Inputs — Befunde (Stand 2026-10-28)

Datenbasis: Production-DB, Zeitraum 30.07.–27.10.2026 (`per_unit` ab 22.08.), Auswertung mit `gap_review.py`.
Lücke = Zeitpunkt ohne Zeile, mit NULL oder `''`; eine gemeldete 0 ist keine Lücke.

## 1. Gesamtergebnis je Quelle

| Quelle | Tabelle | Reihen | Auflösung | Fehlquote inkl. Ausfälle | Fehlquote ohne Ausfälle | Lücken ohne Ausfälle | Reihen ohne Lücke |
|---|---|---|---|---|---|---|---|
| Erzeugung | entsoe_raw.Zonal_Generation_Raw | 44 Zonen | 15/30/60 min | 13,5 % | 1,55 % | 207 | 1 |
| Last | entsoe_raw.Zonal_Demand_Raw | 44 Zonen | 15/30/60 min | 13,9 % | 1,96 % | 1.279 | 0 |
| Flows physikalisch | entsoe_raw.Cross_Border_Physical_Flows_Bidding_Zones_Raw | 172 Richtungen | 60 min | 12,6 % | 0,25 % (Schwelle 0,4) | 33 | 139 |
| Kraftwerksblöcke | cosema.per_unit_gen | 151 Blöcke | 15/60 min | 1,46 % | 1,46 % | 137 | 88 |

## 2. Crawler-Ausfalltage

| Datum | Art | Erzeugung | Last | Flows |
|---|---|---|---|---|
| 25.08. | Komplettausfall | ja | ja | ja |
| 28.08. | Teilausfall Flows (40 % der Grenzen fehlen) | nein | nein | teilweise |
| 30.08.–31.08. | Komplettausfall | ja | ja | ja |
| 01.09. | Ausfall Erzeugung/Last | ja | ja | nein |
| 05.09.–07.09. | Komplettausfall | ja | ja | ja |
| 14.09. | Teilausfall Flows (33 Richtungen ganztägig) | nein | nein | teilweise |
| 15.09.–18.09. | Komplettausfall | ja | ja | ja |
| 19.09. | Teilausfall Flows (71 % der Grenzen fehlen) | nein | nein | teilweise |

Seit 20.09. kein Crawler-Ausfall mehr.

## 3. Lücken je Land (ohne Ausfalltage)

| Zone | Fehlquote Erzeugung | Fehlquote Last | Bemerkung |
|---|---|---|---|
| MK | 51,1 % | 20,9 % | Erzeugung fehlt am Stück 05.–24.08. (458 h) |
| GB | 0,0 % | 39,0 % | Zeilen vorhanden, Lastwert leer; viele 30-min-Lücken |
| ME | 0,6 % | 13,9 % | nur Last |
| DK_1 | 0,6 % | 9,0 % | nur Last, 129 kurze Lücken |
| DK_2 | 0,6 % | 9,0 % | nur Last, 129 kurze Lücken |
| RO | 7,1 % | 6,9 % | Blöcke bis 119 h |
| GR | 5,0 % | 4,9 % | Blöcke bis 85 h |
| BG | 2,3 % | 2,6 % | |
| DE_LU | 0,46 % | 0,92 % | fast nur Viertelstunden-Lücken |
| übrige | < 2 % | < 2 % | |
| AL, IE | keine Daten | keine Daten | in entsoe_raw nicht vorhanden |
| LU | — | — | Teil der Zone DE_LU, kein Fehlbestand |

## 4. Deutschland (DE_LU) — Lücken über 3 h

| Datum | Quelle | Zeitraum (UTC) | Dauer | Art | Füllung durch Map |
|---|---|---|---|---|---|
| 29.08. | Erzeugung | 17:45–23:45 | 6,25 h | Zeile fehlt | 0 |
| 29.08. | Last | 17:15–23:45 | 6,75 h | Zeile fehlt | 0 |
| 23.10. | Last | 12:30–17:15 | 5 h | Zeile fehlt | 0 |
| 17.–19.10. | Erzeugung Biomasse | ganztägig | 72 h | Wert leer | 0 |

## 5. Lückenfüllung der Map (`cosema/input_output/gap_filling.py`)

Quelle: ursprünglicher CO2-Map-Code (Autoren R. Qussous, R. L. Grether), Füllung nur im Arbeitsspeicher beim
Einlesen, nicht in der DB gespeichert.

| Lückenlänge | Andere Länder | Deutschland | Flows | per_unit |
|---|---|---|---|---|
| ≤ 3 h mittendrin | linear | linear | linear | nicht gefüllt (→ 0) |
| ≤ 3 h am Rand | vorwärts/rückwärts fortgeschrieben | 0 | vorwärts/rückwärts fortgeschrieben | nicht gefüllt (→ 0) |
| 3 h – 1 Woche | Vorwoche kopiert | 0 | 0 | nicht gefüllt (→ 0) |
| > 1 Woche | 0 | 0 | 0 | nicht gefüllt (→ 0) |
| negative Werte | 0 | 0 | 0 | — |

## 6. Was mit den gefundenen Lücken passiert (ohne Ausfalltage)

| Füllung | Lücken | Stunden | Bewertung | Betroffen |
|---|---|---|---|---|
| linear | 1.297 | 1.345 | sauber | alle Quellen, ≤ 3 h |
| Vorwoche | 185 | 2.673 | Schätzung | Erzeugung/Last außer DE |
| 0 | 37 | 1.268 | unsauber | DE (3 Lücken, 18 h), Flows 14.09. (33 × 24 h), MK (458 h) |
| nicht gefüllt | 137 | 3.352 | ungenau | per_unit (v.a. Amprion 25.09., 05.10., 19.10.) |

Crawler-Ausfalltage werden im Betrieb ebenfalls gefüllt: DE und Flows mit 0, andere Länder mit Vorwoche.

## 7. Kommerzielle Flüsse als Ersatz für physikalische

Verfügbarkeit an Tagen mit fehlenden physikalischen Flüssen:

| Datum | Art | physikalisch fehlend | davon kommerziell (Total) vorhanden |
|---|---|---|---|
| Komplettausfälle | Komplettausfall | 100 % | 0 % |
| 28.08. | Teilausfall | 1.656 Werte | 97 % |
| 14.09. | Teilausfall | 792 Werte | 100 % |
| 19.09. | Teilausfall | 2.928 Werte | 32 % |

Übereinstimmung physikalisch vs. kommerziell (Netto-Export DE je Grenze, 01.–26.10.):

| Grenze | Korrelation | mittl. Abweichung [MW] | mittl. phys. Fluss [MW] | gleiche Richtung |
|---|---|---|---|---|
| DK_2 | 1,00 | 35 | 420 | 98,6 % |
| NO_2 | 1,00 | 17 | 983 | 96,5 % |
| SE_4 | 1,00 | 9 | 205 | 91,2 % |
| BE | 0,96 | 171 | 622 | 96,3 % |
| NL | 0,95 | 514 | 1.512 | 90,5 % |
| CZ | 0,94 | 341 | 1.022 | 90,2 % |
| PL | 0,93 | 845 | 1.320 | 80,5 % |
| FR | 0,90 | 931 | 1.070 | 85,7 % |
| DK_1 | 0,88 | 961 | 1.001 | 86,1 % |
| AT | 0,78 | 929 | 1.132 | 93,3 % |
| CH | 0,58 | 781 | 781 | 63,9 % |
| DE gesamt | 0,99 | — | — | — |

## 8. per_unit_gen

| Befund | Detail |
|---|---|
| Beginn | 22.08.2026 für alle Blöcke |
| Lückenart | nur leere Werte, keine fehlenden Zeilen |
| Häufung | Amprion: 25.09. (30 Blöcke, 48 h), 05.10. (30 Blöcke, 24 h), 19.10. (30 Blöcke, 2 h) |
| Auflösung | Blöcke mit Stundenwerten stehen auf 15-min-Index mit leeren Zwischenzeilen (keine Lücke) |
| Verhalten der Map | leerer Wert → 0 MW; Leistung bleibt in Restmenge, wird nach MaStR-Kapazität verteilt |
| Schwachstelle | Kapazität des Blocks zählt trotzdem als „direkt zugeordnet“ → Leistung landet bei anderen Kraftwerken/Ländern |
| Folge | Summen korrekt, regionale Verteilung an diesen Tagen ungenau |

## 9. Weitere Befunde

| Thema | Befund |
|---|---|
| Nullen | Crawler schreibt für Erzeugungsarten, die eine Zone nicht hat, 0 statt NULL (z.B. DE_LU Marine, Peat) |
| Crawler-Zeitpunkt | mind. 1× täglich, jeweils kompletter Vortag; Uhrzeit wechselnd (01:05, 12:10, 15:10 UTC beobachtet) |
| Schema `entsoe` | bereits gefüllte, stündliche Fassung von entsoe_raw; außerhalb von Lücken identisch; lange Last-Lücken mit Mittelwert statt 0; Crawler-Ausfälle dort ebenfalls nicht gefüllt; Map nutzt es nicht |

## 10. Wetter (`cosema.vre_gen`, `cosema.vre_forecast`, Stand 02.11.)

Geprüft direkt per SQL auf dem Server, je Bundesland × Technologie (Solar, Wind onshore, Wind offshore).

| Punkt | Ergebnis |
|---|---|
| Zeitraum | `vre_gen` 21.08.–21.10., `vre_forecast` 27.08.–30.10. |
| Fehlende Stunden | keine |
| Nullen | plausibel: Solar ~50 % (Nacht), Wind 0–59 Stunden (Flaute, SL wenige Anlagen) |
| NULL-Werte | gewollt: je Stunde eine Zeile `Generation [MW]` und eine Zeile `reg_factor` |
| Rückstand | Serverausfall ~29.10.–02.11. (Reboot 02.11. 09:24); `vre_gen` holt 22.–26.10. ab dem Tageslauf 03.11. selbst nach, Prognosen der Ausfalltage verloren (unkritisch) |
| Doppelte Zeilen | Altlast vor dem `write_df`-Fix: Prognose 28.08.–14.09. (bis 11 je Stunde), historisch 06./07.09.; seit 15.09. sauber |
| Auswirkung | Map mittelt Duplikate beim Lesen; CO2-Ergebnisse beginnen erst 13.09. → höchstens `only_per_type` 13./14.09. betroffen; kein Aufräumen nötig |

## 11. Empfehlungen

| Nr. | Bereich | heute | Vorschlag | Begründung |
|---|---|---|---|---|
| 1 | Deutschland, Lücken > 3 h | 0 | Vorwoche | Last = 0 physikalisch unmöglich, Erzeugung = 0 ebenso falsch |
| 2 | Flows, Lücken > 3 h | 0 | kommerzielle Flüsse (Total), sonst 0 | DE gesamt Korrelation 0,99; schließt Teilausfälle 14.09. ganz, 28.08. fast ganz |
| 3 | Lücken > 1 Woche | 0 | letzte vollständige Woche wiederholen | Vorwoche liegt selbst in der Lücke (z.B. MK 458 h) |
| 4 | per_unit, leere Werte | Block = 0, Kapazität gilt als zugeordnet | Kapazität nur zählen, wenn Block in der Stunde einen Wert hat | Leistung bleibt regional beim richtigen Bundesland, Summen bleiben konsistent |
| — | Crawler-Komplettausfälle | — | nicht durch Füllung lösbar | betrifft alle Tabellen gleichzeitig; Thema für den Crawler |
