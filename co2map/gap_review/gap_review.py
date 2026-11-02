"""
Gap review of the CO2-Map's time-series inputs, run locally against the
production DB through an SSH tunnel (see README.md in this folder).

Two phases:
- fetch:   downloads the last --days days of every input into ./data (parquet),
           zone by zone / TSO by TSO, values cast to text so NULL, '' and 0 stay
           distinguishable.
- analyze: builds the result CSVs in ./out from ./data, no DB access.

What counts as a gap: a timestamp on the series' own grid (15/30/60 min,
inferred per series) with no row, a NULL or an empty string. A reported 0 is a
real value, not a gap -- zeros are only counted as info (n_zero,
zero_run_max_h).

Sources:
- generation       entsoe_raw."Zonal_Generation_Raw", one series per zone
                   (row present with at least one technology value)
- generation_type  same table, one series per zone x technology; only
                   technologies the zone reports at least once in the period
- demand           entsoe_raw."Zonal_Demand_Raw"."Actual_Load" per zone
- flows            entsoe_raw."Cross_Border_Physical_Flows_Bidding_Zones_Raw"
                   per (From Zone, To Zone)
- per_unit         cosema.per_unit_gen per unit (ID | technology | TSO)
"""
import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = HERE / "out"
CO2MAP = HERE.parent

sys.path.insert(0, str(CO2MAP))
from cosema.input_output.oeds_zones import zones_for_country  # noqa: E402

GEN_META_COLUMNS = {"time", "zone"}
# Series kinds for which a long run of exact zeros is physically implausible
# (a whole zone with 0 MW load / 0 MW generation) -- reported, not a gap.
ZERO_RUN_SOURCES = {"generation", "demand"}


def get_engine():
    load_dotenv(HERE / ".env")
    url = (
        f"postgresql://{os.environ['GAP_DB_USER']}:{os.environ['GAP_DB_PASSWORD']}"
        f"@{os.environ.get('GAP_DB_HOST', 'localhost')}:{os.environ.get('GAP_DB_PORT', '16432')}"
        f"/{os.environ.get('GAP_DB_NAME', 'opendata')}"
    )
    return create_engine(url)


def q(name):
    return '"' + name.replace('"', '""') + '"'


# --------------------------------------------------------------------- fetch


def fetch(days):
    engine = get_engine()
    start = pd.Timestamp.now(tz="UTC").floor("D") - pd.Timedelta(days=days)
    params = {"start": start.to_pydatetime()}
    meta = {"start": str(start), "fetched_at": str(pd.Timestamp.now(tz="UTC")), "source_end": {}}

    with engine.connect() as conn:
        # generation: wide table, one parquet per zone to keep memory flat
        gen_cols = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='entsoe_raw' AND table_name='Zonal_Generation_Raw' "
                "ORDER BY ordinal_position"
            )
        ).scalars().all()
        tech_cols = [
            c for c in gen_cols
            if c not in GEN_META_COLUMNS and "download" not in c.lower() and "timestamp" not in c.lower()
        ]
        zones = conn.execute(
            text('SELECT DISTINCT zone FROM entsoe_raw."Zonal_Generation_Raw" WHERE time >= :start ORDER BY 1'),
            params,
        ).scalars().all()
        (DATA / "generation").mkdir(parents=True, exist_ok=True)
        select = ", ".join(f"CAST({q(c)} AS TEXT) AS {q(c)}" for c in tech_cols)
        for zone in zones:
            df = pd.read_sql(
                text(
                    f'SELECT time, {select} FROM entsoe_raw."Zonal_Generation_Raw" '
                    "WHERE zone = :zone AND time >= :start ORDER BY time"
                ),
                conn,
                params={**params, "zone": zone},
            )
            df.to_parquet(DATA / "generation" / f"{zone}.parquet", index=False)
            print(f"generation {zone}: {len(df)} rows")
        meta["source_end"]["generation"] = str(
            conn.execute(text('SELECT max(time) FROM entsoe_raw."Zonal_Generation_Raw"')).scalar()
        )

        df = pd.read_sql(
            text(
                'SELECT time, zone, CAST("Actual_Load" AS TEXT) AS value '
                'FROM entsoe_raw."Zonal_Demand_Raw" WHERE time >= :start ORDER BY zone, time'
            ),
            conn,
            params=params,
        )
        df.to_parquet(DATA / "demand.parquet", index=False)
        print(f"demand: {len(df)} rows")
        meta["source_end"]["demand"] = str(df["time"].max())

        df = pd.read_sql(
            text(
                'SELECT time, "From Zone" AS from_zone, "To Zone" AS to_zone, '
                'CAST("Physical Flow" AS TEXT) AS value '
                'FROM entsoe_raw."Cross_Border_Physical_Flows_Bidding_Zones_Raw" '
                "WHERE time >= :start ORDER BY 2, 3, time"
            ),
            conn,
            params=params,
        )
        df.to_parquet(DATA / "flows.parquet", index=False)
        print(f"flows: {len(df)} rows")
        meta["source_end"]["flows"] = str(df["time"].max())

        (DATA / "per_unit").mkdir(parents=True, exist_ok=True)
        tsos = conn.execute(
            text('SELECT DISTINCT "TSO" FROM cosema.per_unit_gen WHERE time >= :start ORDER BY 1'), params
        ).scalars().all()
        for tso in tsos:
            df = pd.read_sql(
                text(
                    'SELECT time, "ID" AS id, technology, "EIC" AS eic, '
                    'CAST("Generation [MW]" AS TEXT) AS value FROM cosema.per_unit_gen '
                    'WHERE "TSO" = :tso AND time >= :start ORDER BY 2, time'
                ),
                conn,
                params={**params, "tso": tso},
            )
            df.to_parquet(DATA / "per_unit" / f"{tso}.parquet", index=False)
            print(f"per_unit {tso}: {len(df)} rows")
        meta["source_end"]["per_unit"] = str(
            conn.execute(text("SELECT max(time) FROM cosema.per_unit_gen")).scalar()
        )

    (DATA / "meta.json").write_text(json.dumps(meta, indent=2))


# ------------------------------------------------------------------- analyze


def classify(values: pd.Series) -> pd.Series:
    """NULL / '' / non-numeric text / 0 / value, per row."""
    status = pd.Series("value", index=values.index, dtype=object)
    as_str = values.astype("string")
    numeric = pd.to_numeric(as_str, errors="coerce")
    status[numeric == 0] = "zero"
    status[numeric.isna()] = "invalid"
    status[(as_str.str.strip() == "").fillna(False).astype(bool)] = "empty"
    status[values.isna()] = "null_value"
    return status


def longest_run(mask: np.ndarray) -> int:
    if not mask.any():
        return 0
    d = np.diff(np.r_[0, mask.astype(np.int8), 0])
    return int((np.flatnonzero(d == -1) - np.flatnonzero(d == 1)).max())


def analyze_series(source, series, times, status, start, source_end, results, excluded=frozenset()):
    """times/status: one entry per DB row of this series (may contain duplicates).
    excluded: dates (crawler outage days) left out of the evaluation."""
    df = pd.DataFrame({"time": pd.to_datetime(times, utc=True), "status": status.to_numpy()})
    duplicates = int(df["time"].duplicated().sum())
    # keep the best row per timestamp (a valid value beats an empty one)
    rank = df["status"].map({"value": 0, "zero": 1}).fillna(2)
    df = df.assign(rank=rank).sort_values(["time", "rank"]).drop_duplicates("time")
    by_time = df.set_index("time")["status"]
    valid_times = by_time.index[by_time.isin(["value", "zero"])]

    row = {"source": source, "series": series, "rows": len(by_time), "duplicates": duplicates}
    if len(valid_times) < 2:
        row.update({"freq_min": None, "missing_pct": 100.0, "note": "keine/kaum gueltige Werte"})
        results["coverage"].append(row)
        return

    diffs = pd.Series(valid_times[1:] - valid_times[:-1])
    freq = diffs.value_counts().idxmax()
    # diffs that are neither the dominant step nor a multiple of it (= a gap)
    # point to a change of resolution within the period
    other = ((diffs % freq) != pd.Timedelta(0)).mean()

    first = valid_times[0]
    grid0 = first - ((first - start) // freq) * freq
    grid = pd.date_range(grid0, source_end, freq=freq)
    on_grid = by_time.reindex(grid)
    kinds = on_grid.fillna("no_row").to_numpy()
    # crawler outage days: neither expected nor missing; marking them (instead
    # of dropping them from the grid) also splits gaps at their borders
    excl = np.isin(grid.date, list(excluded)) if excluded else np.zeros(len(grid), bool)
    kinds[excl] = "excluded"
    missing = ~np.isin(kinds, ["value", "zero", "excluded"])
    # rows between grid points: real values there mean a resolution problem;
    # empty ones are filler (per_unit_gen stores hourly units on a 15-min index)
    off = by_time[~by_time.index.isin(grid)]
    off_grid = int(off.isin(["value", "zero"]).sum())
    off_grid_empty = int(len(off) - off_grid)

    d = np.diff(np.r_[0, missing.astype(np.int8), 0])
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    freq_h = freq / pd.Timedelta("1h")
    for s, e in zip(starts, ends):
        k = set(kinds[s:e])
        position = ("start" if s == 0 else "") + ("+end" if e == len(grid) else "")
        results["gaps"].append(
            {
                "source": source,
                "series": series,
                "gap_start": grid[s],
                "gap_end": grid[e - 1],
                "missing_steps": int(e - s),
                "duration_h": round((e - s) * freq_h, 2),
                "kind": k.pop() if len(k) == 1 else "mixed",
                "position": position.lstrip("+") or "inside",
            }
        )

    daily = pd.Series(missing[~excl], index=grid[~excl])
    daily = daily.groupby(daily.index.date).mean()
    for day, frac in daily[daily > 0].items():
        results["daily"].append({"source": source, "series": series, "date": day, "missing_frac": round(frac, 4)})
    results["series_days"].append((source, series, daily))

    zero_mask = kinds == "zero"
    counts = pd.Series(kinds).value_counts()
    row.update(
        {
            "freq_min": int(freq / pd.Timedelta("1min")),
            "first_value": valid_times[0],
            "last_value": valid_times[-1],
            "expected": int((~excl).sum()),
            "excluded_outage": int(excl.sum()),
            "valid": int((~missing & ~excl).sum()),
            "missing": int(missing.sum()),
            "missing_pct": round(100 * missing.sum() / max((~excl).sum(), 1), 2),
            "n_gaps": len(starts),
            "longest_gap_h": round((ends - starts).max() * freq_h, 2) if len(starts) else 0.0,
            "n_no_row": int(counts.get("no_row", 0)),
            "n_null": int(counts.get("null_value", 0)),
            "n_empty": int(counts.get("empty", 0)),
            "n_invalid": int(counts.get("invalid", 0)),
            "n_zero": int(zero_mask.sum()),
            "zero_run_max_h": round(longest_run(zero_mask) * freq_h, 2) if source in ZERO_RUN_SOURCES else None,
            "off_grid": off_grid,
            "off_grid_empty": off_grid_empty,
            "other_freq_share": round(float(other), 4),
        }
    )
    results["coverage"].append(row)


def collect(start, end, excluded):
    """One pass over all sources. excluded: {source: set of dates} to leave out."""
    results = {"gaps": [], "coverage": [], "daily": [], "series_days": []}
    no_days = frozenset()

    gen_excl = excluded.get("generation", no_days)
    for path in sorted((DATA / "generation").glob("*.parquet")):
        zone = path.stem
        df = pd.read_parquet(path)
        techs = [c for c in df.columns if c != "time"]
        status = {t: classify(df[t]) for t in techs}
        has_value = pd.DataFrame({t: s.isin(["value", "zero"]) for t, s in status.items()})
        all_zero = pd.DataFrame({t: s != "value" for t, s in status.items()}).all(axis=1)
        zone_status = pd.Series(np.where(has_value.any(axis=1), np.where(all_zero, "zero", "value"), "null_value"))
        analyze_series("generation", zone, df["time"], zone_status, start, end["generation"], results, gen_excl)
        for t in techs:
            if has_value[t].any():
                analyze_series("generation_type", f"{zone}|{t}", df["time"], status[t], start,
                               end["generation"], results, gen_excl)

    df = pd.read_parquet(DATA / "demand.parquet")
    for zone, g in df.groupby("zone"):
        analyze_series("demand", zone, g["time"], classify(g["value"]), start, end["demand"], results,
                       excluded.get("demand", no_days))

    df = pd.read_parquet(DATA / "flows.parquet")
    for (f, t), g in df.groupby(["from_zone", "to_zone"]):
        analyze_series("flows", f"{f}->{t}", g["time"], classify(g["value"]), start, end["flows"], results,
                       excluded.get("flows", no_days))

    # per_unit_gen only exists since the daily per-unit job went live -- count
    # gaps from the table's first value, not from the period start
    paths = sorted((DATA / "per_unit").glob("*.parquet"))
    pu_start = max(start, min(pd.read_parquet(p, columns=["time"])["time"].min() for p in paths)) if paths else start
    for path in paths:
        df = pd.read_parquet(path)
        for (uid, tech), g in df.groupby(["id", "technology"]):
            analyze_series("per_unit", f"{uid}|{tech}|{path.stem}", g["time"], classify(g["value"]), pu_start,
                           end["per_unit"], results, excluded.get("per_unit", no_days))
    return results


def analyze(keep_outages=False, outage_share=0.8):
    meta = json.loads((DATA / "meta.json").read_text())
    start = pd.Timestamp(meta["start"])
    end = {k: pd.Timestamp(v) for k, v in meta["source_end"].items()}

    # pass 1 finds the crawler outage days, pass 2 leaves them out
    results = collect(start, end, {})
    outages = find_outages(results, outage_share)
    if not keep_outages:
        excluded = {s: set(d["date"]) for s, d in outages[outages["outage"]].groupby("source")}
        results = collect(start, end, excluded)

    OUT.mkdir(exist_ok=True)
    pd.DataFrame(results["gaps"]).to_csv(OUT / "gaps.csv", index=False)
    coverage = pd.DataFrame(results["coverage"]).sort_values(["source", "missing_pct"], ascending=[True, False])
    coverage.to_csv(OUT / "coverage.csv", index=False)
    pd.DataFrame(results["daily"]).to_csv(OUT / "daily_missing.csv", index=False)
    outages.to_csv(OUT / "outages.csv", index=False)

    write_missing_series(coverage)
    print_summary(coverage, outages, keep_outages)


def find_outages(results, outage_share):
    # outages: share of a source's series missing at least half of a day.
    # generation_type left out -- it would only repeat the zone-level picture.
    rows = []
    for source in ["generation", "demand", "flows", "per_unit"]:
        days = [d for s, _, d in results["series_days"] if s == source]
        if not days:
            continue
        matrix = pd.concat(days, axis=1)
        share = (matrix >= 0.5).sum(axis=1) / matrix.notna().sum(axis=1)
        for day, sh in share.items():
            rows.append({"source": source, "date": day, "series": int(matrix.loc[day].notna().sum()),
                         "share_missing": round(sh, 3), "outage": sh >= outage_share})
    return pd.DataFrame(rows, columns=["source", "date", "series", "share_missing", "outage"])


def write_missing_series(coverage):
    with open(CO2MAP / "config.yaml") as f:
        config = yaml.safe_load(f)
    present = {s: set(coverage.loc[coverage["source"] == s, "series"]) for s in ["generation", "demand"]}
    flow_pairs = set(coverage.loc[coverage["source"] == "flows", "series"])
    rows = []
    for country in config["countries"]:
        for zone in zones_for_country(country):
            for source in ["generation", "demand"]:
                if zone not in present[source]:
                    rows.append({"source": source, "expected": zone, "country": country})
    for border in config["country_borders"]:
        a, b = border.split("-")
        pairs = {f"{x}->{y}" for x in zones_for_country(a) for y in zones_for_country(b)}
        pairs |= {f"{y}->{x}" for x in zones_for_country(a) for y in zones_for_country(b)}
        if not pairs & flow_pairs:
            rows.append({"source": "flows", "expected": border, "country": f"{a}/{b}"})
    pd.DataFrame(rows, columns=["source", "expected", "country"]).to_csv(OUT / "missing_series.csv", index=False)


def print_summary(coverage, outages, keep_outages):
    print()
    if not keep_outages:
        print("Crawler-Ausfalltage sind herausgerechnet (zaehlen weder als Soll noch als Luecke).\n")
    for source, g in coverage.groupby("source"):
        total = g["expected"].sum()
        print(f"=== {source}: {len(g)} Reihen, {g['missing'].sum():.0f}/{total:.0f} fehlend "
              f"({100 * g['missing'].sum() / max(total, 1):.2f} %), {g['n_gaps'].sum():.0f} Luecken")
        top = g[g["missing_pct"] > 0].head(8)
        for _, r in top.iterrows():
            print(f"    {r['series']:40s} {r['missing_pct']:6.2f} %  Luecken {r['n_gaps']:.0f}, "
                  f"laengste {r['longest_gap_h']} h")
        days = outages[(outages["source"] == source) & outages["outage"]]
        if len(days):
            label = "herausgerechnet" if not keep_outages else "erkannt, mitgezaehlt"
            print(f"    Ausfalltage ({label}): {', '.join(str(d) for d in days['date'])}")
    print(f"\nErgebnisse in {OUT}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--skip-fetch", action="store_true", help="nur aus ./data auswerten, keine DB-Abfrage")
    parser.add_argument("--keep-outages", action="store_true",
                        help="Crawler-Ausfalltage mitzaehlen statt herausrechnen")
    parser.add_argument("--outage-share", type=float, default=0.8,
                        help="Ausfalltag, wenn mind. dieser Anteil der Reihen einer Quelle >=50 %% des Tages fehlt")
    args = parser.parse_args()
    if not args.skip_fetch:
        fetch(args.days)
    analyze(args.keep_outages, args.outage_share)
