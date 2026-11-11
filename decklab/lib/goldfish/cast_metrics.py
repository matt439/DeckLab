"""Integer cast/colour-wait counters, and category labels that never change card identity or play choices."""
from collections import defaultdict, deque

from decklab.lib import cards


class Copy(int):
    """One physical copy's category rides alongside its unchanged engine card id."""
    def __new__(cls, cid, category=None):
        value = int.__new__(cls, cid)
        value.category = category
        return value


def category_queues(sections):
    labels = sorted({line.category for section in ("Commander", "Deck") for line in sections.get(section, [])
                     if getattr(line, "category", None)}, key=lambda name: (name.casefold(), name))
    ids = {name: i for i, name in enumerate(labels)}
    queues = defaultdict(deque)
    info = [{"name": name, "cards": 0, "spells": 0, "unresolved": 0} for name in labels]
    for section in ("Commander", "Deck"):
        for line in sections.get(section, []):
            exact = cards.resolve(line.name)
            card = cards.card(exact) if exact else None
            if card is not None and line.set and line.number:
                printed = cards.printing_card(line.set, line.number)
                if printed is not None and printed["name"] == card["name"]:
                    card = printed
            category = ids.get(getattr(line, "category", None))
            if category is not None:
                info[category]["cards"] += line.quantity
                if card is None:
                    info[category]["unresolved"] += line.quantity
            key = (section, card["name"], card["oracle_id"]) if card else (section, line.name, None)
            queues[key].extend([category] * line.quantity)
    return queues, info


def counts(model, turns):
    n = len(model["cards"])
    commanders = list(dict.fromkeys(model["commanders"]))
    return {"commander_first": [[0] * (turns + 1) for _ in commanders], "commander_never": [0] * len(commanders),
            "spell_seen": [0] * n, "spell_held": [0] * n, "spell_enough": [0] * n,
            "spell_blocked": [0] * n, "spell_wait_games": [0] * n,
            "category_casts": [[[0] * (turns + 1) for _ in range(category["cards"] + 1)]
                               for category in model.get("categories", [])]}


class Game:
    def __init__(self, engine, tallies):
        self.engine, self.tallies = engine, tallies
        self.commanders = list(dict.fromkeys(engine.commanders))
        self.first = {}
        self.categories = [0] * len(engine.model.get("categories", []))
        self.seen, self.waited = set(), set()

    def observe_hand(self, hand, available, affordable, casts=()):
        cast_names = {int(card) for card, _option in casts}
        for cid in {int(card) for card in hand if self.engine.SPELL[card]}:
            self.seen.add(cid)
            self.tallies["spell_held"][cid] += 1
            if self.engine.MINPAID[cid] <= available:
                self.tallies["spell_enough"][cid] += 1
                if cid not in cast_names and not affordable(cid):
                    self.tallies["spell_blocked"][cid] += 1
                    self.waited.add(cid)

    def cast(self, card, turn, commander):
        if commander and int(card) not in self.first:
            self.first[int(card)] = turn
        category = getattr(card, "category", None)
        if category is not None:
            self.categories[category] += 1

    def end_turn(self, turn):
        for index, total in enumerate(self.categories):
            bins = self.tallies["category_casts"][index]
            bins[min(total, len(bins) - 1)][turn] += 1

    def finish(self):
        for index, cid in enumerate(self.commanders):
            if cid in self.first:
                self.tallies["commander_first"][index][self.first[cid]] += 1
            else:
                self.tallies["commander_never"][index] += 1
        for cid in self.seen:
            self.tallies["spell_seen"][cid] += 1
        for cid in self.waited:
            self.tallies["spell_wait_games"][cid] += 1


def summary(tallies, model, turns, games, share):
    commanders = []
    for index, cid in enumerate(dict.fromkeys(model["commanders"])):
        first = tallies["commander_first"][index]
        cast = games - tallies["commander_never"][index]
        commanders.append({"name": model["cards"][cid]["name"], "by_turn": [
            {"turn": turn, "chance": share(sum(first[1:turn + 1]), games)} for turn in range(1, turns + 1)],
            "average_turn": round(sum(turn * count for turn, count in enumerate(first)) / cast, 2) if cast else None,
            "never": share(tallies["commander_never"][index], games)})
    castability = []
    for cid, card in enumerate(model["cards"]):
        if card["kind"] not in ("spell", "mdfc") or not card["options"]:
            continue
        seen, waited = tallies["spell_seen"][cid], tallies["spell_wait_games"][cid]
        blocked, enough = tallies["spell_blocked"][cid], tallies["spell_enough"][cid]
        castability.append({"name": card["name"], "games_seen": seen, "held_turns": tallies["spell_held"][cid],
                            "enough_mana_turns": enough, "blocked_turns": blocked, "games_waited": waited,
                            "blocked_share": share(blocked, enough), "average_wait": round(blocked / waited, 2) if waited else None})
    castability.sort(key=lambda row: (-(row["blocked_share"] or 0), -row["blocked_turns"], row["name"]))
    categories = []
    for index, category in enumerate(model.get("categories", [])):
        bins = tallies["category_casts"][index]
        categories.append({**category, "checked": not category["unresolved"],
            "by_turn": [{"turn": turn, "at_least": [share(sum(row[turn] for row in bins[count:]), games)
                         for count in range(1, len(bins))]} for turn in range(1, turns + 1)] if not category["unresolved"] else None})
    return {"commanders": commanders, "castability": castability, "categories": categories}
