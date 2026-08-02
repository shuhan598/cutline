"""Project timestamp normalization utilities."""

from datetime import datetime, timedelta, timezone


LOCAL_TIMEZONE = timezone(timedelta(hours=8))


def normalize_local_time(value: datetime) -> datetime:
    """Interpret naive project timestamps as UTC+08:00."""
    if value.utcoffset() is None:
        return value.replace(tzinfo=LOCAL_TIMEZONE)
    return value.astimezone(LOCAL_TIMEZONE)
