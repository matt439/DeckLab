"""Pure, ordered self-hosting findings; adapters return codes, never public prose.

Core readiness describes these preflight checks, not a running server or the
integrity of household records. Optional files never establish game execution.
"""
from types import MappingProxyType

from decklab.lib.config_errors import syntax_message, valid_location


VERSION = 1
CHECKS = (
    ("runtime", "Python runtime", "core", ()),
    ("config", "Configuration", "core", ()),
    ("driver", "PostgreSQL driver", "core", ("runtime",)),
    ("database", "Database", "core", ("config", "driver")),
    ("cards", "Card cache", "core", ()),
    ("java", "Java runtime files", "optional", ("config",)),
    ("forge", "Forge installation files", "optional", ("config",)),
    ("ocr", "Photo scanning engine", "optional", ()),
    ("timezone", "Time zone", "optional", ("config",)),
    ("backups", "Backup folders", "optional", ("config",)),
)
SIMULATION_FILES = ("java", "forge")     # the optional checks optional_files_status sums up
CONFIG_WARNINGS = MappingProxyType({
    "config_unknown_role": ("One or more profiles have an unknown role and are treated as members.",
                            "Use admin or member for each role in decklab/config.json."),
    "config_no_admin": ("No usable admin profile is configured.",
                        "Choose an intended admin locally in decklab/config.json before using admin settings."),
})

# Each outcome contains only public, fixed wording, apart from validated JSON
# line/column integers. Submitted values, paths and exception messages never enter the report.
OUTCOMES = MappingProxyType({
    "simulations_not_set_up": ("not_configured", "Simulations not set up (optional, step 8).", None),
    "runtime_ready": ("ready", "The supported Python 3.14 runtime is selected.", None),
    "runtime_unsupported": ("needs_setup", "This runtime is outside the supported Python 3.14 setup.",
                            "Use Python 3.14 as described in SELF-HOSTING.md, then run the preflight again."),
    "config_ready": ("ready", "The local configuration and usable home profiles passed validation.", None),
    "config_missing": ("needs_setup", "The local configuration is missing.",
                       "Copy decklab/config.example.json to decklab/config.json and follow SELF-HOSTING.md step 4."),
    "config_invalid": ("needs_setup", "The local configuration is not valid for this setup.",
                       "Correct decklab/config.json using SELF-HOSTING.md step 4, then run the preflight again."),
    "config_unavailable": ("unverified", "The local configuration could not be read safely.",
                           "Check local access to decklab/config.json, then run the preflight again."),
    "config_profiles_invalid": ("needs_setup", "The configuration contains unusable profile entries.",
                                "Correct the profile entries in decklab/config.json before setup or profile sync."),
    "config_no_home_profile": ("needs_setup", "No usable home profile is configured for the local chooser.",
                               "Configure a home profile using SELF-HOSTING.md step 4."),
    "config_profile_pending": ("needs_setup", "A profile update needs recovery before this configuration can be used.",
                               "Run python -m decklab.db sync-profiles on the PC, then run the preflight again."),
    "config_override_active": ("needs_setup", "A configuration override prevents verification of the normal setup.",
                               "Clear DECKLAB_CONFIG_EXTRA for this preflight, then run it again."),
    "driver_ready": ("ready", "The PostgreSQL driver can be imported without executing virtual-environment startup files.", None),
    "driver_missing": ("needs_setup", "The PostgreSQL driver is missing from the selected runtime.",
                       "Create a matching .venv and install decklab/requirements.txt using SELF-HOSTING.md step 3."),
    "driver_unusable": ("unverified", "The PostgreSQL driver could not be imported successfully.",
                        "Review the matching .venv and reinstall decklab/requirements.txt using SELF-HOSTING.md step 3."),
    "driver_venv_mismatch": ("needs_setup", "The repository's .venv does not match the selected Python runtime.",
                             "Re-create .venv with the Python used for Deck Lab, following SELF-HOSTING.md step 3."),
    "database_ready": ("ready", "An app-role connection, the migration ledger and inventory/deck initialization markers passed.", None),
    "database_no_answer": ("needs_setup", "Nothing answered at the configured PostgreSQL host and port.",
                           "Check the PostgreSQL service (Get-Service postgresql* on Windows; systemctl status postgresql "
                           "on Linux), then run python -m decklab.db status on the PC."),
    "database_signin_failed": ("needs_setup", "PostgreSQL answered, but Deck Lab could not sign in.",
                               "Run python -m decklab.db setup on the PC; python -m decklab.db status names the cause."),
    "database_setup_needed": ("needs_setup", "PostgreSQL answered, but the database or login roles are not set up.",
                              "Run python -m decklab.db setup on the PC, then python -m decklab.db status."),
    "database_unavailable": ("unverified", "A database connection could not be verified; the cause is not classified as server downtime.",
                             "Run python -m decklab.db status on the PC for the cause; see SELF-HOSTING.md step 5."),
    "database_host_unsupported": ("unverified", "This preflight checks one database host at a time; the configured host form was not contacted.",
                                  "Review database.host and SELF-HOSTING.md step 5 before checking a single host."),
    "database_version_unsupported": ("needs_setup", "The database server is older than the supported PostgreSQL 16 setup.",
                                     "Use PostgreSQL 16 or later, following SELF-HOSTING.md."),
    "database_schema_missing": ("needs_setup", "The required database migration ledger is absent.",
                                "For a fresh install, follow SELF-HOSTING.md step 5 and run python -m decklab.db setup."),
    "database_migrations_pending": ("needs_setup", "The database has unapplied bundled migrations.",
                                    "Run python -m decklab.db migrate before starting the updated server."),
    "database_migrations_mismatch": ("needs_setup", "The recorded migration history does not match this checkout.",
                                     "Restore the unchanged migration files or review the database's migration history before continuing."),
    "database_schema_unavailable": ("unverified", "The database metadata could not be verified with the app role.",
                                    "Review local app-role access and database setup, then run the preflight again."),
    "database_uninitialized": ("needs_setup", "The inventory or deck initialization marker is missing.",
                               "Follow SELF-HOSTING.md's setup or restore guidance; do not treat an existing database as a fresh install."),
    "database_catalog_invalid": ("needs_setup", "The bundled migration catalog is missing, invalid or exceeds the checking limit.",
                                 "Restore the complete migration files for this checkout before checking the database."),
    "cards_ready": ("ready", "A compatible local card index passed the bounded read check.", None),
    "cards_missing": ("needs_setup", "The local card index is missing.",
                      "Run python -m decklab.lib.cards update, then run the preflight again."),
    "cards_invalid": ("needs_setup", "The local card index is damaged or incompatible.",
                      "Run python -m decklab.lib.cards update to rebuild the index."),
    "cards_unavailable": ("unverified", "The local card index could not be read safely.",
                          "Check local access to the card cache, then run python -m decklab.lib.cards update if needed."),
    "cards_oversized": ("unverified", "The local card index exceeds the bounded checking limit.",
                        "Review the local card cache before retrying; no rebuild or download was attempted."),
    "java_files_ready": ("ready", "Selected Java 21 or later runtime files are present; execution and compiler tools were not qualified.", None),
    "java_missing": ("needs_setup", "The selected Java runtime files are missing; simulations are optional.",
                     "Follow SELF-HOSTING.md step 8 to select a Java 21 or later runtime."),
    "java_incomplete": ("needs_setup", "The selected Java runtime files are incomplete; simulations are optional.",
                        "Review the selected Java installation using SELF-HOSTING.md step 8."),
    "java_unavailable": ("unverified", "Java runtime files were not verified; automatic discovery and execution were not performed.",
                         "Set forge_java or review the Java path described in SELF-HOSTING.md step 8."),
    "java_version_unknown": ("unverified", "The selected Java runtime's version could not be verified from local metadata.",
                             "Review the selected Java installation using SELF-HOSTING.md step 8."),
    "java_version_unsupported": ("needs_setup", "The selected Java runtime is older than Java 21; simulations are optional.",
                                 "Select Java 21 or later using SELF-HOSTING.md step 8."),
    "java_linked": ("unverified", "The selected Java runtime's path goes through a symbolic link, which this "
                    "preflight doesn't follow; simulations are optional.",
                    "Set forge_java to the real path, as readlink -f prints it (for example "
                    "/usr/lib/jvm/java-21-openjdk-amd64/bin/java rather than /usr/bin/java)."),
    "forge_files_ready": ("ready", "Forge jar and card-script files are present; archive contents and games were not qualified.", None),
    "forge_missing": ("needs_setup", "Forge installation files are missing; the core app does not require simulations.",
                      "Follow SELF-HOSTING.md step 8 to install the expected Forge build and set forge_dir."),
    "forge_incomplete": ("needs_setup", "Forge installation files are incomplete; simulations are optional.",
                         "Review the Forge jar and card-script files using SELF-HOSTING.md step 8."),
    "forge_invalid": ("needs_setup", "The selected Forge installation files could not be accepted.",
                      "Review the selected Forge folder using SELF-HOSTING.md step 8."),
    "forge_unavailable": ("unverified", "The selected Forge installation files could not be read safely.",
                          "Review local access to the selected Forge folder using SELF-HOSTING.md step 8."),
    "forge_linked": ("unverified", "The selected Forge folder's path goes through a symbolic link, which this "
                     "preflight doesn't follow; simulations are optional.",
                     "Set forge_dir to the real path, as readlink -f prints it."),
    "ocr_ready": ("ready", "An OCR engine for Scan cards and Scan token cards was found; no photo was read.", None),
    "ocr_missing": ("needs_setup", "No OCR engine was found, so Scan cards and Scan token cards offer only typed names; "
                    "scanning is optional.",
                    "On Linux install the tesseract-ocr package (sudo apt install tesseract-ocr); on Windows 10 or 11, "
                    "Windows' own engine needs Windows PowerShell."),
    "ocr_no_language": ("needs_setup", "Tesseract has no English language data; scanning is optional.",
                        "Install the tesseract-ocr-eng package, then run the preflight again."),
    "ocr_unusable": ("unverified", "An OCR engine was found but did not answer; scanning is optional.",
                     "Check that tesseract --list-langs runs, then run the preflight again."),
    "timezone_not_set": ("ready", "No timezone is set in config.json, so dates and the nightly run follow this PC's "
                         "own clock.", None),
    "timezone_matches": ("ready", "This PC's clock keeps config.json's timezone.", None),
    "timezone_differs": ("needs_setup", "This PC's clock doesn't keep config.json's timezone, so the dates Deck Lab "
                         "writes may be a day out.",
                         "Set this PC's time zone to the configured one (on Linux: sudo timedatectl set-timezone "
                         "followed by the zone's name), or correct \"timezone\" in decklab/config.json."),
    "timezone_invalid": ("needs_setup", "config.json's timezone isn't a time zone name.",
                         "Use a name such as Australia/Sydney (timedatectl list-timezones lists them on Linux)."),
    "timezone_unknown": ("unverified", "This PC has no data for config.json's timezone, so it can't be compared.",
                         "On Linux install the tzdata package; on Windows this check needs Python's tzdata "
                         "package, and Deck Lab's own dates use UTC+10 without it."),
    "backups_ready": ("ready", "The backup folder settings can be used here, and backup_dir is on a disk of its "
                      "own or backup_same_device_ok allows the same one; no backup was made.", None),
    "backups_local_only": ("ready", "No backup_dir is set, so each night's dump stays on this PC only; no backup "
                           "was made.", None),
    "backups_setting_invalid": ("needs_setup", "A folder setting in config.json's database block can't be used on "
                                "this PC, so backups, prune, the restore check or the export fail.",
                                "Give backup_dir, staging_dir, export_repo and pg_bin as absolute paths for this "
                                "system (python -m decklab.db backup names the one it refuses); see SELF-HOSTING.md "
                                "step 9."),
    "backups_unreachable": ("needs_setup", "backup_dir's folder (or the folder it would be made in) can't be "
                            "reached, so every backup's copy fails.",
                            "Mount the share or make the parent folder, then run the preflight again."),
    "backups_same_device": ("needs_setup", "backup_dir is on the same disk as the staging folder (is the NAS share "
                            "mounted?), so every backup, prune and restore check is refused.",
                            "Mount the share, or set \"backup_same_device_ok\": true in config.json's database "
                            "block if a second folder on this disk is really meant."),
    "probe_unverified": ("unverified", "This preflight check did not return a verified result.",
                         "Review the local setup and retry the preflight; no raw adapter error is included."),
})

ALLOWED = MappingProxyType({
    "runtime": frozenset({"runtime_ready", "runtime_unsupported"}),
    "config": frozenset({"config_ready", "config_missing", "config_invalid", "config_unavailable",
                         "config_profiles_invalid", "config_no_home_profile", "config_profile_pending", "config_override_active"}),
    "driver": frozenset({"driver_ready", "driver_missing", "driver_unusable", "driver_venv_mismatch"}),
    "database": frozenset({"database_ready", "database_unavailable", "database_no_answer", "database_signin_failed",
                           "database_setup_needed", "database_host_unsupported", "database_version_unsupported",
                           "database_schema_missing", "database_migrations_pending", "database_migrations_mismatch",
                           "database_schema_unavailable", "database_uninitialized", "database_catalog_invalid"}),
    "cards": frozenset({"cards_ready", "cards_missing", "cards_invalid", "cards_unavailable", "cards_oversized"}),
    "java": frozenset({"simulations_not_set_up", "java_files_ready", "java_missing", "java_incomplete", "java_unavailable",
                      "java_version_unknown", "java_version_unsupported", "java_linked"}),
    "forge": frozenset({"simulations_not_set_up", "forge_files_ready", "forge_missing", "forge_incomplete", "forge_invalid", "forge_unavailable",
                        "forge_linked"}),
    "ocr": frozenset({"ocr_ready", "ocr_missing", "ocr_no_language", "ocr_unusable"}),
    "timezone": frozenset({"timezone_not_set", "timezone_matches", "timezone_differs", "timezone_invalid",
                           "timezone_unknown"}),
    "backups": frozenset({"backups_ready", "backups_local_only", "backups_setting_invalid", "backups_unreachable",
                          "backups_same_device"}),
})


def report(probe, *, config_location=None, config_warnings=None, runtime_version=None, platform_name=None):
    """Call eligible probes once in order; every output field comes from this catalog.

    A provider returns a code string. The optional config_location callback returns
    only an already checked (line, column) tuple; config_warnings returns fixed warning
    codes without changing readiness or dependencies. Unknown values and ordinary exceptions
    fail closed; cancellation is deliberately not caught or converted into readiness.
    """
    checks, by_id = [], {}
    for ident, label, scope, dependencies in CHECKS:
        blocked = [dependency for dependency in dependencies if by_id[dependency]["status"] != "ready"]
        if blocked:
            code, status = "dependency_blocked", "blocked"
            message = "This check was not run because an earlier prerequisite is not ready."
            next_step = "Resolve the earlier prerequisite findings, then run python -m decklab.doctor again."
        else:
            try:
                code = probe(ident)
            except Exception:               # noqa: BLE001 - never publish adapter exception text
                code = "probe_unverified"
            if type(code) is not str or code not in ALLOWED[ident]:
                code = "probe_unverified"
            status, message, next_step = OUTCOMES[code]
            if code == "database_no_answer" and platform_name is not None:
                try:
                    if platform_name() == "darwin":
                        next_step = ("For PostgreSQL on this Mac, check brew services list (or Postgres.app). "
                                     "Then run python -m decklab.db status; see SELF-HOSTING.md step 5.")
                except Exception:
                    pass
            if ident == "runtime" and code == "runtime_unsupported" and runtime_version is not None:
                try:
                    version = runtime_version()
                    if type(version) is tuple and len(version) == 2 and all(type(n) is int and 0 <= n < 100 for n in version):
                        message = f"Python {version[0]}.{version[1]} is running; Deck Lab requires Python 3.14."
                except Exception:
                    pass
            if ident == "config" and code == "config_invalid" and config_location is not None:
                try:
                    location = config_location()
                    if type(location) is tuple and len(location) == 2 and valid_location(*location):
                        message = syntax_message(*location)
                except Exception:           # noqa: BLE001 - diagnostics cannot add arbitrary output or fail a report
                    pass
        row = {"id": ident, "label": label, "scope": scope, "status": status, "code": code,
               "message": message, "next_step": next_step, "blocked_by": blocked}
        if ident == "config" and code == "config_ready" and config_warnings is not None:
            try:
                warnings = config_warnings()
                if type(warnings) is tuple and len(warnings) <= len(CONFIG_WARNINGS) and all(
                        type(value) is str and value in CONFIG_WARNINGS for value in warnings):
                    row["warnings"] = [{"code": value, "message": CONFIG_WARNINGS[value][0],
                                        "next_step": CONFIG_WARNINGS[value][1]} for value in dict.fromkeys(warnings)]
            except Exception:               # noqa: BLE001 - optional diagnostics never publish adapter faults
                pass
        checks.append(row)
        by_id[ident] = row
    core = [row for row in checks if row["scope"] == "core"]
    optional = [row for row in checks if row["id"] in SIMULATION_FILES]
    core_ready = all(row["status"] == "ready" for row in core)
    exit_code = 0 if core_ready else 2 if any(row["status"] == "unverified" for row in core) else 1
    files = ("not_configured" if all(row["code"] == "simulations_not_set_up" for row in optional) else
             "present" if all(row["status"] == "ready" for row in optional) else "not_verified"
             if any(row["status"] in ("unverified", "blocked") for row in optional) else "incomplete")
    return {"version": VERSION, "core_ready": core_ready, "optional_files_status": files,
            "simulation_execution": "not_performed", "exit_code": exit_code, "checks": checks}


def text(result):
    """Render only a report constructed here; the CLI never renders adapter objects."""
    core = "ready" if result["core_ready"] else "not verified" if result["exit_code"] == 2 else "needs setup"
    lines = [f"Core preflight: {core}."]
    simulations_said = False
    status_words = {"ready": "READY", "needs_setup": "NEEDS SETUP", "unverified": "UNVERIFIED", "blocked": "NOT RUN"}
    for row in result["checks"]:
        if row["code"] == "simulations_not_set_up":
            if not simulations_said:
                lines.append("OPTIONAL Simulations not set up (optional, step 8).")
                simulations_said = True
            continue
        optional = " (optional)" if row["scope"] == "optional" else ""
        lines.append(f"{status_words[row['status']]} {row['label']}{optional}: {row['message']}")
        if row["next_step"]:
            lines.append("  Next: " + row["next_step"])
        for warning in row.get("warnings", []):
            lines.append(f"WARN {row['label']}: {warning['message']}")
            lines.append("  Next: " + warning["next_step"])
    files = {"present": "present", "incomplete": "incomplete", "not_verified": "not verified",
             "not_configured": "not set up"}[result["optional_files_status"]]
    lines.append(f"Optional simulation files: {files}. Simulation execution qualification: not performed.")
    lines.append("No installation, download, migration, schedule, service activation or game is performed by this preflight.")
    return "\n".join(lines)
