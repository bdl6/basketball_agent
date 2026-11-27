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

ACTIVE = ("queued", "analyzing", "rendering")


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

    def create(self, jid, token):
        state = dict(
            events=None,
            displayed_event_ids=[],
            plan=dict(before_seconds=5, after_seconds=2, excluded_event_ids=[]),
            result=None,
            error=None,
            pending_context=None,
        )
        with self.connect() as db:
            db.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?)",
                (
                    jid,
                    hashlib.sha256(token.encode()).hexdigest(),
                    time.time() + self.settings.retention_hours * 3600,
                    "queued",
                    json.dumps(state),
                ),
            )
            db.execute("INSERT INTO queue(job_id) VALUES (?)", (jid,))
            self.message(db, jid, "assistant", "已收到，正在检查视频")

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
            job = db.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()
            if not progress and job["status"] in ACTIVE:
                return 409, {"detail": "任务正在处理中，请稍后再修改"}
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
            stage = "analyzing" if state["events"] is None else "rendering"
            db.execute("UPDATE jobs SET status=? WHERE id=?", (stage, row["job_id"]))
            self.message(
                db,
                row["job_id"],
                "status",
                "正在分析视频" if stage == "analyzing" else "正在处理剪辑要求",
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
                "SELECT id FROM jobs WHERE expires_at<=? AND status NOT IN ('analyzing','rendering')",
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
