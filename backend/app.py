from backend.candidates import public_clips
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
from pathlib import Path
from fastapi import FastAPI, File, Header, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from .store import Store


class Settings(BaseModel):
    engine_root: Path | None = Field(default_factory=lambda: Path(os.environ['BASKETBALL_ENGINE_ROOT']) if os.getenv('BASKETBALL_ENGINE_ROOT') else None)
    data_dir: Path = Field(
        default_factory=lambda: Path(os.getenv("BASKETBALL_DATA_DIR", "./data"))
    )
    max_upload_bytes: int = Field(default=104857600, gt=0)
    max_duration_seconds: float = Field(default=300, gt=0, allow_inf_nan=False)
    retention_hours: float = Field(default=24, gt=0, allow_inf_nan=False)
    execution_timeout_seconds: float = Field(default=1800, gt=0, allow_inf_nan=False)
    model_path: Path = Field(
        default_factory=lambda: Path(
            os.getenv("BASKETBALL_MODEL_PATH", "models/bball_model.pt")
        )
    )


class PrepareInput(BaseModel):
    request_id: str = Field(min_length=1,max_length=128)


class SelectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1,max_length=128)
    event_ids: list[str] = Field(min_length=1,max_length=1000)


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=4000)


class Rectangle(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    x1: float = Field(ge=0)
    y1: float = Field(ge=0)
    x2: float = Field(gt=0)
    y2: float = Field(gt=0)


class RoiInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(min_length=1, max_length=128)
    roi: Rectangle
    net_roi: Rectangle


def probe_duration(path):
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    data = json.loads(proc.stdout)
    if not any(s.get("codec_type") == "video" for s in data.get("streams", [])):
        raise ValueError("no video stream")
    return float(data["format"]["duration"])


def create_app(settings=None, *, probe=probe_duration, executor=None):
    settings = settings or Settings()
    store = Store(settings)

    app = FastAPI()
    app.state.settings = settings
    app.state.store = store
    from .worker import Worker

    app.state.worker = Worker(store, executor=executor)

    def authorized(jid, token):
        row = store.authorize(jid, token)
        if row is None:
            raise HTTPException(404, "任务不存在或已过期")
        return row

    @app.get("/api/config")
    def config():
        return dict(
            allowed_extensions=[".mp4", ".mov", ".mkv"],
            max_upload_bytes=settings.max_upload_bytes,
            max_duration_seconds=settings.max_duration_seconds,
            retention_hours=settings.retention_hours,
        )

    @app.post("/api/jobs", status_code=202)
    async def upload(file: UploadFile = File(...)):
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in (".mp4", ".mov", ".mkv"):
            raise HTTPException(415, "仅支持 MP4、MOV、MKV 视频")
        jid = secrets.token_hex(16)
        directory = store.tasks / jid
        directory.mkdir()
        path = directory / ("source" + suffix)
        try:
            size = 0
            with path.open("wb") as out:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise HTTPException(413, "视频超过大小限制")
                    out.write(chunk)
            try:
                # Probe runs outside the event loop; uploaded bytes are already bounded.
                from starlette.concurrency import run_in_threadpool

                duration = await run_in_threadpool(probe, path)
                if (
                    not math.isfinite(duration)
                    or duration <= 0
                    or duration > settings.max_duration_seconds
                ):
                    raise ValueError("duration")
            except Exception:
                raise HTTPException(422, "视频损坏、无视频轨道或超过时长限制") from None
            token = secrets.token_urlsafe(32)
            store.create(jid, token, require_roi=True)
            return dict(id=jid, token=token, status="preparing_roi")
        except BaseException:
            shutil.rmtree(directory)
            raise
        finally:
            await file.close()

    @app.get("/api/jobs/{jid}")
    def status(jid: str, x_task_token: str | None = Header(default=None)):
        row = authorized(jid, x_task_token)
        state = json.loads(row["state"])
        return dict(
            id=jid,
            status=row["status"],
            events=state["events"] or [],
            displayed_event_ids=state["displayed_event_ids"],
            plan=state["plan"],
            result=state["result"],
            error=state["error"],
            candidate_clips=public_clips(state),
            roi=state.get('roi'),
        )

    @app.post('/api/jobs/{jid}/roi')
    def confirm_roi(jid: str, payload: RoiInput, x_task_token: str | None = Header(default=None)):
        authorized(jid, x_task_token)
        code, body = store.confirm_roi(jid, payload.request_id, payload.roi.model_dump(), payload.net_roi.model_dump())
        return JSONResponse(body, status_code=code)

    @app.get("/api/jobs/{jid}/messages")
    def messages(jid: str, x_task_token: str | None = Header(default=None)):
        authorized(jid, x_task_token)
        with store.connect() as db:
            return dict(
                messages=[
                    json.loads(r["payload"])
                    for r in db.execute(
                        "SELECT payload FROM messages WHERE job_id=? ORDER BY seq",
                        (jid,),
                    )
                ]
            )

    @app.post("/api/jobs/{jid}/candidates")
    def prepare(jid: str, payload: PrepareInput, x_task_token: str | None = Header(default=None)):
        row=authorized(jid,x_task_token)
        if not json.loads(row['state']).get('events'):
            raise HTTPException(422,'还没有可生成短视频的候选')
        code,body=store.submit(jid,payload.request_id,'准备独立候选短视频',False,prepare_only=True)
        return JSONResponse(body,status_code=code)

    @app.get("/api/jobs/{jid}/candidates/{event_id}")
    def candidate(jid: str,event_id: str,token: str | None=None,x_task_token: str | None=Header(default=None)):
        row=authorized(jid,x_task_token or token)
        clip=json.loads(row['state']).get('candidate_clips',{}).get(event_id,{})
        if clip.get('status')!='ready':
            raise HTTPException(404,'候选短视频尚未生成')
        path=Path(clip['path']).resolve()
        if not path.is_relative_to((store.tasks/jid).resolve()) or not path.is_file():
            raise HTTPException(404,'候选短视频不存在')
        return FileResponse(path,media_type='video/mp4',headers={'Cache-Control':'private, no-store','Referrer-Policy':'no-referrer'})

    @app.post("/api/jobs/{jid}/selection")
    def selection(jid: str, payload: SelectionInput, x_task_token: str | None = Header(default=None)):
        row = authorized(jid, x_task_token)
        state = json.loads(row['state'])
        allowed = {e['id'] for e in state['events'] or [] if e['label'] != 'missed'}
        ids = list(dict.fromkeys(payload.event_ids))
        if not set(ids) <= allowed:
            raise HTTPException(422, '选择包含不存在或明确未进的事件')
        code, body = store.submit(jid,payload.request_id,'按勾选的候选生成集锦',False,selection=ids)
        return JSONResponse(body,status_code=code)

    @app.get("/api/jobs/{jid}/events")
    async def events(jid: str, request: Request, x_task_token: str | None = Header(default=None)):
        authorized(jid, x_task_token)
        from .progress import stream_task_events
        return StreamingResponse(stream_task_events(store, jid, x_task_token, request),
            media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-store",
                "X-Accel-Buffering": "no", "Referrer-Policy": "no-referrer"})

    @app.post("/api/jobs/{jid}/messages")
    def submit(
        jid: str, payload: MessageInput, x_task_token: str | None = Header(default=None)
    ):
        authorized(jid, x_task_token)
        text = payload.text.strip()
        if not text:
            raise HTTPException(422, "请输入要求")
        progress = text.rstrip("？?。!！") in (
            "查看进度",
            "查询进度",
            "进度",
            "现在进度",
            "status",
            "progress",
        )
        code, body = store.submit(jid, payload.request_id, text, progress)
        return JSONResponse(body, status_code=code)

    @app.get("/api/jobs/{jid}/source")
    def source(jid: str, token: str | None = None, x_task_token: str | None = Header(default=None)):
        authorized(jid, x_task_token or token)
        path = next((store.tasks / jid).glob('source.*'), None)
        if path is None or not path.is_file():
            raise HTTPException(404, '原视频不存在')
        return FileResponse(path,headers={'Referrer-Policy':'no-referrer','Cache-Control':'private, no-store'})

    @app.get("/api/jobs/{jid}/result")
    def result(
        jid: str,
        revision: str | None = None,
        token: str | None = None,
        download: bool = False,
        x_task_token: str | None = Header(default=None),
    ):
        row = authorized(jid, x_task_token or token)
        state = json.loads(row["state"])
        current = state["result"]
        if not current or (revision is not None and revision != current["revision"]):
            raise HTTPException(404, "暂无可用成片")
        path = Path(state["result_path"]).resolve()
        if not path.is_relative_to((store.tasks / jid).resolve()) or not path.is_file():
            raise HTTPException(404, "暂无可用成片")
        return FileResponse(
            path,
            media_type="video/mp4",
            filename="basketball-highlights.mp4",
            content_disposition_type="attachment" if download else "inline",
            headers={
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "private, no-store",
            },
        )

    return app


app = create_app()
