"""Durable SQLite persistence for the single-worker service."""

import hashlib
import json
import secrets
import shutil
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ACTIVE = ("queued", "preparing_roi", "analyzing", "rendering")


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class Store:
    def __init__(self, settings):
        self.settings = settings
        self.root = settings.data_dir.resolve()
        self.tasks = self.root / "tasks"
        self.tasks.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "jobs.sqlite3"
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, expires_at REAL NOT NULL, status TEXT NOT NULL, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (seq INTEGER PRIMARY KEY, job_id TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS requests (job_id TEXT NOT NULL, request_id TEXT NOT NULL, status_code INTEGER NOT NULL, response TEXT NOT NULL, PRIMARY KEY(job_id,request_id));
            CREATE TABLE IF NOT EXISTS queue (seq INTEGER PRIMARY KEY, job_id TEXT NOT NULL, text TEXT, request_id TEXT, status TEXT NOT NULL DEFAULT 'queued');
            """)

            if 'selection' not in {r[1] for r in db.execute('PRAGMA table_info(queue)')}:
                db.execute('ALTER TABLE queue ADD COLUMN selection TEXT')
            if 'prepare_only' not in {r[1] for r in db.execute('PRAGMA table_info(queue)')}:
                db.execute('ALTER TABLE queue ADD COLUMN prepare_only INTEGER DEFAULT 0')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def message(self, db, jid, role, text, request_id=None):
        payload = dict(
            id=secrets.token_hex(12),
            role=role,
            text=text,
            created_at=now(),
            request_id=request_id,
        )
        db.execute(
            "INSERT INTO messages(job_id,payload) VALUES (?,?)",
            (jid, json.dumps(payload, ensure_ascii=False)),
        )

    def create(self, jid, token, *, require_roi=False):
        state = dict(
            events=None,
            displayed_event_ids=[],
            plan=dict(before_seconds=5, after_seconds=2, excluded_event_ids=[]),
            result=None,
            error=None,
            pending_context=None,
            roi={'confirmed':False} if require_roi else None,
        )
        with self.connect() as db:
            db.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?)",
                (
                    jid,
                    hashlib.sha256(token.encode()).hexdigest(),
                    time.time() + self.settings.retention_hours * 3600,
                    "preparing_roi" if require_roi else "queued",
                    json.dumps(state),
                ),
            )
            db.execute("INSERT INTO queue(job_id) VALUES (?)", (jid,))
            self.message(db, jid, "assistant", "已收到，正在准备区域建议。请确认投篮分析区和篮网区域，然后我会识别候选进球。" if require_roi else "已收到，正在检查视频")

    def confirm_roi(self, jid, request_id, roi, net_roi):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            replay = db.execute('SELECT status_code,response FROM requests WHERE job_id=? AND request_id=?', (jid,request_id)).fetchone()
            if replay:
                return replay['status_code'], json.loads(replay['response'])
            job = db.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
            state = json.loads(job['state'])
            current = state.get('roi') or {}
            if job['status'] in ACTIVE:
                return 409, {'detail':'任务正在处理中，请稍后再确认区域'}
            width, height = current.get('width',0), current.get('height',0)
            for box in (roi, net_roi):
                if not (0 <= box['x1'] < box['x2'] <= width and 0 <= box['y1'] < box['y2'] <= height):
                    return 422, {'detail':'区域必须位于视频画面内，且宽高大于零'}
            if roi['x2']-roi['x1'] < max(64,width*.08) or roi['y2']-roi['y1'] < max(96,height*.12):
                return 422, {'detail':'投篮分析区过小，请覆盖完整投篮和球的运动区域'}
            if not (roi['x1'] <= net_roi['x1'] < net_roi['x2'] <= roi['x2'] and roi['y1'] <= net_roi['y1'] < net_roi['y2'] <= roi['y2']):
                return 422, {'detail':'篮网区域必须位于投篮分析区内'}
            state.update(roi={**current,'roi':roi,'net_roi':net_roi,'confirmed':True},events=None,
                         displayed_event_ids=[],result=None,result_path=None,candidate_clips={},error=None,
                         pending_context=None,plan=dict(before_seconds=5,after_seconds=2,excluded_event_ids=[]))
            body = {'request_id':request_id,'status':'queued'}
            db.execute('UPDATE jobs SET status=?,state=? WHERE id=?', ('queued',json.dumps(state),jid))
            db.execute('INSERT INTO queue(job_id,request_id) VALUES (?,?)', (jid,request_id))
            db.execute('INSERT INTO requests VALUES (?,?,?,?)', (jid,request_id,202,json.dumps(body)))
            self.message(db,jid,'user','已确认投篮分析区和篮网区域',request_id)
            self.message(db,jid,'assistant','区域已确认，开始原项目的粗筛、精筛和重筛。',request_id)
            return 202, body

    def authorize(self, jid, token):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM jobs WHERE id=? AND expires_at>?", (jid, time.time())
            ).fetchone()
        if (
            row is None
            or not token
            or not secrets.compare_digest(
                row["token_hash"], hashlib.sha256(token.encode()).hexdigest()
            )
        ):
            return None
        return row

    def submit(self, jid, request_id, text, progress, selection=None, prepare_only=False):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            replay = db.execute(
                "SELECT status_code,response FROM requests WHERE job_id=? AND request_id=?",
                (jid, request_id),
            ).fetchone()
            if replay:
                return replay["status_code"], json.loads(replay["response"])
            job = db.execute("SELECT status,state FROM jobs WHERE id=?", (jid,)).fetchone()
            if not progress and job["status"] in ACTIVE:
                return 409, {"detail": "任务正在处理中，请稍后再修改"}
            roi = json.loads(job['state']).get('roi')
            if not progress and roi is not None and not roi.get('confirmed'):
                return 409, {'detail':'请先在视频中确认投篮分析区和篮网区域'}
            response = dict(
                request_id=request_id, status="completed" if progress else "queued"
            )
            code = 200 if progress else 202
            db.execute(
                "INSERT INTO requests VALUES (?,?,?,?)",
                (jid, request_id, code, json.dumps(response)),
            )
            self.message(db, jid, "user", text, request_id)
            if progress:
                labels = {
                    "queued": "排队中",
                    "analyzing": "正在分析",
                    "rendering": "正在剪辑",
                    "completed": "已完成",
                    "failed": "处理失败",
                    "interrupted": "任务已中断",
                    "preparing_roi": "正在准备区域建议",
                    "awaiting_roi": "请确认投篮分析区和篮网区域",
                }
                self.message(db, jid, "status", labels[job["status"]], request_id)
            else:
                db.execute("UPDATE jobs SET status=? WHERE id=?", ("queued", jid))
                db.execute(
                    "INSERT INTO queue(job_id,text,request_id,selection,prepare_only) VALUES (?,?,?,?,?)",
                    (jid, text, request_id, json.dumps(selection) if selection is not None else None, int(prepare_only)),
                )
            return code, response

    def claim(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM queue WHERE status='running'").fetchone():
                return None
            row = db.execute(
                "SELECT q.*,j.state FROM queue q JOIN jobs j ON j.id=q.job_id WHERE q.status='queued' AND j.expires_at>? ORDER BY q.seq LIMIT 1",
                (time.time(),),
            ).fetchone()
            if not row:
                return None
            db.execute("UPDATE queue SET status='running' WHERE seq=?", (row["seq"],))
            state = json.loads(row["state"])
            roi = state.get('roi')
            stage = 'preparing_roi' if roi is not None and not roi.get('confirmed') else ("analyzing" if state["events"] is None else "rendering")
            db.execute("UPDATE jobs SET status=? WHERE id=?", (stage, row["job_id"]))
            self.message(
                db,
                row["job_id"],
                "status",
                '正在准备区域建议' if stage == 'preparing_roi' else ("正在分析视频" if stage == "analyzing" else "正在处理剪辑要求"),
                row["request_id"],
            )
            return dict(row)

    def interrupt(self):
        with self.connect() as db:
            rows = db.execute(
                "SELECT DISTINCT job_id FROM queue WHERE status='running'"
            ).fetchall()
            for row in rows:
                db.execute(
                    "UPDATE jobs SET status='interrupted' WHERE id=?", (row["job_id"],)
                )
                self.message(
                    db, row["job_id"], "status", "任务因服务重启而中断，请重新提交要求"
                )
            db.execute("UPDATE queue SET status='interrupted' WHERE status='running'")

    def cleanup(self):
        count = 0
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT id FROM jobs WHERE expires_at<=? AND NOT EXISTS (SELECT 1 FROM queue WHERE queue.job_id=jobs.id AND queue.status='running') AND status NOT IN ('analyzing','rendering')",
                (time.time(),),
            ).fetchall()
            for row in rows:
                jid = row["id"]
                target = (self.tasks / jid).resolve()
                if target.parent != self.tasks.resolve():
                    continue
                if target.exists():
                    shutil.rmtree(target)
                for table in ("messages", "requests", "queue"):
                    db.execute(f"DELETE FROM {table} WHERE job_id=?", (jid,))
                db.execute("DELETE FROM jobs WHERE id=?", (jid,))
                count += 1
        return count
