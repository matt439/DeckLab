"""Guarded collection-batch adapter for PgInventory.apply, no HTTP/CLI surface.

No caller supplies imported rows or owner: rows come from the locked private draft,
and identity comes from the authenticated Actor. The schema remains staged.
"""
import io
from dataclasses import dataclass

from decklab.lib import cards
from decklab.lib.state import Invalid
from decklab.lib.state import pg_collection_batches as batches

from . import Summary, ops_collection, rules


@dataclass(frozen=True)
class BatchImport:
    space: str
    batch_id: str
    token: dict


def prepare(cur, op, actor):
    pending, receipt = batches.claim(cur, actor.id, op.space, op.batch_id, op.token)
    return pending, receipt


def run(pending, before):
    value = batches.content(pending.row["content"])
    rows = [{**row, "quantity": str(row["quantity"]), "notes": ""} for row in value["rows"]]
    raw = rules.collection_csv_bytes(rows).decode("utf-8")
    try:
        rows = rules.parse_cards(io.StringIO(raw), "collection batch")
    except rules.InvalidCards as error:
        raise Invalid(str(error)) from None
    for row in rows:
        printing = cards.printing(row["set"], row["collector_number"])
        card = cards.printing_card(row["set"], row["collector_number"])
        if (printing is None or card is None or printing["name"] != row["name"]
                or printing.get("digital") or "paper" not in printing.get("games", ())
                or row["finish"] not in printing.get("finishes", ())):
            raise Invalid("A batch printing is no longer valid. Review its exact printing and finish.")
        if row["condition"] not in {"", "NM", "LP", "MP", "HP", "DMG"}:
            raise Invalid("Choose a valid condition.")
        if row["language"] not in {"", "en", "es", "fr", "de", "it", "pt", "ja", "ko", "ru", "zhs", "zht", "he", "la", "grc", "ar", "sa", "ph", "qya"}:
            raise Invalid("Choose a valid card language.")
    after, summary = ops_collection.merge(
        before, pending.space, sources=[("collection batch", rows)],
        uploads=[("batch-" + pending.batch_id, raw)], limit=ops_collection.MAX_IMPORTS,
        message="Add {cards} cards from a reviewed physical batch", capture_additions=True)
    # No silent basic-land drops: a review must explicitly remove them before this path.
    if summary.counts.get("skipped_basics"):
        raise Invalid("Ordinary basic lands are not tracked. Remove them and review this batch again.")
    return after, summary


def replay(receipt):
    result = receipt["result"]
    return Summary(result["text"], result["counts"], {}, {"collection_batch": receipt})


def finish(cur, pending, summary, change_set):
    receipt = batches.finish(cur, pending, {"text": summary.text, "counts": dict(summary.counts),
                                           "change_set": change_set})
    return Summary(summary.text, summary.counts, summary.changed, {**summary.extra, "collection_batch": receipt})
