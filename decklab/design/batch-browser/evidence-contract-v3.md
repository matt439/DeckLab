# Staged draft contract v3: minimal scanner evidence

V3 adds an **optional** `evidence` object to private scratch content. There is no SQL
schema change, numbered migration, production route, feature flag or picker wiring.
Every old valid v1/v2 JSON payload remains accepted unchanged, with its digest and
review token intact. Successful candidate HTTP responses advertise draft_contract 3.

## Bounded content

Evidence version 1 contains only:

- `next_scan_id`: positive integer <=1,000,000, greater than all retained ambiguity IDs;
- `ambiguities`: up to 30 `{source_id,label,language,proposals}` objects. Labels exactly
  match the draft's unresolved-label array. IDs are unique and session-local to this
  batch; candidate selection still requires user confirmation;
- `provenance`: up to 200 ordered `{input_index,row_index,quantity,origin,choices}`
  entries. Input indices are contiguous snapshot-local lineage, row indices point at
  confirmed groups, and source quantities sum exactly to each group's count. Origin
  is explicitly `not recorded by existing pending state`, never invented scan/manual
  origin or physical-copy ownership.

Each proposal/choice accepts only name, set, collector_number, set_name, finish,
language, known recognition-kind (`name`, `number`, `name and number`) and allowed
finish alternatives. Text is bounded to 160 characters without newline/NUL; choices
are at most 200 per source. Evidence is at most **64 KiB**, within the unchanged
256 KiB total-content limit. Excess input is rejected, never truncated. Unknown keys,
photos, raw OCR, error-message blobs, URLs, prices and arbitrary provenance are refused.
Stored candidates are not trusted authority to import: the existing printing/finish
validator still checks confirmed rows at review/commit.

## Persistence, resume and deletion

The existing transaction participant saves evidence with the draft under the same
owner/space/revision contract. Evidence edits change the content digest and invalidate
review. Saving an existing evidence-bearing draft without evidence is refused, so an
older or narrower editor cannot silently erase it. Resolving a pending item must update
its ambiguity record and label together; provenance must continue to match confirmed
quantities. No implicit evidence-drop operation is provided. Explicit whole-batch
discard remains available through its existing contract.

Evidence is private scratch, included in member-removal fingerprints and deleted with
that member, but absent from personal/general export artifacts. It is erased alongside
draft content on completion/discard, not copied into receipts, inventory notes, or raw
collection source. Only confirmed card facts enter normal inventory/raw import. This
is resume evidence, not an indefinite photo-recognition history.

This dormant backend candidate excludes the experimental bridge and browser fixtures.
A future consumer must restore every source row/candidate/counter from a server-validated
owned draft and negotiate contract support. Neither scanner save/resume nor any other
end-user persistence control is enabled by this candidate.

## Compatibility and qualification

There is no rewriting of old drafts, initial digests or receipts. Downgrading a new
v3 evidence draft into a v2 validator/editor is unsafe; keep it on a compatible staged
adapter or explicitly discard disposable fixtures. Existing lifecycle tables already
fingerprint JSON content; no new external store or cascade is introduced.

Pure tests cover allowlisting, size/version/identity bounds, matching provenance counts,
old payload compatibility. Disposable PostgreSQL tests
cover actual save/read, omission refusal, pending-review refusal, evidence-only stale
review, completion retry, export privacy, fingerprint changes and actual member removal.
Browser/bridge qualification remains outside this backend candidate. This is not a
production scanner/browser-auth/native-phone integration proof.
