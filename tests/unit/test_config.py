"""Tests for typed YAML config loading."""

from pathlib import Path

import pytest

from powerhouse.config import RiskConfig, ScannerConfig, load_config, load_section
from powerhouse.core.exceptions import ConfigError


@pytest.mark.unit
class TestConfigLoading:
    def test_load_config_from_repo_config_dir(self):
        cfg = load_config("config")
        assert cfg.app.timezone == "America/New_York"
        assert cfg.risk.max_daily_loss_pct == 1.0
        assert "AAPL" in cfg.scanner.universe

    def test_load_section(self):
        risk = load_section("risk", "config")
        assert isinstance(risk, RiskConfig)
        assert risk.max_per_trade_risk_pct == 0.5

    def test_missing_dir_uses_defaults(self, tmp_path):
        cfg = load_config(tmp_path)
        assert cfg.scanner == ScannerConfig()

    def test_unknown_section_raises(self):
        with pytest.raises(ConfigError):
            load_section("nope", "config")

    def test_invalid_yaml_raises(self, tmp_path: Path):
        bad = tmp_path / "risk.yaml"
        bad.write_text("- not\n- a\n- mapping\n")
        with pytest.raises(ConfigError):
            load_section("risk", tmp_path)
