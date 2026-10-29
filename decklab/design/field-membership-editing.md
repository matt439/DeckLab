# Audited home-field membership: E3-S23

This extends the existing read-only membership view. Checked identity, pure
policy, fixture-qualified persistence, selector integration (2026-10-29,
`forge/field_policy_overlay.py`) and the home-admin preview/save with its
Change the field control (2026-10-29, `api/field_choices.py`) are implemented.
Failing closed on an unreadable policy and database activation remain open.
Development uses supplied fixtures, without changing the household's field or
starting Forge games.

## Checked deck identity

A saved choice must follow a rename without transferring to a different deck
created later under the same name. The current deck ID, current text hash,
`rename_version` and import timestamp cannot independently prove that continuity.

The first foundation is an explicit PostgreSQL reader and a pure checker. One
read-only repeatable-read transaction captures the fresh persisted deck and alias
metadata, current row/text and bounded minimal revision metadata. Convenience
history readers are unsuitable here because they can open another transaction.
No stale, preview, file-backed or missing-schema snapshot supplies this proof.

The checker requires a unique contiguous history from revision 1 through the
current revision, a valid flattened home alias lineage, a legal A/M/D sequence,
and an exact latest revision/text match. Its immutable epoch is the historical
creation row's ID and revision. A first imported M with no change-set ID can
instead establish an explicitly labelled database baseline; this makes no claim
about the deck's origin before import. A later deletion and creation establish
a new epoch. Renames keep the original historical anchor.

The result contains only that epoch and a receipt naming the current canonical
ID, revision and text SHA-256. It relays no text, actor, audit message or kit.
Proof caps are 10,000 history rows, 5,000 current home IDs, 5,000 relevant aliases
and 2 MiB per current/latest text; they do not bound the existing full inventory
snapshot's database reads. Missing, capped, malformed or ambiguous evidence has
one fixed unavailable result, with no weaker fallback.

Normal retirement retains non-null aliases to the historical canonical ID, even
when it has no current deck. A later recreation can therefore still prove the
full lineage and establish its new creation epoch. If a supplied capture has
lost that linkage and has a revision gap, it remains unavailable. Unrelated
retired aliases cannot be joined to guess the missing prefix.

An internal same-connection capture also supports a caller-owned transaction.
It checks an active read-only repeatable-read/serializable transaction or an
already-held inventory advisory claim. It opens no connection or transaction,
acquires no lock and commits nothing. The caller must retain the claim and use
the connection exclusively. A future writer must recompute and compare the
identity inside its actual write transaction; parsing a saved epoch is not
proof that it still belongs to the current deck.

## Next implementation slices

### Persistence in source

Both stores expose `field_policy(format)` and `field_policy_apply(format,
expected_revision, expected_proof, rule, actor, message, reason=None)`. The write
returns `{changed, snapshot}`. Its exact proof contains the checked epoch,
current receipt, an explicit target/owned version and the played-list card hash.
The captured text is parsed directly and hashed without card-index, pilot,
configuration, pool, Git or engine lookups. Even a repeated policy intent must
recheck that full proof before confirming a no-op.

PostgreSQL owns a standalone READ COMMITTED audited transaction, obtaining the
shared inventory claim before the per-format lock and fresh source reads. It
uses one revision-checked policy UPSERT; a confirmed no-op rolls back its empty
audit. Missing schema and corrupt/unavailable state refuse rather than appearing
empty. Memory requires a supplied locked fixture source and holds its identity
through checking and mutation, with policy/audit rollback on failure.

Migration `0017_field_policy.sql` is present but unapplied. The row stores format,
positive revision and `{v, rules}` content. Exclusion reasons remain only in the
private home audit context. Export preserves the state outside inventory exports;
the invariant check validates syntax without discarding obsolete incarnations.
Activity projects fixed home-only summaries before generic admin handling, so
an outside admin cannot see the policy or its human reasons.

Storage does not authorize a request, change current field selection, start
games or provide an edit API. Browser policy revisions must use canonical decimal
strings, since the database range exceeds JavaScript's exact integer range.

### Selector integration (built 2026-10-29)

`field._field` asks `field_policy_overlay.prepare` for a plan after reading the
legacy directives and before its add/remove passes, then applies it after them.
Only HOME's field reads the policy. The format's current house decks are proved
together by `pg_deck_epoch.read_many` (one read-only repeatable-read transaction,
one snapshot load, read()'s bounded proof per deck); a proof counts only when its
receipt matches the pinned snapshot's revision and text hash, and only ready
proofs are cached, by inventory and decks revision. No store, a store without
policies, an empty policy and the missing 0017 table are today's field exactly.
A failed read or an unproved deck while rules exist keeps legacy selection for
those decks, adds a note naming no deck, and makes the membership trace and the
exclusion count unavailable. Exclusions re-notify the observer's parsed removals
with the policy-excluded IDs, so Rankings explains them as manual exclusions.

### Preview and save (built 2026-10-29)

`permissions` has a `field.edit` action: a named home admin, or a script naming
nobody; anyone else gets "Only an admin can change who's in the field." (or
"Choose who you are first."), naming nobody. Both routes check it first, before
any deck, policy or list read, then treat a hidden deck as missing.

`POST /api/field/policy/preview` {profile, id, version, mode} writes nothing. It
reads the format's policy (a missing 0017 table reads as empty, with
`ready: false` and the migrate command) and the stores' `field_policy_review`
proof: memory's explicit fixture source, or PostgreSQL's one read-only
repeatable-read transaction (`pg_field_policy.review`, `capture_on_connection`
in reader mode, no policy table needed). The answer gives the current choice
(`legacy` without an entry), the proposed rule, whether it would change, and
`expect: {revision, proof}`, the revision as a decimal string.

`POST /api/field/policy` {profile, format, revision, proof, mode, reason?}
builds the rule from the proof's epoch (Include takes its version) and calls
`field_policy_apply`, whose audited CAS rechecks revision and proof (409) in
its own write transaction. Its audit message names the deck id and format;
Exclude's required reason stays in the change's reason. A missing 0017 table
answers 503 naming `python -m decklab.db migrate`; the stores' own fixed
unavailable words pass through, any other database error gets the usual words.

The membership answer adds `can_edit` (a named home admin on a home field).
Its Change the field panel lists the format's home house lists, previews one
choice, keeps Save disabled until a changed, ready preview, needs a reason to
leave a deck out, drops late answers after a page, profile or route change,
keeps its List, Choice and reason fixed while a save is in flight (so the
save's answer is never dropped), and reads the membership again after a save.

### Remaining selection and editing work

The selector now implements the rules below, except the failed-read one: on a
failed policy read it keeps legacy selection (so a deck the saved policy
excludes can come back), adds a note naming no deck and makes the trace and
exclusion count unavailable. Failing closed is still open.

Use a per-format, revisioned overlay for current home house-deck incarnations.
Do not copy an entire legacy field into static saved rules: an unqualified
legacy addition follows the deck's current built-version rule, while qualified
additions/removals have different semantics. Unrelated, unsupported and retired
legacy directives retain their existing behavior and order.

- With no overlay entry, preserve the exact legacy rules.
- Include chooses the current incarnation's target or owned list explicitly.
- Exclude removes that incarnation from the selected home field.
- Use field rules retains a revisioned entry that masks its matching legacy
  directives and recomputes the normal automatic choice. Removing the entry
  would incorrectly revive an old manual exclusion.

The pure policy format is `{v: 1, format, revision, rules}`. Each rule has an
exact structured `epoch: {kind, deck_id, revision}` and `mode`; only Include has
an additional `version`. Normalize by the full epoch key, rejecting duplicates
rather than choosing a winner. The historical origin ID must belong to the
format's house-deck kind. Baselines have revision 1; creation revisions use the
identity proof's positive bounded range. These are syntax checks, not evidence
that the epoch still belongs to a current deck.

Policy revisions fit PostgreSQL's nonnegative bigint range. Revision 0 is an
empty initial policy; positive revisions remain after clearing. Check the
expected revision before detecting an identical no-op. A changed rule increments
once; an identical rule at the current revision does not, even at the maximum
revision. Overflow refuses an actual change. Retain obsolete epoch entries as
inert history, with a 5,000-rule cap and no automatic eviction. Updating an
existing entry at capacity remains possible. Public helper results are detached
copies, so neither transition nor lookup can mutate stored input through aliases.

Apply this overlay only to home's field, before membership traces, exclusion
counts and diagnostic notes observe the effective directives. Member fields,
products, pairings and chosen-opponent runs stay outside this first editing
slice. A recreated deck cannot inherit an old overlay; legacy raw-ID behavior
remains compatible independently.

The eventual write needs a dedicated home-admin permission, a reviewed current
list/version/hash/epoch receipt, a format-policy revision and one audited
transaction. Recheck revision before deciding a request is a no-op. Keep human
reasons out of public membership explanations, and add an explicit home-only
Activity boundary before generic admin handling. A failed policy read must not
masquerade as empty policy and revive an excluded deck (not yet built: today
the fallback is legacy selection, made visible by the note and unavailable
counts, but an excluded deck can still return).

Use the existing inventory claim before a format-specific lock; never upgrade a
shared inventory lock to exclusive. An already-held claim alone does not prove
that a repeatable-read snapshot began after a competing writer finished. The
first write slice must own an independent transaction, establish READ COMMITTED
before its audit insert, and read fresh evidence after obtaining the inventory
claim and format lock. Reject existing batches/transactions for this slice.
After a successful save, invalidate pending field reads before refreshing the
page. Refreshing membership starts no games.
Genuine PostgreSQL, unapplied migration activation and browser/device acceptance
remain separate qualification steps.
