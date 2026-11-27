import json
from fastapi.testclient import TestClient
from backend.app import Settings, create_app


def test_upload_waits_for_confirmation_and_roi_edits_invalidate_results(tmp_path):
    calls = []
    def execute(**kw):
        calls.append(kw)
        assert kw['operation'] == 'prepare_roi'
        return {'roi': {'width': 1000, 'height': 600, 'duration_seconds': 10,
                        'roi': None, 'net_roi': None, 'confirmed': False}}
    app = create_app(Settings(data_dir=tmp_path), probe=lambda p: 10, executor=execute)
    with TestClient(app) as c:
        s = c.post('/api/jobs', files={'file': ('x.mp4', b'video')}).json()
        base = f"/api/jobs/{s['id']}"
        h = {'X-Task-Token': s['token']}
        assert c.get(base, headers=h).json()['status'] == 'preparing_roi'
        app.state.worker.run_once()
        assert c.get(base, headers=h).json()['status'] == 'awaiting_roi'
        assert c.get(base+'/source').status_code == 404
        assert c.get(base+'/source',headers=h).content == b'video'
        from backend.progress import snapshot
        assert snapshot(app.state.store,s['id'],s['token'])['job']['roi']['confirmed'] is False
        assert not app.state.worker.run_once()
        assert c.post(base+'/messages', headers=h, json={'request_id':'no','text':'开始'}).status_code == 409
        body = {'request_id':'yes','roi':{'x1':0,'y1':0,'x2':1000,'y2':600},
                'net_roi':{'x1':400,'y1':200,'x2':500,'y2':300}}
        assert c.post(base+'/roi', json=body).status_code == 404
        assert c.post(base+'/roi', headers=h, json={**body,'roi':{**body['roi'],'x2':1001}}).status_code == 422
        assert c.post(base+'/roi', headers=h, json=body).status_code == 202
        assert c.post(base+'/roi', headers=h, json=body).status_code == 202
        with app.state.store.connect() as db:
            assert db.execute("SELECT count(*) FROM queue WHERE status='queued'").fetchone()[0] == 1
            state = json.loads(db.execute('SELECT state FROM jobs').fetchone()[0])
            state.update(events=[{'id':'old','time':1,'label':'made'}],result={'url':'old'},candidate_clips={'old':{}},result_path='old')
            db.execute("UPDATE jobs SET status='completed',state=?", (json.dumps(state),))
            db.execute("UPDATE queue SET status='completed'")
        body['request_id'] = 'edit'
        body['net_roi']['x2'] = 510
        assert c.post(base+'/roi', headers=h, json=body).status_code == 202
        current = c.get(base, headers=h).json()
        assert current['events'] == [] and current['result'] is None and current['candidate_clips'] == {}
        assert len(calls) == 1


def test_roi_requires_nonempty_nested_boxes_and_rejects_busy_edits(tmp_path):
    app=create_app(Settings(data_dir=tmp_path),probe=lambda p:10,
        executor=lambda **kw:{'roi':{'width':1000,'height':600,'duration_seconds':10,'confirmed':False}})
    with TestClient(app) as c:
        s=c.post('/api/jobs',files={'file':('x.mp4',b'video')}).json()
        base=f"/api/jobs/{s['id']}";h={'X-Task-Token':s['token']}
        app.state.worker.run_once()
        body={'request_id':'roi','roi':{'x1':200,'y1':100,'x2':900,'y2':500},'net_roi':{'x1':400,'y1':200,'x2':500,'y2':300}}
        for bad in ({**body['roi'],'x2':200},{**body['roi'],'x2':230},{**body['roi'],'x1':-1}):
            assert c.post(base+'/roi',headers=h,json={**body,'roi':bad}).status_code==422
        assert c.post(base+'/roi',headers=h,json={**body,'net_roi':{'x1':0,'y1':0,'x2':50,'y2':50}}).status_code==422
        assert c.post(base+'/roi',headers=h,json=body).status_code==202
        assert c.post(base+'/roi',headers=h,json={**body,'request_id':'new'}).status_code==409
