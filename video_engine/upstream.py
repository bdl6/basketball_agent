"""Thin client for the original editor's headless engine. No detection rules here."""
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

from contracts.models import Analysis, Event


class EngineError(RuntimeError):
    def __init__(self, error):
        self.code = error.get('code', 'ENGINE_FAILED')
        super().__init__(error.get('message', '原项目引擎执行失败'))


class Engine:
    def __init__(self, root=None, *, log_path=None):
        bundled = Path(__file__).resolve().parents[1]/'vendor/basketball-highlight-editor'
        self.root = Path(root or os.environ.get('BASKETBALL_ENGINE_ROOT') or bundled).resolve()
        self.log_path = Path(log_path) if log_path else None
        if not (self.root/'engine/python/basketball_engine/__main__.py').is_file():
            raise RuntimeError('原项目引擎未配置，请设置 BASKETBALL_ENGINE_ROOT')

    def __enter__(self):
        env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
        env['PYTHONPATH'] = os.pathsep.join([str(self.root/'engine/python'), str(self.root/'src'), env.get('PYTHONPATH', '')])
        self.log = self.log_path.open('w',encoding='utf-8') if self.log_path else None
        try:
            self.proc = subprocess.Popen([os.environ.get('BASKETBALL_ENGINE_PYTHON', sys.executable), '-m', 'basketball_engine'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log or subprocess.DEVNULL,
                text=True, encoding='utf-8', env=env)
        except BaseException:
            if self.log: self.log.close()
            raise
        self.lines = queue.Queue()
        def read():
            try:
                for line in self.proc.stdout:
                    self.lines.put(line)
            finally:
                self.lines.put(None)
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        return self

    def call(self, command, **payload):
        rid = uuid4().hex
        self.proc.stdin.write(json.dumps(dict(protocol_version='1.0',type='request',request_id=rid,command=command,payload=payload))+'\n')
        self.proc.stdin.flush()
        deadline = time.monotonic()+180
        while True:
            try:
                line = self.lines.get(timeout=max(.01, deadline-time.monotonic()))
            except queue.Empty:
                raise TimeoutError('原项目引擎响应超时') from None
            if line is None:
                raise RuntimeError('原项目引擎进程意外退出')
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if value.get('type') != 'response' or value.get('request_id') != rid:
                continue
            if not value.get('ok'):
                raise EngineError(value.get('error', {}))
            return value['payload']

    def __exit__(self, *exc):
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                subprocess.run(['taskkill','/PID',str(self.proc.pid),'/T','/F'], capture_output=True, check=False)
            else:
                self.proc.kill()
            self.proc.wait(timeout=10)
        self.reader.join(timeout=2)
        self.proc.stdout.close()
        if self.log: self.log.close()


def link(engine, video_path, work_dir):
    project = str((Path(work_dir)/'upstream-project').resolve())
    engine.call('create_project', name='篮球视频分析', root_path=project)
    video = engine.call('link_video', project_root=project, video_path=str(Path(video_path).resolve()))['video']
    return {'project_root':project,'video_id':video['id']}, video


def recommended_net_roi(roi, hoop):
    """Source-pixel equivalent of upstream apps/desktop/lib/core/roi_geometry.dart."""
    x1,y1,x2,y2 = map(float,hoop)
    width = min(max((x2-x1)*1.5,(roi['x2']-roi['x1'])*.08),(roi['x2']-roi['x1'])*.34)
    left = min(max((x1+x2)/2-width/2,roi['x1']),roi['x2']-width)
    rim_height = (y2-y1)*.45
    top = min(max((y1+y2)/2-(y2-y1)*.28-rim_height/2,roi['y1']),roi['y2'])
    bottom = min(max(top+rim_height*4.5,top),roi['y2'])
    return dict(x1=left,y1=top,x2=left+width,y2=bottom)


def prepare_roi(video_path, work_dir, *, model_path, engine_root=None, on_progress=None):
    with Engine(engine_root, log_path=Path(work_dir)/'upstream-engine.log') as engine:
        scope, video = link(engine, video_path, work_dir)
        result = dict(width=video['width'], height=video['height'], duration_seconds=video['duration_ms']/1000,
                      roi=None, net_roi=None, confirmed=False, preview_time_seconds=0)
        if on_progress:
            on_progress({'status':'preparing_roi','message':'正在定位篮筐，准备区域建议；确认区域后才会开始识别。'})
        try:
            suggested = engine.call('suggest_roi', **scope, model_path=str(Path(model_path).resolve()))
        except EngineError:
            result['warning'] = '未能自动定位，请在画面上手动框选投篮分析区和篮网区域。'
            return {'roi':result}
        result['roi'] = suggested['roi']
        result['calibration'] = suggested.get('calibration', {})
        hoop = suggested.get('calibration', {}).get('hoop_bbox')
        if isinstance(hoop,(list,tuple)) and len(hoop)==4:
            result['net_roi'] = recommended_net_roi(result['roi'],hoop)
        result['preview_time_seconds'] = suggested.get('preview_time_ms', 0)/1000
        return {'roi':result}


def candidates_to_events(rows):
    events = []
    for row in rows:
        evidence = json.loads(row.get('evidence_json') or '{}')
        excluded = row.get('selection_status') == 'excluded' or row.get('review_status') == 'excluded'
        rim = evidence.get('rim_check') or {}
        label = 'missed' if excluded else ('made' if evidence.get('verdict') == 'made' and rim.get('status') == 'made' else 'probable')
        events.append(Event(id=row['id'],time=row['event_time_ms']/1000,label=label,
                            evidence={**evidence,'upstream_candidate':row,'engine':'basketball-highlight-editor'}))
    return sorted(events, key=lambda e:(e.time,e.id))


STAGES = {'engine_preflight':'检查识别模型','prepare_proxy':'生成分析代理视频',
          'coarse_scan':'粗筛投篮候选','generate_candidates':'整理粗筛候选','refine_candidates':'精筛投篮轨迹','verify_rim_crossing':'重筛篮筐穿越',
          'prepare_review_previews':'准备候选预览','persist_candidates':'保存识别结果'}


def analyze_video(video_path, work_dir, *, model_path, roi, engine_root=None, on_progress=None):
    if not roi or not roi.get('confirmed'):
        raise ValueError('请先确认投篮分析区和篮网区域')
    with Engine(engine_root, log_path=Path(work_dir)/'upstream-engine.log') as engine:
        scope, video = link(engine, video_path, work_dir)
        calibration = {**roi.get('calibration', {}), 'source':'user_confirmed', 'net_roi':roi['net_roi']}
        engine.call('save_roi', **scope, **roi['roi'], calibration=calibration)
        job = engine.call('start_analysis', **scope, mode='standard', model_path=str(Path(model_path).resolve()))['job']
        previous = None
        deadline = time.monotonic()+1800
        while True:
            current = engine.call('get_job', project_root=scope['project_root'], job_id=job['id'])['job']
            stage = current.get('stage', '')
            percent = int(float(current.get('progress') or 0)*100)
            key = stage, percent//5
            if on_progress and key != previous:
                on_progress({'status':'analyzing', 'message':f"{STAGES.get(stage, '原项目识别：'+stage)} · {percent}%"})
                previous = key
            if current['state'] == 'completed':
                break
            if current['state'] in ('failed','cancelled','interrupted'):
                raise RuntimeError('原项目识别失败：'+str(current.get('error_message') or current['state']))
            if time.monotonic()>deadline:
                raise TimeoutError('原项目识别超时')
            time.sleep(.3)
        rows = engine.call('list_candidates', **scope)['candidates']
        return Analysis(events=candidates_to_events(rows), duration_seconds=video['duration_ms']/1000,
                        metadata={'engine':'basketball-highlight-editor','roi':roi,'upstream_job':current})
