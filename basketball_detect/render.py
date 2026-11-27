"""Draw source-coordinate evidence and export a full-length H.264 video."""
from bisect import bisect_right
from functools import lru_cache
import os
from pathlib import Path
import subprocess
import uuid

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .media import inspect_video, probe
from .pipeline import AnalysisResult

LABELS = {"idle": "分析完成 · 无当前候选", "made": "进球", "probable": "疑似进球", "missed": "未进", "uncertain": "无法确认"}
COLORS = {"idle": (230, 230, 230), "made": (70, 235, 110), "probable": (255, 180, 70), "missed": (255, 90, 80), "uncertain": (255, 210, 70)}


class OverlayTimeline:
    def __init__(self, analysis: AnalysisResult, duration: float):
        self.analysis = analysis
        self.duration = duration
        self.events = sorted(analysis.events, key=lambda event: event["time"])
        self.event_times = [event["time"] for event in self.events]
        self.goal_times = [event["time"] for event in self.events if event["label"] == "made"]
        self.records = sorted(analysis.records, key=lambda record: record["time"])
        self.fps = analysis.metadata.get("fps", 0)
        self.frame_records = {record["frame"]: record for record in self.records if "frame" in record}

    def at(self, timestamp: float) -> dict:
        # Offline verdict may appear 0.25s before crossing; count changes at crossing.
        index = bisect_right(self.event_times, timestamp + .25) - 1
        active = self.events[index] if index >= 0 and timestamp <= min(self.duration, self.events[index]["time"] + 1.8) else None
        label = active["label"] if active else "idle"
        points = sorted((p for p in (active or {}).get("trajectory", [])
                         if timestamp - .7 <= p["time"] <= timestamp), key=lambda point: point["time"])
        segments = [((int(a["x"]), int(a["y"])), (int(b["x"]), int(b["y"])))
                    for a, b in zip(points, points[1:]) if 0 < b["time"] - a["time"] <= .2]
        balls = []
        record = self.frame_records.get(round(timestamp * self.fps)) if self.fps else None
        if record:
            balls = [d["xyxy"] for d in record.get("detections", []) if d.get("name") == "ball"]
        return {"label": label, "count": bisect_right(self.goal_times, timestamp),
                "event_id": active.get("id") if active else None,
                "event_time": active["time"] if active else None,
                "rim": (active or {}).get("rim") or self.analysis.rim,
                "segments": segments, "balls": balls}


def find_font(custom: Path | None = None) -> Path:
    candidates = [custom] if custom else [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc",
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/simhei.ttf",
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate
    raise ValueError("未找到中文字体，请通过 --font 指定支持中文的 TTF/TTC 字体")


class Annotator:
    def __init__(self, width: int, font: Path | None):
        self.font = ImageFont.truetype(str(find_font(font)), max(12, min(32, width // 25)))
        self.width = width

    @lru_cache(maxsize=128)
    def banner(self, label, count, event_id, event_time):
        lines = [f"离线检测  |  确认进球：{count}", LABELS[label]]
        if event_id is not None:
            lines[1] += f"  #{event_id}  {event_time:.2f}s"
        else:
            lines.append("证据不足的事件不会计入进球")
        bbox = self.font.getbbox("篮球检测")
        line_height = bbox[3] - bbox[1] + 10
        image = Image.new("RGB", (self.width, len(lines) * line_height + 12), (18, 24, 32))
        draw = ImageDraw.Draw(image)
        for i, line in enumerate(lines):
            draw.text((10, 4 + i * line_height), line, font=self.font,
                      fill=COLORS[label] if i == 1 else (240, 240, 240))
        return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)

    def draw(self, frame, state):
        color = tuple(reversed(COLORS[state["label"]]))
        rim = state["rim"]
        if rim:
            cx, cy, width, height = (float(rim[k]) for k in ("center_x", "rim_y", "width", "height"))
            cv2.rectangle(frame, (round(cx-width/2), round(cy-height/2)),
                          (round(cx+width/2), round(cy+height/2)), (255, 220, 50), 2)
        for a, b in state["segments"]:
            cv2.line(frame, a, b, color, 2, cv2.LINE_AA)
        for box in state["balls"]:
            x1, y1, x2, y2 = map(round, box)
            cv2.rectangle(frame, (x1, y1), (x2, y2), (40, 170, 255), 2)
        banner = self.banner(state["label"], state["count"], state["event_id"], state["event_time"])
        height = min(frame.shape[0], banner.shape[0])
        # Bottom banner keeps the rim visible for typical half-court framing.
        frame[-height:, :self.width] = banner[:height]
        return frame


def render_video(video: Path, analysis: AnalysisResult, destination: Path, *, font: Path | None = None) -> Path:
    video, destination = Path(video).resolve(), Path(destination).resolve()
    if video == destination:
        raise ValueError("输出不能覆盖输入视频")
    if destination.exists():
        raise FileExistsError(f"输出已存在: {destination}")
    meta = inspect_video(video)
    destination.parent.mkdir(parents=True, exist_ok=True)
    annotator = Annotator(meta["width"], font)
    analysis.metadata = meta
    timeline = OverlayTimeline(analysis, meta["duration"])
    temporary = destination.with_name(f".{destination.stem}-{uuid.uuid4().hex}.tmp.mp4")
    log_path = destination.parent / "render.log"
    fps = meta["fps_text"] or str(meta["fps"])
    offset = meta.get("video_start", 0) - meta.get("audio_start", 0)
    audio_filter = f"asetpts=PTS-STARTPTS,atrim=start={max(0, offset):.9f},asetpts=PTS-STARTPTS,adelay={max(0, -offset)*1000:.6f}:all=1,apad"
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-n", "-f", "rawvideo", "-pix_fmt", "bgr24",
               "-s", f"{meta['width']}x{meta['height']}", "-r", fps, "-i", "pipe:0", "-i", str(video),
               "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "libx264", "-preset", "fast", "-crf", "20",
               "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-pix_fmt", "yuv420p", "-c:a", "aac",
               "-af", audio_filter, "-shortest", "-movflags", "+faststart", "-map_metadata", "-1", str(temporary)]
    cap = cv2.VideoCapture(str(video))
    count = 0
    process = None
    try:
        if not cap.isOpened():
            raise RuntimeError("OpenCV 无法解码输入视频")
        expected_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log)
            try:
                while True:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    if frame.shape[:2] != (meta["height"], meta["width"]):
                        raise RuntimeError("视频解码尺寸与元数据不一致")
                    frame = annotator.draw(frame, timeline.at(count / meta["fps"]))
                    process.stdin.write(frame.tobytes())
                    count += 1
            finally:
                process.stdin.close()
            returncode = process.wait()
        if returncode:
            raise RuntimeError(f"FFmpeg 编码失败: {log_path.read_text(encoding='utf-8', errors='replace')[-2000:]}")
        if not count or (expected_frames > 0 and count != expected_frames):
            raise RuntimeError(f"视频未完整解码: {count}/{expected_frames} 帧")
        output = probe(temporary, count_frames=True)
        stream = next(s for s in output["streams"] if s["codec_type"] == "video")
        duration = float(stream.get("duration", 0))
        if (stream["codec_name"] != "h264" or int(stream.get("nb_read_frames", 0)) != count
                or abs(duration - meta["duration"]) > max(.1, 2 / meta["fps"])):
            raise RuntimeError("导出视频帧数、时长或编码校验失败")
        if meta["has_audio"] and not any(s["codec_type"] == "audio" for s in output["streams"]):
            raise RuntimeError("导出视频缺少原音频")
        # rename refuses an existing destination on Windows, and avoids a partial final MP4.
        temporary.rename(destination)
        return destination
    except BrokenPipeError as exc:
        raise RuntimeError(f"FFmpeg 提前退出，请检查 {log_path}") from exc
    finally:
        cap.release()
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        if temporary.exists():
            temporary.unlink()
