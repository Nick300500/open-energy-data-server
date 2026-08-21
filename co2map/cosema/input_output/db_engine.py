"""
Shared Postgres engine builder for module-level/input-loading DB lookups
outside DBClient (gen-type mapping tables, MaStR, shapefiles, demand-
regionalization factors -- all migrated into the `cosema_inputs` schema, see
the standalone "Transfer data to database" scripts, kept intentionally
outside this repo). Reads the same DB_HOST/PORT/NAME/USER/PASSWORD env vars
DBClient's callers already use (see compose.yml's co2map service).
"""
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

INPUTS_SCHEMA = os.environ.get("COSEMA_INPUTS_SCHEMA", "cosema_inputs")


def get_engine():
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    dbname = os.environ.get("DB_NAME", "opendata")
    user = os.environ.get("DB_USER", "postgres")
    password = os.environ.get("DB_PASSWORD", "postgres")
    return create_engine(
        f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}"
    )
