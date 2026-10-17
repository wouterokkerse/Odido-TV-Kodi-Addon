"""Odido guide dates use Amsterdam time, independently of the Kodi timezone."""
import datetime as dt

UTC = dt.timezone.utc
try:
    from zoneinfo import ZoneInfo
    AMSTERDAM = ZoneInfo('Europe/Amsterdam')
except (ImportError, KeyError):
    # Kodi installations do not all ship an IANA timezone database.
    AMSTERDAM = None


def last_sunday(year, month):
    last = dt.datetime(year, month, 31, tzinfo=UTC)
    return last - dt.timedelta(days=(last.weekday() + 1) % 7)


def local_time(timestamp=None):
    instant = dt.datetime.now(UTC) if timestamp is None else dt.datetime.fromtimestamp(timestamp, UTC)
    if AMSTERDAM is not None:
        return instant.astimezone(AMSTERDAM)
    # EU rules in effect since 1996; the addon only browses recent TV days.
    start = last_sunday(instant.year, 3).replace(hour=1)
    end = last_sunday(instant.year, 10).replace(hour=1)
    offset = dt.timedelta(hours=2 if start <= instant < end else 1)
    return instant.astimezone(dt.timezone(offset))


def midnight(date):
    naive = dt.datetime.combine(date, dt.time())
    if AMSTERDAM is not None:
        return naive.replace(tzinfo=AMSTERDAM)
    # At midnight the March transition has not happened yet; likewise October.
    summer = last_sunday(date.year, 3).date() < date <= last_sunday(date.year, 10).date()
    return naive.replace(tzinfo=dt.timezone(dt.timedelta(hours=2 if summer else 1)))


def day_bounds(day):
    # Avoid datetime.strptime's lazy _strptime import in Kodi's interpreter.
    if not isinstance(day, str) or len(day) != 8 or not day.isascii() or not day.isdigit():
        raise ValueError('Invalid guide date')
    date = dt.date(int(day[:4]), int(day[4:6]), int(day[6:]))
    start = midnight(date)
    end = midnight(date + dt.timedelta(days=1))
    # Match the reference's 00:00:00 through 23:59:59 Amsterdam query.
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000) - 1000
