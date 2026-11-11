# Unfinished server runs

E3-S47 keeps an unfinished field, chosen-group, gauntlet or variant request in a
private local journal before accepting it into the server's queue. It never
starts work on startup or on a timer. The run activity icon's details offer
**Play the rest** and **Dismiss** only to the named person who started it.

The journal is under `decklab/data/forge/run-journal/`, outside the database and
its exports. Each starter has a separate folder, selected before reading any
record. It contains the original accepted request (including a variant's list),
resolved budget/sample and fingerprints of the saved lists, engine and plan.
These are private cache files, not public diagnostics. A response contains only
the starter's opaque offer ID, current visible deck title/link, time and whether
resuming is possible. There is no script or admin override. Revoking access to
any participant hides the whole offer; failed fresh visibility reads disclose
no offers and never reuse a cached Public grant.

An accepted request is written with file fsync and atomic replacement before a
worker can see it. OS-held session leases distinguish another live server from
a departed one without enumerating processes. Normal completion, a person's
Stop and an ordinary failed job remove the offer. Server shutdown retains an
interrupted receipt; a crash releases its session lock. Missing/unreadable lease
evidence is unknown, so it cannot authorize a resume. The starter may still
explicitly dismiss their own inactive or unknown receipt. Dismiss leaves saved
game checkpoints intact.

Play the rest re-enters the original API handler. It checks current identity,
deck visibility and ordinary run permissions, simulations policy, current saved card lists,
engine and participants, then atomically claims the receipt before enqueueing.
The backend replans from its normal checkpoints. A gauntlet keeps its accepted
saved sample instead of drawing another, and a More variant keeps its original
prior-look boundary. Completed checkpoints need no new run and their receipt is
removed. Changed or unverifiable inputs require a new deliberate run rather
than substituting a different list or engine. Existing member-removal writer
claims and departed-space guards also cover journaled coordinators.

Per starter, the journal allows at most 128 receipts, 512 KiB per receipt and
8 MiB total. Failed initial persistence refuses the start. Later bookkeeping
failures emit fixed PC log wording; they do not block a person's Stop or change
the existing worker result. Timers are bounded reads marked as polls and never
wake the PC. Buttons remain tied to their original profile, route and mounted
details; stale replies cannot repaint a successor page or change drafts.

`python -m decklab.update` uses the existing local named-home-admin restart
preview before stopping or restarting a running server. It reports only counts
and types of busy work. It refuses an unknown preview too. `--force` explicitly
allows interruption or an unverified busy state; it bypasses only this busy
check, preserving the updater's other guards. The flag follows the post-pull
handoff. No new stop, restart, scheduler or automatic-resume endpoint is added.

Qualification uses synthetic temporary journals, fake coordinators/checkpoints,
fake HTTP transport and the real page scripts with a deterministic DOM. It does
not perform a real Forge run, server restart, member removal, disk-fault test or
power-loss test. A real crash/restart round trip remains a separate operational
qualification; no service or live data is changed by shipping this source.
