# Audited home-field membership: E3-S23

This extends the existing read-only membership view. The implementation is being
built in bounded slices; membership writes, database activation and UI editing
remain open. Development uses supplied fixtures, without changing the household's
field or starting Forge games.

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
masquerade as empty policy and revive an excluded deck.

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
