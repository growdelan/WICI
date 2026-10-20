"""Publication-day selection; dates are civil dates in Europe/Warsaw."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

WARSAW = ZoneInfo('Europe/Warsaw')


def civil_day(value):
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and len(value) == 10:
        return date.fromisoformat(value).isoformat()
    instant = datetime.fromisoformat(value) if isinstance(value, str) else value
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=WARSAW)
    return instant.astimezone(WARSAW).date().isoformat()


def publication_day(item, fallback):
    for key in ('source_published_at', 'source_published_date', 'source_updated_at'):
        if item.get(key):
            return civil_day(item[key]), key
    return civil_day(fallback), 'first_seen_at'
