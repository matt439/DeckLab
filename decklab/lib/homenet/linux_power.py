"""Linux's Sleep and Wake lines for homenet status (wake-on-request on a Linux server PC).

Windows' status reads its sleep and wake facts with one PowerShell call (gather.py) and judges
them in checks.py. On Linux the facts come from files and a few short, unprivileged commands,
gathered by gather() (every reader injectable, so the tests are fixtures on any OS), and judged
by the pure check_sleep_linux and check_wake_linux. status_lines(settings) does both:

- Sleep: what suspends this PC when idle. A headless Linux PC never suspends by itself; logind's
  IdleAction (logind.conf and its logind.conf.d drop-ins) is what does it, unless suspend.target
  is masked. With "wake" in config.json, suspending is the plan; without it, it's warned about.
  With "wake", also whether Deck Lab may hold the PC awake (a short systemd-inhibit trial, as
  lib/keepawake.py holds it: polkit may refuse a user service with no session).
- Wake (only with "wake"): the kernel offers suspend to RAM, and which kind (/sys/power/mem_sleep:
  deep is S3; some network adapters can't wake from s2idle); the default route's adapter is wired
  and wakes on a magic packet (ethtool's Wake-on when it can be read, which often needs root, else
  its device's power/wakeup); the root timer that wakes the PC for the nightly run
  (decklab-wake.timer, db/schedule.py); and the wake gate answering (gather.probe_gate).

A desktop's own power settings (GNOME's automatic suspend, say) aren't read.
"""
import getpass
import os
import shutil
import subprocess

from .common import OK, WARN, line

POWER_STATE = "/sys/power/state"
MEM_SLEEP = "/sys/power/mem_sleep"
ROUTE = "/proc/net/route"
# logind.conf: the first of these that exists, then the drop-ins of every one of these folders,
# in file-name order (a name in a later folder replaces the same name in an earlier one).
LOGIND_MAIN = ("/etc/systemd/logind.conf", "/run/systemd/logind.conf", "/usr/local/lib/systemd/logind.conf",
               "/usr/lib/systemd/logind.conf")
LOGIND_DROPINS = ("/usr/lib/systemd/logind.conf.d", "/usr/local/lib/systemd/logind.conf.d",
                  "/run/systemd/logind.conf.d", "/etc/systemd/logind.conf.d")
SUSPEND_ACTIONS = ("suspend", "hibernate", "hybrid-sleep", "suspend-then-hibernate", "sleep")
DEFAULT_IDLE_ACTION, DEFAULT_IDLE_SEC = "ignore", "30min"
WAKE_TIMER = "decklab-wake.timer"
RUN_TIMEOUT = 5                     # seconds for each command

LOGIND_FIX = ("As root, write /etc/systemd/logind.conf.d/decklab.conf with the lines [Login], IdleAction=suspend "
              "and IdleActionSec=10min, then restart the PC. logind counts an open SSH or terminal session that "
              "isn't idle as use, so log out of them.")
WAKE_TIMER_FIX = "python -m decklab.db schedule wake-timer prints the commands that install it."


def wol_fix(interface):
    adapter = interface or "<adapter>"
    return ("Turn on wake-on-LAN in the BIOS/UEFI, then keep it on at every boot: with netplan (Ubuntu Server), "
            "a file of its own such as /etc/netplan/60-wake-on-lan.yaml matching the adapter by MAC address, "
            f"with set-name: {adapter} and wakeonlan: true, "
            "then sudo netplan generate (SELF-HOSTING.md, step 12); with NetworkManager, sudo nmcli connection "
            "modify <connection> 802-3-ethernet.wake-on-lan magic (nmcli connection show lists them); with "
            "systemd-networkd alone, a .link file with WakeOnLan=magic. "
            f"Check with sudo ethtool {adapter}.")


def polkit_fix(user):
    return ("As root, write /etc/polkit-1/rules.d/50-decklab-inhibit.rules holding: polkit.addRule(function(a, s) "
            "{ if ((a.id == \"org.freedesktop.login1.inhibit-block-sleep\" || a.id == "
            "\"org.freedesktop.login1.inhibit-block-idle\") && s.user == \"" + (user or "<user>") + "\") "
            "return polkit.Result.YES; });")


# ------------------------------------------------------------------ parsing

def parse_logind(texts):
    """{"IdleAction", "IdleActionSec"} from logind.conf texts in the order they apply (later
    wins), only the [Login] section's; a key no text sets is missing."""
    found = {}
    for text in texts:
        section = None
        for raw in (text or "").splitlines():
            stripped = raw.strip()
            if not stripped or stripped[0] in "#;":
                continue
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped[1:-1].strip()
                continue
            key, sep, value = stripped.partition("=")
            if sep and section == "Login" and key.strip() in ("IdleAction", "IdleActionSec"):
                found[key.strip()] = value.strip()
    return found


def selected_mem_sleep(text):
    """(the selected mode, every mode offered) from /sys/power/mem_sleep ("s2idle [deep]")."""
    modes, selected = [], None
    for word in (text or "").split():
        if word.startswith("[") and word.endswith("]"):
            word = word[1:-1]
            selected = word
        modes.append(word)
    return selected, modes


def default_route_interface(text):
    """The interface of /proc/net/route's default route (the lowest metric one that's up), or None."""
    best = None
    for raw in (text or "").splitlines()[1:]:
        fields = raw.split()
        if len(fields) < 8 or fields[1] != "00000000" or fields[7] != "00000000":
            continue
        try:
            flags, metric = int(fields[3], 16), int(fields[6])
        except ValueError:
            continue
        if flags & 1 and (best is None or metric < best[0]):
            best = (metric, fields[0])
    return best[1] if best else None


def parse_ethtool(out, err=""):
    """{"supports", "wake_on", "error"} from `ethtool <adapter>`: the Wake-on letters (g is a
    magic packet, d is off), or None for one it didn't print (it needs root to read them)."""
    supports = wake_on = None
    for raw in (out or "").splitlines():
        key, sep, value = raw.strip().partition(":")
        if not sep:
            continue
        if key.strip() == "Supports Wake-on":
            supports = value.strip()
        elif key.strip() == "Wake-on":
            wake_on = value.strip()
    error = None
    if wake_on is None:
        error = next((t.strip() for t in ((err or "") + "\n" + (out or "")).splitlines()
                      if "wake-on" in t.lower() and ("cannot" in t.lower() or "not permitted" in t.lower())),
                     None) or "it didn't say (reading Wake-on usually needs root)"
    return {"supports": supports, "wake_on": wake_on, "error": error}


def parse_show(out):
    found = {}
    for raw in (out or "").splitlines():
        key, sep, value = raw.partition("=")
        if sep:
            found[key] = value
    return found


# ------------------------------------------------------------------ gathering

def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read(65536)
    except OSError:
        return None


def _listdir(path):
    try:
        return os.listdir(path)
    except OSError:
        return []


def _run(args, timeout=RUN_TIMEOUT):
    """(exit code, stdout, stderr); 127 when the program isn't there, 124 when it took too long."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL, errors="replace")
    except FileNotFoundError:
        return 127, "", f"{args[0]} isn't installed"
    except subprocess.TimeoutExpired:
        return 124, "", f"{args[0]} didn't answer within {timeout} seconds"
    except OSError as e:
        return 126, "", str(e)
    return done.returncode, done.stdout, done.stderr


def logind_settings(read=_read, listdir=_listdir):
    """{"IdleAction", "IdleActionSec", "files"}: logind's idle settings as its files set them
    (the defaults when none does), and the files read."""
    texts, files = [], []
    for path in LOGIND_MAIN:
        text = read(path)
        if text is not None:
            texts.append(text)
            files.append(path)
            break
    dropins = {}
    for folder in LOGIND_DROPINS:
        for name in listdir(folder):
            if name.endswith(".conf"):
                dropins[name] = folder + "/" + name
    for name in sorted(dropins):
        text = read(dropins[name])
        if text is not None:
            texts.append(text)
            files.append(dropins[name])
    found = parse_logind(texts)
    return {"IdleAction": found.get("IdleAction") or DEFAULT_IDLE_ACTION,
            "IdleActionSec": found.get("IdleActionSec") or DEFAULT_IDLE_SEC, "files": files}


def _first_line(*texts):
    for text in texts:
        for raw in (text or "").splitlines():
            if raw.strip():
                return raw.strip()
    return None


def gather(wake=None, *, read=_read, listdir=_listdir, exists=os.path.exists, which=shutil.which, run=_run,
           probe=None, user=None):
    """The facts status_lines judges. wake: keepawake.wake_settings' answer (None: no "wake"
    block, so only the Sleep facts are read). Nothing here needs root or changes anything (the
    inhibit trial holds an inhibitor for as long as `true` runs)."""
    facts = {"power_state": read(POWER_STATE), "mem_sleep": read(MEM_SLEEP),
             "logind": logind_settings(read, listdir), "suspend_target": None}
    if which("systemctl"):
        code, out, _ = run(["systemctl", "is-enabled", "suspend.target"])
        facts["suspend_target"] = (out or "").strip() or None
    tool = which("systemd-inhibit")
    facts["inhibit_tool"] = tool
    if wake is None:
        return facts
    if tool:
        code, out, err = run([tool, "--what=sleep:idle", "--who=Deck Lab",
                              "--why=Checking that Deck Lab may hold the PC awake", "--mode=block", "true"])
        facts["inhibit"] = {"ok": code == 0, "error": None if code == 0 else
                            (_first_line(err, out) or f"exit code {code}")}
        try:
            facts["user"] = user or getpass.getuser()
        except (OSError, KeyError, ImportError):
            facts["user"] = None
    interface = default_route_interface(read(ROUTE))
    facts["interface"] = interface
    if interface:
        base = f"/sys/class/net/{interface}"
        facts["wireless"] = bool(exists(base + "/wireless") or exists(base + "/phy80211"))
        wakeup = read(base + "/device/power/wakeup")
        facts["nic_wakeup"] = wakeup.strip() if wakeup is not None else None
        ethtool = which("ethtool")
        if ethtool:
            code, out, err = run([ethtool, interface])
            facts["ethtool"] = parse_ethtool(out, err)
    if which("systemctl"):
        code, out, _ = run(["systemctl", "show", WAKE_TIMER, "--no-pager", "-p", "LoadState,ActiveState"])
        facts["wake_timer"] = parse_show(out) if code == 0 else None
    gate = (wake or {}).get("gate")
    if gate:
        if probe is None:
            from .gather import probe_gate as probe
        facts["gate"] = probe(gate)
    return facts


# ------------------------------------------------------------------ judging

def check_sleep_linux(facts, wake=False):
    """The Sleep lines. wake: config.json has "wake", so suspending when idle is the plan."""
    area = "Sleep"
    logind = facts.get("logind") or {}
    action = str(logind.get("IdleAction") or DEFAULT_IDLE_ACTION).strip().lower()
    after = logind.get("IdleActionSec") or DEFAULT_IDLE_SEC
    masked = str(facts.get("suspend_target") or "").startswith("masked")
    suspends = action in SUSPEND_ACTIONS and not masked
    where = (logind.get("files") or ["/etc/systemd/logind.conf"])[-1]
    out = []
    if wake:
        if masked:
            out.append(line(WARN, area, "Wake-on-request is set up but suspend.target is masked, so this PC never "
                                        "suspends and saves nothing.",
                            "sudo systemctl unmask suspend.target sleep.target, or remove \"wake\" from config.json."))
        elif suspends:
            out.append(line(OK, area, f"The PC suspends after {after} idle (logind's IdleAction={action}); Deck Lab "
                                      "wakes it on request (wake-on-request)."))
        else:
            out.append(line(WARN, area, "Wake-on-request is set up but nothing here suspends this PC when idle "
                                        f"(logind's IdleAction is {action}), so it saves nothing.", LOGIND_FIX))
        out += _inhibit_lines(facts, area)
        return out
    if suspends:
        return [line(WARN, area, f"The PC suspends after {after} idle (logind's IdleAction={action}), and the page "
                                 "stops while it sleeps.",
                     f"Set IdleAction=ignore in {where} (as root), then restart the PC; or add a \"wake\" block to "
                     "config.json for wake-on-request.")]
    return [line(OK, area, f"Nothing here suspends the PC when idle (logind's IdleAction is {action}), so the page "
                           "stays up. A desktop's own power settings aren't checked.")]


def _inhibit_lines(facts, area):
    if not facts.get("inhibit_tool"):
        return [line(WARN, area, "systemd-inhibit isn't installed, so Deck Lab can't hold the PC awake while it's "
                                 "in use: it may suspend in the middle of a visit or a Forge run.",
                     "Install systemd's tools (systemd-inhibit comes with systemd).")]
    trial = facts.get("inhibit")
    if not isinstance(trial, dict):
        return []
    if trial.get("ok"):
        return [line(OK, area, "Deck Lab may hold the PC awake while it's in use (systemd-inhibit).")]
    return [line(WARN, area, f"Deck Lab isn't allowed to hold the PC awake ({trial.get('error')}), so it may "
                             "suspend in the middle of a visit or a Forge run.", polkit_fix(facts.get("user")))]


def check_wake_linux(facts, gate=None):
    """The Wake lines, when config.json has "wake"; gate: its "gate", whose answer is facts["gate"]."""
    area = "Wake"
    out = [_suspend_line(facts, area), _adapter_line(facts, area), _wake_timer_line(facts, area)]
    if gate:
        answer = facts.get("gate") or {"answered": False, "error": "the check didn't finish"}
        if answer.get("answered"):
            out.append(line(OK, area, f"The wake gate at {gate} answers."))
        else:
            out.append(line(WARN, area, f"The wake gate at {gate} doesn't answer ({answer.get('error')}), so phones "
                                        "at home can't wake the PC through it.",
                            "Check that the wake gate's container is running on the NAS and that \"gate\" in "
                            "config.json is its address."))
    return [x for x in out if x]


def _suspend_line(facts, area):
    state = facts.get("power_state")
    if state is None:
        return line(WARN, area, f"Couldn't read which sleep states the kernel offers ({POWER_STATE}).")
    if "mem" not in state.split():
        return line(WARN, area, f"The kernel offers no suspend to RAM ({POWER_STATE}: {state.strip() or 'nothing'}), "
                                "so the PC can't sleep and be woken by a magic packet.",
                    "Check the BIOS/UEFI's sleep settings.")
    selected, modes = selected_mem_sleep(facts.get("mem_sleep"))
    if selected == "deep":
        return line(OK, area, "The PC suspends to S3 (mem_sleep is deep), which a magic packet can wake.")
    if selected is None:
        return line(WARN, area, f"Couldn't read which kind of suspend the PC uses ({MEM_SLEEP}).")
    fix = ("Add mem_sleep_default=deep to the kernel command line (GRUB_CMDLINE_LINUX_DEFAULT in /etc/default/grub, "
           "then sudo update-grub, or your distribution's way) and restart." if "deep" in modes else
           "This PC offers no deep (S3) suspend: look for S3 in the BIOS/UEFI settings, or test whether a magic "
           "packet wakes it from s2idle.")
    return line(WARN, area, f"The PC suspends with {selected} ({MEM_SLEEP}: {' '.join(modes)}), and some network "
                            "adapters can't wake it from that.", fix)


def _adapter_line(facts, area):
    interface = facts.get("interface")
    if not interface:
        return line(WARN, area, f"Couldn't tell which network adapter the PC uses (no default route in {ROUTE}), so "
                                "wake-on-LAN wasn't checked.")
    if facts.get("wireless"):
        return line(WARN, area, f"The PC reaches the network over Wi-Fi ({interface}), and a magic packet usually "
                                "can't wake a PC over Wi-Fi.", "Use a wired connection for wake-on-request.")
    ethtool = facts.get("ethtool") or {}
    wake_on, supports = ethtool.get("wake_on"), ethtool.get("supports")
    if wake_on is not None:
        if "g" in wake_on:
            return line(OK, area, f"{interface} wakes the PC on a magic packet (ethtool: Wake-on: {wake_on}).")
        if supports is not None and "g" not in supports:
            return line(WARN, area, f"{interface} can't wake the PC on a magic packet (ethtool: Supports Wake-on: "
                                    f"{supports or 'nothing'}).",
                        "Use a network adapter that supports wake-on-LAN (Supports Wake-on lists g).")
        return line(WARN, area, f"{interface} isn't set to wake the PC on a magic packet (ethtool: Wake-on: "
                                f"{wake_on}).", wol_fix(interface))
    why = ethtool.get("error") if ethtool else "ethtool isn't installed"
    wakeup = facts.get("nic_wakeup")
    if wakeup == "enabled":
        return line(OK, area, f"{interface}'s device may wake the PC (power/wakeup is enabled); whether it wakes on "
                              f"a magic packet wasn't read ({why}).")
    if wakeup == "disabled":
        return line(WARN, area, f"{interface}'s device may not wake the PC (power/wakeup is disabled), so a magic "
                                "packet won't wake it.", wol_fix(interface))
    return line(WARN, area, f"Couldn't read whether {interface} may wake the PC ({why}).", wol_fix(interface))


def _wake_timer_line(facts, area):
    state = facts.get("wake_timer")
    if state is None:
        return line(WARN, area, f"Couldn't ask systemctl whether {WAKE_TIMER} wakes the PC for the nightly backup.")
    if state.get("LoadState") != "loaded":
        return line(WARN, area, f"Nothing wakes the PC for the nightly backup ({WAKE_TIMER} isn't installed, and a "
                                "user timer can't), so it runs when the PC next wakes.", WAKE_TIMER_FIX)
    if state.get("ActiveState") != "active":
        return line(WARN, area, f"{WAKE_TIMER} is installed but not active ({state.get('ActiveState') or '?'}), so "
                                "it won't wake the PC for the nightly backup.",
                    f"sudo systemctl enable --now {WAKE_TIMER}")
    return line(OK, area, f"{WAKE_TIMER} wakes the PC for the nightly backup.")


def status_lines(settings, facts=None, **gather_options):
    """homenet status's Sleep (and, with "wake", Wake) lines on Linux, as checks' line dicts.
    facts: gather()'s, when already read; else they're gathered here (gather_options go to it)."""
    from decklab.lib import keepawake
    wake = keepawake.wake_settings(settings)
    if facts is None:
        facts = gather(wake, **gather_options)
    lines = check_sleep_linux(facts, wake=wake is not None)
    if wake is not None:
        lines += check_wake_linux(facts, wake["gate"])
    return lines
