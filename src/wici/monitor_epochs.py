"""Source receipt order independent of source clocks and delayed SQLite writes."""
import json
import threading
import uuid

RECEIPT_KEY = '_monitor_receipt'
_INIT_LOCK = threading.Lock()


def _state(repo):
    state = getattr(repo, '_monitor_receipt_state', None)
    if state is None:
        with _INIT_LOCK:
            state = getattr(repo, '_monitor_receipt_state', None)
            if state is None:
                state = {'boot': uuid.uuid4().hex, 'generation': 0, 'lock': threading.Lock()}
                repo._monitor_receipt_state = state
    return state


def capture_receipt(repo):
    """Capture at receipt/submit, before waiting for a worker or repository lock."""
    state = _state(repo)
    with state['lock']:
        return [state['boot'], state['generation']]


receipt = capture_receipt


def stamp_payload(repo, payload, receipt=None):
    """Copy payload metadata; caller-supplied tokens preserve the queue receipt."""
    result = dict(payload)
    token = receipt if receipt is not None else result.get(RECEIPT_KEY)
    result[RECEIPT_KEY] = token if token is not None else capture_receipt(repo)
    return result


def advance_epoch(repo, rule_ids):
    """Persist affected rule boundaries inside the caller's mutation transaction.

    Failed transactions may consume a generation. Never reuse it: queued receipts
    can have observed that generation even when the database mutation rolls back.
    """
    rule_ids = list(rule_ids)
    if not rule_ids:
        return None
    state = _state(repo)
    with state['lock']:
        state['generation'] += 1
        token = [state['boot'], state['generation']]
    value = json.dumps(token, separators=(',', ':'))
    repo.db.executemany('''INSERT INTO workspace_monitor_meta(key,value) VALUES(?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value''',
        [('rule_epoch:'+rule_id, value) for rule_id in rule_ids])
    return token


def rule_epoch(repo, rule_id):
    row = repo.db.execute('SELECT value FROM workspace_monitor_meta WHERE key=?',
                          ('rule_epoch:'+rule_id,)).fetchone()
    return json.loads(row[0]) if row else None


def accepts_receipt(observation, epoch):
    token = observation.get('payload', {}).get(RECEIPT_KEY)
    # Legacy observations are governed by their existing persisted checkpoint.
    # Queues never survive a process restart; new-boot receipts remain eligible.
    return (not epoch or not token or token[0] != epoch[0] or token[1] >= epoch[1])
