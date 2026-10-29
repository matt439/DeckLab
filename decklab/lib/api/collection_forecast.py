"""Conditional home storage scenario from one pinned snapshot; never a placement or write.

Only verified pending loose-card sources enter the box scenario. Products await an
explicit receipt-time intact choice; token accounting is outside this scenario. All
totals include examined sources omitted from the bounded detail sample. Unknown sources
are explicit, never quantities of zero. No research-path, retailer or price lookups.
"""
from collections import Counter
import io
from pathlib import PurePosixPath
import re

from decklab.lib import cards, decks, inventory, pool, spaces
from decklab.lib.inventory import files, ops_collection as ops, paths, receive, rules

from . import collection_locations as places, guard

MAX_ORDERS = 200
MAX_COMPONENTS = 500
MAX_SOURCES = 1000
MAX_ROWS = 20000
MAX_DETAILS = 100
MAX_OUTPUT_SOURCES = 100
MAX_TOTAL = 1_000_000_000
MAX_BYTES = 8 * 1024 * 1024
MAX_HOLDER_DECKS = 200
MAX_HOLDER_TEXT = 1024 * 1024
ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _number(value):
    return type(value) is int and 0 <= value <= MAX_TOTAL


def _ident(value):
    return value if isinstance(value, str) and len(value) <= 128 and ID.fullmatch(value) else None


def _cell_chars(rows, columns=()):
    if len(rows) > MAX_ROWS or len(columns or ()) > 32 \
            or any(len(row.values) + len(row.overflow) > 64 for row in rows):
        raise OverflowError
    return (sum(len(value) for value in (columns or ()) if isinstance(value, str))
            + sum(len(value) for row in rows for _, value in row.values if isinstance(value, str))
            + sum(len(value) for row in rows for value in row.overflow if isinstance(value, str)))


def _base(box):
    known = isinstance(box, dict) and _number(box.get("cards")) and _number(box.get("capacity")) and box["capacity"] > 0
    return {"status": "ready", "basis": "known_pending_loose_cards", "stale": False,
            "current_cards": box["cards"] if known else None, "capacity": box["capacity"] if known else None,
            "known_loose_cards": 0, "box_candidates": 0, "basic_excluded": 0, "recorded_elsewhere": 0,
            "possible_current_holder_shortfall": None, "cards_if_candidates_filed": None,
            "over_if_candidates_filed": None,
            "pending_products": {"count": 0, "known_reference_cards": 0, "unknown_contents": 0},
            "tokens_excluded": {"known_cards": 0, "unknown_components": 0}, "unknown_sources": 0,
            "sources": [], "omitted_sources": 0, "problems": []}


def _problem(answer, code):
    if code not in answer["problems"]:
        answer["problems"].append(code)
    answer["status"] = "partial"


def _unavailable(box, code="sources_unavailable", *, stale=False):
    answer = _base(box)
    answer.update(status="unknown", stale=stale, box_candidates=None, recorded_elsewhere=None)
    answer["problems"] = [code, "snapshot_stale"] if stale else [code]
    return answer


def _source(order=None, component=None, kind="unknown", problem=None):
    return {"order_id": _ident(order.id) if order is not None else None,
            "component_id": _ident(component.id) if component is not None else None, "kind": kind,
            "label": {"cards": "Pending cards", "tokens": "Pending tokens", "product": "Pending product"}
                     .get(kind, "Unverified source"),
            "known_cards": None, "box_candidates": None, "basic_excluded": 0, "recorded_elsewhere": None,
            "unknown": bool(problem), "problem": problem, "rows": [], "omitted_rows": 0}


class _Projection:
    def __init__(self, inv, box):
        self.inv, self.answer = inv, _base(box)
        self.rows = self.bytes = self.details = self.sources = 0
        self.candidates = Counter()
        self.locations = None
        self.graph_unknown = False
        self.current_keys = None

    def add(self, source):
        self.sources += 1
        if source["unknown"]:
            self.answer["unknown_sources"] += 1
            _problem(self.answer, "source_unknown")
            if source["problem"] in ("invalid_record", "ambiguous_path", "missing_order", "product_status"):
                self.graph_unknown = True
        if len(self.answer["sources"]) < MAX_OUTPUT_SOURCES:
            self.answer["sources"].append(source)
        else:
            self.answer["omitted_sources"] += 1
            _problem(self.answer, "details_omitted")

    def checked_rows(self, source, *, product=False, existing=False):
        rows = source.items if product else source.rows
        self.rows += len(rows)
        if self.rows > MAX_ROWS:
            raise OverflowError
        chars = _cell_chars(rows, source.columns)
        if chars + self.bytes > MAX_BYTES:
            raise OverflowError
        if source.error or source.csv_error or source.strict_error or source.problems \
                or not product and not source.exists:
            raise ValueError
        data = files.render_product(source) if product else files.render_sheet(source)
        self.bytes += len(data)
        if self.bytes > MAX_BYTES:
            raise OverflowError
        parsed = rules.parse_cards(io.StringIO(data.decode("utf-8"), newline=""), "pending source", existing=existing)
        if not parsed and not existing:
            raise ValueError
        if sum(int(row["quantity"]) for row in parsed) > MAX_TOTAL:
            raise OverflowError
        return parsed

    def detail(self, source, row, name, disposition, location=""):
        if self.details < MAX_DETAILS:
            source["rows"].append({"name": name, "set": row["set"], "collector_number": row["collector_number"],
                                   "finish": row["finish"], "quantity": int(row["quantity"]),
                                   "disposition": disposition, "location": location})
            self.details += 1
        else:
            source["omitted_rows"] += 1
            _problem(self.answer, "details_omitted")

    def loose(self, order, component):
        source = _source(order, component, "cards")
        try:
            rows = self.checked_rows(self.inv.payloads[component.path])
            resolved = [(row, cards.resolve(row["name"])) for row in rows]
            if self.current_keys is None:
                self.current_keys = {rules.ident(row): row.name for row in self.inv.collection(spaces.HOME).rows}
            current = self.current_keys
            if any(not name or len(name) > 200 or len(row["collector_number"]) > 40
                   or rules.ident(row) in current and current[rules.ident(row)] != row["name"] for row, name in resolved):
                raise ValueError
        except OverflowError:
            raise
        except Exception:               # noqa: BLE001 - optional facts never expose source errors
            self.add(_source(order, component, "cards", "invalid_cards"))
            return
        source.update(known_cards=0, box_candidates=0 if self.locations is not None else None,
                      recorded_elsewhere=0 if self.locations is not None else None)
        for row, name in resolved:
            qty = int(row["quantity"])
            source["known_cards"] += qty
            if decks.is_basic_land(name):
                source["basic_excluded"] += qty
                disposition, location = "basic", ""
            else:
                location = self.locations.get(rules.ident(row), "") if self.locations is not None else ""
                disposition = "unknown" if self.locations is None else "box" if places.in_box(location) else "elsewhere"
                if disposition == "box":
                    source["box_candidates"] += qty
                    self.candidates[name] += qty
                elif disposition == "elsewhere":
                    source["recorded_elsewhere"] += qty
            self.detail(source, row, name, disposition, location)
        for field in ("known_loose_cards", "basic_excluded", "box_candidates", "recorded_elsewhere"):
            value = source["known_cards" if field == "known_loose_cards" else field]
            if value is not None:
                self.answer[field] += value
        self.add(source)

    def tokens(self, order, component):
        source = _source(order, component, "tokens")
        source["problem"] = "tokens_excluded"
        _problem(self.answer, "tokens_excluded")
        try:
            sheet = self.inv.payloads[component.path]
            self.rows += len(sheet.rows)
            if self.rows > MAX_ROWS:
                raise OverflowError
            self.bytes += _cell_chars(sheet.rows, sheet.columns)
            if self.bytes > MAX_BYTES:
                raise OverflowError
            if not sheet.exists or not sheet.rows or sheet.error or sheet.csv_error or sheet.strict_error or sheet.problems \
                    or any(not isinstance(row.quantity, str) or not re.fullmatch(r"[0-9]+", row.quantity)
                           or int(row.quantity) <= 0 for row in sheet.rows):
                raise ValueError
            quantity = sum(int(row.quantity) for row in sheet.rows)
            if quantity > MAX_TOTAL:
                raise OverflowError
            source["known_cards"] = quantity
            self.answer["tokens_excluded"]["known_cards"] += quantity
        except OverflowError:
            raise
        except Exception:               # noqa: BLE001 - no missing/invalid quantity becomes zero
            source.update(unknown=True, problem="unreadable_source")
            self.answer["tokens_excluded"]["unknown_components"] += 1
        self.add(source)

    def product(self, order, component, statuses):
        source = _source(order, component, "product")
        self.answer["pending_products"]["count"] += 1
        _problem(self.answer, "products_undecided")
        try:
            status = statuses.get(component.path)
            if status not in ("ordered", "preordered"):
                raise ValueError
            product = self.inv.product(component.product_stem)
            if product is None:
                raise ValueError
            rows = self.checked_rows(product, product=True)
            source.update(known_cards=sum(int(row["quantity"]) for row in rows), problem="product_choice")
            self.answer["pending_products"]["known_reference_cards"] += source["known_cards"]
        except OverflowError:
            raise
        except Exception:               # noqa: BLE001 - product count and reference-card count stay separate
            source.update(unknown=True, problem="product_status")
            self.answer["pending_products"]["unknown_contents"] += 1
        self.add(source)

    def shortfall(self):
        try:
            if self.locations is None or self.answer["unknown_sources"]:
                raise ValueError
            if not self.candidates:
                self.answer["possible_current_holder_shortfall"] = 0
                return
            # Pool construction parses recipes, including generated product decks. Bound
            # those inputs before loading; this optional note has its own work budget.
            home_decks = {key: deck for key, deck in self.inv.decks.items() if deck.space == spaces.HOME}
            if len(home_decks) > MAX_HOLDER_DECKS \
                    or sum(len(deck.text or "") for deck in home_decks.values()) > MAX_HOLDER_TEXT:
                raise ValueError
            sources = [*self.inv.payloads.values(), *self.inv.products, self.inv.collection(spaces.HOME)]
            source_rows = [source.items if hasattr(source, "items") else source.rows for source in sources]
            if sum(len(rows) for rows in source_rows) > MAX_ROWS:
                raise ValueError
            if sum(_cell_chars(rows, source.columns) for source, rows in zip(sources, source_rows)) > MAX_BYTES:
                raise ValueError
            physical = Counter()
            sheet = self.inv.collection(spaces.HOME)
            reader = _Projection(self.inv, None)
            for row in reader.checked_rows(sheet, existing=True) if sheet.exists else []:
                name = cards.resolve(row["name"])
                if not name:
                    raise ValueError
                if not decks.is_basic_land(name):
                    physical[name] += int(row["quantity"])
            # The library scans stored deck recipes while constructing the home pool.
            # Keep unrelated member text outside this optional computation entirely.
            with inventory.pinned(self.inv.replace(decks=home_decks)):
                found = pool.load_pool(spaces.HOME)
            if found.space != spaces.HOME or found.warnings or found.unresolved:
                raise ValueError
            held = Counter()
            for holder in found.in_use:
                if len(holder.cards) + reader.rows > MAX_ROWS:
                    raise ValueError
                reader.rows += len(holder.cards)
                if any(not _number(qty) for qty in holder.cards.values()):
                    raise ValueError
                held.update(holder.cards)
            self.answer["possible_current_holder_shortfall"] = sum(
                min(qty, max(held[name] - physical[name], 0)) for name, qty in self.candidates.items())
        except Exception:               # noqa: BLE001 - an optional demand note cannot become an allocation
            _problem(self.answer, "holder_shortfall_unknown")

    def run(self):
        inv, answer = self.inv, self.answer
        # Bound the outer scan before receive.record's cross-order duplicate-path checks.
        if len(inv.orders) > MAX_ORDERS or len(inv.payloads) + len(inv.products) > MAX_SOURCES \
                or len(inv.status.rows) > MAX_SOURCES or len(inv.collection(spaces.HOME).rows) > MAX_ROWS:
            raise OverflowError
        self.bytes += _cell_chars(inv.status.rows, inv.status.columns)
        if self.bytes > MAX_BYTES:
            raise OverflowError
        raw = []
        for order in inv.orders:
            items = (order.data.get("components", []) if isinstance(order.data, dict)
                     and isinstance(order.data.get("components"), list) else [])
            if len(items) + len(raw) > MAX_COMPONENTS:
                raise OverflowError
            raw.extend(items)
            if isinstance(order.data, dict):
                self.bytes += sum(len(value) for value in order.data.values() if isinstance(value, str))
                values = order.data.get("sources")
                if isinstance(values, list):
                    if len(values) > MAX_COMPONENTS:
                        raise OverflowError
                    self.bytes += sum(len(value) for value in values if isinstance(value, str))
                if self.bytes > MAX_BYTES:
                    raise OverflowError
        for item in raw:
            if not isinstance(item, dict):
                continue
            self.bytes += sum(len(value) for value in item.values() if isinstance(value, str))
            for field in ("checks", "verified_checks"):
                values = item.get(field)
                if isinstance(values, list):
                    if len(values) > MAX_COMPONENTS:
                        raise OverflowError
                    self.bytes += sum(len(value) for value in values if isinstance(value, str))
            if self.bytes > MAX_BYTES:
                raise OverflowError
        references = Counter(item.get("path") for item in raw if isinstance(item, dict) and isinstance(item.get("path"), str))
        order_files = Counter(order.file for order in inv.orders)
        if answer["current_cards"] is None:
            _problem(answer, "baseline_unavailable")
        try:
            if not inv.locations_ready:
                raise ValueError
            sheet = inv.location_sheet(spaces.HOME)
            if _cell_chars(sheet.rows, sheet.columns) > MAX_BYTES:
                raise ValueError
            ops.locations_sha256_of(inv, spaces.HOME)
            self.locations = inv.locations_of(spaces.HOME)
            if any(rules.clean_location(text) != text for text in self.locations.values()):
                raise ValueError
        except Exception:               # noqa: BLE001 - {} must not hide an unreadable/orphan location source
            _problem(answer, "locations_unavailable")
            answer.update(box_candidates=None, recorded_elsewhere=None)
        statuses, duplicate_statuses = {}, set()
        if inv.status.error or inv.status.csv_error or inv.status.strict_error or inv.status.problems:
            _problem(answer, "sources_unavailable")
            self.graph_unknown = True
        else:
            for row in inv.status.rows:
                file = row.text("file")
                state = row.text("status").strip().lower()
                if not file or len(file) > 256 or PurePosixPath(file).name != file \
                        or state not in ("owned", "ordered", "preordered", "cancelled"):
                    self.add(_source(problem="product_status"))
                    continue
                # Products share one logical inventory key at every status.
                path = paths.payload("product", "pending", file)
                if path in statuses:
                    duplicate_statuses.add(path)
                statuses[path] = state
            for path in duplicate_statuses:
                statuses[path] = None
                self.add(_source(problem="product_status"))
        for order in inv.orders:
            try:
                if order_files[order.file] != 1 or not _ident(order.id):
                    raise ValueError
                checked = receive.record(inv, order.id)
                if any(references[c.path] != 1 or not _ident(c.id) for c in checked.components):
                    raise ValueError
            except Exception:           # noqa: BLE001 - malformed records may hide incoming components
                self.add(_source(order, problem="invalid_record"))
                continue
            for component in checked.components:
                if component.status != "pending":
                    if component.kind == "product" and statuses.get(component.path) != (
                            "owned" if component.status == "received" else "cancelled"):
                        self.add(_source(problem="product_status"))
                    continue
                {"cards": self.loose, "tokens": self.tokens,
                 "product": lambda o, c: self.product(o, c, statuses)}[component.kind](order, component)
        # Legacy loose payloads and incoming product statuses must never silently disappear.
        for path in inv.payloads:
            folder = PurePosixPath(path).parent.as_posix()
            if folder in (paths.payload_folder("cards", "pending"), paths.payload_folder("tokens", "pending")) \
                    and path not in references:
                self.add(_source(problem="missing_order"))
        for path, status in statuses.items():
            if status in ("ordered", "preordered") and path not in references:
                self.add(_source(problem="missing_order"))
        self.shortfall()
        if self.graph_unknown:
            answer.update(box_candidates=None, recorded_elsewhere=None)
        if any(value > MAX_TOTAL for value in (answer["known_loose_cards"], answer["basic_excluded"],
                   answer["box_candidates"] or 0, answer["recorded_elsewhere"] or 0,
                   answer["pending_products"]["known_reference_cards"], answer["tokens_excluded"]["known_cards"])):
            raise OverflowError
        if inv.stale:
            answer["stale"] = True
            _problem(answer, "snapshot_stale")
        if answer["current_cards"] is not None and answer["box_candidates"] is not None and not answer["stale"]:
            total = answer["current_cards"] + answer["box_candidates"]
            if total > MAX_TOTAL:
                raise OverflowError
            answer.update(cards_if_candidates_filed=total, over_if_candidates_filed=total > answer["capacity"])
        return answer


def build(space, rows, box):
    """Optional rows-answer sibling. Gate this projection before enumerating any home records.

    rows is the caller's current collection view; the snapshot supplies canonical physical
    stock for the separate shortfall note. It is never read as future placement evidence.
    """
    if space != spaces.HOME:
        return None
    try:
        if not guard.sees_home_records():
            return None
    except Exception:                   # noqa: BLE001 - failed permission lookup never grants advice
        return None
    inv = None
    try:
        inv = inventory.current()
        with inventory.pinned(inv):
            return _Projection(inv, box).run()
    except OverflowError:
        return _unavailable(box, "work_limit", stale=bool(inv is not None and inv.stale))
    except Exception:                   # noqa: BLE001 - enrichment must not fail a saved change or 409
        return _unavailable(box, stale=bool(inv is not None and inv.stale))
