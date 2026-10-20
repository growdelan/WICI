"""Display status derived only from explicit publisher warning validity."""
from datetime import datetime


def warning_status(event: dict, now: datetime) -> str:
    if event['warning_status']=='cancelled':
        return 'cancelled'
    start=datetime.fromisoformat(event['valid_from']) if event.get('valid_from') else None
    end=datetime.fromisoformat(event['valid_until']) if event.get('valid_until') else None
    if end and now>=end:
        return 'expired'
    if start and now<start:
        return 'upcoming'
    return 'active' if start and end else 'unknown'
