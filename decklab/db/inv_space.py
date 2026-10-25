"""Member-space commands, registered by db.__main__ like the inventory commands.

Export writes a fresh directory. Remove previews or applies after all runtime,
export and lifecycle checks; recover resolves interrupted removal journals.
"""
import json

from decklab.db import cli_actor, space_export, space_remove


def register(sub):
    p = sub.add_parser("space", help="Export one member's data.")
    actions = p.add_subparsers(dest="action", required=True, metavar="action")
    sp = actions.add_parser("export", help="Export one member's cards and decks into a new folder.")
    sp.add_argument("space", metavar="SPACE", help="the member's space id (not home)")
    sp.add_argument("dir", metavar="DIR", help="a new folder outside the source repository")
    sp.add_argument("--dbname", help="the database to use instead of the settings' one (tests)")
    sp.add_argument("--results-dir", metavar="DIR", help="the Forge results folder (tests)")
    sp.set_defaults(func=_export)
    sp = actions.add_parser("remove", help="Remove a member after a matching export; --dry-run previews exact actions.")
    sp.add_argument("space", metavar="SPACE")
    sp.add_argument("--export", dest="export_dir", required=True, metavar="DIR", help="the matching v2 member export")
    sp.add_argument("--expect", required=True, metavar="SHA", help="the full exported snapshot SHA")
    sp.add_argument("-m", "--message", required=True, help="what and why")
    sp.add_argument("--reason", required=True, help="why this member's data would be removed")
    sp.add_argument("--dry-run", action="store_true", help="preview exact row/file actions without writing")
    sp.add_argument("--json", action="store_true", help="print the row/file plan as JSON (no retained record contents)")
    sp.add_argument("--dbname", help="the database to use instead of the settings' one (tests)")
    sp.add_argument("--results-dir", metavar="DIR", help="the Forge results folder (tests)")
    cli_actor.add_argument(sp)
    sp.set_defaults(func=_remove)
    sp = actions.add_parser("recover", help="Recover an interrupted removal from its durable journal.")
    sp.add_argument("operation", metavar="UUID")
    sp.add_argument("--dbname", help="the database to use instead of the settings' one (tests)")
    sp.add_argument("--results-dir", metavar="DIR", help="the Forge results folder (tests)")
    sp.set_defaults(func=_recover)


def _export(args):
    manifest = space_export.export_to(args.space, args.dir, dbname=args.dbname, results_dir=args.results_dir)
    print(f"Wrote {len(manifest['files'])} member files and manifest.json into {args.dir}.")
    print(f"Snapshot SHA: {manifest['snapshot_sha256']}")
    return 0


def _remove(args):
    if not args.message.strip() or not args.reason.strip():
        raise ValueError("Removal needs a non-blank message and reason")
    if not args.dry_run:
        from decklab.db import space_apply
        from decklab.lib.forge import lifecycle
        try:
            result = space_apply.apply(args.space, args.export_dir, args.expect, cli_actor.resolve(args),
                                       args.message, args.reason, dbname=args.dbname, results_dir=args.results_dir)
        except (lifecycle.LifecycleError, OSError) as exc:
            raise ValueError(str(exc)) from None
        print(f"Removed member space {result['space']!r}: {result['rows']} row(s), {result['files']} Forge file(s).")
        print(f"Removal operation: {result['operation']}")
        _reminders()
        return 0
    plan = space_remove.preview(args.space, args.export_dir, args.expect,
                                dbname=args.dbname, results_dir=args.results_dir)
    # Mixed record contents belong to their surviving spaces and never go in a
    # relayed preview. Pure helpers retain them only for testing the transform.
    public = {key: value for key, value in plan.items() if key != "retained_records"}
    if args.json:
        print(json.dumps(public, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    print(f"Preview only: {len(plan['rows'])} database row(s), {len(plan['forge_files'])} own-only Forge file(s).")
    for row in plan["rows"]:
        print(f"  {row['action']} {row['table']} {json.dumps(row['key'], ensure_ascii=False, sort_keys=True)}")
    for row in plan["forge_files"]:
        print(f"  delete Forge {row['path']} (SHA {row['sha256']})")
    for row in plan.get("maintenance", []):
        print(f"  {row['action']} {row['table']} {json.dumps(row.get('key', {}), sort_keys=True)}")
    print(f"Preserve {plan['preserved_related_forge_files']} mixed and {plan['preserved_unknown_forge_files']} "
          "unknown-provenance Forge file(s).")
    for line in plan["gates"] + plan["reminders"]:
        print(line)
    return 0


def _reminders():
    print("Remove this member's exact email address from Cloudflare Access's policy.")
    print("Remove this member's profile from decklab/config.json, then sync profiles.")


def _recover(args):
    from decklab.db import space_apply
    from decklab.lib.forge import lifecycle
    try:
        result = space_apply.recover(args.operation, dbname=args.dbname, results_dir=args.results_dir)
    except (lifecycle.LifecycleError, OSError) as exc:
        raise ValueError(str(exc)) from None
    print(f"Removal operation {result['operation']}: {result['state']} ({result['files']} Forge file(s)).")
    if result["state"] == "committed":
        _reminders()
    return 0
