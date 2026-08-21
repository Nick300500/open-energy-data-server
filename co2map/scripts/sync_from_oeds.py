"""
Reads ENTSO-E generation/demand data straight from OEDS's own `entsoe` schema
(the server's existing ENTSO-E crawler output) and writes it into our own
`cosema` schema via DBClient, in the same shape cosema.ingestion.entsoe already
writes it in -- so query_per_type_gen/query_demand_data (cosema/input_output/
influxdb.py) can read it back unchanged.

Status (2026-08-20, see co2map/UEBERGABE.md / oeds_integration_plan.md step 2):
server DB access is currently blocked (`pg_filenode.map` permission error), so
none of this has been run against the live server yet. Table/column names for
generation and demand below come from OEDS's own shipped dashboard
(data/provisioning/grafana/dashboards/entsoe.json, entsoe.query_generation /
entsoe.query_load) -- that's an OEDS-authored artifact, not our guess, but
still worth a `--inspect-schema` sanity check once the server is reachable
again before trusting it for real writes.

Cross-border flows are NOT covered here: no matching table showed up in any
shipped Grafana dashboard (checked entsoe.json/smard.json/jao.json/entsog.json --
jao/entsog only cover gas and day-ahead auctions, not electricity flows). Use
--inspect-schema to list what's actually in the `entsoe`/`entsoe_raw` schemas
once DB access works, then extend fetch_cross_border_flows() below.
"""
import argparse
import logging
import os

import pandas as pd
import yaml
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from cosema.logging import get_handlers

logger = logging.getLogger(__name__)

load_dotenv()

with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

# Generation technology names as cosema/DBClient use them (Title Case, see
# cosema/ingestion/entsoe.py::download_per_type_data -- these come straight from
# entsoe-py's own column names). OEDS's crawler appears to just snake_case the
# same entsoe-py columns for entsoe.query_generation: every column visible in
# data/provisioning/grafana/dashboards/entsoe.json matches
# technology.lower().replace(" ", "_") exactly (e.g. "Fossil Brown coal/Lignite"
# -> "fossil_brown_coal/lignite"). The full list here is entsoe-py's fixed
# PSRTYPE vocabulary; _existing_columns() below drops any that aren't actually
# present in the live table instead of assuming they all are.
GEN_TECHNOLOGIES = [
    "Biomass",
    "Fossil Brown coal/Lignite",
    "Fossil Coal-derived gas",
    "Fossil Gas",
    "Fossil Hard coal",
    "Fossil Oil",
    "Fossil Oil shale",
    "Fossil Peat",
    "Geothermal",
    "Hydro Pumped Storage",
    "Hydro Run-of-river and poundage",
    "Hydro Water Reservoir",
    "Marine",
    "Nuclear",
    "Other renewable",
    "Solar",
    "Waste",
    "Wind Offshore",
    "Wind Onshore",
    "Other",
]


def _technology_to_column(technology: str) -> str:
    return technology.lower().replace(" ", "_")


def oeds_engine():
    """Read-only connection to the OEDS server's own database (source) --
    separate from DBClient's connection to our own `cosema` schema (target)."""
    host = os.environ["OEDS_DB_HOST"]
    port = os.environ.get("OEDS_DB_PORT", "5432")
    dbname = os.environ.get("OEDS_DB_NAME", "opendata")
    user = os.environ["OEDS_DB_USER"]
    password = os.environ["OEDS_DB_PASSWORD"]
    return create_engine(
        f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}"
    )


def target_db_client():
    # imported lazily: DBClient's module reads inputs/generation_data/... at
    # import time, which --inspect-schema shouldn't need to depend on.
    from cosema.input_output.influxdb import DBClient

    return DBClient(
        database_name=os.environ.get("DB_NAME", "cosema"),
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "5432")),
        username=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def _existing_columns(engine, schema: str, table: str) -> set:
    query = text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = :schema AND table_name = :table"
    )
    with engine.connect() as conn:
        return {
            row[0]
            for row in conn.execute(query, {"schema": schema, "table": table})
        }


def inspect_schema(engine, schema: str = "entsoe") -> list:
    """Diagnostic helper: list tables in an OEDS schema. Run this first against
    the live server to (re-)verify the table names hardcoded below, and to find
    the cross-border-flow table this script doesn't cover yet."""
    query = text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = :schema ORDER BY 1"
    )
    with engine.connect() as conn:
        tables = [row[0] for row in conn.execute(query, {"schema": schema})]
    for table in tables:
        columns = sorted(_existing_columns(engine, schema, table))
        print(f"{schema}.{table}: {columns}")
    return tables


def fetch_generation(
    engine, country: str, start: pd.Timestamp, end: pd.Timestamp
) -> pd.DataFrame:
    """Long-format-ready DataFrame: index=time (UTC), one column per technology
    present both in GEN_TECHNOLOGIES and in the live table."""
    available = _existing_columns(engine, "entsoe", "query_generation")
    tech_to_column = {tech: _technology_to_column(tech) for tech in GEN_TECHNOLOGIES}
    present = {tech: col for tech, col in tech_to_column.items() if col in available}
    missing = set(tech_to_column.values()) - set(present.values())
    if missing:
        logger.warning(
            f"entsoe.query_generation has no column for: {sorted(missing)} "
            "(schema may have changed -- run --inspect-schema)"
        )
    if not present:
        raise RuntimeError(
            "None of the expected technology columns exist in entsoe.query_generation "
            "-- run --inspect-schema and update GEN_TECHNOLOGIES/_technology_to_column."
        )

    select_cols = ", ".join(f'"{col}"' for col in present.values())
    query = text(
        f'SELECT "index" AS "time", {select_cols} FROM entsoe.query_generation '
        f'WHERE country = :country AND "index" >= :start AND "index" <= :end '
        f'ORDER BY "index"'
    )
    with engine.connect() as conn:
        df = pd.read_sql(
            query,
            conn,
            params={
                "country": country,
                "start": start.to_pydatetime(),
                "end": end.to_pydatetime(),
            },
            index_col="time",
        )
    df.index = pd.to_datetime(df.index, utc=True)
    df = df.rename(columns={col: tech for tech, col in present.items()})
    return df


def fetch_demand(
    engine, country: str, start: pd.Timestamp, end: pd.Timestamp
) -> pd.DataFrame:
    query = text(
        'SELECT "index" AS "time", actual_load AS "Demand [MW]" '
        "FROM entsoe.query_load "
        'WHERE country = :country AND "index" >= :start AND "index" <= :end '
        'ORDER BY "index"'
    )
    with engine.connect() as conn:
        df = pd.read_sql(
            query,
            conn,
            params={
                "country": country,
                "start": start.to_pydatetime(),
                "end": end.to_pydatetime(),
            },
            index_col="time",
        )
    df.index = pd.to_datetime(df.index, utc=True)
    return df


def fetch_cross_border_flows(engine, country_from: str, country_to: str, start, end):
    raise NotImplementedError(
        "No cross-border-flow table has been identified yet in OEDS's entsoe/"
        "entsoe_raw schemas -- run `--inspect-schema` against the live server "
        "and wire the real table/columns in here (see module docstring)."
    )


def sync_generation(
    source_engine, db_client, countries, start, end, dry_run: bool
):
    for country in countries:
        gen = fetch_generation(source_engine, country, start, end)
        if gen.empty:
            logger.warning(f"No generation data for {country}, {start} - {end}")
            continue

        n_technologies = gen.notna().any().sum()
        logger.info(
            f"{country}: {len(gen)} generation rows, {n_technologies} technologies"
        )
        if dry_run:
            continue

        for technology, series in gen.items():
            tech_df = series.dropna().to_frame(name="Generation [MW]")
            if tech_df.empty:
                continue
            db_client.write_df(
                df=tech_df,
                measurement="per_type_gen",
                tags={"country": country, "technology": technology},
            )


def sync_demand(source_engine, db_client, countries, start, end, dry_run):
    for country in countries:
        demand = fetch_demand(source_engine, country, start, end)
        if demand.empty:
            logger.warning(f"No demand data for {country}, {start} - {end}")
            continue

        logger.info(f"{country}: {len(demand)} demand rows")
        if dry_run:
            continue

        db_client.write_df(df=demand, measurement="demand", tags={"country": country})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", help="e.g. 2026-07-01")
    parser.add_argument("--end", help="e.g. 2026-08-01")
    parser.add_argument(
        "--countries",
        nargs="+",
        default=None,
        help="Country codes to sync (default: config.yaml's `countries` list)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only fetch and log row counts, don't write to the target DB",
    )
    parser.add_argument(
        "--inspect-schema",
        metavar="SCHEMA",
        nargs="?",
        const="entsoe",
        help="List tables/columns in the given OEDS schema (default: entsoe) and exit",
    )
    args = parser.parse_args()

    handlers = get_handlers(log_path="logs/sync_from_oeds.log")
    logging.basicConfig(level=logging.INFO, handlers=handlers)

    source_engine = oeds_engine()

    if args.inspect_schema:
        inspect_schema(source_engine, args.inspect_schema)
        return

    if not args.start or not args.end:
        parser.error("--start and --end are required unless --inspect-schema is used")

    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC")
    countries = args.countries or config["countries"]

    db_client = None if args.dry_run else target_db_client()

    sync_generation(source_engine, db_client, countries, start, end, args.dry_run)
    sync_demand(source_engine, db_client, countries, start, end, args.dry_run)

    logger.info(f"Done. {'(dry run, nothing written)' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
