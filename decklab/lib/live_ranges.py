"""Live binomial ranges shared by the page API and Forge's sequential statistics.

The normal-mixture confidence sequence is simulation wave 3's section 7.6.
This module has no Forge or application dependencies, so reading progress does
not load the runner. Non-wins, including draws and errors, stay in games.
"""
import math

AV_RHO = 50.4       # mixture parameter, tuned for 1,600 games
AV_ALPHA = 0.05


def anytime_counts(wins, games, *, rho=AV_RHO, alpha=AV_ALPHA):
    """(value, low, high), valid at every look; None before the first game."""
    if not games:
        return None
    v = games / 4
    half = math.sqrt((v + rho) * math.log((v + rho) / (rho * alpha ** 2))) / games
    value = wins / games
    return value, max(0.0, value - half), min(1.0, value + half)
