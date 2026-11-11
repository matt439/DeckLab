"""Condition/language facts and optional household matching constraints, without I/O.

Missing facts remain unknown. Games Portal's earlier snapshots appended a
non-English language code to condition; read that evidence without assuming an
unmarked listing was English. A constraint only filters the fact it names.
"""
from decimal import Decimal, InvalidOperation

CONDITIONS = {"NM": "Near Mint", "LP": "Lightly Played", "MP": "Moderately Played", "HP": "Heavily Played", "DMG": "Damaged"}
RANK = {code: rank for rank, code in enumerate(CONDITIONS)}
LANGUAGES = {"en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese",
             "ja": "Japanese", "ko": "Korean", "ru": "Russian", "zhs": "Simplified Chinese", "zht": "Traditional Chinese",
             "he": "Hebrew", "la": "Latin", "grc": "Ancient Greek", "ar": "Arabic", "sa": "Sanskrit", "ph": "Phyrexian",
             "qya": "Quenya"}
_CONDITION = {**{code.casefold(): code for code in CONDITIONS},
              **{label.casefold(): code for code, label in CONDITIONS.items()},
              "mint": "NM", "light played": "LP", "moderate played": "MP", "heavy played": "HP", "dmg": "DMG"}
_LANGUAGE = {**{code: code for code in LANGUAGES}, **{label.casefold(): code for code, label in LANGUAGES.items()},
             "eng": "en", "jp": "ja", "jpn": "ja", "ger": "de", "deu": "de", "fre": "fr", "fra": "fr"}


def _word(value):
    if not isinstance(value, str) or len(value) > 100 or any(ord(char) < 32 for char in value):
        return ""
    return " ".join(value.strip().casefold().replace("_", " ").replace("-", " ").split())


def facts(item):
    """Canonical condition/language codes, or None for unreported/unrecognized facts."""
    condition = str(item.get("condition") or "")
    legacy_language = None
    prefix, comma, suffix = condition.rpartition(",")
    if comma and (legacy_language := _LANGUAGE.get(_word(suffix))):
        condition = prefix.strip()
    elif not comma and _LANGUAGE.get(_word(condition)):
        legacy_language, condition = _LANGUAGE[_word(condition)], ""
    explicit = item.get("language")
    language = _LANGUAGE.get(_word(explicit)) if explicit else legacy_language
    if explicit and legacy_language and language != legacy_language:
        language = None
    return {"condition": _CONDITION.get(_word(condition)), "language": language}


def words(item):
    known = facts(item)
    return {"condition": CONDITIONS.get(known["condition"]), "language": LANGUAGES.get(known["language"])}


def normalize(value):
    """None accepts every listing; otherwise exact, bounded independent constraints."""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"minimum_condition", "english_only"}:
        raise ValueError("Listing preferences need minimum_condition and english_only")
    minimum, english = value["minimum_condition"], value["english_only"]
    if minimum not in (None, *CONDITIONS) or type(english) is not bool:
        raise ValueError("Choose a minimum condition (NM, LP, MP, HP or DMG) or none, and English only or any language")
    return {"minimum_condition": minimum, "english_only": english} if minimum is not None or english else None


def fits(item, preference):
    if preference is None:
        return True
    known = facts(item)
    minimum = preference["minimum_condition"]
    return ((minimum is None or known["condition"] is not None and RANK[known["condition"]] <= RANK[minimum])
            and (not preference["english_only"] or known["language"] == "en"))


def filter_listings(listings, preference):
    return [item for item in listings if fits(item, preference)]


def _price(item):
    value = item.get("price") if isinstance(item, dict) else None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)) or len(str(value)) > 32:
        return None
    try:
        price = Decimal(str(value))
        return price if price.is_finite() and price >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def cheaper_skipped(baseline, chosen, preference):
    """The normal unfiltered choice was cheaper but failed an active constraint."""
    before, after = _price(baseline), _price(chosen)
    return bool(preference and before is not None and after is not None and before < after and not fits(baseline, preference))


def scope_words(preference):
    if not preference:
        return "Every condition and language"
    minimum = preference["minimum_condition"]
    return (f"{CONDITIONS[minimum]} or better" if minimum else "Every condition") + (
        ", English only" if preference["english_only"] else ", any language")
