"""Actual API/store/worker/LangGraph/FFmpeg; recognition and LLM are simulated.

These checks make no basketball detection accuracy claim and use no user media.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from agent.graph import create_graph
from agent.interpret import OpenAIInterpreter
from backend.app import Settings, create_app
from contracts.models import Analysis, Event
from video_engine.highlights import render_highlights

pytestmark = pytest.mark.skipif(
    not shutil.which('ffmpeg') or not shutil.which('ffprobe'),
    reason='requires FFmpeg and FFprobe on PATH',
)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'synthetic.mp4'
    subprocess.run([
        'ffmpeg', '-v', 'error', '-n', '-f', 'lavfi', '-i',
        'testsrc2=s=160x120:r=10:d=30', '-f', 'lavfi', '-i',
        'sine=frequency=440:duration=30', '-c:v', 'libx264', '-pix_fmt',
        'yuv420p', '-c:a', 'aac', str(path),
    ], check=True, capture_output=True, timeout=60)
    return path


def duration(path):
    result = subprocess.run([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'json', str(path),
    ], check=True, capture_output=True, text=True, timeout=30)
    return float(json.loads(result.stdout)['format']['duration'])


@pytest.mark.parametrize("second_label", ["made", "probable"])
def test_upload_modify_and_failed_render_preserve_previous_movie(tmp_path, source, second_label):
    calls = {'analysis': 0, 'llm': 0, 'render': 0}
    stages = []

    def simulated_recognition(video, work, *, model_path):
        calls['analysis'] += 1
        assert Path(video).read_bytes() == source.read_bytes()
        return Analysis(events=[Event(id='first', time=10, label='made'),
                                Event(id='second', time=24, label=second_label)],
                        duration_seconds=30, metadata={'simulated': True})

    def simulated_llm(request):
        calls['llm'] += 1
        assert request.url.path == '/v1/chat/completions'
        context = json.loads(json.loads(request.content)['messages'][1]['content'])
        if calls['llm'] == 1:
            assert context['displayed_event_ids'] == ['first', 'second']
            assert context['plan']['before_seconds'] == 5
            operations = [{'op': 'exclude', 'ordinal': 2}, {'op': 'add_before', 'value': 3}]
        else:
            assert context['displayed_event_ids'] == ['first']
            operations = [{'op': 'add_after', 'value': 1}]
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(
            {'status': 'apply', 'operations': operations})}}]})

    def rendering(video, events, plan, output):
        calls['render'] += 1
        summary = stages[-1]
        assert summary['status'] == 'rendering'
        assert summary['before_seconds'] == plan.before_seconds
        assert summary['after_seconds'] == plan.after_seconds
        assert summary['excluded_event_ids'] == plan.excluded_event_ids
        if calls['render'] == 2:
            assert summary['excluded_ordinals'] == [2]
            assert '第 2 球' in summary['message'] and '前 8 秒' in summary['message']
        with app.state.store.connect() as db:
            latest = json.loads(db.execute('SELECT payload FROM messages ORDER BY seq DESC LIMIT 1').fetchone()[0])
        assert latest['role'] == 'status' and latest['text'] == summary['message']
        if calls['render'] == 3:
            # Exercise the actual renderer failure boundary rather than a fake result.
            video = tmp_path / 'missing-source.mp4'
        return render_highlights(video, events, plan, output)

    with httpx.Client(transport=httpx.MockTransport(simulated_llm)) as model_client:
        graph = create_graph(
            interpreter=OpenAIInterpreter(base_url='https://llm.example.test/v1',
                api_key='test-only', model='simulated', client=model_client),
            analyzer=simulated_recognition, renderer=rendering)

        def executor(**state):
            on_stage = state['on_stage']
            def record(stage):
                stages.append(stage)
                on_stage(stage)
            state['on_stage'] = record
            return graph.invoke(state)

        app = create_app(Settings(data_dir=tmp_path / 'store'), executor=executor)
        with TestClient(app) as client:
            upload = client.post('/api/jobs', files={'file': ('synthetic.mp4', source.read_bytes(), 'video/mp4')})
            assert upload.status_code == 202
            job = upload.json()
            base = f"/api/jobs/{job['id']}"
            headers = {'X-Task-Token': job['token']}
            assert client.get(base, headers=headers).json()['status'] == 'queued'
            assert app.state.worker.run_once()
            first = client.get(base, headers=headers).json()
            assert first['status'] == 'completed', first
            assert first['displayed_event_ids'] == ['first', 'second']
            assert calls == {'analysis': 1, 'llm': 0, 'render': 1}
            first_bytes = client.get(first['result']['url'], headers=headers).content
            first_file = tmp_path / 'first.mp4'
            first_file.write_bytes(first_bytes)
            assert duration(first_file) == pytest.approx(14, abs=.2)

            response = client.post(base + '/messages', headers=headers,
                json={'request_id': 'edit-1', 'text': '去掉第二球，每球前面多留三秒'})
            assert response.status_code == 202
            assert app.state.worker.run_once()
            revised = client.get(base, headers=headers).json()
            assert revised['status'] == 'completed'
            assert revised['displayed_event_ids'] == ['first']
            assert revised['plan'] == {'before_seconds': 8, 'after_seconds': 2,
                                       'excluded_event_ids': ['second']}
            assert revised['result']['revision'] != first['result']['revision']
            movie = client.get(revised['result']['url'], headers=headers)
            assert movie.status_code == 200 and movie.headers['content-type'] == 'video/mp4'
            revised_file = tmp_path / 'revised.mp4'
            revised_file.write_bytes(movie.content)
            assert movie.content != first_bytes
            assert duration(revised_file) == pytest.approx(10, abs=.2)
            subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(revised_file),
                            '-f', 'null', '-'], check=True, capture_output=True, timeout=30)
            ranged = client.get(revised['result']['download_url'],
                                headers={**headers, 'Range': 'bytes=0-127'})
            assert ranged.status_code == 206
            assert ranged.content == movie.content[:128]
            assert ranged.headers['content-range'] == f"bytes 0-127/{len(movie.content)}"
            assert 'attachment' in ranged.headers['content-disposition']
            assert client.get(revised['result']['url']).status_code == 404

            assert client.post(base + '/messages', headers=headers,
                json={'request_id': 'edit-2', 'text': '后面再加一秒'}).status_code == 202
            assert app.state.worker.run_once()
            failed = client.get(base, headers=headers).json()
            assert failed['status'] == 'failed' and failed['error']
            for key in ('result', 'plan', 'displayed_event_ids', 'events'):
                assert failed[key] == revised[key]
            assert client.get(revised['result']['url'], headers=headers).content == movie.content
            assert calls == {'analysis': 1, 'llm': 2, 'render': 3}
            assert [stage['status'] if isinstance(stage, dict) else stage for stage in stages] == ['analyzing', 'rendering', 'rendering', 'rendering']
            messages = client.get(base + '/messages', headers=headers).json()['messages']
            assert any('共 1 个' in message['text'] and '前 8 秒' in message['text'] for message in messages)
            assert not app.state.worker.run_once()


def test_real_worker_process_reports_missing_weights(tmp_path, source):
    """Smoke production worker/runner in a separate process with no actual weights."""
    settings = Settings(data_dir=tmp_path / 'process-store', model_path=tmp_path / 'missing.pt')
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post('/api/jobs', files={'file': ('synthetic.mp4', source.read_bytes(), 'video/mp4')})
        assert response.status_code == 202
        job = response.json()
        env = dict(os.environ, BASKETBALL_DATA_DIR=str(settings.data_dir),
                   BASKETBALL_MODEL_PATH=str(settings.model_path))
        process = subprocess.Popen([sys.executable, '-m', 'backend.worker'], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                state = client.get(f"/api/jobs/{job['id']}", headers={'X-Task-Token': job['token']}).json()
                if state['status'] == 'failed':
                    break
                assert process.poll() is None, 'worker exited before consuming the job'
                time.sleep(.1)
            assert state['status'] == 'failed' and '模型' in state['error']
            assert state['result'] is None
            assert not list(settings.data_dir.rglob('execution*.json'))
        finally:
            process.terminate()
            process.wait(timeout=10)


def test_manually_selected_uncertain_event_renders_without_model(tmp_path, source):
    graph=create_graph(interpreter=lambda *a,**k: pytest.fail('selection called LLM'),
                       analyzer=lambda *a,**k: pytest.fail('selection repeated recognition'))
    app=create_app(Settings(data_dir=tmp_path/'selected-store'),executor=lambda **state:graph.invoke(state))
    with TestClient(app) as client:
        job=client.post('/api/jobs',files={'file':('sample.mp4',source.read_bytes(),'video/mp4')}).json()
        h={'X-Task-Token':job['token']};base='/api/jobs/'+job['id']
        with app.state.store.connect() as db:
            row=db.execute('SELECT state FROM jobs WHERE id=?',(job['id'],)).fetchone()
            state=json.loads(row['state']);state['events']=[{'id':'maybe','time':10,'label':'uncertain','evidence':{}}]
            db.execute("UPDATE jobs SET status='completed',state=? WHERE id=?",(json.dumps(state),job['id']))
            db.execute("UPDATE queue SET status='completed' WHERE job_id=?",(job['id'],))
        assert client.post(base+'/selection',headers=h,json={'request_id':'pick','event_ids':['maybe']}).status_code==202
        assert app.state.worker.run_once()
        result=client.get(base,headers=h).json()
        assert result['status']=='completed' and result['displayed_event_ids']==['maybe']
        assert result['events'][0]['label']=='uncertain'
        output=tmp_path/'selected.mp4';output.write_bytes(client.get(result['result']['url'],headers=h).content)
        assert duration(output)==pytest.approx(7,abs=.2)


def test_candidates_are_independent_private_clips(tmp_path, source):
    from backend.candidates import prepare_candidates
    app=create_app(Settings(data_dir=tmp_path/'candidate-store'))
    store=app.state.store;store.create('one','token')
    directory=store.tasks/'one';directory.mkdir()
    import shutil
    shutil.copy(source,directory/'source.mp4')
    state={'events':[{'id':'maybe','time':1,'label':'uncertain','evidence':{}}]}
    with store.connect() as db:
        original=json.loads(db.execute("SELECT state FROM jobs WHERE id='one'").fetchone()['state'])
    original.update(state)
    progress=[]
    prepare_candidates(store,'one',original,directory/'source.mp4',progress.append)
    clip=original['candidate_clips']['maybe']
    assert clip['url']=='/api/jobs/one/candidates/maybe'
    assert duration(Path(clip['path']))==pytest.approx(3,abs=.2)
    assert original['events'][0]['label']=='uncertain'
    with TestClient(app) as client:
        assert client.get(clip['url']).status_code==404
        r=client.get(clip['url'],headers={'X-Task-Token':'token','Range':'bytes=0-127'})
        assert r.status_code==206 and len(r.content)==128
        assert client.get('/api/jobs/one/candidates/unknown',headers={'X-Task-Token':'token'}).status_code==404
