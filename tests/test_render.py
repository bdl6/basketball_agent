from basketball_detect.pipeline import AnalysisResult
from basketball_detect.render import OverlayTimeline


def test_event_boundaries_and_count_are_based_on_event_time():
    analysis = AnalysisResult(events=[{'id': 1, 'time': .1, 'label': 'made', 'rim': None, 'trajectory': []},
                                    {'id': 2, 'time': 2.9, 'label': 'uncertain', 'rim': None, 'trajectory': []}])
    timeline = OverlayTimeline(analysis, 3)
    assert timeline.at(0)['count'] == 0
    assert timeline.at(.1)['count'] == 1
    assert timeline.at(1)['count'] == 1
    assert timeline.at(2.99)['label'] == 'uncertain'


def test_empty_events_do_not_display_missed():
    state = OverlayTimeline(AnalysisResult(), 3).at(1)
    assert state['label'] == 'idle'
    assert state['count'] == 0


def test_trajectory_has_no_future_points_or_links_across_gaps():
    event = {'id': 1, 'time': .5, 'label': 'made', 'rim': None, 'trajectory': [
        {'time': .1, 'x': 10, 'y': 20}, {'time': .15, 'x': 11, 'y': 22},
        {'time': .5, 'x': 30, 'y': 35}, {'time': .6, 'x': 40, 'y': 50}]}
    state = OverlayTimeline(AnalysisResult(events=[event]), 3).at(.5)
    assert state['segments'] == [((10, 20), (11, 22))]
    assert state['balls'] == []


def test_ball_box_uses_source_coordinates_and_expires():
    analysis = AnalysisResult(metadata={'fps': 30}, records=[{'time': .1, 'frame': 3, 'detections': [
        {'name': 'ball', 'confidence': .9, 'xyxy': [100, 200, 110, 210]}]}])
    timeline = OverlayTimeline(analysis, 3)
    assert timeline.at(.1)['balls'] == [[100, 200, 110, 210]]
    assert timeline.at(.5)['balls'] == []


def test_detection_box_is_not_projected_onto_adjacent_frames():
    analysis = AnalysisResult(metadata={'fps': 30}, records=[{'time': .1, 'frame': 3, 'detections': [
        {'name': 'ball', 'xyxy': [10,20,30,40]}]}])
    timeline = OverlayTimeline(analysis, 1)
    assert timeline.at(2/30)['balls'] == []
    assert timeline.at(3/30)['balls'] == [[10,20,30,40]]
    assert timeline.at(4/30)['balls'] == []
