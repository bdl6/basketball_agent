"""FastAPI boundary. Run a separate ``python -m backend.worker`` process.

Disable uvicorn access logs (``--no-access-log``) and redact query strings in
reverse-proxy logs: browser result URLs necessarily carry a task credential.
"""
import json
import math
import os
import secrets
import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from .store import Store

class Settings(BaseModel):
    data_dir: Path = Field(default_factory=lambda:Path(os.getenv('BASKETBALL_DATA_DIR','./data')))
    max_upload_bytes: int = Field(default=104857600,gt=0)
    max_duration_seconds: float = Field(default=300,gt=0,allow_inf_nan=False)
    retention_hours: float = Field(default=24,gt=0,allow_inf_nan=False)
    execution_timeout_seconds: float = Field(default=1800,gt=0,allow_inf_nan=False)
    model_path: Path = Field(default_factory=lambda:Path(os.getenv('BASKETBALL_MODEL_PATH','models/bball_model.pt')))

class MessageInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id: str=Field(min_length=1,max_length=128)
    text: str=Field(min_length=1,max_length=4000)


def probe_duration(path):
    proc=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type','-of','json',str(path)],capture_output=True,text=True,timeout=30,check=True)
    data=json.loads(proc.stdout)
    if not any(s.get('codec_type')=='video' for s in data.get('streams',[])):
        raise ValueError('no video stream')
    return float(data['format']['duration'])


def create_app(settings=None, *, probe=probe_duration, executor=None):
    settings=settings or Settings()
    store=Store(settings)
    @asynccontextmanager
    async def lifespan(app):
        store.interrupt()
        yield
    app=FastAPI(lifespan=lifespan)
    app.state.settings=settings
    app.state.store=store
    from .worker import Worker
    app.state.worker=Worker(store,executor=executor)
    def authorized(jid,token):
        row=store.authorize(jid,token)
        if row is None:
            raise HTTPException(404,'任务不存在或已过期')
        return row

    @app.get('/api/config')
    def config():
        return dict(allowed_extensions=['.mp4','.mov','.mkv'],max_upload_bytes=settings.max_upload_bytes,max_duration_seconds=settings.max_duration_seconds,retention_hours=settings.retention_hours)

    @app.post('/api/jobs',status_code=202)
    async def upload(file: UploadFile=File(...)):
        suffix=Path(file.filename or '').suffix.lower()
        if suffix not in ('.mp4','.mov','.mkv'):
            raise HTTPException(415,'仅支持 MP4、MOV、MKV 视频')
        jid=secrets.token_hex(16)
        directory=store.tasks/jid
        directory.mkdir()
        path=directory/('source'+suffix)
        try:
            size=0
            with path.open('wb') as out:
                while chunk:=await file.read(1024*1024):
                    size+=len(chunk)
                    if size>settings.max_upload_bytes:
                        raise HTTPException(413,'视频超过大小限制')
                    out.write(chunk)
            try:
                # Probe runs outside the event loop; uploaded bytes are already bounded.
                from starlette.concurrency import run_in_threadpool
                duration=await run_in_threadpool(probe,path)
                if not math.isfinite(duration) or duration<=0 or duration>settings.max_duration_seconds:
                    raise ValueError('duration')
            except Exception:
                raise HTTPException(422,'视频损坏、无视频轨道或超过时长限制') from None
            token=secrets.token_urlsafe(32)
            store.create(jid,token)
            return dict(id=jid,token=token,status='queued')
        except BaseException:
            shutil.rmtree(directory)
            raise
        finally:
            await file.close()

    @app.get('/api/jobs/{jid}')
    def status(jid:str,x_task_token:str|None=Header(default=None)):
        row=authorized(jid,x_task_token)
        state=json.loads(row['state'])
        return dict(id=jid,status=row['status'],events=state['events'] or [],displayed_event_ids=state['displayed_event_ids'],plan=state['plan'],result=state['result'],error=state['error'])

    @app.get('/api/jobs/{jid}/messages')
    def messages(jid:str,x_task_token:str|None=Header(default=None)):
        authorized(jid,x_task_token)
        with store.connect() as db:
            return dict(messages=[json.loads(r['payload']) for r in db.execute('SELECT payload FROM messages WHERE job_id=? ORDER BY seq',(jid,))])

    @app.post('/api/jobs/{jid}/messages')
    def submit(jid:str,payload:MessageInput,x_task_token:str|None=Header(default=None)):
        authorized(jid,x_task_token)
        text=payload.text.strip()
        if not text:
            raise HTTPException(422,'请输入要求')
        progress=text.rstrip('？?。!！') in ('查看进度','查询进度','进度','现在进度','status','progress')
        code,body=store.submit(jid,payload.request_id,text,progress)
        return JSONResponse(body,status_code=code)

    @app.get('/api/jobs/{jid}/result')
    def result(jid:str,revision:str|None=None,token:str|None=None,download:bool=False,x_task_token:str|None=Header(default=None)):
        row=authorized(jid,x_task_token or token)
        state=json.loads(row['state'])
        current=state['result']
        if not current or (revision is not None and revision!=current['revision']):
            raise HTTPException(404,'暂无可用成片')
        path=Path(state['result_path']).resolve()
        if not path.is_relative_to((store.tasks/jid).resolve()) or not path.is_file():
            raise HTTPException(404,'暂无可用成片')
        return FileResponse(path,media_type='video/mp4',filename='basketball-highlights.mp4',content_disposition_type='attachment' if download else 'inline',headers={'Referrer-Policy':'no-referrer','Cache-Control':'private, no-store'})
    return app

app=create_app()
