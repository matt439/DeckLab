"""Finish an assembly plan with one atomic, revision-checked save of its decks."""
import hashlib
import json

from decklab.lib import accessories, decks, inventory, spaces
from decklab.lib.decks import assembled, standins
from decklab.lib.inventory import ops_decks, refresh

from . import assembly_sections, drafts, guard, saving
from .carddata import _require_cards
from .common import ApiError, _flag, _keys, _parse_body, _scrub
from .settings import _writer

CHANGED = "The decks or collection changed after this plan was checked. Refresh the plan and check it again."


def _fingerprint(snapshot, selected):
    # The selections are part of the receipt: changing the chosen version must
    # never reuse the confirmation of another list at the same inventory revision.
    text = json.dumps([snapshot.revision, snapshot.decks_revision, selected],
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def decorate(plan, selected, profile=False):
    """Add per-deck state and the whole-plan completion action, without writing."""
    snapshot = inventory.current()
    profile = guard.viewer() if profile is False else profile
    changed, denied = [], []
    for item in plan["decks"]:
        stored = snapshot.deck(item["id"])
        parsed = ops_decks.parsed_deck(stored)
        mutable = parsed is not None and parsed.space == spaces.HOME
        effective = assembled.version(parsed) if parsed else None
        desired = assembly_sections.selected_sections(plan, item["id"]) if mutable else None
        already = bool(parsed and parsed.status == "built" and effective == item["version"]
                       and not assembled.needs_install(parsed, item["version"], desired))
        repack = bool(parsed and standins.needs_install(parsed, item))
        editable = mutable and guard.allowed(profile, "deck.edit", parsed)
        item["completion"] = {"status": parsed.status if parsed else None,
                              "built_version": effective if parsed and parsed.status == "built" else None,
                              "sha256": stored.sha256 if stored else None,
                              "editable": bool(editable), "already_built": already, "repack": repack}
        if mutable and (not already or repack):
            changed.append(_review(item, parsed, profile, editable, desired))
            if not editable:
                denied.append(item["title"])
    reason = None
    if denied:
        reason = "You cannot mark these decks built: " + ", ".join(denied) + "."
    elif not changed:
        reason = ("These decks are already marked built." if any(d["completion"]["already_built"]
                  for d in plan["decks"]) else "Product decks and pairings are read-only here.")
    elif not plan["counts_confirmed"]:
        reason = "The card counts need checking before these decks can be marked built."
    elif not plan["ready"]:
        reason = "All cards must be available now before these decks can be marked built."
    plan["completion"] = {"fingerprint": _fingerprint(snapshot, selected), "review": True,
                          "can_mark_built": reason is None, "reason": reason, "decks": changed}
    return plan


def _review(item, parsed, profile, editable, selected_sections):
    """Only expose a kit's current values when its owner lets this viewer choose it."""
    result = {key: item[key] for key in ("id", "title", "version")}
    result.update(versions=["target", "owned"] if parsed.owned else ["target"],
                  owner=None, kit=None, kit_why_not=None)
    if item["build_scope"]["sideboard_intended"] or item["build_scope"]["return_count"]:
        result["build_scope"] = item["build_scope"]
        result["returns"] = item["returns"]
    if not guard.sees_kit(parsed, guard.accessory_owners(profile)):
        result["kit_why_not"] = "Only this deck's owner can choose its sleeves and deck box."
        return result
    result["owner"] = guard.holder_owner(parsed)
    if not editable:
        result["kit_why_not"] = "You cannot change this deck."
        return result
    try:
        guard.require_kit_choice(profile, parsed, {})
    except ApiError as error:
        result["kit_why_not"] = error.message
        return result
    sections = selected_sections
    result["kit"] = {"sleeves": parsed.sleeves or None, "deck_box": parsed.deck_box or None,
                     "need": accessories.sleeve_need(sections), "editable": True}
    return result


class _BuildPlan:
    """Normal deck saves, all or none, including final-pool table rewrites.

    Every rendered text is prepared before the write. The revision is checked
    inside the backend's transaction/lock, covering all reservations and supply,
    as well as the individual deck hashes checked by deck.save.
    """
    kind = "deck.save"

    def __init__(self, snapshot, items):
        self.revision = (snapshot.revision, snapshot.decks_revision)
        self.params = {"items": items}

    def run(self, snapshot):
        if (snapshot.revision, snapshot.decks_revision) != self.revision:
            raise inventory.Conflict(CHANGED)
        changed, kit_items = {}, []
        for item in self.params["items"]:
            # First make every selected holder built, preserving its current kit.
            # A single kit.set below then validates final assignments together,
            # so a box handoff or swap never depends on selection order.
            text = saving._with_kit(item["text"], snapshot.deck(item["deck_id"]))
            op = inventory.Op("deck.save", {"deck_id": item["deck_id"], "text": text,
                                              "base_sha256": item["base_sha256"],
                                              "allow_assembled": item.get("allow_assembled", False)})
            snapshot, summary = op.run(snapshot)
            changed.update(summary.changed)
            if item.get("kit_changes"):
                kit_items.append(item)
        if kit_items:
            owners = kit_items[0]["owners"]
            if any(item["owners"] != owners for item in kit_items):
                raise inventory.Invalid("The kit choices must belong to one viewer")
            op = inventory.Op("kit.set", {
                "holders": [{"id": item["deck_id"], "expected": snapshot.deck(item["deck_id"]).sha256}
                            for item in kit_items],
                "changes": [change for item in kit_items for change in item["kit_changes"]], "owners": owners})
            snapshot, summary = op.run(snapshot)
            for source, fields in summary.changed.items():
                changed.setdefault(source, []).extend(field for field in fields if field not in changed.get(source, []))
        return snapshot, inventory.Summary("Marked assembled decks built", {"decks": len(changed)}, changed)


def _kit_fields(plan, choices, profile):
    """Optional visible kit choices, confined to the decks this completion changes."""
    if choices is None:
        return {}
    if not isinstance(choices, dict):
        raise ApiError(400, "kit must map selected deck ids to sleeves and deck_box choices.")
    participants = {item["id"] for item in plan["completion"]["decks"]}
    if any(deck_id not in participants for deck_id in choices):
        raise ApiError(400, "Choose kit only for the decks being marked built.")
    inv, result = None, {}
    for deck_id, fields in choices.items():
        if not isinstance(fields, dict) or set(fields) != set(ops_decks.KIT_FIELDS):
            raise ApiError(400, "Each kit choice needs sleeves and deck_box (an accessory id or null).")
        parsed = ops_decks.parsed_deck(inventory.current().deck(deck_id))
        guard.require(profile, "deck.edit", parsed)
        guard.require_kit_choice(profile, parsed, fields)
        for key, value in fields.items():
            if value is None:
                continue
            if not isinstance(value, str) or not value or value != value.strip():
                raise ApiError(400, "A kit choice must be an accessory id or null.")
            if value == getattr(parsed, key):
                continue                    # retain an unchanged older free-text value
            inv = accessories.read() if inv is None else inv
            row = inv.rows_by_id.get(value)
            if row is None or row["kind"] != key:
                raise ApiError(400, f"Choose {'sleeves' if key == 'sleeves' else 'a deck box'} from the accessories list.")
        result[deck_id] = dict(fields)
    return result


def _texts(plan, profile, kit=None):
    """Prepare editor validation and installed stand-ins before one atomic write."""
    snapshot = inventory.current()
    kit = _kit_fields(plan, kit, profile)
    participants = {item["id"]: item for item in plan["decks"]}
    items, warnings = [], []
    for item in plan["completion"]["decks"]:
        stored = snapshot.deck(item["id"])
        parsed = ops_decks.parsed_deck(stored)
        guard.require(profile, "deck.edit", parsed)
        fields = {"status": "built"}
        fields.update(kit.get(item["id"], {}))
        if parsed.owned:
            fields["built_version"] = item["version"]
        elif parsed.built_version is not None:
            fields["built_version"] = None
        draft = drafts._read_draft({"fields": fields}, stored.kind, parsed)
        guard.require(profile, "deck.edit", guard.deck_after(parsed, draft.fields))
        if draft.blocks:
            raise drafts._blocks_error(draft.blocks)
        decks.apply_edit(parsed, None, None, draft.fields, saving._today(), drafts._bracket_names())
        participant = participants[item["id"]]
        try:
            assembled.install(parsed, item["version"], assembly_sections.selected_sections(plan, item["id"]),
                              force=standins.needs_install(parsed, participant))
        except decks.DeckFileError as error:
            raise ApiError(400, f"The physical build cannot be recorded: {error}") from None
        drafts._rule_warnings(draft, parsed)
        proposed = participants[item["id"]].get("standins")
        if proposed is not None:
            standins.install_stand_ins(parsed, item["version"], proposed["rows"], proposed["choices"])
        text = decks.render_deck_file(parsed)
        before = ops_decks.parsed_deck(stored)
        changes = saving._kit_changes(stored.id, before, parsed)
        if stored.id in kit:
            changes = [{key: value for key, value in change.items() if key != "loose"} for change in changes]
        items.append({"deck_id": stored.id, "text": text, "base_sha256": stored.sha256,
                      "allow_assembled": True,
                      "kit_changes": changes,
                      "owners": guard.accessory_owners(profile), "building": before.status != "built"})
        warnings.extend(draft.warnings)

    # Compute every affected table from the FINAL reservations, including the
    # selected decks themselves (refresh.in_op deliberately skips changed decks).
    try:
        after, _ = inventory.preview(_BuildPlan(snapshot, items))
    except ops_decks.DeckRefused as error:
        raise ApiError(error.code, str(error), **(getattr(error, "extra", None) or {})) from None
    except (inventory.Invalid, inventory.Conflict, inventory.Unavailable) as error:
        raise saving._refused(error) from None
    tables = {"written": [], "skipped": [], "error": None}
    try:
        with inventory.pinned(after):
            planned = refresh.plan_texts(only={spaces.HOME})
    except Exception as error:       # as the normal inventory table refresh: saved, with an explicit warning
        tables["error"] = refresh.public_error(error)
        planned = []
    by_id = {item["deck_id"]: item for item in items}
    for deck_id, title, _, text in planned:
        if deck_id in by_id:
            by_id[deck_id]["text"] = text
        else:
            by_id[deck_id] = {"deck_id": deck_id, "text": text,
                              "base_sha256": snapshot.deck(deck_id).sha256}
        tables["written"].append({"id": deck_id, "title": title})
    return list(by_id.values()), _scrub(warnings), tables


def mark_built(body):
    """POST /api/assembly/built {profile,decks:[{id,version}],fingerprint,confirmed:true,kit?}.

    Confirmation is the person's checked physical-card tasks (tokens and kit are
    optional). kit maps changed deck ids to {sleeves,deck_box}, each an accessory
    id or null; omitting it preserves the stored kit. All mutable changed
    participants are saved together, so transfers between selected decks cannot
    leave copies reserved twice. Synthetic product
    decks and pairings remain read-only. The result includes the fresh plan.
    """
    from . import assembly
    data = _parse_body(body)
    _keys(data, ("profile", "decks", "fingerprint", "confirmed"), ("kit",))
    profile = _writer(data)
    guard.require_sees_home_records(profile)
    if "kit" in data and not isinstance(data["kit"], dict):
        raise ApiError(400, "kit must map selected deck ids to sleeves and deck_box choices.")
    if not _flag(data, "confirmed"):
        raise ApiError(400, "Check every card task before marking these decks built.")
    _require_cards()
    with inventory.pinned():
        plan = assembly._preview(data["decks"], profile=profile)
        from .deck_aliases import reject_alias
        for choice in data["decks"]:
            reject_alias(choice["id"], profile)
        for item in plan["completion"]["decks"]:
            guard.require(profile, "deck.edit", ops_decks.parsed_deck(inventory.current().deck(item["id"])))
        if data["fingerprint"] != plan["completion"]["fingerprint"]:
            raise ApiError(409, CHANGED)
        if not plan["completion"]["can_mark_built"]:
            raise ApiError(409, plan["completion"]["reason"])
        built = plan["completion"]["decks"]
        items, warnings, tables = _texts(plan, profile, data.get("kit"))
        snapshot = inventory.current()
        saving.apply_op(_BuildPlan(snapshot, items), profile,
                        "mark built: " + ", ".join(item["title"] for item in built))
        return {"saved": True, "built": built, "plan": assembly._preview(data["decks"], profile=profile),
                "warnings": warnings, "tables": tables}
