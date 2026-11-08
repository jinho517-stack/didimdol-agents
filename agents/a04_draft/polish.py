"""A04 ③-2 AI 문장 다듬기: 보고서 작성 스킬(SKILL.md)의 '문장 규칙'을 AI에게 주고 초안 문장을 다듬게 한다.
AI가 고친 줄은 하나씩 검사해서 숫자가 바뀌었거나, 확인 필요 같은 표시가 사라졌거나, 너무 길면 원래 문장을 그대로 쓴다.
그래서 AI를 써도 숫자는 DB 값 그대로다."""
import json
import re
import time

from agents.a04_draft import skill as SK
from common import llm

TARGET = ('b', 's', 'act', 'summary')     # 다듬는 블록: ㅇ 본문, - 세부, ⇒ 조치, ◈ 핵심요약
SKIP_HEADS = ('종합 의견',)               # AI가 이미 쓴 목차는 건드리지 않음
KEEP_MARKS = ('확인 필요', '미확정', '비공식', '공식 확인 전', '직접 입력', 'AI 미사용')
NUM = re.compile(r'\d[\d,]*(?:\.\d+)?')


def _nums(s):
    return sorted(n.replace(',', '').rstrip('.') for n in NUM.findall(s or ''))


def _parts(b):
    """블록 → (핵심어, 문장)"""
    return (b[1] or '', b[2]) if b[0] == 'b' else ('', b[1])


def _rebuild(b, key, text):
    return ('b', key or None, text) if b[0] == 'b' else (b[0], text)


def _why_not(old_key, old, key, text, max_chars):
    """AI가 고친 줄을 쓰면 안 되는 이유(없으면 None)"""
    if not text.strip():
        return '빈 문장'
    if _nums(old_key + ' ' + old) != _nums(key + ' ' + text):
        return '숫자가 달라짐'
    lost = [m for m in KEEP_MARKS if m in old_key + old and m not in key + text]
    if lost:
        return f"'{lost[0]}' 표시가 빠짐"
    if len(text) > max(max_chars, len(old)):
        return f'너무 김({len(text)}자)'
    return None


def run(blocks, cfg=None, path=SK.PATH):
    """반환: (새 블록 목록, 결과) — 결과 = {'skill','changed':[(전, 후)],'kept':[(문장, 이유)],'total','seconds','error'}"""
    sk = SK.load(path)
    rep = {'skill': f"{sk['title']} v{sk['version']}", 'changed': [], 'kept': [], 'total': 0, 'seconds': 0, 'error': None}
    head, items = '', []
    for i, b in enumerate(blocks):
        if b[0] == 'h':
            head = b[1]
        elif b[0] in TARGET and not any(h in head for h in SKIP_HEADS):
            key, text = _parts(b)
            if text and text.strip() and text.strip('() ') != '직접 입력':
                items.append({'id': i, '목차': head.lstrip('□ '), '핵심어': key, '문장': text})
    rep['total'] = len(items)
    if not items:
        return blocks, rep
    title = next((b[1] for b in blocks if b[0] == 'title'), '')
    max_chars = sk['settings']['writing']['max_chars']
    system = ('너는 LH(한국토지주택공사) 광역교통 보고서의 문장을 다듬는 도구다. 아래 스킬의 문장 규칙을 반드시 지킨다.\n\n'
              f"[스킬: {sk['title']} v{sk['version']}]\n{sk['rules']}")
    prompt = (f'[보고서 제목] {title}\n'
              f'[다듬을 문장 목록]\n{json.dumps(items, ensure_ascii=False, indent=0)}\n\n'
              f'각 항목의 "문장"을 문장 규칙대로 다듬어라. 한 문장은 {max_chars}자 이내. '
              '"핵심어"(사업명 등)는 참고만 하고 바꾸지 않는다. 고칠 필요가 없으면 그대로 돌려준다. '
              'id는 바꾸지 말고 모든 항목을 돌려준다.\n'
              '출력 형식: {"lines": [{"id": 0, "문장": "..."}]}')
    t0 = time.time()
    try:
        data = llm.ask_json(prompt, system=system, cfg=cfg)
    except Exception as e:  # AI가 안 되면 원래 초안 그대로
        rep['error'], rep['seconds'] = str(e), round(time.time() - t0, 1)
        return blocks, rep
    rep['seconds'] = round(time.time() - t0, 1)
    got = {int(x['id']): x for x in (data.get('lines') or []) if isinstance(x, dict) and str(x.get('id', '')).isdigit()}
    out = list(blocks)
    for it in items:
        i = it['id']
        x = got.get(i)
        if not x:
            continue
        old_key, old = it['핵심어'], it['문장']
        key = old_key  # 핵심어(사업명 등)는 그대로 둔다
        text = str(x.get('문장') or '').strip()
        if text == old:
            continue
        why = _why_not(old_key, old, key, text, max_chars)
        if why:
            rep['kept'].append((old, why))
            continue
        out[i] = _rebuild(blocks[i], key, text)
        rep['changed'].append(((f'({old_key}) ' if old_key else '') + old, (f'({key}) ' if key else '') + text))
    return out, rep
