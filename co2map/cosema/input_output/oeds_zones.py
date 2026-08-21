"""
Bidding-zone <-> country-code mapping for reading ENTSO-E data directly out of
OEDS's own entsoe_raw schema (zone-level) into cosema's country-level model
(DBClient.query_per_type_gen / query_demand_data / query_cross_border_flows in
input_output/influxdb.py).

Most countries map 1:1 to an identically-named bidding zone. A handful of
countries are split into several zones; for those, generation/demand get
summed across all of the country's zones. Mapping verified against the live
`zone` values in entsoe_raw."Zonal_Generation_Raw"/"Zonal_Demand_Raw" and the
"From Zone"/"To Zone" values in "Cross_Border_Physical_Flows_Bidding_Zones_Raw"
(2026-08-21).

Known gap: AL and IE have no corresponding zone in entsoe_raw at all (not a
mapping issue -- the data simply isn't there). Callers get an empty result
for these, same as for any zone/time range with no rows.
"""

COUNTRY_TO_ZONES = {
    "DE": ["DE_LU"],
    "IT": ["IT_CALA", "IT_CNOR", "IT_CSUD", "IT_NORD", "IT_SARD", "IT_SICI", "IT_SUD"],
    "NO": ["NO_1", "NO_2", "NO_3", "NO_4", "NO_5"],
    "SE": ["SE_1", "SE_2", "SE_3", "SE_4"],
    "DK": ["DK_1", "DK_2"],
}


def zones_for_country(country: str) -> list:
    return COUNTRY_TO_ZONES.get(country, [country])
