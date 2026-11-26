"""OpenAI-compatible chat completions via bounded server-side HTTP."""
import json
import os
from typing import Literal
from urllib.parse import urlsplit
import httpx
from pydantic import Field, model_validator
from contracts.models import Contract, EditPlan, Event, Operation
from agent.prompts import SYSTEM_PROMPT


class Interpretation(Contract):
    status: Literal['apply', 'clarify', 'unsupported']
    operations: list[Operation] = Field(default_factory=list)
    message: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def valid_action(self):
        if self.status == 'apply' and not self.operations:
            raise ValueError('apply requires operations')
        if self.status != 'apply' and (self.operations or not self.message.strip()):
            raise ValueError('non-apply requires a message and no operations')
        return self


class OpenAIInterpreter:
    def __init__(self, *, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None, client: httpx.Client | None = None):
        self.base_url = (base_url if base_url is not None else os.getenv('LLM_BASE_URL', '')).rstrip('/')
        self.api_key = api_key if api_key is not None else os.getenv('LLM_API_KEY', '')
        self.model = model if model is not None else os.getenv('LLM_MODEL', '')
        self.client = client

    def __call__(self, text: str, *, events: list[Event], plan: EditPlan,
                 displayed_event_ids: list[str]) -> Interpretation:
        try:
            parsed = urlsplit(self.base_url)
        except ValueError:
            raise RuntimeError('模型服务未配置，请检查 LLM_BASE_URL') from None
        if not self.api_key or not self.model or parsed.scheme not in ('http', 'https') or not parsed.netloc:
            raise RuntimeError('模型服务未配置，请设置 LLM_BASE_URL、LLM_API_KEY、LLM_MODEL')
        payload = {'model': self.model, 'temperature': 0,
                   'response_format': {'type': 'json_object'},
                   'messages': [{'role': 'system', 'content': SYSTEM_PROMPT},
                                {'role': 'user', 'content': json.dumps({
                                    'request': text, 'plan': plan.model_dump(),
                                    'events': [{'id': e.id, 'time': e.time, 'label': e.label} for e in events],
                                    'displayed_event_ids': displayed_event_ids}, ensure_ascii=False)}]}
        def request(client):
            response = client.post(self.base_url + '/chat/completions', json=payload,
                                   headers={'Authorization': 'Bearer ' + self.api_key},
                                   timeout=httpx.Timeout(45, connect=10))
            response.raise_for_status()
            content = response.json()['choices'][0]['message']['content']
            return Interpretation.model_validate_json(content)
        try:
            if self.client is not None:
                return request(self.client)
            with httpx.Client() as client:
                return request(client)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            raise RuntimeError('模型服务调用失败或返回无效指令，请稍后重试；当前集锦未修改') from None
