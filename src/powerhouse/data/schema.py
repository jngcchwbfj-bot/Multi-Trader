"""Normalized OHLCV row schema shared by ingestion and query helpers."""

from datetime import date as date_type

from pydantic import BaseModel, field_validator, model_validator

OHLCV_COLUMNS = ["symbol", "date", "open", "high", "low", "close", "volume"]


class OHLCVRow(BaseModel):
    """One normalized daily OHLCV bar for a single symbol."""

    symbol: str
    date: date_type
    open: float
    high: float
    low: float
    close: float
    volume: int

    @field_validator("symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()

    @model_validator(mode="after")
    def _check_high_low(self) -> "OHLCVRow":
        if self.high < self.low:
            raise ValueError(f"high ({self.high}) cannot be less than low ({self.low})")
        return self
