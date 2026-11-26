from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

VENDOR = Path(__file__).resolve().parents[1] / 'vendor'
sys.path.insert(0, str(VENDOR / 'src'))
sys.path.insert(0, str(VENDOR / 'scripts'))
from basketball_highlight.sampling import canonical_sample_times, first_frame_index


def test_native_rate_sampling_does_not_skip_every_third_frame():
    times = canonical_sample_times(0, 1, 30)
    assert [first_frame_index(t, 30) for t in times] == list(range(30))


def test_coarse_and_refined_records_use_actual_source_frame_times(tmp_path, monkeypatch):
    from test_media_export import make_video
    import scan_video
    import refine_candidates
    source = tmp_path / 'source.mp4'; make_video(source)
    class Detector:
        def predict(self, images, **kwargs):
            return [SimpleNamespace(boxes=[], names={}) for _ in images]
    monkeypatch.setattr(scan_video, 'load_yolo_model', lambda _: Detector())
    monkeypatch.setattr(scan_video, 'select_device', lambda _: 'cpu')
    monkeypatch.setattr(scan_video, 'current_device', lambda: 'cpu')
    model = tmp_path / 'model.pt'; model.touch()
    args = SimpleNamespace(video=str(source), model=str(model), output=str(tmp_path / 'scan.json'),
        roi=[0,0,320,240],sample_fps=30,duration=None,time_offset=0,scale=1,batch=8,conf=.1,device='cpu',cache_dir=None)
    scan_video.scan_video(args)
    import json
    coarse = json.loads((tmp_path / 'scan.json').read_text(encoding='utf-8'))['records']
    refined = refine_candidates.scan_window(Detector(), source, [0,0,320,240], .5, .5, 30, 1, .1, 'cpu')
    for records in (coarse, refined):
        assert [record['frame'] for record in records] == list(range(30))
        for record in records:
            assert record['time'] == pytest.approx(record['frame'] / (30000/1001), abs=1e-6)
