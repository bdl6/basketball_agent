"""A genuine LangGraph with explicit interpret, clarify, analyze, plan, render nodes."""
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4
from langgraph.graph import END, START, StateGraph
from contracts.models import EditPlan, Event
from agent.interpret import Interpretation, OpenAIInterpreter
from agent.state import AgentState
from agent.tools import apply_operations, list_events


def create_graph(*, interpreter=None, analyzer=None, renderer=None):
    """Inject synchronous boundaries for offline testing; production uses real adapters."""
    interpreter = interpreter if interpreter is not None else OpenAIInterpreter()
    if analyzer is None:
        from video_engine.analyzer import analyze_video
        analyzer = analyze_video
    if renderer is None:
        from video_engine.highlights import render_highlights
        renderer = render_highlights

    def interpret(state):
        # Initial upload uses defaults without a model call.
        if state.get('text') is None:
            return {'interpretation': None, 'result_path': None, 'message': '', 'blocked': False}
        text = state['text']
        pending = state.get('pending_context')
        if pending:
            text = f"原始需求：{pending.get('original_text', '')}\n澄清回复：{text}"
        decision = Interpretation.model_validate(interpreter(text,
            events=[Event.model_validate(e) for e in state.get('events') or []],
            plan=EditPlan.model_validate(state['plan']), displayed_event_ids=state['displayed_event_ids']))
        return {'interpretation': decision, 'result_path': None, 'message': '', 'blocked': False}

    def route_interpret(state):
        decision = state.get('interpretation')
        if decision and decision.status != 'apply':
            return 'clarify'
        return 'analyze' if state.get('events') is None else 'plan'

    def clarify(state):
        decision = state['interpretation']
        pending = None
        if decision.status == 'clarify':
            previous = state.get('pending_context')
            original = state['text']
            if previous:
                original = f"{previous.get('original_text', '')}\n澄清回复：{state['text']}"
            pending = {'original_text': original}
        return {'message': decision.message, 'pending_context': pending, 'result_path': None}

    def analyze(state):
        state['on_stage']('analyzing')
        analysis = analyzer(state['video_path'], state['work_dir'], model_path=state['model_path'])
        return {'events': [event.model_dump() for event in analysis.events]}

    def plan(state):
        events = [Event.model_validate(e) for e in state['events']]
        current = EditPlan.model_validate(state['plan'])
        decision = state.get('interpretation')
        try:
            updated = apply_operations(events, current, state['displayed_event_ids'], decision.operations) if decision else current
            if not list_events(events, updated):
                raise ValueError('没有可剪辑的可靠进球，未生成集锦')
            if updated.before_seconds + updated.after_seconds == 0:
                raise ValueError('前后保留时长不能同时为零')
        except ValueError as error:
            return {'blocked': True, 'message': str(error), 'pending_context': None, 'result_path': None}
        return {'plan': updated.model_dump(), 'pending_context': None}

    def render(state):
        plan = EditPlan.model_validate(state['plan'])
        events = [Event.model_validate(e) for e in state['events']]
        displayed = state['displayed_event_ids']
        excluded = plan.excluded_event_ids
        ordinals = [i for i, eid in enumerate(displayed, 1) if eid in excluded]
        details = '、'.join(f'第 {i} 球（{displayed[i - 1]}）' for i in ordinals)
        prior = [eid for eid in excluded if eid not in displayed]
        message = f'已理解要求：每球前 {plan.before_seconds:g} 秒、后 {plan.after_seconds:g} 秒。'
        if details:
            message += f'将排除{details}。'
        if prior:
            message += f'继续排除进球 ID：{"、".join(prior)}。'
        message += '正在生成新集锦。'
        state['on_stage']({'status': 'rendering', 'message': message,
            'excluded_event_ids': excluded, 'excluded_ordinals': ordinals,
            'before_seconds': plan.before_seconds, 'after_seconds': plan.after_seconds})
        output = Path(state['work_dir']) / f'highlights-{uuid4().hex}.mp4'
        result = renderer(state['video_path'], events, plan, output)
        message = f'集锦已生成：共 {len(result.event_ids)} 个可靠进球，每球前 {plan.before_seconds:g} 秒、后 {plan.after_seconds:g} 秒。'
        if state.get('interpretation'):
            removed = sum(op.op == 'exclude' for op in state['interpretation'].operations)
            if removed:
                message = '已按当前展示编号排除指定进球。' + message
        return {'result_path': result.path, 'displayed_event_ids': result.event_ids, 'message': message}

    graph = StateGraph(AgentState)
    for name, node in [('interpret', interpret), ('clarify', clarify), ('analyze', analyze), ('plan', plan), ('render', render)]:
        graph.add_node(name, node)
    graph.add_edge(START, 'interpret')
    graph.add_conditional_edges('interpret', route_interpret, {'clarify': 'clarify', 'analyze': 'analyze', 'plan': 'plan'})
    graph.add_edge('clarify', END)
    graph.add_edge('analyze', 'plan')
    graph.add_conditional_edges('plan', lambda s: 'end' if s.get('blocked') else 'render', {'end': END, 'render': 'render'})
    graph.add_edge('render', END)
    return graph.compile()


def execute_job(video_path: Path, work_dir: Path, *, model_path: Path, events: list[dict] | None,
                plan: dict, displayed_event_ids: list[str], text: str | None,
                pending_context: dict | None = None, on_stage: Callable[[str | dict], None]) -> dict:
    result = create_graph().invoke({'video_path': Path(video_path), 'work_dir': Path(work_dir),
        'model_path': Path(model_path), 'events': events, 'plan': plan,
        'displayed_event_ids': displayed_event_ids, 'text': text,
        'pending_context': pending_context, 'on_stage': on_stage})
    return {key: result.get(key) for key in ('events', 'plan', 'displayed_event_ids', 'result_path', 'message', 'pending_context')}
