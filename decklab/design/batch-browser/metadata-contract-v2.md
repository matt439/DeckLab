# Staged draft contract v2: metadata groups

This changes only staged scratch input identity. No numbered migration, production
picker/scan wiring or live schema change is introduced.

## Existing semantics, not a new inventory policy

- `web/collection-scan.js:colScanSame` groups pending copies by set, collector number,
  finish, condition and language. `colScanCsv` sends each group to normal import.
- `lib/inventory/rules.py:parse_cards` accepts these separate incoming rows. The
  collection itself is one row per set/number/finish (`rules.ident`).
- `rules.merge_rows` delegates metadata to `copy_notes.merge`: different recorded
  values or unknown copies leave the aggregate field blank and retain counted
  `Copies: condition ...` / `Copies: language ...` observations. Blank means **not
  recorded**, never NM or English. This is shared by existing import/receipt paths.

V2 preserves the scan's separate input groups in the private draft and raw source.
The final inventory transformation is unchanged. Counted observations are marginal
condition/language breakdowns, not individual copy identities or a promised pairing
model; the original source still preserves supplied row pairings. We do not invent
per-copy storage semantics.

## Contract change

Draft rows are unique by `(set, collector_number, finish, condition, language)`.
Repeated copies with exactly that identity belong in one row with an absolute count.
Different conditions, languages, or blank metadata remain distinct groups. The
200-row cap is now described as 200 card groups, not 200 unique printings. Existing
quantity, byte and ambiguity bounds remain unchanged. No case/whitespace coercion or
metadata default is introduced; the existing adapter checks allowed recorded values.

V2 introduced `draft_contract: 2`; this candidate advertises v3, which retains the
same metadata identity and adds optional bounded evidence. A future editor must
preserve all groups and must not infer metadata for a new copy from matching printing
identity. No renderer or production scanner change is included in this candidate.

## Staged v1 fixtures: upgrade and rollback

There is no data rewrite. Every valid v1 draft is a valid v2 draft because v1 permitted
at most one row per printing/finish. Its content JSON, original-create digest,
revision and existing review token remain byte/semantically unchanged. Do not
re-save, re-hash, reconstruct UUIDs or synthesize condition/language on upgrade.
Existing completion receipts and matching retries remain untouched. Tests verify
initial digest/content/token preservation and successful legacy-shaped completion.
This is an additive source-contract upgrade, not a claim that an old deployed binary
or live migration has been exercised.

A downgrade is **not** generally safe after v2 metadata-distinct groups exist. A v1
validator refuses such a draft, and an old narrow renderer must not load/save it.
Keep routes closed; restore the v2 adapter to continue, or explicitly discard only
throwaway fixtures. Do not flatten groups, regenerate receipts, or silently discard
unknown copies to make v1 accept them. A future production UI must negotiate this
contract and preserve every group before route enablement. Version advertisement
alone is not an authorization check or a universal old-client safety mechanism.

## Proof

The disposable PostgreSQL suite stores NM/en, LP/ja and fully unknown groups of one
printing, rejects a repeated identical group without changing the saved draft,
compares committed output with the existing import transformation, verifies exact
raw-source rows and counted unknowns, and completes concurrently with one receipt /
import / audit change. Fresh-backend retries leave all effects unchanged. Metadata
edits invalidate review. Browser qualification is excluded from this backend candidate.
