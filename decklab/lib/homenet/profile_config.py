"""Local profile diagnostics only; never part of the page's status or roster."""
from decklab.lib import profiles

from .common import PROBLEM, WARN, line

ACCESS_ISSUES = {
    "access_legacy_roles": (PROBLEM, "No profile names a role; outside-home sign-ins are refused.",
                            "Set explicit admin or member roles in decklab/config.json before using Access."),
    "access_no_email": (PROBLEM, "No usable ASCII sign-in email alias is listed for this entry.",
                        "List the intended sign-in email locally, then review the Cloudflare Access policy."),
    "access_invalid_email": (WARN, "One or more declared email aliases use invalid or unsupported address syntax.",
                             "Review the email entries locally. This warning does not change request parsing."),
    "access_duplicate_email": (PROBLEM, "An email alias is listed by another usable profile; that alias cannot identify one profile.",
                               "Give each sign-in alias to exactly one profile in decklab/config.json."),
}


def _access_lines(settings, listed, issues):
    """Static readiness facts only; never query Access or report submitted values."""
    raw = settings.get("profiles", [])
    found = []

    def report(index, code):
        level, reason, fix = ACCESS_ISSUES[code]
        location = "profiles" if index is None else "Entry " + str(index)
        found.append(line(level, "Sign-in", f"{location} [{code}]: {reason}", fix))

    if isinstance(raw, list):
        if profiles.legacy(raw):
            report(None, "access_legacy_roles")
        rejected = {issue["index"] for issue in issues}
        parsed = {p["id"]: p for p in listed}
        counts = {}
        for profile in listed:
            for email in profile["emails"]:
                counts[email] = counts.get(email, 0) + 1
        for index, entry in enumerate(raw, 1):
            if index in rejected:
                continue
            profile = parsed[entry["id"]]
            aliases = entry.get("emails")
            declared = aliases if isinstance(aliases, list) else [] if aliases is None else [aliases]
            if not profile["emails"]:
                report(index, "access_no_email")
            if any(profiles.supported_email(value) is None for value in declared):
                report(index, "access_invalid_email")
            if any(counts[email] > 1 for email in profile["emails"]):
                report(index, "access_duplicate_email")
    return found


def issue_lines(issues):
    """Only positions, stable codes and static reasons, never submitted values."""
    return [line(PROBLEM, "Profiles",
                 f"{'profiles' if issue['index'] is None else 'Entry ' + str(issue['index'])} "
                 f"[{issue['code']}]: {issue['reason']}",
                 "Fix that entry in decklab/config.json; setup and profile sync leave it unchanged until fixed.")
            for issue in issues]


def check(settings):
    """Status keeps checking the rest of the PC while reporting every rejected entry."""
    access = settings.get("access") is not None
    listed, issues = profiles.parse_with_diagnostics(settings.get("profiles", []), access=access)
    return issue_lines(issues) + (_access_lines(settings, listed, issues) if access else [])
