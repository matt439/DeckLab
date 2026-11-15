"""Explicit owner-only staged policy transition. Never installs schema or opens routes.

The cursor functions require a caller-owned transaction. Print confirmation only after
that transaction commits. `recover` confirms state, not attribution of a lost request.
No inventory data or receipt is deleted. This module is not registered in normal CLI.
"""
from decklab.lib.state import Conflict, Invalid
from decklab.lib.state import collection_batch_admission as gate

MAX_EPOCH = 9223372036854775807


def _intent(contract, epoch, enabled):
    if type(contract) is not int or contract != gate.CONTRACT or type(epoch) is not int or not 1 <= epoch < MAX_EPOCH:
        raise Invalid('Use the exact supported contract and a positive, incrementable expected epoch.')
    if type(enabled) is not bool:
        raise Invalid('The target admission state must be a boolean.')


def _locked(cur):
    from psycopg.pq import TransactionStatus
    if cur.connection.info.transaction_status != TransactionStatus.INTRANS:
        raise Invalid('Owner transition requires an existing transaction.')
    # Check actual current SQL role, not a supplied owner name or body identity.
    role = cur.execute('select current_user').fetchone()[0]
    if role != 'decklab_owner':
        raise Invalid('Only the database owner role may change or reconcile admission.')
    cur.execute("set local lock_timeout = '5s'")
    cur.execute("select pg_advisory_xact_lock(hashtext('inventory'))")
    owners = cur.execute("select relname,pg_get_userbyid(relowner) from pg_class "
        "where oid in (to_regclass('public.collection_batch'),to_regclass('public.collection_batch_admission'))").fetchall()
    if dict(owners) != {'collection_batch': role, 'collection_batch_admission': role}:
        raise Invalid('Compatible owner-held batch and admission tables must already be installed.')
    row = cur.execute('select contract,epoch,enabled from public.collection_batch_admission where singleton=1').fetchone()
    if (row is None or type(row[0]) is not int or row[0] != gate.CONTRACT
            or type(row[1]) is not int or row[1] < 1 or type(row[2]) is not bool):
        raise Conflict(gate.REFUSED)
    return dict(zip(('contract', 'epoch', 'enabled'), row))


def recover(cur, *, contract, epoch, enabled):
    """Wait behind prior writes, then confirm the captured target or report actual state.

Never retries a mutation. `unchanged` means this locked observation is still the expected
state, not that some delayed client cannot submit an old request in the future.
"""
    _intent(contract, epoch, enabled)
    current = _locked(cur)
    if current == {'contract': contract, 'epoch': epoch + 1, 'enabled': enabled}:
        outcome = 'target_confirmed'
    elif current['contract'] == contract and current['epoch'] == epoch:
        outcome = 'unchanged'
    else:
        outcome = 'conflict'
    return {'outcome': outcome, 'policy': current}


def transition(cur, *, contract, epoch, enabled):
    """Exact immutable intent retry is read-only at target epoch; all other stale intents refuse."""
    result = recover(cur, contract=contract, epoch=epoch, enabled=enabled)
    if result['outcome'] == 'target_confirmed':
        return result
    current = result['policy']
    if result['outcome'] != 'unchanged':
        raise Conflict('Admission changed. Inspect current policy; do not silently refresh the expected epoch.')
    if current['enabled'] == enabled:
        raise Invalid('Admission already has that state; no epoch was changed.')
    cur.execute('update public.collection_batch_admission set enabled=%s,epoch=epoch+1 where singleton=1', (enabled,))
    return {'outcome': 'transitioned', 'policy': {'contract': contract, 'epoch': epoch + 1, 'enabled': enabled}}


def database_name(value):
    """Require a literal explicit database name; never normalize to connector defaults."""
    if not isinstance(value, str) or not value.strip() or value != value.strip() or '\x00' in value:
        raise Invalid('Use an explicit nonblank database name without surrounding whitespace.')
    return value


def execute(dbname, *, contract, epoch, enabled, recovery=False):
    """Connection-owning boundary: validate target and intent before calling the connector."""
    name = database_name(dbname)
    _intent(contract, epoch, enabled)
    from decklab.db import conn as db
    with db.connect('owner', dbname=name) as connection, connection.cursor() as cur:
        actual = cur.execute('select current_database()').fetchone()[0]
        if actual != name:
            raise Invalid('Connected database does not match the explicit target; nothing was changed.')
        endpoint = {'host': connection.info.host, 'port': connection.info.port}
        answer = (recover if recovery else transition)(cur, contract=contract, epoch=epoch, enabled=enabled)
    return {'database': actual, 'endpoint': endpoint, **answer}


def main(argv=None):
    """Opt-in owner command; required explicit target, no installation or automatic retry."""
    import argparse
    import json
    from decklab.lib import venv
    venv.activate()
    parser = argparse.ArgumentParser(description=__doc__)
    def explicit_name(value):
        try:
            return database_name(value)
        except Invalid as error:
            raise argparse.ArgumentTypeError(str(error)) from error
    parser.add_argument('--dbname', required=True, type=explicit_name)
    parser.add_argument('--contract', required=True, type=int)
    parser.add_argument('--epoch', required=True, type=int)
    parser.add_argument('--target', required=True, choices=('enabled', 'paused'))
    parser.add_argument('--recover', action='store_true', help='locked state observation only; never writes policy')
    args = parser.parse_args(argv)
    intent = dict(contract=args.contract, epoch=args.epoch, enabled=args.target == 'enabled')
    try:
        answer = execute(args.dbname, **intent, recovery=args.recover)
        # execute returns only after the connection context has committed.
        print(json.dumps(answer, sort_keys=True))
        return 0 if answer['outcome'] in ('target_confirmed', 'transitioned') else 2
    except (Invalid, Conflict) as error:
        print(str(error))
        return 1
    except Exception:  # noqa: BLE001 - a lost commit response must not be reported as failure to write
        print('Outcome unconfirmed. Use --recover with the identical database, contract, epoch and target. '
              'Do not refresh the epoch or assume nothing changed.')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
