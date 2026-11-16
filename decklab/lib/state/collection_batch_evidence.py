"""Bounded private scanner evidence for staged collection drafts, not an auth claim."""
import json

from decklab.lib.state import Invalid

ORIGIN = "not recorded by existing pending state"


def _keys(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) <= set(required) | set(optional):
        raise Invalid("Invalid scanner evidence fields; photos and raw OCR are not accepted.")


def _text(value, limit=160):
    if not isinstance(value, str) or len(value) > limit or any(c in value for c in "\r\n\0"):
        raise Invalid("Invalid scanner evidence text.")


def _integer(value, low=0, high=1000000):
    if type(value) is not int or not low <= value <= high:
        raise Invalid("Invalid scanner evidence count or identity.")


def _choices(value):
    if not isinstance(value, list) or len(value) > 200:
        raise Invalid("Too many scanner candidates; nothing was truncated.")
    for candidate in value:
        _keys(candidate, (), ("name", "set", "collector_number", "set_name", "finish", "language", "how", "finishes"))
        for key, text in candidate.items():
            if key != "finishes":
                _text(text)
        if "how" in candidate and candidate["how"] not in ("name", "number", "name and number"):
            raise Invalid("Unknown scanner evidence kind.")
        if "finish" in candidate and candidate["finish"] not in ("", "nonfoil", "foil", "etched"):
            raise Invalid("Invalid scanner candidate finish.")
        if "finishes" in candidate and candidate["finishes"] is not None:
            values = candidate["finishes"]
            if not isinstance(values, list) or len(values) > 3 or any(x not in ("nonfoil", "foil", "etched") for x in values):
                raise Invalid("Invalid scanner candidate finishes.")


def validate(evidence, rows, unresolved):
    _keys(evidence, ("version", "next_scan_id", "provenance", "ambiguities"))
    if type(evidence["version"]) is not int or evidence["version"] != 1:
        raise Invalid("Unsupported scanner evidence version.")
    _integer(evidence["next_scan_id"], 1)
    sources, ambiguities = evidence["provenance"], evidence["ambiguities"]
    if not isinstance(sources, list) or len(sources) > 200 or not isinstance(ambiguities, list) or len(ambiguities) > 30:
        raise Invalid("Scanner evidence bounds exceeded.")
    totals, seen = [0] * len(rows), set()
    for index, source in enumerate(sources):
        _keys(source, ("input_index", "row_index", "quantity", "origin", "choices"))
        _integer(source["input_index"], 0, 199)
        _integer(source["row_index"], 0, len(rows) - 1)
        _integer(source["quantity"], 1, 9999)
        if source["input_index"] != index or source["input_index"] in seen or source["origin"] != ORIGIN:
            raise Invalid("Invalid scanner source identity or asserted origin.")
        seen.add(source["input_index"])
        totals[source["row_index"]] += source["quantity"]
        _choices(source["choices"])
    if totals != [row["quantity"] for row in rows]:
        raise Invalid("Scanner provenance no longer matches the draft quantities.")
    ids, labels = set(), []
    for item in ambiguities:
        _keys(item, ("source_id", "label", "language", "proposals"))
        _integer(item["source_id"])
        if item["source_id"] in ids or item["source_id"] >= evidence["next_scan_id"]:
            raise Invalid("Scanner resume identity would collide.")
        ids.add(item["source_id"])
        _text(item["label"])
        _text(item["language"])
        _choices(item["proposals"])
        labels.append(item["label"])
    if labels != unresolved:
        raise Invalid("Pending labels and scanner evidence must agree.")
    if len(json.dumps(evidence, ensure_ascii=False).encode("utf-8")) > 65536:
        raise Invalid("Scanner evidence is limited to 64 KiB; nothing was truncated.")
