"""Fixture ingestion: normalize raw CSV OHLCV data into curated Parquet files."""

import csv
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from powerhouse.core.exceptions import ConfigError

from .schema import OHLCVRow

REQUIRED_CSV_COLUMNS = {"date", "open", "high", "low", "close", "volume"}


def _symbol_from_filename(path: Path) -> str:
    return path.stem.upper()


def read_csv_rows(csv_path: Path, symbol: str | None = None) -> list[OHLCVRow]:
    """Read and validate one raw OHLCV CSV file into normalized rows."""
    symbol = symbol or _symbol_from_filename(csv_path)
    rows: list[OHLCVRow] = []
    with csv_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        missing = REQUIRED_CSV_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ConfigError(f"{csv_path} is missing required columns: {sorted(missing)}")
        for raw in reader:
            rows.append(
                OHLCVRow(
                    symbol=symbol,
                    date=raw["date"],
                    open=float(raw["open"]),
                    high=float(raw["high"]),
                    low=float(raw["low"]),
                    close=float(raw["close"]),
                    volume=int(float(raw["volume"])),
                )
            )
    rows.sort(key=lambda r: r.date)
    return rows


def write_parquet(rows: list[OHLCVRow], out_path: Path) -> Path:
    """Write normalized OHLCV rows to a Parquet file."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "symbol": [r.symbol for r in rows],
            "date": [r.date for r in rows],
            "open": [r.open for r in rows],
            "high": [r.high for r in rows],
            "low": [r.low for r in rows],
            "close": [r.close for r in rows],
            "volume": [r.volume for r in rows],
        },
        schema=pa.schema(
            [
                ("symbol", pa.string()),
                ("date", pa.date32()),
                ("open", pa.float64()),
                ("high", pa.float64()),
                ("low", pa.float64()),
                ("close", pa.float64()),
                ("volume", pa.int64()),
            ]
        ),
    )
    pq.write_table(table, out_path)
    return out_path


def ingest_csv_to_parquet(csv_path: Path, out_dir: Path, symbol: str | None = None) -> Path:
    """Ingest a single raw CSV file into a curated Parquet file."""
    csv_path = Path(csv_path)
    out_dir = Path(out_dir)
    rows = read_csv_rows(csv_path, symbol=symbol)
    symbol = symbol or _symbol_from_filename(csv_path)
    return write_parquet(rows, out_dir / f"{symbol}.parquet")


def ingest_fixtures(raw_dir: Path, curated_dir: Path) -> list[Path]:
    """Ingest every CSV under raw_dir into curated_dir as Parquet.

    Returns the list of Parquet files written.
    """
    raw_dir = Path(raw_dir)
    curated_dir = Path(curated_dir)
    if not raw_dir.exists():
        raise ConfigError(f"Raw data directory does not exist: {raw_dir}")

    written: list[Path] = []
    for csv_path in sorted(raw_dir.glob("*.csv")):
        written.append(ingest_csv_to_parquet(csv_path, curated_dir))
    return written
