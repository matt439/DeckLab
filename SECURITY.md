# Security boundaries

Deck Lab is a private household/member app whose code is public. Real profiles,
email addresses, domains, Access credentials, inventories, decks, games and
backups do not belong in this repository. See the privacy rules in [AGENTS.md](AGENTS.md).
Do not post those records, configuration files, secrets or unredacted logs in public issues.
Use the repository's private vulnerability-report option when available; otherwise ask
for a private reporting channel without including the sensitive details.

## Listeners and identity

The home listener accepts loopback, private/link-local home addresses and explicitly
configured trusted networks. It rejects Cloudflare headers and tunnel host names, so
pointing a tunnel at this listener does not create an anonymous administration route.
The home chooser offers only the household profiles. Choosing a home profile is an
accepted trust boundary: another client on that trusted network can choose the same
home identity. This is not per-person password authentication. Do not expose that
listener directly to the internet or add untrusted networks to its allowed ranges.

The separate tunnel listener verifies Cloudflare Access signatures, issuer, audience,
expiry and configured profile aliases. A member with a separate space uses this
listener, including from home Wi-Fi. A loopback address or script header never bypasses
the tunnel listener's sign-in checks. Both listeners enforce the selected profile's
permissions on requests; a remote administrator does not gain another space's inventory.

A trusted script is code outside a request, or a home-listener request from loopback
with exactly one `X-Deck-Lab-Script: 1` header and no viewer. Linux additionally checks
that the connecting socket belongs to the server's Unix user. Off Linux, an optional
configured `script_secret` also requires exactly one matching
`X-Deck-Lab-Script-Secret` header. Without that setting the existing loopback rule is
preserved. A named request retains that profile's rights. Profile-private wishlists and
kept drafts retain their own API owner rules; CLI administration is a separate trusted
operator interface. Never place the secret in a URL, web storage or browser code.

## Data visibility and writes

- Collections, token cards, decks and games are private to their space. An admin has
  no override for another space's private records. Refusals do not identify hidden
  people or content; a hidden deck answers like a missing deck.
- Home orders, receipts, products, shopping and packing records stay within home.
  Home members may read those records; their administrative writes require the
  relevant home-admin permission.
- Accessories and their saved pictures follow their owner, with shared home kit
  available to the home profiles. Another owner's Public kit remains read-only.
- Owner-controlled Public switches grant read-only access to signed-in viewers.
  Publishing a deck does not publish its private inventory counts, token packing,
  table state or kit. Public read access never grants a write.
- Activity and game views filter through the requesting space and per-row owner
  rules. Account/maintenance controls and anonymous run-stop controls have explicit
  administrative policies; they do not publish private deck or inventory contents.
- Writes retain method, origin/header, body-size, identity, revision and operation
  checks. Starting a simulation additionally follows the saved simulations policy.
  Native runs and live deployment are separate operational actions.

Static app assets, symbols and public card/reference data use the listener's entry
policy. In particular, `/img/{set}/{number}/{size}` keeps its existing policy: a named
viewer is not required on the home listener, while the tunnel still requires Access.
This GET may populate the public Scryfall image cache. It reads no inventory and is
not a publication mechanism for accessory pictures. Requiring a viewer for this
cache route remains a separate policy decision.

`POST /api/errors/report` is a separate, narrowly bounded operational-metadata
exception to named write authority. It retains the same-origin JSON/header checks,
accepts at most 2 KiB and only a 32-hex reference, an enumerated page category and
an enumerated error type. The server supplies the time. It stores no actor, profile,
IP address, message, file name or deck identifier; browser reports never send those
fields. The process accepts at most 30 reports per minute, and the local diagnostic
cache keeps at most 200 events in 128 KiB. This endpoint grants no inventory, state
or account permission. `GET /api/settings/errors` requires a named home admin;
anonymous scripts do not bypass this rule. Offline, rate-limited or unreadable storage
can leave a browser reference only on that device. Reports are advisory and are not
trusted audit evidence. Unexpected server errors receive the same safe references;
full tracebacks stay only in the operator's local server log.

Optional `alerts` is disabled unless the operator supplies an HTTP(S) address. A
nightly completion or the watchdog's first give-up transition sends only fixed step
names and `ok`/`failed`, with a five-second socket timeout, no redirect following and
no environment proxy. No profile, inventory, message or error text is sent. The one
exception is a failed `shrink` step (E11-S87, off unless `database.shrink_warn` is
true), which carries one bounded line of whole-table names, row counts and the earlier
dump's date, never a space, row or card. The
configured address can itself contain a private monitor token: keep it in local
configuration, never source or a public log. Enabling a monitor and exercising a
real endpoint remain explicit operator actions.

## Route review and checks

`GET /api/changes` gives unnamed requests (scripts included) no data. A named
viewer receives opaque content tokens for their own space's inventory/decks and
the deck projections already visible in the library. Public deck signals exclude
private inventory tables/prose and unreadable kit; the endpoint introduces no
Public collection polling for another space. No ids, counts, actors or global
revision numbers are returned. Unreadable/stale data or a failed fresh visibility
read is explicitly unverified, with no cached Public fallback. Successful JSON
answers may carry the same bounded `X-Deck-Lab-Changes` baseline only after their
inventory snapshot was already loaded. A separate write-acknowledgement header
requires a completed inventory operation with recorded changes; a dry check,
preview or kept draft cannot acknowledge an unseen save. Browser checks use the poll header and
disable wake hops; they neither reload nor save a draft. Reload is an explicit
current-page action, retaining the existing editor reapply/permission checks and
leaving open collection edits intact.

[`feature_routes.ACCESS`](decklab/lib/feature_routes.py) declares an access class for
every concrete feature method/path. `LEGACY_ACCESS` is the reviewed inventory of the
older routes still in `Handler._route`, including dynamic profile and picture paths.
GET declarations include their HEAD alias. The metadata documents policy; existing
handlers remain the permission engine. There is no prefix-based default access class.
An undeclared feature route fails closed, and fixture checks reject missing metadata.

Before adding or changing a route:

1. Declare its method/path and reviewed access class. Explain any `open` classification;
   public source data does not justify exposing household-derived fields.
2. Apply the existing viewer, space, deck and accessory-owner checks before reading
   private contents or disclosing existence. Preserve hidden/missing equivalence.
3. Require explicit write authority, method/origin/body limits and fresh revision
   receipts. Public visibility must not become write permission or an admin override.
4. Extend the table probes with a meaningful private target and valid request shape.
   A syntax/validation error alone is not evidence that a permission guard ran.
   Keep native work, external fetches and actual writes out of these probes.
5. Run `python scripts/test_fixtures.py decklab.tests.test_route_access
   decklab.tests.test_feature_routes decklab.tests.test_script_rule
   decklab.tests.test_server_access`, plus the feature's successful-write and privacy tests.
   The table uses disposable files/memory and fake engine protocols; the existing
   area tests cover complete reviewed writes, Public projections and operation receipts.
6. For schema changes, review privacy/export/restore implications, add the disposable
   database rollback entry and update the migration inventory below. Do not apply a
   migration to household data as part of source validation.

The table probes cover nobody, a tunnel member and another home profile. Private
targets additionally include a named home admin to verify the absence of a cross-space
override. Filtered lists are checked for a seeded private sentinel. Generic unsupported
Undo is checked against a missing source so its refusal cannot disclose existence.
HTTP integration tests separately cover listener/JWT, loopback script, profile and
origin boundaries. These checks do not replace feature-specific positive tests or
real-device, production durability and native-engine qualification.

## Migration inventory

This is the source schema inventory, not a claim about which migrations are installed
on any server. The route-access fixture check fails when a source migration is absent here.

- `0001_foundation.sql`
- `0002_audit_hardening.sql`
- `0003_personal_state.sql`
- `0004_inventory.sql`
- `0005_gate_runs.sql`
- `0006_decks_accessories.sql`
- `0007_check_runs.sql`
- `0008_visits.sql`
- `0009_packing_ticks.sql`
- `0010_deck_aliases.sql`
- `0011_commander_night.sql`
- `0012_visibility.sql`
- `0013_space_departure.sql`
- `0014_product_token_cards.sql`
- `0015_order_check_links.sql`
- `0016_collection_locations.sql`
- `0017_field_policy.sql`
- `0018_deck_drafts.sql`
- `0019_new_deck_drafts.sql`
- `0020_dice_counters.sql`
- `0021_shop_postage.sql`
- `0022_pricing_setting.sql`
- `0023_nightly_receipts.sql`
- `0024_card_loans.sql`
- `0025_listing_preferences.sql`
- `0026_watchlist_buy_under.sql`
- `0027_deck_line_categories.sql`
