import json
import math
from pathlib import Path
import shutil
import subprocess


def require_tools():
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise RuntimeError(f"未找到 {tool}，请安装 FFmpeg 并加入 PATH")


def probe(video: Path, *, count_frames=False) -> dict:
    require_tools()
    command = ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json"]
    if count_frames:
        command.append("-count_frames")
    result = subprocess.run([*command, str(video)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"无法读取视频: {video}\n{result.stderr[-2000:]}")
    return json.loads(result.stdout)


def inspect_video(video: Path) -> dict:
    if not video.is_file():
        raise ValueError(f"视频不存在: {video}")
    data = probe(video)
    stream = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if stream is None:
        raise ValueError("输入不含视频流")
    def rate(text):
        numerator, denominator = text.split("/")
        return float(numerator) / float(denominator) if float(denominator) else 0
    fps_text = stream.get("avg_frame_rate", "0/0")
    if not rate(fps_text):
        fps_text = stream.get("r_frame_rate", "0/0")
    fps = rate(fps_text)
    duration = float(stream.get("duration") or data["format"].get("duration", 0))
    if fps <= 0 or not math.isfinite(fps) or duration <= 0 or not math.isfinite(duration):
        raise ValueError("视频帧率或时长无效")
    # Upstream uses OpenCV source-frame coordinates; reject transforms it cannot preserve.
    rotation = float(stream.get("tags", {}).get("rotate", 0))
    rotation = next((float(s["rotation"]) for s in stream.get("side_data_list", []) if "rotation" in s), rotation)
    if rotation % 360:
        raise ValueError("首版请先将带旋转元数据的视频转成正向画面再处理")
    real_rate = rate(stream.get("r_frame_rate", "0/0"))
    if real_rate and abs(real_rate - fps) / fps > 0.01:
        raise ValueError("首版请先将可变帧率视频转为恒定帧率，避免事件时间偏移")
    audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    return {"width": int(stream["width"]), "height": int(stream["height"]),
            "fps": fps, "duration": duration, "fps_text": fps_text,
            "video_start": float(stream.get("start_time", 0)),
            "audio_start": float(audio.get("start_time", 0)) if audio else 0,
            "has_audio": audio is not None}
