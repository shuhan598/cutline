"""统一项目时间戳的时区和本地时间语义。"""

from datetime import datetime, timedelta, timezone


LOCAL_TIMEZONE = timezone(timedelta(hours=8))


def normalize_local_time(value: datetime) -> datetime:
    """把不带时区的项目时间解释为 UTC+08:00。"""
    if value.utcoffset() is None:
        return value.replace(tzinfo=LOCAL_TIMEZONE)
    return value.astimezone(LOCAL_TIMEZONE)
