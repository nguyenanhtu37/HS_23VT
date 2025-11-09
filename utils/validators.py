import re
TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")  # hh:mm 00..23:00..59
def is_valid_time(s: str) -> bool:
    return bool(TIME_RE.match((s or "").strip()))
def to_int(s: str, default=None):
    try:
        return int(s)
    except:
        return default