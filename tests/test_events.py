import pytest
from basketball_detect.events import classify_events, collect_matches


@pytest.mark.parametrize('verdict,status,reason,want', [
    ('made', 'made', None, 'made'),
    ('ambiguous', 'made', None, 'uncertain'),
    ('made', 'rejected', 'rebound', 'uncertain'),
    ('missed', 'made', None, 'uncertain'),
    ('missed', 'rejected', 'rebound', 'missed'),
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
