"""Loads typed YAML configuration from the config/ directory."""

from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel

from powerhouse.core.exceptions import ConfigError

from .schema import (
    AppConfig,
    BacktestConfig,
    BrokerConfig,
    ReportingConfig,
    RiskConfig,
    RootConfig,
    ScannerConfig,
    StrategyConfig,
)

T = TypeVar("T", bound=BaseModel)

DEFAULT_CONFIG_DIR = Path("config")

_FILES: dict[str, type[BaseModel]] = {
    "app": AppConfig,
    "scanner": ScannerConfig,
    "strategy": StrategyConfig,
    "risk": RiskConfig,
    "reporting": ReportingConfig,
    "backtest": BacktestConfig,
    "broker": BrokerConfig,
}


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"Failed to parse YAML config {path}: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"Config file {path} must contain a mapping at the top level")
    return data


def load_section(name: str, config_dir: Path | str = DEFAULT_CONFIG_DIR) -> BaseModel:
    """Load and validate a single named config section (e.g. 'risk')."""
    if name not in _FILES:
        raise ConfigError(f"Unknown config section: {name}")
    config_dir = Path(config_dir)
    raw = _load_yaml(config_dir / f"{name}.yaml")
    model = _FILES[name]
    try:
        return model.model_validate(raw)
    except Exception as e:
        raise ConfigError(f"Invalid config in {name}.yaml: {e}") from e


def load_config(config_dir: Path | str = DEFAULT_CONFIG_DIR) -> RootConfig:
    """Load every config section into a single typed RootConfig."""
    sections = {name: load_section(name, config_dir) for name in _FILES}
    return RootConfig(**sections)
