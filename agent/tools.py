from contracts.models import highlight_eligible
"""Pure, atomic plan tools; no arbitrary commands are accepted."""
from collections.abc import Sequence
from contracts.models import EditPlan, Event, Operation


def list_events(events: Sequence[Event], plan: EditPlan) -> list[Event]:
    if len({event.id for event in events}) != len(events):
        raise ValueError('事件 ID 重复，无法修改')
    return sorted((event for event in events if highlight_eligible(event)
                   and event.id not in plan.excluded_event_ids), key=lambda event: (event.time, event.id))


def apply_operations(events: Sequence[Event], plan: EditPlan, displayed_event_ids: list[str],
                     operations: Sequence[Operation]) -> EditPlan:
    """Resolve ordinals using one snapshot and validate before returning a new plan."""
    current = [event.id for event in list_events(events, plan)]
    if not current:
        raise ValueError('没有可剪辑的可靠进球')
    if current != displayed_event_ids:
        raise ValueError('当前进球列表与展示列表不一致，请刷新后重试')
    if not operations:
        raise ValueError('没有明确的剪辑操作，请说明需要修改的内容')
    data = plan.model_dump()
    excluded = list(dict.fromkeys(data['excluded_event_ids']))
    for raw in operations:
        operation = Operation.model_validate(raw)
        if operation.op == 'exclude':
            if operation.ordinal > len(displayed_event_ids):
                raise ValueError('进球编号超出当前展示列表，请使用当前列表中的编号')
            event_id = displayed_event_ids[operation.ordinal - 1]
            if event_id not in excluded:
                excluded.append(event_id)
        else:
            field = 'before_seconds' if operation.op.endswith('before') else 'after_seconds'
            data[field] = operation.value if operation.op.startswith('set_') else data[field] + operation.value
    data['excluded_event_ids'] = excluded
    try:
        updated = EditPlan.model_validate(data)
    except ValueError:
        raise ValueError('每球前后保留时长必须在 0 到 60 秒之间') from None
    if not list_events(events, updated):
        raise ValueError('修改后没有可剪辑的可靠进球，请至少保留一个进球')
    if updated.before_seconds + updated.after_seconds == 0:
        raise ValueError('前后保留时长不能同时为零')
    return updated
