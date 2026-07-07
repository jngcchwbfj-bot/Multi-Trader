"""Local data layer: fixture ingestion, Parquet storage, DuckDB queries."""

from .ingest import ingest_csv_to_parquet, ingest_fixtures, read_csv_rows
from .query import available_symbols, load_ohlcv, load_universe, query_sql
from .schema import OHLCVRow

__all__ = [
    "ingest_csv_to_parquet",
    "ingest_fixtures",
    "read_csv_rows",
    "available_symbols",
    "load_ohlcv",
    "load_universe",
    "query_sql",
    "OHLCVRow",
]
