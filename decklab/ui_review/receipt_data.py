"""Invented larger and multipart deliveries, confined to the disposable fixture."""
import csv
import io
import json

LARGE = "2000-01-02-review-large-parcel"
SPLIT = "2000-01-03-review-split-parcel"
FIELDS = ("name", "set", "collector_number", "finish", "quantity", "condition", "language", "notes")
CARDS = (("Llanowar Visionary", "6"), ("Beast Whisperer", "7"), ("Reclamation Sage", "8"))


def seed(fixture):
    """Write only beneath the fresh FixtureServer root; the normal inventory is never opened."""
    root = fixture.root
    for order_id, parts, rows_per_part, quantity in ((LARGE, 1, 24, 1), (SPLIT, 2, 6, 2)):
        components = []
        for part in range(parts):
            component_id = "cards" if parts == 1 else f"cards-{part + 1}"
            payload = f"magic/orders/{order_id}-{component_id}.csv"
            output = io.StringIO(newline="")
            writer = csv.DictWriter(output, fieldnames=FIELDS)
            writer.writeheader()
            for number in range(rows_per_part):
                name, collector_number = CARDS[number % len(CARDS)]
                writer.writerow(dict(name=name, set="sft", collector_number=collector_number,
                    finish="nonfoil", quantity=str(quantity), condition="", language="",
                    notes=f"Synthetic parcel {part + 1}, row {number + 1}; inspect on arrival"))
            (root / payload).write_text(output.getvalue(), encoding="utf-8")
            components.append(dict(id=component_id, kind="cards", status="pending", path=payload,
                                   received_on="", checks=[]))
        record = dict(version=1, id=order_id, seller="Disposable parcel fixture shop",
                      ordered_on="2000-01-01", sources=[],
                      notes="Invented repeated printings for local parcel-layout qualification only.",
                      components=components)
        (root / f"magic/orders/records/{order_id}.json").write_text(json.dumps(record), encoding="utf-8")
