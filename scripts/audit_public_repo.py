"""Check that this public repo names no real email address, Cloudflare zone or configured domain (E11-S62).

Run from any directory: python scripts/audit_public_repo.py [--check] [--config FILE].
It reads every tracked file, and every untracked one .gitignore doesn't cover, for:

- an email address outside the example domains (example.com, example.org, example.net, and
  the reserved .example, .invalid and .test endings) and the small allow-list below;
- in a Cloudflare or wake gate config file (a wrangler config anywhere, a config file under
  decklab/cloudflare/ or decklab/wakegate/), a route, pattern, hostname or zone_name that isn't an
  example host, and an account_id or zone_id that isn't a placeholder;
- on a PC with a decklab/config.json (gitignored, so never in CI): its profiles' emails, its
  allowed_hosts and its Cloudflare Access team address and AUD tag, anywhere in any file.

This file never holds a real value: the configured ones are read at run time and never printed
(a finding names the file, the line and which kind of value it is). Standard library only.
"""
import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "decklab" / "config.json"

EXAMPLE_DOMAINS = ("example.com", "example.org", "example.net")
EXAMPLE_ENDINGS = ("example", "invalid", "test", "localhost")
# Addresses outside the example domains that may stay, each with its reason. Keep it small.
ALLOWED_EMAILS = {
    "noreply@anthropic.com": "the commit trailer's co-author address, quoted in docs",
    "git@github.com": "GitHub's SSH remote, not a mailbox",
    "a@-example.com": "a malformed address the profile validation tests refuse",
    "m@x.com": "a made-up test address (test_profile_list.py)",
    "c@x.com": "a made-up test address (test_profile_list.py)",
    "c2@x.com": "a made-up test address (test_profile_list.py)",
    "user@www.mtgmate.com.au": "a URL's made-up userinfo in the shop URL tests, not a mailbox",
    "secret@www.mtgmate.com.au": "a URL's made-up userinfo in the shop URL tests, not a mailbox",
}
# The last label must be letters, so wrangler@4.151.1, icon@2x.png's "2x" host and user@192.168.0.2 aren't
# addresses; a file-type ending is no top-level domain either.
_EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]+)@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.([A-Za-z]{2,24}))"
                    r"(?![A-Za-z0-9-])")
_NOT_TLDS = {"png", "jpg", "jpeg", "webp", "svg", "gif", "js", "mjs", "css", "html", "py", "json", "md", "txt", "service",
             "timer", "java", "jar", "zip"}

CONFIG_DIRS = ("decklab/cloudflare/", "decklab/wakegate/")
CONFIG_SUFFIXES = {".toml", ".json", ".jsonc", ".yaml", ".yml", ".env", ".ini", ".conf"}
HOST_KEYS = {"route", "routes", "pattern", "zone_name", "hostname", "custom_domain"}
ID_KEYS = {"account_id", "zone_id"}
# One "key = value" or "key: value" line of YAML, JSON or an env file; an env name may end with the key
# (CLOUDFLARE_ACCOUNT_ID).
_LINE = re.compile(r"""^\s*(?:-\s*)?(?:export\s+)?["']?[A-Za-z0-9_.-]*?(?<![A-Za-z0-9])"""
                   r"""(route|routes|pattern|zone_name|hostname|custom_domain|account_id|zone_id)["']?\s*[:=]\s*(.*)$""",
                   re.IGNORECASE)
_QUOTED = re.compile(r"""["']([^"']*)["']""")
MIN_TERM = 6                 # a shorter configured value would match by chance
# Second-level labels that are registries under a two-letter country ending (com.au, co.uk), so
# "shop.com.au" is never searched for as somebody's zone.
_REGISTRY_LABELS = {"com", "net", "org", "co", "edu", "gov", "id", "ac", "asn", "me", "ne", "or"}


def tracked_files(root=None):
    """Every tracked file's repo-relative name, and each untracked one .gitignore doesn't cover."""
    out = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                                  cwd=root or ROOT)
    return sorted({name for name in out.decode("utf-8").split("\0") if name})


def example_host(host):
    """Whether a host name is a placeholder: an example domain or under one, or a reserved ending."""
    host = host.strip().lower().rstrip(".")
    if not host:
        return True
    if any(host == domain or host.endswith("." + domain) for domain in EXAMPLE_DOMAINS):
        return True
    return host.rsplit(".", 1)[-1] in EXAMPLE_ENDINGS


def route_host(value):
    """The host of a route pattern or host value: "*.shop.example.com/api/*" gives "shop.example.com"."""
    value = re.sub(r"^[a-z][a-z0-9+.-]*://", "", value.strip(), flags=re.IGNORECASE)
    host = re.split(r"[/?#]", value, maxsplit=1)[0]
    host = host.rsplit("@", 1)[-1].split(":", 1)[0]
    return host.lstrip("*").lstrip(".")


def placeholder_id(value):
    """Whether an account or zone id is plainly not a real one: blank, <...>, a variable, one repeated
    character, or wording such as "your-account-id"."""
    value = value.strip()
    if not value or value[0] in "<$" or len(set(value.lower())) == 1:
        return True
    return any(word in value.lower() for word in ("example", "placeholder", "your"))


_JSON_STRING = r'"(?:\\.|[^"\\])*"'


def strip_jsonc(text):
    """JSONC as JSON: // and /* */ comments outside strings and trailing commas removed, line breaks kept."""
    out = re.sub("(" + _JSON_STRING + r")|//[^\n]*|/\*.*?\*/",
                 lambda m: m.group(1) or re.sub(r"[^\n]", "", m.group(0)), text, flags=re.DOTALL)
    return re.sub("(" + _JSON_STRING + r")|,(?=\s*[\]}])", lambda m: m.group(1) or "", out)


def zone_names(host):
    """A host and the zones it may sit in: "www.cards.shop.net" gives cards.shop.net and shop.net, never a
    bare registry such as com.au."""
    labels = [label for label in host.strip().lower().rstrip(".").split(".") if label]
    if labels[:1] == ["www"]:
        labels = labels[1:]
    names = []
    for start in range(len(labels) - 1):
        rest = labels[start:]
        if len(rest) == 2 and len(rest[1]) == 2 and rest[0] in _REGISTRY_LABELS:
            break
        names.append(".".join(rest))
    return names


def is_config_file(name):
    """Whether a repo-relative name is a Cloudflare or wake gate config file."""
    path = Path(name)
    leaf = path.name.lower()
    if leaf.startswith("wrangler") and path.suffix.lower() in (".toml", ".json", ".jsonc"):
        return True
    if not name.startswith(CONFIG_DIRS):
        return False
    return path.suffix.lower() in CONFIG_SUFFIXES or leaf.startswith(".env")


def email_findings(text):
    """[(line number, message)] for each address outside the example domains and the allow-list."""
    found = []
    if "@" not in text:
        return found
    for number, line in enumerate(text.splitlines(), 1):
        if "@" not in line:
            continue
        for match in _EMAIL.finditer(line):
            address, host = match.group(0), match.group(2)
            if match.group(3).lower() in _NOT_TLDS or example_host(host) or address.lower() in ALLOWED_EMAILS:
                continue
            found.append((number, f"an email address outside example.com: {address}"))
    return found


def _value_problem(key, value):
    if not isinstance(value, str):
        return None
    if key in ID_KEYS:
        return None if placeholder_id(value) else f"{key} isn't a placeholder"
    host = route_host(value)
    return None if example_host(host) else f"{key} names {host}, not an example.com placeholder"


def _walk(node, key=None):
    """(key, string) for every value under one of the keys, at any depth of parsed TOML or JSON."""
    if isinstance(node, dict):
        for name, value in node.items():
            lowered = str(name).lower()
            yield from _walk(value, lowered if lowered in HOST_KEYS | ID_KEYS else None)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, key)
    elif key and isinstance(node, str):
        yield key, node


def _line_of(lines, value):
    for number, line in enumerate(lines, 1):
        if value and value in line:
            return number
    return 1


def config_findings(name, text):
    """[(line number, message)] for a config file's routes, zone names and ids that aren't placeholders."""
    lines = text.splitlines()
    parsed = None
    suffix = Path(name).suffix.lower()
    try:
        if suffix == ".toml":
            parsed = tomllib.loads(text)
        elif suffix == ".json":
            parsed = json.loads(text)
        elif suffix == ".jsonc":
            plain = strip_jsonc(text)
            parsed = json.loads(plain)
            lines = plain.splitlines()                  # so a value in a comment isn't the line named
    except ValueError:
        parsed = None                                   # read line by line instead
    found = []
    if parsed is not None:
        for key, value in _walk(parsed):
            problem = _value_problem(key, value)
            if problem:
                found.append((_line_of(lines, value), problem))
        return sorted(set(found))
    for number, line in enumerate(lines, 1):
        if line.lstrip().startswith(("#", "//")):
            continue
        match = _LINE.match(line)
        if not match:
            continue
        key, rest = match.group(1).lower(), match.group(2).strip()
        values = _QUOTED.findall(rest) or [re.split(r"\s+#", rest, maxsplit=1)[0].strip(" ,[]{}")]
        for value in values:
            problem = _value_problem(key, value)
            if problem:
                found.append((number, problem))
    return found


def config_terms(config_file=None):
    """{kind: {value}} read from a local config.json: its profiles' emails, its allowed_hosts and its
    Cloudflare Access team address and AUD tag, without placeholders. Empty when the file isn't there
    or can't be read."""
    try:
        config = json.loads(Path(config_file or CONFIG).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    if not isinstance(config, dict):
        return {}
    terms = {}

    def add(kind, value):
        value = str(value).strip().lower()
        if len(value) >= MIN_TERM:
            terms.setdefault(kind, set()).add(value)

    for profile in config.get("profiles") or []:
        emails = profile.get("emails") if isinstance(profile, dict) else None
        for email in emails or []:
            if isinstance(email, str) and "@" in email and not example_host(email.rsplit("@", 1)[-1]):
                add("a configured profile's email", email)
    for host in config.get("allowed_hosts") or []:
        if not isinstance(host, str):
            continue
        if "." in host and not example_host(host) and not re.fullmatch(r"[0-9.:\[\]]+", host.strip()):
            for zone in zone_names(host):
                add("the configured domain", zone)
    access = config.get("access")
    if isinstance(access, dict):
        team = str(access.get("team") or "").strip().lower()
        if team and team not in ("your-team", "example", "team"):
            terms.setdefault("the configured Cloudflare Access team", set()).add(f"{team}.cloudflareaccess.com")
        aud = str(access.get("aud") or "").strip().lower()
        if len(aud) >= 16 and len(set(aud)) > 2:
            add("the configured Cloudflare Access AUD tag", aud)
    return terms


def term_findings(data, terms):
    """[(line number, message)] for each configured value in a file's bytes, any case. The message says
    which kind of value it is, never the value."""
    lowered = data.lower()
    found = []
    for kind in sorted(terms):
        for term in sorted(terms[kind]):
            needle = term.encode("utf-8")
            at = lowered.find(needle)
            while at != -1:
                found.append((lowered.count(b"\n", 0, at) + 1, f"{kind} (from config.json)"))
                at = lowered.find(needle, at + len(needle))
    return sorted(set(found))


def _masked(message, terms):
    """A finding's message without any configured value another rule quoted in it."""
    for term in sorted({term for values in terms.values() for term in values}, key=len, reverse=True):
        message = re.sub(re.escape(term), "(a configured value)", message, flags=re.IGNORECASE)
    return message


def audit(root=None, config_file=None, names=None):
    """[(file, line number, message)] over the repo's files, sorted."""
    root = Path(root or ROOT)
    terms = config_terms(config_file or root / "decklab" / "config.json")
    found = []
    for name in tracked_files(root) if names is None else names:
        path = root / name
        try:
            if not path.is_file():
                continue
            data = path.read_bytes()
        except OSError:
            continue
        rows = term_findings(data, terms) if terms else []
        if b"\0" not in data:
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = None
            if text is not None:
                rows += email_findings(text)
                if is_config_file(name):
                    rows += config_findings(name, text)
        found.extend((name, number, _masked(message, terms)) for number, message in rows)
    return sorted(set(found)), terms


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when anything is found")
    parser.add_argument("--config", help="a config.json to read the real domain and emails from "
                                         "(default: decklab/config.json, when it exists)")
    args = parser.parse_args(argv)
    found, terms = audit(config_file=args.config)
    for name, number, message in found:
        print(f"{name}:{number}: {message}")
    count = sum(len(values) for values in terms.values())
    searched = (f"{count} configured value{'' if count == 1 else 's'} searched for" if count
                else "no local config.json values to search for")
    print(f"{len(found)} public-repo finding{'' if len(found) == 1 else 's'}; {searched}.")
    return int(args.check and bool(found))


if __name__ == "__main__":
    raise SystemExit(main())
