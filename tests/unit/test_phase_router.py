"""Tests for phase router."""

from datetime import datetime

import pytest

from powerhouse.core.enums import Phase
from powerhouse.core.phase_router import PhaseProfile, PhaseRouter


@pytest.mark.unit
class TestPhaseRouter:
    """Test phase resolution logic."""

    def test_premarket_phase(self):
        """Test premarket phase detection."""
        # 7 AM ET = 11 AM UTC (EDT is UTC-4)
        dt = datetime(2026, 7, 7, 11, 0, 0)
        phase = PhaseRouter.resolve_phase(dt)
        assert phase == Phase.PREMARKET

    def test_open_phase(self):
        """Test market open phase detection."""
        # 10 AM ET = 2 PM UTC
        dt = datetime(2026, 7, 7, 14, 0, 0)
        phase = PhaseRouter.resolve_phase(dt)
        assert phase == Phase.OPEN

    def test_midday_phase(self):
        """Test midday phase detection."""
        # 1 PM ET = 5 PM UTC
        dt = datetime(2026, 7, 7, 17, 0, 0)
        phase = PhaseRouter.resolve_phase(dt)
        assert phase == Phase.MIDDAY

    def test_power_hour_phase(self):
        """Test power hour phase detection."""
        # 3:30 PM ET = 7:30 PM UTC
        dt = datetime(2026, 7, 7, 19, 30, 0)
        phase = PhaseRouter.resolve_phase(dt)
        assert phase == Phase.POWER_HOUR

    def test_end_of_day_phase(self):
        """Test end-of-day phase detection."""
        # 4:30 PM ET = 8:30 PM UTC
        dt = datetime(2026, 7, 7, 20, 30, 0)
        phase = PhaseRouter.resolve_phase(dt)
        assert phase == Phase.END_OF_DAY

    def test_closed_phase(self):
        """Test market closed phase detection."""
        # 10 PM ET = 2 AM UTC (next day)
        dt = datetime(2026, 7, 8, 2, 0, 0)
        phase = PhaseRouter.resolve_phase(dt)
        assert phase == Phase.CLOSED

    def test_boundary_conditions(self):
        """Test phase boundaries."""
        # Exactly at premarket start (4 AM ET = 8 AM UTC)
        dt = datetime(2026, 7, 7, 8, 0, 0)
        assert PhaseRouter.resolve_phase(dt) == Phase.PREMARKET

        # Just before market open (9:29:59 AM ET = 1:29:59 PM UTC)
        dt = datetime(2026, 7, 7, 13, 29, 59)
        assert PhaseRouter.resolve_phase(dt) == Phase.PREMARKET

        # Exactly at market open (9:30 AM ET = 1:30 PM UTC)
        dt = datetime(2026, 7, 7, 13, 30, 0)
        assert PhaseRouter.resolve_phase(dt) == Phase.OPEN

        # Just before midday (11:59:59 AM ET = 3:59:59 PM UTC)
        dt = datetime(2026, 7, 7, 15, 59, 59)
        assert PhaseRouter.resolve_phase(dt) == Phase.OPEN

    def test_saturday_is_closed_even_during_market_hours(self):
        # 2026-07-11 is a Saturday; 10 AM ET = 2 PM UTC
        dt = datetime(2026, 7, 11, 14, 0, 0)
        assert PhaseRouter.resolve_phase(dt) == Phase.CLOSED

    def test_sunday_is_closed_even_during_market_hours(self):
        # 2026-07-12 is a Sunday; 10 AM ET = 2 PM UTC
        dt = datetime(2026, 7, 12, 14, 0, 0)
        assert PhaseRouter.resolve_phase(dt) == Phase.CLOSED

    def test_is_market_open_helper(self):
        weekday_open = datetime(2026, 7, 7, 14, 0, 0)
        weekend = datetime(2026, 7, 11, 14, 0, 0)
        assert PhaseRouter.is_market_open(weekday_open) is True
        assert PhaseRouter.is_market_open(weekend) is False

    def test_get_profile_returns_phase_profile(self):
        profile = PhaseRouter.get_profile(Phase.OPEN)
        assert isinstance(profile, PhaseProfile)
        assert profile.phase == Phase.OPEN
        closed_profile = PhaseRouter.get_profile(Phase.CLOSED)
        assert profile.scan_aggressiveness > closed_profile.scan_aggressiveness

    def test_profiles_differ_by_phase(self):
        open_profile = PhaseRouter.get_profile(Phase.OPEN)
        eod_profile = PhaseRouter.get_profile(Phase.END_OF_DAY)
        assert open_profile.max_position_count != eod_profile.max_position_count
