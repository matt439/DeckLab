# Optional outbound backup privacy

E11-S69 adds two independent opt-ins. No installation changes settings, creates a
remote repository, installs encryption tools, generates keys or converts old backups.

```json
{
  "database": {
    "export_remote_scope": null,
    "backup_recipient": null,
    "backup_identity": null,
    "age_bin": null
  }
}
```

With all four unset, exports and dump copies retain their existing behavior.

## A home-only readable export

Set `export_remote_scope` to `home` and select a fresh `export_repo` folder. This
changes that dedicated export's current files and generated history, including
exports made with `--no-push`. It does not change the database or a separate full
dump. The home-only export includes home's profile rows (without email), collection,
token cards, dice/counters, loans, raw imports, deck lists/history, accessories and
their referenced pictures, products, orders, purchase queue, packing ticks,
Commander-night notes and games/plans recorded at home using only home decks.

All wishlists, member files and rows, profile emails, preferences, audit/mixed play
records and global revision/settings/visibility metadata are omitted. These
partial tables are a readable copy, not a restorable database. A new table requires
an explicit home-scope policy in the source and its fixture inventory.

The exporter refuses a repository with earlier unscoped/full history. It checks
scope markers at history roots and every marker change across local refs, with a
bounded review size, and rejects unmanaged or linked paths. Before pushing, an
existing remote must be empty or advertise only history already verified locally;
unknown branches/tags are refused without fetching or changing them. It never rewrites
history, deletes a remote or claims that removing today's files erased older
commits. Decide separately what to retain/remove on the old private git host and
where a new private remote should live. No remote is created or activated here.
Unsetting the scope does not widen a repository already marked home-only; choose
a separate full-export repository if that is intended.

## Encrypting copies to another disk

`backup_recipient` accepts one native age public recipient (`age1…` or `age1pq1…`).
Set `age_bin` to an absolute executable path, or leave it unset to find `age` on
PATH. age is an optional external CLI; Deck Lab's production Python dependencies
remain unchanged. The CLI's recipient/identity flags are documented in the
[official age manual](https://github.com/FiloSottile/age/blob/main/doc/age.1).

The local staging dump remains a PostgreSQL custom-format `.dump`. A configured
off-PC copy is written as `.dump.age.partial` ciphertext, checked for the age format
header, then renamed to `.dump.age`. A tool/key/output failure refuses the copy,
keeps the local dump and records failure. It never falls back to plaintext on the
destination. Existing plaintext NAS copies are not encrypted retroactively; their
retention and any manual disposal remain operator decisions. Ordinary pruning
recognizes both dump suffixes and unfinished copies.

The nightly encryption path needs the public recipient only. It does not read a
private key or require a passphrase. Native classic and post-quantum recipients are
accepted; the installed age version must support the selected type. Plugins, SSH
keys and passphrase encryption are deliberately outside this unattended protocol.

## Restoring encrypted copies

Set `backup_identity` to an absolute local key-file path on a machine authorized to
restore. Keep that file outside both source and export repositories, with access
limited to its operator. Its placement, secure transfer, durable offline copy and
whether the nightly machine should hold a key are explicit deployment decisions.
Scheduled restore checks require access to the matching identity; keeping it only
offline means automated checks of NAS ciphertext will refuse until it is supplied.

`db status` passively warns when encrypted backups are configured but the key file
or CLI is missing. It does not read the key or run age. `restore-check` and
`db restore` accept encrypted copies, validate a bounded native identity file and
send the identity to age over stdin, never as a command-line argument or log text.
Decryption uses an OS-private temporary directory outside the NAS; cleanup runs on
normal and failed exits. Existing restore guards, row/content comparisons and
database rename protection remain in place. Plain dumps need no identity or tool.
Do not submit configuration, identity files, dumps or unredacted logs to this public repo.

The CLI has a five-minute timeout, no shell and no interactive input. Failures use
fixed guidance, excluding tool stderr and key contents. Source fixtures use a fake
command protocol and synthetic bytes; no real encryption, key, export, push, NAS
copy or restore is part of source qualification. A matching-key round trip on an
authorized deployment remains an operational acceptance check.
