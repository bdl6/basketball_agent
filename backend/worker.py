"""One durable serial worker; default graph executes in a killable child process."""

import json
import os
import secrets
import signal
from contextlib import contextmanager
import subprocess
import sys
import time
from pathlib import Path
from contracts.models import EditPlan, Event, highlight_eligible
from .store import Store
from .errors import public_error


PROCESS_PLATFORM = os.name


class Worker:
    def __init__(self, store, *, executor=None):
        self.store = store
        self.executor = executor

    @contextmanager
    def startup(self):
        # Hold the OS lock for the full process lifetime, including recovery.
        with (self.store.root / "worker.lock").open("a+b") as lock:
            lock.seek(0)
            if os.name == "nt":
                import msvcrt
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as error:
                    raise RuntimeError("另一个工作进程正在运行") from error
            else:
                import fcntl
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as error:
                    raise RuntimeError("另一个工作进程正在运行") from error
            try:
                self.store.interrupt()
                yield
            finally:
                lock.seek(0)
                if os.name == "nt":
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def stage(self, jid, stage):
        summary = stage if isinstance(stage, dict) else {}
        status = summary.get("status") if summary else stage
        if status not in ("analyzing", "rendering"):
            return
        message = summary.get("message") or (
            "正在分析视频" if status == "analyzing" else "正在生成集锦"
        )
        with self.store.connect() as db:
            db.execute("UPDATE jobs SET status=? WHERE id=?", (status, jid))
            self.store.message(db, jid, "status", message)

    def execute(self, args):
        if self.executor is not None:
            return self.executor(**args)
        work = args["work_dir"]
        input_path = work / "execution.json"
        output_path = work / "execution-result.json"
        stage_path = work / "execution-stage.json"
        serial = {
            k: (str(v) if isinstance(v, Path) else v)
            for k, v in args.items()
            if k != "on_stage"
        }
        input_path.write_text(json.dumps(serial), encoding="utf8")
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "backend.runner",
                str(input_path),
                str(output_path),
                str(stage_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=PROCESS_PLATFORM != "nt",
        )
        deadline = time.monotonic() + self.store.settings.execution_timeout_seconds
        try:
            while proc.poll() is None:
                if time.monotonic() >= deadline:
                    raise TimeoutError("处理超时，请稍后重新提交要求")
                if stage_path.exists():
                    stage = json.loads(stage_path.read_text(encoding="utf8"))
                    args["on_stage"](stage)
                    # Removing the event acknowledges its committed message.
                    stage_path.unlink()
                time.sleep(0.1)
            if stage_path.exists():
                args["on_stage"](json.loads(stage_path.read_text(encoding="utf8")))
                stage_path.unlink()
            if proc.returncode or not output_path.exists():
                raise RuntimeError("处理失败，请检查模型配置及视频后重试")
            output = json.loads(output_path.read_text(encoding="utf8"))
            if "worker_error" in output:
                raise RuntimeError(output["worker_error"])
            return output
        finally:
            if proc.poll() is None:
                if PROCESS_PLATFORM == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                else:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                proc.wait(timeout=10)
            for path in (input_path, output_path, stage_path):
                path.unlink(missing_ok=True)

    def run_once(self):
        claimed = self.store.claim()
        if not claimed:
            return False
        jid = claimed["job_id"]
        state = json.loads(claimed["state"])
        directory = self.store.tasks / jid
        work = directory / ("run-" + secrets.token_hex(12))
        work.mkdir()
        try:
            video = next(directory.glob("source.*"))
            execution_state = json.loads(json.dumps(state))
            selection = json.loads(claimed['selection']) if claimed.get('selection') else None
            if selection is not None:
                for event in execution_state['events'] or []:
                    event.setdefault('evidence', {})['user_selected'] = event['id'] in selection
                execution_state['plan']['excluded_event_ids'] = [
                    e['id'] for e in execution_state['events'] or [] if e['id'] not in selection]
            output = self.execute(
                dict(
                    video_path=video,
                    work_dir=work,
                    model_path=self.store.settings.model_path,
                    events=execution_state["events"],
                    plan=execution_state["plan"],
                    displayed_event_ids=state["displayed_event_ids"],
                    text=None if selection is not None else claimed["text"],
                    pending_context=None if selection is not None else state.get("pending_context"),
                    on_stage=lambda s: self.stage(jid, s),
                )
            )
            candidate_events = [
                Event.model_validate(e).model_dump() for e in output["events"]
            ]
            candidate_plan = EditPlan.model_validate(output["plan"]).model_dump()
            if output.get("result_path"):
                path = Path(output["result_path"]).resolve()
                if (
                    not path.is_relative_to(directory.resolve())
                    or not path.is_file()
                    or path.stat().st_size == 0
                ):
                    raise ValueError("invalid result path")
                expected = [
                    e["id"]
                    for e in sorted(candidate_events, key=lambda e: e["time"])
                    if highlight_eligible(Event.model_validate(e))
                    and e["id"] not in candidate_plan["excluded_event_ids"]
                ]
                if output["displayed_event_ids"] != expected or not expected:
                    raise ValueError("invalid displayed events")
                revision = secrets.token_hex(12)
                url = f"/api/jobs/{jid}/result?revision={revision}"
                state.update(
                    events=candidate_events,
                    plan=candidate_plan,
                    displayed_event_ids=expected,
                    result_path=str(path),
                    result=dict(
                        url=url, download_url=url + "&download=1", revision=revision
                    ),
                )
            elif state["events"] is None:
                # Persist completed analysis even when no confident made events exist.
                state["events"] = candidate_events
            state["pending_context"] = output.get("pending_context")
            state["error"] = None
            status = "completed"
            message = output.get("message") or "处理完成"
        except Exception as exc:
            status = "failed"
            message = public_error(exc)
            state["error"] = message
        with self.store.connect() as db:
            db.execute(
                "UPDATE jobs SET status=?,state=? WHERE id=?",
                (status, json.dumps(state, ensure_ascii=False), jid),
            )
            db.execute(
                "UPDATE queue SET status=? WHERE seq=?", (status, claimed["seq"])
            )
            self.store.message(db, jid, "assistant", message, claimed["request_id"])
        return True


def main():
    from .app import Settings

    store = Store(Settings())
    worker = Worker(store)
    with worker.startup():
        try:
            while True:
                if not worker.run_once():
                    time.sleep(0.5)
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    main()
