"""Qualify batch participant on an isolated disposable PostgreSQL cluster only.

Usage: <python-with-psycopg> scripts/test_collection_batch_pg.py --pg-bin PATH
Never reads DeckLab config, credentials or the configured server. Creates a new
cluster under the OS temp directory, loopback on an OS-selected free port, with
synthetic identities only. Stops it in finally; retains its directory for diagnosis.
Also qualifies actual inventory/audit writes on the existing migration chain,
and tests the candidate HTTP adapter through a fixture-only loopback dispatch.
Normal routes stay unregistered and no deployable migration is promoted.
"""
import argparse
import os
import shlex
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def inventory_proof(root, connect_role, restart):
    """Actual migrations and app-role writes, still only in this fresh temp cluster."""
    from unittest import mock

    from decklab.db import conn as db
    from decklab.db import migrate, setup
    from decklab.tests import test_collection_batch_inventory as tests
    from decklab.tests.test_inventory_contract import fixture_world
    with connect_role("super", "postgres", autocommit=True) as c:
        for role in ("decklab_owner", "decklab_app", "decklab_ro"):
            c.execute(f"create role {role} login")  # fixed fixture constants
    def prepare(dbname):
        # Fresh migrations, not a copy of a seeded template's identity sequences:
        # crash/WAL proofs must not inherit a template's sequence prelogging state.
        with mock.patch.object(db, "connect", side_effect=connect_role), fixture_world():
            migrate.apply(dbname=dbname)
            with connect_role("owner", dbname, autocommit=True) as c:
                with db.change("system", "cli", "Seed fixture profiles", conn=c) as (cur, _):
                    cur.execute("insert into space values ('home'),('user2')")
                    cur.execute("insert into profile (id,name,role,space_id,plays_as,position) values "
                                "('user1','User1','member','home','wife',0),"
                                "('matt','Matt','admin','home','user',1),"
                                "('user2','User2','member','user2',null,2)")
                c.execute((root / "decklab/design/resumable-batch-schema.sql").read_text(encoding="utf-8"))
            setup.ensure_empty_inventory(dbname, say=lambda *_: None)
    tests.PREPARE = prepare
    tests.CONNECT = connect_role
    tests.RESTART = restart
    from decklab.tests import test_collection_batch_http as http
    from decklab.tests import test_collection_batch_release as release
    from decklab.tests import test_collection_batch_admission as admission
    from decklab.tests import test_collection_batch_owner as owner
    from decklab.tests import test_collection_batch_receipt as receipt
    suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromModule(module) for module in (tests, release, http, admission, owner, receipt)])
    return unittest.TextTestRunner(verbosity=2).run(suite)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", type=Path, required=True)
    args = parser.parse_args()
    # Process-local only: never inherit a service/credential/host override.
    for key in list(os.environ):
        if key.upper().startswith("PG"):
            del os.environ[key]
    import psycopg
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from decklab.tests import test_collection_batch_postgres as tests
    temp = Path(tempfile.mkdtemp(prefix="decklab-batch-proof-" )).resolve()
    data, log = temp / "data", temp / "server.log"
    suffix = ".exe" if os.name == "nt" else ""
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PG")}
    def run(name, *options):
        subprocess.run([str(args.pg_bin / (name + suffix)), *map(str, options)],
                       check=True, env=env, creationflags=flags, timeout=45)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server_options = f"-h 127.0.0.1 -p {port}"
    if os.name != "nt":
        # Debian/PGDG defaults to /var/run/postgresql, which a CI runner cannot write.
        # Keep the Unix-domain socket in this runner-owned directory too.
        server_options += " -k " + shlex.quote(str(temp))
    print(f"Isolated synthetic cluster: {temp}; port {port}", flush=True)
    run("initdb", "-D", data, "-A", "trust", "-U", "batch_test", "--no-locale", "--encoding=UTF8")
    # Never a public listener or existing service. Trust covers only this loopback cluster.
    started = False
    try:
        run("pg_ctl", "-D", data, "-l", log, "-o", server_options, "-w", "start")
        started = True
        def connect():
            return psycopg.connect(host="127.0.0.1", port=port, user="batch_test", dbname="postgres",
                                   passfile=str(temp / "no-password-file"), sslmode="disable",
                                   connect_timeout=5, options="-c statement_timeout=10000 -c lock_timeout=5000")
        with connect() as c:
            c.execute("create table space (id text primary key)")
            c.execute("create table profile (id text primary key, space_id text references space)")
            c.execute("create table space_departure (space_id text primary key)")
            c.execute("insert into space values ('home'),('user2')")
            c.execute("insert into profile values ('user1','home'),('user3','home'),('user2','user2')")
            c.execute("create table inventory_revision (revision bigint not null)")
            c.execute("create table synthetic_effect (quantity int not null)")
            c.execute((root / "decklab/design/resumable-batch-schema.sql").read_text(encoding="utf-8"))
        def restart():
            run("pg_ctl", "-D", data, "-m", "immediate", "-w", "stop")
            run("pg_ctl", "-D", data, "-l", log, "-o", server_options, "-w", "start")
        tests.CONNECT = connect
        tests.RESTART = restart
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(tests))
        def connect_role(role="app", dbname=None, autocommit=False, **kwargs):
            # Never route a DeckLab default/configured database name to any service.
            if dbname != "postgres" and not str(dbname).startswith("batch_inventory_"):
                raise AssertionError("unexpected isolated database target")
            user = "batch_test" if role == "super" else {"app": "decklab_app", "owner": "decklab_owner", "ro": "decklab_ro"}[role]
            return psycopg.connect(host="127.0.0.1", port=port, user=user, dbname=dbname,
                                   passfile=str(temp / "no-password-file"), sslmode="disable",
                                   autocommit=autocommit, connect_timeout=5,
                                   options="-c statement_timeout=15000 -c lock_timeout=5000")
        inventory_result = inventory_proof(root, connect_role, restart)
        return 0 if result.wasSuccessful() and inventory_result.wasSuccessful() else 1
    finally:
        if started or (data / "postmaster.pid").exists():
            run("pg_ctl", "-D", data, "-m", "immediate", "-w", "stop")
        print(f"Stopped disposable cluster; diagnostic files retained at {temp}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
