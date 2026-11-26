from pathlib import Path
import json
import httpx
import pytest
from agent.graph import create_graph
from agent.interpret import Interpretation, OpenAIInterpreter
from agent.tools import apply_operations
from contracts.models import Analysis, EditPlan, Event, Operation, RenderResult

EVENTS = [Event(id=f'e{i}', time=i * 10, label='made') for i in range(1, 4)]

def state(tmp_path, **updates):
    return dict(video_path=tmp_path/'in.mp4', work_dir=tmp_path, model_path=tmp_path/'m.pt',
                events=None, plan=EditPlan().model_dump(), displayed_event_ids=[], text=None,
                pending_context=None, on_stage=lambda stage: None, **updates)

def harness(answer):
    calls = {'analysis': 0, 'render': 0, 'texts': []}
    def analyze(*args, **kwargs):
        calls['analysis'] += 1
        return Analysis(events=EVENTS, duration_seconds=50)
    def render(video, events, plan, output):
        calls['render'] += 1
        return RenderResult(path=str(output), duration_seconds=10,
                            event_ids=[e.id for e in events if e.label == 'made' and e.id not in plan.excluded_event_ids])
    def interpret(text, **kwargs):
        calls['texts'].append(text)
        return answer
    return create_graph(interpreter=interpret, analyzer=analyze, renderer=render), calls

def test_initial_and_composite_modification_reuse_analysis(tmp_path):
    graph, calls = harness(Interpretation(status='apply', operations=[
        Operation(op='exclude', ordinal=2), Operation(op='add_before', value=3)]))
    first = graph.invoke(state(tmp_path))
    next_state = state(tmp_path)
    next_state.update({k:first[k] for k in ('events','plan','displayed_event_ids')})
    next_state['text'] = '去掉第二球，每球前面多留三秒'
    result = graph.invoke(next_state)
    assert calls['analysis'] == 1 and calls['render'] == 2
    assert result['plan']['before_seconds'] == 8
    assert result['plan']['excluded_event_ids'] == ['e2']
    assert result['displayed_event_ids'] == ['e1','e3']
    assert first['result_path'] != result['result_path']
    assert set(graph.get_graph().nodes) >= {'interpret','clarify','analyze','plan','render'}

@pytest.mark.parametrize('operations', [
    [Operation(op='exclude',ordinal=4)],
    [Operation(op='add_before',value=60)],
    [Operation(op='exclude',ordinal=i) for i in (1,2,3)],
])
def test_invalid_operations_are_atomic(tmp_path, operations):
    graph, calls = harness(Interpretation(status='apply',operations=operations))
    initial = state(tmp_path)
    initial.update(events=[e.model_dump() for e in EVENTS], displayed_event_ids=['e1','e2','e3'],text='修改')
    result = graph.invoke(initial)
    assert result['result_path'] is None and result['message']
    assert result['plan'] == EditPlan().model_dump()
    assert calls['render'] == calls['analysis'] == 0

def test_ordinals_share_snapshot_and_no_duplicate_exclusions():
    result = apply_operations(EVENTS, EditPlan(), ['e1','e2','e3'],
                              [Operation(op='exclude',ordinal=i) for i in (1,2,1)])
    assert result.excluded_event_ids == ['e1','e2']


def test_clarification_context_and_unavailable(tmp_path):
    graph, calls = harness(Interpretation(status='clarify',message='前面还是后面？'))
    initial = state(tmp_path)
    initial.update(events=[e.model_dump() for e in EVENTS],text='多留三秒',displayed_event_ids=['e1','e2','e3'])
    result = graph.invoke(initial)
    assert result['pending_context']['original_text'] == '多留三秒'
    assert result['result_path'] is None and calls['render'] == 0
    second = dict(initial, text='前面',pending_context=result['pending_context'])
    graph.invoke(second)
    assert '多留三秒' in calls['texts'][-1] and '前面' in calls['texts'][-1]
    graph, calls = harness(Interpretation(status='unsupported',message='暂不支持配乐'))
    result = graph.invoke(initial)
    assert result['result_path'] is None and result['pending_context'] is None
    assert calls['render'] == 0


def test_empty_analysis_is_not_repeated(tmp_path):
    graph, calls = harness(Interpretation(status='apply',operations=[Operation(op='set_before',value=8)]))
    initial = state(tmp_path)
    initial.update(events=[], text='前面八秒')
    result = graph.invoke(initial)
    assert calls['analysis'] == calls['render'] == 0
    assert result['result_path'] is None and '进球' in result['message']


def test_no_made_events_no_render(tmp_path):
    graph,calls = harness(None)
    initial=state(tmp_path)
    initial['events']=[Event(id='u',time=1,label='uncertain').model_dump()]
    result=graph.invoke(initial)
    assert calls['render']==0 and result['result_path'] is None


def model_client(payload, status=200):
    def respond(request):
        body=json.loads(request.content)
        assert request.url.path == '/v1/chat/completions'
        assert body['response_format']['type']=='json_object'
        assert request.headers['Authorization']=='Bearer secret'
        return httpx.Response(status,json=payload)
    return httpx.Client(transport=httpx.MockTransport(respond))


def test_openai_compatible_structured_parser():
    answer={'status':'apply','operations':[{'op':'exclude','ordinal':2},{'op':'add_before','value':3}]}
    interpreter=OpenAIInterpreter(base_url='https://example.test/v1',api_key='secret',model='model',
            client=model_client({'choices':[{'message':{'content':json.dumps(answer)}}]}))
    result=interpreter('去掉第二球，每球前面多留三秒',events=EVENTS,plan=EditPlan(),displayed_event_ids=['e1','e2','e3'])
    assert result.operations[1].value==3

@pytest.mark.parametrize('payload,status', [({'error':'secret'},401),
    ({'choices':[{'message':{'content':'not JSON'}}]},200),
    ({'choices':[{'message':{'content':'{"status":"apply","operations":[{"op":"shell","value":3}]}'}}]},200),
    ({'choices':[{'message':{'content':'{"status":"clarify","operations":[{"op":"set_before","value":3}],"message":"?"}'}}]},200)])
def test_model_failures_sanitized(payload,status):
    interpreter=OpenAIInterpreter(base_url='https://example.test/v1',api_key='secret',model='model',client=model_client(payload,status))
    with pytest.raises(RuntimeError) as error:
        interpreter('改一下',events=EVENTS,plan=EditPlan(),displayed_event_ids=['e1'])
    assert 'secret' not in str(error.value)


def test_http_interpreter_runs_core_composite_in_real_graph(tmp_path):
    answer={'status':'apply','operations':[{'op':'exclude','ordinal':2},{'op':'add_before','value':3}]}
    interpreter=OpenAIInterpreter(base_url='https://example.test/v1',api_key='secret',model='model',
        client=model_client({'choices':[{'message':{'content':json.dumps(answer)}}]}))
    outputs=[]
    def render(video, events, plan, output):
        outputs.append(plan)
        return RenderResult(path=str(output),duration_seconds=10,event_ids=['e1','e3'])
    graph=create_graph(interpreter=interpreter, analyzer=lambda *a,**k: pytest.fail('modification analyzed again'),renderer=render)
    initial=state(tmp_path)
    initial.update(events=[e.model_dump() for e in EVENTS],displayed_event_ids=['e1','e2','e3'],
                   text='去掉第二球，每球前面多留三秒')
    result=graph.invoke(initial)
    assert outputs[0].before_seconds==8 and outputs[0].after_seconds==2
    assert result['displayed_event_ids']==['e1','e3']
    assert result['plan']['excluded_event_ids']==['e2']


def test_next_ordinal_uses_new_display_and_set_vs_add():
    first=apply_operations(EVENTS,EditPlan(),['e1','e2','e3'],[Operation(op='exclude',ordinal=2)])
    second=apply_operations(EVENTS,first,['e1','e3'],[
        Operation(op='exclude',ordinal=2), Operation(op='set_before',value=8),
        Operation(op='set_after',value=3),Operation(op='add_after',value=1)])
    assert second.excluded_event_ids==['e2','e3']
    assert second.before_seconds==8 and second.after_seconds==4


def test_transport_timeout_is_bounded_and_sanitized():
    def fail(request):
        assert request.extensions['timeout']['read']==45
        assert request.extensions['timeout']['connect']==10
        raise httpx.ReadTimeout('secret',request=request)
    interpreter=OpenAIInterpreter(base_url='https://example.test/v1',api_key='secret',model='model',
                                client=httpx.Client(transport=httpx.MockTransport(fail)))
    with pytest.raises(RuntimeError,match='模型服务调用失败') as error:
        interpreter('修改',events=EVENTS,plan=EditPlan(),displayed_event_ids=['e1'])
    assert 'secret' not in str(error.value)


def test_malformed_model_output_never_reaches_render(tmp_path):
    interpreter=OpenAIInterpreter(base_url='https://example.test/v1',api_key='secret',model='model',
          client=model_client({'choices':[{'message':{'content':'{"status":"apply","operations":[]}'}}]}))
    graph=create_graph(interpreter=interpreter, analyzer=lambda *a,**k: pytest.fail('analyze executed'),
                       renderer=lambda *a: pytest.fail('render executed'))
    initial=state(tmp_path)
    initial.update(events=[e.model_dump() for e in EVENTS],text='修改',displayed_event_ids=['e1','e2','e3'])
    with pytest.raises(RuntimeError,match='无效指令'):
        graph.invoke(initial)
    assert initial['plan']==EditPlan().model_dump()


def test_missing_model_configuration_does_not_fallback():
    interpreter=OpenAIInterpreter(base_url='',api_key='',model='')
    with pytest.raises(RuntimeError,match='LLM_BASE_URL'):
        interpreter('前面八秒',events=EVENTS,plan=EditPlan(),displayed_event_ids=['e1'])


def test_initial_upload_calls_no_model_and_uses_real_stages(tmp_path):
    stages=[]
    graph=create_graph(interpreter=lambda *a,**k: pytest.fail('model called on upload'),
        analyzer=lambda *a,**k: Analysis(events=EVENTS,duration_seconds=50),
        renderer=lambda video,events,plan,output: RenderResult(path=str(output),duration_seconds=10,event_ids=['e1','e2','e3']))
    initial=state(tmp_path)
    initial['on_stage']=stages.append
    result=graph.invoke(initial)
    assert stages[0] == 'analyzing'
    assert stages[1]['status'] == 'rendering'
    assert result['plan']==EditPlan().model_dump()


def test_invalid_base_url_has_clear_configuration_error():
    interpreter=OpenAIInterpreter(base_url='https://[bad',api_key='secret',model='model')
    with pytest.raises(RuntimeError,match='模型服务未配置'):
        interpreter('前面八秒',events=EVENTS,plan=EditPlan(),displayed_event_ids=['e1'])


def test_summary_arrives_before_renderer(tmp_path):
    stages = []
    def render(video, events, plan, output):
        summary = stages[-1]
        assert summary['status'] == 'rendering'
        assert summary['excluded_event_ids'] == ['e2']
        assert summary['excluded_ordinals'] == [2]
        assert summary['before_seconds'] == 8 and summary['after_seconds'] == 2
        assert all(s in summary['message'] for s in ('第 2 球', 'e2', '前 8 秒', '后 2 秒'))
        return RenderResult(path=str(output), duration_seconds=10, event_ids=['e1','e3'])
    graph = create_graph(interpreter=lambda *a, **k: Interpretation(status='apply', operations=[
        Operation(op='exclude',ordinal=2), Operation(op='add_before',value=3)]), renderer=render)
    initial = state(tmp_path)
    initial.update(events=[e.model_dump() for e in EVENTS], displayed_event_ids=['e1','e2','e3'], text='修改', on_stage=stages.append)
    graph.invoke(initial)
