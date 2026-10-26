"""Local profile diagnostics only; never part of the page's status or roster."""
from decklab.lib import profiles

from .common import PROBLEM, line


def issue_lines(issues):
    """Only positions, stable codes and static reasons, never submitted values."""
    return [line(PROBLEM, "Profiles",
                 f"{'profiles' if issue['index'] is None else 'Entry ' + str(issue['index'])} "
                 f"[{issue['code']}]: {issue['reason']}",
                 "Fix that entry in decklab/config.json; setup and profile sync leave it unchanged until fixed.")
            for issue in issues]


def check(settings):
    """Status keeps checking the rest of the PC while reporting every rejected entry."""
    _, issues = profiles.parse_with_diagnostics(settings.get("profiles", []), access=settings.get("access") is not None)
    return issue_lines(issues)
