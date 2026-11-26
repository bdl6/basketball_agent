"""Render verified, chronological highlights from the original source."""
from collections.abc import Sequence
import math
import os
from pathlib import Path
import subprocess
import uuid

from basketball_detect.media import inspect_video, probe
from contracts.models import EditPlan, Event, RenderResult


def build_intervals(events: Sequence[Event], plan: EditPlan, duration: float) -> tuple[list[tuple[float, float]], list[str]]:
    """Select events before merging clips, so event ordinals remain independent."""
    plan = EditPlan.model_validate(plan.model_dump())
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('原视频时长无效')
    if len({event.id for event in events}) != len(events):
        raise ValueError('事件 ID 重复')
    if any(not math.isfinite(event.time) or not 0 <= event.time <= duration for event in events):
        raise ValueError('事件时间超出原视频范围')
    selected = sorted((event for event in events if event.label == 'made'
                       and event.id not in plan.excluded_event_ids), key=lambda event: (event.time, event.id))
    if not selected:
        raise ValueError('没有可剪辑的可靠进球')
    intervals = []
    for event in selected:
        start, end = max(0, event.time - plan.before_seconds), min(duration, event.time + plan.after_seconds)
        if end <= start:
            raise ValueError('剪辑区间为空，请增加进球前后保留时长')
        if intervals and start <= intervals[-1][1]:
            intervals[-1] = (intervals[-1][0], max(intervals[-1][1], end))
        else:
            intervals.append((start, end))
    return intervals, [event.id for event in selected]


def _run(command: list[str]) -> None:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                   errors='replace', timeout=1800)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError('视频剪辑超时') from error
    if completed.returncode:
        raise RuntimeError(f'FFmpeg 视频剪辑或校验失败: {completed.stderr[-2000:]}')


def render_highlights(video_path: Path, events: Sequence[Event], plan: EditPlan, output_path: Path) -> RenderResult:
    video_path, output_path = Path(video_path).resolve(), Path(output_path).resolve()
    if video_path == output_path:
        raise ValueError('输出不能覆盖原视频')
    if output_path.exists():
        raise FileExistsError(f'输出已存在: {output_path}')
    meta = inspect_video(video_path)
    intervals, event_ids = build_intervals(events, plan, meta['duration'])
    duration = sum(end - start for start, end in intervals)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f'.{output_path.stem}-{uuid.uuid4().hex}.tmp.mp4')
    filters, labels = [], []
    offset = meta.get('video_start', 0) - meta.get('audio_start', 0)
    # Source event time starts at the first video frame. Align audio once to that origin.
    audio_origin = (f'asetpts=PTS-STARTPTS,atrim=start={max(0, offset):.9f},asetpts=PTS-STARTPTS,'
                    f'adelay={max(0, -offset) * 1000:.6f}:all=1,apad')
    for index, (start, end) in enumerate(intervals):
        filters.append(f'[0:v:0]setpts=PTS-STARTPTS,trim=start={start:.9f}:end={end:.9f},'
                       f'setpts=PTS-STARTPTS,pad=ceil(iw/2)*2:ceil(ih/2)*2,setsar=1[v{index}]')
        labels.append(f'[v{index}]')
        if meta['has_audio']:
            filters.append(f'[0:a:0]{audio_origin},atrim=start={start:.9f}:end={end:.9f},'
                           f'asetpts=PTS-STARTPTS[a{index}]')
            labels.append(f'[a{index}]')
    filters.append(''.join(labels) + f"concat=n={len(intervals)}:v=1:a={int(meta['has_audio'])}[video]"
                   + ('[audio]' if meta['has_audio'] else ''))
    command = ['ffmpeg', '-hide_banner', '-v', 'error', '-n', '-i', str(video_path),
               '-filter_complex', ';'.join(filters), '-map', '[video]']
    if meta['has_audio']:
        command += ['-map', '[audio]', '-c:a', 'aac']
    command += ['-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart', '-map_metadata', '-1', str(temporary)]
    try:
        _run(command)
        data = probe(temporary, count_frames=True)
        video = next((stream for stream in data.get('streams', []) if stream['codec_type'] == 'video'), None)
        audio = next((stream for stream in data.get('streams', []) if stream['codec_type'] == 'audio'), None)
        tolerance = max(.15, (len(intervals) + 1) / meta['fps'])
        if (video is None or video.get('codec_name') != 'h264' or video.get('pix_fmt') != 'yuv420p'
                or int(video.get('nb_read_frames', 0)) <= 0
                or abs(float(video.get('duration', 0)) - duration) > tolerance):
            raise RuntimeError('导出视频编码、帧数或时长校验失败')
        if meta['has_audio'] and (audio is None or audio.get('codec_name') != 'aac'
                                 or abs(float(audio.get('duration', 0)) - duration) > tolerance):
            raise RuntimeError('导出视频音频校验失败')
        _run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(temporary), '-f', 'null', '-'])
        # Same-directory hard link publishes a verified file atomically and refuses overwrite.
        os.link(temporary, output_path)
        return RenderResult(path=str(output_path), duration_seconds=float(video['duration']), event_ids=event_ids)
    finally:
        temporary.unlink(missing_ok=True)
