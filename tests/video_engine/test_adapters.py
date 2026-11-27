import subprocess
from pathlib import Path

import pytest
from contracts.models import EditPlan, Event
from video_engine.highlights import build_intervals, render_highlights
from video_engine.media import probe


def event(identifier, time, label='made'):
    return Event(id=identifier, time=time, label=label)


def test_intervals_clamp_sort_merge_and_keep_event_ordinals():
    events = [event('last', 19), event('second', 4), event('first', 1),
              event('unclear', 10, 'uncertain'), event('miss', 12, 'missed')]
    intervals, ids = build_intervals(events, EditPlan(), 20)
    assert intervals == [(0, 6), (14, 20)]
    assert ids == ['first', 'second', 'last']
    intervals, ids = build_intervals(events, EditPlan(before_seconds=8, excluded_event_ids=['second']), 20)
    assert intervals == [(0, 3), (11, 20)]
    assert ids == ['first', 'last']


@pytest.mark.parametrize('events,plan', [
    ([], EditPlan()),
    ([event('maybe', 3, 'uncertain')], EditPlan()),
    ([event('one', 3)], EditPlan(excluded_event_ids=['one'])),
    ([event('one', 3)], EditPlan(before_seconds=0, after_seconds=0)),
    ([event('same', 2), event('same', 3)], EditPlan()),
    ([event('outside', 21)], EditPlan()),
])
def test_invalid_or_empty_selection_never_builds_empty_movie(events, plan):
    with pytest.raises(ValueError):
        build_intervals(events, plan, 20)




def make_source(path, audio):
    command = ['ffmpeg', '-v', 'error', '-n', '-f', 'lavfi', '-i',
               'testsrc2=s=160x120:r=10:d=12']
    if audio:
        command += ['-f', 'lavfi', '-i', 'sine=frequency=440:duration=8']
    command += ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(path)]
    subprocess.run(command, check=True, capture_output=True)


@pytest.mark.parametrize('audio', [True, False])
def test_render_real_mp4_clamps_excludes_preserves_optional_audio(tmp_path, audio):
    source = tmp_path / 'source.mp4'
    make_source(source, audio)
    destination = tmp_path / 'new-revision.mp4'
    result = render_highlights(source, [event('tail', 11.5), event('excluded', 3), event('head', .5),
                                       event('unclear', 5, 'uncertain')],
                               EditPlan(excluded_event_ids=['excluded']), destination)
    assert result.event_ids == ['head', 'tail']
    assert result.path == str(destination.resolve())
    assert result.duration_seconds == pytest.approx(8, abs=.15)
    data = probe(destination, count_frames=True)
    video = next(s for s in data['streams'] if s['codec_type'] == 'video')
    assert video['codec_name'] == 'h264'
    assert video['pix_fmt'] == 'yuv420p'
    assert int(video['nb_read_frames']) == 80
    audio_stream = next((s for s in data['streams'] if s['codec_type'] == 'audio'), None)
    assert (audio_stream is not None) is audio
    if audio:
        assert audio_stream['codec_name'] == 'aac'
        assert float(audio_stream['duration']) == pytest.approx(8, abs=.15)
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(destination), '-f', 'null', '-'], check=True, capture_output=True)
    assert not list(tmp_path.glob('.*.tmp.mp4'))


def test_render_merges_overlaps_instead_of_repeating_footage(tmp_path):
    source = tmp_path / 'source.mp4'
    make_source(source, False)
    result = render_highlights(source, [event('two', 3), event('one', 1)], EditPlan(), tmp_path / 'out.mp4')
    assert result.event_ids == ['one', 'two']
    assert result.duration_seconds == pytest.approx(5, abs=.1)


def test_existing_result_and_source_are_never_overwritten(tmp_path):
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'original')
    previous = tmp_path / 'previous.mp4'
    previous.write_bytes(b'valid previous result')
    with pytest.raises(ValueError):
        render_highlights(source, [event('one', 1)], EditPlan(), source)
    with pytest.raises(FileExistsError):
        render_highlights(source, [event('one', 1)], EditPlan(), previous)
    assert source.read_bytes() == b'original'
    assert previous.read_bytes() == b'valid previous result'




def test_failed_output_validation_keeps_previous_result_and_removes_partial(tmp_path, monkeypatch):
    from video_engine import highlights
    source = tmp_path / 'source.mp4'
    make_source(source, False)
    previous = tmp_path / 'previous.mp4'
    previous.write_bytes(b'previous verified result')
    destination = tmp_path / 'replacement.mp4'
    monkeypatch.setattr(highlights, 'probe', lambda *args, **kwargs: {'streams': []})
    with pytest.raises(RuntimeError, match='校验失败'):
        render_highlights(source, [event('one', 1)], EditPlan(), destination)
    assert previous.read_bytes() == b'previous verified result'
    assert not destination.exists()
    assert not list(tmp_path.glob('.*.tmp.mp4'))


def test_import_does_not_load_heavy_detector_or_annotator_dependencies():
    import sys
    subprocess.run([sys.executable, '-c',
                    "import video_engine, sys; assert not {'cv2', 'torch', 'ultralytics'}.intersection(sys.modules)"],
                   check=True, capture_output=True)


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows long paths')
def test_render_publishes_long_windows_path_and_cleans_temporary(tmp_path):
    source = tmp_path / 'source.mp4'
    make_source(source, False)
    nested = tmp_path
    while len(str(nested)) < 280:
        nested = nested / ('nested-' + 'x' * 30)
    native = Path('//?/' + str(nested))
    native.mkdir(parents=True)
    destination = nested / 'result.mp4'
    result = render_highlights(source, [event('one', 1)], EditPlan(), destination)
    assert result.path == str(destination.resolve())
    published = native / 'result.mp4'
    assert published.stat().st_size > 0
    assert not list(native.glob('.*.tmp.mp4'))
    original = published.read_bytes()
    with pytest.raises(FileExistsError):
        render_highlights(source, [event('one',1)], EditPlan(), destination)
    assert published.read_bytes() == original
