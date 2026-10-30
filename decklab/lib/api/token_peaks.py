"""The deck page's suggested token counts (E7-S08): deck_view's tokens with each need's "forge"
(tokens.peaks.annotate), from the card log's token peaks pooled over the list's saved Forge
results (forge.tokenpeaks.list_token_peaks).

Only results whose every side the viewer sees count (forge_runs._Seen, as the matchups and the
per-card stats are kept), so a matchup against a hidden deck adds nothing; and deck_view asks
only for a viewer who sees the deck's space's inventory, since the counts sit beside the token
cards owned ("N more than the cards that fit"). A Beginner Box half plays only in a pairing and
has no counts. Any failure leaves the Tokens part as it was, with the log saying why.
"""
import importlib
import traceback

from decklab.lib import decks
from decklab.lib.tokens import peaks

from . import common

FAILED = "The suggested counts couldn't be worked out from the saved Forge games (the server log says why)."


def with_peaks(result, summary, sections):
    """result (deck_view's tokens, deck_tokens' shape) with the suggested counts, or as it is
    when it has no needs, for a pairing or a Beginner Box half (no saved games of its own)."""
    if not (isinstance(result, dict) and result.get("needs")) or summary["id"].startswith("pairing/"):
        return result
    from .forge_runs import _Seen, is_half
    if is_half(summary):
        return result
    try:
        forge = importlib.import_module("decklab.lib.forge")
        seen = _Seen()
        with forge.engine.held():
            pooled = forge.tokenpeaks.list_token_peaks(sections, decks.engine_kind(summary),
                                                       keep=lambda stored: seen.result(forge, stored))
    except Exception:           # the Tokens part still shows; the log has the details
        common._log(f"The token peaks of {summary['id']} can't be worked out:\n" + traceback.format_exc())
        return dict(result, forge={"games": 0, "why": FAILED})
    return peaks.annotate(result, pooled)
