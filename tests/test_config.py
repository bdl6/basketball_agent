import json
from pathlib import Path
import pytest
from basketball_detect.config import load_config


def test_empty_video_explains_configuration(tmp_path):
    with pytest.raises(ValueError, match='video'):
        load_config(None, {'video': ''})


def test_cli_overrides_config_and_resolves_paths(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'video': 'old.mp4', 'model': 'model.pt', 'output': 'runs'}))
    cfg = load_config(path, {'video': str(tmp_path / 'new.mp4')})
    assert cfg.video == tmp_path / 'new.mp4'
    assert cfg.model == tmp_path / 'model.pt'
    assert cfg.output == tmp_path / 'runs'


@pytest.mark.parametrize('override', [{'coarse_fps': 0}, {'refine_fps': float('nan')}, {'roi': [0, 0, 0, 10]}, {'roi': [-1, 0, 10, 10]}, {'device': 'bad'}])
def test_invalid_parameters_rejected(override):
    with pytest.raises(ValueError):
        load_config(None, {'video': 'v.mp4', 'model': 'm.pt', **override})
