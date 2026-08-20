# cosema/ (oberste Ebene)

Dateien, die bewusst nicht in einem Unterordner liegen — entweder weil sie
projektweite Basis-Infrastruktur sind (`config.py`, `regions.py`, `logging.py`),
von Generation- UND Consumption-Seite gebraucht werden (`balance.py`), oder weil
sie zur Consumption-Side gehören und noch nicht einsortiert wurden
(`calc_intensities.py`, `pypsa_scripts.py`, `cross_border_scripts.py` —
bewusst zurückgestellt, siehe `modularization_docs/modularisierung_status.md`).

## config.py

- `config` — Modulvariable, lädt `config.yaml` einmal zentral. Andere Module
  importieren `from cosema.config import config` statt selbst zu laden.

## regions.py

- `State` — Enum der 13 Bundesland-Kürzel, einzige Quelle der Wahrheit
- `BUSES` — Liste aller Bundesland-Kürzel (Enum-Werte), Ersatz für das alte
  `config["states"].values()`
- `OFFSHORE_STATES` — die drei Bundesländer mit Wind-Offshore-Kapazität
  (MV, NI, SH)

## logging.py

- `get_handlers` — baut die Logging-Handler (Konsole + rotierende Logdatei)
  für ein Skript

## balance.py

Ausgleichsrechnung (SIGI/"internal sigma"-Ansatz), damit Erzeugung, Verbrauch
und Grenzflüsse konsistent zueinander sind (Bilanzgleichung erfüllt ist), bevor
weitergerechnet wird — genutzt sowohl von der Produktions- als auch der
Verbrauchsseite:

- `prepare_cross_border_flows` — bereitet rohe (bidirektionale) Grenzflussdaten zu Netto-Flüssen auf
- `calcualte_weighting_factors` / `calcualte_threshold_factors` — berechnen Gewichtungen/Toleranzen je Land für den Ausgleich
- `calculate_internal_sigma` — Kernrechnung des Ausgleichsalgorithmus
- `make_balance` — führt Erzeugung, Verbrauch und Flüsse zu einer Bilanz zusammen
- `make_bilateral` / `make_unilateral` — wandeln zwischen bidirektionaler und gerichteter Flussdarstellung um
- `make_country_flow_balance` — baut die Länder-Flussbilanz (aktuell ungenutzt)
- `normalization_g_d` / `normalization_F` — normalisieren Erzeugung/Verbrauch bzw. Flüsse vor der Optimierung
- `renormalization_g_d` / `renormalization_F` — kehren die Normalisierung nach der Optimierung wieder um
- `get_data` — sammelt/baut die Eingabedaten für den Ausgleichsalgorithmus zusammen
- `internal_sigma_approach` — Haupteinstieg: führt den kompletten Ausgleich aus (nutzt Pyomo zur Optimierung)

## calc_intensities.py — Consumption-Side, zurückgestellt

Enthält sowohl die produktionsseitigen Kernschritte (durch den Golden-Master-Test
abgesichert) als auch die verbrauchsseitige Flow-Tracing-Logik, die noch nicht
herausgetrennt wurde:

- `load_config` / `load_technologies_and_ef` — Konfiguration bzw. Emissionsfaktoren laden
- `collect_and_prepare_data` — sammelt alle Vorstufen-Daten aus InfluxDB ein
- `balance_data` — gleicht Erzeugung/Verbrauch/Grenzflüsse aus (nutzt `balance.py`)
- `refactor_demand_column_names` / `aggregate_technologies` / `apply_regionalization_factors` — Produktionsseite, vom Golden-Master-Test abgedeckt
- `reconcile_cross_border_flows` — gleicht Grenzflüsse zwischen den Ebenen ab
- `save_balanced_reg_data` — speichert Zwischenergebnis
- `prepare_and_solve_network` — baut ein PyPSA-Netzmodell und löst es (nutzt `pypsa_scripts.py`)
- `run_flow_tracing` — Verbrauchsseite: führt Flow-Tracing aus (nutzt `Vendor/netallocation`)
- `extract_regional_data` — liest Ergebnisse aus dem gelösten Netz aus
- `get_reg_intensities` / `get_country_intensities` — produktionsseitige Intensität je Bundesland bzw. Land
- `calculate_intensities` — Haupteinstieg, orchestriert alle obigen Schritte

## pypsa_scripts.py — Consumption-Side, zurückgestellt

Aufbau und Lösen des PyPSA-Netzmodells, nur für die Flow-Tracing-Verbrauchsseite
gebraucht:

- `get_regions` / `get_crossborders` — lesen Regionen bzw. Grenzverbindungen aus einem Netz aus
- `get_reference_network` — lädt ein Referenznetz
- `prepare_network` — baut das PyPSA-Netz aus Erzeugung/Verbrauch/Flüssen auf
- `_quadexpr` — interne Hilfsfunktion für die Optimierung
- `solve_network_transport` — löst das Netzmodell

## cross_border_scripts.py — Consumption-Side, zurückgestellt

- `query_cross_border_flows` — liest Grenzflüsse, speist den Netzwerk-Aufbau in `pypsa_scripts.py`
