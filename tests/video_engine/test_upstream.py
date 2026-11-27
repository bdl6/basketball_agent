import json
from video_engine.upstream import candidates_to_events


def test_default_engine_uses_vendored_source(monkeypatch):
    from video_engine.upstream import Engine
    monkeypatch.delenv('BASKETBALL_ENGINE_ROOT',raising=False)
    engine=Engine()
    assert engine.root.name=='basketball-highlight-editor'
    assert 'vendor' in engine.root.parts
    assert (engine.root/'scripts/create_proxy.py').is_file()


def test_net_suggestion_matches_original_desktop_geometry():
    from video_engine.upstream import recommended_net_roi
    box = recommended_net_roi({'x1':0,'y1':0,'x2':1000,'y2':600}, [450,200,550,240])
    assert box == {'x1':425,'y1':199.8,'x2':575,'y2':280.8}


def test_standard_engine_pipeline_receives_confirmed_regions(tmp_path, monkeypatch):
    from video_engine import upstream
    calls = []
    class FakeEngine:
        def __init__(self, root, **kw): pass
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def call(self, command, **payload):
            calls.append((command,payload))
            if command=='link_video': return {'video':{'id':'v','width':1000,'height':600,'duration_ms':10000}}
            if command=='start_analysis': return {'job':{'id':'job'}}
            if command=='get_job': return {'job':{'id':'job','state':'completed','stage':'persist_candidates','progress':1}}
            if command=='list_candidates': return {'candidates':[{'id':'a','event_time_ms':2000,'selection_status':'included','evidence_json':'{}'}]}
            return {}
    monkeypatch.setattr(upstream,'Engine',FakeEngine)
    roi={'confirmed':True,'roi':{'x1':0,'y1':0,'x2':1000,'y2':600},'net_roi':{'x1':425,'y1':200,'x2':575,'y2':280}}
    result=upstream.analyze_video(tmp_path/'source.mp4',tmp_path,model_path=tmp_path/'model.pt',roi=roi)
    assert [cmd for cmd,_ in calls]==['create_project','link_video','save_roi','start_analysis','get_job','list_candidates']
    assert calls[2][1]['calibration']['net_roi']==roi['net_roi']
    assert calls[3][1]['mode']=='standard'
    assert result.events[0].label=='probable'


def test_candidate_mapping_preserves_upstream_selection_and_evidence():
    rows = [dict(id='pending',event_time_ms=4200,selection_status='included',evidence_json=json.dumps({'verdict':'ambiguous','rim_check':{'status':'uncertain'}})),
            dict(id='rejected',event_time_ms=1000,selection_status='excluded',evidence_json=json.dumps({'rim_check':{'status':'rejected'}})),
            dict(id='made',event_time_ms=7000,selection_status='included',evidence_json=json.dumps({'verdict':'made','rim_check':{'status':'made'}}))]
    events = candidates_to_events(rows)
    assert [(e.id,e.time,e.label) for e in events] == [('rejected',1,'missed'),('pending',4.2,'probable'),('made',7,'made')]
    assert events[1].evidence['upstream_candidate'] == rows[0]
    assert events[1].evidence['rim_check']['status'] == 'uncertain'
