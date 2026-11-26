import asyncio
import json
from backend.app import Settings, create_app
from backend.store import Store
from backend.progress import stream_task_events
from fastapi.testclient import TestClient


def test_stream_delivers_persisted_stage_and_later_completion(tmp_path):
    store=Store(Settings(data_dir=tmp_path))
    store.create('one','token')
    class Request:
        async def is_disconnected(self): return False
    async def exercise():
        stream=stream_task_events(store,'one','token',Request(),interval=0)
        first=await anext(stream)
        assert json.loads(first.split('data: ',1)[1])['job']['status']=='queued'
        with store.connect() as db:
            db.execute("UPDATE jobs SET status='completed' WHERE id='one'")
            store.message(db,'one','status','穿筐复核完成')
        second=await anext(stream)
        data=json.loads(second.split('data: ',1)[1])
        assert data['job']['status']=='completed'
        assert data['messages'][-1]['text']=='穿筐复核完成'
        with store.connect() as db:
            db.execute("UPDATE jobs SET expires_at=0 WHERE id='one'")
        assert 'event: expired' in await anext(stream)
        await stream.aclose()
    asyncio.run(exercise())


def test_event_stream_rejects_other_task_token(tmp_path):
    app=create_app(Settings(data_dir=tmp_path))
    app.state.store.create('one','token')
    with TestClient(app) as client:
        assert client.get('/api/jobs/one/events',headers={'X-Task-Token':'wrong'}).status_code==404
