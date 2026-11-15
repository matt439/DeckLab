"""Exact-owned receipt recovery candidate, deliberately unregistered in normal startup.

Reads only; no completion, creation, admission transition or inventory fallback.
A missing result is never evidence that an earlier request did not commit.
"""
from decklab.lib.state import pg_collection_batches as batches
from . import collection_batches as private
from .common import ApiError


def view(space=None, batch_id=None):
    profile, space = private._owner(space)
    if not isinstance(batch_id, str) or not batch_id:
        raise ApiError(400, 'An exact saved batch ID is required.', code='batch_id_required')
    with private._errors():
        backend = private._backend()
        row = private._transaction(backend, lambda cur: batches.read(cur, profile['id'], space, batch_id))
    status = row['status']
    if status == 'committed':
        if not isinstance(row['receipt'], dict):
            raise ApiError(503, 'Receipt could not be confirmed. Do not repeat this pile as a new batch.',
                           code='batch_unconfirmed', retry='same_batch')
        return {'batch_id': batches._identity(batch_id), 'space': space, 'state': 'committed',
                'receipt': row['receipt']}
    return {'batch_id': batches._identity(batch_id), 'space': space,
            'state': 'discarded' if status == 'discarded' else 'unconfirmed',
            'message': 'No completed receipt is confirmed here. Do not repeat the pile as a new batch.'}
