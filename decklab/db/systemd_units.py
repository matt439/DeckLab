"""Pure previews of the nightly job's systemd user service and timer.

These functions neither inspect the host nor install anything. Paths describe the target
POSIX machine explicitly, even when the preview is made on Windows. Unit syntax follows
systemd.service(5), systemd.exec(5), systemd.syntax(7) and systemd.timer(5). WorkingDirectory
has a raw path parser, whereas ExecStart splits and unquotes command arguments.
"""
import re
import unicodedata
from pathlib import PurePosixPath

SERVICE = "decklab-nightly.service"
TIMER = "decklab-nightly.timer"
DEFAULT_AT = "03:30"


def _path(value, name, executable=False):
    if not isinstance(value, (str, PurePosixPath)):
        raise ValueError(f"{name} must be an absolute POSIX path.")
    text = str(value)
    if (not text.startswith("/") or text.startswith("//") or text != text.strip()
            or ".." in text.split("/")
            or any(unicodedata.category(c) == "Cc" for c in text)):
        raise ValueError(f"{name} must be an absolute POSIX path without controls or '..' components.")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"{name} must be valid UTF-8.") from None
    if executable:
        # systemd's executable-path validation rejects these even after C unquoting.
        if text.endswith("/") or any(c in text for c in "\\\"'"):
            raise ValueError(f"{name} must name an executable without quotes or backslashes.")
    elif text.endswith("\\"):
        # A raw directive ending in a backslash continues onto the next unit line.
        raise ValueError(f"{name} cannot end in a backslash.")
    return text


def _time(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{2}:[0-9]{2}", value):
        raise ValueError("--at must be a local time in HH:MM form.")
    hours, minutes = map(int, value.split(":"))
    if hours > 23 or minutes > 59:
        raise ValueError("--at must be a local time in HH:MM form.")
    return value


def nightly_units(python, workdir, at=DEFAULT_AT):
    """Return two fixed filenames mapped to complete unit text, without reading or writing.

    The ':' command prefix disables environment expansion, including dollar signs in the
    executable name. Percent specifiers are escaped in both path directives. No shell is
    involved. Timer activation cannot start this same service while it is already active;
    this does not serialize separate direct invocations of the nightly command.
    """
    program = _path(python, "--python", executable=True).replace("%", "%%")
    directory = _path(workdir, "--workdir").replace("%", "%%")
    at = _time(at)
    return {
        SERVICE: f"""[Unit]
Description=Deck Lab nightly maintenance

[Service]
Type=oneshot
WorkingDirectory={directory}
ExecStart=":{program}" -m decklab.db nightly
TimeoutStartSec=2h
Restart=no
RemainAfterExit=no
""",
        TIMER: f"""[Unit]
Description=Deck Lab nightly maintenance schedule

[Timer]
OnCalendar=*-*-* {at}:00
Persistent=true
Unit={SERVICE}

[Install]
WantedBy=timers.target
""",
    }
