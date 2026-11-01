"""Pure previews of the nightly job's systemd user service and timer, and of the root-installed
system timer that wakes the PC for it (wake_units).

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
WAKE_SERVICE = "decklab-wake.service"
WAKE_TIMER = "decklab-wake.timer"
SYSTEM_DIR = "/etc/systemd/system"


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
Nice=10
IOSchedulingClass=idle
UMask=0077
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


def wake_time(at=DEFAULT_AT):
    """The minute before at (HH:MM), wrapping past midnight: when the wake timer fires."""
    hours, minutes = map(int, _time(at).split(":"))
    total = (hours * 60 + minutes - 1) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def wake_units(at=DEFAULT_AT):
    """The system timer that wakes a sleeping PC a minute before the nightly run at `at`, and
    the do-nothing service it starts: {filename: unit text}, without reading or writing.

    A user timer can't wake the PC (WakeSystem= needs CAP_WAKE_ALARM, which only the system
    manager has), so these are installed once by root in SYSTEM_DIR. Once the PC is awake, the
    user's nightly timer fires on time and the nightly run holds the PC awake while it works.
    """
    wake = wake_time(at)
    return {
        WAKE_SERVICE: """[Unit]
Description=Wake the PC for Deck Lab's nightly maintenance (does nothing itself)

[Service]
Type=oneshot
ExecStart=/bin/true
""",
        WAKE_TIMER: f"""[Unit]
Description=Wake the PC a minute before Deck Lab's nightly maintenance

[Timer]
OnCalendar=*-*-* {wake}:00
WakeSystem=true
Persistent=false
AccuracySec=1s
Unit={WAKE_SERVICE}

[Install]
WantedBy=timers.target
""",
    }


def wake_install_commands(at=DEFAULT_AT):
    """The shell commands (as lines) that install wake_units as root: each unit written with
    sudo tee from a quoted here-document, then the timer enabled. Nothing is run here."""
    units = wake_units(at)
    lines = []
    for name in (WAKE_SERVICE, WAKE_TIMER):
        lines.append(f"sudo tee {SYSTEM_DIR}/{name} >/dev/null <<'EOF'")
        lines.extend(units[name].rstrip("\n").split("\n"))      # fixed text: no line reads EOF
        lines.append("EOF")
    lines += ["sudo systemctl daemon-reload", f"sudo systemctl enable --now {WAKE_TIMER}"]
    return lines


def wake_remove_commands():
    """The shell commands (as lines) that take the wake timer away again."""
    return [f"sudo systemctl disable --now {WAKE_TIMER}",
            f"sudo rm {SYSTEM_DIR}/{WAKE_TIMER} {SYSTEM_DIR}/{WAKE_SERVICE}",
            "sudo systemctl daemon-reload"]
