# cosema/forecast/

Prognose-Pipeline (zukünftige Erzeugung/Intensität statt vergangener Ist-Werte).
Bewusst unverändert übernommen — nur verschoben, keine inhaltliche Anpassung,
da aktuell nicht im Fokus der Modularisierung.

## calc_forecast.py

- `get_demand_data` — liest Verbrauchsdaten für die Prognose
- `get_vre_data` — liest VRE-Kapazitätsfaktoren für die Prognose
- `get_forecasts` — sammelt die Rohdaten ein, die als Eingabe fürs Prognosemodell dienen
- `get_temp_forecast` — liest/berechnet Temperaturprognose (Einflussgröße fürs Modell)
- `forecast_intensities` — Haupteinstieg: berechnet die Intensitätsprognose

## forecast_scripts.py

- `prepare_inputs` — bereitet Eingabedaten fürs LightGBM-Modell auf
- `prepare_outputs` — bereitet die Zielgröße (CO2-Intensität) auf
- `norm_data` / `denorm_data` — normalisieren/denormalisieren Daten vor bzw. nach dem Modell
- `load_forecast_model` — lädt ein trainiertes Modell für ein Bundesland
- `forecast_bus_intensity` — führt die eigentliche Vorhersage für ein Bundesland aus
- `update_model` — trainiert/aktualisiert ein Modell mit neuen Daten
- `update_forecast_model` — Haupteinstieg zum Nachtrainieren (aktuell ungenutzt)

Hinweis: `import lightgbm` ist optional abgesichert (`try/except`) — ohne
installiertes LightGBM funktioniert die Prognose nicht, der Rest der Pipeline
bleibt aber lauffähig.
