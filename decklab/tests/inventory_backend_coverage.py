"""Inventory operation coverage claims and successful database-write evidence.

The fixture guard checks the registered production kinds and real DbTestCase
owners. Database CI checks actual changed PgInventory.apply calls in passing
test methods, not seeds, previews, refusals, source-string matches or skips.
"""
import ast
import importlib
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
_observed = {}
_lock = threading.Lock()

# Each claim names a module whose DbTestCase tests complete that operation.
GROUPS = {
    "test_collection_ops": ("collection.add", "collection.edit", "collection.remove", "collection.apply", "collection.import"),
    "test_collection_trade": ("collection.trade",),
    "test_loans_pg": ("collection.lend", "collection.return"),
    "test_inventory_accessories": ("accessory.add", "accessory.edit", "accessory.remove", "image.put", "image.remove", "kit.set"),
    "test_deck_saving_db": ("deck.save", "deck.create", "deck.delete", "deck.update_tables", "precon.add"),
    "test_inventory_rename": ("deck.rename",),
    "test_inventory_kit": ("product.set-kit",),
    "test_product_tokens_pg": ("product.set_tokens",),
    "test_token_ops": ("tokens.add", "tokens.edit", "tokens.remove"),
    "test_token_plan_mixed_pg": ("tokens.plan",),
    "test_receive_partial": ("receipt.receive",),
    "test_inventory_orders": ("order.add", "order.edit", "order.checks", "order.split", "order.cancel", "order.extra_copies",
                              "product.add", "product.set_intact", "watchlist.set", "watchlist.remove", "watchlist.replace"),
    "test_order_records": ("order.record",),
    "test_order_lifecycle": ("order.remove",),
    "test_order_merge": ("order.merge",),
    "test_pending_products": ("product.edit",),
    "test_shop_reference_pg": ("watchlist.reference_review",),
    "test_inventory_undo_pg": ("inventory.undo",),
    "test_inventory_undo_mixed_pg": ("inventory.undo_mixed",),
    "test_dice_operations_pg": ("dice.add", "dice.edit", "dice.remove"),
}
CLAIMS = {kind: "decklab.tests." + module for module, kinds in GROUPS.items() for kind in kinds}

# Frozen initial allowance. Closing a gap removes it from GAPS; new operations
# cannot enter this allowance. Changes to this baseline need an explicit review.
INITIAL_GAPS = frozenset({"dice.add", "dice.edit", "dice.remove", "collection.locations", "deck.token_cards", "tokens.add_many",
                          "watchlist.add_many", "watchlist.target_edit"})
GAPS = {
    "collection.locations": "Bulk exact-printing locations currently have only files/API fixtures.",
    "deck.token_cards": "Direct deck packing operation needs its own successful database operation case.",
    "tokens.add_many": "Scan/batch additions need a shared database operation suite.",
    "watchlist.add_many": "Reviewed multi-row queue additions need a direct database operation suite.",
    "watchlist.target_edit": "The CLI target-edit wrapper needs a direct database operation suite; reference_review is covered separately.",
}


def registered():
    """Load operation definitions only, never a backend/configuration/data snapshot."""
    from decklab.lib import inventory
    folder = ROOT / "lib" / "inventory"
    for path in sorted(folder.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "register"
               for node in ast.walk(tree)):
            importlib.import_module("decklab.lib.inventory." + path.stem)
    importlib.import_module("decklab.lib.tokens.ops")
    return {kind for kind, function in inventory._OPS.items() if function.__module__.startswith("decklab.lib.")}


def missing_claims(kinds):
    return set(kinds) - set(CLAIMS) - set(GAPS)


@contextmanager
def observe(module, dbname):
    """Only changed committed operations in this disposable DB and passing method count."""
    from decklab.lib.inventory import pg
    from decklab.db import conn
    from decklab.tests import db_support
    hit = set()
    original = pg.PgInventory.apply

    def apply(backend, operation, *args, **kwargs):
        kind = getattr(operation, "kind", None)
        target = backend.dbname or os.environ.get(conn.NAME_ENV)
        eligible = (isinstance(dbname, str) and dbname.startswith(db_support.PREFIX) and target == dbname
                    and CLAIMS.get(kind) == module)
        before = None
        if eligible:
            try:
                snapshot = backend.load()
                before = (snapshot.revision, snapshot.decks_revision)
            except Exception:
                pass      # original apply still owns its normal refusal/error behavior
        result = original(backend, operation, *args, **kwargs)
        after = (result[0].revision, result[0].decks_revision) if eligible else None
        if before is not None and after != before:
            with _lock:
                hit.add(kind)
        return result

    if module in CLAIMS.values():
        with mock.patch.object(pg.PgInventory, "apply", apply):
            yield hit
    else:
        yield hit
    # Exceptions/skips leave before here: failed assertions never establish coverage.
    with _lock:
        _observed.setdefault(module, set()).update(hit)


def unmet(modules, evidence=None):
    """Claims owned by this shard which passing DbTestCase methods didn't exercise."""
    evidence = _observed if evidence is None else evidence
    selected = set(modules)
    return {kind: module for kind, module in CLAIMS.items()
            if module in selected and kind not in evidence.get(module, set())}


def reset():
    with _lock:
        _observed.clear()
