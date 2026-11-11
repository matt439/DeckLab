"""Bounded nonland mana classes: self sacrifice, charge counters, assistants and untap restrictions.

Only explicit supported costs become sources. Other modes keep the old unmodelled notes.
"""
import re

from decklab.lib import stats
from .common import _mask

WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def _number(text):
    return int(text) if text.isdigit() else WORDS.get(text, 1)


def read(card, identity, colours):
    text = stats.REMINDER_RE.sub("", stats.front_text(card).lower())
    types = stats.type_words(card["type_line"].split(" // ")[0])
    if not types.intersection({"Artifact", "Creature"}) or "spend this mana only" in text:
        return None
    name = re.escape(card["name"].split(" // ")[0].lower())
    self_name = rf"(?:{name}|this (?:artifact|creature|permanent))"
    methods, special = [], set()
    no_untap = "doesn't untap during your untap step" in text
    bank = None
    for line in text.split("\n"):
        if ":" not in line or '"' in line:
            continue
        cost, effect = line.split(":", 1)
        stored = re.search(r"put (?:a|one) charge counter", effect)
        if stored and "add " not in effect:
            rest = re.sub(r"\{t\}|\{\d+\}|[,\s]", "", cost)
            paid = sum(int(n) for n in re.findall(r"\{(\d+)\}", cost))
            if not rest and (paid or "{t}" in cost):
                bank = {"cost": paid, "tap": "{t}" in cost}
        made = re.search(r"\badd\s+([^.]*)", effect)
        if not made or "activate only if" in effect:
            continue
        clause = made.group(1)
        mask, chosen = colours(clause, _mask(card.get("produced_mana")), identity)
        if not mask or chosen:
            continue
        if "charge counter" in clause or re.search(r"where x is[^.]*charge counter", clause):
            amount = "charges"
            special.add("charge")
        elif clause.startswith(("two mana", "three mana", "four mana")):
            amount = _number(clause.split()[0])
        else:
            amount = max(1, len(stats.SYMBOL_RE.findall(clause))) if " or " not in clause else 1
        sacr = re.search(rf"sacrifice {self_name}", cost)
        remove = re.search(rf"remove (?:a|one) charge counter from {self_name}", cost)
        helper = re.search(r"tap (a|an|one|two|three|another) (?:untapped )?(legendary )?creatures? you control", cost)
        rest = cost
        for found in (sacr, remove, helper):
            if found:
                rest = rest.replace(found.group(0), "")
        rest = re.sub(r"\{t\}|\{\d+\}|[,\s]", "", rest)
        if rest:
            continue
        tap = "{t}" in cost
        if not (tap or sacr or remove or helper):
            continue             # never turn an unbounded/free filtering loop into infinite mana
        grow = bool(stored and made.start() > stored.start())
        methods.append({"mask": mask, "amount": amount, "cost": sum(int(n) for n in re.findall(r"\{(\d+)\}", cost)),
                        "tap": tap, "sacrifice": bool(sacr), "remove_charge": bool(remove), "grow": grow,
                        "crew": _number(helper[1]) if helper else 0, "legendary": bool(helper and helper[2]),
                        "other": bool(helper and helper[1] == "another"),
                        "single_colour": "any one color" in clause or "single color" in clause})
        if sacr:
            special.add("sacrifice")
        if remove or grow:
            special.add("charge")
        if helper:
            special.add("assistants")
    if no_untap:
        special.add("untap")
    initial = re.search(r"enters (?:the battlefield )?(?:tapped )?with (a|one|two|three|four|five|\d+) charge counters?", text)
    kicker = re.search(r"multikicker\s*\{(\d+)\}", text)
    sunburst = "sunburst" in text
    start = _number(initial[1]) if initial else 1 if kicker and "charge counter" in text else 1 if re.search(r"with x charge counters?", text) else 0
    release = bool("precombat main phase" in text and "remove all charge counters" in text)
    if bank and not release and not any(method["remove_charge"] or method["amount"] == "charges" for method in methods):
        bank = None
    release_mask = 0
    if release:
        phrase = re.search(r"add ([^.]*)", text[text.find("precombat main phase"):])
        release_mask = colours(phrase[1], _mask(card.get("produced_mana")), identity)[0] if phrase else 0
        if not release_mask:
            return None
        special.add("charge")
    if not special or not methods:
        return None
    untap = re.search(rf"\{{(\d+)\}}:\s*untap {self_name}", text)
    return {"classes": sorted(special), "methods": methods, "charges": start, "sunburst": sunburst,
            "bank": bank, "release": release_mask, "untaps": not no_untap,
            "untap_cost": int(untap[1]) if untap else None,
            "tapped": bool(stats.ENTERS_TAPPED_RE.search(text)), "creature": "Creature" in types,
            "haste": "Haste" in card.get("keywords", []), "cast_extra": int(kicker[1]) if kicker and "charge counter" in text else 0}


def describe(config):
    parts = []
    if "sacrifice" in config["classes"]:
        parts.append("self-sacrifice mana is available once; the source leaves the battlefield")
    if "charge" in config["classes"]:
        parts.append("charge counters are tracked; spent counters cannot be reused")
    if config["cast_extra"]:
        parts.append(f"cast with one multikicker payment of {{{config['cast_extra']}}}, the smallest mana-producing form")
    if config["sunburst"]:
        parts.append("sunburst counts distinct colours among the mana paid")
    if config["release"]:
        parts.append("unused tap-to-charge mode banks a counter at turn end; banked counters become mana next main phase")
    if "assistants" in config["classes"]:
        parts.append("tap costs use untapped cast creature cards, including newly cast ones; ready ordinary mana creatures keep their own mana ability")
    if "untap" in config["classes"]:
        parts.append("does not untap normally" + (f"; spare mana pays its {{{config['untap_cost']}}} untap cost" if config["untap_cost"] is not None else "; optional untap modes outside the supported costs are not used"))
    return "; ".join(parts)
