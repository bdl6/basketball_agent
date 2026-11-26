import pytest
from basketball_detect.events import classify_events, collect_matches


@pytest.mark.parametrize('verdict,status,reason,want', [
    ('made', 'made', None, 'made'),
    ('ambiguous', 'made', None, 'uncertain'),
    ('made', 'rejected', 'rebound', 'uncertain'),
    ('missed', 'made', None, 'uncertain'),
    ('missed', 'rejected', 'rebound', 'missed'),
    ('ambiguous', 'rejected', 'rebound', 'missed'),
    ('ambiguous', 'skipped', 'small_rim', 'uncertain'),
    ('ambiguous', 'unsure', 'no_crossing', 'uncertain'),
])
def test_evidence_agreement_required(verdict, status, reason, want):
    result = classify_events([{'time': 1.0, 'state': 'confirmed', 'verdict': verdict}],
                             [{'status': status, 'reason': reason}])
    assert result[0]['label'] == want


def test_missing_check_and_duplicate_are_not_extra_goals():
    events = classify_events([{'time': 1, 'verdict': 'made'}, {'time': 1.2, 'verdict': 'made'}], [])
    assert len(events) == 1
    assert events[0]['label'] == 'uncertain'


def test_duplicate_conflicting_results_do_not_hide_negative_evidence():
    events = classify_events([{'time': 1, 'verdict': 'made'}, {'time': 1.2, 'verdict': 'missed'}],
                             [{'status': 'made'}, {'status': 'rejected', 'reason': 'rebound'}])
    assert len(events) == 1
    assert events[0]['label'] == 'uncertain'


def test_failed_refinement_retains_uncertain_coarse_candidate():
    matches = collect_matches({'results': [{'coarse': {'time': 1.5}, 'refined': [],
        'rim_local': {'center_x': 20, 'rim_y': 30, 'width': 20, 'height': 8},
        'fallback_trajectory': [{'time': 1.4, 'x': 20, 'y': 25}]}]})
    assert matches[0]['coarse_crossing'] is True
    assert matches[0]['overlay']['trajectory'][0]['x'] == 20
    assert classify_events(matches, [{'status': 'made'}])[0]['label'] == 'uncertain'


def test_producer_deduplication_preserves_conflicting_hypotheses():
    from basketball_detect.pipeline import VENDOR
    import sys
    sys.path.insert(0, str(VENDOR / 'src'))
    from basketball_highlight.ranking import dedupe_candidates
    first = [{'time': 1, 'verdict': 'made'}, {'time': 1.1, 'verdict': 'missed'}]
    # Both upstream producer dedupe passes must carry their losing evidence.
    inner = dedupe_candidates(first, 2, preserve_evidence=True)
    outer = dedupe_candidates(inner, 2, preserve_evidence=True)
    matches = collect_matches({'results': [{'refined': outer}]})
    assert {m['verdict'] for m in matches} == {'made', 'missed'}
    events = classify_events(matches, [{'status': 'made'}] * len(matches))
    assert events[0]['label'] == 'uncertain'


@pytest.mark.parametrize('resumed,want', [(False,'missed'), (True,'uncertain')])
def test_actual_rebound_observations_can_reach_missed_class(resumed, want):
    from basketball_detect.pipeline import recompute_checks, VENDOR
    import sys
    sys.path.insert(0, str(VENDOR / 'src'))
    from basketball_highlight.events import find_refined_crossings
    rim = {'center_x':160, 'rim_y':80, 'width':50, 'height':20}
    def frame(y):
        cy = 80 + y*50
        return [{'name':'ball','confidence':.85,'xyxy':[147.5,cy-12.5,172.5,cy+12.5],'center':[160,cy]}]
    frames = [[] if i == 6 else frame(-1.5+i*.25) for i in range(16)]
    frames = frames[:10] + [frame(.25), frame(.3)] + (frames[10:] if resumed else [])
    records = [{'frame':i,'time':i/30,'detections':f} for i,f in enumerate(frames)]
    refined = find_refined_crossings(records, rim)
    matches = collect_matches({'results':[{'coarse':{'time':.2},'refined':refined,
                                           'rim_local':rim,'fallback_trajectory':[]}]})
    checks = recompute_checks(matches, {'results':[{'frames':frames} for _ in matches]})
    assert any(check['reason'] == 'rebound' for check in checks)
    assert classify_events(matches, checks)[0]['label'] == want


def test_neighboring_goal_does_not_swallow_unrefined_seed():
    matches = collect_matches({'results':[{'coarse':{'time':5},
        'refined':[{'time':7,'verdict':'made'}], 'rim_local':None, 'fallback_trajectory':[]}]})
    assert {m['time'] for m in matches} == {5,7}
