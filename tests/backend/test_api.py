import json
import sqlite3
from pathlib import Path
import pytest
from fastapi.testclient import TestClient


def make_app(tmp_path, **kw):
    from backend.app import Settings, create_app

    return create_app(
        Settings(data_dir=tmp_path, max_upload_bytes=16, max_duration_seconds=30),
        probe=lambda p: 10,
        **kw,
    )


def upload(client):
    r = client.post("/api/jobs", files={"file": ("clip.mp4", b"video", "video/mp4")})
    assert r.status_code == 202
    j = r.json()
    return j["id"], {"X-Task-Token": j["token"]}, j["token"]


def test_app_factory_and_public_limits(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        assert c.get("/api/config").json()["max_upload_bytes"] == 16
        assert "LLM_API_KEY" not in c.get("/api/config").text


def test_upload_validation_and_token_isolation(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        assert c.post("/api/jobs", files={"file": ("x.exe", b"x")}).status_code == 415
        assert (
            c.post("/api/jobs", files={"file": ("x.mp4", b"x" * 17)}).status_code == 413
        )
        jid, h, token = upload(c)
        other, oh, _ = upload(c)
        for url in [
            f"/api/jobs/{jid}",
            f"/api/jobs/{jid}/messages",
            f"/api/jobs/{jid}/result",
        ]:
            assert c.get(url).status_code == 404
            assert c.get(url, headers=oh).status_code == 404
        assert (
            c.post(
                f"/api/jobs/{jid}/messages", json={"request_id": "x", "text": "go"}
            ).status_code
            == 404
        )
        assert c.get(f"/api/jobs/{jid}", headers=h).json()["status"] == "queued"
        assert token not in (tmp_path / "jobs.sqlite3").read_bytes().decode("latin1")


@pytest.mark.parametrize("duration", [0, 31, float("nan")])
def test_duration_rejected(tmp_path, duration):
    from backend.app import Settings, create_app

    with TestClient(
        create_app(Settings(data_dir=tmp_path), probe=lambda p: duration)
    ) as c:
        # Set the max duration explicitly for the over-limit case.
        c.app.state.settings.max_duration_seconds = 30
        assert c.post("/api/jobs", files={"file": ("x.mp4", b"bad")}).status_code == 422
    assert not list((tmp_path / "tasks").iterdir())


def success(**kw):
    kw["on_stage"]("rendering")
    target = kw["work_dir"] / "result.mp4"
    target.write_bytes(b"0123456789")
    return {
        "events": [{"id": "e1", "time": 4, "label": "made", "evidence": {}}],
        "plan": {"before_seconds": 5, "after_seconds": 2, "excluded_event_ids": []},
        "displayed_event_ids": ["e1"],
        "result_path": str(target),
        "message": "done",
        "pending_context": None,
    }


def test_dedupe_busy_progress_range_and_failure_retention(tmp_path):
    app = make_app(tmp_path, executor=success)
    with TestClient(app) as c:
        jid, h, token = upload(c)
        app.state.worker.run_once()
        initial = c.get(f"/api/jobs/{jid}", headers=h).json()
        assert initial["status"] == "completed"
        url = initial["result"]["url"] + "&token=" + token
        r = c.get(url, headers={"Range": "bytes=2-5"})
        assert r.status_code == 206 and r.content == b"2345"
        assert r.headers["referrer-policy"] == "no-referrer"
        assert (
            c.get(url.replace(initial["result"]["revision"], "stale")).status_code
            == 404
        )
        payload = {"request_id": "once", "text": "每球前面多留三秒"}
        assert (
            c.post(f"/api/jobs/{jid}/messages", headers=h, json=payload).status_code
            == 202
        )
        assert c.post(f"/api/jobs/{jid}/messages", headers=h, json=payload).json() == {
            "request_id": "once",
            "status": "queued",
        }
        assert (
            c.post(
                f"/api/jobs/{jid}/messages",
                headers=h,
                json={"request_id": "two", "text": "去掉第二球"},
            ).status_code
            == 409
        )
        assert (
            c.post(
                f"/api/jobs/{jid}/messages",
                headers=h,
                json={"request_id": "p", "text": "查看进度"},
            ).status_code
            == 200
        )

        def fail(**kw):
            raise RuntimeError("secret upstream details")

        app.state.worker.executor = fail
        app.state.worker.run_once()
        failed = c.get(f"/api/jobs/{jid}", headers=h).json()
        assert failed["status"] == "failed"
        assert failed["result"] == initial["result"]
        assert (
            failed["displayed_event_ids"] == ["e1"]
            and failed["plan"] == initial["plan"]
        )
        assert c.get(url).content == b"0123456789"
        messages = c.get(f"/api/jobs/{jid}/messages", headers=h).json()["messages"]
        assert (
            len(
                [
                    m
                    for m in messages
                    if m["role"] == "user" and m["request_id"] == "once"
                ]
            )
            == 1
        )
        assert any(m["role"] == "status" and m["request_id"] == "p" for m in messages)


def test_restart_interruption_and_expiry_cleanup(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        jid, h, _ = upload(c)
        app.state.store.claim()
    other = make_app(tmp_path)
    with TestClient(other) as c:
        assert c.get(f"/api/jobs/{jid}", headers=h).json()["status"] == "interrupted"
        active, ah, _ = upload(c)
        other.state.store.claim()
        with other.state.store.connect() as db:
            db.execute("UPDATE jobs SET expires_at=0")
        sentinel = tmp_path / "keep.txt"
        sentinel.write_text("keep")
        assert c.get(f"/api/jobs/{jid}", headers=h).status_code == 404
        assert other.state.store.cleanup() == 1
        assert sentinel.exists() and (tmp_path / "tasks" / active).exists()


def test_expired_queued_task_is_cleaned_but_running_task_survives(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as c:
        active, _, _ = upload(c)
        app.state.store.claim()
        queued, _, _ = upload(c)
        with app.state.store.connect() as db:
            db.execute("UPDATE jobs SET expires_at=0")
        assert app.state.store.cleanup() == 1
        assert not (tmp_path / "tasks" / queued).exists()
        assert (tmp_path / "tasks" / active).exists()


def test_clarification_keeps_plan_and_persists_pending_context(tmp_path):
    app = make_app(tmp_path, executor=success)
    with TestClient(app) as c:
        jid, h, _ = upload(c)
        app.state.worker.run_once()
        previous = c.get(f"/api/jobs/{jid}", headers=h).json()

        def clarify(**kw):
            return dict(
                events=kw["events"],
                plan={
                    "before_seconds": 50,
                    "after_seconds": 2,
                    "excluded_event_ids": [],
                },
                displayed_event_ids=kw["displayed_event_ids"],
                result_path=None,
                message="请说明要去掉哪球",
                pending_context={"question": "which event"},
            )

        app.state.worker.executor = clarify
        c.post(
            f"/api/jobs/{jid}/messages",
            headers=h,
            json={"request_id": "clarify", "text": "去掉那个球"},
        )
        app.state.worker.run_once()
        current = c.get(f"/api/jobs/{jid}", headers=h).json()
        assert (
            current["plan"] == previous["plan"]
            and current["result"] == previous["result"]
        )

        def answer(**kw):
            assert kw["pending_context"] == {"question": "which event"}
            assert kw["events"][0]["id"] == "e1"
            return clarify(**kw)

        app.state.worker.executor = answer
        c.post(
            f"/api/jobs/{jid}/messages",
            headers=h,
            json={"request_id": "answer", "text": "第二球"},
        )
        app.state.worker.run_once()
        assert c.get(f"/api/jobs/{jid}", headers=h).json()["status"] == "completed"


def test_default_worker_process_timeout_and_claim_serialization(tmp_path, monkeypatch):
    from backend.app import Settings, create_app
    import time

    app = create_app(
        Settings(data_dir=tmp_path, execution_timeout_seconds=0.0001),
        probe=lambda p: 10,
    )
    with TestClient(app) as c:
        jid, h, _ = upload(c)
        # Deadline expires before a real graph subprocess can initialize.
        started = time.monotonic()
        assert app.state.worker.run_once()
        assert time.monotonic() - started < 10
        state = c.get(f"/api/jobs/{jid}", headers=h).json()
        assert state["status"] == "failed" and "超时" in state["error"]
        upload(c)
        upload(c)
        assert app.state.store.claim() is not None
        assert app.state.store.claim() is None


def test_real_ffprobe_rejects_corrupt_video(tmp_path):
    from backend.app import Settings, create_app

    with TestClient(create_app(Settings(data_dir=tmp_path))) as c:
        assert (
            c.post("/api/jobs", files={"file": ("bad.mp4", b"not a video")}).status_code
            == 422
        )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("未稳定定位篮筐 /private/secret.mp4", "篮筐"),
        ("模型不存在: C:/private/key.pt", "识别模型"),
        ("模型服务未配置，请设置 LLM_API_KEY=SECRET", "模型服务未配置"),
        ("模型服务调用失败 bearer SECRET", "模型服务调用失败"),
        ("FFmpeg 视频剪辑或校验失败: SECRET", "视频导出失败"),
        ("没有可剪辑的可靠进球 secret", "没有可剪辑的可靠进球"),
    ],
)
def test_known_domain_failures_are_useful_without_exposing_details(
    tmp_path, error, expected
):
    def fail(**kw):
        raise RuntimeError(error)

    app = make_app(tmp_path, executor=fail)
    with TestClient(app) as c:
        jid, h, _ = upload(c)
        app.state.worker.run_once()
        message = c.get(f"/api/jobs/{jid}", headers=h).json()["error"]
        assert expected in message
        assert (
            "SECRET" not in message
            and "private" not in message
            and "secret" not in message
        )
