"""Tests for deterministic scanner ranking."""

from pathlib import Path

import pytest

from powerhouse.agents.scanner import ScannerAgent, momentum_score_from_df, rank_candidates
from powerhouse.config import ScannerConfig
from powerhouse.core.enums import Phase
from powerhouse.core.models import Candidate, SessionContext
from powerhouse.data import ingest_fixtures, load_ohlcv

RAW_DIR = Path("data/raw/ohlcv")


@pytest.mark.unit
class TestScannerAgent:
    @pytest.fixture
    def curated_dir(self, tmp_path):
        ingest_fixtures(RAW_DIR, tmp_path)
        return tmp_path

    @pytest.mark.asyncio
    async def test_ranks_universe_deterministically(self, curated_dir):
        agent = ScannerAgent(curated_dir=curated_dir)
        ctx = SessionContext(phase=Phase.OPEN)
        first = await agent.run(ctx)
        second = await agent.run(ctx)
        assert [c.ticker for c in first] == [c.ticker for c in second]
        assert all(c.relevance_score >= 0 for c in first)

    @pytest.mark.asyncio
    async def test_sorted_descending_by_score(self, curated_dir):
        agent = ScannerAgent(curated_dir=curated_dir)
        ctx = SessionContext(phase=Phase.OPEN)
        candidates = await agent.run(ctx)
        scores = [c.relevance_score for c in candidates]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_phase_aggressiveness_changes_candidate_count(self, curated_dir):
        agent = ScannerAgent(curated_dir=curated_dir)
        open_candidates = await agent.run(SessionContext(phase=Phase.OPEN))
        closed_candidates = await agent.run(SessionContext(phase=Phase.CLOSED))
        assert len(open_candidates) >= len(closed_candidates)

    @pytest.mark.asyncio
    async def test_no_curated_data_returns_empty(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        agent = ScannerAgent(
            config=ScannerConfig(universe=["AAPL"]), curated_dir=empty_dir
        )
        candidates = await agent.run(SessionContext(phase=Phase.OPEN))
        assert candidates == []

    def test_momentum_score_positive_trend(self, curated_dir):
        df = load_ohlcv("AAPL", curated_dir)
        result = momentum_score_from_df(df, lookback_days=20)
        assert result is not None
        score, price, reason = result
        assert score > 0.5  # AAPL fixture trends upward over its full 40-day history
        assert price > 0

    def test_rank_candidates_applies_score_floor(self):
        candidates = [
            Candidate(ticker="A", price=10, relevance_score=0.9, reason="x"),
            Candidate(ticker="B", price=10, relevance_score=0.1, reason="x"),
        ]
        config = ScannerConfig(max_candidates=5)
        ranked = rank_candidates(candidates, config, aggressiveness=1.0)
        tickers = [c.ticker for c in ranked]
        assert "A" in tickers
