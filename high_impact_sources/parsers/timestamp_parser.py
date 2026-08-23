from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from dateparser import parse

def parse_timestamp(value: str | datetime) -> datetime:
    if isinstance(value, datetime): result = value
    else:
        try: result = parsedate_to_datetime(value)
        except (TypeError, ValueError): result = parse(value)
    if result is None: raise ValueError(f"Unparseable timestamp: {value!r}")
    return result.replace(tzinfo=result.tzinfo or timezone.utc).astimezone(timezone.utc)

def next_full_minute(value: datetime) -> datetime:
    value = parse_timestamp(value)
    return value.replace(second=0, microsecond=0) + __import__("datetime").timedelta(minutes=1)
