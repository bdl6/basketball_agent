import json
import signal
import subprocess
import sys
import pytest
from backend.app import Settings
from backend.store import Store
from backend.worker import Worker


def test_second_worker_cannot_interrupt_owner(tmp_path):
    store = Store(Settings(data_dir=tmp_path))
    store.create('one','token')
    with Worker(store).startup():
        store.claim()
        result = subprocess.run([sys.executable, '-c', "from pathlib import Path; from backend.app import Settings; from backend.store import Store; from backend.worker import Worker; import sys; Worker(Store(Settings(data_dir=Path(sys.argv[1])))).startup().__enter__()", str(tmp_path)], capture_output=True, timeout=15)
        assert result.returncode != 0
        assert store.authorize('one','token')['status'] == 'analyzing'
    with Worker(store).startup():
        assert store.authorize('one','token')['status'] == 'interrupted'


def test_summary_is_persisted_before_failed_render(tmp_path):
    store = Store(Settings(data_dir=tmp_path))
    store.create('one','token')
    directory = store.tasks / 'one'
    directory.mkdir()
    (directory/'source.mp4').write_bytes(b'video')
    old = json.loads(store.authorize('one','token')['state'])
    old.update(events=[{'id':'e1','time':1,'label':'made','evidence':{}}], result={'revision':'old'})
    with store.connect() as db:
        db.execute('UPDATE jobs SET state=?',(json.dumps(old),))
    summary = {'status':'rendering','message':'将排除第 2 球（e2），每球前 8 秒、后 2 秒。'}
    persisted = []
    def execute(**args):
        args['on_stage'](summary)
        with store.connect() as db:
            messages = [json.loads(r['payload']) for r in db.execute('SELECT payload FROM messages')]
        assert messages[-1]['text'] == summary['message']
        assert json.loads(store.authorize('one','token')['state'])['plan'] == old['plan']
        persisted.append(True)
        raise RuntimeError('FFmpeg failed')
    Worker(store,executor=execute).run_once()
    row = store.authorize('one','token')
    current = json.loads(row['state'])
    assert persisted == [True]
    assert row['status'] == 'failed'
    assert current['plan'] == old['plan'] and current['result'] == old['result']


@pytest.mark.parametrize('platform',['posix','nt'])
def test_timeout_kills_descendants(tmp_path,monkeypatch,platform):
    import backend.worker as module
    store = Store(Settings(data_dir=tmp_path,execution_timeout_seconds=0.00001))
    options, killed = {}, []
    class Process:
        pid = 123
        returncode = None
        def poll(self): return None
        def kill(self): pytest.fail('only runner killed')
        def wait(self,**kw): pass
    def popen(*a,**kw):
        options.update(kw)
        return Process()
    monkeypatch.setattr(signal, 'SIGKILL', 9, raising=False)
    monkeypatch.setattr(module,'PROCESS_PLATFORM',platform,raising=False)
    monkeypatch.setattr(module.subprocess,'Popen',popen)
    monkeypatch.setattr(module.subprocess,'run',lambda args,**kw:killed.append(args))
    monkeypatch.setattr(module.os,'killpg',lambda pid,sig:killed.append((pid,sig)),raising=False)
    with pytest.raises(TimeoutError):
        Worker(store).execute({'work_dir':tmp_path,'on_stage':lambda s:None})
    if platform == 'posix':
        assert options['start_new_session'] is True
        assert killed == [(123,signal.SIGKILL)]
    else:
        assert killed == [['taskkill','/PID','123','/T','/F']]


def test_runner_waits_for_persisted_stage_ack(tmp_path, monkeypatch):
    import threading
    import time
    import agent.graph
    import backend.runner as runner
    source, output, stage = [tmp_path/name for name in ('input.json','output.json','stage.json')]
    source.write_text(json.dumps({'video_path':'video','work_dir':str(tmp_path),'model_path':'model'}))
    rendered = []
    def execute(**args):
        args['on_stage']({'status':'rendering','message':'每球前 8 秒、后 2 秒。'})
        rendered.append(True)
        return {'ok':True}
    monkeypatch.setattr(agent.graph,'execute_job',execute)
    monkeypatch.setattr(sys,'argv',['runner',str(source),str(output),str(stage)])
    thread = threading.Thread(target=runner.main,daemon=True)
    thread.start()
    deadline = time.monotonic()+5
    while not stage.exists() and time.monotonic()<deadline:
        time.sleep(.01)
    try:
        assert json.loads(stage.read_text(encoding='utf8'))['status'] == 'rendering'
        assert rendered == []
    finally:
        stage.unlink(missing_ok=True)
        thread.join(5)
    assert rendered == [True]
    assert json.loads(output.read_text(encoding='utf8')) == {'ok':True}
