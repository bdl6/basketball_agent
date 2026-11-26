"""Task-scoped SSE snapshots, backed by durable messages across worker processes."""
import asyncio
import json
import time


def snapshot(store, jid, token):
    row = store.authorize(jid, token)
    if row is None:
        return None
    state = json.loads(row['state'])
    with store.connect() as db:
        messages = [json.loads(r['payload']) for r in db.execute(
            'SELECT payload FROM messages WHERE job_id=? ORDER BY seq', (jid,))]
    return {'job': dict(id=jid, status=row['status'], events=state['events'] or [],
            displayed_event_ids=state['displayed_event_ids'], plan=state['plan'],
            result=state['result'], error=state['error']), 'messages': messages}


async def stream_task_events(store, jid, token, request, *, interval=.3):
    previous = None
    heartbeat = time.monotonic()
    while not await request.is_disconnected():
        data = snapshot(store, jid, token)
        if data is None:
            yield 'event: expired\ndata: {}\n\n'
            return
        encoded = json.dumps(data, ensure_ascii=False)
        if encoded != previous:
            yield 'event: snapshot\ndata: ' + encoded + '\n\n'
            previous = encoded
            heartbeat = time.monotonic()
        elif time.monotonic() - heartbeat >= 10:
            yield ': heartbeat\n\n'
            heartbeat = time.monotonic()
        await asyncio.sleep(interval)
