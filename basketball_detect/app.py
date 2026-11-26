from collections import Counter
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sys
import time
import uuid

from .config import DetectConfig
from .media import inspect_video
from .pipeline import analyze
from .render import find_font, render_video


def write_json(path: Path, data: dict):
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def run(config: DetectConfig) -> Path:
    if not config.model.is_file():
        raise ValueError(f"模型不存在: {config.model}")
    metadata = inspect_video(config.video)
    find_font(config.font)
    run_dir = config.output / f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=False)
    report = {"status": "analyzing", "config": asdict(config), "metadata": metadata}
    write_json(run_dir / "run.json", report)
    start = time.perf_counter()
    try:
        analysis = analyze(config, run_dir, metadata=metadata)
        report["status"] = "rendering"
        write_json(run_dir / "run.json", report)
        print("正在导出标注视频…", file=sys.stderr, flush=True)
        render_start = time.perf_counter()
        destination = render_video(config.video, analysis, run_dir / "annotated.mp4", font=config.font)
        counts = Counter(event["label"] for event in analysis.events)
        analysis.timings["render"] = round(time.perf_counter() - render_start, 3)
        report.update(status="complete", output=destination, events=analysis.events,
                      summary={key: counts[key] for key in ("made", "missed", "uncertain")},
                      model_sha256=analysis.model_sha256, timings=analysis.timings,
                      total_seconds=round(time.perf_counter() - start, 3))
        write_json(run_dir / "events.json", report)
        write_json(run_dir / "run.json", report)
        return destination
    except Exception as exc:
        report.update(status="failed", error=str(exc), total_seconds=round(time.perf_counter() - start, 3))
        write_json(run_dir / "run.json", report)
        raise
