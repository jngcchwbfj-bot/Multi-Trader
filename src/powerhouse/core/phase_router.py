"""Market phase resolution from datetime, with US/Eastern assumptions."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from .enums import Phase

# Eastern Time timezone
ET = ZoneInfo("America/New_York")

SATURDAY = 5
SUNDAY = 6


class PhaseProfile(BaseModel):
    """Per-phase tuning knobs used by the scanner/strategy specialists."""

    phase: Phase
    scan_aggressiveness: float  # 0.0 (conservative) to 1.0 (aggressive)
    max_position_count: int
    risk_multiplier: float  # multiplies the default per-trade risk %
    require_premarket_analysis: bool = False


_PHASE_PROFILES: dict[Phase, PhaseProfile] = {
    Phase.PREMARKET: PhaseProfile(
        phase=Phase.PREMARKET,
        scan_aggressiveness=0.3,
        max_position_count=2,
        risk_multiplier=0.5,
        require_premarket_analysis=True,
    ),
    Phase.OPEN: PhaseProfile(
        phase=Phase.OPEN,
        scan_aggressiveness=0.9,
        max_position_count=5,
        risk_multiplier=1.0,
    ),
    Phase.MIDDAY: PhaseProfile(
        phase=Phase.MIDDAY,
        scan_aggressiveness=0.5,
        max_position_count=3,
        risk_multiplier=0.75,
    ),
    Phase.POWER_HOUR: PhaseProfile(
        phase=Phase.POWER_HOUR,
        scan_aggressiveness=0.7,
        max_position_count=3,
        risk_multiplier=0.75,
    ),
    Phase.END_OF_DAY: PhaseProfile(
        phase=Phase.END_OF_DAY,
        scan_aggressiveness=0.2,
        max_position_count=0,
        risk_multiplier=0.0,
    ),
    Phase.CLOSED: PhaseProfile(
        phase=Phase.CLOSED,
        scan_aggressiveness=0.0,
        max_position_count=0,
        risk_multiplier=0.0,
    ),
}


class PhaseRouter:
    """Resolves market phase from datetime with Eastern Time assumptions."""

    @staticmethod
    def resolve_phase(dt: datetime) -> Phase:
        """
        Resolve market phase for a given datetime.

        Assumes Eastern Time business hours:
        - 4:00 AM - 9:30 AM ET: premarket
        - 9:30 AM - 12:00 PM ET: open
        - 12:00 PM - 3:00 PM ET: midday
        - 3:00 PM - 4:00 PM ET: power_hour
        - 4:00 PM - 5:00 PM ET: end_of_day
        - All other times, and all weekends: closed

        Args:
            dt: datetime (if naive, assumed UTC; if aware, converted to ET)

        Returns:
            Phase enum value
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))

        et_dt = dt.astimezone(ET)

        if et_dt.weekday() in (SATURDAY, SUNDAY):
            return Phase.CLOSED

        current_time = et_dt.time()

        if time(4, 0) <= current_time < time(9, 30):
            return Phase.PREMARKET
        elif time(9, 30) <= current_time < time(12, 0):
            return Phase.OPEN
        elif time(12, 0) <= current_time < time(15, 0):
            return Phase.MIDDAY
        elif time(15, 0) <= current_time < time(16, 0):
            return Phase.POWER_HOUR
        elif time(16, 0) <= current_time < time(17, 0):
            return Phase.END_OF_DAY
        else:
            return Phase.CLOSED

    @staticmethod
    def is_market_open(dt: datetime) -> bool:
        """True if the market is in an active trading phase (not closed)."""
        return PhaseRouter.resolve_phase(dt) != Phase.CLOSED

    @staticmethod
    def get_profile(phase: Phase) -> PhaseProfile:
        """Return the tuning profile for a given market phase."""
        return _PHASE_PROFILES[phase]
