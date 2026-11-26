"""Keep the detector's original judgments; never render its annotated movie."""
from pathlib import Path

from basketball_detect.config import DetectConfig
from basketball_detect.pipeline import analyze as _analyze
from contracts.models import Analysis, Event


def analyze_video(video_path: Path, work_dir: Path, *, model_path: Path, on_progress=None) -> Analysis:
    video_path, work_dir, model_path = Path(video_path), Path(work_dir), Path(model_path)
    options = {"on_progress": on_progress} if on_progress is not None else {}
    result = _analyze(DetectConfig(video=video_path, model=model_path, output=work_dir), work_dir, **options)
    if not result.rim:
        raise RuntimeError('未稳定定位篮筐，请使用篮筐清晰的固定机位视频')
    events = [Event(id=f"event-{raw['id']}", time=raw['time'], label=raw['label'], evidence=dict(raw))
              for raw in sorted(result.events, key=lambda item: (item['time'], str(item['id'])))]
    if len({event.id for event in events}) != len(events):
        raise RuntimeError('识别结果包含重复事件 ID')
    return Analysis(events=events, duration_seconds=result.metadata['duration'],
                    metadata={**result.metadata, 'rim': result.rim, 'timings': result.timings,
                              'model_sha256': result.model_sha256})
