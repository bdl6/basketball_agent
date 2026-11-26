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


def test_overlapping_windows_do_not_inflate_occlusion_calibration():
    rim = {'center_x': 160, 'rim_y': 80, 'width': 50, 'height': 20}
    matches, results = [], []
    # Only four physical events: below the eight-unique-event calibration floor.
    for repetition in range(2):
        for event in range(4):
            frames = []
            for step in range(16):
                cx = 160 + (.3 - .5 * step / 15) * 50
                cy = 80 + (-1.5 + step*.25)*50
                frames.append([] if event == 3 and step in {6,7} else [{'name':'ball','confidence':.85,
                    'xyxy':[cx-12.5,cy-12.5,cx+12.5,cy+12.5]}])
            matches.append({'time':event*3+1,'verdict':'made','overlay':{'rim':rim}})
            results.append({'frames':frames})
    checks = recompute_checks(matches, {'results':results})
    assert all(check['status'] != 'made' for check in checks[:3])
    assert checks[3]['status'] == 'made'


def test_thin_net_calibration_without_motion_measurements_stays_uncertain():
    rim = {'center_x':160,'rim_y':80,'width':50,'height':20}
    frames = []
    for i in range(16):
        cy = 80 + (-1.5+i*.25)*50
        frames.append([{'name':'ball','confidence':.85,'xyxy':[147.5,cy-12.5,172.5,cy+12.5]}])
    matches = [{'time':i*3+1,'verdict':'made','overlay':{'rim':rim}} for i in range(8)]
    checks = recompute_checks(matches, {'results':[{'frames':frames} for _ in matches]})
    assert all(c['status'] == 'unsure' for c in checks)


@pytest.mark.parametrize("automatic_roi", [
    {"x1": 10, "y1": 0, "x2": 90, "y2": 80},
    [10, 0, 90, 80],
])
def test_successful_auto_roi_is_passed_as_coordinates(tmp_path, automatic_roi):
    video = tmp_path / "v.mp4"
    model = tmp_path / "m.pt"
    video.touch()
    model.write_bytes(b"model")
    cfg = load_config(None, {"video": video, "model": model})
    observed = []
    def stage(script, args, output, log):
        if script == "detect_auto_roi.py":
            return {"success": True, "roi": automatic_roi}
        if script == "scan_video.py":
            start = args.index("--roi") + 1
            observed.extend(args[start:start + 4])
            return {"records": []}
        if script == "generate_candidates.py":
            return {"candidates": [], "rim": {"center_x": 50}}
        raise AssertionError(script)
    result = analyze(cfg, tmp_path, stage_runner=stage,
                     metadata={"width": 100, "height": 100, "fps": 25, "duration": 1})
    assert observed == ["10", "0", "90", "80"]
    assert result.events == []
