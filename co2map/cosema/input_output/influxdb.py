"""
This file contains the class that writes the results of the simulation to a database or to CSV files.

Implemented by Nick Harder, University of Freiburg, 2023

Renamed from db_client.py during modularization (2026-07-16): the class wraps
InfluxDBClient/DataFrameClient specifically, not a generic DB backend, and
this module is planned to absorb the query-loop helpers from per_type_scripts.py
/ demand_scripts.py too (see modularization_docs/modularisierung_zielstruktur.md) -- so
"influxdb" describes its scope better than "db_client" going forward.

Ported from InfluxDB to TimescaleDB/Postgres (2026-08-13, see TASK_dbclient_rewrite.md):
same method names/signatures as before, SQL instead of InfluxQL. Scope decision for
this port (confirmed with Nick): the three methods that will eventually read from
OEDS's existing entsoe_raw/entsoe schema (query_per_type_gen, query_demand_data,
query_cross_border_flows) keep their own read/write logic here for now -- no OEDS
server access yet. That redirection is a separate, later task; parts of this file
will be dropped again once it happens.

Tables are created dynamically per `measurement` name (mirroring InfluxDB's schemaless
measurements/tags): write_df() infers columns from the tag dict + dataframe columns and
creates/extends the table as needed. This matters because write_df is also called
directly (not just through DBClient's own methods) from cosema/ingestion/entsoe.py with
varying measurement/tag combinations.
"""
import logging
import traceback

logger = logging.getLogger(__name__)

import pandas as pd
import yaml
from sqlalchemy import create_engine, text

from cosema.input_output.gap_filling import (
    cross_border_rules_unilateral,
    default_rules,
    find_gaps,
    germany_rules,
)
from cosema.regions import BUSES, OFFSHORE_STATES

gen_types_df = pd.read_csv("inputs/generation_data/gen_types_and_emission_factors.csv")
ALLOW_NEGATIVE_GENERATION = list(
    gen_types_df[gen_types_df["is_storage"]]["entsoe"].unique()
)
GEN_TYPES = gen_types_df["entsoe"].unique()

with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)


def _quote_ident(name: str) -> str:
    """Double-quote a Postgres identifier, escaping embedded quotes."""
    return '"' + name.replace('"', '""') + '"'


class DBClient:
    def __init__(
        self,
        database_name,
        host="localhost",
        port=5432,
        username="postgres",
        password="postgres",
        time_zone="UTC",
        schema="cosema",
    ):
        self.time_zone = time_zone
        self.schema = schema

        self.engine = create_engine(
            f"postgresql+psycopg2://{username}:{password}@{host}:{port}/{database_name}"
        )
        with self.engine.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_quote_ident(schema)}"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))

        # (table, column) pairs already known to exist -- avoids an ALTER TABLE
        # round-trip on every single write_df call once a table has stabilized.
        self._known_columns = set()

    def _ensure_table(self, measurement: str, tag_columns: list, value_columns: list):
        schema_q = _quote_ident(self.schema)
        table_q = _quote_ident(measurement)
        all_columns = list(tag_columns) + list(value_columns)

        missing = [
            c for c in all_columns if (measurement, c) not in self._known_columns
        ]
        if not missing:
            return

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    f"CREATE TABLE IF NOT EXISTS {schema_q}.{table_q} "
                    f'("time" TIMESTAMPTZ NOT NULL)'
                )
            )
            conn.execute(
                text(
                    "SELECT create_hypertable(:table, 'time', if_not_exists => TRUE)"
                ),
                {"table": f"{self.schema}.{measurement}"},
            )
            for column in tag_columns:
                if (measurement, column) in self._known_columns:
                    continue
                conn.execute(
                    text(
                        f"ALTER TABLE {schema_q}.{table_q} "
                        f"ADD COLUMN IF NOT EXISTS {_quote_ident(column)} TEXT"
                    )
                )
            for column in value_columns:
                if (measurement, column) in self._known_columns:
                    continue
                conn.execute(
                    text(
                        f"ALTER TABLE {schema_q}.{table_q} "
                        f"ADD COLUMN IF NOT EXISTS {_quote_ident(column)} DOUBLE PRECISION"
                    )
                )

        self._known_columns.update((measurement, c) for c in all_columns)

    def write_df(self, df: pd.DataFrame, measurement: str, tags: dict):
        if df.empty:
            return

        tags = tags or {}
        value_columns = list(df.columns)
        self._ensure_table(
            measurement, tag_columns=list(tags.keys()), value_columns=value_columns
        )

        insert_df = df.copy()
        insert_df.index.name = "time"
        insert_df = insert_df.reset_index()
        for key, value in tags.items():
            insert_df[key] = value

        insert_df.to_sql(
            measurement,
            self.engine,
            schema=self.schema,
            if_exists="append",
            index=False,
            method="multi",
        )

    def _table_exists(self, measurement: str) -> bool:
        with self.engine.connect() as conn:
            result = conn.execute(
                text("SELECT to_regclass(:full_name)"),
                {"full_name": f"{self.schema}.{measurement}"},
            ).scalar()
        return result is not None

    def _where_clause(self, filters: dict, start: pd.Timestamp, end: pd.Timestamp):
        where_clauses = ['"time" >= :start', '"time" <= :end']
        params = {"start": start.to_pydatetime(), "end": end.to_pydatetime()}
        for i, (key, value) in enumerate(filters.items()):
            param_name = f"filter_{i}"
            where_clauses.append(f"{_quote_ident(key)} = :{param_name}")
            params[param_name] = value
        return " AND ".join(where_clauses), params

    def _read_raw(
        self,
        measurement: str,
        value_column: str,
        filters: dict,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> pd.DataFrame:
        """Plain SELECT of one value column, filtered by tag equality + time range.
        No server-side aggregation -- matches the raw (non-GROUP BY) InfluxQL queries."""
        if not self._table_exists(measurement):
            return pd.DataFrame(columns=[value_column])

        schema_q = _quote_ident(self.schema)
        table_q = _quote_ident(measurement)
        value_q = _quote_ident(value_column)
        where_sql, params = self._where_clause(filters, start, end)

        query = (
            f'SELECT "time", {value_q} FROM {schema_q}.{table_q} '
            f'WHERE {where_sql} ORDER BY "time"'
        )
        with self.engine.connect() as conn:
            df = pd.read_sql(text(query), conn, params=params, index_col="time")
        if df.empty:
            # an empty resultset has no rows to infer a dtype from, so
            # pandas gives it a plain Index -- force a tz-aware DatetimeIndex
            # so callers can still call .tz_convert() on the (empty) result.
            df.index = pd.DatetimeIndex([], tz="UTC", name="time")
        return df

    def _read_aggregated(
        self,
        measurement: str,
        value_column: str,
        filters: dict,
        start: pd.Timestamp,
        end: pd.Timestamp,
        agg: str,
    ) -> pd.DataFrame:
        """time_bucket('1 hour', ...) aggregation -- matches the InfluxQL
        `GROUP BY time(1h)` queries (mean()/sum())."""
        if not self._table_exists(measurement):
            return pd.DataFrame(columns=[value_column])

        agg_fn = {"avg": "AVG", "sum": "SUM"}[agg]
        schema_q = _quote_ident(self.schema)
        table_q = _quote_ident(measurement)
        value_q = _quote_ident(value_column)
        where_sql, params = self._where_clause(filters, start, end)

        query = (
            f'SELECT time_bucket(\'1 hour\', "time") AS "time", '
            f'{agg_fn}({value_q}) AS {value_q} '
            f"FROM {schema_q}.{table_q} WHERE {where_sql} "
            f'GROUP BY 1 ORDER BY 1'
        )
        with self.engine.connect() as conn:
            df = pd.read_sql(text(query), conn, params=params, index_col="time")
        if df.empty:
            df.index = pd.DatetimeIndex([], tz="UTC", name="time")
        return df

    def query_per_type_gen(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
        technologies: list,
        country: str = "DE",
        fill_gaps: bool = True,
        return_gap_info: bool = False,
        resample: str = "1h",
    ):
        measurement = "per_type_gen"
        per_type_gen = pd.DataFrame()
        orig_start = start

        # for gap filling we require the previous weeks' data as well
        if fill_gaps:
            start = start - pd.Timedelta(weeks=2)

        for technology in technologies:
            temp_df = self._read_raw(
                measurement,
                value_column="Generation [MW]",
                filters={"country": country, "technology": technology},
                start=start,
                end=end,
            )
            if len(temp_df) == 0:
                continue
            temp_df = temp_df.rename(columns={"Generation [MW]": technology})
            per_type_gen = pd.concat([per_type_gen, temp_df], axis=1)

        # convert time zone and fill missing rows with nan
        per_type_gen.index = per_type_gen.index.tz_convert(self.time_zone)
        per_type_gen = per_type_gen.reindex(
            pd.date_range(
                start=start, end=end, freq=pd.infer_freq(per_type_gen.index[:3])
            )
        )

        # fill gaps if requested
        if fill_gaps:
            per_type_gen, gap_dict = find_gaps(
                per_type_gen,
                check_negatives=True,
                allow_negatives=ALLOW_NEGATIVE_GENERATION,
                fill_gaps=True,
                gap_filling_rules=(germany_rules if country == "DE" else default_rules),
            )

        # resample data if requested
        if (resample is not None) and (resample is not False):
            per_type_gen = per_type_gen.resample(resample).mean()

        # trim additional data if necessary
        per_type_gen = per_type_gen[orig_start:end]

        if fill_gaps and return_gap_info:
            return per_type_gen, gap_dict
        else:
            return per_type_gen

    def query_per_unit_gen(self, start: pd.Timestamp, end: pd.Timestamp):
        measurement = "per_unit_gen"
        tag_columns = ["ID", "technology", "TSO", "EIC"]
        value_column = "Generation [MW]"

        if not self._table_exists(measurement):
            return {}

        schema_q = _quote_ident(self.schema)
        table_q = _quote_ident(measurement)
        select_cols = ", ".join(_quote_ident(c) for c in tag_columns + [value_column])
        query = (
            f'SELECT "time", {select_cols} FROM {schema_q}.{table_q} '
            f'WHERE "time" >= :start AND "time" <= :end ORDER BY "time"'
        )
        with self.engine.connect() as conn:
            df = pd.read_sql(
                text(query),
                conn,
                params={"start": start.to_pydatetime(), "end": end.to_pydatetime()},
            )

        # mimics InfluxDB's `GROUP BY *` ResultSet: a dict keyed by
        # (measurement, [(tag, value), ...]) -> per-group DataFrame, so that
        # `for keys, values in per_unit_gen.items(): dict(keys[1])` (see
        # regional_split.py::preprocess_gen_per_unit) keeps working unchanged.
        per_unit_gen = {}
        for tag_values, group in df.groupby(tag_columns, dropna=False):
            if not isinstance(tag_values, tuple):
                tag_values = (tag_values,)
            group_df = group.set_index("time")[[value_column]]
            tag_items = tuple(zip(tag_columns, tag_values))
            per_unit_gen[(measurement, tag_items)] = group_df

        return per_unit_gen

    def check_per_unit_data(self, start: pd.Timestamp, end: pd.Timestamp):
        measurement = "per_unit_gen"

        gen = self._read_raw(
            measurement,
            value_column="Generation [MW]",
            filters={"technology": "Hydro Run-of-river and poundage"},
            start=start,
            end=end,
        )
        gen = gen.dropna()
        gen.index = gen.index.tz_convert(self.time_zone)

        return gen.index.unique()

    def query_vre(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
        technology: str = "solar",
        state: str = "BW",
        value: str = "Generation [MW]" or "reg_factor",
        mode: str = "historical" or "forecast",
    ):
        measurement = "vre_gen" if mode == "historical" else "vre_forecast"

        vre_cf = self._read_aggregated(
            measurement,
            value_column=value,
            filters={"state": state, "technology": technology},
            start=start,
            end=end,
            agg="avg",
        )
        vre_cf.index = vre_cf.index.tz_convert(self.time_zone)

        return vre_cf

    def query_demand_data(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
        country: str = "DE",
        mode: str = "historical" or "forecast",
        fill_gaps: bool = True,
        return_gap_info: bool = False,
        resample: str = "1h",
    ):
        measurement = "demand" if mode == "historical" else "demand_forecast"
        orig_start = start

        # for gap filling we require the previous weeks' data as well
        if fill_gaps:
            start = start - pd.Timedelta(weeks=2)

        demand = self._read_raw(
            measurement,
            value_column="Demand [MW]",
            filters={"country": country},
            start=start,
            end=end,
        )

        # convert time zone and fill missing rows with nan
        demand.index = demand.index.tz_convert(self.time_zone)
        demand = demand.reindex(
            pd.date_range(start=start, end=end, freq=pd.infer_freq(demand.index[:3]))
        )

        # fill gaps if requested
        if fill_gaps:
            demand, gap_dict = find_gaps(
                demand,
                check_negatives=True,
                fill_gaps=True,
                gap_filling_rules=(germany_rules if country == "DE" else default_rules),
            )

        # resample data if requested
        if (resample is not None) and (resample is not False):
            demand = demand.resample(resample).mean()

        # trim additional data if necessary
        demand = demand[orig_start:end]

        if fill_gaps and return_gap_info:
            return demand, gap_dict
        else:
            return demand

    def query_reg_gen_data(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
        state: str = "DE",
        mode: str = "with_per_unit",
        technologies: list = None,
        column_name: str = "Generation [MW]",
        balanced: bool = False,
    ):
        measurement = "reg_generation"
        balanced = "yes" if balanced else "no"

        per_type_gen = pd.DataFrame()

        for technology in technologies:
            temp_df = self._read_aggregated(
                measurement,
                value_column=column_name,
                filters={
                    "state": state,
                    "technology": technology,
                    "mode": mode,
                    "balanced": balanced,
                },
                start=start,
                end=end,
                agg="sum",
            )
            if len(temp_df) == 0:
                continue
            temp_df = temp_df.rename(columns={column_name: technology})
            per_type_gen[technology] = temp_df[technology]

        if not per_type_gen.empty:
            per_type_gen.index = per_type_gen.index.tz_convert(self.time_zone)

        return per_type_gen

    def query_reg_demand_data(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
        state: str = "DE",
        column_name: str = "Demand [MW]",
        balanced: bool = False,
    ):
        measurement = "reg_demand"
        balanced = "yes" if balanced else "no"

        reg_demand = self._read_aggregated(
            measurement,
            value_column=column_name,
            filters={"state": state, "balanced": balanced},
            start=start,
            end=end,
            agg="sum",
        )
        reg_demand.index = reg_demand.index.tz_convert(self.time_zone)

        return reg_demand

    def query_intensities(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
        state: str = "DE",
        emission_type: str = "consumption" or "production",
        mode: str = "with_per_unit" or "forecast",
    ):
        measurement = "co2_intensity"

        intensity = self._read_aggregated(
            measurement,
            value_column="Intensity [g/kWh]",
            filters={"state": state, "type": emission_type, "mode": mode},
            start=start,
            end=end,
            agg="avg",
        )
        intensity.index = intensity.index.tz_convert(self.time_zone)

        return intensity

    def query_cross_border_flows(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
        country_code_from: str,
        country_code_to: str,
        fill_gaps: bool = True,
        return_gap_info: bool = False,
        resample: str = "1h",
    ):
        measurement = "cross_border_flow"
        orig_start = start

        # for gap filling we require the previous weeks' data as well
        if fill_gaps:
            start = start - pd.Timedelta(weeks=2)

        flows = self._read_raw(
            measurement,
            value_column="Flow [MW]",
            filters={"from": country_code_from, "to": country_code_to},
            start=start,
            end=end,
        )

        # convert time zone and fill missing rows with nan
        flows.index = flows.index.tz_convert(self.time_zone)
        flows = flows.reindex(
            pd.date_range(start=start, end=end, freq=pd.infer_freq(flows.index[:3]))
        )

        # fill gaps if requested
        if fill_gaps:
            flows, gap_dict = find_gaps(
                flows,
                check_negatives=True,
                fill_gaps=True,
                gap_filling_rules=cross_border_rules_unilateral,
            )

        # resample data if requested
        if (resample is not None) and (resample is not False):
            flows = flows.resample(resample).mean()

        # trim additional data if necessary
        flows = flows[orig_start:end]

        if fill_gaps and return_gap_info:
            return flows, gap_dict
        else:
            return flows

    def write_vre_data(
        self,
        df: pd.DataFrame,
        technology: str,
        state: str,
        mode: str = "historical" or "forecast",
        column_name: str = "Generation [MW]" or "reg_factor",
    ):
        measurement = "vre_gen" if mode == "historical" else "vre_forecast"

        tempDF = pd.DataFrame(
            index=df.index,
            columns=[column_name],
            data=df.values,
        ).astype("float32")

        self.write_df(
            df=tempDF,
            measurement=measurement,
            tags={"state": state, "technology": technology},
        )

    def write_reg_intensities(
        self,
        intensity: pd.DataFrame,
        type: str = "generation" or "consumption",
        mode="only_per_type" or "with_per_unit" or "forecast",
    ):
        intensity.index = intensity.index.tz_convert("UTC")

        for state, content in intensity.items():
            tempDF = pd.DataFrame(
                index=content.index, columns=["Intensity [g/kWh]"], data=content.values
            ).astype("int")
            self.write_df(
                df=tempDF,
                measurement="co2_intensity",
                tags={"type": type, "state": state, "mode": mode},
            )

    def write_reg_demand_data(
        self,
        df,
        column_name="Demand [MW]",
        balanced=False,
        extra_tags=None,
    ):
        balanced = "yes" if balanced else "no"
        dtype = "int" if balanced else "float32"

        for state in df:
            tempDF = pd.DataFrame(
                index=df.index,
                columns=[column_name],
                data=df[state].values,
            ).astype(dtype)

            tags = {"state": state, "balanced": balanced}
            if extra_tags is not None:
                tags.update(extra_tags)

            self.write_df(
                df=tempDF,
                measurement="reg_demand",
                tags=tags,
            )

    def write_reg_generation_data(
        self,
        df,
        mode,
        column_name="Generation [MW]",
        balanced=False,
        extra_tags=None,
    ):
        balanced = "yes" if balanced else "no"
        dtype = "int" if balanced else "float32"

        for column in df:
            state, technology = column.split("_")
            tempDF = pd.DataFrame(
                index=df.index,
                columns=[column_name],
                data=df[column].values,
            ).astype(dtype)

            tags = {
                "state": state,
                "technology": technology,
                "mode": mode,
                "balanced": balanced,
            }
            if extra_tags is not None:
                tags.update(extra_tags)

            self.write_df(
                df=tempDF,
                measurement="reg_generation",
                tags=tags,
            )

    # Function to delete databases and simulations
    def delete_series(self, tags: dict = None, measurement: str = None):
        print(f"You are about to delete measurement {measurement} with tags: {tags}")
        reply = input('Are you sure? Type "yes" or "y" to confirm:')
        if reply.lower() in ["yes", "y"]:
            tags = tags or {}
            schema_q = _quote_ident(self.schema)
            table_q = _quote_ident(measurement)
            where_clauses = []
            params = {}
            for i, (key, value) in enumerate(tags.items()):
                param_name = f"filter_{i}"
                where_clauses.append(f"{_quote_ident(key)} = :{param_name}")
                params[param_name] = value
            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

            with self.engine.begin() as conn:
                conn.execute(text(f"DELETE FROM {schema_q}.{table_q} {where_sql}"), params)
            print(f"Measurement {measurement}, tags {tags} deleted")
        else:
            print("Ok, not deleted !")

    # Function to delete intervals
    def delete_interval(self, measurement: str, start: pd.Timestamp, end: pd.Timestamp):
        print(
            f"You are about to delete measurement {measurement} between {start} and {end}"
        )
        reply = input('Are you sure? Type "yes" or "y" to confirm:')
        if reply.lower() in ["yes", "y"]:
            schema_q = _quote_ident(self.schema)
            table_q = _quote_ident(measurement)

            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        f'DELETE FROM {schema_q}.{table_q} '
                        f'WHERE "time" >= :start AND "time" <= :end'
                    ),
                    {"start": start.to_pydatetime(), "end": end.to_pydatetime()},
                )
            print(f"Measurement {measurement} between {start} and {end} deleted")
        else:
            print("Ok, not deleted !")


# Moved from demand_scripts.py during modularization (2026-07-16): these are
# pure InfluxDB query wrappers (loop over countries/states, no computation
# beyond assembling the result), same reasoning as the DBClient move above.
def query_demand_data(
    start: pd.Timestamp,
    end: pd.Timestamp,
    db_client,
    mode="historical",
    countries: list = None,
):
    if countries is None:
        countries = config["countries"]

    demand_df = pd.DataFrame(
        index=pd.date_range(start=start, end=end, freq="1h"),
        columns=countries,
        data=0.0,
    )

    for country in countries:
        try:
            demand = db_client.query_demand_data(
                start=start, end=end, country=country, mode=mode
            )
            demand_df[country] = demand.values
        except Exception as e:
            logger.warning(
                f"No data for {country} for period {start} - {end}. Returning 0.0..."
            )
            demand_df[country] = 0.0

    return demand_df


def query_DE_demand_data(
    start: pd.Timestamp, end: pd.Timestamp, db_client, country="DE", mode="historical"
):
    demand_DE = db_client.query_demand_data(
        start=start, end=end, country=country, mode=mode
    )

    return demand_DE


def query_reg_demand_data(
    start: pd.Timestamp,
    end: pd.Timestamp,
    db_client,
    column_name="Demand [MW]",
    balanced=False,
):
    demand_df = pd.DataFrame(
        index=pd.date_range(start=start, end=end, freq="1h"),
        columns=[f"DE_{bus}" for bus in BUSES],
        data=0.0,
    )

    for state in BUSES:
        try:
            demand = db_client.query_reg_demand_data(
                start=start,
                end=end,
                state=state,
                column_name=column_name,
                balanced=balanced,
            )
        except Exception as e:
            error = traceback.format_exc().splitlines()[-1]
            logger.warning(
                f'Error "{error}" during demand data query: state {state}, period {start}-{end}.'
            )
            continue

        demand_df[f"DE_{state}"] = demand.values

    return demand_df


# Moved from per_type_scripts.py during modularization (2026-07-16): pure
# InfluxDB query wrappers, same reasoning as the demand_scripts.py move above.
def query_per_type_data(
    start: pd.Timestamp,
    end: pd.Timestamp,
    db_client,
    countries: list = None,
):
    gen_per_type = {}

    if countries is None:
        countries = config["countries"]

    for country in countries:
        try:
            country_gen = db_client.query_per_type_gen(
                start=start, end=end, technologies=GEN_TYPES, country=country
            )
        except Exception:
            logger.warning(
                f"No data for {country} for period {start} - {end}. Returning 0.0..."
            )
            country_gen = pd.DataFrame(
                index=pd.date_range(start, end, freq="1h"),
                columns=["Other"],
                data=0.0,
            )

        gen_per_type[country] = country_gen

    gen_per_type = pd.concat(gen_per_type, axis=1)

    return gen_per_type


def query_reg_per_type_data(
    start: pd.Timestamp,
    end: pd.Timestamp,
    db_client,
    mode="with_per_unit" or "only_per_type",
    column_name="Generation [MW]",
    balanced=False,
):
    reg_gen_per_type = {}

    for state in BUSES:
        try:
            state_gen = db_client.query_reg_gen_data(
                start=start,
                end=end,
                technologies=GEN_TYPES,
                state=state,
                mode=mode,
                column_name=column_name,
                balanced=balanced,
            )
            # fill nan values with 0
            state_gen = state_gen.fillna(0)
            # drop columns with all 0 values
            state_gen = state_gen.loc[:, (state_gen != 0).any(axis=0)]
        except Exception:
            logger.warning(f"No data for {state} for period {start} - {end}.")
            continue

        reg_gen_per_type[f"DE_{state}"] = state_gen

    reg_gen_per_type = pd.concat(reg_gen_per_type, axis=1)

    return reg_gen_per_type


def collect_vre(
    start: pd.Timestamp,
    end: pd.Timestamp,
    db_client,
    mode: str = "historical" or "forecast",
    value: str = "Generation [MW]" or "reg_factor",
):
    index = pd.date_range(start=start, end=end, freq="1h")
    solar = pd.DataFrame(index=index, columns=BUSES, data=0.0)
    wind_onshore = pd.DataFrame(index=index, columns=BUSES, data=0.0)
    wind_offshore = pd.DataFrame(index=index, columns=BUSES, data=0.0)

    for state in BUSES:
        temp_df = db_client.query_vre(
            start=start,
            end=end,
            technology="solar",
            state=state,
            value=value,
            mode=mode,
        )
        solar[state] = temp_df.values

        temp_df = db_client.query_vre(
            start=start,
            end=end,
            technology="wind_onshore",
            state=state,
            value=value,
            mode=mode,
        )
        wind_onshore[state] = temp_df.values

        if state not in OFFSHORE_STATES:
            continue

        temp_df = db_client.query_vre(
            start=start,
            end=end,
            technology="wind_offshore",
            state=state,
            value=value,
            mode=mode,
        )
        wind_offshore[state] = temp_df.values

    return solar, wind_onshore, wind_offshore


def collect_intensities(start: pd.Timestamp, end: pd.Timestamp, db_client):
    index = pd.date_range(start=start, end=end, freq="1h")
    cons_intensity = pd.DataFrame(index=index, columns=BUSES, data=0.0)
    gen_intensity = pd.DataFrame(index=index, columns=BUSES, data=0.0)

    for state in BUSES:
        temp_df = db_client.query_intensities(
            start=start,
            end=end,
            state=state,
            emission_type="Consumption",
            mode="with_per_unit",
        )
        cons_intensity[state] = temp_df.values

        temp_df = db_client.query_intensities(
            start=start,
            end=end,
            state=state,
            emission_type="Generation",
            mode="with_per_unit",
        )
        gen_intensity[state] = temp_df.values

    return cons_intensity, gen_intensity
