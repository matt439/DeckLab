"""Actor attribution for user-facing database commands; PC access is unchanged.

Only an explicitly named actor needs a configured profile. Scripts that omit --actor
keep Claude's existing identity; maintenance commands keep their own system actors.
"""
from decklab.lib import profiles, state


def add_argument(parser):
    parser.add_argument("--actor", metavar="PROFILE",
                        help="who made this change: a profile id from config.json (default Claude)")


def resolve(args=None):
    """The command-line Actor, or ValueError before a write for an unknown profile."""
    profile_id = getattr(args, "actor", None)
    if profile_id is None:
        return state.Actor("claude", "Claude", None, "cli")
    profile = profiles.find(profile_id)
    if profile is None:
        raise ValueError(f"--actor {profile_id!r} isn't a profile in decklab/config.json")
    return state.Actor(profile["id"], profile["name"], None, "cli")
