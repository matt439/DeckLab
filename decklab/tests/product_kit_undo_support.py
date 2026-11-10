"""Disposable product/shared-kit snapshots and an exact-audit in-memory adapter."""
import copy

from decklab.lib import accessories
from decklab.lib.inventory import files, paths, rules, product_kit_undo as undo, changes
from decklab.tests import accessory_undo_support as accessory

CID = 42
OWNERS = frozenset({"matt", "shared"})


def snapshot():
    listing = [accessory.row(id="shared-sleeves-a", owner="shared", image="", crop=""),
               accessory.row(id="shared-sleeves-b", owner="shared", image="", crop=""),
               accessory.row(id="shared-box-a", owner="shared", kind="deck_box", quantity="1", capacity="100", image="", crop=""),
               accessory.row(id="shared-box-b", owner="shared", kind="deck_box", quantity="1", capacity="100", image="", crop=""),
               accessory.row(id="private-sleeves", owner="user1", image="", crop="")]
    tree = {paths.ACCESSORIES: accessories.csv_bytes(listing), paths.STATUS: (",".join(rules.STATUS_FIELDS) + "\n" +
        "alpha.csv,owned,yes,shared-sleeves-b,shared-box-b,Keep alpha,\n" +
        "beta.csv,owned,yes,shared-sleeves-a,shared-box-a,Keep beta,\n").encode()}
    for stem in ("alpha", "beta"):
        tree[paths.product(stem)] = b"deck,section,name,quantity,finish,set,collector_number\nFixture,deck,Forest,60,nonfoil,fdn,272\n"
    return files.build(tree, revision="kit-fixture-1", decks_revision="kit-decks-1")


class Store:
    def __init__(self):
        self.snapshot = snapshot()
        current = undo._status(self.snapshot)
        self.audit = {CID: [{"id": 101 + index, "table": undo.TABLE, "op": "UPDATE", "key": {"file": name},
            "after": copy.deepcopy(row), "before": {**row, "sleeves": "shared-sleeves-a" if name == "alpha.csv" else "shared-sleeves-b",
                                                    "deck_box": "shared-box-a" if name == "alpha.csv" else "shared-box-b"}}
            for index, (name, row) in enumerate(current.items())]}
        self.latest = {row["after"]["file"]: row["id"] for row in self.audit[CID]}
        self.writes = []

    def load(self):
        return self.snapshot

    def undo_audit_batch(self, cid):
        return copy.deepcopy(self.audit.get(cid, []))

    def undo_latest(self, table, key):
        return self.latest.get(key["file"])

    def product_kit_undo_review(self, cid, owners):
        return undo.review(cid, owners, self.snapshot, self)

    def apply(self, op, actor, message, reason=None, expected_revision=None):
        before = self.snapshot
        after, summary = op.run(changes.detach(before))
        rows = [{**row, "id": 200 + index, "before": row["after"], "after": row["before"]}
                for index, row in enumerate(summary.extra[undo.PROOF]["proof"]["source"])]
        summary = undo.confirm(before, after, summary, rows, reason)
        self.snapshot = after
        self.writes.append((actor, message, copy.deepcopy(rows)))
        return after, summary
