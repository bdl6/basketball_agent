from dataclasses import dataclass
import json
import math
from pathlib import Path


@dataclass(frozen=True)
class DetectConfig:
    video: Path
    model: Path
    output: Path
    device: str = "auto"
    roi: tuple[int, int, int, int] | None = None
    coarse_fps: float = 10.0
    refine_fps: float = 30.0
    font: Path | None = None


def load_config(config_path: Path | None, overrides: dict) -> DetectConfig:
    values = {}
    base = Path.cwd()
    if config_path is not None:
        config_path = Path(config_path).resolve()
        values = json.loads(config_path.read_text(encoding="utf-8-sig"))
        if not isinstance(values, dict):
            raise ValueError("配置必须是 JSON 对象")
        base = config_path.parent
    allowed = set(DetectConfig.__dataclass_fields__)
    if set(values) - allowed:
        raise ValueError(f"未知配置项: {sorted(set(values) - allowed)}")
    # JSON paths belong to the JSON directory; CLI paths belong to the shell cwd.
    for name in ("video", "model", "output", "font"):
        if values.get(name):
            values[name] = (base / Path(values[name]).expanduser()).resolve()
    values.update({key: value for key, value in overrides.items() if value is not None})
    for name in ("video", "model"):
        if not values.get(name) or not str(values[name]).strip():
            raise ValueError(f"请配置 {name} 路径，或通过 --{name} 传入")
    values.setdefault("output", Path("runs"))
    for name in ("video", "model", "output", "font"):
        if values.get(name):
            values[name] = Path(values[name]).expanduser().resolve()
        elif name == "font":
            values[name] = None
    cfg = DetectConfig(**values)
    if cfg.device not in {"auto", "cpu", "cuda", "mps", "dml", "coreml"}:
        raise ValueError("device 不受支持")
    for name in ("coarse_fps", "refine_fps"):
        value = getattr(cfg, name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} 必须为正数")
    if cfg.roi is not None:
        roi = cfg.roi
        if (not isinstance(roi, (list, tuple)) or len(roi) != 4
                or any(isinstance(v, bool) or not isinstance(v, int) for v in roi)
                or roi[0] < 0 or roi[1] < 0 or roi[2] <= roi[0] or roi[3] <= roi[1]):
            raise ValueError("roi 必须为 [x1,y1,x2,y2] 整数且范围有效")
    return cfg
