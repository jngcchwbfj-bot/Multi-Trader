"""DuckDB helpers for querying local curated Parquet OHLCV datasets."""

from pathlib import Path

import duckdb
import pandas as pd

from powerhouse.core.exceptions import ConfigError


def _glob(curated_dir: Path) -> str:
    return str(Path(curated_dir) / "*.parquet")


def available_symbols(curated_dir: Path) -> list[str]:
    """List symbols present in the curated Parquet dataset."""
    curated_dir = Path(curated_dir)
    files = sorted(curated_dir.glob("*.parquet"))
    return [f.stem.upper() for f in files]


def load_ohlcv(symbol: str, curated_dir: Path) -> pd.DataFrame:
    """Load all OHLCV bars for one symbol, sorted by date."""
    path = Path(curated_dir) / f"{symbol.upper()}.parquet"
    if not path.exists():
        raise ConfigError(f"No curated data for symbol {symbol!r} at {path}")
    con = duckdb.connect(database=":memory:")
    try:
        df = con.execute(
            "SELECT * FROM read_parquet(?) ORDER BY date", [str(path)]
        ).fetchdf()
    finally:
        con.close()
    return df


def load_universe(symbols: list[str], curated_dir: Path) -> pd.DataFrame:
    """Load OHLCV bars for multiple symbols into one combined frame."""
    curated_dir = Path(curated_dir)
    frames = []
    for symbol in symbols:
        path = curated_dir / f"{symbol.upper()}.parquet"
        if path.exists():
            frames.append(load_ohlcv(symbol, curated_dir))
    if not frames:
        return pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume"])
    return pd.concat(frames, ignore_index=True)


def query_sql(sql: str, curated_dir: Path) -> pd.DataFrame:
    """Run an arbitrary read-only SQL query against the curated dataset.

    The query may reference a virtual table `ohlcv` backed by every Parquet
    file in curated_dir, e.g. ``SELECT symbol, avg(close) FROM ohlcv GROUP BY symbol``.
    """
    con = duckdb.connect(database=":memory:")
    try:
        con.execute(f"CREATE VIEW ohlcv AS SELECT * FROM read_parquet('{_glob(curated_dir)}')")
        return con.execute(sql).fetchdf()
    finally:
        con.close()
