"""The normaliser for the committed reader goldens (decklab/tests/fixtures/inventory_goldens),
kept from phase 4's gate (decklab/db/gate_p4.py until phase 5b retired the gates), with the
receipt-preview refresh plan and the other items golden_dump.deck_items asks this module for.

EXPECTED_P4 is the fixed list of differences phase 4's areas make on purpose, each a function run
on both dumps (the golden and this checkout's) before compare(), so the golden is never recorded
again or edited by hand for them: an area may only make the differences listed here.
- "no-git": deck saves no longer commit to git (R1, R8), so the "uncommitted", "commit_pending",
  "commit" and "committed" fields of the deck pages, the editor, the library and the Accessories
  page are dropped.
- "deck-ids": the pages name a deck by its id, not its file (R8): a "source" that's a deck file's
  path (magic/decks/<kind>/<slug>.md, magic/people/<id>/decks/<kind>/<slug>.md) becomes the id.
- "hidden-inventory": a viewer who can't see a deck's space's inventory (permissions.
  sees_inventory) sees no owned, missing or on-the-way counts, token chips, substitute
  availability or owned-vs-needed table (R6d): those fields of their deck pages, library entries
  and editor views are dropped.
- "per-viewer-accessory-token": the Accessories page's list token is worked out over only the
  rows the viewer may see (R6b), so a profile's view "sha256" is dropped; the local viewer's
  (everything) is still compared.

EXPECTED_P5 is phase 5's (normalise() applies it after EXPECTED_P4), for the goldens recorded by
older code (the committed tests/fixtures/inventory_goldens):
- "deck-id-messages": every message names a deck by its id, not its file: a deck file's path
  (DECK_PATH_IN) anywhere in a string value (never a key: deck_table's are the gate's own) becomes
  the id, as "deck-ids" does for a whole "source" ("magic/decks/casual/broken.md can't be read: ..."
  becomes "casual/broken can't be read: ..."). A bare "<slug>.md" (the deck-table refresh's own
  refusals) names no space, so it can't be mapped; no kept golden has one.
- "phase-5-wording": the advice and file names phase 5 reworded (phase5_wording(): the pool's
  "move the order file" and "set its status to owned" advice, "fix it by hand", "no deck file",
  a product order's "Change it by hand", the collection import's and the home-only accessories'
  file names, the editor's "The file has", the deck page's token line and the Tokens page's
  re-sort note) become the new words.
- "ui-additions": the fields the UI redesign added to the page answers (ui_additions()): a deck's
  "cover", "colors", "revision", "cover_card" and "edited" in the library and the deck page, the
  packing plan's "cards" and a wishlist entry's "source_deck" are dropped.
- "kit-editability": E10-S33 adds Boolean summary.kit.editable to deck-view answers so public
  kit readers get no Choose controls. Only that exact additive field is dropped; every kit value,
  warning and other editable field still compares. test_golden_kit_editability checks this boundary
  and verifies the real kit projection for its owner and a public reader.
- "shared-sleeves": several holders may use one sleeve design since E8-S20 (shared_sleeves()):
  the kit warnings and accessories check problems about a design or colour another holder has are
  dropped, the built-without-sleeves warning loses "(no two built decks share a colour)", and a
  kit's "shared_with" and the packing plan's "sleeve_notes" are dropped.
- "incoming-sources": E6-S03 adds source identities and ordered/preordered status to the pool,
  owned-vs-needed rows and their API labels. Only the new "incoming_sources" fields are dropped;
  the legacy labels and all counts still compare unchanged. test_api_incoming checks the new
  fields, their allocated quantities, snapshot consistency and inventory privacy.
- "assembly-completion": the builder now saves assembled decks, so its old plan-only note
  becomes the current note. The new plan and per-deck "completion" metadata and per-deck
  "finishes" are dropped only within assembly answers. test_assembly_completion and
  test_assembly_finishes cover these additions, including the snapshot-dependent fingerprint.
- "assembly-progress": E4-S02 saves shared checks. The note names shared progress and the
  additive token task hashes are dropped only from assembly answers; test_assembly_token_keys
  covers their physical identity rules independently.
- "usual-opponents": E4-S22 adds reciprocal opponent links to deck pages, library summaries
  and packing choices, plus a synthetic-pairing lookup on the library and packing answers.
  Only that new API metadata is dropped. test_opponents checks its values, same-space and
  visibility rules, header preservation, save races and audited database writes separately.
- "stand-in-defaults": E4-S21 adds physical-marker projections. Only empty deck mappings and
  holder warnings, and assembly metadata without saved mappings, retirements or warnings are
  dropped. Logical totals and shortages are dropped only when they duplicate the legacy
  totals and steps; every previous allocation field still compares. test_standins and the
  assembly stand-in tests cover saved mappings, physical allocation and inventory privacy.
- "rename-defaults": E1-S19 adds a library revision token and packing rename generations.
  Only the library index's token and a packing plan's consistent all-zero generation fields
  are dropped. Nonzero generations, mismatched maps, aliases and every allocation/privacy field
  still compare; test_golden_rename_defaults checks this boundary, while the rename tests check
  old links, immutable history and generation changes independently.
- "assembly-section-defaults": E4-S24/E5-S23 add optional sideboard recipes and physical-build
  projections. Only consistent implicit whole-list selections with no physical snapshot key,
  empty known-version sideboard choices (or choices matching already-compared deck sections),
  matching whole-list scope counts, empty retained intent
  and unchanged full-build projections matching existing summary counts are dropped. Explicit
  recipes, partial builds, snapshot keys, remaining intent, malformed metadata and every legacy
  allocation still compare. test_section_goldens checks this boundary independently; the section,
  assembled-model and intent tests cover the new behavior.
- "swap-defaults": E2-S07 adds deck_view's "swaps", the swaps a saved Play-now list makes,
  worked out from the two lists and the Substitutes prose the goldens already compare. Only that
  new key is dropped; test_swaps_core and test_swaps_api check its values and privacy.
- "considering-defaults": E2-S23 adds deck_view's "considering", a deck text's Considering list.
  No golden deck has one, so only an absent list (None) or an empty one is dropped; a list with
  cards still compares. test_deck_considering checks its values and privacy.
- "assembly-colors": packing participants carry the Planned/library "colors" already in their
  deck summaries. Only that new key is dropped from assembly answers; test_assembly_colors
  checks its values and privacy.
"""
import copy
import re

from decklab.lib import config
from decklab.tests import golden_dump as gate

LOCAL = "(local)"                    # the viewer key of a request on the home network naming nobody
RECEIVED_ON = "2026-12-31"           # the date a receipt preview receives every pending component on
NO_GIT = ("uncommitted", "commit_pending", "commit", "committed")
HIDDEN_PAGE = ("owned", "table", "tokens")
HIDDEN_INDEX = ("missing", "on_the_way", "availability_confirmed", "tokens")
HIDDEN_EDIT = ("table",)
DECK_ITEMS = ("list_decks", "beginner_box_pairings", "load_deck", "decks_index", "deck_view", "assembly",
              "by_viewer", "accessories", "accessories_p4")
DECK_PATH = re.compile(r"^magic/(?:people/([a-z0-9]+(?:-[a-z0-9]+)*)/)?decks/(casual|commander)/([^/]+)\.md$")
# A deck file's path inside a message (also after golden_dump._plain's <ROOT>/ for a tree outside the repo).
DECK_PATH_IN = re.compile(r"(?:<ROOT>/)?magic/(?:people/([a-z0-9]+(?:-[a-z0-9]+)*)/)?decks/(casual|commander)/"
                          r"([^/\s:'\"()]+)\.md")


# ------------------------------------------------------------------ the normaliser (H1)

def _drop_keys(value, keys):
    if isinstance(value, dict):
        for key in keys:
            value.pop(key, None)
        for item in value.values():
            _drop_keys(item, keys)
    elif isinstance(value, list):
        for item in value:
            _drop_keys(item, keys)


def deck_id_of(path):
    """The deck id a deck file's repo path names, or None."""
    m = DECK_PATH.match(path) if isinstance(path, str) else None
    if m is None:
        return None
    space, kind, slug = m.groups()
    return f"{kind}/{slug}" if space is None else f"{space}/{kind}/{slug}"


def _deck_sources(value):
    if isinstance(value, dict):
        found = deck_id_of(value.get("source"))
        if found is not None:
            value["source"] = found
        for item in value.values():
            _deck_sources(item)
    elif isinstance(value, list):
        for item in value:
            _deck_sources(item)


def no_git(dump):
    for key in DECK_ITEMS:
        _drop_keys(dump.get(key), NO_GIT)


def deck_ids(dump):
    for key in DECK_ITEMS:
        _deck_sources(dump.get(key))


def _space_of(deck_id):
    parts = deck_id.split("/")
    return parts[0] if len(parts) == 3 and parts[0] not in ("product", "pairing") else "home"


def _profiles():
    from decklab.lib import profiles as profile_list
    try:
        return {p["id"]: p for p in profile_list.read(config.load())}
    except (OSError, ValueError):
        return {}


def hidden_inventory(dump):
    from decklab.lib import permissions
    profiles = _profiles()
    for viewer, mine in (dump.get("by_viewer") or {}).items():
        if not isinstance(mine, dict):
            continue
        profile = None if viewer == LOCAL else profiles.get(viewer)

        def sees(space):
            return permissions.sees_inventory(profile, space, script=viewer == LOCAL)

        for key, view in (mine.get("deck_view") or {}).items():
            if isinstance(view, dict) and not sees(_space_of(key.rsplit("@", 1)[0])):
                for field in HIDDEN_PAGE:
                    view.pop(field, None)
        index = mine.get("decks_index")
        for entry in (index.get("decks") or []) if isinstance(index, dict) else []:
            if isinstance(entry, dict) and not sees(entry.get("space") or "home"):
                for field in HIDDEN_INDEX:
                    entry.pop(field, None)
        for deck_id, view in (mine.get("edit_view") or {}).items():
            if isinstance(view, dict) and not sees(_space_of(deck_id)):
                for field in HIDDEN_EDIT:
                    view.pop(field, None)


def per_viewer_accessory_token(dump):
    for viewer, mine in ((dump.get("accessories_p4") or {}).get("by_viewer") or {}).items():
        view = mine.get("view") if isinstance(mine, dict) else None
        if viewer != LOCAL and isinstance(view, dict):
            view.pop("sha256", None)


def _rewrite_strings(value, fn, skip=()):
    """value with fn applied to every string in it, dict keys left alone, and so are the values of
    the keys in skip (in place for a dict or list; returns the result)."""
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, dict):
        for key, item in value.items():
            if key not in skip:
                value[key] = _rewrite_strings(item, fn, skip)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            value[i] = _rewrite_strings(item, fn, skip)
    return value


def _id_for(m):
    space, kind, slug = m.groups()
    return f"{kind}/{slug}" if space is None else f"{space}/{kind}/{slug}"


def deck_id_messages(dump):
    # A "source" is "deck-ids"' in the deck items; elsewhere it's data (a watchlist row's), kept.
    _rewrite_strings(dump, lambda text: DECK_PATH_IN.sub(_id_for, text) if ".md" in text else text,
                     skip=("source",))


def _words(text):
    """A re.sub replacement that puts text in as it is (no group references)."""
    return lambda _: text


def phase5_wording():
    """[(the old words as a compiled pattern, the new words as re.sub's replacement)]: what
    "phase-5-wording" rewrites, with the new words from this checkout's code (imported here, not at the top: record() runs this module over older
    code, which hasn't these names)."""
    from decklab.lib import pool
    from decklab.lib.inventory import rules
    from decklab.lib.tokens import ops as token_ops
    merged = r"is already in collection\.csv; if it has arrived and been merged, (?:move the order file to " \
             r"orders/received/|set its status to owned in products/status\.csv), or its cards count twice"
    return [
        (re.compile(merged),
         _words(f"is already in the collection; if it has arrived and been merged, {pool.RECEIVE_IT}, or its "
                f"cards count twice")),
        (re.compile(r"; fix it by hand"), _words(rules.UNTIL_PUT_RIGHT)),
        (re.compile(r"\b([Nn])o deck file (?=[a-z0-9])"), r"\1o deck "),
        (re.compile(r"\(its card list and status row stay\)\. Change it by hand\."),
         _words("(its card list and status row stay). There's no command yet to change or remove a pending "
                "product.")),
        (re.compile(r"Deckbox or collection\.csv export"), _words("Deckbox or collection-columns export")),
        (re.compile(r"^The file has (?=no fenced decklist block)"), _words("The deck has ")),
        (re.compile(r"\((?:magic/)?accessories\.csv is home's\)"), _words("(the accessories are home's)")),
        (re.compile(r"^tokens\.csv line (\d+) couldn't be read; see the Tokens page$"),
         r"Token cards line \1 couldn't be read; see the Tokens page"),
        (re.compile(r"^Also sorted magic/tokens\.csv into the standard order \(no other row changed\)$"),
         _words(token_ops.RESORTED)),
    ]


def phase5_reworded(dump):
    wording = phase5_wording()

    def fix(text):
        for pattern, new in wording:
            text = pattern.sub(new, text)
        return text

    _rewrite_strings(dump, fix)


# The page answers' fields the UI redesign (stage 2, 2026-10) added; nothing they already had changed.
UI_SUMMARY = ("cover", "colors", "revision", "cover_card", "edited")


def ui_additions(dump):
    for mine in [dump, *((dump.get("by_viewer") or {}).values())]:
        if not isinstance(mine, dict):
            continue
        for entry in mine.get("list_decks") or [] if isinstance(mine.get("list_decks"), list) else []:
            if isinstance(entry, dict):
                entry.pop("cover_card", None)
        index = mine.get("decks_index")
        for entry in (index.get("decks") or []) if isinstance(index, dict) else []:
            if isinstance(entry, dict):
                for field in UI_SUMMARY:
                    entry.pop(field, None)
        for view in (mine.get("deck_view") or {}).values() if isinstance(mine.get("deck_view"), dict) else []:
            summary = view.get("summary") if isinstance(view, dict) else None
            if isinstance(summary, dict):
                for field in UI_SUMMARY:
                    summary.pop(field, None)
        for answer in (mine.get("assembly") or {}).values() if isinstance(mine.get("assembly"), dict) else []:
            if isinstance(answer, dict):
                answer.pop("cards", None)
        for view in (mine.get("wishlist_view") or {}).values() if isinstance(mine.get("wishlist_view"), dict) else []:
            for entry in (view.get("entries") or []) if isinstance(view, dict) else []:
                if isinstance(entry, dict):
                    entry.pop("source_deck", None)


def kit_editability(dump):
    """Only the deck page's additive Boolean kit permission, absent from historical snapshots."""
    for mine in [dump, *((dump.get("by_viewer") or {}).values())]:
        if not isinstance(mine, dict):
            continue
        views = mine.get("deck_view")
        for view in views.values() if isinstance(views, dict) else []:
            summary = view.get("summary") if isinstance(view, dict) else None
            kit = summary.get("kit") if isinstance(summary, dict) else None
            if isinstance(kit, dict) and type(kit.get("editable")) is bool:
                kit.pop("editable")


# The warnings and check problems the one-holder sleeves rule gave (E8-S20 dropped the rule), and
# the built-without-sleeves warning's old ending.
_ONE_HOLDER = re.compile(r"sleeves are (?:also )?recorded for .+: one design belongs to one deck"
                         r"|sleeves too: no two built decks share a colour"
                         r"|^.+ have .+ sleeves: no two built decks share a colour$")
_NO_SLEEVES_OLD = " (no two built decks share a colour)"


def shared_sleeves(dump):
    """"shared-sleeves": E8-S20 lets several holders use one sleeve design (Matt's decision of
    2026-10-13), so the warnings and problems about a shared design or colour are dropped from
    every list of strings, the built-without-sleeves warning loses its "(no two built decks share
    a colour)", a kit's "shared_with" (the other holders in its sleeves) and the packing plan's
    "sleeve_notes" are dropped."""
    def walk(value):
        if isinstance(value, dict):
            if "need" in value and "short" in value and "warnings" in value:
                value.pop("shared_with", None)          # a kit (accessories.kit)
            if "decks" in value and "token_plan" in value:
                value.pop("sleeve_notes", None)         # a packing plan answer
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            value[:] = [item for item in value if not (isinstance(item, str) and _ONE_HOLDER.search(item))]
            for i, item in enumerate(value):
                if isinstance(item, str) and item.endswith(_NO_SLEEVES_OLD):
                    value[i] = item[:-len(_NO_SLEEVES_OLD)]
                else:
                    walk(item)
    walk(dump)


def incoming_sources(dump):
    """E6-S03's additive metadata, absent from the historical reader snapshots."""
    _drop_keys(dump, ("incoming_sources",))


def assembly_completion(dump):
    """Builder additions from 2026-10-14; preserve every pre-existing allocation field."""
    old_note = ("This is a plan. Other built decks stay reserved. "
                "Nothing is moved, marked built or written to inventory.")
    new_note = ("Checking cards keeps progress in this browser. Mark as built saves the assembled lists; "
                "other built decks stay reserved.")
    for mine in [dump, *((dump.get("by_viewer") or {}).values())]:
        if not isinstance(mine, dict):
            continue
        plans = mine.get("assembly")
        for plan in plans.values() if isinstance(plans, dict) else []:
            if not isinstance(plan, dict):
                continue
            plan.pop("completion", None)
            if plan.get("note") == old_note:
                plan["note"] = new_note
            for deck in plan.get("decks") or []:
                if isinstance(deck, dict):
                    deck.pop("completion", None)
                    deck.pop("finishes", None)


def assembly_progress(dump):
    """E4-S02's additive task hashes and shared-progress wording; allocations stay unchanged."""
    for mine in [dump, *((dump.get("by_viewer") or {}).values())]:
        plans = mine.get("assembly") if isinstance(mine, dict) else None
        for plan in plans.values() if isinstance(plans, dict) else []:
            if not isinstance(plan, dict):
                continue
            if isinstance(plan.get("note"), str):
                plan["note"] = plan["note"].replace("keeps progress in this browser", "saves shared progress")
            for deck in plan.get("decks") or []:
                for need in (deck.get("tokens") or {}).get("needs", []):
                    need.pop("packing_key", None)


def usual_opponents(dump):
    """E4-S22's additive links; keep every legacy deck count, choice and packing allocation."""
    for mine in [dump, *((dump.get("by_viewer") or {}).values())]:
        if not isinstance(mine, dict):
            continue
        index = mine.get("decks_index")
        if isinstance(index, dict):
            index.pop("usual_opponents", None)
            for summary in index.get("decks") or []:
                if isinstance(summary, dict):
                    summary.pop("usual_opponents", None)
        views = mine.get("deck_view")
        for view in views.values() if isinstance(views, dict) else []:
            if isinstance(view, dict):
                view.pop("usual_opponents", None)
                if isinstance(view.get("summary"), dict):
                    view["summary"].pop("usual_opponents", None)
        plans = mine.get("assembly")
        for plan in plans.values() if isinstance(plans, dict) else []:
            if isinstance(plan, dict):
                plan.pop("usual_opponents", None)
                for choice in plan.get("choices") or []:
                    if isinstance(choice, dict):
                        choice.pop("usual_opponents", None)


def standin_defaults(dump):
    """Ignore only E4-S21's no-marker projections, retaining discrepancies and saved evidence."""
    plan_fields = {"version", "rows", "choices", "needs", "candidates", "retired", "warnings", "editable", "sha256"}
    for mine in [dump, *((dump.get("by_viewer") or {}).values())]:
        if not isinstance(mine, dict):
            continue
        pools = mine.get("pools")
        for pool in pools.values() if isinstance(pools, dict) else []:
            for holder in pool.get("in_use") or [] if isinstance(pool, dict) else []:
                if isinstance(holder, dict) and holder.get("standin_warnings") == []:
                    holder.pop("standin_warnings")
        views = mine.get("deck_view")
        for view in views.values() if isinstance(views, dict) else []:
            if not isinstance(view, dict):
                continue
            projection = view.get("standins")
            if projection is None or projection == {"version": view.get("version"), "rows": [], "warnings": []}:
                view.pop("standins", None)
        plans = mine.get("assembly")
        for plan in plans.values() if isinstance(plans, dict) else []:
            if not isinstance(plan, dict):
                continue
            if isinstance(plan.get("totals"), dict) and plan.get("logical_totals") == plan["totals"]:
                plan.pop("logical_totals", None)
            for deck in plan.get("decks") or []:
                if not isinstance(deck, dict):
                    continue
                steps = deck.get("steps")
                if isinstance(steps, list) and all(isinstance(step, dict) and
                        {"name", "waiting", "missing"} <= step.keys() for step in steps):
                    shortages = [{key: step[key] for key in ("name", "waiting", "missing")}
                                 for step in steps if step["waiting"] or step["missing"]]
                    if deck.get("logical_shortages") == shortages:
                        deck.pop("logical_shortages", None)
                projection = deck.get("standins")
                if (isinstance(projection, dict) and projection.keys() == plan_fields
                        and projection["version"] == deck.get("version")
                        and all(projection[key] == [] for key in ("rows", "choices", "retired", "warnings"))
                        and isinstance(projection["needs"], list) and isinstance(projection["candidates"], list)
                        and isinstance(projection["editable"], bool)
                        and (projection["sha256"] is None or isinstance(projection["sha256"], str))):
                    deck.pop("standins")


def swap_defaults(dump):
    """Drop only E2-S07's new "swaps" key on deck pages (derived from fields that still compare)."""
    for mine in [dump, *((dump.get("by_viewer") or {}).values())]:
        views = mine.get("deck_view") if isinstance(mine, dict) else None
        for view in views.values() if isinstance(views, dict) else []:
            if isinstance(view, dict):
                view.pop("swaps", None)


def considering_defaults(dump):
    """Drop only E2-S23's new "considering" key on deck pages, when it holds no card."""
    for mine in [dump, *((dump.get("by_viewer") or {}).values())]:
        views = mine.get("deck_view") if isinstance(mine, dict) else None
        for view in views.values() if isinstance(views, dict) else []:
            found = view.get("considering", False) if isinstance(view, dict) else False
            if found is None or (isinstance(found, dict) and found.get("lines") == []):
                view.pop("considering")


def assembly_colors(dump):
    """Drop only the packing participants' new "colors" key (copied from their deck summaries)."""
    for mine in [dump, *((dump.get("by_viewer") or {}).values())]:
        plans = mine.get("assembly") if isinstance(mine, dict) else None
        for plan in plans.values() if isinstance(plans, dict) else []:
            for deck in (plan.get("decks") or []) if isinstance(plan, dict) else []:
                if isinstance(deck, dict):
                    deck.pop("colors", None)


def rename_defaults(dump):
    """Only additive default generations; retain malformed or changed rename evidence."""
    for mine in [dump, *((dump.get("by_viewer") or {}).values())]:
        if not isinstance(mine, dict):
            continue
        index = mine.get("decks_index")
        if isinstance(index, dict):
            index.pop("decks_revision", None)
        plans = mine.get("assembly")
        for plan in plans.values() if isinstance(plans, dict) else []:
            if not isinstance(plan, dict):
                continue
            decks, generations = plan.get("decks"), plan.get("rename_versions")
            if not isinstance(decks, list) or not isinstance(generations, dict):
                continue
            if not all(isinstance(deck, dict) and isinstance(deck.get("id"), str)
                       and type(deck.get("rename_version")) is int and deck["rename_version"] == 0 for deck in decks):
                continue
            expected = {deck["id"]: 0 for deck in decks}
            if len(expected) != len(decks) or generations != expected or not all(type(v) is int for v in generations.values()):
                continue
            plan.pop("rename_versions")
            for deck in decks:
                deck.pop("rename_version")


def _whole(value):
    return type(value) is int and value >= 0


def _quantity_total(rows, field):
    if not isinstance(rows, list) or not all(isinstance(row, dict) and _whole(row.get(field)) for row in rows):
        return None
    return sum(row[field] for row in rows)


def _default_sideboards(choice, views):
    maps, versions = choice.get("sideboards"), choice.get("versions")
    if (not isinstance(choice.get("id"), str) or not choice["id"]
            or not isinstance(maps, dict) or not isinstance(versions, list)
            or not all(version in ("target", "owned") for version in versions)
            or len(set(versions)) != len(versions) or set(maps) - set(versions)):
        return False
    for version, rows in maps.items():
        if not isinstance(rows, list) or not all(
                isinstance(row, dict) and set(row) == {"name", "quantity"}
                and isinstance(row["name"], str) and bool(row["name"])
                and _whole(row["quantity"]) and row["quantity"] > 0 for row in rows):
            return False
        view = views.get(f"{choice.get('id')}@{version}") if isinstance(views, dict) else None
        sections = view.get("sections") if isinstance(view, dict) else None
        if isinstance(sections, dict):
            counts = {}
            lines = sections.get("Sideboard", [])
            if not isinstance(lines, list):
                return False
            for line in lines:
                if not isinstance(line, dict) or not isinstance(line.get("name"), str) or not _whole(line.get("qty")):
                    return False
                counts[line["name"]] = counts.get(line["name"], 0) + line["qty"]
            if rows != [{"name": name, "quantity": qty} for name, qty in sorted(counts.items())]:
                return False
        elif rows != []:
            return False
    return True


def _full_scope(deck, choices, views):
    scope = deck.get("build_scope")
    if not isinstance(scope, dict) or set(scope) != {
            "mode", "label", "main_count", "sideboard_count", "sideboard_intended", "return_count"}:
        return False
    fields = ("main_count", "sideboard_count", "sideboard_intended", "return_count")
    if not all(_whole(scope[field]) for field in fields):
        return False
    sideboard = scope["sideboard_count"]
    if (scope["mode"] != "all" or sideboard != scope["sideboard_intended"]
            or scope["label"] != ("Main deck + whole sideboard" if sideboard else "Main deck only")):
        return False
    choice = next((choice for choice in choices if isinstance(choice, dict)
                   and choice.get("id") == deck["id"]), None)
    if not choice or not _default_sideboards(choice, views):
        return False
    maps = choice["sideboards"]
    if deck["version"] in maps:
        if _quantity_total(maps[deck["version"]], "quantity") != sideboard:
            return False
    elif not choice["id"].startswith(("product/", "pairing/")) or sideboard:
        return False
    steps, basics = _quantity_total(deck.get("steps"), "need"), _quantity_total(deck.get("basics"), "quantity")
    returns = _quantity_total(deck.get("returns"), "quantity")
    return (steps is not None and basics is not None and returns is not None
            and scope["main_count"] + sideboard == steps + basics and scope["return_count"] == returns)


def _unchanged_assembled(value, summary):
    if (not isinstance(value, dict) or not isinstance(summary, dict)
            or summary.get("status") != "built" or set(value) != {
                "version", "intended_version", "main_count", "sideboard_count", "sideboard_intended",
                "remaining_count", "remaining", "changed"}):
        return False
    fields = ("main_count", "sideboard_count", "sideboard_intended", "remaining_count")
    return (all(_whole(value[field]) for field in fields)
            and _whole(summary.get("card_count")) and _whole(summary.get("sideboard_count"))
            and value["version"] == value["intended_version"] == "target"
            and value["main_count"] == summary["card_count"]
            and value["sideboard_count"] == value["sideboard_intended"] == summary["sideboard_count"]
            and value["remaining_count"] == 0 and value["remaining"] == [] and value["changed"] is False)


def assembly_section_defaults(dump):
    """Normalize only neutral whole-list additions, retaining partial builds and allocation evidence."""
    from decklab.lib import permissions
    profiles = _profiles()
    for viewer, mine in [(None, dump), *((dump.get("by_viewer") or {}).items())]:
        if not isinstance(mine, dict):
            continue

        def visible(summary):
            if viewer is None or viewer == LOCAL:
                return True
            deck_id = summary.get("id") if isinstance(summary, dict) else None
            return (isinstance(deck_id, str)
                    and permissions.sees_inventory(profiles.get(viewer), _space_of(deck_id)))

        views = mine.get("deck_view")
        plans = mine.get("assembly")
        for plan in plans.values() if isinstance(plans, dict) else []:
            if not isinstance(plan, dict):
                continue
            participants, choices = plan.get("decks"), plan.get("choices")
            if isinstance(participants, list) and isinstance(choices, list) and all(
                    isinstance(deck, dict) and isinstance(deck.get("id"), str)
                    and deck.get("version") in ("target", "owned") for deck in participants):
                expected = [{"id": deck["id"], "version": deck["version"]} for deck in participants]
                if (len({deck["id"] for deck in participants}) == len(participants)
                        and plan.get("selections") == expected and plan.get("assembly_keys") == {}
                        and all("assembly_key" in deck and deck["assembly_key"] is None for deck in participants)):
                    plan.pop("selections")
                    plan.pop("assembly_keys")
                    for deck in participants:
                        deck.pop("assembly_key")
                        if _full_scope(deck, choices, views):
                            deck.pop("build_scope")
                            if deck.get("remaining_intent") == []:
                                deck.pop("remaining_intent")
            for choice in choices if isinstance(choices, list) else []:
                if isinstance(choice, dict) and _default_sideboards(choice, views):
                    choice.pop("sideboards", None)
        index = mine.get("decks_index")
        for summary in (index.get("decks") or []) if isinstance(index, dict) else []:
            if (isinstance(summary, dict) and visible(summary)
                    and _unchanged_assembled(summary.get("assembled"), summary)):
                summary.pop("assembled")
        for view in views.values() if isinstance(views, dict) else []:
            if not isinstance(view, dict):
                continue
            summary = view.get("summary")
            if visible(summary) and _unchanged_assembled(view.get("assembled"), summary):
                view.pop("assembled")
            if (isinstance(summary, dict) and visible(summary)
                    and _unchanged_assembled(summary.get("assembled"), summary)):
                summary.pop("assembled")


EXPECTED_P4 = (("no-git", no_git), ("deck-ids", deck_ids), ("hidden-inventory", hidden_inventory),
               ("per-viewer-accessory-token", per_viewer_accessory_token))
EXPECTED_P5 = (("deck-id-messages", deck_id_messages), ("phase-5-wording", phase5_reworded),
               ("ui-additions", ui_additions), ("kit-editability", kit_editability), ("shared-sleeves", shared_sleeves),
               ("incoming-sources", incoming_sources), ("assembly-completion", assembly_completion),
               ("assembly-progress", assembly_progress), ("usual-opponents", usual_opponents),
               ("stand-in-defaults", standin_defaults), ("rename-defaults", rename_defaults),
               ("assembly-section-defaults", assembly_section_defaults), ("swap-defaults", swap_defaults),
               ("assembly-colors", assembly_colors), ("considering-defaults", considering_defaults))


def normalise(dump):
    """A copy of a dump with every EXPECTED_P4 and EXPECTED_P5 entry applied (see the module
    docstring)."""
    out = copy.deepcopy(dump)
    for _, fn in EXPECTED_P4 + EXPECTED_P5:
        fn(out)
    return out


# ------------------------------------------------------------------ the extra items

def receipt_refresh_plan(root):
    """{received: [order ids], skipped: [[order id, why]], plan: {deck id: sha256}}: the refresh
    plan after a pinned preview of receiving every pending component of every order (in name
    order, each preview on the one before; products kept whole: no), as plan_refresh gives it."""
    import hashlib

    from decklab.lib import inventory
    from decklab.lib.inventory import receive
    snapshot = inventory.current()
    received, skipped = [], []
    for order in snapshot.orders:
        if order.error is not None:
            continue
        pending = [c for c in order.components if c.status == "pending"]
        if not pending:
            continue
        chosen = [{"id": c.id, "verified": True, **({"intact": "no"} if c.kind == "product" else {})}
                  for c in pending]
        try:
            with inventory.pinned(snapshot):
                snapshot = gate.reader("inventory.preview", root, receive.op(order.id, chosen, RECEIVED_ON))
        except Exception as e:     # noqa: BLE001 - a refusal is part of what's compared
            skipped.append([order.id, gate._plain(f"{type(e).__name__}: {e}", root)])
            continue
        received.append(order.id)
    with inventory.pinned(snapshot):
        planned = gate.reader("decks.refresh_plan", root)
    ids = {rel: deck_id_of(rel) or rel for rel, _ in planned}
    return {"received": received, "skipped": skipped,
            "plan": {ids[rel]: hashlib.sha256(new).hexdigest() for rel, new in planned}}


def preview_snapshot(op):
    """inventory.preview(op)'s snapshot, without the in-op table refresh where preview has one
    (so the plan after it is the refresh's, as before phase 4)."""
    import inspect

    from decklab.lib import inventory
    if "refresh" in inspect.signature(inventory.preview).parameters:
        return inventory.preview(op, refresh=False)[0]
    return inventory.preview(op)[0]


def image_answer(name):
    """What a viewer's GET /accessory-img/<name>?v=<version> gives: {type, size, sha256} of the
    picture, at the address the page names it by (v from its sha256: accessories.image_version;
    any v for a picture the inventory doesn't have, which is 404 whatever v is). The pre-phase-4
    code (a --live or fixture golden dumped by GOLDEN_REV_P4's readers) has no v: its
    image_file(name) is called as it was."""
    import hashlib
    import inspect

    from decklab.lib import accessories, inventory
    from decklab.lib.api import accessories as api_accessories
    if "version" not in inspect.signature(api_accessories.image_file).parameters:
        data, kind = api_accessories.image_file(name)
        return {"type": kind, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    meta = inventory.current().image_meta(name) if isinstance(name, str) else None
    version = accessories.image_version(meta) if meta is not None else "0" * 8
    data, kind = api_accessories.image_file(name, version)
    return {"type": kind, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


# ------------------------------------------------------------------ the fixture (H2)
