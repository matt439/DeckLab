"""Optional staged admission contract. No installer or ordinary startup activation.

Call admit only under the participant's existing exclusive inventory lock. Owner
pause/re-enable must take that same lock and advance epoch before committing.
Absent table preserves the pre-admission staged contract, never a public route.
"""
from decklab.lib.state import Conflict

CONTRACT = 1
REFUSED = 'Batch writes are paused or this client needs a fresh compatible review. Saved state was not changed.'


def policy(cur):
    if not cur.execute("select to_regclass('public.collection_batch_admission') is not null").fetchone()[0]:
        return None
    row = cur.execute('select contract,epoch,enabled from collection_batch_admission where singleton=1').fetchone()
    if row is None or type(row[0]) is not int or row[0] != CONTRACT or type(row[1]) is not int or row[1] < 1:
        raise Conflict(REFUSED)
    return {'contract': row[0], 'epoch': row[1], 'enabled': row[2]}


def admit(cur, offered):
    current = policy(cur)
    if current is None:
        if offered is not None:
            raise Conflict(REFUSED)
        return None
    if (not current['enabled'] or type(offered) is not dict or set(offered) != {'contract', 'epoch'}
            or type(offered['contract']) is not int or type(offered['epoch']) is not int
            or offered != {key: current[key] for key in ('contract', 'epoch')}):
        raise Conflict(REFUSED)
    return dict(offered)
