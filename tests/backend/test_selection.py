from fastapi.testclient import TestClient
from backend.app import Settings,create_app
from video_engine.highlights import build_intervals
from contracts.models import Event,EditPlan
import json


def test_manual_selection_keeps_uncertain_label_and_skips_llm(tmp_path):
    seen=[]
    def execute(**args):
        assert args['text'] is None
        assert args['events'][1]['label']=='uncertain'
        assert args['events'][1]['evidence']['user_selected'] is True
        selected=build_intervals([Event.model_validate(e) for e in args['events']],EditPlan.model_validate(args['plan']),20)[1]
        seen.extend(selected)
        output=args['work_dir']/'result.mp4';output.write_bytes(b'mp4')
        return {**args,'displayed_event_ids':selected,'result_path':str(output),'message':'已生成','pending_context':None}
    app=create_app(Settings(data_dir=tmp_path),executor=execute)
    store=app.state.store;store.create('one','secret')
    d=store.tasks/'one';d.mkdir();(d/'source.mp4').write_bytes(b'video')
    with store.connect() as db:
        db.execute("UPDATE queue SET status='completed'")
        row=db.execute("SELECT state FROM jobs WHERE id='one'").fetchone();state=json.loads(row['state'])
        state['events']=[{'id':'a','time':5,'label':'made','evidence':{}},{'id':'b','time':10,'label':'uncertain','evidence':{}}]
        db.execute("UPDATE jobs SET state=?,status='completed'",(json.dumps(state),))
    with TestClient(app) as c:
        endpoint='/api/jobs/one/selection';payload={'request_id':'pick1','event_ids':['b']};h={'X-Task-Token':'secret'}
        assert c.post(endpoint,json=payload).status_code==404
        assert c.get('/api/jobs/one/source').status_code==404
        assert c.get('/api/jobs/one/source',headers=h).status_code==200
        assert c.post(endpoint,json={**payload,'event_ids':['bad']},headers=h).status_code==422
        assert c.post(endpoint,json=payload,headers=h).status_code==202
        assert c.post(endpoint,json=payload,headers=h).status_code==202
        assert app.state.worker.run_once()
        job=c.get('/api/jobs/one',headers=h).json()
        assert job['displayed_event_ids']==['b'] and seen==['b']
        assert not app.state.worker.run_once()
