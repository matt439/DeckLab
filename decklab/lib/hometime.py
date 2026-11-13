"""The household's time zone: config.json's optional "timezone" (an IANA name such as
"Australia/Sydney"; config.example.json carries it blank).

Most of Deck Lab dates things by this PC's own clock (date.today(), the nightly run at 03:30,
backup names, visit days), so the PC's time zone should be the household's. A minimal Linux
image often starts on UTC, so "timezone" says what the household's zone is:

- the Linux nightly timer (and the wake timer) runs at 03:30 in that zone (systemd's OnCalendar
  takes a zone after the time), whatever the PC's own zone;
- smoke and doctor warn when the PC's own offset differs from it (host_mismatch);
- the few dates that are always the household's (a receipt's arrival date, a game's date)
  are worked out in it (household_today).

Without "timezone" (missing or blank), everything follows this PC's own zone: the timer's
OnCalendar names no zone (so systemd uses the PC's), the smoke step and doctor have nothing to
compare, and household_today is the PC's local date (Matt, 2026-11-13; it was a fixed UTC+10
before). When the name is set but this PC has no data for it (Windows has no zone data of its
own unless Python's tzdata package is installed), only household_today falls back to the PC's
local date (datetime.astimezone() with no argument reads the PC's own offset, which needs no
tzdata): the timer still names the zone, so systemd needs the system's own zone data for it,
and smoke and doctor warn that the zone can't be compared.

Only the standard library is used (zoneinfo).
"""
import re
import sys
import time
from datetime import datetime, timezone

# An IANA name as systemd and zoneinfo take it: "UTC", "Australia/Sydney", "America/Argentina/Salta",
# "Etc/GMT+10". No spaces, quotes, % or "..", so it's safe in a unit file too.
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_+\-]*(?:/[A-Za-z0-9_+\-]+){0,3}")
HALF_YEAR = 182 * 24 * 3600


def valid_name(value):
    """Whether value has an IANA zone name's form (not whether this PC has its data)."""
    return isinstance(value, str) and len(value) <= 64 and NAME.fullmatch(value) is not None


def setting(settings=None):
    """(name, problem) for config.json's "timezone": (None, None) when it isn't set, (name, None)
    when it has a zone name's form, else (None, why)."""
    if settings is None:
        try:
            from decklab.lib import config
            settings = config.load()
        except (OSError, ValueError):
            return None, None
    value = (settings or {}).get("timezone")
    if value in (None, ""):
        return None, None
    if not valid_name(value):
        return None, ('config.json\'s "timezone" isn\'t a time zone name such as "Australia/Sydney" '
                      '(timedatectl list-timezones lists them on Linux)')
    return value, None


def configured(settings=None):
    """config.json's "timezone", when it's set and has a zone name's form, else None."""
    return setting(settings)[0]


def zone(name):
    """The ZoneInfo for name, or None when this PC has no data for it."""
    if not valid_name(name):
        return None
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:           # noqa: BLE001 - ZoneInfoNotFoundError, ValueError, a damaged tzdata file
        return None


def household_today(settings=None, now=None):
    """Today's date (YYYY-MM-DD) in the household's zone: config.json's "timezone" when this PC
    can load it, else this PC's own zone. now: an aware datetime, for tests."""
    try:
        found = zone(configured(settings))
    except Exception:           # noqa: BLE001 - a date must always come back
        found = None
    now = now or datetime.now(timezone.utc)
    if found is not None:
        return now.astimezone(found).date().isoformat()
    return _local(now).date().isoformat()


def _local(now):
    """now in this PC's own zone (its offset at that moment, from the OS: no tzdata needed)."""
    try:
        return now.astimezone()
    except (OverflowError, OSError, ValueError):     # a moment the OS can't convert
        return now


def _offset_text(seconds):
    sign = "-" if seconds < 0 else "+"
    seconds = abs(int(seconds))
    return f"UTC{sign}{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"


def fix_hint(name, platform=None):
    """How to set this PC's zone to name, as this system does it."""
    platform = sys.platform if platform is None else platform
    if platform.startswith("linux"):
        return f"sudo timedatectl set-timezone {name}"
    if platform == "win32":
        return "set the time zone in Windows' Settings > Time & language > Date & time"
    return "set this computer's time zone in its system settings"


def host_mismatch(name, now=None, localtime=time.localtime, platform=None):
    """Why this PC's own clock doesn't keep name's time, or None when it does: its UTC offset is
    compared with the zone's now and half a year from now (so a zone with another daylight
    saving rule differs too). Raises LookupError when this PC has no data for name."""
    found = zone(name)
    if found is None:
        raise LookupError(name)
    now = time.time() if now is None else now
    for moment in (now, now + HALF_YEAR):
        host = localtime(moment).tm_gmtoff
        want = datetime.fromtimestamp(moment, found).utcoffset().total_seconds()
        if host is None or int(host) != int(want):
            day = datetime.fromtimestamp(moment, found).date().isoformat()
            return (f"This PC keeps {_offset_text(host or 0)} time on {day}, but config.json's \"timezone\" is "
                    f"{name} ({_offset_text(want)}), so the dates Deck Lab writes follow the wrong clock: "
                    f"{fix_hint(name, platform)}, or correct \"timezone\" in config.json.")
    return None
