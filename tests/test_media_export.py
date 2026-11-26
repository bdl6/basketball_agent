import subprocess
from pathlib import Path
import pytest
import cv2
from basketball_detect.media import probe
from basketball_detect.pipeline import AnalysisResult
from basketball_detect.render import render_video


def make_video(path, *, audio=False, odd=False):
    size = '321x241' if odd else '320x240'
    cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c=gray:s={size}:r=30000/1001:d=1.001,format=yuv444p']
    if odd:
        # color source internally rounds; pad explicitly creates an odd source size.
        cmd += ['-vf', 'pad=321:241']
    if audio:
        # Add audio as a second input; output options follow all inputs.
        cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=gray:s=320x240:r=30000/1001:d=1.001',
               '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.8']
    cmd += ['-c:v', 'libx264', '-pix_fmt', 'yuv444p', '-c:a', 'aac', str(path)]
    subprocess.run(cmd, check=True, capture_output=True)


@pytest.mark.parametrize('audio,odd', [(False, False), (True, False), (False, True)])
def test_render_preserves_frames_audio_and_valid_h264(tmp_path, audio, odd):
    source = tmp_path / 'source.mp4'
    make_video(source, audio=audio, odd=odd)
    destination = tmp_path / 'annotated.mp4'
    render_video(source, AnalysisResult(), destination)
    before, after = probe(source, count_frames=True), probe(destination, count_frames=True)
    src_v = next(s for s in before['streams'] if s['codec_type'] == 'video')
    out_v = next(s for s in after['streams'] if s['codec_type'] == 'video')
    assert out_v['codec_name'] == 'h264'
    assert out_v['nb_read_frames'] == src_v['nb_read_frames'] == '30'
    assert abs(float(out_v['duration']) - float(src_v['duration'])) < .04
    assert any(s['codec_type'] == 'audio' for s in after['streams']) is audio
    assert out_v['width'] % 2 == out_v['height'] % 2 == 0
    cap = cv2.VideoCapture(str(destination)); ok, frame = cap.read(); cap.release()
    assert ok and frame[-70:].std() > 10  # Bottom status banner is drawn on the gray input.


def test_source_and_existing_destination_are_protected(tmp_path):
    source = tmp_path / 'source.mp4'; source.write_bytes(b'original')
    with pytest.raises(ValueError):
        render_video(source, AnalysisResult(), source)
    existing = tmp_path / 'out.mp4'; existing.write_bytes(b'old output')
    with pytest.raises(FileExistsError):
        render_video(source, AnalysisResult(), existing)
    assert source.read_bytes() == b'original'
    assert existing.read_bytes() == b'old output'
