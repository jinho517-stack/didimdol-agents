"""LLM 호출은 전부 이 파일 한 곳에서 한다 (모델 교체 지점).
config.yaml의 llm.provider(anthropic | openai_compatible), model, base_url, api_key_env만 읽는다.
키 값은 파일에 쓰지 않고 환경변수로만 받는다. 표준 라이브러리 HTTP만 사용(별도 SDK 불필요)."""
import json
import os
import time
import re
import urllib.error
import urllib.request
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[1] / 'config.yaml'  # 프로젝트 맨 위의 config.yaml
JSON_RULE = '반드시 JSON만 출력한다. 설명 문장, 코드블록 표시(```)를 붙이지 않는다.'


def load_config(path=CONFIG_PATH):
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def _llm_cfg(cfg=None):
    return (cfg or load_config()).get('llm', {})


def api_key(cfg=None):
    env = _llm_cfg(cfg).get('api_key_env') or ''
    return os.environ.get(env, '') if env else ''


def available(cfg=None):
    """실제 추출을 돌릴 수 있는지. 키가 필요 없는 로컬 OpenAI 호환 서버는 api_key_env를 비워 둔다."""
    c = _llm_cfg(cfg)
    if not c.get('model'):
        return False
    if c.get('provider') == 'openai_compatible' and not c.get('api_key_env'):
        return True
    return bool(api_key(cfg))


RETRY_CODES = (429, 500, 502, 503, 529)  # 사용량 초과(429)·일시 장애는 잠시 쉬었다 다시 보낸다
RETRIES = 2  # 5초·10초 쉬고 다시 → 그래도 안 되면 오류 문구를 바로 보여 준다


def _post(url, headers, body, timeout=180):
    data = json.dumps(body).encode('utf-8')
    for attempt in range(RETRIES + 1):
        req = urllib.request.Request(url, data=data, headers={'content-type': 'application/json', **headers}, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            msg = e.read().decode('utf-8', 'replace')[:500]
            if e.code in RETRY_CODES and attempt < RETRIES:
                try:
                    wait = float(e.headers.get('retry-after') or 0)
                except ValueError:
                    wait = 0
                time.sleep(min(max(wait, 5 * 2 ** attempt), 60))  # 5·10·20·40초(최대 60초)
                continue
            raise RuntimeError(f'LLM 호출 실패 (HTTP {e.code}): {msg}') from e


def ask(prompt, system=None, json_mode=False, cfg=None) -> str:
    c = _llm_cfg(cfg)
    provider = c.get('provider', 'anthropic')
    if json_mode:
        system = f'{system}\n{JSON_RULE}' if system else JSON_RULE
    if provider == 'anthropic':
        body = {'model': c['model'], 'max_tokens': c.get('max_tokens', 4096),
                'messages': [{'role': 'user', 'content': prompt}]}
        if system:
            body['system'] = system
        if c.get('effort'):  # 생각(추론) 정도: low·medium·high·xhigh·max
            body['output_config'] = {'effort': c['effort']}
        base = (c.get('base_url') or 'https://api.anthropic.com').rstrip('/')
        headers = {'x-api-key': api_key(cfg), 'anthropic-version': '2023-06-01'}
        ws = c.get('workspace_id') or os.environ.get('ANTHROPIC_WORKSPACE_ID', '')
        if ws:  # 작업공간(workspace)에 묶이지 않은 조직 키는 어느 작업공간을 쓸지 함께 보내야 한다
            headers['anthropic-workspace-id'] = ws
        data = _post(f'{base}/v1/messages', headers, body)
        return ''.join(b.get('text', '') for b in data.get('content', []) if b.get('type') == 'text')
    if provider == 'openai_compatible':
        msgs = ([{'role': 'system', 'content': system}] if system else []) + [{'role': 'user', 'content': prompt}]
        body = {'model': c['model'], 'messages': msgs, 'max_tokens': c.get('max_tokens', 4096)}
        if c.get('reasoning_effort'):  # 생각(추론) 정도: none·low·medium·high (지원하는 서버만)
            body['reasoning_effort'] = c['reasoning_effort']
        if 'temperature' in c:
            body['temperature'] = c['temperature']
        if json_mode and c.get('json_response_format'):
            body['response_format'] = {'type': 'json_object'}
        key = api_key(cfg)
        data = _post(f"{c['base_url'].rstrip('/')}/chat/completions", {'authorization': f'Bearer {key}'} if key else {}, body)
        return data['choices'][0]['message']['content'] or ''
    raise ValueError(f'지원하지 않는 provider: {provider} (anthropic 또는 openai_compatible)')


def parse_json(text):
    t = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip())
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        starts = [i for i in (t.find('{'), t.find('[')) if i >= 0]
        if not starts:
            raise
        s = min(starts)
        e = max(t.rfind('}'), t.rfind(']'))
        return json.loads(t[s:e + 1])


def ask_json(prompt, system=None, cfg=None):
    """JSON 출력을 요구하고, 파싱에 실패하면 한 번 재시도한다."""
    last = None
    for attempt in range(2):
        p = prompt if attempt == 0 else prompt + '\n\n[재요청] 앞선 응답이 JSON 형식이 아니었다. 형식에 맞는 JSON만 다시 출력하라.'
        text = ask(p, system=system, json_mode=True, cfg=cfg)
        try:
            return parse_json(text)
        except (json.JSONDecodeError, ValueError) as e:
            last = e
    raise RuntimeError(f'LLM 응답을 JSON으로 읽지 못함(2회 시도): {last}')
