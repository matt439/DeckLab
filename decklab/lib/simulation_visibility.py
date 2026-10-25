"""Resolve saved simulation lists to names a viewer may see.

Results belong to their lists, rather than to the last deck which played them.
An old visible name or a visible current list with the same hash can therefore
represent a side whose latest name is private. This module has no request or
write behavior; callers provide the deck-read rule and list-hash reader.
"""
from decklab.lib import decks, spaces

class VisibleLists:
    """One answer's visible aliases and current-list hashes, read lazily."""

    def __init__(self, visible, card_sha, historical=None, own_space=None):
        self.visible = visible
        self.card_sha = card_sha
        self.historical = historical or visible
        self.own_space = own_space
        self._current = None

    def _catalog(self):
        if self._current is None:
            self._current = []
            for summary in [*decks.list_decks(), *decks.beginner_box_pairings()]:
                if summary.get("error") or not self.visible(summary["id"]):
                    continue
                for version in summary.get("versions") or []:
                    try:
                        sha = self.card_sha(decks.load_deck(summary["id"], version), decks.engine_kind(summary))
                    except (decks.DeckNotFound, decks.DeckFileError, OSError, ValueError, RuntimeError):
                        continue
                    self._current.append({"id": summary["id"], "version": version,
                                          "title": summary.get("title"), "card_sha": sha})
            if self.own_space is not None:
                self._current.sort(key=lambda row: spaces.space_of(row["id"]) != self.own_space)
        return self._current

    def reference(self, side, prefer=None):
        """A visible {id, version, title} for side, or None.

        prefer is a deck page's current reference: that page uses its own name
        for its list even when another visible deck played the list last.
        Historical aliases remain valid after a list is edited.
        """
        if not isinstance(side, dict):
            return None
        sha = side.get("card_sha")
        if prefer is not None and sha == prefer.get("card_sha") and self.visible(prefer.get("id")):
            return {key: prefer.get(key) for key in ("id", "version", "title")}
        aliases = list(reversed(side.get("seen_as") or []))
        if side.get("id"):
            aliases.insert(0, side)
        for alias in aliases:
            if isinstance(alias, dict) and self.historical(alias.get("id")):
                return {key: alias.get(key) for key in ("id", "version", "title")}
        if sha is not None:
            for alias in self._catalog():
                if alias["card_sha"] == sha:
                    return {key: alias.get(key) for key in ("id", "version", "title")}
        return None

    def result(self, result):
        """Whether both sides of a stored result have a visible representative."""
        sides = result.get("sides") or []
        return len(sides) == 2 and all(self.reference(side) is not None for side in sides)

    def side(self, side, stored=None, prefer=None):
        """A page side with a visible name, or None; never return raw aliases."""
        source = dict(side)
        if stored is not None:
            source["seen_as"] = stored.get("seen_as") or []
        reference = self.reference(source, prefer)
        if reference is None:
            return None
        try:
            kind = spaces.split_deck_id(reference["id"])[1]
        except ValueError:
            kind = "casual"
        out = {key: value for key, value in side.items() if key != "seen_as"}
        return dict(out, **reference, kind=kind)

    def item(self, item, stored=None, prefer=None):
        """A list item whose every side is visible, or None."""
        sides = []
        for side in item["sides"]:
            raw = next((s for s in (stored or {}).get("sides") or []
                        if s.get("card_sha") == side.get("card_sha")), None)
            resolved = self.side(side, raw, prefer)
            if resolved is None:
                return None
            sides.append(resolved)
        return dict(item, sides=sides) if len(sides) == 2 else None
