"""Market phase resolution from datetime."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

from .enums import Phase

# Eastern Time timezone
ET = ZoneInfo("America/New_York")


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
        - All other times: closed

        Args:
            dt: datetime (if naive, assumed UTC; if aware, converted to ET)

        Returns:
            Phase enum value
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))

        et_dt = dt.astimezone(ET)
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
