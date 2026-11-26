import json
from pathlib import Path
import pytest
from basketball_detect.config import load_config
from basketball_detect.pipeline import analyze, recompute_checks


def test_empty_candidates_return_valid_analysis_without_refinement(tmp_path):
    video = tmp_path / 'v.mp4'
    model = tmp_path / 'm.pt'
    video.touch()
    model.write_bytes(b'model')
    cfg = load_config(None, {'video': video, 'model': model, 'roi': [0, 0, 100, 100]})
    def stage(script, args, output, log):
        if script == 'scan_video.py':
            return {'records': [], 'video': str(video)}
        if script == 'generate_candidates.py':
            return {'candidates': [], 'rim': {'center_x': 50, 'rim_y': 50, 'width': 20, 'height': 10}}
        raise AssertionError(f'Unexpected expensive stage: {script}')
    result = analyze(cfg, tmp_path, stage_runner=stage, metadata={'width': 100, 'height': 100, 'fps': 25, 'duration': 1})
    assert result.events == []
    assert result.rim['center_x'] == 50
    assert result.model_sha256


def test_auto_roi_failure_is_not_zero_goals(tmp_path):
    video = tmp_path / 'v.mp4'; video.touch()
    model = tmp_path / 'm.pt'; model.touch()
    cfg = load_config(None, {'video': video, 'model': model})
    with pytest.raises(RuntimeError, match='篮筐'):
        analyze(cfg, tmp_path, stage_runner=lambda *args: {'success': False},
                metadata={'width': 100, 'height': 100, 'fps': 25, 'duration': 1})


def test_checks_without_frames_remain_uncertain():
    match = {'time': 1, 'verdict': 'made', 'overlay': {'rim': {'center_x': 10, 'rim_y': 10, 'width': 30, 'height': 10}}}
    checks = recompute_checks([match], {'results': [{'status': 'made'}]})
    assert checks[0]['status'] == 'skipped'


def test_raw_rim_detections_are_recomputed_before_automatic_confirmation():
    from basketball_detect.events import classify_events
    rim = {'center_x': 160, 'rim_y': 80, 'width': 50, 'height': 20}
    frames = []
    for step in range(16):
        cx = 160 + (.3 - .5 * step / 15) * 50
        cy = 80 + (-1.5 + step * .25) * 50
        frames.append([] if step in {6, 7} else [{'name': 'ball', 'confidence': .85,
                         'xyxy': [cx-12.5, cy-12.5, cx+12.5, cy+12.5]}])
    match = {'time': .5, 'verdict': 'made', 'overlay': {'rim': rim}}
    checks = recompute_checks([match], {'results': [{'status': 'rejected', 'frames': frames}]})
    assert checks[0]['status'] == 'made'  # Cached status is deliberately wrong.
    assert classify_events([match], checks)[0]['label'] == 'made'
