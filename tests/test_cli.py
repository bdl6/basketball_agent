import json
from pathlib import Path
import subprocess
import sys

from basketball_detect.__main__ import main
from basketball_detect.pipeline import AnalysisResult
from test_media_export import make_video


def test_cli_analysis_to_annotated_video_and_events(tmp_path, monkeypatch, capsys):
    # Only the expensive detector is injected; CLI, config, report and video export are real.
    import basketball_detect.app as app
    video = tmp_path / '原片.mp4'; make_video(video, audio=True)
    model = tmp_path / 'm.pt'; model.touch()
    def detector(config, run_dir, **kwargs):
        return AnalysisResult(events=[{'id': 1, 'time': .4, 'label': 'made', 'reason': 'fixture',
                                      'rim': None, 'trajectory': [], 'raw_evidence': []}],
                              metadata=kwargs['metadata'])
    monkeypatch.setattr(app, 'analyze', detector)
    args = ['--video', str(video), '--model', str(model), '--output', str(tmp_path / 'runs')]
    assert main(args) == 0
    output = Path(capsys.readouterr().out.strip())
    assert output.is_file()
    events = json.loads((output.parent / 'events.json').read_text(encoding='utf-8'))
    assert events['events'][0]['label'] == 'made'
    assert events['summary']['made'] == 1
    assert events['status'] == 'complete'
    assert main(args) == 0
    second = Path(capsys.readouterr().out.strip())
    assert second != output and output.is_file() and second.is_file()


def test_empty_config_exits_nonzero_with_actionable_message():
    result = subprocess.run([sys.executable, '-m', 'basketball_detect', '--config', 'config.example.json'],
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    assert result.returncode == 1
    assert 'video' in result.stderr
    assert 'Traceback' not in result.stderr


def test_failed_analysis_records_failure_without_final_video(tmp_path, monkeypatch):
    import basketball_detect.app as app
    from basketball_detect.config import load_config
    video = tmp_path / 'source.mp4'; make_video(video)
    model = tmp_path / 'm.pt'; model.touch()
    def broken(*args, **kwargs):
        raise RuntimeError('test detector unavailable')
    monkeypatch.setattr(app, 'analyze', broken)
    cfg = load_config(None, {'video': video, 'model': model, 'output': tmp_path / 'runs'})
    import pytest
    with pytest.raises(RuntimeError, match='unavailable'):
        app.run(cfg)
    reports = list((tmp_path / 'runs').glob('*/run.json'))
    assert len(reports) == 1
    assert json.loads(reports[0].read_text(encoding='utf-8'))['status'] == 'failed'
    assert not list((tmp_path / 'runs').glob('*/annotated.mp4'))
