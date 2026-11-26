from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import os
import subprocess
import sys
import time

from .config import DetectConfig
from .events import classify_events, collect_matches
from .media import inspect_video

VENDOR = Path(__file__).resolve().parents[1] / "vendor"


@dataclass
class AnalysisResult:
    events: list[dict] = field(default_factory=list)
    rim: dict | None = None
    records: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)
    model_sha256: str = ""


def run_stage(script: str, args: list[str], output: Path, log: Path) -> dict:
    settings = log.parent / "yolo-settings"
    settings.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONUTF8": "1", "YOLO_CONFIG_DIR": str(settings)}
    command = [sys.executable, str(VENDOR / "scripts" / script), *map(str, args), "--output", str(output)]
    with log.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(command, ensure_ascii=False) + "\n")
        handle.flush()
        result = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT, env=env)
    if result.returncode:
        tail = log.read_text(encoding="utf-8", errors="replace")[-2500:]
        raise RuntimeError(f"检测阶段 {script} 失败，日志: {log}\n{tail}")
    if not output.is_file():
        raise RuntimeError(f"{script} 未生成结果: {output}")
    data = json.loads(output.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"{script} 结果结构无效")
    return data


def recompute_checks(matches: list[dict], output: dict) -> list[dict]:
    sys.path.insert(0, str(VENDOR / "src")) if str(VENDOR / "src") not in sys.path else None
    from basketball_highlight.rim_check import assess_rim_crossing, apply_video_occlusion, keep_unless_seen, skipped_result
    results = output.get("results", [])
    if len(results) != len(matches):
        return [skipped_result("check_failed") for _ in matches]
    checks = []
    for match, result in zip(matches, results):
        rim = (match.get("overlay") or {}).get("rim")
        if not isinstance(result, dict) or not isinstance(result.get("frames"), list) or not rim:
            checks.append(skipped_result(result.get("reason", "check_failed") if isinstance(result, dict) else "check_failed"))
        else:
            checks.append(assess_rim_crossing(result["frames"], rim, result.get("net_motion_series")))
    # Overlapping refinement windows contain repeated observations of one
    # crossing. They must not count as independent camera-calibration samples.
    groups = []
    for index in sorted(range(len(matches)), key=lambda i: float(matches[i]["time"])):
        if groups and float(matches[index]["time"]) - float(matches[groups[-1][0]]["time"]) <= .8:
            groups[-1].append(index)
        else:
            groups.append([index])
    unique = []
    for group in groups:
        variants = [checks[i] for i in group]
        if len({(c.get("status"), c.get("reason")) for c in variants}) > 1:
            unique.append(skipped_result("hypothesis_conflict"))
        else:
            unique.append(dict(variants[0]))
    calibrated = apply_video_occlusion(unique)
    final = [None] * len(matches)
    for group, check in zip(groups, calibrated):
        for index in group:
            result = keep_unless_seen(check, refined=not matches[index].get("coarse_crossing"))
            final[index] = {**result, "observations": [checks[i] for i in group]}
    return final


def analyze(config: DetectConfig, run_dir: Path, *, stage_runner=run_stage, metadata=None) -> AnalysisResult:
    if not config.model.is_file():
        raise ValueError(f"模型不存在: {config.model}")
    meta = metadata if metadata is not None else inspect_video(config.video)
    run_dir.mkdir(parents=True, exist_ok=True)
    timings = {}
    def stage(script, args):
        print(f"正在处理: {script}", file=sys.stderr, flush=True)
        start = time.perf_counter()
        result = stage_runner(script, list(map(str, args)), run_dir / f"{Path(script).stem}.json", run_dir / f"{Path(script).stem}.log")
        timings[Path(script).stem] = round(time.perf_counter() - start, 3)
        return result
    common = ["--video", config.video, "--model", config.model, "--device", config.device]
    roi = config.roi
    if roi is None:
        auto = stage("detect_auto_roi.py", common)
        if not auto.get("success"):
            raise RuntimeError("未稳定定位篮筐；请检查画面，或配置 roi 分析区域后重试")
        roi = auto["roi"]
    if roi[2] > meta["width"] or roi[3] > meta["height"]:
        raise ValueError("roi 超出视频画面")
    roi_args = ["--roi", *roi]
    scan = stage("scan_video.py", [*common, *roi_args, "--sample-fps", min(config.coarse_fps, meta["fps"]), "--conf", 0.10])
    if not isinstance(scan.get("records"), list):
        raise RuntimeError("粗扫 records 结构无效")
    coarse = stage("generate_candidates.py", ["--detections", run_dir / "scan_video.json", "--rim-band-seeds"])
    if not isinstance(coarse.get("candidates"), list) or not isinstance(coarse.get("rim"), dict):
        raise RuntimeError("候选或篮筐结构无效")
    matches = []
    checks = []
    if coarse["candidates"]:
        refined = stage("refine_dynamic_candidates.py", [*common, *roi_args, "--coarse", run_dir / "generate_candidates.json",
            "--proxy-scale", 1, "--sample-fps", min(config.refine_fps, meta["fps"]), "--conf", 0.10])
        if not isinstance(refined.get("results"), list):
            raise RuntimeError("精扫结果结构无效")
        matches = collect_matches(refined)
        if matches:
            candidate_file = run_dir / "rim_inputs.json"
            candidate_file.write_text(json.dumps({"candidates": [{"time": m["time"], "rim": (m.get("overlay") or {}).get("rim")} for m in matches]}), encoding="utf-8")
            checked = stage("verify_rim_crossing.py", [*common, "--candidates", candidate_file])
            checks = recompute_checks(matches, checked)
    with config.model.open("rb") as handle:
        model_hash = hashlib.file_digest(handle, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else _sha256(handle)
    return AnalysisResult(classify_events(matches, checks), coarse["rim"], scan["records"], meta, timings, model_hash)


def _sha256(handle):
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()
