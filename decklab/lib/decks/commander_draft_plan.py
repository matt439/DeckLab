"""Recognize a few explicit commander payoffs using only the local Oracle index."""
import re


# Keep the subject: opponents casting these spells is a different payoff.
_CAST = re.compile(r"\b(?:whenever you cast|if you've cast) an? "
                   r"(instant or sorcery|artifact|creature) spell(?: this turn)?, (?!if\b)")
_BUFF = re.compile(r"\b([\w-]+)(?: creatures?)? you control (?:get|have|gain)\b")
_DRAW_BUFF = re.compile(r"whenever you draw a card, " + _BUFF.pattern)
# Ordinary cycling with a fixed cost of at most two mana, excluding typecycling and extra costs.
_CHEAP_CYCLING = re.compile(r"^cycling (\{[012wubrgc]\}|\{[1wubrgc]\}\{[1wubrgc]\})(?= \(|$)", re.MULTILINE)
_TOKENS = re.compile(r"(?:^|[,:.] |\byou (?:may )?)create ([\w /+*-]+) creature tokens?\b(?! under )", re.MULTILINE)
_AMASS = re.compile(r"(?:^|[,:.] |\byou (?:may )?|\byou lose \d+ life and )amass ([\w-]+) \d+", re.MULTILINE)
_POWER = re.compile(r"that spell's power is (\d+) or greater")
_RETRIEVE = re.compile(r"(?:^|[,:.] |you may )(?:return|cast|play|exile|shuffle) "
                       r"[^.,:;\n]*?\bfrom your graveyard\b", re.MULTILINE)
_REUSE = {"Delve", "Dredge", "Flashback", "Escape", "Unearth", "Embalm", "Eternalize", "Scavenge", "Disturb", "Encore"}
_TAX = re.compile(r'^all artifacts have "at the beginning of your upkeep, sacrifice this artifact '
                  r'unless you pay (\{\d+\})\."', re.MULTILINE)


def _plural_forms(tribe):
    word = tribe.casefold()
    return {word, word + "s", word + "es",
            word[:-1] + "ies" if word.endswith("y") else word,
            word[:-1] + "ves" if word.endswith("f") else word}


def spell_reasons(leads, spells):
    """Return explicit matches and drawbacks, computed once before drafting."""
    texts = [(c.get("oracle_text") or "").split("\n//\n")[0].casefold() for c in leads]
    cast = {kind for text in texts for kind in _CAST.findall(text)}
    powers = [int(n) for text in texts if "creature" in _CAST.findall(text) for n in _POWER.findall(text)]
    buffs = {word for text in texts for word in _BUFF.findall(text)}
    draw_buffs = {word for text in texts for word in _DRAW_BUFF.findall(text)}
    leaves = any("whenever one or more cards leave your graveyard" in text for text in texts)
    reasons, drawbacks, cheap_cyclers = {}, {}, set()
    for entry in spells:
        card = entry["card"]
        text = (card.get("oracle_text") or "").split("\n//\n")[0].casefold()
        if "artifact" in cast:
            tax = _TAX.search(text)
            if tax:
                drawbacks[entry["name"]] = f"It also makes you pay {tax[1]} at each upkeep for each artifact you keep."
        kind, _, subtypes = (card.get("type_line") or "").split(" // ")[0].partition("—")
        types = set(kind.split())
        reason = None
        if buffs and "Creature" in types:
            tribe = next((t for t in subtypes.split() if _plural_forms(t) & buffs), None)
            if tribe:
                reason = f"Its {tribe} creature type benefits from the commander's ability."
                if _plural_forms(tribe) & draw_buffs and (cycling := _CHEAP_CYCLING.search(text)):
                    cheap_cyclers.add(entry["name"])
                    reason += f" Cycling it for {cycling[1].upper()} also triggers the commander's draw ability."
        if buffs and not reason:
            # Reminder text can describe tokens created by other players.
            rules_text = re.sub(r"\([^()]*\)", "", text)
            if any(t in buffs for t in _AMASS.findall(rules_text)):
                reason = "It can amass an Army of a creature type the commander rewards."
            elif any(_plural_forms(t) & buffs for token in _TOKENS.findall(rules_text) for t in token.split()):
                reason = "It can create creature tokens of a type the commander rewards."
        if not reason and "instant or sorcery" in cast and types & {"Instant", "Sorcery"}:
            reason = "Casting this instant or sorcery supports the commander's ability."
        if not reason and "artifact" in cast and "Artifact" in types:
            reason = "Casting this artifact supports the commander's ability."
        if not reason and "creature" in cast and "Creature" in types:
            power = str(card.get("power") or "")
            if not powers:
                reason = "Casting this creature supports the commander's ability."
            elif power.isdecimal() and int(power) >= min(powers):
                reason = "Its printed power meets the commander's creature-spell threshold."
        if not reason and leaves and (set(card.get("keywords") or ()) & _REUSE
                                      or _RETRIEVE.search(text)):
            reason = "It can move a card out of your graveyard for the commander's ability."
        if reason:
            reasons[entry["name"]] = reason
    return reasons, drawbacks, cheap_cyclers
