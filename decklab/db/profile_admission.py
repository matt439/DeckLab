"""Refuse new member identities that could inherit retained private records.

The caller holds the profile-config claim and an exclusive inventory claim across
database creation and config publication. Forge's exclusive claim is held for the
same interval. These checks never remove old records or inspect OS processes.
"""
from contextlib import ExitStack, contextmanager
import json
import re

from decklab.lib import profiles, spaces
from decklab.lib.profile_config import InvalidProfileEdit, PendingProfileEdit


USED = "That member id has existing records or history. Choose a new id; nothing was saved."
FORGE_USED = "That member id has existing Forge records. Choose a new id; nothing was saved."
FORGE_UNAVAILABLE = "Forge records could not be checked safely. Check them locally before adding a member."
FORGE_PENDING = "Forge records are busy or need member-removal recovery. Finish that work before adding a member."
KEY = re.compile(r"[0-9a-f]{64}\Z")
MAX_METADATA = 8 * 1024 * 1024


def validate(member_id, name, email=None):
    """Validate a new own-space identity; the writer separately validates email."""
    if not profiles.valid_id(member_id) or member_id in profiles.RESERVED_IDS | profiles.RESERVED_SPACES:
        raise InvalidProfileEdit("Use a non-reserved member id: lowercase letters, digits and single hyphens, up to 40 characters.")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120 \
            or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise InvalidProfileEdit("Enter a member name of 1 to 120 characters without control characters.")
    return name.strip()


_MEMBERSHIP = """
with requested as (select %s::text as member_id)
select exists (
    select 1 from space, requested where id = member_id
    union all select 1 from profile, requested where id = member_id or space_id = member_id
    union all select 1 from profile_email, requested where profile_id = member_id
)
"""

_PRIVATE = """
with requested as (select %s::text as member_id)
select exists (
    select 1 from collection_card, requested where space_id = member_id
    union all select 1 from token_card, requested where space_id = member_id
    union all select 1 from collection_import, requested where space_id = member_id
    union all select 1 from deck, requested where space_id = member_id or split_part(id, '/', 1) = member_id
    union all select 1 from deck_text, requested where split_part(deck_id, '/', 1) = member_id
    union all select 1 from deck_line, requested where split_part(deck_id, '/', 1) = member_id
    union all select 1 from deck_revision, requested
        where split_part(deck_id, '/', 1) = member_id or actor = member_id
    union all select 1 from deck_alias, requested
        where split_part(alias_id, '/', 1) = member_id or split_part(deck_id, '/', 1) = member_id
    union all select 1 from wishlist_entry, requested where profile_id = member_id
    union all select 1 from profile_setting, requested where profile_id = member_id
    union all select 1 from simulation_mode, requested where set_by = member_id
    union all select 1 from play_record, requested where content->>'space' = member_id
        or exists (select 1 from unnest(deck_ids) d where split_part(d, '/', 1) = member_id)
        or exists (select 1 from jsonb_path_query(content, '$.**.id') d
                   where split_part(d #>> '{}', '/', 1) = member_id)
    union all select 1 from ops.visit_day, requested where profile_id = member_id
    union all select 1 from ops.visit_page, requested
        where profile_id = member_id or split_part(deck_id, '/', 1) = member_id
    union all select 1 from accessory, requested where owner = member_id
)
"""

_AUDIT = """
with requested as (select %s::text as member_id), prior_rows as (
    select r.table_name, value.data from audit.row_change r
    cross join lateral (values (r.row_key), (r.before), (r.after)) value(data)
    where r.change_set_id is distinct from %s::bigint
)
select exists (
    select 1 from audit.change_set, requested
        where actor = member_id and id is distinct from %s::bigint
    union all select 1 from prior_rows r, requested where
        r.data->>'space_id' = member_id or r.data->>'profile_id' = member_id or r.data->>'owner' = member_id
        or r.data->>'set_by' = member_id
        or (r.table_name in ('space', 'profile') and r.data->>'id' = member_id)
        or split_part(r.data->>'deck_id', '/', 1) = member_id
        or split_part(r.data->>'alias_id', '/', 1) = member_id
        or (r.table_name = 'deck' and split_part(r.data->>'id', '/', 1) = member_id)
        or (r.table_name = 'play_record' and (
            r.data->'content'->>'space' = member_id
            or exists (select 1 from jsonb_path_query(r.data, '$.**.id') d
                       where split_part(d #>> '{}', '/', 1) = member_id)
            or exists (select 1 from jsonb_array_elements(
                case when jsonb_typeof(r.data->'deck_ids') = 'array' then r.data->'deck_ids' else '[]'::jsonb end) d
                where split_part(d #>> '{}', '/', 1) = member_id)))
)
"""


def require_unused(cur, member_id, *, created_change_set_id=None):
    """Check only existence, under the caller's exclusive inventory DB claim.

    Recovery separately verifies its exact new membership and INSERT audit. It
    may then exempt those current membership rows and only its own change set;
    every other current/private/history/departure check still applies.
    """
    validate(member_id, "Member")
    if created_change_set_id is not None and (type(created_change_set_id) is not int or created_change_set_id < 1):
        raise InvalidProfileEdit(USED)
    if created_change_set_id is None and cur.execute(_MEMBERSHIP, (member_id,)).fetchone()[0]:
        raise InvalidProfileEdit(USED)
    if cur.execute(_PRIVATE, (member_id,)).fetchone()[0]:
        raise InvalidProfileEdit(USED)
    for table, column in (("visibility", "owner"), ("space_departure", "space_id")):
        if cur.execute("select to_regclass(%s) is not null", ("public." + table,)).fetchone()[0]:
            # Identifiers are fixed pairs above; submitted values are always parameters.
            if cur.execute(f"select exists (select 1 from {table} where {column} = %s)", (member_id,)).fetchone()[0]:
                raise InvalidProfileEdit(USED)
    if cur.execute(_AUDIT, (member_id, created_change_set_id, created_change_set_id)).fetchone()[0]:
        raise InvalidProfileEdit(USED)


def _belongs(value, member_id):
    if not isinstance(value, str):
        return False
    candidate = value.removeprefix("variant:").split("@", 1)[0]
    try:
        return spaces.split_deck_id(candidate)[0] == member_id
    except ValueError:
        return False


def _legacy_namespace(value, member_id):
    """A parsed unknown record may pass only when no string/key names the namespace."""
    if isinstance(value, str):
        return value == member_id or bool(re.search(r"(?:^|[^a-z0-9-])" + re.escape(member_id) + r"/", value)) \
            or "field:" + member_id + ":" in value
    if isinstance(value, list):
        return any(_legacy_namespace(item, member_id) for item in value)
    if isinstance(value, dict):
        return any(_legacy_namespace(key, member_id) or _legacy_namespace(item, member_id)
                   for key, item in value.items())
    return False


def _forge_files(claim, member_id):
    from decklab.lib.forge import lifecycle
    root = claim.root
    if not root.exists():
        return
    for folder, field in ((root, False), (root / "paired", False),
                          (root / "paired" / "tests", False), (root / "field", True)):
        lifecycle._ordinary(folder)
        for path in sorted(folder.glob("*.json")):
            if not field and not KEY.fullmatch(path.stem):
                continue                  # not a path a saved-result/variant reader accepts
            lifecycle._ordinary(path, directory=False)
            if field and re.search(r"-(?:Constructed|Commander)-" + re.escape(member_id) + r"$", path.stem):
                raise InvalidProfileEdit(FORGE_USED)
            value = _read_metadata(path)
            if any(_belongs(ref, member_id) for ref in lifecycle.references(value)) \
                    or _legacy_namespace(value, member_id):
                raise InvalidProfileEdit(FORGE_USED)


def _read_metadata(path):
    before = path.stat()
    if before.st_size > MAX_METADATA:
        raise InvalidProfileEdit(FORGE_UNAVAILABLE)
    with path.open("rb") as stream:
        content = stream.read(MAX_METADATA + 1)
    after = path.stat()
    if len(content) > MAX_METADATA or len(content) != after.st_size \
            or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise InvalidProfileEdit(FORGE_UNAVAILABLE)
    value = json.loads(content)
    if not isinstance(value, dict):
        raise InvalidProfileEdit(FORGE_UNAVAILABLE)
    return value


@contextmanager
def forge_claim(member_id, results_dir=None):
    """Hold an exclusive cooperative Forge claim through creation/publication.

    Invalid JSON at a readable result path cannot establish namespace absence;
    parsed legacy objects with no occurrence of that namespace may pass.
    """
    from decklab.db import space_journal
    from decklab.lib.forge import lifecycle
    validate(member_id, "Member")
    with ExitStack() as stack:
        try:
            claim = stack.enter_context(lifecycle.maintenance(results_dir))
            if member_id in lifecycle._departed(claim):
                raise InvalidProfileEdit(USED)
            if space_journal.pending(claim):
                raise PendingProfileEdit(FORGE_PENDING)
            _forge_files(claim, member_id)
        except lifecycle.LifecycleError as exc:
            if str(exc) in (lifecycle.BUSY, lifecycle.PENDING):
                raise PendingProfileEdit(FORGE_PENDING) from None
            raise InvalidProfileEdit(FORGE_UNAVAILABLE) from None
        except (OSError, ValueError, RecursionError) as exc:
            if isinstance(exc, (InvalidProfileEdit, PendingProfileEdit)):
                raise
            raise InvalidProfileEdit(FORGE_UNAVAILABLE) from None
        yield claim
