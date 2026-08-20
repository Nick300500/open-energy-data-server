# cosema/ingestion/

Stufe 1 der Pipeline: Rohdaten-Download von externen Quellen. Schreibt direkt
über `cosema.input_output.influxdb.DBClient` in die Datenbank.

## entsoe.py

Haupt-Downloadquelle (ENTSO-E Transparency Platform), mit Spezialfällen für
GB/IE (aus `uk.py`) und DE (Ergänzung aus `smard.py`):

- `retry_function` — allgemeine Wiederholungslogik bei Verbindungsfehlern
- `download_per_unit_data` — Erzeugung je Einzelkraftwerk, pro TSO/Regelzone
- `download_per_type_data` (+ `_download_per_type_data`) — Erzeugung nach Typ, pro Land
- `download_demand_data` (+ `_download_demand_data`) — Verbrauch, pro Land
- `download_demand_forecast_data` — Verbrauchsprognose (Forecast-Pipeline)
- `download_vre_forecast_data` — VRE-Erzeugungsprognose (aktuell ungenutzt)
- `download_cross_border_flows` (+ `_download_cross_border_flows`) — Grenzflüsse zwischen Ländern

## smard.py

Zusatzquelle nur für Deutschland (SMARD-API), ergänzt/kombiniert mit den
ENTSO-E-Daten in `entsoe.py`:

- `download_DE_per_type_data` (+ `_download_DE_per_type_data`) — Erzeugung nach Typ für DE — **wird genutzt**
- `download_DE_demand_data` (+ `_download_DE_demand_data`) — Verbrauch für DE (aktuell ungenutzt)
- `download_DE_per_unit_data` (+ `_download_DE_per_unit_data`) — Pro-Einheit-Erzeugung für DE (aktuell ungenutzt)
- `_update_DE_power_plant_list` — aktualisiert die zugrundeliegende Kraftwerksliste (SMARD-Metadaten)

## uk.py

Zusatzquelle für Großbritannien/Irland (ENTSO-E deckt diese nicht vollständig
ab), genutzt in `entsoe.py`:

- `download_GB_per_type_data` / `download_IE_per_type_data` — Erzeugung nach Typ, GB bzw. IE
- `download_GB_demand_data` / `download_IE_demand_data` — Verbrauch, GB bzw. IE
- `download_GB_IE_flows` — Grenzfluss speziell zwischen GB und IE
- jeweils dazugehörige `_download_*`-Hilfsfunktionen mit der eigentlichen API-Abfrage
