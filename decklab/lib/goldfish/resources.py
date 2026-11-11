"""Finite mana-source state. Trial plans clone it; only the chosen turn changes the battlefield."""
from itertools import combinations, islice

from .common import POP, _colour_bits

SEARCH_LIMIT = 2048


class Plan(tuple):
    def __new__(cls, casts, used, spent, added, context=None):
        value = tuple.__new__(cls, (casts, used, spent, added))
        value.context = context
        return value


def begin_turn(engine, resources, creatures, turn):
    """Untap ordinary sources/bodies and resolve explicitly modelled precombat charge releases."""
    mana = []
    for body in creatures:
        source = next((source for source in resources if source["body"] == body["uid"]), None)
        body["tapped"] = (bool(source["tapped"]) if source and not engine.RESOURCE[source["cid"]]["untaps"] else
                          body["tapped"] if not engine.CREATURE_UNTAPS[body["cid"]] else False)
    for source in resources:
        config = engine.RESOURCE[source["cid"]]
        if config["untaps"] and source["born"] < turn:
            source["tapped"] = False
        if config["release"] and source["charges"] and source["born"] < turn:
            mana.extend([config["release"]] * source["charges"])
            source["charges"] = 0
    return mana


def _sunburst(payment):
    """Most distinct actual colours the paid source masks can supply (colourless doesn't count)."""
    best = {frozenset()}
    for mask in payment:
        choices = [bit for bit in _colour_bits(mask & 31)]
        best = best | {old | {bit} for old in best for bit in choices}
    return max(map(len, best), default=0)


def pay(pool, generic, pips, option, sunburst=False):
    """Pay prior commitments and this spell together, retaining this spell's actual colour masks."""
    sources = sorted(pool, key=lambda mask: (POP[mask], -mask))
    needs = [(pip, False) for pip in pips] + [(pip, True) for pip in option[2]]
    needs.sort(key=lambda need: sum(bool(mask & need[0]) for mask in sources))
    used, own = set(), []

    def assign(index):
        if index == len(needs):
            return True
        pip, current = needs[index]
        for i, mask in enumerate(sources):
            if i in used or not mask & pip:
                continue
            used.add(i)
            if current:
                own.append(mask & pip)
            if assign(index + 1):
                return True
            if current:
                own.pop()
            used.remove(i)
        return False

    if not assign(0):
        raise ValueError("A planned payment wasn't payable")
    remaining = [i for i in range(len(sources)) if i not in used]
    if sunburst and option[1] <= 3:
        # Selecting k mana can never need more than k representatives of one mask.
        # Keep their first indices, preserving the exhaustive search's first best payment.
        copies, representatives, palette = {}, [], 0
        for i in remaining:
            mask = sources[i]
            palette |= mask & 31
            if copies.get(mask, 0) < option[1]:
                representatives.append(i)
                copies[mask] = copies.get(mask, 0) + 1
        for mask in own:
            palette |= mask & 31
        attainable = min(POP[palette], len(own) + option[1], 5)
        best, score = None, -1
        for picked in combinations(representatives, option[1]):
            value = _sunburst(own + [sources[i] for i in picked])
            if value > score:
                best, score = picked, value
                if score >= attainable:
                    break
        picked = list(best or ())
        own.extend(sources[i] for i in picked)
        used.update(picked)
        remaining = [i for i in remaining if i not in used]
        used.update(remaining[:generic])
    else:
        used.update(remaining[:generic])
        picked = remaining[generic:generic + option[1]]
        own.extend(sources[i] for i in picked)
        used.update(picked)
    return [mask for i, mask in enumerate(sources) if i not in used], own


class Context:
    def __init__(self, engine, resources, creatures, turn):
        self.engine, self.turn = engine, turn
        self.sources = [dict(source) for source in resources]
        self.creatures = [dict(body) for body in creatures]
        self.next_id = max([row["uid"] for row in self.sources + self.creatures], default=0) + 1
        self.spent = self.generated = 0
        self.mana_costs = 0

    def clone(self):
        copy = object.__new__(type(self))
        copy.engine, copy.turn, copy.next_id = self.engine, self.turn, self.next_id
        copy.sources = [dict(source) for source in self.sources]
        copy.creatures = [dict(body) for body in self.creatures]
        copy.spent, copy.generated = self.spent, self.generated
        copy.mana_costs = self.mana_costs
        return copy

    def adopt(self, other):
        self.sources, self.creatures, self.next_id = other.sources, other.creatures, other.next_id
        self.spent, self.generated = other.spent, other.generated
        self.mana_costs = other.mana_costs

    def spawn(self, card, payment):
        cid = int(card)
        body_uid = None
        effect = self.engine.EFF[cid]
        sacrificed_at_once = bool(effect and effect[0] == "ramp" and self.engine.SACRIFICE_RAMP[cid])
        if self.engine.CREW and self.engine.CREATURE[cid] and not sacrificed_at_once:
            body_uid = self.next_id
            self.next_id += 1
            ordinary = bool(effect and (effect[0] == "dork" or effect[0] == "ability" and effect[2]))
            ready = self.turn if effect and effect[0] == "dork" and effect[3] else self.turn + 1
            self.creatures.append({"uid": body_uid, "cid": cid, "born": self.turn, "tapped": self.engine.CREATURE_TAPPED[cid],
                                   "ordinary": ordinary, "ready": ready})
        config = self.engine.RESOURCE[cid]
        if config is not None:
            self.sources.append({"uid": self.next_id, "cid": cid, "body": body_uid, "born": self.turn,
                                 "tapped": config["tapped"], "charges": _sunburst(payment) if config["sunburst"] else config["charges"]})
            self.next_id += 1

    def actions(self, pool):
        """Legal finite activations. Assistant choices exclude already-counted ready mana creatures."""
        for source in self.sources:
            config = self.engine.RESOURCE[source["cid"]]
            own_body = next((body for body in self.creatures if body["uid"] == source["body"]), None)
            for index, method in enumerate(config["methods"]):
                if method["tap"] and (source["tapped"] or own_body and own_body["tapped"]
                                      or config["creature"] and not config["haste"] and source["born"] >= self.turn):
                    continue
                if method["cost"] > len(pool) or method["remove_charge"] and not source["charges"]:
                    continue
                helpers = []
                if method["crew"]:
                    helpers = [body for body in self.creatures if not body["tapped"]
                               and not ((method["tap"] or method.get("other")) and body["uid"] == source["body"])
                               and not (body["ordinary"] and body["ready"] <= self.turn)
                               and (not method["legendary"] or self.engine.LEGENDARY[body["cid"]])]
                    if len(helpers) < method["crew"]:
                        continue
                amount = source["charges"] + int(method["grow"]) if method["amount"] == "charges" else method["amount"]
                if amount <= 0:
                    continue
                helper_groups = combinations(helpers, method["crew"]) if method["crew"] else [()]
                for bodies in islice(helper_groups, 32):
                    masks = _colour_bits(method["mask"]) if method["single_colour"] and amount > 1 else [method["mask"]]
                    for mask in masks:
                        yield source["uid"], index, tuple(body["uid"] for body in bodies), mask, amount

    def activate(self, pool, action, deferred=False):
        from .engine import _leftover
        uid, index, bodies, mask, amount = action
        source = next(source for source in self.sources if source["uid"] == uid)
        method = self.engine.RESOURCE[source["cid"]]["methods"][index]
        left = list(pool) if deferred else _leftover(pool, method["cost"], ())
        self.spent += method["cost"]
        self.mana_costs += method["cost"]
        self.generated += amount
        for body in self.creatures:
            if body["uid"] in bodies or method["tap"] and body["uid"] == source["body"]:
                body["tapped"] = True
                for linked in self.sources:
                    if linked["body"] == body["uid"]:
                        linked["tapped"] = True
        if method["tap"]:
            source["tapped"] = True
        if method["grow"]:
            source["charges"] += 1
        if method["remove_charge"]:
            source["charges"] -= 1
        if method["sacrifice"]:
            self.sources.remove(source)
            self.creatures = [body for body in self.creatures if body["uid"] != source["body"]]
        return left + [mask] * amount

    def supply(self, pool, generic, pips, option, card=None):
        """Settle earlier casts, then activate only sources needed to make this payment possible."""
        if not self.sources:
            return None  # the caller already checked payment from the ordinary pool
        examined, seen = 0, set()

        def search(context, mana, committed):
            nonlocal examined
            examined += 1
            if examined > SEARCH_LIMIT:
                return None
            combined = tuple(sorted(pips + option[2]))
            if context.engine.payable(mana, context.engine.pool_id(mana), committed + option[1], combined):
                config = context.engine.RESOURCE[card] if card is not None else None
                left, payment = pay(mana, committed, pips, option, bool(config and config["sunburst"]))
                return context, left, payment
            key = (tuple(sorted(mana)), committed, tuple((source["uid"], source["tapped"], source["charges"]) for source in context.sources),
                   tuple((body["uid"], body["tapped"]) for body in context.creatures))
            if key in seen:
                return None
            seen.add(key)
            actions = list(context.actions(mana))
            actions.sort(key=lambda action: (context.engine.RESOURCE[next(source["cid"] for source in context.sources if source["uid"] == action[0])]["methods"][action[1]]["sacrifice"], -action[4], action[0], action[1], action[3]))
            for action in actions:
                source = next(source for source in context.sources if source["uid"] == action[0])
                cost = context.engine.RESOURCE[source["cid"]]["methods"][action[1]]["cost"]
                if not context.engine.payable(mana, context.engine.pool_id(mana), committed + cost, pips):
                    continue
                trial = context.clone()
                found = search(trial, trial.activate(mana, action, deferred=True), committed + cost)
                if found:
                    return found
            return None

        found = search(self.clone(), list(pool), generic)
        if found:
            context, mana, payment = found
            self.adopt(context)
            return mana, payment
        return None

    def capacity(self, pool):
        """Finite total-mana capacity, with the same body/source conservation as actual payments."""
        trial, mana = self.clone(), list(pool)
        for _ in range(128):
            actions = list(trial.actions(mana))
            useful = []
            for action in actions:
                source = next(source for source in trial.sources if source["uid"] == action[0])
                method = trial.engine.RESOURCE[source["cid"]]["methods"][action[1]]
                if action[4] > method["cost"]:
                    useful.append((action[4] - method["cost"], not method["sacrifice"], action))
            if not useful:
                break
            action = max(useful, key=lambda item: (item[0], item[1], -item[2][0]))[2]
            mana = trial.activate(mana, action)
        return len(mana)

    def finish(self, pool, generic, pips):
        from .engine import _leftover
        left = _leftover(pool, generic, pips)
        for source in self.sources:
            config = self.engine.RESOURCE[source["cid"]]
            cost = config["untap_cost"]
            if source["tapped"] and cost is not None and cost <= len(left):
                left = _leftover(left, cost, ())
                self.spent += cost
                source["tapped"] = False
            bank = config["bank"]
            if bank:
                for _ in range(128):
                    if bank["cost"] > len(left) or bank["tap"] and (source["tapped"] or config["creature"] and not config["haste"] and source["born"] >= self.turn):
                        break
                    left = _leftover(left, bank["cost"], ())
                    self.spent += bank["cost"]
                    source["charges"] += 1
                    if bank["tap"]:
                        source["tapped"] = True
                        break

    def used_ability(self, cid):
        body = next((body for body in self.creatures if body["cid"] == cid), None)
        if body:
            if self.engine.SACRIFICE_RAMP[cid]:
                self.creatures.remove(body)
            else:
                body["ordinary"] = False
                body["tapped"] = True
